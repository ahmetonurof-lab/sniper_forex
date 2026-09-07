#!/usr/bin/env python
"""cTrader data adapter — İş-4a (D155): MT5-shaped data surface on CTraderConnection.

Purpose: bridge `CTraderConnection` (read-only connection layer, D126 Adım A.2)
into the orchestrator's canonical fetch contract
(`get_rates(symbol, timeframe, count)` / `get_tick_data(symbol)`), so that
`Orchestrator._fetch_m1_tri_state` and `_get_spread_state` can consume cTrader
market data WITHOUT a parallel conversion mechanism (AGENTS.md §2.2 — reuse
existing SignalRunner._rates_to_bars / orchestrator conversion, don't invent one).

Official-message evidence (docs/ctrader_openapi_official_research.md + live docs
help.ctrader.com/open-api/messages/, D155 verification):

- ProtoOAGetTrendbarsReq: ctidTraderAccountId, fromTimestamp(ms), toTimestamp(ms),
  period (ProtoOATrendbarPeriod.M1 == 1), symbolId, count (bars back from
  toTimestamp). Rate limit: 5 historical req/s per connection.
- ProtoOATrendbar fields: volume, period, low, deltaOpen, deltaClose, deltaHigh,
  utcTimestampInMinutes. Prices are encoded as `low` in 1/100000 of a price unit
  plus deltas relative to `low` (SpotEvent docs use the same 1/100000 convention).
- ProtoOASpotEvent: symbolId, bid, ask (1/100000), timestamp (optional — requires
  subscribeToSpotTimestamp=TRUE on ProtoOASubscribeSpotsReq). First event after
  subscribe carries the latest spot price even if market is closed.

TIME SEMANTICS (AGENTS.md §6.3 — single canonical convention):

  cTrader trendbar timestamps are UTC epoch minutes. The canonical live ingest
  (SignalRunner._rates_to_bars, D15) converts naive MT5 **server time** to UTC via
  clock.server_to_utc_historical(). To feed the SAME canonical converter, this
  adapter re-expresses UTC minutes as MT5-server-time seconds using the SAME
  DST-heuristic offset (clock.server_utc_offset), so the runner's conversion
  subtracts exactly what this adapter added. Net result: UTC timestamps, one
  conversion convention, zero parallel converters.

Output shape: list of dicts with keys
  {"time": int epoch seconds (server-time, see above), "open", "high", "low",
   "close", "tick_volume"} — exactly the dict-access path consumed by
  SignalRunner._rates_to_bars / Orchestrator._rates_to_bars (r["time"], r["open"], ...).

Symbol resolution: name ("BTCUSD") → cTrader symbolId via
CTraderConnection.request_symbols_list() (ProtoOASymbolsListReq/Res), cached.
Fail-loud (AGENTS.md §19): unknown symbol, missing response, or auth errors raise
CTraderDataError — no silent fallback, no synthetic data.

This module performs NO network calls of its own: it only enqueues requests via
the existing connection and drains the existing event_queue. All threading stays
inside CTraderConnection (reactor worker thread + callFromThread bridge).
"""

import logging
import queue
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from src.live.clock import server_utc_offset

logger = logging.getLogger(__name__)

# cTrader price encoding: prices are specified in 1/100000 of a price unit
# (official docs: "123000 in protocol means 1.23").
CTRADER_PRICE_SCALE = 100000.0

# Trendbar period: M1 == 1 (ProtoOATrendbarPeriod).
CTRADER_PERIOD_M1 = 1

# How long a synchronous data request may wait on the event_queue for its
# matching response before failing loud. Historical-data rate limit is 5 req/s;
# server round-trip is typically well under 2 s (D142 live evidence: auth +
# symbols round-trips completed inside REQUEST_TIMEOUT_SEC=5.0).
DEFAULT_RESPONSE_TIMEOUT_SEC = 10.0

# ProtoOASpotEvent freshness window for get_tick_data: a spot quote older than
# this is reported (not silently served as fresh). The orchestrator's own
# tick_stale_sec gate performs the authoritative staleness decision (D44);
# this bound only prevents serving arbitrarily old first-subscribe quotes as
# "current" when the market has been closed for days.
DEFAULT_TICK_MAX_AGE_SEC = 300.0

# S1 (İş-4a): single-request trendbar ceiling. The official docs do not
# publish a numeric chunkSize for ProtoOAGetTrendbarsRes; the response
# carries `hasMore` which signals truncation. We conservatively cap the
# single-request count so the fail-loud hasMore guard (below) is the
# authoritative protection and callers get a clear pre-request error for
# oversized counts. 65k warmup via cTrader requires chunked pagination —
# a follow-up work item, explicitly NOT silently approximated.
CTRADER_MAX_SINGLE_REQUEST_BARS = 5000


class CTraderDataError(RuntimeError):
    """Fail-loud adapter error (AGENTS.md §19): no silent fallbacks."""


def trendbar_to_dict(tb: Any, server_offset_hours: int) -> Dict[str, Any]:
    """Convert a ProtoOATrendbar to the MT5-shaped dict contract.

    Price decode (official convention): low is 1/100000-scaled absolute low;
    open/high/close are low + respective delta, all 1/100000-scaled.
    Time: utcTimestampInMinutes (UTC epoch minutes) re-expressed as MT5
    server-time epoch seconds so SignalRunner._rates_to_bars's
    server_to_utc_historical() conversion restores true UTC.
    """
    low = float(tb.low)
    o = (low + float(tb.deltaOpen)) / CTRADER_PRICE_SCALE
    h = (low + float(tb.deltaHigh)) / CTRADER_PRICE_SCALE
    lo = low / CTRADER_PRICE_SCALE
    c = (low + float(tb.deltaClose)) / CTRADER_PRICE_SCALE
    # UTC epoch minutes → UTC seconds → MT5 server-time seconds.
    ts_server = int(tb.utcTimestampInMinutes) * 60 + server_offset_hours * 3600
    return {
        "time": ts_server,
        "open": o,
        "high": h,
        "low": lo,
        "close": c,
        "tick_volume": float(tb.volume),
    }


class CTraderDataAdapter:
    """MT5-shaped data facade over CTraderConnection (read-only).

    Exposes the orchestrator's fetch contract:
      - get_rates(symbol, timeframe="M1", count) -> List[dict] | None
      - get_tick_data(symbol) -> {"bid","ask","time"} | None
    plus is_connected() mirroring the underlying connection state.

    Request/response correlation runs on the connection's event_queue: each
    synchronous call sends its protobuf via callFromThread, then drains queue
    events until the matching response arrives or the timeout elapses.
    """

    def __init__(
        self,
        connection: Any,
        response_timeout_sec: float = DEFAULT_RESPONSE_TIMEOUT_SEC,
        tick_max_age_sec: float = DEFAULT_TICK_MAX_AGE_SEC,
        server_offset_hours: Optional[int] = None,
    ) -> None:
        self._conn = connection
        self._timeout = float(response_timeout_sec)
        self._tick_max_age = float(tick_max_age_sec)
        # Single canonical DST offset (clock.py) — resolved once per adapter
        # lifetime; a live session has one offset at any moment.
        self._server_offset = (
            int(server_offset_hours) if server_offset_hours is not None else server_utc_offset()
        )
        # name -> symbolId cache, populated from ProtoOASymbolsListRes.
        self._symbol_ids: Dict[str, int] = {}
        self._symbols_resolved = False
        # Latest spot quote per symbol name (from ProtoOASpotEvent drain).
        self._last_spot: Dict[str, Dict[str, Any]] = {}
        # Spot subscription requested (once per symbol).
        self._spot_subscribed: set = set()
        # Serialize synchronous request/response cycles (single consumer
        # discipline on the shared event_queue).
        self._req_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Connection surface used by Orchestrator wiring
    # ------------------------------------------------------------------
    @property
    def config(self) -> Dict[str, Any]:
        """Account-identity config (S2 audit: login/server in cTrader mode).

        İŞ-4a D159: single source of truth is the underlying connection's
        own validated config dict (CTraderConnection stores the
        get_ctrader_config() result). The adapter only DELEGATES — it
        never duplicates credentials (§2.2). A connection without a
        config attribute yields {} (beyanlı: orchestrator fills explicit
        zeros; no silent credential invention).
        """
        cfg = getattr(self._conn, "config", None)
        return cfg if isinstance(cfg, dict) else {}

    def is_connected(self) -> bool:
        """True when the underlying cTrader connection is established.

        İŞ-4a S1 (D159) property/method tolerance: CTraderConnection
        exposes `is_connected` as a @property (returns bool); some fakes
        (and the MT5Connection convention) expose it as a method. Calling
        a bool as a function raises TypeError → the previous strict
        `self._conn.is_connected()` would have ALWAYS returned False with
        a real connection (S1 boot would FATAL spuriously). We accept
        both shapes explicitly — this is shape normalization, NOT a
        silent fallback: a genuinely broken connection still returns
        False through the same except path.
        """
        try:
            val = self._conn.is_connected
            if callable(val):
                return bool(val())
            return bool(val)
        except Exception:
            return False

    def ensure_connected(self, max_attempts: int = 1) -> bool:
        """Orchestrator-side liveness check. Reconnection is owned by the
        connection layer's ClientService reconnect policy; here we only
        report state and (best-effort) wait briefly for it."""
        if self.is_connected():
            return True
        deadline = time.monotonic() + min(max_attempts, 5) * 2.0
        while time.monotonic() < deadline:
            if self.is_connected():
                return True
            time.sleep(0.2)
        return self.is_connected()

    def stop(self) -> None:
        """Teardown delegation (İŞ-4a D159): Orchestrator.shutdown() calls
        conn.stop() via duck-typing (hasattr 'stop') in cTrader mode. The
        adapter is the injected connection object, so it must surface the
        stop surface; ownership of the reactor teardown remains with
        CTraderConnection.stop() (§2.2 — no duplicate teardown logic).
        Missing stop on the underlying connection is tolerated (nothing
        to stop — e.g. already-torn-down fake) WITHOUT hiding a real
        failure: anything other than AttributeError propagates."""
        stop_fn = getattr(self._conn, "stop", None)
        if stop_fn is None:
            return
        stop_fn()

    # ------------------------------------------------------------------
    # Event-queue plumbing
    # ------------------------------------------------------------------
    def _drain_until(
        self,
        match_fn,
        timeout_sec: float,
    ) -> Tuple[Optional[Any], List[Any]]:
        """Drain event_queue until match_fn(kind, payload) returns True.

        Returns (payload, leftovers) where leftovers are re-queued side
        events (auth/heartbeat/other messages) so nothing is lost.
        Raises CTraderDataError on fatal queue events (AUTH_ERROR,
        PARSE_ERROR are tolerated as side events and returned as errors).
        """
        leftovers: List[Any] = []
        deadline = time.monotonic() + timeout_sec
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                kind, payload = self._conn.event_queue.get(timeout=remaining)
            except queue.Empty:
                break
            if match_fn(kind, payload):
                return payload, leftovers
            leftovers.append((kind, payload))
        return None, leftovers

    def _requeue(self, leftovers: List[Any]) -> None:
        for kind, payload in leftovers:
            self._conn.event_queue.put((kind, payload))

    # ------------------------------------------------------------------
    # Symbol resolution
    # ------------------------------------------------------------------
    def _resolve_symbol_id(self, symbol: str) -> int:
        """Resolve a symbol name to a cTrader symbolId (cached). Fail-loud."""
        cached = self._symbol_ids.get(symbol)
        if cached is not None:
            return cached
        if not self.is_connected():
            raise CTraderDataError(f"ctrader_not_connected: cannot resolve symbol {symbol}")
        with self._req_lock:
            # Re-check under lock (another thread may have resolved).
            cached = self._symbol_ids.get(symbol)
            if cached is not None:
                return cached
            try:
                self._conn.request_symbols_list()
            except Exception as exc:
                raise CTraderDataError(
                    f"symbols_request_failed: {type(exc).__name__}: {exc}"
                ) from exc
            res, leftovers = self._drain_until(
                lambda kind, payload: (
                    kind in ("MESSAGE", "SYMBOLS_ERROR", "PARSE_ERROR")
                    and (
                        (
                            kind == "MESSAGE"
                            and payload is not None
                            and type(payload).__name__ == "ProtoOASymbolsListRes"
                        )
                        or kind in ("SYMBOLS_ERROR", "PARSE_ERROR")
                    )
                ),
                self._timeout,
            )
            self._requeue(leftovers)
            if res is None:
                raise CTraderDataError(f"symbols_response_timeout: {symbol}")
            if type(res).__name__ != "ProtoOASymbolsListRes":
                raise CTraderDataError(f"symbols_error: {res}")
            for light in res.symbol:
                name = str(getattr(light, "symbolName", ""))
                if name:
                    self._symbol_ids[name] = int(light.symbolId)
        resolved = self._symbol_ids.get(symbol)
        if resolved is None:
            raise CTraderDataError(f"unknown_symbol: {symbol}")
        self._symbols_resolved = True
        return resolved

    # ------------------------------------------------------------------
    # get_rates — orchestrator fetch contract (M1 trendbars)
    # ------------------------------------------------------------------
    def get_rates(
        self,
        symbol: str,
        timeframe: str = "M1",
        count: int = 10,
    ) -> Optional[List[Dict[str, Any]]]:
        """Fetch M1 trendbars, MT5-shaped dict list (see module docstring).

        Mirrors MT5Connection.get_rates semantics the orchestrator expects:
          - None            → transient/transport failure (ERROR-ladder path)
          - []              → request succeeded, zero bars (empty-data path)
          - List[dict]      → bars, oldest-first, keyed time/open/high/low/
                              close/tick_volume
        Only M1 is supported (canonical live ingest timeframe); anything else
        raises fail-loud (AGENTS.md §19).
        """
        if timeframe != "M1":
            raise CTraderDataError(f"unsupported_timeframe: {timeframe} (only M1)")
        if count <= 0:
            raise CTraderDataError(f"invalid_count: {count}")
        if not self.is_connected():
            # Transient transport state → tri-state None (ERROR-ladder path),
            # consistent with the disconnected re-check inside the lock below.
            # Fail-loud is reserved for permanent misconfiguration (unknown
            # symbol, unsupported timeframe) — not for connection state.
            logger.warning("ctrader_adapter_get_rates_not_connected")
            return None
        if count > CTRADER_MAX_SINGLE_REQUEST_BARS:
            # S1 (İş-4a): fail-loud BEFORE the request — a count above the
            # documented chunkSize ceiling would come back hasMore=True and
            # be rejected anyway; rejecting here gives the caller a clear
            # reason instead of a wasted round-trip (AGENTS.md §19).
            raise CTraderDataError(
                f"count_exceeds_single_request_limit: {count} > "
                f"{CTRADER_MAX_SINGLE_REQUEST_BARS} — chunked pagination "
                "not implemented (S1 fail-loud guard)"
            )

        symbol_id = self._resolve_symbol_id(symbol)

        with self._req_lock:
            if not self.is_connected():
                logger.warning("ctrader_adapter_get_rates_not_connected")
                return None
            now_ms = int(time.time() * 1000)
            # 65k-bar warmup requests reach back ~45 days; request a window
            # slightly larger than count so the newest bucket completes.
            from_ms = now_ms - int((count + 2) * 60) * 1000
            try:
                self._conn.request_trendbars(
                    symbol_id=symbol_id,
                    period=CTRADER_PERIOD_M1,
                    from_ms=from_ms,
                    to_ms=now_ms,
                    count=count,
                )
            except AttributeError:
                raise CTraderDataError(
                    "connection_missing_request_trendbars: CTraderConnection "
                    "must expose request_trendbars (İş-4a extension)"
                )
            except Exception as exc:
                logger.warning("ctrader_adapter_trendbars_request_failed: %s", exc)
                return None

            res, leftovers = self._drain_until(
                lambda kind, payload: (
                    kind in ("MESSAGE", "TRENDBARS_ERROR", "PARSE_ERROR")
                    and (
                        (
                            kind == "MESSAGE"
                            and payload is not None
                            and type(payload).__name__ == "ProtoOAGetTrendbarsRes"
                        )
                        or kind in ("TRENDBARS_ERROR", "PARSE_ERROR")
                    )
                ),
                self._timeout,
            )
            self._requeue(leftovers)

        if res is None:
            logger.warning("ctrader_adapter_trendbars_timeout: %s", symbol)
            return None
        if type(res).__name__ != "ProtoOAGetTrendbarsRes":
            logger.warning("ctrader_adapter_trendbars_error: %s", res)
            return None
        # S1 (İş-4a) fail-loud guard (AGENTS.md §19): hasMore=TRUE means the
        # server chunked the response (official docs: "If TRUE then the
        # number of records by filter is larger than chunkSize"). Serving a
        # TRUNCATED history would silently corrupt warmup/replay state.
        # Large warmup counts (65k single request) are therefore REJECTED
        # loudly instead of being served partially — chunked pagination is
        # a follow-up work item, NOT a silent path.
        if bool(getattr(res, "hasMore", False)):
            raise CTraderDataError(
                f"trendbars_truncated_response: {symbol} count={count} "
                "hasMore=True — server chunked the response; single-request "
                "fetch would silently drop history (S1 fail-loud guard)"
            )

        bars = [trendbar_to_dict(tb, self._server_offset) for tb in res.trendbar]
        # Server returns bars ascending by time; canonical consumer expects
        # oldest-first ordering (is_closed_m1 + resample_15m assumptions).
        bars.sort(key=lambda b: b["time"])
        return bars

    # ------------------------------------------------------------------
    # get_tick_data — orchestrator spread-state contract
    # ------------------------------------------------------------------
    def subscribe_spots(self, symbol: str) -> None:
        """Subscribe to spot events for `symbol` (idempotent per symbol).

        The first ProtoOASpotEvent after subscription carries the latest
        spot price even if the market is closed (official docs) — that is
        what makes get_tick_data work without a push-loop consumer.
        """
        if symbol in self._spot_subscribed:
            return
        symbol_id = self._resolve_symbol_id(symbol)
        with self._req_lock:
            try:
                self._conn.subscribe_spots(symbol_id=symbol_id)
            except AttributeError:
                raise CTraderDataError(
                    "connection_missing_subscribe_spots: CTraderConnection "
                    "must expose subscribe_spots (İş-4a extension)"
                )
            self._spot_subscribed.add(symbol)

    def _consume_spot_events(self, leftover_budget: int = 50) -> None:
        """Non-blocking drain of queued ProtoOASpotEvents into _last_spot."""
        drained = 0
        while drained < leftover_budget:
            try:
                kind, payload = self._conn.event_queue.get_nowait()
            except queue.Empty:
                break
            drained += 1
            if (
                kind == "MESSAGE"
                and payload is not None
                and type(payload).__name__ == "ProtoOASpotEvent"
            ):
                self._record_spot(payload)
            else:
                self._conn.event_queue.put((kind, payload))
                # Stop at the first non-spot event to keep requeue order
                # (re-put puts it at the tail; remaining spot events behind
                # it are fetched on the next call).

    def _record_spot(self, evt: Any) -> None:
        bid = getattr(evt, "bid", 0)
        ask = getattr(evt, "ask", 0)
        ts = int(getattr(evt, "timestamp", 0) or 0)
        if not bid or not ask:
            return  # partial quote — wait for the next event
        # Resolve symbol name for the event (reverse map).
        sym_id = int(getattr(evt, "symbolId", 0))
        name = None
        for n, sid in self._symbol_ids.items():
            if sid == sym_id:
                name = n
                break
        if name is None:
            name = f"symid_{sym_id}"
        self._last_spot[name] = {
            "bid": float(bid) / CTRADER_PRICE_SCALE,
            "ask": float(ask) / CTRADER_PRICE_SCALE,
            "time": ts,  # UTC epoch seconds (subscribeToSpotTimestamp=TRUE)
        }

    def get_tick_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Latest spot quote for `symbol`, MT5 tick-shape {bid, ask, time}.

        Returns None when no quote is available or the last quote is older
        than tick_max_age_sec (caller maps None → connection gate failure —
        the same tri-state semantics MT5Connection.get_tick_data exposes).
        """
        self._consume_spot_events()
        if symbol not in self._spot_subscribed:
            try:
                self.subscribe_spots(symbol)
            except CTraderDataError as exc:
                logger.warning("ctrader_adapter_spot_subscribe_failed: %s", exc)
                return None
            # First quote may need a moment; bounded wait.
            deadline = time.monotonic() + self._timeout
            while time.monotonic() < deadline:
                self._consume_spot_events()
                if symbol in self._last_spot:
                    break
                time.sleep(0.1)
        quote = self._last_spot.get(symbol)
        if quote is None:
            return None
        if quote["time"] > 0:
            age = time.time() - quote["time"]
            if age > self._tick_max_age or age < -self._tick_max_age:
                logger.warning("ctrader_adapter_stale_quote: %s age=%.0fs", symbol, age)
                return None
        return dict(quote)
