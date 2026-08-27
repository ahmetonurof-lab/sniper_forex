#!/usr/bin/env python
"""PHASE 7 — AUDIT CHAIN.

Append-only event log covering the full trade lifecycle:

    CANDLE -> SIGNAL -> RISK -> ORDER -> FILL -> POSITION -> EXIT

Every event is timestamped, typed, and carries a free-form `payload`
dict so the runtime can attach context (price, size, reason, etc.) for
offline review. The chain can be flushed to a JSONL file for debugging
or post-mortem analysis.

Pure / injectable: no MT5 dep. The runtime loop (PHASE 11) is expected
to call `append(...)` at each lifecycle step.
"""

from __future__ import annotations

import json
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
    """In-memory append-only event log with optional JSONL flush.

    Usage:
        audit = AuditChain()
        audit.append(AuditEvent(time.time(), EventType.SIGNAL, "EURUSD", {"entry": 1.1}))
        audit.save("audit.jsonl")
    """

    def __init__(self) -> None:
        self._events: List[AuditEvent] = []

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
        return evt

    def append_event(self, event: AuditEvent) -> None:
        """Append a pre-built event (e.g. one returned by a prior append)."""
        self._events.append(event)

    @property
    def events(self) -> List[AuditEvent]:
        """Read-only snapshot of all events recorded so far."""
        return list(self._events)

    def clear(self) -> None:
        """Drop all events (e.g. on session reset)."""
        self._events = []

    def __len__(self) -> int:
        return len(self._events)

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

        Missing file -> 0. Malformed lines are skipped (logged via
        print; production should swap to a logger).
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
                except Exception as e:
                    print(f"audit.load: skipped malformed line: {e}")
        return n
