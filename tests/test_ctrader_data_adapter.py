#!/usr/bin/env python
"""Unit tests for the cTrader data adapter — İş-4a (D155).

Controlled unit evidence (AGENTS.md §3): these tests exercise the REAL
adapter code path (src/ctrader/data_adapter.py + connection request
methods) WITHOUT a network socket or Twisted reactor. A scripted fake
connection feeds real protobuf-shaped objects through the same
event_queue contract the production connection uses.

NOT claimed as production-network evidence; that belongs to the first
cTrader-path boot (audit-observed).
"""

import queue
import time
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from src.ctrader.data_adapter import (
    CTRADER_PERIOD_M1,
    CTraderDataAdapter,
    CTraderDataError,
    trendbar_to_dict,
)


# ---------------------------------------------------------------------------
# Protobuf-shaped fakes (attribute-compatible with the real SDK messages)
# ---------------------------------------------------------------------------
class FakeTrendbar:
    def __init__(
        self,
        utc_min: int,
        low_scaled: int,
        d_open: int,
        d_high: int,
        d_close: int,
        volume: int = 100,
    ):
        self.utcTimestampInMinutes = utc_min
        self.low = low_scaled
        self.deltaOpen = d_open
        self.deltaHigh = d_high
        self.deltaClose = d_close
        self.volume = volume
        self.period = CTRADER_PERIOD_M1


class FakeLightSymbol:
    def __init__(self, symbol_id: int, symbol_name: str):
        self.symbolId = symbol_id
        self.symbolName = symbol_name


# NOTE: fake class names intentionally mirror the real protobuf message
# names — the adapter matches responses via type(payload).__name__, so
# these fakes must present the exact same type names (no weakening).
class ProtoOASymbolsListRes:
    def __init__(self, symbols):
        self.symbol = symbols


class ProtoOAGetTrendbarsRes:
    def __init__(self, bars):
        self.trendbar = bars
        # Mirrors the real protobuf message: hasMore is an Optional bool
        # field (official docs). Default absent/False — the fail-loud
        # guard only fires when the server actually chunked the response.
        self.hasMore = False


class ProtoOASpotEvent:
    def __init__(self, symbol_id, bid, ask, ts):
        self.symbolId = symbol_id
        self.bid = bid
        self.ask = ask
        self.timestamp = ts


def make_bars(n: int, start_utc_min: int = 29_000_000) -> List[FakeTrendbar]:
    """n ascending M1 bars: low=60000.00, o/c/h offsets deterministic."""
    bars = []
    for i in range(n):
        bars.append(
            FakeTrendbar(
                utc_min=start_utc_min + i,
                low_scaled=6_000_000_000,  # 60000.00
                d_open=1000 + i,  # +0.010
                d_high=5000,  # +0.050
                d_close=2000,  # +0.020
                volume=10 + i,
            )
        )
    return bars


class FakeConnection:
    """Scripted fake of CTraderConnection's surface the adapter touches.

    Mirrors the production contract: event_queue responses, send-side
    request methods, is_connected flag. Raises on send when disconnected.
    """

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
        bars = make_bars(count or 5)
        self.event_queue.put(("MESSAGE", ProtoOAGetTrendbarsRes(bars)))

    def subscribe_spots(self, symbol_id):
        self.calls.append(("spots", symbol_id))
        if not self._connected:
            raise RuntimeError("not connected")
        # First spot event arrives right after subscribe (official docs).
        self.event_queue.put(
            (
                "MESSAGE",
                ProtoOASpotEvent(symbol_id, 6_000_010_000, 6_000_020_000, int(time.time())),
            )
        )


# ---------------------------------------------------------------------------
# trendbar_to_dict — price/time decode
# ---------------------------------------------------------------------------
class TestTrendbarDecode:
    def test_price_decode_1e5_scale(self):
        d = trendbar_to_dict(make_bars(1)[0], server_offset_hours=2)
        assert d["open"] == pytest.approx(60000.01)
        assert d["high"] == pytest.approx(60000.05)
        assert d["low"] == pytest.approx(60000.00)
        assert d["close"] == pytest.approx(60000.02)
        # make_bars first bar: volume = 10 + 0
        assert d["tick_volume"] == 10.0

    def test_time_reexpressed_as_server_seconds(self):
        utc_min = 29_000_000
        d = trendbar_to_dict(make_bars(1, utc_min)[0], server_offset_hours=2)
        assert d["time"] == utc_min * 60 + 2 * 3600

    def test_roundtrip_via_rates_to_bars_recovers_utc(self):
        """Adapter(server-seconds) → SignalRunner._rates_to_bars → UTC:
        the single-conversion-convention invariant (module docstring).

        Bar date is chosen inside the SAME DST bucket as the adapter's
        server_offset (July → summer offset 3), mirroring live conditions
        where both sides resolve the same bucket for the same moment.
        """
        import pandas as pd

        from src.live.clock import server_utc_offset
        from src.live.signal_runner import SignalRunner

        # July 2025 15:20 UTC → inside the Mar-last-Sun..Oct-last-Sun bucket.
        utc_min = int(pd.Timestamp("2025-07-15 15:20:00").timestamp()) // 60
        offset = server_utc_offset(pd.Timestamp("2025-07-15 15:20:00").to_pydatetime())
        d = trendbar_to_dict(make_bars(1, utc_min)[0], server_offset_hours=offset)
        rates = [d]
        bars = SignalRunner._rates_to_bars(rates)
        expected_utc = pd.Timestamp(utc_min * 60, unit="s")
        assert bars[0].timestamp == expected_utc


# ---------------------------------------------------------------------------
# Symbol resolution
# ---------------------------------------------------------------------------
class TestSymbolResolution:
    def test_resolve_and_cache(self):
        conn = FakeConnection()
        ad = CTraderDataAdapter(conn, server_offset_hours=2)
        sid = ad._resolve_symbol_id("BTCUSD")
        assert sid == 10026
        # Second call is cached — no new request.
        ad._resolve_symbol_id("BTCUSD")
        assert conn.calls.count(("symbols", None)) == 1

    def test_unknown_symbol_fail_loud(self):
        conn = FakeConnection()
        ad = CTraderDataAdapter(conn, server_offset_hours=2)
        with pytest.raises(CTraderDataError, match="unknown_symbol"):
            ad._resolve_symbol_id("NOPEUSD")

    def test_not_connected_fail_loud(self):
        conn = FakeConnection(connected=False)
        ad = CTraderDataAdapter(conn, server_offset_hours=2)
        with pytest.raises(CTraderDataError, match="ctrader_not_connected"):
            ad._resolve_symbol_id("BTCUSD")


# ---------------------------------------------------------------------------
# get_rates — tri-state contract
# ---------------------------------------------------------------------------
class TestGetRates:
    def test_returns_mt5_shaped_dicts_oldest_first(self):
        conn = FakeConnection()
        ad = CTraderDataAdapter(conn, server_offset_hours=2)
        rates = ad.get_rates("BTCUSD", "M1", 5)
        assert rates is not None and len(rates) == 5
        assert all(set(r) == {"time", "open", "high", "low", "close", "tick_volume"} for r in rates)
        times = [r["time"] for r in rates]
        assert times == sorted(times)

    def test_request_params_period_and_count(self):
        conn = FakeConnection()
        ad = CTraderDataAdapter(conn, server_offset_hours=2)
        ad.get_rates("BTCUSD", "M1", 7)
        tb_calls = [c for c in conn.calls if c[0] == "trendbars"]
        assert len(tb_calls) == 1
        params = tb_calls[0][1]
        assert params["period"] == CTRADER_PERIOD_M1 == 1
        assert params["count"] == 7
        assert params["symbol_id"] == 10026
        # Window: (count+2) minutes back from now_ms.
        assert params["to_ms"] > params["from_ms"]
        assert params["to_ms"] - params["from_ms"] == (7 + 2) * 60 * 1000

    def test_unsupported_timeframe_fail_loud(self):
        conn = FakeConnection()
        ad = CTraderDataAdapter(conn, server_offset_hours=2)
        with pytest.raises(CTraderDataError, match="unsupported_timeframe"):
            ad.get_rates("BTCUSD", "M5", 5)

    def test_disconnected_returns_none_transient(self):
        conn = FakeConnection(connected=False)
        ad = CTraderDataAdapter(conn, server_offset_hours=2)
        assert ad.get_rates("BTCUSD", "M1", 5) is None

    def test_timeout_returns_none(self):
        conn = FakeConnection()

        # Response never arrives → None (orchestrator ERROR-ladder path).
        def slow_trendbars(symbol_id, period, from_ms, to_ms, count=None):
            conn.calls.append(("trendbars", {}))  # no queue put

        conn.request_trendbars = slow_trendbars
        ad = CTraderDataAdapter(conn, response_timeout_sec=0.3, server_offset_hours=2)
        assert ad.get_rates("BTCUSD", "M1", 5) is None

    def test_error_event_returns_none(self):
        conn = FakeConnection()

        def err_trendbars(symbol_id, period, from_ms, to_ms, count=None):
            conn.calls.append(("trendbars", {}))
            conn.event_queue.put(("TRENDBARS_ERROR", "boom"))

        conn.request_trendbars = err_trendbars
        ad = CTraderDataAdapter(conn, server_offset_hours=2)
        assert ad.get_rates("BTCUSD", "M1", 5) is None

    def test_leftover_events_requeued(self):
        """Side events between request and response are preserved."""
        conn = FakeConnection()
        orig = conn.request_trendbars

        def with_noise(symbol_id, period, from_ms, to_ms, count=None):
            conn.event_queue.put(("HEARTBEAT", None))
            conn.event_queue.put(("ACCOUNT_AUTH_RES", SimpleNamespace()))
            orig(symbol_id, period, from_ms, to_ms, count)

        conn.request_trendbars = with_noise
        ad = CTraderDataAdapter(conn, server_offset_hours=2)
        rates = ad.get_rates("BTCUSD", "M1", 3)
        assert rates is not None and len(rates) == 3
        # HEARTBEAT + ACCOUNT_AUTH_RES preserved in queue.
        kinds = []
        while True:
            try:
                kinds.append(conn.event_queue.get_nowait()[0])
            except queue.Empty:
                break
        assert "HEARTBEAT" in kinds and "ACCOUNT_AUTH_RES" in kinds


# ---------------------------------------------------------------------------
# get_tick_data — spot contract
# ---------------------------------------------------------------------------
class TestGetTickData:
    def test_first_quote_after_subscribe(self):
        conn = FakeConnection()
        ad = CTraderDataAdapter(conn, server_offset_hours=2)
        tick = ad.get_tick_data("BTCUSD")
        assert tick is not None
        assert tick["bid"] == pytest.approx(60000.10)
        assert tick["ask"] == pytest.approx(60000.20)
        assert abs(tick["time"] - time.time()) < 60

    def test_stale_quote_returns_none(self):
        conn = FakeConnection()
        ad = CTraderDataAdapter(conn, tick_max_age_sec=10.0, server_offset_hours=2)
        # Pre-mark subscribed so the forced old quote is not overwritten by
        # the fake's fresh subscribe-time event.
        ad._spot_subscribed.add("BTCUSD")
        ad._last_spot["BTCUSD"] = {"bid": 1.0, "ask": 1.1, "time": int(time.time()) - 300}
        assert ad.get_tick_data("BTCUSD") is None

    def test_no_subscription_and_no_response_returns_none(self):
        conn = FakeConnection()
        conn.subscribe_spots = lambda symbol_id: conn.calls.append(("spots", symbol_id))
        ad = CTraderDataAdapter(conn, response_timeout_sec=0.3, server_offset_hours=2)
        assert ad.get_tick_data("BTCUSD") is None

    def test_future_age_symmetric_guard(self):
        """Adapter age guard is symmetric ±tick_max_age_sec: a quote slightly
        ahead of local clock (within tolerance) is served; a quote far in the
        future (clock-skew suspect) is rejected. D44's one-sided negative-age
        tolerance lives in the orchestrator's tick gate, above this bound."""
        conn = FakeConnection()
        ad = CTraderDataAdapter(conn, tick_max_age_sec=10.0, server_offset_hours=2)
        # +5s future: within -max tolerance → served.
        ad._spot_subscribed.add("BTCUSD")
        ad._last_spot["BTCUSD"] = {"bid": 1.0, "ask": 1.1, "time": int(time.time()) + 5}
        tick = ad.get_tick_data("BTCUSD")
        assert tick is not None and tick["bid"] == pytest.approx(1.0)
        # +30s future: beyond -max → rejected (symmetric stale guard).
        ad._last_spot["BTCUSD"] = {"bid": 1.0, "ask": 1.1, "time": int(time.time()) + 30}
        assert ad.get_tick_data("BTCUSD") is None


# ---------------------------------------------------------------------------
# Connection-side request methods (real protobuf construction)
# ---------------------------------------------------------------------------
class TestConnectionRequests:
    def test_request_trendbars_builds_protobuf(self):
        from src.ctrader.connection import CTraderConnection

        cfg = {
            "host": "demo.ctraderapi.com",
            "account_id": "48407657",
            "client_id": "x",
            "client_secret": "y",
        }
        conn = CTraderConnection(cfg)
        deferred = conn.request_trendbars(
            symbol_id=10026, period=1, from_ms=1000, to_ms=2000, count=5
        )
        assert deferred is not None  # client.send stub from Twisted Client

    def test_subscribe_spots_builds_protobuf_with_timestamp(self):
        from src.ctrader.connection import CTraderConnection

        cfg = {
            "host": "demo.ctraderapi.com",
            "account_id": "48407657",
            "client_id": "x",
            "client_secret": "y",
        }
        conn = CTraderConnection(cfg)
        deferred = conn.subscribe_spots(symbol_id=10026)
        assert deferred is not None


# ---------------------------------------------------------------------------
# İŞ-4a S1 (D159) — fail-loud guards + property/method tolerance
# ---------------------------------------------------------------------------
class PropertyStyleConnection(FakeConnection):
    """Fake whose is_connected is a @property (real CTraderConnection shape).

    The adapter must tolerate BOTH shapes: the real connection exposes
    is_connected as a property (bool), while MT5Connection-style fakes
    expose it as a method. The previous strict call
    `self._conn.is_connected()` raised TypeError on a property → the
    adapter ALWAYS reported disconnected with a real connection.
    """

    @property
    def is_connected(self) -> bool:  # type: ignore[override]
        return self._connected


class TestS1FailLoudGuards:
    def test_is_connected_property_shape(self):
        """Real-connection shape: is_connected is a @property → adapter
        must report True (the TypeError bug would return False)."""
        conn = PropertyStyleConnection(connected=True)
        ad = CTraderDataAdapter(conn, server_offset_hours=2)
        assert ad.is_connected() is True

    def test_is_connected_method_shape(self):
        """MT5Connection-style fake: is_connected is a method → still True."""
        conn = FakeConnection(connected=True)
        ad = CTraderDataAdapter(conn, server_offset_hours=2)
        assert ad.is_connected() is True

    def test_is_connected_property_false(self):
        conn = PropertyStyleConnection(connected=False)
        ad = CTraderDataAdapter(conn, server_offset_hours=2)
        assert ad.is_connected() is False

    def test_has_more_true_fails_loud(self):
        """hasMore=True (server chunked the response) → CTraderDataError,
        NOT a truncated silent serve (§19)."""
        conn = FakeConnection()

        def chunked_trendbars(symbol_id, period, from_ms, to_ms, count=None):
            conn.calls.append(("trendbars", {}))
            res = ProtoOAGetTrendbarsRes(make_bars(count or 5))
            res.hasMore = True
            conn.event_queue.put(("MESSAGE", res))

        conn.request_trendbars = chunked_trendbars
        ad = CTraderDataAdapter(conn, server_offset_hours=2)
        with pytest.raises(CTraderDataError, match="trendbars_truncated_response"):
            ad.get_rates("BTCUSD", "M1", 5)

    def test_count_above_single_request_limit_fails_loud(self):
        """count > CTRADER_MAX_SINGLE_REQUEST_BARS → CTraderDataError
        BEFORE the request (clear pre-request reason, no wasted round-trip)."""
        from src.ctrader.data_adapter import CTRADER_MAX_SINGLE_REQUEST_BARS

        conn = FakeConnection()
        ad = CTraderDataAdapter(conn, server_offset_hours=2)
        with pytest.raises(CTraderDataError, match="count_exceeds_single_request_limit"):
            ad.get_rates("BTCUSD", "M1", CTRADER_MAX_SINGLE_REQUEST_BARS + 1)
        # No request was sent.
        assert not [c for c in conn.calls if c[0] == "trendbars"]
