"""
exp_maxdd_D_open_exposure_cap.py — Experiment D: C2 MaxDD research

Isolates ONE variable: Open Exposure / Total-Risk Cap.

Rule
----
For each new baseline entry, compute the SUM of the initial R-risk of all
currently-OPEN accepted trades at the moment of entry. If adding the new
trade's initial R-risk would EXCEED the cap, the new entry is BLOCKED.

- Initial R-risk per trade: the C2 engine normalises pnl_r to the initial
  SL distance, so every trade risks exactly 1R at entry (loss = -1R).
  Confirmed in main_research_c_v1_0.run_test_a (SL = -1R by construction)
  and in the exp_maxdd_C docstring. Therefore each open trade contributes
  INITIAL_RISK_R = 1.0 to the open-exposure sum, and "Max Open Exposure = 3R"
  is equivalent to "at most 3 concurrently open positions".

  NOTE (mechanical equivalence): under the C2 engine's 1R-per-trade
  normalisation, this overlay is numerically equivalent to Experiment A
  (Concurrent Exposure Cap = 3). It is filed as a SEPARATE experiment
  because the user spec frames the lever as "total R exposure" and the
  audit / MaxDD-episode binding analysis are distinct deliverables. The
  1R-per-trade assumption is documented and can be revisited if the engine
  ever moves to variable initial risk.

NO lookahead guarantees
-----------------------
- The open-exposure sum is computed from trades that are already ACCEPTED
  and have an entry_timestamp <= the new entry's entry_timestamp.
- A trade is REMOVED from the open set when its exit_timestamp <= the new
  entry's entry_timestamp (closed before the new entry, in the engine's
  "exit at bar t processed before entry at bar t+1" sense; here using
  timestamps, exit <= entry means the position is closed by the time of
  the new entry).
- BLOCKED trades are NEVER added to the open set, so their hypothetical
  future exits CANNOT affect the exposure sum or any downstream metric
  (no streak / no PnL / no exposure contamination).
- Same-bar causality: exit_ts == entry_ts of a later trade -> the earlier
  trade is considered closed (released), matching the engine's
  EXIT-before-ENTRY ordering at the same bar.
- Cross-symbol same-bar determinism: the overlay sorts by
  (entry_timestamp, trade_id) so the cap evaluation is reproducible across
  runs (a tie-breaker is required because the per-symbol data loader uses
  a thread pool and the aggregation order is otherwise non-deterministic).

Methodology
-----------
- Baseline = UNTOUCHED C2 engine (main_research_c_v1_0.run_test_a) on the
  6 majors / 2.7Y 15m dataset. EQ, FVG, entry/SL/TP, 1.8R trailing, exit
  logic, compute_stats are all unchanged inside main_research_c_v1_0.py.
- The cap is applied as a POST-HOC portfolio overlay on the baseline trade
  stream. entry_timestamp is attached externally from the 15m bars (the
  canonical engine is not modified).

Deliverables
------------
- PART A: 5 synthetic invariant tests (mechanism proof).
- PART B: FULL 2.7Y/6-major run. C2 baseline vs C2 + cap=3R.
- MaxDD-episode binding analysis: was the cap binding during the MaxDD
  trough? max concurrent exposure over the whole run.

Run:
    python experiment/exp_maxdd_D_open_exposure_cap.py
    python experiment/exp_maxdd_D_open_exposure_cap.py --max-exposure 3.0
    python experiment/exp_maxdd_D_open_exposure_cap.py --dry-run
    python experiment/exp_maxdd_D_open_exposure_cap.py --synth-only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Tuple

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ── Import the canonical, UNTOUCHED C2 engine ─────────────────────────────
from experiment.main_research_c_v1_0 import (  # noqa: E402
    STARTING_BALANCE_R,
    BenchmarkTrade,
    compute_stats,
    run_test_a,
)

# ── Constants ─────────────────────────────────────────────────────────────
# C2 engine: every trade risks 1R at entry (pnl_r normalised to the initial
# SL distance; loss = -1R). Verified in main_research_c_v1_0.run_test_a and
# documented in exp_maxdd_C. Therefore each open trade contributes exactly
# 1.0 to the open-exposure sum.
INITIAL_RISK_R: float = 1.0


# ═════════════════════════════════════════════════════════════════════════════
# PART A — Synthetic invariant tests
# ═════════════════════════════════════════════════════════════════════════════


def _mk_trade(
    trade_id: int,
    entry_ts: float,
    exit_ts: float,
    result: str = "TP",
    symbol: str = "TEST",
) -> SimpleNamespace:
    """Minimal trade-like object for the overlay algorithm.

    The overlay reads only .entry_timestamp and .exit_timestamp (and assumes
    each accepted trade contributes INITIAL_RISK_R = 1.0).
    """
    return SimpleNamespace(
        trade_id=trade_id,
        symbol=symbol,
        entry_timestamp=entry_ts,
        exit_timestamp=exit_ts,
        result=result,
    )


def _exposure_at(kept: List[SimpleNamespace], new_entry_ts: float) -> float:
    """Helper: compute open-exposure (in R) at the moment of a new entry.

    Mirrors the release rule: a prior trade is open iff its exit_ts > the
    new entry_ts. Returns sum of INITIAL_RISK_R over open trades.
    """
    open_n = sum(1 for t in kept if t.exit_timestamp > new_entry_ts)
    return open_n * INITIAL_RISK_R


def synthetic_invariants() -> bool:
    """Run the 5 synthetic invariant tests for the open-exposure cap.

    Tests:
      A1. 1R+1R+1R open -> new 1R entry BLOCKED  (sum 3 + 1 > 3)
      A2. 1R+1R open     -> new 1R entry ACCEPTED (sum 2 + 1 = 3, not > 3)
      A3. Trade closes -> exposure drops -> new entry re-evaluated ACCEPTED
      A4. Blocked trade's later exit does NOT affect exposure
      A5. Same-bar causality: exit_ts == entry_ts of later trade -> released
    """
    print("=" * 72)
    print("PART A -- SYNTHETIC INVARIANT TESTS (mechanism proof)")
    print("=" * 72)
    all_pass = True

    # A1: 1+1+1 open -> 4th BLOCKED
    # Prior trades' exit_ts must be > the new entry_ts so they remain OPEN.
    print()
    print("[A1] 1R+1R+1R open -> new 1R entry BLOCKED (4 > 3)")
    trades = [
        _mk_trade(1, entry_ts=10, exit_ts=300),  # open at ts=200
        _mk_trade(2, entry_ts=20, exit_ts=400),  # open at ts=200
        _mk_trade(3, entry_ts=30, exit_ts=500),  # open at ts=200
        _mk_trade(4, entry_ts=200, exit_ts=600),  # the candidate
    ]
    kept, blocked, stats = apply_open_exposure_cap(trades, max_exposure_r=3.0)
    print(
        f"  kept={[t.trade_id for t in kept]} blocked=4? {stats['blocked_count'] == 1} "
        f"max_open_count={stats['max_open_count']} max_open_r={stats['max_open_r']}"
    )
    ok = (
        [t.trade_id for t in kept] == [1, 2, 3]
        and stats["blocked_count"] == 1
        and stats["max_open_count"] == 3
        and stats["max_open_r"] == 3.0
    )
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}")
    all_pass &= ok

    # A2: 1+1 open -> 3rd ACCEPTED (sum 2+1=3, not > 3)
    print()
    print("[A2] 1R+1R open -> new 1R entry ACCEPTED (3 not > 3)")
    trades = [
        _mk_trade(1, entry_ts=10, exit_ts=100),
        _mk_trade(2, entry_ts=20, exit_ts=110),
        _mk_trade(3, entry_ts=30, exit_ts=200),  # the candidate
    ]
    kept, blocked, stats = apply_open_exposure_cap(trades, max_exposure_r=3.0)
    print(
        f"  kept={[t.trade_id for t in kept]} blocked=0? {stats['blocked_count'] == 0} "
        f"max_open_count={stats['max_open_count']}"
    )
    ok = (
        [t.trade_id for t in kept] == [1, 2, 3]
        and stats["blocked_count"] == 0
        and stats["max_open_count"] == 3
    )
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}")
    all_pass &= ok

    # A3: close releases; new entry ACCEPTED after a close
    print()
    print("[A3] One trade closes -> exposure drops -> new entry ACCEPTED")
    trades = [
        _mk_trade(1, entry_ts=10, exit_ts=100),  # closes at 100
        _mk_trade(2, entry_ts=20, exit_ts=200),  # still open at 150
        _mk_trade(3, entry_ts=150, exit_ts=300),  # at ts=150: only #2 open (1R) -> 1+1=2 OK
    ]
    kept, blocked, stats = apply_open_exposure_cap(trades, max_exposure_r=3.0)
    exposure_at_3 = _exposure_at(kept[:2], 150)
    print(
        f"  kept={[t.trade_id for t in kept]} blocked=0? {stats['blocked_count'] == 0} "
        f"exposure_at_entry3={exposure_at_3}R (expect 1.0)"
    )
    ok = (
        [t.trade_id for t in kept] == [1, 2, 3]
        and stats["blocked_count"] == 0
        and abs(exposure_at_3 - 1.0) < 1e-9
    )
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}")
    all_pass &= ok

    # A4: blocked trade's exit must NOT affect exposure
    print()
    print("[A4] Blocked trade's later exit does NOT affect exposure / open set")
    trades = [
        _mk_trade(1, entry_ts=10, exit_ts=100),
        _mk_trade(2, entry_ts=20, exit_ts=200),
        _mk_trade(3, entry_ts=30, exit_ts=250),
        _mk_trade(4, entry_ts=40, exit_ts=300),  # BLOCKED (3 already open)
        _mk_trade(
            5, entry_ts=260, exit_ts=400
        ),  # by ts=260: #1,2,3 closed (exit<=260?) -> 1 close 100<260 yes; 2 close 200<260 yes; 3 close 250<260 yes. All closed. 0 open. 0+1=1 OK. ACCEPT.
    ]
    kept, blocked, stats = apply_open_exposure_cap(trades, max_exposure_r=3.0)
    print(
        f"  kept={[t.trade_id for t in kept]} blocked=4? {stats['blocked_count'] == 1} "
        f"max_open_count={stats['max_open_count']}"
    )
    # After block of #4, at ts=260: releases #1(e100<260), #2(e200<260), #3(e250<260). All released. #4 blocked, not in open set. So open=0. #5: 0+1=1, accept.
    ok = (
        [t.trade_id for t in kept] == [1, 2, 3, 5]
        and stats["blocked_count"] == 1
        and stats["max_open_count"] == 3
    )
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}")
    all_pass &= ok

    # A5: same-bar causality -- exit_ts == entry_ts of new trade -> released
    print()
    print("[A5] Same-bar causality: exit_ts == new entry_ts -> trade released")
    trades = [
        _mk_trade(1, entry_ts=10, exit_ts=200),  # closes at ts=200
        _mk_trade(2, entry_ts=20, exit_ts=250),  # open at 200
        _mk_trade(3, entry_ts=200, exit_ts=300),  # entry at ts=200; #1 exit=200 <= 200 -> RELEASED
    ]
    kept, blocked, stats = apply_open_exposure_cap(trades, max_exposure_r=3.0)
    exposure_at_3 = _exposure_at(kept[:2], 200)
    print(
        f"  kept={[t.trade_id for t in kept]} blocked=0? {stats['blocked_count'] == 0} "
        f"exposure_at_entry3={exposure_at_3}R (expect 1.0, since #1 released)"
    )
    ok = (
        [t.trade_id for t in kept] == [1, 2, 3]
        and stats["blocked_count"] == 0
        and abs(exposure_at_3 - 1.0) < 1e-9
    )
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}")
    all_pass &= ok

    print()
    print("=" * 72)
    print(f"PART A: {'ALL PASS' if all_pass else 'FAIL'}")
    print("=" * 72)
    return all_pass


# ═════════════════════════════════════════════════════════════════════════════
# Overlay
# ═════════════════════════════════════════════════════════════════════════════


def apply_open_exposure_cap(
    trades: List[BenchmarkTrade],
    max_exposure_r: float = 3.0,
) -> Tuple[List[BenchmarkTrade], List[BenchmarkTrade], Dict[str, float]]:
    """Post-hoc overlay: cap total open R exposure at max_exposure_r.

    Each accepted trade contributes INITIAL_RISK_R (1.0 in the C2 engine) to
    the open-exposure sum while it is open. The overlay replays the trade
    stream in entry-time order:

      1. Release any prior accepted trade whose exit_timestamp <= the new
         entry_timestamp (it is closed by the time of the new entry).
      2. If current_open_R + INITIAL_RISK_R > max_exposure_r -> BLOCK the
         new entry (do NOT add it to the open set, do NOT count its pnl).
      3. Otherwise ACCEPT: add the trade to the open set with its exit_ts.

    Returns (kept, blocked, stats). Blocked trades are returned so the
    caller can analyse their distribution.

    Determinism: trades are sorted by (entry_timestamp, trade_id) so that
    cross-symbol same-bar entries are processed in a stable, reproducible
    order (the first run without this tie-breaker showed non-determinism
    because ThreadPoolExecutor's as_completed order varied run-to-run).
    """
    ordered = sorted(trades, key=lambda t: (t.entry_timestamp, t.trade_id))
    open_exits: List[float] = []
    kept: List[BenchmarkTrade] = []
    blocked: List[BenchmarkTrade] = []
    max_open_count = 0
    max_open_r = 0.0
    exposure_at_entry: List[float] = []  # R-exposure BEFORE each entry decision

    for t in ordered:
        # Release closed positions (exit_ts <= entry_ts of the new trade).
        open_exits = [e for e in open_exits if e > t.entry_timestamp]
        current_open_r = len(open_exits) * INITIAL_RISK_R
        exposure_at_entry.append(current_open_r)
        if current_open_r + INITIAL_RISK_R > max_exposure_r:
            blocked.append(t)
            continue
        kept.append(t)
        open_exits.append(t.exit_timestamp)
        if len(open_exits) > max_open_count:
            max_open_count = len(open_exits)
        if current_open_r + INITIAL_RISK_R > max_open_r:
            max_open_r = current_open_r + INITIAL_RISK_R

    stats = {
        "blocked_count": float(len(blocked)),
        "max_open_count": float(max_open_count),
        "max_open_r": max_open_r,
    }
    return kept, blocked, stats


# ═════════════════════════════════════════════════════════════════════════════
# Data loading (engine untouched; entry_timestamp attached externally)
# ═════════════════════════════════════════════════════════════════════════════


def _load_symbol_trades(symbol: str, dry_run: bool) -> List[BenchmarkTrade]:
    """Run the UNTOUCHED C2 engine for one symbol and attach entry_timestamp
    from the 15m bars. Engine code is never modified."""
    import pandas as pd

    from src.strategy.models import Bar

    feather_dir = _PROJECT_ROOT / "data" / "icmarket_feather"
    feather_path = feather_dir / f"{symbol}_15m.feather"
    df = pd.read_feather(feather_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    bars_15m = [
        Bar(
            index=i,
            timestamp=pd.Timestamp(ts),
            open=float(o),
            high=float(h),
            low=float(l),
            close=float(c),
            volume=float(v),
        )
        for i, ts, o, h, l, c, v in zip(
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

    trades = run_test_a(symbol, bars_15m)
    for t in trades:
        ei = getattr(t, "entry_bar_index", 0)
        if 0 <= ei < len(bars_15m):
            t.entry_timestamp = bars_15m[ei].timestamp
    return trades


def _load_all_trades(symbols: List[str], dry_run: bool) -> List[BenchmarkTrade]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from tqdm import tqdm

    all_trades: List[BenchmarkTrade] = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(_load_symbol_trades, sym, dry_run): sym for sym in symbols}
        pbar = tqdm(total=len(symbols), desc="Processing", unit="sym", ncols=80)
        for future in as_completed(futures):
            sym = futures[future]
            try:
                all_trades.extend(future.result())
            except Exception as e:
                print(f"  ERROR {sym}: {e}")
            pbar.update(1)
        pbar.close()
    return all_trades


# ═════════════════════════════════════════════════════════════════════════════
# MaxDD-episode binding analysis
# ═════════════════════════════════════════════════════════════════════════════


def _baseline_equity_curve(
    trades: List[BenchmarkTrade], starting_balance: float = STARTING_BALANCE_R
) -> List[Tuple[float, float, BenchmarkTrade]]:
    """Chronological equity curve from REALIZED exits. Returns
    list of (cum_pnl_after, dd_at_this_point, trade)."""
    completed = [t for t in trades if t.result in ("TP", "PROFIT_TRAIL", "LOSS")]
    ordered = sorted(completed, key=lambda t: t.exit_timestamp)
    cum = 0.0
    peak = 0.0
    curve: List[Tuple[float, float, BenchmarkTrade]] = []
    for t in ordered:
        cum += t.pnl_r
        peak = max(peak, cum)
        dd = peak - cum
        curve.append((cum, dd, t))
    return curve


def _maxdd_trough_info(baseline_trades: List[BenchmarkTrade]) -> Dict:
    """Find the trade at the maximum-drawdown trough of the baseline equity
    curve and report the open-exposure context around it."""
    curve = _baseline_equity_curve(baseline_trades)
    if not curve:
        return {}
    # MaxDD = max(dd) and the trade that caused it (last trade at the trough).
    max_dd = max(c[1] for c in curve)
    # Find the trough: the first (or any) trade achieving max_dd
    trough_trade = next(c[2] for c in curve if c[1] == max_dd)
    return {
        "max_dd_r": max_dd,
        "trough_trade_id": trough_trade.trade_id,
        "trough_symbol": trough_trade.symbol,
        "trough_exit_ts": pd_timestamp(trough_trade.exit_timestamp),
        "trough_entry_ts": pd_timestamp(trough_trade.entry_timestamp),
        "trough_pnl_r": trough_trade.pnl_r,
    }


def pd_timestamp(ts) -> str:
    try:
        return str(ts)
    except Exception:
        return "?"


# ═════════════════════════════════════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        description="C2 MaxDD Experiment D: Open Exposure / Total-Risk Cap"
    )
    parser.add_argument("symbols", nargs="*", help="Symbols (default: 6 majors)")
    parser.add_argument("--dry-run", action="store_true", help="Smoke test (2000 bars)")
    parser.add_argument(
        "--max-exposure",
        type=float,
        default=3.0,
        help="Max open R exposure (default: 3.0 = 3R)",
    )
    parser.add_argument(
        "--starting-balance",
        type=float,
        default=STARTING_BALANCE_R,
        help=f"Starting balance in R for DD% (default: {STARTING_BALANCE_R})",
    )
    parser.add_argument(
        "--synth-only",
        action="store_true",
        help="Run synthetic invariant tests only and exit",
    )
    args = parser.parse_args()

    # ── PART A: synthetic invariants ────────────────────────────────────
    synth_ok = synthetic_invariants()
    if args.synth_only:
        return 0 if synth_ok else 1

    SIX_MAJORS = ["EURUSD", "GBPUSD", "GBPJPY", "USDJPY", "AUDUSD", "USDCAD"]
    symbols = [s.upper() for s in args.symbols] if args.symbols else SIX_MAJORS

    # ── PART B: full run ─────────────────────────────────────────────────
    print()
    print("=" * 72)
    print("PART B -- FULL 2.7Y / 6-MAJOR RUN")
    print("=" * 72)
    print("=== C2 MaxDD EXPERIMENT D -- Open Exposure / Total-Risk Cap ===")
    print(
        f"MaxExposure={args.max_exposure}R | Symbols: {symbols} | "
        f"{'DRY RUN' if args.dry_run else 'FULL 2.7Y'}"
    )
    print(f"INITIAL_RISK_R per trade = {INITIAL_RISK_R} (C2 engine normalisation)")

    base_trades = _load_all_trades(symbols, args.dry_run)
    base_stats = compute_stats(base_trades, starting_balance=args.starting_balance)

    # Apply the cap overlay
    capped_trades, blocked_trades, overlay_stats = apply_open_exposure_cap(
        base_trades, max_exposure_r=args.max_exposure
    )
    capped_stats = compute_stats(capped_trades, starting_balance=args.starting_balance)

    print()
    print("=== C2 BASELINE vs C2 + Open Exposure Cap={}R ===".format(args.max_exposure))
    print(f"{'Metric':<22} {'Baseline':>14} {'ExpD':>14}")
    print("-" * 52)
    print(f"{'Trades':<22} {base_stats['trades']:>14d} {capped_stats['trades']:>14d}")
    print(f"{'Blocked':<22} {0:>14d} {int(overlay_stats['blocked_count']):>14d}")
    print(f"{'WinRate%':<22} {base_stats['win_rate']:>13.2f} {capped_stats['win_rate']:>13.2f}")
    print(f"{'TotalR':<22} {base_stats['total_pnl']:>14.2f} {capped_stats['total_pnl']:>14.2f}")
    print(f"{'AvgR':<22} {base_stats['avg_r']:>14.4f} {capped_stats['avg_r']:>14.4f}")
    print(f"{'PF':<22} {base_stats['profit_factor']:>14.2f} {capped_stats['profit_factor']:>14.2f}")
    print(f"{'MaxDD(R)':<22} {base_stats['max_dd']:>14.2f} {capped_stats['max_dd']:>14.2f}")
    print(f"{'MaxDD(%)':<22} {base_stats['max_dd_pct']:>13.2f} {capped_stats['max_dd_pct']:>13.2f}")
    print()
    print(f"Max concurrent open count : {int(overlay_stats['max_open_count'])}")
    print(f"Max concurrent open R     : {overlay_stats['max_open_r']:.2f}R")
    print(
        f"Cap ({args.max_exposure}R) ever binding?  : "
        f"{'YES' if overlay_stats['max_open_r'] >= args.max_exposure else 'NO'}"
    )
    print(f"Blocked by cap            : {int(overlay_stats['blocked_count'])}")

    # ── MaxDD-episode binding analysis ───────────────────────────────────
    print()
    print("=" * 72)
    print("MaxDD-EPISODE BINDING ANALYSIS")
    print("=" * 72)
    trough = _maxdd_trough_info(base_trades)
    if trough:
        print(f"Baseline MaxDD(R)         : {trough['max_dd_r']:.2f}R")
        print(
            f"Trough trade              : id={trough['trough_trade_id']} "
            f"sym={trough['trough_symbol']} pnl={trough['trough_pnl_r']:.2f}R"
        )
        # At the trough trade's entry, what was the open exposure (in the
        # capped replay)? The trough trade is a baseline trade; if it was
        # ACCEPTED in the cap replay, its open-exposure-at-entry is known
        # from the overlay. If it was BLOCKED, it didn't contribute.
        capped_ids = {t.trade_id for t in capped_trades}
        if trough["trough_trade_id"] in capped_ids:
            # Recompute exposure-at-entry for the trough trade by re-walking.
            # Get the actual Timestamp from the trough trade object (the dict
            # stored a string for display). Find the trough trade in base_trades.
            trough_trade_obj = next(
                (t for t in base_trades if t.trade_id == trough["trough_trade_id"]),
                None,
            )
            if trough_trade_obj is not None:
                entry_ts = trough_trade_obj.entry_timestamp
                open_at_trough = sum(
                    1
                    for t in capped_trades
                    if t.entry_timestamp < entry_ts and t.exit_timestamp > entry_ts
                )
                open_r = open_at_trough * INITIAL_RISK_R
                print(f"Open exposure AT trough entry : {open_at_trough} trades = {open_r:.2f}R")
                print(
                    f"Cap ({args.max_exposure}R) binding at MaxDD entry? : "
                    f"{'YES' if open_r + INITIAL_RISK_R > args.max_exposure else 'NO'}"
                )
        else:
            print("Trough trade was BLOCKED by the cap (not in capped set).")
        # Was the cap EVER binding in the entire run?
        ever_binding = overlay_stats["max_open_r"] >= args.max_exposure
        print(
            f"Cap EVER reached in 2.7Y?      : {'YES' if ever_binding else 'NO'} "
            f"(max_open_r={overlay_stats['max_open_r']:.2f}R)"
        )
    else:
        print("  (no completed trades)")

    # ── Blocked-trade distribution (if any) ─────────────────────────────
    if blocked_trades:
        print()
        print("=" * 72)
        print("BLOCKED-TRADE DISTRIBUTION")
        print("=" * 72)
        from collections import Counter

        sym_counts = Counter(t.symbol for t in blocked_trades)
        for sym, n in sym_counts.most_common():
            print(f"  {sym}: {n}")
        # Direction breakdown
        dir_counts = Counter(getattr(t, "direction", "?") for t in blocked_trades)
        for d, n in dir_counts.items():
            print(f"  direction {d}: {n}")
        # How many blocked trades' hypothetical pnl would have been a loss
        losses_blocked = sum(1 for t in blocked_trades if getattr(t, "result", "") == "LOSS")
        wins_blocked = sum(
            1 for t in blocked_trades if getattr(t, "result", "") in ("TP", "PROFIT_TRAIL")
        )
        print(f"  would-be LOSS blocked     : {losses_blocked}")
        print(f"  would-be WIN blocked      : {wins_blocked}")
    else:
        print()
        print("Blocked-trade distribution: NONE (cap never binding).")

    # ── Persist ──────────────────────────────────────────────────────────
    out_dir = _PROJECT_ROOT / "results" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "expD_open_exposure_cap_trades.json", "w") as f:
        json.dump([t.__dict__ for t in capped_trades], f, indent=2, default=str)
    with open(out_dir / "expD_open_exposure_cap_blocked.json", "w") as f:
        json.dump([t.__dict__ for t in blocked_trades], f, indent=2, default=str)
    summary = {
        "baseline": base_stats,
        "capped": capped_stats,
        "max_exposure_r": args.max_exposure,
        "initial_risk_r": INITIAL_RISK_R,
        "overlay_stats": overlay_stats,
        "blocked_count": int(overlay_stats["blocked_count"]),
        "maxdd_trough": trough,
        "cap_ever_binding": bool(overlay_stats["max_open_r"] >= args.max_exposure),
        "synthetic_invariants": "ALL PASS" if synth_ok else "FAIL",
        "engine_untouched": True,
    }
    with open(out_dir / "expD_open_exposure_cap_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nResults saved to {out_dir}")

    return 0 if synth_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
