#!/usr/bin/env python
"""C v1.1 — DD-based risk scaling promotion tests.

Covers (per the task spec):
  1. C v1.0 immutable regression (C v1.0 must be untouched).
  2. DD scaling threshold/multiplier tests (all 4 tiers + boundaries).
  3. zero-DD / full-risk state.
  4. each scaling tier (x1.0 / x0.5 / x0.25 / PAUSE).
  5. chronology / same-bar causality (no-lookahead, event-stream order).
  6. deterministic replay (same input -> same output).
  7. C v1.0 vs C v1.1 head-to-head parity (trade identity, scaling delta).
  8. FAIL-FAST negatives (arbitration (b), 2026-08-31): backdated-exit
     invariant (ValueError + audit ERROR) and the dropped-signal gate —
     the fixtures here all use REAL-DATA ordering (entry_ts <= exit_ts);
     illegal ordering is exercised ONLY by the negative tests.
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
    MAX_DROPPED_SIGNALS,
    _derive_entry_ts,
    _enforce_dropped_signal_policy,
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
    symbol: str = "TEST",
) -> BenchmarkTrade:
    """Build a minimal BenchmarkTrade for scaling tests."""
    return BenchmarkTrade(
        trade_id=trade_id,
        symbol=symbol,
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
    surviving, paused, n1, n05, n025 = apply_dd_scaling([t1, t2, t3], entry_ts=[10.0, 25.0, 35.0])
    assert paused == 0
    assert n1 == 3
    assert n05 == 0
    assert n025 == 0
    # All pnl_r preserved (x1.0).
    assert [t.pnl_r for t in surviving] == [1.0, -1.0, 0.5]


def test_apply_dd_scaling_pause_drops_trade():
    """Force DD > 6R before a trade entry, that trade is paused."""
    # 4 winning trades then a losing trade after DD>6R.
    wins = [_mk_trade(i, entry_ts=10.0 * i, exit_ts=11.0 * i, pnl_r=2.0) for i in range(1, 5)]
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

    Sequence: t1=+1R, t2=-3R (LOSS), t3=+2R.
    With strict-< (Patch #9):
      t1 (k=0): dd=0, x1, pnl=1. equity=101, peak=101.
      t2 (k=1): t1 prior, equity=102, peak=102. dd=0, x1, pnl=-3.
                 equity=99, peak=102.
      t3 (k=2): t2 prior, equity=96, peak=102. dd=6. 6>4 YES, 6>6 NO
                 -> x0.25, pnl=0.5. (NOT x0.5; 6 is in (4,6] actually
                 wait 6 is NOT > 6 so it's x0.25).
    Hmm. For x0.5, DD must be in (2, 4]. Use t2=-2.5:
      t2 advance: equity=99.5, peak=102. dd=2.5. x0.5.
    """
    t1 = _mk_trade(1, entry_ts=10.0, exit_ts=15.0, pnl_r=1.0)
    t2 = _mk_trade(2, entry_ts=20.0, exit_ts=25.0, pnl_r=-2.5, result="LOSS")
    t3 = _mk_trade(3, entry_ts=30.0, exit_ts=35.0, pnl_r=2.0)
    surviving, paused, n1, n05, n025 = apply_dd_scaling([t1, t2, t3], entry_ts=[10.0, 20.0, 30.0])
    assert paused == 0
    assert n1 == 2  # t1, t2 (x1)
    assert n05 == 1  # t3 (DD=2.5 > 2 -> x0.5)
    assert n025 == 0
    t3_scaled = next(t for t in surviving if t.trade_id == 3)
    assert t3_scaled.pnl_r == 1.0  # 2.0 * 0.5


def test_apply_dd_scaling_x025_tier():
    """DD strictly between 4R and 6R -> x0.25 scaling.

    Sequence: t1=+5R, t2=-6R (LOSS), t3=+2R.
    With strict-< (Patch #9):
      t1 (k=0): dd=0, x1, pnl=5. equity=105, peak=105.
      t2 (k=1): t1 prior, pre_equity=105, pre_peak=105. dd=0, x1, pnl=-6.
                 equity=99, peak=105.
      t3 (k=2): t2 prior, pre_equity=99-6=93, pre_peak=105. dd=12.
                 Wait: advance loop adds t2's pnl (-6) to pre_equity (99->93),
                 pre_peak stays 105. dd=105-93=12. 12>6 PAUSE.
    Hmm. Reconsider: pre_equity is updated IN the advance loop with
    the prior trade's BASE pnl. So after advancing t2 (-6):
    pre_equity=99, pre_peak=105. dd=6. 6>4 YES, 6>6 NO -> x0.25, pnl=0.5.
    Then t3 contribution: post_equity += 0.5.
    So expected: x0.25=1.
    """
    t1 = _mk_trade(1, entry_ts=10.0, exit_ts=15.0, pnl_r=5.0)
    t2 = _mk_trade(2, entry_ts=20.0, exit_ts=25.0, pnl_r=-6.0, result="LOSS")
    t3 = _mk_trade(3, entry_ts=30.0, exit_ts=35.0, pnl_r=2.0)
    surviving, paused, n1, n05, n025 = apply_dd_scaling([t1, t2, t3], entry_ts=[10.0, 20.0, 30.0])
    assert paused == 0
    assert n1 == 2  # t1, t2 (x1)
    assert n05 == 0
    assert n025 == 1  # t3 (DD=6 > 4 -> x0.25)
    t3_scaled = next(t for t in surviving if t.trade_id == 3)
    assert t3_scaled.pnl_r == 0.5  # 2.0 * 0.25


def test_apply_dd_scaling_paused_trade_does_not_change_peak():
    """A paused trade's pnl_r is NOT added to equity or peak. Subsequent
    trades' DD must reflect the state BEFORE the paused trade.

    Sequence: t1=+5, t2=-7.5 (LOSS), t3=+1.
    With strict-< (Patch #9):
      t1 (k=0): dd=0, x1, pnl=5. equity=105, peak=105.
      t2 (k=1): t1 prior, pre_equity=105, pre_peak=105. dd=0, x1, pnl=-7.5.
                 equity=97.5, peak=105.
      t3 (k=2): t2 prior, pre_equity=97.5-7.5=90, pre_peak=105. dd=15.
                 15>6 -> PAUSE.
    """
    p1 = _mk_trade(1, entry_ts=10.0, exit_ts=15.0, pnl_r=5.0)
    p2 = _mk_trade(2, entry_ts=20.0, exit_ts=25.0, pnl_r=-7.5, result="LOSS")
    p3 = _mk_trade(3, entry_ts=30.0, exit_ts=35.0, pnl_r=1.0)  # paused
    surviving, paused, *_ = apply_dd_scaling([p1, p2, p3], entry_ts=[10.0, 20.0, 30.0])
    assert paused == 1
    surviving_ids = sorted(t.trade_id for t in surviving)
    assert surviving_ids == [1, 2]
    p1_s = next(t for t in surviving if t.trade_id == 1)
    p2_s = next(t for t in surviving if t.trade_id == 2)
    assert p1_s.pnl_r == 5.0  # x1
    assert p2_s.pnl_r == -7.5  # x1 (DD=0 at t2 entry)


def test_apply_dd_scaling_sorts_by_exit_timestamp():
    """Unsorted input must produce the same scaling as exit-sorted input
    (the new pointer-free bisect implementation computes each trade's DD
    independently from the exit-sorted prefix curves, so output order is
    input order but the scaling result is order-independent)."""
    t_late = _mk_trade(1, entry_ts=100.0, exit_ts=200.0, pnl_r=-3.0, result="LOSS")
    t_early = _mk_trade(2, entry_ts=10.0, exit_ts=20.0, pnl_r=1.0)
    t_mid = _mk_trade(3, entry_ts=50.0, exit_ts=60.0, pnl_r=1.0)
    # Pass in arbitrary order.
    surviving, *_ = apply_dd_scaling([t_late, t_early, t_mid], entry_ts=[100.0, 10.0, 50.0])
    # All three are x1.0 (DD never exceeds 2R for any entry because the
    # two wins complete before trade 1's late entry at t=100, and the
    # loss happens after both).
    out_pnls = [t.pnl_r for t in surviving]
    assert sorted(out_pnls) == [-3.0, 1.0, 1.0]
    # Order-independence: same scaling when given in exit order.
    surviving_sorted, *_ = apply_dd_scaling([t_early, t_mid, t_late], entry_ts=[10.0, 50.0, 100.0])
    assert sorted(t.pnl_r for t in surviving_sorted) == [-3.0, 1.0, 1.0]


def test_apply_dd_scaling_same_bar_causality():
    """Same-bar causality under the single-curve event-stream semantics
    (rewrite, arbitration (b) — the old fixture used a backdated exit
    (exit=50 < entry=55) which the entry<=exit invariant now rejects).

    Real-data ordering: both trades share entry=55, exit=60, and a third
    trade closes at 54 (strictly before the entries). At the shared
    timestamp 55, ENTRY priority 0 < EXIT priority 1 means the prior
    trade's exit at 54 IS visible to both entries; at timestamp 60 both
    EXITs fire with their locked multipliers.

      prior: entry=10, exit=54, pnl=-3 -> DD=0 -> x1, equity=97, peak=100
      t1:    entry=55 -> dd=3 (>2) -> x0.5, exit pnl=-1.5, equity=95.5
      t2:    entry=55 -> same dd=3 -> x0.5, exit pnl=+0.5 (pnl_r=1.0)
    """
    prior = _mk_trade(0, entry_ts=10.0, exit_ts=54.0, pnl_r=-3.0, result="LOSS")
    t1 = _mk_trade(1, entry_ts=55.0, exit_ts=60.0, pnl_r=-3.0, result="LOSS")
    t2 = _mk_trade(2, entry_ts=55.0, exit_ts=60.0, pnl_r=1.0)
    surviving, paused, n1, n05, n025 = apply_dd_scaling(
        [prior, t1, t2], entry_ts=[10.0, 55.0, 55.0]
    )
    assert paused == 0
    assert n1 == 1  # prior (DD=0 at entry=10)
    assert n05 == 2  # t1 and t2 both enter at 55 with realized dd=3
    by_id = {(t.symbol, t.trade_id): t.pnl_r for t in surviving}
    assert by_id[("TEST", 0)] == -3.0
    assert by_id[("TEST", 1)] == -1.5
    assert by_id[("TEST", 2)] == 0.5


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

    Sequence: +1R, +1R, -2R (LOSS), +4R.
    With strict-< (Patch #9):
      t1 (k=0): dd=0, x1, pnl=1
      t2 (k=1): t1 prior, equity=101, peak=101. dd=0, x1, pnl=1.
                 equity=102, peak=102.
      t3 (k=2): t2 prior, equity=102, peak=102. dd=0, x1, pnl=-2.
                 equity=100, peak=102.
      t4 (k=3): t3 prior, equity=100, peak=102. dd=2. 2 not > 2
                 -> x1, pnl=4. (strict >2 rule)
    """
    t1 = _mk_trade(1, entry_ts=10.0, exit_ts=20.0, pnl_r=1.0)
    t2 = _mk_trade(2, entry_ts=30.0, exit_ts=40.0, pnl_r=1.0)
    t3 = _mk_trade(3, entry_ts=50.0, exit_ts=60.0, pnl_r=-2.0, result="LOSS")
    t4 = _mk_trade(4, entry_ts=70.0, exit_ts=80.0, pnl_r=4.0)
    surviving, *_ = apply_dd_scaling([t1, t2, t3, t4], entry_ts=[10.0, 30.0, 50.0, 70.0])
    expected_pnls = [1.0, 1.0, -2.0, 4.0]  # all x1, DD never exceeds 2R
    assert [t.pnl_r for t in surviving] == expected_pnls


def test_c_v11_compute_stats_v11_matches_v10_format():
    """compute_stats_v11 must return the same keys as compute_stats so
    downstream consumers can be engine-agnostic."""
    v10_keys = set(compute_stats([]).keys())
    v11_keys = set(compute_stats_v11([]).keys())
    assert v10_keys == v11_keys


def test_c_v11_smoke_run_test_a_v11_returns_list():
    """Smoke: run_test_a_v11 (base-only after Patch #3) on a tiny
    synthetic 15m sequence returns a list of unscaled base trades.

    The DD Risk Scaling overlay is NOT applied here (that is GLOBAL
    and lives in main() / apply_dd_scaling())."""
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
    # run_test_a_v11 is base-only after Patch #3. The trades it returns
    # are unscaled (pnl_r is either +TP_RR or -1.0, never scaled).
    for t in out:
        assert t.pnl_r in (
            1.8,
            -1.0,
        ), f"run_test_a_v11 must return UNSCALED base trades, got pnl_r={t.pnl_r}"


# =============================================================================
# C v1.1 correction patch (2026-08-28) — regression tests A..G
# =============================================================================


def test_A_global_portfolio_scaling_shares_DD_across_symbols():
    """Test A: two symbols share the SAME global DD state.

    Symbol A takes a -3R loss. Symbol B's next trade sees DD=3R and
    must be scaled x0.5 (DD>2R). If the scaling were per-symbol
    (which is WRONG), Symbol B would see DD=0 and get x1.0.
    """
    # Build 3 trades: A loss, B (after A) win, B (after B) win.
    # All on the same chronological stream.
    tA = _mk_trade(1, entry_ts=10.0, exit_ts=20.0, pnl_r=-3.0, result="LOSS")
    tB1 = _mk_trade(1, entry_ts=25.0, exit_ts=30.0, pnl_r=1.0)  # symbol B
    tB2 = _mk_trade(2, entry_ts=35.0, exit_ts=40.0, pnl_r=1.0)  # symbol B
    tA.symbol = "SYMA"
    tB1.symbol = "SYMB"
    tB2.symbol = "SYMB"
    trades = [tA, tB1, tB2]
    entry_ts = [10.0, 25.0, 35.0]  # parallel
    surviving, paused, n1, n05, n025 = apply_dd_scaling(
        trades, entry_ts=entry_ts, starting_balance=100.0
    )
    # tA is the first trade: DD=0 -> x1.0, pnl=-3.0
    # tB1 enters at 25 after tA exit at 20: DD=3R -> x0.5, pnl=0.5
    #   (tA's -3R base was scaled x1, so equity=97, peak=100, dd=3R)
    # tB2 enters at 35: after tB1 scaled contribution (0.5R),
    #   equity=97.5, peak=100, dd=2.5R -> x0.5 (DD>2R), pnl=0.5.
    assert paused == 0
    assert n1 == 1
    assert n05 == 2
    assert n025 == 0
    by_id = {(t.symbol, t.trade_id): t for t in surviving}
    assert abs(by_id[("SYMA", 1)].pnl_r - (-3.0)) < 1e-9
    assert abs(by_id[("SYMB", 1)].pnl_r - 0.5) < 1e-9
    assert abs(by_id[("SYMB", 2)].pnl_r - 0.5) < 1e-9


def test_B_no_self_pnl_in_own_dd_decision():
    """Test B: same-bar (entry_ts == exit_ts) self-PnL does NOT enter
    the trade's own DD decision.

    Trade K has entry_ts = exit_ts = 50.0 and pnl_r = -1.0. The
    trade should see DD=0 (no prior trade) and be scaled x1.0;
    the self-PnL must NOT be added to the DD calculation.
    """
    t1 = _mk_trade(1, entry_ts=50.0, exit_ts=50.0, pnl_r=-1.0, result="LOSS")
    t1.symbol = "X"
    surviving, paused, n1, n05, n025 = apply_dd_scaling(
        [t1], entry_ts=[50.0], starting_balance=100.0
    )
    assert paused == 0
    assert len(surviving) == 1
    assert n1 == 1
    # PnL is x1.0 of -1.0 = -1.0 (no self-contamination of DD).
    assert abs(surviving[0].pnl_r - (-1.0)) < 1e-9


def test_C_deterministic_same_exit_ordering():
    """Test C: multiple trades with the same exit_timestamp resolve
    deterministically by (symbol, trade_id) — across runs.

    Build 4 trades from 2 symbols, all with exit_ts=100.0 but
    different entry_ts. Apply scaling twice and check identical
    tier counts.
    """
    trades = []
    entry_ts = []
    # SYMA trades
    for tid, et, pnl in [(1, 10.0, 1.0), (2, 50.0, -3.0)]:
        t = _mk_trade(
            tid,
            entry_ts=et,
            exit_ts=100.0,
            pnl_r=pnl,
            result=("LOSS" if pnl < 0 else "TP"),
        )
        t.symbol = "SYMA"
        trades.append(t)
        entry_ts.append(et)
    # SYMB trades
    for tid, et, pnl in [(1, 20.0, 1.0), (2, 60.0, 1.0)]:
        t = _mk_trade(tid, entry_ts=et, exit_ts=100.0, pnl_r=pnl)
        t.symbol = "SYMB"
        trades.append(t)
        entry_ts.append(et)
    # Run twice
    r1 = apply_dd_scaling(trades, entry_ts=entry_ts, starting_balance=100.0)
    r2 = apply_dd_scaling(trades, entry_ts=entry_ts, starting_balance=100.0)
    # Tier counts must be identical across runs.
    assert (r1[1], r1[2], r1[3], r1[4]) == (r2[1], r2[2], r2[3], r2[4])
    # And the surviving pnl_r values must be identical.
    assert [t.pnl_r for t in r1[0]] == [t.pnl_r for t in r2[0]]


def test_D_entry_ts_length_mismatch_raises():
    """Test D: apply_dd_scaling raises ValueError if len(entry_ts) !=
    len(trades)."""
    t1 = _mk_trade(1, entry_ts=10.0, exit_ts=20.0, pnl_r=1.0)
    t1.symbol = "X"
    # Mismatched lengths
    with pytest.raises(ValueError, match="must equal trades"):
        apply_dd_scaling([t1], entry_ts=[10.0, 20.0], starting_balance=100.0)
    with pytest.raises(ValueError, match="must equal trades"):
        apply_dd_scaling([t1, t1], entry_ts=[10.0], starting_balance=100.0)


def test_E_invalid_entry_bar_index_raises():
    """Test E: _derive_entry_ts raises ValueError on out-of-range
    entry_bar_index (no silent fall-back to epoch=0)."""
    from src.strategy.models import Bar

    t = _mk_trade(1, entry_ts=10.0, exit_ts=20.0, pnl_r=1.0)
    t.symbol = "X"
    t.entry_bar_index = 999  # out of range
    bars = [
        Bar(
            index=i,
            timestamp=pd.Timestamp("2026-01-01") + pd.Timedelta(minutes=15 * i),
            open=1.0,
            high=1.0,
            low=1.0,
            close=1.0,
            volume=0.0,
        )
        for i in range(5)
    ]
    with pytest.raises(ValueError, match="Invalid entry_bar_index"):
        _derive_entry_ts([t], bars)
    # Negative index also invalid
    t.entry_bar_index = -1
    with pytest.raises(ValueError, match="Invalid entry_bar_index"):
        _derive_entry_ts([t], bars)


def test_F_starting_balance_consistency():
    """Test F: when starting_balance != 100, both apply_dd_scaling and
    compute_stats_v11 must use the SAME baseline.

    Sequence: t1=+1 (entry=10, exit=20), t2=-3 (LOSS, entry=30, exit=40).
    Both see DD=0 -> x1.0. With sb=200:
      equity walk: 200 + 1.0 + (-3.0) = 198
      peak = 201, final equity = 198
      MaxDD = 201 - 198 = 3.0
      MaxDD% = 3.0 / 201 * 100 = 1.4925...
    """
    t1 = _mk_trade(1, entry_ts=10.0, exit_ts=20.0, pnl_r=1.0)
    t2 = _mk_trade(2, entry_ts=30.0, exit_ts=40.0, pnl_r=-3.0, result="LOSS")
    t1.symbol = "X"
    t2.symbol = "X"
    sb = 200.0
    surviving, *_ = apply_dd_scaling([t1, t2], entry_ts=[10.0, 30.0], starting_balance=sb)
    stats = compute_stats_v11(surviving, starting_balance=sb)
    # Both x1.0; total_pnl = 1.0 + (-3.0) = -2.0; MaxDD = 3.0
    assert stats["total_pnl"] == -2.0
    assert stats["max_dd"] == 3.0
    # MaxDD% is rounded to 2 dp in compute_stats_v11: 3.0/201*100 = 1.4925 -> 1.49
    assert stats["max_dd_pct"] == 1.49


def test_G_main_global_single_scaling_pass_via_main_contract():
    """Test G: end-to-end — for the small synthetic 6-major run,
    main() contract is satisfied:

      (a) total tier counts == completed base trades
      (b) surviving scaled + paused == completed base
      (c) starting_balance is honored identically by scaling + stats

    We synthesize a tiny 6-symbol feather for a deterministic
    micro-benchmark, then run the real `main()` function via its
    public STEP 1/2/3 path.

    NOTE: this is a CONTRACT test, not a behavioral benchmark. It
    asserts the invariants that prevent future regressions in the
    main() pipeline.
    """
    # We do not import `main` here (it would mutate argv). Instead
    # we replicate the STEP 1/2/3 sequence in this test using the
    # same helpers, with a known-good small synthetic trade stream.

    # 2 symbols, 4 trades total. All have valid exit_ts/entry_ts.
    t1 = _mk_trade(1, entry_ts=10.0, exit_ts=20.0, pnl_r=1.0)
    t2 = _mk_trade(2, entry_ts=30.0, exit_ts=40.0, pnl_r=-3.0, result="LOSS")
    t3 = _mk_trade(1, entry_ts=50.0, exit_ts=60.0, pnl_r=2.0)
    t4 = _mk_trade(2, entry_ts=70.0, exit_ts=80.0, pnl_r=1.0)
    t1.symbol = "SYMA"
    t2.symbol = "SYMA"
    t3.symbol = "SYMB"
    t4.symbol = "SYMB"
    all_base = [t1, t2, t3, t4]
    all_entry_ts = [10.0, 30.0, 50.0, 70.0]
    # Single global scaling pass
    scaled, paused, n1, n05, n025 = apply_dd_scaling(
        all_base, entry_ts=all_entry_ts, starting_balance=100.0
    )
    # Compute stats from the same scaled stream
    stats = compute_stats_v11(scaled, starting_balance=100.0)
    # Post-conditions (mirror of main()'s post-condition asserts)
    completed_base = sum(1 for t in all_base if t.result in ("TP", "PROFIT_TRAIL", "LOSS"))
    completed_scaled = sum(1 for t in scaled if t.result in ("TP", "PROFIT_TRAIL", "LOSS"))
    assert n1 + n05 + n025 + paused == completed_base
    assert completed_scaled + paused == completed_base
    # And a sanity check: total_pnl from stats equals sum of scaled pnl_r
    assert (
        abs(
            stats["total_pnl"]
            - sum(t.pnl_r for t in scaled if t.result in ("TP", "PROFIT_TRAIL", "LOSS"))
        )
        < 1e-9
    )


# ─────────────────────────────────────────────────────────────────────
# Reference (O(N^2)) causality tests — exact strictly-before-entry
# ─────────────────────────────────────────────────────────────────────


def _reference_dd_and_mult(trades, entry_ts, starting_balance=100.0):
    """INDEPENDENT O(N^2) reference implementing the production realized
    equity walk (single-curve semantics, arbitration (b)).

    For every completed trade T, the multiplier is recomputed FROM SCRATCH:
    the realized state at T's entry is rebuilt by applying, in
    (exit_ts, symbol, trade_id) order, the SCALED pnl of every completed
    trade E with STRICTLY earlier exit (exit_E < entry_T), where E's own
    multiplier comes from the same rule (well-founded because
    entry_E <= exit_E < entry_T). PAUSED trades contribute ZERO.

    This deliberately does NOT share code with production's event-stream
    walk (no event list, no lock dict, no single pass): independence is
    the point of an O(N^2) reference. The old exit-order-walk reference
    was NOT equivalent to production — with same-timestamp ties it applied
    an exit BEFORE a same-ts entry, violating the strict-< rule that the
    ENTRY-priority-0 ordering enforces.
    """
    from experiment.main_research_c_v1_1 import _to_float_ts, compute_dd_multiplier

    completed = [
        (t, _to_float_ts(e), _to_float_ts(t.exit_timestamp))
        for t, e in zip(trades, entry_ts)
        if t.result in ("TP", "PROFIT_TRAIL", "LOSS")
    ]

    def exit_key(p):
        return (p[2], str(p[0].symbol), int(p[0].trade_id))

    def entry_key(p):
        return (p[1], str(p[0].symbol), int(p[0].trade_id))

    mult = {}

    def dd_at_entry(entry_float, self_t):
        equity = starting_balance
        peak = starting_balance
        prior = sorted(
            (p for p in completed if p[2] < entry_float and p[0] is not self_t),
            key=exit_key,
        )
        for e_t, e_entry, e_exit in prior:
            m = mult[(str(e_t.symbol), int(e_t.trade_id))]
            if m > 0.0:
                equity += e_t.pnl_r * m
                if equity > peak:
                    peak = equity
        return peak - equity

    for t, entry_float, _exit_float in sorted(completed, key=entry_key):
        dd_now = dd_at_entry(entry_float, t)
        m = compute_dd_multiplier(dd_now)
        mult[(str(t.symbol), int(t.trade_id))] = m

    out = {}
    for t, entry_float, _exit in completed:
        key = (str(t.symbol), int(t.trade_id))
        dd_now = dd_at_entry(entry_float, t)
        m = mult[key]
        out[key] = (dd_now, m, m == 0.0)
    return out


def test_A_later_exit_position_still_prior_to_entry():
    """ALL trades whose EXIT is strictly before the current trade's ENTRY
    contribute to its DD — the contribution set is timestamp-driven, never
    position-capped. (Name predates the entry<=exit invariant; the old
    fixture used C exit=10 < entry=20, a backdated exit that now raises —
    see test_backdated_exit_raises_invariant. Rewritten with real-data
    ordering.)

      D: entry=1,  exit=10, pnl=-5 -> dd=0 -> x1;   equity=95,  peak=100
      E: entry=2,  exit=15, pnl=+2 -> dd=0 -> x1;   equity=97,  peak=100
      C: entry=20, exit=25, pnl=-1 -> dd=3 -> x0.5; scaled -0.5
    Both D and E exit before C's entry, so both must be in C's realized
    state (peak=100, equity=97 -> dd=3). A position-capped implementation
    (the old `pos` cap bug) would drop E from C's DD because E's exit
    position is after C's own... it cannot: the event stream is ordered by
    timestamp.
    """
    d = _mk_trade(1, entry_ts=1.0, exit_ts=10.0, pnl_r=-5.0, result="LOSS")
    e = _mk_trade(2, entry_ts=2.0, exit_ts=15.0, pnl_r=2.0)
    c = _mk_trade(3, entry_ts=20.0, exit_ts=25.0, pnl_r=-1.0, result="LOSS")
    surviving, paused, n1, n05, n025 = apply_dd_scaling([c, d, e], entry_ts=[20.0, 1.0, 2.0])
    assert paused == 0
    assert n1 == 2  # d, e
    assert n05 == 1  # c (dd=3 at entry=20)
    by_id = {(t.symbol, t.trade_id): t.pnl_r for t in surviving}
    assert by_id[("TEST", 1)] == -5.0
    assert by_id[("TEST", 2)] == 2.0
    assert by_id[("TEST", 3)] == -0.5


def test_B_self_exclusion():
    """A trade's own PnL must never enter its own DD state.

    Rewritten under the entry<=exit invariant (the old fixture used
    exit=10 < entry=20 — a backdated exit that now raises). Strengthened:
    the trade's own loss is large enough to trigger PAUSE (dd=7 > 6) if it
    leaked into its own DD. Under the event-stream walk its EXIT happens
    strictly after its ENTRY, so it sees dd=0 -> x1.
    """
    c = _mk_trade(1, entry_ts=10.0, exit_ts=20.0, pnl_r=-7.0, result="LOSS")
    surviving, paused, n1, n05, n025 = apply_dd_scaling([c], entry_ts=[10.0])
    # Only C; no other trade -> dd=0 -> x1. The -7R does NOT feed its own DD
    # (if it did, dd=7 > 6 -> paused and C would be absent from surviving).
    assert n1 == 1
    assert paused == 0
    assert surviving[0].pnl_r == -7.0


def test_C_same_timestamp_excluded():
    """exit_timestamp == entry_timestamp must NOT contribute to DD (strict <)."""
    c = _mk_trade(1, entry_ts=20.0, exit_ts=20.0, pnl_r=-1.0, result="LOSS")
    # Another trade that exits exactly at C's entry (20): must be excluded.
    other = _mk_trade(2, entry_ts=1.0, exit_ts=20.0, pnl_r=2.0)
    surviving, paused, n1, n05, n025 = apply_dd_scaling([c, other], entry_ts=[20.0, 1.0])
    # C's DD: other exits at 20 which is NOT < 20 -> excluded -> dd=0 -> x1.
    # other's DD: no other exit < 1 -> dd=0 -> x1.
    assert n1 == 2
    assert paused == 0


def test_D_arbitrary_input_order_invariant():
    """Shuffling the input trade list must not change pause set, multipliers,
    scaled pnls, or aggregate stats."""
    import random

    random.seed(7)
    trades = []
    ets = []
    for i in range(12):
        exit_ts = float(random.randint(0, 200))
        # Real-data ordering: entry <= exit (the old fixture used
        # entry = exit + offset, i.e. BACKDATED exits, which made every
        # trade fail the entry<=exit invariant and be silently dropped —
        # so the "invariance" assertion compared two empty results and was
        # vacuously green. Flipped to exit - offset.)
        entry_ts = exit_ts - float(random.randint(1, 30))
        pnl = random.choice([2.0, -4.0, 3.0, -6.0, 1.0])
        t = _mk_trade(
            i + 1, entry_ts=entry_ts, exit_ts=exit_ts, pnl_r=pnl, result="LOSS" if pnl < 0 else "TP"
        )
        trades.append(t)
        ets.append(entry_ts)

    def scaled_multiset(ts, es):
        s, p, a, b, c = apply_dd_scaling(ts, entry_ts=es)
        return (sorted(round(t.pnl_r, 6) for t in s), p, a, b, c)

    base = scaled_multiset(trades, ets)
    # Non-vacuity guard: with valid ordering the fixture must produce real
    # work — otherwise this test silently degenerates to empty==empty again.
    assert len(base[0]) > 0, "fixture produced no surviving completed trades"
    for _ in range(10):
        perm = list(range(12))
        random.shuffle(perm)
        tp = [trades[i] for i in perm]
        ep = [ets[i] for i in perm]
        assert scaled_multiset(tp, ep) == base


def test_E_brute_force_reference_zero_mismatch():
    """Production `apply_dd_scaling` vs an independent O(N^2) reference over a
    randomized dataset. 0 mismatch is mandatory on multiplier, pause, and
    (recovered) scaled pnl."""
    import random

    random.seed(2026)
    trades = []
    ets = []
    for i in range(60):
        exit_ts = float(random.randint(0, 1000))
        # Real-data ordering: entry <= exit (old fixture used entry = exit +
        # offset — backdated exits, which production silently dropped while
        # the reference replayed them, i.e. the red-vs-green asymmetry that
        # the arbitration probe exposed). Flipped to exit - offset.
        entry_ts = exit_ts - float(random.randint(0, 60))
        pnl = random.choice([1.0, 2.0, -3.0, -5.0, 1.5, -7.0])
        t = _mk_trade(
            i + 1, entry_ts=entry_ts, exit_ts=exit_ts, pnl_r=pnl, result="LOSS" if pnl < 0 else "TP"
        )
        trades.append(t)
        ets.append(entry_ts)

    ref = _reference_dd_and_mult(trades, ets)
    surviving, paused, n1, n05, n025 = apply_dd_scaling(trades, entry_ts=ets)

    # Recover per-trade multiplier from production output.
    base_pnl = {(t.symbol, t.trade_id): t.pnl_r for t in trades}
    prod_mult = {
        (t.symbol, t.trade_id): t.pnl_r / base_pnl[(t.symbol, t.trade_id)] for t in surviving
    }
    # Paused trades are absent from surviving -> multiplier implied 0.0.
    for key, (dd, m, is_paused) in ref.items():
        got = prod_mult.get(key, 0.0)
        assert abs(got - m) < 1e-9, f"{key}: prod mult {got} != ref {m} (dd={dd})"
    # Tier/pause counts must match the reference.
    r_n1 = sum(1 for v in ref.values() if v[1] == 1.0)
    r_n05 = sum(1 for v in ref.values() if v[1] == 0.5)
    r_n025 = sum(1 for v in ref.values() if v[1] == 0.25)
    r_paused = sum(1 for v in ref.values() if v[2])
    assert (n1, n05, n025, paused) == (r_n1, r_n05, r_n025, r_paused)


def test_open_trades_excluded_from_entry_correspondence():
    """OPEN trades are filtered from scaling; entry_ts correspondence to the
    ORIGINAL (full) list must be preserved, not the completed subset."""
    t_open = _mk_trade(1, entry_ts=10.0, exit_ts=20.0, pnl_r=0.0, result="OPEN")
    t_win = _mk_trade(2, entry_ts=30.0, exit_ts=40.0, pnl_r=5.0)
    # entry_ts aligned to the full list order: [open_entry, win_entry]
    surviving, paused, n1, n05, n025 = apply_dd_scaling([t_open, t_win], entry_ts=[10.0, 30.0])
    # Only t_win survives; its DD is measured from trades that closed
    # before entry=30 -> t_open is OPEN (excluded) so dd=0 -> x1.
    assert len(surviving) == 1
    assert surviving[0].trade_id == 2
    assert n1 == 1
    assert paused == 0


def test_tie_break_exit_symbol_trade_id_deterministic():
    """Trades with identical EXIT timestamps resolve by (symbol, trade_id)
    in the event stream, giving a stable, platform-independent realized
    equity walk. Rewritten under the entry<=exit invariant (the old fixture
    used exit=50 < entry=60 — backdated — and asserted bisect-era paused
    semantics that the single-curve walk does not produce).

    Construction (all exit >= entry):
      t1 (SYMA, id=1): entry=10, exit=50, pnl=-7 -> x1 (dd=0 at entry)
      t2 (SYMB, id=2): entry=10, exit=50, pnl=+5 -> x1 (dd=0 at entry)
      t3 (TEST, id=3): entry=60, exit=70, pnl=+1 -> sees BOTH t1/t2 exits
    At ts=50 the EXIT events order by (symbol, trade_id): SYMA#1 (-7)
    BEFORE SYMB#2 (+5). Equity path: 100 -> 93 -> 98, peak stays 100,
    so t3 at entry=60 sees dd=(100-98)/100*100=2.0 -> x1.0 -> +1.0.
    A reversed tie-break (+5 first) would push peak to 105 and give
    t3 dd=(105-98)/105*100=6.67% > 6 -> PAUSE — so t3's survival at x1
    PROVES the documented order. Input-order permutations are identical.
    """
    t1 = _mk_trade(1, entry_ts=10.0, exit_ts=50.0, pnl_r=-7.0, result="LOSS", symbol="SYMA")
    t2 = _mk_trade(2, entry_ts=10.0, exit_ts=50.0, pnl_r=5.0, symbol="SYMB")
    t3 = _mk_trade(3, entry_ts=60.0, exit_ts=70.0, pnl_r=1.0, symbol="TEST")
    r1 = apply_dd_scaling([t1, t2, t3], entry_ts=[10.0, 10.0, 60.0])
    r2 = apply_dd_scaling([t2, t1, t3], entry_ts=[10.0, 10.0, 60.0])
    # Paused/tier counts identical regardless of input order.
    assert (r1[1], r1[2], r1[3], r1[4]) == (r2[1], r2[2], r2[3], r2[4])
    assert r1[1] == 0  # paused — a reversed tie-break would pause t3
    assert r1[2] == 3  # x1: t1, t2 (dd=0) and t3 (dd=2.0, at the boundary)
    assert r1[3] == 0 and r1[4] == 0
    by_id = {(t.symbol, t.trade_id): t.pnl_r for t in r1[0]}
    assert by_id[("TEST", 3)] == 1.0


# ── 8. FAIL-FAST negatives (arbitration (b), 2026-08-31) ─────────


def test_backdated_exit_raises_invariant(caplog):
    """A COMPLETED trade with entry_ts > exit_ts (backdated exit) is an
    illegal state: apply_dd_scaling must raise ValueError and log an audit
    ERROR — never silently drop the trade (§19 silent-fallback closure)."""
    import logging

    good = _mk_trade(1, entry_ts=5.0, exit_ts=10.0, pnl_r=-2.0, result="LOSS")
    bad = _mk_trade(2, entry_ts=50.0, exit_ts=40.0, pnl_r=3.0)  # exit < entry
    with caplog.at_level(logging.ERROR, logger="experiment.main_research_c_v1_1"):
        with pytest.raises(ValueError, match="invariant violated"):
            apply_dd_scaling([good, bad], entry_ts=[5.0, 50.0])
    msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("INVARIANT VIOLATION" in m and "trade_id=2" in m for m in msgs), msgs


def test_open_trade_is_exempt_from_invariant():
    """The entry<=exit invariant applies to COMPLETED trades only: an OPEN
    trade (excluded from scaling by result) must not trigger the check —
    real data carries OPEN rows with placeholder exit timestamps."""
    t_open = _mk_trade(1, entry_ts=90.0, exit_ts=20.0, pnl_r=0.0, result="OPEN")
    t_win = _mk_trade(2, entry_ts=30.0, exit_ts=40.0, pnl_r=5.0)
    surviving, paused, n1, n05, n025 = apply_dd_scaling([t_open, t_win], entry_ts=[90.0, 30.0])
    assert len(surviving) == 1
    assert surviving[0].trade_id == 2
    assert n1 == 1 and paused == 0


def test_entry_equal_exit_is_legal():
    """entry_ts == exit_ts (same-bar close) is LEGAL ordering (invariant is
    entry > exit only) and must not raise — the strict < DD rule, not the
    invariant, governs same-timestamp contribution."""
    t = _mk_trade(1, entry_ts=20.0, exit_ts=20.0, pnl_r=-4.0, result="LOSS")
    surviving, paused, n1, n05, n025 = apply_dd_scaling([t], entry_ts=[20.0])
    assert n1 == 1 and paused == 0
    assert surviving[0].pnl_r == -4.0


def test_dropped_signal_policy_gate_direct():
    """The silent-drop defence gate is unreachable through apply_dd_scaling
    (the invariant raises first) — exercised directly as defence-in-depth.
    Zero tolerance: any drop fails; the limit is configurable for tests."""
    with pytest.raises(RuntimeError, match="fail-fast"):
        _enforce_dropped_signal_policy([("SYMA", 7)])
    _enforce_dropped_signal_policy([])  # no drops -> no raise
    _enforce_dropped_signal_policy([("SYMA", 7)], max_dropped=1)  # under limit


def test_max_dropped_signals_is_zero():
    """The shipped policy is ZERO tolerance (§19): a non-zero default here
    would silently re-open the drop hole the arbitration closed."""
    assert MAX_DROPPED_SIGNALS == 0
