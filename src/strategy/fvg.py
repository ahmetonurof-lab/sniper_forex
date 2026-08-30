#!/usr/bin/env python
"""SNIPER FOREX — FVG Detector

Identifies Fair Value Gaps on M1 bars.
FVG direction must agree with daily_bias.
"""

from typing import List, Optional

from src.strategy.models import FVG, Bar, Direction


def detect_fvg(
    bars: List[Bar], current_index: int, daily_bias: Direction, symbol: str = ""
) -> Optional[FVG]:
    """Detect FVG at current bar position.

    FVG requires 3 consecutive candles:
    - Candle 1 (first): establishes one side
    - Candle 2 (middle): creates the gap (strong move)
    - Candle 3 (third): confirms the gap exists

    Bullish FVG: candle 3 low > candle 1 high (gap up)
    Bearish FVG: candle 1 low > candle 3 high (gap down)

    FVG direction must agree with daily_bias.

    Args:
        bars: Full bar list
        current_index: Index of current bar (the third candle)
        daily_bias: Current daily bias direction
        symbol: Symbol name

    Returns:
        FVG if detected, None otherwise
    """
    if current_index < 2:
        return None

    bar1 = bars[current_index - 2]
    bar2 = bars[current_index - 1]
    bar3 = bars[current_index]

    # Bullish FVG: gap between candle 1 high and candle 3 low
    if bar3.low > bar1.high:
        fvg_high = bar3.low
        fvg_low = bar1.high
        fvg_size = fvg_high - fvg_low
        direction = Direction.BULLISH

        # Direction must agree with bias
        if daily_bias != Direction.BULLISH and daily_bias != Direction.NEUTRAL:
            return None

        return FVG(
            symbol=symbol,
            fvg_index=current_index,
            fvg_first_candle=bar1.index,
            fvg_middle_candle=bar2.index,
            fvg_third_candle=bar3.index,
            fvg_high=fvg_high,
            fvg_low=fvg_low,
            fvg_size=fvg_size,
            direction=direction,
            creation_time=bar3.timestamp,
        )

    # Bearish FVG: gap between candle 1 low and candle 3 high
    if bar1.low > bar3.high:
        fvg_high = bar1.low
        fvg_low = bar3.high
        fvg_size = fvg_high - fvg_low
        direction = Direction.BEARISH

        # Direction must agree with bias
        if daily_bias != Direction.BEARISH and daily_bias != Direction.NEUTRAL:
            return None

        return FVG(
            symbol=symbol,
            fvg_index=current_index,
            fvg_first_candle=bar1.index,
            fvg_middle_candle=bar2.index,
            fvg_third_candle=bar3.index,
            fvg_high=fvg_high,
            fvg_low=fvg_low,
            fvg_size=fvg_size,
            direction=direction,
            creation_time=bar3.timestamp,
        )

    return None


def find_all_fvgs(
    bars: List[Bar], start_index: int, daily_bias: Direction, symbol: str = ""
) -> List[FVG]:
    """Find all FVGs from start_index onwards.

    Args:
        bars: Full bar list
        start_index: Starting bar index (after sweep)
        daily_bias: Current daily bias
        symbol: Symbol name

    Returns:
        List of FVGs found
    """
    fvgs = []
    for i in range(start_index + 2, len(bars)):
        fvg = detect_fvg(bars, i, daily_bias, symbol)
        if fvg:
            fvgs.append(fvg)
    return fvgs
