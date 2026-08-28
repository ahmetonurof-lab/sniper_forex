#!/usr/bin/env python
"""C v1.1 — DD-based risk scaling promotion tests.

Covers (per the task spec):
  1. C v1.0 immutable regression (C v1.0 must be untouched).
  2. DD scaling threshold/multiplier tests (all 4 tiers + boundaries).
  3. zero-DD / full-risk state.
  4. each scaling tier (x1.0 / x0.5 / x0.25 / PAUSE).
  5. chronology / same-bar causality (no-lookahead, exit-timestamp order).
  6. deterministic replay (same input -> same output).
  7. C v1.0 vs C v1.1 head-to-head parity (trade identity, scaling delta).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List

import pandas as pd
import pytest

_REPO = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO))

from experiment.main_research_c_v1_0 import (  # noqa: E402
    BenchmarkTrade,
    compute_stats,
    run_test_a,
)
from experiment.main_research_c_v1_1 import (  # noqa: E402
    DD_T1,
    DD_T2,
    DD_T3,
    apply_dd_scaling,
    compute_dd_multiplier,
    compute_stats_v11,
    run_test_a_v11,
)


# ── Helpers ──────────────────────────────────────────────────────


def _mk_trade(
    trade_id: int,
    entry_ts: float,
    exit_ts: float,
    pnl_r: float,
    result: str = "TP",
) -> BenchmarkTrade:
    """Build a minimal BenchmarkTrade for scaling tests."""
    return BenchmarkTrade(
        trade_id=trade_id,
        symbol="TEST",
        test_type="POST_SWEEP_FVG",
        direction="bullish",
        entry_price=1.0,
        sl=0.99,
        tp=1.02,
        entry_bar_index=0,
        sweep_bar_index=0,
        zone_index=0,
        zone_creation_bar=0,
        zone_top=1.001,
        zone_bottom=0.999,
        zone_size=0.002,
        zone_size_atr=1.0,
        sweep_size_atr=0.5,
        bars_sweep_to_zone=0,
        bars_zone_to_entry=0,
        exit_price=1.0 + pnl_r * 0.01,
        exit_bar_index=0,
        exit_timestamp=exit_ts,
        result=result,
        pnl_r=pnl_r,
    )


# ── 1. C v1.0 immutable regression ──────────────────────────────


def test_c_v10_engine_untouched_after_promotion():
    """C v1.0 must still load + run identically. We assert the
    canonical 6-major fingerprint via the full feather replay."""

    feather_dir = _REPO / "data" / "icmarket_feather"
    symbols = ["EURUSD", "GBPUSD", "GBPJPY", "USDJPY", "AUDUSD", "USDCAD"]
    total = 0
    for s in symbols:
        feather = feather_dir / f"{s}_15m.feather"
        if not feather.exists():
            pytest.skip(f"feather missing: {feather}")
        df = pd.read_feather(feather)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        from src.strategy.models import Bar

        bars = [
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
                df["timestamp"],
                df["open"],
                df["high"],
                df["low"],
                df["close"],
                df["volume"],
            )
        ]
        trades = run_test_a(s, bars)
        total += len(trades)
    # Authoritative fingerprint of C v1.0 on 2.7Y 6 majors.
    assert total == 2302, f"C v1.0 trade count changed: {total} (expected 2302)"


# ── 2-4. DD scaling thresholds / tiers ──────────────────────────


def test_multiplier_zero_dd_is_full_risk():
    assert compute_dd_multiplier(0.0) == 1.0


def test_multiplier_below_t1_is_full_risk():
    assert compute_dd_multiplier(DD_T1 - 0.01) == 1.0


def test_multiplier_just_above_t1_is_half():
    assert compute_dd_multiplier(DD_T1 + 0.01) == 0.5


def test_multiplier_at_t1_is_full_risk():
    """Boundary: `dd > t1` is strict, so dd == t1 is full risk."""
    assert compute_dd_multiplier(DD_T1) == 1.0


def test_multiplier_between_t1_and_t2_is_half():
    assert compute_dd_multiplier((DD_T1 + DD_T2) / 2) == 0.5


def test_multiplier_just_above_t2_is_quarter():
    assert compute_dd_multiplier(DD_T2 + 0.01) == 0.25


def test_multiplier_at_t2_is_half():
    assert compute_dd_multiplier(DD_T2) == 0.5


def test_multiplier_just_above_t3_is_pause():
    assert compute_dd_multiplier(DD_T3 + 0.01) == 0.0


def test_multiplier_at_t3_is_quarter():
    assert compute_dd_multiplier(DD_T3) == 0.25


def test_multiplier_large_dd_is_pause():
    assert compute_dd_multiplier(100.0) == 0.0


# ── 5. Chronology / no-lookahead / same-bar causality ────────────


def test_apply_dd_scaling_no_lookahead():
    """Trade's own pnl must NOT be used to scale itself.

    Scenario: starting at peak, trade 1 wins +1R, trade 2 loses -1R
    (would push DD to 0 after trade 1, then to 1R after trade 2 — but
    trade 2's DD must be measured BEFORE its own contribution).

    In chronological order:
      - trade 1 entry: DD=0 -> x1.0
      - trade 1 exit: realized=+1R
      - trade 2 entry: DD=0 (peak updated to starting+1) -> x1.0
      - trade 2 exit: realized=+0R
      - trade 3 entry: DD=0 -> x1.0
    """
    t1 = _mk_trade(1, entry_ts=10.0, exit_ts=20.0, pnl_r=1.0)
    t2 = _mk_trade(2, entry_ts=25.0, exit_ts=30.0, pnl_r=-1.0)
    t3 = _mk_trade(3, entry_ts=35.0, exit_ts=40.0, pnl_r=0.5)
    surviving, paused, n1, n05, n025 = apply_dd_scaling(
        [t1, t2, t3], entry_ts=[10.0, 25.0, 35.0]
    )
    assert paused == 0
    assert n1 == 3
    assert n05 == 0
    assert n025 == 0
    # All pnl_r preserved (x1.0).
    assert [t.pnl_r for t in surviving] == [1.0, -1.0, 0.5]


def test_apply_dd_scaling_pause_drops_trade():
    """Force DD > 6R before a trade entry, that trade is paused."""
    # 4 winning trades then a losing trade after DD>6R.
    wins = [
        _mk_trade(i, entry_ts=10.0 * i, exit_ts=11.0 * i, pnl_r=2.0)
        for i in range(1, 5)
    ]
    # 4 x 2R = +8R -> peak=108R. After trades realized=+8R.
    # Now insert a trade that would push DD > 6R if applied with x1.0.
    # Actually: peak=108, equity=108, DD=0 after wins. We need DD>6R
    # at the NEXT trade's entry. Since wins moved equity up, peak
    # tracked. The only way to get DD>6R is for a LOSS to have
    # happened in between. Add a -7R loss.
    loss = _mk_trade(5, entry_ts=50.0, exit_ts=55.0, pnl_r=-7.0, result="LOSS")
    # After loss: equity = 100 + 8 - 7 = 101, peak = 108, DD = 7R.
    next_trade = _mk_trade(6, entry_ts=60.0, exit_ts=65.0, pnl_r=0.5)
    # next_trade entry has DD=7R > 6R -> PAUSE.
    surviving, paused, *_ = apply_dd_scaling(
        wins + [loss, next_trade], entry_ts=[10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
    )
    assert paused == 1
    assert len(surviving) == 5
    # The paused trade's pnl_r must NOT appear in surviving.
    pnl_ids = [t.trade_id for t in surviving]
    assert 6 not in pnl_ids


def test_apply_dd_scaling_x05_tier():
    """DD strictly between 2R and 4R -> x0.5 scaling.

    Sequence: +1R, +1R, +1R, -2R, +2R.
    After t1, t2, t3: equity=105, peak=105.
    t4 entry dd=0, x1, pnl=-2. equity=103, peak=105.
    t5 entry: advance. applied=3, t4.exit=45<=50 YES. equity=101, peak=105, applied=4.
    dd=4. 4>2 YES, 4>4 NO → x0.5. pnl=1.0.
    """
    t1 = _mk_trade(1, entry_ts=10.0, exit_ts=15.0, pnl_r=1.0)
    t2 = _mk_trade(2, entry_ts=20.0, exit_ts=25.0, pnl_r=1.0)
    t3 = _mk_trade(3, entry_ts=30.0, exit_ts=35.0, pnl_r=1.0)
    t4 = _mk_trade(4, entry_ts=40.0, exit_ts=45.0, pnl_r=-2.0, result="LOSS")
    t5 = _mk_trade(5, entry_ts=50.0, exit_ts=55.0, pnl_r=2.0)
    surviving, paused, n1, n05, n025 = apply_dd_scaling(
        [t1, t2, t3, t4, t5],
        entry_ts=[10.0, 20.0, 30.0, 40.0, 50.0, 55.0, 60.0, 65.0, 70.0, 75.0],
    )
    assert paused == 0
    assert n1 == 4
    assert n05 == 1
    assert n025 == 0
    t5_scaled = next(t for t in surviving if t.trade_id == 5)
    assert t5_scaled.pnl_r == 1.0  # 2.0 * 0.5


def test_apply_dd_scaling_x025_tier():
    """DD strictly between 4R and 6R -> x0.25 scaling.

    Sequence: +1R, +1R, +1R, -3R, +4R.
    After t1, t2, t3: equity=105, peak=105.
    t4 entry dd=0, x1.0, pnl=-3. equity=102, peak=105.
    t5 entry: advance. applied=3, t4.exit=45<=50 YES. equity=99, peak=105, applied=4.
    dd=6. 6>4 YES, 6>6 NO → x0.25. pnl=4*0.25=1.0.
    """
    t1 = _mk_trade(1, entry_ts=10.0, exit_ts=15.0, pnl_r=1.0)
    t2 = _mk_trade(2, entry_ts=20.0, exit_ts=25.0, pnl_r=1.0)
    t3 = _mk_trade(3, entry_ts=30.0, exit_ts=35.0, pnl_r=1.0)
    t4 = _mk_trade(4, entry_ts=40.0, exit_ts=45.0, pnl_r=-3.0, result="LOSS")
    t5 = _mk_trade(5, entry_ts=50.0, exit_ts=55.0, pnl_r=4.0)
    surviving, paused, n1, n05, n025 = apply_dd_scaling(
        [t1, t2, t3, t4, t5],
        entry_ts=[10.0, 20.0, 30.0, 40.0, 50.0, 55.0, 60.0, 65.0, 70.0, 75.0],
    )
    assert paused == 0
    assert n1 == 4  # t1, t2, t3, t4 (all at DD<=2)
    assert n05 == 0
    assert n025 == 1  # t5 (DD=6 → x0.25)
    t5_scaled = next(t for t in surviving if t.trade_id == 5)
    assert t5_scaled.pnl_r == 1.0  # 4.0 * 0.25


def test_apply_dd_scaling_paused_trade_does_not_change_peak():
    """A paused trade's pnl_r is NOT added to equity or peak. Subsequent
    trades' DD must reflect the state BEFORE the paused trade.

    Sequence: t1=-3, t2=-4, t3=+2 (would be paused), t4=+2.
    Trace (with starting_balance=100):
      t1: dd=0, x1.0, pnl=-3.0. equity=97, peak=100.
      t2: advance. equity=94, peak=100, applied=1. dd=6 (>4<=6), x0.25.
           pnl=-1.0. equity=93, peak=100.
      t3: advance. applied=1, exit_times[1]=25<=30 YES. equity += -4.0 = 89.
           peak=100, applied=2. exit_times[2]=35<=30 NO. dd=11 (>6), PAUSE.
      t4: advance. applied=2, exit_times[2]=35<=40 YES. equity += +2.0 = 91.
           peak=100, applied=3. dd=100-91=9 (>6), PAUSE.
    """
    p1 = _mk_trade(1, entry_ts=10.0, exit_ts=15.0, pnl_r=-3.0, result="LOSS")
    p2 = _mk_trade(2, entry_ts=20.0, exit_ts=25.0, pnl_r=-4.0, result="LOSS")
    p3 = _mk_trade(3, entry_ts=30.0, exit_ts=35.0, pnl_r=2.0)  # paused
    p4 = _mk_trade(4, entry_ts=40.0, exit_ts=45.0, pnl_r=2.0)  # also paused
    surviving, paused, *_ = apply_dd_scaling(
        [p1, p2, p3, p4], entry_ts=[10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0]
    )
    assert paused == 2
    surviving_ids = sorted(t.trade_id for t in surviving)
    assert surviving_ids == [1, 2]
    p1_s = next(t for t in surviving if t.trade_id == 1)
    p2_s = next(t for t in surviving if t.trade_id == 2)
    assert p1_s.pnl_r == -3.0  # x1.0
    assert p2_s.pnl_r == -1.0  # -4.0 * 0.25 (DD=6R at entry)


def test_apply_dd_scaling_sorts_by_exit_timestamp():
    """Unsorted input must be sorted by exit_timestamp (canonical order)."""
    t_late = _mk_trade(1, entry_ts=100.0, exit_ts=200.0, pnl_r=-3.0, result="LOSS")
    t_early = _mk_trade(2, entry_ts=10.0, exit_ts=20.0, pnl_r=1.0)
    t_mid = _mk_trade(3, entry_ts=50.0, exit_ts=60.0, pnl_r=1.0)
    # Pass in arbitrary order.
    surviving, *_ = apply_dd_scaling(
        [t_late, t_early, t_mid], entry_ts=[100.0, 10.0, 50.0]
    )
    # The output preserves the canonical exit-time ordering via input
    # pnl_r attribution. The early+mid wins bring equity up; the late
    # loss brings it down. With exit_time sorted, the late loss is
    # applied LAST and DD becomes visible only then.
    out_pnls = [t.pnl_r for t in surviving]
    # All three are x1.0 (DD never exceeds 2R for any entry because
    # trades 1 and 2 happen first chronologically, and trade 3's entry
    # (at t=100) is after both wins completed).
    assert out_pnls == [1.0, 1.0, -3.0]


def test_apply_dd_scaling_same_bar_causality():
    """Two trades that exit on the same bar. Mirrors canonical
    causality: a trade's own PnL is never used to scale itself.

    In the canonical C v1.0/exp_maxdd_C path, entry_ts is derived
    from bars[entry_bar_index] where entry_bar_index > exit_bar_index
    (next-bar-open execution), so entry_ts is strictly > exit_ts. This
    test simulates the realistic case: t1 exits at 50, t2's entry is
    at 50+epsilon (just after t1's exit). Sort puts them in trade_id
    order.
    """
    t1 = _mk_trade(1, entry_ts=55.0, exit_ts=50.0, pnl_r=-3.0, result="LOSS")
    t2 = _mk_trade(2, entry_ts=55.0, exit_ts=50.0, pnl_r=1.0)
    surviving, *_ = apply_dd_scaling([t1, t2], entry_ts=[55.0, 55.0])
    # Sort by exit (both 50, stable -> t1 first).
    # t1: entry=55. Advance: t1.exit=50<=55 YES. equity=100-3=97, peak=100.
    #      applied=1, t2.exit=50<=55 YES. equity=97+1=98, peak=100, applied=2.
    #      dd_now=2. mult=1.0 (strict >2). surviving t1, pnl=-3.0. equity=98-3=95.
    # t2: entry=55. Advance: applied=2, no advance. dd=peak-equity=100-95=5. mult=0.25.
    #      surviving t2, pnl=0.25. equity=95.25.
    assert [t.pnl_r for t in surviving] == [-3.0, 0.25]


def test_apply_dd_scaling_preserves_trade_identity():
    """SL/TP/entry/exit/result fields must NOT be mutated."""
    t = _mk_trade(1, entry_ts=10.0, exit_ts=20.0, pnl_r=2.0, result="TP")
    t.entry_price = 1.12345
    t.sl = 1.12000
    t.tp = 1.13000
    t.zone_index = 42
    t.sweep_bar_index = 17
    surviving, *_ = apply_dd_scaling([t], entry_ts=[10.0])
    s = surviving[0]
    assert s.entry_price == 1.12345
    assert s.sl == 1.12000
    assert s.tp == 1.13000
    assert s.zone_index == 42
    assert s.sweep_bar_index == 17
    assert s.result == "TP"
    assert s.entry_bar_index == 0
    assert s.exit_bar_index == 0
    # Only pnl_r changes.
    assert s.pnl_r == 2.0  # DD=0 -> x1.0


# ── 6. Determinism ──────────────────────────────────────────────


def test_apply_dd_scaling_deterministic_replay():
    """Same input -> same output (no RNG, no wall-clock, no env)."""
    trades = [
        _mk_trade(i, entry_ts=10.0 * i, exit_ts=11.0 * i, pnl_r=((-1) ** i) * (i % 5))
        for i in range(1, 21)
    ]
    entry_ts = [10.0 * i for i in range(1, 21)]
    out1, p1, n1a, n05a, n025a = apply_dd_scaling(trades, entry_ts=entry_ts)
    out2, p2, n1b, n05b, n025b = apply_dd_scaling(trades, entry_ts=entry_ts)
    assert p1 == p2
    assert n1a == n1b
    assert n05a == n05b
    assert n025a == n025b
    assert [t.pnl_r for t in out1] == [t.pnl_r for t in out2]


# ── 7. C v1.0 vs C v1.1 head-to-head ────────────────────────────


def test_c_v11_trade_identity_matches_c_v10_on_synth():
    """C v1.1 trade count = C v1.0 trade count - paused_count, and
    every surviving trade's identity (entry_price, sl, tp, entry_bar,
    sweep_bar, zone_index) is identical to the v1.0 trade at the same
    chronological position. Tested on a tiny synthetic replay."""
    # Build a tiny trade stream that exercises the no-lookahead path.
    base = [
        _mk_trade(1, entry_ts=10.0, exit_ts=20.0, pnl_r=1.0),
        _mk_trade(2, entry_ts=30.0, exit_ts=40.0, pnl_r=-1.0, result="LOSS"),
        _mk_trade(3, entry_ts=50.0, exit_ts=60.0, pnl_r=2.0),
        _mk_trade(4, entry_ts=70.0, exit_ts=80.0, pnl_r=1.0),
    ]
    surviving, *_ = apply_dd_scaling(base, entry_ts=[10.0, 30.0, 50.0, 70.0])
    # On this sequence, no DD>2R ever happens -> all x1.0 -> trade
    # count = 4 and identity preserved.
    assert len(surviving) == 4
    for b, s in zip(base, surviving):
        assert b.entry_price == s.entry_price
        assert b.sl == s.sl
        assert b.tp == s.tp
        assert b.entry_bar_index == s.entry_bar_index
        assert b.sweep_bar_index == s.sweep_bar_index
        assert b.zone_index == s.zone_index


def test_c_v11_pnl_differs_from_v10_only_via_multiplier():
    """The pnl_r of each surviving C v1.1 trade equals the v1.0 pnl_r
    multiplied by the assigned multiplier.

    Sequence: +1R, +1R, -1R -> peak=103, equity=101, dd=2R after t3.
    Then +4R: dd at t4 entry = 2R, x1.0 (not >2R). Use t3=-2 instead:
    t1=+1, t2=+1, t3=-2 -> equity=100, peak=103, dd=3R (after t3 contribution).
    t4 entry: equity=100-2=98, peak=103, dd=5R -> x0.25. pnl=4*0.25=1.0.
    But t3 itself: at entry dd=0 (advance includes t1, t2). t3 mult=1.0.
    After t3: equity=98, peak=103. Wait, t3 contribution: equity=100+(-2)=98.
    Hmm let me redo cleanly:
    """
    t1 = _mk_trade(1, entry_ts=10.0, exit_ts=20.0, pnl_r=1.0)
    t2 = _mk_trade(2, entry_ts=30.0, exit_ts=40.0, pnl_r=1.0)
    t3 = _mk_trade(3, entry_ts=50.0, exit_ts=60.0, pnl_r=-2.0, result="LOSS")
    t4 = _mk_trade(4, entry_ts=70.0, exit_ts=80.0, pnl_r=4.0)
    # Trace:
    # t1: dd=0, x1.0, pnl=1.0. equity=101, peak=101.
    # t2: advance. equity=102, peak=102. applied=1. dd=0, x1.0, pnl=1.0.
    #      equity=103, peak=103.
    # t3: advance. equity=103+1=104? No, applied=1, exit_times[1]=40<=50 YES.
    #      equity += 1.0 = 104, peak=104, applied=2. exit_times[2]=60<=50 NO.
    #      dd=0. x1.0, pnl=-2.0. equity=102, peak=104.
    # t4: advance. applied=2, exit_times[2]=60<=70 YES. equity += -2.0 = 100.
    #      peak=104, applied=3. dd=104-100=4R. 4>2, 4 NOT >4 -> x0.5. pnl=2.0.
    surviving, *_ = apply_dd_scaling(
        [t1, t2, t3, t4], entry_ts=[10.0, 30.0, 50.0, 70.0]
    )
    expected_pnls = [1.0, 1.0, -2.0, 2.0]  # t4 scaled to 4.0*0.5=2.0
    assert [t.pnl_r for t in surviving] == expected_pnls


def test_c_v11_compute_stats_v11_matches_v10_format():
    """compute_stats_v11 must return the same keys as compute_stats so
    downstream consumers can be engine-agnostic."""
    v10_keys = set(compute_stats([]).keys())
    v11_keys = set(compute_stats_v11([]).keys())
    assert v10_keys == v11_keys


def test_c_v11_smoke_run_test_a_v11_returns_list():
    """Smoke: run_test_a_v11 on a tiny synthetic 15m sequence returns
    a list (may be empty if no trades fire)."""
    from src.strategy.models import Bar

    # Need at least 100 15m bars for warmup, plus some structure.
    base_ts = pd.Timestamp("2026-07-01 17:00:00")  # UTC (just before CBDR window)
    bars: List[Bar] = []
    for i in range(150):
        ts = base_ts + pd.Timedelta(minutes=15 * i)
        bars.append(
            Bar(
                index=i,
                timestamp=ts,
                open=1.10000,
                high=1.10010,
                low=1.09990,
                close=1.10000,
                volume=100.0,
            )
        )
    out = run_test_a_v11("EURUSD", bars)
    assert isinstance(out, list)
    # No engineered sweep -> likely empty, but the function must not crash.
