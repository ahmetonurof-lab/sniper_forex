#!/usr/bin/env python
"""MT5 Trading Connection Module - Phase 0 / PHASE 1 HARDENED

Handles MetaTrader5 connection, login, and account/terminal information.
NO order sending, NO position management, NO trading logic.
Connection layer only.

PHASE 1 hardening (2026-08-27):
- Path-based initialize (uses MT5_TERMINAL_PATH from config when provided).
- last_error capture on every failure (never logs credentials).
- Terminal availability check.
- Reconnect / recovery (ensure_connected, reconnect).
- Structured status reporting.
"""

import MetaTrader5 as mt5

from src.config.mt5_config import get_mt5_config


class MT5Connection:
    """Manages MT5 connection lifecycle."""

    def __init__(self):
        self.config = get_mt5_config()
        self.connected = False
        self.account_info = None
        self.terminal_info = None
        self._last_error = None

    # ── Error helpers ──────────────────────────────────────────────
    def _capture_error(self, context: str) -> str:
        """Capture the last MT5 error into self._last_error and return it.

        Never includes credentials. Returns a human-readable string.
        """
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

    # ── Connection lifecycle ───────────────────────────────────────
    def connect(self):
        """Initialize MT5 connection and login.

        Returns:
            bool: True if connection successful, False otherwise
        """
        print("Initializing MetaTrader5...")

        # Initialize MT5 — use terminal path when provided in config
        terminal_path = self.config.get("terminal_path", "")
        try:
            if terminal_path:
                init_ok = mt5.initialize(path=terminal_path)
            else:
                init_ok = mt5.initialize()
        except Exception as e:
            self._last_error = ("initialize_exception", str(e))
            print(f"ERROR: MT5 initialize exception: {e}")
            return False

        if not init_ok:
            print(f"ERROR: MT5 initialize failed! {self._capture_error('initialize')}")
            return False

        print("[OK] MT5 initialized")

        # Terminal availability check
        self.terminal_info = mt5.terminal_info()
        if self.terminal_info is None:
            print(f"[WARN] Terminal info unavailable: {self._capture_error('terminal_info')}")
        else:
            print(
                f"[OK] Terminal connected: {self.terminal_info.path} (build {self.terminal_info.build})"
            )

        # Login
        try:
            login_result = mt5.login(
                login=int(self.config["login"]),
                password=self.config["password"],
                server=self.config["server"],
            )
            if not login_result:
                print(f"ERROR: Login failed! {self._capture_error('login')}")
                mt5.shutdown()
                self.connected = False
                return False
        except Exception as e:
            self._last_error = ("login_exception", str(e))
            print(f"ERROR: Login exception: {e}")
            mt5.shutdown()
            self.connected = False
            return False

        print("[OK] Login successful")
        self.connected = True

        # Get account information
        self.account_info = mt5.account_info()
        if self.account_info:
            print("[OK] Account information available")
            print(f"   Login: {self.account_info.login}")
            print(f"   Server: {self.account_info.server}")
            print(f"   Balance: {self.account_info.balance}")
            print(f"   Equity: {self.account_info.equity}")
        else:
            print(f"[WARN] Could not retrieve account info: {self._capture_error('account_info')}")

        return True

    def is_connected(self) -> bool:
        """Return True if the MT5 terminal is currently reachable."""
        if not self.connected:
            return False
        try:
            info = mt5.terminal_info()
            return info is not None
        except Exception:
            return False

    def reconnect(self, max_attempts: int = 3) -> bool:
        """Attempt to re-establish the MT5 connection.

        Args:
            max_attempts: Number of connect attempts.

        Returns:
            bool: True if reconnected, False otherwise.
        """
        if self.connected:
            try:
                mt5.shutdown()
            except Exception:
                pass
            self.connected = False

        for attempt in range(1, max_attempts + 1):
            print(f"[RECONNECT] attempt {attempt}/{max_attempts}")
            if self.connect():
                print("[RECONNECT] success")
                return True
        print(f"[RECONNECT] failed after {max_attempts} attempts")
        return False

    def ensure_connected(self, max_attempts: int = 3) -> bool:
        """Ensure the connection is alive; reconnect if not.

        Returns:
            bool: True if connected (already or after reconnect).
        """
        if self.is_connected():
            return True
        return self.reconnect(max_attempts=max_attempts)

    def get_symbol_info(self, symbol_name):
        """Get symbol information.

        Args:
            symbol_name: Name of the symbol (e.g., "EURUSD")

        Returns:
            dict or None: Symbol information or None if not found
        """
        if not self.ensure_connected():
            print("[ERROR] Not connected to MT5")
            return None

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
            }
        return None

    def get_tick_data(self, symbol_name):
        """Get tick data for a symbol.

        Args:
            symbol_name: Name of the symbol

        Returns:
            dict or None: Tick data or None if not available
        """
        if not self.ensure_connected():
            print("[ERROR] Not connected to MT5")
            return None

        try:
            tick = mt5.symbol_tick(symbol_name)
        except Exception as e:
            self._last_error = ("symbol_tick_exception", str(e))
            print(f"[ERROR] symbol_tick exception for {symbol_name}: {e}")
            return None

        if tick:
            return {
                "bid": tick.bid,
                "ask": tick.ask,
                "last": tick.last,
                "time": tick.time,
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
        if not self.ensure_connected():
            print("[ERROR] Not connected to MT5")
            return None

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

    def shutdown(self):
        """Clean shutdown of MT5 connection."""
        if self.connected:
            print("[OK] Shutting down MT5 connection...")
            try:
                mt5.shutdown()
            except Exception as e:
                self._last_error = ("shutdown_exception", str(e))
                print(f"[WARN] shutdown exception: {e}")
            self.connected = False
            print("[OK] MT5 connection closed")
