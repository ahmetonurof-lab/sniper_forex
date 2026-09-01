#!/usr/bin/env python
"""MT5 Data Layer Module - Phase 0 / PHASE 1 HARDENED

Provides market data access from MT5.
Independent from trading layer and strategy.
Only provides data retrieval, no signal generation or trading logic.

PHASE 1 hardening (2026-08-27):
- last_error capture on every failure.
- Robust error handling around all MT5 calls.
- Never logs credentials.
"""

import MetaTrader5 as mt5

from src.config.mt5_config import get_mt5_config


class MT5DataLayer:
    """Provides market data access from MT5 terminal.

    Responsibilities:
    - Symbol information
    - Tick data
    - OHLC/bar data
    - No signal generation, no trading logic
    """

    def __init__(self):
        self.config = get_mt5_config()
        self._last_error = None

    def _capture_error(self, context: str) -> str:
        """Capture the last MT5 error into self._last_error and return it."""
        try:
            err = mt5.last_error()
        except Exception:
            err = (0, "unknown")
        self._last_error = err
        return f"{context}: {err}"

    @property
    def last_error(self):
        """Last captured MT5 error (tuple or None)."""
        return self._last_error

    def get_symbol_info(self, symbol_name):
        """Get symbol metadata.

        Args:
            symbol_name: Name of the symbol (e.g., "EURUSD")

        Returns:
            dict or None: Symbol information or None if not found
        """
        try:
            if not mt5.symbol_select(symbol_name, True):
                print(f"[WARN] Could not select symbol: {symbol_name}")
                return None
        except Exception as e:
            self._last_error = ("symbol_select_exception", str(e))
            print(f"[ERROR] symbol_select exception for {symbol_name}: {e}")
            return None

        symbol_info = mt5.symbol_info(symbol_name)
        if symbol_info:
            return {
                "name": symbol_name,
                "spread": symbol_info.spread,
                "digits": symbol_info.digits,
                "point": symbol_info.point,
                "trade_mode": symbol_info.trade_mode,
                "point_size": symbol_info.point,
            }
        return None

    def get_tick(self, symbol_name):
        """Get current tick data for a symbol.

        Args:
            symbol_name: Name of the symbol

        Returns:
            dict or None: Tick data with bid, ask, last, time
        """
        try:
            # Bug A fix (live boot 2026-09-01): MetaTrader5 exposes
            # symbol_info_tick(), not symbol_tick(). See
            # src/trading/mt5_connection.py:get_tick_data for the full
            # root-cause note.
            tick = mt5.symbol_info_tick(symbol_name)
        except Exception as e:
            self._last_error = ("symbol_info_tick_exception", str(e))
            print(f"[ERROR] symbol_info_tick exception for {symbol_name}: {e}")
            return None

        if tick:
            return {
                "bid": tick.bid,
                "ask": tick.ask,
                "last": tick.last,
                "time": tick.time,
                "volume": tick.volume,
            }
        return None

    def get_rates(self, symbol_name, timeframe="M1", count=100):
        """Get OHLC bar data for a symbol.

        Args:
            symbol_name: Name of the symbol
            timeframe: Timeframe string (M1, M5, M15, H1, H4, D1)
            count: Number of bars to retrieve

        Returns:
            list or None: List of rate dictionaries with time, open, high, low, close, tick_volume
        """
        timeframe_map = {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1,
        }

        tf = timeframe_map.get(timeframe, mt5.TIMEFRAME_M1)
        try:
            rates = mt5.copy_rates_from_pos(symbol_name, tf, 0, count)
        except Exception as e:
            self._last_error = ("copy_rates_exception", str(e))
            print(f"[ERROR] copy_rates exception for {symbol_name}: {e}")
            return None

        if rates is not None and len(rates) > 0:
            return rates
        return None

    def get_symbols_list(self):
        """Get list of all available symbols.

        Returns:
            list or None: List of symbol names
        """
        try:
            symbols = mt5.symbols_get()
        except Exception as e:
            self._last_error = ("symbols_get_exception", str(e))
            print(f"[ERROR] symbols_get exception: {e}")
            return None

        if symbols:
            return [str(sym.name) for sym in symbols]
        return None

    def find_forex_symbols(self, base="EUR", quote="USD"):
        """Find Forex symbols containing base/quote currencies.

        Args:
            base: Base currency (e.g., "EUR")
            quote: Quote currency (e.g., "USD")

        Returns:
            list or None: Matching symbol names
        """
        symbols = self.get_symbols_list()
        if symbols:
            return [s for s in symbols if base in s.upper() and quote in s.upper()]
        return None
