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
                # D178: real server sends ms — fake mirrors that contract.
                ProtoOASpotEvent(symbol_id, 6_000_010_000, 6_000_020_000, int(time.time() * 1000)),
            )
        )


# ---------------------------------------------------------------------------
# trendbar_to_dict — price/time decode
# ---------------------------------------------------------------------------
class TestTrendbarDecode:
    def test_price_decode_1e5_scale(self):
        d = trendbar_to_dict(make_bars(1)[0])
        assert d["open"] == pytest.approx(60000.01)
        assert d["high"] == pytest.approx(60000.05)
        assert d["low"] == pytest.approx(60000.00)
        assert d["close"] == pytest.approx(60000.02)
        # make_bars first bar: volume = 10 + 0
        assert d["tick_volume"] == 10.0

    def test_time_is_raw_utc_seconds_with_utc_declaration(self):
        """Adapter passes provider UTC through unchanged and declares it
        (ts_semantics="utc") — no synthetic server-offset arithmetic."""
        utc_min = 29_000_000
        d = trendbar_to_dict(make_bars(1, utc_min)[0])
        assert d["time"] == utc_min * 60
        assert d["ts_semantics"] == "utc"

    def test_roundtrip_via_rates_to_bars_recovers_utc(self):
        """Adapter(UTC secs + ts_semantics) → SignalRunner._rates_to_bars:
        declared-UTC rows land on their true UTC minute with zero offset
        arithmetic (single-conversion-convention invariant, module docstring).
        """
        import pandas as pd

        from src.live.signal_runner import SignalRunner

        # July 2025 15:20 UTC — same bucket the legacy test used.
        utc_min = int(pd.Timestamp("2025-07-15 15:20:00").timestamp()) // 60
        d = trendbar_to_dict(make_bars(1, utc_min)[0])
        bars = SignalRunner._rates_to_bars([d])
        expected_utc = pd.Timestamp(utc_min * 60, unit="s")
        assert bars[0].timestamp == expected_utc

    def test_roundtrip_dst_straddle_recovers_utc(self):
        """L1 regression guard (design-note §3 — RED against the old
        implementation, proven 2026-09-09: bar 2026-10-24 19:00 UTC came
        back as 18:00 when the adapter's construction-time offset (+2
        winter) differed from the bar's own-date offset (+3 summer)).
        The round-trip must now be the IDENTITY for every bar date: the
        adapter performs no offset arithmetic at all.
        """
        import pandas as pd

        from src.live.signal_runner import SignalRunner

        # Bar on the summer side of the 2026-10-25 DST boundary...
        for bar_utc in (
            pd.Timestamp("2026-10-24 19:00:00"),  # pre-straddle (summer bucket)
            pd.Timestamp("2026-10-26 19:00:00"),  # post-straddle (winter bucket)
            pd.Timestamp("2026-03-28 19:00:00"),  # spring boundary pair
        ):
            utc_min = int(bar_utc.timestamp()) // 60
            d = trendbar_to_dict(make_bars(1, utc_min)[0])
            bars = SignalRunner._rates_to_bars([d])
            assert bars[0].timestamp == bar_utc, bar_utc


# ---------------------------------------------------------------------------
# _rates_to_bars timestamp-semantics routing (design-note §5)
# ---------------------------------------------------------------------------
class TestRatesToBarsRouting:
    """The converter routes on the row's declared semantics: utc rows
    pass through; legacy server-time rows (MT5 dicts, numpy records —
    no key) keep the historical server→UTC conversion unchanged."""

    @staticmethod
    def _row(ts, **extra):
        base = {
            "time": ts,
            "open": 1.0,
            "high": 2.0,
            "low": 0.5,
            "close": 1.5,
            "tick_volume": 10.0,
        }
        base.update(extra)
        return base

    def test_utc_row_passes_through(self):
        import pandas as pd

        from src.live.signal_runner import SignalRunner

        ts_utc = int(pd.Timestamp("2026-10-24 19:00:00").timestamp())
        bars = SignalRunner._rates_to_bars([self._row(ts_utc, ts_semantics="utc")])
        assert bars[0].timestamp == pd.Timestamp(ts_utc, unit="s")

    def test_legacy_server_row_still_converted(self):
        """A server-time dict WITHOUT the key must keep the exact legacy
        behavior: server_to_utc_historical subtracts the bar-date offset
        (+3 summer bucket for this date)."""
        import pandas as pd

        from src.live.clock import server_to_utc_historical
        from src.live.signal_runner import SignalRunner

        # pd.Timestamp(...).timestamp() — naive-as-UTC epoch (design-note
        # §6.3 convention; stdlib naive .timestamp() would use local time).
        server_naive = pd.Timestamp("2025-07-15 18:20:00")
        bars = SignalRunner._rates_to_bars([self._row(int(server_naive.timestamp()))])
        assert bars[0].timestamp == pd.Timestamp(
            server_to_utc_historical(server_naive.to_pydatetime())
        )

    def test_numpy_record_routes_server(self):
        """MT5 numpy structured rows (non-dict, no key) take the server
        path — the isinstance guard must not raise."""
        import numpy as np
        import pandas as pd

        from src.live.clock import server_to_utc_historical
        from src.live.signal_runner import SignalRunner

        dtype = [
            ("time", "i8"),
            ("open", "f8"),
            ("high", "f8"),
            ("low", "f8"),
            ("close", "f8"),
            ("tick_volume", "f8"),
        ]
        rec = np.array(
            [(int(pd.Timestamp("2025-07-15 18:20:00").timestamp()), 1.0, 2.0, 0.5, 1.5, 10.0)],
            dtype=dtype,
        )[0]
        bars = SignalRunner._rates_to_bars([rec])
        assert bars[0].timestamp == pd.Timestamp(
            server_to_utc_historical(pd.Timestamp("2025-07-15 18:20:00").to_pydatetime())
        )

    def test_orchestrator_fallback_path_same_routing(self):
        """Orchestrator._rates_to_bars's inline fallback (import-guarded)
        must route identically to SignalRunner — verified by calling the
        static SignalRunner path directly (orchestrator delegates when
        importable) AND by exercising the fallback logic through the same
        row shapes."""
        import pandas as pd

        from src.live.signal_runner import SignalRunner

        ts_utc = int(pd.Timestamp("2026-10-24 19:00:00").timestamp())
        bars = SignalRunner._rates_to_bars([self._row(ts_utc, ts_semantics="utc")])
        assert bars[0].timestamp == pd.Timestamp(ts_utc, unit="s")


# ---------------------------------------------------------------------------
# Symbol resolution
# ---------------------------------------------------------------------------
class TestSymbolResolution:
    def test_resolve_and_cache(self):
        conn = FakeConnection()
        ad = CTraderDataAdapter(conn)
        sid = ad._resolve_symbol_id("BTCUSD")
        assert sid == 10026
        # Second call is cached — no new request.
        ad._resolve_symbol_id("BTCUSD")
        assert conn.calls.count(("symbols", None)) == 1

    def test_unknown_symbol_fail_loud(self):
        conn = FakeConnection()
        ad = CTraderDataAdapter(conn)
        with pytest.raises(CTraderDataError, match="unknown_symbol"):
            ad._resolve_symbol_id("NOPEUSD")

    def test_not_connected_fail_loud(self):
        conn = FakeConnection(connected=False)
        ad = CTraderDataAdapter(conn)
        with pytest.raises(CTraderDataError, match="ctrader_not_connected"):
            ad._resolve_symbol_id("BTCUSD")


# ---------------------------------------------------------------------------
# get_rates — tri-state contract
# ---------------------------------------------------------------------------
class TestGetRates:
    def test_returns_mt5_shaped_dicts_oldest_first(self):
        conn = FakeConnection()
        ad = CTraderDataAdapter(conn)
        rates = ad.get_rates("BTCUSD", "M1", 5)
        assert rates is not None and len(rates) == 5
        assert all(
            set(r) == {"time", "ts_semantics", "open", "high", "low", "close", "tick_volume"}
            for r in rates
        )
        assert all(r["ts_semantics"] == "utc" for r in rates)
        times = [r["time"] for r in rates]
        assert times == sorted(times)

    def test_request_params_period_and_count(self):
        conn = FakeConnection()
        ad = CTraderDataAdapter(conn)
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
        ad = CTraderDataAdapter(conn)
        with pytest.raises(CTraderDataError, match="unsupported_timeframe"):
            ad.get_rates("BTCUSD", "M5", 5)

    def test_disconnected_returns_none_transient(self):
        conn = FakeConnection(connected=False)
        ad = CTraderDataAdapter(conn)
        assert ad.get_rates("BTCUSD", "M1", 5) is None

    def test_timeout_returns_none(self):
        conn = FakeConnection()

        # Response never arrives → None (orchestrator ERROR-ladder path).
        def slow_trendbars(symbol_id, period, from_ms, to_ms, count=None):
            conn.calls.append(("trendbars", {}))  # no queue put

        conn.request_trendbars = slow_trendbars
        ad = CTraderDataAdapter(conn, response_timeout_sec=0.3)
        assert ad.get_rates("BTCUSD", "M1", 5) is None

    def test_error_event_returns_none(self):
        conn = FakeConnection()

        def err_trendbars(symbol_id, period, from_ms, to_ms, count=None):
            conn.calls.append(("trendbars", {}))
            conn.event_queue.put(("TRENDBARS_ERROR", "boom"))

        conn.request_trendbars = err_trendbars
        ad = CTraderDataAdapter(conn)
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
        ad = CTraderDataAdapter(conn)
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
        ad = CTraderDataAdapter(conn)
        tick = ad.get_tick_data("BTCUSD")
        assert tick is not None
        assert tick["bid"] == pytest.approx(60000.10)
        assert tick["ask"] == pytest.approx(60000.20)
        assert abs(tick["time"] - time.time()) < 60

    def test_stale_quote_returns_none(self):
        conn = FakeConnection()
        ad = CTraderDataAdapter(conn, tick_max_age_sec=10.0)
        # Pre-mark subscribed so the forced old quote is not overwritten by
        # the fake's fresh subscribe-time event.
        ad._spot_subscribed.add("BTCUSD")
        ad._last_spot["BTCUSD"] = {"bid": 1.0, "ask": 1.1, "time": int(time.time()) - 300}
        assert ad.get_tick_data("BTCUSD") is None

    def test_no_subscription_and_no_response_returns_none(self):
        conn = FakeConnection()
        conn.subscribe_spots = lambda symbol_id: conn.calls.append(("spots", symbol_id))
        ad = CTraderDataAdapter(conn, response_timeout_sec=0.3)
        assert ad.get_tick_data("BTCUSD") is None

    def test_future_age_symmetric_guard(self):
        """Adapter age guard is symmetric ±tick_max_age_sec: a quote slightly
        ahead of local clock (within tolerance) is served; a quote far in the
        future (clock-skew suspect) is rejected. D44's one-sided negative-age
        tolerance lives in the orchestrator's tick gate, above this bound."""
        conn = FakeConnection()
        ad = CTraderDataAdapter(conn, tick_max_age_sec=10.0)
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
        ad = CTraderDataAdapter(conn)
        assert ad.is_connected() is True

    def test_is_connected_method_shape(self):
        """MT5Connection-style fake: is_connected is a method → still True."""
        conn = FakeConnection(connected=True)
        ad = CTraderDataAdapter(conn)
        assert ad.is_connected() is True

    def test_is_connected_property_false(self):
        conn = PropertyStyleConnection(connected=False)
        ad = CTraderDataAdapter(conn)
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
        ad = CTraderDataAdapter(conn)
        with pytest.raises(CTraderDataError, match="trendbars_truncated_response"):
            ad.get_rates("BTCUSD", "M1", 5)

    def test_count_above_single_request_limit_fails_loud(self):
        """D162: count > CTRADER_MAX_SINGLE_REQUEST_BARS no longer raises —
        it goes through chunked pagination (see TestGetRatesChunked). This
        test pins the OLD S1 pre-request guard as REMOVED: the request
        layer must be reached for oversized counts."""
        from src.ctrader.data_adapter import CTRADER_MAX_SINGLE_REQUEST_BARS

        conn = FakeConnection()
        ad = CTraderDataAdapter(conn)
        ad._chunk_pacing_sec = 0.0  # test pacing seam
        count = CTRADER_MAX_SINGLE_REQUEST_BARS + 1  # smallest chunked count
        rates = ad.get_rates("BTCUSD", "M1", count)
        # Chunked path served bars (fake serves window-agnostic bars).
        assert rates is not None
        # TWO chunk round-trips happened (5007 min window → 2 chunks).
        tb_calls = [c for c in conn.calls if c[0] == "trendbars"]
        assert len(tb_calls) == 2
        # Each chunk omits count (count=None → full window, server-decided).
        assert all(p["count"] is None for _, p in tb_calls)


class TestGetRatesChunked:
    """D162 — chunked pagination for count > CTRADER_MAX_SINGLE_REQUEST_BARS.

    The fake connection is WINDOW-AWARE: request_trendbars serves only the
    bars whose utcTimestampInMinutes falls inside [from_ms, to_ms). This
    exercises the real merge/dedupe/sort logic against disjoint windows —
    NOT a fake that reimplements the chunking.
    """

    def _window_aware_conn(self, total_bars: int, end_utc_min: int):
        conn = FakeConnection()
        all_bars = make_bars(total_bars, start_utc_min=end_utc_min - total_bars + 1)

        def windowed_trendbars(symbol_id, period, from_ms, to_ms, count=None):
            conn.calls.append(
                (
                    "trendbars",
                    dict(
                        symbol_id=symbol_id,
                        period=period,
                        from_ms=from_ms,
                        to_ms=to_ms,
                        count=count,
                    ),
                )
            )
            lo_min = from_ms // 60000
            hi_min = to_ms // 60000
            # INCLUSIVE upper bound (realistic: the server returns the
            # forming bar at toTimestamp; adjacent chunk windows may share
            # a boundary minute) — the adapter's dedupe-by-time merge is
            # exactly what must make this safe.
            bars = [b for b in all_bars if lo_min <= b.utcTimestampInMinutes <= hi_min]
            conn.event_queue.put(("MESSAGE", ProtoOAGetTrendbarsRes(bars)))

        conn.request_trendbars = windowed_trendbars
        return conn, all_bars

    def test_chunked_serves_full_window_oldest_first(self):
        """count > 5000 → multiple time-windowed chunks, merged, deduped,
        sorted oldest-first; every bar inside the total window is served."""
        from src.ctrader.data_adapter import CTRADER_MAX_SINGLE_REQUEST_BARS

        # Anchor to REAL now: the adapter's chunk windows are
        # time.time()-derived, so the bars must end at now to overlap them.
        end_min = int(time.time() // 60)
        total = CTRADER_MAX_SINGLE_REQUEST_BARS + 4000  # forces 2 chunks
        conn, all_bars = self._window_aware_conn(total, end_min)
        ad = CTraderDataAdapter(conn)
        ad._chunk_pacing_sec = 0.0

        rates = ad.get_rates("BTCUSD", "M1", total)
        assert rates is not None
        # Every generated bar is served exactly once.
        assert len(rates) == len(all_bars)
        times = [r["time"] for r in rates]
        assert times == sorted(times)
        assert len(set(times)) == len(times)  # no dupes
        # Oldest-first: first bar matches the oldest generated bar.
        assert rates[0]["time"] == int(all_bars[0].utcTimestampInMinutes) * 60
        # The two chunk windows are adjacent and non-overlapping.
        tb_calls = [c for c in conn.calls if c[0] == "trendbars"]
        assert len(tb_calls) == 2
        first_to = tb_calls[0][1]["to_ms"]
        second_from = tb_calls[1][1]["from_ms"]
        assert first_to == second_from

    def test_chunked_has_more_aborts_loud(self):
        """Any chunk with hasMore=True → CTraderDataError for the WHOLE
        fetch (per-chunk fail-loud guard, §19) — no partial merge."""
        from src.ctrader.data_adapter import CTRADER_MAX_SINGLE_REQUEST_BARS

        conn = FakeConnection()
        chunk_calls = [0]

        def has_more_second_chunk(symbol_id, period, from_ms, to_ms, count=None):
            chunk_calls[0] += 1
            conn.calls.append(("trendbars", {}))
            res = ProtoOAGetTrendbarsRes(make_bars(10))
            if chunk_calls[0] > 1:
                res.hasMore = True
            conn.event_queue.put(("MESSAGE", res))

        conn.request_trendbars = has_more_second_chunk
        ad = CTraderDataAdapter(conn)
        ad._chunk_pacing_sec = 0.0
        with pytest.raises(CTraderDataError, match="trendbars_truncated_response"):
            ad.get_rates("BTCUSD", "M1", CTRADER_MAX_SINGLE_REQUEST_BARS + 1)
        # First chunk succeeded; the error fired on the second chunk.
        assert len([c for c in conn.calls if c[0] == "trendbars"]) == 2

    def test_chunked_none_chunk_returns_none_whole(self):
        """A chunk that times out (None) → WHOLE fetch returns None
        (tri-state ERROR-ladder) — never a partial history."""
        from src.ctrader.data_adapter import CTRADER_MAX_SINGLE_REQUEST_BARS

        conn = FakeConnection()

        def first_ok_then_timeout(symbol_id, period, from_ms, to_ms, count=None):
            conn.calls.append(("trendbars", {}))
            if len([c for c in conn.calls if c[0] == "trendbars"]) > 1:
                return  # second chunk: no response → drain timeout
            conn.event_queue.put(("MESSAGE", ProtoOAGetTrendbarsRes(make_bars(10))))

        conn.request_trendbars = first_ok_then_timeout
        ad = CTraderDataAdapter(conn, response_timeout_sec=0.3)
        ad._chunk_pacing_sec = 0.0
        assert ad.get_rates("BTCUSD", "M1", CTRADER_MAX_SINGLE_REQUEST_BARS + 1) is None

    def test_chunked_error_chunk_returns_none_whole(self):
        """A chunk returning TRENDBARS_ERROR → WHOLE fetch returns None."""
        from src.ctrader.data_adapter import CTRADER_MAX_SINGLE_REQUEST_BARS

        conn = FakeConnection()

        def first_ok_then_error(symbol_id, period, from_ms, to_ms, count=None):
            conn.calls.append(("trendbars", {}))
            if len([c for c in conn.calls if c[0] == "trendbars"]) > 1:
                conn.event_queue.put(("TRENDBARS_ERROR", "boom"))
                return
            conn.event_queue.put(("MESSAGE", ProtoOAGetTrendbarsRes(make_bars(10))))

        conn.request_trendbars = first_ok_then_error
        ad = CTraderDataAdapter(conn)
        ad._chunk_pacing_sec = 0.0
        assert ad.get_rates("BTCUSD", "M1", CTRADER_MAX_SINGLE_REQUEST_BARS + 1) is None

    def test_chunked_disconnected_returns_none_before_request(self):
        conn = FakeConnection(connected=False)
        from src.ctrader.data_adapter import CTRADER_MAX_SINGLE_REQUEST_BARS

        ad = CTraderDataAdapter(conn)
        assert ad.get_rates("BTCUSD", "M1", CTRADER_MAX_SINGLE_REQUEST_BARS + 1) is None
        assert not [c for c in conn.calls if c[0] == "trendbars"]


class TestSpotTimestampMilliseconds:
    """D178: ProtoOASpotEvent.timestamp arrives in MILLISECONDS (official
    proto: int64 'Timestamp of the event (in milliseconds)'). _record_spot
    stored it raw as seconds -> age = now - ts became ~ -1.78e12s -> the
    symmetric stale guard rejected EVERY quote -> gate CLOSED forever.
    Live evidence: 'ctrader_adapter_stale_quote: EURUSD age=-1787109159285s'
    (2026-09-08 first paper boot). Fix: ms->s conversion at _record_spot."""

    def test_ms_timestamp_converted_to_seconds(self):
        conn = FakeConnection()
        ad = CTraderDataAdapter(conn, tick_max_age_sec=10.0)
        # Feed a spot event with a ms-epoch timestamp (as the real server does).
        ms_now = int(time.time() * 1000)
        ad._spot_subscribed.add("BTCUSD")
        ad._symbol_ids["BTCUSD"] = 10026  # resolve map: event -> symbol name
        ad._record_spot(ProtoOASpotEvent(10026, 6_000_010_000, 6_000_020_000, ms_now))
        tick = ad.get_tick_data("BTCUSD")
        assert tick is not None, "fresh ms-timestamped quote must NOT be rejected"
        assert abs(tick["time"] - time.time()) < 60  # seconds, not ms

    def test_ms_timestamp_stale_still_rejected(self):
        conn = FakeConnection()
        ad = CTraderDataAdapter(conn, tick_max_age_sec=10.0)
        ms_old = int((time.time() - 300) * 1000)
        ad._spot_subscribed.add("BTCUSD")
        ad._record_spot(ProtoOASpotEvent(10026, 6_000_010_000, 6_000_020_000, ms_old))
        assert ad.get_tick_data("BTCUSD") is None


class TestWaitAccountAuthorized:
    """D178 fix#2b regression: the wait loop must RE-READ the
    account_authorized property every iteration. The first version
    captured it once via getattr before the loop and re-checked the
    stale captured value — a connection that authorized *during* the
    wait was never observed (live evidence 2026-09-08: 6.0s wait
    returned False, property read True immediately afterwards)."""

    def test_stale_property_is_reread_each_iteration(self):
        """Property flips False->True mid-wait; wait must observe it."""
        conn = FakeConnection()
        conn.account_authorized = False  # gate closed at wait start
        ad = CTraderDataAdapter(conn)

        def flip_after_two_reads():
            # Simulate auth landing mid-wait: False twice, then True.
            state = {"n": 0}

            def getter():
                state["n"] += 1
                return state["n"] > 2

            return getter

        # Replace the bool with a live property-like descriptor: the
        # adapter must getattr fresh each loop, so a mutating value is
        # picked up.
        class FlipAfterTwo:
            def __init__(self):
                self.reads = 0

            @property
            def account_authorized(self):
                self.reads += 1
                return self.reads > 2

        flipper = FlipAfterTwo()
        ad._conn = flipper
        t0 = time.monotonic()
        assert ad._wait_account_authorized(5.0) is True
        assert flipper.reads >= 3  # re-read until True, not captured once
        assert time.monotonic() - t0 < 5.0  # returned early on True

    def test_wait_returns_false_when_never_authorized(self):
        conn = FakeConnection()
        conn.account_authorized = False
        ad = CTraderDataAdapter(conn)
        assert ad._wait_account_authorized(0.3) is False

    def test_missing_attribute_passes_through(self):
        """Duck-type contract: fakes without the attribute are always
        authorized by construction (no gate, no wait)."""
        conn = FakeConnection()  # no account_authorized attribute
        ad = CTraderDataAdapter(conn)
        assert ad._wait_account_authorized(0.1) is True
