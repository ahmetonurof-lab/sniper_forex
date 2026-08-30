#!/usr/bin/env python
"""STEP 12 — FINAL END-TO-END live chain test (mock broker).

One continuous flow:

    signal -> base lot -> current DD -> RiskManager -> multiplier
    -> final quantized lot -> Execution.send -> broker fill
    -> register_open_context (fill data, real risk lock)
    -> trailing decision -> TRADE_ACTION_SLTP modify -> broker confirm
    -> deal history poll -> process_exit_deal (idempotent)
    -> PortfolioDD.record_realized -> NEXT entry with scaled lot

Asserts the full wiring is live, not just unit-level.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from src.live.live_runner import LiveRunner, default_contract
from src.live.portfolio_dd import PortfolioDD
from src.live.risk import Account
from src.live.strategy_runtime import Signal
from src.live.trade_lifecycle import TradeLifecycle


class E2EBroker:
    """Scripted fake broker: entry, SLTP, positions, deal history."""

    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_SLTP = 2
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TIME_GTC = 1
    ORDER_FILLING_IOC = 1
    TRADE_RETCODE_DONE = 10009

    def __init__(self):
        self.requests = []
        self.deals = []
        self.open = {1: SimpleNamespace(ticket=1)}
        self.next_pos = 1

    def order_check(self, request):
        return SimpleNamespace(retcode=self.TRADE_RETCODE_DONE)

    def order_send(self, request):
        self.requests.append(dict(request))
        if request.get("action") == self.TRADE_ACTION_SLTP:
            return SimpleNamespace(
                retcode=self.TRADE_RETCODE_DONE,
                order=0,
                deal=0,
                price=0.0,
                volume=0.0,
                position=request["position"],
                comment="sltp",
            )
        self.next_pos += 1
        pid = self.next_pos
        self.open[pid] = SimpleNamespace(ticket=pid)
        return SimpleNamespace(
            retcode=self.TRADE_RETCODE_DONE,
            order=111,
            deal=222,
            price=request["price"],
            volume=request["volume"],
            position=pid,
            comment="filled",
        )

    def positions_get(self, ticket=None, *a, **k):
        if ticket is None:
            return list(self.open.values())
        return [self.open[ticket]] if ticket in self.open else []

    def history_deals_get(self, from_ts, to_ts, ticket=None, *a, **k):
        due = [d for d in self.deals if from_ts <= d.time <= to_ts]
        for d in due:
            self.deals.remove(d)
        return due

    def emit_exit(self, ticket, position_id, cash, time):
        self.deals.append(
            SimpleNamespace(
                ticket=ticket,
                order=0,
                position_id=position_id,
                magic=9007001,
                entry=1,
                profit=cash,
                commission=0.0,
                swap=0.0,
                time=time,
            )
        )

    def close_open(self, position_id):
        self.open.pop(position_id, None)


SIG1 = Signal(
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
ACCOUNT = Account(balance=10000.0, equity=10000.0)
CONTRACT = default_contract("EURUSD")


def _build_runner(fake):
    runner = LiveRunner(
        symbol="EURUSD",
        mt5=fake,
        signal_only=False,
        contract=CONTRACT,
        lifecycle=TradeLifecycle(portfolio_dd=PortfolioDD(starting_balance_r=100.0)),
    )
    runner.runtime.on_bar = lambda bar: SIG1  # deterministic strategy stub
    return runner


def test_e2e_full_live_chain():
    fake = E2EBroker()
    runner = _build_runner(fake)

    # 1) ENTRY: risk -> final lot -> broker fill -> context.
    res = runner.on_bar(None, ACCOUNT)
    assert res.approved and res.context_registered is not None
    assert res.final_lot == 0.3  # $10000 * 0.003 / (100 ticks * $1)
    entry_pos = res.context_registered.position_id
    entry_req = [r for r in fake.requests if r["action"] == fake.TRADE_ACTION_DEAL][0]
    assert entry_req["action"] == fake.TRADE_ACTION_DEAL

    # 2) TRAILING: runtime raises SL -> TRADE_ACTION_SLTP modify -> confirm.
    runner.runtime.active_trade = {
        "side": "long",
        "sl": 1.0995,
        "tp": 1.1023,
        "closed": False,
    }
    events = runner.sync_trailing()
    assert events[0].confirmed, events
    modify = [r for r in fake.requests if r["action"] == fake.TRADE_ACTION_SLTP][-1]
    assert modify["sl"] == 1.0995 and modify["position"] == entry_pos

    # 3) EXIT: broker closes position -> deal poll -> lifecycle -> DD.
    fake.close_open(entry_pos)
    fake.emit_exit(ticket=555, position_id=entry_pos, cash=15.0, time=1001.0)
    runner._last_poll_ts = 0.0
    exits = runner.poll_deals(now=1002.0)
    assert exits and exits[0]["status"] == "recorded"
    # risk cash locked = 0.3 lot * 100 = $30 -> pnl_r = 15/30 = +0.5R
    assert abs(exits[0]["pnl_r"] - 0.5) < 1e-9
    dd = runner.lifecycle.portfolio_dd
    assert abs(dd.realized_pnl_r - 0.5) < 1e-9
    assert abs(dd.current_equity_r() - 100.5) < 1e-9

    # 4) NEXT ENTRY: same signal again -> fills again (DD=0, full lot).
    res2 = runner.on_bar(None, ACCOUNT)
    assert res2.approved and res2.final_lot == 0.3
    # 5) Final deal poll after all exits: no double-count.
    assert len(runner.lifecycle.realized_journal) == 1


def test_e2e_loss_reduces_next_entry_lot():
    fake = E2EBroker()
    runner = _build_runner(fake)
    res = runner.on_bar(None, ACCOUNT)
    entry_pos = res.context_registered.position_id

    # Loss -$75 at $30 risk = -2.5R (DD > t1=2 -> x0.5 on next entry).
    fake.close_open(entry_pos)
    fake.emit_exit(ticket=556, position_id=entry_pos, cash=-75.0, time=1001.0)
    runner._last_poll_ts = 0.0
    runner.poll_deals(now=1002.0)
    assert abs(runner.lifecycle.portfolio_dd.current_dd_r() - 2.5) < 1e-9

    runner.runtime.active_trade = None  # simulate the closed trade state
    res2 = runner.on_bar(None, ACCOUNT)
    assert res2.approved
    assert res2.lot_multiplier == 0.5, "DD>2R must produce x0.5 scaling"
    assert abs(res2.final_lot - 0.15) < 1e-9, "x0.5 scaled lot must reach broker"
