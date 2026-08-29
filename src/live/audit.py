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
from typing import Any, Dict, List, Optional


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
    ) -> None:
        self._events: List[AuditEvent] = []
        self._auto_flush_path = auto_flush_path
        self._flush_threshold = flush_threshold
        self._flush_interval_sec = flush_interval_sec
        self._last_flush_time: float = time.time()
        self._last_flush_count: int = 0

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
        return (
            count_since >= self._flush_threshold
            or time_since >= self._flush_interval_sec
        )

    def _maybe_flush(self) -> None:
        """Flush if conditions met."""
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

        Atomic-ish via tmp+rename. Each line is a self-contained JSON
        object so partial reads still yield valid events.
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for evt in self._events:
                f.write(json.dumps(evt.to_dict(), default=str, sort_keys=True))
                f.write("\n")
        tmp.replace(p)

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
