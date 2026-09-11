#!/usr/bin/env python
"""İŞ-7 (SEÇENEK-C) — cTrader Execution Wiring: CTraderExecution inject +
MT5-Execution-yapılmaz-guard + execution-yok → emir-yok fail-closed.

Reis kararı (2026-09-11): wiringsiz-mode-0 "düşük-riskli" DEĞİL — sinyal
ateşlenirse LiveRunner MT5-Execution'a gider → MetaTrader5-import → emir
YANLIŞ platforma gidebilir (MT5-hesabı) — sessiz-fallback (§19). C-zaten
D168-Karar-A'nın kendi tasarımı: tasarım-yok, tamamlama-var.

RED testleri (test-first):
  RED-1   cTrader-mode → orchestrator S5 CTraderExecution inject eder
  RED-2   cTrader-mode → MT5 Execution ASLA kullanılmaz (MetaTrader5 poisoned)
  RED-2b  LiveRunner(mt5=None, execution=None) → MT5 import YOK, fail-closed
  RED-3   execution=None → on_bar emir gönderemez (execution_unavailable_fail_closed)
"""

from __future__ import annotations

import queue
import sys
import time
from typing import Any, Dict, List

import pandas as pd
import pytest

from src.ctrader.data_adapter import CTRADER_PERIOD_M1, CTraderDataAdapter
from src.live.audit import EventType
from src.live.orchestrator import Orchestrator, StartupVerdict
from src.live.risk import Account
from src.live.strategy_runtime import Signal


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


class ProtoOAReconcileRes:
    def __init__(self, positions=None):
        self.position = positions or []
        self.order = []


class FakeTrader:
    def __init__(
        self,
        balance_raw,
        money_digits=2,
        leverage_in_cents=10000,
        deposit_asset_id=1,
    ):
        self.ctidTraderAccountId = 48407657
        self.balance = balance_raw
        self.moneyDigits = money_digits
        self.leverageInCents = leverage_in_cents
        self.depositAssetId = deposit_asset_id


class ProtoOATraderRes:
    def __init__(self, trader):
        self.trader = trader


def _make_m1_bars(n, end_utc_min=None):
    """n M1 bars ENDING near `now` so the D28 smoke's last-closed-M1 age
    check (±3 min) passes."""
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


class FakeCtraderConnection:
    """Scripted fake of CTraderConnection's surface (İŞ-7)."""

    def __init__(self, m1_bars=None, reconcile_positions=None):
        self.event_queue: queue.Queue = queue.Queue()
        self._connected = True
        self.calls: List[Dict[str, Any]] = []
        self._m1_bars = m1_bars if m1_bars is not None else _make_m1_bars(120)
        self._reconcile_positions = reconcile_positions or []

    @property
    def is_connected(self) -> bool:
        return self._connected

    def ensure_connected(self, max_attempts: int = 1) -> bool:
        return self._connected

    def reconnect(self, max_attempts: int = 1) -> bool:
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
        self.calls.append(("reconcile", None))
        self.event_queue.put(
            ("MESSAGE", ProtoOAReconcileRes(positions=list(self._reconcile_positions)))
        )

    def request_trader(self):
        self.calls.append(("trader", None))
        self.event_queue.put(
            ("MESSAGE", ProtoOATraderRes(FakeTrader(balance_raw=1_000_000, money_digits=2)))
        )


@pytest.fixture()
def ctrader_orch(tmp_path):
    """Orchestrator with the REAL adapter over a scripted connection."""
    conn = FakeCtraderConnection()
    adapter = CTraderDataAdapter(conn, response_timeout_sec=2.0)
    orch = Orchestrator(
        state_dir=str(tmp_path / "state"),
        magic=9007001,
        configured_symbols=["EURUSD"],
        mt5_conn=adapter,
    )
    return orch, conn


def _signal():
    return Signal(
        symbol="EURUSD",
        direction="bullish",
        side="long",
        entry_price=1.1000,
        sl=1.0990,
        tp=1.1018,
        entry_bar_index=1,
        sweep_bar_index=0,
        zone_index=0,
        zone_top=1.1005,
        zone_bottom=1.0995,
        zone_size=0.001,
        timestamp=pd.Timestamp("2026-08-01 00:00"),
    )


class TestCtraderExecutionWiring:
    """İŞ-7 (SEÇENEK-C): cTrader-mode execution wiring."""

    def test_s5_ctrader_mode_injects_ctrader_execution(self, ctrader_orch):
        """RED-1: cTrader mode → orchestrator S5 CTraderExecution inject eder
        (self._runner.execution bir CTraderExecution'dır)."""
        from src.ctrader.execution import CTraderExecution

        orch, conn = ctrader_orch
        result = orch.startup()
        assert result.verdict in (StartupVerdict.PROCEED, StartupVerdict.SAFE_START)
        assert isinstance(orch._runner.execution, CTraderExecution)

    def test_s5_ctrader_mode_never_uses_mt5_execution(self, ctrader_orch, monkeypatch):
        """RED-2: cTrader mode → MT5 Execution ASLA kullanılmaz. MetaTrader5
        poisoned — runner/execution MT5'e dokunursa startup patlar (fail-loud
        proof of the guard, §4.2)."""
        from src.ctrader.execution import CTraderExecution

        orch, conn = ctrader_orch

        class _Poison:
            def __getattr__(self, name):
                raise AssertionError("MetaTrader5 touched in cTrader mode")

        monkeypatch.setitem(sys.modules, "MetaTrader5", _Poison())
        result = orch.startup()
        assert result.verdict in (StartupVerdict.PROCEED, StartupVerdict.SAFE_START)
        assert orch._runner.mt5 is None  # MT5 module never touched
        assert isinstance(orch._runner.execution, CTraderExecution)

    def test_live_runner_no_mt5_no_execution_fail_closed(self, monkeypatch):
        """RED-2b: LiveRunner(mt5=None, execution=None) → MetaTrader5 import
        YOK (sessiz-fallback yasağı §19). Fail-closed: execution=None."""
        from src.live.live_runner import LiveRunner

        class _Poison:
            def __getattr__(self, name):
                raise AssertionError("MetaTrader5 touched")

        monkeypatch.setitem(sys.modules, "MetaTrader5", _Poison())
        runner = LiveRunner(symbol="EURUSD", mt5=None)
        assert runner.mt5 is None
        assert runner.execution is None

    def test_on_bar_execution_none_fail_closed(self):
        """RED-3: execution=None → on_bar emir GÖNDEREMEZ — fail-closed
        (execution_unavailable_fail_closed), görünür RISK audit."""
        from src.live.live_runner import LiveRunner

        runner = LiveRunner(symbol="EURUSD", mt5=None)  # fail-closed: execution=None
        runner.runtime.on_bar = lambda bar: _signal()
        res = runner.on_bar(None, Account(balance=10000.0, equity=10000.0))
        assert not res.approved
        assert res.blocked_reason == "execution_unavailable_fail_closed"
        assert not res.order_sent
        risk_events = [
            e for e in runner.audit.events if getattr(e, "event_type", None) == EventType.RISK
        ]
        assert any(
            "execution_unavailable_fail_closed" in str(getattr(e, "payload", {}))
            for e in risk_events
        )
