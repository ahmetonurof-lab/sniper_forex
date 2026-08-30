"""
EXP 5C — OB/Breaker Context × Outcome Attribution
====================================================

Amaç: EXP5C OB/Breaker telemetry'yi KNOWN-GOOD historical trades ile
eslestirip context kırılımında outcome raporu üretmek.

DISIPLIN:
- Entry filtreleri DEGISTIRILMEZ; OB/Breaker yalnizca forensic context.
- KNOWN-GOOD run_test_a, EXP5B, Research EQ ve production'a dokunulmaz.
- Yeni backtest framework YAZILMAZ; mevcut exp5c_ob_breaker_forensics
  toplama dongusu + run_test_a yeniden kullanilir.
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

# ── Canonical imports (same as exp5c_ob_breaker_forensics) ──
from fvg import detect_fvgs as _nexus_detect_fvgs
from models import Bar as NexusBar

from experiment.config import (
    ATR_PERIOD,
    FVG_MIN_SIZE_ATR_MULT,
    FVG_WICK_RATIO_MAX,
    SESSION_END_HOUR,
    SESSION_START_HOUR,
)

# ── OB/Breaker detectors (from exp5c) ──
from experiment.exp5c_ob_breaker_forensics import (
    W_BB,
    W_OB,
    _zones_overlap,
    find_breaker_block,
    find_order_block,
)
from experiment.gemini_benchmark import _is_fresh_fvg, _to_nexus_bar, compute_atr
from experiment.main_research_c_v1_0 import resample_15m, run_test_a
from src.strategy.data_loader import DataLoader
from src.strategy.models import Direction
from src.strategy.session import SessionManager

ICMARKET_FEATHER = _PROJECT_ROOT / "data" / "icmarket_feather"
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "GBPJPY"]
WINDOW_DAYS = 180


# ─────────────────────────────────────────────────────────────────────────────
# Per-symbol: collection + run_test_a + OB/BB lookup → attributed trades
# ─────────────────────────────────────────────────────────────────────────────
def _analyze_symbol(symbol: str) -> Dict[str, Any]:
    loader = DataLoader(feather_dir=ICMARKET_FEATHER)
    bars_1m = loader.load(symbol)

    if bars_1m:
        max_ts = bars_1m[-1].timestamp
        cutoff = max_ts - pd.Timedelta(days=WINDOW_DAYS)
        bars_1m = [b for b in bars_1m if b.timestamp >= cutoff]

    bars_15m = resample_15m(bars_1m)

    if len(bars_15m) < 100:
        return {"symbol": symbol, "attributed_trades": [], "n_sweeps": 0}

    warmup = min(100, len(bars_15m) - 10)
    atr_val = compute_atr(bars_15m[:warmup], period=ATR_PERIOD)
    if atr_val <= 0:
        return {"symbol": symbol, "attributed_trades": [], "n_sweeps": 0}

    session = SessionManager(
        symbol=symbol,
        start_hour=SESSION_START_HOUR,
        end_hour=SESSION_END_HOUR,
        atr=atr_val,
        sweep_atr_tolerance_mult=0.5,
        sweep_default_tolerance=10.0,
    )

    min_fvg_size = max(atr_val * FVG_MIN_SIZE_ATR_MULT, 1e-8)

    sweep_contexts: List[Dict[str, Any]] = []
    active_context: Optional[Dict[str, Any]] = None
    sweep_counter = 0
    nexus_bars: List[NexusBar] = []

    # ── BEGIN: verbatim collection loop (same as exp5b/exp5c) ──
    for i in range(warmup + 1, len(bars_15m)):
        bar = bars_15m[i]
        nexus_bars.append(_to_nexus_bar(bar))

        if i > warmup + 1:
            prev_close = bars_15m[i - 1].close
            tr = max(
                bar.high - bar.low,
                abs(bar.high - prev_close),
                abs(bar.low - prev_close),
            )
            atr_val = (atr_val * (ATR_PERIOD - 1) + tr) / ATR_PERIOD
            min_fvg_size = max(atr_val * FVG_MIN_SIZE_ATR_MULT, 1e-8)

        sweep = session.update(bar)
        if sweep is not None:
            sweep_counter += 1
            active_context = {
                "sweep": sweep,
                "sweep_index": sweep_counter,
                "direction": "bullish" if sweep.direction == Direction.BULLISH else "bearish",
                "fvgs": [],
                "real_indices": set(),
                "complete": False,
            }
            sweep_contexts.append(active_context)

        if active_context is not None and not active_context["complete"]:
            fvgs = _nexus_detect_fvgs(
                nexus_bars,
                lookback=min(100, len(nexus_bars)),
                timeframe="15m",
                min_fvg_size=min_fvg_size,
                max_wick_ratio=FVG_WICK_RATIO_MAX,
            )
            for fvg in fvgs:
                if fvg.real_index <= active_context["sweep"].bar_index:
                    continue
                if fvg.direction != active_context["direction"]:
                    continue
                if fvg.invalidated:
                    continue
                if not _is_fresh_fvg(fvg, bars_15m, i):
                    continue
                if fvg.real_index in active_context["real_indices"]:
                    continue
                active_context["real_indices"].add(fvg.real_index)
                active_context["fvgs"].append(fvg)
                if len(active_context["fvgs"]) >= 2:
                    active_context["complete"] = True
                    break
    # ── END: verbatim collection loop ──

    # Build sweep → FVG map (same as exp5b)
    sweep_fvg_map: Dict[int, Tuple[Optional[int], Optional[int]]] = {}
    for ctx in sweep_contexts:
        fvgs = ctx["fvgs"]
        f1 = fvgs[0].real_index if len(fvgs) >= 1 else None
        f2 = fvgs[1].real_index if len(fvgs) >= 2 else None
        sweep_fvg_map[ctx["sweep"].bar_index] = (f1, f2)

    # Build sweep_index → bar_index map (for OB/BB lookup)
    sweep_bar_to_idx: Dict[int, int] = {}
    for ctx in sweep_contexts:
        sweep_bar_to_idx[ctx["sweep"].bar_index] = ctx["sweep_index"]

    # Run KNOWN-GOOD pipeline
    trades = run_test_a(symbol, bars_15m)

    # Compute OB/Breaker for each FVG per sweep (same as exp5c)
    ob_bb_map: Dict[Tuple[int, int], Dict[str, Any]] = {}  # (sweep_idx, slot) → context
    for ctx in sweep_contexts:
        sweep = ctx["sweep"]
        sweep_idx = ctx["sweep_index"]
        direction = ctx["direction"]
        for slot, fvg in enumerate(ctx["fvgs"], start=1):
            fvg_first = fvg.real_index - 1
            ob = find_order_block(bars_15m, direction, fvg_first, W_OB)
            bb = find_breaker_block(bars_15m, direction, fvg_first, W_BB)

            ob_bb_map[(sweep_idx, slot)] = {
                "ob_found": ob is not None,
                "ob_mitigated": bool(ob["mitigated_before_fvg"]) if ob else None,
                "ob_overlaps": bool(_zones_overlap(ob["top"], ob["bottom"], fvg.top, fvg.bottom))
                if ob
                else None,
                "breaker_found": bb is not None,
                "breaker_overlaps": bool(
                    _zones_overlap(bb["top"], bb["bottom"], fvg.top, fvg.bottom)
                )
                if bb
                else None,
            }

    # Attribute trades
    attributed = []
    for t in trades:
        f1, f2 = sweep_fvg_map.get(t.sweep_bar_index, (None, None))
        if t.zone_index == f1:
            slot = 1
        elif t.zone_index == f2:
            slot = 2
        else:
            slot = 0  # Later/Unknown

        sweep_idx = sweep_bar_to_idx.get(t.sweep_bar_index)
        ctx = ob_bb_map.get((sweep_idx, slot)) if sweep_idx is not None else None

        attributed.append(
            {
                "symbol": t.symbol,
                "result": t.result,
                "pnl_r": t.pnl_r,
                "direction": t.direction,
                "slot": slot,
                "zone_index": t.zone_index,
                "sweep_bar_index": t.sweep_bar_index,
                "entry_bar_index": t.entry_bar_index,
                "exit_bar_index": t.exit_bar_index,
                # OB/BB context (None for slot=0)
                "ob_found": ctx["ob_found"] if ctx else None,
                "ob_mitigated": ctx["ob_mitigated"] if ctx else None,
                "ob_overlaps": ctx["ob_overlaps"] if ctx else None,
                "breaker_found": ctx["breaker_found"] if ctx else None,
                "breaker_overlaps": ctx["breaker_overlaps"] if ctx else None,
            }
        )

    return {
        "symbol": symbol,
        "attributed_trades": attributed,
        "n_sweeps": len(sweep_contexts),
    }


def _worker(symbol: str) -> Dict[str, Any]:
    try:
        return _analyze_symbol(symbol)
    except Exception as e:
        return {
            "symbol": symbol,
            "attributed_trades": [],
            "n_sweeps": 0,
            "error": str(e),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Stats helper
# ─────────────────────────────────────────────────────────────────────────────
def _outcome_stats(trades: List[Dict], label: str) -> Dict[str, Any]:
    completed = [t for t in trades if t["result"] in ("TP", "PROFIT_TRAIL", "LOSS")]
    wins = [t for t in completed if t["result"] in ("TP", "PROFIT_TRAIL")]
    losses = [t for t in completed if t["result"] == "LOSS"]
    opens = [t for t in trades if t["result"] == "OPEN"]
    n = len(trades)
    wr = len(wins) / len(completed) * 100 if completed else 0.0
    rs = [t["pnl_r"] for t in completed]
    total_r = sum(rs)
    avg_r = total_r / len(completed) if completed else 0.0
    expectancy = avg_r  # same as avg_R for fixed-fraction
    cum = peak = maxdd = 0.0
    for t in sorted(completed, key=lambda x: x["exit_bar_index"]):
        cum += t["pnl_r"]
        peak = max(peak, cum)
        maxdd = max(maxdd, peak - cum)
    return {
        "label": label,
        "N": n,
        "completed": len(completed),
        "WR%": round(wr, 1),
        "AvgR": round(avg_r, 3),
        "Expectancy": round(expectancy, 3),
        "TotalR": round(total_r, 2),
        "MaxDD": round(maxdd, 2),
    }


def _fmt_row(st: Dict) -> str:
    return (
        f"| {st['label']} | {st['N']} | {st['completed']} | "
        f"{st['WR%']} | {st['AvgR']} | {st['Expectancy']} | "
        f"{st['TotalR']} | {st['MaxDD']} |"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    t0 = time.time()
    print("=== EXP 5C — OB/Breaker Context × Outcome Attribution ===")
    print(f"Symbols: {SYMBOLS} | 6 workers | window={WINDOW_DAYS}d")
    print()

    with mp.Pool(processes=6) as pool:
        results = pool.map(_worker, SYMBOLS)

    all_trades: List[Dict] = []
    per_symbol: Dict[str, Dict] = {}
    for sym, res in zip(SYMBOLS, results):
        if res.get("error"):
            print(f"  {sym:10s}: ERROR -> {res['error']}")
            continue
        per_symbol[sym] = res
        all_trades.extend(res["attributed_trades"])
        n = len(res["attributed_trades"])
        print(f"  {sym:10s}: trades={n:3d} | sweeps={res['n_sweeps']:3d}")

    completed = [t for t in all_trades if t["result"] in ("TP", "PROFIT_TRAIL", "LOSS")]
    print(f"\nTotal trades: {len(all_trades)} | Completed: {len(completed)}")
    print(f"elapsed {time.time() - t0:.1f}s")
    print()

    # ── Save raw JSON ──
    out_dir = _PROJECT_ROOT / "results" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "exp5c_outcome_attribution.json"
    json_path.write_text(json.dumps(all_trades, indent=2, default=str), encoding="utf-8")
    print(f"JSON: {json_path}")

    # ── Report ──
    L: List[str] = []
    L.append("# EXP 5C — OB/Breaker Context × Outcome Attribution")
    L.append("")
    L.append("Definitions: `results/research/exp5c_ob_breaker_definitions.md`")
    L.append("Entry rules: UNCHANGED (KNOWN-GOOD run_test_a). OB/BB = forensic context only.")
    L.append("")
    L.append("## POPULATION")
    L.append("")
    L.append(f"- Total trades: **{len(all_trades)}** | Completed: **{len(completed)}**")
    L.append(
        f"- FVG #1: {sum(1 for t in all_trades if t['slot'] == 1)} | "
        f"FVG #2: {sum(1 for t in all_trades if t['slot'] == 2)} | "
        f"Later/Unknown: {sum(1 for t in all_trades if t['slot'] == 0)}"
    )
    L.append("")

    # ── Table 1: Slot-level ──
    L.append("## 1. FVG SLOT")
    L.append("")
    L.append("| Context | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |")
    L.append("|---|---|---|---|---|---|---|---|")
    for slot, label in [(1, "FVG #1"), (2, "FVG #2"), (0, "Later/Unknown")]:
        st = _outcome_stats([t for t in all_trades if t["slot"] == slot], label)
        L.append(_fmt_row(st))
    L.append("")

    # ── Table 2: OB context (slot 1+2 only) ──
    fvg_trades = [t for t in all_trades if t["slot"] in (1, 2)]
    L.append("## 2. OB CONTEXT (FVG #1 + #2)")
    L.append("")
    L.append("| Context | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |")
    L.append("|---|---|---|---|---|---|---|---|")
    for label, filt in [
        ("FVG #1 + OB", lambda t: t["slot"] == 1 and t["ob_found"] is True),
        ("FVG #1 + no OB", lambda t: t["slot"] == 1 and t["ob_found"] is False),
        ("FVG #2 + OB", lambda t: t["slot"] == 2 and t["ob_found"] is True),
        ("FVG #2 + no OB", lambda t: t["slot"] == 2 and t["ob_found"] is False),
    ]:
        st = _outcome_stats([t for t in fvg_trades if filt(t)], label)
        L.append(_fmt_row(st))
    L.append("")

    # ── Table 3: OB mitigation (slot 1+2, OB found only) ──
    ob_trades = [t for t in fvg_trades if t["ob_found"] is True]
    L.append("## 3. OB MITIGATION (FVG #1 + #2, OB found only)")
    L.append("")
    L.append("| Context | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |")
    L.append("|---|---|---|---|---|---|---|---|")
    for label, filt in [
        ("OB mitigated", lambda t: t["ob_mitigated"] is True),
        ("OB unmitigated", lambda t: t["ob_mitigated"] is False),
    ]:
        st = _outcome_stats([t for t in ob_trades if filt(t)], label)
        L.append(_fmt_row(st))
    L.append("")

    # ── Table 3b: OB mitigation × slot ──
    L.append("### OB Mitigation × Slot")
    L.append("")
    L.append("| Context | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |")
    L.append("|---|---|---|---|---|---|---|---|")
    for slot, slabel in [(1, "#1"), (2, "#2")]:
        for label, filt in [
            (
                f"OB mitigated {slabel}",
                lambda t, s=slot: t["slot"] == s and t["ob_mitigated"] is True,
            ),
            (
                f"OB unmitigated {slabel}",
                lambda t, s=slot: t["slot"] == s and t["ob_mitigated"] is False,
            ),
        ]:
            st = _outcome_stats([t for t in ob_trades if filt(t)], label)
            L.append(_fmt_row(st))
    L.append("")

    # ── Table 4: Breaker context (slot 1+2 only) ──
    L.append("## 4. BREAKER CONTEXT (FVG #1 + #2)")
    L.append("")
    L.append("| Context | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |")
    L.append("|---|---|---|---|---|---|---|---|")
    for label, filt in [
        ("FVG #1 + Breaker", lambda t: t["slot"] == 1 and t["breaker_found"] is True),
        (
            "FVG #1 + no Breaker",
            lambda t: t["slot"] == 1 and t["breaker_found"] is False,
        ),
        ("FVG #2 + Breaker", lambda t: t["slot"] == 2 and t["breaker_found"] is True),
        (
            "FVG #2 + no Breaker",
            lambda t: t["slot"] == 2 and t["breaker_found"] is False,
        ),
    ]:
        st = _outcome_stats([t for t in fvg_trades if filt(t)], label)
        L.append(_fmt_row(st))
    L.append("")

    # ── Table 5: Breaker overlap (slot 1+2, breaker found only) ──
    bb_trades = [t for t in fvg_trades if t["breaker_found"] is True]
    L.append("## 5. BREAKER OVERLAP (FVG #1 + #2, Breaker found only)")
    L.append("")
    L.append("| Context | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |")
    L.append("|---|---|---|---|---|---|---|---|")
    for label, filt in [
        ("Breaker + overlap FVG", lambda t: t["breaker_overlaps"] is True),
        ("Breaker + no overlap", lambda t: t["breaker_overlaps"] is False),
    ]:
        st = _outcome_stats([t for t in bb_trades if filt(t)], label)
        L.append(_fmt_row(st))
    L.append("")

    # ── Table 6: Breaker overlap × slot ──
    L.append("### Breaker Overlap × Slot")
    L.append("")
    L.append("| Context | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |")
    L.append("|---|---|---|---|---|---|---|---|")
    for slot, slabel in [(1, "#1"), (2, "#2")]:
        for label, filt in [
            (
                f"BB overlap {slabel}",
                lambda t, s=slot: t["slot"] == s and t["breaker_overlaps"] is True,
            ),
            (
                f"BB no overlap {slabel}",
                lambda t, s=slot: t["slot"] == s and t["breaker_overlaps"] is False,
            ),
        ]:
            st = _outcome_stats([t for t in bb_trades if filt(t)], label)
            L.append(_fmt_row(st))
    L.append("")

    # ── Table 7: Combined OB × Breaker matrix (slot 1+2) ──
    L.append("## 6. COMBINED OB × BREAKER MATRIX (FVG #1 + #2)")
    L.append("")
    L.append("| Context | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |")
    L.append("|---|---|---|---|---|---|---|---|")
    for label, filt in [
        ("OB + BB", lambda t: t["ob_found"] is True and t["breaker_found"] is True),
        ("OB + no BB", lambda t: t["ob_found"] is True and t["breaker_found"] is False),
        ("no OB + BB", lambda t: t["ob_found"] is False and t["breaker_found"] is True),
        (
            "no OB + no BB",
            lambda t: t["ob_found"] is False and t["breaker_found"] is False,
        ),
    ]:
        st = _outcome_stats([t for t in fvg_trades if filt(t)], label)
        L.append(_fmt_row(st))
    L.append("")

    L.append("Observation-only. No commentary or decision.")
    L.append("")

    report_path = out_dir / "exp5c_outcome_report.md"
    report_path.write_text("\n".join(L), encoding="utf-8")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    mp.freeze_support()
    main()
