#!/usr/bin/env python
"""TAŞ-1 — Orchestrator startup + lock ownership contract tests."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from src.live.orchestrator import (
    Lock,
    LockData,
    LockError,
    Orchestrator,
    OrchestratorConfig,
    StartupPhase,
    StartupVerdict,
)

# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def tmp_state(tmp_path: Path) -> Path:
    return tmp_path / "state"


@pytest.fixture
def orch(tmp_state: Path) -> Orchestrator:
    return Orchestrator(state_dir=str(tmp_state))


# ── Lock basics ───────────────────────────────────────────────────


class TestLock:
    def test_acquire_creates_file(self, tmp_state: Path):
        lock = Lock(tmp_state / "orch.lock")
        lock.acquire()
        assert lock.owned
        assert (tmp_state / "orch.lock").exists()

    def test_acquire_raises_on_conflict(self, tmp_state: Path):
        lock1 = Lock(tmp_state / "orch.lock")
        lock1.acquire()
        lock2 = Lock(tmp_state / "orch.lock")
        with pytest.raises(LockError):
            lock2.acquire()

    def test_release_removes_file(self, tmp_state: Path):
        lock = Lock(tmp_state / "orch.lock")
        lock.acquire()
        lock.release()
        assert not lock.owned
        assert not (tmp_state / "orch.lock").exists()

    def test_release_idempotent(self, tmp_state: Path):
        lock = Lock(tmp_state / "orch.lock")
        lock.acquire()
        lock.release()
        lock.release()  # second release must not raise

    def test_release_no_op_if_not_owned(self, tmp_state: Path):
        lock = Lock(tmp_state / "orch.lock")
        lock.release()  # never acquired — must be no-op

    def test_release_does_not_remove_other_pid_lock(self, tmp_state: Path):
        lock_path = tmp_state / "orch.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        foreign = LockData(pid=999999, created_at=time.time(), phase="other")
        lock_path.write_text(json.dumps(foreign.to_dict()), encoding="utf-8")
        lock = Lock(lock_path)
        lock.release()  # not our pid — file must remain
        assert lock_path.exists()

    def test_stale_lock_taken_over(self, tmp_state: Path):
        lock_path = tmp_state / "orch.lock"
        stale = LockData(
            pid=999999,
            created_at=time.time() - 99999,  # very old
            phase="stale",
        )
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(json.dumps(stale.to_dict()), encoding="utf-8")
        lock = Lock(lock_path)
        lock.acquire()  # should succeed (stale)
        assert lock.owned

    def test_write_recovers_from_transient_open_error(self, tmp_state: Path, monkeypatch):
        """N2 #17: a transient OSError (WinError 5) on the IN-PLACE lock
        write open is retried and the lock write eventually succeeds — the
        primary crash site of the T0 WinError 5 incident. (Name continuity
        from N2 #15; the rename step no longer exists on the lock path.)"""
        lock = Lock(tmp_state / "orch.lock")
        lock.acquire()
        assert lock.owned

        # Simulate the in-place open failing once (transient handle lock)
        # then succeeding: patch os.open so the first orch.lock open raises
        # PermissionError, later calls behave normally.
        real_open = os.open
        calls = {"n": 0}

        def flaky_open(path, flags, *a, **k):
            if str(path).endswith("orch.lock") and calls["n"] == 0:
                calls["n"] += 1
                raise PermissionError(5, "Access is denied")
            return real_open(path, flags, *a, **k)

        monkeypatch.setattr(os, "open", flaky_open)
        import src.live.orchestrator as _orch

        monkeypatch.setattr(_orch.time, "sleep", lambda s: None)
        lock.heartbeat()  # must not raise despite one transient failure
        assert lock.owned
        assert (tmp_state / "orch.lock").exists()
        # After the retry the file content is our own PID.
        data = json.loads((tmp_state / "orch.lock").read_text(encoding="utf-8"))
        assert data["pid"] == os.getpid()


# ── Startup: FATAL → lock released ────────────────────────────────


class TestStartupFatal:
    def test_fatal_config_invalid_releases_lock(self, tmp_state: Path, monkeypatch):
        """S0 config fail → FATAL + lock released."""

        def bad_config():
            raise ValueError("MT5_LOGIN not set")

        monkeypatch.setattr("src.live.orchestrator.get_mt5_config", bad_config)
        orch = Orchestrator(state_dir=str(tmp_state))
        result = orch.startup()
        assert result.verdict == StartupVerdict.FATAL
        assert result.phase == StartupPhase.S0_CONFIG
        assert not orch.lock.owned
        assert not (tmp_state / "orchestrator.lock").exists()

    def test_fatal_initialize_failed_releases_lock(self, tmp_state: Path, monkeypatch):
        """S1 initialize fail → FATAL + lock released."""

        class FakeMT5:
            @staticmethod
            def initialize(path=None):
                return False

            @staticmethod
            def login(**kwargs):
                return False

            @staticmethod
            def shutdown():
                pass

        import sys

        sys.modules["MetaTrader5"] = FakeMT5
        monkeypatch.setattr(
            "src.live.orchestrator.get_mt5_config",
            lambda: {
                "login": "123",
                "password": "x",
                "server": "demo",
                "terminal_path": "",
            },
        )
        orch = Orchestrator(state_dir=str(tmp_state))
        result = orch.startup()
        assert result.verdict == StartupVerdict.FATAL
        assert result.phase == StartupPhase.S1_CONNECT
        assert not orch.lock.owned
        assert not (tmp_state / "orchestrator.lock").exists()
        del sys.modules["MetaTrader5"]

    def test_fatal_after_s0_can_reacquire(self, tmp_state: Path, monkeypatch):
        """FATAL sonrası yeni orchestrator aynı state_dir'dan lock alabilmeli."""

        def bad_config():
            raise ValueError("MT5_LOGIN not set")

        monkeypatch.setattr("src.live.orchestrator.get_mt5_config", bad_config)
        orch1 = Orchestrator(state_dir=str(tmp_state))
        result1 = orch1.startup()
        assert result1.verdict == StartupVerdict.FATAL

        # New orchestrator should be able to acquire lock
        orch2 = Orchestrator(state_dir=str(tmp_state))
        orch2.lock.acquire()
        assert orch2.lock.owned
        orch2.release_lock()


# ── Startup: PROCEED → lock held ──────────────────────────────────


class TestStartupProceed:
    def test_proceed_holds_lock(self, tmp_state: Path, monkeypatch):
        """PROCEED sonrası lock tutuluyor olmalı."""

        class FakeAccount:
            login = 53012914
            server = "ICMarketsSC-Demo"
            balance = 10000.0
            equity = 10000.0
            currency = "USD"
            leverage = 100
            margin_level = 1000.0

        class FakeTerminal:
            build = 6140
            path = "C:/MT5/terminal64.exe"
            trade_allowed = True

        class FakeSymbolInfo:
            point = 0.00001
            digits = 5
            trade_tick_value = 1.0
            volume_min = 0.01
            volume_max = 100.0
            volume_step = 0.01
            trade_contract_size = 100000.0
            trade_stops_level = 10
            trade_mode = 4  # FULL — MetaTrader5 enum (Bug B fix 2026-09-01)

        class FakeMT5:
            TIMEFRAME_M1 = 1

            @staticmethod
            def initialize(path=None):
                return True

            @staticmethod
            def login(**kwargs):
                return True

            @staticmethod
            def account_info():
                return FakeAccount()

            @staticmethod
            def terminal_info():
                return FakeTerminal()

            @staticmethod
            def symbol_select(symbol, visible=True):
                return True

            @staticmethod
            def symbol_info(symbol):
                return FakeSymbolInfo()

            @staticmethod
            def positions_get(ticket=None, group=None, symbol=None):
                return []

            @staticmethod
            def orders_get(group=None, symbol=None):
                return []

            @staticmethod
            def copy_rates_from_pos(symbol, tf, start, count):
                # Return enough synthetic M1 bars for warmup to succeed.
                # We need at least 100 * 15 + 30 = 1530 M1 bars for 100 15m candles.
                # Create bars with timestamps on a 1-minute grid.
                from datetime import datetime, timezone

                import pandas as pd

                base = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
                rows = []
                for i in range(min(count, 1600)):
                    t = base + pd.Timedelta(minutes=i)
                    ts = int(t.timestamp())
                    row = pd.DataFrame(
                        {
                            "time": [ts],
                            "open": [1.1000 + i * 0.0001],
                            "high": [1.1001 + i * 0.0001],
                            "low": [1.0999 + i * 0.0001],
                            "close": [1.1000 + i * 0.0001],
                            "tick_volume": [100],
                        }
                    )
                    rows.append(row.iloc[0].to_dict())
                # Return as a list of dicts (compatible with _rates_to_bars field access)
                return rows

        import sys

        sys.modules["MetaTrader5"] = FakeMT5
        monkeypatch.setattr(
            "src.live.orchestrator.get_mt5_config",
            lambda: {
                "login": "53012914",
                "password": "x",
                "server": "ICMarketsSC-Demo",
                "terminal_path": "",
            },
        )
        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
            config_obj=OrchestratorConfig(
                symbols=["EURUSD"],
                state_dir=str(tmp_state),
                expected_login="53012914",  # D12 Taş 2: identity set + match → PROCEED
            ),
        )
        result = orch.startup()
        assert result.verdict == StartupVerdict.PROCEED
        assert result.phase == StartupPhase.S11_READY
        assert orch.lock.owned
        assert (tmp_state / "orchestrator.lock").exists()
        del sys.modules["MetaTrader5"]

    def test_proceed_release_idempotent(self, tmp_state: Path, monkeypatch):
        """PROCEED sonrası release idempotent olmalı."""

        class FakeAccount:
            login = 53012914
            server = "ICMarketsSC-Demo"
            balance = 10000.0
            equity = 10000.0
            currency = "USD"
            leverage = 100
            margin_level = 500.0

        class FakeSymbolInfo:
            point = 0.00001
            digits = 5
            trade_tick_value = 1.0
            volume_min = 0.01
            volume_max = 100.0
            volume_step = 0.01
            trade_contract_size = 100000.0
            trade_stops_level = 10
            trade_mode = 4  # FULL — MetaTrader5 enum (Bug B fix 2026-09-01)

        class FakeTerminal:
            build = 6140
            path = "C:/MT5/terminal64.exe"
            trade_allowed = True

        class FakeMT5:
            TIMEFRAME_M1 = 1

            @staticmethod
            def initialize(path=None):
                return True

            @staticmethod
            def login(**kwargs):
                return True

            @staticmethod
            def account_info():
                return FakeAccount()

            @staticmethod
            def terminal_info():
                return FakeTerminal()

            @staticmethod
            def symbol_select(symbol, visible=True):
                return True

            @staticmethod
            def symbol_info(symbol):
                return FakeSymbolInfo()

            @staticmethod
            def positions_get(ticket=None, group=None, symbol=None):
                return []

            @staticmethod
            def orders_get(group=None, symbol=None):
                return []

            @staticmethod
            def copy_rates_from_pos(symbol, tf, start, count):
                from datetime import datetime, timezone

                import pandas as pd

                base = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
                rows = []
                for i in range(min(count, 1600)):
                    t = base + pd.Timedelta(minutes=i)
                    ts = int(t.timestamp())
                    row = {
                        "time": ts,
                        "open": 1.1000 + i * 0.0001,
                        "high": 1.1001 + i * 0.0001,
                        "low": 1.0999 + i * 0.0001,
                        "close": 1.1000 + i * 0.0001,
                        "tick_volume": 100,
                    }
                    rows.append(row)
                return rows

        import sys

        sys.modules["MetaTrader5"] = FakeMT5
        monkeypatch.setattr(
            "src.live.orchestrator.get_mt5_config",
            lambda: {
                "login": "53012914",
                "password": "x",
                "server": "ICMarketsSC-Demo",
                "terminal_path": "",
            },
        )
        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
            config_obj=OrchestratorConfig(
                symbols=["EURUSD"],
                state_dir=str(tmp_state),
                expected_login="53012914",  # D12 Taş 2: identity set + match → PROCEED
            ),
        )
        result = orch.startup()
        assert result.verdict == StartupVerdict.PROCEED
        orch.release_lock()
        assert not orch.lock.owned
        orch.release_lock()  # idempotent
        assert not orch.lock.owned
        del sys.modules["MetaTrader5"]


# ── Bug B regression — trade_mode enum (FULL=4 PROCEED, DISABLED=0 flag) ─
# The MetaTrader5 enum is DISABLED=0, LONGONLY=1, SHORTONLY=2, CLOSEONLY=3,
# FULL=4 (package-verified 2026-09-01). The old code compared trade_mode == 0
# (assuming 0=FULL) — inverted. Live EURUSD reports 4, so the old check
# falsely SAFE-STARTED, and a DISABLED symbol (0) would have counted as FULL
# (a reverse-lock hazard). These tests exercise the REAL startup() branch.


def _install_fake_mt5(monkeypatch, trade_mode):
    """Install a sys.modules['MetaTrader5'] fake whose symbol_info reports
    `trade_mode`, and wire get_mt5_config. Returns nothing; caller builds the
    Orchestrator and runs startup() against the real S3 contract branch."""
    import sys

    class FakeAccount:
        login = 53012914
        server = "ICMarketsSC-Demo"
        balance = 10000.0
        equity = 10000.0
        currency = "USD"
        leverage = 100
        margin_level = 1000.0

    class FakeTerminal:
        build = 6140
        path = "C:/MT5/terminal64.exe"
        trade_allowed = True

    class FakeSymbolInfo:
        point = 0.00001
        digits = 5
        trade_tick_value = 1.0
        volume_min = 0.01
        volume_max = 100.0
        volume_step = 0.01
        trade_contract_size = 100000.0
        trade_stops_level = 10
        # set per-call below

    # Bind the parameterised trade_mode onto the class namespace.
    FakeSymbolInfo.trade_mode = trade_mode

    class FakeMT5:
        TIMEFRAME_M1 = 1

        @staticmethod
        def initialize(path=None):
            return True

        @staticmethod
        def login(**kwargs):
            return True

        @staticmethod
        def account_info():
            return FakeAccount()

        @staticmethod
        def terminal_info():
            return FakeTerminal()

        @staticmethod
        def symbol_select(symbol, visible=True):
            return True

        @staticmethod
        def symbol_info(symbol):
            return FakeSymbolInfo()

        @staticmethod
        def positions_get(ticket=None, group=None, symbol=None):
            return []

        @staticmethod
        def orders_get(group=None, symbol=None):
            return []

        @staticmethod
        def copy_rates_from_pos(symbol, tf, start, count):
            from datetime import datetime, timezone

            import pandas as pd

            base = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
            rows = []
            for i in range(min(count, 1600)):
                t = base + pd.Timedelta(minutes=i)
                rows.append(
                    {
                        "time": int(t.timestamp()),
                        "open": 1.1000 + i * 0.0001,
                        "high": 1.1001 + i * 0.0001,
                        "low": 1.0999 + i * 0.0001,
                        "close": 1.1000 + i * 0.0001,
                        "tick_volume": 100,
                    }
                )
            return rows

    sys.modules["MetaTrader5"] = FakeMT5
    monkeypatch.setattr(
        "src.live.orchestrator.get_mt5_config",
        lambda: {
            "login": "53012914",
            "password": "x",
            "server": "ICMarketsSC-Demo",
            "terminal_path": "",
        },
    )


class TestTradeModeEnumRegression:
    def test_trade_mode_full_proceeds(self, tmp_state, monkeypatch):
        """B(i): trade_mode=4 (FULL) → the REAL startup() path reaches
        PROCEED. This is the only test type that catches the inverted ==0
        bug (§4.1): the pre-fix code SAFE-STARTED here because 4 != 0."""
        import sys

        _install_fake_mt5(monkeypatch, trade_mode=4)
        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
            config_obj=OrchestratorConfig(
                symbols=["EURUSD"],
                state_dir=str(tmp_state),
                expected_login="53012914",
            ),
        )
        result = orch.startup()
        assert orch._trade_mode_ok is True
        assert result.verdict == StartupVerdict.PROCEED
        assert result.phase == StartupPhase.S11_READY
        orch.release_lock()
        del sys.modules["MetaTrader5"]

    def test_trade_mode_disabled_adds_safe_reason(self, tmp_state, monkeypatch):
        """B(ii): trade_mode=0 (DISABLED) → safe_reason 'trade_mode_not_full'
        → SAFE-START. This is the reverse-lock permanence check: the pre-fix
        code counted 0 as FULL and would have PROCEEDed on a disabled symbol."""
        import sys

        _install_fake_mt5(monkeypatch, trade_mode=0)
        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
            config_obj=OrchestratorConfig(
                symbols=["EURUSD"],
                state_dir=str(tmp_state),
                expected_login="53012914",
            ),
        )
        result = orch.startup()
        assert orch._contract is not None  # D30: builder returns spec, not None
        assert orch._trade_mode_ok is False
        assert result.verdict == StartupVerdict.SAFE_START
        assert "trade_mode_not_full" in result.reason
        del sys.modules["MetaTrader5"]


# ── Startup: lock conflict ────────────────────────────────────────


class TestLockConflict:
    def test_lock_conflict_returns_fatal(self, tmp_state: Path, monkeypatch):
        """Lock varsa ve stale değilse → FATAL."""
        lock_path = tmp_state / "orchestrator.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        existing = LockData(pid=os.getpid(), created_at=time.time(), phase="running")
        lock_path.write_text(json.dumps(existing.to_dict()), encoding="utf-8")
        orch = Orchestrator(state_dir=str(tmp_state))
        result = orch.startup()
        assert result.verdict == StartupVerdict.FATAL
        assert "lock_conflict" in result.reason
