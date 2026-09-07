#!/usr/bin/env python
"""P1 — MIN LOT / MULTIPLIER SEMANTICS tests.

Forensic bug @ 721633f:
    base=0.01, mult=0.5, step=0.01, min=0.01
    raw=0.005 -> quantize=0 -> min clamp=0.01  (silent x1.0 risk!)

Fixed semantics:
    x1.0           -> normal lot (min clamp allowed for full size)
    x0.5 / x0.25   -> effective risk <= requested reduction, else BLOCK
    pause          -> no order
    unachievable   -> no order (never silently upgraded to x1.0)
"""

from __future__ import annotations

from src.live.sizing import PositionSizer

STEP, VMIN, VMAX = 0.01, 0.01, 100.0


def _scale(base, mult):
    return PositionSizer.apply_scaling_and_quantize(
        base_lot=base,
        lot_multiplier=mult,
        volume_step=STEP,
        volume_min=VMIN,
        volume_max=VMAX,
    )


def test_full_size_min_lot_entry_still_allowed():
    # mult == 1.0: base below min clamps up (full-size entry, no reduction).
    assert _scale(0.005, 1.0) == 0.01


def test_x05_unachievable_at_min_lot_blocks_trade():
    # THE forensic counterexample: DD says x0.5, broker min lot x1.0 -> BLOCK.
    assert _scale(0.01, 0.5) == 0.0


def test_x025_unachievable_at_min_lot_blocks_trade():
    assert _scale(0.01, 0.25) == 0.0


def test_x05_achievable_reduces_effective_risk():
    assert _scale(0.04, 0.5) == 0.02  # effective x0.5


def test_x025_achievable_reduces_effective_risk():
    assert _scale(0.04, 0.25) == 0.01  # effective x0.25


def test_quantize_down_keeps_effective_within_reduction():
    # 0.03 * 0.5 = 0.015 -> quantize down to 0.01 (effective x0.333 <= x0.5).
    lot = _scale(0.03, 0.5)
    assert lot == 0.01
    assert lot <= 0.03 * 0.5 + 1e-9, "effective risk must never exceed reduction"


def test_pause_yields_no_order():
    assert _scale(0.10, 0.0) == 0.0


def test_effective_multiplier_never_silently_rises_to_x1():
    for base in (0.01, 0.015, 0.02):
        for mult in (0.5, 0.25):
            lot = _scale(base, mult)
            raw = base * mult
            if raw < VMIN:
                assert lot == 0.0, f"base={base} mult={mult} must BLOCK"
            else:
                assert 0 < lot <= raw + 1e-9
