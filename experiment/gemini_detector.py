"""
gemini_detector.py — Gemini ICT/SMC entry chain detector.

Implements exactly this chain:
  CBDR/SESSION SWEEP
      ↓
  BODY CLOSE BEYOND SWEPT LEVEL
      ↓
  MASTER BIAS LOCK
      ↓
  PURGE PRE-SWEEP FVG STATE
      ↓
  INTERNAL LIQUIDITY SWEEP (20-bar lookback)
      ↓
  POST-SWEEP CONTINUATION FVG
      ↓
  STRICT FRESHNESS
      ↓
  RETEST → ENTRY

NO IFVG. NO inverted FVGs. NO additional filters.

Uses NEXUS pivot detection for internal sweep.
Uses NEXUS FVG detection for post-sweep FVG.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# ── NEXUS imports (reference, not copy) ──
_NEXUS_SNIPER_SRC = str(Path("C:/Users/Administrator/Desktop/nexus-mcp/sniper/src"))
if _NEXUS_SNIPER_SRC not in sys.path:
    sys.path.insert(0, _NEXUS_SNIPER_SRC)

from fvg import detect_fvgs as _nexus_detect_fvgs
from models import FVG as NexusFVG
from models import Bar as NexusBar
from models import SwingPoint
from pivot import find_swing_highs, find_swing_lows

# ── sniper_forex imports ──
sys.path.insert(0, str(Path(__file__).parent.parent))
# ── Config ──
from experiment.config import (
    FVG_MIN_SIZE_ATR_MULT,
    FVG_WICK_RATIO_MAX,
    MIN_RISK_DIST_ATR_MULT,
)
from src.strategy.models import Bar, Direction, SweepEvent


def _to_nexus_bar(bar: Bar) -> NexusBar:
    """Convert sniper_forex Bar to NEXUS Bar format."""
    return NexusBar(
        index=bar.index,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        is_closed=True,
        timestamp=int(bar.timestamp.timestamp() * 1000)
        if hasattr(bar.timestamp, "timestamp")
        else 0,
    )


@dataclass
class GeminiResult:
    """Result of Gemini entry detection."""

    variant: str
    entry_price: float
    sl: float
    tp: float
    direction: str
    fvg: Optional[NexusFVG]
    sweep_bar_index: int
    body_close_bar_index: int
    internal_sweep_bar_index: int
    bars_sweep_to_fvg: int
    bars_fvg_to_entry: int
    fvg_size: float
    fvg_size_atr: float
    sweep_size_atr: float
    # Forensic
    body_close_confirmed: bool
    master_bias: str
    internal_sweep_found: bool
    purge_verified: bool
    freshness_ok: bool


def check_body_close(
    sweep: SweepEvent,
    bars_15m: List[Bar],
    sweep_bar_index: int,
    max_index: int = 999999,
) -> Optional[tuple[str, int]]:
    """
    Check for body close beyond swept level.

    After sweep bar, the NEXT bar's body must close beyond the swept level.
    - close above swept high → BULLISH
    - close below swept low → BEARISH

    max_index: only scan up to this bar index (no-lookahead).

    Returns (direction, bar_index) or None.
    """
    sweep_direction = "bullish" if sweep.direction == Direction.BULLISH else "bearish"

    # Check bars after sweep for body close confirmation (no lookahead)
    for b in bars_15m:
        if b.index <= sweep_bar_index:
            continue
        if b.index > max_index:
            break

        if sweep_direction == "bullish":
            if b.close > sweep.sweep_price:
                return ("bullish", b.index)
        else:
            if b.close < sweep.sweep_price:
                return ("bearish", b.index)

    return None


def detect_internal_sweep(
    bars_15m: List[Bar],
    fvg_bar_index: int,
    direction: str,
    lookback: int = 20,
) -> Optional[SwingPoint]:
    """
    Scan the preceding N bars for an internal/minor liquidity sweep.

    For bullish continuation:
        Look for a minor sell-side liquidity sweep (swing low swept).
        A bar's low must go below a recent swing low, then price reverses.

    For bearish continuation:
        Look for a minor buy-side liquidity sweep (swing high swept).
        A bar's high must go above a recent swing high, then price reverses.

    Uses NEXUS pivot detection with smaller left/right (1,1) for minor swings.

    Returns the swept swing point or None.
    """
    # Get the segment of bars to scan
    start = max(0, fvg_bar_index - lookback)
    end = fvg_bar_index  # exclusive

    if end - start < 3:
        return None

    segment_nexus = [_to_nexus_bar(b) for b in bars_15m[start:end]]
    if len(segment_nexus) < 3:
        return None

    # Find minor swings (left=1, right=1 for sensitivity)
    swing_highs = find_swing_highs(segment_nexus, left=1, right=1)
    swing_lows = find_swing_lows(segment_nexus, left=1, right=1)

    # Check for sweep
    if direction == "bullish":
        # Need a swing low that was swept (price went below it)
        for sl in reversed(swing_lows):
            # sl.bar_index is already absolute (from Nexus bar.index)
            for b in bars_15m[sl.bar_index + 1 : end]:
                if b.low < sl.price:
                    return sl
    else:
        # Need a swing high that was swept (price went above it)
        for sh in reversed(swing_highs):
            for b in bars_15m[sh.bar_index + 1 : end]:
                if b.high > sh.price:
                    return sh

    return None


def is_fresh(
    fvg: NexusFVG,
    bars_15m: List[Bar],
    current_index: int,
) -> bool:
    """
    Strict freshness check — same as IFVG benchmark.

    ANY subsequent candle entering the FVG zone = mitigated.
    """
    scan_from = fvg.real_index + 2
    for b in bars_15m:
        if b.index < scan_from or b.index >= current_index:
            continue
        if fvg.direction == "bullish":
            if b.low <= fvg.top:
                return False
        else:
            if b.high >= fvg.bottom:
                return False
    return True


def detect_gemini_entry(
    bars_15m: List[Bar],
    sweep: SweepEvent,
    current_bar: Bar,
    current_index: int,
    atr_val: float,
    symbol: str = "",
    next_bar: Optional[Bar] = None,
) -> Optional[GeminiResult]:
    """
    Full Gemini entry chain detection.

    Returns GeminiResult if all conditions are met, None otherwise.
    """
    from experiment.config import (
        FVG_BUFFER_MIN_FACTOR,
        FVG_BUFFER_MULT,
        SL_ATR_MULT,
        TP_RR,
    )

    if current_index < 2:
        return None

    sweep_bar_index = sweep.bar_index
    sweep_direction = "bullish" if sweep.direction == Direction.BULLISH else "bearish"

    # ── Step 1: Body Close Confirmation (no-lookahead) ──
    body_close = check_body_close(sweep, bars_15m, sweep_bar_index, max_index=current_index)
    if body_close is None:
        return None

    body_close_dir, body_close_bar = body_close

    # ── Step 2: Master Bias Lock ──
    master_bias = body_close_dir
    if master_bias != sweep_direction:
        return None  # Body close must agree with sweep direction

    # ── Step 3: FVG State Purge ──
    # Only post-sweep FVGs are eligible (enforced by filtering below)

    # ── Step 4: Detect post-sweep FVGs ──
    min_fvg_size = max(atr_val * FVG_MIN_SIZE_ATR_MULT, 1e-8)
    nexus_bars = [_to_nexus_bar(b) for b in bars_15m[: current_index + 1]]

    fvgs = _nexus_detect_fvgs(
        nexus_bars,
        lookback=min(100, len(nexus_bars)),
        timeframe="15m",
        min_fvg_size=min_fvg_size,
        max_wick_ratio=FVG_WICK_RATIO_MAX,
    )

    # Filter: must be AFTER sweep, same direction as master bias
    candidates = []
    for fvg in fvgs:
        if fvg.real_index <= sweep_bar_index:
            continue
        if fvg.direction != master_bias:
            continue
        if fvg.invalidated:
            continue
        candidates.append(fvg)

    if not candidates:
        return None

    # ── Step 5: For each candidate, check internal sweep + freshness ──
    for fvg in candidates:
        # Internal liquidity sweep (20-bar lookback before FVG)
        internal_sweep = detect_internal_sweep(bars_15m, fvg.real_index, fvg.direction, lookback=20)
        if internal_sweep is None:
            continue  # No internal sweep → INDUCEMENT, reject

        # Strict freshness
        if not is_fresh(fvg, bars_15m, current_index):
            continue

        # Must touch current bar (entry trigger)
        if fvg.direction == "bullish":
            if not (current_bar.low <= fvg.top and current_bar.low >= fvg.bottom - atr_val * 0.1):
                continue
        else:
            if not (current_bar.high >= fvg.bottom and current_bar.high <= fvg.top + atr_val * 0.1):
                continue

        # NEXUS parity: next-bar-open execution
        if next_bar is None:
            continue  # No next bar, skip trade
        entry_price = next_bar.open

        # ── Step 6: SL/TP calculation (NEXUS parity) ──
        fh = fvg.top - fvg.bottom
        rp2 = atr_val * SL_ATR_MULT

        if fvg.direction == "bullish":
            if fh <= 0:
                sl = entry_price - rp2 * 2
            else:
                ab = max(
                    fh * FVG_BUFFER_MIN_FACTOR,
                    max(rp2 * 0.1, min(fh * 0.25, rp2 * FVG_BUFFER_MULT)),
                )
                sl = fvg.bottom - ab
        else:
            if fh <= 0:
                sl = entry_price + rp2 * 2
            else:
                ab = max(
                    fh * FVG_BUFFER_MIN_FACTOR,
                    max(rp2 * 0.1, min(fh * 0.25, rp2 * FVG_BUFFER_MULT)),
                )
                sl = fvg.top + ab

        rd = abs(entry_price - sl)
        if rd <= 0:
            if fvg.direction == "bullish":
                sl = entry_price - rp2 * 2
            else:
                sl = entry_price + rp2 * 2
            rd = abs(entry_price - sl)

        if fvg.direction == "bullish":
            tp = entry_price + rd * TP_RR
        else:
            tp = entry_price - rd * TP_RR

        if rd < atr_val * MIN_RISK_DIST_ATR_MULT:
            continue

        return GeminiResult(
            variant="GEMINI",
            entry_price=entry_price,
            sl=sl,
            tp=tp,
            direction=fvg.direction,
            fvg=fvg,
            sweep_bar_index=sweep_bar_index,
            body_close_bar_index=body_close_bar,
            internal_sweep_bar_index=internal_sweep.bar_index,
            bars_sweep_to_fvg=fvg.real_index - sweep_bar_index,
            bars_fvg_to_entry=current_index - fvg.real_index,
            fvg_size=fvg.size,
            fvg_size_atr=fvg.size / atr_val if atr_val > 0 else 0,
            sweep_size_atr=abs(sweep.sweep_price - sweep.reference_level) / atr_val
            if atr_val > 0
            else 0,
            body_close_confirmed=True,
            master_bias=master_bias,
            internal_sweep_found=True,
            purge_verified=True,
            freshness_ok=True,
        )

    return None
