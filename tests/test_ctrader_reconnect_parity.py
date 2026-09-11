#!/usr/bin/env python
"""İŞ-3 red tests — cTrader reconnect parity (MT5 semantics).

Directive (HAKEM_DIREKTIFI_UCISLI_TUR_20260910.md, İŞ-3):
  bağlantı-düşüşü-simülasyonu → quote-stream'ının-kendiliğinden-dönmesi
  BEKLENİR (MT5-paritesi: operasyon-öncesi-ensure_connected +
  attempts-yükseltme).

Root cause under test (post-soak audit F1, 2026-09-10): cTrader transport
corruption 19:27:26 → gate-CLOSED 19:31:18 → ~75 min NO recovery until kill.
The ClientService retry policy only engages on a DETECTED disconnect
(Twisted connectionLost); a half-open TCP connection (network drop without
FIN/RST) never fires it, so the passive policy never reconnects. The
adapter's is_connected() reads the stale callback flag → True forever →
ensure_connected(max_attempts=1) returns True without reconnecting →
requests time out → quote stream stays dead.

MT5 parity (mt5_connection.py:130/:154/:173/:206/:242): per-operation
ensure_connected → real liveness probe → reconnect(max_attempts=3).

These tests exercise the REAL adapter code path
(src/ctrader/data_adapter.py) over a scripted fake connection that can
drop and recover. Controlled unit evidence (AGENTS.md §3) — not
production-network proof (that is the new-soak natural observation, ADIM-4).
"""

import queue
import time
from typing import Any, List

from src.ctrader.data_adapter import (
    CTRADER_PERIOD_M1,
    CTraderDataAdapter,
)


# ---------------------------------------------------------------------------
# Protobuf-shaped fakes (attribute-compatible with the real SDK messages)
# ---------------------------------------------------------------------------
class FakeTrendbar:
    def __init__(self, utc_min: int, low_scaled: int, d_open: int, d_high: int, d_close: int):
        self.utcTimestampInMinutes = utc_min
        self.low = low_scaled
        self.deltaOpen = d_open
        self.deltaHigh = d_high
        self.deltaClose = d_close
        self.volume = 100
        self.period = CTRADER_PERIOD_M1


class FakeLightSymbol:
    def __init__(self, symbol_id: int, symbol_name: str):
        self.symbolId = symbol_id
        self.symbolName = symbol_name


class ProtoOASymbolsListRes:
    def __init__(self, symbols):
        self.symbol = symbols


class ProtoOAGetTrendbarsRes:
    def __init__(self, bars):
        self.trendbar = bars
        self.hasMore = False


class ProtoOASpotEvent:
    def __init__(self, symbol_id, bid, ask, ts_ms):
        self.symbolId = symbol_id
        self.bid = bid
        self.ask = ask
        self.timestamp = ts_ms


class ProtoOAReconcileRes:
    def __init__(self, positions):
        self.position = positions


def _make_bars(n: int, start_utc_min: int = 29_000_000) -> List[FakeTrendbar]:
    bars = []
    for i in range(n):
        bars.append(
            FakeTrendbar(
                utc_min=start_utc_min + i,
                low_scaled=6_000_000_000,
                d_open=1000 + i,
                d_high=5000,
                d_close=2000,
            )
        )
    return bars


class RecoverableConnection:
    """Scripted fake of CTraderConnection's surface that can drop and
    recover. Mirrors the production contract: event_queue responses,
    send-side request methods, is_connected flag, is_stale liveness probe,
    and an ACTIVE reconnect() (the MT5-parity surface the adapter must use).

    `_stale` simulates a half-open TCP connection: the callback flag stays
    True (no disconnect event fired) but no server messages arrive.
    """

    def __init__(self, connected: bool = True):
        self.event_queue: queue.Queue = queue.Queue()
        self._connected = connected
        self._stale = False
        self.calls: List[Any] = []
        self._reconnect_count = 0

    # -- connection surface ------------------------------------------------
    def is_connected(self) -> bool:
        return self._connected

    def is_stale(self, timeout_sec: float = 60.0) -> bool:
        return self._stale

    def reconnect(self, max_attempts: int = 3) -> bool:
        """Active reconnect — simulates recovery (connection + auth back)."""
        self._reconnect_count += 1
        self.calls.append(("reconnect", max_attempts))
        self._connected = True
        self._stale = False
        return True

    # -- request methods ----------------------------------------------------
    def request_symbols_list(self, include_archived=False):
        self.calls.append(("symbols", None))
        if not self._connected:
            raise RuntimeError("not connected")
        self.event_queue.put(
            (
                "MESSAGE",
                ProtoOASymbolsListRes(
                    [FakeLightSymbol(10026, "BTCUSD"), FakeLightSymbol(3, "EURUSD")]
                ),
            )
        )

    def request_trendbars(self, symbol_id, period, from_ms, to_ms, count=None):
        self.calls.append(
            (
                "trendbars",
                dict(symbol_id=symbol_id, period=period, from_ms=from_ms, to_ms=to_ms, count=count),
            )
        )
        if not self._connected:
            raise RuntimeError("not connected")
        bars = _make_bars(count or 5)
        self.event_queue.put(("MESSAGE", ProtoOAGetTrendbarsRes(bars)))

    def subscribe_spots(self, symbol_id):
        self.calls.append(("spots", symbol_id))
        if not self._connected:
            raise RuntimeError("not connected")
        self.event_queue.put(
            (
                "MESSAGE",
                ProtoOASpotEvent(symbol_id, 6_000_010_000, 6_000_020_000, int(time.time() * 1000)),
            )
        )

    def reconcile(self):
        self.calls.append(("reconcile", None))
        if not self._connected:
            raise RuntimeError("not connected")
        self.event_queue.put(("MESSAGE", ProtoOAReconcileRes(positions=[])))


def _make_adapter(conn, **kw) -> CTraderDataAdapter:
    ad = CTraderDataAdapter(conn, **kw)
    # Pre-populate the symbol map so requests skip the symbols round-trip.
    ad._symbol_ids = {"BTCUSD": 10026, "EURUSD": 3}
    return ad


# ---------------------------------------------------------------------------
# ADIM-2 red tests — connection-drop simulation → quote-stream self-recovery
# ---------------------------------------------------------------------------
class TestQuoteStreamSelfRecovery:
    def test_quote_stream_self_recovers_after_connection_drop(self):
        """MT5 parity: per-operation ensure_connected + attempts upgrade.

        After a full connection drop, get_tick_data must trigger an active
        reconnect and the quote stream must recover (the 19:31→20:46 gap:
        current code returns None on the stale quote and NEVER reconnects).
        """
        conn = RecoverableConnection(connected=True)
        adapter = _make_adapter(conn, tick_max_age_sec=300.0)
        # Prime the spot subscription with a fresh quote.
        assert adapter.get_tick_data("BTCUSD") is not None
        # Simulate the drop: connection dead AND the stored quote goes stale
        # (no new spot events arrive — the 19:27→19:31 audit trace).
        conn._connected = False
        adapter._last_spot["BTCUSD"]["time"] = int(time.time()) - 1000  # > 300s old
        # RED: current code returns None (stale) and never reconnects.
        quote = adapter.get_tick_data("BTCUSD")
        assert quote is not None
        assert ("reconnect", 3) in conn.calls

    def test_half_open_connection_reconnects_via_stale_detection(self):
        """Half-open TCP (callback flag True but no server messages) →
        is_stale detects it → ensure_connected triggers reconnect.

        This is the exact 19:31→20:46 root cause: the flag never flips
        (no connectionLost), so the passive ClientService policy never
        engages. The liveness probe must catch it.
        """
        conn = RecoverableConnection(connected=True)
        adapter = _make_adapter(conn)
        # Prime the spot subscription.
        assert adapter.get_tick_data("BTCUSD") is not None
        # Half-open: flag stays True but no server messages arrive.
        conn._stale = True
        quote = adapter.get_tick_data("BTCUSD")
        assert quote is not None
        assert ("reconnect", 3) in conn.calls


class TestGetRatesReconnect:
    def test_get_rates_reconnects_after_drop(self):
        """Per-operation ensure_connected: get_rates must reconnect when the
        connection is down instead of returning None without recovery."""
        conn = RecoverableConnection(connected=True)
        adapter = _make_adapter(conn)
        conn._connected = False
        rates = adapter.get_rates("BTCUSD", "M1", 5)
        assert rates is not None and len(rates) == 5
        assert ("reconnect", 3) in conn.calls

    def test_get_rates_timeout_triggers_reconnect(self):
        """Stale-gate → reconnect trigger: a request timeout on a stale
        (half-open) connection must trigger an active reconnect."""
        conn = RecoverableConnection(connected=True)
        adapter = _make_adapter(conn, response_timeout_sec=0.3)

        def no_response(symbol_id, period, from_ms, to_ms, count=None):
            conn.calls.append(("trendbars", {}))  # never responds

        conn.request_trendbars = no_response
        # Half-open: flag True but stale (no server messages).
        conn._stale = True
        rates = adapter.get_rates("BTCUSD", "M1", 5)
        assert rates is None  # still no data — but the reconnect must fire
        assert ("reconnect", 3) in conn.calls


class TestGetPositionsReconnect:
    def test_get_positions_reconnects_after_drop(self):
        """Per-operation ensure_connected: get_positions must reconnect when
        the connection is down instead of raising ctrader_not_connected."""
        conn = RecoverableConnection(connected=True)
        adapter = _make_adapter(conn)
        conn._connected = False
        positions = adapter.get_positions()
        assert positions == []
        assert ("reconnect", 3) in conn.calls


class TestEnsureConnectedAttempts:
    def test_ensure_connected_attempts_upgrade(self):
        """MT5 parity: ensure_connected default max_attempts=3 (was 1) and
        actively reconnects a dead connection instead of a bounded wait."""
        conn = RecoverableConnection(connected=False)
        adapter = _make_adapter(conn)
        ok = adapter.ensure_connected()
        assert ok is True
        assert ("reconnect", 3) in conn.calls
