"""
EXP 5E — Entry-Time Mitigation Snapshot
=========================================

AMAÇ: Trade entry timestamp'ında mitigation state'i snapshot olarak kaydet.

Mevcut EXP5D tüm barları tarar → final state'i atar. Ama bir trade
belirli bir timestamp'te girer. Entry'den SONRA S4 gerçekleşmiş olabilir
ama entry anında S2/S3 olabilir.

Bu analiz dört boyut kaydeder:
  1. entry_max_penetration_pct — entry öncesi max penetration
  2. entry_state — entry anındaki S-state
  3. post_entry_max_state — entry'den sonra ulaşan max state
  4. post_entry_invalidation — entry'den sonra S4 oldu mu?

Dört cohort:
  A) S0/S1/S2 at entry — hafif temasta, FVG hâlâ "live"
  B) S3 at entry — derin penetration ama far-side close yok
  C) S4 at entry — zaten invalid entry öncesi (neden girildi?)
  D) Post-entry S4 — entry'de healthy idi ama sonra invalid oldu

DISIPLIN:
- Production freshness DEGISTIRILMEZ.
- Yeni backtest window OLUSTURULMAZ.
- KNOWN-GOOD run_test_a unchanged.
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

from fvg import detect_fvgs as _nexus_detect_fvgs
from models import Bar as NexusBar

from experiment.config import (
    ATR_PERIOD,
    FVG_MIN_SIZE_ATR_MULT,
    FVG_WICK_RATIO_MAX,
    SESSION_END_HOUR,
    SESSION_START_HOUR,
)
from experiment.exp5d_fvg_mitigation import (
    S0,
    S1,
    S2,
    S3,
    S4,
    _classify_mitigation_state,
)
from experiment.gemini_benchmark import (
    _is_fresh_fvg,
    _to_nexus_bar,
    compute_atr,
)
from experiment.main_research_c_v1_0 import resample_15m, run_test_a
from src.strategy.data_loader import DataLoader
from src.strategy.models import Bar, Direction
from src.strategy.session import SessionManager

ICMARKET_FEATHER = str(_PROJECT_ROOT / "data" / "icmarket_feather")
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "GBPJPY"]
WINDOW_DAYS = 180


# ── Entry-time snapshot ──────────────────────────────────────────────────────


def _classify_state_in_window(
    bars_15m: List[Bar],
    fvg_top: float,
    fvg_bottom: float,
    direction: str,
    scan_start: int,
    scan_end: int,
) -> Dict[str, Any]:
    """Classify mitigation state within a bounded window [scan_start, scan_end).

    Same logic as _classify_mitigation_state but stops at scan_end.
    scan_end is EXCLUSIVE (bar at scan_end is NOT checked).
    """
    fvg_size = fvg_top - fvg_bottom
    if fvg_size <= 0:
        return {
            "state": S0,
            "max_pen_pct": 0.0,
            "first_touch_index": None,
            "invalidation_index": None,
        }

    first_touch_index: Optional[int] = None
    invalidation_index: Optional[int] = None
    max_penetration = 0.0
    state = S0

    for b in bars_15m:
        if b.index < scan_start or b.index >= scan_end:
            continue

        # Check any interaction with zone
        if direction == "bullish":
            touches_zone = b.low <= fvg_top
        else:
            touches_zone = b.high >= fvg_bottom

        if not touches_zone:
            continue

        # First touch
        if first_touch_index is None:
            first_touch_index = b.index

        # Penetration depth
        if direction == "bullish":
            pen = max(0.0, fvg_top - max(b.low, fvg_bottom))
        else:
            pen = max(0.0, min(b.high, fvg_top) - fvg_bottom)

        pen_pct = (pen / fvg_size * 100.0) if fvg_size > 0 else 0.0
        max_penetration = max(max_penetration, pen_pct)

        # Body entry check
        body_top = max(b.open, b.close)
        body_bottom = min(b.open, b.close)
        if direction == "bullish":
            body_enters = body_bottom < fvg_top
        else:
            body_enters = body_top > fvg_bottom

        # Far-side close check (S4 invalidation)
        if direction == "bullish":
            far_side_close = b.close > fvg_top
        else:
            far_side_close = b.close < fvg_bottom

        if far_side_close and invalidation_index is None:
            invalidation_index = b.index

        # Classify: first meaningful interaction determines state
        if state == S0:
            if far_side_close:
                state = S4
            elif body_enters:
                state = S2
            else:
                state = S1

        # Upgrade S2 → S3 if penetration > 70%
        if state == S2 and pen_pct > 70.0:
            state = S3

    return {
        "state": state,
        "max_pen_pct": round(max_penetration, 2),
        "first_touch_index": first_touch_index,
        "invalidation_index": invalidation_index,
    }


def _entry_snapshot(
    bars_15m: List[Bar],
    fvg_top: float,
    fvg_bottom: float,
    direction: str,
    fvg_real_index: int,
    entry_bar_index: int,
) -> Dict[str, Any]:
    """Capture mitigation state AT entry + post-entry evolution.

    Returns:
        entry_state, entry_max_pen_pct: state at entry moment
        post_entry_max_state: highest state reached after entry
        post_entry_s4: did S4 happen after entry?
        post_entry_max_pen_pct: max penetration after entry
    """
    scan_start = fvg_real_index + 2

    # Phase 1: entry snapshot (scan_start → entry_bar_index)
    entry_result = _classify_state_in_window(
        bars_15m,
        fvg_top,
        fvg_bottom,
        direction,
        scan_start,
        entry_bar_index,
    )

    # Phase 2: post-entry (entry_bar_index → end of data)
    post_result = _classify_state_in_window(
        bars_15m,
        fvg_top,
        fvg_bottom,
        direction,
        entry_bar_index,
        len(bars_15m),
    )

    # Determine post-entry max state
    state_order = {S0: 0, S1: 1, S2: 2, S3: 3, S4: 4}
    entry_level = state_order.get(entry_result["state"], 0)
    post_level = state_order.get(post_result["state"], 0)
    post_entry_max_state = (
        post_result["state"] if post_level > entry_level else entry_result["state"]
    )

    # Did S4 happen post-entry?
    post_entry_s4 = (
        post_result["invalidation_index"] is not None
        and post_result["invalidation_index"] >= entry_bar_index
    )

    # Also check: did entry_result already have S4?
    entry_s4 = entry_result["state"] == S4

    return {
        "entry_state": entry_result["state"],
        "entry_max_pen_pct": entry_result["max_pen_pct"],
        "entry_first_touch_index": entry_result["first_touch_index"],
        "entry_invalidation_index": entry_result["invalidation_index"],
        "post_entry_max_state": post_entry_max_state,
        "post_entry_s4": post_entry_s4,
        "post_entry_max_pen_pct": post_result["max_pen_pct"],
        "entry_s4": entry_s4,
    }


# ── Per-symbol analysis (verbatim collection loop) ──────────────────────────


def _analyze_symbol(symbol: str) -> Dict[str, Any]:
    """Per-symbol: collection loop + entry snapshot + run_test_a."""
    loader = DataLoader(feather_dir=ICMARKET_FEATHER)
    bars_1m = loader.load(symbol)

    if bars_1m:
        max_ts = bars_1m[-1].timestamp
        cutoff = max_ts - pd.Timedelta(days=WINDOW_DAYS)
        bars_1m = [b for b in bars_1m if b.timestamp >= cutoff]

    bars_15m = resample_15m(bars_1m)
    if len(bars_15m) < 100:
        return {"symbol": symbol, "snapshots": [], "trades": [], "n_sweeps": 0}

    warmup = min(100, len(bars_15m) - 10)
    atr_val = compute_atr(bars_15m[:warmup], period=ATR_PERIOD)
    if atr_val <= 0:
        return {"symbol": symbol, "snapshots": [], "trades": [], "n_sweeps": 0}

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

    # ── BEGIN: verbatim collection loop ──
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

    # Sweep → FVG map
    sweep_fvg_map: Dict[int, Tuple[Optional[int], Optional[int]]] = {}
    for ctx in sweep_contexts:
        fvgs = ctx["fvgs"]
        f1 = fvgs[0].real_index if len(fvgs) >= 1 else None
        f2 = fvgs[1].real_index if len(fvgs) >= 2 else None
        sweep_fvg_map[ctx["sweep"].bar_index] = (f1, f2)

    # FVG details lookup (for entry snapshot)
    fvg_details: Dict[int, Dict[str, Any]] = {}
    for ctx in sweep_contexts:
        direction = ctx["direction"]
        for fvg in ctx["fvgs"]:
            fvg_details[fvg.real_index] = {
                "top": fvg.top,
                "bottom": fvg.bottom,
                "direction": direction,
            }

    # Full-state telemetry (for canonical fresh check)
    full_state: Dict[int, Dict[str, Any]] = {}
    for ctx in sweep_contexts:
        sweep = ctx["sweep"]
        direction = ctx["direction"]
        for slot, fvg in enumerate(ctx["fvgs"], start=1):
            result = _classify_mitigation_state(
                bars_15m,
                fvg.top,
                fvg.bottom,
                direction,
                fvg.real_index,
            )
            canonical_fresh = _is_fresh_fvg(fvg, bars_15m, len(bars_15m))
            full_state[fvg.real_index] = {
                **result,
                "canonical_fresh": canonical_fresh,
                "fvg_top": fvg.top,
                "fvg_bottom": fvg.bottom,
            }

    # Run KNOWN-GOOD pipeline for trade outcomes
    trades = run_test_a(symbol, bars_15m)

    # For each trade → entry snapshot
    snapshots: List[Dict[str, Any]] = []
    trade_list: List[Dict[str, Any]] = []

    for t in trades:
        f1, f2 = sweep_fvg_map.get(t.sweep_bar_index, (None, None))
        if t.zone_index == f1:
            slot = 1
        elif t.zone_index == f2:
            slot = 2
        else:
            slot = 0

        # Get FVG details
        fd = fvg_details.get(t.zone_index)
        fs = full_state.get(t.zone_index)

        if fd is not None and t.zone_index is not None and t.entry_bar_index is not None:
            snap = _entry_snapshot(
                bars_15m,
                fd["top"],
                fd["bottom"],
                fd["direction"],
                t.zone_index,
                t.entry_bar_index,
            )
        else:
            snap = {
                "entry_state": None,
                "entry_max_pen_pct": None,
                "entry_first_touch_index": None,
                "entry_invalidation_index": None,
                "post_entry_max_state": None,
                "post_entry_s4": False,
                "post_entry_max_pen_pct": None,
                "entry_s4": False,
            }

        # Canonical fresh = check at entry moment (not end of data)
        if fd is not None and t.zone_index is not None and t.entry_bar_index is not None:
            canonical_fresh_at_entry = _is_fresh_fvg_at(
                t.zone_index,
                bars_15m,
                t.entry_bar_index,
                fd["direction"],
                fd["top"],
                fd["bottom"],
            )
        else:
            canonical_fresh_at_entry = None

        trade_list.append(
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
                # Entry snapshot
                **snap,
                # Canonical fresh at entry
                "canonical_fresh_at_entry": canonical_fresh_at_entry,
                # Full-state canonical fresh (end of data)
                "canonical_fresh_eod": fs["canonical_fresh"] if fs else None,
                "full_state": fs["state"] if fs else None,
            }
        )

    return {
        "symbol": symbol,
        "trades": trade_list,
        "n_sweeps": len(sweep_contexts),
    }


def _is_fresh_fvg_at(
    fvg_real_index: int,
    bars_15m: List[Bar],
    at_index: int,
    direction: str,
    fvg_top: float,
    fvg_bottom: float,
) -> Optional[bool]:
    """Check canonical freshness at a specific point in time (not end of data).

    Mirrors _is_fresh_fvg but stops at at_index instead of len(bars_15m).
    """
    if fvg_real_index is None or at_index is None:
        return None
    scan_from = fvg_real_index + 2
    for b in bars_15m:
        if b.index < scan_from or b.index >= at_index:
            continue
        if direction == "bullish":
            if b.low <= fvg_top:
                return False
        else:
            if b.high >= fvg_bottom:
                return False
    return True


def _worker(symbol: str) -> Dict[str, Any]:
    try:
        return _analyze_symbol(symbol)
    except Exception as e:
        return {
            "symbol": symbol,
            "snapshots": [],
            "trades": [],
            "n_sweeps": 0,
            "error": str(e),
        }


def _outcome_stats(trades: List[Dict], label: str) -> Dict[str, Any]:
    completed = [t for t in trades if t["result"] in ("TP", "PROFIT_TRAIL", "LOSS")]
    wins = [t for t in completed if t["result"] in ("TP", "PROFIT_TRAIL")]
    n = len(trades)
    wr = len(wins) / len(completed) * 100 if completed else 0.0
    rs = [t["pnl_r"] for t in completed]
    total_r = sum(rs)
    avg_r = total_r / len(completed) if completed else 0.0
    cum = peak = maxdd = 0.0
    for t in sorted(completed, key=lambda x: x.get("exit_bar_index", 0) or 0):
        cum += t["pnl_r"]
        peak = max(peak, cum)
        maxdd = max(maxdd, peak - cum)
    return {
        "label": label,
        "N": n,
        "completed": len(completed),
        "WR%": round(wr, 1),
        "AvgR": round(avg_r, 3),
        "Expectancy": round(avg_r, 3),
        "TotalR": round(total_r, 2),
        "MaxDD": round(maxdd, 2),
    }


def _fmt(st: Dict) -> str:
    return (
        f"| {st['label']} | {st['N']} | {st['completed']} | "
        f"{st['WR%']} | {st['AvgR']} | {st['Expectancy']} | "
        f"{st['TotalR']} | {st['MaxDD']} |"
    )


def main():
    t0 = time.time()
    print("=== EXP 5E — Entry-Time Mitigation Snapshot ===")
    print(f"Symbols: {SYMBOLS} | 6 workers | window={WINDOW_DAYS}d")
    print()

    with mp.Pool(processes=6) as pool:
        results = pool.map(_worker, SYMBOLS)

    all_trades: List[Dict] = []
    for sym, res in zip(SYMBOLS, results):
        if res.get("error"):
            print(f"  {sym:10s}: ERROR -> {res['error']}")
            continue
        all_trades.extend(res["trades"])
        n_tr = len(res["trades"])
        print(f"  {sym:10s}: trades={n_tr:3d} | sweeps={res['n_sweeps']:3d}")

    elapsed = time.time() - t0
    print(f"\nTotal trades: {len(all_trades)} | elapsed {elapsed:.1f}s")
    print()

    # ── Entry state distribution ──
    entry_dist: Dict[str, int] = {}
    for t in all_trades:
        s = t.get("entry_state") or "N/A"
        entry_dist[s] = entry_dist.get(s, 0) + 1
    print("Entry-state distribution:")
    for s in [S0, S1, S2, S3, S4, "N/A"]:
        n = entry_dist.get(s, 0)
        if n > 0:
            print(f"  {s}: {n} ({100 * n / len(all_trades):.1f}%)")
    print()

    # ── Post-entry invalidation ──
    post_s4 = sum(1 for t in all_trades if t.get("post_entry_s4"))
    entry_s4 = sum(1 for t in all_trades if t.get("entry_s4"))
    print(f"Entry S4 (invalid before entry): {entry_s4}")
    print(f"Post-entry S4 (invalidated after entry): {post_s4}")
    print()

    # ── Save outputs ──
    out_dir = _PROJECT_ROOT / "results" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)

    trades_path = out_dir / "exp5e_entry_snapshots.json"
    trades_path.write_text(json.dumps(all_trades, indent=2, default=str), encoding="utf-8")

    # ── Load cohort data ──
    cohort_path = out_dir / "exp5c_research_eq_cohort.json"
    cohort_lookup: Dict[tuple, Dict] = {}
    if cohort_path.exists():
        cohort_data = json.loads(cohort_path.read_text(encoding="utf-8"))
        cohort_lookup = {(c["symbol"], c["zone_index"]): c for c in cohort_data}
    for t in all_trades:
        c = cohort_lookup.get((t["symbol"], t["zone_index"]))
        t["cohort"] = c["cohort"] if c else "UNKNOWN"

    # ── FOUR COHORTS ──
    # A) S0/S1/S2 at entry (lightly touched, FVG still "live")
    # B) S3 at entry (deep penetration, no far-side close)
    # C) S4 at entry (already invalid before entry)
    # D) Post-entry S4 (healthy at entry, invalid after)
    cohort_a = [t for t in all_trades if t.get("entry_state") in (S0, S1, S2)]
    cohort_b = [t for t in all_trades if t.get("entry_state") == S3]
    cohort_c = [t for t in all_trades if t.get("entry_s4")]
    cohort_d = [t for t in all_trades if not t.get("entry_s4") and t.get("post_entry_s4")]

    # Non-invalidated (never S4)
    cohort_never_s4 = [
        t for t in all_trades if not t.get("entry_s4") and not t.get("post_entry_s4")
    ]

    # ── Report ──
    L: List[str] = []
    L.append("# EXP 5E — Entry-Time Mitigation Snapshot")
    L.append("")
    L.append("## TANIM")
    L.append("")
    L.append("Her trade'in entry timestamp'ında mitigation state'i snapshot olarak kaydedilir.")
    L.append("Mevcut EXP5D tüm barları tarar → final state. Bu analiz entry anını hedefler.")
    L.append("")
    L.append("### Dört boyut:")
    L.append("1. **entry_max_penetration_pct** — entry öncesi max penetration")
    L.append("2. **entry_state** — entry anındaki S-state")
    L.append("3. **post_entry_max_state** — entry'den sonra ulaşan max state")
    L.append("4. **post_entry_invalidation** — entry'den sonra S4 oldu mu?")
    L.append("")
    L.append("### Dört cohort:")
    L.append("- **A) S0/S1/S2 at entry** — hafif temasta, FVG hâlâ live")
    L.append("- **B) S3 at entry** — derin penetration, far-side close yok")
    L.append("- **C) S4 at entry** — zaten invalid (neden girildi?)")
    L.append("- **D) Post-entry S4** — entry'de healthy ama sonra invalid")
    L.append("")
    L.append("Entry rules: UNCHANGED (KNOWN-GOOD run_test_a). Observation-only.")
    L.append("")

    # ── Population ──
    L.append("## POPULATION")
    L.append("")
    L.append(f"- Total trades: **{len(all_trades)}**")
    L.append(f"- Entry S0/S1/S2 (cohort A): **{len(cohort_a)}**")
    L.append(f"- Entry S3 (cohort B): **{len(cohort_b)}**")
    L.append(f"- Entry S4 (cohort C): **{len(cohort_c)}**")
    L.append(f"- Post-entry S4 (cohort D): **{len(cohort_d)}**")
    L.append(f"- Never S4: **{len(cohort_never_s4)}**")
    L.append("")

    # ── Table 1: Entry state × outcome ──
    L.append("## 1. ENTRY STATE × OUTCOME (all trades)")
    L.append("")
    L.append("| Entry State | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |")
    L.append("|---|---|---|---|---|---|---|---|")
    for s in [S0, S1, S2, S3, S4]:
        subset = [t for t in all_trades if t.get("entry_state") == s]
        if subset:
            st = _outcome_stats(subset, s)
            L.append(_fmt(st))
    # N/A
    na = [t for t in all_trades if t.get("entry_state") is None]
    if na:
        st = _outcome_stats(na, "N/A")
        L.append(_fmt(st))
    st = _outcome_stats(all_trades, "ALL")
    L.append(_fmt(st))
    L.append("")

    # ── Table 2: Four cohorts × outcome ──
    L.append("## 2. FOUR COHORTS × OUTCOME")
    L.append("")
    L.append("| Cohort | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |")
    L.append("|---|---|---|---|---|---|---|---|")
    for label, subset in [
        ("A: S0/S1/S2 at entry", cohort_a),
        ("B: S3 at entry", cohort_b),
        ("C: S4 at entry", cohort_c),
        ("D: Post-entry S4", cohort_d),
        ("Never S4", cohort_never_s4),
    ]:
        if subset:
            st = _outcome_stats(subset, label)
            L.append(_fmt(st))
    st = _outcome_stats(all_trades, "ALL")
    L.append(_fmt(st))
    L.append("")

    # ── Table 3: Entry state × canonical_fresh_at_entry ──
    L.append("## 3. ENTRY STATE × CANONICAL FRESH (at entry)")
    L.append("")
    L.append("| Entry State | Fresh=True | Fresh=False |")
    L.append("|---|---|---|")
    for s in [S0, S1, S2, S3, S4]:
        subset = [t for t in all_trades if t.get("entry_state") == s]
        fresh_t = sum(1 for t in subset if t.get("canonical_fresh_at_entry") is True)
        fresh_f = sum(1 for t in subset if t.get("canonical_fresh_at_entry") is False)
        if subset:
            L.append(f"| {s} | {fresh_t} | {fresh_f} |")
    L.append("")

    # ── Table 4: Canonical fresh=False × entry state (THE KEY QUESTION) ──
    L.append("## 4. CRITICAL: canonical fresh=False × ENTRY STATE")
    L.append("")
    L.append("**\"canonical fresh=False olan FVG'ler entry anında hangi state'teydi?")
    L.append('Hangisi hâlâ pozitif expectancy taşıyor?"**')
    L.append("")
    L.append("| Entry State | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |")
    L.append("|---|---|---|---|---|---|---|---|")
    fresh_false = [t for t in all_trades if t.get("canonical_fresh_at_entry") is False]
    for s in [S0, S1, S2, S3, S4]:
        subset = [t for t in fresh_false if t.get("entry_state") == s]
        if subset:
            st = _outcome_stats(subset, f"fresh=F + {s}")
            L.append(_fmt(st))
    st = _outcome_stats(fresh_false, "ALL fresh=False")
    L.append(_fmt(st))
    L.append("")

    # ── Table 5: Entry penetration distribution by outcome ──
    L.append("## 5. ENTRY PENETRATION BY OUTCOME")
    L.append("")
    completed = [t for t in all_trades if t["result"] in ("TP", "PROFIT_TRAIL", "LOSS")]
    wins = [
        t
        for t in completed
        if t["result"] in ("TP", "PROFIT_TRAIL") and t.get("entry_max_pen_pct") is not None
    ]
    losses = [
        t for t in completed if t["result"] == "LOSS" and t.get("entry_max_pen_pct") is not None
    ]
    if wins and losses:
        w_pens = sorted(t["entry_max_pen_pct"] for t in wins)
        l_pens = sorted(t["entry_max_pen_pct"] for t in losses)
        L.append("| Metric | Winners | Losers |")
        L.append("|---|---|---|")
        for label, p in [("P25", 25), ("P50", 50), ("P75", 75), ("Mean", None)]:
            if p is not None:
                wi = min(int(len(w_pens) * p / 100), len(w_pens) - 1)
                li = min(int(len(l_pens) * p / 100), len(l_pens) - 1)
                L.append(f"| {label} | {w_pens[wi]:.1f}% | {l_pens[li]:.1f}% |")
            else:
                L.append(
                    f"| {label} | {sum(w_pens) / len(w_pens):.1f}% | "
                    f"{sum(l_pens) / len(l_pens):.1f}% |"
                )
    L.append("")

    # ── Table 6: Post-entry invalidation analysis ──
    L.append("## 6. POST-ENTRY INVALIDATION ANALYSIS")
    L.append("")
    L.append("### Trades that were healthy at entry but invalidated after")
    L.append("")
    post_s4_trades = [t for t in all_trades if not t.get("entry_s4") and t.get("post_entry_s4")]
    post_no_s4 = [t for t in all_trades if not t.get("entry_s4") and not t.get("post_entry_s4")]
    L.append("| Post-Entry | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |")
    L.append("|---|---|---|---|---|---|---|---|")
    if post_s4_trades:
        st = _outcome_stats(post_s4_trades, "S4 after entry")
        L.append(_fmt(st))
    if post_no_s4:
        st = _outcome_stats(post_no_s4, "No S4")
        L.append(_fmt(st))
    L.append("")

    # ── Table 7: Cohort A detail — entry state within S0/S1/S2 ──
    L.append("## 7. COHORT A DETAIL — S0/S1/S2 at entry × post-entry")
    L.append("")
    L.append("| Entry | Post Max | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    state_order = {S0: 0, S1: 1, S2: 2, S3: 3, S4: 4}
    for es in [S0, S1, S2]:
        for ps in [S0, S1, S2, S3, S4]:
            subset = [
                t
                for t in cohort_a
                if t.get("entry_state") == es and t.get("post_entry_max_state") == ps
            ]
            if subset:
                st = _outcome_stats(subset, f"{es}→{ps}")
                L.append(
                    f"| {es} | {ps} | {st['N']} | {st['completed']} | "
                    f"{st['WR%']} | {st['AvgR']} | {st['Expectancy']} | "
                    f"{st['TotalR']} | {st['MaxDD']} |"
                )
    L.append("")

    # ── Table 8: fresh=F + S3/S4 at entry — the real question ──
    L.append("## 8. FRESH=F + ENTRY STATE — does entry-state matter?")
    L.append("")
    L.append("**canonical fresh=False olan trade'ler entry anında hangi state'teydi?")
    L.append("S3 at entry vs S4 at entry vs post-entry S4 — hangisi daha iyi?**")
    L.append("")
    L.append("| Entry State | Post S4? | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for s in [S0, S1, S2, S3, S4]:
        for ps4 in [True, False]:
            subset = [
                t
                for t in fresh_false
                if t.get("entry_state") == s and t.get("post_entry_s4") == ps4
            ]
            if subset:
                ps4_label = "post-S4" if ps4 else "no-S4"
                st = _outcome_stats(subset, f"{s}+{ps4_label}")
                L.append(
                    f"| {s} | {ps4_label} | {st['N']} | {st['completed']} | "
                    f"{st['WR%']} | {st['AvgR']} | {st['Expectancy']} | "
                    f"{st['TotalR']} | {st['MaxDD']} |"
                )
    L.append("")

    L.append("Observation-only. No commentary or decision.")
    L.append("")

    report_path = out_dir / "exp5e_entry_snapshot_report.md"
    report_path.write_text("\n".join(L), encoding="utf-8")

    print(f"Trades JSON : {trades_path}")
    print(f"Report      : {report_path}")


if __name__ == "__main__":
    mp.freeze_support()
    main()
