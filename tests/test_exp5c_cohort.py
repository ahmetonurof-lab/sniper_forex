"""Tests for exp5c_research_eq_cohort classification logic."""

import sys

sys.path.insert(0, ".")

from experiment.exp5c_research_eq_cohort import _classify_cohort, _outcome_stats


def _make_tel(
    eq_position="WRONG_SIDE",
    fresh=False,
    first_correct_bar=None,
    still_fresh=None,
    swings=0,
):
    return {
        "symbol": "EURUSD",
        "sweep_index": 1,
        "fvg_slot": 1,
        "eq_position": eq_position,
        "fresh": fresh,
        "first_correct_side_bar_index": first_correct_bar,
        "still_fresh_at_first_correct": still_fresh,
        "first_correct_side_swings": swings,
        "research_eq": 1.1000,
    }


def _make_trade(result="TP", pnl_r=1.8, slot=1, zone_index=100):
    return {
        "symbol": "EURUSD",
        "result": result,
        "pnl_r": pnl_r,
        "direction": "bullish",
        "slot": slot,
        "zone_index": zone_index,
        "sweep_bar_index": 50,
        "entry_bar_index": 55,
        "exit_bar_index": 70,
        "ob_found": None,
        "ob_mitigated": None,
        "breaker_found": None,
        "breaker_overlaps": None,
    }


# ── _classify_cohort ────────────────────────────────────────────────────────
def test_correct_fresh():
    t = _make_tel(eq_position="CORRECT_SIDE", fresh=True)
    assert _classify_cohort(t) == "CORRECT_AT_FORMATION + FRESH"


def test_correct_stale():
    t = _make_tel(eq_position="CORRECT_SIDE", fresh=False)
    assert _classify_cohort(t) == "CORRECT_AT_FORMATION + STALE"


def test_later_correct_fresh():
    t = _make_tel(eq_position="WRONG_SIDE", first_correct_bar=200, still_fresh=True)
    assert _classify_cohort(t) == "WRONG_LATER_CORRECT + FRESH"


def test_later_correct_stale():
    t = _make_tel(eq_position="WRONG_SIDE", first_correct_bar=200, still_fresh=False)
    assert _classify_cohort(t) == "WRONG_LATER_CORRECT + STALE"


def test_never_correct():
    t = _make_tel(eq_position="WRONG_SIDE", first_correct_bar=None)
    assert _classify_cohort(t) == "NEVER_CORRECT"


def test_crosses_eq_never_correct():
    t = _make_tel(eq_position="CROSSES_EQ", first_correct_bar=None)
    assert _classify_cohort(t) == "NEVER_CORRECT"


def test_crosses_eq_later_correct():
    t = _make_tel(eq_position="CROSSES_EQ", first_correct_bar=150, still_fresh=True)
    assert _classify_cohort(t) == "WRONG_LATER_CORRECT + FRESH"


def test_no_swing_yet_never_correct():
    t = _make_tel(eq_position="NO_SWING_YET", first_correct_bar=None)
    assert _classify_cohort(t) == "NEVER_CORRECT"


# ── _outcome_stats (same as exp5c_outcome tests, but import from cohort module) ──
def test_stats_basic():
    trades = [
        _make_trade(result="TP", pnl_r=1.8),
        _make_trade(result="LOSS", pnl_r=-1.0),
    ]
    st = _outcome_stats(trades, "test")
    assert st["N"] == 2
    assert st["completed"] == 2
    assert st["WR%"] == 50.0
    assert st["TotalR"] == 0.8


def test_stats_empty():
    st = _outcome_stats([], "empty")
    assert st["N"] == 0
    assert st["completed"] == 0
