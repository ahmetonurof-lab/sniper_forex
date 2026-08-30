"""
exp_maxdd_F_d_risk_scaling.py — Experiment F: D v1.0 (PURE D EQ) + DD Risk Scaling

Mirror of Experiment C (C2 + DD Risk Scaling) applied to the D engine.

Methodology
-----------
- Baseline = the UNTOUCHED D v1.0 engine (main_research_d_v1_0.run_test_a_pure_d)
  over the same 6 majors / 2.7Y 15m dataset.
- Risk scaling is applied as a POST-HOC portfolio overlay on the baseline
  trade stream. D EQ formula, FVG logic, entry/SL/TP, 1.8R trailing and the
  engine in main_research_d_v1_0.py are 100% untouched.

Thresholds (identical to Experiment C — no tuning)
---------------------------------------------------
- portfolio DD > 2R  -> risk 50%  (pnl_r scaled by 0.5)
- portfolio DD > 4R  -> risk 25%  (pnl_r scaled by 0.25)
- portfolio DD > 6R  -> pause      (trade NOT taken)

Expected D baseline (KNOWN-GOOD FROZEN BENCHMARK):
  2847 trades / +2949.05R / WR 66.1% / PF 4.05 / MaxDD 7.36R / MaxDD% 2.76%

Run:
    python experiment/exp_maxdd_F_d_risk_scaling.py
    python experiment/exp_maxdd_F_d_risk_scaling.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ── Import canonical compute_stats + BenchmarkTrade from C (shared) ──────
from experiment.main_research_c_v1_0 import (  # noqa: E402
    STARTING_BALANCE_R,
    BenchmarkTrade,
    compute_stats,
)

# ── Import D engine-specific runner + pivot builder ──────────────────────
from experiment.main_research_d_v1_0 import (  # noqa: E402
    _build_1h_swing_timeline,
    run_test_a_pure_d,
)
from src.strategy.models import Bar  # noqa: E402

# Risk scaling thresholds (identical to Experiment C — no tuning).
DD_T1 = 2.0  # >2R  -> 50% risk
DD_T2 = 4.0  # >4R  -> 25% risk
DD_T3 = 6.0  # >6R  -> pause

SIX_MAJORS = ["EURUSD", "GBPUSD", "GBPJPY", "USDJPY", "AUDUSD", "USDCAD"]


# ═════════════════════════════════════════════════════════════════════════════
# DD Risk Scaling (identical logic to Experiment C)
# ═════════════════════════════════════════════════════════════════════════════


def apply_dd_risk_scaling(
    trades: List[BenchmarkTrade],
    entry_ts: List[Any],
    starting_balance: float = STARTING_BALANCE_R,
) -> Tuple[List[BenchmarkTrade], int, float, float]:
    """Replay the portfolio trade stream in exit-time order and scale each
    trade's pnl_r by the current realized drawdown. Returns
    (surviving_trades, paused_count, pre_scale_maxdd_r, post_scale_maxdd_r).

    NO lookahead: the DD used for a trade's risk decision is the portfolio DD
    measured from trades that have ALREADY closed before this trade's entry."""
    completed = [t for t in trades if t.result in ("TP", "PROFIT_TRAIL", "LOSS")]
    paired = sorted(
        zip(completed, entry_ts),
        key=lambda p: p[0].exit_timestamp,
    )
    ordered = [p[0] for p in paired]
    entry_times = [p[1] for p in paired]

    exit_times = [t.exit_timestamp for t in ordered]

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
        while applied < len(ordered) and exit_times[applied] <= entry_times[k]:
            et = ordered[applied]
            equity += et.pnl_r
            peak = max(peak, equity)
            dd = peak - equity
            pre_scale_maxdd = max(pre_scale_maxdd, dd)
            applied += 1
        dd_now = peak - equity

        if dd_now > DD_T3:
            paused += 1
            continue
        elif dd_now > DD_T2:
            mult = 0.25
        elif dd_now > DD_T1:
            mult = 0.50
        else:
            mult = 1.00

        scaled = BenchmarkTrade(**t.__dict__)
        scaled.pnl_r = t.pnl_r * mult
        surviving.append(scaled)

        post_equity += scaled.pnl_r
        post_peak = max(post_peak, post_equity)
        post_scale_maxdd = max(post_scale_maxdd, post_peak - post_equity)

    return surviving, paused, pre_scale_maxdd, post_scale_maxdd


# ═════════════════════════════════════════════════════════════════════════════
# Synthetic boundary tests
# ═════════════════════════════════════════════════════════════════════════════


def _run_synthetic_tests() -> bool:
    """Verify risk-scaling thresholds with synthetic trades.

    CRITICAL: exit_timestamp of trade k must be BEFORE entry_timestamp of
    trade k+1, otherwise the overlay cannot "see" the realized DD when
    making the next trade's decision.
    """
    from datetime import datetime, timedelta

    print("=" * 72)
    print("PART A -- SYNTHETIC DD RISK SCALING TESTS")
    print("=" * 72)
    all_pass = True

    # ── Scenario 1: 5 consecutive losses ────────────────────────────────
    # Entry every 72h, hold 24h → exit 24h after entry (before next entry).
    # T0: entry=0h, exit=24h, pnl=-1.0 → after close DD=1R
    # T1: entry=72h, exit=96h, pnl=-1.0 → DD=1.0 (from T0 only) → x1.00
    # T2: entry=144h, exit=168h, pnl=-1.0 → DD=2.0 → x0.50
    # T3: entry=216h, exit=240h, pnl=-1.0 → DD=2.5 → x0.50
    # T4: entry=288h, exit=312h, pnl=-1.0 → DD=3.0 → x0.50
    # Expected: 5 survive, 0 paused, total=-3.5R
    base_ts = datetime(2024, 6, 1, 0, 0)
    trades1 = []
    entry1 = []
    for i in range(5):
        entry_t = base_ts + timedelta(hours=i * 72)
        exit_t = entry_t + timedelta(hours=24)
        t = BenchmarkTrade(
            trade_id=i,
            symbol="EURUSD",
            test_type="D",
            direction="bullish",
            entry_price=1.1,
            sl=1.09,
            tp=1.118,
            entry_bar_index=i * 100,
            sweep_bar_index=0,
            zone_index=0,
            zone_creation_bar=0,
            zone_top=1.105,
            zone_bottom=1.1,
            zone_size=0.005,
            zone_size_atr=0.5,
            sweep_size_atr=0.3,
            bars_sweep_to_zone=5,
            bars_zone_to_entry=2,
            exit_price=1.09,
            exit_bar_index=i * 100 + 10,
            exit_timestamp=exit_t,
            result="LOSS",
            pnl_r=-1.0,
            trailing_count=0,
            max_favorable=0.0,
            max_adverse=1.0,
            hold_bars=10,
        )
        trades1.append(t)
        entry1.append(entry_t)

    s1, p1, pre1, post1 = apply_dd_risk_scaling(trades1, entry1, starting_balance=100.0)
    total_r1 = sum(t.pnl_r for t in s1)
    # Trace: strict > means DD=2.0R does NOT trigger x0.50.
    # T0: DD=0 → x1.00 (-1.0), T1: DD=1R → x1.00 (-1.0),
    # T2: DD=2R (not >2) → x1.00 (-1.0), T3: DD=3R → x0.50 (-0.5),
    # T4: DD=3.5R → x0.50 (-0.5). Total = -4.0R.
    tests = [
        ("5 losses: 5 survive (DD never >6R)", len(s1) == 5),
        ("5 losses: 0 paused", p1 == 0),
        (
            "5 losses: total pnl = -4.0R (strict > threshold)",
            abs(total_r1 - (-4.0)) < 0.01,
        ),
        ("5 losses: pre-scale MaxDD = 4.0R", abs(pre1 - 4.0) < 0.01),
    ]

    # ── Scenario 2: 8 consecutive losses → DD>6R → pauses ───────────────
    # T0: x1.00 (-1.0), T1: x1.00 (-1.0), T2: x1.00 (-1.0, DD=2R not >2)
    # T3: x0.50 (-0.5, DD=3R>2), T4: x0.50 (-0.5, DD=3.5R)
    # T5: x0.25 (-0.25, DD=4.5R>4), T6: x0.25 (-0.25, DD=5.5R>4 but not >6)
    # T7: PAUSE (DD=6.5R>6)
    trades2 = []
    entry2 = []
    for i in range(8):
        entry_t = base_ts + timedelta(hours=i * 72)
        exit_t = entry_t + timedelta(hours=24)
        t = BenchmarkTrade(
            trade_id=100 + i,
            symbol="EURUSD",
            test_type="D",
            direction="bullish",
            entry_price=1.1,
            sl=1.09,
            tp=1.118,
            entry_bar_index=i * 100,
            sweep_bar_index=0,
            zone_index=0,
            zone_creation_bar=0,
            zone_top=1.105,
            zone_bottom=1.1,
            zone_size=0.005,
            zone_size_atr=0.5,
            sweep_size_atr=0.3,
            bars_sweep_to_zone=5,
            bars_zone_to_entry=2,
            exit_price=1.09,
            exit_bar_index=i * 100 + 10,
            exit_timestamp=exit_t,
            result="LOSS",
            pnl_r=-1.0,
            trailing_count=0,
            max_favorable=0.0,
            max_adverse=1.0,
            hold_bars=10,
        )
        trades2.append(t)
        entry2.append(entry_t)

    s2, p2, pre2, post2 = apply_dd_risk_scaling(trades2, entry2, starting_balance=100.0)
    tests.append(("8 losses: 1 paused (DD>6R only at T7)", p2 == 1))
    tests.append(("8 losses: 7 trades survive", len(s2) == 7))

    # ── Scenario 3: mixed wins/losses ────────────────────────────────────
    # T0: win +1.0 → equity 101, peak 101, DD=0
    # T1: loss -1.0 → equity 100, peak 101, DD=1 → x1.00
    # T2: loss -1.0 → equity 99, peak 101, DD=2 → x1.00 (not >2)
    # T3: loss -1.0 → equity 98, peak 101, DD=3 → x0.50
    # T4: win +0.5 (scaled) → equity 98.5, peak 101, DD=2.5
    trades3 = []
    entry3 = []
    pnls3 = [1.0, -1.0, -1.0, -1.0, 1.0]
    for i, pnl in enumerate(pnls3):
        entry_t = base_ts + timedelta(hours=i * 72)
        exit_t = entry_t + timedelta(hours=24)
        t = BenchmarkTrade(
            trade_id=200 + i,
            symbol="EURUSD",
            test_type="D",
            direction="bullish",
            entry_price=1.1,
            sl=1.09,
            tp=1.118,
            entry_bar_index=i * 100,
            sweep_bar_index=0,
            zone_index=0,
            zone_creation_bar=0,
            zone_top=1.105,
            zone_bottom=1.1,
            zone_size=0.005,
            zone_size_atr=0.5,
            sweep_size_atr=0.3,
            bars_sweep_to_zone=5,
            bars_zone_to_entry=2,
            exit_price=1.09 if pnl < 0 else 1.118,
            exit_bar_index=i * 100 + 10,
            exit_timestamp=exit_t,
            result="LOSS" if pnl < 0 else "TP",
            pnl_r=pnl,
            trailing_count=0,
            max_favorable=0.0,
            max_adverse=1.0,
            hold_bars=10,
        )
        trades3.append(t)
        entry3.append(entry_t)

    s3, p3, pre3, post3 = apply_dd_risk_scaling(trades3, entry3, starting_balance=100.0)
    # T0: x1.00 (+1.0), T1: x1.00 (-1.0), T2: x1.00 (-1.0), T3: x1.00 (-1.0, DD=2R not >2)
    # T4: x0.50 (+0.5, DD=3R>2). Total = 1.0 - 1.0 - 1.0 - 1.0 + 0.5 = -1.5R
    total_r3 = sum(t.pnl_r for t in s3)
    tests.append(("mixed: 5 survive", len(s3) == 5))
    tests.append(("mixed: 0 paused", p3 == 0))
    tests.append(("mixed: total pnl = -1.5R", abs(total_r3 - (-1.5)) < 0.01))

    for label, ok in tests:
        all_pass &= ok
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")

    print()
    print("=" * 72)
    print(f"PART A: {'ALL PASS' if all_pass else 'FAIL'}")
    print("=" * 72)
    return all_pass


# ═════════════════════════════════════════════════════════════════════════════
# Data loading — mirrors D engine's _run_symbol
# ═════════════════════════════════════════════════════════════════════════════


def _load_symbol_trades(symbol: str, dry_run: bool) -> List[BenchmarkTrade]:
    """Run the UNTOUCHED D v1.0 engine for one symbol."""
    feather_dir = _PROJECT_ROOT / "data" / "icmarket_feather"
    feather_path = feather_dir / f"{symbol}_15m.feather"
    df = pd.read_feather(feather_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    bars_15m = [
        Bar(
            index=i,
            timestamp=pd.Timestamp(df["timestamp"].iloc[i]),
            open=float(df["open"].iloc[i]),
            high=float(df["high"].iloc[i]),
            low=float(df["low"].iloc[i]),
            close=float(df["close"].iloc[i]),
            volume=float(df["volume"].iloc[i]),
        )
        for i in range(len(df))
    ]
    if dry_run:
        bars_15m = bars_15m[:3000]

    he, hk, le, lk = _build_1h_swing_timeline(bars_15m)
    trades, _audits, _counters = run_test_a_pure_d(symbol, bars_15m, he, hk, le, lk)
    return trades, bars_15m


def _load_all_trades(
    symbols: List[str], dry_run: bool
) -> Tuple[List[BenchmarkTrade], Dict[str, List[Bar]]]:
    """Load trades + bars for all symbols in parallel."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from tqdm import tqdm

    all_trades: List[BenchmarkTrade] = []
    bars_map: Dict[str, List[Bar]] = {}
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(_load_symbol_trades, sym, dry_run): sym for sym in symbols}
        pbar = tqdm(total=len(symbols), desc="Processing", unit="sym", ncols=80)
        for future in as_completed(futures):
            sym = futures[future]
            try:
                trades, bars = future.result()
                all_trades.extend(trades)
                bars_map[sym] = bars
            except Exception as e:
                print(f"  ERROR {sym}: {e}")
            pbar.update(1)
        pbar.close()
    return all_trades, bars_map


# ═════════════════════════════════════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="D v1.0 + DD Risk Scaling (Experiment F)")
    parser.add_argument("symbols", nargs="*", help="Symbols (default: 6 majors)")
    parser.add_argument("--dry-run", action="store_true", help="Smoke test (3000 bars)")
    parser.add_argument(
        "--starting-balance",
        type=float,
        default=STARTING_BALANCE_R,
        help=f"Starting balance in R for DD% (default: {STARTING_BALANCE_R})",
    )
    args = parser.parse_args()

    symbols = [s.upper() for s in args.symbols] if args.symbols else SIX_MAJORS

    # ── PART A: synthetic tests ──────────────────────────────────────────
    synth_ok = _run_synthetic_tests()

    # ── PART B: full run ─────────────────────────────────────────────────
    print()
    print("=" * 72)
    print("PART B -- FULL 2.7Y / 6-MAJOR RUN")
    print("=" * 72)
    print("=== D v1.0 + DD Risk Scaling (Experiment F) ===")
    print(f"Thresholds: DD>{DD_T1}R x0.50 | DD>{DD_T2}R x0.25 | DD>{DD_T3}R PAUSE")
    print(f"Symbols: {symbols} | {'DRY RUN' if args.dry_run else 'FULL 2.7Y'}")

    base_trades, bars_map = _load_all_trades(symbols, args.dry_run)
    base_stats = compute_stats(base_trades, starting_balance=args.starting_balance)

    # Attach entry_timestamp externally (engine untouched).
    entry_ts_map = {}
    for sym in symbols:
        if sym not in bars_map:
            continue
        bars = bars_map[sym]
        sym_trades = [t for t in base_trades if t.symbol == sym]
        for t in sym_trades:
            ei = getattr(t, "entry_bar_index", 0)
            entry_ts_map[t.trade_id] = (
                pd.Timestamp(bars[ei].timestamp) if 0 <= ei < len(bars) else pd.Timestamp(0)
            )

    entry_ts = [entry_ts_map.get(t.trade_id, pd.Timestamp(0)) for t in base_trades]

    scaled_trades, paused, pre_dd, post_dd = apply_dd_risk_scaling(
        base_trades, entry_ts, starting_balance=args.starting_balance
    )
    scaled_stats = compute_stats(scaled_trades, starting_balance=args.starting_balance)

    print()
    print("=== D BASELINE vs D + DD Risk Scaling ===")
    hdr = f"{'Metric':<14} {'Baseline':>14} {'Scaled':>14} {'Delta':>14}"
    print(hdr)
    print("-" * len(hdr))
    print(
        f"{'Trades':<14} {base_stats['trades']:>14d} {scaled_stats['trades']:>14d} "
        f"{scaled_stats['trades'] - base_stats['trades']:>+14d}"
    )
    print(f"{'Blocked':<14} {0:>14d} {paused:>14d} {paused:>+14d}")
    print(
        f"{'WR%':<14} {base_stats['win_rate']:>13.2f} {scaled_stats['win_rate']:>13.2f} "
        f"{scaled_stats['win_rate'] - base_stats['win_rate']:>+13.2f}"
    )
    print(
        f"{'TotalR':<14} {base_stats['total_pnl']:>14.2f} {scaled_stats['total_pnl']:>14.2f} "
        f"{scaled_stats['total_pnl'] - base_stats['total_pnl']:>+14.2f}"
    )
    print(
        f"{'AvgR':<14} {base_stats['avg_r']:>14.4f} {scaled_stats['avg_r']:>14.4f} "
        f"{scaled_stats['avg_r'] - base_stats['avg_r']:>+14.4f}"
    )
    print(
        f"{'PF':<14} {base_stats['profit_factor']:>14.2f} {scaled_stats['profit_factor']:>14.2f} "
        f"{scaled_stats['profit_factor'] - base_stats['profit_factor']:>+14.2f}"
    )
    print(
        f"{'MaxDD(R)':<14} {base_stats['max_dd']:>14.2f} {scaled_stats['max_dd']:>14.2f} "
        f"{scaled_stats['max_dd'] - base_stats['max_dd']:>+14.2f}"
    )
    print(
        f"{'MaxDD(%)':<14} {base_stats['max_dd_pct']:>13.2f} {scaled_stats['max_dd_pct']:>13.2f} "
        f"{scaled_stats['max_dd_pct'] - base_stats['max_dd_pct']:>+13.2f}"
    )

    # ── Per-symbol ───────────────────────────────────────────────────────
    print()
    print("=" * 72)
    print("PER-SYMBOL BREAKDOWN")
    print("=" * 72)
    base_by_sym: Dict[str, List[BenchmarkTrade]] = {}
    for t in base_trades:
        base_by_sym.setdefault(t.symbol, []).append(t)
    scaled_ids = set(t.trade_id for t in scaled_trades)

    print(
        f"{'Symbol':<8} {'Base N':>7} {'Scaled N':>9} {'Blocked':>8} "
        f"{'WR%':>8} {'TotalR':>10} {'AvgR':>8} {'PF':>6}"
    )
    print("-" * 64)
    for sym in sorted(base_by_sym):
        bsym = base_by_sym[sym]
        ssym = [t for t in scaled_trades if t.symbol == sym]
        bstats = compute_stats(bsym, starting_balance=STARTING_BALANCE_R)
        sstats = compute_stats(ssym, starting_balance=STARTING_BALANCE_R)
        blocked = bstats["trades"] - sstats["trades"]
        print(
            f"{sym:<8} {bstats['trades']:>7d} {sstats['trades']:>9d} {blocked:>8d} "
            f"{sstats['win_rate']:>7.2f}% {sstats['total_pnl']:>10.2f} "
            f"{sstats['avg_r']:>8.4f} {sstats['profit_factor']:>6.2f}"
        )

    # ── Risk scaling event distribution ──────────────────────────────────
    print()
    print("=" * 72)
    print("RISK SCALING EVENT DISTRIBUTION")
    print("=" * 72)
    # Recount: walk trades again to classify each surviving trade's multiplier.
    completed = [t for t in base_trades if t.result in ("TP", "PROFIT_TRAIL", "LOSS")]
    paired = sorted(zip(completed, entry_ts), key=lambda p: p[0].exit_timestamp)
    ordered = [p[0] for p in paired]
    entry_times = [p[1] for p in paired]
    exit_times = [t.exit_timestamp for t in ordered]

    equity = STARTING_BALANCE_R
    peak = STARTING_BALANCE_R
    applied = 0
    mult_counts = {"x1.00": 0, "x0.50": 0, "x0.25": 0}
    pause_count = 0
    for k, t in enumerate(ordered):
        while applied < len(ordered) and exit_times[applied] <= entry_times[k]:
            et = ordered[applied]
            equity += et.pnl_r
            peak = max(peak, equity)
            applied += 1
        dd_now = peak - equity
        if dd_now > DD_T3:
            pause_count += 1
        elif dd_now > DD_T2:
            mult_counts["x0.25"] += 1
        elif dd_now > DD_T1:
            mult_counts["x0.50"] += 1
        else:
            mult_counts["x1.00"] += 1

    print(f"  x1.00 (DD≤2R):  {mult_counts['x1.00']:>5d} trades")
    print(f"  x0.50 (DD>2R):  {mult_counts['x0.50']:>5d} trades")
    print(f"  x0.25 (DD>4R):  {mult_counts['x0.25']:>5d} trades")
    print(f"  PAUSE (DD>6R):  {pause_count:>5d} trades")
    print(f"  Total baseline: {len(ordered):>5d}")

    # ── Decision ─────────────────────────────────────────────────────────
    print()
    print("=" * 72)
    print("DECISION SUMMARY")
    print("=" * 72)
    d_maxdd = scaled_stats["max_dd"] - base_stats["max_dd"]
    d_maxdd_pct = scaled_stats["max_dd_pct"] - base_stats["max_dd_pct"]
    d_pf = scaled_stats["profit_factor"] - base_stats["profit_factor"]
    d_wr = scaled_stats["win_rate"] - base_stats["win_rate"]
    d_totalr = scaled_stats["total_pnl"] - base_stats["total_pnl"]
    print(f"  MaxDD(R) delta     : {d_maxdd:+.2f}")
    print(f"  MaxDD(%) delta     : {d_maxdd_pct:+.2f}")
    print(f"  PF delta           : {d_pf:+.2f}")
    print(f"  WR delta           : {d_wr:+.2f}")
    print(f"  TotalR delta       : {d_totalr:+.2f}")
    print(f"  Trades paused      : {paused}")

    if d_maxdd < 0 and d_pf >= 0:
        decision = "PROMOTE (MaxDD reduced, PF preserved)"
    elif d_maxdd < 0 and abs(d_pf) < 0.1:
        decision = "KEEP candidate (MaxDD reduced, PF marginal cost)"
    elif d_maxdd == 0 and paused == 0:
        decision = "REJECT — non-binding (scaling never triggered)"
    elif d_maxdd == 0:
        decision = "REJECT — non-impact (scaling triggered but MaxDD unchanged)"
    else:
        decision = "REJECT (MaxDD increased)"
    print(f"  Suggested decision : {decision}")

    # ── Persist ──────────────────────────────────────────────────────────
    out_dir = _PROJECT_ROOT / "results" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "expF_d_risk_scaling_trades.json", "w") as f:
        json.dump([t.__dict__ for t in scaled_trades], f, indent=2, default=str)
    summary = {
        "engine": "main_research_d_v1_0",
        "experiment": "F",
        "baseline": base_stats,
        "scaled": scaled_stats,
        "paused_entries": paused,
        "thresholds": {"t1": DD_T1, "t2": DD_T2, "t3": DD_T3},
        "params": {"x_t1": 0.50, "x_t2": 0.25, "x_t3": 0.0},
        "delta": {
            "trades": scaled_stats["trades"] - base_stats["trades"],
            "win_rate": scaled_stats["win_rate"] - base_stats["win_rate"],
            "total_r": scaled_stats["total_pnl"] - base_stats["total_pnl"],
            "avg_r": scaled_stats["avg_r"] - base_stats["avg_r"],
            "profit_factor": scaled_stats["profit_factor"] - base_stats["profit_factor"],
            "max_dd": scaled_stats["max_dd"] - base_stats["max_dd"],
            "max_dd_pct": scaled_stats["max_dd_pct"] - base_stats["max_dd_pct"],
        },
        "risk_scaling_events": mult_counts,
        "lookahead_free": True,
        "synthetic_tests": "ALL PASS" if synth_ok else "FAIL",
        "suggested_decision": decision,
    }
    with open(out_dir / "expF_d_risk_scaling_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nResults saved to {out_dir}")

    return 0 if synth_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
