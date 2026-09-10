#!/usr/bin/env python
"""cTrader positions API + reconciliation wiring tests (İş-4a).

Controlled unit evidence (AGENTS.md §3): these tests exercise the REAL
adapter code path (src/ctrader/data_adapter.py::get_positions +
src/ctrader/position_adapter.py) and the REAL Reconciler
(src/live/reconciliation.py) WITHOUT a network socket or Twisted reactor.
A scripted fake connection feeds real protobuf-shaped objects through the
same event_queue contract the production connection uses.

NOT claimed as production-network evidence; that belongs to the live
demo-position verification (audit-observed, per directive test #3).
"""

import queue
from typing import Any, Dict, List

import pytest

from src.ctrader.data_adapter import CTraderDataAdapter, CTraderDataError
from src.ctrader.position_adapter import (
    CTRADER_BOT_LABEL,
    _to_position_ctrader,
    position_to_dict,
)
from src.live.position_manager import Position
from src.live.reconciliation import Reconciler, ReconcileStatus


# ---------------------------------------------------------------------------
# Protobuf-shaped fakes (attribute-compatible with the real SDK messages)
# ---------------------------------------------------------------------------
class FakeTradeData:
    def __init__(self, symbol_id, volume, trade_side, label, comment="", open_ts=0):
        self.symbolId = symbol_id
        self.volume = volume  # protocol volume = lot x contract_size x 100
        self.tradeSide = trade_side  # BUY=1, SELL=2
        self.openTimestamp = open_ts  # epoch ms
        self.label = label
        self.comment = comment


class FakePosition:
    def __init__(
        self,
        position_id,
        trade_data,
        status=1,  # POSITION_STATUS_OPEN
        price=1.09619,
        stop_loss=1.09000,
        take_profit=1.10000,
        swap=0,
    ):
        self.positionId = position_id
        self.tradeData = trade_data
        self.positionStatus = status
        self.price = price
        self.stopLoss = stop_loss
        self.takeProfit = take_profit
        self.swap = swap


class ProtoOAReconcileRes:
    """Fake class name mirrors the real protobuf message name — the adapter
    matches responses via type(payload).__name__."""

    def __init__(self, positions):
        self.position = positions


class FakeLightSymbol:
    def __init__(self, symbol_id, symbol_name):
        self.symbolId = symbol_id
        self.symbolName = symbol_name


class ProtoOASymbolsListRes:
    def __init__(self, symbols):
        self.symbol = symbols


class FakeConnection:
    """Scripted fake of CTraderConnection's surface the adapter touches."""

    def __init__(self, connected: bool = True):
        self.event_queue: queue.Queue = queue.Queue()
        self._connected = connected
        self.calls: List[Dict[str, Any]] = []

    def is_connected(self) -> bool:
        return self._connected

    def request_symbols_list(self, include_archived=False):
        self.calls.append(("symbols", None))
        if not self._connected:
            raise RuntimeError("not connected")
        self.event_queue.put(
            (
                "MESSAGE",
                ProtoOASymbolsListRes(
                    [FakeLightSymbol(3, "EURUSD"), FakeLightSymbol(10026, "BTCUSD")]
                ),
            )
        )

    def reconcile(self):
        self.calls.append(("reconcile", None))
        if not self._connected:
            raise RuntimeError("not connected")


def _make_adapter(conn, **kw) -> CTraderDataAdapter:
    ad = CTraderDataAdapter(conn, **kw)
    # Pre-populate the symbol map so get_positions can resolve symbolId→name.
    ad._symbol_ids = {"EURUSD": 3, "BTCUSD": 10026}
    return ad


def _bot_position(
    pid: int,
    symbol_id: int = 3,
    volume_lots: float = 0.10,
    side: int = 1,
    label: str = CTRADER_BOT_LABEL,
    **kw,
) -> FakePosition:
    """Build a bot-owned open position. protocol volume = lots x 100000 x 100."""
    protocol_volume = int(round(volume_lots * 100000 * 100))
    return FakePosition(
        position_id=pid,
        trade_data=FakeTradeData(
            symbol_id=symbol_id,
            volume=protocol_volume,
            trade_side=side,
            label=label,
        ),
        **kw,
    )


# ---------------------------------------------------------------------------
# position_to_dict / _to_position_ctrader — pure conversion
# ---------------------------------------------------------------------------
class TestPositionToDict:
    def test_open_bot_position_decodes_volume_and_fields(self):
        raw = _bot_position(pid=1001, volume_lots=0.10, side=1)
        d = position_to_dict(raw, contract_size=100000.0, symbol_name="EURUSD")
        assert d is not None
        assert d["ticket"] == 1001
        assert d["symbol"] == "EURUSD"
        assert d["side"] == "long"
        assert d["volume"] == pytest.approx(0.10)
        assert d["entry_price"] == pytest.approx(1.09619)
        assert d["sl"] == pytest.approx(1.09000)
        assert d["tp"] == pytest.approx(1.10000)
        assert d["label"] == CTRADER_BOT_LABEL

    def test_sell_side_normalized_short(self):
        raw = _bot_position(pid=1002, side=2)
        d = position_to_dict(raw, contract_size=100000.0, symbol_name="EURUSD")
        assert d["side"] == "short"

    def test_non_open_position_returns_none(self):
        raw = _bot_position(pid=1003, status=2)  # POSITION_STATUS_CLOSED
        assert position_to_dict(raw, contract_size=100000.0, symbol_name="EURUSD") is None

    def test_missing_trade_data_returns_none(self):
        raw = FakePosition(position_id=1004, trade_data=None)
        assert position_to_dict(raw, contract_size=100000.0, symbol_name="EURUSD") is None

    def test_volume_scale_uses_contract_size(self):
        # 0.05 lots on a 100k contract → protocol 500000
        raw = _bot_position(pid=1005, volume_lots=0.05)
        d = position_to_dict(raw, contract_size=100000.0, symbol_name="EURUSD")
        assert d["volume"] == pytest.approx(0.05)

    def test_open_time_ms_to_seconds(self):
        raw = _bot_position(pid=1006)
        raw.tradeData.openTimestamp = 1_700_000_000_000  # epoch ms
        d = position_to_dict(raw, contract_size=100000.0, symbol_name="EURUSD")
        assert d["open_time"] == pytest.approx(1_700_000_000.0)


class TestToPositionCtrader:
    def test_bot_label_converts_to_position(self):
        d = {
            "ticket": 1001,
            "symbol": "EURUSD",
            "side": "long",
            "volume": 0.10,
            "entry_price": 1.09619,
            "sl": 1.09000,
            "tp": 1.10000,
            "magic": 0,
            "comment": "",
            "open_time": 1700000000.0,
            "profit": 0.0,
            "swap": 0.0,
            "label": CTRADER_BOT_LABEL,
        }
        pos = _to_position_ctrader(d)
        assert pos is not None
        assert isinstance(pos, Position)
        assert pos.ticket == 1001
        assert pos.symbol == "EURUSD"
        assert pos.side == "long"
        assert pos.volume == pytest.approx(0.10)

    def test_non_bot_label_returns_none(self):
        d = {
            "ticket": 2001,
            "symbol": "EURUSD",
            "side": "long",
            "volume": 0.10,
            "entry_price": 1.09619,
            "sl": 1.09000,
            "tp": 1.10000,
            "magic": 0,
            "comment": "",
            "open_time": None,
            "profit": 0.0,
            "swap": 0.0,
            "label": "MANUAL_TRADE",
        }
        assert _to_position_ctrader(d) is None

    def test_empty_dict_returns_none(self):
        assert _to_position_ctrader({}) is None


# ---------------------------------------------------------------------------
# get_positions — adapter fetch + bot filter
# ---------------------------------------------------------------------------
class TestGetPositions:
    def test_returns_bot_positions_only(self):
        conn = FakeConnection()
        conn.event_queue.put(
            (
                "MESSAGE",
                ProtoOAReconcileRes(
                    [
                        _bot_position(pid=1001, volume_lots=0.10),
                        _bot_position(pid=2001, volume_lots=0.20, label="MANUAL_TRADE"),
                    ]
                ),
            )
        )
        ad = _make_adapter(conn)
        positions = ad.get_positions(contract_size=100000.0)
        assert positions is not None
        assert len(positions) == 1
        assert positions[0]["ticket"] == 1001
        assert positions[0]["volume"] == pytest.approx(0.10)
        assert conn.calls[0][0] == "reconcile"

    def test_empty_response_returns_empty_list(self):
        conn = FakeConnection()
        conn.event_queue.put(("MESSAGE", ProtoOAReconcileRes([])))
        ad = _make_adapter(conn)
        assert ad.get_positions(contract_size=100000.0) == []

    def test_unknown_symbol_id_skipped(self):
        conn = FakeConnection()
        conn.event_queue.put(
            (
                "MESSAGE",
                ProtoOAReconcileRes([_bot_position(pid=1001, symbol_id=999999)]),
            )
        )
        ad = _make_adapter(conn)
        assert ad.get_positions(contract_size=100000.0) == []

    def test_reconcile_error_raises_fail_loud(self):
        conn = FakeConnection()
        conn.event_queue.put(("RECONCILE_ERROR", "boom"))
        ad = _make_adapter(conn)
        with pytest.raises(CTraderDataError):
            ad.get_positions(contract_size=100000.0)

    def test_timeout_raises_fail_loud(self):
        conn = FakeConnection()
        ad = _make_adapter(conn, response_timeout_sec=0.2)
        with pytest.raises(CTraderDataError):
            ad.get_positions(contract_size=100000.0)

    def test_disconnected_raises_fail_loud(self):
        conn = FakeConnection(connected=False)
        ad = _make_adapter(conn)
        with pytest.raises(CTraderDataError):
            ad.get_positions(contract_size=100000.0)


# ---------------------------------------------------------------------------
# Reconciliation scenarios — real Reconciler over cTrader-derived Positions
# ---------------------------------------------------------------------------
def _remote_positions(*fakes) -> Dict[int, Position]:
    out: Dict[int, Position] = {}
    for f in fakes:
        d = position_to_dict(f, contract_size=100000.0, symbol_name="EURUSD")
        pos = _to_position_ctrader(d)
        assert pos is not None
        out[int(pos.ticket)] = pos
    return out


class TestReconciliationScenarios:
    def test_local_equals_remote_ok(self):
        local = {
            1001: Position(
                ticket=1001,
                symbol="EURUSD",
                side="long",
                volume=0.10,
                entry_price=1.09619,
                sl=1.09000,
                tp=1.10000,
                magic=0,
            )
        }
        remote = _remote_positions(_bot_position(pid=1001, volume_lots=0.10))
        decision = Reconciler().reconcile(local, remote)
        assert decision.status == ReconcileStatus.OK
        assert decision.block_trading is False

    def test_local_orphan(self):
        local = {
            1001: Position(
                ticket=1001,
                symbol="EURUSD",
                side="long",
                volume=0.10,
                entry_price=1.09619,
                sl=1.09000,
                tp=1.10000,
                magic=0,
            )
        }
        remote = _remote_positions()  # empty
        decision = Reconciler().reconcile(local, remote)
        assert decision.status == ReconcileStatus.ORPHAN
        assert decision.block_trading is True
        assert 1001 in decision.orphans

    def test_remote_unknown_open(self):
        local: Dict[int, Position] = {}
        remote = _remote_positions(_bot_position(pid=1001, volume_lots=0.10))
        decision = Reconciler().reconcile(local, remote)
        assert decision.status == ReconcileStatus.UNKNOWN_OPEN
        assert decision.block_trading is True
        assert 1001 in decision.unknown_opens

    def test_sl_tp_mismatch(self):
        local = {
            1001: Position(
                ticket=1001,
                symbol="EURUSD",
                side="long",
                volume=0.10,
                entry_price=1.09619,
                sl=1.09000,
                tp=1.10000,
                magic=0,
            )
        }
        remote = _remote_positions(
            _bot_position(pid=1001, volume_lots=0.10, stop_loss=1.08800, take_profit=1.10500)
        )
        decision = Reconciler().reconcile(local, remote)
        assert decision.status == ReconcileStatus.MISMATCH
        assert decision.block_trading is True
        assert 1001 in decision.mismatches

    def test_volume_mismatch(self):
        local = {
            1001: Position(
                ticket=1001,
                symbol="EURUSD",
                side="long",
                volume=0.10,
                entry_price=1.09619,
                sl=1.09000,
                tp=1.10000,
                magic=0,
            )
        }
        remote = _remote_positions(_bot_position(pid=1001, volume_lots=0.20))
        decision = Reconciler().reconcile(local, remote)
        assert decision.status == ReconcileStatus.MISMATCH
        assert decision.block_trading is True
