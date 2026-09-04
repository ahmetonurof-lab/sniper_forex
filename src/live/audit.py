#!/usr/bin/env python
"""PHASE 7 — AUDIT CHAIN.

Append-only event log covering the full trade lifecycle:

    CANDLE -> SIGNAL -> RISK -> ORDER -> FILL -> POSITION -> EXIT

Every event is timestamped, typed, and carries a free-form `payload`
dict so the runtime can attach context (price, size, reason, etc.) for
offline review. The chain can be flushed to a JSONL file for debugging
or post-mortem analysis.

Auto-flush: events are periodically persisted to disk based on
event count threshold and/or time interval, ensuring crash recovery
of recent events without blocking the trading loop.

Pure / injectable: no MT5 dep. The runtime loop (PHASE 11) is expected
to call `append(...)` at each lifecycle step.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# ── Shared write primitive (N2 #21 madde-8 — tek-modül) ────────────
# The former local tmp+rename copy (N2 #15/#15-b) is gone: the single
# primitive lives in src/live/atomic_write.py with the K2 crash-log
# floor standard (BULGU-14). The audit path uses its NEIGHBOR
# append_line() for delta-appends (Hakem N1-e — komşu fonksiyon, kopya
# değil). Budget constants are re-exported so the §2.2 same-budget pin
# (test_orchestrator_n2_15b) holds by identity.
from src.live.atomic_write import (  # noqa: F401 — budget-pin re-export
    _TMP_RETRY_BASE_SLEEP,
    _TMP_WRITE_RETRIES,
    append_line,
)


class EventType(str, Enum):
    """Full trade lifecycle event types (roadmap acceptance)."""

    CANDLE = "CANDLE"  # closed 15m bar received
    SIGNAL = "SIGNAL"  # StrategyRuntime produced a Signal
    RISK = "RISK"  # RiskManager evaluated (approved/blocked)
    ORDER = "ORDER"  # Execution sent (or attempted) an order
    FILL = "FILL"  # Broker confirmed fill (filled=True)
    POSITION = "POSITION"  # PositionManager observed an open position
    EXIT = "EXIT"  # Position closed (ClosedTrade emitted)
    SAFETY = "SAFETY"  # SafetyMonitor blocked a trade
    RECONCILE = "RECONCILE"  # Reconciler produced a decision
    ERROR = "ERROR"  # caught exception / unexpected failure
    STARTUP = "STARTUP"  # session started
    SHUTDOWN = "SHUTDOWN"  # session ended
    MT5_CONNECT = "MT5_CONNECT"  # MT5 terminal connected
    MT5_DISCONNECT = "MT5_DISCONNECT"  # MT5 terminal disconnected
    STATE_SAVE = "STATE_SAVE"  # state persisted
    WRITE_BLOCK = "WRITE_BLOCK"  # N2 #15-b: tmp→target rename blocked (AV/sync handle)
    LOCK_CORRUPT = "LOCK_CORRUPT"  # N2 #17/A9: lock unreadable (torn JSON) — read-path triage


@dataclass
class AuditEvent:
    """Single audit event."""

    timestamp: float  # epoch seconds
    event_type: EventType
    symbol: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize (event_type -> str for JSON)."""
        d = asdict(self)
        d["event_type"] = self.event_type.value
        return d


class AuditChain:
    """In-memory append-only event log with auto-flush to JSONL.

    Auto-flush triggers when:
    - Event count since last flush >= flush_threshold
    - Time since last flush >= flush_interval_sec

    Call shutdown() for a final flush at session end.

    Usage:
        audit = AuditChain(auto_flush_path="logs/audit.jsonl")
        audit.append(time.time(), EventType.SIGNAL, "EURUSD", {"entry": 1.1})
        audit.shutdown()  # final flush
    """

    def __init__(
        self,
        auto_flush_path: Optional[str] = None,
        flush_threshold: int = 50,
        flush_interval_sec: float = 30.0,
        on_block: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self._events: List[AuditEvent] = []
        self._auto_flush_path = auto_flush_path
        self._flush_threshold = flush_threshold
        self._flush_interval_sec = flush_interval_sec
        self._last_flush_time: float = time.time()
        self._last_flush_count: int = 0
        # N2 #15-b (K3): forensic sink for blocked renames during save.
        self.on_block = on_block
        # N2 #15-b: re-entrancy guard. A WRITE_BLOCK append fired from
        # inside save() must NOT trigger another flush → save recursion
        # (the T0#4 shutdown death-spiral shape). Events buffered during
        # a save land on disk with the next successful flush.
        self._saving = False

    # ── Public API ──────────────────────────────────────────────
    def append(
        self,
        timestamp: float,
        event_type: EventType,
        symbol: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        """Append a new event. Returns the event for chaining/tests."""
        evt = AuditEvent(
            timestamp=float(timestamp),
            event_type=event_type,
            symbol=symbol,
            payload=dict(payload) if payload else {},
        )
        self._events.append(evt)
        self._maybe_flush()
        return evt

    def append_event(self, event: AuditEvent) -> None:
        """Append a pre-built event (e.g. one returned by a prior append)."""
        self._events.append(event)
        self._maybe_flush()

    @property
    def events(self) -> List[AuditEvent]:
        """Read-only snapshot of all events recorded so far."""
        return list(self._events)

    def clear(self) -> None:
        """Drop all events (e.g. on session reset)."""
        self._events = []

    def __len__(self) -> int:
        return len(self._events)

    # ── Auto-flush ──────────────────────────────────────────────
    def _should_flush(self) -> bool:
        """Check if auto-flush conditions are met."""
        if not self._auto_flush_path:
            return False
        count_since = len(self._events) - self._last_flush_count
        time_since = time.time() - self._last_flush_time
        return count_since >= self._flush_threshold or time_since >= self._flush_interval_sec

    def _maybe_flush(self) -> None:
        """Flush if conditions met."""
        if self._saving:
            return  # N2 #15-b re-entrancy guard (see save())
        if self._should_flush():
            self.flush(self._auto_flush_path)

    def flush_if_due(self) -> None:
        """Persist buffered events if auto-flush conditions are met.

        Unlike ``_maybe_flush`` (only reachable from ``append``), this is
        safe to call from a runtime loop on a timer: it no-ops when no
        path is configured or no event has crossed the threshold/interval,
        and guarantees a quiet loop still lands buffered events on disk.
        """
        if self._should_flush():
            self.flush(self._auto_flush_path)

    def flush(self, path: Optional[str] = None) -> None:
        """Flush events to JSONL file. The delta watermark is owned by
        save() (advances to its pre-snapshot on success) — flush() only
        resets the flush CLOCK. Overwriting the watermark here would
        silently swallow events buffered during save (N2 #21)."""
        target = path or self._auto_flush_path
        if not target:
            return
        self.save(target)
        self._last_flush_time = time.time()

    def shutdown(self) -> None:
        """Final flush at session end."""
        if self._auto_flush_path:
            self.flush(self._auto_flush_path)

    # ── Persistence ─────────────────────────────────────────────
    def save(self, path: str) -> None:
        """Persist the delta since the last flush to the JSONL journal
        (one event per line) — N2 #21 madde-1, Hakem N1-a.

        DELTA-APPEND via the shared primitive's ``append_line``: the
        whole-file tmp+rename overwrite (the BULGU-1 root cause — every
        flush rewrote and thus erased the on-disk chain) is GONE. The
        flushed count starts from the boot-time load, so each flush
        appends exactly the events flushed so far minus the loaded
        history — prior boots' lines stay on disk. Each line is a
        self-contained JSON object so a torn tail never destroys
        recoverable history (load() skips the malformed tail).
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        # Delta snapshot: everything after the watermark, up to THIS call's
        # length (events appended mid-save belong to the NEXT delta).
        pre = len(self._events)
        lines = "".join(
            json.dumps(evt.to_dict(), default=str, sort_keys=True) + "\n"
            for evt in self._events[self._last_flush_count : pre]
        )
        self._saving = True
        try:
            append_line(p, lines, encoding="utf-8", on_block=self.on_block)
            # Watermark advances to the DELTA SNAPSHOT (pre), not the live
            # length: events appended DURING save (the re-entrancy-guarded
            # WRITE_BLOCK) stay above the watermark and land on the next
            # flush — never silently swallowed, never duplicated.
            self._last_flush_count = pre
        finally:
            self._saving = False

    def load(self, path: str) -> int:
        """Load events from a JSONL file into the chain.

        Returns the number of events loaded. Missing file -> 0. Malformed
        lines are skipped — a torn last line (crash mid-append) drops on
        the floor while all intact prior lines are recovered (Hakem
        N1-b: torn-line tolerance, TESTLE MÜHÜRLENDİ).

        N2 #21 madde-1 integration: the flush watermark
        (``_last_flush_count``) is initialized to the loaded count so
        the first post-load save delta-appends ONLY new events — the
        loaded history is never rewritten or duplicated. Last-write-wins
        is the declared boundary (single-writer O1 topology, Hakem
        N1-c); events buffered BEFORE the load are preserved.
        """
        p = Path(path)
        if not p.exists():
            return 0
        pre = len(self._events)
        n = 0
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    self._events.append(
                        AuditEvent(
                            timestamp=float(obj.get("timestamp", 0.0)),
                            event_type=EventType(obj["event_type"]),
                            symbol=obj.get("symbol"),
                            payload=dict(obj.get("payload", {})),
                        )
                    )
                    n += 1
                except Exception:
                    pass
        self._last_flush_count = pre + n
        return n
