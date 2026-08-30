#!/usr/bin/env python
"""SNIPER FOREX — Entry Detector

Detects first-touch entry into FVG after sweep.
Baseline: FVG_TOUCH_ENTRY (wick touch sufficient).
"""

from typing import Optional

from src.strategy.models import FVG, Bar, Direction, EntryType, SweepEvent


def detect_first_touch(
    bar: Bar, fvg: FVG, daily_bias: Direction, sweep: SweepEvent
) -> Optional[EntryType]:
    """Detect if bar touches FVG for first time.

    Entry rules (from spec):
    - Wick touch of FVG is sufficient
    - No candle-close requirement for initial entry
    - FVG direction must agree with daily_bias

    For LONG (bullish):
    - Entry when price wicks down into FVG (low <= fvg_high and low >= fvg_low)
    - Or when price wicks below FVG (low < fvg_low)

    For SHORT (bearish):
    - Entry when price wicks up into FVG (high >= fvg_low and high <= fvg_high)
    - Or when price wicks above FVG (high > fvg_high)

    Args:
        bar: Current bar
        fvg: The FVG to check touch against
        daily_bias: Current daily bias
        sweep: The sweep event

    Returns:
        EntryType if touch detected, None otherwise
    """
    if fvg.direction == Direction.BULLISH:
        # Bullish FVG: price should come down into the gap
        # Wick touch: bar's low enters the FVG zone
        if bar.low <= fvg.fvg_high and bar.low >= fvg.fvg_low:
            return EntryType.FVG_TOUCH_ENTRY
        # Price wicks below FVG (deeper penetration)
        if bar.low < fvg.fvg_low:
            # Check if close is still above FVG low (wick only)
            if bar.close >= fvg.fvg_low:
                return EntryType.FVG_TOUCH_ENTRY

    elif fvg.direction == Direction.BEARISH:
        # Bearish FVG: price should come up into the gap
        # Wick touch: bar's high enters the FVG zone
        if bar.high >= fvg.fvg_low and bar.high <= fvg.fvg_high:
            return EntryType.FVG_TOUCH_ENTRY
        # Price wicks above FVG (deeper penetration)
        if bar.high > fvg.fvg_high:
            # Check if close is still below FVG high (wick only)
            if bar.close <= fvg.fvg_high:
                return EntryType.FVG_TOUCH_ENTRY

    return None


def calculate_sl_tp(fvg: FVG, direction: Direction, rr_ratio: float = 1.8) -> tuple:
    """Calculate SL and TP from FVG.

    From spec:
    - LONG: SL = FVG.bottom (fvg_low)
    - SHORT: SL = FVG.top (fvg_high)
    - TP = 1.8R

    Args:
        fvg: The entry FVG
        direction: Trade direction
        rr_ratio: Risk-reward ratio (default 1.8)

    Returns:
        Tuple of (sl, tp, entry_price)
    """
    if direction == Direction.BULLISH:
        sl = fvg.fvg_low
        entry_price = fvg.fvg_high  # Entry at top of FVG
        risk = entry_price - sl
        tp = entry_price + (risk * rr_ratio)
    else:  # BEARISH
        sl = fvg.fvg_high
        entry_price = fvg.fvg_low  # Entry at bottom of FVG
        risk = sl - entry_price
        tp = entry_price - (risk * rr_ratio)

    return sl, tp, entry_price
