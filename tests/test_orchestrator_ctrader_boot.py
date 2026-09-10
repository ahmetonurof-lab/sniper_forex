#!/usr/bin/env python
"""İŞ-4a S1 (D159) — cTrader-first Orchestrator boot tests.

§4.2 evidence discipline: these tests execute the REAL Orchestrator
startup() branches (S1/S2/S3/S5/S9) with a duck-typed cTrader adapter —
NOT a fake that reimplements the branch. The key production-branch claim
tested here:

    With a cTrader adapter injected, startup() must NOT die on
    `mt5_import_failed` (the MetaTrader5 import is skipped), and must
    reach S9/S11 without importing MetaTrader5 at all.

The adapter itself is the REAL src.ctrader.data_adapter.CTraderDataAdapter
over a scripted FakeConnection (same pattern as test_ctrader_data_adapter).
"""

from __future__ import annotations

import queue
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.ctrader.data_adapter import CTRADER_PERIOD_M1, CTraderDataAdapter
from src.live.orchestrator import Orchestrator, StartupVerdict


# ---------------------------------------------------------------------------
# Protobuf-shaped fakes (identical names → adapter type(payload).__name__)
# ---------------------------------------------------------------------------
class FakeTrendbar:
    def __init__(self, utc_min, low_scaled, d_open, d_high, d_close, volume=100):
        self.utcTimestampInMinutes = utc_min
        self.low = low_scaled
        self.deltaOpen = d_open
        self.deltaHigh = d_high
        self.deltaClose = d_close
        self.volume = volume
        self.period = CTRADER_PERIOD_M1


class ProtoOASymbolsListRes:
    def __init__(self, symbols):
        self.symbol = symbols


class ProtoOAGetTrendbarsRes:
    def __init__(self, bars):
        self.trendbar = bars
        self.hasMore = False


class ProtoOASpotEvent:
    def __init__(self, symbol_id, bid, ask, ts):
        self.symbolId = symbol_id
        self.bid = bid
        self.ask = ask
        self.timestamp = ts


class FakeLightSymbol:
    def __init__(self, symbol_id, symbol_name):
        self.symbolId = symbol_id
        self.symbolName = symbol_name


def _make_m1_bars(n, end_utc_min=None):
    """n M1 bars ENDING near `now` (server-offset 0 → UTC seconds) so the
    D28 smoke's last-closed-M1 age check (±3 min) passes."""
    if end_utc_min is None:
        end_utc_min = int(time.time() // 60)
    bars = []
    for i in range(n):
        utc_min = end_utc_min - (n - 1 - i)
        base = 60_000_000  # 60000.00 scaled 1e5
        bars.append(
            FakeTrendbar(
                utc_min=utc_min,
                low_scaled=base,
                d_open=1000 + (i % 7),
                d_high=5000,
                d_close=2000 + (i % 3),
                volume=10 + i,
            )
        )
    return bars


class FakeReconcileRes:
    """ProtoOAReconcileRes-shaped fake for get_positions()."""

    def __init__(self, positions=None):
        self.position = positions or []
        self.order = []


class FakeCtraderConnection:
    """Scripted fake of CTraderConnection's surface: property-style
    is_connected (real shape), event_queue responses."""

    def __init__(self, m1_bars=None):
        self.event_queue: queue.Queue = queue.Queue()
        self._connected = True
        self.calls: List[Dict[str, Any]] = []
        self._m1_bars = m1_bars if m1_bars is not None else _make_m1_bars(120)

    @property
    def is_connected(self) -> bool:
        return self._connected

    def ensure_connected(self, max_attempts: int = 1) -> bool:
        return self._connected

    def stop(self):
        self.calls.append(("stop", None))

    def request_symbols_list(self, include_archived=False):
        self.calls.append(("symbols", None))
        self.event_queue.put(
            (
                "MESSAGE",
                ProtoOASymbolsListRes([FakeLightSymbol(3, "EURUSD"), FakeLightSymbol(7, "GBPUSD")]),
            )
        )

    def request_trendbars(self, symbol_id, period, from_ms, to_ms, count=None):
        self.calls.append(
            (
                "trendbars",
                dict(
                    symbol_id=symbol_id,
                    period=period,
                    from_ms=from_ms,
                    to_ms=to_ms,
                    count=count,
                ),
            )
        )
        bars = (
            self._m1_bars[-(count or 5) :] if (count or 5) <= len(self._m1_bars) else self._m1_bars
        )
        self.event_queue.put(("MESSAGE", ProtoOAGetTrendbarsRes(bars)))

    def subscribe_spots(self, symbol_id):
        self.calls.append(("spots", symbol_id))
        self.event_queue.put(
            (
                "MESSAGE",
                ProtoOASpotEvent(symbol_id, 60_000_100_000, 60_000_120_000, int(time.time())),
            )
        )

    def reconcile(self):
        """ProtoOAReconcileReq handler — enqueues empty reconciliation."""
        self.calls.append(("reconcile", None))
        self.event_queue.put(("MESSAGE", FakeReconcileRes(positions=[])))


@pytest.fixture()
def ctrader_orch(tmp_path):
    """Orchestrator with the REAL adapter over a scripted connection.

    The test module does NOT provide a MetaTrader5 module: if the S1
    cTrader branch were broken, startup() would hit the
    `import MetaTrader5` path → ImportError → mt5_import_failed FATAL,
    and these tests would fail loudly (§4.2).
    """
    conn = FakeCtraderConnection()
    adapter = CTraderDataAdapter(
        conn,
        response_timeout_sec=2.0,
    )
    orch = Orchestrator(
        state_dir=str(tmp_path / "state"),
        magic=9007001,
        configured_symbols=["EURUSD"],
        mt5_conn=adapter,
    )
    return orch, conn


class TestCtraderBoot:
    def test_s1_ctrader_mode_no_mt5_import(self, ctrader_orch, monkeypatch):
        """THE production-branch claim: cTrader adapter injected → S1 does
        NOT import MetaTrader5 (no mt5_import_failed), sets _ctrader_mode.

        Evidence shape: MetaTrader5 IS installed in this venv, so absence
        from sys.modules proves nothing. Instead we poison sys.modules with
        a sentinel that RAISES on import — if the S1 branch touched
        MetaTrader5 at all, startup() would explode (fail-loud proof of
        the skip, §4.2)."""
        orch, conn = ctrader_orch

        class _Poison:
            def __getattr__(self, name):
                raise AssertionError("MetaTrader5 touched in cTrader mode")

        monkeypatch.setitem(sys.modules, "MetaTrader5", _Poison())

        result = orch.startup()

        assert result.verdict in (StartupVerdict.PROCEED, StartupVerdict.SAFE_START)
        assert result.reason != "mt5_import_failed"
        assert result.reason != "ctrader_connect_failed"
        assert orch._ctrader_mode is True
        assert orch._mt5 is None  # MT5 module never touched

    def test_s1_audit_transport_ctrader(self, ctrader_orch):
        orch, conn = ctrader_orch
        result = orch.startup()
        assert result.verdict in (StartupVerdict.PROCEED, StartupVerdict.SAFE_START)
        connect_events = [
            e
            for e in orch.audit.events
            if getattr(e, "event_type", None) is not None
            and "ctrader" in str(getattr(e, "payload", {}))
        ]
        assert connect_events, "cTrader transport audit event missing"

    def test_s2_account_skip_audit(self, ctrader_orch):
        """Karar-4: cTrader-mode skips account_info; account dict is
        explicit zeros + audited (beyanlı, not silent)."""
        orch, conn = ctrader_orch
        result = orch.startup()
        assert result.verdict in (StartupVerdict.PROCEED, StartupVerdict.SAFE_START)
        payload_text = repr([getattr(e, "payload", {}) for e in orch.audit.events])
        assert "account_info_skipped_ctrader_mode" in payload_text

    def test_s3_contract_preset_built(self, ctrader_orch):
        """Karar-3-S3: cTrader-mode contract comes from the FX-major preset
        (contract_build_failed must NOT appear as a safe reason)."""
        orch, conn = ctrader_orch
        result = orch.startup()
        assert result.verdict in (StartupVerdict.PROCEED, StartupVerdict.SAFE_START)
        assert "contract_build_failed" not in result.reason
        assert orch._contract is not None
        assert orch._contract.symbol == "EURUSD"
        assert orch._contract.digits == 5
        assert orch._contract.contract_size == 100000.0

    def test_s5_manual_snapshot_no_safe_persist_loop(self, ctrader_orch):
        """Karar-5: S5 calls _build_ctrader_snapshot() which performs
        REAL reconciliation via adapter.get_positions() (no more manual
        NOT_RUN). Snapshot carries beyanlı reconciliation status."""
        orch, conn = ctrader_orch
        result = orch.startup()
        assert result.verdict in (StartupVerdict.PROCEED, StartupVerdict.SAFE_START)
        payload_text = repr([getattr(e, "payload", {}) for e in orch.audit.events])
        # New behavior: real reconciliation via cTrader positions API
        assert "ctrader_snapshot_reconciled" in payload_text
        # reconcile() must have been called by get_positions()
        assert any(c[0] == "reconcile" for c in conn.calls)
        # No safe-mode file persisted by S5 (would force §7.2 degraded boot).
        safe_file = orch._safe_path()
        assert not safe_file.exists() or "ctrader" not in safe_file.read_text(encoding="utf-8")

    def test_warmup_reaches_s9_not_no_mt5_connection(self, ctrader_orch):
        """Karar-6: _warmup must NOT return no_mt5_connection in cTrader
        mode; the D28 smoke runs over the adapter (real S9 path)."""
        orch, conn = ctrader_orch
        result = orch.startup()
        assert result.verdict in (StartupVerdict.PROCEED, StartupVerdict.SAFE_START)
        assert "no_mt5_connection" not in result.reason
        # Real trendbar requests flowed through the adapter (65k full warmup
        # would exceed the single-request guard — smoke 100 + warmup chunks
        # are bounded by the preset; either way requests must exist).
        tb_calls = [c for c in conn.calls if c[0] == "trendbars"]
        assert tb_calls, "no trendbar requests reached the connection"

    def test_shutdown_delegates_to_conn_stop(self, ctrader_orch):
        """Karar-7: shutdown() calls conn.stop() in cTrader mode."""
        orch, conn = ctrader_orch
        orch.startup()
        orch.shutdown(exit_code=0, reason="test")
        assert any(c[0] == "stop" for c in conn.calls)

    def test_get_account_zero_beyanli(self, ctrader_orch):
        """Karar-7: _get_account returns explicit zero Account in cTrader
        mode → sizing rejects → no order can ever be built."""
        orch, conn = ctrader_orch
        orch.startup()
        orch._ctrader_mode = True
        acc = orch._get_account()
        assert acc is not None
        assert acc.balance == 0.0
        assert acc.equity == 0.0


class TestCtraderFailLoud:
    def test_connect_failure_fatal(self, tmp_path):
        """ensure_connected False → FATAL ctrader_connect_failed with lock
        released (fail-loud, no silent degradation)."""
        conn = FakeCtraderConnection()
        conn._connected = False
        adapter = CTraderDataAdapter(
            conn,
            response_timeout_sec=0.3,
        )
        orch = Orchestrator(
            state_dir=str(tmp_path / "state"),
            configured_symbols=["EURUSD"],
            mt5_conn=adapter,
        )
        result = orch.startup()
        assert result.verdict == StartupVerdict.FATAL
        assert result.reason == "ctrader_connect_failed"


# ---------------------------------------------------------------------------
# D167 — _build_data_connection() caller contract (Hakem-hükmü 2026-09-08)
#
# Bug provenance: D159 commit 78fa8a4 treated the validator's SUCCESS
# return value (truthy config dict) as a problem list → SystemExit on
# every ctrader boot. Hakem-approved min-fix (D167): try/except ValueError
# around validate_ctrader_config; success flows through untouched.
#
# §4.2 evidence discipline: these tests call the REAL _build_data_connection
# path boundary. The connection layer itself is monkeypatched (network is
# out of unit scope — §3 controlled-integration layer), but the config
# validation contract under test is the REAL src.config.ctrader_config code.
# ---------------------------------------------------------------------------


class TestBuildDataConnectionValidatorContract:
    def test_valid_config_passes_without_systemexit(self, monkeypatch):
        """Success path: valid cfg → validator returns dict (truthy!) →
        caller must STILL proceed to construct the adapter (the D167 bug
        failed exactly here)."""
        import src.live.run_production as rp

        valid_cfg = {
            "client_id": "cid",
            "client_secret": "secret",
            "host": "demo.ctraderapi.com",
            "account_id": "48407657",
            "redirect_uri": "http://localhost",
            "access_token": "tok",
        }
        monkeypatch.setattr("src.config.ctrader_config.get_ctrader_config", lambda: dict(valid_cfg))

        captured: Dict[str, Any] = {}

        class FakeAdapter:
            def __init__(self, conn):
                captured["conn"] = conn

        class FakeConn:
            def __init__(self, cfg, token_cache_path=None):
                captured["cfg"] = cfg
                captured["token_cache_path"] = token_cache_path

            def start(self):
                captured["started"] = True

        # CTraderConnection / CTraderDataAdapter are LAZY-imported inside
        # _build_data_connection() (D159 import-time discipline) → patch
        # their SOURCE modules; the call-time import resolves the fake.
        monkeypatch.setattr("src.ctrader.connection.CTraderConnection", FakeConn)
        monkeypatch.setattr("src.ctrader.data_adapter.CTraderDataAdapter", FakeAdapter)

        result = rp._build_data_connection()

        assert isinstance(result, FakeAdapter)
        assert captured["started"] is True
        assert captured["cfg"] == valid_cfg
        assert Path(captured["token_cache_path"]).is_absolute()

    def test_invalid_config_raises_systemexit_with_valueerror_cause(self, monkeypatch):
        """Failure path: validator ValueError → fail-loud SystemExit with
        the validator message and __cause__ chain preserved."""
        import src.live.run_production as rp

        def _raise(cfg, require_credentials=True):
            raise ValueError("CTRADER_CLIENT_ID environment variable not set")

        monkeypatch.setattr(
            "src.config.ctrader_config.get_ctrader_config",
            lambda: {
                "client_id": "",
                "client_secret": "",
                "host": "demo.ctraderapi.com",
                "account_id": "48407657",
                "redirect_uri": "http://localhost",
                "access_token": "",
            },
        )
        monkeypatch.setattr("src.config.ctrader_config.validate_ctrader_config", _raise)

        with pytest.raises(SystemExit) as excinfo:
            rp._build_data_connection()
        assert "ctrader config invalid" in str(excinfo.value)
        assert "CTRADER_CLIENT_ID" in str(excinfo.value)

    def test_validator_contract_return_vs_raise_is_unchanged(self):
        """§2.2 guard: the fix must NOT have changed the validator API.
        Pin the real src.config.ctrader_config contract: success → returns
        the SAME dict object; failure → raises ValueError (never a
        truthy/None return)."""
        from src.config.ctrader_config import validate_ctrader_config

        valid = {
            "client_id": "cid",
            "client_secret": "secret",
            "host": "demo.ctraderapi.com",
            "account_id": "48407657",
            "redirect_uri": "http://localhost",
            "access_token": "tok",
        }
        out = validate_ctrader_config(valid, require_credentials=True)
        assert out is valid  # returns the config, not a problem list

        bad = dict(valid, client_id="")
        with pytest.raises(ValueError, match="CLIENT_ID"):
            validate_ctrader_config(bad, require_credentials=True)
