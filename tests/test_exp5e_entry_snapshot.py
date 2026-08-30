"""Tests for exp5e_entry_snapshot — entry-time mitigation state classification."""

import sys

sys.path.insert(0, ".")
sys.path.insert(0, "C:/Users/Administrator/Desktop/nexus-mcp/sniper/src")

from experiment.exp5e_entry_snapshot import (
    S0,
    S1,
    S2,
    S3,
    S4,
    _classify_state_in_window,
    _entry_snapshot,
    _is_fresh_fvg_at,
)
from src.strategy.models import Bar

FVG_TOP = 1.1050
FVG_BOTTOM = 1.1000
FVG_SIZE = 0.0050
FVG_RI = 10  # real_index


def _bar(idx, o, h, l, c):
    from datetime import datetime, timedelta

    ts = datetime(2026, 1, 1) + timedelta(minutes=idx * 15)
    return Bar(index=idx, timestamp=ts, open=o, high=h, low=l, close=c, volume=1000)


def _bars_from_ohlc(ohlc_list):
    return [_bar(i, o, h, l, c) for i, (o, h, l, c) in enumerate(ohlc_list)]


# ── _classify_state_in_window ──


def test_window_scans_only_in_range():
    """Bars outside [scan_start, scan_end) should be ignored."""
    ohlc = [(1.1060, 1.1080, 1.1055, 1.1070)] * 13  # idx 0-12
    # idx 13: far-side close (close > fvg_top + wick in zone)
    ohlc.append((1.1030, 1.1080, 1.1010, 1.1070))
    ohlc += [(1.1070, 1.1090, 1.1060, 1.1080)] * 6
    bars = _bars_from_ohlc(ohlc)
    # Window: 12→13 (only idx 12 checked, no touch → S0)
    r = _classify_state_in_window(bars, FVG_TOP, FVG_BOTTOM, "bullish", 12, 13)
    assert r["state"] == S0
    # Window: 12→14 (idx 12 + idx 13 checked, idx 13 has far-side close → S4)
    r2 = _classify_state_in_window(bars, FVG_TOP, FVG_BOTTOM, "bullish", 12, 14)
    assert r2["state"] == S4


def test_window_empty_returns_s0():
    """No bars in window → S0."""
    ohlc = [(1.1060, 1.1080, 1.1055, 1.1070)] * 20
    bars = _bars_from_ohlc(ohlc)
    # Window 5→5 (empty)
    r = _classify_state_in_window(bars, FVG_TOP, FVG_BOTTOM, "bullish", 5, 5)
    assert r["state"] == S0
    assert r["max_pen_pct"] == 0.0


def test_window_body_entry_s2():
    """Body enters zone within window → S2."""
    ohlc = [(1.1060, 1.1080, 1.1055, 1.1070)] * 20
    # idx 14: body enters zone
    ohlc[14] = (1.1060, 1.1070, 1.1025, 1.1025)
    bars = _bars_from_ohlc(ohlc)
    # Window: 12→16
    r = _classify_state_in_window(bars, FVG_TOP, FVG_BOTTOM, "bullish", 12, 16)
    assert r["state"] == S2


# ── _entry_snapshot ──


def test_entry_snapshot_before_any_touch():
    """Entry before any zone interaction → entry_state=S0."""
    ohlc = [(1.1060, 1.1080, 1.1055, 1.1070)] * 20
    bars = _bars_from_ohlc(ohlc)
    snap = _entry_snapshot(bars, FVG_TOP, FVG_BOTTOM, "bullish", FVG_RI, 12)
    assert snap["entry_state"] == S0
    assert snap["post_entry_max_state"] == S0
    assert snap["post_entry_s4"] is False


def test_entry_snapshot_s2_at_entry_s3_post():
    """Entry at S2 (body enters), post-entry deepens to S3."""
    ohlc = [(1.1060, 1.1080, 1.1055, 1.1070)] * 20
    # idx 13: body enters zone (pen ~50%) → S2
    ohlc[13] = (1.1060, 1.1070, 1.1025, 1.1025)
    # idx 15: deep penetration (pen ~90%) → S2→S3 upgrade
    ohlc[15] = (1.1040, 1.1050, 1.1005, 1.1008)
    bars = _bars_from_ohlc(ohlc)
    # Entry at bar 14 (between the two events)
    snap = _entry_snapshot(bars, FVG_TOP, FVG_BOTTOM, "bullish", FVG_RI, 14)
    assert snap["entry_state"] == S2
    assert snap["post_entry_max_state"] == S3


def test_entry_snapshot_s4_post_entry():
    """Entry at S1, then S4 happens after entry."""
    ohlc = [(1.1060, 1.1080, 1.1055, 1.1070)] * 20
    # idx 12: wick touch (close=fvg_top → not S4) → S1
    ohlc[12] = (1.1060, 1.1080, 1.1030, 1.1050)
    # idx 16: far-side close → S4
    ohlc[16] = (1.1030, 1.1080, 1.1010, 1.1070)
    bars = _bars_from_ohlc(ohlc)
    # Entry at bar 14 (after S1, before S4)
    snap = _entry_snapshot(bars, FVG_TOP, FVG_BOTTOM, "bullish", FVG_RI, 14)
    assert snap["entry_state"] == S1
    assert snap["post_entry_s4"] is True
    assert snap["post_entry_max_state"] == S4


def test_entry_snapshot_s4_before_entry():
    """S4 happens before entry → entry_s4=True."""
    ohlc = [(1.1060, 1.1080, 1.1055, 1.1070)] * 20
    # idx 12: far-side close → S4
    ohlc[12] = (1.1030, 1.1080, 1.1010, 1.1070)
    bars = _bars_from_ohlc(ohlc)
    # Entry at bar 15 (after S4)
    snap = _entry_snapshot(bars, FVG_TOP, FVG_BOTTOM, "bullish", FVG_RI, 15)
    assert snap["entry_state"] == S4
    assert snap["entry_s4"] is True
    assert snap["post_entry_s4"] is False  # already S4 at entry, not post


def test_bearish_entry_snapshot():
    """Bearish FVG entry snapshot."""
    bear_top = 1.1050
    bear_bottom = 1.1000
    ohlc = [(1.0990, 1.0995, 1.0980, 1.0990)] * 20
    # idx 12: body enters zone (high enters) → S2
    ohlc[12] = (1.1010, 1.1030, 1.0980, 1.1020)
    bars = _bars_from_ohlc(ohlc)
    snap = _entry_snapshot(bars, bear_top, bear_bottom, "bearish", FVG_RI, 14)
    assert snap["entry_state"] == S2


# ── _is_fresh_fvg_at ──


def test_fresh_at_entry_true():
    """No touch before entry → fresh=True at entry."""
    ohlc = [(1.1060, 1.1080, 1.1055, 1.1070)] * 20
    bars = _bars_from_ohlc(ohlc)
    r = _is_fresh_fvg_at(FVG_RI, bars, 15, "bullish", FVG_TOP, FVG_BOTTOM)
    assert r is True


def test_fresh_at_entry_false():
    """Touch before entry → fresh=False at entry."""
    ohlc = [(1.1060, 1.1080, 1.1055, 1.1070)] * 20
    # idx 12: wick enters zone
    ohlc[12] = (1.1060, 1.1080, 1.1030, 1.1070)
    bars = _bars_from_ohlc(ohlc)
    r = _is_fresh_fvg_at(FVG_RI, bars, 15, "bullish", FVG_TOP, FVG_BOTTOM)
    assert r is False


def test_fresh_at_entry_touch_after_not_counted():
    """Touch AFTER entry index → still fresh=True at entry."""
    ohlc = [(1.1060, 1.1080, 1.1055, 1.1070)] * 20
    # idx 16: wick enters zone (after entry at 15)
    ohlc[16] = (1.1060, 1.1080, 1.1030, 1.1070)
    bars = _bars_from_ohlc(ohlc)
    r = _is_fresh_fvg_at(FVG_RI, bars, 15, "bullish", FVG_TOP, FVG_BOTTOM)
    assert r is True
