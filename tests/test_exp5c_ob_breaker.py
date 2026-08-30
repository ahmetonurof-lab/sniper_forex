"""
EXP 5C — OB & Breaker Block forensic rule tests
================================================
Each test maps 1:1 to a rule in results/research/exp5c_ob_breaker_definitions.md
(OB-R1..R3, BB-R1..R5) plus the mirror (bearish) variants.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from experiment.exp5c_ob_breaker_forensics import (
    _zones_overlap,
    find_breaker_block,
    find_order_block,
)
from src.strategy.models import Bar


def _bars_from_hl(hl_pairs, start="2024-01-01"):
    ts = pd.date_range(start=start, periods=len(hl_pairs), freq="15min")
    bars = []
    for i, ((h, l), t) in enumerate(zip(hl_pairs, ts)):
        mid = (h + l) / 2
        bars.append(Bar(index=i, timestamp=t, open=mid, high=h, low=l, close=mid, volume=100.0))
    return bars


def _set_oc(bars, idx, open_, close_):
    """Force specific open/close on a bar while keeping high/low consistent."""
    b = bars[idx]
    hi = max(b.high, open_, close_)
    lo = min(b.low, open_, close_)
    bars[idx] = Bar(
        index=b.index,
        timestamp=b.timestamp,
        open=open_,
        high=hi,
        low=lo,
        close=close_,
        volume=b.volume,
    )


def _bars_from_ohlc(ohlc_pairs, start="2024-01-01"):
    """Build bars from exact (open, high, low, close) tuples — no implicit
    range expansion, zones stay exactly as specified."""
    ts = pd.date_range(start=start, periods=len(ohlc_pairs), freq="15min")
    return [
        Bar(index=i, timestamp=t, open=o, high=h, low=l, close=c, volume=100.0)
        for i, ((o, h, l, c), t) in enumerate(zip(ohlc_pairs, ts))
    ]


# Reusable shapes (explicit OHLC so zones are exact):
_AMBIENT = (0.9930, 0.9935, 0.9925, 0.9930)  # neutral candle INSIDE breaker zones


def _breaker_fixture(n=40, fvg_first=25):
    """Bullish-breaker scenario: candidate z=10 zone [0.9900, 0.9960],
    engineered failure at 13 (close 0.9850 < 0.9900), flip at 17 (close 1.0000
    > 0.9960). Ambient candles sit inside the zone -> no premature events."""
    ohlc = [_AMBIENT] * n
    ohlc[10] = (0.9950, 0.9960, 0.9900, 0.9920)  # bearish breaker candidate
    ohlc[13] = (0.9880, 0.9885, 0.9845, 0.9850)  # FAILURE close < zone low
    ohlc[17] = (0.9970, 1.0005, 0.9965, 1.0000)  # FLIP close > zone high
    return _bars_from_ohlc(ohlc)


# ── Order Block ──────────────────────────────────────────────────────────────
def test_bullish_ob_basic():
    """OB-R1+R2: bearish candle displaced by a later CLOSE above its high."""
    hl = [(1.00, 0.98)] * 20
    bars = _bars_from_hl(hl)
    _set_oc(bars, 10, 0.99, 0.985)  # bearish candle at idx 10 (close<open)
    _set_oc(bars, 12, 0.99, 1.005)  # close above high(≈0.99) -> displacement

    ob = find_order_block(bars, "bullish", fvg_first=15)
    assert ob is not None
    assert ob["index"] == 10
    assert ob["bars_from_fvg"] == 5
    assert ob["top"] >= 0.99 and ob["bottom"] <= 0.985


def test_bullish_ob_requires_close_displacement():
    """OB-R2: wick above the candidate high without a CLOSE above -> no OB."""
    hl = [(1.00, 0.98)] * 20
    bars = _bars_from_hl(hl)
    _set_oc(bars, 10, 0.99, 0.985)  # bearish candle
    # wick above high but close below it
    b = bars[12]
    bars[12] = Bar(
        index=b.index,
        timestamp=b.timestamp,
        open=b.open,
        high=1.02,
        low=b.low,
        close=0.988,
        volume=b.volume,
    )

    assert find_order_block(bars, "bullish", fvg_first=15) is None


def test_bullish_ob_nearest_candidate_wins():
    """OB-R3: two qualifying candidates -> the LATEST one is selected."""
    hl = [(1.00, 0.98)] * 30
    bars = _bars_from_hl(hl)
    _set_oc(bars, 8, 0.99, 0.985)
    _set_oc(bars, 11, 0.99, 0.985)
    _set_oc(bars, 13, 0.99, 1.005)  # displaces both

    ob = find_order_block(bars, "bullish", fvg_first=15)
    assert ob is not None and ob["index"] == 11


def test_bullish_ob_window_limit():
    """OB-R1: qualifying candle just OUTSIDE W_OB window -> None."""
    hl = [(1.00, 0.98)] * 40
    bars = _bars_from_hl(hl)
    _set_oc(bars, 4, 0.99, 0.985)
    _set_oc(bars, 6, 0.99, 1.005)  # displacement right after candidate
    # FVG_FIRST = 4 + 10 + 1 = 15 -> candidate at distance 11 > W_OB=10
    assert find_order_block(bars, "bullish", fvg_first=15, window=10) is None
    # widening the window finds it
    assert find_order_block(bars, "bullish", fvg_first=15, window=12) is not None


def test_bearish_ob_mirror():
    """Bearish OB mirror of OB-R1/R2."""
    hl = [(1.00, 0.98)] * 20
    bars = _bars_from_hl(hl)
    _set_oc(bars, 10, 0.985, 0.99)  # bullish candle (close>open)
    _set_oc(bars, 12, 0.99, 0.965)  # close below low -> displacement down

    ob = find_order_block(bars, "bearish", fvg_first=15)
    assert ob is not None and ob["index"] == 10


def test_ob_mitigation_flag():
    """Mitigation: price returned into the OB zone before the FVG."""
    # OB candle idx8 zone [0.9900, 0.9955]; displacement close 1.0005 at idx10
    # (its low stays ABOVE the zone top so it does not count as a touch).
    ohlc = [(1.0000, 1.0005, 0.9995, 1.0000)] * 25
    ohlc[8] = (0.9950, 0.9955, 0.9900, 0.9920)  # bearish OB candidate
    ohlc[10] = (0.9970, 1.0010, 0.9970, 1.0005)  # displacement up (no touch)
    bars = _bars_from_ohlc(ohlc)

    ob = find_order_block(bars, "bullish", fvg_first=15)
    assert ob is not None and ob["index"] == 8
    assert ob["mitigated_before_fvg"] is False

    # dip back into the zone at idx 12 (low <= zone high) -> mitigated
    ohlc[12] = (0.9958, 0.9965, 0.9940, 0.9960)  # bullish candle, dips into zone
    bars2 = _bars_from_ohlc(ohlc)
    ob2 = find_order_block(bars2, "bullish", fvg_first=15)
    assert ob2 is not None and ob2["index"] == 8
    assert ob2["mitigated_before_fvg"] is True


# ── Breaker Block ────────────────────────────────────────────────────────────
def test_bullish_breaker_full_sequence():
    """BB-R1..R4: bearish candle -> close below low (failure) -> close above high (flip)."""
    bars = _breaker_fixture()

    bb = find_breaker_block(bars, "bullish", fvg_first=25)
    assert bb is not None
    assert bb["index"] == 10
    assert bb["failure_index"] == 13
    assert bb["flip_index"] == 17
    assert bb["flip_to_fvg_bars"] == 25 - 17


def test_breaker_failure_without_flip_is_none():
    """BB-R3: failure without subsequent flip -> None."""
    ohlc = [_AMBIENT] * 40
    ohlc[10] = (0.9950, 0.9960, 0.9900, 0.9920)
    ohlc[13] = (0.9880, 0.9885, 0.9845, 0.9850)  # failure only; never reclaims
    bars = _bars_from_ohlc(ohlc)

    assert find_breaker_block(bars, "bullish", fvg_first=25) is None


def test_breaker_wick_failure_not_counted():
    """BB-R2: low pierced by WICK only (no close below low) -> no failure."""
    ohlc = [_AMBIENT] * 40
    ohlc[10] = (0.9950, 0.9960, 0.9900, 0.9920)
    ohlc[13] = (0.9930, 0.9935, 0.9850, 0.9930)  # wick below low, close inside zone
    ohlc[17] = (0.9970, 1.0005, 0.9965, 1.0000)
    bars = _bars_from_ohlc(ohlc)

    assert find_breaker_block(bars, "bullish", fvg_first=25) is None


def test_breaker_events_after_fvg_do_not_qualify():
    """BB-R4: failure/flip completing at or after FVG_FIRST -> None (as-of)."""
    ohlc = [_AMBIENT] * 40
    ohlc[10] = (0.9950, 0.9960, 0.9900, 0.9920)
    ohlc[24] = (0.9880, 0.9885, 0.9845, 0.9850)  # failure just before FVG_FIRST
    ohlc[26] = (0.9970, 1.0005, 0.9965, 1.0000)  # flip AFTER fvg_first=25
    bars = _bars_from_ohlc(ohlc)

    assert find_breaker_block(bars, "bullish", fvg_first=25) is None


def test_breaker_latest_flip_wins():
    """BB-R5: two valid sequences -> latest flip completion wins."""
    n = 60
    ohlc = [_AMBIENT] * n
    for z in (8, 20):
        ohlc[z] = (0.9950, 0.9960, 0.9900, 0.9920)  # candidates
    ohlc[11] = (0.9880, 0.9885, 0.9845, 0.9850)  # failure for z=8
    ohlc[14] = (0.9970, 1.0005, 0.9965, 1.0000)  # flip#1 (z=8 @14)
    ohlc[23] = (0.9880, 0.9885, 0.9845, 0.9850)  # failure for z=20
    ohlc[27] = (0.9970, 1.0005, 0.9965, 1.0000)  # flip#2 later (z=20 @27)
    bars = _bars_from_ohlc(ohlc)

    bb = find_breaker_block(bars, "bullish", fvg_first=35)
    assert bb is not None
    assert bb["index"] == 20
    assert bb["flip_index"] == 27


def test_bearish_breaker_mirror():
    """Bearish breaker mirror of BB-R1..R4."""
    ohlc = [_AMBIENT] * 40
    ohlc[10] = (0.9920, 0.9960, 0.9900, 0.9950)  # bullish candidate z
    ohlc[13] = (0.9970, 1.0005, 0.9965, 1.0000)  # FAILURE: close > high(z)
    ohlc[17] = (0.9890, 0.9895, 0.9845, 0.9850)  # FLIP: close < low(z)
    bars = _bars_from_ohlc(ohlc)

    bb = find_breaker_block(bars, "bearish", fvg_first=25)
    assert bb is not None
    assert bb["index"] == 10
    assert bb["failure_index"] == 13
    assert bb["flip_index"] == 17


# ── Overlap helper ───────────────────────────────────────────────────────────
def test_zones_overlap_strict():
    assert _zones_overlap(1.05, 1.00, 1.03, 0.98) is True  # intersect
    assert _zones_overlap(1.05, 1.00, 1.00, 0.95) is False  # touch only
    assert _zones_overlap(1.05, 1.00, 1.10, 1.06) is False  # disjoint
