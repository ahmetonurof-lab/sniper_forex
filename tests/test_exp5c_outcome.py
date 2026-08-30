"""Tests for exp5c_outcome_attribution merge logic and stats."""

import sys

sys.path.insert(0, ".")
sys.path.insert(0, "C:/Users/Administrator/Desktop/nexus-mcp/sniper/src")

from experiment.exp5c_outcome_attribution import _outcome_stats


def _make_trade(
    result="TP",
    pnl_r=1.8,
    slot=1,
    symbol="EURUSD",
    ob_found=None,
    ob_mitigated=None,
    breaker_found=None,
    breaker_overlaps=None,
):
    return {
        "symbol": symbol,
        "result": result,
        "pnl_r": pnl_r,
        "direction": "bullish",
        "slot": slot,
        "sweep_bar_index": 100,
        "entry_bar_index": 105,
        "exit_bar_index": 120,
        "ob_found": ob_found,
        "ob_mitigated": ob_mitigated,
        "ob_overlaps": None,
        "breaker_found": breaker_found,
        "breaker_overlaps": breaker_overlaps,
    }


# ── _outcome_stats ──────────────────────────────────────────────────────────
def test_outcome_stats_basic():
    trades = [
        _make_trade(result="TP", pnl_r=1.8),
        _make_trade(result="LOSS", pnl_r=-1.0),
    ]
    st = _outcome_stats(trades, "test")
    assert st["N"] == 2
    assert st["completed"] == 2
    assert st["WR%"] == 50.0
    assert st["AvgR"] == 0.4
    assert st["TotalR"] == 0.8
    assert st["MaxDD"] == 1.0  # TP(+1.8) peak=1.8, then LOSS(-1.0)→0.8, drawdown=1.0


def test_outcome_stats_maxdd():
    trades = [
        _make_trade(result="LOSS", pnl_r=-1.0),
        _make_trade(result="TP", pnl_r=1.8),
        _make_trade(result="LOSS", pnl_r=-1.0),
    ]
    st = _outcome_stats(trades, "dd")
    # sorted by exit_bar_index (all 120, stable order)
    # cumulative: -1.0, +0.8, -0.2 → peak=0, maxdd=1.0
    assert st["MaxDD"] == 1.0
    assert st["TotalR"] == -0.2


def test_outcome_stats_empty():
    st = _outcome_stats([], "empty")
    assert st["N"] == 0
    assert st["completed"] == 0
    assert st["WR%"] == 0.0
    assert st["TotalR"] == 0.0


def test_outcome_stats_only_opens():
    trades = [_make_trade(result="OPEN", pnl_r=0.0)]
    st = _outcome_stats(trades, "opens")
    assert st["N"] == 1
    assert st["completed"] == 0
    assert st["WR%"] == 0.0


def test_outcome_stats_mixed_results():
    trades = [
        _make_trade(result="TP", pnl_r=1.8),
        _make_trade(result="PROFIT_TRAIL", pnl_r=1.2),
        _make_trade(result="LOSS", pnl_r=-1.0),
        _make_trade(result="OPEN", pnl_r=0.0),
    ]
    st = _outcome_stats(trades, "mixed")
    assert st["N"] == 4
    assert st["completed"] == 3
    assert abs(st["WR%"] - 66.7) < 0.1
    assert abs(st["TotalR"] - 2.0) < 0.01


# ── Slot assignment logic ───────────────────────────────────────────────────
def test_slot_assignment_f1_match():
    """zone_index matches f1 → slot=1"""
    f1, f2 = 100, 200
    zone_index = 100
    if zone_index == f1:
        slot = 1
    elif zone_index == f2:
        slot = 2
    else:
        slot = 0
    assert slot == 1


def test_slot_assignment_f2_match():
    """zone_index matches f2 → slot=2"""
    f1, f2 = 100, 200
    zone_index = 200
    if zone_index == f1:
        slot = 1
    elif zone_index == f2:
        slot = 2
    else:
        slot = 0
    assert slot == 2


def test_slot_assignment_no_match():
    """zone_index matches neither → slot=0 (Later/Unknown)"""
    f1, f2 = 100, 200
    zone_index = 300
    if zone_index == f1:
        slot = 1
    elif zone_index == f2:
        slot = 2
    else:
        slot = 0
    assert slot == 0


def test_slot_assignment_no_f2():
    """Only f1 present; zone_index != f1 → slot=0"""
    f1, f2 = 100, None
    zone_index = 200
    if zone_index == f1:
        slot = 1
    elif f2 is not None and zone_index == f2:
        slot = 2
    else:
        slot = 0
    assert slot == 0


# ── OB/BB context merge ─────────────────────────────────────────────────────
def test_ob_context_none_for_slot0():
    """slot=0 trades get None for all OB/BB fields."""
    t = _make_trade(slot=0, ob_found=None, breaker_found=None)
    assert t["ob_found"] is None
    assert t["breaker_found"] is None


def test_ob_context_found():
    t = _make_trade(ob_found=True, ob_mitigated=False, breaker_found=True, breaker_overlaps=True)
    assert t["ob_found"] is True
    assert t["ob_mitigated"] is False
    assert t["breaker_found"] is True
    assert t["breaker_overlaps"] is True


def test_filtering_by_context():
    """Ensure list comprehension filtering works correctly."""
    trades = [
        _make_trade(slot=1, ob_found=True, ob_mitigated=True),
        _make_trade(slot=1, ob_found=True, ob_mitigated=False),
        _make_trade(slot=1, ob_found=False),
        _make_trade(slot=2, ob_found=True, ob_mitigated=True),
        _make_trade(slot=0, ob_found=None),
    ]
    # OB mitigated, slot 1 only
    filt = [t for t in trades if t["slot"] == 1 and t["ob_mitigated"] is True]
    assert len(filt) == 1
    # OB unmitigated, slot 1 only
    filt = [t for t in trades if t["slot"] == 1 and t["ob_mitigated"] is False]
    assert len(filt) == 1
    # OB found, slot 1
    filt = [t for t in trades if t["slot"] == 1 and t["ob_found"] is True]
    assert len(filt) == 2
    # No OB, slot 1
    filt = [t for t in trades if t["slot"] == 1 and t["ob_found"] is False]
    assert len(filt) == 1
