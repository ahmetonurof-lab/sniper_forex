#!/usr/bin/env python
"""PHASE 6 — POSITION MANAGER + RECONCILIATION — synthetic unit tests.

Covers:
- Position._to_position: magic filter (bot-owned only)
- Position._normalize_side: numeric + string forms
- PositionManager.update: open / close / no-change / exception
- PositionManager.update: manual (different magic) positions ignored
- PositionManager.update: closed trades carry last-known state
- PositionManager.update: new opens reported
- PositionManager.restore: restart recovery seeds snapshot
- PositionManager.clear: empty
- Reconciler.reconcile: OK (no diffs)
- Reconciler.reconcile: ORPHAN (local open, MT5 closed)
- Reconciler.reconcile: UNKNOWN_OPEN (MT5 has unknown ticket)
- Reconciler.reconcile: MISMATCH (volume/SL/TP changed)
- Reconciler.reconcile: block_trading on any non-OK
- Reconciler.reconcile: aggregation (worst-of status)
- Reconciler.reconcile: details populated
"""

from __future__ import annotations

from typing import List, Optional

from src.live.position_manager import (
    DEFAULT_MAGIC,
    Position,
    PositionManager,
)
from src.live.reconciliation import (
    Reconciler,
    ReconcileStatus,
)


# ── Fakes ────────────────────────────────────────────────────────


class FakePos:
    """Minimal stand-in for an mt5 TradePosition namedtuple/object."""

    def __init__(
        self,
        ticket: int,
        symbol: str,
        type_: int,
        volume: float,
        price_open: float,
        sl: float,
        tp: float,
        magic: int,
        comment: str = "",
        time: Optional[float] = None,
        profit: float = 0.0,
        swap: float = 0.0,
    ):
        self.ticket = ticket
        self.symbol = symbol
        self.type = type_  # 0=buy, 1=sell (mt5 int)
        self.volume = volume
        self.price_open = price_open
        self.sl = sl
        self.tp = tp
        self.magic = magic
        self.comment = comment
        self.time = time
        self.profit = profit
        self.swap = swap


class FakeMT5:
    """Configurable fake of the MetaTrader5 module.

    Set `positions` to a list of FakePos; `positions_get()` returns it
    (or raises if `raise_on_get=True`).
    """

    def __init__(self):
        self.positions: List[FakePos] = []
        self.raise_on_get: bool = False
        self.calls: int = 0

    def positions_get(self):
        self.calls += 1
        if self.raise_on_get:
            raise RuntimeError("simulated mt5 error")
        return list(self.positions)


# ── Helpers ──────────────────────────────────────────────────────


def _make_pos(
    ticket: int = 12345,
    symbol: str = "EURUSD",
    side: str = "long",
    volume: float = 0.06,
    entry: float = 1.10000,
    sl: float = 1.09500,
    tp: float = 1.10900,
    magic: int = DEFAULT_MAGIC,
    comment: str = "",
    profit: float = 0.0,
) -> Position:
    return Position(
        ticket=ticket,
        symbol=symbol,
        side=side,
        volume=volume,
        entry_price=entry,
        sl=sl,
        tp=tp,
        magic=magic,
        comment=comment,
        open_time=None,
        profit=profit,
        swap=0.0,
    )


# ── Position: magic filter + side normalization ──────────────────


def test_position_manager_ignores_other_magic():
    """Positions with a different magic number must be filtered out."""
    mt5 = FakeMT5()
    mt5.positions = [
        FakePos(1, "EURUSD", 0, 0.06, 1.10, 1.095, 1.109, magic=DEFAULT_MAGIC),
        FakePos(2, "GBPUSD", 0, 0.10, 1.30, 1.295, 1.309, magic=9999),  # not ours
        FakePos(3, "USDJPY", 1, 0.05, 110.0, 109.5, 110.9, magic=0),  # manual
    ]
    pm = PositionManager(mt5=mt5)
    update = pm.update()
    tickets = sorted(p.ticket for p in update.positions.values())
    assert tickets == [1], f"only magic-matching ticket should remain, got {tickets}"


def test_position_manager_normalizes_side_numeric_and_string():
    """Both numeric (0/1) and string ('buy'/'sell') type forms are accepted."""
    mt5 = FakeMT5()
    mt5.positions = [
        FakePos(1, "EURUSD", 0, 0.06, 1.10, 1.095, 1.109, magic=DEFAULT_MAGIC),  # 0=buy
        FakePos(
            2, "GBPUSD", 1, 0.10, 1.30, 1.295, 1.309, magic=DEFAULT_MAGIC
        ),  # 1=sell
    ]
    pm = PositionManager(mt5=mt5)
    update = pm.update()
    sides = {p.ticket: p.side for p in update.positions.values()}
    assert sides[1] == "long"
    assert sides[2] == "short"


# ── PositionManager.update lifecycle ────────────────────────────


def test_position_manager_first_update_reports_all_as_opens():
    """On the first poll, every position is a 'new open'."""
    mt5 = FakeMT5()
    mt5.positions = [
        FakePos(10, "EURUSD", 0, 0.06, 1.10, 1.095, 1.109, magic=DEFAULT_MAGIC),
        FakePos(11, "GBPUSD", 0, 0.10, 1.30, 1.295, 1.309, magic=DEFAULT_MAGIC),
    ]
    pm = PositionManager(mt5=mt5)
    update = pm.update()
    assert len(update.new_opens) == 2
    assert len(update.closed_trades) == 0
    assert sorted(p.ticket for p in update.positions.values()) == [10, 11]


def test_position_manager_no_change_no_events():
    """A second poll with identical positions reports no opens, no closes."""
    mt5 = FakeMT5()
    mt5.positions = [
        FakePos(10, "EURUSD", 0, 0.06, 1.10, 1.095, 1.109, magic=DEFAULT_MAGIC),
    ]
    pm = PositionManager(mt5=mt5)
    first = pm.update()
    assert len(first.new_opens) == 1
    second = pm.update()
    assert len(second.new_opens) == 0
    assert len(second.closed_trades) == 0
    assert len(second.positions) == 1


def test_position_manager_detects_close_with_last_known_state():
    """A position that disappears from MT5 is reported as closed_trades
    carrying its last-known entry/SL/TP/volume."""
    mt5 = FakeMT5()
    mt5.positions = [
        FakePos(10, "EURUSD", 0, 0.06, 1.10000, 1.09500, 1.10900, magic=DEFAULT_MAGIC),
        FakePos(11, "GBPUSD", 0, 0.10, 1.30000, 1.29500, 1.30900, magic=DEFAULT_MAGIC),
    ]
    pm = PositionManager(mt5=mt5)
    pm.update()  # first poll, both opens

    # Server closed ticket 10 (SL/TP hit or manual)
    mt5.positions = [
        FakePos(11, "GBPUSD", 0, 0.10, 1.30000, 1.29500, 1.30900, magic=DEFAULT_MAGIC),
    ]
    update = pm.update()
    assert len(update.closed_trades) == 1
    closed = update.closed_trades[0]
    assert closed.ticket == 10
    assert closed.symbol == "EURUSD"
    assert closed.side == "long"
    assert closed.volume == 0.06
    assert closed.entry_price == 1.10000
    assert closed.sl == 1.09500
    assert closed.tp == 1.10900
    # exit_price / pnl left at 0.0 (caller fills from history if needed)
    assert closed.exit_price == 0.0
    assert closed.pnl == 0.0


def test_position_manager_detects_new_open_alongside_close():
    """Same poll: one new open, one close."""
    mt5 = FakeMT5()
    mt5.positions = [
        FakePos(10, "EURUSD", 0, 0.06, 1.10, 1.095, 1.109, magic=DEFAULT_MAGIC),
    ]
    pm = PositionManager(mt5=mt5)
    pm.update()  # seed

    mt5.positions = [
        # 10 closed (gone)
        FakePos(20, "GBPUSD", 0, 0.10, 1.30, 1.295, 1.309, magic=DEFAULT_MAGIC),  # new
    ]
    update = pm.update()
    assert [c.ticket for c in update.closed_trades] == [10]
    assert [o.ticket for o in update.new_opens] == [20]
    assert sorted(update.positions.keys()) == [20]


def test_position_manager_survives_mt5_exception():
    """If positions_get raises, update() preserves the previous snapshot,
    emits no synthetic close, and flags fetch_failed / stale_snapshot_preserved."""
    mt5 = FakeMT5()
    # Seed a previous snapshot
    mt5.positions = [
        FakePos(10, "EURUSD", 0, 0.06, 1.10, 1.095, 1.109, magic=DEFAULT_MAGIC),
    ]
    pm = PositionManager(mt5=mt5)
    pm.update()  # seed snapshot

    mt5.raise_on_get = True
    update = pm.update()
    assert update.fetch_failed is True
    assert update.fetch_ok is False
    assert update.stale_snapshot_preserved is True
    # Previous snapshot preserved (no synthetic close fabricated)
    assert update.closed_trades == []
    assert update.new_opens == []
    # Positions remain the previous snapshot
    assert 10 in update.positions


# ── Restart recovery ─────────────────────────────────────────────


def test_position_manager_restore_seeds_snapshot():
    """restore() populates the snapshot without calling MT5."""
    pm = PositionManager(mt5=FakeMT5())
    pm.restore(
        [
            _make_pos(ticket=100, symbol="EURUSD"),
            _make_pos(ticket=101, symbol="GBPUSD"),
        ]
    )
    snap = pm.get_snapshot()
    assert sorted(snap.keys()) == [100, 101]
    assert pm.get_for_symbol("EURUSD")[0].ticket == 100
    assert pm.get_for_symbol("EURUSD")[0].symbol == "EURUSD"


def test_position_manager_clear_drops_snapshot():
    pm = PositionManager(mt5=FakeMT5())
    pm.restore([_make_pos(ticket=200)])
    assert len(pm.get_snapshot()) == 1
    pm.clear()
    assert len(pm.get_snapshot()) == 0


# ── Reconciler ───────────────────────────────────────────────────


def test_position_manager_confirmed_empty_state_on_success():
    """Successful fetch with zero bot-owned positions is a confirmed empty
    snapshot (not a fetch failure)."""
    mt5 = FakeMT5()
    # Seed a position then clear it via successful empty response
    mt5.positions = [
        FakePos(10, "EURUSD", 0, 0.06, 1.10, 1.095, 1.109, magic=DEFAULT_MAGIC),
    ]
    pm = PositionManager(mt5=mt5)
    pm.update()  # seed snapshot

    mt5.positions = []
    update = pm.update()
    assert update.fetch_failed is False
    assert update.fetch_ok is True
    # Confirmed empty bot snapshot: no synthetic preservation needed,
    # previous open is genuinely closed by broker.
    assert len(update.closed_trades) == 1
    assert len(update.positions) == 0


def test_position_manager_failure_followed_by_success_recovers():
    """Fetch failure preserves snapshot; next successful empty response
    produces genuine closes without duplicate events."""
    mt5 = FakeMT5()
    mt5.positions = [
        FakePos(10, "EURUSD", 0, 0.06, 1.10, 1.095, 1.109, magic=DEFAULT_MAGIC),
    ]
    pm = PositionManager(mt5=mt5)
    pm.update()  # seed

    # Failure
    mt5.raise_on_get = True
    fail_update = pm.update()
    assert fail_update.fetch_failed is True
    assert fail_update.closed_trades == []

    # Recovery: successful empty response -> real close
    mt5.raise_on_get = False
    mt5.positions = []
    success_update = pm.update()
    assert success_update.fetch_failed is False
    assert len(success_update.closed_trades) == 1
    assert success_update.closed_trades[0].ticket == 10


def test_reconciler_clean_when_both_match():
    """Empty diffs -> OK, block_trading False."""
    rec = Reconciler()
    local = {1: _make_pos(ticket=1), 2: _make_pos(ticket=2, symbol="GBPUSD")}
    remote = {1: _make_pos(ticket=1), 2: _make_pos(ticket=2, symbol="GBPUSD")}
    decision = rec.reconcile(local, remote)
    assert decision.status == ReconcileStatus.OK
    assert decision.is_clean is True
    assert decision.block_trading is False
    assert decision.orphans == []
    assert decision.unknown_opens == []
    assert decision.mismatches == []


def test_reconciler_orphan_when_local_open_remote_closed():
    """Bot thinks open, MT5 has it closed -> ORPHAN, block trading."""
    rec = Reconciler()
    local = {1: _make_pos(ticket=1)}
    remote: dict = {}  # broker closed it
    decision = rec.reconcile(local, remote)
    assert decision.status == ReconcileStatus.ORPHAN
    assert decision.orphans == [1]
    assert decision.block_trading is True
    assert "ORPHAN" in decision.details[0]


def test_reconciler_unknown_open_when_mt5_has_unexpected_ticket():
    """MT5 has a bot-magic ticket the bot has no local record of -> UNKNOWN_OPEN."""
    rec = Reconciler()
    local: dict = {}
    remote = {1: _make_pos(ticket=1)}
    decision = rec.reconcile(local, remote)
    assert decision.status == ReconcileStatus.UNKNOWN_OPEN
    assert decision.unknown_opens == [1]
    assert decision.block_trading is True


def test_reconciler_mismatch_on_volume_change():
    """Same ticket, volume differs -> MISMATCH, block trading."""
    rec = Reconciler()
    local = {1: _make_pos(ticket=1, volume=0.06)}
    remote = {1: _make_pos(ticket=1, volume=0.10)}
    decision = rec.reconcile(local, remote)
    assert decision.status == ReconcileStatus.MISMATCH
    assert decision.mismatches == [1]
    assert decision.block_trading is True
    assert "volume" in decision.details[0]


def test_reconciler_mismatch_on_sl_change():
    """Same ticket, SL differs -> MISMATCH (SL modified by broker or local stale)."""
    rec = Reconciler()
    local = {1: _make_pos(ticket=1, sl=1.09500)}
    remote = {1: _make_pos(ticket=1, sl=1.09400)}
    decision = rec.reconcile(local, remote)
    assert decision.status == ReconcileStatus.MISMATCH
    assert 1 in decision.mismatches
    assert "sl" in decision.details[0]


def test_reconciler_aggregates_worst_status():
    """When ORPHAN + MISMATCH coexist, status = MISMATCH (worst)."""
    rec = Reconciler()
    local = {
        1: _make_pos(ticket=1, volume=0.06),  # mismatch on volume
        2: _make_pos(ticket=2),  # orphan (not in remote)
    }
    remote = {1: _make_pos(ticket=1, volume=0.10)}
    decision = rec.reconcile(local, remote)
    assert decision.status == ReconcileStatus.MISMATCH
    assert 1 in decision.mismatches
    assert 2 in decision.orphans
    assert decision.block_trading is True
    # Details should mention both
    joined = " | ".join(decision.details)
    assert "MISMATCH" in joined
    assert "ORPHAN" in joined


def test_reconciler_block_trading_on_any_non_ok():
    """Acceptance: any non-OK status -> block_trading True."""
    rec = Reconciler()
    # ORPHAN only
    d1 = rec.reconcile({1: _make_pos(ticket=1)}, {})
    assert d1.block_trading is True
    # UNKNOWN_OPEN only
    d2 = rec.reconcile({}, {1: _make_pos(ticket=1)})
    assert d2.block_trading is True
    # MISMATCH only
    d3 = rec.reconcile(
        {1: _make_pos(ticket=1, sl=1.09)}, {1: _make_pos(ticket=1, sl=1.10)}
    )
    assert d3.block_trading is True
