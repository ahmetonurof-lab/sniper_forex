#!/usr/bin/env python
"""MT5 Data Layer Module - Phase 0

Provides market data access from MT5.
Independent from trading layer and strategy.
Only provides data retrieval, no signal generation or trading logic.
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
    
    def get_symbol_info(self, symbol_name):
        """Get symbol metadata.
        
        Args:
            symbol_name: Name of the symbol (e.g., "EURUSD")
            
        Returns:
            dict or None: Symbol information or None if not found
        """
        if not mt5.symbol_select(symbol_name, True):
            print(f"[WARN] Could not select symbol: {symbol_name}")
            return None
        
        symbol_info = mt5.symbol_info(symbol_name)
        if symbol_info:
            return {
                "name": symbol_name,
                "spread": symbol_info.spread,
                "digits": symbol_info.digits,
                "point": symbol_info.point,
                "trade_mode": symbol_info.trade_mode,
                "point_size": symbol_info.point
            }
        return None
    
    def get_tick(self, symbol_name):
        """Get current tick data for a symbol.
        
        Args:
            symbol_name: Name of the symbol
            
        Returns:
            dict or None: Tick data with bid, ask, last, time
        """
        tick = mt5.symbol_tick(symbol_name)
        if tick:
            return {
                "bid": tick.bid,
                "ask": tick.ask,
                "last": tick.last,
                "time": tick.time,
                "volume": tick.volume
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
            "D1": mt5.TIMEFRAME_D1
        }
        
        tf = timeframe_map.get(timeframe, mt5.TIMEFRAME_M1)
        rates = mt5.copy_rates_from_pos(symbol_name, tf, 0, count)
        
        if rates and len(rates) > 0:
            return rates
        return None
    
    def get_symbols_list(self):
        """Get list of all available symbols.
        
        Returns:
            list or None: List of symbol names
        """
        symbols = mt5.symbols_get()
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