#!/usr/bin/env python
"""PHASE 11 — PORTFOLIO DD + DD-BASED RISK SCALING — synthetic unit tests.

Covers:
- PortfolioDD: zero state, no drawdown
- PortfolioDD: record realized profit (no DD, peak updated)
- PortfolioDD: record realized loss (DD > 0)
- PortfolioDD: recovery (DD shrinks after a new high)
- compute_lot_multiplier: default 1.0 when DD <= t1
- compute_lot_multiplier: 0.50 when t1 < DD <= t2
- compute_lot_multiplier: 0.25 when t2 < DD <= t3
- compute_lot_multiplier: 0.00 (PAUSE) when DD > t3
- compute_lot_multiplier: threshold boundary
- RiskManager.evaluate backward compat: dd_r=0 -> multiplier 1.0
- RiskManager.evaluate: dd_r=3 -> multiplier 0.50
- RiskManager.evaluate: dd_r=5 -> multiplier 0.25
- RiskManager.evaluate: dd_r=7 -> BLOCKED (pause, multiplier 0.0)
- RiskManager.evaluate: existing Phase 4 tests still pass (no dd_r arg)
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.live.portfolio_dd import (
    DEFAULT_T1,
    DEFAULT_T2,
    DEFAULT_T3,
    PortfolioDD,
    compute_lot_multiplier,
)
from src.live.risk import Account, RiskManager
from src.live.sizing import ContractSpec
from src.live.strategy_runtime import Signal

# ── Helpers ──────────────────────────────────────────────────────


def _signal(
    side: str = "long",
    entry: float = 1.10000,
    sl: float = 1.09500,
    tp: float = 1.10900,
) -> Signal:
    return Signal(
        symbol="EURUSD",
        direction="bullish" if side == "long" else "bearish",
        side=side,
        entry_price=entry,
        sl=sl,
        tp=tp,
        entry_bar_index=0,
        sweep_bar_index=0,
        zone_index=0,
        zone_top=entry + 0.001,
        zone_bottom=entry - 0.001,
        zone_size=0.002,
        timestamp=pd.Timestamp("2026-08-28 00:00:00"),
    )


def _contract() -> ContractSpec:
    return ContractSpec(
        symbol="EURUSD",
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        tick_size=0.00001,
        tick_value=1.0,
        contract_size=100000.0,
        stops_level=0.0,
        digits=5,
    )


# ── PortfolioDD ──────────────────────────────────────────────────


def test_portfolio_dd_zero_state():
    p = PortfolioDD()
    assert p.current_dd_r() == 0.0
    assert p.current_equity_r() == pytest.approx(100.0)


def test_portfolio_dd_record_profit_updates_peak():
    p = PortfolioDD(starting_balance_r=100.0)
    p.record_realized(+5.0)
    assert p.current_equity_r() == 105.0
    assert p.peak_r == 105.0
    assert p.current_dd_r() == 0.0


def test_portfolio_dd_record_loss_creates_dd():
    p = PortfolioDD(starting_balance_r=100.0)
    p.record_realized(-3.0)
    assert p.current_equity_r() == 97.0
    assert p.peak_r == 100.0
    assert p.current_dd_r() == pytest.approx(3.0)


def test_portfolio_dd_recovery_shrinks_dd():
    """After a new equity high, the DD relative to that new peak is 0."""
    p = PortfolioDD(starting_balance_r=100.0)
    p.record_realized(-5.0)  # dd=5
    assert p.current_dd_r() == pytest.approx(5.0)
    p.record_realized(+8.0)  # equity=103, peak=103
    assert p.current_dd_r() == 0.0
    assert p.peak_r == 103.0


def test_portfolio_dd_dd_never_negative():
    """current_dd_r is clamped to >=0 (peak-relative)."""
    p = PortfolioDD(starting_balance_r=100.0)
    p.record_realized(+100.0)  # way above
    p.record_realized(-10.0)  # equity=190, peak=200 -> dd=10
    assert p.current_dd_r() == pytest.approx(10.0)


# ── compute_lot_multiplier ──────────────────────────────────────


def test_multiplier_default_when_dd_zero():
    assert compute_lot_multiplier(0.0) == 1.0


def test_multiplier_default_when_dd_below_t1():
    assert compute_lot_multiplier(1.5) == 1.0
    assert compute_lot_multiplier(DEFAULT_T1) == 1.0  # boundary


def test_multiplier_half_when_dd_between_t1_and_t2():
    assert compute_lot_multiplier(2.5) == 0.50
    assert compute_lot_multiplier(DEFAULT_T2) == 0.50  # boundary


def test_multiplier_quarter_when_dd_between_t2_and_t3():
    assert compute_lot_multiplier(4.5) == 0.25
    assert compute_lot_multiplier(DEFAULT_T3) == 0.25  # boundary


def test_multiplier_pause_when_dd_above_t3():
    assert compute_lot_multiplier(7.0) == 0.0
    assert compute_lot_multiplier(100.0) == 0.0


def test_multiplier_custom_thresholds():
    """Custom t1/t2/t3 respected."""
    assert compute_lot_multiplier(0.5, t1=0.3, t2=0.6, t3=1.0) == 0.50
    assert compute_lot_multiplier(0.8, t1=0.3, t2=0.6, t3=1.0) == 0.25
    assert compute_lot_multiplier(1.5, t1=0.3, t2=0.6, t3=1.0) == 0.0


# ── RiskManager.evaluate with portfolio_dd_r ────────────────────


def test_risk_manager_default_dd_is_full_size():
    """No dd_r argument -> multiplier 1.0 (backward compat with Phase 4)."""
    rm = RiskManager()
    d = rm.evaluate(
        _signal(),
        account=Account(balance=10000.0, equity=10000.0),
        contract=_contract(),
        spread=0.00010,
    )
    assert d.approved is True
    assert d.lot_multiplier == 1.0


def test_risk_manager_explicit_dd_zero_full_size():
    rm = RiskManager()
    d = rm.evaluate(
        _signal(),
        account=Account(balance=10000.0, equity=10000.0),
        contract=_contract(),
        spread=0.00010,
        portfolio_dd_r=0.0,
    )
    assert d.approved is True
    assert d.lot_multiplier == 1.0


def test_risk_manager_dd_3R_half_size():
    rm = RiskManager()
    d = rm.evaluate(
        _signal(),
        account=Account(balance=10000.0, equity=10000.0),
        contract=_contract(),
        spread=0.00010,
        portfolio_dd_r=3.0,
    )
    assert d.approved is True
    assert d.lot_multiplier == 0.50


def test_risk_manager_dd_5R_quarter_size():
    rm = RiskManager()
    d = rm.evaluate(
        _signal(),
        account=Account(balance=10000.0, equity=10000.0),
        contract=_contract(),
        spread=0.00010,
        portfolio_dd_r=5.0,
    )
    assert d.approved is True
    assert d.lot_multiplier == 0.25


def test_risk_manager_dd_7R_pause_blocks_trade():
    """DD > t3 -> trade BLOCKED, multiplier 0.0."""
    rm = RiskManager()
    d = rm.evaluate(
        _signal(),
        account=Account(balance=10000.0, equity=10000.0),
        contract=_contract(),
        spread=0.00010,
        portfolio_dd_r=7.0,
    )
    assert d.approved is False
    assert d.blocked is True
    assert d.lot_multiplier == 0.0
    assert "portfolio_dd_pause" in d.checks


def test_risk_manager_dd_pause_does_not_trigger_when_other_check_fails():
    """If a more fundamental check fails first, the pause gate is
    evaluated only after the others pass (Phase 4 ordering preserved)."""
    rm = RiskManager()
    d = rm.evaluate(
        _signal(),  # default stop=0.005, spread 0.00010 -> ratio 0.02 < 0.5 OK
        account=Account(balance=10000.0, equity=10000.0),
        contract=_contract(),
        spread=0.10000,  # huge spread -> blocks before DD check
        portfolio_dd_r=7.0,  # would pause if reached
    )
    assert d.approved is False
    assert "spread_too_high" in d.checks


def test_risk_manager_dd_does_not_break_existing_phase4_paths():
    """All Phase 4 evaluate() returns with default dd_r (0.0) still work."""
    rm = RiskManager()
    # No dd_r arg at all -> defaults to 0.0
    d = rm.evaluate(
        _signal(),
        account=Account(balance=10000.0, equity=10000.0),
        contract=_contract(),
        spread=0.00010,
        lot=0.10,
    )
    assert d.approved is True
    assert d.lot_multiplier == 1.0
    assert d.risk_pct > 0
