#!/usr/bin/env python
"""SNIPER FOREX — Data Models

Core data models for the strategy engine.
Immutable dataclasses for bars, events, trades.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pandas as pd


class Direction(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class SweepType(Enum):
    BULLISH_SWEEP = "bullish_sweep"
    BEARISH_SWEEP = "bearish_sweep"


class EntryType(Enum):
    FVG_TOUCH_ENTRY = "fvg_touch_entry"
    FVG_RETRACE_ENTRY = "fvg_retrace_entry"
    PRE_TOUCH_ENTRY = "pre_touch_entry"
    AMBIGUOUS = "ambiguous"


class TradeResult(Enum):
    WIN = "win"
    LOSS = "loss"
    BREAKEVEN = "breakeven"
    OPEN = "open"


@dataclass(frozen=True)
class Bar:
    """Single M1 OHLCV bar."""

    index: int
    timestamp: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def body_high(self) -> float:
        return max(self.open, self.close)

    @property
    def body_low(self) -> float:
        return min(self.open, self.close)

    @property
    def body_size(self) -> float:
        return abs(self.close - self.open)

    @property
    def candle_range(self) -> float:
        return self.high - self.low


@dataclass
class CBDRState:
    """CBDR body accumulation state for a single trading day."""

    body_high: float = 0.0
    body_low: float = float("inf")
    locked: bool = False
    bias_locked: bool = False
    sweep_confirmed: bool = False
    sweep_direction: Optional[Direction] = None
    sweep_level: Optional[float] = None
    sweep_index: Optional[int] = None
    daily_bias: Direction = Direction.NEUTRAL

    def reset(self):
        self.body_high = 0.0
        self.body_low = float("inf")
        self.locked = False
        self.bias_locked = False
        self.sweep_confirmed = False
        self.sweep_direction = None
        self.sweep_level = None
        self.sweep_index = None
        self.daily_bias = Direction.NEUTRAL


@dataclass(frozen=True)
class SweepEvent:
    """Detected sweep event."""

    symbol: str
    timestamp: pd.Timestamp
    direction: Direction
    sweep_price: float
    reference_level: float  # body_high or body_low
    sweep_index: int
    bar_index: int
    tolerance: float


@dataclass(frozen=True)
class FVG:
    """Fair Value Gap."""

    symbol: str
    fvg_index: int
    fvg_first_candle: int  # bar index of first candle
    fvg_middle_candle: int  # bar index of middle (gap) candle
    fvg_third_candle: int  # bar index of third candle
    fvg_high: float
    fvg_low: float
    fvg_size: float
    direction: Direction
    creation_time: pd.Timestamp


@dataclass(frozen=True)
class TradeSetup:
    """A trade setup ready for simulation."""

    symbol: str
    sweep: SweepEvent
    fvg: FVG
    entry_type: EntryType
    direction: Direction
    sl: float
    tp: float
    entry_price: Optional[float] = None
    entry_time: Optional[pd.Timestamp] = None
    rejected_reason: Optional[str] = None


@dataclass
class Trade:
    """Completed or open trade."""

    trade_id: int
    symbol: str
    date: str
    session: str
    direction: Direction

    # CBDR
    cbdr_high: float = 0.0
    cbdr_low: float = 0.0
    cbdr_range: float = 0.0

    # Sweep
    sweep_time: Optional[pd.Timestamp] = None
    sweep_price: float = 0.0
    sweep_type: Optional[SweepType] = None
    sweep_index: int = 0

    # FVG
    fvg_time: Optional[pd.Timestamp] = None
    fvg_index: int = 0
    fvg_first_candle: int = 0
    fvg_middle_candle: int = 0
    fvg_third_candle: int = 0
    fvg_high: float = 0.0
    fvg_low: float = 0.0
    fvg_size: float = 0.0

    # Entry
    entry_time: Optional[pd.Timestamp] = None
    entry_price: float = 0.0
    entry_type: EntryType = EntryType.FVG_TOUCH_ENTRY

    # SL/TP
    sl: float = 0.0
    tp: float = 0.0

    # Exit
    exit_time: Optional[pd.Timestamp] = None
    exit_price: float = 0.0
    result: TradeResult = TradeResult.OPEN
    pnl_r: float = 0.0

    # Classification
    rejected_reason: Optional[str] = None
    anchor: Optional[str] = None
