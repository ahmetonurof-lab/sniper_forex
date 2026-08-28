#!/usr/bin/env python
"""PHASE 2 — MARKET DATA / 15M CANDLE FEED — synthetic unit tests.

Covers:
- Canonical 15m aggregation parity (same M1 -> same 15m OHLC/timestamp).
- Duplicate candle detection.
- Missing candle detection.
- Forming vs closed candle distinction.
- Historical warmup.
- Timezone / server-time handling (clock).
- Incremental update (only new 15m candles returned).
"""

from datetime import datetime

import pandas as pd

from src.live.candle_feed import M1CandleFeed, resample_15m
from src.live import clock
from src.strategy.models import Bar


def _m1_bar(ts: pd.Timestamp, o, h, lo, c, v=1.0, index=0) -> Bar:
    return Bar(index=index, timestamp=ts, open=o, high=h, low=lo, close=c, volume=v)


def _m1_series(start: pd.Timestamp, n: int, base=1.0, step=0.0001):
    """Build n consecutive M1 bars starting at `start`."""
    bars = []
    for i in range(n):
        ts = start + pd.Timedelta(minutes=i)
        o = base + i * step
        bars.append(_m1_bar(ts, o, o + 0.0002, o - 0.0001, o + 0.0001, v=1.0, index=i))
    return bars


class _StubDataLayer:
    """Minimal stand-in for MT5DataLayer with a replaceable get_rates."""

    def __init__(self, rates=None):
        self._rates = rates or []

    def get_rates(self, symbol, timeframe="M1", count=100):
        return self._rates


# ---------------------------------------------------------------------------
# Canonical 15m aggregation parity
# ---------------------------------------------------------------------------
class TestResample15mParity:
    def test_single_full_bucket(self):
        """15 M1 bars in one 15m slot -> one 15m bar with correct OHLC."""
        start = pd.Timestamp("2026-01-01 00:00:00")
        m1 = _m1_series(start, 15)
        m15 = resample_15m(m1)
        assert len(m15) == 1
        b = m15[0]
        # Label = FIRST bar timestamp (not grid-aligned)
        assert b.timestamp == start
        assert b.open == m1[0].open
        assert b.close == m1[-1].close
        assert b.high == max(x.high for x in m1)
        assert b.low == min(x.low for x in m1)
        assert b.volume == sum(x.volume for x in m1)

    def test_bucket_boundary_grid_aligned(self):
        """Bars straddling a 15m boundary split into two buckets."""
        # 00:00..00:14 (15 bars) + 00:15..00:29 (15 bars)
        m1 = _m1_series(pd.Timestamp("2026-01-01 00:00:00"), 30)
        m15 = resample_15m(m1)
        assert len(m15) == 2
        assert m15[0].timestamp == pd.Timestamp("2026-01-01 00:00:00")
        assert m15[1].timestamp == pd.Timestamp("2026-01-01 00:15:00")

    def test_drop_lt3_bars(self):
        """Buckets with <3 bars are dropped (canonical rule)."""
        # 00:00 (2 bars) + 00:15 (15 bars)
        m1 = _m1_series(pd.Timestamp("2026-01-01 00:00:00"), 2)
        m1 += _m1_series(pd.Timestamp("2026-01-01 00:15:00"), 15, base=2.0)
        m15 = resample_15m(m1)
        assert len(m15) == 1
        assert m15[0].timestamp == pd.Timestamp("2026-01-01 00:15:00")

    def test_parity_with_reference_impl(self):
        """Cross-check against an independent reference aggregation."""
        start = pd.Timestamp("2026-01-01 00:00:00")
        m1 = _m1_series(start, 45)  # 3 full buckets
        m15 = resample_15m(m1)

        # Independent reference: group by grid slot, first-bar label
        _15M = 15 * 60 * 1000
        groups = {}
        for b in m1:
            slot = (int(b.timestamp.timestamp() * 1000) // _15M) * _15M
            groups.setdefault(slot, []).append(b)
        ref = []
        for slot in sorted(groups):
            c = groups[slot]
            if len(c) < 3:
                continue
            ref.append(
                Bar(
                    index=len(ref),
                    timestamp=c[0].timestamp,
                    open=c[0].open,
                    high=max(x.high for x in c),
                    low=min(x.low for x in c),
                    close=c[-1].close,
                    volume=sum(x.volume for x in c),
                )
            )
        assert len(m15) == len(ref)
        for a, b in zip(m15, ref):
            assert a.timestamp == b.timestamp
            assert a.open == b.open
            assert a.high == b.high
            assert a.low == b.low
            assert a.close == b.close
            assert a.volume == b.volume


# ---------------------------------------------------------------------------
# Duplicate / missing detection
# ---------------------------------------------------------------------------
class TestDetection:
    def test_duplicate_detection(self):
        m1 = _m1_series(pd.Timestamp("2026-01-01 00:00:00"), 5)
        # Inject a duplicate at 00:02
        dup = _m1_bar(pd.Timestamp("2026-01-01 00:02:00"), 9.0, 9.0, 9.0, 9.0)
        m1.insert(3, dup)
        dups = M1CandleFeed.find_duplicates(m1)
        assert dups == [pd.Timestamp("2026-01-01 00:02:00")]

    def test_no_duplicates(self):
        m1 = _m1_series(pd.Timestamp("2026-01-01 00:00:00"), 10)
        assert M1CandleFeed.find_duplicates(m1) == []

    def test_missing_detection(self):
        # 00:00, 00:01, 00:02, then jump to 00:05 -> missing 00:03, 00:04
        m1 = _m1_series(pd.Timestamp("2026-01-01 00:00:00"), 3)
        m1 += _m1_series(pd.Timestamp("2026-01-01 00:05:00"), 2, base=2.0)
        missing = M1CandleFeed.find_missing(m1)
        assert missing == [
            pd.Timestamp("2026-01-01 00:03:00"),
            pd.Timestamp("2026-01-01 00:04:00"),
        ]

    def test_no_missing(self):
        m1 = _m1_series(pd.Timestamp("2026-01-01 00:00:00"), 10)
        assert M1CandleFeed.find_missing(m1) == []


# ---------------------------------------------------------------------------
# Forming vs closed
# ---------------------------------------------------------------------------
class TestFormingClosed:
    def test_closed_m1(self):
        """Bar at T is closed when now >= T + 1min."""
        m1 = _m1_series(pd.Timestamp("2026-01-01 00:00:00"), 3)
        # now = 00:03:30 -> bars 00:00, 00:01, 00:02 all closed (>= +1min)
        now = pd.Timestamp("2026-01-01 00:03:30").to_pydatetime()
        closed = M1CandleFeed.is_closed_m1(m1, now)
        assert len(closed) == 3

    def test_forming_excluded(self):
        """Bar at 00:03 is still forming at now=00:03:30 (not yet +1min)."""
        m1 = _m1_series(pd.Timestamp("2026-01-01 00:00:00"), 4)
        now = pd.Timestamp("2026-01-01 00:03:30").to_pydatetime()
        closed = M1CandleFeed.is_closed_m1(m1, now)
        # 00:00, 00:01, 00:02 closed; 00:03 forming (excluded)
        assert len(closed) == 3
        assert closed[-1].timestamp == pd.Timestamp("2026-01-01 00:02:00")


# ---------------------------------------------------------------------------
# Warmup
# ---------------------------------------------------------------------------
class TestWarmup:
    def test_warmup_builds_15m(self, monkeypatch):
        feed = M1CandleFeed(data_layer=_StubDataLayer())
        # 3 full 15m buckets = 45 M1 bars
        m1 = _m1_series(pd.Timestamp("2026-01-01 00:00:00"), 45)

        def fake_fetch(symbol, timeframe="M1", count=100):
            return [
                {
                    "time": int(b.timestamp.timestamp()),
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "tick_volume": b.volume,
                }
                for b in m1
            ]

        monkeypatch.setattr(feed.data, "get_rates", fake_fetch)
        m15 = feed.warmup("EURUSD", n_15m=3)
        assert len(m15) == 3
        # fetch_m1 converts server-time -> UTC using the bar's own date.
        # January bar = winter = UTC+2, so server 00:00 -> UTC 22:00 previous day.
        assert m15[0].timestamp == pd.Timestamp("2025-12-31 22:00:00")
        assert m15[2].timestamp == pd.Timestamp("2025-12-31 22:30:00")


# ---------------------------------------------------------------------------
# Incremental update
# ---------------------------------------------------------------------------
class TestUpdate:
    def test_update_returns_only_new(self, monkeypatch):
        feed = M1CandleFeed(data_layer=_StubDataLayer())
        # First call: 45 M1 bars -> 3 new 15m candles
        m1 = _m1_series(pd.Timestamp("2026-01-01 00:00:00"), 45)

        def fake_fetch(symbol, timeframe="M1", count=100):
            return [
                {
                    "time": int(b.timestamp.timestamp()),
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "tick_volume": b.volume,
                }
                for b in m1
            ]

        monkeypatch.setattr(feed.data, "get_rates", fake_fetch)
        now = pd.Timestamp("2026-01-01 01:00:00").to_pydatetime()
        new1 = feed.update("EURUSD", now=now)
        assert len(new1) == 3

        # Second call with same data -> no new candles
        new2 = feed.update("EURUSD", now=now)
        assert new2 == []


# ---------------------------------------------------------------------------
# Clock / timezone
# ---------------------------------------------------------------------------
class TestClock:
    def test_server_utc_offset_summer(self):
        # July = summer -> +3
        assert clock.server_utc_offset(datetime(2026, 7, 1)) == 3

    def test_server_utc_offset_winter(self):
        # January = winter -> +2
        assert clock.server_utc_offset(datetime(2026, 1, 1)) == 2

    def test_utc_to_server_roundtrip(self):
        dt = datetime(2026, 7, 1, 12, 0, 0)
        assert clock.server_to_utc(clock.utc_to_server(dt)) == dt

    def test_in_session_spans_midnight(self):
        # 19:00 and 00:30 server time are in session; 12:00 is not
        assert clock.in_session(datetime(2026, 7, 1, 19, 0))
        assert clock.in_session(datetime(2026, 7, 1, 0, 30))
        assert not clock.in_session(datetime(2026, 7, 1, 12, 0))
