#!/usr/bin/env python
"""PHASE 4 — POSITION SIZING (lot calculation).

Computes the lot size for a `Signal` given account balance, risk-per-trade and
broker contract specs. Pure / injectable: no MT5 dependency.

Reference: `RISK_PER_TRADE = 0.003` in `experiment/config.py`.

Lot formula (standard MT5):
    risk_amount   = balance * risk_per_trade
    stop_distance = |entry - sl|                       (price units)
    ticks         = stop_distance / tick_size
    loss_per_lot  = ticks * tick_value                 (per 1.0 lot)
    lot           = risk_amount / loss_per_lot
    lot           = clamp to [volume_min, volume_max], rounded down to volume_step
"""

from __future__ import annotations

from dataclasses import dataclass

from src.live.strategy_runtime import Signal


@dataclass
class ContractSpec:
    """Broker contract specification for a symbol (from MT5 symbol_info)."""

    symbol: str
    volume_min: float = 0.01
    volume_max: float = 100.0
    volume_step: float = 0.01
    tick_size: float = 0.00001
    tick_value: float = 1.0
    contract_size: float = 100000.0
    stops_level: float = 0.0  # min stop distance in price units (0 = none)
    digits: int = 5


@dataclass
class SizingResult:
    """Result of a lot-size computation."""

    lot: float
    risk_amount: float
    stop_distance: float
    loss_per_lot: float
    clamped: bool = False
    reason: str = "ok"


class PositionSizer:
    """Compute lot size from a signal + account + contract specs."""

    def __init__(self, risk_per_trade: float = 0.003):
        self.risk_per_trade = risk_per_trade

    def compute_lot(
        self,
        signal: Signal,
        balance: float,
        contract: ContractSpec,
    ) -> SizingResult:
        """Compute the lot size for `signal`.

        Returns a SizingResult. If the stop distance is invalid (<= 0) or the
        contract is degenerate (tick_size/tick_value <= 0), `lot` is 0 and
        `reason` explains why (caller must NOT trade).
        """
        stop_distance = abs(signal.entry_price - signal.sl)
        # Round to the symbol's digits to avoid float drift (e.g. 0.0050000...115).
        if contract.digits > 0:
            stop_distance = round(stop_distance, contract.digits)
        if stop_distance <= 0:
            return SizingResult(
                lot=0.0,
                risk_amount=0.0,
                stop_distance=0.0,
                loss_per_lot=0.0,
                reason="stop_distance<=0",
            )
        if contract.tick_size <= 0 or contract.tick_value <= 0:
            return SizingResult(
                lot=0.0,
                risk_amount=0.0,
                stop_distance=stop_distance,
                loss_per_lot=0.0,
                reason="invalid_contract_spec",
            )

        risk_amount = balance * self.risk_per_trade
        ticks = stop_distance / contract.tick_size
        loss_per_lot = round(ticks * contract.tick_value, 10)
        if loss_per_lot <= 0:
            return SizingResult(
                lot=0.0,
                risk_amount=risk_amount,
                stop_distance=stop_distance,
                loss_per_lot=0.0,
                reason="loss_per_lot<=0",
            )

        lot = risk_amount / loss_per_lot
        lot = self._round_to_step(lot, contract.volume_step)
        clamped = False
        if lot < contract.volume_min:
            lot = contract.volume_min
            clamped = True
        elif lot > contract.volume_max:
            lot = contract.volume_max
            clamped = True

        return SizingResult(
            lot=lot,
            risk_amount=risk_amount,
            stop_distance=stop_distance,
            loss_per_lot=loss_per_lot,
            clamped=clamped,
            reason="ok",
        )

    @staticmethod
    def _round_to_step(lot: float, step: float) -> float:
        """Round `lot` down to the nearest multiple of `step`."""
        if step <= 0:
            return lot
        return round(int(lot / step) * step, 10)
