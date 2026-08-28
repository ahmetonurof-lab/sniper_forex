#!/usr/bin/env python
"""P0-2 — Authoritative live lifecycle owner for broker-realized close accounting.

Owns the immutable open-trade context (locked at first broker-confirmed open)
and the deal-level realized PnL path. Does NOT replace PositionManager
(open-state only) or Reconciler (open-state comparator) — it is the
realized-close / PnL authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set

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
class TradeLifecycle:
    """Single account-level lifecycle owner for realized close accounting."""

    open_trades: Dict[int, OpenTradeContext] = field(default_factory=dict)
    portfolio_dd: PortfolioDD = field(default_factory=lambda: PortfolioDD())
    last_seen_deals: Set[int] = field(default_factory=set)

    # --- Authoritative close tracking ----------------------------------

    def register_open_context(
        self,
        context: OpenTradeContext,
    ) -> None:
        self.open_trades[context.position_id] = context

    def process_exit_deal(
        self,
        deal_id: int,
        position_id: int,
        _net_realized_cash: float,
        pnl_r: float,
    ) -> bool:
        """Idempotent deal processing; returns True if accepted (not duplicate)."""
        if deal_id in self.last_seen_deals:
            return False
        self.last_seen_deals.add(deal_id)
        # Find or create trade context by position_id
        ctx = self.open_trades.get(position_id)
        if ctx is not None:
            if deal_id not in ctx.processed_deal_ids:
                ctx.processed_deal_ids.add(deal_id)
            # Update accumulated realized PnL in R using locked initial risk
            ctx.realized_r_accumulated += float(pnl_r)
            # Call PortfolioDD exactly once per realized contribution
            self.portfolio_dd.record_realized(float(pnl_r))
            return True
        # If no open context exists but deal references a known historical
        # position, we still record PnL for DD tracking but do not invent context.
        self.portfolio_dd.record_realized(float(pnl_r))
        return True

    def rebuild_from_persisted(self, contexts: List[OpenTradeContext]) -> None:
        """Restart/recovery: rebuild open-trade state from persisted journal."""
        self.open_trades = {c.position_id: c for c in contexts if c.position_id > 0}
        # Rebuild PortfolioDD from accumulated realized_r values
        total_r = sum(c.realized_r_accumulated for c in self.open_trades.values())
        # Note: full portfolio DD rebuild requires historical deal replay;
        # here we seed from open contexts only (minimal safe default).
        self.portfolio_dd = PortfolioDD()
        if total_r != 0.0:
            # The initial balance is not recoverable from open context alone;
            # caller should pass the session starting balance separately.
            self.portfolio_dd.realized_pnl_r = float(total_r)
            self.portfolio_dd.peak_r = self.portfolio_dd.starting_balance_r + float(
                total_r
            )
