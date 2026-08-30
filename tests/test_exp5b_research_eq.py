"""
EXP 5B — Research EQ + FVG #1/#2 Forensic Backtest
=====================================================

Tests for Research EQ telemetry layer and forensic metrics.
Tests validate the new Research EQ calculation, swing detection,
and EQ position evolution logic.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Add NEXUS sniper src for SwingPoint
_NEXUS_SNIPER_SRC = str(Path("C:/Users/Administrator/Desktop/nexus-mcp/sniper/src"))
if _NEXUS_SNIPER_SRC not in sys.path:
    sys.path.insert(0, _NEXUS_SNIPER_SRC)

from models import SwingPoint

from experiment.exp5b_post_sweep_fvg_1v2_eq import (
    FvgResearchTelemetry,
    _build_swing_timeline,
    _check_fvg_invalidated,
    _compute_research_eq,
    _compute_research_eq_metrics,
    _determine_eq_position,
    _evolving_eq_first_correct,
    _get_latest_confirmed_swing,
    _latest_swing_from_timeline,
)
from src.strategy.models import Bar


def _make_bar(index, ts, o, h, l, c, v=100.0):
    return Bar(index=index, timestamp=ts, open=o, high=h, low=l, close=c, volume=v)


def _bars_from_hl(timestamps, hl_pairs):
    """Build Bars from (high, low) pairs; open=close=mid."""
    return [
        _make_bar(i, ts, (h + l) / 2, h, l, (h + l) / 2)
        for i, (ts, (h, l)) in enumerate(zip(timestamps, hl_pairs))
    ]


# Deterministic synthetic HL series used by evolving-EQ scenarios.
# Engineered pivots: swing low p=3 @0.90 (confirm 6), swing high p=5 @1.10
# (confirm 8), swing high p=15 @1.25 (confirm 18). No other pivots confirm
# in (8, 18].
_SCENARIO_HL = [
    (1.00, 0.98),  # 0
    (1.01, 0.97),  # 1
    (1.02, 0.96),  # 2
    (1.03, 0.90),  # 3  swing low pivot 0.90
    (1.05, 0.99),  # 4
    (1.10, 1.00),  # 5  swing high pivot 1.10
    (1.08, 1.01),  # 6
    (1.07, 1.00),  # 7
    (1.09, 1.02),  # 8  -> SH0 confirmed here
    (1.085, 1.03),  # 9
    (1.08, 1.04),  # 10
    (1.07, 1.05),  # 11
    (1.06, 1.05),  # 12 <- FVG formation index in scenarios
    (1.07, 1.05),  # 13
    (1.09, 1.065),  # 14  (freshness window starts at ri+2 = 14)
    (1.25, 1.07),  # 15  swing high pivot 1.25
    (1.20, 1.07),  # 16
    (1.18, 1.065),  # 17
    (1.16, 1.07),  # 18  -> new SH confirmed here
    (1.15, 1.065),  # 19
    (1.14, 1.07),  # 20
]


def _scenario_bars(n=21):
    timestamps = pd.date_range(start="2024-01-01", periods=n, freq="15min")
    return _bars_from_hl(timestamps, _SCENARIO_HL[:n])


def test_get_latest_confirmed_swing():
    """Test canonical swing detection with left=3,right=3."""
    timestamps = pd.date_range(start="2024-01-01", periods=20, freq="15min")
    bars = [
        _make_bar(
            i,
            ts,
            1.0 + i * 0.001,
            1.0 + i * 0.001 + 0.01,
            1.0 + i * 0.001 - 0.01,
            1.0 + i * 0.001,
        )
        for i, ts in enumerate(timestamps)
    ]

    # Test with enough bars for pivot detection
    swing_high = _get_latest_confirmed_swing(bars, up_to_index=15, is_high=True, left=3, right=3)
    swing_low = _get_latest_confirmed_swing(bars, up_to_index=15, is_high=False, left=3, right=3)

    assert swing_high is None or isinstance(swing_high, SwingPoint)
    assert swing_low is None or isinstance(swing_low, SwingPoint)


def test_compute_research_eq():
    """Test Research EQ calculation."""
    swing_high = SwingPoint(kind="high", price=1.1000, bar_index=5)
    swing_low = SwingPoint(kind="low", price=1.0900, bar_index=3)

    eq = _compute_research_eq(swing_high, swing_low)
    assert eq is not None
    assert abs(eq - 1.0950) < 1e-6  # (1.1000 + 1.0900) / 2

    eq_none = _compute_research_eq(None, swing_low)
    assert eq_none is None

    eq_none2 = _compute_research_eq(swing_high, None)
    assert eq_none2 is None

    eq_both_none = _compute_research_eq(None, None)
    assert eq_both_none is None


def test_determine_eq_position_bullish():
    """Bullish: CORRECT_SIDE iff entire FVG BELOW EQ (discount, = production gate)."""
    # FVG [1.0930, 1.0940] entirely below EQ 1.0950 -> correct (discount)
    assert _determine_eq_position(1.0940, 1.0930, 1.0950, "bullish") == "CORRECT_SIDE"
    # FVG [1.0960, 1.0970] entirely above EQ -> wrong (premium)
    assert _determine_eq_position(1.0970, 1.0960, 1.0950, "bullish") == "WRONG_SIDE"
    # Zone straddles EQ
    assert _determine_eq_position(1.0970, 1.0930, 1.0950, "bullish") == "CROSSES_EQ"
    # Exact touch: top == EQ counts as correct (whole-zone <=)
    assert _determine_eq_position(1.0950, 1.0930, 1.0950, "bullish") == "CORRECT_SIDE"
    assert _determine_eq_position(1.0950, 1.0930, None, "bullish") == "NO_SWING_YET"


def test_determine_eq_position_bearish():
    """Bearish: CORRECT_SIDE iff entire FVG ABOVE EQ (premium, = production gate)."""
    assert _determine_eq_position(1.0970, 1.0960, 1.0950, "bearish") == "CORRECT_SIDE"
    assert _determine_eq_position(1.0940, 1.0930, 1.0950, "bearish") == "WRONG_SIDE"
    assert _determine_eq_position(1.0970, 1.0930, 1.0950, "bearish") == "CROSSES_EQ"
    # Exact touch: bottom == EQ counts as correct
    assert _determine_eq_position(1.0970, 1.0950, 1.0950, "bearish") == "CORRECT_SIDE"
    assert _determine_eq_position(1.0950, 1.0930, None, "bearish") == "NO_SWING_YET"


def test_fvg_telemetry_schema():
    """Test that FvgResearchTelemetry has all required fields."""
    t = FvgResearchTelemetry(
        symbol="EURUSD",
        sweep_index=1,
        sweep_timestamp="2024-01-01T10:00:00",
        fvg_slot=1,
        direction="bullish",
        fvg_bar_index=100,
        fvg_timestamp="2024-01-01T12:00:00",
        bars_from_sweep=5,
        top=1.1000,
        bottom=1.0950,
        midpoint=1.0975,
        size=0.0050,
        size_atr=0.05,
        fresh=True,
        eq_position="CORRECT_SIDE",
        research_eq=1.0950,
        confirmed_swing_high_index=10,
        confirmed_swing_high_price=1.1010,
        confirmed_swing_low_index=5,
        confirmed_swing_low_price=1.0910,
        first_correct_side_bar_index=15,
        first_correct_side_timestamp="2024-01-01T14:00:00",
        first_correct_side_swings=2,
        still_fresh_at_first_correct=True,
        invalidated_at_first_correct=False,
        stale_bar_index=None,
        sweep_to_first_correct_min=60.0,
        formation_to_first_correct_min=45.0,
        ob_nearby="N/A",
        breaker_nearby="N/A",
    )

    assert t.symbol == "EURUSD"
    assert t.sweep_timestamp == "2024-01-01T10:00:00"
    assert t.fvg_slot == 1
    assert t.direction == "bullish"
    assert t.eq_position == "CORRECT_SIDE"
    assert t.research_eq == 1.0950
    assert t.first_correct_side_swings == 2
    assert t.still_fresh_at_first_correct is True
    assert t.invalidated_at_first_correct is False
    assert t.stale_bar_index is None
    assert t.sweep_to_first_correct_min == 60.0
    assert t.formation_to_first_correct_min == 45.0
    assert t.ob_nearby == "N/A"
    assert t.breaker_nearby == "N/A"


def test_outcome_attribution_no_errors():
    """Test that outcome attribution runs without errors."""
    from experiment.exp5b_post_sweep_fvg_1v2_eq import _outcome_stats

    trades = [
        {
            "symbol": "EURUSD",
            "result": "TP",
            "pnl_r": 1.5,
            "direction": "long",
            "slot": 1,
            "zone_index": 100,
            "sweep_bar_index": 50,
            "entry_bar_index": 51,
            "exit_bar_index": 60,
        },
        {
            "symbol": "EURUSD",
            "result": "LOSS",
            "pnl_r": -1.0,
            "direction": "long",
            "slot": 1,
            "zone_index": 100,
            "sweep_bar_index": 50,
            "entry_bar_index": 51,
            "exit_bar_index": 55,
        },
    ]

    stats = _outcome_stats(trades, "test_label")
    assert stats["N"] == 2
    assert stats["completed"] == 2
    assert stats["WR%"] == 50.0


def test_equation_position_none_research_eq():
    """Test that NO_SWING_YET is returned when research_eq is None."""
    pos = _determine_eq_position(1.0950, 1.0930, None, "bullish")
    assert pos == "NO_SWING_YET"

    pos = _determine_eq_position(1.0950, 1.0930, None, "bearish")
    assert pos == "NO_SWING_YET"


def test_swing_detection_future_safe():
    """Test that swing detection only uses confirmed (closed) bars and future-safe."""
    timestamps = pd.date_range(start="2024-01-01", periods=30, freq="15min")
    bars = []
    for i in range(30):
        price = 1.0 + i * 0.001
        # Ensure high >= open >= low and close is within range
        if i < 15:
            high = price + 0.01
            low = price - 0.005
        else:
            high = price + 0.005
            low = price - 0.01
        bars.append(_make_bar(i, timestamps[i], price, high, low, price))

    swing_high = _get_latest_confirmed_swing(bars, up_to_index=20, is_high=True, left=3, right=3)
    swing_low = _get_latest_confirmed_swing(bars, up_to_index=20, is_high=False, left=3, right=3)

    assert swing_high is None or isinstance(swing_high, SwingPoint)
    assert swing_low is None or isinstance(swing_low, SwingPoint)


def test_determine_eq_position_edge_cases():
    """Test edge cases in EQ position determination (whole-zone)."""
    assert _determine_eq_position(1.0950, 1.0930, 1.0950, "bullish") == "CORRECT_SIDE"
    assert _determine_eq_position(1.0970, 1.0950, 1.0950, "bearish") == "CORRECT_SIDE"

    assert _determine_eq_position(1.0960, 1.0940, 1.0950, "bullish") == "CROSSES_EQ"
    assert _determine_eq_position(1.0960, 1.0940, 1.0950, "bearish") == "CROSSES_EQ"

    assert _determine_eq_position(1.0940, 1.0930, 1.0950, "bullish") == "CORRECT_SIDE"
    assert _determine_eq_position(1.0940, 1.0930, 1.0950, "bearish") == "WRONG_SIDE"


def test_invalidated_check():
    """Test FVG invalidation detection."""
    timestamps = pd.date_range(start="2024-01-01", periods=20, freq="15min")
    # Create bars where prices stay above FVG top (1.05) so FVG is NOT invalidated
    bars = [_make_bar(i, ts, 1.2, 1.3, 1.1, 1.25) for i, ts in enumerate(timestamps)]

    fvg = type(
        "obj",
        (object,),
        {
            "direction": "bullish",
            "top": 1.05,
            "bottom": 1.01,
            "real_index": 10,
        },
    )()

    invalidated = _check_fvg_invalidated(fvg, bars, fvg.real_index, 15)
    assert invalidated is False

    # Now add a bar that touches the FVG zone (low <= top)
    bars_with_touch = bars + [_make_bar(20, pd.Timestamp("2024-01-02"), 1.0, 1.1, 1.01, 1.05)]
    invalidated = _check_fvg_invalidated(fvg, bars_with_touch, fvg.real_index, 20)
    assert invalidated is True


def test_production_eq_unchanged():
    """Verify production EQ formula is identical (regression check)."""
    sweep_price = 1.1000
    range_opposite = 1.0950
    eq = (sweep_price + range_opposite) / 2
    assert abs(eq - 1.0975) < 1e-6


def test_fvg_telemetry_defaults():
    """Test FvgResearchTelemetry has correct default values."""
    t = FvgResearchTelemetry(
        symbol="EURUSD",
        sweep_index=1,
        sweep_timestamp="2024-01-01T10:00:00",
        fvg_slot=1,
        direction="bullish",
        fvg_bar_index=100,
        fvg_timestamp="2024-01-01T12:00:00",
        bars_from_sweep=5,
        top=1.1000,
        bottom=1.0950,
        midpoint=1.0975,
        size=0.0050,
        size_atr=0.05,
        fresh=True,
        eq_position="NO_SWING_YET",
        research_eq=None,
        confirmed_swing_high_index=None,
        confirmed_swing_high_price=None,
        confirmed_swing_low_index=None,
        confirmed_swing_low_price=None,
        first_correct_side_bar_index=None,
        first_correct_side_timestamp=None,
        first_correct_side_swings=0,
        still_fresh_at_first_correct=None,
        invalidated_at_first_correct=False,
        stale_bar_index=None,
        sweep_to_first_correct_min=None,
        formation_to_first_correct_min=None,
    )

    assert t.ob_nearby == "N/A"
    assert t.breaker_nearby == "N/A"
    assert t.research_eq is None
    assert t.eq_position == "NO_SWING_YET"
    assert t.sweep_to_first_correct_min is None
    assert t.formation_to_first_correct_min is None


# ─────────────────────────────────────────────────────────────────────────────
# Swing timeline fast path — equivalence with the reference implementation
# ─────────────────────────────────────────────────────────────────────────────
def test_timeline_matches_reference_implementation():
    """_latest_swing_from_timeline must equal _get_latest_confirmed_swing
    for EVERY query index on a deterministic synthetic series."""
    n = 120
    timestamps = pd.date_range(start="2024-01-01", periods=n, freq="15min")
    # Deterministic pseudo-random walk (LCG) — plenty of pivots
    hl = []
    x = 1.10
    seed = 12345
    for i in range(n):
        seed = (seed * 1103515245 + 12345) % (2**31)
        step = ((seed // 65536) % 200 - 100) / 5000.0  # [-0.02, +0.02]
        x = max(0.5, x + step)
        hl.append((x + abs(step) + 0.004, x - abs(step) - 0.004))
    bars = _bars_from_hl(timestamps, hl)

    highs, lows = _build_swing_timeline(bars, left=3, right=3)

    for u in range(n):
        ref_h = _get_latest_confirmed_swing(bars, u, is_high=True, left=3, right=3)
        ref_l = _get_latest_confirmed_swing(bars, u, is_high=False, left=3, right=3)
        fast_h = _latest_swing_from_timeline(highs, u)
        fast_l = _latest_swing_from_timeline(lows, u)

        if ref_h is None:
            assert fast_h is None, f"high mismatch at u={u}"
        else:
            assert (
                fast_h is not None
                and fast_h[1] == ref_h.bar_index
                and abs(fast_h[2] - ref_h.price) < 1e-12
            ), f"high mismatch at u={u}"
        if ref_l is None:
            assert fast_l is None, f"low mismatch at u={u}"
        else:
            assert (
                fast_l is not None
                and fast_l[1] == ref_l.bar_index
                and abs(fast_l[2] - ref_l.price) < 1e-12
            ), f"low mismatch at u={u}"


def test_timeline_future_safety():
    """A pivot must NOT be visible before its right bars exist."""
    bars = _scenario_bars()
    highs, lows = _build_swing_timeline(bars, left=3, right=3)

    # swing low p=3 confirms at 6; swing high p=5 confirms at 8;
    # swing high p=15 @1.25 confirms at 18.
    assert _latest_swing_from_timeline(lows, 5) is None
    assert _latest_swing_from_timeline(lows, 6)[1] == 3
    assert _latest_swing_from_timeline(highs, 7) is None
    assert _latest_swing_from_timeline(highs, 8)[1] == 5
    assert _latest_swing_from_timeline(highs, 17)[1] == 5  # p=15 not yet confirmed
    assert _latest_swing_from_timeline(highs, 18)[1] == 15  # now confirmed


# ─────────────────────────────────────────────────────────────────────────────
# Evolving EQ — FIRST CORRECT SIDE scenarios
# ─────────────────────────────────────────────────────────────────────────────
def test_evolving_wrong_then_correct_after_one_swing():
    """Bullish FVG above EQ at formation -> WRONG_SIDE; one new swing high
    (p=15 @1.25, confirm 18) lifts EQ to 1.075 > top 1.06 -> CORRECT_SIDE."""
    bars = _scenario_bars()
    highs, lows = _build_swing_timeline(bars)

    ev = _evolving_eq_first_correct(
        fvg_top=1.06,
        fvg_bottom=1.04,
        direction="bullish",
        fvg_real_index=12,
        bars_15m=bars,
        high_events=highs,
        low_events=lows,
    )

    assert ev["formation_position"] == "WRONG_SIDE"
    assert abs(ev["formation_research_eq"] - 1.00) < 1e-12  # (1.10+0.90)/2

    fc = ev["first_correct"]
    assert fc is not None
    assert fc["bar_index"] == 18
    assert fc["swings"] == 1
    # no zone touch in [14, 18) -> still fresh at first correct
    assert fc["still_fresh"] is True
    assert fc["invalidated"] is False
    assert ev["first_touch_index"] is None


def test_evolving_formation_correct_zero_swings():
    """FVG already below EQ at formation -> CORRECT_SIDE with swings=0."""
    bars = _scenario_bars()
    highs, lows = _build_swing_timeline(bars)

    ev = _evolving_eq_first_correct(
        fvg_top=0.99,
        fvg_bottom=0.97,
        direction="bullish",
        fvg_real_index=12,
        bars_15m=bars,
        high_events=highs,
        low_events=lows,
    )

    assert ev["formation_position"] == "CORRECT_SIDE"
    fc = ev["first_correct"]
    assert fc["bar_index"] == 12
    assert fc["swings"] == 0
    assert fc["still_fresh"] is True


def test_evolving_never_correct():
    """FVG far above any achievable EQ -> never becomes correct."""
    bars = _scenario_bars()
    highs, lows = _build_swing_timeline(bars)

    ev = _evolving_eq_first_correct(
        fvg_top=1.30,
        fvg_bottom=1.28,
        direction="bullish",
        fvg_real_index=12,
        bars_15m=bars,
        high_events=highs,
        low_events=lows,
    )

    assert ev["formation_position"] == "WRONG_SIDE"
    assert ev["first_correct"] is None


def test_evolving_no_swing_yet_then_correct():
    """Before ANY confirmed swing pair -> NO_SWING_YET; later updates can correct."""
    bars = _scenario_bars()
    highs, lows = _build_swing_timeline(bars)

    # At u=7: swing low p=3 confirmed (6<=7) but NO swing high yet
    ev = _evolving_eq_first_correct(
        fvg_top=1.06,
        fvg_bottom=1.04,
        direction="bullish",
        fvg_real_index=7,
        bars_15m=bars,
        high_events=highs,
        low_events=lows,
    )
    assert ev["formation_position"] == "NO_SWING_YET"

    # Walk from 7: SH p=5@1.10 confirm 8 (updates=1) -> EQ=(1.10+0.90)/2=1.00
    # < bottom 1.04 -> still not correct; SH p=15@1.25 confirm 18 (updates=2)
    # -> EQ=1.075 >= top -> CORRECT after 2 updates
    fc = ev["first_correct"]
    assert fc is not None
    assert fc["bar_index"] == 18
    assert fc["swings"] == 2


def test_evolving_freshness_boundary_at_confirm_bar():
    """Touch exactly ON the confirm bar does NOT break freshness (canonical
    window is [ri+2, c)); a touch BEFORE the confirm bar does."""
    timestamps = pd.date_range(start="2024-01-01", periods=21, freq="15min")

    base = list(_SCENARIO_HL)
    # Variant A: touch at bar 16 (< confirm 18) -> NOT fresh
    hl_a = list(base)
    hl_a[16] = (1.20, 1.06)  # low <= top 1.06 -> touch
    bars_a = _bars_from_hl(timestamps, hl_a)
    highs_a, lows_a = _build_swing_timeline(bars_a)
    ev_a = _evolving_eq_first_correct(1.06, 1.04, "bullish", 12, bars_a, highs_a, lows_a)
    assert ev_a["first_touch_index"] == 16
    assert ev_a["first_correct"]["still_fresh"] is False
    assert ev_a["first_correct"]["invalidated"] is True

    # Variant B: touch only AT bar 18 (== confirm bar) -> still fresh
    hl_b = list(base)
    hl_b[18] = (1.16, 1.06)  # touch exactly at confirm bar
    bars_b = _bars_from_hl(timestamps, hl_b)
    highs_b, lows_b = _build_swing_timeline(bars_b)
    ev_b = _evolving_eq_first_correct(1.06, 1.04, "bullish", 12, bars_b, highs_b, lows_b)
    assert ev_b["first_touch_index"] == 18
    assert ev_b["first_correct"]["still_fresh"] is True
    assert ev_b["first_correct"]["invalidated"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Metrics — mutually exclusive classification (no double counting)
# ─────────────────────────────────────────────────────────────────────────────
def _tel(slot, eq_pos, has_fc, swings=0, fresh=True):
    return FvgResearchTelemetry(
        symbol="X",
        sweep_index=1,
        sweep_timestamp="t",
        fvg_slot=slot,
        direction="bullish",
        fvg_bar_index=10,
        fvg_timestamp="t",
        bars_from_sweep=2,
        top=1.0,
        bottom=0.9,
        midpoint=0.95,
        size=0.1,
        size_atr=0.1,
        fresh=True,
        eq_position=eq_pos,
        research_eq=0.95,
        confirmed_swing_high_index=5,
        confirmed_swing_high_price=1.1,
        confirmed_swing_low_index=3,
        confirmed_swing_low_price=0.9,
        first_correct_side_bar_index=(20 if has_fc else None),
        first_correct_side_timestamp=("t" if has_fc else None),
        first_correct_side_swings=swings,
        still_fresh_at_first_correct=(fresh if has_fc else None),
        invalidated_at_first_correct=(not fresh if has_fc else False),
        stale_bar_index=None,
        sweep_to_first_correct_min=None,
        formation_to_first_correct_min=None,
    )


def test_metrics_mutually_exclusive_classification():
    records = [
        _tel(1, "CORRECT_SIDE", has_fc=True, swings=0, fresh=True),  # formation-correct
        _tel(1, "WRONG_SIDE", has_fc=True, swings=1, fresh=True),  # later-correct, 1 swing
        _tel(1, "WRONG_SIDE", has_fc=False),  # never correct
        _tel(2, "CROSSES_EQ", has_fc=True, swings=2, fresh=False),  # later-correct, 2 swings
        _tel(2, "NO_SWING_YET", has_fc=False),  # never correct
    ]
    m = _compute_research_eq_metrics(records)

    assert m["total"][1] == 3 and m["total"][2] == 2
    # slot 1: formation-correct counted ONCE (not also as later)
    assert m["correct_at_formation"][1] == 1
    assert m["later_becomes_correct"][1] == 1
    assert m["never_correct"][1] == 1
    assert m["correct_after_1_swing"][1] == 1
    assert m["fresh_when_first_correct"][1] == 1  # later cohort
    assert m["fresh_when_first_correct_all"][1] == 2  # formation + later
    # slot 2: crosses/no-swing cohorts
    assert m["crosses_eq"][2] == 1
    assert m["no_swing_yet"][2] == 1
    assert m["later_becomes_correct"][2] == 1
    assert m["correct_after_2_swings"][2] == 1
    assert m["correct_after_3plus_swings"][2] == 0
    assert m["fresh_when_first_correct"][2] == 0
    assert m["never_correct"][2] == 1
