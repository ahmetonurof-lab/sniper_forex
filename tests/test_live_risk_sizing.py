#!/usr/bin/env python
"""PHASE 4 — RISK + POSITION SIZING — synthetic unit tests.

Covers:
- Lot calculation (standard MT5 formula).
- Volume min/max clamping.
- Volume step rounding.
- Risk check: stop below broker stops_level -> NO trade.
- Risk check: excessive spread -> NO trade.
- Risk check: exposure cap -> NO trade.
- Risk check: risk-per-trade ceiling -> NO trade.
- Acceptance: if a risk check fails -> NO trade (blocked + logged).
"""

import pandas as pd

from src.live.risk import Account, RiskManager
from src.live.sizing import ContractSpec, PositionSizer
from src.live.strategy_runtime import Signal


def _signal(
    entry=1.10000,
    sl=1.09500,
    tp=1.10900,
    direction="bullish",
    symbol="EURUSD",
) -> Signal:
    return Signal(
        symbol=symbol,
        direction=direction,
        side="long" if direction == "bullish" else "short",
        entry_price=entry,
        sl=sl,
        tp=tp,
        entry_bar_index=100,
        sweep_bar_index=90,
        zone_index=95,
        zone_top=1.10100,
        zone_bottom=1.09900,
        zone_size=0.00200,
        timestamp=pd.Timestamp("2026-08-27 19:00:00"),
    )


def _contract(**overrides) -> ContractSpec:
    base = dict(
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
    base.update(overrides)
    return ContractSpec(**base)


def _account(balance=10000.0, equity=10000.0) -> Account:
    return Account(balance=balance, equity=equity)


# ── Lot calculation ──────────────────────────────────────────────


def test_lot_calculation_standard_formula():
    # stop = 0.00500, tick_size=0.00001 -> 500 ticks, tick_value=1.0
    # loss_per_lot = 500 * 1.0 = 500
    # risk = 10000 * 0.003 = 30 -> lot = 30 / 500 = 0.06
    sizer = PositionSizer(risk_per_trade=0.003)
    res = sizer.compute_lot(_signal(), balance=10000.0, contract=_contract())
    assert res.lot == 0.06
    assert res.risk_amount == 30.0
    assert res.loss_per_lot == 500.0
    assert res.reason == "ok"


def test_lot_rounds_down_to_volume_step():
    # stop = 0.00333 -> 333 ticks -> loss_per_lot = 333
    # risk = 30 -> lot = 30/333 = 0.09009... -> round down to 0.09
    sizer = PositionSizer(risk_per_trade=0.003)
    res = sizer.compute_lot(
        _signal(entry=1.10000, sl=1.09667),
        balance=10000.0,
        contract=_contract(),
    )
    assert res.lot == 0.09


def test_lot_clamped_to_volume_min():
    # stop = 0.05 -> 5000 ticks -> loss_per_lot = 5000
    # risk = 30 -> lot = 30/5000 = 0.006 -> clamp up to volume_min 0.01
    sizer = PositionSizer(risk_per_trade=0.003)
    res = sizer.compute_lot(
        _signal(entry=1.10000, sl=1.05000),
        balance=10000.0,
        contract=_contract(volume_min=0.01),
    )
    assert res.lot == 0.01
    assert res.clamped is True


def test_lot_clamped_to_volume_max():
    # huge stop -> tiny lot -> clamp to volume_max (unlikely, but test)
    sizer = PositionSizer(risk_per_trade=0.003)
    res = sizer.compute_lot(
        _signal(entry=1.10000, sl=1.00000),
        balance=10000.0,
        contract=_contract(volume_max=0.01),
    )
    assert res.lot == 0.01
    assert res.clamped is True


def test_lot_zero_on_invalid_stop():
    sizer = PositionSizer(risk_per_trade=0.003)
    res = sizer.compute_lot(
        _signal(entry=1.10000, sl=1.10000),  # stop = 0
        balance=10000.0,
        contract=_contract(),
    )
    assert res.lot == 0.0
    assert res.reason == "stop_distance<=0"


def test_lot_zero_on_invalid_contract():
    sizer = PositionSizer(risk_per_trade=0.003)
    res = sizer.compute_lot(
        _signal(),
        balance=10000.0,
        contract=_contract(tick_size=0.0),
    )
    assert res.lot == 0.0
    assert res.reason == "invalid_contract_spec"


# ── Risk checks ──────────────────────────────────────────────────


def test_risk_approves_clean_signal():
    rm = RiskManager()
    dec = rm.evaluate(_signal(), _account(), _contract(), spread=0.0001, lot=0.06)
    assert dec.approved is True
    assert dec.blocked is False
    assert dec.stop_distance == 0.00500


def test_risk_blocks_stop_below_stops_level():
    rm = RiskManager()
    # stops_level = 0.00600 > stop 0.00500 -> block
    dec = rm.evaluate(
        _signal(), _account(), _contract(stops_level=0.00600), spread=0.0001, lot=0.06
    )
    assert dec.approved is False
    assert dec.blocked is True
    assert "stop_below_stops_level" in dec.checks


def test_risk_blocks_excessive_spread():
    rm = RiskManager(max_spread_ratio=0.5)
    # stop = 0.00500, spread = 0.00300 -> ratio 0.6 >= 0.5 -> block
    dec = rm.evaluate(_signal(), _account(), _contract(), spread=0.00300, lot=0.06)
    assert dec.approved is False
    assert dec.blocked is True
    assert "spread_too_high" in dec.checks


def test_risk_blocks_exposure_cap():
    rm = RiskManager(max_exposure_mult=0.05)
    # equity 10000 -> cap 500. notional = lot * contract_size * price
    # = 0.06 * 100000 * 1.1 = 6600 > 500 -> block.
    dec = rm.evaluate(
        _signal(), _account(), _contract(), spread=0.0001, exposure=0.0, lot=0.06
    )
    assert dec.approved is False
    assert dec.blocked is True
    assert "exposure_cap_exceeded" in dec.checks


def test_risk_blocks_risk_per_trade_ceiling():
    rm = RiskManager(max_risk_per_trade=0.01)
    # stop 0.00500 -> 500 ticks * 1.0 = 500 loss per lot; lot=1.0
    # -> risk_pct = 0.05 > 0.01 -> block (before exposure check).
    dec = rm.evaluate(_signal(), _account(), _contract(), spread=0.0001, lot=1.0)
    assert dec.approved is False
    assert dec.blocked is True
    assert "risk_per_trade_ceiling" in dec.checks


def test_risk_blocks_zero_stop():
    rm = RiskManager()
    dec = rm.evaluate(
        _signal(entry=1.10000, sl=1.10000),
        _account(),
        _contract(),
        spread=0.0001,
        lot=0.06,
    )
    assert dec.approved is False
    assert dec.blocked is True
    assert "stop_distance<=0" in dec.checks
