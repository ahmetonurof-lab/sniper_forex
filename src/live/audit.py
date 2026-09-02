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
import os
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# ── Atomic tmp+rename write (N2 #15 — WinError 5 hardening) ────────
# N2 #15-b (T0#4): the original 3-attempt / ~0.35s budget cleared tmp-name
# contention but NOT the second root-cause layer — a transient EXTERNAL
# handle (AV/Defender on-access scan) locking the TARGET file for seconds.
# Budget raised to 8 attempts / ~6.4s worst-case total sleep (0.05·(2^0..2^6)
# = 6.35s), still 0.7% of LOCK_STALE_SEC=900 (§7.4 invariant preserved).
# ``on_block`` (K3): forensic callback invoked once per blocked file
# (first failed rename) with {file, retries, error} — the WRITE_BLOCK
# audit event.
_TMP_WRITE_RETRIES = 8
_TMP_RETRY_BASE_SLEEP = 0.05


def _atomic_write_text(
    path: Path,
    text: str,
    encoding: str = "utf-8",
    on_block: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> None:
    """Atomically write ``text`` to ``path`` via a PID-unique tmp + rename.

    Identical contract to src.live.orchestrator._atomic_write_text — kept
    here as a local copy to avoid a circular import (audit.py is imported
    by orchestrator.py).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding=encoding)
    last_err: Optional[OSError] = None
    for attempt in range(_TMP_WRITE_RETRIES):
        try:
            tmp.replace(path)
            return
        except OSError as e:
            last_err = e
            # Fire once per file (first failed attempt) — the orchestrator
            # and AuditChain sinks depend on single-event semantics.
            if on_block is not None and attempt == 0:
                try:
                    on_block(
                        {
                            "file": str(path),
                            "retries": _TMP_WRITE_RETRIES,
                            "error": f"{type(e).__name__}: {e}",
                        }
                    )
                except Exception:
                    pass  # forensics must never mask the original failure
            if attempt + 1 < _TMP_WRITE_RETRIES:
                time.sleep(_TMP_RETRY_BASE_SLEEP * (2**attempt))
    try:
        tmp.unlink()
    except OSError:
        pass
    raise last_err  # type: ignore[misc]


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
        """Flush events to JSONL file."""
        target = path or self._auto_flush_path
        if not target:
            return
        self.save(target)
        self._last_flush_time = time.time()
        self._last_flush_count = len(self._events)

    def shutdown(self) -> None:
        """Final flush at session end."""
        if self._auto_flush_path:
            self.flush(self._auto_flush_path)

    # ── Persistence ─────────────────────────────────────────────
    def save(self, path: str) -> None:
        """Flush events to a JSONL file (one event per line).

        Atomic-ish via PID-unique tmp + rename (N2 #15: the old fixed
        ".tmp" sibling was the secondary WinError 5 crash site during
        shutdown flush at audit.py:184). Each line is a self-contained
        JSON object so partial reads still yield valid events.
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        lines = "".join(
            json.dumps(evt.to_dict(), default=str, sort_keys=True) + "\n" for evt in self._events
        )
        self._saving = True
        try:
            _atomic_write_text(p, lines, encoding="utf-8", on_block=self.on_block)
        finally:
            self._saving = False

    def load(self, path: str) -> int:
        """Load events from a JSONL file. Returns the number of events loaded.

        Missing file -> 0. Malformed lines are skipped.
        """
        p = Path(path)
        if not p.exists():
            return 0
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
        return n
