#!/usr/bin/env python
"""SNIPER FOREX — Session Manager

Manages daily CBDR cycles, sweep detection, and bias locking.
Based on REAL_CBDR reference extract: 19:00→01:00 UTC window.
"""

from datetime import datetime
from typing import Optional

import pandas as pd

from src.strategy.models import Bar, CBDRState, Direction, SweepEvent


class SessionManager:
    """Manages daily session cycles and CBDR detection.

    CBDR window: 19:00→01:00 UTC (spans midnight)
    in_window = (h >= 19 or h < 1)

    Reference: REAL_CBDR profile from sniper reference extract
    """

    def __init__(
        self,
        symbol: str,
        start_hour: int = 19,
        end_hour: int = 1,
        atr: float = 0.0,
        sweep_atr_tolerance_mult: float = 0.5,
        sweep_default_tolerance: float = 10.0,
    ):
        """Initialize SessionManager.

        Args:
            symbol: Symbol name
            start_hour: CBDR window start hour (default 19)
            end_hour: CBDR window end hour (default 1)
            atr: Current ATR value for tolerance calculation
            sweep_atr_tolerance_mult: ATR multiplier for sweep tolerance
            sweep_default_tolerance: Default tolerance when ATR <= 0
        """
        self.symbol = symbol
        self.start_hour = start_hour
        self.end_hour = end_hour
        self.spans_midnight = start_hour > end_hour
        self.atr = atr
        self.sweep_atr_tolerance_mult = sweep_atr_tolerance_mult
        self.sweep_default_tolerance = sweep_default_tolerance

        # State
        self.cbdr = CBDRState()
        self.current_cbdr_key: Optional[str] = None

    def in_window(self, dt: datetime) -> bool:
        """Check if timestamp is inside CBDR window."""
        h = dt.hour
        if self.spans_midnight:
            return h >= self.start_hour or h < self.end_hour
        else:
            return self.start_hour <= h < self.end_hour

    def cbdr_day_key(self, dt: datetime) -> str:
        """Get CBDR day key for a timestamp.

        For spans_midnight windows, the day key is the date
        when the window ENDS (next calendar day).
        """
        h = dt.hour
        if self.spans_midnight:
            if h >= self.start_hour:
                # We're in the evening part — day key is tomorrow
                return (dt + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                # We're in the early morning part — day key is today
                return dt.strftime("%Y-%m-%d")
        else:
            return dt.strftime("%Y-%m-%d")

    def track_body(self, bar: Bar):
        """Accumulate CBDR body high/low from bars inside window.

        Reference: sniper/src/session.py:74-82
        body_high = max(body_high, open/close)
        body_low = min(body_low, open/close)
        """
        if self.cbdr.locked:
            return

        body_high = bar.body_high
        body_low = bar.body_low

        if self.cbdr.body_high == 0.0:
            self.cbdr.body_high = body_high
        else:
            self.cbdr.body_high = max(self.cbdr.body_high, body_high)

        if self.cbdr.body_low == float("inf"):
            self.cbdr.body_low = body_low
        else:
            self.cbdr.body_low = min(self.cbdr.body_low, body_low)

    def check_sweep(self, bar: Bar) -> Optional[SweepEvent]:
        """Check for sweep in current bar.

        Reference: sniper/src/session.py:89-128

        Bearish sweep: high > body_high + tolerance AND close < body_high
        Bullish sweep: low < body_low - tolerance AND close > body_low

        First sweep only: if bias_locked, return
        """
        if self.cbdr.bias_locked:
            return None

        if self.cbdr.body_high == 0.0 or self.cbdr.body_low == float("inf"):
            return None

        # Calculate tolerance
        if self.atr > 0:
            tolerance = self.atr * self.sweep_atr_tolerance_mult
        else:
            tolerance = self.sweep_default_tolerance

        # Check bearish sweep: price goes above body_high then closes below
        if bar.high > self.cbdr.body_high + tolerance and bar.close < self.cbdr.body_high:
            sweep = SweepEvent(
                symbol=self.symbol,
                timestamp=bar.timestamp,
                direction=Direction.BEARISH,
                sweep_price=bar.high,
                reference_level=self.cbdr.body_high,
                sweep_index=bar.index,
                bar_index=bar.index,
                tolerance=tolerance,
            )
            self._confirm_sweep(sweep)
            return sweep

        # Check bullish sweep: price goes below body_low then closes above
        if bar.low < self.cbdr.body_low - tolerance and bar.close > self.cbdr.body_low:
            sweep = SweepEvent(
                symbol=self.symbol,
                timestamp=bar.timestamp,
                direction=Direction.BULLISH,
                sweep_price=bar.low,
                reference_level=self.cbdr.body_low,
                sweep_index=bar.index,
                bar_index=bar.index,
                tolerance=tolerance,
            )
            self._confirm_sweep(sweep)
            return sweep

        return None

    def _confirm_sweep(self, sweep: SweepEvent):
        """Confirm sweep and lock bias."""
        self.cbdr.sweep_confirmed = True
        self.cbdr.sweep_direction = sweep.direction
        self.cbdr.sweep_level = sweep.sweep_price
        self.cbdr.sweep_index = sweep.bar_index
        self.cbdr.daily_bias = sweep.direction
        self.cbdr.bias_locked = True

    def lock_cbdr(self):
        """Lock CBDR when price exits window.

        Reference: sniper/src/session.py:451
        out_of_window and not locked and body_high > 0 → lock()
        """
        if not self.cbdr.locked and self.cbdr.body_high > 0.0:
            self.cbdr.locked = True

    def reset_for_new_cycle(self):
        """Reset all state for new CBDR cycle.

        Reference: sniper/src/session.py:129-137
        """
        self.cbdr.reset()

    def update(self, bar: Bar) -> Optional[SweepEvent]:
        """Process a bar through the session engine.

        Returns:
            SweepEvent if sweep detected, None otherwise
        """
        dt = bar.timestamp.to_pydatetime()
        cbdr_key = self.cbdr_day_key(dt)

        # Check for new cycle
        if self.current_cbdr_key is not None and cbdr_key != self.current_cbdr_key:
            self.reset_for_new_cycle()

        self.current_cbdr_key = cbdr_key

        in_w = self.in_window(dt)

        if in_w:
            # Inside window: track body only (no sweep check)
            self.track_body(bar)
        else:
            # Outside window: lock body accumulation first bar only
            if not self.cbdr.locked and self.cbdr.body_high > 0.0:
                self.cbdr.locked = True

            # Check for sweep on EVERY bar outside window
            # (bias_locked prevents re-detection after first sweep)
            if not self.cbdr.bias_locked:
                sweep = self.check_sweep(bar)
                if sweep:
                    return sweep

        return None
