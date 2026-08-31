#!/usr/bin/env python
"""P0-1 — Entry-time DD → scaled lot validation (minimal)."""

from src.live.sizing import ContractSpec, PositionSizer, SizingResult


def test_apply_scaling_quantizes_correctly():
    contract = ContractSpec(
        symbol="EURUSD",
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
    )
    # Base lot = 0.12; multiplier = 0.5 -> 0.06 (quantized exactly)
    scaled = PositionSizer.apply_scaling_and_quantize(
        base_lot=0.12,
        lot_multiplier=0.5,
        volume_step=contract.volume_step,
        volume_min=contract.volume_min,
        volume_max=contract.volume_max,
    )
    assert scaled == 0.06, f"expected 0.06 got {scaled}"

    # Multiplier 0.0 (pause) -> 0.0 (no order)
    scaled_pause = PositionSizer.apply_scaling_and_quantize(
        base_lot=0.12,
        lot_multiplier=0.0,
        volume_step=contract.volume_step,
        volume_min=contract.volume_min,
        volume_max=contract.volume_max,
    )
    assert scaled_pause == 0.0


def test_compute_lot_formula_unchanged():
    """The base sizing formula (compute_lot) is preserved; scaling is separate."""
    # Minimal structural check: compute_lot exists and returns SizingResult.
    sizer = PositionSizer()
    from src.live.strategy_runtime import Signal

    sig = Signal(
        symbol="EURUSD",
        direction="long",
        side="long",
        entry_price=1.10,
        sl=1.095,
        tp=1.109,
        entry_bar_index=0,
        sweep_bar_index=0,
        zone_index=0,
        zone_top=1.11,
        zone_bottom=1.09,
        zone_size=0.02,
        timestamp=None,
    )
    result = sizer.compute_lot(sig, balance=10000.0, contract=ContractSpec(symbol="EURUSD"))
    assert isinstance(result, SizingResult)
    assert result.lot >= 0.0
