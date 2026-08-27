#!/usr/bin/env python
"""PHASE 4 — RISK ENGINE.

Evaluates whether a `Signal` may be traded given account, contract, spread and
exposure constraints. If any risk check fails -> NO trade (blocked + logged).

Pure / injectable: no MT5 dependency. Callers supply `Account`, `ContractSpec`
and current spread/exposure. See `src/live/sizing.py` for lot sizing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.live.portfolio_dd import compute_lot_multiplier
from src.live.strategy_runtime import Signal


@dataclass
class Account:
    """Trading account snapshot (balance/equity in account currency)."""

    balance: float
    equity: float
    currency: str = "USD"


@dataclass
class RiskDecision:
    """Outcome of a risk evaluation."""

    approved: bool
    reason: str = ""
    # Populated when approved:
    stop_distance: float = 0.0
    risk_amount: float = 0.0
    risk_pct: float = 0.0
    # Populated when rejected:
    blocked: bool = False
    checks: list = field(default_factory=list)
    # Phase 11: DD-based lot multiplier (1.0 / 0.5 / 0.25 / 0.0).
    # 0.0 means PAUSE (the trade is blocked because portfolio DD > t3).
    # Callers MUST apply this multiplier to their proposed lot before
    # sending the order. See `src/live/portfolio_dd.py`.
    lot_multiplier: float = 1.0


class RiskManager:
    """Gatekeeper: reject a signal if any risk constraint is breached.

    Acceptance criterion: if a risk check fails -> NO trade. Trade blocked and
    logged (the `reason` + `checks` carry the audit trail).
    """

    def __init__(
        self,
        max_spread_ratio: float = 0.5,
        max_exposure_mult: float = 20.0,
        max_risk_per_trade: float = 0.01,
    ):
        # max_spread_ratio: spread must be < ratio * stop_distance (else spread
        # eats too much of the stop).
        self.max_spread_ratio = max_spread_ratio
        # max_exposure_mult: total open notional exposure cap as a multiple of
        # equity (leverage-style guard). e.g. 20.0 = max 20x equity notional.
        self.max_exposure_mult = max_exposure_mult
        # max_risk_per_trade: hard ceiling on risk per trade (sanity guard).
        self.max_risk_per_trade = max_risk_per_trade

    def evaluate(
        self,
        signal: Signal,
        account: Account,
        contract,
        spread: float,
        exposure: float = 0.0,
        lot: float = 0.0,
        portfolio_dd_r: float = 0.0,
    ) -> RiskDecision:
        """Evaluate a signal against risk constraints.

        Args:
            signal: entry signal (entry_price, sl, tp).
            account: balance/equity snapshot.
            contract: ContractSpec (volume min/max/step, stops_level, ...).
            spread: current spread in price units.
            exposure: current total open notional exposure (account currency).
            lot: proposed lot size (from PositionSizer). If 0, exposure and
                risk-ceiling checks are skipped (cannot size).
            portfolio_dd_r: realized portfolio drawdown in R (from
                `PortfolioDD.current_dd_r()`). When > 0, the lot multiplier
                from `compute_lot_multiplier(dd_r)` is applied. If the
                multiplier is 0.0 (DD > t3), the trade is BLOCKED (pause).
        """
        checks: list = []
        stop_distance = abs(signal.entry_price - signal.sl)
        if contract.digits > 0:
            stop_distance = round(stop_distance, contract.digits)

        # 1. Stop distance must be positive.
        if stop_distance <= 0:
            return RiskDecision(
                approved=False,
                reason="stop_distance<=0",
                blocked=True,
                checks=["stop_distance<=0"],
            )

        # 2. Stop distance must respect broker stops_level (min distance).
        if contract.stops_level > 0 and stop_distance < contract.stops_level:
            checks.append("stop_below_stops_level")
            return RiskDecision(
                approved=False,
                reason=f"stop_distance {stop_distance:.6f} < stops_level {contract.stops_level}",
                blocked=True,
                checks=checks,
            )

        # 3. Spread must not be excessive relative to stop distance.
        if spread > 0 and stop_distance > 0:
            if spread / stop_distance >= self.max_spread_ratio:
                checks.append("spread_too_high")
                return RiskDecision(
                    approved=False,
                    reason=(
                        f"spread {spread:.6f} >= "
                        f"{self.max_spread_ratio:.2f} * stop {stop_distance:.6f}"
                    ),
                    blocked=True,
                    checks=checks,
                )

        # 4. Risk per trade ceiling (uses actual lot).
        if lot > 0:
            risk_pct = self._risk_pct(signal, account, contract, lot)
            if risk_pct > self.max_risk_per_trade:
                checks.append("risk_per_trade_ceiling")
                return RiskDecision(
                    approved=False,
                    reason=f"risk_pct {risk_pct:.4f} > {self.max_risk_per_trade}",
                    blocked=True,
                    checks=checks,
                )
        else:
            risk_pct = 0.0

        # 5. Exposure cap (notional) must not be exceeded.
        if lot > 0:
            notional = lot * contract.contract_size * signal.entry_price
            if exposure + notional > account.equity * self.max_exposure_mult:
                checks.append("exposure_cap_exceeded")
                return RiskDecision(
                    approved=False,
                    reason=(
                        f"exposure {exposure + notional:.2f} > "
                        f"{account.equity * self.max_exposure_mult:.2f}"
                    ),
                    blocked=True,
                    checks=checks,
                )

        # 6. Portfolio DD scaling (Phase 11, mirrors exp_maxdd_C).
        # Compute the lot multiplier from current realized DD. If 0.0 -> pause.
        mult = compute_lot_multiplier(portfolio_dd_r)
        if mult <= 0.0:
            checks.append("portfolio_dd_pause")
            return RiskDecision(
                approved=False,
                reason=(f"portfolio DD {portfolio_dd_r:.2f}R > t3 " f"(PAUSE)"),
                blocked=True,
                checks=checks,
                lot_multiplier=0.0,
            )

        return RiskDecision(
            approved=True,
            reason="ok",
            stop_distance=stop_distance,
            risk_amount=account.balance * risk_pct,
            risk_pct=risk_pct,
            checks=checks,
            lot_multiplier=mult,
        )

    # -- helpers ---------------------------------------------------------

    def _risk_pct(
        self, signal: Signal, account: Account, contract, lot: float
    ) -> float:
        """Risk as a fraction of balance for the proposed `lot` size."""
        stop_distance = abs(signal.entry_price - signal.sl)
        if contract.digits > 0:
            stop_distance = round(stop_distance, contract.digits)
        if stop_distance <= 0 or account.balance <= 0:
            return 0.0
        ticks = stop_distance / contract.tick_size if contract.tick_size > 0 else 0.0
        loss = ticks * contract.tick_value * lot
        return loss / account.balance
