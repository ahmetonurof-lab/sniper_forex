"""SNIPER FOREX — Strategy Module

Core strategy engine for backtesting.
"""

from src.strategy.data_loader import DataLoader
from src.strategy.entry import calculate_sl_tp, detect_first_touch
from src.strategy.fvg import detect_fvg, find_all_fvgs
from src.strategy.models import (
    FVG,
    Bar,
    CBDRState,
    Direction,
    EntryType,
    SweepEvent,
    SweepType,
    Trade,
    TradeResult,
    TradeSetup,
)
from src.strategy.session import SessionManager
from src.strategy.strategy import StrategyEngine
from src.strategy.sweep import detect_sweep, is_sweep_valid
from src.strategy.trade_simulator import TradeSimulator

__all__ = [
    "Bar",
    "Direction",
    "SweepType",
    "EntryType",
    "TradeResult",
    "CBDRState",
    "SweepEvent",
    "FVG",
    "TradeSetup",
    "Trade",
    "DataLoader",
    "SessionManager",
    "detect_sweep",
    "is_sweep_valid",
    "detect_fvg",
    "find_all_fvgs",
    "detect_first_touch",
    "calculate_sl_tp",
    "TradeSimulator",
    "StrategyEngine",
]
