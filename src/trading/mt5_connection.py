#!/usr/bin/env python
"""MT5 Trading Connection Module - Phase 0

Handles MetaTrader5 connection, login, and account/terminal information.
NO order sending, NO position management, NO trading logic.
Connection layer only.
"""

import MetaTrader5 as mt5
from src.config.mt5_config import get_mt5_config, mask_sensitive_info

class MT5Connection:
    """Manages MT5 connection lifecycle."""
    
    def __init__(self):
        self.config = get_mt5_config()
        self.connected = False
        self.account_info = None
        self.terminal_info = None
    
    def connect(self):
        """Initialize MT5 connection and login.
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        print("Initializing MetaTrader5...")
        
        # Initialize MT5
        if not mt5.initialize():
            print(f"ERROR: MT5 initialize failed! Error: {mt5.last_error()}")
            return False
        
        print("[OK] MT5 initialized")
        
        # Login
        try:
            login_result = mt5.login(
                login=int(self.config["login"]),
                password=self.config["password"],
                server=self.config["server"]
            )
            if not login_result:
                print(f"ERROR: Login failed! Error: {mt5.last_error()}")
                mt5.shutdown()
                return False
        except Exception as e:
            print(f"ERROR: Login exception: {e}")
            mt5.shutdown()
            return False
        
        print("[OK] Login successful")
        self.connected = True
        
        # Get account information
        self.account_info = mt5.account_info()
        if self.account_info:
            print(f"[OK] Account information available")
            print(f"   Login: {self.account_info.login}")
            print(f"   Server: {self.account_info.server}")
            print(f"   Balance: {self.account_info.balance}")
            print(f"   Equity: {self.account_info.equity}")
        else:
            print("[WARN] Could not retrieve account information")
        
        # Get terminal information
        self.terminal_info = mt5.terminal_info()
        if self.terminal_info:
            print(f"[OK] Terminal connected")
            print(f"   Terminal: {self.terminal_info.path}")
            print(f"   Build: {self.terminal_info.build}")
        else:
            print("[WARN] Could not retrieve terminal information")
        
        return True
    
    def get_symbol_info(self, symbol_name):
        """Get symbol information.
        
        Args:
            symbol_name: Name of the symbol (e.g., "EURUSD")
            
        Returns:
            dict or None: Symbol information or None if not found
        """
        if not self.connected:
            print("[ERROR] Not connected to MT5")
            return None
        
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
                "trade_mode": symbol_info.trade_mode
            }
        return None
    
    def get_tick_data(self, symbol_name):
        """Get tick data for a symbol.
        
        Args:
            symbol_name: Name of the symbol
            
        Returns:
            dict or None: Tick data or None if not available
        """
        if not self.connected:
            print("[ERROR] Not connected to MT5")
            return None
        
        tick = mt5.symbol_tick(symbol_name)
        if tick:
            return {
                "bid": tick.bid,
                "ask": tick.ask,
                "last": tick.last,
                "time": tick.time
            }
        return None
    
    def get_rates(self, symbol_name, timeframe="M1", count=10):
        """Get OHLC bar data for a symbol.
        
        Args:
            symbol_name: Name of the symbol
            timeframe: Timeframe (M1, M5, M15, H1, etc.)
            count: Number of bars to retrieve
            
        Returns:
            list or None: List of rate dictionaries or None if not available
        """
        if not self.connected:
            print("[ERROR] Not connected to MT5")
            return None
        
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
    
    def shutdown(self):
        """Clean shutdown of MT5 connection."""
        if self.connected:
            print("[OK] Shutting down MT5 connection...")
            mt5.shutdown()
            self.connected = False
            print("[OK] MT5 connection closed")