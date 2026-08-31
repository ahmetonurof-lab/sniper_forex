#!/usr/bin/env python
"""P2-6 — Paper incremental 15m continuity test (minimal)."""

import pandas as pd

from src.live.candle_feed import resample_15m
from src.strategy.models import Bar


def _m1_bar(ts, o, h, lo, c, v=1.0, index=0):
    return Bar(index=index, timestamp=ts, open=o, high=h, low=lo, close=c, volume=v)


def test_continuous_tail_preserves_partial_15m():
    """Split M1 buckets must not duplicate 15m emission when combined with tail."""
    start = pd.Timestamp("2026-01-01 00:00:00")
    # 8 M1 bars (not a full 15m) + 7 M1 bars = exactly one 15m bucket when combined
    tail = [
        _m1_bar(start + pd.Timedelta(minutes=i), 1.0, 1.0, 1.0, 1.0, v=1.0, index=i)
        for i in range(8)
    ]
    new_m1 = [
        _m1_bar(start + pd.Timedelta(minutes=8 + i), 1.0, 1.0, 1.0, 1.0, v=1.0, index=8 + i)
        for i in range(7)
    ]
    combined = tail + new_m1
    m15 = resample_15m(combined)
    # 15 M1 bars in one bucket -> exactly one 15m bar
    assert len(m15) == 1
    assert m15[0].timestamp == start
