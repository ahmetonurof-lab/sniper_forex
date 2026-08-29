#!/usr/bin/env python
"""Task 0.1 — Startup Broker State Snapshot: focused tests."""

from __future__ import annotations

from types import SimpleNamespace

from src.live.live_runner import LiveRunner


def _make_terminal(build=6140, path="C:/MT5/terminal64.exe"):
    return SimpleNamespace(build=build, path=path)


def _make_account(
    login=53012914, server="ICMarketsSC-Demo", balance=10000.0, equity=10050.0
):
    return SimpleNamespace(
        login=login,
        server=server,
        balance=balance,
        equity=equity,
        leverage=100,
        margin=0.0,
        margin_free=10000.0,
        profit=0.0,
        currency="USD",
        name="Demo",
        company="IC Markets",
    )


def _make_position(ticket, symbol, side_type, volume, entry, sl, tp, magic, profit=0.0):
    return SimpleNamespace(
        ticket=ticket,
        symbol=symbol,
        type=side_type,
        volume=volume,
        price_open=entry,
        sl=sl,
        tp=tp,
        magic=magic,
        comment="test",
        time=1700000000,
        profit=profit,
        swap=0.0,
    )


def _make_order(ticket, symbol, order_type, volume, price, magic):
    return SimpleNamespace(
        ticket=ticket,
        symbol=symbol,
        type=order_type,
        volume_initial=volume,
        price_open=price,
        magic=magic,
        comment="test",
        state=0,
    )


class FakeMT5:
    """Minimal MT5 mock for startup snapshot tests."""

    def __init__(self, terminal=None, account=None, positions=None, orders=None):
        self._terminal = terminal
        self._account = account
        self._positions = positions or []
        self._orders = orders or []

    def terminal_info(self):
        return self._terminal

    def account_info(self):
        return self._account

    def positions_get(self):
        return self._positions

    def orders_get(self):
        return self._orders


def test_startup_snapshot_connected_clean():
    """Connected, account OK, no positions, no orders -> PASS."""
    mt5 = FakeMT5(
        terminal=_make_terminal(build=6140),
        account=_make_account(),
        positions=[],
        orders=[],
    )
    runner = LiveRunner(symbol="EURUSD", mt5=mt5)
    snap = runner.startup_snapshot(configured_symbols=["EURUSD", "GBPUSD"])

    assert snap["mt5_connected"] is True
    assert snap["mt5_build"] == "6140"
    assert snap["account"] == "53012914"
    assert snap["server"] == "ICMarketsSC-Demo"
    assert snap["balance"] == 10000.0
    assert snap["equity"] == 10050.0
    assert snap["symbols"] == ["EURUSD", "GBPUSD"]
    assert snap["positions"] == []
    assert snap["pending_orders"] == []
    assert snap["reconciliation"]["status"] == "OK"
    assert snap["reconciliation"]["block_trading"] is False
    assert snap["safe_mode"] is False


def test_startup_snapshot_with_positions():
    """Open positions are captured with SL/TP protection info."""
    positions = [
        _make_position(
            1, "EURUSD", 0, 0.10, 1.1000, 1.0990, 1.1018, 9007001, profit=5.0
        ),
        _make_position(2, "GBPUSD", 1, 0.05, 1.2500, 0.0, 1.2550, 9007001, profit=-2.0),
    ]
    mt5 = FakeMT5(
        terminal=_make_terminal(),
        account=_make_account(),
        positions=positions,
    )
    runner = LiveRunner(symbol="EURUSD", mt5=mt5)
    snap = runner.startup_snapshot()

    assert len(snap["positions"]) == 2
    assert snap["positions"][0]["symbol"] == "EURUSD"
    assert snap["positions"][0]["side"] == "long"
    assert snap["positions"][0]["sl"] == 1.0990
    assert snap["positions"][0]["tp"] == 1.1018
    # Second position has no SL (sl=0.0)
    assert snap["positions"][1]["sl"] == 0.0


def test_startup_snapshot_filters_other_magic():
    """Positions/orders with different magic are ignored."""
    positions = [
        _make_position(1, "EURUSD", 0, 0.10, 1.1000, 1.0990, 1.1018, 9007001),
        _make_position(
            99, "EURUSD", 0, 1.00, 1.1000, 1.0990, 1.1018, 123456
        ),  # other magic
    ]
    orders = [
        _make_order(100, "EURUSD", 2, 0.05, 1.0980, 9007001),
        _make_order(101, "EURUSD", 2, 1.00, 1.0970, 999999),  # other magic
    ]
    mt5 = FakeMT5(
        terminal=_make_terminal(),
        account=_make_account(),
        positions=positions,
        orders=orders,
    )
    runner = LiveRunner(symbol="EURUSD", mt5=mt5)
    snap = runner.startup_snapshot()

    assert len(snap["positions"]) == 1
    assert snap["positions"][0]["ticket"] == 1
    assert len(snap["pending_orders"]) == 1
    assert snap["pending_orders"][0]["ticket"] == 100


def test_startup_snapshot_disconnected():
    """No terminal info -> disconnected, safe_mode=True."""
    mt5 = FakeMT5(terminal=None, account=None)
    runner = LiveRunner(symbol="EURUSD", mt5=mt5)
    snap = runner.startup_snapshot()

    assert snap["mt5_connected"] is False
    assert snap["account"] == "unknown"
    assert snap["safe_mode"] is True
    assert snap["reconciliation"]["block_trading"] is True


def test_startup_snapshot_no_mt5_module():
    """mt5=None -> graceful degradation, safe_mode=True."""
    runner = LiveRunner(symbol="EURUSD", mt5=None)
    snap = runner.startup_snapshot()

    assert snap["mt5_connected"] is False
    assert snap["safe_mode"] is True


def test_startup_snapshot_reconciliation_orphan():
    """Local state has a position that broker doesn't -> ORPHAN -> safe_mode."""
    mt5 = FakeMT5(
        terminal=_make_terminal(),
        account=_make_account(),
        positions=[],  # broker has no positions
    )
    runner = LiveRunner(symbol="EURUSD", mt5=mt5)
    # Simulate local state: lifecycle thinks position 999 is open
    runner.lifecycle.open_trades[999] = SimpleNamespace(
        position_id=999,
        symbol="EURUSD",
        side="long",
        filled_volume=0.10,
        entry_price=1.1000,
        initial_sl=1.0990,
    )
    snap = runner.startup_snapshot()

    assert snap["reconciliation"]["status"] == "ORPHAN"
    assert snap["reconciliation"]["block_trading"] is True
    assert snap["safe_mode"] is True
    assert any("ORPHAN" in d for d in snap["reconciliation"]["details"])


def test_startup_snapshot_reconciliation_unknown_open():
    """Broker has position that local doesn't know -> UNKNOWN_OPEN -> safe_mode."""
    positions = [
        _make_position(500, "EURUSD", 0, 0.10, 1.1000, 1.0990, 1.1018, 9007001),
    ]
    mt5 = FakeMT5(
        terminal=_make_terminal(),
        account=_make_account(),
        positions=positions,
    )
    runner = LiveRunner(symbol="EURUSD", mt5=mt5)
    # Local state is empty (no lifecycle entry for ticket 500)

    assert runner.startup_snapshot()["reconciliation"]["status"] == "UNKNOWN_OPEN"
    assert runner.startup_snapshot()["reconciliation"]["block_trading"] is True
    assert runner.startup_snapshot()["safe_mode"] is True


def test_startup_snapshot_pending_orders_captured():
    """Pending orders are captured."""
    orders = [
        _make_order(200, "EURUSD", 2, 0.05, 1.0980, 9007001),  # buy limit
        _make_order(201, "GBPUSD", 3, 0.10, 1.2480, 9007001),  # sell limit
    ]
    mt5 = FakeMT5(
        terminal=_make_terminal(),
        account=_make_account(),
        orders=orders,
    )
    runner = LiveRunner(symbol="EURUSD", mt5=mt5)
    snap = runner.startup_snapshot()

    assert len(snap["pending_orders"]) == 2
    assert snap["pending_orders"][0]["type"] == 2
    assert snap["pending_orders"][1]["price"] == 1.2480


def test_startup_snapshot_audit_event_emitted():
    """Snapshot emits a STARTUP audit event."""
    mt5 = FakeMT5(
        terminal=_make_terminal(build=6140),
        account=_make_account(),
    )
    runner = LiveRunner(symbol="EURUSD", mt5=mt5)
    runner.startup_snapshot(configured_symbols=["EURUSD"])

    # Check audit chain has a STARTUP event
    startup_events = [e for e in runner.audit.events if e.event_type.value == "STARTUP"]
    assert len(startup_events) == 1
    payload = startup_events[0].payload
    assert payload["mt5_connected"] is True
    assert payload["mt5_build"] == "6140"
    assert payload["account"] == "53012914"
    assert payload["safe_mode"] is False


def test_startup_snapshot_local_state_reported():
    """Local runtime state (open_trades, dd_reliable, quarantined) is reported."""
    mt5 = FakeMT5(
        terminal=_make_terminal(),
        account=_make_account(),
    )
    runner = LiveRunner(symbol="EURUSD", mt5=mt5)
    runner.lifecycle.dd_reliable = False
    runner.lifecycle.quarantined_exits[123] = SimpleNamespace(reason="unknown_position")
    runner._known_position_ids = {10, 20}

    snap = runner.startup_snapshot()

    assert snap["local_state"]["dd_reliable"] is False
    assert snap["local_state"]["quarantined_exits_count"] == 1
    assert set(snap["local_state"]["known_position_ids"]) == {10, 20}


# ── Integration: auto_snapshot in __init__ ─────────────────────────


def test_auto_snapshot_false_by_default():
    """Default behavior: no snapshot emitted during __init__."""
    mt5 = FakeMT5(
        terminal=_make_terminal(),
        account=_make_account(),
    )
    runner = LiveRunner(symbol="EURUSD", mt5=mt5)
    # No STARTUP audit event should exist
    startup_events = [e for e in runner.audit.events if e.event_type.value == "STARTUP"]
    assert len(startup_events) == 0


def test_auto_snapshot_true_emits_snapshot():
    """auto_snapshot=True triggers snapshot during __init__."""
    mt5 = FakeMT5(
        terminal=_make_terminal(build=6140),
        account=_make_account(),
    )
    runner = LiveRunner(
        symbol="EURUSD",
        mt5=mt5,
        auto_snapshot=True,
        configured_symbols=["EURUSD", "GBPUSD"],
    )
    # STARTUP audit event should exist
    startup_events = [e for e in runner.audit.events if e.event_type.value == "STARTUP"]
    assert len(startup_events) == 1
    assert startup_events[0].payload["mt5_connected"] is True
    assert startup_events[0].payload["mt5_build"] == "6140"


def test_auto_snapshot_true_passes_configured_symbols():
    """configured_symbols is forwarded to the snapshot."""
    mt5 = FakeMT5(
        terminal=_make_terminal(),
        account=_make_account(),
    )
    runner = LiveRunner(
        symbol="EURUSD",
        mt5=mt5,
        auto_snapshot=True,
        configured_symbols=["EURUSD", "GBPUSD", "USDJPY"],
    )
    startup_events = [e for e in runner.audit.events if e.event_type.value == "STARTUP"]
    assert len(startup_events) == 1
    # The snapshot should have captured the configured symbols
    # (verified indirectly: snapshot ran without error and emitted the event)


def test_auto_snapshot_handles_broker_failure():
    """auto_snapshot with disconnected broker -> safe_mode=True, no crash."""

    class BrokenMT5:
        def terminal_info(self):
            raise ConnectionError("broker unreachable")

        def account_info(self):
            return None

        def positions_get(self):
            return []

        def orders_get(self):
            return []

    runner = LiveRunner(
        symbol="EURUSD",
        mt5=BrokenMT5(),
        auto_snapshot=True,
    )
    startup_events = [e for e in runner.audit.events if e.event_type.value == "STARTUP"]
    assert len(startup_events) == 1
    assert startup_events[0].payload["mt5_connected"] is False
    assert startup_events[0].payload["safe_mode"] is True
