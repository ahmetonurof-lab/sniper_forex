#!/usr/bin/env python
"""İŞ-4/N2#27 red tests — RECONNECT-V2: spot-freshness liveness.

Directive (DİREKTİF-10, Hakem verdict KABUL — ADIM-2/3/4-GO):
  failör modu "spot-ölü / TCP-sağlıklı" (SOAK-2 F1-reopened post-mortem,
  memory-bank/ARARAPOR_IS4_N227_RECONNECT_V2_20260911.md).

Root cause under test (SOAK-2, 2026-09-11): spot subscription died
~03:25 UTC (server-side silent) while TCP stayed healthy — heartbeat
traffic kept `is_stale()`==False forever, so `ensure_connected()` never
reconnected and the spot stream stayed dead → gate CLOSED ~13 min until
kill. `is_stale()` measures TCP/heartbeat traffic, NOT the spot-quote
stream.

İŞ-4 fix trio (pre-reg `results/N2_27_reconnect_v2_prereg.md`, pins FROZEN):
  1. CONNECTED-event → subscription reset (single point — covers passive
     AND active reconnect; both fire `_on_connected` → CONNECTED event).
  2. spot-freshness liveness: SPOT_FRESHNESS_SEC=90.0 → re-subscribe
     (churn-guard: ≥60s between attempts) → N=2 attempts → escalate
     reconnect.
  3. reconnect logs (connection.py — behaviour unchanged).

These tests exercise the REAL adapter code path
(src/ctrader/data_adapter.py) over a scripted fake connection that is
TCP-alive but spot-dead. Controlled unit evidence (AGENTS.md §3) — not
production-network proof (that is SOAK-3 natural retest, ADIM-4).
"""

import queue
import time

from src.ctrader.data_adapter import CTraderDataAdapter


class SpotDeadConnection:
    """TCP-alive / spot-ölü fake — SOAK-2 F1-reopened failure mode.

    `is_stale()` returns False (TCP healthy — heartbeat traffic flowing)
    but `subscribe_spots` enqueues NO spot event (the subscription is
    dead server-side). Mirrors the production contract surface the
    adapter touches: event_queue, is_connected, is_stale, reconnect,
    subscribe_spots.
    """

    def __init__(self, connected: bool = True):
        self.event_queue: queue.Queue = queue.Queue()
        self._connected = connected
        self.calls = []
        self._reconnect_count = 0

    # -- connection surface ------------------------------------------------
    def is_connected(self) -> bool:
        return self._connected

    def is_stale(self, timeout_sec: float = 60.0) -> bool:
        """TCP alive — heartbeat traffic flowing (is_stale()==False)."""
        return False

    def reconnect(self, max_attempts: int = 3) -> bool:
        """Active reconnect — simulates a forced ClientService restart."""
        self._reconnect_count += 1
        self.calls.append(("reconnect", max_attempts))
        self._connected = True
        return True

    # -- request methods ----------------------------------------------------
    def subscribe_spots(self, symbol_id):
        self.calls.append(("spots", symbol_id))
        # Spot-dead: NO spot event is enqueued (subscription is dead).


def _make_adapter(conn, **kw) -> CTraderDataAdapter:
    ad = CTraderDataAdapter(conn, **kw)
    # Pre-populate the symbol map so requests skip the symbols round-trip.
    ad._symbol_ids = {"BTCUSD": 10026, "EURUSD": 3}
    return ad


# ---------------------------------------------------------------------------
# ADIM-2 red tests — spot-dead / TCP-alive failure mode
# ---------------------------------------------------------------------------
class TestConnectedEventResetsSubscriptions:
    def test_connected_event_resets_spot_subscriptions(self):
        """CONNECTED event (passive reconnect) must reset per-connection
        spot subscriptions so the next get_tick_data re-subscribes.

        RED: `_consume_spot_events` requeues CONNECTED (non-spot) and never
        clears `_spot_subscribed` → after a passive reconnect the dead
        subscription is never re-established (SOAK-2 F1-reopened).
        """
        conn = SpotDeadConnection()
        adapter = _make_adapter(conn, response_timeout_sec=0.3)
        # Prime subscription state (as if subscribed before the drop).
        adapter._spot_subscribed.add("BTCUSD")
        adapter._last_spot["BTCUSD"] = {"bid": 1.0, "ask": 1.1, "time": int(time.time())}
        # Passive reconnect: CONNECTED event arrives (no adapter-triggered
        # _reconnect — the ClientService reconnected silently).
        conn.event_queue.put(("CONNECTED", None))
        adapter.get_tick_data("BTCUSD")
        # Re-subscribe must have fired (subscription was reset).
        assert ("spots", 10026) in conn.calls
        assert "BTCUSD" in adapter._spot_subscribed


class TestSpotFreshnessLiveness:
    def test_spot_freshness_triggers_resubscribe(self):
        """Spot quote older than SPOT_FRESHNESS_SEC (90s) but younger than
        tick_max_age (300s) must trigger a re-subscribe while the quote is
        still served (gate stays OPEN).

        RED: current code serves the quote and does nothing — the dead
        spot stream is never revived (SOAK-2 F1-reopened).
        """
        conn = SpotDeadConnection()
        adapter = _make_adapter(conn, response_timeout_sec=0.3)
        adapter._spot_subscribed.add("BTCUSD")
        adapter._last_spot["BTCUSD"] = {"bid": 1.0, "ask": 1.1, "time": int(time.time()) - 120}
        tick = adapter.get_tick_data("BTCUSD")
        assert tick is not None  # quote still served (< 300s)
        assert ("spots", 10026) in conn.calls  # re-subscribe fired

    def test_spot_freshness_churn_guard(self):
        """A stale quote must NOT re-subscribe on every tick — attempts are
        ≥ SPOT_RESUBSCRIBE_MIN_INTERVAL_SEC (60s) apart (churn guard)."""
        conn = SpotDeadConnection()
        adapter = _make_adapter(conn, response_timeout_sec=0.3)
        adapter._spot_subscribed.add("BTCUSD")
        adapter._last_spot["BTCUSD"] = {"bid": 1.0, "ask": 1.1, "time": int(time.time()) - 120}
        # First call → re-subscribe.
        adapter.get_tick_data("BTCUSD")
        spots = [c for c in conn.calls if c[0] == "spots"]
        assert len(spots) == 1
        # Second call within 60s → churn guard: NO re-subscribe.
        adapter.get_tick_data("BTCUSD")
        spots = [c for c in conn.calls if c[0] == "spots"]
        assert len(spots) == 1

    def test_spot_freshness_escalates_reconnect_after_n(self):
        """After SPOT_ESCALATE_AFTER_N (2) re-subscribe attempts the stream
        is still stale → escalate to an active reconnect (force-restart)."""
        conn = SpotDeadConnection()
        adapter = _make_adapter(conn, response_timeout_sec=0.3)
        adapter._spot_subscribed.add("BTCUSD")
        adapter._last_spot["BTCUSD"] = {"bid": 1.0, "ask": 1.1, "time": int(time.time()) - 120}
        # First attempt (attempts=1) — no escalate yet.
        adapter.get_tick_data("BTCUSD")
        assert conn._reconnect_count == 0
        # Second attempt after ≥60s (attempts=2 → escalate reconnect).
        adapter._spot_refresh_ts["BTCUSD"] = time.monotonic() - 61
        adapter._spot_refresh_attempts["BTCUSD"] = 1
        adapter.get_tick_data("BTCUSD")
        assert conn._reconnect_count == 1
