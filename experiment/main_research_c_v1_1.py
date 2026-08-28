"""
main_research_c_v1_1.py — Research C Engine v1.1: C2 EQ + DD-Based Risk Scaling

=============================================================================
PROMOTION HEADER (PROMOTED 2026-08-28)
=============================================================================
- Engine:          C v1.1 (CANONICAL research engine, version 1.1)
- Parent:          C v1.0  (`experiment/main_research_c_v1_0.py`, FROZEN baseline)
- Variant:         DD-Based Risk Scaling overlay (global portfolio)
- Promotion source:`experiment/exp_maxdd_C_dd_risk_scaling.py`
                   (corrected 2026-08-28 — see provenance section)
- Status:          PROMOTED. The old "pending promotion" / "candidate"
                   status is REMOVED. C v1.1 is the canonical reference
                   for the C2 + DD Scaling research line.
- Authoritative
  benchmark (C v1.0
  baseline, 2.7Y / 6 majors
  / 15m / full):       Trades 2302, WR 69.37%, TotalR +2875.00,
                      AvgR +1.2489, PF 5.08, MaxDD 8.00R, MaxDD% 2.73%
- Authoritative
  benchmark (C v1.1
  with DD scaling,    Trades 2300, paused 2, WR 69.39%, TotalR +2766.91R,
  corrected Exp C,   AvgR +1.2026, PF 5.13, MaxDD 4.71R, MaxDD% 2.19%
  2.7Y / 6 majors /
  15m / full):
- Scaling event
  distribution
  (C v1.1):          x1.0 = 2186, x0.5 = 99, x0.25 = 15, paused = 2.
- Paused set
  (C v1.1):          {('GBPJPY', 96), ('USDJPY', 82)}.

This is NOT a re-implementation. The C v1.0 trade-generation core
(sweep → FVG → C2 EQ → first touch → next-bar-open entry → SL/TP →
trailing → exit) is preserved BY IMPORT. The verified DD Risk
Scaling overlay is embedded as an in-line, post-trade-risk attribution
layer.

=============================================================================
INVALIDATED OLD EXP C REFERENCE
=============================================================================
The earlier Exp C reference numbers
(Trades 2302, paused 0, MaxDD% 1.85, PF 5.13, TotalR ≈ +2823R)
were an ARTIFACT of a cross-symbol `entry_ts_map` bug in
`experiment/exp_maxdd_C_dd_risk_scaling.py` (Phase 1, 2026-08-28):

  - `run_test_a` resets its per-symbol `trade_counter` to 0 on every
    call, so `trade_id` is NOT globally unique across symbols.
  - The old `entry_ts_map = { t.trade_id: ... }` keyed by `trade_id`
    only, so 1895/2302 trades (82%) received a cross-symbol-contaminated
    `entry_ts` value.
  - The contamination happened to produce 0 paused, MaxDD 8.00R,
    MaxDD% 1.85% — those numbers are an artifact, NOT the real
    behavior.
  - Phase 1 fixed the bug (per-symbol lookup) and re-ran the full
    benchmark. The CORRECTED Exp C result IS the C v1.1 result
    (2300/2300 surviving trade identity match, 0 `pnl_r` mismatch,
    identical pause set, identical multiplier distribution).

The 1.85% MaxDD% number is INVALIDATED. The corrected authoritative
reference is 2.19% (C v1.1 = corrected Exp C, both ways).

=============================================================================
WHAT CHANGED VS C v1.0
=============================================================================
ONE isolated change: a per-trade `pnl_r` scaling layer based on the
realized portfolio drawdown at the trade's entry time, applied
GLOBALLY across the 6-major merged trade stream.

- C v1.0 contributes each trade's `pnl_r` (= ±1R SL-relative) directly
  to the equity curve. That is a 1R-per-trade fixed risk model.
- C v1.1 multiplies each accepted trade's `pnl_r` by a multiplier
  derived from the portfolio DD observed BEFORE that trade's entry:
      DD > 6R  -> PAUSE   (trade excluded; 2 paused on canonical data)
      DD > 4R  -> x0.25
      DD > 2R  -> x0.50
      else     -> x1.00

  The scaling is applied to the trade's CONTRIBUTION to the equity
  curve (pnl_r is what would have been added to realized equity). It
  does NOT modify:
    - the trade's existence,
    - the trade's entry / exit prices,
    - the trade's SL / TP,
    - the trade's result type (TP / LOSS / PROFIT_TRAIL / OPEN),
    - the trade's exit timestamp / exit_bar_index,
    - the underlying entry/SL/TP/trailing/exit logic.

=============================================================================
NO-LOOKAHEAD / SAME-BAR CAUSALITY
=============================================================================
The portfolio DD used for a trade's risk decision is measured from
trades that have ALREADY CLOSED (exit_timestamp <= this trade's
entry_timestamp). This is the same no-lookahead rule as
`exp_maxdd_C_dd_risk_scaling.py::apply_dd_risk_scaling`.

When two trades share the same `entry_bar` AND the same
`exit_bar` (hold_bars=0), their relative order is by trade_id (the
canonical engine assigns trade_id in entry order), which preserves
causality: a trade's own PnL is never used to scale itself.

=============================================================================
GLOBAL PORTFOLIO DD (per-symbol entry_ts is preserved)
=============================================================================
The scaling is applied to the MERGED 6-major trade stream (not
per-symbol). Each trade keeps its OWN entry timestamp (derived from
its own symbol's `bars_15m[entry_bar_index].timestamp`) and the
global equity/peak are walked in chronological `exit_timestamp`
order. Per-symbol entry_ts is NEVER cross-contaminated: the lookup
key is `(t.symbol, t.entry_bar_index)`, not `t.trade_id`.

=============================================================================
BEHAVIORAL INVARIANTS (unchanged from C v1.0)
=============================================================================
- 15m construction: identical (M1 → resample_15m, no change here; live
                    ingestion is exercised at the live layer, not the
                    research engine).
- ATR: 14-period Wilder update, computed on bars_15m[:warmup] initially.
- CBDR session window: 19:00→01:00 (server time, spans midnight).
- Sweep detection: SessionManager.update() — IDENTICAL.
- Bias lock: post-sweep — IDENTICAL.
- FVG detection: nexus `detect_fvgs()` — IDENTICAL.
- FVG freshness: `_is_fresh_fvg()` — IDENTICAL.
- C2 EQ formula: eq = (sweep_price + leg_mid) / 2 — IDENTICAL.
- EQ gate: entire FVG on correct side of EQ — IDENTICAL.
- First-touch: bar.low ≤ fvg.top (bullish) / bar.high ≥ fvg.bottom (bearish)
              within ±0.1*ATR — IDENTICAL.
- Next-bar-open execution: entry_price = bars_15m[i+1].open — IDENTICAL.
- SL placement: rp2 = atr * SL_ATR_MULT (1.5); buffer = max(MIN, min(0.25*fh,
               BUFFER_MULT * rp2)) — IDENTICAL.
- TP placement: TP_RR (1.8) × risk distance — IDENTICAL.
- Trailing: `experiment.trailing_adapter.apply_trailing` (1.8R) — IDENTICAL.
- Exit chronology: exit_timestamp-ordered equity curve — IDENTICAL.
- Starting balance: 100R — IDENTICAL.

=============================================================================
USAGE
=============================================================================
  from experiment.main_research_c_v1_1 import run_test_a_v11, compute_stats_v11
  trades = run_test_a_v11("EURUSD", bars_15m)
  stats  = compute_stats_v11(trades)

Or via the 6-major worker:

  python experiment/main_research_c_v1_1.py
  python experiment/main_research_c_v1_1.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Setup paths ──
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# Import the FROZEN C v1.0 engine (UNTOUCHED). We re-use its trade
# generation core BY IMPORT. We do NOT modify it.
from experiment.main_research_c_v1_0 import (  # noqa: E402
    BenchmarkTrade,
    STARTING_BALANCE_R,
    run_test_a as _run_test_a_v10,
)

# ── DD Risk Scaling thresholds (validated in Exp C) ──
# These mirror the production defaults in src/live/portfolio_dd.py
# and the experiment defaults in exp_maxdd_C_dd_risk_scaling.py.
DD_T1: float = 2.0  # >2R  -> x0.50 risk
DD_T2: float = 4.0  # >4R  -> x0.25 risk
DD_T3: float = 6.0  # >6R  -> PAUSE  (trade excluded)


# ─────────────────────────────────────────────────────────────────────
# DD scaling core
# ─────────────────────────────────────────────────────────────────────


def compute_dd_multiplier(dd_now: float) -> float:
    """Return the lot/pnl multiplier for a given realized DD (in R).

    Returns:
        0.00 if dd_now > DD_T3  (PAUSE)
        0.25 if dd_now > DD_T2
        0.50 if dd_now > DD_T1
        1.00 otherwise

    Mirrors `exp_maxdd_C_dd_risk_scaling.py::apply_dd_risk_scaling`
    and `src/live/portfolio_dd.py::compute_lot_multiplier`.
    """
    if dd_now > DD_T3:
        return 0.0
    if dd_now > DD_T2:
        return 0.25
    if dd_now > DD_T1:
        return 0.50
    return 1.0


def apply_dd_scaling(
    trades: List[BenchmarkTrade],
    entry_ts: Optional[List[float]] = None,
    starting_balance: float = STARTING_BALANCE_R,
) -> Tuple[List[BenchmarkTrade], int, int, int, int]:
    """Apply DD-based risk scaling to a list of COMPLETED trades.

    The trade stream is sorted by `exit_timestamp` (chronological, same
    as canonical `compute_stats`). For each trade, the portfolio DD
    measured from already-realized trades (exit_timestamp <= this
    trade's entry_timestamp) determines the multiplier applied to the
    trade's `pnl_r`.

    Args:
        trades:            trade list. May include OPEN trades; they
                           are skipped (no scaling applied, no equity
                           contribution).
        entry_ts:          parallel list of entry timestamps (one per
                           trade, in the same order as `trades`). If
                           None, we use the feather timestamps derived
                           from `entry_bar_index` (mirrors
                           `exp_maxdd_C_dd_risk_scaling.py` main()
                           which builds this list from the bars).
        starting_balance:  starting equity in R (default 100R).

    Returns:
        surviving_trades:  list of accepted, scaled BenchmarkTrade
                           (pnl_r is the SCALED pnl_r; SL/TP/entry/exit
                           fields are UNCHANGED).
        paused_count:      number of trades that were paused
                           (multiplier == 0.0, trade dropped).
        x1_count:          number of trades scaled at x1.00.
        x05_count:         number of trades scaled at x0.50.
        x025_count:        number of trades scaled at x0.25.

    NO-LOOKAHEAD rule: the DD used for a trade's scaling is measured
    from trades that have ALREADY closed BEFORE this trade's entry.
    When `entry_ts` is provided, it MUST be in exit-timestamp-sortable
    order relative to the trade stream — i.e. `sorted(trades, key=exit)`
    and the parallel `entry_ts` list give the correct chronological
    causality.
    """
    completed = [t for t in trades if t.result in ("TP", "PROFIT_TRAIL", "LOSS")]
    # Sort by exit_timestamp (canonical equity-curve order).
    if entry_ts is None:
        # Caller didn't supply entry timestamps: derive from each
        # trade's entry_bar_index via the feather (only used by
        # run_test_a_v11 which has access to the bars).
        raise ValueError(
            "entry_ts is required for apply_dd_scaling (the canonical "
            "BenchmarkTrade has no entry_timestamp field — this is the "
            "same convention as exp_maxdd_C_dd_risk_scaling.py)."
        )

    def _to_float_ts(t) -> float:
        """Normalize Timestamp/float/number to float seconds since epoch."""
        import pandas as _pd

        if hasattr(t, "timestamp") and callable(t.timestamp):
            return float(t.timestamp())
        if hasattr(t, "timestamp") and not callable(t.timestamp):
            # numpy datetime64-like
            return float(_pd.Timestamp(t).timestamp())
        return float(t)

    paired = sorted(
        zip(completed, entry_ts),
        key=lambda p: _to_float_ts(p[0].exit_timestamp),
    )
    ordered = [p[0] for p in paired]
    # Normalize entry_ts to float.
    entry_times_ordered = [_to_float_ts(p[1]) for p in paired]
    # Normalize exit_timestamp to float.
    exit_times = [_to_float_ts(t.exit_timestamp) for t in ordered]

    # TWO equity curves (mirrors exp_maxdd_C_dd_risk_scaling.py):
    #   pre_scale: built from base pnl_r of every trade (including paused
    #     ones — they still contributed to the realized state at the
    #     time their DD was measured). Used to compute the DD that
    #     informs each trade's risk decision.
    #   post_scale: built from scaled pnl_r of surviving trades only.
    #     Paused trades contribute 0 here. Used for post-scale MaxDD.
    pre_equity = starting_balance
    pre_peak = starting_balance
    post_equity = starting_balance
    post_peak = starting_balance
    applied = 0
    surviving: List[BenchmarkTrade] = []
    paused = 0
    n_x1 = 0
    n_x05 = 0
    n_x025 = 0

    for k, t in enumerate(ordered):
        # Advance the applied pointer: include all closed trades whose
        # exit <= this trade's entry (NO lookahead). Both pre_equity and
        # pre_peak are updated so the DD computed below uses the full
        # realized base state up to (and not including) this trade.
        while applied < len(ordered) and exit_times[applied] <= entry_times_ordered[k]:
            et = ordered[applied]
            pre_equity += et.pnl_r
            if pre_equity > pre_peak:
                pre_peak = pre_equity
            applied += 1
        dd_now = pre_peak - pre_equity

        mult = compute_dd_multiplier(dd_now)
        if mult == 0.0:
            paused += 1
            continue
        if mult == 1.0:
            n_x1 += 1
        elif mult == 0.5:
            n_x05 += 1
        elif mult == 0.25:
            n_x025 += 1

        # Build a copy with scaled pnl_r. Dataclass fields are unchanged
        # except pnl_r (the equity-curve contribution).
        scaled = BenchmarkTrade(**t.__dict__)
        scaled.pnl_r = t.pnl_r * mult
        surviving.append(scaled)
        # Update the POST-scale equity curve with this (scaled) contribution.
        # Paused trades do NOT contribute to post_scale (they were dropped).
        post_equity += scaled.pnl_r
        if post_equity > post_peak:
            post_peak = post_equity

    return surviving, paused, n_x1, n_x05, n_x025


def _derive_entry_ts(trades: List[BenchmarkTrade], bars_15m: List) -> List[float]:
    """Build a parallel `entry_ts` list from each trade's
    `entry_bar_index` and the bars' timestamps. Mirrors
    `exp_maxdd_C_dd_risk_scaling.py::main` (the entry_ts_map step).
    """
    import pandas as pd

    ts_array = [b.timestamp for b in bars_15m]
    out: List[float] = []
    for t in trades:
        ei = getattr(t, "entry_bar_index", 0)
        if 0 <= ei < len(ts_array):
            out.append(float(pd.Timestamp(ts_array[ei]).timestamp()))
        else:
            out.append(0.0)
    return out


# ─────────────────────────────────────────────────────────────────────
# C v1.1 entry point
# ─────────────────────────────────────────────────────────────────────


def run_test_a_v11(
    symbol: str,
    bars_15m: List,
) -> List[BenchmarkTrade]:
    """C v1.1 trade list.

    Generates trades using the FROZEN C v1.0 engine (imported as
    `_run_test_a_v10`) and then applies the DD risk scaling overlay.

    Returns the SCALED trade list (paused trades excluded).
    Trade identity (entry/exit/SL/TP/zone/sweep) is identical to C v1.0.
    """

    base_trades = _run_test_a_v10(symbol, bars_15m)
    entry_ts = _derive_entry_ts(base_trades, bars_15m)
    scaled, _paused, _n1, _n05, _n025 = apply_dd_scaling(base_trades, entry_ts=entry_ts)
    return scaled


# ─────────────────────────────────────────────────────────────────────
# Stats (mirrors C v1.0 compute_stats so v1.0 ↔ v1.1 are comparable)
# ─────────────────────────────────────────────────────────────────────


def compute_stats_v11(
    trades: List[BenchmarkTrade],
    starting_balance: float = STARTING_BALANCE_R,
) -> Dict[str, Any]:
    """Compute portfolio statistics on a (post-scaling) trade list.

    Mirrors `main_research_c_v1_0.compute_stats` so C v1.0 and C v1.1
    can be compared apples-to-apples. The trade list is expected to
    already be SCALED (output of `run_test_a_v11`).
    """
    if not trades:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "open": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "avg_r": 0.0,
            "max_dd": 0.0,
            "max_dd_pct": 0.0,
            "profit_factor": 0.0,
            "trailing_trades": 0,
            "total_hops": 0,
            "avg_hops": 0.0,
            "avg_mfe": 0.0,
            "avg_mae": 0.0,
            "median_mfe": 0.0,
            "median_mae": 0.0,
        }

    completed = [t for t in trades if t.result in ("TP", "PROFIT_TRAIL", "LOSS")]
    wins = [t for t in completed if t.result in ("TP", "PROFIT_TRAIL")]
    losses = [t for t in completed if t.result == "LOSS"]
    total_pnl = sum(t.pnl_r for t in completed)

    # Chronological equity curve using exit_timestamp (same as C v1.0).
    sorted_trades = sorted(completed, key=lambda t: t.exit_timestamp)
    equity = starting_balance
    peak = starting_balance
    max_dd = 0.0
    max_dd_pct = 0.0
    for t in sorted_trades:
        equity += t.pnl_r
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
        if peak > 0:
            pct = dd / peak * 100
            if pct > max_dd_pct:
                max_dd_pct = pct

    trailed = [t for t in trades if t.trailing_count > 0]
    total_hops = sum(t.trailing_count for t in trades)

    mfes = [t.max_favorable for t in completed]
    maes = [t.max_adverse for t in completed]
    avg_mfe = statistics.mean(mfes) if mfes else 0.0
    avg_mae = statistics.mean(maes) if maes else 0.0
    median_mfe = statistics.median(mfes) if mfes else 0.0
    median_mae = statistics.median(maes) if maes else 0.0

    gross_wins = sum(t.pnl_r for t in wins)
    gross_losses = abs(sum(t.pnl_r for t in losses))
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else float("inf")

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "open": len([t for t in trades if t.result == "OPEN"]),
        "win_rate": len(wins) / len(completed) * 100 if completed else 0.0,
        "total_pnl": round(total_pnl, 4),
        "avg_r": round(total_pnl / len(completed), 4) if completed else 0.0,
        "max_dd": round(max_dd, 4),
        "max_dd_pct": round(max_dd_pct, 2),
        "profit_factor": round(profit_factor, 2),
        "trailing_trades": len(trailed),
        "total_hops": total_hops,
        "avg_hops": round(total_hops / len(trailed), 2) if trailed else 0.0,
        "avg_mfe": round(avg_mfe, 4),
        "avg_mae": round(avg_mae, 4),
        "median_mfe": round(median_mfe, 4),
        "median_mae": round(median_mae, 4),
    }


# ─────────────────────────────────────────────────────────────────────
# Worker (mirrors C v1.0 _run_symbol) — BASE trades only (no scaling)
# ─────────────────────────────────────────────────────────────────────


def _run_symbol_base(
    sym: str, dry_run: bool
) -> Tuple[List[BenchmarkTrade], List[float]]:
    """Run the FROZEN C v1.0 engine for one symbol and derive per-symbol
    `entry_ts` (one timestamp per base trade). No DD scaling here.

    Returns:
        base_trades: unscaled (base) BenchmarkTrade list for `sym`.
        entry_ts:    parallel list of pd.Timestamp (entry time) for
                     each base trade, derived from
                     `bars_15m[entry_bar_index].timestamp`. Trade
                     identity and chronological order match
                     `base_trades` exactly.
    """
    import pandas as pd

    print(f"  [WORKER] {sym}: starting C v1.1 (base) ...", flush=True)
    from src.strategy.models import Bar

    feather_path = _PROJECT_ROOT / "data" / "icmarket_feather" / f"{sym}_15m.feather"
    df = pd.read_feather(feather_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    bars_15m = [
        Bar(
            index=i,
            timestamp=pd.Timestamp(ts),
            open=float(o),
            high=float(h),
            low=float(lo),
            close=float(c),
            volume=float(v),
        )
        for i, ts, o, h, lo, c, v in zip(
            range(len(df)),
            df["timestamp"].values,
            df["open"].values.astype(float),
            df["high"].values.astype(float),
            df["low"].values.astype(float),
            df["close"].values.astype(float),
            df["volume"].values.astype(float),
        )
    ]
    if dry_run:
        bars_15m = bars_15m[:2000]
    base_trades = _run_test_a_v10(sym, bars_15m)
    entry_ts = _derive_entry_ts(base_trades, bars_15m)
    return base_trades, entry_ts


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Research C v1.1 — C2 EQ + DD Risk Scaling"
    )
    parser.add_argument("symbols", nargs="*", help="Symbols (default: 6 majors)")
    parser.add_argument("--dry-run", action="store_true", help="Smoke test (2000 bars)")
    parser.add_argument(
        "--starting-balance",
        type=float,
        default=STARTING_BALANCE_R,
        help=f"Starting balance in R for DD% (default: {STARTING_BALANCE_R})",
    )
    args = parser.parse_args()

    SIX_MAJORS = ["EURUSD", "GBPUSD", "GBPJPY", "USDJPY", "AUDUSD", "USDCAD"]
    symbols = [s.upper() for s in args.symbols] if args.symbols else SIX_MAJORS

    print("=== RESEARCH C v1.1 — C2 EQ + DD-BASED RISK SCALING ===")
    print(f"Thresholds: DD>{DD_T1}R x0.50 | DD>{DD_T2}R x0.25 | DD>{DD_T3}R PAUSE")
    print(f"Symbols: {symbols} | {'DRY RUN' if args.dry_run else 'FULL 2.7Y'}")
    print()

    # STEP 1: Run C v1.0 base engine for all 6 majors in parallel and
    # collect BASE trades + per-symbol entry_ts. No scaling here.
    t0 = time.time()
    all_base_trades: List[BenchmarkTrade] = []
    all_entry_ts: List[float] = []
    # We need each symbol's base_trades + entry_ts in a deterministic
    # order so that the global apply_dd_scaling() sees a stable
    # chronological stream. We use a serial loop (one symbol at a
    # time) — C v1.0's per-symbol work is fast enough at 6-symbol
    # scale (~6 minutes) and the determinism matters for a valid
    # global portfolio equity curve. (Pure-parallel mode would
    # require a global sort by entry/exit timestamp; serial is
    # simpler and still within budget.)
    for s in symbols:
        base_sym, et_sym = _run_symbol_base(s, args.dry_run)
        all_base_trades.extend(base_sym)
        all_entry_ts.extend(et_sym)
    elapsed = time.time() - t0

    # STEP 2: Apply DD scaling GLOBALLY across the 6 majors. One
    # call, one equity curve, one chronological walk. The base
    # trade stream is the merged 6-major stream; the per-symbol
    # entry_ts is preserved (each trade knows when IT entered, the
    # scaling logic only needs the entry timestamp relative to the
    # global exit-timestamp order).
    scaled_trades, paused, n_x1, n_x05, n_x025 = apply_dd_scaling(
        all_base_trades,
        entry_ts=all_entry_ts,
        starting_balance=args.starting_balance,
    )

    # STEP 3: Stats come from the SAME scaled stream. No
    # recomputation, no second pass.
    stats = compute_stats_v11(scaled_trades, starting_balance=args.starting_balance)
    completed = [t for t in scaled_trades if t.result != "OPEN"]
    open_n = len(scaled_trades) - len(completed)

    print(
        f"  [C v1.1] {stats['trades']}T | {stats['wins']}W/{stats['losses']}L | "
        f"{stats['win_rate']:.2f}% WR | {stats['total_pnl']:+.2f}R | "
        f"PF {stats['profit_factor']:.2f} | DD {stats['max_dd']:.2f}R "
        f"({stats['max_dd_pct']:.2f}%) | OPEN {open_n} | "
        f"x1={n_x1} x0.5={n_x05} x0.25={n_x025} paused={paused} | {elapsed:.1f}s"
    )
    print()

    # Per-symbol breakdown
    print("=== PER-SYMBOL (C v1.1, from scaled stream) ===")
    syms: Dict[str, List[BenchmarkTrade]] = {}
    for t in scaled_trades:
        syms.setdefault(t.symbol, []).append(t)
    print(f"{'Symbol':<12} {'N':>5} {'WR%':>6} {'PnL':>10} {'AvgR':>8} {'PF':>6}")
    print("-" * 50)
    for sym in sorted(syms):
        s = compute_stats_v11(syms[sym], starting_balance=args.starting_balance)
        print(
            f"{sym:<12} {s['trades']:>5d} {s['win_rate']:>5.1f}% "
            f"{s['total_pnl']:>+9.2f}R {s['avg_r']:>+7.4f} {s['profit_factor']:>5.2f}"
        )
    print()

    # Persist
    out_dir = _PROJECT_ROOT / "results" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "stats": stats,
        "scaling": {
            "x1": n_x1,
            "x0_5": n_x05,
            "x0_25": n_x025,
            "paused": paused,
            "t1": DD_T1,
            "t2": DD_T2,
            "t3": DD_T3,
        },
        "engine": "C v1.1",
        "parent": "C v1.0",
        "promotion_source": "experiment/exp_maxdd_C_dd_risk_scaling.py",
        "starting_balance_r": args.starting_balance,
        "elapsed_s": round(elapsed, 1),
    }
    with open(out_dir / "c_v1_1_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"Results saved to {out_dir}/c_v1_1_summary.json")


def _load_bars(sym: str, dry_run: bool) -> List:
    import pandas as pd
    from src.strategy.models import Bar

    df = pd.read_feather(
        _PROJECT_ROOT / "data" / "icmarket_feather" / f"{sym}_15m.feather"
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    bars_15m = [
        Bar(
            index=i,
            timestamp=pd.Timestamp(ts),
            open=float(o),
            high=float(h),
            low=float(lo),
            close=float(c),
            volume=float(v),
        )
        for i, ts, o, h, lo, c, v in zip(
            range(len(df)),
            df["timestamp"].values,
            df["open"].values.astype(float),
            df["high"].values.astype(float),
            df["low"].values.astype(float),
            df["close"].values.astype(float),
            df["volume"].values.astype(float),
        )
    ]
    if dry_run:
        bars_15m = bars_15m[:2000]
    return bars_15m


if __name__ == "__main__":
    main()
