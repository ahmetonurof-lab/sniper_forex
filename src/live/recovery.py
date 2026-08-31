#!/usr/bin/env python
"""P1 — RESTART / RECOVERY bridge (runtime-untouched).

StrategyRuntime's own to_state()/from_state() does NOT persist the
historical 15m bar buffer or FVG objects (`bars`/`nexus_bars_full` are
absent; `pending_entry["fvg"]` falls to the JSON string `default=str`
bug). Per directive, the runtime MAY only change if strictly required —
so this module provides recovery as an EXTERNAL layer:

    RuntimeRecovery.save(runtime, state_path)
        = runtime.to_state()
        + `bars` (index/timestamp/ohlcv/volume rows)
        + `nexus_bars_full` (derived)
        + `pending_entry` (FVG -> schema dict)
        + `active_trade` (incl. trailing state + entry risk lock when set)

    RuntimeRecovery.load(runtime, state_path)
        = runtime.from_state(state)
        + rebuild bars buffer and Nexus bar list
        + rebuild `pending_entry["fvg"]` as a REAL Nexus FVG object
        + rebuild `active_trade` continuation state

The lifecycle (journal, DD, quarantined exits, entry risk locks) is
persisted separately via `TradeLifecycle.to_persisted()`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, List

from src.live.state import StateStore
from src.strategy.models import Bar

_NEXUS_SNIPER_SRC = str(Path("C:/Users/Administrator/Desktop/nexus-mcp/sniper/src"))
if _NEXUS_SNIPER_SRC not in sys.path:
    sys.path.insert(0, _NEXUS_SNIPER_SRC)


def _nexus_fvg_from_dict(d: dict) -> Any:
    """Rebuild a real Nexus `FVG` object from a serialized dict."""
    from models import FVG as NexusFVG  # type: ignore

    return NexusFVG(
        direction=d["direction"],
        top=float(d["top"]),
        bottom=float(d["bottom"]),
        real_index=int(d["real_index"]),
        timeframe=d.get("timeframe", "15m"),
        filled=bool(d.get("filled", False)),
        invalidated=bool(d.get("invalidated", False)),
    )


def _bars_to_json(bars: List[Bar]) -> List[dict]:
    rows = []
    for b in bars:
        ts = b.timestamp
        ts_iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        rows.append(
            {
                "index": b.index,
                "timestamp": ts_iso,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
            }
        )
    return rows


def _bars_from_json(rows: List[dict]) -> List[Bar]:
    import pandas as pd

    bars = []
    for r in rows:
        ts = pd.Timestamp(r["timestamp"])
        bars.append(
            Bar(
                index=int(r["index"]),
                timestamp=ts,
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                volume=float(r.get("volume", 0.0)),
            )
        )
    return bars


def _fvg_to_dict(fvg: Any) -> dict:
    return {
        "direction": getattr(fvg, "direction", "bullish"),
        "top": getattr(fvg, "top", 0.0),
        "bottom": getattr(fvg, "bottom", 0.0),
        "real_index": getattr(fvg, "real_index", 0),
        "timeframe": getattr(fvg, "timeframe", "15m"),
        "filled": getattr(fvg, "filled", False),
        "invalidated": getattr(fvg, "invalidated", False),
    }


class RuntimeRecovery:
    """External persistence layer for `StrategyRuntime` state."""

    def __init__(self, state_dir: str = "state"):
        self.store = StateStore(state_dir)

    def save(self, runtime, symbol: str) -> Path:
        """Serialize runtime incl. bars buffer + FVG-aware pending entry."""
        state = runtime.to_state()
        state["bars"] = _bars_to_json(runtime.bars)
        # NOTE: nexus_bars_full is epoch-ms ints; NOT persisted directly
        # (rebuilt on load from `bars`). See _rebuild_nexus.
        pe = runtime.pending_entry
        if pe is not None:
            pe_safe = dict(pe)
            if pe_safe.get("fvg") is not None:
                pe_safe["fvg"] = _fvg_to_dict(pe_safe["fvg"])
            state["pending_entry"] = pe_safe
        # Trailing continuation state lives inside active_trade dict; keep it.
        if runtime.active_trade is not None:
            state["active_trade"] = runtime.active_trade
        self.store.save(symbol, state)
        return self.store._path(symbol)

    @staticmethod
    def _rebuild_nexus(runtime) -> None:
        """Rebuild `nexus_bars_full` from the restored `bars` buffer.

        Mirrors `strategy_runtime._to_nexus_bar` (NexusBar timestamp is
        epoch-ms int). The runtime's detection path reads only this list.
        """
        from models import Bar as NexusBar  # type: ignore

        runtime.nexus_bars_full = []
        for b in runtime.bars:
            ts_ms = int(b.timestamp.timestamp() * 1000) if hasattr(b.timestamp, "timestamp") else 0
            runtime.nexus_bars_full.append(
                NexusBar(
                    index=b.index,
                    open=b.open,
                    high=b.high,
                    low=b.low,
                    close=b.close,
                    volume=b.volume,
                    is_closed=True,
                    timestamp=ts_ms,
                )
            )

    def load(self, runtime, symbol: str) -> bool:
        """Restore a runtime, rebuilding the 15m buffer and FVG objects."""
        state = self.store.load(symbol)
        if state is None:
            return False
        bars = _bars_from_json(state.get("bars", []))
        runtime.from_state({k: v for k, v in state.items() if k not in ("bars", "nexus_bars_full")})
        runtime.bars = bars
        self._rebuild_nexus(runtime)
        pe = state.get("pending_entry")
        if isinstance(pe, dict) and pe.get("fvg") is not None:
            pe["fvg"] = _nexus_fvg_from_dict(pe["fvg"])
            runtime.pending_entry = pe
        return True

    def save_lifecycle(self, lifecycle, symbol: str) -> Path:
        self.store.save(f"{symbol}_lifecycle", lifecycle.to_persisted())
        return self.store._path(f"{symbol}_lifecycle")

    def load_lifecycle(self, lifecycle, symbol: str) -> bool:
        data = self.store.load(f"{symbol}_lifecycle")
        if data is None:
            return False
        lifecycle.restore_persisted(data)
        return True


def schedule_snapshot(runtime, lifecycle, symbol: str, state_dir: str = "state"):
    """Atomic close-save helper (production convenience)."""
    rec = RuntimeRecovery(state_dir)
    rec.save(runtime, symbol)
    rec.save_lifecycle(lifecycle, symbol)
