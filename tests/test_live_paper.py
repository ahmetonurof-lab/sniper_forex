#!/usr/bin/env python
"""PHASE 10 — PAPER / DRY RUN — synthetic unit tests.

Covers:
- PaperPosition lifecycle: OPEN -> CLOSED_* with status + exit fields
- PaperBroker.open: ticket increments, position registered, instant fill
- PaperBroker.close: removes from open, appends to closed
- PaperBroker.on_tick: SL hit (long/short)
- PaperBroker.on_tick: TP hit (long/short)
- PaperBroker.on_tick: no-hit (price moves within band)
- PaperBroker.on_tick: only matching symbol positions are checked
- PnL math: long profit, long loss, short profit, short loss
- PnL math: contract-size scaling (volume, tick_value, tick_size)
- PnL math: zero / defensive (tick_size=0 returns 0)
- PaperSession.run_step without warmup returns error
- PaperSession does NOT call mt5.order_send (no real orders)
- PaperSession is signal-only / dry-run invariant
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.live.audit import AuditChain
from src.live.paper import (
    PaperBroker,
    PaperPosition,
    PaperSession,
    PaperStepResult,
    PositionStatus,
    _pnl,
)
from src.live.sizing import ContractSpec
from src.live.strategy_runtime import Signal


# ── Helpers ──────────────────────────────────────────────────────


def _signal(
    symbol: str = "EURUSD",
    side: str = "long",
    entry: float = 1.10000,
    sl: float = 1.09500,
    tp: float = 1.10900,
) -> Signal:
    return Signal(
        symbol=symbol,
        direction="bullish" if side == "long" else "bearish",
        side=side,
        entry_price=entry,
        sl=sl,
        tp=tp,
        entry_bar_index=0,
        sweep_bar_index=0,
        zone_index=0,
        zone_top=entry + 0.001,
        zone_bottom=entry - 0.001,
        zone_size=0.002,
        timestamp=pd.Timestamp("2026-08-28 00:00:00"),
    )


def _contract(
    symbol: str = "EURUSD",
    tick_size: float = 0.00001,
    tick_value: float = 1.0,
    contract_size: float = 100000.0,
) -> ContractSpec:
    return ContractSpec(
        symbol=symbol,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        tick_size=tick_size,
        tick_value=tick_value,
        contract_size=contract_size,
        stops_level=0.0,
        digits=5,
    )


# ── PaperPosition ───────────────────────────────────────────────


def test_paper_position_default_status_is_open():
    p = PaperPosition(
        ticket=1,
        symbol="EURUSD",
        side="long",
        volume=0.0,
        entry_price=1.0,
        sl=0.9,
        tp=1.1,
        magic=9007001,
        open_time=0.0,
    )
    assert p.status == PositionStatus.OPEN
    assert p.exit_price == 0.0
    assert p.pnl == 0.0


def test_paper_position_to_position_shape():
    p = PaperPosition(
        ticket=42,
        symbol="GBPUSD",
        side="short",
        volume=0.1,
        entry_price=1.30,
        sl=1.31,
        tp=1.29,
        magic=9007001,
        open_time=1.0,
    )
    pos = p.to_position()
    assert pos.ticket == 42
    assert pos.symbol == "GBPUSD"
    assert pos.side == "short"
    assert pos.volume == 0.1
    assert pos.entry_price == 1.30


# ── PaperBroker: open / close ───────────────────────────────────


def test_broker_open_assigns_unique_tickets():
    b = PaperBroker()
    s1 = _signal(side="long", entry=1.10, sl=1.09, tp=1.12)
    s2 = _signal(side="short", entry=1.20, sl=1.21, tp=1.18)
    p1 = b.open(s1, volume=0.0, contract=_contract())
    p2 = b.open(s2, volume=0.0, contract=_contract())
    assert p1.ticket == 1
    assert p2.ticket == 2
    assert sorted(p.ticket for p in b.get_open()) == [1, 2]


def test_broker_open_uses_signal_entry_price():
    b = PaperBroker()
    s = _signal(entry=1.12345, sl=1.12000, tp=1.13000)
    p = b.open(s, volume=0.0, contract=_contract())
    assert p.entry_price == 1.12345
    assert p.sl == 1.12000
    assert p.tp == 1.13000
    assert p.status == PositionStatus.OPEN


def test_broker_close_moves_position_from_open_to_closed():
    b = PaperBroker()
    s = _signal()
    p = b.open(s, volume=0.0, contract=_contract())
    closed = b.close(p.ticket, exit_price=1.105, reason=PositionStatus.CLOSED_MANUAL)
    assert closed is not None
    assert closed.status == PositionStatus.CLOSED_MANUAL
    assert closed.exit_price == 1.105
    assert b.get_open() == []
    assert len(b.get_closed()) == 1


def test_broker_close_unknown_ticket_returns_none():
    b = PaperBroker()
    assert b.close(999, exit_price=1.0) is None


# ── PaperBroker: SL / TP check via on_tick ─────────────────────


def test_on_tick_long_sl_hit():
    """Long: bid <= sl -> CLOSED_SL at sl price."""
    b = PaperBroker()
    b.open(
        _signal(side="long", entry=1.10000, sl=1.09500, tp=1.10900),
        volume=0.10,
        contract=_contract(),
    )
    closed = b.on_tick("EURUSD", bid=1.09400, ask=1.09420)  # bid <= sl
    assert len(closed) == 1
    assert closed[0].status == PositionStatus.CLOSED_SL
    assert closed[0].exit_price == 1.09500
    assert b.get_open() == []


def test_on_tick_long_tp_hit():
    """Long: bid >= tp -> CLOSED_TP at tp price."""
    b = PaperBroker()
    b.open(
        _signal(side="long", entry=1.10000, sl=1.09500, tp=1.10900),
        volume=0.10,
        contract=_contract(),
    )
    closed = b.on_tick("EURUSD", bid=1.11000, ask=1.11020)  # bid >= tp
    assert len(closed) == 1
    assert closed[0].status == PositionStatus.CLOSED_TP
    assert closed[0].exit_price == 1.10900


def test_on_tick_short_sl_hit():
    """Short: ask >= sl -> CLOSED_SL at sl price."""
    b = PaperBroker()
    b.open(
        _signal(side="short", entry=1.10000, sl=1.10500, tp=1.09100),
        volume=0.10,
        contract=_contract(),
    )
    closed = b.on_tick("EURUSD", bid=1.10450, ask=1.10520)  # ask >= sl
    assert len(closed) == 1
    assert closed[0].status == PositionStatus.CLOSED_SL
    assert closed[0].exit_price == 1.10500


def test_on_tick_short_tp_hit():
    """Short: ask <= tp -> CLOSED_TP at tp price."""
    b = PaperBroker()
    b.open(
        _signal(side="short", entry=1.10000, sl=1.10500, tp=1.09100),
        volume=0.10,
        contract=_contract(),
    )
    closed = b.on_tick("EURUSD", bid=1.09050, ask=1.09080)  # ask <= tp
    assert len(closed) == 1
    assert closed[0].status == PositionStatus.CLOSED_TP
    assert closed[0].exit_price == 1.09100


def test_on_tick_no_hit_when_price_within_band():
    """Price within [sl, tp] -> no close, position still open."""
    b = PaperBroker()
    b.open(
        _signal(side="long", entry=1.10000, sl=1.09500, tp=1.10900),
        volume=0.10,
        contract=_contract(),
    )
    closed = b.on_tick("EURUSD", bid=1.10200, ask=1.10220)
    assert closed == []
    assert len(b.get_open()) == 1


def test_on_tick_only_matching_symbol_processed():
    """GBPUSD tick must NOT affect a EURUSD position."""
    b = PaperBroker()
    b.open(
        _signal(symbol="EURUSD", side="long", entry=1.10000, sl=1.09500, tp=1.10900),
        volume=0.10,
        contract=_contract(symbol="EURUSD"),
    )
    closed = b.on_tick("GBPUSD", bid=1.05000, ask=1.05020)  # GBPUSD bid way below
    assert closed == []
    assert len(b.get_open()) == 1


# ── PnL math ─────────────────────────────────────────────────────


def test_pnl_long_profit():
    """Long 0.10 lot EURUSD, +50 pips, $1/pip/lot -> pnl = +50.0 USD."""
    c = _contract(tick_size=0.00001, tick_value=1.0, contract_size=100000.0)
    pnl = _pnl(
        side="long",
        entry=1.10000,
        exit_price=1.10500,
        volume=0.10,
        contract_size=c.contract_size,
        tick_size=c.tick_size,
        tick_value=c.tick_value,
    )
    # 500 ticks * 1.0 * 0.10 = 50.0
    assert pnl == pytest.approx(50.0)


def test_pnl_long_loss():
    c = _contract(tick_size=0.00001, tick_value=1.0, contract_size=100000.0)
    pnl = _pnl(
        side="long",
        entry=1.10000,
        exit_price=1.09500,
        volume=0.10,
        contract_size=c.contract_size,
        tick_size=c.tick_size,
        tick_value=c.tick_value,
    )
    assert pnl == pytest.approx(-50.0)


def test_pnl_short_profit():
    """Short 0.10 lot, price falls 50 pips -> +50 USD."""
    c = _contract(tick_size=0.00001, tick_value=1.0, contract_size=100000.0)
    pnl = _pnl(
        side="short",
        entry=1.10000,
        exit_price=1.09500,
        volume=0.10,
        contract_size=c.contract_size,
        tick_size=c.tick_size,
        tick_value=c.tick_value,
    )
    assert pnl == pytest.approx(50.0)


def test_pnl_short_loss():
    c = _contract(tick_size=0.00001, tick_value=1.0, contract_size=100000.0)
    pnl = _pnl(
        side="short",
        entry=1.10000,
        exit_price=1.10500,
        volume=0.10,
        contract_size=c.contract_size,
        tick_size=c.tick_size,
        tick_value=c.tick_value,
    )
    assert pnl == pytest.approx(-50.0)


def test_pnl_volume_scaling():
    """Doubling volume must double pnl."""
    c = _contract()
    base = _pnl(
        side="long",
        entry=1.10000,
        exit_price=1.10100,
        volume=0.10,
        contract_size=c.contract_size,
        tick_size=c.tick_size,
        tick_value=c.tick_value,
    )
    double = _pnl(
        side="long",
        entry=1.10000,
        exit_price=1.10100,
        volume=0.20,
        contract_size=c.contract_size,
        tick_size=c.tick_size,
        tick_value=c.tick_value,
    )
    assert double == pytest.approx(2.0 * base)


def test_pnl_jpy_pair_3_digit():
    """JPY pair: tick_size=0.001, tick_value=$X. pnl = ticks * tick_value * vol."""
    c = _contract(tick_size=0.001, tick_value=0.5, contract_size=100000.0)
    # +10 JPY pips = +100 ticks * 0.5 * 0.10 = 5.0 USD
    pnl = _pnl(
        side="long",
        entry=110.000,
        exit_price=110.100,
        volume=0.10,
        contract_size=c.contract_size,
        tick_size=c.tick_size,
        tick_value=c.tick_value,
    )
    assert pnl == pytest.approx(5.0)


def test_pnl_zero_tick_size_returns_zero():
    """Defensive: zero/negative tick_size returns 0 (avoid div-by-zero)."""
    pnl = _pnl(
        side="long",
        entry=1.0,
        exit_price=1.1,
        volume=0.1,
        contract_size=100000.0,
        tick_size=0.0,
        tick_value=1.0,
    )
    assert pnl == 0.0


def test_broker_update_pnl_patches_closed_position():
    b = PaperBroker()
    s = _signal(side="long", entry=1.10000, sl=1.09500, tp=1.10900)
    p = b.open(s, volume=0.10, contract=_contract())
    b.close(p.ticket, exit_price=1.10500, reason=PositionStatus.CLOSED_TP)
    pnl = b.update_pnl(p.ticket, _contract(), exit_price=1.10500)
    assert pnl == pytest.approx(50.0)
    # And it's persisted
    assert b.get_closed()[0].pnl == pytest.approx(50.0)


def test_broker_total_pnl_sums_closed():
    b = PaperBroker()
    c = _contract()
    s1 = _signal(side="long", entry=1.10, sl=1.09, tp=1.12)
    s2 = _signal(side="short", entry=1.30, sl=1.31, tp=1.29)
    p1 = b.open(s1, volume=0.10, contract=c)
    p2 = b.open(s2, volume=0.20, contract=c)
    b.close(p1.ticket, exit_price=1.11, reason=PositionStatus.CLOSED_TP)
    b.close(p2.ticket, exit_price=1.305, reason=PositionStatus.CLOSED_SL)
    b.update_pnl(p1.ticket, c, exit_price=1.11)  # +100 ticks * 1 * 0.10 = 10
    b.update_pnl(p2.ticket, c, exit_price=1.305)  # -50 ticks * 1 * 0.20 = -10
    assert b.total_pnl() == pytest.approx(0.0, abs=1e-6)


# ── PaperSession ────────────────────────────────────────────────


def test_paper_session_run_step_without_warmup_errors():
    """run_step before warmup must return an error (not crash)."""
    s = PaperSession(symbol="EURUSD", broker=PaperBroker())
    audit = AuditChain()
    res = s.run_step(audit)
    assert isinstance(res, PaperStepResult)
    assert res.errors
    assert "warmed" in res.errors[0].lower()


def test_paper_session_dry_run_invariant():
    """PaperSession must NOT call mt5.order_send. The paper broker is
    the only one allowed to mutate position state.

    We pass a tiny `m1_bars` (empty) and verify mt5 is never touched.
    """

    class NoSendMT5:
        def __init__(self):
            self.send_calls = 0

        def order_send(self, *_a, **_k):
            self.send_calls += 1
            return None

        def copy_rates_from_pos(self, *_a, **_k):
            return []

    mt5 = NoSendMT5()
    s = PaperSession(symbol="EURUSD", mt5=mt5, broker=PaperBroker())
    s._warmed = True  # bypass warmup so run_step executes
    res = s.run_step(AuditChain())
    assert mt5.send_calls == 0
    assert isinstance(res, PaperStepResult)
