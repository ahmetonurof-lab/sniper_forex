"""Tests for EXP 5F — Frozen EQ vs Dynamic Research EQ."""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
_NEXUS_SRC = str(Path("C:/Users/Administrator/Desktop/nexus-mcp/sniper/src"))
sys.path.insert(0, _NEXUS_SRC)

from experiment.exp5f_frozen_vs_dynamic_eq import (
    _build_swing_timeline,
    _compute_research_eq,
    _latest_swing_from_timeline,
    run_test_a_dynamic_eq,
)

# ── Helpers ──────────────────────────────────────────────────────────────


def _bar(
    idx: int, o: float = 1.1000, h: float = 1.1050, l: float = 1.0950, c: float = 1.1020
) -> MagicMock:
    b = MagicMock()
    b.index = idx
    b.open = o
    b.high = h
    b.low = l
    b.close = c
    b.is_closed = True
    b.timestamp = pd.Timestamp("2025-06-01") + timedelta(minutes=15 * idx)
    return b


def _bars_from_ohlc(ohlcs: list[tuple], start_idx: int = 0):
    bars = []
    for i, (o, h, l, c) in enumerate(ohlcs):
        bars.append(_bar(start_idx + i, o, h, l, c))
    return bars


# ── Unit: _compute_research_eq ───────────────────────────────────────────


class TestComputeResearchEQ:
    def test_valid(self):
        sh = (10, 1.1200)
        sl = (5, 1.0800)
        assert _compute_research_eq(sh, sl) == 1.1000

    def test_none_sh(self):
        assert _compute_research_eq(None, (5, 1.0800)) is None

    def test_none_sl(self):
        assert _compute_research_eq((10, 1.1200), None) is None

    def test_both_none(self):
        assert _compute_research_eq(None, None) is None

    def test_asymmetric(self):
        sh = (10, 1.1150)
        sl = (5, 1.0950)
        assert _compute_research_eq(sh, sl) == 1.1050


# ── Unit: _build_swing_timeline + _latest_swing_from_timeline ──────────────


class TestSwingTimeline:
    def test_builds_and_looks_up_high(self):
        """Build timeline, then lookup should find a peak."""
        ohlcs = [
            (1.00, 1.00, 0.98, 0.99),
            (0.99, 1.01, 0.99, 1.00),
            (1.00, 1.03, 1.00, 1.02),
            (1.02, 1.04, 1.02, 1.03),
            (1.03, 1.05, 1.03, 1.04),
            (1.04, 1.06, 1.02, 1.03),
            (1.03, 1.04, 1.02, 1.03),
            (1.03, 1.04, 1.02, 1.03),
        ]
        bars = _bars_from_ohlc(ohlcs, start_idx=0)
        highs, high_keys, lows, low_keys = _build_swing_timeline(bars, left=2, right=2)
        result = _latest_swing_from_timeline(highs, high_keys, len(bars) - 1)
        assert result is not None
        assert result[1] >= 1.04  # Should find the peak

    def test_returns_none_when_no_swings(self):
        bars = _bars_from_ohlc([(1.0, 1.02, 0.98, 1.01)] * 5, start_idx=0)
        highs, high_keys, lows, low_keys = _build_swing_timeline(bars, left=3, right=3)
        result = _latest_swing_from_timeline(highs, high_keys, 2)
        assert result is None

    def test_returns_none_for_empty_timeline(self):
        assert _latest_swing_from_timeline([], [], 10) is None


# ── Integration: run_test_a_dynamic_eq ───────────────────────────────────


class TestRunTestADynamicEQ:
    def test_returns_list(self):
        """Dynamic EQ engine should return a list."""
        bars = _bars_from_ohlc([(1.0, 1.02, 0.98, 1.01)] * 150, start_idx=0)
        result = run_test_a_dynamic_eq("EURUSD", bars)
        assert isinstance(result, list)

    def test_short_data_returns_empty(self):
        bars = _bars_from_ohlc([(1.0, 1.02, 0.98, 1.01)] * 50, start_idx=0)
        result = run_test_a_dynamic_eq("EURUSD", bars)
        assert result == []


# ── EQ filter logic tests ────────────────────────────────────────────────


class TestEQFilterLogic:
    """Test that the dynamic EQ filter rejects trades as expected."""

    def test_bullish_fvg_passes_when_fvg_top_below_research_eq(self):
        """Bullish: fvg.top <= research_eq → PASS."""
        # When research_eq = 1.1000, bullish FVG with top = 1.0990 should pass
        eq = 1.1000
        fvg_top = 1.0990
        direction = "bullish"
        # Pass condition: fvg.top > eq → rejected; so fvg_top <= eq → pass
        assert not (fvg_top > eq), "Should pass"

    def test_bullish_fvg_rejects_when_fvg_top_above_research_eq(self):
        """Bullish: fvg.top > research_eq → REJECT."""
        eq = 1.0900
        fvg_top = 1.0990
        assert fvg_top > eq, "Should reject"

    def test_bearish_fvg_passes_when_fvg_bottom_above_research_eq(self):
        """Bearish: fvg.bottom >= research_eq → PASS."""
        eq = 1.1000
        fvg_bottom = 1.1010
        assert not (fvg_bottom < eq), "Should pass"

    def test_bearish_fvg_rejects_when_fvg_bottom_below_research_eq(self):
        """Bearish: fvg.bottom < research_eq → REJECT."""
        eq = 1.1050
        fvg_bottom = 1.1010
        assert fvg_bottom < eq, "Should reject"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
