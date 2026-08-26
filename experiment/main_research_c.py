"""
main_research_c.py — Research C Engine: C2 EQ (Post-Sweep Displacement EQ)

C2 EQ Formula: eq = (sweep_price + leg_mid) / 2.0
  where leg_mid = (max_high + min_low) / 2.0 across sweep→current window.
Canonical trailing: 1.8R. Dataset: 2.7Y / 6-major.

Parallel: 6 workers via ThreadPoolExecutor.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Dict, Any

# ── Setup paths ──
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# noqa: E402 — Project paths must be inserted before strategy imports
from src.strategy.data_loader import DataLoader  # noqa: E402
from src.strategy.session import SessionManager  # noqa: E402
from src.strategy.models import Bar, SweepEvent, Direction  # noqa: E402

# noqa: E402 — Project paths must be inserted before experiment imports
from experiment.config import (  # noqa: E402
    TP_RR,
    SL_ATR_MULT,
    FVG_MIN_SIZE_ATR_MULT,
    FVG_WICK_RATIO_MAX,
    FVG_BUFFER_MULT,
    FVG_BUFFER_MIN_FACTOR,
    MIN_RISK_DIST_ATR_MULT,
    ATR_PERIOD,
    SESSION_START_HOUR,
    SESSION_END_HOUR,
)
from experiment.trailing_adapter import apply_trailing, check_exit, _norm_side  # noqa: E402
from experiment.gemini_detector import detect_gemini_entry  # noqa: E402

# ── Portfolio equity curve starting balance ──
STARTING_BALANCE_R = 100.0
_NEXUS_SNIPER_SRC = str(Path("C:/Users/Administrator/Desktop/nexus-mcp/sniper/src"))
if _NEXUS_SNIPER_SRC not in sys.path:
    sys.path.insert(0, _NEXUS_SNIPER_SRC)

# noqa: E402,N813 — Nexus path must be set before importing from nexus models
from fvg import detect_fvgs as _nexus_detect_fvgs  # noqa: E402,N813
from models import FVG as NexusFVG  # noqa: N813,E402


# ── Trade Record ──
@dataclass
class BenchmarkTrade:
    trade_id: int
    symbol: str
    test_type: str
    direction: str
    entry_price: float
    sl: float
    tp: float
    entry_bar_index: int
    sweep_bar_index: int
    zone_index: int
    zone_creation_bar: int
    zone_top: float
    zone_bottom: float
    zone_size: float
    zone_size_atr: float
    sweep_size_atr: float
    bars_sweep_to_zone: int
    bars_zone_to_entry: int
    # Gemini-specific
    body_close_confirmed: bool = False
    master_bias: str = ""
    internal_sweep_found: bool = False
    purge_verified: bool = False
    freshness_ok: bool = True
    # Exit
    exit_price: float = 0.0
    exit_bar_index: int = 0
    exit_timestamp: float = 0.0
    result: str = ""
    pnl_r: float = 0.0
    # Trailing
    trailing_count: int = 0
    max_favorable: float = 0.0
    max_adverse: float = 0.0
    hold_bars: int = 0


# ── Helpers ──
def _to_nexus_bar(bar: Bar) -> "NexusBar":  # type: ignore[name-defined]  # noqa: F821,N813
    from models import Bar as NexusBar  # noqa: N813

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


def compute_atr(bars: List[Bar], period: int = 14) -> float:
    if len(bars) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(bars)):
        bar = bars[i]
        prev = bars[i - 1]
        tr = max(
            bar.high - bar.low,
            abs(bar.high - prev.close),
            abs(bar.low - prev.close),
        )
        trs.append(tr)
    if len(trs) < period:
        return 0.0
    import numpy as np

    return float(np.mean(trs[-period:]))


def resample_15m(bars_1m: List[Bar]) -> List[Bar]:
    _15M_MS = 15 * 60 * 1000
    buckets: dict = {}
    for b in bars_1m:
        ts_ms = (
            int(b.timestamp.timestamp() * 1000)
            if hasattr(b.timestamp, "timestamp")
            else 0
        )
        slot = (ts_ms // _15M_MS) * _15M_MS
        if slot not in buckets:
            buckets[slot] = []
        buckets[slot].append(b)

    m15: list[Bar] = []
    for slot in sorted(buckets):
        c = buckets[slot]
        if len(c) < 3:
            continue
        m15.append(
            Bar(
                index=len(m15),
                timestamp=c[0].timestamp,
                open=c[0].open,
                high=max(b.high for b in c),
                low=min(b.low for b in c),
                close=c[-1].close,
                volume=sum(b.volume for b in c),
            )
        )
    return m15


def _is_fresh_fvg(
    fvg: NexusFVG,
    bars_15m: List[Bar],
    current_index: int,
) -> bool:
    """Strict freshness check for FVG."""
    scan_from = fvg.real_index + 2
    for b in bars_15m[scan_from:current_index]:
        if fvg.direction == "bullish":
            if b.low <= fvg.top:
                return False
        else:
            if b.high >= fvg.bottom:
                return False
    return True


# ── TEST A: POST_SWEEP_FVG (existing baseline) ──
def run_test_a(
    symbol: str,
    bars_15m: List[Bar],
) -> List[BenchmarkTrade]:
    """Existing POST_SWEEP_FVG baseline — no body close, no internal sweep."""
    if len(bars_15m) < 100:
        return []

    warmup = min(100, len(bars_15m) - 10)
    atr_val = compute_atr(bars_15m[:warmup], period=ATR_PERIOD)
    if atr_val <= 0:
        return []

    session = SessionManager(
        symbol=symbol,
        start_hour=SESSION_START_HOUR,
        end_hour=SESSION_END_HOUR,
        atr=atr_val,
        sweep_atr_tolerance_mult=0.5,
        sweep_default_tolerance=10.0,
    )

    sweep_detected = False
    last_sweep: Optional[SweepEvent] = None
    active_trade: Optional[dict] = None
    trades: List[BenchmarkTrade] = []
    trade_counter = 0

    # Pre-build full nexus_bars list once — O(n), not O(n²)
    nexus_bars_full = [_to_nexus_bar(b) for b in bars_15m]

    start_idx = warmup + 1
    _last_heartbeat = start_idx
    for i in range(start_idx, len(bars_15m)):
        if i - _last_heartbeat >= 5000:
            print(f"  [HEARTBEAT] {symbol} bar {i}/{len(bars_15m)}", flush=True)
            _last_heartbeat = i
        bar = bars_15m[i]

        if i > start_idx:
            prev_close = bars_15m[i - 1].close
            tr = max(
                bar.high - bar.low,
                abs(bar.high - prev_close),
                abs(bar.low - prev_close),
            )
            atr_val = (atr_val * (ATR_PERIOD - 1) + tr) / ATR_PERIOD

        min_fvg_size = max(atr_val * FVG_MIN_SIZE_ATR_MULT, 1e-8)

        if active_trade is not None:
            apply_trailing(
                bars_15m[max(0, i - 500) : i + 1], [active_trade], atr_val, symbol
            )
            exit_info = check_exit(bar, active_trade)
            if exit_info is not None:
                exit_price = exit_info["exit_price"]
                result = exit_info["result"]
                # Direction-dispatch fix: branch on normalized side ("long"/"short"),
                # NOT on direction ("bullish"/"bearish") which never matched.
                if _norm_side(active_trade["side"]) == "long":
                    pnl_r = (exit_price - active_trade["entry_price"]) / abs(
                        active_trade["entry_price"] - active_trade["initial_sl"]
                    )
                else:
                    pnl_r = (active_trade["entry_price"] - exit_price) / abs(
                        active_trade["sl"] - active_trade["entry_price"]
                    )
                if result == "LOSS":
                    pnl_r = -1.0

                if _norm_side(active_trade["side"]) == "long":
                    mfe = (
                        active_trade.get("max_price", active_trade["entry_price"])
                        - active_trade["entry_price"]
                    ) / abs(active_trade["entry_price"] - active_trade["initial_sl"])
                    mae = (
                        active_trade["entry_price"]
                        - active_trade.get("min_price", active_trade["entry_price"])
                    ) / abs(active_trade["entry_price"] - active_trade["initial_sl"])
                else:
                    mfe = (
                        active_trade["entry_price"]
                        - active_trade.get("min_price", active_trade["entry_price"])
                    ) / abs(active_trade["sl"] - active_trade["entry_price"])
                    mae = (
                        active_trade.get("max_price", active_trade["entry_price"])
                        - active_trade["entry_price"]
                    ) / abs(active_trade["sl"] - active_trade["entry_price"])

                record = BenchmarkTrade(
                    trade_id=active_trade["trade_id"],
                    symbol=symbol,
                    test_type="POST_SWEEP_FVG",
                    direction=active_trade["direction"],
                    entry_price=active_trade["entry_price"],
                    sl=active_trade["initial_sl"],
                    tp=active_trade["initial_tp"],
                    entry_bar_index=active_trade["entry_bar"],
                    sweep_bar_index=active_trade["sweep_bar_index"],
                    zone_index=active_trade.get("zone_index", 0),
                    zone_creation_bar=active_trade.get("zone_creation_bar", 0),
                    zone_top=active_trade.get("zone_top", 0),
                    zone_bottom=active_trade.get("zone_bottom", 0),
                    zone_size=active_trade.get("zone_size", 0),
                    zone_size_atr=active_trade.get("zone_size_atr", 0),
                    sweep_size_atr=active_trade.get("sweep_size_atr", 0),
                    bars_sweep_to_zone=active_trade.get("bars_sweep_to_zone", 0),
                    bars_zone_to_entry=active_trade.get("bars_zone_to_entry", 0),
                    exit_price=exit_price,
                    exit_bar_index=i,
                    exit_timestamp=bar.timestamp,
                    result=result,
                    pnl_r=pnl_r,
                    trailing_count=active_trade.get("trailing_count", 0),
                    max_favorable=mfe,
                    max_adverse=mae,
                    hold_bars=i - active_trade["entry_bar"],
                )
                trades.append(record)
                active_trade = None
                continue

            active_trade["max_price"] = max(
                active_trade.get("max_price", bar.high), bar.high
            )
            active_trade["min_price"] = min(
                active_trade.get("min_price", bar.low), bar.low
            )
            continue

        sweep = session.update(bar)
        if sweep is not None:
            sweep_detected = True
            last_sweep = sweep

        if not sweep_detected or last_sweep is None:
            continue

        sweep_direction = (
            "bullish" if last_sweep.direction == Direction.BULLISH else "bearish"
        )
        lb = min(100, i + 1)
        nexus_bars = nexus_bars_full[i + 1 - lb : i + 1]

        fvgs = _nexus_detect_fvgs(
            nexus_bars,
            lookback=lb,
            timeframe="15m",
            min_fvg_size=min_fvg_size,
            max_wick_ratio=FVG_WICK_RATIO_MAX,
        )

        eq_rejected = 0

        for fvg in fvgs:
            if fvg.real_index <= last_sweep.bar_index:
                continue
            if fvg.direction != sweep_direction:
                continue
            if fvg.invalidated:
                continue
            if not _is_fresh_fvg(fvg, bars_15m, i):
                continue

            # ============================================================
            # SWEEP -> DISPLACEMENT EQ FILTER  (C2 variant)
            # ============================================================
            if i <= last_sweep.bar_index:
                continue

            window = bars_15m[last_sweep.bar_index : i + 1]

            if not window:
                continue

            leg_high = max(b.high for b in window)
            leg_low = min(b.low for b in window)

            # C2: midpoint between sweep_price and leg midpoint
            leg_mid = (leg_high + leg_low) / 2.0
            eq = (last_sweep.sweep_price + leg_mid) / 2.0

            # Entire FVG must be on the correct side of EQ.
            # Long  -> entire FVG in Discount
            # Short -> entire FVG in Premium
            if last_sweep.direction == Direction.BULLISH:
                if fvg.top > eq:
                    eq_rejected += 1
                    continue
            else:
                if fvg.bottom < eq:
                    eq_rejected += 1
                    continue

            if fvg.direction == "bullish":
                if not (bar.low <= fvg.top and bar.low >= fvg.bottom - atr_val * 0.1):
                    continue
            else:
                if not (bar.high >= fvg.bottom and bar.high <= fvg.top + atr_val * 0.1):
                    continue

            # NEXUS parity: next-bar-open execution
            if i + 1 >= len(bars_15m):
                continue  # No next bar available, skip trade
            entry_price = bars_15m[i + 1].open

            fh = fvg.top - fvg.bottom
            rp2 = atr_val * SL_ATR_MULT
            if fvg.direction == "bullish":
                ab = (
                    max(
                        fh * FVG_BUFFER_MIN_FACTOR,
                        max(rp2 * 0.1, min(fh * 0.25, rp2 * FVG_BUFFER_MULT)),
                    )
                    if fh > 0
                    else rp2 * 2
                )
                sl = fvg.bottom - ab if fh > 0 else entry_price - rp2 * 2
            else:
                ab = (
                    max(
                        fh * FVG_BUFFER_MIN_FACTOR,
                        max(rp2 * 0.1, min(fh * 0.25, rp2 * FVG_BUFFER_MULT)),
                    )
                    if fh > 0
                    else rp2 * 2
                )
                sl = fvg.top + ab if fh > 0 else entry_price + rp2 * 2

            rd = abs(entry_price - sl)
            if rd <= 0:
                sl = (
                    entry_price - rp2 * 2
                    if fvg.direction == "bullish"
                    else entry_price + rp2 * 2
                )
                rd = abs(entry_price - sl)
            tp = (
                entry_price + rd * TP_RR
                if fvg.direction == "bullish"
                else entry_price - rd * TP_RR
            )

            if rd < atr_val * MIN_RISK_DIST_ATR_MULT:
                continue

            trade_counter += 1
            active_trade = {
                # Direction-dispatch fix: side must be "long"/"short" for the
                # execution engine; direction stays "bullish"/"bearish" for records.
                "trade_id": trade_counter,
                "side": _norm_side(fvg.direction),
                "direction": fvg.direction,
                "entry_price": entry_price,
                "sl": sl,
                "tp": tp,
                "initial_sl": sl,
                "initial_tp": tp,
                "entry_bar": i + 1,
                "sweep_bar_index": last_sweep.bar_index,
                "zone_index": fvg.real_index,
                "zone_creation_bar": fvg.real_index,
                "zone_top": fvg.top,
                "zone_bottom": fvg.bottom,
                "zone_size": fvg.size,
                "zone_size_atr": fvg.size / atr_val if atr_val > 0 else 0,
                "sweep_size_atr": abs(
                    last_sweep.sweep_price - last_sweep.reference_level
                )
                / atr_val
                if atr_val > 0
                else 0,
                "bars_sweep_to_zone": fvg.real_index - last_sweep.bar_index,
                "bars_zone_to_entry": i - fvg.real_index,
                "trailing_count": 0,
                "max_price": entry_price,
                "min_price": entry_price,
                "closed": False,
            }
            sweep_detected = False
            last_sweep = None
            break

    # Close open trade
    if active_trade is not None and not active_trade.get("closed"):
        last_bar = bars_15m[-1]
        if _norm_side(active_trade["side"]) == "long":
            exit_price = last_bar.close
            pnl_r = (exit_price - active_trade["entry_price"]) / abs(
                active_trade["entry_price"] - active_trade["initial_sl"]
            )
        else:
            exit_price = last_bar.close
            pnl_r = (active_trade["entry_price"] - exit_price) / abs(
                active_trade["sl"] - active_trade["entry_price"]
            )

        record = BenchmarkTrade(
            trade_id=active_trade["trade_id"],
            symbol=symbol,
            test_type="POST_SWEEP_FVG",
            direction=active_trade["direction"],
            entry_price=active_trade["entry_price"],
            sl=active_trade["initial_sl"],
            tp=active_trade["initial_tp"],
            entry_bar_index=active_trade["entry_bar"],
            sweep_bar_index=active_trade["sweep_bar_index"],
            zone_index=active_trade.get("zone_index", 0),
            zone_creation_bar=active_trade.get("zone_creation_bar", 0),
            zone_top=active_trade.get("zone_top", 0),
            zone_bottom=active_trade.get("zone_bottom", 0),
            zone_size=active_trade.get("zone_size", 0),
            zone_size_atr=active_trade.get("zone_size_atr", 0),
            sweep_size_atr=active_trade.get("sweep_size_atr", 0),
            bars_sweep_to_zone=active_trade.get("bars_sweep_to_zone", 0),
            bars_zone_to_entry=active_trade.get("bars_zone_to_entry", 0),
            exit_price=exit_price,
            exit_bar_index=len(bars_15m) - 1,
            exit_timestamp=last_bar.timestamp,
            result="OPEN",
            pnl_r=pnl_r,
            trailing_count=active_trade.get("trailing_count", 0),
        )
        trades.append(record)

    return trades


# ── TEST B: GEMINI_SWEEP_FVG_NO_IFVG ──
def run_test_b(
    symbol: str,
    bars_15m: List[Bar],
) -> List[BenchmarkTrade]:
    """Gemini ICT/SMC — body close + master bias + internal sweep + FVG."""
    if len(bars_15m) < 100:
        return []

    warmup = min(100, len(bars_15m) - 10)
    atr_val = compute_atr(bars_15m[:warmup], period=ATR_PERIOD)
    if atr_val <= 0:
        return []

    session = SessionManager(
        symbol=symbol,
        start_hour=SESSION_START_HOUR,
        end_hour=SESSION_END_HOUR,
        atr=atr_val,
        sweep_atr_tolerance_mult=0.5,
        sweep_default_tolerance=10.0,
    )

    sweep_detected = False
    last_sweep: Optional[SweepEvent] = None
    active_trade: Optional[dict] = None
    trades: List[BenchmarkTrade] = []
    trade_counter = 0
    # Gemini state: track pending sweep waiting for body close + FVG
    pending_sweep: Optional[SweepEvent] = None
    pending_body_close_bar: Optional[int] = None

    start_idx = warmup + 1
    for i in range(start_idx, len(bars_15m)):
        bar = bars_15m[i]

        if i > start_idx:
            prev_close = bars_15m[i - 1].close
            tr = max(
                bar.high - bar.low,
                abs(bar.high - prev_close),
                abs(bar.low - prev_close),
            )
            atr_val = (atr_val * (ATR_PERIOD - 1) + tr) / ATR_PERIOD

        if active_trade is not None:
            apply_trailing(
                bars_15m[max(0, i - 500) : i + 1], [active_trade], atr_val, symbol
            )
            exit_info = check_exit(bar, active_trade)
            if exit_info is not None:
                exit_price = exit_info["exit_price"]
                result = exit_info["result"]
                # Direction-dispatch fix: branch on normalized side ("long"/"short").
                if _norm_side(active_trade["side"]) == "long":
                    pnl_r = (exit_price - active_trade["entry_price"]) / abs(
                        active_trade["entry_price"] - active_trade["initial_sl"]
                    )
                else:
                    pnl_r = (active_trade["entry_price"] - exit_price) / abs(
                        active_trade["sl"] - active_trade["entry_price"]
                    )
                if result == "LOSS":
                    pnl_r = -1.0

                if _norm_side(active_trade["side"]) == "long":
                    mfe = (
                        active_trade.get("max_price", active_trade["entry_price"])
                        - active_trade["entry_price"]
                    ) / abs(active_trade["entry_price"] - active_trade["initial_sl"])
                    mae = (
                        active_trade["entry_price"]
                        - active_trade.get("min_price", active_trade["entry_price"])
                    ) / abs(active_trade["entry_price"] - active_trade["initial_sl"])
                else:
                    mfe = (
                        active_trade["entry_price"]
                        - active_trade.get("min_price", active_trade["entry_price"])
                    ) / abs(active_trade["sl"] - active_trade["entry_price"])
                    mae = (
                        active_trade.get("max_price", active_trade["entry_price"])
                        - active_trade["entry_price"]
                    ) / abs(active_trade["sl"] - active_trade["entry_price"])

                record = BenchmarkTrade(
                    trade_id=active_trade["trade_id"],
                    symbol=symbol,
                    test_type="GEMINI_SWEEP_FVG",
                    direction=active_trade["direction"],
                    entry_price=active_trade["entry_price"],
                    sl=active_trade["initial_sl"],
                    tp=active_trade["initial_tp"],
                    entry_bar_index=active_trade["entry_bar"],
                    sweep_bar_index=active_trade["sweep_bar_index"],
                    zone_index=active_trade.get("zone_index", 0),
                    zone_creation_bar=active_trade.get("zone_creation_bar", 0),
                    zone_top=active_trade.get("zone_top", 0),
                    zone_bottom=active_trade.get("zone_bottom", 0),
                    zone_size=active_trade.get("zone_size", 0),
                    zone_size_atr=active_trade.get("zone_size_atr", 0),
                    sweep_size_atr=active_trade.get("sweep_size_atr", 0),
                    bars_sweep_to_zone=active_trade.get("bars_sweep_to_zone", 0),
                    bars_zone_to_entry=active_trade.get("bars_zone_to_entry", 0),
                    body_close_confirmed=active_trade.get(
                        "body_close_confirmed", False
                    ),
                    master_bias=active_trade.get("master_bias", ""),
                    internal_sweep_found=active_trade.get(
                        "internal_sweep_found", False
                    ),
                    purge_verified=active_trade.get("purge_verified", False),
                    exit_price=exit_price,
                    exit_bar_index=i,
                    exit_timestamp=bar.timestamp,
                    result=result,
                    pnl_r=pnl_r,
                    trailing_count=active_trade.get("trailing_count", 0),
                    max_favorable=mfe,
                    max_adverse=mae,
                    hold_bars=i - active_trade["entry_bar"],
                )
                trades.append(record)
                active_trade = None
                continue

            active_trade["max_price"] = max(
                active_trade.get("max_price", bar.high), bar.high
            )
            active_trade["min_price"] = min(
                active_trade.get("min_price", bar.low), bar.low
            )
            continue

        # ── Sweep detection ──
        sweep = session.update(bar)
        if sweep is not None:
            sweep_detected = True
            last_sweep = sweep
            pending_sweep = sweep
            pending_body_close_bar = None  # noqa: F841

        # ── Gemini entry chain: sweep → body close → FVG → internal sweep → entry ──
        if sweep_detected and last_sweep is not None:
            next_bar = bars_15m[i + 1] if i + 1 < len(bars_15m) else None
            gemini_result = detect_gemini_entry(
                bars_15m,
                last_sweep,
                bar,
                i,
                atr_val,
                symbol,
                next_bar=next_bar,
            )

            if gemini_result is not None:
                trade_counter += 1
                active_trade = {
                    # Direction-dispatch fix: side normalized for execution engine.
                    "trade_id": trade_counter,
                    "side": _norm_side(gemini_result.direction),
                    "direction": gemini_result.direction,
                    "entry_price": gemini_result.entry_price,
                    "sl": gemini_result.sl,
                    "tp": gemini_result.tp,
                    "initial_sl": gemini_result.sl,
                    "initial_tp": gemini_result.tp,
                    "entry_bar": i + 1,
                    "sweep_bar_index": gemini_result.sweep_bar_index,
                    "zone_index": gemini_result.fvg.real_index
                    if gemini_result.fvg
                    else 0,
                    "zone_creation_bar": gemini_result.fvg.real_index
                    if gemini_result.fvg
                    else 0,
                    "zone_top": gemini_result.fvg.top if gemini_result.fvg else 0,
                    "zone_bottom": gemini_result.fvg.bottom if gemini_result.fvg else 0,
                    "zone_size": gemini_result.fvg_size,
                    "zone_size_atr": gemini_result.fvg_size_atr,
                    "sweep_size_atr": gemini_result.sweep_size_atr,
                    "bars_sweep_to_zone": gemini_result.bars_sweep_to_fvg,
                    "bars_zone_to_entry": gemini_result.bars_fvg_to_entry,
                    "body_close_confirmed": gemini_result.body_close_confirmed,
                    "master_bias": gemini_result.master_bias,
                    "internal_sweep_found": gemini_result.internal_sweep_found,
                    "purge_verified": gemini_result.purge_verified,
                    "trailing_count": 0,
                    "max_price": gemini_result.entry_price,
                    "min_price": gemini_result.entry_price,
                    "closed": False,
                }
                sweep_detected = False
                last_sweep = None
                pending_sweep = None  # noqa: F841

    # Close open trade
    if active_trade is not None and not active_trade.get("closed"):
        last_bar = bars_15m[-1]
        if _norm_side(active_trade["side"]) == "long":
            exit_price = last_bar.close
            pnl_r = (exit_price - active_trade["entry_price"]) / abs(
                active_trade["entry_price"] - active_trade["initial_sl"]
            )
        else:
            exit_price = last_bar.close
            pnl_r = (active_trade["entry_price"] - exit_price) / abs(
                active_trade["sl"] - active_trade["entry_price"]
            )

        record = BenchmarkTrade(
            trade_id=active_trade["trade_id"],
            symbol=symbol,
            test_type="GEMINI_SWEEP_FVG",
            direction=active_trade["direction"],
            entry_price=active_trade["entry_price"],
            sl=active_trade["initial_sl"],
            tp=active_trade["initial_tp"],
            entry_bar_index=active_trade["entry_bar"],
            sweep_bar_index=active_trade["sweep_bar_index"],
            zone_index=active_trade.get("zone_index", 0),
            zone_creation_bar=active_trade.get("zone_creation_bar", 0),
            zone_top=active_trade.get("zone_top", 0),
            zone_bottom=active_trade.get("zone_bottom", 0),
            zone_size=active_trade.get("zone_size", 0),
            zone_size_atr=active_trade.get("zone_size_atr", 0),
            sweep_size_atr=active_trade.get("sweep_size_atr", 0),
            bars_sweep_to_zone=active_trade.get("bars_sweep_to_zone", 0),
            bars_zone_to_entry=active_trade.get("bars_zone_to_entry", 0),
            body_close_confirmed=active_trade.get("body_close_confirmed", False),
            master_bias=active_trade.get("master_bias", ""),
            internal_sweep_found=active_trade.get("internal_sweep_found", False),
            purge_verified=active_trade.get("purge_verified", False),
            exit_price=exit_price,
            exit_bar_index=len(bars_15m) - 1,
            exit_timestamp=last_bar.timestamp,
            result="OPEN",
            pnl_r=pnl_r,
            trailing_count=active_trade.get("trailing_count", 0),
        )
        trades.append(record)

    return trades


# ── Stats ──
def compute_stats(trades: List[BenchmarkTrade], starting_balance: float = STARTING_BALANCE_R) -> Dict[str, Any]:
    if not trades:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "open": 0,
            "win_rate": 0,
            "total_pnl": 0,
            "avg_r": 0,
            "max_dd": 0,
            "max_dd_pct": 0,
            "profit_factor": 0,
            "trailing_trades": 0,
            "total_hops": 0,
            "avg_hops": 0,
            "avg_mfe": 0,
            "avg_mae": 0,
            "median_mfe": 0,
            "median_mae": 0,
        }

    # Completed trades only (OPEN trades excluded from equity curve)
    completed = [t for t in trades if t.result in ("TP", "PROFIT_TRAIL", "LOSS")]
    wins = [t for t in completed if t.result in ("TP", "PROFIT_TRAIL")]
    losses = [t for t in completed if t.result == "LOSS"]
    total_pnl = sum(t.pnl_r for t in completed)

    # Chronological equity curve using exit_timestamp
    sorted_trades = sorted(completed, key=lambda t: t.exit_timestamp)
    equity = starting_balance
    peak = starting_balance
    max_dd = 0.0
    max_dd_pct = 0.0
    for t in sorted_trades:
        equity += t.pnl_r
        peak = max(peak, equity)
        dd = peak - equity
        max_dd = max(max_dd, dd)
        if peak > 0:
            max_dd_pct = max(max_dd_pct, dd / peak * 100)

    # Trailing stats
    trailed = [t for t in trades if t.trailing_count > 0]
    total_hops = sum(t.trailing_count for t in trades)

    # MFE/MAE
    mfes = [t.max_favorable for t in completed]
    maes = [t.max_adverse for t in completed]
    avg_mfe = statistics.mean(mfes) if mfes else 0
    avg_mae = statistics.mean(maes) if maes else 0
    median_mfe = statistics.median(mfes) if mfes else 0
    median_mae = statistics.median(maes) if maes else 0

    # Profit factor
    gross_wins = sum(t.pnl_r for t in wins)
    gross_losses = abs(sum(t.pnl_r for t in losses))
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else float("inf")

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "open": len([t for t in trades if t.result == "OPEN"]),
        "win_rate": len(wins) / len(completed) * 100 if completed else 0,
        "total_pnl": round(total_pnl, 4),
        "avg_r": round(total_pnl / len(completed), 4) if completed else 0,
        "max_dd": round(max_dd, 4),
        "max_dd_pct": round(max_dd_pct, 2),
        "profit_factor": round(profit_factor, 2),
        "trailing_trades": len(trailed),
        "total_hops": total_hops,
        "avg_hops": round(total_hops / len(trailed), 2) if trailed else 0,
        "avg_mfe": round(avg_mfe, 4),
        "avg_mae": round(avg_mae, 4),
        "median_mfe": round(median_mfe, 4),
        "median_mae": round(median_mae, 4),
    }


# ── Worker ──
def _run_symbol(sym: str, test_type: str, dry_run: bool) -> List[dict]:
    print(f"  [WORKER] {sym}: starting...", flush=True)
    feather_dir = _PROJECT_ROOT / "data" / "icmarket_feather"
    # Load 15m directly — no resampling needed
    import pandas as pd
    from src.strategy.models import Bar
    feather_path = feather_dir / f"{sym}_15m.feather"
    print(f"  [WORKER] {sym}: loading {feather_path}...", flush=True)
    df = pd.read_feather(feather_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    timestamps = df["timestamp"].values
    opens = df["open"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    closes = df["close"].values.astype(float)
    volumes = df["volume"].values.astype(float)
    bars_15m = [
        Bar(index=i, timestamp=pd.Timestamp(ts),
            open=o, high=h, low=l, close=c, volume=v)
        for i, ts, o, h, l, c, v in
        zip(range(len(timestamps)), timestamps, opens, highs, lows, closes, volumes)
    ]
    print(f"  [WORKER] {sym}: loaded {len(bars_15m)} 15m bars, backtesting...", flush=True)
    if dry_run:
        bars_15m = bars_15m[:2000]
    print(f"  [WORKER] {sym}: backtesting run_test_a({sym}, {len(bars_15m)} bars)...", flush=True)
    import time
    t0 = time.time()
    if test_type == "POST_SWEEP_FVG":
        trades = run_test_a(sym, bars_15m)
        t1 = time.time()
        print(f"  [WORKER] {sym}: run_test_a took {t1-t0:.1f}s", flush=True)
    else:
        trades = run_test_b(sym, bars_15m)
    elapsed = time.time() - t0
    print(f"  [WORKER] {sym}: done {len(trades)} trades in {elapsed:.1f}s", flush=True)
    return [asdict(t) for t in trades]


# ── Main ──
def main():
    parser = argparse.ArgumentParser(description="Gemini vs POST_SWEEP_FVG Benchmark")
    parser.add_argument("symbols", nargs="*", help="Symbols (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="Smoke test")
    parser.add_argument(
        "--workers", type=int, default=6, help="Parallel workers (default: 6)"
    )
    parser.add_argument(
        "--test", default="POST_SWEEP_FVG", help="Test type (default: POST_SWEEP_FVG)"
    )
    parser.add_argument(
        "--starting-balance",
        type=float,
        default=STARTING_BALANCE_R,
        help=f"Starting balance in R for DD% calc (default: {STARTING_BALANCE_R})",
    )
    args = parser.parse_args()

    loader = DataLoader(feather_dir=_PROJECT_ROOT / "data" / "icmarket_feather")
    symbols = (
        [s.upper() for s in args.symbols] if args.symbols else loader.list_symbols()
    )
    test_types = [args.test]

    print("=== RESEARCH C — C2 EQ BENCHMARK ===")
    print(f"Symbols: {len(symbols)} | Test: {test_types} | Workers: {args.workers} | Starting: {args.starting_balance}R")
    print(f"{'DRY RUN' if args.dry_run else 'FULL RUN'}")
    print()

    all_results = {}

    for test_type in test_types:
        print(f"--- {test_type} ---")
        t0 = time.time()
        test_trades = []

        print(f"  Submitting {len(symbols)} symbols to thread pool ({args.workers} workers)...", flush=True)
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(_run_symbol, sym, test_type, args.dry_run): sym
                for sym in symbols
            }
            pbar = tqdm(total=len(symbols), desc="Processing", unit="sym", ncols=80)
            print(f"  {len(futures)} futures submitted, waiting...", flush=True)
            for future in as_completed(futures):
                sym = futures[future]
                try:
                    trade_dicts = future.result()
                    for td in trade_dicts:
                        test_trades.append(BenchmarkTrade(**td))
                except Exception as e:
                    print(f"  ERROR {sym}: {e}")
                pbar.update(1)
            pbar.close()

        elapsed = time.time() - t0
        print(f"  Computing stats for {len(test_trades)} trades...", flush=True)
        stats = compute_stats(test_trades, starting_balance=args.starting_balance)
        all_results[test_type] = {
            "stats": stats,
            "trades": test_trades,
            "elapsed": elapsed,
        }

        completed = [t for t in test_trades if t.result != "OPEN"]
        open_n = len(test_trades) - len(completed)
        equity_trade_n = len([t for t in completed if t.exit_timestamp])

        print(
            f"  [{test_type}] {stats['trades']}T | {stats['wins']}W/{stats['losses']}L | "
            f"{stats['win_rate']:.1f}% WR | {stats['total_pnl']:+.2f}R | PF {stats['profit_factor']:.2f} | "
            f"DD {stats['max_dd']:.2f}R ({stats['max_dd_pct']:.2f}%) | "
            f"OPEN {open_n} | equity_curve {equity_trade_n} | completed==equity {len(completed) == equity_trade_n} | "
            f"{elapsed:.1f}s"
        )
        print()

    # Per-symbol breakdown
    print("\n=== PER-SYMBOL ===")
    syms = {}
    for t in test_trades:
        syms.setdefault(t.symbol, []).append(t)
    print(f"{'Symbol':<12} {'N':>5} {'WR%':>6} {'PnL':>10} {'AvgR':>8} {'PF':>6}")
    print("-" * 50)
    for sym in sorted(syms):
        s = compute_stats(syms[sym], starting_balance=args.starting_balance)
        print(
            f"{sym:<12} {s['trades']:>5d} {s['win_rate']:>5.1f}% "
            f"{s['total_pnl']:>+9.2f}R {s['avg_r']:>+7.4f} {s['profit_factor']:>5.2f}"
        )
    print()

    # Comparison
    print("=== COMPARISON ===")
    print(
        f"{'Test':<22} {'Trades':>7} {'WR%':>6} {'PnL':>10} {'AvgR':>8} {'PF':>6} "
        f"{'MaxDD':>8} {'MaxDD%':>8} {'Trail':>6}"
    )
    print("-" * 105)
    for tt in test_types:
        s = all_results[tt]["stats"]
        print(
            f"{tt:<22} {s['trades']:>7d} {s['win_rate']:>5.1f}% "
            f"{s['total_pnl']:>+9.2f}R {s['avg_r']:>+7.4f} {s['profit_factor']:>5.2f} "
            f"{s['max_dd']:>7.2f}R {s['max_dd_pct']:>7.2f}% {s['trailing_trades']:>6d}"
        )

    # Save
    output_dir = _PROJECT_ROOT / "results" / "benchmark"
    output_dir.mkdir(exist_ok=True)

    for tt in test_types:
        trades_data = [asdict(t) for t in all_results[tt]["trades"]]
        fname = f"{tt.lower()}_execution_v2_trades.json"
        with open(output_dir / fname, "w") as f:
            json.dump(trades_data, f, indent=2, default=str)

    summary = {tt: all_results[tt]["stats"] for tt in test_types}
    with open(output_dir / "execution_v2_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nResults saved to {output_dir}")


if __name__ == "__main__":
    main()
