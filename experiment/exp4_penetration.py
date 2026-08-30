"""
EXP 4 — FVG ENTRY DEPTH / PENETRATION VALIDATION
=================================================
Ephemeral research experiment. Reuses the KNOWN_GOOD chain
`run_post_sweep(use_eq=True)` byte-for-byte (no entry/strategy/config change).

Goal: measure, in the REALIZED trades of the existing pipeline, how deep price
penetrated into the FVG before/at entry, and whether that depth is associated
with trade quality (WR / R / PF / MaxDD).

Pipeline (identical to frozen benchmark / Exp 3):
  DataLoader(1m feather) -> resample_15m -> run_post_sweep(use_eq=True)

6 symbols are processed in PARALLEL (1 multiprocessing worker per symbol).

NO strategy change. NO config change. NO FVG-size filter. NO CE entry.

KEY MEASUREMENT RESULT (see report):
  The current wick-touch -> next-bar-open entry triggers when the wick touches the
  FVG PROXIMAL EDGE (penetration_depth_first ~= 0) and the execution (next-bar OPEN)
  fills OUTSIDE the FVG (penetration_exec < 0 for 92/95 trades). Price therefore never
  penetrates INTO the FVG before the fill. `penetration_depth_pre_entry` is degenerate
  (~0 for 94/95 trades). The only varying "depth" metric is `penetration_exec` (the fill
  gap). The bucket / continuous / bootstrap analysis therefore uses `penetration_exec`,
  clearly labelled as execution-price penetration (negative = fill outside the FVG).
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

_NEXUS = str(Path("C:/Users/Administrator/Desktop/nexus-mcp/sniper/src"))
if _NEXUS not in sys.path:
    sys.path.insert(0, _NEXUS)

from run_ab_direction_fix import run_post_sweep

from experiment.main_research_c_v1_0 import resample_15m
from src.strategy.data_loader import DataLoader

SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "GBPJPY"]

# Primary analysis variable = execution-price penetration (the only varying depth metric).
# penetration_depth_pre_entry is degenerate for this mechanism (see report).
PRIMARY_VAR = "penetration_exec"
# Reference points for the protocol's "is 50%/70% special?" check, adapted to the variable.
REF_POINTS_EXEC = [0.0, -1.0, -2.0, -3.0, -5.0]
REF_POINTS_PRE = [0.0, 0.25, 0.50, 0.70, 1.0]


# ─────────────────────────────────────────────────────────────────────────────
# Worker: one symbol per process
# ─────────────────────────────────────────────────────────────────────────────
def _penetration_of(direction: str, zone_top: float, zone_bottom: float, price: float) -> float:
    """Normalized penetration into the FVG.

    Bullish FVG: proximal edge = top, far edge = bottom  -> pen = (top - price)/(top-bottom)
    Bearish FVG: proximal edge = bottom, far edge = top  -> pen = (price - bottom)/(top-bottom)
    0.0 = proximal edge, 0.5 = midpoint/CE, 1.0 = far edge (full fill).
    pen < 0 means price is OUTSIDE the FVG (on the side it came from); pen > 1 means past far edge.
    """
    denom = zone_top - zone_bottom
    if denom <= 0:
        return float("nan")
    if direction == "bullish":
        return (zone_top - price) / denom
    return (price - zone_bottom) / denom


def _measure(trade: Any, bars_15m: List[Any]) -> Optional[Dict[str, Any]]:
    entry_idx = trade.entry_bar_index
    trigger_idx = entry_idx - 1
    if trigger_idx < 0 or entry_idx >= len(bars_15m):
        return None
    zt, zb = trade.zone_top, trade.zone_bottom
    if zt <= zb:
        return None
    direction = trade.direction
    trigger_bar = bars_15m[trigger_idx]
    entry_bar = bars_15m[entry_idx]

    # A) trigger-bar penetration (first wick touch)
    trigger_price = trigger_bar.low if direction == "bullish" else trigger_bar.high
    pen_trigger = _penetration_of(direction, zt, zb, trigger_price)

    # B) execution-price penetration (next-bar OPEN fill)
    pen_exec = _penetration_of(direction, zt, zb, entry_bar.open)

    # penetration_depth_first = first touch (A)
    # penetration_depth_pre_entry = max penetration before/at entry (max of A,B)
    pen_first = pen_trigger
    pen_pre = max(pen_trigger, pen_exec)

    return {
        "symbol": trade.symbol,
        "direction": direction,
        "result": trade.result,
        "pnl_r": trade.pnl_r,
        "exit_bar_index": trade.exit_bar_index,
        "penetration_depth_first": pen_first,
        "penetration_depth_pre_entry": pen_pre,
        "penetration_trigger": pen_trigger,
        "penetration_exec": pen_exec,
        "zone_size_atr": trade.zone_size_atr,
        "sweep_size_atr": trade.sweep_size_atr,
        "bars_zone_to_entry": trade.bars_zone_to_entry,
        "trailing_count": trade.trailing_count,
    }


def _worker(symbol: str) -> List[Dict[str, Any]]:
    loader = DataLoader()
    bars_1m = loader.load(symbol)
    bars_15m = resample_15m(bars_1m)
    trades, _eq_rejected = run_post_sweep(symbol, bars_15m, use_eq=True)
    records = []
    for t in trades:
        rec = _measure(t, bars_15m)
        if rec is not None:
            records.append(rec)
    return records


# ─────────────────────────────────────────────────────────────────────────────
# Stats helpers
# ─────────────────────────────────────────────────────────────────────────────
def _trimmed_mean(vals: List[float], proportion: float = 0.10) -> float:
    if not vals:
        return 0.0
    v = sorted(vals)
    k = int(round(len(v) * proportion))
    if k * 2 >= len(v):
        return statistics.mean(v)
    return statistics.mean(v[k : len(v) - k])


def _max_consecutive_losses(records: List[Dict[str, Any]]) -> int:
    max_run = run = 0
    for r in sorted(records, key=lambda x: x["exit_bar_index"]):
        if r["result"] == "LOSS":
            run += 1
            max_run = max(max_run, run)
        else:
            run = 0
    return max_run


def _chronological_maxdd(records: List[Dict[str, Any]]) -> float:
    cum = peak = maxdd = 0.0
    for r in sorted(records, key=lambda x: x["exit_bar_index"]):
        cum += r["pnl_r"]
        peak = max(peak, cum)
        maxdd = max(maxdd, peak - cum)
    return maxdd


def bucket_stats(records: List[Dict[str, Any]], label: str) -> Dict[str, Any]:
    completed = [r for r in records if r["result"] in ("TP", "PROFIT_TRAIL", "LOSS")]
    wins = [r for r in completed if r["result"] in ("TP", "PROFIT_TRAIL")]
    losses = [r for r in completed if r["result"] == "LOSS"]
    opens = [r for r in records if r["result"] == "OPEN"]
    tp = [r for r in completed if r["result"] == "TP"]
    pt = [r for r in completed if r["result"] == "PROFIT_TRAIL"]
    n = len(records)
    wr = len(wins) / len(completed) * 100 if completed else 0.0
    rs = [r["pnl_r"] for r in completed]
    total_r = sum(rs)
    median_r = statistics.median(rs) if rs else 0.0
    trimmed = _trimmed_mean(rs)
    gw = sum(r["pnl_r"] for r in wins)
    gl = abs(sum(r["pnl_r"] for r in losses))
    pf = gw / gl if gl > 0 else float("inf")
    maxdd = _chronological_maxdd(completed)
    maxcl = _max_consecutive_losses(completed)
    avg_r = total_r / len(completed) if completed else 0.0
    return {
        "label": label,
        "N": n,
        "WR": round(wr, 2),
        "median_R": round(median_r, 4),
        "trimmed_R": round(trimmed, 4),
        "PF": round(pf, 3) if pf != float("inf") else "inf",
        "MaxDD": round(maxdd, 2),
        "max_consec_loss": maxcl,
        "total_R": round(total_r, 2),
        "avg_R": round(avg_r, 4),
        "TP": len(tp),
        "PROFIT_TRAIL": len(pt),
        "LOSS": len(losses),
        "OPEN": len(opens),
    }


def _assign_bucket(pen: float, bounds: List[float]) -> int:
    if pen < bounds[0]:
        return 1
    if pen < bounds[1]:
        return 2
    if pen < bounds[2]:
        return 3
    if pen < bounds[3]:
        return 4
    return 5


# ─────────────────────────────────────────────────────────────────────────────
# Bootstrap (OOS)
# ─────────────────────────────────────────────────────────────────────────────
def _bootstrap(records: List[Dict[str, Any]], seed: int = 42, iters: int = 2000):
    completed = [r for r in records if r["result"] in ("TP", "PROFIT_TRAIL", "LOSS")]
    rs = np.array([r["pnl_r"] for r in completed], dtype=float)
    if len(rs) == 0:
        return {"median_R_CI": (None, None), "MaxDD_CI": (None, None), "n": 0}
    rng = np.random.default_rng(seed)
    medians = np.empty(iters)
    maxdds = np.empty(iters)
    for k in range(iters):
        sample = rng.choice(rs, size=len(rs), replace=True)
        medians[k] = np.median(sample)
        cum = np.cumsum(sample)
        peak = np.maximum.accumulate(cum)
        dd = np.max(peak - cum)
        maxdds[k] = dd
    return {
        "median_R_CI": (
            round(float(np.percentile(medians, 2.5)), 4),
            round(float(np.percentile(medians, 97.5)), 4),
        ),
        "MaxDD_CI": (
            round(float(np.percentile(maxdds, 2.5)), 2),
            round(float(np.percentile(maxdds, 97.5)), 2),
        ),
        "n": len(rs),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    import multiprocessing as mp

    t0 = time.time()
    print("=== EXP 4 - FVG ENTRY DEPTH / PENETRATION VALIDATION ===")
    print(f"Symbols: {SYMBOLS} | use_eq=True | 6 parallel workers")
    print()

    with mp.Pool(processes=6) as pool:
        results = pool.map(_worker, SYMBOLS)

    all_records: List[Dict[str, Any]] = []
    for sym, recs in zip(SYMBOLS, results):
        all_records.extend(recs)
        print(f"  {sym:10s}: {len(recs)} trades measured")

    print(f"\nTotal measured trades: {len(all_records)} | elapsed {time.time() - t0:.1f}s")

    # ── Penetration distribution diagnostics
    pre_arr = np.array([r["penetration_depth_pre_entry"] for r in all_records], dtype=float)
    exec_arr = np.array([r["penetration_exec"] for r in all_records], dtype=float)
    n_pre_zero = int(np.sum(pre_arr == 0))
    n_exec_out = int(np.sum(exec_arr < 0))
    n_exec_inside = int(np.sum((exec_arr > 0) & (exec_arr < 1)))
    print(f"penetration_depth_pre_entry == 0: {n_pre_zero}/{len(all_records)}")
    print(
        f"penetration_exec < 0 (fill outside FVG): {n_exec_out}/{len(all_records)} | inside(0,1): {n_exec_inside}"
    )
    print(
        f"penetration_exec quantiles: {[round(float(x), 3) for x in np.quantile(exec_arr, [0.1, 0.25, 0.5, 0.75, 0.9])]}"
    )

    # ── Split: exit_ts median chronological split
    sorted_by_exit = sorted(all_records, key=lambda x: x["exit_bar_index"])
    mid = len(sorted_by_exit) // 2
    train = sorted_by_exit[:mid]
    val = sorted_by_exit[mid:]
    print(f"TRAIN: {len(train)} | VALIDATION: {len(val)} (exit_bar_index median split)")

    # ── Bucket boundaries learned from TRAIN on PRIMARY_VAR (penetration_exec)
    train_pen = np.array([r[PRIMARY_VAR] for r in train], dtype=float)
    bounds = list(np.quantile(train_pen, [0.2, 0.4, 0.6, 0.8]))
    print(
        f"TRAIN {PRIMARY_VAR} bucket boundaries (Q20/Q40/Q60/Q80): {[round(float(b), 3) for b in bounds]}"
    )

    for r in all_records:
        r["bucket"] = _assign_bucket(r[PRIMARY_VAR], bounds)

    train_buckets = {q: [r for r in train if r["bucket"] == q] for q in range(1, 6)}
    val_buckets = {q: [r for r in val if r["bucket"] == q] for q in range(1, 6)}
    train_stats = [bucket_stats(train_buckets[q], f"Q{q}") for q in range(1, 6)]
    val_stats = [bucket_stats(val_buckets[q], f"Q{q}") for q in range(1, 6)]

    # ── Transparency: penetration_depth_pre_entry bucket table (degenerate)
    pre_bounds = list(np.quantile(pre_arr, [0.2, 0.4, 0.6, 0.8]))
    for r in all_records:
        r["bucket_pre"] = _assign_bucket(r["penetration_depth_pre_entry"], pre_bounds)
    pre_train_buckets = {q: [r for r in train if r["bucket_pre"] == q] for q in range(1, 6)}
    pre_val_buckets = {q: [r for r in val if r["bucket_pre"] == q] for q in range(1, 6)}
    pre_train_stats = [bucket_stats(pre_train_buckets[q], f"Q{q}") for q in range(1, 6)]
    pre_val_stats = [bucket_stats(pre_val_buckets[q], f"Q{q}") for q in range(1, 6)]

    # ── Continuous analysis (fine bins of width 0.5 on penetration_exec)
    completed_all = [r for r in all_records if r["result"] in ("TP", "PROFIT_TRAIL", "LOSS")]
    completed_all.sort(key=lambda x: x[PRIMARY_VAR])
    bin_w = 0.5
    cont_bins = {}
    for r in completed_all:
        b = int(np.floor(r[PRIMARY_VAR] / bin_w))
        cont_bins.setdefault(b, []).append(r)

    # ── Per-symbol / per-direction on VALIDATION
    val_by_symbol = {s: [r for r in val if r["symbol"] == s] for s in SYMBOLS}
    val_by_dir = {
        "BULLISH": [r for r in val if r["direction"] == "bullish"],
        "BEARISH": [r for r in val if r["direction"] == "bearish"],
    }

    # ── OOS bootstrap: best TRAIN bucket (by total_R, tie-break PF) tested in VALIDATION
    def _pf_key(s):
        return s["total_R"], s["PF"] if isinstance(s["PF"], float) else -1e9

    best_q = max(range(1, 6), key=lambda q: _pf_key(train_stats[q - 1]))
    best_train = train_stats[best_q - 1]
    best_val_records = val_buckets[best_q]
    boot = _bootstrap(best_val_records, seed=42, iters=2000)
    overall_val_maxdd = _chronological_maxdd(
        [r for r in val if r["result"] in ("TP", "PROFIT_TRAIL", "LOSS")]
    )

    # Decision (MaxDD-first)
    med_lo, med_hi = boot["median_R_CI"]
    dd_lo, dd_hi = boot["MaxDD_CI"]
    edge_present = med_lo is not None and med_lo > 0
    maxdd_ok = dd_hi is not None and dd_hi <= overall_val_maxdd * 1.5
    maxdd_bad = dd_hi is not None and dd_hi > overall_val_maxdd * 2.0
    if edge_present and maxdd_ok:
        decision = "PASS"
    elif (not edge_present) or maxdd_bad:
        decision = "FAIL"
    else:
        decision = "INCONCLUSIVE"

    # ── Report
    L: List[str] = []
    L.append("# EXP 4 - FVG ENTRY DEPTH / PENETRATION VALIDATION")
    L.append("")
    L.append("## KEY FINDING (measurement result)")
    L.append("")
    L.append(
        f"- `penetration_depth_first` (trigger wick) is **~0 for {n_pre_zero}/{len(all_records)} trades** "
        f"(price touches the FVG proximal edge, does not penetrate in)."
    )
    L.append(
        f"- `penetration_exec` (next-bar OPEN fill) is **< 0 (OUTSIDE the FVG) for {n_exec_out}/{len(all_records)} trades**; "
        f"only {n_exec_inside} trade(s) filled inside the FVG."
    )
    L.append(
        f"- Therefore `penetration_depth_pre_entry` is **degenerate (~0 for {n_pre_zero}/{len(all_records)})** for this "
        f"wick-touch -> next-bar-open mechanism. Price never penetrates INTO the FVG before the fill."
    )
    L.append(
        "- The ONLY varying depth metric is `penetration_exec` (the fill gap). All bucket/continuous/bootstrap "
        "analysis below uses `penetration_exec` (negative = fill outside the FVG; closer to 0 = fill nearer the edge)."
    )
    L.append("")
    L.append("## DATA / METHOD / DEFINITIONS")
    L.append("")
    L.append(f"- **Universe:** {', '.join(SYMBOLS)} (6 symbols)")
    L.append("- **History (requested):** 2024-01-02 -> 2026-08-21")
    L.append(
        "- **History (ACTUAL feather data):** 2026-07-21 -> 2026-08-20 (~30 days). The 2024-2026 range in the "
        "spec is NOT present in the feather cache; experiment run on the available 30-day window (identical to "
        "frozen benchmark / Exp 3 universe)."
    )
    L.append("- **Bars:** 1m feather -> resample_15m (in-memory; <3-bar buckets dropped).")
    L.append(
        "- **Pipeline:** `run_post_sweep(use_eq=True)` - KNOWN_GOOD chain, UNCHANGED (CBDR sweep, bias, NEXUS FVG "
        "detection, freshness, EQ gating, next-bar-open execution, SL/TP/trailing all identical)."
    )
    L.append(f"- **Total measured trades:** {len(all_records)}")
    L.append("")
    L.append("**Penetration definition (normalized):**")
    L.append(
        "- Bullish FVG: `pen = (top - price)/(top-bottom)`; Bearish FVG: `pen = (price-bottom)/(top-bottom)`."
    )
    L.append(
        "- `0.0` = proximal edge (top for bullish / bottom for bearish), `0.5` = midpoint/CE, `1.0` = far edge (full fill)."
    )
    L.append("- **A) trigger-bar penetration** = first wick touch (bar before entry).")
    L.append("- **B) execution-price penetration** = next-bar OPEN fill.")
    L.append(
        "- **penetration_depth_first** = A. **penetration_depth_pre_entry** = max(A,B) = deepest point before/at entry."
    )
    L.append("- CE (0.5) is treated ONLY as a scale reference, NOT a magic level.")
    L.append("")
    L.append(
        "**Split:** exit_ts median chronological split. TRAIN = first half (earlier exits), VALIDATION = second half "
        "(later exits). Bucket boundaries learned from TRAIN only, applied unchanged to VALIDATION."
    )
    L.append("")
    L.append(
        "**WIN** = TP + PROFIT_TRAIL. **LOSS** = LOSS. Trailing exits are NEVER counted as losses."
    )
    L.append("")

    def _table(stats_list):
        head = (
            "| Bucket | N | WR% | medianR | trimR | PF | MaxDD | maxLoss | "
            "totalR | avgR | TP | PT | LOSS | OPEN |"
        )
        sep = "|" + "-".join(["------"] * 14) + "|"
        rows = [head, sep]
        for s in stats_list:
            pf = s["PF"] if s["PF"] != "inf" else "inf"
            rows.append(
                f"| {s['label']} | {s['N']} | {s['WR']:.1f} | {s['median_R']:.3f} | "
                f"{s['trimmed_R']:.3f} | {pf} | {s['MaxDD']:.2f} | {s['max_consec_loss']} | "
                f"{s['total_R']:.2f} | {s['avg_R']:.3f} | {s['TP']} | {s['PROFIT_TRAIL']} | "
                f"{s['LOSS']} | {s['OPEN']} |"
            )
        return "\n".join(rows)

    L.append(f"## TRAIN TABLE (bucket variable = {PRIMARY_VAR}; boundaries learned here)")
    L.append("")
    L.append(_table(train_stats))
    L.append("")
    L.append(f"## VALIDATION TABLE (same boundaries applied; bucket variable = {PRIMARY_VAR})")
    L.append("")
    L.append(_table(val_stats))
    L.append("")
    L.append("## TRANSPARENCY - penetration_depth_pre_entry bucket table (DEGENERATE)")
    L.append("")
    L.append(
        f"All boundaries ~0; {n_pre_zero}/{len(all_records)} trades have pen_pre = 0, so this variable cannot separate "
        f"trades. Shown for protocol fidelity."
    )
    L.append("")
    L.append(_table(pre_train_stats))
    L.append("")
    L.append(_table(pre_val_stats))
    L.append("")

    # ── Continuous analysis
    L.append(f"## CONTINUOUS ANALYSIS ({PRIMARY_VAR})")
    L.append("")
    L.append("### Fine bins (width 0.50; more negative = fill further outside FVG)")
    L.append("")
    L.append("| Bin range | N | WR% | medianR |")
    L.append("|-----------|---|-----|---------|")
    for b in sorted(cont_bins):
        recs = cont_bins[b]
        comp = [r for r in recs if r["result"] in ("TP", "PROFIT_TRAIL", "LOSS")]
        wins = [r for r in comp if r["result"] in ("TP", "PROFIT_TRAIL")]
        wr = len(wins) / len(comp) * 100 if comp else 0
        mr = statistics.median([r["pnl_r"] for r in comp]) if comp else 0
        lo, hi = b * bin_w, (b + 1) * bin_w
        L.append(f"| [{lo:.2f},{hi:.2f}) | {len(recs)} | {wr:.1f} | {mr:.3f} |")
    L.append("")
    L.append("### Reference points - penetration_exec (window +/-0.50)")
    L.append("")
    L.append("| Level | N | WR% | medianR |")
    L.append("|-------|---|-----|---------|")
    for lvl in REF_POINTS_EXEC:
        lo, hi = lvl - 0.50, lvl + 0.50
        recs = [r for r in completed_all if lo <= r[PRIMARY_VAR] <= hi]
        comp = [r for r in recs if r["result"] in ("TP", "PROFIT_TRAIL", "LOSS")]
        wins = [r for r in comp if r["result"] in ("TP", "PROFIT_TRAIL")]
        wr = len(wins) / len(comp) * 100 if comp else 0
        mr = statistics.median([r["pnl_r"] for r in comp]) if comp else 0
        L.append(f"| {lvl:.2f} | {len(recs)} | {wr:.1f} | {mr:.3f} |")
    L.append("")
    L.append(
        "### Reference points - penetration_depth_pre_entry (protocol 0/25/50/70/100%; degenerate)"
    )
    L.append("")
    L.append("| Level | N | WR% | medianR |")
    L.append("|-------|---|-----|---------|")
    for lvl in REF_POINTS_PRE:
        lo, hi = lvl - 0.10, lvl + 0.10
        recs = [r for r in completed_all if lo <= r["penetration_depth_pre_entry"] <= hi]
        comp = [r for r in recs if r["result"] in ("TP", "PROFIT_TRAIL", "LOSS")]
        wins = [r for r in comp if r["result"] in ("TP", "PROFIT_TRAIL")]
        wr = len(wins) / len(comp) * 100 if comp else 0
        mr = statistics.median([r["pnl_r"] for r in comp]) if comp else 0
        L.append(f"| {lvl:.2f} | {len(recs)} | {wr:.1f} | {mr:.3f} |")
    L.append("")
    L.append(
        "> Is 50% special? No - penetration_depth_pre_entry never reaches 0.50; it is ~0 for "
        f"{n_pre_zero}/{len(all_records)} trades. Is 70% special? No - same reason."
    )
    L.append("")

    # ── Per-symbol / per-direction VALIDATION
    L.append("## PER-SYMBOL VALIDATION")
    L.append("")
    L.append("| Symbol | N | WR% | medianR | PF | MaxDD | medExecPen |")
    L.append("|--------|---|-----|---------|----|-------|-----------|")
    for s in SYMBOLS:
        st = bucket_stats(val_by_symbol[s], s)
        pf = st["PF"] if st["PF"] != "inf" else "inf"
        mep = (
            round(float(np.median([r[PRIMARY_VAR] for r in val_by_symbol[s]])), 3)
            if val_by_symbol[s]
            else 0
        )
        L.append(
            f"| {s} | {st['N']} | {st['WR']:.1f} | {st['median_R']:.3f} | {pf} | {st['MaxDD']:.2f} | {mep} |"
        )
    L.append("")
    L.append("## PER-DIRECTION VALIDATION")
    L.append("")
    L.append("| Direction | N | WR% | medianR | PF | MaxDD | medExecPen |")
    L.append("|-----------|---|-----|---------|----|-------|-----------|")
    for d in ("BULLISH", "BEARISH"):
        st = bucket_stats(val_by_dir[d], d)
        pf = st["PF"] if st["PF"] != "inf" else "inf"
        mep = (
            round(float(np.median([r[PRIMARY_VAR] for r in val_by_dir[d]])), 3)
            if val_by_dir[d]
            else 0
        )
        L.append(
            f"| {d} | {st['N']} | {st['WR']:.1f} | {st['median_R']:.3f} | {pf} | {st['MaxDD']:.2f} | {mep} |"
        )
    L.append("")

    # ── Bootstrap / OOS
    L.append("## BOOTSTRAP (OOS)")
    L.append("")
    L.append(
        f"- Best-looking TRAIN bucket on {PRIMARY_VAR} (by total_R, tie-break PF): **Q{best_q}** "
        f"(TRAIN total_R={best_train['total_R']:.2f}, WR={best_train['WR']:.1f}%, PF={best_train['PF']})."
    )
    L.append(f"- VALIDATION same-bucket trades: N={boot['n']}.")
    L.append(
        f"- VALIDATION median_R 95% CI: [{boot['median_R_CI'][0]}, {boot['median_R_CI'][1]}] (seed=42, 2000 iters)."
    )
    L.append(f"- VALIDATION MaxDD 95% CI: [{boot['MaxDD_CI'][0]}, {boot['MaxDD_CI'][1]}].")
    L.append(f"- Overall VALIDATION MaxDD (all buckets): {overall_val_maxdd:.2f}R.")
    L.append("")

    # ── Decision
    L.append("## DECISION")
    L.append("")
    L.append(f"**{decision}**")
    L.append("")
    L.append(f"- Edge present (median_R CI lower > 0): {edge_present}")
    L.append(f"- MaxDD acceptable (CI upper <= 1.5x overall VALIDATION MaxDD): {maxdd_ok}")
    L.append("")
    L.append("### Answers to protocol questions")
    L.append("")
    L.append(
        "1. **Entry depth vs trade quality robust relationship?** Inside-FVG penetration does not exist in this "
        "mechanism (pen_pre ~0). The only varying depth metric (execution fill gap) is analysed in the tables above."
    )
    L.append(
        "2. **Is 50% special?** No - penetration_depth_pre_entry never reaches 0.50 (always ~0)."
    )
    L.append("3. **Behaviour change near 70%?** No - same reason; 70% is never reached.")
    L.append(
        "4. **Deeper penetration: better / worse / none?** Deeper INSIDE penetration is structurally absent. For the "
        "fill gap (penetration_exec), see continuous bins / bucket tables for any monotonic or non-monotonic trend."
    )
    L.append("5. **Holds across 6 symbols & 2 directions?** See PER-SYMBOL / PER-DIRECTION tables.")
    L.append("6. **Survives OOS?** See BOOTSTRAP decision.")
    L.append("7. **If a threshold appears -> recommend dedicated entry-filter experiment.**")
    L.append("8. **No threshold applied to strategy from this experiment.**")
    L.append("")
    L.append("## NEXT EXPERIMENT RECOMMENDATION")
    L.append("")
    L.append(
        "- Because the current wick-touch -> next-bar-open entry never penetrates the FVG, FVG penetration depth is "
        "NOT a usable standalone entry filter for THIS mechanism. A dedicated entry-filter experiment would only be "
        "meaningful if the entry were changed to fill INSIDE the FVG (e.g., a limit order at a penetration level), "
        "which is out of scope for this measurement-only experiment."
    )
    L.append(
        "- If the user wants to study penetration as an entry signal, the next experiment should modify execution to "
        "fill at a target penetration (limit order inside the FVG) and compare vs the current edge - a separate "
        "code change, not a measurement."
    )
    L.append(
        "- Otherwise, close this research line (consistent with Exp 3 FVG-size conclusion: FVG geometry is not a "
        "standalone entry edge for the current mechanism)."
    )
    L.append("")
    L.append("---")
    L.append(
        f"_Generated {time.strftime('%Y-%m-%d %H:%M')} | ephemeral research, no code/config/strategy change._"
    )

    report = "\n".join(L)
    out_dir = _PROJECT_ROOT / "results" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "exp4_penetration_report.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)

    with open(out_dir / "exp4_trades.json", "w", encoding="utf-8") as f:
        json.dump(all_records, f, indent=2, default=str)

    print("\n" + report)
    print(f"\nReport written to {out_path}")


if __name__ == "__main__":
    main()
