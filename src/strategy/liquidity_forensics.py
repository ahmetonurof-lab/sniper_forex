#!/usr/bin/env python
"""PHASE 3.2 — LIQUIDITY SOURCE / SWEEP FORENSICS

Classifies every detected sweep event by its liquidity source:
  A) CBDR High/Low (existing baseline)
  B) Session High/Low (daily high/low)
  C) Swing High/Low (N-bar pivot)
  D) UNKNOWN (cannot classify)

Runs the SAME baseline execution model (FVG + first-touch + 1.8R TP + initial SL)
on ALL detected sweeps, then compares performance by liquidity source.

IMPORTANT: This analysis does NOT change any strategy logic.
"""

import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.strategy.entry import calculate_sl_tp, detect_first_touch
from src.strategy.fvg import detect_fvg
from src.strategy.models import Bar, Direction, EntryType, TradeResult
from src.strategy.session import SessionManager

# ============================================================
# LIQUIDITY SOURCE DEFINITIONS
# ============================================================


class LiquiditySource(Enum):
    """Liquidity sources for sweep classification."""

    CBDR = "CBDR"
    SESSION_HL = "SESSION_HL"
    SWING_HL = "SWING_HL"
    UNKNOWN = "UNKNOWN"


@dataclass
class LiquidityLevel:
    """A detected liquidity level."""

    source: LiquiditySource
    high: float
    low: float
    start_bar_index: int
    end_bar_index: int
    start_time: pd.Timestamp
    end_time: pd.Timestamp
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ClassifiedSweep:
    """A sweep event classified by its liquidity source."""

    symbol: str
    timestamp: pd.Timestamp
    direction: Direction
    sweep_price: float
    reference_level: float
    bar_index: int
    tolerance: float
    atr: float
    liquidity_source: LiquiditySource
    liquidity_level: LiquidityLevel
    # Post-sweep tracking
    has_fvg: bool = False
    fvg_timestamp: Optional[pd.Timestamp] = None
    fvg_size: float = 0.0
    has_entry: bool = False
    entry_timestamp: Optional[pd.Timestamp] = None
    entry_price: float = 0.0
    entry_type: Optional[EntryType] = None
    sl: float = 0.0
    tp: float = 0.0
    result: Optional[TradeResult] = None
    pnl_r: float = 0.0
    exit_timestamp: Optional[pd.Timestamp] = None
    exit_price: float = 0.0
    date: str = ""


# ============================================================
# LIQUIDITY DETECTORS
# ============================================================


def detect_session_hl_levels(
    bars: List[Bar], symbol: str, max_active_days: int = 3
) -> List[LiquidityLevel]:
    """Detect Session (Daily) High/Low levels.

    Each trading day produces one SessionHL level:
      - high = max(high) across all bars that day
      - low = min(low) across all bars that day

    The level is "active" from the last bar of the day until the end of
    the next day (or until invalidated by a sweep).

    NEWLY DEFINED FOR THIS ANALYSIS — not in existing strategy code.

    Args:
        max_active_days: Only keep last N days of levels (performance).
    """
    if not bars:
        return []

    # Group bars by date
    daily_groups = defaultdict(list)
    for bar in bars:
        day = bar.timestamp.date()
        daily_groups[day].append(bar)

    levels = []
    sorted_dates = sorted(daily_groups.keys())

    # Only keep last max_active_days for performance
    start_idx = max(0, len(sorted_dates) - max_active_days)
    active_dates = sorted_dates[start_idx:]

    for i, day in enumerate(sorted_dates):
        day_bars = daily_groups[day]
        day_high = max(b.high for b in day_bars)
        day_low = min(b.low for b in day_bars)

        # The level is defined at end of day, active from next day
        if i + 1 < len(sorted_dates):
            next_day = sorted_dates[i + 1]
            next_bars = daily_groups[next_day]
            start_bar = next_bars[0].index
            start_time = next_bars[0].timestamp
        else:
            start_bar = day_bars[-1].index
            start_time = day_bars[-1].timestamp

        # Level active until end of dataset or next reset
        end_bar = bars[-1].index
        end_time = bars[-1].timestamp

        levels.append(
            LiquidityLevel(
                source=LiquiditySource.SESSION_HL,
                high=day_high,
                low=day_low,
                start_bar_index=start_bar,
                end_bar_index=end_bar,
                start_time=start_time,
                end_time=end_time,
                metadata={"date": str(day), "bar_count": len(day_bars)},
            )
        )

    return levels


def detect_swing_hl_levels(
    bars: List[Bar], symbol: str, swing_lookback: int = 5, max_levels: int = 50
) -> List[LiquidityLevel]:
    """Detect Swing High/Low levels using N-bar pivot detection.

    Swing High: bar.high > max(high of N bars before AND after)
    Swing Low: bar.low < min(low of N bars before AND after)

    NEWLY DEFINED FOR THIS ANALYSIS — not in existing strategy code.

    Args:
        bars: Full bar list
        symbol: Symbol name
        swing_lookback: Number of bars on each side for pivot detection
        max_levels: Only keep last N swing levels (performance)
    """
    if len(bars) < 2 * swing_lookback + 1:
        return []

    all_levels = []

    for i in range(swing_lookback, len(bars) - swing_lookback):
        bar = bars[i]

        # Check swing high
        left_highs = [bars[j].high for j in range(i - swing_lookback, i)]
        right_highs = [bars[j].high for j in range(i + 1, i + swing_lookback + 1)]

        if bar.high > max(left_highs) and bar.high > max(right_highs):
            all_levels.append(
                LiquidityLevel(
                    source=LiquiditySource.SWING_HL,
                    high=bar.high,
                    low=bar.high,
                    start_bar_index=bar.index,
                    end_bar_index=bars[-1].index,
                    start_time=bar.timestamp,
                    end_time=bars[-1].timestamp,
                    metadata={
                        "type": "swing_high",
                        "pivot_bar_index": bar.index,
                        "lookback": swing_lookback,
                    },
                )
            )

        # Check swing low
        left_lows = [bars[j].low for j in range(i - swing_lookback, i)]
        right_lows = [bars[j].low for j in range(i + 1, i + swing_lookback + 1)]

        if bar.low < min(left_lows) and bar.low < min(right_lows):
            all_levels.append(
                LiquidityLevel(
                    source=LiquiditySource.SWING_HL,
                    high=bar.low,
                    low=bar.low,
                    start_bar_index=bar.index,
                    end_bar_index=bars[-1].index,
                    start_time=bar.timestamp,
                    end_time=bars[-1].timestamp,
                    metadata={
                        "type": "swing_low",
                        "pivot_bar_index": bar.index,
                        "lookback": swing_lookback,
                    },
                )
            )

    # Keep only last max_levels for performance
    return all_levels[-max_levels:] if len(all_levels) > max_levels else all_levels


def check_sweep_against_level(
    bar: Bar,
    level: LiquidityLevel,
    tolerance: float,
    _direction_hint: Optional[Direction] = None,
) -> Optional[Tuple[Direction, float, float]]:
    """Check if bar sweeps a liquidity level.

    Returns:
        (direction, sweep_price, reference_level) if sweep detected
        None otherwise
    """
    if level.source == LiquiditySource.SWING_HL:
        meta = level.metadata
        if meta.get("type") == "swing_high":
            # Sweep above swing high: high > level.high + tolerance
            # Close back below: close < level.high
            if bar.high > level.high + tolerance and bar.close < level.high:
                return (Direction.BEARISH, bar.high, level.high)
        elif meta.get("type") == "swing_low":
            # Sweep below swing low: low < level.low - tolerance
            # Close back above: close > level.low
            if bar.low < level.low - tolerance and bar.close > level.low:
                return (Direction.BULLISH, bar.low, level.low)
    else:
        # CBDR or SessionHL: has both high and low
        # Bearish sweep: above high
        if bar.high > level.high + tolerance and bar.close < level.high:
            return (Direction.BEARISH, bar.high, level.high)
        # Bullish sweep: below low
        if bar.low < level.low - tolerance and bar.close > level.low:
            return (Direction.BULLISH, bar.low, level.low)

    return None


# ============================================================
# MAIN ANALYSIS ENGINE
# ============================================================


class LiquidityForensics:
    """Main analysis engine for PHASE 3.2."""

    def __init__(
        self,
        swing_lookback: int = 5,
        sweep_atr_mult: float = 0.5,
        default_tolerance: float = 0.001,
        rr_ratio: float = 1.8,
        cbdr_start_hour: int = 19,
        cbdr_end_hour: int = 1,
    ):
        self.swing_lookback = swing_lookback
        self.sweep_atr_mult = sweep_atr_mult
        self.default_tolerance = default_tolerance
        self.rr_ratio = rr_ratio
        self.cbdr_start_hour = cbdr_start_hour
        self.cbdr_end_hour = cbdr_end_hour

    def load_symbol_data(self, symbol: str) -> Optional[List[Bar]]:
        """Load M1 bars from Feather file. Optimized for speed."""
        feather_path = Path("data/feather") / f"{symbol}_1m.feather"
        if not feather_path.exists():
            return None

        df = pd.read_feather(feather_path)

        # Standardize columns
        col_map = {}
        for col in df.columns:
            cl = col.lower()
            if cl in ("open", "high", "low", "close", "volume", "tick_volume"):
                col_map[col] = cl
        df = df.rename(columns=col_map)

        if "volume" not in df.columns and "tick_volume" in df.columns:
            df["volume"] = df["tick_volume"]

        df = df.sort_values("timestamp").reset_index(drop=True)

        # Vectorized conversion — much faster than iterrows
        timestamps = pd.to_datetime(df["timestamp"])  # Ensure pandas Timestamps
        opens = df["open"].values.astype(float)
        highs = df["high"].values.astype(float)
        lows = df["low"].values.astype(float)
        closes = df["close"].values.astype(float)
        volumes = df["volume"].values.astype(float) if "volume" in df.columns else np.zeros(len(df))

        bars = [
            Bar(
                index=i,
                timestamp=timestamps.iloc[i],
                open=opens[i],
                high=highs[i],
                low=lows[i],
                close=closes[i],
                volume=volumes[i],
            )
            for i in range(len(df))
        ]

        return bars

    def calculate_atr(self, bars: List[Bar], period: int = 14) -> float:
        """Calculate ATR from bars."""
        if len(bars) < period + 1:
            return 0.0
        trs = []
        for i in range(1, len(bars)):
            tr = max(
                bars[i].high - bars[i].low,
                abs(bars[i].high - bars[i - 1].close),
                abs(bars[i].low - bars[i - 1].close),
            )
            trs.append(tr)
        if len(trs) < period:
            return 0.0
        return float(np.mean(trs[-period:]))

    def detect_all_cbdr_events(
        self, bars: List[Bar], symbol: str, atr: float
    ) -> List[ClassifiedSweep]:
        """Detect CBDR sweeps using existing SessionManager."""
        tolerance = atr * self.sweep_atr_mult if atr > 0 else self.default_tolerance

        session = SessionManager(
            symbol=symbol,
            start_hour=self.cbdr_start_hour,
            end_hour=self.cbdr_end_hour,
            atr=atr,
            sweep_atr_tolerance_mult=self.sweep_atr_mult,
            sweep_default_tolerance=self.default_tolerance,
        )

        cbdr_events = []
        # Track the current CBDR level for classification
        current_cbdr_level = None

        for bar in bars:
            dt = bar.timestamp.to_pydatetime()
            in_w = session.in_window(dt)

            if in_w:
                session.track_body(bar)
                # Update current CBDR level
                if session.cbdr.body_high > 0 and session.cbdr.body_low < float("inf"):
                    current_cbdr_level = LiquidityLevel(
                        source=LiquiditySource.CBDR,
                        high=session.cbdr.body_high,
                        low=session.cbdr.body_low,
                        start_bar_index=bar.index,
                        end_bar_index=bar.index,
                        start_time=bar.timestamp,
                        end_time=bar.timestamp,
                        metadata={"cbdr_key": session.current_cbdr_key},
                    )
            else:
                # Lock on first bar outside window
                if not session.cbdr.locked and session.cbdr.body_high > 0:
                    session.cbdr.locked = True

                # Check sweep on every bar outside window
                if not session.cbdr.bias_locked:
                    sweep = session.check_sweep(bar)
                    if sweep and current_cbdr_level:
                        cbdr_events.append(
                            ClassifiedSweep(
                                symbol=symbol,
                                timestamp=bar.timestamp,
                                direction=sweep.direction,
                                sweep_price=sweep.sweep_price,
                                reference_level=sweep.reference_level,
                                bar_index=bar.index,
                                tolerance=tolerance,
                                atr=atr,
                                liquidity_source=LiquiditySource.CBDR,
                                liquidity_level=current_cbdr_level,
                                date=str(bar.timestamp.date()),
                            )
                        )

            # Check for new cycle
            cbdr_key = session.cbdr_day_key(dt)
            if session.current_cbdr_key is not None and cbdr_key != session.current_cbdr_key:
                session.reset_for_new_cycle()
                current_cbdr_level = None
            session.current_cbdr_key = cbdr_key

        return cbdr_events

    def detect_session_hl_sweeps(
        self, bars: List[Bar], symbol: str, atr: float
    ) -> List[ClassifiedSweep]:
        """Detect sweeps against Session H/L levels.

        Only checks the PREVIOUS day's high/low (most recent 1 day).
        This avoids hundreds of stale levels dominating the event count.
        """
        tolerance = atr * self.sweep_atr_mult if atr > 0 else self.default_tolerance
        levels = detect_session_hl_levels(bars, symbol, max_active_days=1)

        events = []
        for bar in bars:
            for level in levels:
                if bar.index < level.start_bar_index:
                    continue

                result = check_sweep_against_level(bar, level, tolerance)
                if result:
                    direction, sweep_price, ref_level = result
                    events.append(
                        ClassifiedSweep(
                            symbol=symbol,
                            timestamp=bar.timestamp,
                            direction=direction,
                            sweep_price=sweep_price,
                            reference_level=ref_level,
                            bar_index=bar.index,
                            tolerance=tolerance,
                            atr=atr,
                            liquidity_source=LiquiditySource.SESSION_HL,
                            liquidity_level=level,
                            date=str(bar.timestamp.date()),
                        )
                    )
                    break

        return events

    def detect_swing_hl_sweeps(
        self, bars: List[Bar], symbol: str, atr: float
    ) -> List[ClassifiedSweep]:
        """Detect sweeps against Swing H/L levels."""
        tolerance = atr * self.sweep_atr_mult if atr > 0 else self.default_tolerance
        levels = detect_swing_hl_levels(bars, symbol, self.swing_lookback, max_levels=50)

        events = []
        for bar in bars:
            for level in levels:
                if bar.index < level.start_bar_index:
                    continue

                result = check_sweep_against_level(bar, level, tolerance)
                if result:
                    direction, sweep_price, ref_level = result
                    events.append(
                        ClassifiedSweep(
                            symbol=symbol,
                            timestamp=bar.timestamp,
                            direction=direction,
                            sweep_price=sweep_price,
                            reference_level=ref_level,
                            bar_index=bar.index,
                            tolerance=tolerance,
                            atr=atr,
                            liquidity_source=LiquiditySource.SWING_HL,
                            liquidity_level=level,
                            date=str(bar.timestamp.date()),
                        )
                    )
                    break

        return events

    def deduplicate_events(self, events: List[ClassifiedSweep]) -> List[ClassifiedSweep]:
        """Remove duplicate events (same bar_index + direction).

        When multiple liquidity levels are swept on the same bar,
        we keep the event but note all applicable sources.
        """
        # Group by (bar_index, direction)
        groups = defaultdict(list)
        for e in events:
            key = (e.bar_index, e.direction)
            groups[key].append(e)

        deduplicated = []
        for key, group in groups.items():
            if len(group) == 1:
                deduplicated.append(group[0])
            else:
                # Multiple sources on same bar — keep all sources in metadata
                primary = group[0]
                sources = [e.liquidity_source.value for e in group]
                primary.liquidity_level.metadata["overlapping_sources"] = sources
                deduplicated.append(primary)

        return deduplicated

    def run_fvg_and_entry(
        self, events: List[ClassifiedSweep], bars: List[Bar], symbol: str
    ) -> List[ClassifiedSweep]:
        """For each sweep event, detect FVG and entry using baseline rules.

        Optimized: pre-compute FVG positions, then match events.
        """
        if not events:
            return events

        # Pre-compute ALL FVG positions in one pass (much faster)
        # Group events by direction to batch FVG detection
        max_fvg_lookahead = 300
        max_entry_lookahead = 100

        for event in events:
            sweep_bar_idx = event.bar_index
            daily_bias = event.direction

            fvg_end = min(sweep_bar_idx + 3 + max_fvg_lookahead, len(bars))

            found_fvg = False
            for i in range(sweep_bar_idx + 3, fvg_end):
                fvg = detect_fvg(bars, i, daily_bias, symbol)
                if fvg and fvg.fvg_index > sweep_bar_idx:
                    event.has_fvg = True
                    event.fvg_timestamp = fvg.creation_time
                    event.fvg_size = fvg.fvg_size

                    entry_end = min(fvg.fvg_index + max_entry_lookahead, len(bars))
                    for j in range(fvg.fvg_index, entry_end):
                        entry_type = detect_first_touch(bars[j], fvg, daily_bias, None)
                        if entry_type:
                            sl, tp, entry_price = calculate_sl_tp(fvg, daily_bias, self.rr_ratio)
                            event.has_entry = True
                            event.entry_timestamp = bars[j].timestamp
                            event.entry_price = entry_price
                            event.entry_type = entry_type
                            event.sl = sl
                            event.tp = tp
                            self._simulate_exit(event, bars, j)
                            break

                    found_fvg = True
                    break

            if found_fvg:
                continue

        return events

    def _simulate_exit(self, event: ClassifiedSweep, bars: List[Bar], start_idx: int):
        """Simulate trade exit from entry bar."""
        if event.entry_price == 0 or event.sl == 0 or event.tp == 0:
            return

        for i in range(start_idx, len(bars)):
            bar = bars[i]

            if event.direction == Direction.BULLISH:
                if bar.low <= event.sl:
                    event.exit_timestamp = bar.timestamp
                    event.exit_price = event.sl
                    event.result = TradeResult.LOSS
                    event.pnl_r = -1.0
                    return
                if bar.high >= event.tp:
                    event.exit_timestamp = bar.timestamp
                    event.exit_price = event.tp
                    event.result = TradeResult.WIN
                    risk = event.entry_price - event.sl
                    event.pnl_r = (event.tp - event.entry_price) / risk if risk > 0 else 0.0
                    return
            else:  # BEARISH
                if bar.high >= event.sl:
                    event.exit_timestamp = bar.timestamp
                    event.exit_price = event.sl
                    event.result = TradeResult.LOSS
                    event.pnl_r = -1.0
                    return
                if bar.low <= event.tp:
                    event.exit_timestamp = bar.timestamp
                    event.exit_price = event.tp
                    event.result = TradeResult.WIN
                    risk = event.sl - event.entry_price
                    event.pnl_r = (event.entry_price - event.tp) / risk if risk > 0 else 0.0
                    return

        # End of data — mark as open
        event.result = TradeResult.OPEN

    def analyze_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Run full analysis on a single symbol."""
        bars = self.load_symbol_data(symbol)
        if not bars or len(bars) < 100:
            return None

        atr = self.calculate_atr(bars, period=14)

        # STEP 2: Detect all sweep events
        cbdr_events = self.detect_all_cbdr_events(bars, symbol, atr)
        session_events = self.detect_session_hl_sweeps(bars, symbol, atr)
        swing_events = self.detect_swing_hl_sweeps(bars, symbol, atr)

        # Combine and deduplicate
        all_events = cbdr_events + session_events + swing_events
        all_events = self.deduplicate_events(all_events)

        # Limit events per symbol for performance
        # Keep proportional representation from each source
        max_events_per_source = 80
        cbdr_limited = cbdr_events[:max_events_per_source]
        session_limited = session_events[:max_events_per_source]
        swing_limited = swing_events[:max_events_per_source]
        all_events = self.deduplicate_events(cbdr_limited + session_limited + swing_limited)

        # STEP 3-5: Run FVG + entry + simulation on all events
        all_events = self.run_fvg_and_entry(all_events, bars, symbol)

        # STEP 6: Sweep frequency audit
        trading_days = len(set(b.timestamp.date() for b in bars))

        total_sweeps = len(all_events)
        cbdr_count = sum(1 for e in all_events if e.liquidity_source == LiquiditySource.CBDR)
        session_count = sum(
            1 for e in all_events if e.liquidity_source == LiquiditySource.SESSION_HL
        )
        swing_count = sum(1 for e in all_events if e.liquidity_source == LiquiditySource.SWING_HL)
        unknown_count = sum(1 for e in all_events if e.liquidity_source == LiquiditySource.UNKNOWN)

        # Calculate tolerance stats
        tolerances = [e.tolerance for e in all_events]
        median_tolerance = float(np.median(tolerances)) if tolerances else 0.0
        tolerance_atr_ratio = median_tolerance / atr if atr > 0 else 0.0

        # FVG conversion
        fvg_count = sum(1 for e in all_events if e.has_fvg)
        entry_count = sum(1 for e in all_events if e.has_entry)
        trade_count = sum(1 for e in all_events if e.result in (TradeResult.WIN, TradeResult.LOSS))

        # Group by source
        source_stats = {}
        for src in [
            LiquiditySource.CBDR,
            LiquiditySource.SESSION_HL,
            LiquiditySource.SWING_HL,
        ]:
            src_events = [e for e in all_events if e.liquidity_source == src]
            src_trades = [e for e in src_events if e.result in (TradeResult.WIN, TradeResult.LOSS)]
            src_wins = [e for e in src_trades if e.result == TradeResult.WIN]
            src_losses = [e for e in src_trades if e.result == TradeResult.LOSS]

            wins_pnl = sum(e.pnl_r for e in src_wins)
            losses_pnl = sum(e.pnl_r for e in src_losses)

            pnls = [e.pnl_r for e in src_trades]

            # Max drawdown
            cumulative = np.cumsum(pnls) if pnls else np.array([0])
            running_max = (
                np.maximum.accumulate(cumulative) if len(cumulative) > 0 else np.array([0])
            )
            drawdowns = running_max - cumulative
            max_dd = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

            source_stats[src.value] = {
                "total_events": len(src_events),
                "sweeps_with_fvg": sum(1 for e in src_events if e.has_fvg),
                "sweeps_with_entry": sum(1 for e in src_events if e.has_entry),
                "trades": len(src_trades),
                "wins": len(src_wins),
                "losses": len(src_losses),
                "win_rate": len(src_wins) / len(src_trades) * 100 if src_trades else 0.0,
                "gross_profit": wins_pnl,
                "gross_loss": losses_pnl,
                "profit_factor": wins_pnl / abs(losses_pnl) if losses_pnl != 0 else float("inf"),
                "total_pnl": sum(pnls),
                "avg_r": float(np.mean(pnls)) if pnls else 0.0,
                "median_r": float(np.median(pnls)) if pnls else 0.0,
                "max_drawdown": max_dd,
                "expectancy": float(np.mean(pnls)) if pnls else 0.0,
                "trades_per_day": len(src_trades) / trading_days if trading_days > 0 else 0.0,
                "fvg_conversion_rate": sum(1 for e in src_events if e.has_fvg)
                / len(src_events)
                * 100
                if src_events
                else 0.0,
                "entry_conversion_rate": sum(1 for e in src_events if e.has_entry)
                / len(src_events)
                * 100
                if src_events
                else 0.0,
                "sweeps_per_day": len(src_events) / trading_days if trading_days > 0 else 0.0,
            }

        # Overlapping sources analysis
        overlapping = [e for e in all_events if "overlapping_sources" in e.liquidity_level.metadata]

        return {
            "symbol": symbol,
            "bars": len(bars),
            "trading_days": trading_days,
            "atr": atr,
            "median_tolerance": median_tolerance,
            "tolerance_atr_ratio": tolerance_atr_ratio,
            "total_events": total_sweeps,
            "cbdr_count": cbdr_count,
            "session_hl_count": session_count,
            "swing_hl_count": swing_count,
            "unknown_count": unknown_count,
            "overlapping_count": len(overlapping),
            "fvg_count": fvg_count,
            "entry_count": entry_count,
            "trade_count": trade_count,
            "source_stats": source_stats,
        }

    def run_full_analysis(self) -> Dict[str, Any]:
        """Run forensics across all symbols."""
        feather_dir = Path("data/feather")
        symbols = sorted([f.stem.replace("_1m", "") for f in feather_dir.glob("*_1m.feather")])

        print(f"Found {len(symbols)} symbols")

        results = {}

        for i, symbol in enumerate(symbols):
            if (i + 1) % 10 == 0 or i == 0:
                print(f"  Processing {i + 1}/{len(symbols)}: {symbol}", flush=True)

            try:
                result = self.analyze_symbol(symbol)
                if result:
                    results[symbol] = result
            except Exception as e:
                print(f"  ERROR on {symbol}: {e}", flush=True)
                continue

        # Aggregate
        total_events = sum(r["total_events"] for r in results.values())
        total_cbdr = sum(r["cbdr_count"] for r in results.values())
        total_session = sum(r["session_hl_count"] for r in results.values())
        total_swing = sum(r["swing_hl_count"] for r in results.values())
        total_unknown = sum(r["unknown_count"] for r in results.values())
        total_trades = sum(r["trade_count"] for r in results.values())
        total_fvg = sum(r["fvg_count"] for r in results.values())
        total_entry = sum(r["entry_count"] for r in results.values())
        total_bars = sum(r["bars"] for r in results.values())
        total_days = sum(r["trading_days"] for r in results.values())

        # Aggregate source stats
        agg_source_stats = {}
        for src_name in ["CBDR", "SESSION_HL", "SWING_HL"]:
            src_trades = []
            src_wins = 0
            src_losses = 0
            src_gross_profit = 0.0
            src_gross_loss = 0.0
            src_total_pnl = 0.0
            src_total_events = 0
            src_fvg_count = 0
            src_entry_count = 0

            for r in results.values():
                if src_name in r["source_stats"]:
                    s = r["source_stats"][src_name]
                    src_trades += [s["trades"]]
                    src_wins += s["wins"]
                    src_losses += s["losses"]
                    src_gross_profit += s["gross_profit"]
                    src_gross_loss += s["gross_loss"]
                    src_total_pnl += s["total_pnl"]
                    src_total_events += s["total_events"]
                    src_fvg_count += s["sweeps_with_fvg"]
                    src_entry_count += s["sweeps_with_entry"]

            total_src_trades = sum(src_trades)

            # Calculate aggregate max DD
            all_pnls = []
            for r in results.values():
                if src_name in r["source_stats"]:
                    # We need per-trade pnls for DD calc, approximate from stats
                    s = r["source_stats"][src_name]
                    if s["trades"] > 0 and s["total_pnl"] != 0:
                        avg = s["total_pnl"] / s["trades"]
                        all_pnls.extend([avg] * s["trades"])

            if all_pnls:
                cumulative = np.cumsum(all_pnls)
                running_max = np.maximum.accumulate(cumulative)
                max_dd = float(np.max(running_max - cumulative))
            else:
                max_dd = 0.0

            agg_source_stats[src_name] = {
                "total_events": src_total_events,
                "fvg_conversion": src_fvg_count,
                "entry_conversion": src_entry_count,
                "trades": total_src_trades,
                "wins": src_wins,
                "losses": src_losses,
                "win_rate": src_wins / total_src_trades * 100 if total_src_trades > 0 else 0.0,
                "gross_profit": src_gross_profit,
                "gross_loss": src_gross_loss,
                "profit_factor": src_gross_profit / abs(src_gross_loss)
                if src_gross_loss != 0
                else float("inf"),
                "total_pnl": src_total_pnl,
                "avg_r": src_total_pnl / total_src_trades if total_src_trades > 0 else 0.0,
                "max_drawdown": max_dd,
                "expectancy": src_total_pnl / total_src_trades if total_src_trades > 0 else 0.0,
                "sweeps_per_day": src_total_events / total_days if total_days > 0 else 0.0,
                "trades_per_day": total_src_trades / total_days if total_days > 0 else 0.0,
            }

        # Top/Bottom symbols by source
        top_bottom = {}
        for src_name in ["CBDR", "SESSION_HL", "SWING_HL"]:
            sym_pnls = []
            for sym, r in results.items():
                if src_name in r["source_stats"]:
                    s = r["source_stats"][src_name]
                    sym_pnls.append((sym, s["total_pnl"], s["trades"], s["win_rate"]))
            sym_pnls.sort(key=lambda x: x[1], reverse=True)
            top_bottom[src_name] = {
                "top_5": sym_pnls[:5],
                "bottom_5": sym_pnls[-5:],
            }

        return {
            "summary": {
                "symbols_analyzed": len(results),
                "total_bars": total_bars,
                "total_events": total_events,
                "cbdr_events": total_cbdr,
                "session_hl_events": total_session,
                "swing_hl_events": total_swing,
                "unknown_events": total_unknown,
                "total_fvg": total_fvg,
                "total_entries": total_entry,
                "total_trades": total_trades,
            },
            "aggregate_source_stats": agg_source_stats,
            "top_bottom_by_source": top_bottom,
            "per_symbol": results,
        }

    def _aggregate_results(self, per_symbol: Dict[str, Any]) -> Dict[str, Any]:
        """Aggregate per-symbol results into full report structure.

        Used by batch runner to reconstruct the full report from saved partial results.
        """
        results = per_symbol

        total_events = sum(r.get("total_events", 0) for r in results.values())
        total_cbdr = sum(r.get("cbdr_count", 0) for r in results.values())
        total_session = sum(r.get("session_hl_count", 0) for r in results.values())
        total_swing = sum(r.get("swing_hl_count", 0) for r in results.values())
        total_unknown = sum(r.get("unknown_count", 0) for r in results.values())
        total_trades = sum(r.get("trade_count", 0) for r in results.values())
        total_fvg = sum(r.get("fvg_count", 0) for r in results.values())
        total_entry = sum(r.get("entry_count", 0) for r in results.values())
        total_bars = sum(r.get("bars", 0) for r in results.values())
        total_days = sum(r.get("trading_days", 0) for r in results.values())

        agg_source_stats = {}
        for src_name in ["CBDR", "SESSION_HL", "SWING_HL"]:
            src_wins = 0
            src_losses = 0
            src_gross_profit = 0.0
            src_gross_loss = 0.0
            src_total_pnl = 0.0
            src_total_events = 0
            src_fvg_count = 0
            src_entry_count = 0
            total_src_trades = 0

            for r in results.values():
                ss = r.get("source_stats", {})
                if src_name in ss:
                    s = ss[src_name]
                    src_wins += s.get("wins", 0)
                    src_losses += s.get("losses", 0)
                    src_gross_profit += s.get("gross_profit", 0)
                    src_gross_loss += s.get("gross_loss", 0)
                    src_total_pnl += s.get("total_pnl", 0)
                    src_total_events += s.get("total_events", 0)
                    src_fvg_count += s.get("sweeps_with_fvg", 0)
                    src_entry_count += s.get("sweeps_with_entry", 0)
                    total_src_trades += s.get("trades", 0)

            # Approximate max DD
            all_pnls = []
            for r in results.values():
                ss = r.get("source_stats", {})
                if src_name in ss:
                    s = ss[src_name]
                    if s.get("trades", 0) > 0 and s.get("total_pnl", 0) != 0:
                        avg = s["total_pnl"] / s["trades"]
                        all_pnls.extend([avg] * s["trades"])

            if all_pnls:
                cumulative = np.cumsum(all_pnls)
                running_max = np.maximum.accumulate(cumulative)
                max_dd = float(np.max(running_max - cumulative))
            else:
                max_dd = 0.0

            agg_source_stats[src_name] = {
                "total_events": src_total_events,
                "sweeps_with_fvg": src_fvg_count,
                "sweeps_with_entry": src_entry_count,
                "trades": total_src_trades,
                "wins": src_wins,
                "losses": src_losses,
                "win_rate": src_wins / total_src_trades * 100 if total_src_trades > 0 else 0.0,
                "gross_profit": src_gross_profit,
                "gross_loss": src_gross_loss,
                "profit_factor": src_gross_profit / abs(src_gross_loss)
                if src_gross_loss != 0
                else float("inf"),
                "total_pnl": src_total_pnl,
                "avg_r": src_total_pnl / total_src_trades if total_src_trades > 0 else 0.0,
                "max_drawdown": max_dd,
                "expectancy": src_total_pnl / total_src_trades if total_src_trades > 0 else 0.0,
                "sweeps_per_day": src_total_events / total_days if total_days > 0 else 0.0,
                "trades_per_day": total_src_trades / total_days if total_days > 0 else 0.0,
            }

        top_bottom = {}
        for src_name in ["CBDR", "SESSION_HL", "SWING_HL"]:
            sym_pnls = []
            for sym, r in results.items():
                ss = r.get("source_stats", {})
                if src_name in ss:
                    s = ss[src_name]
                    sym_pnls.append(
                        (
                            sym,
                            s.get("total_pnl", 0),
                            s.get("trades", 0),
                            s.get("win_rate", 0),
                        )
                    )
            sym_pnls.sort(key=lambda x: x[1], reverse=True)
            top_bottom[src_name] = {
                "top_5": sym_pnls[:5],
                "bottom_5": sym_pnls[-5:],
            }

        return {
            "summary": {
                "symbols_analyzed": len(results),
                "total_bars": total_bars,
                "total_events": total_events,
                "cbdr_events": total_cbdr,
                "session_hl_events": total_session,
                "swing_hl_events": total_swing,
                "unknown_events": total_unknown,
                "total_fvg": total_fvg,
                "total_entries": total_entry,
                "total_trades": total_trades,
            },
            "aggregate_source_stats": agg_source_stats,
            "top_bottom_by_source": top_bottom,
            "per_symbol": results,
        }


# ============================================================
# OUTPUT GENERATORS
# ============================================================


def generate_forensics_json(results: Dict, output_path: str):
    """Generate JSON output."""

    # Convert numpy types for JSON serialization
    def convert(obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        elif isinstance(obj, (np.floating,)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, float) and (obj == float("inf") or obj == float("-inf")):
            return str(obj)
        return obj

    def recursive_convert(obj):
        if isinstance(obj, dict):
            return {k: recursive_convert(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [recursive_convert(v) for v in obj]
        else:
            return convert(obj)

    results_clean = recursive_convert(results)

    with open(output_path, "w") as f:
        json.dump(results_clean, f, indent=2, default=str)
    print(f"Written: {output_path}")


def generate_forensics_md(results: Dict, output_path: str):
    """Generate Markdown report."""
    summary = results["summary"]
    agg = results["aggregate_source_stats"]
    top_bot = results["top_bottom_by_source"]

    lines = []
    lines.append("# PHASE 3.2 — LIQUIDITY SOURCE / SWEEP FORENSICS REPORT")
    lines.append("")
    lines.append("## 1. DEFINITIONS")
    lines.append("")
    lines.append("### Liquidity Sources")
    lines.append("")
    lines.append("| Source | Definition | Timeframe | Lookback | Tolerance | Baseline? |")
    lines.append("|--------|-----------|-----------|----------|-----------|-----------|")
    lines.append(
        "| **CBDR** | Body accumulation from 19:00-01:00 (MT5_SERVER_TIME) window. Bearish: high > body_high + tol & close < body_high. Bullish: low < body_low - tol & close > body_low. | M1 | Session window | ATR × 0.5 | ✅ YES |"
    )
    lines.append(
        "| **SESSION_HL** | Previous day's high/low. Bearish: high > day_high + tol & close < day_high. Bullish: low < day_low - tol & close > day_low. | Daily | 1 day | ATR × 0.5 | ❌ NEWLY DEFINED |"
    )
    lines.append(
        "| **SWING_HL** | N-bar pivot high/low (N=5). Swing High: bar.high > max(high of 5 bars before AND after). Swing Low: bar.low < min(low of 5 bars before AND after). | M1 | 5 bars each side | ATR × 0.5 | ❌ NEWLY DEFINED |"
    )
    lines.append("")
    lines.append(
        "**IMPORTANT:** SESSION_HL and SWING_HL are NEWLY DEFINED for this analysis. They do NOT exist in the current strategy implementation. Only CBDR is the existing baseline liquidity source."
    )
    lines.append("")
    lines.append("### Execution Model (UNCHANGED from baseline)")
    lines.append("")
    lines.append("- FVG: 3-candle gap detection, direction must agree with sweep direction")
    lines.append("- Entry: First wick touch of FVG")
    lines.append("- SL: FVG bottom (LONG) / FVG top (SHORT)")
    lines.append("- TP: 1.8R")
    lines.append("- Trailing: OFF")
    lines.append("- ATR fallback: OFF")
    lines.append("")
    lines.append("### Timezone")
    lines.append("")
    lines.append("**MT5_SERVER_TIME** — NOT verified as UTC. Do not claim UTC.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 2. EVENT COUNTS")
    lines.append("")
    lines.append(f"- **Symbols analyzed:** {summary['symbols_analyzed']}")
    lines.append(f"- **Total M1 bars:** {summary['total_bars']:,}")
    lines.append(f"- **Total sweep events:** {summary['total_events']:,}")
    lines.append(f"- **CBDR sweeps:** {summary['cbdr_events']:,}")
    lines.append(f"- **SESSION_HL sweeps:** {summary['session_hl_events']:,}")
    lines.append(f"- **SWING_HL sweeps:** {summary['swing_hl_events']:,}")
    lines.append(f"- **UNKNOWN:** {summary['unknown_events']:,}")
    lines.append(f"- **Total FVGs after sweeps:** {summary['total_fvg']:,}")
    lines.append(f"- **Total entries:** {summary['total_entries']:,}")
    lines.append(f"- **Total trades:** {summary['total_trades']:,}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 3. EVENT FUNNEL")
    lines.append("")
    lines.append("```")
    for src_name in ["CBDR", "SESSION_HL", "SWING_HL"]:
        s = agg.get(src_name, {})
        total_evt = s.get("total_events", 0)
        fvg = s.get("fvg_conversion", 0)
        entry = s.get("entry_conversion", 0)
        trades = s.get("trades", 0)
        wins = s.get("wins", 0)
        losses = s.get("losses", 0)

        fvg_pct = f"{fvg / total_evt * 100:.1f}%" if total_evt > 0 else "N/A"
        entry_pct = f"{entry / total_evt * 100:.1f}%" if total_evt > 0 else "N/A"

        print_str = f"""{src_name}
  liquidity events:  {total_evt}
  sweep → FVG:       {fvg} ({fvg_pct})
  sweep → entry:     {entry} ({entry_pct})
  entry → TP:        {wins}
  entry → SL:        {losses}
"""
        lines.append(print_str)
    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 4. PERFORMANCE COMPARISON")
    lines.append("")
    lines.append("| Metric | CBDR | SESSION_HL | SWING_HL |")
    lines.append("|--------|------|------------|----------|")

    metrics = [
        ("Trades", "trades"),
        ("Win Rate %", "win_rate"),
        ("Gross Profit", "gross_profit"),
        ("Gross Loss", "gross_loss"),
        ("Profit Factor", "profit_factor"),
        ("Total PnL (R)", "total_pnl"),
        ("Avg R/trade", "avg_r"),
        ("Max DD (R)", "max_drawdown"),
        ("Expectancy (R)", "expectancy"),
        ("Trades/day", "trades_per_day"),
        ("FVG conversion %", "sweeps_with_fvg"),
    ]

    for label, key in metrics:
        vals = []
        for src_name in ["CBDR", "SESSION_HL", "SWING_HL"]:
            s = agg.get(src_name, {})
            v = s.get(key, 0)
            if isinstance(v, float):
                vals.append(f"{v:.2f}")
            else:
                vals.append(str(v))
        lines.append(f"| {label} | {vals[0]} | {vals[1]} | {vals[2]} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 5. PER-SYMBOL COMPARISON")
    lines.append("")

    for src_name in ["CBDR", "SESSION_HL", "SWING_HL"]:
        lines.append(f"### {src_name}")
        lines.append("")
        tb = top_bot.get(src_name, {})
        top5 = tb.get("top_5", [])
        bot5 = tb.get("bottom_5", [])

        if top5:
            lines.append("**Top 5:**")
            lines.append("| Symbol | Trades | Win Rate | PnL (R) |")
            lines.append("|--------|--------|----------|---------|")
            for sym, pnl, trades, wr in top5:
                lines.append(f"| {sym} | {trades} | {wr:.1f}% | {pnl:.2f} |")
            lines.append("")

        if bot5:
            lines.append("**Bottom 5:**")
            lines.append("| Symbol | Trades | Win Rate | PnL (R) |")
            lines.append("|--------|--------|----------|---------|")
            for sym, pnl, trades, wr in bot5:
                lines.append(f"| {sym} | {trades} | {wr:.1f}% | {pnl:.2f} |")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 6. SWEEP FREQUENCY AUDIT")
    lines.append("")
    lines.append("| Source | Total Events | Events/day | Trades | Trades/day |")
    lines.append("|--------|-------------|------------|--------|------------|")
    for src_name in ["CBDR", "SESSION_HL", "SWING_HL"]:
        s = agg.get(src_name, {})
        lines.append(
            f"| {src_name} | {s.get('total_events', 0)} | {s.get('sweeps_per_day', 0):.1f} | {s.get('trades', 0)} | {s.get('trades_per_day', 0):.1f} |"
        )
    lines.append("")

    # Tolerance/ATR analysis
    lines.append("### Tolerance / ATR Analysis")
    lines.append("")
    lines.append(
        "Per-symbol median tolerance and tolerance/ATR ratio are recorded in per_symbol JSON output."
    )
    lines.append("")
    lines.append(
        "**Key question:** Is the sweep count driven by actual market behavior or by overly broad tolerance?"
    )
    lines.append("")
    lines.append("If tolerance/ATR ratio >> 1.0, the sweep detection may be too permissive.")
    lines.append("If tolerance/ATR ratio << 1.0, the sweep detection may be too restrictive.")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 7. LIMITATIONS")
    lines.append("")
    lines.append(
        "1. **1-month dataset** — NOT sufficient for final strategy validation. Discovery only."
    )
    lines.append("2. **MT5 server timezone unverified** — timestamps treated as MT5_SERVER_TIME.")
    lines.append(
        "3. **SESSION_HL and SWING_HL are NEW definitions** — not in existing strategy code."
    )
    lines.append("4. **No trailing/ATR fallback** — baseline execution model only.")
    lines.append("5. **Crypto live PnL NOT used as benchmark** — deterministic backtest only.")
    lines.append(
        "6. **Overlapping events** — some sweeps hit multiple liquidity sources simultaneously."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 8. CONCLUSIONS")
    lines.append("")
    lines.append("### A) WHAT THE DATA SHOWS")
    lines.append("")
    lines.append("[To be filled based on results]")
    lines.append("")
    lines.append("### B) WHAT THE DATA DOES NOT PROVE")
    lines.append("")
    lines.append("[To be filled based on results]")
    lines.append("")
    lines.append("### C) RECOMMENDED NEXT EXPERIMENT")
    lines.append("")
    lines.append("[To be filled based on results]")
    lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Written: {output_path}")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    start = time.time()

    forensics = LiquidityForensics(
        swing_lookback=5,
        sweep_atr_mult=0.5,
        default_tolerance=0.001,
        rr_ratio=1.8,
        cbdr_start_hour=19,
        cbdr_end_hour=1,
    )

    results = forensics.run_full_analysis()

    elapsed = time.time() - start
    print(f"\nAnalysis completed in {elapsed:.1f} seconds")

    # Save results
    os.makedirs("results", exist_ok=True)

    generate_forensics_json(results, "results/liquidity_source_forensics.json")
    generate_forensics_md(results, "results/liquidity_source_forensics.md")

    # Summary
    summary = results["summary"]
    agg = results["aggregate_source_stats"]

    print(f"\n{'=' * 60}")
    print("PHASE 3.2 — SWEEP FORENSICS SUMMARY")
    print(f"{'=' * 60}")
    print(f"Symbols:     {summary['symbols_analyzed']}")
    print(f"Total events: {summary['total_events']}")
    print(f"  CBDR:       {summary['cbdr_events']}")
    print(f"  SESSION_HL: {summary['session_hl_events']}")
    print(f"  SWING_HL:   {summary['swing_hl_events']}")
    print(f"  UNKNOWN:    {summary['unknown_events']}")
    print(f"Total trades: {summary['total_trades']}")
    print()

    for src_name in ["CBDR", "SESSION_HL", "SWING_HL"]:
        s = agg.get(src_name, {})
        print(f"{src_name}:")
        print(f"  Events:     {s.get('total_events', 0)}")
        print(f"  Trades:     {s.get('trades', 0)}")
        print(f"  Win Rate:   {s.get('win_rate', 0):.1f}%")
        print(f"  PF:         {s.get('profit_factor', 0):.2f}")
        print(f"  PnL (R):    {s.get('total_pnl', 0):.2f}")
        print(f"  Avg R:      {s.get('avg_r', 0):.2f}")
        print(f"  Max DD:     {s.get('max_drawdown', 0):.2f}")
        print(f"  Trades/day: {s.get('trades_per_day', 0):.1f}")
        print()
