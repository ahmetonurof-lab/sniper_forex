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
import os
import time
from pathlib import Path
from typing import Optional

# ── Atomic tmp+rename write (N2 #15 — WinError 5 hardening) ────────
_TMP_WRITE_RETRIES = 3
_TMP_RETRY_BASE_SLEEP = 0.05


def _atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Atomically write ``text`` to ``path`` via a PID-unique tmp + rename.

    Identical contract to src.live.orchestrator._atomic_write_text — kept
    here as a local copy to avoid a circular import.
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
            if attempt + 1 < _TMP_WRITE_RETRIES:
                time.sleep(_TMP_RETRY_BASE_SLEEP * (2**attempt))
    try:
        tmp.unlink()
    except OSError:
        pass
    raise last_err  # type: ignore[misc]


class StateStore:
    """JSON-backed persistence for per-symbol runtime state."""

    def __init__(self, state_dir: str = "state"):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, symbol: str) -> Path:
        return self.state_dir / f"{symbol}.json"

    def save(self, symbol: str, state: dict) -> None:
        """Write a runtime state dict to disk (atomic via PID-unique tmp+rename)."""
        path = self._path(symbol)
        _atomic_write_text(path, json.dumps(state, indent=2, default=str), encoding="utf-8")

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
