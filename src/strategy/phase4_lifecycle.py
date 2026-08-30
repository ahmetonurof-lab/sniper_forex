#!/usr/bin/env python
"""PHASE 4 — SWEEP LIFECYCLE FORENSICS

Reconstructs the full event chain for every trade in the baseline strategy:
  sweep_event → FVG → entry → exit

Then runs counterfactual experiments (ONE-SHOT, FRESH-SWEEP).

Does NOT modify production code.
"""

import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.strategy.entry import calculate_sl_tp, detect_first_touch
from src.strategy.fvg import detect_fvg
from src.strategy.models import (
    FVG,
    Bar,
    CBDRState,
    Direction,
    SweepEvent,
    TradeResult,
    TradeSetup,
)
from src.strategy.session import SessionManager
from src.strategy.strategy import calculate_atr
from src.strategy.trade_simulator import TradeSimulator

# ============================================================
# LIQUIDITY SOURCE DEFINITIONS (from Phase 3.2)
# ============================================================


class LiquiditySource(Enum):
    CBDR = "CBDR"
    SESSION_HL = "SESSION_HL"
    SWING_HL = "SWING_HL"
    UNKNOWN = "UNKNOWN"


def detect_session_hl_levels(bars: List[Bar], window: int = 50) -> List[Dict]:
    """Detect session high/low levels (daily high/low).
    NEWLY DEFINED FOR THIS ANALYSIS — not in baseline strategy.
    """
    levels = []
    current_date = None
    day_bars = []

    for bar in bars:
        bar_date = bar.timestamp.date()
        if bar_date != current_date:
            if day_bars and current_date is not None:
                day_high = max(b.high for b in day_bars)
                day_low = min(b.low for b in day_bars)
                levels.append(
                    {
                        "source": LiquiditySource.SESSION_HL,
                        "high": day_high,
                        "low": day_low,
                        "date": str(current_date),
                        "bar_start": day_bars[0].index,
                        "bar_end": day_bars[-1].index,
                    }
                )
            current_date = bar_date
            day_bars = [bar]
        else:
            day_bars.append(bar)

    if day_bars and current_date is not None:
        day_high = max(b.high for b in day_bars)
        day_low = min(b.low for b in day_bars)
        levels.append(
            {
                "source": LiquiditySource.SESSION_HL,
                "high": day_high,
                "low": day_low,
                "date": str(current_date),
                "bar_start": day_bars[0].index,
                "bar_end": day_bars[-1].index,
            }
        )
    return levels


def detect_swing_hl_levels(bars: List[Bar], lookback: int = 50) -> List[Dict]:
    """Detect swing high/low levels (N-bar pivot).
    NEWLY DEFINED FOR THIS ANALYSIS — not in baseline strategy.
    """
    levels = []
    for i in range(lookback, len(bars)):
        window = bars[i - lookback : i]
        swing_high = max(b.high for b in window)
        swing_low = min(b.low for b in window)
        levels.append(
            {
                "source": LiquiditySource.SWING_HL,
                "high": swing_high,
                "low": swing_low,
                "bar_index": i,
            }
        )
    return levels


def classify_sweep_source(
    sweep: SweepEvent,
    cbdr_state: Optional[CBDRState],
    session_levels: List[Dict],
    swing_levels: List[Dict],
    tolerance: float,
) -> LiquiditySource:
    """Classify which liquidity source a sweep event came from."""
    # Check CBDR first
    if cbdr_state and cbdr_state.body_high > 0 and cbdr_state.body_low < float("inf"):
        if sweep.direction == Direction.BEARISH:
            if abs(sweep.reference_level - cbdr_state.body_high) < tolerance * 0.1:
                return LiquiditySource.CBDR
        elif sweep.direction == Direction.BULLISH:
            if abs(sweep.reference_level - cbdr_state.body_low) < tolerance * 0.1:
                return LiquiditySource.CBDR

    # Check SESSION_HL
    for level in session_levels[-20:]:
        if sweep.direction == Direction.BEARISH:
            if abs(sweep.reference_level - level["high"]) < tolerance * 0.1:
                return LiquiditySource.SESSION_HL
        elif sweep.direction == Direction.BULLISH:
            if abs(sweep.reference_level - level["low"]) < tolerance * 0.1:
                return LiquiditySource.SESSION_HL

    # Check SWING_HL
    for level in swing_levels[-20:]:
        if sweep.direction == Direction.BEARISH:
            if abs(sweep.reference_level - level["high"]) < tolerance * 0.1:
                return LiquiditySource.SWING_HL
        elif sweep.direction == Direction.BULLISH:
            if abs(sweep.reference_level - level["low"]) < tolerance * 0.1:
                return LiquiditySource.SWING_HL

    return LiquiditySource.UNKNOWN


# ============================================================
# ENHANCED STRATEGY ENGINE — TRACKS FULL EVENT CHAIN
# ============================================================


@dataclass
class TradeRecord:
    """Full event chain for one trade."""

    trade_id: int
    symbol: str
    sweep_id: int  # Unique sweep event ID
    sweep_ordinal: int  # 1st, 2nd, 3rd trade from this sweep
    sweep_timestamp: pd.Timestamp
    sweep_bar_index: int
    sweep_direction: str
    sweep_price: float
    sweep_reference_level: float
    sweep_liquidity_source: str  # CBDR, SESSION_HL, SWING_HL, UNKNOWN
    fvg_index: int
    fvg_timestamp: pd.Timestamp
    fvg_high: float
    fvg_low: float
    fvg_size: float
    fvg_direction: str
    entry_timestamp: pd.Timestamp
    entry_bar_index: int
    entry_price: float
    entry_type: str
    sl: float
    tp: float
    exit_timestamp: Optional[pd.Timestamp] = None
    exit_price: float = 0.0
    result: str = ""
    pnl_r: float = 0.0
    # Timing
    bars_sweep_to_fvg: int = 0
    bars_sweep_to_entry: int = 0
    bars_fvg_to_entry: int = 0
    fvg_timing: str = ""  # "after_sweep", "at_sweep", "before_sweep"


def run_strategy_with_tracking(
    symbol: str,
    bars: List[Bar],
    rr_ratio: float = 1.8,
    sweep_atr_mult: float = 0.5,
    default_tolerance: float = 0.001,
) -> List[TradeRecord]:
    """Run strategy and track full event chain for every trade."""

    if len(bars) < 100:
        return []

    atr = calculate_atr(bars[:100], period=14)
    tolerance = atr * sweep_atr_mult if atr > 0 else default_tolerance

    session = SessionManager(
        symbol=symbol,
        start_hour=19,
        end_hour=1,
        atr=atr,
        sweep_atr_tolerance_mult=sweep_atr_mult,
        sweep_default_tolerance=default_tolerance,
    )
    session.atr = atr
    simulator = TradeSimulator(symbol)

    # State tracking
    sweep_counter = 0
    sweep_events = {}  # sweep_bar_index → SweepEvent
    sweep_trade_count = defaultdict(int)  # sweep_bar_index → trade count
    current_sweep: Optional[SweepEvent] = None
    current_fvgs: List[FVG] = []
    in_trade = False
    current_trade = None
    entry_bar_index = None
    trade_records = []

    for i, bar in enumerate(bars):
        # 1. If in trade, simulate exit
        if in_trade and current_trade:
            simulator.simulate_exit(current_trade, bars, i)
            if current_trade.result != TradeResult.OPEN:
                # Record the trade
                sweep_bi = current_trade.sweep_index
                sweep_trade_count[sweep_bi] += 1
                ordinal = sweep_trade_count[sweep_bi]
                sweep_ev = sweep_events.get(sweep_bi)

                # FVG timing classification
                if sweep_ev:
                    fvg_before = current_trade.fvg_index < sweep_ev.bar_index
                    fvg_at = current_trade.fvg_index == sweep_ev.bar_index
                    fvg_after = current_trade.fvg_index > sweep_ev.bar_index
                    if fvg_before:
                        fvg_timing = "before_sweep"
                    elif fvg_at:
                        fvg_timing = "at_sweep"
                    else:
                        fvg_timing = "after_sweep"

                    bars_s2f = current_trade.fvg_index - sweep_ev.bar_index
                    bars_s2e = i - sweep_ev.bar_index
                    bars_f2e = i - current_trade.fvg_index
                else:
                    fvg_timing = "unknown"
                    bars_s2f = 0
                    bars_s2e = 0
                    bars_f2e = 0

                # Classify liquidity source
                source = (
                    classify_sweep_source(
                        sweep_ev,
                        session.cbdr,
                        [],
                        [],
                        tolerance,  # Simplified — full classification done later
                    )
                    if sweep_ev
                    else LiquiditySource.UNKNOWN
                )

                rec = TradeRecord(
                    trade_id=current_trade.trade_id,
                    symbol=symbol,
                    sweep_id=sweep_bi,
                    sweep_ordinal=ordinal,
                    sweep_timestamp=sweep_ev.timestamp if sweep_ev else bar.timestamp,
                    sweep_bar_index=sweep_bi,
                    sweep_direction=sweep_ev.direction.value if sweep_ev else "",
                    sweep_price=sweep_ev.sweep_price if sweep_ev else 0.0,
                    sweep_reference_level=sweep_ev.reference_level if sweep_ev else 0.0,
                    sweep_liquidity_source=source.value,
                    fvg_index=current_trade.fvg_index,
                    fvg_timestamp=current_trade.fvg_time
                    if current_trade.fvg_time
                    else bar.timestamp,
                    fvg_high=current_trade.fvg_high,
                    fvg_low=current_trade.fvg_low,
                    fvg_size=current_trade.fvg_size,
                    fvg_direction=current_trade.direction.value,
                    entry_timestamp=current_trade.entry_time
                    if current_trade.entry_time
                    else bar.timestamp,
                    entry_bar_index=entry_bar_index if entry_bar_index else i,
                    entry_price=current_trade.entry_price,
                    entry_type=current_trade.entry_type.value,
                    sl=current_trade.sl,
                    tp=current_trade.tp,
                    exit_timestamp=current_trade.exit_time,
                    exit_price=current_trade.exit_price,
                    result=current_trade.result.value,
                    pnl_r=current_trade.pnl_r,
                    bars_sweep_to_fvg=bars_s2f,
                    bars_sweep_to_entry=bars_s2e,
                    bars_fvg_to_entry=bars_f2e,
                    fvg_timing=fvg_timing,
                )
                trade_records.append(rec)

                # Reset
                in_trade = False
                current_trade = None
                entry_bar_index = None
                current_sweep = None
                current_fvgs = []
            continue

        # 2. Session update (CBDR + sweep)
        sweep = session.update(bar)

        if sweep is not None:
            sweep_counter += 1
            sweep_events[sweep.bar_index] = sweep
            current_sweep = sweep
            current_fvgs = []

        # 3. If sweep detected, look for FVGs
        if current_sweep is not None:
            start_idx = current_sweep.bar_index + 1
            if i >= start_idx + 2:
                fvg = detect_fvg(bars, i, session.cbdr.daily_bias, symbol)
                if fvg and fvg.fvg_index > current_sweep.bar_index:
                    if not current_fvgs:
                        current_fvgs.append(fvg)

        # 4. If FVG found, check for first touch
        if current_fvgs and not in_trade:
            fvg = current_fvgs[0]
            entry_type = detect_first_touch(bar, fvg, session.cbdr.daily_bias, current_sweep)

            if entry_type:
                sl, tp, entry_price = calculate_sl_tp(fvg, fvg.direction, rr_ratio)
                setup = TradeSetup(
                    symbol=symbol,
                    sweep=current_sweep,
                    fvg=fvg,
                    entry_type=entry_type,
                    direction=fvg.direction,
                    sl=sl,
                    tp=tp,
                    entry_price=entry_price,
                    entry_time=bar.timestamp,
                )
                current_trade = simulator.create_trade(
                    setup,
                    bars,
                    cbdr_high=session.cbdr.body_high,
                    cbdr_low=session.cbdr.body_low,
                )
                in_trade = True
                entry_bar_index = i

    return trade_records


# ============================================================
# COUNTERFACTUAL ENGINES
# ============================================================


def run_one_shot_strategy(
    symbol: str,
    bars: List[Bar],
    rr_ratio: float = 1.8,
    sweep_atr_mult: float = 0.5,
    default_tolerance: float = 0.001,
) -> List[TradeRecord]:
    """ONE-SHOT: one sweep → first eligible FVG only."""

    if len(bars) < 100:
        return []

    atr = calculate_atr(bars[:100], period=14)
    tolerance = atr * sweep_atr_mult if atr > 0 else default_tolerance

    session = SessionManager(
        symbol=symbol,
        start_hour=19,
        end_hour=1,
        atr=atr,
        sweep_atr_tolerance_mult=sweep_atr_mult,
        sweep_default_tolerance=default_tolerance,
    )
    session.atr = atr
    simulator = TradeSimulator(symbol)

    sweep_counter = 0
    current_sweep: Optional[SweepEvent] = None
    fvg_found_for_sweep = False  # KEY DIFFERENCE: track if we already found an FVG for this sweep
    current_fvgs: List[FVG] = []
    in_trade = False
    current_trade = None
    entry_bar_index = None
    trade_records = []
    sweep_events = {}
    sweep_trade_count = defaultdict(int)

    for i, bar in enumerate(bars):
        if in_trade and current_trade:
            simulator.simulate_exit(current_trade, bars, i)
            if current_trade.result != TradeResult.OPEN:
                sweep_bi = current_trade.sweep_index
                sweep_trade_count[sweep_bi] += 1
                ordinal = sweep_trade_count[sweep_bi]
                sweep_ev = sweep_events.get(sweep_bi)

                if sweep_ev:
                    fvg_timing = (
                        "after_sweep"
                        if current_trade.fvg_index > sweep_ev.bar_index
                        else (
                            "at_sweep"
                            if current_trade.fvg_index == sweep_ev.bar_index
                            else "before_sweep"
                        )
                    )
                    bars_s2f = current_trade.fvg_index - sweep_ev.bar_index
                    bars_s2e = i - sweep_ev.bar_index
                    bars_f2e = i - current_trade.fvg_index
                else:
                    fvg_timing = "unknown"
                    bars_s2f = bars_s2e = bars_f2e = 0

                rec = TradeRecord(
                    trade_id=current_trade.trade_id,
                    symbol=symbol,
                    sweep_id=sweep_bi,
                    sweep_ordinal=ordinal,
                    sweep_timestamp=sweep_ev.timestamp if sweep_ev else bar.timestamp,
                    sweep_bar_index=sweep_bi,
                    sweep_direction=sweep_ev.direction.value if sweep_ev else "",
                    sweep_price=sweep_ev.sweep_price if sweep_ev else 0.0,
                    sweep_reference_level=sweep_ev.reference_level if sweep_ev else 0.0,
                    sweep_liquidity_source="ONE_SHOT",
                    fvg_index=current_trade.fvg_index,
                    fvg_timestamp=current_trade.fvg_time
                    if current_trade.fvg_time
                    else bar.timestamp,
                    fvg_high=current_trade.fvg_high,
                    fvg_low=current_trade.fvg_low,
                    fvg_size=current_trade.fvg_size,
                    fvg_direction=current_trade.direction.value,
                    entry_timestamp=current_trade.entry_time
                    if current_trade.entry_time
                    else bar.timestamp,
                    entry_bar_index=entry_bar_index if entry_bar_index else i,
                    entry_price=current_trade.entry_price,
                    entry_type=current_trade.entry_type.value,
                    sl=current_trade.sl,
                    tp=current_trade.tp,
                    exit_timestamp=current_trade.exit_time,
                    exit_price=current_trade.exit_price,
                    result=current_trade.result.value,
                    pnl_r=current_trade.pnl_r,
                    bars_sweep_to_fvg=bars_s2f,
                    bars_sweep_to_entry=bars_s2e,
                    bars_fvg_to_entry=bars_f2e,
                    fvg_timing=fvg_timing,
                )
                trade_records.append(rec)

                in_trade = False
                current_trade = None
                entry_bar_index = None
                current_sweep = None
                current_fvgs = []
                fvg_found_for_sweep = False
            continue

        sweep = session.update(bar)

        if sweep is not None:
            sweep_counter += 1
            sweep_events[sweep.bar_index] = sweep
            current_sweep = sweep
            current_fvgs = []
            fvg_found_for_sweep = False  # NEW SWEEP → reset FVG flag

        if current_sweep is not None:
            start_idx = current_sweep.bar_index + 1
            if i >= start_idx + 2:
                fvg = detect_fvg(bars, i, session.cbdr.daily_bias, symbol)
                if fvg and fvg.fvg_index > current_sweep.bar_index:
                    if not current_fvgs:
                        current_fvgs.append(fvg)
                        fvg_found_for_sweep = True

        if current_fvgs and not in_trade and fvg_found_for_sweep:
            fvg = current_fvgs[0]
            entry_type = detect_first_touch(bar, fvg, session.cbdr.daily_bias, current_sweep)
            if entry_type:
                sl, tp, entry_price = calculate_sl_tp(fvg, fvg.direction, rr_ratio)
                setup = TradeSetup(
                    symbol=symbol,
                    sweep=current_sweep,
                    fvg=fvg,
                    entry_type=entry_type,
                    direction=fvg.direction,
                    sl=sl,
                    tp=tp,
                    entry_price=entry_price,
                    entry_time=bar.timestamp,
                )
                current_trade = simulator.create_trade(
                    setup,
                    bars,
                    cbdr_high=session.cbdr.body_high,
                    cbdr_low=session.cbdr.body_low,
                )
                in_trade = True
                entry_bar_index = i

    return trade_records


def run_fresh_sweep_strategy(
    symbol: str,
    bars: List[Bar],
    rr_ratio: float = 1.8,
    sweep_atr_mult: float = 0.5,
    default_tolerance: float = 0.001,
) -> List[TradeRecord]:
    """FRESH-SWEEP: new trade requires new sweep."""

    if len(bars) < 100:
        return []

    atr = calculate_atr(bars[:100], period=14)
    tolerance = atr * sweep_atr_mult if atr > 0 else default_tolerance

    session = SessionManager(
        symbol=symbol,
        start_hour=19,
        end_hour=1,
        atr=atr,
        sweep_atr_tolerance_mult=sweep_atr_mult,
        sweep_default_tolerance=default_tolerance,
    )
    session.atr = atr
    simulator = TradeSimulator(symbol)

    sweep_counter = 0
    current_sweep: Optional[SweepEvent] = None
    current_fvgs: List[FVG] = []
    in_trade = False
    current_trade = None
    entry_bar_index = None
    trade_records = []
    sweep_events = {}
    sweep_trade_count = defaultdict(int)
    sweep_used = set()  # Track which sweeps have been used

    for i, bar in enumerate(bars):
        if in_trade and current_trade:
            simulator.simulate_exit(current_trade, bars, i)
            if current_trade.result != TradeResult.OPEN:
                sweep_bi = current_trade.sweep_index
                sweep_trade_count[sweep_bi] += 1
                ordinal = sweep_trade_count[sweep_bi]
                sweep_ev = sweep_events.get(sweep_bi)

                if sweep_ev:
                    fvg_timing = (
                        "after_sweep"
                        if current_trade.fvg_index > sweep_ev.bar_index
                        else (
                            "at_sweep"
                            if current_trade.fvg_index == sweep_ev.bar_index
                            else "before_sweep"
                        )
                    )
                    bars_s2f = current_trade.fvg_index - sweep_ev.bar_index
                    bars_s2e = i - sweep_ev.bar_index
                    bars_f2e = i - current_trade.fvg_index
                else:
                    fvg_timing = "unknown"
                    bars_s2f = bars_s2e = bars_f2e = 0

                rec = TradeRecord(
                    trade_id=current_trade.trade_id,
                    symbol=symbol,
                    sweep_id=sweep_bi,
                    sweep_ordinal=ordinal,
                    sweep_timestamp=sweep_ev.timestamp if sweep_ev else bar.timestamp,
                    sweep_bar_index=sweep_bi,
                    sweep_direction=sweep_ev.direction.value if sweep_ev else "",
                    sweep_price=sweep_ev.sweep_price if sweep_ev else 0.0,
                    sweep_reference_level=sweep_ev.reference_level if sweep_ev else 0.0,
                    sweep_liquidity_source="FRESH_SWEEP",
                    fvg_index=current_trade.fvg_index,
                    fvg_timestamp=current_trade.fvg_time
                    if current_trade.fvg_time
                    else bar.timestamp,
                    fvg_high=current_trade.fvg_high,
                    fvg_low=current_trade.fvg_low,
                    fvg_size=current_trade.fvg_size,
                    fvg_direction=current_trade.direction.value,
                    entry_timestamp=current_trade.entry_time
                    if current_trade.entry_time
                    else bar.timestamp,
                    entry_bar_index=entry_bar_index if entry_bar_index else i,
                    entry_price=current_trade.entry_price,
                    entry_type=current_trade.entry_type.value,
                    sl=current_trade.sl,
                    tp=current_trade.tp,
                    exit_timestamp=current_trade.exit_time,
                    exit_price=current_trade.exit_price,
                    result=current_trade.result.value,
                    pnl_r=current_trade.pnl_r,
                    bars_sweep_to_fvg=bars_s2f,
                    bars_sweep_to_entry=bars_s2e,
                    bars_fvg_to_entry=bars_f2e,
                    fvg_timing=fvg_timing,
                )
                trade_records.append(rec)

                # Mark sweep as used
                sweep_used.add(sweep_bi)

                in_trade = False
                current_trade = None
                entry_bar_index = None
                current_sweep = None
                current_fvgs = []
            continue

        sweep = session.update(bar)

        if sweep is not None:
            sweep_counter += 1
            sweep_events[sweep.bar_index] = sweep
            current_sweep = sweep
            current_fvgs = []

        if current_sweep is not None:
            # FRESH-SWEEP: only use sweep if not already used
            if current_sweep.bar_index in sweep_used:
                continue  # Skip — this sweep was already used

            start_idx = current_sweep.bar_index + 1
            if i >= start_idx + 2:
                fvg = detect_fvg(bars, i, session.cbdr.daily_bias, symbol)
                if fvg and fvg.fvg_index > current_sweep.bar_index:
                    if not current_fvgs:
                        current_fvgs.append(fvg)

        if current_fvgs and not in_trade:
            # FRESH-SWEEP: only enter if sweep not already used
            if current_sweep and current_sweep.bar_index in sweep_used:
                continue

            fvg = current_fvgs[0]
            entry_type = detect_first_touch(bar, fvg, session.cbdr.daily_bias, current_sweep)
            if entry_type:
                sl, tp, entry_price = calculate_sl_tp(fvg, fvg.direction, rr_ratio)
                setup = TradeSetup(
                    symbol=symbol,
                    sweep=current_sweep,
                    fvg=fvg,
                    entry_type=entry_type,
                    direction=fvg.direction,
                    sl=sl,
                    tp=tp,
                    entry_price=entry_price,
                    entry_time=bar.timestamp,
                )
                current_trade = simulator.create_trade(
                    setup,
                    bars,
                    cbdr_high=session.cbdr.body_high,
                    cbdr_low=session.cbdr.body_low,
                )
                in_trade = True
                entry_bar_index = i

    return trade_records


# ============================================================
# STATISTICS HELPERS
# ============================================================


def calc_stats(trades: List[TradeRecord]) -> Dict:
    """Calculate aggregate stats for a list of trades."""
    if not trades:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "open": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "total_pnl": 0.0,
            "avg_r": 0.0,
            "median_r": 0.0,
            "max_drawdown": 0.0,
            "expectancy": 0.0,
        }

    completed = [t for t in trades if t.result in ("win", "loss")]
    wins = [t for t in completed if t.result == "win"]
    losses = [t for t in completed if t.result == "loss"]
    open_trades = [t for t in trades if t.result == "open"]

    total_pnl = sum(t.pnl_r for t in completed)
    gross_profit = sum(t.pnl_r for t in wins) if wins else 0.0
    gross_loss = sum(t.pnl_r for t in losses) if losses else 0.0

    pnls = [t.pnl_r for t in completed]
    # Max drawdown
    running = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        running += p
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd:
            max_dd = dd

    wr = len(wins) / len(completed) * 100 if completed else 0.0
    pf = (
        gross_profit / abs(gross_loss)
        if gross_loss != 0
        else float("inf")
        if gross_profit > 0
        else 0.0
    )

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "open": len(open_trades),
        "win_rate": round(wr, 2),
        "profit_factor": round(pf, 3) if pf != float("inf") else "inf",
        "total_pnl": round(total_pnl, 4),
        "avg_r": round(total_pnl / len(completed), 4) if completed else 0.0,
        "median_r": round(float(np.median(pnls)), 4) if pnls else 0.0,
        "max_drawdown": round(max_dd, 4),
        "expectancy": round(total_pnl / len(completed), 4) if completed else 0.0,
    }


def ordinal_stats(trades: List[TradeRecord]) -> Dict:
    """Group trades by sweep_ordinal and calc stats for each group."""
    by_ordinal = defaultdict(list)
    for t in trades:
        key = t.sweep_ordinal if t.sweep_ordinal <= 4 else 4
        by_ordinal[key].append(t)

    result = {}
    for ordinal in sorted(by_ordinal.keys()):
        label = f"#{ordinal}" if ordinal < 4 else "#4+"
        result[label] = calc_stats(by_ordinal[ordinal])
    return result


# ============================================================
# MAIN ANALYSIS
# ============================================================


def run_phase4_analysis():
    """Run the full Phase 4 analysis."""
    from src.strategy.data_loader import DataLoader

    start_time = time.time()
    loader = DataLoader()
    symbols = loader.list_symbols()

    print("PHASE 4 — SWEEP LIFECYCLE FORENSICS")
    print(f"Symbols: {len(symbols)}")
    print("=" * 60)

    all_trades = []
    per_symbol = {}
    sweep_distribution = defaultdict(int)  # trades_per_sweep → count

    for idx, sym in enumerate(symbols):
        bars = loader.load(sym)
        t0 = time.time()

        trades = run_strategy_with_tracking(sym, bars)

        # Count trades per sweep
        sweep_trades = defaultdict(list)
        for t in trades:
            sweep_trades[t.sweep_id].append(t)

        for sweep_id, sweep_trade_list in sweep_trades.items():
            n = len(sweep_trade_list)
            sweep_distribution[n] += 1

        # FVG timing classification
        fvg_timing_counts = defaultdict(int)
        for t in trades:
            fvg_timing_counts[t.fvg_timing] += 1

        stats = calc_stats(trades)
        ord_stats = ordinal_stats(trades)

        elapsed = time.time() - t0
        print(
            f"  [{idx + 1:3d}/{len(symbols)}] {sym:15s} {len(trades):3d}T | "
            f"{stats['win_rate']:5.1f}% WR | {stats['total_pnl']:+8.2f}R | "
            f"{len(sweep_trades)} sweeps | {elapsed:.1f}s"
        )

        per_symbol[sym] = {
            "bars": len(bars),
            "stats": stats,
            "ordinal_stats": ord_stats,
            "fvg_timing": dict(fvg_timing_counts),
            "trades_per_sweep": {str(k): v for k, v in sorted(sweep_distribution.items())},
            "unique_sweeps": len(sweep_trades),
        }
        all_trades.extend(trades)

    # ============================================================
    # AGGREGATE ANALYSIS
    # ============================================================

    print()
    print("=" * 60)
    print("AGGREGATE RESULTS")
    print("=" * 60)

    agg_stats = calc_stats(all_trades)
    agg_ord = ordinal_stats(all_trades)

    # Sweep distribution
    sweep_dist = defaultdict(int)
    for t in all_trades:
        sweep_dist[t.sweep_id] += 1
    trades_per_sweep_dist = defaultdict(int)
    for sweep_id, count in sweep_dist.items():
        trades_per_sweep_dist[count] += 1

    # FVG timing
    fvg_timing_agg = defaultdict(int)
    for t in all_trades:
        fvg_timing_agg[t.fvg_timing] += 1

    print(f"\nTotal trades: {agg_stats['trades']}")
    print(f"Win rate: {agg_stats['win_rate']}%")
    print(f"Profit factor: {agg_stats['profit_factor']}")
    print(f"Total PnL: {agg_stats['total_pnl']:+.2f}R")
    print(f"Max drawdown: {agg_stats['max_drawdown']:.2f}R")
    print(f"Avg R: {agg_stats['avg_r']:.4f}")

    print("\n--- TRADE ORDINAL PERFORMANCE ---")
    for label, stats in sorted(agg_ord.items()):
        print(
            f"  {label:4s} | {stats['trades']:5d}T | {stats['win_rate']:5.1f}% WR | "
            f"PF {str(stats['profit_factor']):>6s} | {stats['total_pnl']:+8.2f}R | "
            f"Avg {stats['avg_r']:+.4f}"
        )

    print("\n--- SWEEP → TRADE DISTRIBUTION ---")
    total_sweeps_with_trades = sum(trades_per_sweep_dist.values())
    for n_trades in sorted(trades_per_sweep_dist.keys()):
        count = trades_per_sweep_dist[n_trades]
        print(f"  1 sweep → {n_trades} trade(s): {count} sweeps")

    print("\n--- FVG TIMING ---")
    for timing, count in sorted(fvg_timing_agg.items()):
        print(f"  {timing:15s}: {count}")

    # ============================================================
    # COUNTERFACTUAL: ONE-SHOT
    # ============================================================
    print()
    print("=" * 60)
    print("COUNTERFACTUAL: ONE-SHOT (first FVG only)")
    print("=" * 60)

    one_shot_all = []
    for idx, sym in enumerate(symbols):
        bars = loader.load(sym)
        trades = run_one_shot_strategy(sym, bars)
        one_shot_all.extend(trades)
        if (idx + 1) % 20 == 0:
            print(f"  ... {idx + 1}/{len(symbols)}")

    one_shot_stats = calc_stats(one_shot_all)
    print(
        f"\nONE-SHOT: {one_shot_stats['trades']}T | {one_shot_stats['win_rate']}% WR | "
        f"PF {one_shot_stats['profit_factor']} | {one_shot_stats['total_pnl']:+.2f}R | "
        f"DD {one_shot_stats['max_drawdown']:.2f}R"
    )

    # ============================================================
    # COUNTERFACTUAL: FRESH-SWEEP
    # ============================================================
    print()
    print("=" * 60)
    print("COUNTERFACTUAL: FRESH-SWEEP (new sweep required)")
    print("=" * 60)

    fresh_all = []
    for idx, sym in enumerate(symbols):
        bars = loader.load(sym)
        trades = run_fresh_sweep_strategy(sym, bars)
        fresh_all.extend(trades)
        if (idx + 1) % 20 == 0:
            print(f"  ... {idx + 1}/{len(symbols)}")

    fresh_stats = calc_stats(fresh_all)
    print(
        f"\nFRESH-SWEEP: {fresh_stats['trades']}T | {fresh_stats['win_rate']}% WR | "
        f"PF {fresh_stats['profit_factor']} | {fresh_stats['total_pnl']:+.2f}R | "
        f"DD {fresh_stats['max_drawdown']:.2f}R"
    )

    # ============================================================
    # COMPARISON TABLE
    # ============================================================
    print()
    print("=" * 60)
    print("COMPARISON: CURRENT vs ONE-SHOT vs FRESH-SWEEP")
    print("=" * 60)

    current_stats = agg_stats
    comparison = {
        "CURRENT": current_stats,
        "ONE_SHOT": one_shot_stats,
        "FRESH_SWEEP": fresh_stats,
    }

    header = (
        f"{'Model':<15} {'Trades':>7} {'WR%':>6} {'PF':>7} {'PnL':>10} {'AvgR':>8} {'MaxDD':>8}"
    )
    print(header)
    print("-" * len(header))
    for model, stats in comparison.items():
        pf = (
            stats["profit_factor"]
            if isinstance(stats["profit_factor"], str)
            else f"{stats['profit_factor']:.3f}"
        )
        print(
            f"{model:<15} {stats['trades']:>7d} {stats['win_rate']:>5.1f}% {pf:>7s} "
            f"{stats['total_pnl']:>+9.2f}R {stats['avg_r']:>+7.4f} {stats['max_drawdown']:>7.2f}R"
        )

    # ============================================================
    # DATASET DISCREPANCY DOCUMENTATION
    # ============================================================
    print()
    print("=" * 60)
    print("DATASET DISCREPANCY: 1,845 vs 16,257")
    print("=" * 60)
    print("""
Dataset A (Phase 3 baseline):  1,845 trades
  - Source: StrategyEngine with CBDR-only sweep detection
  - bias_locked: YES (one sweep per CBDR cycle)
  - Entry: first touch only
  - Each sweep → exactly 1 trade (CBDR-only source)

Dataset B (Phase 3.2 forensics): 16,257 trades
  - Source: liquidity_forensics.py (3 INDEPENDENT sources)
  - Each source runs its own SessionManager with independent bias_locking
  - CBDR: 1,826 trades
  - SESSION_HL: 7,558 trades
  - SWING_HL: 6,873 trades
  - Total: 16,257 (sum of 3 independent runs)

WHY DIFFERENT:
  - Dataset A uses ONLY CBDR as liquidity source (1 source)
  - Dataset B uses THREE independent liquidity sources
  - Each source in B has its own sweep detection → own trades
  - Same bar can produce sweeps in multiple sources
  - B's trade count = sum of 3 independent strategy runs

EXECUTION MODEL:
  - Entry rules: SAME (first-touch FVG)
  - Exit rules: SAME (1.8R TP, initial SL)
  - No trailing: SAME
  - No retrace: SAME

DIRECTLY COMPARABLE: NO
  - A measures CBDR-only performance
  - B measures 3 sources independently
  - B's aggregate includes overlaps
""")

    # ============================================================
    # SAVE RESULTS
    # ============================================================

    output = {
        "summary": {
            "symbols_analyzed": len(symbols),
            "total_bars": sum(per_symbol[s]["bars"] for s in per_symbol),
            "total_trades": agg_stats["trades"],
            "analysis_date": pd.Timestamp.now().isoformat(),
        },
        "aggregate_stats": agg_stats,
        "ordinal_stats": agg_ord,
        "sweep_trade_distribution": {str(k): v for k, v in sorted(trades_per_sweep_dist.items())},
        "fvg_timing": dict(fvg_timing_agg),
        "counterfactual": {
            "ONE_SHOT": one_shot_stats,
            "FRESH_SWEEP": fresh_stats,
        },
        "comparison": {model: stats for model, stats in comparison.items()},
        "dataset_discrepancy": {
            "dataset_a_trades": 1845,
            "dataset_b_trades": 16257,
            "dataset_a_source": "StrategyEngine CBDR-only (1 source)",
            "dataset_b_source": "liquidity_forensics.py (3 independent sources: CBDR+SESSION_HL+SWING_HL)",
            "why_different": "Dataset B sums trades from 3 independent strategy runs; same bar can trigger sweeps in multiple sources",
            "execution_model_same": True,
            "entry_exit_rules_same": True,
            "directly_comparable": False,
        },
        "per_symbol": per_symbol,
    }

    results_dir = Path(__file__).parent.parent.parent / "results"
    results_dir.mkdir(exist_ok=True)

    # Save JSON
    json_path = results_dir / "phase4_sweep_lifecycle_forensics.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str, ensure_ascii=False)
    print(f"\nSaved: {json_path}")

    elapsed = time.time() - start_time
    print(f"\nTotal analysis time: {elapsed:.0f}s")

    return output


if __name__ == "__main__":
    run_phase4_analysis()
