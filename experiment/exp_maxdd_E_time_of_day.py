"""
exp_maxdd_E_time_of_day.py — Experiment E: C2 MaxDD research

Isolates ONE variable: Time-of-Day entry filter (post-hoc).

Rule
----
Only allow entries whose entry_timestamp falls inside the predefined
quality windows (London 10:00-13:00 or NY AM 15:30-18:00, in the
timestamps as they appear on the trades). All other entries are
BLOCKED (the trade is treated as if the overlay rejected it; its
hypothetical exit contributes nothing to the equity curve).

NO lookahead: only entry_timestamp is used. Trade result (LOSS/TP/PROFIT_TRAIL)
is NEVER used to classify the entry. The filter is evaluated per
baseline trade based on its own entry_timestamp.

Methodology
-----------
- Baseline = UNTOUCHED C2 engine (main_research_c_v1_0.run_test_a) on the
  6 majors / 2.7Y 15m dataset. EQ, FVG, entry/SL/TP, 1.8R trailing, exit
  logic, compute_stats are all unchanged inside main_research_c_v1_0.py.
- The filter is applied as a POST-HOC portfolio overlay on the baseline
  trade stream. entry_timestamp is attached externally from the 15m
  bars (the canonical engine is not modified).
- No timezone conversion: we use the timestamps exactly as the engine
  produces them (the canonical engine's `exit_timestamp` / bars'
  `timestamp` field is the reference clock; the codebase is documented
  as MT5 server time, UTC+2/3 DST-aware).

Deliverables
------------
- PART A: synthetic boundary tests for the windows.
- PART B: FULL 2.7Y/6-major run. C2 baseline vs C2 + ToD filter.
- Per-symbol breakdown.
- Window attribution (London / NY AM / Outside).
- MaxDD episode trade dump + window classification.

Run:
    python experiment/exp_maxdd_E_time_of_day.py
    python experiment/exp_maxdd_E_time_of_day.py --dry-run
    python experiment/exp_maxdd_E_time_of_day.py --synth-only
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import time
from pathlib import Path
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

# ── Allowed entry windows (server time, as carried by bars/trade records) ─
LONDON_START = time(10, 0)
LONDON_END = time(13, 0)  # exclusive
NY_AM_START = time(15, 30)
NY_AM_END = time(18, 0)  # exclusive


def _bucket_of(ts) -> str:
    """Classify a timestamp into a window bucket: 'london' / 'ny_am' / 'outside'."""
    t = ts.time() if hasattr(ts, "time") else ts
    if LONDON_START <= t < LONDON_END:
        return "london"
    if NY_AM_START <= t < NY_AM_END:
        return "ny_am"
    return "outside"


def _allowed_entry_time(ts) -> bool:
    """Accept entry iff its time-of-day is inside London or NY AM window."""
    return _bucket_of(ts) in ("london", "ny_am")


# ═════════════════════════════════════════════════════════════════════════════
# PART A — Synthetic boundary tests
# ═════════════════════════════════════════════════════════════════════════════


def _run_synthetic_tests() -> bool:
    """Boundary tests for the allowed windows. 5+ PASS required."""
    from datetime import datetime

    print("=" * 72)
    print("PART A -- SYNTHETIC WINDOW BOUNDARY TESTS")
    print("=" * 72)
    all_pass = True

    cases = [
        # (label, time, expected_allowed)
        ("London 10:00 (start)        ", time(10, 0), True),
        ("London 12:59 (end-1s)       ", time(12, 59), True),
        ("London 13:00 (end, EXCL)    ", time(13, 0), False),
        ("NY AM 15:29 (start-1s)      ", time(15, 29), False),
        ("NY AM 15:30 (start)         ", time(15, 30), True),
        ("NY AM 17:59 (end-1s)        ", time(17, 59), True),
        ("NY AM 18:00 (end, EXCL)     ", time(18, 0), False),
        ("Gap 14:00 (between windows) ", time(14, 0), False),
        ("Gap 13:30 (between windows) ", time(13, 30), False),
        ("Early 09:59 (before london) ", time(9, 59), False),
        ("Late 18:01 (after ny)       ", time(18, 1), False),
    ]

    print()
    print(f"  {'Case':<32} {'time':<10} {'expect':<8} {'got':<8} ok")
    print("  " + "-" * 64)
    for label, t, expected in cases:
        got = _allowed_entry_time(t)
        ok = got == expected
        all_pass &= ok
        print(
            f"  {label:<32} {str(t):<10} {str(expected):<8} {str(got):<8} {'PASS' if ok else 'FAIL'}"
        )

    # Also test with full datetimes (the real shape of entry_timestamp)
    print()
    print("  Full datetime shape (mirrors entry_timestamp):")
    dt_cases = [
        ("datetime 2024-06-15 10:00", datetime(2024, 6, 15, 10, 0), True),
        ("datetime 2024-06-15 13:00", datetime(2024, 6, 15, 13, 0), False),
        ("datetime 2024-06-15 15:30", datetime(2024, 6, 15, 15, 30), True),
        ("datetime 2024-06-15 18:00", datetime(2024, 6, 15, 18, 0), False),
    ]
    for label, dt, expected in dt_cases:
        got = _allowed_entry_time(dt)
        ok = got == expected
        all_pass &= ok
        print(f"    {label:<40} expect={expected} got={got} {'PASS' if ok else 'FAIL'}")

    print()
    print("=" * 72)
    print(f"PART A: {'ALL PASS' if all_pass else 'FAIL'}")
    print("=" * 72)
    return all_pass


# ═════════════════════════════════════════════════════════════════════════════
# Overlay
# ═════════════════════════════════════════════════════════════════════════════


def apply_tod_filter(
    trades: List[BenchmarkTrade],
) -> Tuple[List[BenchmarkTrade], List[BenchmarkTrade], Dict[str, int]]:
    """Post-hoc entry-time filter.

    Returns (allowed, blocked, window_counts) where window_counts maps
    bucket name -> number of baseline trades in that bucket (the FULL
    distribution, not just blocked/allowed).
    """
    allowed: List[BenchmarkTrade] = []
    blocked: List[BenchmarkTrade] = []
    window_counts: Counter = Counter()
    for t in trades:
        bucket = _bucket_of(t.entry_timestamp)
        window_counts[bucket] += 1
        if bucket in ("london", "ny_am"):
            allowed.append(t)
        else:
            blocked.append(t)
    return allowed, blocked, dict(window_counts)


# ═════════════════════════════════════════════════════════════════════════════
# Per-symbol stats helper
# ═════════════════════════════════════════════════════════════════════════════


def _per_symbol_stats(
    base_trades: List[BenchmarkTrade],
    allowed_trades: List[BenchmarkTrade],
) -> List[Dict]:
    """Per-symbol comparison. `blocked` = baseline - allowed for that symbol."""
    base_by_sym: Dict[str, List[BenchmarkTrade]] = {}
    for t in base_trades:
        base_by_sym.setdefault(t.symbol, []).append(t)
    allowed_ids_by_sym: Dict[str, set] = {}
    for t in allowed_trades:
        allowed_ids_by_sym.setdefault(t.symbol, set()).add(t.trade_id)

    rows: List[Dict] = []
    for sym in sorted(base_by_sym):
        bsym = base_by_sym[sym]
        asym = [t for t in bsym if t.trade_id in allowed_ids_by_sym.get(sym, set())]
        bstats = compute_stats(bsym, starting_balance=STARTING_BALANCE_R)
        astats = compute_stats(asym, starting_balance=STARTING_BALANCE_R)
        rows.append(
            {
                "symbol": sym,
                "baseline": {
                    "trades": bstats["trades"],
                    "win_rate": bstats["win_rate"],
                    "total_r": bstats["total_pnl"],
                    "avg_r": bstats["avg_r"],
                    "profit_factor": bstats["profit_factor"],
                    "max_dd": bstats["max_dd"],
                    "max_dd_pct": bstats["max_dd_pct"],
                },
                "filtered": {
                    "trades": astats["trades"],
                    "blocked": bstats["trades"] - astats["trades"],
                    "win_rate": astats["win_rate"],
                    "total_r": astats["total_pnl"],
                    "avg_r": astats["avg_r"],
                    "profit_factor": astats["profit_factor"],
                    "max_dd": astats["max_dd"],
                    "max_dd_pct": astats["max_dd_pct"],
                },
            }
        )
    return rows


# ═════════════════════════════════════════════════════════════════════════════
# MaxDD episode extraction
# ═════════════════════════════════════════════════════════════════════════════


def _baseline_equity_curve(
    trades: List[BenchmarkTrade],
) -> List[Tuple[float, float, BenchmarkTrade]]:
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


def _maxdd_episode_trades(
    baseline_trades: List[BenchmarkTrade],
) -> List[BenchmarkTrade]:
    """Return the trades that build the MaxDD episode: from the equity peak
    to the trough, inclusive (all trades whose exit moves equity from
    the peak down to the trough)."""
    curve = _baseline_equity_curve(baseline_trades)
    if not curve:
        return []
    max_dd = max(c[1] for c in curve)
    # Find peak index (any peak before the trough) and trough index.
    trough_idx = next(i for i, c in enumerate(curve) if c[1] == max_dd)
    # The peak is the max cum before the trough.
    peak_cum = max(c[0] for c in curve[: trough_idx + 1])
    peak_idx = next(i for i, c in enumerate(curve) if c[0] == peak_cum and i <= trough_idx)
    # Episode = trades from peak+1 .. trough inclusive.
    return [c[2] for c in curve[peak_idx : trough_idx + 1]]


def _fmt_ts(ts) -> str:
    try:
        return str(ts)
    except Exception:
        return "?"


# ═════════════════════════════════════════════════════════════════════════════
# Data loading (engine untouched; entry_timestamp attached externally)
# ═════════════════════════════════════════════════════════════════════════════


def _load_symbol_trades(symbol: str, dry_run: bool) -> List[BenchmarkTrade]:
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
# Main
# ═════════════════════════════════════════════════════════════════════════════


def _fmt_delta(v0: float, v1: float, pct: bool = False) -> str:
    if pct:
        return f"{v1 - v0:+.2f}%"
    return f"{v1 - v0:+.2f}"


def main():
    parser = argparse.ArgumentParser(
        description="C2 MaxDD Experiment E: Time-of-Day Quality Filter"
    )
    parser.add_argument("symbols", nargs="*", help="Symbols (default: 6 majors)")
    parser.add_argument("--dry-run", action="store_true", help="Smoke test (2000 bars)")
    parser.add_argument(
        "--starting-balance",
        type=float,
        default=STARTING_BALANCE_R,
        help=f"Starting balance in R for DD% (default: {STARTING_BALANCE_R})",
    )
    parser.add_argument(
        "--synth-only",
        action="store_true",
        help="Run synthetic boundary tests only and exit",
    )
    args = parser.parse_args()

    # ── PART A: synthetic boundary tests ────────────────────────────────
    synth_ok = _run_synthetic_tests()
    if args.synth_only:
        return 0 if synth_ok else 1

    SIX_MAJORS = ["EURUSD", "GBPUSD", "GBPJPY", "USDJPY", "AUDUSD", "USDCAD"]
    symbols = [s.upper() for s in args.symbols] if args.symbols else SIX_MAJORS

    # ── PART B: full run ─────────────────────────────────────────────────
    print()
    print("=" * 72)
    print("PART B -- FULL 2.7Y / 6-MAJOR RUN")
    print("=" * 72)
    print("=== C2 MaxDD EXPERIMENT E -- Time-of-Day Quality Filter ===")
    print(
        f"Allowed windows (server time, exclusive end): "
        f"London {LONDON_START}-{LONDON_END} | NY AM {NY_AM_START}-{NY_AM_END}"
    )
    print(f"Symbols: {symbols} | {'DRY RUN' if args.dry_run else 'FULL 2.7Y'}")

    base_trades = _load_all_trades(symbols, args.dry_run)
    base_stats = compute_stats(base_trades, starting_balance=args.starting_balance)

    allowed_trades, blocked_trades, window_counts = apply_tod_filter(base_trades)
    filt_stats = compute_stats(allowed_trades, starting_balance=args.starting_balance)

    blocked = len(blocked_trades)

    print()
    print("=== C2 BASELINE vs C2 + ToD Filter (London + NY AM only) ===")
    hdr = f"{'Metric':<14} {'Baseline':>14} {'Filtered':>14} {'Delta':>14}"
    print(hdr)
    print("-" * len(hdr))
    print(
        f"{'Trades':<14} {base_stats['trades']:>14d} {filt_stats['trades']:>14d} "
        f"{filt_stats['trades'] - base_stats['trades']:>+14d}"
    )
    print(f"{'Blocked':<14} {0:>14d} {blocked:>14d} {blocked:>+14d}")
    bk_pct = (blocked / base_stats["trades"] * 100) if base_stats["trades"] else 0.0
    print(f"{'Blocked %':<14} {0.0:>13.2f}% {bk_pct:>13.2f}% {bk_pct:>+13.2f}%")
    print(
        f"{'WR%':<14} {base_stats['win_rate']:>13.2f} {filt_stats['win_rate']:>13.2f} "
        f"{filt_stats['win_rate'] - base_stats['win_rate']:>+13.2f}"
    )
    print(
        f"{'TotalR':<14} {base_stats['total_pnl']:>14.2f} {filt_stats['total_pnl']:>14.2f} "
        f"{filt_stats['total_pnl'] - base_stats['total_pnl']:>+14.2f}"
    )
    print(
        f"{'AvgR':<14} {base_stats['avg_r']:>14.4f} {filt_stats['avg_r']:>14.4f} "
        f"{filt_stats['avg_r'] - base_stats['avg_r']:>+14.4f}"
    )
    print(
        f"{'PF':<14} {base_stats['profit_factor']:>14.2f} {filt_stats['profit_factor']:>14.2f} "
        f"{filt_stats['profit_factor'] - base_stats['profit_factor']:>+14.2f}"
    )
    print(
        f"{'MaxDD(R)':<14} {base_stats['max_dd']:>14.2f} {filt_stats['max_dd']:>14.2f} "
        f"{filt_stats['max_dd'] - base_stats['max_dd']:>+14.2f}"
    )
    print(
        f"{'MaxDD(%)':<14} {base_stats['max_dd_pct']:>13.2f} {filt_stats['max_dd_pct']:>13.2f} "
        f"{filt_stats['max_dd_pct'] - base_stats['max_dd_pct']:>+13.2f}"
    )

    # ── Per-symbol ───────────────────────────────────────────────────────
    print()
    print("=" * 72)
    print("PER-SYMBOL BREAKDOWN")
    print("=" * 72)
    per_sym = _per_symbol_stats(base_trades, allowed_trades)
    print(
        f"{'Symbol':<8} {'Trades':>7} {'Blocked':>8} {'WR%':>8} {'TotalR':>10} "
        f"{'AvgR':>8} {'PF':>6}"
    )
    print("-" * 60)
    for r in per_sym:
        b = r["baseline"]
        f_ = r["filtered"]
        print(
            f"{r['symbol']:<8} {b['trades']:>7d} {b['trades'] - f_['trades']:>8d} "
            f"{f_['win_rate']:>7.2f}% {f_['total_r']:>10.2f} "
            f"{f_['avg_r']:>8.4f} {f_['profit_factor']:>6.2f}"
        )

    # ── Window attribution (ALL baseline trades, not just allowed/blocked) ─
    print()
    print("=" * 72)
    print("WINDOW ATTRIBUTION (all baseline trades)")
    print("=" * 72)
    # Split by bucket
    by_bucket: Dict[str, List[BenchmarkTrade]] = {
        "london": [],
        "ny_am": [],
        "outside": [],
    }
    for t in base_trades:
        by_bucket[_bucket_of(t.entry_timestamp)].append(t)
    print(
        f"{'Window':<28} {'Trades':>8} {'WR%':>8} {'TotalR':>10} {'AvgR':>9} {'PF':>7} "
        f"{'Status':>10}"
    )
    print("-" * 84)
    for name, lbl in [
        ("london", "London 10:00-13:00"),
        ("ny_am", "NY AM 15:30-18:00"),
        ("outside", "Outside (blocked)"),
    ]:
        sub = by_bucket[name]
        if not sub:
            print(f"{lbl:<28} {0:>8d} {'--':>8} {'--':>10} {'--':>9} {'--':>7} {'--':>10}")
            continue
        s = compute_stats(sub, starting_balance=STARTING_BALANCE_R)
        status = "ACCEPTED" if name in ("london", "ny_am") else "BLOCKED"
        print(
            f"{lbl:<28} {s['trades']:>8d} {s['win_rate']:>7.2f}% "
            f"{s['total_pnl']:>10.2f} {s['avg_r']:>9.4f} {s['profit_factor']:>7.2f} "
            f"{status:>10}"
        )
    # Combined accepted
    accepted_all = by_bucket["london"] + by_bucket["ny_am"]
    if accepted_all:
        s = compute_stats(accepted_all, starting_balance=STARTING_BALANCE_R)
        print(
            f"{'ACCEPTED (London+NY AM)':<28} {s['trades']:>8d} {s['win_rate']:>7.2f}% "
            f"{s['total_pnl']:>10.2f} {s['avg_r']:>9.4f} {s['profit_factor']:>7.2f} "
            f"{'ACCEPTED':>10}"
        )

    # ── MaxDD episode ────────────────────────────────────────────────────
    print()
    print("=" * 72)
    print("BASELINE MaxDD EPISODE TRADE DUMP")
    print("=" * 72)
    ep_trades = _maxdd_episode_trades(base_trades)
    curve = _baseline_equity_curve(base_trades)
    max_dd = max((c[1] for c in curve), default=0.0)
    print(f"Baseline MaxDD(R) = {max_dd:.2f}R over {len(ep_trades)} trades")
    if ep_trades:
        print()
        print(
            f"{'#':<3} {'sym':<8} {'entry_ts':<22} {'exit_ts':<22} "
            f"{'entry_bar':>10} {'exit_bar':>10} {'pnl_r':>8} {'window':<10}"
        )
        for i, t in enumerate(ep_trades, 1):
            w = _bucket_of(t.entry_timestamp)
            print(
                f"{i:<3} {t.symbol:<8} {_fmt_ts(t.entry_timestamp):<22} "
                f"{_fmt_ts(t.exit_timestamp):<22} "
                f"{getattr(t, 'entry_bar_index', '?'):>10} "
                f"{getattr(t, 'exit_bar_index', '?'):>10} "
                f"{t.pnl_r:>+8.2f} {w:<10}"
            )
        # Window classification of the episode
        ep_windows = Counter(_bucket_of(t.entry_timestamp) for t in ep_trades)
        print()
        print(f"Episode window breakdown: {dict(ep_windows)}")
        # Of the allowed windows in the episode, how many would survive the filter?
        ep_surviving = sum(
            1 for t in ep_trades if _bucket_of(t.entry_timestamp) in ("london", "ny_am")
        )
        ep_blocked = len(ep_trades) - ep_surviving
        print(f"Episode trades that would SURVIVE the filter: {ep_surviving} / {len(ep_trades)}")
        print(
            f"Episode trades that would be BLOCKED by the filter: {ep_blocked} / {len(ep_trades)}"
        )
        # PnL of blocked vs surviving
        surv_pnl = sum(
            t.pnl_r for t in ep_trades if _bucket_of(t.entry_timestamp) in ("london", "ny_am")
        )
        block_pnl = sum(t.pnl_r for t in ep_trades if _bucket_of(t.entry_timestamp) == "outside")
        print(f"PnL of episode trades SURVIVING the filter: {surv_pnl:+.2f}R")
        print(f"PnL of episode trades BLOCKED by the filter:  {block_pnl:+.2f}R")

    # ── Decision summary ─────────────────────────────────────────────────
    print()
    print("=" * 72)
    print("DECISION SUMMARY")
    print("=" * 72)
    d_maxdd = filt_stats["max_dd"] - base_stats["max_dd"]
    d_pf = filt_stats["profit_factor"] - base_stats["profit_factor"]
    d_wr = filt_stats["win_rate"] - base_stats["win_rate"]
    d_totalr = filt_stats["total_pnl"] - base_stats["total_pnl"]
    print(f"  MaxDD(R) delta     : {d_maxdd:+.2f}")
    print(f"  MaxDD(%) delta     : {filt_stats['max_dd_pct'] - base_stats['max_dd_pct']:+.2f}")
    print(f"  PF delta           : {d_pf:+.2f}")
    print(f"  WR delta           : {d_wr:+.2f}")
    print(f"  TotalR delta       : {d_totalr:+.2f}")
    # Naive decision rule (advisory, not binding):
    # REJECT if MaxDD does not decrease AND PF/WR/TotalR not improved enough.
    if d_maxdd < 0 and (d_pf >= 0 or d_wr >= 0):
        decision = "PROMOTE (MaxDD reduced, PF/WR preserved)"
    elif d_maxdd < 0:
        decision = "KEEP candidate (MaxDD reduced but quality cost)"
    elif d_maxdd == 0 and d_pf > 0 and d_wr > 0 and d_totalr > 0:
        decision = "INCONCLUSIVE (MaxDD unchanged, mild quality lift)"
    elif d_maxdd == 0 and (d_pf <= 0 or d_wr <= 0 or d_totalr <= 0):
        decision = "REJECT — non-impact (MaxDD unchanged, quality not improved)"
    else:
        decision = "REJECT (MaxDD increased)"
    print(f"  Suggested decision : {decision}")

    # ── Persist ──────────────────────────────────────────────────────────
    out_dir = _PROJECT_ROOT / "results" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "expE_time_of_day_trades.json", "w") as f:
        json.dump([t.__dict__ for t in allowed_trades], f, indent=2, default=str)
    summary = {
        "engine": "main_research_c_v1_0",
        "experiment": "E",
        "windows": {
            "london": f"{LONDON_START.strftime('%H:%M')}-{LONDON_END.strftime('%H:%M')}",
            "ny_am": f"{NY_AM_START.strftime('%H:%M')}-{NY_AM_END.strftime('%H:%M')}",
        },
        "window_counts": window_counts,
        "baseline": base_stats,
        "filtered": filt_stats,
        "blocked_entries": blocked,
        "blocked_pct": (blocked / base_stats["trades"] * 100) if base_stats["trades"] else 0.0,
        "delta": {
            "trades": filt_stats["trades"] - base_stats["trades"],
            "win_rate": filt_stats["win_rate"] - base_stats["win_rate"],
            "total_r": filt_stats["total_pnl"] - base_stats["total_pnl"],
            "avg_r": filt_stats["avg_r"] - base_stats["avg_r"],
            "profit_factor": filt_stats["profit_factor"] - base_stats["profit_factor"],
            "max_dd": filt_stats["max_dd"] - base_stats["max_dd"],
            "max_dd_pct": filt_stats["max_dd_pct"] - base_stats["max_dd_pct"],
        },
        "per_symbol": per_sym,
        "maxdd_episode": {
            "baseline_max_dd_r": max_dd,
            "n_trades": len(ep_trades),
            "trades": [
                {
                    "symbol": t.symbol,
                    "entry_ts": _fmt_ts(t.entry_timestamp),
                    "exit_ts": _fmt_ts(t.exit_timestamp),
                    "entry_bar_index": getattr(t, "entry_bar_index", None),
                    "exit_bar_index": getattr(t, "exit_bar_index", None),
                    "pnl_r": t.pnl_r,
                    "window": _bucket_of(t.entry_timestamp),
                }
                for t in ep_trades
            ],
            "window_breakdown": dict(Counter(_bucket_of(t.entry_timestamp) for t in ep_trades)),
        },
        "lookahead_free": True,
        "synthetic_tests": "ALL PASS" if synth_ok else "FAIL",
        "suggested_decision": decision,
    }
    with open(out_dir / "expE_time_of_day_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nResults saved to {out_dir}")

    return 0 if synth_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
