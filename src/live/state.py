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
from typing import Optional


class StateStore:
    """JSON-backed persistence for per-symbol runtime state."""

    def __init__(self, state_dir: str = "state"):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, symbol: str) -> Path:
        return self.state_dir / f"{symbol}.json"

    def save(self, symbol: str, state: dict) -> None:
        """Write a runtime state dict to disk (atomic-ish via tmp+rename)."""
        path = self._path(symbol)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
        tmp.replace(path)

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
