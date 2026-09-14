#!/usr/bin/env python
"""Logging-parity: SIGNAL→RISK→ORDER_REQUEST→ORDER→FILL→POSITION→EXIT zinciri.

Kapsam: mevcut Forex logging mekanizmasının genişletmesi (yeni mimari YOK).
Her halka aynı trade_id ile bağlanabilmeli; ORDER_REQUEST pre-send intent'i,
FILL broker-onayını, SLTP_PLACED broker-kanıtını, RECONCILE typed kararı taşır.

Üretim-yolu taahhüdü: GERÇEK LiveRunner.on_bar zinciri (fake-production
yasak; §4.2). Broker tarafı FakeMT5 seam'i (p0_2 deseni) — emir GİTMEZ.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.live.audit import AuditChain, EventType
from src.live.live_runner import LiveRunner
from src.live.portfolio_dd import PortfolioDD
from src.live.risk import Account
from src.live.sizing import ContractSpec, contract_for_symbol
from src.live.strategy_runtime import Signal
from src.live.trade_lifecycle import TradeLifecycle


def _signal() -> Signal:
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
        trade_id="EURUSD:7",
    )


class _FakeMT5:
    """p0_2 FakeMT5 deseni (entry fills + deal history)."""

    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_SLTP = 2
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TIME_GTC = 1
    ORDER_FILLING_IOC = 1
    TRADE_RETCODE_DONE = 10009
    CHECK_RETCODE_OK = 0

    def __init__(self):
        self.requests = []
        self.deal_queue = []
        self.open_positions = {999: object()}
        self.next_position = 999

    def order_check(self, request):
        from types import SimpleNamespace

        return SimpleNamespace(retcode=0)

    def order_send(self, request):
        from types import SimpleNamespace

        self.requests.append(dict(request))
        return SimpleNamespace(
            retcode=self.TRADE_RETCODE_DONE,
            order=111,
            deal=222,
            price=request["price"],
            volume=request["volume"],
            position=self.next_position,
            comment="filled",
        )

    def positions_get(self, ticket=None, *a, **k):
        if ticket is None:
            return list(self.open_positions.values())
        return [self.open_positions[ticket]] if ticket in self.open_positions else []

    def history_deals_get(self, from_ts=None, to_ts=None, ticket=None, position=None, *a, **k):
        if position is not None:
            return [d for d in self.deal_queue if getattr(d, "position_id", 0) == position] or None
        return None


ACCOUNT = Account(balance=10000.0, equity=10000.0)
CONTRACT = ContractSpec(symbol="EURUSD", **contract_for_symbol("EURUSD"))


def _runner():
    chain = AuditChain()
    chain.append(0.0, EventType.STARTUP, "EURUSD", {"phase": "test_seed"})
    fake = _FakeMT5()
    runner = LiveRunner(
        symbol="EURUSD",
        mt5=fake,
        signal_only=False,
        contract=CONTRACT,
        lifecycle=TradeLifecycle(portfolio_dd=PortfolioDD(starting_balance_r=100.0)),
        audit=chain,
    )
    sig = _signal()
    runner.runtime.on_bar = lambda bar: sig
    return runner, fake, chain


def _by_type(chain, etype):
    return [e for e in chain.events if e.event_type == etype]


def test_chain_single_trade_id_across_all_links():
    """should [bind SIGNAL→RISK→ORDER_REQUEST→ORDER→FILL→POSITION with one
    trade_id] when [a real fill flows through LiveRunner.on_bar]"""
    runner, fake, chain = _runner()
    res = runner.on_bar(None, ACCOUNT)
    assert res.approved and res.context_registered is not None

    for etype in (
        EventType.SIGNAL,
        EventType.ORDER_REQUEST,
        EventType.ORDER,
        EventType.FILL,
        EventType.POSITION,
    ):
        evts = _by_type(chain, etype)
        assert len(evts) == 1, f"{etype}: tek emit beklenir, {len(evts)}"
        assert evts[0].payload.get("trade_id") == "EURUSD:7", f"{etype} trade_id"


def test_order_request_precedes_order_response():
    """should [emit ORDER_REQUEST before ORDER] when [execution runs]"""
    runner, fake, chain = _runner()
    runner.on_bar(None, ACCOUNT)
    idx_req = chain.events.index(_by_type(chain, EventType.ORDER_REQUEST)[0])
    idx_ord = chain.events.index(_by_type(chain, EventType.ORDER)[0])
    assert idx_req < idx_ord


def test_order_carries_broker_ticket_ids():
    """should [carry order_id + deal_id on ORDER] when [broker fills]"""
    runner, fake, chain = _runner()
    runner.on_bar(None, ACCOUNT)
    p = _by_type(chain, EventType.ORDER)[0].payload
    assert p["order_id"] == 111
    assert p["deal_id"] == 222
    assert p["filled"] is True


def test_fill_carries_broker_confirmed_ids():
    """should [carry position_id + order_id + deal_id on FILL] when [filled]"""
    runner, fake, chain = _runner()
    runner.on_bar(None, ACCOUNT)
    p = _by_type(chain, EventType.FILL)[0].payload
    assert p["position_id"] == 999
    assert p["order_id"] == 111
    assert p["entry_deal_id"] == 222
    assert p["trade_id"] == "EURUSD:7"


def test_sltp_placed_at_entry():
    """should [emit SLTP_PLACED with signal SL/TP at entry] when [filled]"""
    runner, fake, chain = _runner()
    runner.on_bar(None, ACCOUNT)
    evts = _by_type(chain, EventType.SLTP_PLACED)
    assert len(evts) >= 1
    p = evts[0].payload
    assert p["trade_id"] == "EURUSD:7"
    assert p["position_id"] == 999
    assert p["sl"] == pytest.approx(1.0990)
    assert p["tp"] == pytest.approx(1.1018)
    assert p["confirmed"] is True


def test_exit_carries_trade_id():
    """should [carry trade_id on EXIT] when [position closes]"""
    runner, fake, chain = _runner()
    res = runner.on_bar(None, ACCOUNT)
    pid = res.context_registered.position_id
    from types import SimpleNamespace

    # Broker closed the position: remove from live set, queue the exit deal.
    del fake.open_positions[999]
    fake.deal_queue.append(
        SimpleNamespace(
            position_id=pid,
            ticket=555,
            entry=1,
            magic=9007001,
            profit=1.8,
            swap=0.0,
            commission=0.0,
            price=1.1010,
            time=1000.0,
        )
    )
    runner._last_poll_ts = 0.0
    exits = runner.poll_deals(now=1001.0)
    assert exits and exits[0]["status"] == "recorded"
    p = _by_type(chain, EventType.EXIT)[0].payload
    assert p["trade_id"] == "EURUSD:7"
    assert p["position_id"] == pid


def test_duplicate_signal_second_bar_blocked_visibly():
    """should [block the second same-signal bar with a visible RISK reason]
    when [position is already open] (duplicate-order guard evidence)"""
    runner, fake, chain = _runner()
    first = runner.on_bar(None, ACCOUNT)
    assert first.approved
    # Broker now reports the position live (C2 lock path).
    from types import SimpleNamespace

    pid = first.context_registered.position_id
    fake.open_positions = {pid: SimpleNamespace(ticket=pid, symbol="EURUSD", magic=9007001)}
    n_orders = len([e for e in chain.events if e.event_type == EventType.ORDER])
    second = runner.on_bar(None, ACCOUNT)
    assert second.blocked_reason == "c2_symbol_entry_lock_active_trade"
    assert len([e for e in chain.events if e.event_type == EventType.ORDER]) == n_orders
    risks = _by_type(chain, EventType.RISK)
    assert risks[-1].payload.get("trade_id") == "EURUSD:7"
