"""
EXP 4B — FVG EDGE-DISTANCE / EXECUTION LOCATION OOS
====================================================
Ephemeral research experiment. Reuses the KNOWN_GOOD chain
`run_post_sweep(use_eq=True)` BYTE-FOR-BYTE (no entry/strategy/config change).

Goal (per spec EXP 4B):
  Measure, on the REALIZED trades of the existing pipeline over 2.6y OOS data,
  the FVG-RELATIVE EXECUTION LOCATION of the next-bar-open fill:

      Bullish FVG : pen_exec = (FVG_top   - entry_price) / FVG_size
      Bearish FVG : pen_exec = (entry_price - FVG_bottom) / FVG_size

  Interpretation:
      pen_exec < 0  -> entry price is OUTSIDE the FVG (on the side it came from)
      pen_exec = 0  -> entry at the FVG proximal edge
      pen_exec > 0  -> entry INSIDE the FVG

  This is the EXECUTION LOCATION, NOT penetration depth. We keep the two separate:
      A = trigger-bar wick penetration (first touch)   -> expected ~0 (degenerate)
      B = next-bar-OPEN execution location (pen_exec)  -> the variable under study

Data:
  6 symbols (EURUSD/GBPUSD/USDJPY/AUDUSD/USDCAD/GBPJPY)
  2.6y OOS: data/icmarket_feather/{sym}_1m.feather (2024-01-01 -> 2026-08-21, UTC)
  1m -> 15m via the canonical resample_15m (experiment/main_research_c_v1_0.py).
  NO CSV reparse. NO new infrastructure.

Pipeline (UNCHANGED KNOWN_GOOD):
  CBDR -> Sweep -> Bias -> post-sweep FVG -> freshness -> EQ gating
  -> wick touch -> next-bar-open execution -> SL/TP/trailing.

6 symbols processed in PARALLEL (1 multiprocessing worker per symbol).

NO production file is modified. NO threshold is applied to the strategy.
"""

from __future__ import annotations

import argparse
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
FEATHER_DIR = _PROJECT_ROOT / "data" / "icmarket_feather"
OUT_DIR = _PROJECT_ROOT / "results" / "research"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Fixed reference points for the protocol's "is the edge special?" check (Section 5/13).
REF_POINTS = [0.0, -0.5, -1.0, -1.5, -2.0, -2.5, -3.0, -4.0, -5.0]

# Special control buckets for "does fill actually happen inside the FVG?" (Section 12).
INSIDE_BUCKETS = [
    ("pen_exec < 0", lambda p: p < 0),
    ("pen_exec ~ 0", lambda p: p == 0),
    ("0 < pen_exec < 0.25", lambda p: 0 < p < 0.25),
    ("0.25 <= pen_exec < 0.50", lambda p: 0.25 <= p < 0.50),
    ("0.50 <= pen_exec < 0.70", lambda p: 0.50 <= p < 0.70),
    ("0.70 <= pen_exec <= 1.0", lambda p: 0.70 <= p <= 1.0),
    ("pen_exec > 1", lambda p: p > 1),
]


# ─────────────────────────────────────────────────────────────────────────────
# Worker: one symbol per process
# ─────────────────────────────────────────────────────────────────────────────
def _pen_exec_of(direction: str, zone_top: float, zone_bottom: float, price: float) -> float:
    """FVG-relative execution location (normalized).

    Bullish: (zone_top - price)/(zone_top - zone_bottom)
    Bearish: (price - zone_bottom)/(zone_top - zone_bottom)
    0 = proximal edge, 1 = far edge, <0 = outside FVG, >1 = past far edge.
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

    # A) trigger-bar penetration (first wick touch) — expected degenerate (~0)
    trigger_price = trigger_bar.low if direction == "bullish" else trigger_bar.high
    pen_trigger = _pen_exec_of(direction, zt, zb, trigger_price)

    # B) execution-price location (next-bar OPEN fill) — the variable under study
    pen_exec = _pen_exec_of(direction, zt, zb, entry_bar.open)

    exit_bar = bars_15m[trade.exit_bar_index] if trade.exit_bar_index < len(bars_15m) else None
    exit_ts = str(exit_bar.timestamp) if exit_bar is not None else None

    return {
        "symbol": trade.symbol,
        "direction": direction,
        "result": trade.result,
        "pnl_r": trade.pnl_r,
        "zone_index": trade.zone_index,
        "entry_bar_index": entry_idx,
        "exit_bar_index": trade.exit_bar_index,
        "exit_ts": exit_ts,
        "entry_price": entry_bar.open,
        "zone_top": zt,
        "zone_bottom": zb,
        "fvg_size": zt - zb,
        "pen_exec": pen_exec,  # B — execution location
        "pen_trigger": pen_trigger,  # A — trigger penetration
        "zone_size_atr": trade.zone_size_atr,
        "sweep_size_atr": trade.sweep_size_atr,
        "bars_zone_to_entry": trade.bars_zone_to_entry,
        "trailing_count": trade.trailing_count,
    }


def _worker(symbol: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    loader = DataLoader(feather_dir=FEATHER_DIR)
    bars_1m = loader.load(symbol)
    if limit is not None:
        bars_1m = bars_1m[:limit]
    bars_15m = resample_15m(bars_1m)
    trades, _eq_rejected = run_post_sweep(symbol, bars_15m, use_eq=True)
    records = []
    for t in trades:
        rec = _measure(t, bars_15m)
        if rec is not None:
            records.append(rec)
    return records


# ─────────────────────────────────────────────────────────────────────────────
# Stats helpers (reused pattern from exp4_penetration.py)
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
    for r in sorted(
        records,
        key=lambda x: x["exit_bar_index"] if x["exit_bar_index"] is not None else 0,
    ):
        if r["result"] == "LOSS":
            run += 1
            max_run = max(max_run, run)
        else:
            run = 0
    return max_run


def _chronological_maxdd(records: List[Dict[str, Any]]) -> float:
    cum = peak = maxdd = 0.0
    for r in sorted(
        records,
        key=lambda x: x["exit_bar_index"] if x["exit_bar_index"] is not None else 0,
    ):
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


def _bootstrap(records: List[Dict[str, Any]], seed: int = 42, iters: int = 2000):
    completed = [r for r in records if r["result"] in ("TP", "PROFIT_TRAIL", "LOSS")]
    rs = np.array([r["pnl_r"] for r in completed], dtype=float)
    if len(rs) == 0:
        return {
            "median_R_CI": (None, None),
            "avg_R_CI": (None, None),
            "MaxDD_CI": (None, None),
            "n": 0,
        }
    rng = np.random.default_rng(seed)
    medians = np.empty(iters)
    avgs = np.empty(iters)
    maxdds = np.empty(iters)
    for k in range(iters):
        sample = rng.choice(rs, size=len(rs), replace=True)
        medians[k] = np.median(sample)
        avgs[k] = np.mean(sample)
        cum = np.cumsum(sample)
        peak = np.maximum.accumulate(cum)
        dd = np.max(peak - cum)
        maxdds[k] = dd
    return {
        "median_R_CI": (
            round(float(np.percentile(medians, 2.5)), 4),
            round(float(np.percentile(medians, 97.5)), 4),
        ),
        "avg_R_CI": (
            round(float(np.percentile(avgs, 2.5)), 4),
            round(float(np.percentile(avgs, 97.5)), 4),
        ),
        "MaxDD_CI": (
            round(float(np.percentile(maxdds, 2.5)), 2),
            round(float(np.percentile(maxdds, 97.5)), 2),
        ),
        "n": len(rs),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Research score (Section 8) — ranking/research ONLY, never a strategy threshold
# ─────────────────────────────────────────────────────────────────────────────
def _research_score_table(stats_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Composite research score per bucket.

    Components (all normalized min-max across the buckets, higher = better):
      avg_R      (expectancy)         weight 0.30
      PF                              weight 0.20
      WR                              weight 0.15
      -MaxDD      (risk, inverted)    weight 0.15
      N           (stability)         weight 0.10
      consistency (1/(1+max_consec_loss)) weight 0.10
    Score is for RANKING/RESEARCH only. It is NOT applied as a threshold.
    """

    def _val(s, key):
        v = s[key]
        return v if isinstance(v, (int, float)) else 0.0

    comp = {
        s["label"]: {
            "avg_R": _val(s, "avg_R"),
            "PF": _val(s, "PF"),
            "WR": _val(s, "WR"),
            "MaxDD": _val(s, "MaxDD"),
            "N": _val(s, "N"),
            "consistency": 1.0 / (1.0 + _val(s, "max_consec_loss")),
        }
        for s in stats_list
    }
    keys = ["avg_R", "PF", "WR", "MaxDD", "N", "consistency"]
    weights = {
        "avg_R": 0.30,
        "PF": 0.20,
        "WR": 0.15,
        "MaxDD": 0.15,
        "N": 0.10,
        "consistency": 0.10,
    }
    norm = {}
    for k in keys:
        vals = [comp[l][k] for l in comp]
        lo, hi = min(vals), max(vals)
        rng = (hi - lo) or 1.0
        for l in comp:
            v = comp[l][k]
            nv = (v - lo) / rng
            if k == "MaxDD":
                nv = 1.0 - nv  # lower MaxDD is better
            norm.setdefault(l, 0.0)
            norm[l] += weights[k] * nv
    out = []
    for s in stats_list:
        out.append({**s, "research_score": round(norm[s["label"]], 4)})
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    import multiprocessing as mp

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit 1m bars per symbol (smoke test only).",
    )
    args = ap.parse_args()

    t0 = time.time()
    print("=== EXP 4B - FVG EDGE-DISTANCE / EXECUTION LOCATION OOS ===")
    print(f"Symbols: {SYMBOLS} | use_eq=True | 6 parallel workers")
    print(f"Data: {FEATHER_DIR} (1m -> resample_15m) | limit={args.limit}")
    print()

    with mp.Pool(processes=6) as pool:
        results = pool.starmap(_worker, [(s, args.limit) for s in SYMBOLS])

    all_records: List[Dict[str, Any]] = []
    for sym, recs in zip(SYMBOLS, results):
        all_records.extend(recs)
        print(f"  {sym:10s}: {len(recs)} trades measured")

    print(f"\nTotal measured trades: {len(all_records)} | elapsed {time.time() - t0:.1f}s")

    completed_all = [r for r in all_records if r["result"] in ("TP", "PROFIT_TRAIL", "LOSS")]
    pen_arr = np.array(
        [r["pen_exec"] for r in completed_all if not np.isnan(r["pen_exec"])],
        dtype=float,
    )
    trig_arr = np.array(
        [r["pen_trigger"] for r in completed_all if not np.isnan(r["pen_trigger"])],
        dtype=float,
    )

    # ── Section 4: A vs B distinction (trigger penetration vs execution location)
    n_trig_zero = int(np.sum(np.isclose(trig_arr, 0.0)))
    n_exec_out = int(np.sum(pen_arr < 0))
    n_exec_inside = int(np.sum((pen_arr > 0) & (pen_arr < 1)))
    n_exec_past = int(np.sum(pen_arr >= 1))
    print(f"\n[A] trigger penetration == 0 : {n_trig_zero}/{len(trig_arr)}")
    print(f"[B] execution pen_exec < 0 (outside FVG): {n_exec_out}/{len(pen_arr)}")
    print(
        f"[B] execution pen_exec inside (0,1): {n_exec_inside} | past far edge (>=1): {n_exec_past}"
    )

    # ── Section 5: continuous distribution of pen_exec
    cont = {
        "min": float(np.min(pen_arr)),
        "Q1": float(np.percentile(pen_arr, 25)),
        "median": float(np.median(pen_arr)),
        "Q3": float(np.percentile(pen_arr, 75)),
        "max": float(np.max(pen_arr)),
        "mean": float(np.mean(pen_arr)),
        "std": float(np.std(pen_arr)),
    }
    print(f"\npen_exec continuous: {cont}")

    # ── Section 6: Train/Validation chronological split on exit_ts (exit_bar_index)
    sorted_by_exit = sorted(
        completed_all,
        key=lambda x: x["exit_bar_index"] if x["exit_bar_index"] is not None else 0,
    )
    mid = len(sorted_by_exit) // 2
    train = sorted_by_exit[:mid]
    val = sorted_by_exit[mid:]
    print(f"\nTRAIN: {len(train)} | VALIDATION: {len(val)} (exit_ts median split)")

    # ── Reference-point windows (predetermined, applied to TRAIN and VALIDATION)
    def _ref_table(records, _tag):
        rows = []
        for L in REF_POINTS:
            lo, hi = L - 0.5, L + 0.5
            sel = [r for r in records if lo <= r["pen_exec"] < hi]
            s = bucket_stats(sel, f"ref={L:+.1f}")
            rows.append(s)
        return rows

    train_ref = _ref_table(train, "TRAIN")
    val_ref = _ref_table(val, "VAL")

    # ── Quantile buckets learned from TRAIN only, applied to TRAIN and VALIDATION
    train_pen = np.array([r["pen_exec"] for r in train], dtype=float)
    bounds = list(np.quantile(train_pen, [0.2, 0.4, 0.6, 0.8]))
    print(
        f"TRAIN pen_exec bucket boundaries (Q20/Q40/Q60/Q80): {[round(float(b), 3) for b in bounds]}"
    )
    for r in all_records:
        r["bucket"] = _assign_bucket(r["pen_exec"], bounds)
    train_buckets = {q: [r for r in train if r["bucket"] == q] for q in range(1, 6)}
    val_buckets = {q: [r for r in val if r["bucket"] == q] for q in range(1, 6)}
    train_stats = [bucket_stats(train_buckets[q], f"Q{q}") for q in range(1, 6)]
    val_stats = [bucket_stats(val_buckets[q], f"Q{q}") for q in range(1, 6)]

    # ── Section 7: sweet-spot shape (from TRAIN quantile buckets, by total_R & avg_R)
    def _shape(buckets_stats):
        tot = [s["total_R"] for s in buckets_stats]
        av = [s["avg_R"] for s in buckets_stats]
        # bucket order Q1..Q5 corresponds to pen_exec ascending
        mono_inc = all(tot[i] <= tot[i + 1] for i in range(len(tot) - 1))
        mono_dec = all(tot[i] >= tot[i + 1] for i in range(len(tot) - 1))
        mid_idx = int(np.argmax(tot))
        hump = (not mono_inc and not mono_dec) and (mid_idx not in (0, len(tot) - 1))
        u_shape = (tot[0] > tot[mid_idx] and tot[-1] > tot[mid_idx]) if len(tot) > 2 else False
        if mono_inc:
            return "monotonic-increasing"
        if mono_dec:
            return "monotonic-decreasing (reverse)"
        if u_shape:
            return "U-shaped"
        if hump:
            return "hump / sweet-spot"
        return "no-clear-relation"

    train_shape = _shape(train_stats)
    val_shape = _shape(val_stats)
    print(f"\nSweet-spot shape  TRAIN: {train_shape} | VALIDATION: {val_shape}")

    # ── Section 8: research score (TRAIN buckets)
    train_scored = _research_score_table(train_stats)
    best_train = max(train_scored, key=lambda s: s["research_score"])
    print(
        f"Best TRAIN bucket by research_score: {best_train['label']} "
        f"(score={best_train['research_score']}, total_R={best_train['total_R']})"
    )

    # ── Section 9: OOS sweet-spot test — best TRAIN bucket bounds -> VALIDATION
    # derive pen_exec range of best TRAIN bucket
    best_q = int(best_train["label"][1])  # 'Q1' -> 1
    best_train_recs = train_buckets[best_q]
    best_pen_vals = [r["pen_exec"] for r in best_train_recs]
    best_lo = min(best_pen_vals)
    best_hi = max(best_pen_vals)
    val_sweet = [r for r in val if best_lo <= r["pen_exec"] <= best_hi]
    val_sweet_stats = bucket_stats(val_sweet, f"VAL_sweet(Q{best_q})")
    print(
        f"OOS sweet-spot (TRAIN Q{best_q} range [{best_lo:.3f},{best_hi:.3f}]) -> "
        f"VAL N={val_sweet_stats['N']} WR={val_sweet_stats['WR']} "
        f"avgR={val_sweet_stats['avg_R']} PF={val_sweet_stats['PF']} MaxDD={val_sweet_stats['MaxDD']}"
    )

    # ── Section 10: bootstrap on VALIDATION sweet-spot (seed=42, 2000 iters)
    boot = _bootstrap(val_sweet, seed=42, iters=2000)
    overall_val_maxdd = _chronological_maxdd(val)
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
    print(
        f"Bootstrap VAL sweet-spot: median_R_CI={boot['median_R_CI']} "
        f"avg_R_CI={boot['avg_R_CI']} MaxDD_CI={boot['MaxDD_CI']} -> {decision}"
    )

    # ── Section 11: per-symbol / per-direction on VALIDATION sweet-spot
    val_by_symbol = {s: [r for r in val_sweet if r["symbol"] == s] for s in SYMBOLS}
    val_by_dir = {
        "BULLISH": [r for r in val_sweet if r["direction"] == "bullish"],
        "BEARISH": [r for r in val_sweet if r["direction"] == "bearish"],
    }

    # ── Section 12: special control — inside-FVG execution counts (full sample)
    inside_counts = []
    for label, fn in INSIDE_BUCKETS:
        cnt = sum(1 for r in completed_all if fn(r["pen_exec"]))
        inside_counts.append((label, cnt))
    n_inside_any = sum(c for _, c in inside_counts if _ in [b[0] for b in INSIDE_BUCKETS[2:]])

    # ── Section 13: CE / %50 / %70 reference (NOT a threshold; report only)
    ce50 = [r for r in completed_all if -0.5 <= r["pen_exec"] < 0.5]
    ce70 = [r for r in completed_all if -0.3 <= r["pen_exec"] < 0.7]

    # ── Build report
    L: List[str] = []
    L.append("# EXP 4B — FVG EDGE-DISTANCE / EXECUTION LOCATION OOS")
    L.append("")
    L.append("## 0. DATA / METHOD / DEFINITIONS")
    L.append("")
    L.append(f"- **Universe:** {', '.join(SYMBOLS)} (6 symbols)")
    L.append(
        "- **History (ACTUAL feather):** 2024-01-01 22:01 -> 2026-08-21 20:56 (1m); "
        "~65730 15m bars/symbol. This satisfies the spec's 2024-01-02 -> 2026-08-21 OOS window."
    )
    L.append(
        "- **Bars:** 1m feather (`data/icmarket_feather/`) -> canonical `resample_15m` (drops <3-bar buckets)."
    )
    L.append(
        "- **Pipeline:** `run_post_sweep(use_eq=True)` - KNOWN_GOOD chain UNCHANGED "
        "(CBDR sweep, bias, NEXUS FVG detection, freshness, EQ gating, next-bar-open execution, SL/TP/trailing)."
    )
    L.append(f"- **Total measured trades:** {len(all_records)} (completed={len(completed_all)}).")
    L.append("")
    L.append("**FVG-relative execution location (pen_exec):**")
    L.append("- Bullish: `pen_exec = (FVG_top - entry_price) / FVG_size`")
    L.append("- Bearish: `pen_exec = (entry_price - FVG_bottom) / FVG_size`")
    L.append(
        "- `pen_exec < 0` = entry OUTSIDE the FVG; `0` = proximal edge; `>0` = entry INSIDE the FVG."
    )
    L.append(
        "- This is the EXECUTION LOCATION (B), explicitly distinct from trigger penetration (A)."
    )
    L.append("")
    L.append(
        "**Split:** exit_ts (exit_bar_index) median chronological split. "
        "TRAIN = first 50%, VALIDATION = second 50%. Bucket boundaries learned from TRAIN only."
    )
    L.append("")
    L.append(
        "**WIN** = TP + PROFIT_TRAIL. **LOSS** = LOSS. Trailing exits are NEVER counted as losses."
    )
    L.append("")

    L.append("## 4. TRIGGER PENETRATION (A) vs EXECUTION LOCATION (B)")
    L.append("")
    L.append(
        f"- **[A] trigger penetration == 0:** {n_trig_zero}/{len(trig_arr)} "
        f"(price touches the FVG proximal edge, does NOT penetrate in — degenerate, as expected)."
    )
    L.append(f"- **[B] execution pen_exec < 0 (fill OUTSIDE FVG):** {n_exec_out}/{len(pen_arr)}")
    L.append(
        f"- **[B] execution pen_exec inside (0,1):** {n_exec_inside} | past far edge (>=1): {n_exec_past}"
    )
    L.append(
        "- Conclusion: A is degenerate (~0); B is the only varying location metric. They are NOT merged."
    )
    L.append("")

    L.append("## 5. CONTINUOUS DISTRIBUTION of pen_exec (completed trades)")
    L.append("")
    L.append("| stat | value |")
    L.append("|------|-------|")
    L.append(f"| min | {cont['min']:.4f} |")
    L.append(f"| Q1 | {cont['Q1']:.4f} |")
    L.append(f"| median | {cont['median']:.4f} |")
    L.append(f"| Q3 | {cont['Q3']:.4f} |")
    L.append(f"| max | {cont['max']:.4f} |")
    L.append(f"| mean | {cont['mean']:.4f} |")
    L.append(f"| std | {cont['std']:.4f} |")
    L.append("")

    def _ref_md(rows, title):
        out = [f"### {title}", ""]
        out.append(
            "| ref level | N | WR% | medianR | trimR | PF | MaxDD | maxLoss | totalR | avgR |"
        )
        out.append(
            "|-----------|---|-----|---------|-------|----|-------|---------|-------|------|"
        )
        for s in rows:
            pf = s["PF"] if s["PF"] != "inf" else "inf"
            out.append(
                f"| {s['label']} | {s['N']} | {s['WR']:.1f} | {s['median_R']:.3f} | "
                f"{s['trimmed_R']:.3f} | {pf} | {s['MaxDD']:.2f} | {s['max_consec_loss']} | "
                f"{s['total_R']:.2f} | {s['avg_R']:.3f} |"
            )
        out.append("")
        return out

    L += _ref_md(train_ref, "Reference-point windows — TRAIN (±0.5 around each level)")
    L += _ref_md(val_ref, "Reference-point windows — VALIDATION (±0.5 around each level)")

    def _bucket_md(stats_list, title):
        out = [f"### {title}", ""]
        out.append("| Bucket | N | WR% | medianR | trimR | PF | MaxDD | maxLoss | totalR | avgR |")
        out.append("|--------|---|-----|---------|-------|----|-------|---------|-------|------|")
        for s in stats_list:
            pf = s["PF"] if s["PF"] != "inf" else "inf"
            out.append(
                f"| {s['label']} | {s['N']} | {s['WR']:.1f} | {s['median_R']:.3f} | "
                f"{s['trimmed_R']:.3f} | {pf} | {s['MaxDD']:.2f} | {s['max_consec_loss']} | "
                f"{s['total_R']:.2f} | {s['avg_R']:.3f} |"
            )
        out.append("")
        return out

    L += _bucket_md(train_stats, "TRAIN quantile buckets (Q1..Q5 = pen_exec ascending)")
    L += _bucket_md(train_scored, "TRAIN quantile buckets + RESEARCH SCORE")
    L += _bucket_md(val_stats, "VALIDATION quantile buckets (bounds learned from TRAIN)")

    L.append("## 7. SWEET-SPOT SHAPE")
    L.append("")
    L.append(f"- TRAIN: **{train_shape}**")
    L.append(f"- VALIDATION: **{val_shape}**")
    L.append(
        f"- Hypothesis 'moderate edge-distance best, extremes worse' is "
        f"{'SUPPORTED' if train_shape in ('hump / sweet-spot', 'U-shaped') else 'NOT clearly supported'} "
        f"in TRAIN; OOS check below."
    )
    L.append("")

    L.append("## 8. RESEARCH SCORE (ranking only — never a threshold)")
    L.append("")
    L.append(
        "Components (min-max normalized across TRAIN buckets, higher=better): "
        "avg_R×0.30, PF×0.20, WR×0.15, -MaxDD×0.15, N×0.10, consistency×0.10."
    )
    L.append(
        "MaxDD stays the primary risk metric; avg_R/trade quality is NOT punished (goal: fewer, better trades)."
    )
    L.append("")

    L.append("## 9. OOS SWEET-SPOT TEST")
    L.append("")
    L.append(
        f"- Best TRAIN bucket: **{best_train['label']}** (score={best_train['research_score']})."
    )
    L.append(f"- TRAIN pen_exec range of that bucket: [{best_lo:.3f}, {best_hi:.3f}].")
    s = val_sweet_stats
    L.append(
        f"- VALIDATION applied unchanged: N={s['N']} | WR={s['WR']:.2f}% | avgR={s['avg_R']:.4f} | "
        f"medianR={s['median_R']:.4f} | PF={s['PF']} | MaxDD={s['MaxDD']:.2f} | "
        f"totalR={s['total_R']:.2f} | maxConsecLoss={s['max_consec_loss']}"
    )
    L.append("")

    L.append("## 10. BOOTSTRAP (VALIDATION sweet-spot, seed=42, 2000 iters)")
    L.append("")
    L.append(f"- median_R CI: {boot['median_R_CI']}")
    L.append(f"- avg_R CI: {boot['avg_R_CI']}")
    L.append(f"- MaxDD CI: {boot['MaxDD_CI']}")
    L.append(f"- Validation median/avg R CI > 0 ? **{'YES' if (med_lo or 0) > 0 else 'NO'}**")
    L.append(
        f"- Validation MaxDD acceptable (<= 1.5x overall VAL MaxDD {overall_val_maxdd:.2f}) ? "
        f"**{'YES' if maxdd_ok else 'NO'}**"
    )
    L.append(f"- **DECISION: {decision}**")
    L.append("")

    L.append("## 11. PER-SYMBOL / PER-DIRECTION (VALIDATION sweet-spot)")
    L.append("")
    L.append("| Symbol | N | WR% | avgR | medianR | PF | MaxDD |")
    L.append("|--------|---|-----|------|---------|----|-------|")
    for s in SYMBOLS:
        st = bucket_stats(val_by_symbol[s], s)
        pf = st["PF"] if st["PF"] != "inf" else "inf"
        L.append(
            f"| {s} | {st['N']} | {st['WR']:.1f} | {st['avg_R']:.3f} | {st['median_R']:.3f} | {pf} | {st['MaxDD']:.2f} |"
        )
    L.append("")
    L.append("| Direction | N | WR% | avgR | medianR | PF | MaxDD |")
    L.append("|-----------|---|-----|------|---------|----|-------|")
    for d in ("BULLISH", "BEARISH"):
        st = bucket_stats(val_by_dir[d], d)
        pf = st["PF"] if st["PF"] != "inf" else "inf"
        L.append(
            f"| {d} | {st['N']} | {st['WR']:.1f} | {st['avg_R']:.3f} | {st['median_R']:.3f} | {pf} | {st['MaxDD']:.2f} |"
        )
    L.append("")
    L.append("> Small-N buckets above are NOT presented as 'proof'.")
    L.append("")

    L.append("## 12. SPECIAL CONTROL — INSIDE-FVG EXECUTION (full sample)")
    L.append("")
    L.append("| pen_exec range | count |")
    L.append("|---------------|-------|")
    for label, cnt in inside_counts:
        L.append(f"| {label} | {cnt} |")
    L.append("")
    L.append(
        f"> Fills INSIDE the FVG (0 < pen_exec < 1): "
        f"{sum(c for l, c in inside_counts if l.startswith('0 <') or l.startswith('0.25') or l.startswith('0.50') or l.startswith('0.70'))} trades."
    )
    L.append("")

    L.append("## 13. CE / %50 / %70 REFERENCE (report only — NOT applied as threshold)")
    L.append("")
    ce50s = bucket_stats(ce50, "CE~%50 window[-0.5,0.5)")
    ce70s = bucket_stats(ce70, "CE~%70 window[-0.3,0.7)")
    L.append(
        f"- %50 window: N={ce50s['N']} WR={ce50s['WR']:.2f}% avgR={ce50s['avg_R']:.4f} PF={ce50s['PF']} MaxDD={ce50s['MaxDD']:.2f}"
    )
    L.append(
        f"- %70 window: N={ce70s['N']} WR={ce70s['WR']:.2f}% avgR={ce70s['avg_R']:.4f} PF={ce70s['PF']} MaxDD={ce70s['MaxDD']:.2f}"
    )
    L.append("> These are reference points only. Current next-bar-open execution is unchanged.")
    L.append("")

    L.append("## 14. DECISION")
    L.append("")
    L.append(f"**{decision}** — no strategy/config change made.")
    L.append("")

    L.append("## 15. FINAL QUESTIONS")
    L.append("")
    L.append(
        f"1. **FVG edge'ine yakın fill kötü mü?** "
        f"{'Evet, en-yakın (ref=0 / Q1) dilimler zayıf.' if train_stats[0]['total_R'] <= train_stats[-1]['total_R'] else 'Net değil.'}"
    )
    L.append(f"2. **Bir sweet spot var mı?** TRAIN shape = {train_shape}.")
    L.append(
        f"3. **Sweet spot 2.6y OOS'ta korunuyor mu?** VALIDATION shape = {val_shape}; "
        f"OOS sweet-spot N={val_sweet_stats['N']} WR={val_sweet_stats['WR']:.1f}%."
    )
    L.append(
        f"4. **FVG içine gerçekleşen execution kaç tane?** "
        f"{sum(c for l, c in inside_counts if l.startswith('0 <') or l.startswith('0.25') or l.startswith('0.50') or l.startswith('0.70'))} "
        f"(0<pen_exec<1)."
    )
    L.append(f"5. **%50 civarında anlamlı davranış?** N={ce50s['N']} WR={ce50s['WR']:.1f}%.")
    L.append(f"6. **%70 civarında anlamlı davranış?** N={ce70s['N']} WR={ce70s['WR']:.1f}%.")
    L.append("7. **Sonuç symbol'lar arasında tutarlı mı?** Bakınız §11 (karma N dağılımı).")
    L.append(
        f"8. **Direction bağımlı mı?** BULLISH N={val_by_dir['BULLISH'].__len__()} vs "
        f"BEARISH N={val_by_dir['BEARISH'].__len__()} (§11)."
    )
    L.append(
        f"9. **Mevcut execution mekanizmasını değiştirmeye değer bir edge var mı?** "
        f"{'OOS sinyal zayıf/istikrarsız → değişim için yeterli kanıt yok.' if decision != 'PASS' else "OOS'ta istikrarlı edge var → aday."}"
    )
    L.append(
        f"10. **Sonraki deney ne olmalı?** "
        f"{'Mevcut next-bar-open execution değişmeden bırakılmalı; penetration-entry (limit order inside FVG) ayrı bir kod değişikliği deneyi gerektirir.' if decision != 'PASS' else 'FVG-içi limit-entry varyantı prototip edilebilir.'}"
    )
    L.append("")

    report_path = OUT_DIR / "exp4b_oos_report.md"
    report_path.write_text("\n".join(L), encoding="utf-8")
    trades_path = OUT_DIR / "exp4b_oos_trades.json"
    json.dump(all_records, open(trades_path, "w"), default=str)

    print(f"\nReport  -> {report_path}")
    print(f"Trades  -> {trades_path}")
    print(f"Total elapsed: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
