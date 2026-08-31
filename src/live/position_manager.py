#!/usr/bin/env python
"""PHASE 6 — POSITION MANAGER.

Tracks open positions owned by the bot (filtered by `magic` number) and
detects closed trades between successive MT5 polls. Bot NEVER touches
positions it does not own (other magic numbers, manual trades, etc.).

Pure / injectable: MT5 module is passed in as `mt5` (default = real
MetaTrader5 package). Tests inject a fake `mt5` to avoid any real terminal
dependency. See `src/live/reconciliation.py` for state<->MT5 reconciliation
on restart.

Position lifecycle
------------------
1. `update(mt5)` — fetch current MT5 positions, filter by `magic`.
2. Compare with previous snapshot (built internally). New tickets that
   did not exist in the previous snapshot are reported as `new_opens`.
   Tickets that existed in the previous snapshot but are gone now are
   reported as `closed_trades` (with their last-known state).
3. Snapshot is updated. Caller receives a `PositionUpdate` containing
   the new opens, the closed trades, and the current `positions` dict
   keyed by ticket.

Acceptance
----------
- Bot only manages its own (magic) positions.
- Closed trades are detected on next poll after MT5 close.
- Manual positions (different magic) are ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ── Default magic for Phase 5/6 (mirrors src/live/execution.py) ───
DEFAULT_MAGIC = 9007001


@dataclass
class Position:
    """Snapshot of an open MT5 position owned by the bot."""

    ticket: int
    symbol: str
    side: str  # "long" / "short" (normalized: "buy"->"long", "sell"->"short")
    volume: float
    entry_price: float
    sl: float
    tp: float
    magic: int
    comment: str = ""
    open_time: Optional[float] = None  # epoch seconds (int mt5 time)
    profit: float = 0.0
    swap: float = 0.0

    def matches(self, other: "Position") -> bool:
        """True if `other` represents the same logical position
        (same ticket, same volume, same SL/TP). Used by Reconciler."""
        return (
            self.ticket == other.ticket
            and self.volume == other.volume
            and self.sl == other.sl
            and self.tp == other.tp
        )


@dataclass
class ClosedTrade:
    """A position that was open in the previous snapshot but is now gone.

    `exit_price` and `pnl` may be 0.0 if the broker did not report them
    (some MT5 versions). `pnl` is in account currency. Caller is
    responsible for filling these from `mt5.history_deals_get` if
    needed.
    """

    ticket: int
    symbol: str
    side: str
    volume: float
    entry_price: float
    sl: float
    tp: float
    magic: int
    exit_price: float = 0.0
    pnl: float = 0.0
    close_time: Optional[float] = None


@dataclass
class PositionUpdate:
    """Result of a single `PositionManager.update()` poll."""

    positions: Dict[int, Position] = field(default_factory=dict)
    new_opens: List[Position] = field(default_factory=list)
    closed_trades: List[ClosedTrade] = field(default_factory=list)
    fetch_ok: bool = True
    fetch_failed: bool = False
    stale_snapshot_preserved: bool = False

    @property
    def symbols(self) -> List[str]:
        """Unique symbols in the current snapshot (preserves insertion order)."""
        seen: List[str] = []
        for p in self.positions.values():
            if p.symbol not in seen:
                seen.append(p.symbol)
        return seen


def _normalize_side(raw_side: Any) -> str:
    """MT5 returns 0/ORDER_TYPE_BUY or 1/ORDER_TYPE_SELL. Normalize to
    'long' / 'short' for our internal use (matches strategy_runtime)."""
    if isinstance(raw_side, str):
        s = raw_side.lower()
        if s in ("buy", "long", "0", "order_type_buy"):
            return "long"
        if s in ("sell", "short", "1", "order_type_sell"):
            return "short"
        return s
    # numeric: 0 = buy, 1 = sell
    try:
        return "long" if int(raw_side) == 0 else "short"
    except Exception:
        return str(raw_side)


def _to_position(raw: Any, magic: int) -> Optional[Position]:
    """Convert a raw MT5 trade position object into our `Position`."""
    if raw is None:
        return None
    # Skip positions not owned by the bot
    raw_magic = getattr(raw, "magic", 0)
    try:
        if int(raw_magic) != int(magic):
            return None
    except Exception:
        return None
    try:
        return Position(
            ticket=int(getattr(raw, "ticket", 0)),
            symbol=str(getattr(raw, "symbol", "")),
            side=_normalize_side(getattr(raw, "type", 0)),
            volume=float(getattr(raw, "volume", 0.0)),
            entry_price=float(getattr(raw, "price_open", 0.0)),
            sl=float(getattr(raw, "sl", 0.0)),
            tp=float(getattr(raw, "tp", 0.0)),
            magic=int(raw_magic),
            comment=str(getattr(raw, "comment", "")),
            open_time=getattr(raw, "time", None),
            profit=float(getattr(raw, "profit", 0.0)),
            swap=float(getattr(raw, "swap", 0.0)),
        )
    except Exception:
        return None


class PositionManager:
    """Tracks bot-owned open positions across MT5 polls.

    Args:
        magic: magic number that identifies bot-owned positions. Only
            positions whose `magic` matches this value are managed.
            Default mirrors `src/live/execution.py` (9007001).
        mt5: optional injected MT5 module (testability).
    """

    def __init__(self, magic: int = DEFAULT_MAGIC, mt5: Any = None):
        self.magic = magic
        if mt5 is None:
            import MetaTrader5 as mt5_mod  # type: ignore

            mt5 = mt5_mod
        self.mt5 = mt5
        # Last known snapshot, keyed by ticket
        self._snapshot: Dict[int, Position] = {}

    # ── Public API ──────────────────────────────────────────────
    def update(self) -> PositionUpdate:
        """Poll MT5 for current open positions, return new opens + closes.

        - Fetches via `mt5.positions_get()`.
        - Filters by `self.magic` (bot-owned only).
        - Compares with the previous snapshot:
            * new ticket   -> `new_opens`
            * missing now  -> `closed_trades` (data from previous snapshot)
        - Updates the snapshot to the current set.
        - Returns a `PositionUpdate` with all three collections.
        """
        try:
            raw_positions = self.mt5.positions_get() or []
        except Exception:
            # Preserve previous snapshot on fetch failure; emit no synthetic close.
            return PositionUpdate(
                positions=dict(self._snapshot),
                new_opens=[],
                closed_trades=[],
                fetch_ok=False,
                fetch_failed=True,
                stale_snapshot_preserved=True,
            )

        # Build current dict (bot-owned only)
        current: Dict[int, Position] = {}
        for raw in raw_positions:
            pos = _to_position(raw, self.magic)
            if pos is None or pos.ticket <= 0:
                continue
            current[pos.ticket] = pos

        # Diff
        new_opens: List[Position] = []
        closed_trades: List[ClosedTrade] = []
        prev_tickets = set(self._snapshot.keys())
        curr_tickets = set(current.keys())

        for t in curr_tickets - prev_tickets:
            new_opens.append(current[t])
        for t in prev_tickets - curr_tickets:
            prev = self._snapshot[t]
            closed_trades.append(
                ClosedTrade(
                    ticket=prev.ticket,
                    symbol=prev.symbol,
                    side=prev.side,
                    volume=prev.volume,
                    entry_price=prev.entry_price,
                    sl=prev.sl,
                    tp=prev.tp,
                    magic=prev.magic,
                    exit_price=0.0,
                    pnl=0.0,
                    close_time=None,
                )
            )

        self._snapshot = dict(current)
        return PositionUpdate(
            positions=dict(current),
            new_opens=new_opens,
            closed_trades=closed_trades,
            fetch_ok=True,
            fetch_failed=False,
            stale_snapshot_preserved=False,
        )

    def get_snapshot(self) -> Dict[int, Position]:
        """Read-only copy of the last snapshot."""
        return dict(self._snapshot)

    def get_for_symbol(self, symbol: str) -> List[Position]:
        """All currently-known open positions for `symbol`."""
        return [p for p in self._snapshot.values() if p.symbol == symbol]

    def restore(self, positions: List[Position]) -> None:
        """Seed the snapshot from persisted state (restart recovery).

        Positions are stored as-is; no MT5 verification at restore time.
        Use `Reconciler` to verify after restart (PHASE 6 acceptance).
        """
        self._snapshot = {p.ticket: p for p in positions if p.ticket > 0}

    def clear(self) -> None:
        """Drop the entire snapshot (e.g. after clean shutdown)."""
        self._snapshot = {}
