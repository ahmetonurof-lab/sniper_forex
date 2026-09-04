#!/usr/bin/env python
"""Live runtime state persistence / recovery.

PHASE 3 — STRATEGY RUNTIME.

Persists per-symbol `StrategyRuntime` state to JSON so the bot can recover
after a restart without losing CBDR/sweep/active-trade context. State is
serialized via `StrategyRuntime.to_state()` and restored via
`StrategyRuntime.from_state()`.

State files live under a configurable directory (default `state/`). One file
per symbol: `state/<SYMBOL>.json`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, Optional

# ── Shared write primitive (N2 #21 madde-8 — tek-modül) ────────────
# The former local tmp+rename copy (N2 #15/#15-b) is gone: the single
# primitive lives in src/live/atomic_write.py with the K2 crash-log
# floor standard (BULGU-14). Budget constants are re-exported so the
# §2.2 same-budget pin (test_orchestrator_n2_15b) holds by identity.
from src.live.atomic_write import (  # noqa: F401 — budget-pin re-export
    _TMP_RETRY_BASE_SLEEP,
    _TMP_WRITE_RETRIES,
    atomic_write_text,
)


class StateStore:
    """JSON-backed persistence for per-symbol runtime state."""

    def __init__(
        self,
        state_dir: str = "state",
        on_block: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        # N2 #15-b (K3): forensic sink for blocked state renames.
        self.on_block = on_block

    def _path(self, symbol: str) -> Path:
        return self.state_dir / f"{symbol}.json"

    def save(self, symbol: str, state: dict) -> None:
        """Write a runtime state dict to disk (atomic via the shared
        tmp+rename primitive — never a torn JSON document)."""
        path = self._path(symbol)
        atomic_write_text(
            path,
            json.dumps(state, indent=2, default=str),
            encoding="utf-8",
            on_block=self.on_block,
        )

    def load(self, symbol: str) -> Optional[dict]:
        """Load a runtime state dict, or None if absent/corrupt."""
        path = self._path(symbol)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def exists(self, symbol: str) -> bool:
        return self._path(symbol).exists()

    def clear(self, symbol: str) -> None:
        """Remove a symbol's persisted state (e.g. after a clean cycle)."""
        path = self._path(symbol)
        if path.exists():
            path.unlink()
