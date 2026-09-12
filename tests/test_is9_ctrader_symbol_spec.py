#!/usr/bin/env python
"""İŞ-9 — cTrader Symbol Full-Fetch + S5 Decode Fix.

Red-tests-first (Hakem K4):
  RED-1  BTCUSD (digits=2, contractSize=1) → ContractSpec correctly built
  RED-2  EURUSD (digits=5, contractSize=100000) → FX-major regression
  RED-3  get_symbol_spec returns None → fallback preset used
  RED-4  unknown_symbol → CTraderDataError (fail-loud)
  RED-5  _build_ctrader_symbol_meta uses broker-truth pip_position
  RED-6  _build_ctrader_symbol_meta fallback when spec unavailable

The core bug: _build_contract cTrader branch used hardcoded FX-major
preset (contract_size=100000, digits=5) — wrong for BTCUSD
(contract_size=1, digits=2). İŞ-9 fixes this by fetching broker-truth
via ProtoOASymbolByIdReq.
"""

from __future__ import annotations

import queue
from typing import Any, List

import pytest

from src.ctrader.data_adapter import CTraderDataAdapter, CTraderDataError
from src.live.orchestrator import Orchestrator
from src.live.sizing import ContractSpec


# ---------------------------------------------------------------------------
# Protobuf-shaped fakes for ProtoOASymbolByIdReq/Res
# ---------------------------------------------------------------------------
class FakeSymbolById:
    """Mirrors ProtoOASymbol from ProtoOASymbolByIdRes."""

    def __init__(
        self,
        symbol_id: int,
        symbol_name: str,
        digits: int,
        contract_size: float,
        pip_position: int,
        pip_size: float,
        min_volume: int,
        max_volume: int,
        step_volume: int,
    ):
        self.symbolId = symbol_id
        self.symbolName = symbol_name
        self.digits = digits
        self.contractSize = contract_size
        self.pipPosition = pip_position
        self.pipSize = pip_size
        self.minVolume = min_volume
        self.maxVolume = max_volume
        self.stepVolume = step_volume


class ProtoOASymbolByIdRes:
    def __init__(self, symbol):
        self.symbol = [symbol]


class FakeLightSymbol:
    def __init__(self, symbol_id: int, symbol_name: str):
        self.symbolId = symbol_id
        self.symbolName = symbol_name


class ProtoOASymbolsListRes:
    def __init__(self, symbols):
        self.symbol = symbols


class ProtoOAReconcileRes:
    def __init__(self, positions=None):
        self.position = positions or []
        self.order = []


class FakeTrader:
    def __init__(self, balance_raw, money_digits=2, leverage_in_cents=10000):
        self.ctidTraderAccountId = 48407657
        self.balance = balance_raw
        self.moneyDigits = money_digits
        self.leverageInCents = leverage_in_cents
        self.depositAssetId = 1


class ProtoOATraderRes:
    def __init__(self, trader):
        self.trader = trader


# ---------------------------------------------------------------------------
# FakeConnection with symbol-by-id support
# ---------------------------------------------------------------------------
class FakeConnection:
    """Scripted fake of CTraderConnection for symbol spec tests."""

    def __init__(self, connected: bool = True):
        self.event_queue: queue.Queue = queue.Queue()
        self._connected = connected
        self.calls: List[Any] = []

    def is_connected(self) -> bool:
        return self._connected

    def is_stale(self, timeout_sec: float = 60.0) -> bool:
        return False

    def reconnect(self, max_attempts: int = 3) -> bool:
        self.calls.append(("reconnect", max_attempts))
        return self._connected

    def request_symbols_list(self, include_archived=False):
        self.calls.append(("symbols", None))
        if not self._connected:
            raise RuntimeError("not connected")
        self.event_queue.put(
            (
                "MESSAGE",
                ProtoOASymbolsListRes(
                    [
                        FakeLightSymbol(10026, "BTCUSD"),
                        FakeLightSymbol(3, "EURUSD"),
                    ]
                ),
            )
        )

    def request_symbol_by_id(self, symbol_id: int):
        self.calls.append(("symbol_by_id", symbol_id))
        if not self._connected:
            raise RuntimeError("not connected")
        # Response is injected by the test via event_queue.put before calling


# ---------------------------------------------------------------------------
# Symbol spec fixtures
# ---------------------------------------------------------------------------
BTCUSD_SPEC = FakeSymbolById(
    symbol_id=10026,
    symbol_name="BTCUSD",
    digits=2,
    contract_size=1.0,
    pip_position=1,
    pip_size=0.1,
    min_volume=1,  # 0.01 lot in protocol units
    max_volume=1000000,  # 10000 lots
    step_volume=1,  # 0.01 lot step
)

EURUSD_SPEC = FakeSymbolById(
    symbol_id=3,
    symbol_name="EURUSD",
    digits=5,
    contract_size=100000.0,
    pip_position=4,
    pip_size=0.0001,
    min_volume=1,  # 0.01 lot
    max_volume=100000000,  # 100 lots (10000000 / (100000*100))
    step_volume=1,
)


def _inject_symbol_response(conn: FakeConnection, spec: FakeSymbolById):
    """Put a ProtoOASymbolByIdRes on the queue before the adapter reads."""
    conn.event_queue.put(("MESSAGE", ProtoOASymbolByIdRes(spec)))


# ---------------------------------------------------------------------------
# RED-1: BTCUSD (crypto) → correct ContractSpec
# ---------------------------------------------------------------------------
class TestBTCUDSymbolSpec:
    def test_btcusd_digits_2_contract_1(self):
        """BTCUSD: digits=2, contractSize=1 → tick_size=0.01,
        tick_value=0.01, contract_size=1. NOT the FX-major preset."""
        conn = FakeConnection()
        ad = CTraderDataAdapter(conn)
        _inject_symbol_response(conn, BTCUSD_SPEC)
        spec = ad.get_symbol_spec("BTCUSD")
        assert spec is not None
        assert spec["digits"] == 2
        assert spec["contract_size"] == 1.0
        assert spec["pip_position"] == 1
        assert spec["pip_size"] == pytest.approx(0.1)
        assert spec["symbol_id"] == 10026
        assert spec["symbol_name"] == "BTCUSD"

    def test_btcusd_contract_spec_via_orchestrator(self):
        """Orchestrator._fetch_ctrader_symbol_spec builds ContractSpec
        with tick_size=0.01, tick_value=0.01 for BTCUSD."""
        conn = FakeConnection()
        _inject_symbol_response(conn, BTCUSD_SPEC)

        orch = _make_orchestrator(conn, symbol="BTCUSD")
        cs = orch._fetch_ctrader_symbol_spec("BTCUSD")
        assert cs is not None
        assert isinstance(cs, ContractSpec)
        assert cs.symbol == "BTCUSD"
        assert cs.digits == 2
        assert cs.contract_size == 1.0
        assert cs.tick_size == pytest.approx(0.01)
        assert cs.tick_value == pytest.approx(0.01)  # 1.0 * 0.01
        assert cs.stops_level == 0.0


# ---------------------------------------------------------------------------
# RED-2: EURUSD (FX major) → regression passes
# ---------------------------------------------------------------------------
class TestEURUDSymbolSpec:
    def test_eurusd_digits_5_contract_100k(self):
        """EURUSD: digits=5, contractSize=100000 → tick_size=0.00001,
        tick_value=1.0. Classic FX-major values preserved."""
        conn = FakeConnection()
        ad = CTraderDataAdapter(conn)
        _inject_symbol_response(conn, EURUSD_SPEC)
        spec = ad.get_symbol_spec("EURUSD")
        assert spec is not None
        assert spec["digits"] == 5
        assert spec["contract_size"] == 100000.0
        assert spec["pip_position"] == 4
        assert spec["pip_size"] == pytest.approx(0.0001)

    def test_eurusd_contract_spec_via_orchestrator(self):
        """Orchestrator._fetch_ctrader_symbol_spec builds ContractSpec
        with tick_size=0.00001, tick_value=1.0 for EURUSD."""
        conn = FakeConnection()
        _inject_symbol_response(conn, EURUSD_SPEC)

        orch = _make_orchestrator(conn, symbol="EURUSD")
        cs = orch._fetch_ctrader_symbol_spec("EURUSD")
        assert cs is not None
        assert cs.digits == 5
        assert cs.contract_size == 100000.0
        assert cs.tick_size == pytest.approx(0.00001)
        assert cs.tick_value == pytest.approx(1.0)  # 100000 * 0.00001


# ---------------------------------------------------------------------------
# RED-3: get_symbol_spec returns None → fallback
# ---------------------------------------------------------------------------
class TestSymbolSpecFallback:
    def test_transient_failure_returns_none(self):
        """When the adapter returns None (timeout/disconnect),
        _fetch_ctrader_symbol_spec returns None → caller falls back."""
        conn = FakeConnection()
        # Don't inject any response → timeout → None
        orch = _make_orchestrator(conn, symbol="BTCUSD")
        cs = orch._fetch_ctrader_symbol_spec("BTCUSD")
        assert cs is None

    def test_disconnected_returns_none(self):
        """Disconnected adapter → get_symbol_spec returns None."""
        conn = FakeConnection(connected=False)
        orch = _make_orchestrator(conn, symbol="BTCUSD")
        cs = orch._fetch_ctrader_symbol_spec("BTCUSD")
        assert cs is None


# ---------------------------------------------------------------------------
# RED-4: unknown_symbol → CTraderDataError
# ---------------------------------------------------------------------------
class TestUnknownSymbol:
    def test_unknown_symbol_raises(self):
        """Unknown symbol → CTraderDataError (fail-loud, not silent None)."""
        conn = FakeConnection()
        ad = CTraderDataAdapter(conn)
        # Inject symbols list but NO symbol-by-id response for NOPEUSD
        conn.request_symbols_list()
        # Drain the symbols list response
        conn.event_queue.get(timeout=1)
        # Now try to resolve an unknown symbol
        with pytest.raises(CTraderDataError, match="unknown_symbol"):
            ad._resolve_symbol_id("NOPEUSD")


# ---------------------------------------------------------------------------
# RED-5: _build_ctrader_symbol_meta uses broker-truth pip_position
# ---------------------------------------------------------------------------
class TestSymbolMetaPipPosition:
    def test_meta_uses_broker_truth_pip_position(self):
        """_build_ctrader_symbol_meta must use pip_position from
        get_symbol_spec (broker-truth), not from _contract.digits."""
        conn = FakeConnection()
        _inject_symbol_response(conn, BTCUSD_SPEC)

        orch = _make_orchestrator(conn, symbol="BTCUSD")
        # Set _contract to FX-major preset (digits=5) — the OLD code
        # would use this, giving pip_position=5 (WRONG for BTCUSD).
        orch._contract = ContractSpec(
            symbol="BTCUSD",
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            tick_size=0.00001,
            tick_value=1.0,
            contract_size=100000.0,
            stops_level=0.0,
            digits=5,
        )
        meta = orch._build_ctrader_symbol_meta()
        assert "BTCUSD" in meta
        # Broker-truth pip_position=1, NOT contract.digits=5
        assert meta["BTCUSD"]["pip_position"] == 1
        assert meta["BTCUSD"]["symbol_id"] == 10026


# ---------------------------------------------------------------------------
# RED-6: _build_ctrader_symbol_meta fallback when spec unavailable
# ---------------------------------------------------------------------------
class TestSymbolMetaFallback:
    def test_meta_fallback_to_contract_digits(self):
        """When get_symbol_spec fails, _build_ctrader_symbol_meta
        falls back to _contract.digits for pip_position."""
        conn = FakeConnection()

        orch = _make_orchestrator(conn, symbol="EURUSD")
        orch._contract = ContractSpec(
            symbol="EURUSD",
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            tick_size=0.00001,
            tick_value=1.0,
            contract_size=100000.0,
            stops_level=0.0,
            digits=5,
        )
        # Need to inject symbols list for resolve_symbol_id
        conn.request_symbols_list()
        conn.event_queue.get(timeout=1)  # drain symbols response
        # Inject symbol-by-id timeout (no response) — get_symbol_spec
        # will return None, but resolve_symbol_id already cached from
        # symbols list. We need to inject a fresh symbols response for
        # the get_symbol_spec call's resolve step.
        conn.event_queue.put(
            (
                "MESSAGE",
                ProtoOASymbolsListRes([FakeLightSymbol(3, "EURUSD")]),
            )
        )
        meta = orch._build_ctrader_symbol_meta()
        assert "EURUSD" in meta
        # Fallback: _contract.digits = 5
        assert meta["EURUSD"]["pip_position"] == 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_orchestrator(conn: FakeConnection, symbol: str = "EURUSD") -> Orchestrator:
    """Build a minimal Orchestrator for testing _fetch_ctrader_symbol_spec."""
    adapter = CTraderDataAdapter(conn, response_timeout_sec=2.0)
    orch = Orchestrator(
        state_dir="state_test_is9",
        magic=9007009,
        configured_symbols=[symbol],
        mt5_conn=adapter,
    )
    return orch
