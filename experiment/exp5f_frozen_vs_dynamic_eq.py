"""
EXP 5F — Frozen EQ vs Dynamic Research EQ Head-to-Head
=======================================================

AMAÇ: Aynı motorun tek değişkenli EQ karşılaştırması.

Variant A (Frozen EQ): Mevcut KNOWN-GOOD run_test_a() aynen kullanılır.
  eq = (sweep_price + range_opposite) / 2

Variant B (Dynamic Research EQ): Aynı engine, aynı sweep, aynı FVG, aynı execution.
  Ama EQ reference: research_eq = (latest_confirmed_swing_high + swing_low) / 2

Tek değişken: EQ definition / EQ selection.

DISIPLIN:
- Yeni backtest motoru YAZILMAZ.
- Frozen benchmark DEĞİŞTİRİLMEZ.
- Production/frozen dosyalarına DOKUNULMAZ.
- FVG #1/#2 kuralı EKLENMEZ.
- Freshness DEĞİŞTİRİLMEZ.
- OB/Breaker EKLENMEZ.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

_NEXUS_SNIPER_SRC = str(Path("C:/Users/Administrator/Desktop/nexus-mcp/sniper/src"))
if _NEXUS_SNIPER_SRC not in sys.path:
    sys.path.insert(0, _NEXUS_SNIPER_SRC)

from bisect import bisect_right  # noqa: E402

from fvg import detect_fvgs as _nexus_detect_fvgs  # noqa: E402
from pivot import find_swing_highs, find_swing_lows  # noqa: E402

from experiment.config import (  # noqa: E402
    ATR_PERIOD,
    FVG_BUFFER_MIN_FACTOR,
    FVG_BUFFER_MULT,
    FVG_MIN_SIZE_ATR_MULT,
    FVG_WICK_RATIO_MAX,
    MIN_RISK_DIST_ATR_MULT,
    SESSION_END_HOUR,
    SESSION_START_HOUR,
    SL_ATR_MULT,
    TP_RR,
)
from experiment.gemini_benchmark import _is_fresh_fvg, _to_nexus_bar, compute_atr  # noqa: E402
from experiment.main_research_c_v1_0 import run_test_a  # noqa: E402
from experiment.trailing_adapter import _norm_side, apply_trailing, check_exit  # noqa: E402
from src.strategy.models import Bar, Direction, SweepEvent  # noqa: E402
from src.strategy.session import SessionManager  # noqa: E402

ICMARKET_FEATHER = str(_PROJECT_ROOT / "data" / "icmarket_feather")
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "GBPJPY"]
WINDOW_DAYS = 180


# ── Research EQ helpers (from EXP5B) ────────────────────────────────────────


def _build_swing_timeline(
    bars_15m: List[Bar],
    left: int = 3,
    right: int = 3,
) -> Tuple[List[Tuple[int, int, float]], List[int], List[Tuple[int, int, float]], List[int]]:
    """Precompute ALL confirmed swing events ONCE per symbol. O(n).

    Returns (high_events, high_keys, low_events, low_keys).
    Events sorted by confirm_index ascending.
    Keys are pre-extracted bisect arrays for O(log n) lookup.
    """
    nexus_bars = [_to_nexus_bar(b) for b in bars_15m]
    highs = [
        (sp.bar_index + right, sp.bar_index, sp.price)
        for sp in find_swing_highs(nexus_bars, left=left, right=right)
    ]
    lows = [
        (sp.bar_index + right, sp.bar_index, sp.price)
        for sp in find_swing_lows(nexus_bars, left=left, right=right)
    ]
    highs.sort(key=lambda e: e[0])
    lows.sort(key=lambda e: e[0])
    high_keys = [e[0] for e in highs]
    low_keys = [e[0] for e in lows]
    return highs, high_keys, lows, low_keys


def _latest_swing_from_timeline(
    events: List[Tuple[int, int, float]],
    keys: List[int],
    up_to_index: int,
) -> Optional[Tuple[int, float]]:
    """Latest swing CONFIRMED at or before up_to_index. O(log n) bisect."""
    idx = bisect_right(keys, up_to_index) - 1
    if idx < 0:
        return None
    _, pivot_index, price = events[idx]
    return (pivot_index, price)


def _compute_research_eq(
    swing_high: Optional[Tuple[int, float]],
    swing_low: Optional[Tuple[int, float]],
) -> Optional[float]:
    if swing_high is None or swing_low is None:
        return None
    return (swing_high[1] + swing_low[1]) / 2.0


# ── Variant B: Dynamic Research EQ engine ──────────────────────────────────


def run_test_a_dynamic_eq(
    symbol: str,
    bars_15m: List[Bar],
) -> List[Dict[str, Any]]:
    """COPY of run_test_a with ONLY the EQ filter changed to dynamic research EQ.

    Everything else is identical to the frozen KNOWN-GOOD run_test_a.
    Uses precomputed swing timeline for O(1) lookup per sweep.
    """
    if len(bars_15m) < 100:
        return []

    warmup = min(100, len(bars_15m) - 10)
    atr_val = compute_atr(bars_15m[:warmup], period=ATR_PERIOD)
    if atr_val <= 0:
        return []

    # ── Precompute swing timeline once (O(n)) ──
    swing_highs, high_keys, swing_lows, low_keys = _build_swing_timeline(bars_15m, left=3, right=3)

    session = SessionManager(
        symbol=symbol,
        start_hour=SESSION_START_HOUR,
        end_hour=SESSION_END_HOUR,
        atr=atr_val,
        sweep_atr_tolerance_mult=0.5,
        sweep_default_tolerance=10.0,
    )

    sweep_detected = False
    last_sweep: Optional[SweepEvent] = None
    active_trade: Optional[dict] = None
    trades: List[Dict[str, Any]] = []
    trade_counter = 0

    # Dynamic EQ state
    current_research_eq: Optional[float] = None

    # Pre-build full nexus_bars list once — O(n), not O(n²)
    nexus_bars_full = [_to_nexus_bar(b) for b in bars_15m]

    start_idx = warmup + 1
    for i in range(start_idx, len(bars_15m)):
        bar = bars_15m[i]

        if i > start_idx:
            prev_close = bars_15m[i - 1].close
            tr = max(
                bar.high - bar.low,
                abs(bar.high - prev_close),
                abs(bar.low - prev_close),
            )
            atr_val = (atr_val * (ATR_PERIOD - 1) + tr) / ATR_PERIOD

        min_fvg_size = max(atr_val * FVG_MIN_SIZE_ATR_MULT, 1e-8)

        if active_trade is not None:
            apply_trailing(bars_15m[max(0, i - 500) : i + 1], [active_trade], atr_val, symbol)
            exit_info = check_exit(bar, active_trade)
            if exit_info is not None:
                exit_price = exit_info["exit_price"]
                result = exit_info["result"]
                if _norm_side(active_trade["side"]) == "long":
                    pnl_r = (exit_price - active_trade["entry_price"]) / abs(
                        active_trade["entry_price"] - active_trade["initial_sl"]
                    )
                else:
                    pnl_r = (active_trade["entry_price"] - exit_price) / abs(
                        active_trade["sl"] - active_trade["entry_price"]
                    )
                if result == "LOSS":
                    pnl_r = -1.0

                if _norm_side(active_trade["side"]) == "long":
                    mfe = (
                        active_trade.get("max_price", active_trade["entry_price"])
                        - active_trade["entry_price"]
                    ) / abs(active_trade["entry_price"] - active_trade["initial_sl"])
                    mae = (
                        active_trade["entry_price"]
                        - active_trade.get("min_price", active_trade["entry_price"])
                    ) / abs(active_trade["entry_price"] - active_trade["initial_sl"])
                else:
                    mfe = (
                        active_trade["entry_price"]
                        - active_trade.get("min_price", active_trade["entry_price"])
                    ) / abs(active_trade["entry_price"] - active_trade["initial_sl"])
                    mae = (
                        active_trade.get("max_price", active_trade["entry_price"])
                        - active_trade["entry_price"]
                    ) / abs(active_trade["sl"] - active_trade["entry_price"])

                trades.append(
                    {
                        "trade_id": active_trade["trade_id"],
                        "symbol": symbol,
                        "direction": active_trade["direction"],
                        "entry_price": active_trade["entry_price"],
                        "sl": active_trade["initial_sl"],
                        "tp": active_trade["initial_tp"],
                        "entry_bar_index": active_trade["entry_bar"],
                        "sweep_bar_index": active_trade["sweep_bar_index"],
                        "zone_index": active_trade.get("zone_index", 0),
                        "zone_top": active_trade.get("zone_top", 0),
                        "zone_bottom": active_trade.get("zone_bottom", 0),
                        "zone_size": active_trade.get("zone_size", 0),
                        "research_eq": active_trade.get("research_eq"),
                        "exit_price": exit_price,
                        "exit_bar_index": i,
                        "result": result,
                        "pnl_r": pnl_r,
                        "max_favorable": mfe,
                        "max_adverse": mae,
                        "hold_bars": i - active_trade["entry_bar"],
                    }
                )
                active_trade = None
                continue

            active_trade["max_price"] = max(active_trade.get("max_price", bar.high), bar.high)
            active_trade["min_price"] = min(active_trade.get("min_price", bar.low), bar.low)
            continue

        sweep = session.update(bar)
        if sweep is not None:
            sweep_detected = True
            last_sweep = sweep
            # ── DYNAMIC EQ: O(log n) lookup from precomputed timeline ──
            sh = _latest_swing_from_timeline(swing_highs, high_keys, i)
            sl = _latest_swing_from_timeline(swing_lows, low_keys, i)
            current_research_eq = _compute_research_eq(sh, sl)

        if not sweep_detected or last_sweep is None:
            continue

        sweep_direction = "bullish" if last_sweep.direction == Direction.BULLISH else "bearish"
        lb = min(100, i + 1)
        nexus_bars = nexus_bars_full[i + 1 - lb : i + 1]

        fvgs = _nexus_detect_fvgs(
            nexus_bars,
            lookback=min(100, len(nexus_bars)),
            timeframe="15m",
            min_fvg_size=min_fvg_size,
            max_wick_ratio=FVG_WICK_RATIO_MAX,
        )

        for fvg in fvgs:
            if fvg.real_index <= last_sweep.bar_index:
                continue
            if fvg.direction != sweep_direction:
                continue
            if fvg.invalidated:
                continue
            if not _is_fresh_fvg(fvg, bars_15m, i):
                continue

            # ============================================================
            # DYNAMIC RESEARCH EQ FILTER (only change from frozen)
            # ============================================================
            if current_research_eq is None:
                continue  # No valid research EQ → skip

            # Same EQ check logic as frozen, but with research_eq
            if last_sweep.direction == Direction.BULLISH:
                if fvg.top > current_research_eq:
                    continue
            else:
                if fvg.bottom < current_research_eq:
                    continue

            # Entry check (identical to frozen)
            if fvg.direction == "bullish":
                if not (bar.low <= fvg.top and bar.low >= fvg.bottom - atr_val * 0.1):
                    continue
            else:
                if not (bar.high >= fvg.bottom and bar.high <= fvg.top + atr_val * 0.1):
                    continue

            # Next-bar-open execution (identical to frozen)
            if i + 1 >= len(bars_15m):
                continue
            entry_price = bars_15m[i + 1].open

            fh = fvg.top - fvg.bottom
            rp2 = atr_val * SL_ATR_MULT
            if fvg.direction == "bullish":
                ab = (
                    max(
                        fh * FVG_BUFFER_MIN_FACTOR,
                        max(rp2 * 0.1, min(fh * 0.25, rp2 * FVG_BUFFER_MULT)),
                    )
                    if fh > 0
                    else rp2 * 2
                )
                sl_price = fvg.bottom - ab if fh > 0 else entry_price - rp2 * 2
            else:
                ab = (
                    max(
                        fh * FVG_BUFFER_MIN_FACTOR,
                        max(rp2 * 0.1, min(fh * 0.25, rp2 * FVG_BUFFER_MULT)),
                    )
                    if fh > 0
                    else rp2 * 2
                )
                sl_price = fvg.top + ab if fh > 0 else entry_price + rp2 * 2

            rd = abs(entry_price - sl_price)
            if rd <= 0:
                sl_price = (
                    entry_price - rp2 * 2 if fvg.direction == "bullish" else entry_price + rp2 * 2
                )
                rd = abs(entry_price - sl_price)
            tp = (
                entry_price + rd * TP_RR if fvg.direction == "bullish" else entry_price - rd * TP_RR
            )

            if rd < atr_val * MIN_RISK_DIST_ATR_MULT:
                continue

            trade_counter += 1
            active_trade = {
                "trade_id": trade_counter,
                "side": _norm_side(fvg.direction),
                "direction": fvg.direction,
                "entry_price": entry_price,
                "sl": sl_price,
                "tp": tp,
                "initial_sl": sl_price,
                "initial_tp": tp,
                "entry_bar": i + 1,
                "sweep_bar_index": last_sweep.bar_index,
                "zone_index": fvg.real_index,
                "zone_creation_bar": fvg.real_index,
                "zone_top": fvg.top,
                "zone_bottom": fvg.bottom,
                "zone_size": fvg.size,
                "zone_size_atr": fvg.size / atr_val if atr_val > 0 else 0,
                "research_eq": current_research_eq,
                "trailing_count": 0,
                "max_price": entry_price,
                "min_price": entry_price,
                "closed": False,
            }
            sweep_detected = False
            last_sweep = None
            break

    # Close open trade
    if active_trade is not None and not active_trade.get("closed"):
        last_bar = bars_15m[-1]
        if _norm_side(active_trade["side"]) == "long":
            exit_price = last_bar.close
            pnl_r = (exit_price - active_trade["entry_price"]) / abs(
                active_trade["entry_price"] - active_trade["initial_sl"]
            )
        else:
            exit_price = last_bar.close
            pnl_r = (active_trade["entry_price"] - exit_price) / abs(
                active_trade["sl"] - active_trade["entry_price"]
            )

        trades.append(
            {
                "trade_id": active_trade["trade_id"],
                "symbol": symbol,
                "direction": active_trade["direction"],
                "entry_price": active_trade["entry_price"],
                "sl": active_trade["initial_sl"],
                "tp": active_trade["initial_tp"],
                "entry_bar_index": active_trade["entry_bar"],
                "sweep_bar_index": active_trade["sweep_bar_index"],
                "zone_index": active_trade.get("zone_index", 0),
                "zone_top": active_trade.get("zone_top", 0),
                "zone_bottom": active_trade.get("zone_bottom", 0),
                "zone_size": active_trade.get("zone_size", 0),
                "research_eq": active_trade.get("research_eq"),
                "exit_price": exit_price,
                "exit_bar_index": len(bars_15m) - 1,
                "result": "OPEN",
                "pnl_r": pnl_r,
                "max_favorable": 0,
                "max_adverse": 0,
                "hold_bars": len(bars_15m) - 1 - active_trade["entry_bar"],
            }
        )

    return trades


# ── Per-symbol comparison ──────────────────────────────────────────────────


def _analyze_symbol(symbol: str) -> Dict[str, Any]:
    """Run both variants on the same data and compare."""
    # Load 15m Feather directly — no 1m resampling
    feather_path = Path(ICMARKET_FEATHER) / f"{symbol}_15m.feather"
    df = pd.read_feather(feather_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    max_ts = df["timestamp"].max()
    cutoff = max_ts - pd.Timedelta(days=WINDOW_DAYS)
    df = df[df["timestamp"] >= cutoff].reset_index(drop=True)
    bars_15m = [
        Bar(
            index=i,
            timestamp=row["timestamp"],
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        )
        for i, row in df.iterrows()
    ]
    if len(bars_15m) < 100:
        return {
            "symbol": symbol,
            "frozen": [],
            "dynamic": [],
            "error": "insufficient data",
        }

    # Variant A: Frozen EQ (KNOWN-GOOD)
    frozen_trades = run_test_a(symbol, bars_15m)
    frozen_dicts = []
    for t in frozen_trades:
        frozen_dicts.append(
            {
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "direction": t.direction,
                "entry_price": t.entry_price,
                "sl": t.sl,
                "tp": t.tp,
                "entry_bar_index": t.entry_bar_index,
                "sweep_bar_index": t.sweep_bar_index,
                "zone_index": t.zone_index,
                "zone_top": t.zone_top,
                "zone_bottom": t.zone_bottom,
                "zone_size": t.zone_size,
                "exit_price": t.exit_price,
                "exit_bar_index": t.exit_bar_index,
                "result": t.result,
                "pnl_r": t.pnl_r,
                "max_favorable": t.max_favorable,
                "max_adverse": t.max_adverse,
                "hold_bars": t.hold_bars,
            }
        )

    # Variant B: Dynamic Research EQ
    dynamic_trades = run_test_a_dynamic_eq(symbol, bars_15m)

    return {
        "symbol": symbol,
        "frozen": frozen_dicts,
        "dynamic": dynamic_trades,
        "n_bars_15m": len(bars_15m),
    }


def _worker(symbol: str) -> Dict[str, Any]:
    try:
        return _analyze_symbol(symbol)
    except Exception as e:
        return {"symbol": symbol, "frozen": [], "dynamic": [], "error": str(e)}


# ── Stats helpers ──────────────────────────────────────────────────────────


def _outcome_stats(trades: List[Dict], label: str) -> Dict[str, Any]:
    completed = [t for t in trades if t["result"] in ("TP", "PROFIT_TRAIL", "LOSS")]
    wins = [t for t in completed if t["result"] in ("TP", "PROFIT_TRAIL")]
    n = len(trades)
    wr = len(wins) / len(completed) * 100 if completed else 0.0
    rs = [t["pnl_r"] for t in completed]
    total_r = sum(rs)
    avg_r = total_r / len(completed) if completed else 0.0

    # MaxDD in R — equity starts at STARTING_BALANCE_R
    STARTING_BALANCE_R = 100.0
    cum = STARTING_BALANCE_R
    peak = STARTING_BALANCE_R
    maxdd_r = 0.0
    for t in sorted(completed, key=lambda x: x.get("exit_bar_index", 0)):
        cum += t["pnl_r"]
        peak = max(peak, cum)
        maxdd_r = max(maxdd_r, peak - cum)

    # MaxDD in % — peak balance'e göre
    cum_pct = STARTING_BALANCE_R
    peak_pct = STARTING_BALANCE_R
    maxdd_pct = 0.0
    for t in sorted(completed, key=lambda x: x.get("exit_bar_index", 0)):
        cum_pct += t["pnl_r"]
        peak_pct = max(peak_pct, cum_pct)
        dd_pct = peak_pct - cum_pct
        if peak_pct > 0:
            maxdd_pct = max(maxdd_pct, dd_pct / peak_pct * 100)

    # Profit factor
    gross_profit = sum(r for r in rs if r > 0)
    gross_loss = abs(sum(r for r in rs if r < 0))
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    return {
        "label": label,
        "N": n,
        "completed": len(completed),
        "wins": len(wins),
        "WR%": round(wr, 1),
        "AvgR": round(avg_r, 3),
        "TotalR": round(total_r, 2),
        "MaxDD_R": round(maxdd_r, 2),
        "MaxDD_%": round(maxdd_pct, 2),
        "PF": round(pf, 2) if pf != float("inf") else "∞",
    }


def _fmt(st: Dict) -> str:
    return (
        f"| {st['label']} | {st['N']} | {st['completed']} | "
        f"{st['WR%']} | {st['AvgR']} | {st['TotalR']} | "
        f"{st['MaxDD_R']} | {st['MaxDD_%']} | {st['PF']} |"
    )


# ── Main ───────────────────────────────────────────────────────────────────


def main():
    t0 = time.time()
    print("=== EXP 5F — Frozen EQ vs Dynamic Research EQ ===")
    print(f"Symbols: {SYMBOLS} | 6 workers | window={WINDOW_DAYS}d")
    print()

    with mp.Pool(processes=6) as pool:
        results = pool.map(_worker, SYMBOLS)

    all_frozen: List[Dict] = []
    all_dynamic: List[Dict] = []
    sym_results = []

    for sym, res in zip(SYMBOLS, results):
        if res.get("error"):
            print(f"  {sym:10s}: ERROR -> {res['error']}")
            continue
        all_frozen.extend(res["frozen"])
        all_dynamic.extend(res["dynamic"])
        sym_results.append(
            {
                "symbol": sym,
                "frozen_n": len(res["frozen"]),
                "dynamic_n": len(res["dynamic"]),
            }
        )
        fs = _outcome_stats(res["frozen"], sym)
        ds = _outcome_stats(res["dynamic"], sym)
        print(
            f"  {sym:10s}: frozen={len(res['frozen']):3d}({fs['MaxDD_%']:.1f}%) | dynamic={len(res['dynamic']):3d}({ds['MaxDD_%']:.1f}%)"
        )

    elapsed = time.time() - t0
    print(
        f"\nTotal: frozen={len(all_frozen)} | dynamic={len(all_dynamic)} | elapsed {elapsed:.1f}s"
    )

    # ── Trade-level attribution ──
    # Match by (symbol, zone_index) — same FVG, different EQ decision
    frozen_keys = {(t["symbol"], t["zone_index"]): t for t in all_frozen}
    dynamic_keys = {(t["symbol"], t["zone_index"]): t for t in all_dynamic}

    only_frozen = [k for k in frozen_keys if k not in dynamic_keys]
    only_dynamic = [k for k in dynamic_keys if k not in frozen_keys]
    both = [k for k in frozen_keys if k in dynamic_keys]
    neither_count = 0  # Would need sweep-level tracking  # noqa: F841

    print("Trade-level attribution:")
    print(f"  Both variants traded:     {len(both)}")
    print(f"  Only Frozen EQ:           {len(only_frozen)}")
    print(f"  Only Dynamic EQ:          {len(only_dynamic)}")
    print()

    # ── Save outputs ──
    out_dir = _PROJECT_ROOT / "results" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)

    comparison = {
        "frozen_trades": all_frozen,
        "dynamic_trades": all_dynamic,
        "attribution": {
            "both": [{"symbol": k[0], "zone_index": k[1]} for k in both],
            "only_frozen": [{"symbol": k[0], "zone_index": k[1]} for k in only_frozen],
            "only_dynamic": [{"symbol": k[0], "zone_index": k[1]} for k in only_dynamic],
        },
        "symbol_results": sym_results,
    }
    comp_path = out_dir / "exp5f_frozen_vs_dynamic.json"
    comp_path.write_text(json.dumps(comparison, indent=2, default=str), encoding="utf-8")

    # ── Report ──
    L: List[str] = []
    L.append("# EXP 5F — Frozen EQ vs Dynamic Research EQ")
    L.append("")
    L.append("## TANIM")
    L.append("")
    L.append("Aynı motorun tek değişkenli EQ karşılaştırması.")
    L.append("")
    L.append("- **Variant A (Frozen EQ)**: `eq = (sweep_price + range_opposite) / 2`")
    L.append("- **Variant B (Dynamic Research EQ)**: `research_eq = (swing_high + swing_low) / 2`")
    L.append("")
    L.append("Tek değişken: EQ definition. Her şey aynı.")
    L.append("")

    # ── Population ──
    L.append("## POPULATION")
    L.append("")
    L.append(f"- Symbols: {SYMBOLS}")
    L.append(f"- Window: {WINDOW_DAYS}d")
    L.append(f"- Frozen EQ trades: **{len(all_frozen)}**")
    L.append(f"- Dynamic EQ trades: **{len(all_dynamic)}**")
    L.append("")

    # ── Table 1: Side-by-side comparison ──
    L.append("## 1. SIDE-BY-SIDE COMPARISON")
    L.append("")
    L.append("| Metric | Frozen EQ | Dynamic EQ | Delta |")
    L.append("|---|---|---|---|")

    fs = _outcome_stats(all_frozen, "Frozen")
    ds = _outcome_stats(all_dynamic, "Dynamic")

    for key, fmt_str in [
        ("N", "{}"),
        ("completed", "{}"),
        ("WR%", "{}%"),
        ("AvgR", "{}"),
        ("TotalR", "{}"),
        ("MaxDD_R", "{}"),
        ("MaxDD_%", "{}%"),
        ("PF", "{}"),
    ]:
        fv = fs[key]
        dv = ds[key]
        if isinstance(fv, (int, float)) and isinstance(dv, (int, float)):
            delta = dv - fv
            sign = "+" if delta > 0 else ""
            L.append(f"| {key} | {fv} | {dv} | {sign}{delta:.2f} |")
        else:
            L.append(f"| {key} | {fv} | {dv} | — |")
    L.append("")

    # ── Table 2: Per-symbol comparison ──
    L.append("## 2. PER-SYMBOL COMPARISON")
    L.append("")
    L.append(
        "| Symbol | Frozen N | Frozen WR% | Frozen AvgR | Dynamic N | Dynamic WR% | Dynamic AvgR | Delta N |"
    )
    L.append("|---|---|---|---|---|---|---|---|")
    for sym, res in zip(SYMBOLS, results):
        if res.get("error"):
            continue
        ft = _outcome_stats(res["frozen"], sym)
        dt = _outcome_stats(res["dynamic"], sym)
        dn = dt["N"] - ft["N"]
        sign = "+" if dn > 0 else ""
        L.append(
            f"| {sym} | {ft['N']} | {ft['WR%']} | {ft['AvgR']} | "
            f"{dt['N']} | {dt['WR%']} | {dt['AvgR']} | {sign}{dn} |"
        )
    L.append("")

    # ── Table 3: Trade-level attribution ──
    L.append("## 3. TRADE-LEVEL ATTRIBUTION")
    L.append("")
    L.append("| Category | N |")
    L.append("|---|---|")
    L.append(f"| Both variants traded | {len(both)} |")
    L.append(f"| Only Frozen EQ | {len(only_frozen)} |")
    L.append(f"| Only Dynamic EQ | {len(only_dynamic)} |")
    L.append("")

    # Common trades outcome comparison
    if both:
        common_frozen = [frozen_keys[k] for k in both]
        common_dynamic = [dynamic_keys[k] for k in both]
        cfs = _outcome_stats(common_frozen, "Common-Frozen")
        cds = _outcome_stats(common_dynamic, "Common-Dynamic")
        L.append("### Common Trades Outcome")
        L.append("")
        L.append("| Variant | N | WR% | AvgR | TotalR | MaxDD_R | MaxDD_% | PF |")
        L.append("|---|---|---|---|---|---|---|---|")
        L.append(_fmt(cfs))
        L.append(_fmt(cds))
        L.append("")

    # Only-Frozen trades
    if only_frozen:
        of_trades = [frozen_keys[k] for k in only_frozen]
        ofs = _outcome_stats(of_trades, "Only-Frozen")
        L.append("### Only-Frozen EQ Trades")
        L.append("")
        L.append("| Variant | N | WR% | AvgR | TotalR | MaxDD_R | MaxDD_% | PF |")
        L.append("|---|---|---|---|---|---|---|---|")
        L.append(_fmt(ofs))
        L.append("")

    # Only-Dynamic trades
    if only_dynamic:
        od_trades = [dynamic_keys[k] for k in only_dynamic]
        ods = _outcome_stats(od_trades, "Only-Dynamic")
        L.append("### Only-Dynamic EQ Trades")
        L.append("")
        L.append("| Variant | N | WR% | AvgR | TotalR | MaxDD_R | MaxDD_% | PF |")
        L.append("|---|---|---|---|---|---|---|---|")
        L.append(_fmt(ods))
        L.append("")

    # ── Table 4: Dynamic EQ adds/removes ──
    L.append("## 4. DYNAMIC EQ NET IMPACT")
    L.append("")
    if only_dynamic:
        od_wins = sum(
            1
            for t in [dynamic_keys[k] for k in only_dynamic]
            if t["result"] in ("TP", "PROFIT_TRAIL")
        )
        od_losses = sum(1 for t in [dynamic_keys[k] for k in only_dynamic] if t["result"] == "LOSS")
        L.append(
            f"- Dynamic EQ **added** {len(only_dynamic)} new trades "
            f"({od_wins} wins, {od_losses} losses)"
        )
    if only_frozen:
        of_wins = sum(
            1
            for t in [frozen_keys[k] for k in only_frozen]
            if t["result"] in ("TP", "PROFIT_TRAIL")
        )
        of_losses = sum(1 for t in [frozen_keys[k] for k in only_frozen] if t["result"] == "LOSS")
        L.append(
            f"- Dynamic EQ **removed** {len(only_frozen)} Frozen EQ trades "
            f"({of_wins} wins, {of_losses} losses)"
        )
    L.append("")

    L.append("Observation-only. No commentary or decision.")
    L.append("")

    report_path = out_dir / "exp5f_frozen_vs_dynamic_report.md"
    report_path.write_text("\n".join(L), encoding="utf-8")

    print(f"Comparison JSON : {comp_path}")
    print(f"Report          : {report_path}")


if __name__ == "__main__":
    mp.freeze_support()
    main()
