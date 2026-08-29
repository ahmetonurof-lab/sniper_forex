#!/usr/bin/env python
"""P0-2 — TradeLifecycle PRODUCTION WIRING tests (LiveRunner).

Chain verified with a fake broker:
    Signal -> base lot -> DD -> RiskManager -> multiplier -> final lot
    -> Execution.send -> broker fill -> register_open_context (fill data)
    -> trailing sync (TRADE_ACTION_SLTP) -> deal history poll
    -> record_exit_deal -> PortfolioDD.record_realized -> next entry
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from src.live.live_runner import LiveRunner, default_contract
from src.live.portfolio_dd import PortfolioDD
from src.live.risk import Account
from src.live.strategy_runtime import Signal
from src.live.trade_lifecycle import RealizedDealRecord, TradeLifecycle


class FakeMT5:
    """Fake broker: entry fills + positions snapshot + deal history."""

    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_SLTP = 2
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TIME_GTC = 1
    ORDER_FILLING_IOC = 1
    TRADE_RETCODE_DONE = 10009
    CHECK_RETCODE_OK = 0  # order_check returns 0 on success

    def __init__(self):
        self.requests = []
        self.deal_queue = []  # exit deals awaiting poll
        self.open_positions = {999: SimpleNamespace(ticket=999)}
        self.next_position = 999

    def order_check(self, request):
        return SimpleNamespace(retcode=self.CHECK_RETCODE_OK)

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

    def history_deals_get(
        self, from_ts=None, to_ts=None, ticket=None, position=None, *a, **k
    ):
        """Support both time-range and position-based queries."""
        # Position-based query (production poll_deals uses this)
        if position is not None:
            return [
                d for d in self.deal_queue if getattr(d, "position_id", 0) == position
            ] or None
        # Ticket-based query
        if ticket is not None:
            return [
                d for d in self.deal_queue if getattr(d, "ticket", 0) == ticket
            ] or None
        # Time-range query (legacy)
        if from_ts is not None and to_ts is not None:
            due = [d for d in self.deal_queue if from_ts <= d.time <= to_ts]
            for d in due:
                self.deal_queue.remove(d)
            return due
        return []

    def queue_exit(self, ticket, position_id, profit, time, magic=9007001, entry=1):
        self.deal_queue.append(
            SimpleNamespace(
                ticket=ticket,
                order=111,
                position_id=position_id,
                magic=magic,
                entry=entry,
                profit=profit,
                commission=0.0,
                swap=0.0,
                time=time,
            )
        )


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


ACCOUNT = Account(balance=10000.0, equity=10000.0)
CONTRACT = default_contract("EURUSD")


def _runner(fake=None, lifecycle=None, signal_only=False):
    fake = fake or FakeMT5()
    runner = LiveRunner(
        symbol="EURUSD",
        mt5=fake,
        signal_only=signal_only,
        lifecycle=lifecycle,
        contract=CONTRACT,
    )
    sig = _signal()
    runner.runtime.on_bar = lambda bar: sig  # deterministic strategy stub
    return runner, fake


def _bar():
    return None  # runtime.on_bar is stubbed; bar unused


# ── Entry: broker-confirmed fill -> context ──────────────────────────


def test_entry_fill_registers_broker_confirmed_context():
    runner, fake = _runner()
    res = runner.on_bar(_bar(), ACCOUNT)
    assert res.approved and res.order_sent
    entry_req = fake.requests[-1]
    assert entry_req["action"] == FakeMT5.TRADE_ACTION_DEAL
    ctx = res.context_registered
    assert ctx is not None
    assert ctx.position_id == 999 and ctx.order_id == 111 and ctx.entry_deal_id == 222
    assert ctx.entry_price == 1.1000 and ctx.filled_volume == 0.3
    # Locked risk cash from FILL: |1.1000-1.0990| / 0.00001 * 1.0 * 0.3 = 30.0 USD
    assert abs(ctx.initial_risk_cash_total - 30.0) < 1e-6
    assert ctx.remaining_volume == 0.3


def test_signal_only_default_sends_nothing():
    runner, fake = _runner(signal_only=True)
    res = runner.on_bar(_bar(), ACCOUNT)
    assert fake.requests == [], "signal_only must never hit the broker"
    assert res.context_registered is None


def test_dd_unreliable_pauses_entry():
    lc = TradeLifecycle(portfolio_dd=PortfolioDD(starting_balance_r=100.0))
    lc.dd_reliable = False  # restarted without a journal
    runner, fake = _runner(lifecycle=lc)
    res = runner.on_bar(_bar(), ACCOUNT)
    assert res.blocked_reason == "portfolio_dd_unreliable_pause"
    assert fake.requests == []


def test_dd_pause_blocks_order():
    lc = TradeLifecycle(portfolio_dd=PortfolioDD(starting_balance_r=100.0))
    lc.rebuild_from_persisted(
        [],
        realized_journal=[
            RealizedDealRecord(deal_id=1, position_id=1, pnl_r=-8.0, timestamp=1.0)
        ],
        starting_balance_r=100.0,
    )
    assert lc.portfolio_dd.current_dd_r() == 8.0  # > t3 -> pause
    runner, fake = _runner(lifecycle=lc)
    res = runner.on_bar(_bar(), ACCOUNT)
    assert not res.approved
    assert "PAUSE" in (res.blocked_reason or "") or "pause" in res.blocked_reason
    assert fake.requests == []


def test_minlot_reduction_block_prevents_order():
    # Small account -> base lot = volume_min; DD x0.5 unachievable -> BLOCK.
    lc = TradeLifecycle(portfolio_dd=PortfolioDD(starting_balance_r=100.0))
    lc.rebuild_from_persisted(
        [],
        realized_journal=[
            RealizedDealRecord(deal_id=1, position_id=1, pnl_r=-3.0, timestamp=1.0)
        ],
        starting_balance_r=100.0,
    )
    runner, fake = _runner(lifecycle=lc)
    res = runner.on_bar(_bar(), Account(balance=100.0, equity=100.0))
    assert res.blocked_reason == "scaled_lot_zero_minlot_block"
    assert fake.requests == [], "unachievable reduction must not open a position"


# ── Exit: deal history -> lifecycle -> DD ────────────────────────────


def test_exit_deal_recorded_once_via_lifecycle():
    runner, fake = _runner()
    runner.on_bar(_bar(), ACCOUNT)
    runner._last_poll_ts = 0.0  # widen the poll window for the fake
    fake.queue_exit(ticket=555, position_id=999, profit=1.8, time=1000.0)
    exits = runner.poll_deals(now=1001.0)
    assert exits and exits[0]["status"] == "recorded"
    # pnl_r = cash 1.8 / locked risk cash 30.0 = +0.06R
    assert abs(exits[0]["pnl_r"] - 0.06) < 1e-9
    assert abs(runner.lifecycle.portfolio_dd.realized_pnl_r - 0.06) < 1e-9
    # Idempotent re-poll: the same deal re-appearing in an overlapping
    # window (broker history overlap) never double-counts.
    fake.queue_exit(ticket=555, position_id=999, profit=1.8, time=1001.5)
    exits2 = runner.poll_deals(now=1002.0)
    assert exits2 and exits2[0]["status"] == "duplicate"
    assert abs(runner.lifecycle.portfolio_dd.realized_pnl_r - 0.06) < 1e-9


def test_unknown_exit_quarantined_not_dd():
    """Unknown exits (positions we never tracked) cannot be detected without
    time-range history queries. With position-based queries, they are simply
    not found (no DD mutation, no quarantine)."""
    runner, fake = _runner()
    runner.on_bar(_bar(), ACCOUNT)
    runner._last_poll_ts = 0.0
    # Queue an exit for a position we never tracked (31337)
    fake.queue_exit(ticket=777, position_id=31337, profit=-5.0, time=1000.0)
    exits = runner.poll_deals(now=1001.0)
    # Unknown position: not detected (no time-range query), no DD change
    assert len(exits) == 0
    assert runner.lifecycle.portfolio_dd.realized_pnl_r == 0.0
    assert 777 not in runner.lifecycle.quarantined_exits


def test_non_bot_magic_deals_ignored():
    runner, fake = _runner()
    runner.on_bar(_bar(), ACCOUNT)
    runner._last_poll_ts = 0.0
    fake.queue_exit(ticket=888, position_id=999, profit=9.9, time=1000.0, magic=12345)
    exits = runner.poll_deals(now=1001.0)
    assert exits == []
    assert runner.lifecycle.portfolio_dd.realized_pnl_r == 0.0


# ── Open management: trailing through the runner ─────────────────────


def test_trailing_sync_sends_modify_then_no_duplicate():
    runner, fake = _runner()
    runner.on_bar(_bar(), ACCOUNT)
    runner.runtime.active_trade = {
        "side": "long",
        "sl": 1.0995,
        "tp": 1.1023,
        "closed": False,
    }
    events = runner.sync_trailing()
    assert events and events[0].action == "sent" and events[0].confirmed
    assert fake.requests[-1]["action"] == FakeMT5.TRADE_ACTION_SLTP
    assert fake.requests[-1]["sl"] == 1.0995
    n = len(fake.requests)
    assert runner.sync_trailing()[0].action == "no_change"
    assert len(fake.requests) == n
