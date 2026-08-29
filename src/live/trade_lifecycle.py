#!/usr/bin/env python
"""P0-2 — Authoritative live lifecycle owner for broker-realized close accounting.

Owns the immutable open-trade context (locked at first broker-confirmed open)
and the deal-level realized PnL path. Does NOT replace PositionManager
(open-state only) or Reconciler (open-state comparator) — it is the
realized-close / PnL authority.

P1 upgrades (post-forensic audit @ 721633f):
- Realized deal journal: every accepted exit deal is appended; DD rebuild
  is a chronological REPLAY of this journal (never a total-PnL guess).
- Unknown/unmapped exits are QUARANTINED: PortfolioDD is NOT touched.
  Recovery re-maps a quarantined deal idempotently.
- `dd_is_reliable()` — DD state rebuilt without a journal is explicitly
  unreliable; callers must treat it conservatively (pause).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from src.live.portfolio_dd import PortfolioDD


@dataclass
class OpenTradeContext:
    """Immutable entry-time context for an open trade."""

    position_id: int
    order_id: int = 0
    entry_deal_id: int = 0
    symbol: str = ""
    side: str = "long"
    entry_price: float = 0.0
    initial_sl: float = 0.0
    base_lot: float = 0.0
    final_lot: float = 0.0
    filled_volume: float = 0.0
    remaining_volume: float = 0.0
    lot_multiplier: float = 1.0
    initial_risk_cash_total: float = 0.0
    initial_risk_cash_per_lot_or_unit: float = 0.0
    realized_r_accumulated: float = 0.0
    processed_deal_ids: Set[int] = field(default_factory=set)


@dataclass
class RealizedDealRecord:
    """One authoritative realized-exit record (chronological journal)."""

    deal_id: int
    position_id: int
    pnl_r: float
    net_realized_cash: float = 0.0
    timestamp: float = 0.0


@dataclass
class QuarantinedExit:
    """An exit deal that could not be mapped to an open trade context.

    PortfolioDD is NEVER updated for these; they wait for reconciliation.
    """

    deal_id: int
    position_id: int
    pnl_r: float
    net_realized_cash: float = 0.0
    reason: str = "unknown_position"
    timestamp: float = 0.0


def build_open_context_from_fill(
    *,
    position_id: int,
    order_id: int,
    entry_deal_id: int,
    symbol: str,
    side: str,
    entry_price: float,
    initial_sl: float,
    base_lot: float,
    filled_volume: float,
    lot_multiplier: float,
    initial_risk_cash_total: float,
    initial_risk_cash_per_unit: float,
) -> OpenTradeContext:
    """Build an OpenTradeContext from BROKER-CONFIRMED entry fill data.

    Callers must pass fill metadata from an ExecutionResult with
    `filled=True` (broker retcode DONE) — never from a pre-send request.
    """
    if position_id <= 0:
        raise ValueError("position_id must be a positive broker id")
    if filled_volume <= 0:
        raise ValueError("filled_volume must be positive")
    return OpenTradeContext(
        position_id=int(position_id),
        order_id=int(order_id),
        entry_deal_id=int(entry_deal_id),
        symbol=symbol,
        side=side,
        entry_price=float(entry_price),
        initial_sl=float(initial_sl),
        base_lot=float(base_lot),
        final_lot=float(filled_volume),
        filled_volume=float(filled_volume),
        remaining_volume=float(filled_volume),
        lot_multiplier=float(lot_multiplier),
        initial_risk_cash_total=float(initial_risk_cash_total),
        initial_risk_cash_per_lot_or_unit=float(initial_risk_cash_per_unit),
        realized_r_accumulated=0.0,
        processed_deal_ids=set(),
    )


@dataclass
class TradeLifecycle:
    """Single account-level lifecycle owner for realized close accounting."""

    open_trades: Dict[int, OpenTradeContext] = field(default_factory=dict)
    portfolio_dd: PortfolioDD = field(default_factory=lambda: PortfolioDD())
    last_seen_deals: Set[int] = field(default_factory=set)
    # Chronological realized-exit journal (authoritative DD rebuild source).
    realized_journal: List[RealizedDealRecord] = field(default_factory=list)
    # Unknown/unmapped exit deals (PortfolioDD NEVER touched for these).
    quarantined_exits: Dict[int, QuarantinedExit] = field(default_factory=dict)
    # True only when portfolio_dd reflects a full journal replay.
    dd_reliable: bool = True

    # --- Authoritative close tracking ----------------------------------

    def register_open_context(
        self,
        context: OpenTradeContext,
    ) -> None:
        self.open_trades[context.position_id] = context

    # -- Exit deal processing -------------------------------------------

    def record_exit_deal(
        self,
        deal_id: int,
        position_id: int,
        net_realized_cash: float,
        pnl_r: float,
        timestamp: float = 0.0,
    ) -> str:
        """Authoritative deal processing.

        Returns one of:
          "recorded"    -> context found, PortfolioDD updated exactly once
          "duplicate"   -> deal already seen (idempotent no-op)
          "quarantined" -> unknown/unmapped position; DD NOT touched
        """
        if deal_id in self.last_seen_deals:
            return "duplicate"
        ctx = self.open_trades.get(position_id)
        if ctx is None:
            # UNKNOWN / UNMAPPED EXIT -> quarantine. DD must NOT change.
            self.quarantined_exits[int(deal_id)] = QuarantinedExit(
                deal_id=int(deal_id),
                position_id=int(position_id),
                pnl_r=float(pnl_r),
                net_realized_cash=float(net_realized_cash),
                reason="unknown_position",
                timestamp=float(timestamp),
            )
            return "quarantined"

        self.last_seen_deals.add(deal_id)
        if deal_id not in ctx.processed_deal_ids:
            ctx.processed_deal_ids.add(deal_id)
        # Update accumulated realized PnL in R using locked initial risk.
        ctx.realized_r_accumulated += float(pnl_r)
        # PortfolioDD exactly once per realized contribution.
        self.portfolio_dd.record_realized(float(pnl_r))
        # Append the authoritative journal record (chronological replay src).
        self.realized_journal.append(
            RealizedDealRecord(
                deal_id=int(deal_id),
                position_id=int(position_id),
                pnl_r=float(pnl_r),
                net_realized_cash=float(net_realized_cash),
                timestamp=float(timestamp),
            )
        )
        return "recorded"

    def process_exit_deal(
        self,
        deal_id: int,
        position_id: int,
        _net_realized_cash: float,
        pnl_r: float,
    ) -> bool:
        """Backward-compatible boolean wrapper around `record_exit_deal`.

        True ONLY when the deal was accepted and PortfolioDD updated.
        Unknown/unmapped exits return False (and are quarantined).
        """
        return (
            self.record_exit_deal(deal_id, position_id, _net_realized_cash, pnl_r)
            == "recorded"
        )

    def recover_quarantined(
        self,
        deal_id: int,
        position_id: int,
    ) -> str:
        """Re-map a quarantined exit after reconciliation (idempotent).

        If the deal was quarantined because its position was unknown and
        the mapping is now available, it is processed through the normal
        authoritative path (exactly once). Returns the same statuses as
        `record_exit_deal` ("not_found" when no such quarantine exists).
        """
        q = self.quarantined_exits.pop(int(deal_id), None)
        if q is None:
            return "not_found"
        if deal_id in self.last_seen_deals:
            return "duplicate"
        return self.record_exit_deal(
            deal_id,
            position_id,
            q.net_realized_cash,
            q.pnl_r,
            timestamp=q.timestamp,
        )

    # -- DD reliability ---------------------------------------------------

    def dd_is_reliable(self) -> bool:
        """True when PortfolioDD was built from a full journal replay.

        When False (e.g. restart without a persisted journal), callers
        MUST treat DD as unknown and apply the conservative pause rule.
        """
        return self.dd_reliable

    # -- Restart / recovery -------------------------------------------------

    def rebuild_from_persisted(
        self,
        contexts: List[OpenTradeContext],
        realized_journal: Optional[List[RealizedDealRecord]] = None,
        starting_balance_r: Optional[float] = None,
    ) -> None:
        """Restart/recovery: rebuild open-trade + DD state.

        With a persisted realized journal: chronological REPLAY rebuilds
        equity/peak/DD exactly (authoritative, reliable).

        Without a journal: open-trade state is restored, but the realized
        total alone can NEVER reconstruct the historical peak — DD is
        marked UNRELIABLE (callers must pause risk scaling).
        """
        self.open_trades = {c.position_id: c for c in contexts if c.position_id > 0}
        self.realized_journal = list(realized_journal or [])
        self.quarantined_exits = {}
        self.last_seen_deals = set()
        start = (
            float(starting_balance_r)
            if starting_balance_r is not None
            else self.portfolio_dd.starting_balance_r
        )
        self.portfolio_dd = PortfolioDD(starting_balance_r=start)

        if self.realized_journal:
            # Chronological replay: equity evolves; the peak only ratchets
            # up when equity exceeds the running peak (correct DD math).
            self.dd_reliable = True
            for rec in sorted(
                self.realized_journal,
                key=lambda r: (r.timestamp, r.deal_id),
            ):
                if rec.deal_id in self.last_seen_deals:
                    continue  # idempotent replay (no duplicate DD)
                self.last_seen_deals.add(rec.deal_id)
                self.portfolio_dd.record_realized(float(rec.pnl_r))
                ctx = self.open_trades.get(rec.position_id)
                if ctx is not None and rec.deal_id not in ctx.processed_deal_ids:
                    ctx.processed_deal_ids.add(rec.deal_id)
                    ctx.realized_r_accumulated += float(rec.pnl_r)
        else:
            # No journal: the realized total alone cannot rebuild peak/DD.
            total_r = sum(c.realized_r_accumulated for c in self.open_trades.values())
            if total_r != 0.0:
                self.portfolio_dd.realized_pnl_r = float(total_r)
            # peak_r stays at the starting balance; DD marked UNRELIABLE so
            # callers pause risk scaling instead of trusting a fabricated peak.
            self.dd_reliable = False
            for ctx in self.open_trades.values():
                self.last_seen_deals.update(ctx.processed_deal_ids)

    # -- Persistence (JSON-safe) --------------------------------------------

    def to_persisted(self) -> dict:
        """JSON-safe snapshot for restart recovery (see recovery.py)."""
        return {
            "open_trades": [
                {
                    "position_id": c.position_id,
                    "order_id": c.order_id,
                    "entry_deal_id": c.entry_deal_id,
                    "symbol": c.symbol,
                    "side": c.side,
                    "entry_price": c.entry_price,
                    "initial_sl": c.initial_sl,
                    "base_lot": c.base_lot,
                    "final_lot": c.final_lot,
                    "filled_volume": c.filled_volume,
                    "remaining_volume": c.remaining_volume,
                    "lot_multiplier": c.lot_multiplier,
                    "initial_risk_cash_total": c.initial_risk_cash_total,
                    "initial_risk_cash_per_lot_or_unit": (
                        c.initial_risk_cash_per_lot_or_unit
                    ),
                    "realized_r_accumulated": c.realized_r_accumulated,
                    "processed_deal_ids": sorted(c.processed_deal_ids),
                }
                for c in self.open_trades.values()
            ],
            "realized_journal": [
                {
                    "deal_id": r.deal_id,
                    "position_id": r.position_id,
                    "pnl_r": r.pnl_r,
                    "net_realized_cash": r.net_realized_cash,
                    "timestamp": r.timestamp,
                }
                for r in self.realized_journal
            ],
            "quarantined_exits": [
                {
                    "deal_id": q.deal_id,
                    "position_id": q.position_id,
                    "pnl_r": q.pnl_r,
                    "net_realized_cash": q.net_realized_cash,
                    "reason": q.reason,
                    "timestamp": q.timestamp,
                }
                for q in self.quarantined_exits.values()
            ],
            "dd_reliable": self.dd_reliable,
            "starting_balance_r": self.portfolio_dd.starting_balance_r,
        }

    def restore_persisted(self, data: dict) -> None:
        """Inverse of `to_persisted` (replays the journal for DD rebuild)."""
        contexts = [
            OpenTradeContext(
                position_id=int(c["position_id"]),
                order_id=int(c.get("order_id", 0)),
                entry_deal_id=int(c.get("entry_deal_id", 0)),
                symbol=c.get("symbol", ""),
                side=c.get("side", "long"),
                entry_price=float(c.get("entry_price", 0.0)),
                initial_sl=float(c.get("initial_sl", 0.0)),
                base_lot=float(c.get("base_lot", 0.0)),
                final_lot=float(c.get("final_lot", 0.0)),
                filled_volume=float(c.get("filled_volume", 0.0)),
                remaining_volume=float(c.get("remaining_volume", 0.0)),
                lot_multiplier=float(c.get("lot_multiplier", 1.0)),
                initial_risk_cash_total=float(c.get("initial_risk_cash_total", 0.0)),
                initial_risk_cash_per_lot_or_unit=float(
                    c.get("initial_risk_cash_per_lot_or_unit", 0.0)
                ),
                realized_r_accumulated=float(c.get("realized_r_accumulated", 0.0)),
                processed_deal_ids=set(c.get("processed_deal_ids", [])),
            )
            for c in data.get("open_trades", [])
        ]
        journal = [
            RealizedDealRecord(
                deal_id=int(r["deal_id"]),
                position_id=int(r["position_id"]),
                pnl_r=float(r["pnl_r"]),
                net_realized_cash=float(r.get("net_realized_cash", 0.0)),
                timestamp=float(r.get("timestamp", 0.0)),
            )
            for r in data.get("realized_journal", [])
        ]
        self.rebuild_from_persisted(
            contexts,
            realized_journal=journal,
            starting_balance_r=data.get("starting_balance_r"),
        )
        self.dd_reliable = bool(data.get("dd_reliable", True)) and self.dd_reliable
        for q in data.get("quarantined_exits", []):
            self.quarantined_exits[int(q["deal_id"])] = QuarantinedExit(
                deal_id=int(q["deal_id"]),
                position_id=int(q["position_id"]),
                pnl_r=float(q["pnl_r"]),
                net_realized_cash=float(q.get("net_realized_cash", 0.0)),
                reason=q.get("reason", "unknown_position"),
                timestamp=float(q.get("timestamp", 0.0)),
            )
