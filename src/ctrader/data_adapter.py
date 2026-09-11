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

  cTrader trendbar timestamps are UTC epoch minutes (official proto field
  utcTimestampInMinutes). The adapter passes them through as raw UTC epoch
  seconds and declares ts_semantics="utc"; the canonical ingest
  (SignalRunner._rates_to_bars) skips the MT5 server-time conversion for
  such rows. The adapter performs NO offset arithmetic of its own — the
  previous add-then-subtract round-trip resolved the DST heuristic at two
  different moments (construction time vs the bar's own date) and drifted
  ±1h across a DST straddle (docs/
  DESIGN_NOTE_TIMESTAMP_SEMANTICS_UTC_NORMALIZATION.md §3, red test
  test_roundtrip_dst_straddle_recovers_utc). MT5-shaped rows (no
  ts_semantics key) keep the legacy server→UTC conversion unchanged.

Output shape: list of dicts with keys
  {"time": int epoch seconds (UTC — see above), "ts_semantics": "utc",
   "open", "high", "low", "close", "tick_volume"} — the dict-access path
  consumed by SignalRunner._rates_to_bars / Orchestrator._rates_to_bars
  (r["time"], r["open"], ...).

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

from src.ctrader.position_adapter import (
    CTRADER_BOT_LABEL,
    _to_position_ctrader,
    position_to_dict,
)

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

# S1 (İş-4a) / D162: per-request trendbar ceiling. The official docs do
# not publish a numeric chunkSize for ProtoOAGetTrendbarsRes; the response
# carries `hasMore` which signals truncation. Counts above this ceiling are
# served by time-windowed chunked pagination (D162) — each chunk stays
# within the ceiling and the per-chunk hasMore guard remains the
# authoritative fail-loud protection against silent truncation.
CTRADER_MAX_SINGLE_REQUEST_BARS = 5000

# D162: inter-chunk pacing for the historical rate limit (5 req/s per
# connection, official docs). 0.25 s keeps ≤4 req/s even with instant
# round-trips; PEP 475 makes the sleep signal-interruptible (§7.4) and it
# is orders of magnitude below any stale-ownership window.
CTRADER_CHUNK_PACING_SEC = 0.25


class CTraderDataError(RuntimeError):
    """Fail-loud adapter error (AGENTS.md §19): no silent fallbacks."""


def trendbar_to_dict(tb: Any) -> Dict[str, Any]:
    """Convert a ProtoOATrendbar to the MT5-shaped dict contract.

    Price decode (official convention): low is 1/100000-scaled absolute low;
    open/high/close are low + respective delta, all 1/100000-scaled.
    Time: utcTimestampInMinutes (UTC epoch minutes) passes through as raw UTC
    epoch seconds with ts_semantics="utc" — the provider is UTC, so the
    canonical ingest skips the MT5 server-time conversion for these rows
    (no synthetic offset round-trip; design-note §2–§3).
    """
    low = float(tb.low)
    o = (low + float(tb.deltaOpen)) / CTRADER_PRICE_SCALE
    h = (low + float(tb.deltaHigh)) / CTRADER_PRICE_SCALE
    lo = low / CTRADER_PRICE_SCALE
    c = (low + float(tb.deltaClose)) / CTRADER_PRICE_SCALE
    # UTC epoch minutes → UTC epoch seconds, unchanged (provider is UTC).
    ts_utc = int(tb.utcTimestampInMinutes) * 60
    return {
        "time": ts_utc,
        "ts_semantics": "utc",
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
    ) -> None:
        self._conn = connection
        self._timeout = float(response_timeout_sec)
        self._tick_max_age = float(tick_max_age_sec)
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
        # D162: inter-chunk pacing (instance seam so tests can set 0 —
        # visible test seam, NOT a silent production fallback).
        self._chunk_pacing_sec = float(CTRADER_CHUNK_PACING_SEC)

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

    def ensure_connected(self, max_attempts: int = 3) -> bool:
        """Orchestrator-side liveness check — MT5 parity (İŞ-3).

        MT5Connection.ensure_connected → is_connected() (REAL liveness
        probe) → reconnect(max_attempts=3). cTrader parity: when the
        connection is dead OR stale (no server message within the liveness
        window — half-open TCP), actively reconnect via
        CTraderConnection.reconnect() instead of passively waiting for the
        ClientService retry policy (which never engages on a half-open
        connection — the 19:31→20:46 outage root cause).

        D178: waits for ACCOUNT authorization, not just TCP. Live evidence
        (2026-09-08): ensure_connected returned True while ACCOUNT_AUTH_RES
        was ~2s away; the first request_symbols_list hit the server
        pre-auth -> ProtoOAErrorRes 'Trading account is not authorized' ->
        symbols_response_timeout -> warmup_failed -> SAFE_START forever.
        """
        if self.is_connected() and not self._conn_stale():
            return self._wait_account_authorized(6.0)
        return self._reconnect(max_attempts)

    def _conn_stale(self) -> bool:
        """İŞ-3: half-open TCP liveness probe (duck-typed).

        Delegates to the connection's `is_stale()`; fakes without it are
        never stale (returns False). A stale connection has the callback
        flag True but receives no server messages — the passive
        ClientService policy cannot detect it.
        """
        probe = getattr(self._conn, "is_stale", None)
        if probe is None:
            return False
        try:
            return bool(probe())
        except Exception:
            return False

    def _reconnect(self, max_attempts: int) -> bool:
        """İŞ-3: active reconnect (duck-typed) — MT5 reconnect parity.

        Delegates to the connection's `reconnect(max_attempts=...)`.
        On success, resets per-connection subscription state (server-side
        spot subscriptions are per-connection and are lost on reconnect).

        Fakes without `reconnect` fall back to the legacy bounded-wait
        behavior (wait for the ClientService policy) — visible test seam,
        NOT a silent production fallback: the real CTraderConnection
        always exposes reconnect.
        """
        reconnect = getattr(self._conn, "reconnect", None)
        if reconnect is None:
            deadline = time.monotonic() + min(max_attempts, 5) * 2.0
            while time.monotonic() < deadline:
                if self.is_connected():
                    return self._wait_account_authorized(6.0)
                time.sleep(0.2)
            return self.is_connected()
        ok = reconnect(max_attempts=max_attempts)
        if ok:
            # Server-side spot subscriptions are per-connection — the
            # adapter must re-subscribe after a reconnect.
            self._spot_subscribed.clear()
            self._last_spot.clear()
        return ok

    def _wait_account_authorized(self, timeout_sec: float) -> bool:
        """D178: bounded wait for the connection's account-authorized gate.
        Duck-typed: fakes without the attribute pass through untouched
        (test fakes are always authorized by construction).

        D178 fix#2b: the attribute is a property (bool), so it must be
        re-read every iteration. The first version captured it once via
        getattr before the loop and then re-checked the stale captured
        value — a connection that authorized *during* the wait was never
        observed (live evidence 2026-09-08: 6.0s wait returned False,
        account_authorized read True immediately afterwards)."""
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            val = getattr(self._conn, "account_authorized", None)
            if val is None or val:
                return True
            time.sleep(0.1)
        return bool(getattr(self._conn, "account_authorized", False))

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
        D162: counts above CTRADER_MAX_SINGLE_REQUEST_BARS are served via
        time-windowed chunked pagination (_get_rates_chunked) — the
        per-chunk hasMore guard stays fail-loud.
        """
        if timeframe != "M1":
            raise CTraderDataError(f"unsupported_timeframe: {timeframe} (only M1)")
        if count <= 0:
            raise CTraderDataError(f"invalid_count: {count}")
        if not self.ensure_connected():
            # İŞ-3: per-operation ensure_connected (MT5 parity) — a dead or
            # stale connection is actively reconnected here, not just
            # reported. On failure → tri-state None (ERROR-ladder path).
            # Fail-loud is reserved for permanent misconfiguration (unknown
            # symbol, unsupported timeframe) — not for connection state.
            logger.warning("ctrader_adapter_get_rates_not_connected")
            return None
        if count > CTRADER_MAX_SINGLE_REQUEST_BARS:
            # D162: chunked pagination — time-windowed requests, each within
            # the single-request ceiling, merged oldest-first. The per-chunk
            # hasMore guard below remains the authoritative fail-loud
            # protection (AGENTS.md §19): any chunk reporting hasMore=True
            # aborts the WHOLE fetch loudly (no partial history served).
            return self._get_rates_chunked(symbol, count)

        symbol_id = self._resolve_symbol_id(symbol)

        with self._req_lock:
            if not self.ensure_connected():
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
            # İŞ-3: stale-gate → reconnect trigger. A request timeout on a
            # dead/stale connection must trigger an active reconnect (MT5
            # parity) instead of leaving the quote stream dead for ~75 min
            # (19:31→20:46 outage). ensure_connected is a no-op when the
            # connection is fresh (transient timeout) — it only reconnects
            # when the liveness probe says the connection is dead/stale.
            self.ensure_connected()
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

        bars = [trendbar_to_dict(tb) for tb in res.trendbar]
        # Server returns bars ascending by time; canonical consumer expects
        # oldest-first ordering (is_closed_m1 + resample_15m assumptions).
        bars.sort(key=lambda b: b["time"])
        return bars

    # ------------------------------------------------------------------
    # D162 — chunked pagination (count > CTRADER_MAX_SINGLE_REQUEST_BARS)
    # ------------------------------------------------------------------
    def _get_rates_chunked(self, symbol: str, count: int) -> Optional[List[Dict[str, Any]]]:
        """Fetch `count` M1 bars via time-windowed chunked requests.

        Semantics (D162):
          - The window is split into CTRADER_MAX_SINGLE_REQUEST_BARS-minute
            chunks walking BACKWARD from now; each chunk is one
            request_trendbars round-trip with count=None (full window) so
            the server decides how many bars fit the window.
          - Per-chunk hasMore=True → CTraderDataError (fail-loud, §19):
            a truncated chunk means the window held more bars than the
            server's chunkSize — serving it would silently drop history.
          - Any chunk returning None (timeout/transport) → the WHOLE fetch
            returns None (tri-state ERROR-ladder path). A partial merge
            would silently corrupt warmup/replay state (§19).
          - Chunks are merged, deduplicated by bar time, and sorted
            oldest-first (canonical consumer contract).
          - Inter-chunk pacing (CTRADER_CHUNK_PACING_SEC) respects the
            5 req/s historical rate limit; the sleep is signal-interruptible
            (PEP 475, §7.4).
          - The whole loop runs under _req_lock (single-consumer discipline
            on the shared event_queue).
        """
        symbol_id = self._resolve_symbol_id(symbol)
        chunk_minutes = CTRADER_MAX_SINGLE_REQUEST_BARS
        merged: Dict[int, Dict[str, Any]] = {}

        with self._req_lock:
            if not self.ensure_connected():
                logger.warning("ctrader_adapter_get_rates_not_connected")
                return None
            now_ms = int(time.time() * 1000)
            # Walk backward from now in chunk_minutes windows until the
            # requested bar count is covered. The +2-minute headroom mirrors
            # the single-request path (newest bucket completion).
            total_minutes = count + 2
            chunk_start_ms = now_ms - total_minutes * 60 * 1000
            first_chunk_start_ms = chunk_start_ms
            while chunk_start_ms < now_ms:
                chunk_end_ms = min(chunk_start_ms + chunk_minutes * 60 * 1000, now_ms)
                if chunk_start_ms != first_chunk_start_ms:
                    # Inter-chunk pacing: historical rate limit is 5 req/s
                    # per connection (official docs). PEP 475 makes the
                    # sleep signal-interruptible (§7.4); 0.25 s is orders
                    # of magnitude below any stale-ownership window.
                    time.sleep(self._chunk_pacing_sec)
                try:
                    self._conn.request_trendbars(
                        symbol_id=symbol_id,
                        period=CTRADER_PERIOD_M1,
                        from_ms=chunk_start_ms,
                        to_ms=chunk_end_ms,
                        count=None,
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
                    logger.warning(
                        "ctrader_adapter_chunked_timeout: %s window=[%s,%s]",
                        symbol,
                        chunk_start_ms,
                        chunk_end_ms,
                    )
                    return None
                if type(res).__name__ != "ProtoOAGetTrendbarsRes":
                    logger.warning("ctrader_adapter_trendbars_error: %s", res)
                    return None
                # Per-chunk fail-loud guard (§19) — same rationale as the
                # single-request path: hasMore=True means the server chunked
                # THIS window; merging it would silently drop history.
                if bool(getattr(res, "hasMore", False)):
                    raise CTraderDataError(
                        f"trendbars_truncated_response: {symbol} chunk "
                        f"[{chunk_start_ms},{chunk_end_ms}] hasMore=True — "
                        "server chunked the chunk window; fetch aborted "
                        "loudly (D162 per-chunk fail-loud guard)"
                    )
                for tb in res.trendbar:
                    d = trendbar_to_dict(tb)
                    merged[int(d["time"])] = d  # dedupe by bar time
                chunk_start_ms = chunk_end_ms

        bars = sorted(merged.values(), key=lambda b: b["time"])
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
        # D178: ProtoOASpotEvent.timestamp is in MILLISECONDS (official proto:
        # int64 "Timestamp of the event (in milliseconds)"). Stored as SECONDS
        # — raw ms storage made age = now - ts ~ -1.78e12s and the symmetric
        # stale guard rejected every quote (gate CLOSED; 2026-09-08 evidence).
        ts_ms = int(getattr(evt, "timestamp", 0) or 0)
        ts = ts_ms // 1000 if ts_ms > 0 else 0
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
            "time": ts,  # UTC epoch seconds (converted from ms — D178)
        }

    def get_tick_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Latest spot quote for `symbol`, MT5 tick-shape {bid, ask, time}.

        Returns None when no quote is available or the last quote is older
        than tick_max_age_sec (caller maps None → connection gate failure —
        the same tri-state semantics MT5Connection.get_tick_data exposes).

        İŞ-3 (MT5 parity): per-operation ensure_connected — a dead/stale
        connection is actively reconnected before the quote is read, so the
        quote stream self-recovers after a drop instead of staying dead
        (19:31→20:46 outage).
        """
        if not self.ensure_connected():
            logger.warning("ctrader_adapter_get_tick_not_connected")
            return None
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
                # İŞ-3: stale-gate → reconnect trigger. A stale quote means
                # the spot stream stopped (dead/half-open connection) — the
                # CONNECTION gate closes on this path. Trigger an active
                # reconnect so the next call can recover (MT5 parity).
                self.ensure_connected()
                return None
        return dict(quote)

    # ------------------------------------------------------------------
    # get_positions — reconciliation fetch contract (İş-4a / reconciliation)
    # ------------------------------------------------------------------
    def _resolve_symbol_name(self, symbol_id: int) -> Optional[str]:
        """Reverse symbolId → name lookup from the cached symbol map."""
        for name, sid in self._symbol_ids.items():
            if int(sid) == int(symbol_id):
                return name
        return None

    def get_positions(
        self,
        contract_size: float = 100000.0,
    ) -> Optional[List[Dict[str, Any]]]:
        """Fetch open positions via ProtoOAReconcileReq, MT5-shaped dict list.

        Mirrors get_rates tri-state semantics:
          - None            → transient/transport failure (ERROR-ladder path)
          - []              → request succeeded, zero positions
          - List[dict]      → positions, MT5-shaped (ticket/symbol/side/
                              volume/entry_price/sl/tp/...)

        Only bot-owned positions (label == CTRADER_BOT_LABEL) are returned,
        matching the MT5 magic-filter semantics in
        `LiveRunner.startup_snapshot`. Volume is decoded from protocol units
        (lot x contract_size x 100) to lots via `position_to_dict`.

        İŞ-3 (MT5 parity): per-operation ensure_connected — a dead/stale
        connection is actively reconnected before the reconcile instead of
        raising ctrader_not_connected without recovery.
        """
        if not self.ensure_connected():
            raise CTraderDataError("ctrader_not_connected: cannot get_positions")
        with self._req_lock:
            try:
                self._conn.reconcile()
            except Exception as exc:
                raise CTraderDataError(
                    f"reconcile_request_failed: {type(exc).__name__}: {exc}"
                ) from exc
            res, leftovers = self._drain_until(
                lambda kind, payload: (
                    kind in ("MESSAGE", "RECONCILE_ERROR", "PARSE_ERROR")
                    and (
                        (
                            kind == "MESSAGE"
                            and payload is not None
                            and type(payload).__name__ == "ProtoOAReconcileRes"
                        )
                        or kind in ("RECONCILE_ERROR", "PARSE_ERROR")
                    )
                ),
                self._timeout,
            )
            self._requeue(leftovers)
            if res is None:
                raise CTraderDataError("reconcile_response_timeout")
            if type(res).__name__ != "ProtoOAReconcileRes":
                raise CTraderDataError(f"reconcile_error: {res}")
            positions: List[Dict[str, Any]] = []
            for pos in res.position:
                trade_data = getattr(pos, "tradeData", None)
                symbol_id = int(getattr(trade_data, "symbolId", 0))
                symbol_name = self._resolve_symbol_name(symbol_id)
                if symbol_name is None:
                    logger.warning(
                        "ctrader_adapter_unknown_symbol_id: %s (position skipped)",
                        symbol_id,
                    )
                    continue
                d = position_to_dict(pos, contract_size, symbol_name)
                if d is None:
                    continue
                if _to_position_ctrader(d, CTRADER_BOT_LABEL) is None:
                    continue  # not bot-owned — skip (MT5 magic-filter parity)
                positions.append(d)
            return positions
