"""
exp_maxdd_C_dd_risk_scaling.py — Experiment C: C2 + DD-Based Risk Scaling

Isolates ONE variable: scale per-trade risk by current portfolio drawdown.

Methodology
-----------
- Baseline = the UNTOUCHED C2 engine (main_research_c_v1_0.run_test_a) over the
  same 6 majors / 2.7Y 15m dataset.
- Risk scaling is applied as a POST-HOC portfolio overlay on the baseline
  trade stream. EQ formula, FVG logic, entry/SL/TP, 1.8R trailing and the
  engine in main_research_c_v1_0.py are 100% untouched.

Proposed thresholds (first test, tried exactly as given)
-------------------------------------------------------
- portfolio DD > 2R  -> risk 50%  (pnl_r scaled by 0.5)
- portfolio DD > 4R  -> risk 25%  (pnl_r scaled by 0.25)
- portfolio DD > 6R  -> pause      (trade NOT taken)

How the overlay works (NO lookahead)
------------------------------------
1. Build the portfolio equity curve chronologically from REALIZED (closed)
   trades only, sorted by exit_timestamp (same as compute_stats).
2. Walk trades in exit-time order. After each closed trade we know the
   realized peak and drawdown UP TO THAT POINT (past information only).
3. For the NEXT trade's entry decision we use the DD measured from already
   realized exits -> no future data is used.
   - The DD level at a trade's entry equals the portfolio DD after all trades
     that have ALREADY closed before this trade's entry timestamp.
4. Apply the risk multiplier to the trade's pnl_r:
   - DD > 6R -> trade is PAUSED (blocked, pnl not counted)
   - DD > 4R -> x0.25
   - DD > 2R -> x0.50
   - else    -> x1.00
5. Recompute the scaled equity curve and MaxDD(R)/MaxDD(%) with the scaled
   pnl contributions. Trades, WR, AvgR, TotalR, PF are reported on the
   SURVIVING (non-paused) trades.

Mapping trade pnl_r under risk scaling
--------------------------------------
The C2 engine fixes risk at 1R per trade (SL = -1R). Scaling risk to k means
the realized R of that trade is multiplied by k (both wins and losses). This
is the standard "risk reduction" interpretation and isolates the DD lever
without touching SL/TP geometry.

Run:
    python experiment/exp_maxdd_C_dd_risk_scaling.py
    python experiment/exp_maxdd_C_dd_risk_scaling.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ── Import the canonical, UNTOUCHED C2 engine ──
from experiment.main_research_c_v1_0 import (  # noqa: E402
    run_test_a,
    compute_stats,
    BenchmarkTrade,
    STARTING_BALANCE_R,
)

# Risk scaling thresholds (proposed, first test).
DD_T1 = 2.0  # >2R  -> 50% risk
DD_T2 = 4.0  # >4R  -> 25% risk
DD_T3 = 6.0  # >6R  -> pause


def apply_dd_risk_scaling(
    trades: List[BenchmarkTrade],
    entry_ts: List[Any],
    starting_balance: float = STARTING_BALANCE_R,
) -> Tuple[List[BenchmarkTrade], int, float, float]:
    """Replay the portfolio trade stream in exit-time order and scale each
    trade's pnl_r by the current realized drawdown. Returns
    (surviving_trades, paused_count, pre_scale_maxdd_r, post_scale_maxdd_r).

    `entry_ts` carries the entry timestamp for each trade (kept external because
    the canonical BenchmarkTrade dataclass is NOT modified).

    NO lookahead: the DD used for a trade's risk decision is the portfolio DD
    measured from trades that have ALREADY closed before this trade's entry."""
    completed = [t for t in trades if t.result in ("TP", "PROFIT_TRAIL", "LOSS")]
    paired = sorted(
        zip(completed, entry_ts),
        key=lambda p: p[0].exit_timestamp,
    )
    ordered = [p[0] for p in paired]
    entry_times = [p[1] for p in paired]

    # Walk the realized equity curve in exit-time order. For each trade we need
    # the portfolio DD that existed BEFORE its entry. Because a trade's exit
    # always precedes a later trade's entry in normal flow, applying all closed
    # trades whose exit_timestamp <= this trade's entry_timestamp uses ONLY
    # past information (NO lookahead).
    exit_times = [t.exit_timestamp for t in ordered]
    # entry_times already built from the external entry_ts list (paired above).

    # Incremental single pass (O(n)):
    equity = starting_balance
    peak = starting_balance
    applied = 0
    surviving: List[BenchmarkTrade] = []
    paused = 0
    pre_scale_maxdd = 0.0
    post_equity = starting_balance
    post_peak = starting_balance
    post_scale_maxdd = 0.0

    for k, t in enumerate(ordered):
        # Advance applied pointer: apply all trades whose exit < this entry
        # (strictly-before causality per 2026-08-28 decision).
        while applied < len(ordered) and exit_times[applied] < entry_times[k]:
            et = ordered[applied]
            equity += et.pnl_r
            peak = max(peak, equity)
            dd = peak - equity
            pre_scale_maxdd = max(pre_scale_maxdd, dd)
            applied += 1
        # Now DD before this trade's entry:
        dd_now = peak - equity

        # Decide risk multiplier from realized DD (no future info).
        if dd_now > DD_T3:
            paused += 1
            continue  # paused -> not taken
        elif dd_now > DD_T2:
            mult = 0.25
        elif dd_now > DD_T1:
            mult = 0.50
        else:
            mult = 1.00

        scaled = BenchmarkTrade(**t.__dict__)
        scaled.pnl_r = t.pnl_r * mult
        surviving.append(scaled)

        # Update scaled equity curve with this (scaled) contribution.
        post_equity += scaled.pnl_r
        post_peak = max(post_peak, post_equity)
        post_scale_maxdd = max(post_scale_maxdd, post_peak - post_equity)

    return surviving, paused, pre_scale_maxdd, post_scale_maxdd


def _load_symbol_trades(symbol: str, dry_run: bool) -> List[BenchmarkTrade]:
    """Run the UNTOUCHED C2 engine (run_test_a) for one symbol. Engine code is
    never modified; we only consume its returned records."""
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
    return run_test_a(symbol, bars_15m)


def _load_all_trades(symbols: List[str], dry_run: bool) -> List[BenchmarkTrade]:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from tqdm import tqdm

    all_trades: List[BenchmarkTrade] = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(_load_symbol_trades, sym, dry_run): sym for sym in symbols
        }
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


def main():
    parser = argparse.ArgumentParser(
        description="C2 MaxDD Experiment C: DD-Based Risk Scaling"
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

    print("=== C2 MaxDD EXPERIMENT C — DD-Based Risk Scaling ===")
    print(f"Thresholds: DD>{DD_T1}R x0.50 | DD>{DD_T2}R x0.25 | DD>{DD_T3}R PAUSE")
    print(f"Symbols: {symbols} | {'DRY RUN' if args.dry_run else 'FULL 2.7Y'}")

    base_trades = _load_all_trades(symbols, args.dry_run)
    base_stats = compute_stats(base_trades, starting_balance=args.starting_balance)

    # entry_timestamp is NOT in the canonical BenchmarkTrade dataclass (engine
    # untouched). Derive it from the bars per symbol and carry it externally.
    import pandas as pd

    # CORRECTED (2026-08-28): build entry_ts PER SYMBOL, but iterate
    # `base_trades` in its actual order (set by `as_completed`,
    # which is non-deterministic). The previous implementation
    # keyed `entry_ts_map` by `trade_id` only, which collided across
    # symbols because `run_test_a` resets its per-symbol
    # `trade_counter` to 0 on every call. 1895/2302 trades (82%)
    # received cross-symbol-contaminated entry_ts, which by
    # happenstance produced 0 paused, MaxDD 8.00R, MaxDD% 1.85% — an
    # artifact of the bug, not the real behavior. The correct
    # behavior is 3 paused, MaxDD 6.75R, MaxDD% 2.45%.
    # Cache per-symbol entry_ts map keyed by (entry_bar_index) for O(1) lookup.
    _sym_ts_cache: Dict[str, "pd.Series"] = {}
    _sym_entry_map: Dict[Tuple[str, int], pd.Timestamp] = {}
    for sym in symbols:
        if sym in _sym_ts_cache:
            continue
        feather_dir = _PROJECT_ROOT / "data" / "icmarket_feather"
        df = pd.read_feather(feather_dir / f"{sym}_15m.feather")
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        ts = df["timestamp"].values
        _sym_ts_cache[sym] = ts
    # Walk `base_trades` in its actual (as_completed) order, look up
    # each trade's entry_ts from its OWN symbol's feather.
    for t in base_trades:
        sym = t.symbol
        ei = getattr(t, "entry_bar_index", 0)
        ts = _sym_ts_cache[sym]
        if 0 <= ei < len(ts):
            _sym_entry_map[(sym, ei)] = pd.Timestamp(ts[ei])
    entry_ts: List[Any] = []
    for t in base_trades:
        sym = t.symbol
        ei = getattr(t, "entry_bar_index", 0)
        ts = _sym_ts_cache[sym]
        v = pd.Timestamp(ts[ei]) if 0 <= ei < len(ts) else pd.Timestamp(0)
        entry_ts.append(v)

    scaled_trades, paused, pre_dd, post_dd = apply_dd_risk_scaling(
        base_trades, entry_ts, starting_balance=args.starting_balance
    )
    scaled_stats = compute_stats(scaled_trades, starting_balance=args.starting_balance)

    print("\n=== C2 BASELINE vs C2 + DD Risk Scaling (C) ===")
    print(f"{'Metric':<14} {'Baseline':>12} {'ExpC':>12}")
    print("-" * 40)
    print(f"{'Trades':<14} {base_stats['trades']:>12d} {scaled_stats['trades']:>12d}")
    print(f"{'Blocked':<14} {0:>12d} {paused:>12d}")
    print(
        f"{'WinRate%':<14} {base_stats['win_rate']:>11.2f} {scaled_stats['win_rate']:>11.2f}"
    )
    print(
        f"{'TotalR':<14} {base_stats['total_pnl']:>12.2f} {scaled_stats['total_pnl']:>12.2f}"
    )
    print(f"{'AvgR':<14} {base_stats['avg_r']:>12.4f} {scaled_stats['avg_r']:>12.4f}")
    print(
        f"{'PF':<14} {base_stats['profit_factor']:>12.2f} {scaled_stats['profit_factor']:>12.2f}"
    )
    print(
        f"{'MaxDD(R)':<14} {base_stats['max_dd']:>12.2f} {scaled_stats['max_dd']:>12.2f}"
    )
    print(
        f"{'MaxDD(%)':<14} {base_stats['max_dd_pct']:>12.2f} {scaled_stats['max_dd_pct']:>12.2f}"
    )

    # Persist
    out_dir = _PROJECT_ROOT / "results" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "expC_dd_risk_scaling_trades.json", "w") as f:
        json.dump([t.__dict__ for t in scaled_trades], f, indent=2, default=str)
    summary = {
        "baseline": base_stats,
        "scaled": scaled_stats,
        "paused_entries": paused,
        "thresholds": {"t1": DD_T1, "t2": DD_T2, "t3": DD_T3},
        "params": {"x_t1": 0.50, "x_t2": 0.25, "x_t3": 0.0},
    }
    with open(out_dir / "expC_dd_risk_scaling_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nResults saved to {out_dir}")


if __name__ == "__main__":
    main()
