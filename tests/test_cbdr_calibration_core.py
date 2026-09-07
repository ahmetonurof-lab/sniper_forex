"""Unit tests for the CBDR calibration cBot compute engine.

Exercises the REAL compute path in ``src/ctrader/cbot/core.py`` (fed synthetic
OHLC bars) — not a mocked copy — honouring AGENTS.md §4.2. The cTrader
presentation shim (``cbdr_calibration_bot.py``) delegates all maths here, so
these tests cover the logic that determines drawn rectangles/icons.
"""

from __future__ import annotations

import pytest

from src.ctrader.cbot.core import (
    CBDRConfig,
    CBDRTracker,
    Direction,
    FVGHit,
    MiniBar,
    cbdr_day_num,
    clock_hhmm,
    day_num,
    detect_fvg_on,
    fmt_date,
)


def _mb(day: int, hhmm: int, o: float, h: float, l: float, c: float) -> MiniBar:
    total = day * 1440 + (hhmm // 100) * 60 + (hhmm % 100)
    return MiniBar(total, o, h, l, c)


@pytest.fixture
def zero_tol_tracker() -> CBDRTracker:
    """Zero-tolerance tracker isolates sweep predicates from ATR effects."""
    cfg = CBDRConfig(
        atr_period=8,
        sweep_atr_tolerance_mult=0.0,
        sweep_default_tolerance=0.0,
    )
    return CBDRTracker(cfg)


# ---------------------------------------------------------------------------
# Clock helpers
# ---------------------------------------------------------------------------


def test_clock_hhmm_boundaries():
    assert clock_hhmm(0) == 0
    assert clock_hhmm(19 * 60) == 1900
    assert clock_hhmm(23 * 60 + 59) == 2359
    assert clock_hhmm(24 * 60) == 0  # wraps to next day


def test_day_num_floors_negative():
    assert day_num(0) == 0
    assert day_num(1439) == 0
    assert day_num(1440) == 1
    assert day_num(-1) == -1


def test_fmt_date_is_utc_iso():
    assert fmt_date(0) == "1970-01-01"


def test_fmt_date_takes_epoch_minutes_not_day_ordinal():
    """Regression: flush_row/_track_window passed a day ORDINAL to fmt_date,
    collapsing every day_key into Jan 1970. fmt_date's contract is
    epoch-MINUTES — a 2026 day ordinal (~20419) must NOT render as 1970."""
    # 2026-01-01 00:00 UTC == epoch minute 29,904,000 (day ordinal 20454).
    assert fmt_date(20454 * 1440) == "2026-01-01"
    # Distinct consecutive ordinals must yield distinct dates.
    assert fmt_date(20455 * 1440) == "2026-01-02"


# ---------------------------------------------------------------------------
# CBDR cycle key — midnight-spanning window must be ONE cycle
# (canonical parity: session.py::cbdr_day_key)
# ---------------------------------------------------------------------------


def test_cbdr_day_num_rolls_evening_to_window_end_day():
    """19:00 evening bar of day D belongs to the cycle that ENDS day D+1."""
    # 2026-01-05 19:00 UTC -> epoch minute 29,915,400 (day ordinal 20461).
    evening = 20461 * 1440 + 19 * 60
    # 2026-01-06 00:30 UTC — the early-morning tail of the SAME window.
    morning = 20462 * 1440 + 30
    assert cbdr_day_num(evening, 1900, 100) == 20462
    assert cbdr_day_num(morning, 1900, 100) == 20462  # SAME cycle


def test_cbdr_day_num_morning_outside_window_is_plain_day():
    """Midday bar (outside window) keeps its plain civil-day ordinal."""
    midday = 20462 * 1440 + 12 * 60
    assert cbdr_day_num(midday, 1900, 100) == 20462


def test_cbdr_day_num_non_spanning_window_unchanged():
    """For a same-day window (end > start) no rolling occurs."""
    noon = 20462 * 1440 + 12 * 60
    assert cbdr_day_num(noon, 800, 1600) == 20462


def test_tracker_one_body_across_midnight(zero_tol_tracker):
    """THE regression: ingest() must accumulate ONE body over the full
    19:00->01:00 window. Raw civil-day keying split it into a 19:00-23:59
    fragment (locked at midnight) and a separate 00:00-00:59 fragment —
    halving the body and poisoning width% + sweeps."""
    tr = zero_tol_tracker
    # Evening: wide body range (bodies = open/close extremes, NOT wicks).
    tr.ingest(_mb(0, 1900, 1.1000, 1.1010, 1.0990, 1.1005))
    tr.ingest(_mb(0, 2100, 1.1005, 1.1035, 1.1000, 1.1030))  # body_high -> 1.1030 (close)
    # Midnight passes; early morning still in-window: extends body LOW.
    tr.ingest(_mb(1, 30, 1.1020, 1.1025, 1.0965, 1.0970))  # body_low -> 1.0970 (close)
    rows = list(tr.iter_rows())
    assert len(rows) == 1, "evening + morning fragments must be ONE CBDR cycle"
    r = rows[0]
    assert r.body_high == pytest.approx(1.1030)
    assert r.body_low == pytest.approx(1.0970)
    # Lock happens only when the window ENDS (01:00), not at midnight.
    assert r.closed_within is False  # still in-window at 00:30


def test_tracker_body_locks_at_window_end_not_midnight(zero_tol_tracker):
    """A bar at 01:15 (outside window) locks the SAME cycle's body."""
    tr = zero_tol_tracker
    tr.ingest(_mb(0, 1900, 1.1000, 1.1010, 1.0990, 1.1005))
    tr.ingest(_mb(1, 115, 1.1005, 1.1012, 1.0980, 1.0990))  # window over
    rows = list(tr.iter_rows())
    assert len(rows) == 1
    assert rows[0].closed_within is True


# ---------------------------------------------------------------------------
# CBDR accumulation + width %
# ---------------------------------------------------------------------------


def test_body_absorbs_extrema(zero_tol_tracker):
    tr = zero_tol_tracker
    tr.ingest(_mb(0, 1900, 1.1000, 1.1010, 1.0990, 1.1005))
    tr.ingest(_mb(0, 1915, 1.1005, 1.1020, 1.1000, 1.1015))  # widens high
    # Widening the BODY downwards requires lowering open-or-close,
    # not the wick low (CBDR tracks open/close extremes only).
    tr.ingest(_mb(0, 1930, 1.1003, 1.1018, 1.0995, 1.0995))  # body_low -> 1.0995
    rows = list(tr.iter_rows())
    assert len(rows) == 1
    r = rows[0]
    assert r.body_high == pytest.approx(1.1015)
    assert r.body_low == pytest.approx(1.0995)


def test_width_pct_formula_zero_tolerance(zero_tol_tracker):
    tr = zero_tol_tracker
    tr.ingest(_mb(0, 1900, 1.1000, 1.1010, 1.0990, 1.1005))
    tr.ingest(_mb(0, 1915, 1.1005, 1.1020, 1.1000, 1.1015))
    r = list(tr.iter_rows())[0]
    expected = ((r.body_high - r.body_low) / r.body_low) * 100.0
    # flush_row rounds width_pct to 4 dp by design.
    assert r.width_pct == pytest.approx(round(expected, 4))


# ---------------------------------------------------------------------------
# Sweep detection
# ---------------------------------------------------------------------------


def test_no_sweep_while_inside_window(zero_tol_tracker):
    tr = zero_tol_tracker
    tr.ingest(_mb(0, 1900, 1.1000, 1.1010, 1.0990, 1.1005))
    tr.ingest(_mb(0, 1915, 1.1005, 1.1020, 1.1000, 1.1015))
    # Extreme spike INSIDE window must NOT register a sweep.
    tr.ingest(_mb(0, 1930, 1.1015, 1.1050, 1.1000, 1.1001))
    r = list(tr.iter_rows())[0]
    assert r.swept_up is False
    assert r.swept_down is False


def test_bearish_sweep_up_registered(zero_tol_tracker):
    tr = zero_tol_tracker
    tr.ingest(_mb(0, 1900, 1.1000, 1.1010, 1.0990, 1.1005))
    tr.ingest(_mb(0, 1915, 1.1005, 1.1020, 1.1000, 1.1015))
    # Outside window, NEXT morning (day 1, 02:00 — same CBDR cycle as the
    # day-0 evening): high pierces body_high, close settles below -> sweep up.
    tr.ingest(_mb(1, 200, 1.1003, 1.1030, 1.1000, 1.1001))
    r = list(tr.iter_rows())[0]
    assert r.swept_up is True
    assert r.swept_down is False


def test_bullish_sweep_down_registered(zero_tol_tracker):
    tr = zero_tol_tracker
    tr.ingest(_mb(0, 1900, 1.1000, 1.1010, 1.0990, 1.1005))
    tr.ingest(_mb(0, 1915, 1.1005, 1.1020, 1.1000, 1.1015))
    # Outside window, NEXT morning (same cycle): low dips below body_low,
    # close recovers above -> sweep down.
    tr.ingest(_mb(1, 200, 1.1003, 1.1008, 1.0980, 1.1002))
    r = list(tr.iter_rows())[0]
    assert r.swept_down is True
    assert r.swept_up is False


def test_lock_once_across_two_leaving_bars(zero_tol_tracker):
    tr = zero_tol_tracker
    tr.ingest(_mb(0, 1900, 1.1000, 1.1010, 1.0990, 1.1005))
    tr.ingest(_mb(0, 1915, 1.1005, 1.1020, 1.1000, 1.1015))
    tr.ingest(_mb(1, 200, 1.1003, 1.1030, 1.1000, 1.1001))  # sweep up fires
    tr.ingest(_mb(1, 215, 1.1001, 1.1009, 1.0970, 1.0975))  # dip below low
    r = list(tr.iter_rows())[0]
    # First sweep sticks; downstream opposite movement must not flip it.
    assert r.swept_up is True
    assert r.swept_down is False


def test_closed_within_transitions(zero_tol_tracker):
    """Drives the bot's draw decision: active day redraws, closed day draws once."""
    tr = zero_tol_tracker
    tr.ingest(_mb(0, 1900, 1.1000, 1.1010, 1.0990, 1.1005))
    # In-window: body is active (not yet locked) -> bot redraws each bar.
    r = list(tr.iter_rows())[0]
    assert r.closed_within is False
    # Leave window (next morning, same cycle): body locks once -> bot draws
    # it once and stops updating.
    tr.ingest(_mb(1, 200, 1.1003, 1.1008, 1.0990, 1.1002))
    r = list(tr.iter_rows())[0]
    assert r.closed_within is True


# ---------------------------------------------------------------------------
# FVG detection
# ---------------------------------------------------------------------------


def test_bullish_fvg_gap_up():
    seq = [
        MiniBar(100, 1.10, 1.11, 1.09, 1.105),
        MiniBar(101, 1.11, 1.13, 1.105, 1.125),
        MiniBar(102, 1.125, 1.14, 1.115, 1.13),
    ]
    hit = detect_fvg_on(seq, Direction.BULLISH)
    assert isinstance(hit, FVGHit)
    assert hit.direction == Direction.BULLISH
    assert hit.fvg_low == pytest.approx(1.11)  # bar1.high
    assert hit.fvg_high == pytest.approx(1.115)  # bar3.low


def test_bearish_fvg_blocked_by_bull_bias():
    seq = [
        MiniBar(100, 1.14, 1.15, 1.13, 1.145),
        MiniBar(101, 1.13, 1.135, 1.12, 1.125),
        MiniBar(102, 1.12, 1.125, 1.10, 1.105),
    ]
    # bar1.low(1.13) > bar3.high(1.125) -> bearish gap, but bias=bull blocks it.
    assert detect_fvg_on(seq, Direction.BULLISH) is None
    hit = detect_fvg_on(seq, Direction.BEARISH)
    assert hit is not None and hit.direction == Direction.BEARISH


def test_no_fvg_on_overlapping_seq():
    # Overlapping candles: no upward or downward gap between outer highs/lows.
    seq = [
        MiniBar(0, 1.10, 1.12, 1.08, 1.11),
        MiniBar(1, 1.11, 1.13, 1.09, 1.12),
        MiniBar(2, 1.12, 1.14, 1.10, 1.13),
    ]
    assert detect_fvg_on(seq, Direction.NEUTRAL) is None


def test_fvg_requires_three_bars():
    assert detect_fvg_on([MiniBar(0, 1, 2, 0, 1)], Direction.NEUTRAL) is None
