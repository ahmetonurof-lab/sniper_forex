"""
exp_maxdd_A_concurrent_cap.py — Experiment A: C2 MaxDD research

Isolates ONE variable: Concurrent Exposure Cap = 3.

Methodology
-----------
- Baseline = the untouched C2 engine (main_research_c_v1_0.run_test_a) over the
  same 6 majors / 2.7Y 15m dataset.
- The cap is applied as a POST-HOC portfolio overlay on the baseline trade
  stream. This leaves the C2 engine 100% untouched (EQ formula, FVG logic,
  entry/SL/TP, 1.8R trailing are all unchanged inside main_research_c_v1_0.py).

Rule (per spec)
--------------
Before a new trade is opened, if the count of currently-open positions
(closed trades excluded) >= cap, the new entry is SKIPPED.

The overlay replays the aggregated trade stream in entry-time order and
enforces the global cap. main_research_c_v1_0 is imported only; never modified.

Run:
    python experiment/exp_maxdd_A_concurrent_cap.py
    python experiment/exp_maxdd_A_concurrent_cap.py --max-parallel 3
    python experiment/exp_maxdd_A_concurrent_cap.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Tuple

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ── Import the canonical, UNTOUCHED C2 engine ──
from experiment.main_research_c_v1_0 import (  # noqa: E402
    STARTING_BALANCE_R,
    BenchmarkTrade,
    compute_stats,
    run_test_a,
)


# ── Concurrent Exposure Cap overlay (the ONLY new variable) ──
def apply_concurrency_cap(
    trades: List[BenchmarkTrade], cap: int = 3
) -> Tuple[List[BenchmarkTrade], int]:
    """Replay the trade stream in entry-time order and enforce a global
    concurrent-exposure cap. If currently-open positions >= cap at the moment
    of a new entry, that entry is SKIPPED. Engine logic is untouched."""
    ordered = sorted(trades, key=lambda t: t.entry_timestamp)
    open_exits: List[float] = []
    kept: List[BenchmarkTrade] = []
    blocked = 0
    for t in ordered:
        open_exits = [e for e in open_exits if e > t.entry_timestamp]
        if len(open_exits) >= cap:
            blocked += 1
            continue
        kept.append(t)
        open_exits.append(t.exit_timestamp)
    return kept, blocked


def _load_symbol_trades(symbol: str, dry_run: bool) -> List[BenchmarkTrade]:
    """Run the UNTOUCHED C2 engine (run_test_a) for one symbol, then attach
    entry_timestamp from the bars (the engine does not expose it). The engine
    code itself is never modified — we only enrich the returned records."""
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
    # Attach entry timestamp from the entry bar (engine untouched).
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


def main():
    parser = argparse.ArgumentParser(description="C2 MaxDD Experiment A: Concurrent Exposure Cap")
    parser.add_argument("symbols", nargs="*", help="Symbols (default: all 6 majors)")
    parser.add_argument("--dry-run", action="store_true", help="Smoke test (2000 bars)")
    parser.add_argument(
        "--max-parallel",
        type=int,
        default=3,
        help="Concurrent exposure cap (default: 3). Use 0 to disable (=baseline).",
    )
    parser.add_argument(
        "--starting-balance",
        type=float,
        default=STARTING_BALANCE_R,
        help=f"Starting balance in R for DD% (default: {STARTING_BALANCE_R})",
    )
    args = parser.parse_args()

    SIX_MAJORS = ["EURUSD", "GBPUSD", "GBPJPY", "USDJPY", "AUDUSD", "USDCAD"]
    symbols = [s.upper() for s in args.symbols] if args.symbols else SIX_MAJORS

    print("=== C2 MaxDD EXPERIMENT A — Concurrent Exposure Cap ===")
    print(
        f"Symbols: {symbols} | MaxParallel: {args.max_parallel} | "
        f"{'DRY RUN' if args.dry_run else 'FULL 2.7Y'}"
    )

    # Baseline = untouched C2 engine output
    base_trades = _load_all_trades(symbols, args.dry_run)
    base_stats = compute_stats(base_trades, starting_balance=args.starting_balance)

    # Cap overlay (isolated variable)
    capped_trades, blocked = apply_concurrency_cap(base_trades, cap=args.max_parallel)
    capped_stats = compute_stats(capped_trades, starting_balance=args.starting_balance)

    print("\n=== C2 BASELINE vs C2 + MaxParallel=%d ===" % args.max_parallel)
    print(f"{'Metric':<14} {'Baseline':>12} {'Cap=%d' % args.max_parallel:>12}")
    print("-" * 40)
    print(f"{'Trades':<14} {base_stats['trades']:>12d} {capped_stats['trades']:>12d}")
    print(f"{'WinRate%':<14} {base_stats['win_rate']:>11.2f} {capped_stats['win_rate']:>11.2f}")
    print(f"{'TotalR':<14} {base_stats['total_pnl']:>12.2f} {capped_stats['total_pnl']:>12.2f}")
    print(f"{'AvgR':<14} {base_stats['avg_r']:>12.4f} {capped_stats['avg_r']:>12.4f}")
    print(f"{'PF':<14} {base_stats['profit_factor']:>12.2f} {capped_stats['profit_factor']:>12.2f}")
    print(f"{'MaxDD(R)':<14} {base_stats['max_dd']:>12.2f} {capped_stats['max_dd']:>12.2f}")
    print(f"{'MaxDD(%)':<14} {base_stats['max_dd_pct']:>12.2f} {capped_stats['max_dd_pct']:>12.2f}")
    print(f"{'Blocked':<14} {0:>12d} {blocked:>12d}")

    # Persist
    out_dir = _PROJECT_ROOT / "results" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "expA_concurrent_cap_trades.json", "w") as f:
        json.dump([t.__dict__ for t in capped_trades], f, indent=2, default=str)
    summary = {
        "baseline": base_stats,
        "capped_maxparallel": args.max_parallel,
        "capped": capped_stats,
        "blocked_entries": blocked,
    }
    with open(out_dir / "expA_concurrent_cap_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nResults saved to {out_dir}")


if __name__ == "__main__":
    main()
