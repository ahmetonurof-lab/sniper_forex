#!/usr/bin/env python
"""PHASE 6 — RECONCILIATION (local state <-> MT5 ground truth).

Compares the bot's local view of open positions (loaded from
`state.py` after restart, or held in `PositionManager` during a session)
against the MT5 terminal ground truth. Detects:

- **ORPHAN**: local says open, MT5 says gone (broker closed it, slippage
  triggered an SL outside, manual close, etc.).
- **UNKNOWN_OPEN**: MT5 has a bot-magic position the bot has no local
  record of (e.g. fill was missed on a prior run, or external recovery).
- **MISMATCH**: same ticket but different SL/TP/volume (broker may have
  modified, or local state is stale).
- **OK**: every local position matches an MT5 position; every MT5
  bot-magic position is known locally.

Acceptance
----------
On `MISMATCH` or `ORPHAN` the bot must block new trades. The decision
is consumed by the runtime loop (PHASE 7 audit / safety will read it).

Pure / injectable: takes plain Python objects. No MT5 dependency here
— `PositionManager.update()` already returns the MT5 side; reconciliation
itself just compares two dicts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List

from src.live.position_manager import Position


class ReconcileStatus(str, Enum):
    """Status of a single reconciliation pass."""

    OK = "OK"
    ORPHAN = "ORPHAN"  # local has ticket, MT5 does not
    UNKNOWN_OPEN = "UNKNOWN_OPEN"  # MT5 has ticket, local does not
    MISMATCH = "MISMATCH"  # ticket in both, but state diverges


@dataclass
class ReconciliationDecision:
    """Outcome of a reconciliation pass.

    `status` is the worst status found across all comparisons
    (MISMATCH > UNKNOWN_OPEN > ORPHAN > OK in severity).
    `block_trading` is True if the bot must not open new positions.
    `details` lists the offending tickets + their reason (for the
    audit log).
    """

    status: ReconcileStatus
    orphans: List[int] = field(default_factory=list)
    unknown_opens: List[int] = field(default_factory=list)
    mismatches: List[int] = field(default_factory=list)
    block_trading: bool = False
    details: List[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return self.status == ReconcileStatus.OK


# Severity ordering for "worst status" aggregation
_SEVERITY = {
    ReconcileStatus.OK: 0,
    ReconcileStatus.ORPHAN: 1,
    ReconcileStatus.UNKNOWN_OPEN: 2,
    ReconcileStatus.MISMATCH: 3,
}


def _worse(a: ReconcileStatus, b: ReconcileStatus) -> ReconcileStatus:
    return a if _SEVERITY[a] >= _SEVERITY[b] else b


class Reconciler:
    """Compares local positions (dict keyed by ticket) with MT5 positions.

    Usage:
        local = {p.ticket: p for p in state_manager.get_open_trades()}
        remote = {p.ticket: p for p in position_update.positions.values()}
        decision = reconciler.reconcile(local, remote)
        if not decision.is_clean:
            # block new trades, log details
    """

    # Fields that must match for a ticket to be considered OK.
    # If any of these differ, status = MISMATCH.
    MISMATCH_FIELDS = ("volume", "sl", "tp", "side", "entry_price", "symbol")

    def reconcile(
        self,
        local: Dict[int, Position],
        remote: Dict[int, Position],
    ) -> ReconciliationDecision:
        """Run a reconciliation pass. Pure function — no side effects."""
        local_tickets = set(local.keys())
        remote_tickets = set(remote.keys())

        orphans: List[int] = []
        unknown_opens: List[int] = []
        mismatches: List[int] = []
        details: List[str] = []

        # ORPHAN: local has, remote doesn't
        for t in sorted(local_tickets - remote_tickets):
            orphans.append(t)
            details.append(f"ORPHAN ticket={t} symbol={local[t].symbol} local=open remote=closed")

        # UNKNOWN_OPEN: remote has, local doesn't
        for t in sorted(remote_tickets - local_tickets):
            unknown_opens.append(t)
            details.append(
                f"UNKNOWN_OPEN ticket={t} symbol={remote[t].symbol} local=missing remote=open"
            )

        # MISMATCH: both have, but state differs
        for t in sorted(local_tickets & remote_tickets):
            lp = local[t]
            rp = remote[t]
            diffs = []
            for field_name in self.MISMATCH_FIELDS:
                lv = getattr(lp, field_name)
                rv = getattr(rp, field_name)
                if lv != rv:
                    diffs.append(f"{field_name}: local={lv} remote={rv}")
            if diffs:
                mismatches.append(t)
                details.append(f"MISMATCH ticket={t} symbol={lp.symbol} diffs=[{'; '.join(diffs)}]")

        # Aggregate status (worst-of)
        status = ReconcileStatus.OK
        if mismatches:
            status = _worse(status, ReconcileStatus.MISMATCH)
        if unknown_opens:
            status = _worse(status, ReconcileStatus.UNKNOWN_OPEN)
        if orphans:
            status = _worse(status, ReconcileStatus.ORPHAN)

        # Acceptance: any non-OK status blocks new trades.
        # Even ORPHAN is risky (bot may have missed a close and would
        # re-open a trade on the same idea). Conservative.
        block_trading = status != ReconcileStatus.OK

        return ReconciliationDecision(
            status=status,
            orphans=orphans,
            unknown_opens=unknown_opens,
            mismatches=mismatches,
            block_trading=block_trading,
            details=details,
        )
