#!/usr/bin/env python
"""PHASE 7 — SAFETY MONITOR (fail-safe gating).

Composite safety check that combines five independent guards required
by the roadmap before any trade may be sent:

- KILL_SWITCH     — explicit user/operator shutdown
- STALE_DATA      — no fresh 15m bar within `stale_seconds`
- CONNECTION      — MT5 connection is up (live data path alive)
- SPREAD          — current spread below `max_spread_points`
- RECONCILIATION  — last Reconciler decision is OK (no orphan/mismatch)

If ANY check fails, `SafetyDecision.allowed = False` and the bot must
NOT open new trades. The decision carries per-check booleans + the
first failing check (for the audit log).

Pure / injectable: takes plain Python inputs (timestamp, spread, etc.)
and a `ReconciliationDecision`. No MT5 dep. The runtime loop is
expected to call `check(...)` at the top of each tick.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from src.live.reconciliation import ReconciliationDecision, ReconcileStatus


class SafetyCheck(str, Enum):
    """Independent safety guards (roadmap acceptance)."""

    KILL_SWITCH = "KILL_SWITCH"
    STALE_DATA = "STALE_DATA"
    CONNECTION = "CONNECTION"
    SPREAD = "SPREAD"
    RECONCILIATION = "RECONCILIATION"


# Severity order for "first failing check" reporting
_CHECK_ORDER = [
    SafetyCheck.KILL_SWITCH,
    SafetyCheck.STALE_DATA,
    SafetyCheck.CONNECTION,
    SafetyCheck.SPREAD,
    SafetyCheck.RECONCILIATION,
]


@dataclass
class SafetyDecision:
    """Outcome of a single safety pass."""

    allowed: bool
    reason: str = ""
    failing_check: Optional[SafetyCheck] = None
    # Per-check booleans (all True when allowed=True)
    checks: List[bool] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return self.allowed


class SafetyMonitor:
    """Composite safety gate. Stateless; one instance per runtime is fine."""

    def __init__(
        self,
        max_spread_points: float = 30.0,
        stale_seconds: float = 30.0 * 60.0,  # 30 minutes default
    ):
        # max_spread_points: in MT5 points (e.g. 30 = 3.0 pips on a 5-digit
        # symbol). The runtime converts the symbol's spread (price units)
        # to points before calling `check()`.
        self.max_spread_points = float(max_spread_points)
        # stale_seconds: how old the latest 15m bar can be before we treat
        # the feed as stale. 15m bar + 1 bar of slack = 30 min is sane.
        self.stale_seconds = float(stale_seconds)

    def check(
        self,
        *,
        kill_switch: bool = False,
        connection_ok: bool = True,
        last_candle_time: Optional[float] = None,
        now: Optional[float] = None,
        spread_points: float = 0.0,
        reconciliation: Optional[ReconciliationDecision] = None,
    ) -> SafetyDecision:
        """Run the composite safety check.

        Args:
            kill_switch: True if operator has issued a shutdown.
            connection_ok: True if MT5 connection is alive.
            last_candle_time: epoch seconds of the most recent closed 15m
                bar received (or None = no data yet).
            now: epoch seconds (defaults to `time.time()` if not given).
            spread_points: current spread in MT5 points.
            reconciliation: last `ReconciliationDecision`. None is treated
                as "no reconciliation yet" — does NOT block (initial state).

        Returns:
            SafetyDecision.allowed is True iff all checks pass.
        """
        import time

        if now is None:
            now = time.time()

        results: List[bool] = []
        failing: Optional[SafetyCheck] = None
        reason: str = ""

        # 1) KILL_SWITCH
        ks_ok = not bool(kill_switch)
        results.append(ks_ok)
        if not ks_ok and failing is None:
            failing = SafetyCheck.KILL_SWITCH
            reason = "kill switch is ON"

        # 2) STALE_DATA
        if last_candle_time is None:
            stale_ok = False
            stale_reason = "no candle received yet"
        else:
            age = now - float(last_candle_time)
            stale_ok = age <= self.stale_seconds
            stale_reason = (
                f"candle age {age:.0f}s > stale threshold {self.stale_seconds:.0f}s"
            )
        results.append(stale_ok)
        if not stale_ok and failing is None:
            failing = SafetyCheck.STALE_DATA
            reason = stale_reason

        # 3) CONNECTION
        conn_ok = bool(connection_ok)
        results.append(conn_ok)
        if not conn_ok and failing is None:
            failing = SafetyCheck.CONNECTION
            reason = "MT5 connection is down"

        # 4) SPREAD
        spread_ok = float(spread_points) <= self.max_spread_points
        results.append(spread_ok)
        if not spread_ok and failing is None:
            failing = SafetyCheck.SPREAD
            reason = (
                f"spread {spread_points:.1f} > max {self.max_spread_points:.1f} points"
            )

        # 5) RECONCILIATION
        if reconciliation is None:
            recon_ok = True  # no reconciliation run yet — don't block initial
            recon_reason = "no reconciliation run yet"
        else:
            recon_ok = reconciliation.status == ReconcileStatus.OK
            recon_reason = f"reconciliation status: {reconciliation.status.value}"
        results.append(recon_ok)
        if not recon_ok and failing is None:
            failing = SafetyCheck.RECONCILIATION
            reason = recon_reason

        allowed = all(results)
        return SafetyDecision(
            allowed=allowed,
            reason=reason if not allowed else "",
            failing_check=failing,
            checks=results,
        )
