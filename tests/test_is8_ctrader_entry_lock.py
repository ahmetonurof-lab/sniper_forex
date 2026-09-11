#!/usr/bin/env python
"""İŞ-8 (Hakem-kararı) — C2 ENTRY-LOCK paritesi: cTrader-mode broker truth.

Hakem kararı (2026-09-11): `_symbol_entry_locked()` mt5-None→True →
cTrader-mode'da TÜM girişler bloklu → mode-0-milestone'un SON kod kapısı.

Kapsam: lock-kararı adapter-broker-truth'undan:
  - bot-labeled açık pozisyon → lock (True)
  - adapter fail (None/exception) → lock-fail-closed (True)
  - MT5 semantiği birebir korunur (MT5 yolu değişmez)

RED testleri (test-first):
  RED-1  cTrader-mode bot-labeled açık pozisyon → _symbol_entry_locked() True
  RED-2  cTrader-mode boş pozisyon → False (entry serbest)
  RED-3  adapter fail (None/exception) → True (lock-fail-closed)
  RED-4  başka symbol pozisyonu → False (bu symbol için lock yok)
  RED-5  orchestrator S5 cTrader-mode → _runner.mt5_conn inject eder
"""

from __future__ import annotations

import queue
import time
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


class FakeTradeData:
    def __init__(self, symbol_id, volume, trade_side, label, comment="", open_ts=0):
        self.symbolId = symbol_id
        self.volume = volume  # protocol volume = lot x contract_size x 100
        self.tradeSide = trade_side
        self.openTimestamp = open_ts
        self.label = label
        self.comment = comment


class FakePosition:
    def __init__(
        self,
        position_id,
        trade_data,
        status=1,
        price=1.09619,
        stop_loss=0.0,
        take_profit=0.0,
        swap=0,
    ):
        self.positionId = position_id
        self.tradeData = trade_data
        self.positionStatus = status
        self.price = price
        self.stopLoss = stop_loss
        self.takeProfit = take_profit
        self.swap = swap


def _bot_position(
    pid: int,
    symbol_id: int = 3,  # EURUSD (FakeCtraderConnection symbols map)
    volume_lots: float = 0.01,
    side: int = 2,
) -> FakePosition:
    """Bot-labelled open position (protocol volume = lots x 100000 x 100)."""
    return FakePosition(
        position_id=pid,
        trade_data=FakeTradeData(
            symbol_id=symbol_id,
            volume=int(round(volume_lots * 100000 * 100)),
            trade_side=side,
            label="SNIPER_FOREX",
        ),
    )


def _make_m1_bars(n, end_utc_min=None):
    if end_utc_min is None:
        end_utc_min = int(time.time() // 60)
    bars = []
    for i in range(n):
        utc_min = end_utc_min - (n - 1 - i)
        base = 60_000_000
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
    """Scripted fake of CTraderConnection's surface (İŞ-8)."""

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


def _adapter(conn) -> CTraderDataAdapter:
    return CTraderDataAdapter(conn, response_timeout_sec=2.0)


@pytest.fixture()
def ctrader_orch(tmp_path):
    conn = FakeCtraderConnection()
    orch = Orchestrator(
        state_dir=str(tmp_path / "state"),
        magic=9007001,
        configured_symbols=["EURUSD"],
        mt5_conn=_adapter(conn),
    )
    return orch, conn


class TestCtraderEntryLock:
    """İŞ-8: C2 entry-lock cTrader-mode broker truth paritesi."""

    def test_ctrader_entry_lock_bot_position_locks(self):
        """RED-1: cTrader-mode bot-labeled açık pozisyon → lock (True)."""
        from src.live.live_runner import LiveRunner

        conn = FakeCtraderConnection(reconcile_positions=[_bot_position(pid=5001)])
        runner = LiveRunner(symbol="EURUSD", mt5=None, mt5_conn=_adapter(conn))
        assert runner._symbol_entry_locked() is True

    def test_ctrader_entry_lock_no_positions_unlocked(self):
        """RED-2: cTrader-mode boş pozisyon → entry serbest (False)."""
        from src.live.live_runner import LiveRunner

        conn = FakeCtraderConnection()  # no positions
        runner = LiveRunner(symbol="EURUSD", mt5=None, mt5_conn=_adapter(conn))
        assert runner._symbol_entry_locked() is False

    def test_ctrader_entry_lock_adapter_fail_fail_closed(self):
        """RED-3: adapter fail (None/exception) → lock-fail-closed (True)."""
        from src.live.live_runner import LiveRunner

        conn = FakeCtraderConnection()
        conn._connected = False  # adapter fetch fails
        runner = LiveRunner(symbol="EURUSD", mt5=None, mt5_conn=_adapter(conn))
        assert runner._symbol_entry_locked() is True

    def test_ctrader_entry_lock_other_symbol_no_lock(self):
        """RED-4: başka symbol pozisyonu → bu symbol için lock YOK (False)."""
        from src.live.live_runner import LiveRunner

        # GBPUSD (symbol_id=7) position — runner symbol EURUSD
        conn = FakeCtraderConnection(reconcile_positions=[_bot_position(pid=5002, symbol_id=7)])
        runner = LiveRunner(symbol="EURUSD", mt5=None, mt5_conn=_adapter(conn))
        assert runner._symbol_entry_locked() is False

    def test_s5_ctrader_mode_injects_mt5_conn(self, ctrader_orch):
        """RED-5: orchestrator S5 cTrader-mode → _runner.mt5_conn inject eder."""
        orch, conn = ctrader_orch
        result = orch.startup()
        assert result.verdict in (StartupVerdict.PROCEED, StartupVerdict.SAFE_START)
        assert orch._runner.mt5_conn is not None
