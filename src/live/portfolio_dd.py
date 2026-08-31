#!/usr/bin/env python
"""PHASE 11 — PORTFOLIO DRAWDOWN STATE + DD-BASED RISK SCALING.

Roadmap acceptance: the live runtime must implement the DD-based risk
scaling overlay that experiment/exp_maxdd_C_dd_risk_scaling.py proved
out on the canonical engine:
    - portfolio DD > 2R  -> risk 50%  (lot multiplier 0.50)
    - portfolio DD > 4R  -> risk 25%  (lot multiplier 0.25)
    - portfolio DD > 6R  -> pause      (block, multiplier 0.0)

The frozen engine is NOT modified. This is a post-hoc live overlay
fed by the realized trade stream (closed positions only). The
multiplier is applied at sizing time by `RiskManager.evaluate()` and
consumed by the live sizing step.

Pure / injectable: no MT5 dep. The runtime loop is expected to:
    1) call `record_realized(trade_pnl_r)` after each closed position
    2) before each new entry, call `current_dd_r()` and pass it to
       `RiskManager.evaluate(..., portfolio_dd_r=...)`
    3) read the `lot_multiplier` field on the returned `RiskDecision`
       and apply it to the proposed lot.

This file deliberately re-uses exp_maxdd_C's threshold defaults
(DD_T1=2, DD_T2=4, DD_T3=6) so the live behavior is in lock-step
with the research result. Thresholds are configurable for future
experiments.
"""

from __future__ import annotations

from dataclasses import dataclass

# Default thresholds (mirror experiment/exp_maxdd_C_dd_risk_scaling.py).
DEFAULT_T1 = 2.0  # >2R  -> 0.50 risk
DEFAULT_T2 = 4.0  # >4R  -> 0.25 risk
DEFAULT_T3 = 6.0  # >6R  -> 0.00 (pause)


@dataclass
class PortfolioDD:
    """Realized portfolio state in R units.

    `starting_balance_r` is the equity in R at the start of the
    session. Each closed trade contributes its `pnl_r` to realized
    equity. `current_dd_r` is `peak - realized`, never negative.

    `realized_pnl_r` and `peak_r` are kept for inspection / audit.
    """

    starting_balance_r: float = 100.0
    realized_pnl_r: float = 0.0
    peak_r: float = 100.0

    def current_dd_r(self) -> float:
        """Current realized drawdown in R (>=0, 0 means at peak)."""
        equity = self.starting_balance_r + self.realized_pnl_r
        return max(0.0, self.peak_r - equity)

    def current_equity_r(self) -> float:
        return self.starting_balance_r + self.realized_pnl_r

    def record_realized(self, pnl_r: float) -> None:
        """Append a realized trade's pnl (in R) and update peak / DD."""
        self.realized_pnl_r += float(pnl_r)
        equity = self.starting_balance_r + self.realized_pnl_r
        if equity > self.peak_r:
            self.peak_r = equity


def compute_lot_multiplier(
    dd_r: float,
    t1: float = DEFAULT_T1,
    t2: float = DEFAULT_T2,
    t3: float = DEFAULT_T3,
) -> float:
    """Compute the lot multiplier for a given realized drawdown (in R).

    Returns:
        0.0  if dd_r > t3  (PAUSE — caller should block the trade)
        0.25 if dd_r > t2
        0.50 if dd_r > t1
        1.00 otherwise

    Mirrors the logic in `experiment/exp_maxdd_C_dd_risk_scaling.py`.
    """
    if dd_r > t3:
        return 0.0
    if dd_r > t2:
        return 0.25
    if dd_r > t1:
        return 0.50
    return 1.00
