#!/usr/bin/env python
"""P0-1 — REAL MT5 TRAILING tests.

Covers:
- Execution.modify_position_sl_tp builds a real TRADE_ACTION_SLTP request.
- Broker confirmation (TRADE_RETCODE_DONE) gates local state updates.
- Duplicate suppression: same SL never re-sent.
- Rejection is surfaced (never silently ignored) and allows retry.
- signal_only=True stays dry-run.
- TrailingBridge: long/short, no_change, stale-position protection,
  closed-trade protection, rejection surfacing.
- End-to-end mock integration:
  signal -> entry fill -> runtime trailing decision (real apply_trailing)
  -> MT5 modify request -> broker confirmation.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pandas as pd

from src.live.execution import Execution, OrderRequest
from src.live.strategy_runtime import Signal, StrategyRuntime
from src.live.sizing import ContractSpec
from src.live.trailing_bridge import TrailingBridge
from src.strategy.models import Bar


# ── Fakes ────────────────────────────────────────────────────────────


class FakeMT5:
    """Fake MetaTrader5 module: captures every order_send payload."""

    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_SLTP = 2
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TIME_GTC = 1
    ORDER_FILLING_IOC = 1
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_INVALID = 10013
    CHECK_RETCODE_OK = 0  # order_check returns 0 on success

    def __init__(self, modify_ok: bool = True):
        self.requests = []
        self.modify_ok = modify_ok

    def order_check(self, request):
        return SimpleNamespace(retcode=self.CHECK_RETCODE_OK)

    def order_send(self, request):
        self.requests.append(dict(request))
        if request.get("action") == self.TRADE_ACTION_SLTP:
            if not self.modify_ok:
                return SimpleNamespace(
                    retcode=self.TRADE_RETCODE_INVALID, comment="invalid stops"
                )
            return SimpleNamespace(
                retcode=self.TRADE_RETCODE_DONE,
                order=0,
                deal=0,
                price=0.0,
                volume=0.0,
                position=request["position"],
                comment="sltp",
            )
        # Entry market order.
        return SimpleNamespace(
            retcode=self.TRADE_RETCODE_DONE,
            order=111,
            deal=222,
            price=request["price"],
            volume=request["volume"],
            position=999,
            comment="filled",
        )


def _signal(side="long"):
    entry = 1.1000
    sl = 1.0990 if side == "long" else 1.1010
    tp = 1.1018 if side == "long" else 1.0982
    return Signal(
        symbol="EURUSD",
        direction="bullish" if side == "long" else "bearish",
        side=side,
        entry_price=entry,
        sl=sl,
        tp=tp,
        entry_bar_index=1,
        sweep_bar_index=0,
        zone_index=0,
        zone_top=1.1005,
        zone_bottom=1.0995,
        zone_size=0.001,
        timestamp=pd.Timestamp("2026-08-01 00:00"),
    )


CONTRACT = ContractSpec(symbol="EURUSD")
ATR = 0.0010  # runtime ATR passed to apply_trailing


def _runtime_with_trade(side="long"):
    """Runtime holding an open trade exactly as on_bar would create it."""
    rt = StrategyRuntime("EURUSD")
    entry = 1.1000
    sl = 1.0990 if side == "long" else 1.1010
    tp = 1.1018 if side == "long" else 1.0982
    rt.active_trade = {
        "trade_id": 1,
        "side": side,
        "direction": "bullish" if side == "long" else "bearish",
        "entry_price": entry,
        "sl": sl,
        "tp": tp,
        "initial_sl": sl,
        "initial_tp": tp,
        "entry_bar": 1,
        "sweep_bar_index": 0,
        "zone_index": 0,
        "zone_creation_bar": 0,
        "zone_top": 1.1005,
        "zone_bottom": 1.0995,
        "zone_size": 0.001,
        "zone_size_atr": 1.0,
        "sweep_size_atr": 1.0,
        "bars_sweep_to_zone": 1,
        "bars_zone_to_entry": 1,
        "trailing_count": 0,
        "max_price": entry,
        "min_price": entry,
        "closed": False,
    }
    return rt


def _trailing_chunk():
    """15m bars engineering a bullish FVG trailing hop (deterministic).

    FVG: bottom=1.1005 (bar0.high), top=1.1010 (bar2.low), size 0.0005.
    bar4 closes inside the gap -> _fvg_close_confirmed True.
    """
    base = datetime(2026, 8, 3, 0, 0)
    spec = [
        # open,    high,    low,     close
        (1.1000, 1.1005, 1.0995, 1.1004),
        (1.1004, 1.1030, 1.1004, 1.1029),  # displacement
        (1.1025, 1.1035, 1.1010, 1.1032),
        (1.1032, 1.1036, 1.1025, 1.1030),
        (1.1030, 1.1032, 1.1006, 1.1007),  # close inside FVG -> confirm
        (1.1007, 1.1012, 1.1000, 1.1008),  # current bar (excluded by adapter)
    ]
    bars = []
    for i, (o, h, lo, c) in enumerate(spec):
        bars.append(
            Bar(
                index=i,
                timestamp=pd.Timestamp(base + timedelta(minutes=15 * i)),
                open=o,
                high=h,
                low=lo,
                close=c,
                volume=1000,
            )
        )
    return bars


# ── Execution.modify_position_sl_tp ─────────────────────────────────


def test_modify_builds_trade_action_sltp_and_confirms():
    fake = FakeMT5()
    ex = Execution(mt5=fake, signal_only=False)
    res = ex.modify_position_sl_tp(999, "EURUSD", sl=1.1004, tp=1.1018)
    assert res.sent and res.confirmed
    assert fake.requests, "order_send must be called"
    payload = fake.requests[-1]
    assert payload["action"] == FakeMT5.TRADE_ACTION_SLTP
    assert payload["position"] == 999
    assert payload["sl"] == 1.1004
    assert payload["tp"] == 1.1018
    assert payload["symbol"] == "EURUSD"
    # Broker-confirmed -> authoritative local mirror updated.
    assert ex.confirmed_sl_tp(999) == (1.1004, 1.1018)


def test_same_sl_never_resent():
    fake = FakeMT5()
    ex = Execution(mt5=fake, signal_only=False)
    ex.modify_position_sl_tp(999, "EURUSD", sl=1.1004, tp=1.1018)
    n_calls = len(fake.requests)
    res = ex.modify_position_sl_tp(999, "EURUSD", sl=1.1004, tp=1.1018)
    assert not res.sent and not res.confirmed
    assert res.reason == "already_confirmed"
    assert len(fake.requests) == n_calls, "duplicate modify must not hit broker"


def test_rejection_surfaced_and_local_state_unchanged_then_retry_ok():
    fake = FakeMT5(modify_ok=False)
    ex = Execution(mt5=fake, signal_only=False)
    res = ex.modify_position_sl_tp(999, "EURUSD", sl=1.1004, tp=1.1018)
    assert res.sent and not res.confirmed
    assert res.retcode == FakeMT5.TRADE_RETCODE_INVALID
    assert res.reason, "rejection must not be silent"
    assert ex.confirmed_sl_tp(999) is None, "no local update before confirmation"
    # In-flight marker cleared -> retry with broker OK succeeds.
    fake.modify_ok = True
    res2 = ex.modify_position_sl_tp(999, "EURUSD", sl=1.1004, tp=1.1018)
    assert res2.confirmed
    assert ex.confirmed_sl_tp(999) == (1.1004, 1.1018)


def test_signal_only_modify_is_dry_run():
    fake = FakeMT5()
    ex = Execution(mt5=fake, signal_only=True)
    res = ex.modify_position_sl_tp(999, "EURUSD", sl=1.1004, tp=1.1018)
    assert res.dry_run and not res.sent and not res.confirmed
    assert fake.requests == [], "signal_only must not hit the broker"


def test_entry_path_unchanged_captures_fill_metadata():
    fake = FakeMT5()
    ex = Execution(mt5=fake, signal_only=False)
    res = ex.send(OrderRequest(signal=_signal(), lot=0.01, contract=CONTRACT))
    assert res.filled
    assert res.order_id == 111 and res.deal_id == 222
    assert res.volume == 0.01 and res.position_id == 999
    payload = fake.requests[-1]
    assert payload["action"] == FakeMT5.TRADE_ACTION_DEAL, "entry path intact"


# ── TrailingBridge ───────────────────────────────────────────────────


def test_bridge_long_trailing_hop_reaches_broker():
    fake = FakeMT5()
    ex = Execution(mt5=fake, signal_only=False)
    bridge = TrailingBridge(execution=ex)
    rt = _runtime_with_trade("long")
    bridge.register_position(999, rt.active_trade["sl"], rt.active_trade["tp"])

    from experiment.trailing_adapter import apply_trailing  # noqa: E402

    apply_trailing(_trailing_chunk(), [rt.active_trade], ATR, "EURUSD")
    new_sl = rt.active_trade["sl"]
    assert new_sl > 1.0990, "engineered FVG must produce a real trailing hop"

    ev = bridge.sync(rt, 999)
    assert ev.action == "sent" and ev.confirmed
    assert ev.desired_sl == new_sl
    payload = fake.requests[-1]
    assert payload["action"] == FakeMT5.TRADE_ACTION_SLTP
    assert payload["sl"] == new_sl, "final modified SL must reach the request"
    assert bridge.confirmed_sl(999) == new_sl, "local state only after confirm"


def test_bridge_short_trailing_reaches_broker():
    fake = FakeMT5()
    ex = Execution(mt5=fake, signal_only=False)
    bridge = TrailingBridge(execution=ex)
    rt = _runtime_with_trade("short")
    bridge.register_position(999, rt.active_trade["sl"], rt.active_trade["tp"])
    # Simulate the adapter's short hop (bearish case is the mirror of the
    # long FVG engineering; the bridge consumes whatever runtime decided).
    rt.active_trade["sl"] = 1.1004
    rt.active_trade["tp"] = 1.0994
    rt.active_trade["trailing_count"] = 1

    ev = bridge.sync(rt, 999)
    assert ev.action == "sent" and ev.confirmed
    payload = fake.requests[-1]
    assert payload["sl"] == 1.1004 and payload["tp"] == 1.0994


def test_bridge_no_duplicate_modify_same_bar():
    fake = FakeMT5()
    ex = Execution(mt5=fake, signal_only=False)
    bridge = TrailingBridge(execution=ex)
    rt = _runtime_with_trade("long")
    bridge.register_position(999, rt.active_trade["sl"], rt.active_trade["tp"])
    rt.active_trade["sl"] = 1.1004
    ev1 = bridge.sync(rt, 999)
    assert ev1.action == "sent"
    n_calls = len(fake.requests)
    ev2 = bridge.sync(rt, 999)  # same bar / same SL
    assert ev2.action == "no_change"
    assert len(fake.requests) == n_calls


def test_bridge_stale_position_never_modifies():
    fake = FakeMT5()
    ex = Execution(mt5=fake, signal_only=False)
    bridge = TrailingBridge(execution=ex, is_open=lambda pid: False)
    rt = _runtime_with_trade("long")
    bridge.register_position(999, rt.active_trade["sl"], rt.active_trade["tp"])
    rt.active_trade["sl"] = 1.1004
    ev = bridge.sync(rt, 999)
    assert ev.action == "stale"
    assert fake.requests == [], "closed position must not receive modifies"
    assert bridge.confirmed_sl(999) is None


def test_bridge_closed_trade_no_modify():
    fake = FakeMT5()
    ex = Execution(mt5=fake, signal_only=False)
    bridge = TrailingBridge(execution=ex)
    rt = _runtime_with_trade("long")
    bridge.register_position(999, rt.active_trade["sl"], rt.active_trade["tp"])
    rt.active_trade["sl"] = 1.1004
    rt.active_trade["closed"] = True
    ev = bridge.sync(rt, 999)
    assert ev.action == "no_trade"
    assert fake.requests == []


def test_bridge_rejection_not_confirmed_and_surfaced():
    fake = FakeMT5(modify_ok=False)
    ex = Execution(mt5=fake, signal_only=False)
    bridge = TrailingBridge(execution=ex)
    rt = _runtime_with_trade("long")
    bridge.register_position(999, rt.active_trade["sl"], rt.active_trade["tp"])
    rt.active_trade["sl"] = 1.1004
    ev = bridge.sync(rt, 999)
    assert ev.action == "skipped" and not ev.confirmed
    assert ev.reason, "rejection must be surfaced"
    assert bridge.confirmed_sl(999) == 1.0990, "unconfirmed -> no local update"


# ── End-to-end mock integration ──────────────────────────────────────


def test_e2e_signal_entry_trailing_modify_confirm():
    """signal -> entry fill -> trailing decision -> MT5 modify -> confirm."""
    fake = FakeMT5()
    ex = Execution(mt5=fake, signal_only=False)
    sig = _signal()
    entry = ex.send(OrderRequest(signal=sig, lot=0.01, contract=CONTRACT))
    assert entry.filled and entry.position_id == 999

    bridge = TrailingBridge(execution=ex, is_open=lambda pid: pid == 999)
    bridge.register_position(entry.position_id, sig.sl, sig.tp)

    rt = _runtime_with_trade("long")
    assert rt.active_trade["sl"] == sig.sl
    from experiment.trailing_adapter import apply_trailing  # noqa: E402

    apply_trailing(_trailing_chunk(), [rt.active_trade], ATR, "EURUSD")
    trailed_sl = rt.active_trade["sl"]

    ev = bridge.sync(rt, entry.position_id)
    assert ev.confirmed and ev.desired_sl == trailed_sl
    # The modify request on the wire carries the final modified SL.
    assert fake.requests[-1]["sl"] == trailed_sl
    # Broker-confirmed mirror matches; a repeat sync sends nothing.
    assert bridge.confirmed_sl(999) == trailed_sl
    # Adapter also parallel-shifts TP (ctp += sl_delta); confirmed TP matches.
    assert ex.confirmed_sl_tp(999) == (trailed_sl, rt.active_trade["tp"])
    n = len(fake.requests)
    assert bridge.sync(rt, 999).action == "no_change"
    assert len(fake.requests) == n
