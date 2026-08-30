#!/usr/bin/env python
"""SNIPER FOREX — Sweep Detector

Identifies CBDR body sweeps on M1 bars.
Based on REAL_CBDR reference extract.
"""

from typing import Optional

from src.strategy.models import Bar, CBDRState, Direction, SweepEvent


def detect_sweep(
    bar: Bar, cbdr: CBDRState, tolerance: float, symbol: str = ""
) -> Optional[SweepEvent]:
    """Detect a sweep in the current bar.

    Sweep definition (from reference):
    - Bearish: high > body_high + tolerance AND close < body_high
    - Bullish: low < body_low - tolerance AND close > body_low

    First sweep only: if bias_locked, skip.

    Args:
        bar: Current bar
        cbdr: Current CBDR state
        tolerance: Sweep tolerance (ATR-based or default)
        symbol: Symbol name

    Returns:
        SweepEvent if detected, None otherwise
    """
    # First sweep only
    if cbdr.locked:
        return None

    # Need accumulated body
    if cbdr.body_high == 0.0 or cbdr.body_low == float("inf"):
        return None

    # Bearish sweep: wick above body_high, close back below
    if bar.high > cbdr.body_high + tolerance and bar.close < cbdr.body_high:
        return SweepEvent(
            symbol=symbol,
            timestamp=bar.timestamp,
            direction=Direction.BEARISH,
            sweep_price=bar.high,
            reference_level=cbdr.body_high,
            sweep_index=bar.index,
            bar_index=bar.index,
            tolerance=tolerance,
        )

    # Bullish sweep: wick below body_low, close back above
    if bar.low < cbdr.body_low - tolerance and bar.close > cbdr.body_low:
        return SweepEvent(
            symbol=symbol,
            timestamp=bar.timestamp,
            direction=Direction.BULLISH,
            sweep_price=bar.low,
            reference_level=cbdr.body_low,
            sweep_index=bar.index,
            bar_index=bar.index,
            tolerance=tolerance,
        )

    return None


def is_sweep_valid(sweep: SweepEvent, cbdr: CBDRState) -> bool:
    """Validate a sweep event against CBDR state."""
    if sweep.direction == Direction.BEARISH:
        return sweep.sweep_price > cbdr.body_high
    elif sweep.direction == Direction.BULLISH:
        return sweep.sweep_price < cbdr.body_low
    return False
