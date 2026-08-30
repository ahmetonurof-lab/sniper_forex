"""
exp_maxdd_B_streak_breaker.py — Experiment B: C2 + 3-Loss Circuit Breaker

Isolates ONE variable: a 3-consecutive-LOSS circuit breaker.

Methodology
-----------
- Baseline = the UNTOUCHED C2 engine (main_research_c_v1_0.run_test_a) over the
  same 6 majors / 2.7Y 15m dataset.
- The breaker is a POST-HOC per-symbol overlay on the baseline trade stream.
  EQ formula, FVG logic, entry/SL/TP, 1.8R trailing and the engine in
  main_research_c_v1_0.py are 100% untouched (imported only).

Rule (per spec / corrected)
---------------------------
- Only CLOSED trades count toward the loss streak.
- The loss streak is evaluated on the CLOSE (exit) time line, NOT the entry line.
- When the 3rd consecutive closed LOSS occurs (at bar index L_exit, exit_time T),
  the breaker activates: entries whose entry_bar_index falls in
  (L_exit, L_exit + 12] (i.e. the 12 bars AFTER the 3rd loss closed) are SKIPPED.
- The 3rd loss trade itself is NOT blocked (it already happened).
- Open (unclosed) trades are NEVER closed by the breaker.
- While the breaker is active, blocked baseline trades are EXCLUDED from the
  loss-streak / equity accounting entirely (they never happened).
- The breaker can re-trigger if a new 3-loss streak forms AFTER the previous
  pause window ends.

NO Lookahead (invariant)
------------------------
The replay walks events on the bar timeline. Events:
  - CLSE(t): a trade closes at bar t (its exit_bar_index = t). Its result is
    known ONLY at exit -> contributes to streak from that point onward.
  - ENTRY(t): a trade intends to enter at bar t (entry_bar_index = t+1, since the
    engine uses next-bar-open execution; entry bar = i+1).
We process bars in increasing order within a symbol. At each bar we:
  (1) close any trade whose exit_bar_index == bar,
  (2) then test new-entry acceptance for trades whose entry_bar_index == bar.
Because closures at bar t are processed before the entry test at bar t+1, and
entry_bar_index = i+1 (next bar), a trade only sees closures that already
happened (exit_bar_index <= entry_bar_index - 1). No future info is used.
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

from experiment.main_research_c_v1_0 import (  # noqa: E402
    STARTING_BALANCE_R,
    BenchmarkTrade,
    compute_stats,
    run_test_a,
)

LOSS_STREAK = 3
PAUSE_BARS = 12


def apply_streak_breaker(
    trades: List[BenchmarkTrade],
    loss_streak: int = LOSS_STREAK,
    pause_bars: int = PAUSE_BARS,
) -> Tuple[List[BenchmarkTrade], int, int, int]:
    """Per-symbol replay enforcing the 3-loss / 12-bar breaker (NO lookahead).

    Returns: (kept_trades, blocked, triggers, total_pause_bars).

    Causal invariant (critical):
      - A trade is ACCEPTED only if its ENTRY event passes the pause test.
      - A trade that is BLOCKED at ENTRY is treated as if it never happened:
        its EXIT event must NEVER drive the loss streak.
      - Only ACCEPTED trades' closures are counted toward the streak
        (tracked via the `accepted` set).
      - OPEN (unclosed) tail trades are appended exactly once after the loop;
        they are NOT in the event stream, so they cannot affect the streak.
    """
    closed = [t for t in trades if t.result in ("TP", "PROFIT_TRAIL", "LOSS")]
    open_tail = [t for t in trades if t.result == "OPEN"]

    # Build the event stream from CLOSED trades only. OPEN tail trades are
    # handled separately (appended once after the loop) and never enter the
    # stream, so they cannot duplicate or affect the streak.
    events = []  # (bar_index, kind, trade)   kind in {ENTRY, EXIT}
    for t in closed:
        events.append((t.entry_bar_index, "ENTRY", t))
        events.append((t.exit_bar_index, "EXIT", t))

    # At the SAME bar, process EXITS before ENTRY tests (causal ordering).
    events.sort(key=lambda e: (e[0], 0 if e[1] == "EXIT" else 1))

    accepted: set = set()  # trade_ids of trades actually ACCEPTED at ENTRY
    consecutive_losses = 0
    pause_until_bar = -1  # entries with entry_bar_index <= pause_until_bar blocked
    triggers = 0
    total_pause_bars = 0
    kept: List[BenchmarkTrade] = []
    blocked = 0

    for bar_idx, kind, t in events:
        if kind == "EXIT":
            # Only ACCEPTED trades' closures drive the streak. A BLOCKED trade
            # is excluded from the streak in every condition.
            if t.trade_id in accepted:
                if t.result == "LOSS":
                    consecutive_losses += 1
                elif t.result in ("TP", "PROFIT_TRAIL"):
                    consecutive_losses = 0
                # Trigger exactly when the 3rd consecutive accepted LOSS closes.
                if consecutive_losses == loss_streak:
                    pause_until_bar = t.exit_bar_index + pause_bars
                    triggers += 1
                    total_pause_bars += pause_bars
                    consecutive_losses = 0  # reset so it can re-trigger
        else:  # ENTRY
            # Accept/reject based on the current pause window, which is derived
            # ONLY from already-closed ACCEPTED trades (NO lookahead).
            if pause_until_bar >= 0 and t.entry_bar_index <= pause_until_bar:
                blocked += 1
                continue  # blocked -> never accepted, never affects streak
            if pause_until_bar >= 0 and t.entry_bar_index > pause_until_bar:
                pause_until_bar = -1
            accepted.add(t.trade_id)
            kept.append(t)

    # OPEN tail trades: accepted as-is, appended EXACTLY ONCE (not in stream).
    kept.extend(open_tail)
    return kept, blocked, triggers, total_pause_bars


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
    return run_test_a(symbol, bars_15m)


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
    parser = argparse.ArgumentParser(
        description="C2 MaxDD Experiment B: 3-Loss / 12-bar Circuit Breaker"
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

    print("=== C2 MaxDD EXPERIMENT B (corrected) — 3-Loss / 12-bar Breaker ===")
    print("Rule: 3 consecutive CLOSED losses -> pause entries 12 bars (from L_exit).")
    print(f"Symbols: {symbols} | {'DRY RUN' if args.dry_run else 'FULL 2.7Y'}")

    base_trades = _load_all_trades(symbols, args.dry_run)
    base_stats = compute_stats(base_trades, starting_balance=args.starting_balance)

    # Per-symbol breaker replay (engine untouched).
    breaker_trades: List[BenchmarkTrade] = []
    per_sym = {}
    total_blocked = 0
    total_triggers = 0
    total_pause_bars = 0
    for sym in symbols:
        sym_trades = [t for t in base_trades if t.symbol == sym]
        kept, blocked, triggers, pause_bars = apply_streak_breaker(sym_trades)
        breaker_trades.extend(kept)
        total_blocked += blocked
        total_triggers += triggers
        total_pause_bars += pause_bars
        per_sym[sym] = {
            "kept": len(kept),
            "blocked": blocked,
            "triggers": triggers,
            "pause_bars": pause_bars,
        }

    breaker_stats = compute_stats(breaker_trades, starting_balance=args.starting_balance)

    print("\n=== C2 BASELINE vs C2 + 3L/12bar Breaker (corrected) ===")
    print(f"{'Metric':<14} {'Baseline':>12} {'Breaker':>12}")
    print("-" * 40)
    print(f"{'Trades':<14} {base_stats['trades']:>12d} {breaker_stats['trades']:>12d}")
    print(f"{'Blocked':<14} {0:>12d} {total_blocked:>12d}")
    print(f"{'WinRate%':<14} {base_stats['win_rate']:>11.2f} {breaker_stats['win_rate']:>11.2f}")
    print(f"{'TotalR':<14} {base_stats['total_pnl']:>12.2f} {breaker_stats['total_pnl']:>12.2f}")
    print(f"{'AvgR':<14} {base_stats['avg_r']:>12.4f} {breaker_stats['avg_r']:>12.4f}")
    print(
        f"{'PF':<14} {base_stats['profit_factor']:>12.2f} {breaker_stats['profit_factor']:>12.2f}"
    )
    print(f"{'MaxDD(R)':<14} {base_stats['max_dd']:>12.2f} {breaker_stats['max_dd']:>12.2f}")
    print(
        f"{'MaxDD(%)':<14} {base_stats['max_dd_pct']:>12.2f} {breaker_stats['max_dd_pct']:>12.2f}"
    )
    print(f"{'Triggers':<14} {0:>12d} {total_triggers:>12d}")
    print(f"{'PauseBars':<14} {0:>12d} {total_pause_bars:>12d}")

    print("\n--- Per-symbol breaker ---")
    print(f"{'Symbol':<12} {'Kept':>6} {'Blocked':>8} {'Trig':>6} {'PauseBars':>10}")
    print("-" * 44)
    for sym in sorted(per_sym):
        d = per_sym[sym]
        print(
            f"{sym:<12} {d['kept']:>6d} {d['blocked']:>8d} {d['triggers']:>6d} {d['pause_bars']:>10d}"
        )

    out_dir = _PROJECT_ROOT / "results" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "expB_streak_breaker_trades.json", "w") as f:
        json.dump([t.__dict__ for t in breaker_trades], f, indent=2, default=str)
    summary = {
        "baseline": base_stats,
        "breaker": breaker_stats,
        "blocked_entries": total_blocked,
        "triggers": total_triggers,
        "total_pause_bars": total_pause_bars,
        "per_symbol": per_sym,
        "params": {"loss_streak": LOSS_STREAK, "pause_bars": PAUSE_BARS},
        "lookahead_free": True,
    }
    with open(out_dir / "expB_streak_breaker_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nResults saved to {out_dir}")


if __name__ == "__main__":
    main()
