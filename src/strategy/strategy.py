#!/usr/bin/env python
"""SNIPER FOREX — Strategy Engine

Main strategy engine that processes M1 bars chronologically.
Baseline: SWEEP → FVG → FIRST TOUCH → ENTRY

No retrace in baseline. No trailing. No ATR fallback.
"""

from typing import List, Optional

import numpy as np

from src.strategy.entry import calculate_sl_tp, detect_first_touch
from src.strategy.fvg import detect_fvg
from src.strategy.models import FVG, Bar, SweepEvent, Trade, TradeResult, TradeSetup
from src.strategy.session import SessionManager
from src.strategy.trade_simulator import TradeSimulator


def calculate_atr(bars: List[Bar], period: int = 14) -> float:
    """Calculate ATR from bars.

    Args:
        bars: List of bars
        period: ATR period (default 14)

    Returns:
        Current ATR value
    """
    if len(bars) < period + 1:
        return 0.0

    trs = []
    for i in range(1, len(bars)):
        bar = bars[i]
        prev = bars[i - 1]
        tr = max(bar.high - bar.low, abs(bar.high - prev.close), abs(bar.low - prev.close))
        trs.append(tr)

    if len(trs) < period:
        return 0.0

    # Simple moving average of TR
    atr = np.mean(trs[-period:])
    return float(atr)


class StrategyEngine:
    """Baseline strategy engine.

    Flow per bar:
    1. Session update (CBDR tracking + sweep detection)
    2. After sweep: detect FVGs
    3. After FVG: detect first touch → entry
    4. Entry → trade simulation to exit
    """

    def __init__(
        self,
        symbol: str,
        rr_ratio: float = 1.8,
        start_hour: int = 19,
        end_hour: int = 1,
        sweep_atr_mult: float = 0.5,
        default_tolerance: float = 0.001,
    ):
        self.symbol = symbol
        self.rr_ratio = rr_ratio

        # Calculate ATR from data (will be set before run)
        self.sweep_atr_mult = sweep_atr_mult
        self.default_tolerance = default_tolerance

        self.session = None  # Will be initialized in run()
        self.simulator = TradeSimulator(symbol)
        self.trades: List[Trade] = []

        # State
        self.sweep_detected = False
        self.last_sweep: Optional[SweepEvent] = None
        self.fvgs: List[FVG] = []
        self.in_trade = False
        self.current_trade: Optional[Trade] = None
        self.entry_bar_index: Optional[int] = None
        self.fvg_detected_index: Optional[int] = None

    def run(self, bars: List[Bar]) -> List[Trade]:
        """Run strategy on bars chronologically.

        No look-ahead: each bar only sees past/current data.
        """
        self.trades = []

        # Calculate ATR from first 100 bars
        atr = calculate_atr(bars[:100], period=14)
        tolerance = atr * self.sweep_atr_mult if atr > 0 else self.default_tolerance

        self.session = SessionManager(
            symbol=self.symbol,
            start_hour=19,
            end_hour=1,
            atr=atr,
            sweep_atr_tolerance_mult=self.sweep_atr_mult,
            sweep_default_tolerance=self.default_tolerance,
        )

        # Override tolerance to use calculated value
        self.session.atr = atr

        for i, bar in enumerate(bars):
            self._process_bar(bar, bars, i)

        return self.trades

    def _process_bar(self, bar: Bar, bars: List[Bar], index: int):
        """Process a single bar through the strategy."""

        # 1. If in trade, simulate
        if self.in_trade and self.current_trade:
            self.simulator.simulate_exit(self.current_trade, bars, index)
            if self.current_trade.result != TradeResult.OPEN:
                self.trades.append(self.current_trade)
                self.in_trade = False
                self.current_trade = None
                self.entry_bar_index = None
                self.sweep_detected = False
                self.last_sweep = None
                self.fvgs = []
                self.fvg_detected_index = None
            return

        # 2. Session update (CBDR + sweep)
        sweep = self.session.update(bar)

        if sweep is not None:
            self.sweep_detected = True
            self.last_sweep = sweep
            self.fvgs = []
            self.fvg_detected_index = None

        # 3. If sweep detected, look for FVGs
        if self.sweep_detected and self.last_sweep:
            start_idx = self.last_sweep.bar_index + 1

            if index >= start_idx + 2:
                fvg = detect_fvg(bars, index, self.session.cbdr.daily_bias, self.symbol)
                if fvg and fvg.fvg_index > self.last_sweep.bar_index:
                    if not self.fvgs:
                        self.fvgs.append(fvg)
                        self.fvg_detected_index = fvg.fvg_index

        # 4. If FVG found, check for first touch
        if self.fvgs and not self.in_trade:
            fvg = self.fvgs[0]
            entry_type = detect_first_touch(bar, fvg, self.session.cbdr.daily_bias, self.last_sweep)

            if entry_type:
                sl, tp, entry_price = calculate_sl_tp(fvg, fvg.direction, self.rr_ratio)

                setup = TradeSetup(
                    symbol=self.symbol,
                    sweep=self.last_sweep,
                    fvg=fvg,
                    entry_type=entry_type,
                    direction=fvg.direction,
                    sl=sl,
                    tp=tp,
                    entry_price=entry_price,
                    entry_time=bar.timestamp,
                )

                self.current_trade = self.simulator.create_trade(
                    setup,
                    bars,
                    cbdr_high=self.session.cbdr.body_high,
                    cbdr_low=self.session.cbdr.body_low,
                )
                self.in_trade = True
                self.entry_bar_index = index
