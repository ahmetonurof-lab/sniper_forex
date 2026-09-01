"""Tests for PHASE 1 — MT5 Connection + Data Layer hardening.

These are PURE unit tests (no real MT5 terminal required). They mock the
MetaTrader5 module to validate:
- connect() failure handling (initialize / login)
- last_error capture
- reconnect() / ensure_connected() logic
- data layer error handling

Run via: python -m pytest tests/test_mt5_connection_hardening.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))


# ── MT5Connection tests ────────────────────────────────────────────────


def _make_connection():
    """Build an MT5Connection with a mocked config (no .env dependency)."""
    from src.trading.mt5_connection import MT5Connection

    conn = MT5Connection.__new__(MT5Connection)
    conn.config = {
        "login": "12345",
        "password": "secret",
        "server": "ICMarketsSC-Demo",
        "terminal_path": "",
    }
    conn.connected = False
    conn.account_info = None
    conn.terminal_info = None
    conn._last_error = None
    return conn


def test_connect_initialize_failure_captures_error():
    """initialize() returning False must capture last_error and return False."""
    conn = _make_connection()
    with patch("src.trading.mt5_connection.mt5") as mock_mt5:
        mock_mt5.initialize.return_value = False
        mock_mt5.last_error.return_value = (10004, "init failed")
        result = conn.connect()
    assert result is False
    assert conn.connected is False
    assert conn.last_error == (10004, "init failed")


def test_connect_login_failure_captures_error():
    """login() returning False must capture last_error, shutdown, return False."""
    conn = _make_connection()
    with patch("src.trading.mt5_connection.mt5") as mock_mt5:
        mock_mt5.initialize.return_value = True
        mock_mt5.terminal_info.return_value = MagicMock(path="C:/term", build=4000)
        mock_mt5.login.return_value = False
        mock_mt5.last_error.return_value = (10010, "login failed")
        result = conn.connect()
    assert result is False
    assert conn.connected is False
    assert conn.last_error == (10010, "login failed")
    mock_mt5.shutdown.assert_called_once()


def test_connect_success_sets_connected():
    """Successful initialize + login must set connected=True."""
    conn = _make_connection()
    with patch("src.trading.mt5_connection.mt5") as mock_mt5:
        mock_mt5.initialize.return_value = True
        mock_mt5.terminal_info.return_value = MagicMock(path="C:/term", build=4000)
        mock_mt5.login.return_value = True
        mock_mt5.account_info.return_value = MagicMock(
            login=12345, server="ICMarketsSC-Demo", balance=10000, equity=10000
        )
        result = conn.connect()
    assert result is True
    assert conn.connected is True
    assert conn.account_info is not None


def test_connect_uses_terminal_path_when_provided():
    """When terminal_path is set, initialize must be called with path=."""
    conn = _make_connection()
    conn.config["terminal_path"] = "C:/Program Files/MT5/terminal64.exe"
    with patch("src.trading.mt5_connection.mt5") as mock_mt5:
        mock_mt5.initialize.return_value = True
        mock_mt5.terminal_info.return_value = MagicMock(path="C:/term", build=4000)
        mock_mt5.login.return_value = True
        mock_mt5.account_info.return_value = MagicMock(login=12345, server="s", balance=1, equity=1)
        conn.connect()
    mock_mt5.initialize.assert_called_once_with(path="C:/Program Files/MT5/terminal64.exe")


def test_reconnect_calls_connect_until_success():
    """reconnect() must retry connect() and return True on success."""
    conn = _make_connection()
    with patch("src.trading.mt5_connection.mt5") as mock_mt5:
        mock_mt5.initialize.side_effect = [False, True]
        mock_mt5.last_error.return_value = (1, "err")
        mock_mt5.terminal_info.return_value = MagicMock(path="p", build=1)
        mock_mt5.login.return_value = True
        mock_mt5.account_info.return_value = MagicMock(login=1, server="s", balance=1, equity=1)
        result = conn.reconnect(max_attempts=3)
    assert result is True
    assert conn.connected is True
    assert mock_mt5.initialize.call_count == 2


def test_reconnect_fails_after_max_attempts():
    """reconnect() must return False when all attempts fail."""
    conn = _make_connection()
    with patch("src.trading.mt5_connection.mt5") as mock_mt5:
        mock_mt5.initialize.return_value = False
        mock_mt5.last_error.return_value = (1, "err")
        result = conn.reconnect(max_attempts=2)
    assert result is False
    assert conn.connected is False
    assert mock_mt5.initialize.call_count == 2


def test_ensure_connected_returns_true_when_connected():
    """ensure_connected() must return True when already connected."""
    conn = _make_connection()
    conn.connected = True
    with patch("src.trading.mt5_connection.mt5") as mock_mt5:
        mock_mt5.terminal_info.return_value = MagicMock(path="p", build=1)
        result = conn.ensure_connected()
    assert result is True


def test_get_rates_captures_exception():
    """get_rates() must capture copy_rates exception and return None."""
    conn = _make_connection()
    conn.connected = True
    with patch("src.trading.mt5_connection.mt5") as mock_mt5:
        mock_mt5.terminal_info.return_value = MagicMock(path="p", build=1)
        mock_mt5.copy_rates_from_pos.side_effect = Exception("boom")
        result = conn.get_rates("EURUSD", "M1", 10)
    assert result is None
    assert conn.last_error[0] == "copy_rates_exception"


# ── MT5DataLayer tests ─────────────────────────────────────────────────


def _make_data_layer():
    from src.data.mt5_data import MT5DataLayer

    dl = MT5DataLayer.__new__(MT5DataLayer)
    dl.config = {"server": "s", "login": "1", "password": "p", "terminal_path": ""}
    dl._last_error = None
    return dl


def test_data_layer_get_rates_captures_exception():
    """MT5DataLayer.get_rates() must capture exception and return None."""
    dl = _make_data_layer()
    with patch("src.data.mt5_data.mt5") as mock_mt5:
        mock_mt5.copy_rates_from_pos.side_effect = Exception("boom")
        result = dl.get_rates("EURUSD", "M1", 10)
    assert result is None
    assert dl.last_error[0] == "copy_rates_exception"


def test_data_layer_get_symbols_list_captures_exception():
    """MT5DataLayer.get_symbols_list() must capture exception and return None."""
    dl = _make_data_layer()
    with patch("src.data.mt5_data.mt5") as mock_mt5:
        mock_mt5.symbols_get.side_effect = Exception("boom")
        result = dl.get_symbols_list()
    assert result is None
    assert dl.last_error[0] == "symbols_get_exception"


# ── Bug A regression — real API surface (symbol_info_tick, NOT symbol_tick) ─
# The MetaTrader5 package has NO symbol_tick(); the old code called it and
# swallowed the resulting AttributeError into None, so the entry gate never
# opened live (proven at first live boot 2026-09-01). MagicMock auto-creates
# symbol_tick and hid the bug — these fakes deliberately OMIT it (§4.1).


class _RealSurfaceMT5:
    """Fake exposing ONLY the real MetaTrader5 call surface: symbol_info_tick
    exists, symbol_tick does NOT. Also satisfies ensure_connected()."""

    @staticmethod
    def terminal_info():
        return MagicMock(path="p", build=1)

    @staticmethod
    def symbol_info_tick(symbol):
        return MagicMock(bid=1.10001, ask=1.10002, last=1.10001, time=1788241900, volume=42)


def test_get_tick_data_uses_symbol_info_tick_not_symbol_tick():
    """Regression (Bug A): MT5Connection.get_tick_data() must call the real
    symbol_info_tick(). A fake WITHOUT symbol_tick must still return a dict."""
    conn = _make_connection()
    conn.connected = True
    assert not hasattr(_RealSurfaceMT5, "symbol_tick")  # fake is real-surface
    with patch("src.trading.mt5_connection.mt5", new=_RealSurfaceMT5()):
        result = conn.get_tick_data("EURUSD")
    assert result is not None, "get_tick_data returned None — symbol_tick bug"
    assert result["bid"] == 1.10001
    assert result["time"] == 1788241900


def test_data_layer_get_tick_uses_symbol_info_tick():
    """Regression (Bug A): MT5DataLayer.get_tick() must call symbol_info_tick()."""
    dl = _make_data_layer()
    with patch("src.data.mt5_data.mt5", new=_RealSurfaceMT5()):
        result = dl.get_tick("EURUSD")
    assert result is not None, "get_tick returned None — symbol_tick bug"
    assert result["volume"] == 42


def test_mt5_package_api_surface_pin():
    """Package-authoritative pin (verified live 2026-09-01): the installed
    MetaTrader5 build exposes symbol_info_tick (NOT symbol_tick) and the
    trade-mode enum DISABLED=0..FULL=4. Skips if the package is absent."""
    mt5 = pytest.importorskip("MetaTrader5")
    assert hasattr(mt5, "symbol_info_tick")
    assert not hasattr(mt5, "symbol_tick")
    assert mt5.SYMBOL_TRADE_MODE_DISABLED == 0
    assert mt5.SYMBOL_TRADE_MODE_LONGONLY == 1
    assert mt5.SYMBOL_TRADE_MODE_SHORTONLY == 2
    assert mt5.SYMBOL_TRADE_MODE_CLOSEONLY == 3
    assert mt5.SYMBOL_TRADE_MODE_FULL == 4
