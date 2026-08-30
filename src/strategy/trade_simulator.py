#!/usr/bin/env python
"""SNIPER FOREX — Trade Simulator

Simulates trade execution from entry to exit.
Deterministic: same bars → same result.
"""

from typing import List

from src.strategy.models import (
    Bar,
    Direction,
    SweepType,
    Trade,
    TradeResult,
    TradeSetup,
)


class TradeSimulator:
    """Simulates trade execution."""

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.trade_counter = 0

    def create_trade(
        self,
        setup: TradeSetup,
        bars: List[Bar],
        cbdr_high: float = 0.0,
        cbdr_low: float = 0.0,
    ) -> Trade:
        """Create a trade from a setup."""
        self.trade_counter += 1

        sweep = setup.sweep
        fvg = setup.fvg

        sweep_type = (
            SweepType.BEARISH_SWEEP
            if sweep.direction == Direction.BEARISH
            else SweepType.BULLISH_SWEEP
        )

        return Trade(
            trade_id=self.trade_counter,
            symbol=self.symbol,
            date=str(sweep.timestamp.date()),
            session="",
            direction=setup.direction,
            cbdr_high=cbdr_high,
            cbdr_low=cbdr_low,
            cbdr_range=cbdr_high - cbdr_low if cbdr_high > 0 and cbdr_low > 0 else 0.0,
            sweep_time=sweep.timestamp,
            sweep_price=sweep.sweep_price,
            sweep_type=sweep_type,
            sweep_index=sweep.sweep_index,
            fvg_time=fvg.creation_time,
            fvg_index=fvg.fvg_index,
            fvg_first_candle=fvg.fvg_first_candle,
            fvg_middle_candle=fvg.fvg_middle_candle,
            fvg_third_candle=fvg.fvg_third_candle,
            fvg_high=fvg.fvg_high,
            fvg_low=fvg.fvg_low,
            fvg_size=fvg.fvg_size,
            entry_time=setup.entry_time,
            entry_price=setup.entry_price or 0.0,
            entry_type=setup.entry_type,
            sl=setup.sl,
            tp=setup.tp,
        )

    def simulate_exit(self, trade: Trade, bars: List[Bar], start_bar_index: int) -> Trade:
        """Simulate trade from entry bar to exit.

        Exit conditions:
        - TP hit → win
        - SL hit → loss
        - End of data → open

        Note: No trailing, no ATR fallback in baseline.
        Only initial SL/TP.
        """
        if trade.entry_price == 0.0 or trade.sl == 0.0 or trade.tp == 0.0:
            trade.result = TradeResult.OPEN
            return trade

        for i in range(start_bar_index, len(bars)):
            bar = bars[i]

            if trade.direction == Direction.BULLISH:
                # Check SL first (worst case)
                if bar.low <= trade.sl:
                    trade.exit_time = bar.timestamp
                    trade.exit_price = trade.sl
                    trade.result = TradeResult.LOSS
                    trade.pnl_r = -1.0  # -1R loss
                    return trade

                # Check TP
                if bar.high >= trade.tp:
                    trade.exit_time = bar.timestamp
                    trade.exit_price = trade.tp
                    trade.result = TradeResult.WIN
                    risk = trade.entry_price - trade.sl
                    trade.pnl_r = (trade.tp - trade.entry_price) / risk if risk > 0 else 0.0
                    return trade

            else:  # BEARISH
                # Check SL first (worst case)
                if bar.high >= trade.sl:
                    trade.exit_time = bar.timestamp
                    trade.exit_price = trade.sl
                    trade.result = TradeResult.LOSS
                    trade.pnl_r = -1.0
                    return trade

                # Check TP
                if bar.low <= trade.tp:
                    trade.exit_time = bar.timestamp
                    trade.exit_price = trade.tp
                    trade.result = TradeResult.WIN
                    risk = trade.sl - trade.entry_price
                    trade.pnl_r = (trade.entry_price - trade.tp) / risk if risk > 0 else 0.0
                    return trade

        # End of data
        trade.result = TradeResult.OPEN
        return trade
