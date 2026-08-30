"""Tests for exp5d_fvg_mitigation state classification."""

import sys

sys.path.insert(0, ".")
sys.path.insert(0, "C:/Users/Administrator/Desktop/nexus-mcp/sniper/src")

from experiment.exp5d_fvg_mitigation import (
    S0,
    S1,
    S2,
    S3,
    S4,
    _classify_mitigation_state,
)
from src.strategy.models import Bar


def _bar(idx, o, h, l, c):
    """Create a 15m Bar with given OHLC."""
    from datetime import datetime, timedelta

    ts = datetime(2026, 1, 1) + timedelta(minutes=idx * 15)
    return Bar(index=idx, timestamp=ts, open=o, high=h, low=l, close=c, volume=1000)


def _bars_from_ohlc(ohlc_list):
    """Build bars from list of (open, high, low, close) tuples."""
    return [_bar(i, o, h, l, c) for i, (o, h, l, c) in enumerate(ohlc_list)]


# Bullish FVG: zone = [fvg_bottom, fvg_top] = [1.1000, 1.1050]
FVG_TOP = 1.1050
FVG_BOTTOM = 1.1000
FVG_SIZE = 0.0050
FVG_RI = 10  # real_index


def test_s0_untouched():
    """No bars touch the zone → S0."""
    ohlc = [(1.1060, 1.1080, 1.1055, 1.1070)] * 12  # idx 0-11: pre-formation + gap
    ohlc += [(1.1070, 1.1090, 1.1060, 1.1080)] * 8  # idx 12-19: after FVG, lows > top
    bars = _bars_from_ohlc(ohlc)
    r = _classify_mitigation_state(bars, FVG_TOP, FVG_BOTTOM, "bullish", FVG_RI)
    assert r["state"] == S0
    assert r["max_pen_pct"] == 0.0
    assert r["first_touch_index"] is None
    assert r["invalidation_index"] is None


def test_s1_wick_touch():
    """Wick touches zone but body stays outside → S1."""
    ohlc = [(1.1060, 1.1080, 1.1055, 1.1070)] * 12  # pre-formation
    # idx 12: wick dips into zone (low=1.1030) but body stays above
    # close=fvg_top exactly → far_side_close (close > fvg_top) is False
    ohlc.append((1.1060, 1.1080, 1.1030, 1.1050))
    ohlc += [(1.1070, 1.1090, 1.1060, 1.1080)] * 7  # no more touch
    bars = _bars_from_ohlc(ohlc)
    r = _classify_mitigation_state(bars, FVG_TOP, FVG_BOTTOM, "bullish", FVG_RI)
    assert r["state"] == S1
    assert r["first_touch_index"] == 12
    assert r["max_pen_pct"] > 0


def test_s2_partial_penetration():
    """Body enters zone but doesn't consume it → S2."""
    ohlc = [(1.1060, 1.1080, 1.1055, 1.1070)] * 12
    # idx 12: body enters zone (close=1.1025 inside zone, pen=50%)
    ohlc.append((1.1060, 1.1070, 1.1025, 1.1025))
    ohlc += [(1.1070, 1.1090, 1.1060, 1.1080)] * 7
    bars = _bars_from_ohlc(ohlc)
    r = _classify_mitigation_state(bars, FVG_TOP, FVG_BOTTOM, "bullish", FVG_RI)
    assert r["state"] == S2
    assert 0 < r["max_pen_pct"] <= 70


def test_s3_deep_penetration():
    """Body enters zone deeply (>70%) but no far-side close → S3."""
    ohlc = [(1.1060, 1.1080, 1.1055, 1.1070)] * 12
    # idx 12: deep penetration (low=1.1005, close=1.1008)
    # pen = 1.1050 - 1.1005 = 0.0045 → 90% → S3
    ohlc.append((1.1040, 1.1050, 1.1005, 1.1008))
    ohlc += [(1.1070, 1.1090, 1.1060, 1.1080)] * 7
    bars = _bars_from_ohlc(ohlc)
    r = _classify_mitigation_state(bars, FVG_TOP, FVG_BOTTOM, "bullish", FVG_RI)
    assert r["state"] == S3
    assert r["max_pen_pct"] > 70


def test_s4_invalidated_far_side_close():
    """Far-side close (close > fvg_top for bullish) → S4."""
    ohlc = [(1.1060, 1.1080, 1.1055, 1.1070)] * 12
    # idx 12: candle dips into zone AND closes above top (far-side close)
    ohlc.append((1.1030, 1.1080, 1.1010, 1.1070))
    ohlc += [(1.1070, 1.1090, 1.1060, 1.1080)] * 7
    bars = _bars_from_ohlc(ohlc)
    r = _classify_mitigation_state(bars, FVG_TOP, FVG_BOTTOM, "bullish", FVG_RI)
    assert r["state"] == S4
    assert r["invalidation_index"] == 12


def test_s4_is_immediate_on_far_side_close():
    """Far-side close on first touch → directly S4 (not S1/S2)."""
    ohlc = [(1.1060, 1.1080, 1.1055, 1.1070)] * 12
    # First bar after scan window: wick enters zone + close > top
    ohlc.append((1.1030, 1.1080, 1.1000, 1.1070))
    ohlc += [(1.1070, 1.1090, 1.1060, 1.1080)] * 7
    bars = _bars_from_ohlc(ohlc)
    r = _classify_mitigation_state(bars, FVG_TOP, FVG_BOTTOM, "bullish", FVG_RI)
    assert r["state"] == S4


def test_bearish_mirror():
    """Bearish FVG: S4 = close < fvg_bottom."""
    bear_top = 1.1050
    bear_bottom = 1.1000
    ohlc = [(1.0990, 1.0995, 1.0980, 1.0990)] * 12  # bars below zone
    # idx 12: wick into zone + close below bottom (far-side close for bearish)
    ohlc.append((1.1010, 1.1040, 1.0980, 1.0990))
    ohlc += [(1.0990, 1.0995, 1.0980, 1.0990)] * 7
    bars = _bars_from_ohlc(ohlc)
    r = _classify_mitigation_state(bars, bear_top, bear_bottom, "bearish", FVG_RI)
    assert r["state"] == S4
    assert r["invalidation_index"] == 12


def test_penetration_pct_calculation():
    """Verify penetration % = (penetration depth / fvg_size) * 100."""
    ohlc = [(1.1060, 1.1080, 1.1055, 1.1070)] * 12
    # idx 12: low=1.1025 → pen = 1.1050 - 1.1025 = 0.0025 = 50%
    ohlc.append((1.1060, 1.1070, 1.1025, 1.1060))
    ohlc += [(1.1070, 1.1090, 1.1060, 1.1080)] * 7
    bars = _bars_from_ohlc(ohlc)
    r = _classify_mitigation_state(bars, FVG_TOP, FVG_BOTTOM, "bullish", FVG_RI)
    assert abs(r["max_pen_pct"] - 50.0) < 0.1


def test_max_penetration_tracks_highest():
    """max_pen_pct tracks the highest across all bars, S2→S3 upgrade."""
    ohlc = [(1.1060, 1.1080, 1.1055, 1.1070)] * 12
    # idx 12: body enters zone shallowly (pen ~40%) → S2
    # low=1.1030 → pen = (1.1050-1.1030)/0.0050 = 40%
    ohlc.append((1.1060, 1.1070, 1.1030, 1.1040))
    # idx 13: deep body entry (pen ~80%), close < fvg_top → S2→S3 upgrade
    # low=1.1010 → pen = (1.1050-1.1010)/0.0050 = 80%
    ohlc.append((1.1040, 1.1050, 1.1010, 1.1015))
    ohlc += [(1.1070, 1.1090, 1.1060, 1.1080)] * 6
    bars = _bars_from_ohlc(ohlc)
    r = _classify_mitigation_state(bars, FVG_TOP, FVG_BOTTOM, "bullish", FVG_RI)
    # max pen from idx 13: (1.1050-1.1010)/0.0050 = 80%
    assert r["max_pen_pct"] >= 79.0
    assert r["state"] == S3  # upgraded from S2 due to >70%


def test_no_pre_formation_scanning():
    """Bars before fvg_real_index+2 should not be scanned."""
    ohlc = [(1.1030, 1.1040, 1.1010, 1.1015)] * 12  # all bars touch zone, but before scan window
    bars = _bars_from_ohlc(ohlc)
    r = _classify_mitigation_state(bars, FVG_TOP, FVG_BOTTOM, "bullish", FVG_RI)
    # scan starts at fvg_real_index+2 = 12, no bars at index >=12
    assert r["state"] == S0
