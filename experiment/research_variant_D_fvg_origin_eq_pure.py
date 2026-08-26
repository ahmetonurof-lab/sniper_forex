"""
Variant D — PURE FVG-Origin EQ (NO Frozen pre-filter, NO post-filter).

This is a PURE EQ comparison runner.

Architecture
============

Canonical engine: experiment/gemini_benchmark_eq.py  ← UNCHANGED (byte/semantic)
Variant file:     experiment/research_variant_D_fvg_origin_eq_pure.py

What this does
==============

Walks the canonical FVG evaluation/execution loop with ONLY one change:

  Frozen EQ source  →  D FVG-Origin EQ

Everything else is verbatim canonical:
  - sweep detection (canonical SessionManager)
  - FVG detection (canonical _nexus_detect_fvgs)
  - FVG direction filter (canonical)
  - FVG freshness (canonical _is_fresh_fvg)
  - entry touch check (canonical)
  - entry timing: next-bar-open (canonical)
  - SL/TP calculation (canonical, same constants)
  - trailing (canonical apply_trailing)
  - exit (canonical check_exit)
  - stats (canonical compute_stats)
  - starting balance (canonical STARTING_BALANCE_R = 100R)

What this does NOT do
=====================

  - No Frozen EQ pre-filter
  - No Frozen → D secondary veto
  - No Frozen → D refinement
  - No fallback to second FVG
  - No special second-FVG logic
  - No post-filter on canonical trades
  - No SessionManager monkey-patch
  - No body_low/body_high property proxy

Why we walk the loop ourselves (not call canon.run_test_a)
===========================================================

canon.run_test_a() has Frozen EQ hardcoded in its FVG evaluation block
(line ~352-364 in gemini_benchmark_eq.py):
  range_opposite = session.cbdr.body_low if ... else session.cbdr.body_high
  eq = (last_sweep.sweep_price + range_opposite) / 2
  if fvg.top > eq: continue   # Frozen EQ reject

The spec (item #7) explicitly disqualifies post-filtering canonical trades:
"Previous post-filter result is NOT a PURE D result."

To get a TRUE PURE D result, we must walk the FVG evaluation loop with
ONLY the EQ line swapped. The rest of the loop is verbatim canonical.

This is the minimum required to swap the EQ source. No new strategy rules,
no new sweep logic, no new FVG detector, no new SL/TP, no new trailing,
no new exit, no new stats. Every other line of the loop is canon.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
from tqdm import tqdm

# Force UTF-8 stdout (Windows cp1252 cannot encode arrows etc.)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.strategy.models import Bar, Direction  # noqa: E402

# ── Canonical engine — import only, do NOT modify ──────────────────────────
import experiment.gemini_benchmark_eq as _canon  # noqa: E402
from experiment.gemini_benchmark_eq import (  # noqa: E402
    STARTING_BALANCE_R,
    BenchmarkTrade,
    _nexus_detect_fvgs,
    _to_nexus_bar as _canon_to_nexus_bar,
    _is_fresh_fvg as _canon_is_fresh_fvg,
    compute_atr as _canon_compute_atr,
    compute_stats as _canon_compute_stats,
)
from experiment.trailing_adapter import (  # noqa: E402
    apply_trailing,
    check_exit,
    _norm_side,
)
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

# ── Nexus pivot API (FVG detection itself comes from canonical) ───────────
_NEXUS = str(Path("C:/Users/Administrator/Desktop/nexus-mcp/sniper/src"))
if _NEXUS not in sys.path:
    sys.path.insert(0, _NEXUS)

from pivot import find_swing_highs, find_swing_lows  # noqa: E402

# ── Constants ──────────────────────────────────────────────────────────────
BARS_PER_HOUR = 4
PIVOT_RIGHT = 3
PIVOT_LEFT = 3


# ═══════════════════════════════════════════════════════════════════════════════
# D EQ AUDIT
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class DAudit:
    """Audit record for one FVG candidate's D EQ decision."""

    symbol: str
    direction: str
    fvg_real_index: int
    fvg_confirm_bar: int
    pivot_1h_index: int
    pivot_1h_kind: str
    pivot_1h_price: float
    pivot_confirmation_1h: int
    leg_high: float
    leg_low: float
    d_eq: float
    decision: str  # "ACCEPT" | "REJECT"
    reject_reason: str = ""  # e.g. "no_pivot", "future_pivot", "fvg_above_eq"
    fvg_top: float = 0.0
    fvg_bottom: float = 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# PIVOT TIMELINE  (1H swings built from 15m bars, no future data)
# ═══════════════════════════════════════════════════════════════════════════════


def _build_1h_swing_timeline(
    bars_15m: List[Bar],
) -> Tuple[
    List[Tuple[int, int, float]],
    List[int],
    List[Tuple[int, int, float]],
    List[int],
]:
    """
    1H swing timeline from 15m bars.
    Returns (high_events, high_keys, low_events, low_keys), each sorted by
    confirm_15m where:
      event = (confirm_15m, pivot_1h_index, price)
      1H pivot h with right=3 → confirm_15m = 4·(h+4)-1
    """
    n_h = math.ceil(len(bars_15m) / BARS_PER_HOUR)
    if n_h < PIVOT_LEFT + PIVOT_RIGHT + 1:
        return ([], [], [], [])

    o_h, hi_h, lo_h, cl_h = [], [], [], []
    for h in range(n_h):
        s = h * BARS_PER_HOUR
        e = min(s + BARS_PER_HOUR, len(bars_15m))
        bk = bars_15m[s:e]
        o_h.append(bk[0].open)
        hi_h.append(max(b.high for b in bk))
        lo_h.append(min(b.low for b in bk))
        cl_h.append(bk[-1].close)

    nbars = [
        _canon_to_nexus_bar(
            Bar(
                index=h,
                timestamp=pd.Timestamp(0),
                open=o_h[h],
                high=hi_h[h],
                low=lo_h[h],
                close=cl_h[h],
                volume=0.0,
            )
        )
        for h in range(n_h)
    ]

    hr = find_swing_highs(nbars, left=PIVOT_LEFT, right=PIVOT_RIGHT)
    lr = find_swing_lows(nbars, left=PIVOT_LEFT, right=PIVOT_RIGHT)

    he = sorted(
        [
            (
                BARS_PER_HOUR * (sp.bar_index + PIVOT_RIGHT + 1) - 1,
                sp.bar_index,
                sp.price,
            )
            for sp in hr
            if sp.kind == "high"
        ],
        key=lambda e: e[0],
    )
    le = sorted(
        [
            (
                BARS_PER_HOUR * (sp.bar_index + PIVOT_RIGHT + 1) - 1,
                sp.bar_index,
                sp.price,
            )
            for sp in lr
            if sp.kind == "low"
        ],
        key=lambda e: e[0],
    )
    return he, [e[0] for e in he], le, [e[0] for e in le]


def _bisect_swing(
    keys: List[int],
    events: List[Tuple[int, int, float]],
    up_to: int,
) -> Optional[Tuple[int, float]]:
    """O(log n) latest swing confirmed at or before up_to."""
    idx = bisect_right(keys, up_to) - 1
    if idx < 0:
        return None
    return (events[idx][1], events[idx][2])  # (pivot_1h, price)


# ═══════════════════════════════════════════════════════════════════════════════
# D EQ CORE  (pure, no-lookahead, reference time f = fvg.real_index)
# ═══════════════════════════════════════════════════════════════════════════════


def compute_d_eq(
    f: int,
    direction: str,
    he,
    hk,
    le,
    lk,
    bars_15m: List[Bar],
) -> DAudit:
    """
    Compute D EQ at FVG-formation bar f.

    Returns DAudit with decision="REJECT" and reject_reason filled on any
    pre-filter failure. The D position filter is applied externally so the
    audit record can capture both the swing failure modes and the position
    filter failure mode.

    NO-LOOKAHEAD:
      - 1H pivot at h confirmed at 15m bar 4·(h+4)-1.
      - FVG forms at 15m bar f, confirmed at f+1.
      - leg scan window [origin_1h·4, f+1) is fully ≤ f.
      - We require 4·(h+4)-1 ≤ f to use the swing.
    """
    if direction == "bullish":
        sw = _bisect_swing(lk, le, f)
        if sw is None:
            return DAudit(
                symbol="",
                direction=direction,
                fvg_real_index=f,
                fvg_confirm_bar=f + 1,
                pivot_1h_index=0,
                pivot_1h_kind="low",
                pivot_1h_price=0.0,
                pivot_confirmation_1h=0,
                leg_high=0.0,
                leg_low=0.0,
                d_eq=0.0,
                decision="REJECT",
                reject_reason="no_pivot",
            )
        pivot_1h, swing_price = sw
        confirm_15m = BARS_PER_HOUR * (pivot_1h + PIVOT_RIGHT + 1) - 1
        if confirm_15m > f:
            return DAudit(
                symbol="",
                direction=direction,
                fvg_real_index=f,
                fvg_confirm_bar=f + 1,
                pivot_1h_index=pivot_1h,
                pivot_1h_kind="low",
                pivot_1h_price=swing_price,
                pivot_confirmation_1h=pivot_1h + PIVOT_RIGHT,
                leg_high=0.0,
                leg_low=0.0,
                d_eq=0.0,
                decision="REJECT",
                reject_reason="future_pivot",
            )
        origin_15m = pivot_1h * BARS_PER_HOUR
        scan_end = f + 1
        if origin_15m >= scan_end or scan_end > len(bars_15m):
            return DAudit(
                symbol="",
                direction=direction,
                fvg_real_index=f,
                fvg_confirm_bar=f + 1,
                pivot_1h_index=pivot_1h,
                pivot_1h_kind="low",
                pivot_1h_price=swing_price,
                pivot_confirmation_1h=pivot_1h + PIVOT_RIGHT,
                leg_high=0.0,
                leg_low=0.0,
                d_eq=0.0,
                decision="REJECT",
                reject_reason="empty_leg",
            )
        leg_high = max(bars_15m[j].high for j in range(origin_15m, scan_end))
        leg_low = swing_price
        d_eq = (leg_high + leg_low) / 2.0
        return DAudit(
            symbol="",
            direction=direction,
            fvg_real_index=f,
            fvg_confirm_bar=f + 1,
            pivot_1h_index=pivot_1h,
            pivot_1h_kind="low",
            pivot_1h_price=swing_price,
            pivot_confirmation_1h=pivot_1h + PIVOT_RIGHT,
            leg_high=leg_high,
            leg_low=leg_low,
            d_eq=d_eq,
            decision="ACCEPT",
            reject_reason="",
        )

    # bearish
    sw = _bisect_swing(hk, he, f)
    if sw is None:
        return DAudit(
            symbol="",
            direction=direction,
            fvg_real_index=f,
            fvg_confirm_bar=f + 1,
            pivot_1h_index=0,
            pivot_1h_kind="high",
            pivot_1h_price=0.0,
            pivot_confirmation_1h=0,
            leg_high=0.0,
            leg_low=0.0,
            d_eq=0.0,
            decision="REJECT",
            reject_reason="no_pivot",
        )
    pivot_1h, swing_price = sw
    confirm_15m = BARS_PER_HOUR * (pivot_1h + PIVOT_RIGHT + 1) - 1
    if confirm_15m > f:
        return DAudit(
            symbol="",
            direction=direction,
            fvg_real_index=f,
            fvg_confirm_bar=f + 1,
            pivot_1h_index=pivot_1h,
            pivot_1h_kind="high",
            pivot_1h_price=swing_price,
            pivot_confirmation_1h=pivot_1h + PIVOT_RIGHT,
            leg_high=0.0,
            leg_low=0.0,
            d_eq=0.0,
            decision="REJECT",
            reject_reason="future_pivot",
        )
    origin_15m = pivot_1h * BARS_PER_HOUR
    scan_end = f + 1
    if origin_15m >= scan_end or scan_end > len(bars_15m):
        return DAudit(
            symbol="",
            direction=direction,
            fvg_real_index=f,
            fvg_confirm_bar=f + 1,
            pivot_1h_index=pivot_1h,
            pivot_1h_kind="high",
            pivot_1h_price=swing_price,
            pivot_confirmation_1h=pivot_1h + PIVOT_RIGHT,
            leg_high=0.0,
            leg_low=0.0,
            d_eq=0.0,
            decision="REJECT",
            reject_reason="empty_leg",
        )
    leg_low = min(bars_15m[j].low for j in range(origin_15m, scan_end))
    leg_high = swing_price
    d_eq = (leg_high + leg_low) / 2.0
    return DAudit(
        symbol="",
        direction=direction,
        fvg_real_index=f,
        fvg_confirm_bar=f + 1,
        pivot_1h_index=pivot_1h,
        pivot_1h_kind="high",
        pivot_1h_price=swing_price,
        pivot_confirmation_1h=pivot_1h + PIVOT_RIGHT,
        leg_high=leg_high,
        leg_low=leg_low,
        d_eq=d_eq,
        decision="ACCEPT",
        reject_reason="",
    )


def _d_position_filter(audit: DAudit, fvg_top: float, fvg_bottom: float) -> DAudit:
    """
    Apply D EQ position filter to an audit that passed swing resolution.

    Bullish FVG must be ENTIRELY below D EQ.
    Bearish FVG must be ENTIRELY above D EQ.
    """
    if audit.decision == "REJECT":
        return audit
    if audit.direction == "bullish":
        if fvg_top > audit.d_eq:
            audit.decision = "REJECT"
            audit.reject_reason = "fvg_above_eq"
    else:
        if fvg_bottom < audit.d_eq:
            audit.decision = "REJECT"
            audit.reject_reason = "fvg_below_eq"
    return audit


# ═══════════════════════════════════════════════════════════════════════════════
# PURE D RUNNER — canonical FVG evaluation loop, ONLY the EQ source swapped
# ═══════════════════════════════════════════════════════════════════════════════


def run_test_a_pure_d(
    symbol: str,
    bars_15m: List[Bar],
    he,
    hk,
    le,
    lk,
) -> Tuple[List[BenchmarkTrade], Dict[Tuple[str, int], DAudit], Dict[str, int]]:
    """
    Verbatim canonical FVG evaluation/execution loop from gemini_benchmark_eq.run_test_a()
    with the ONLY change being the EQ source.

    Canonical EQ:
        range_opposite = session.cbdr.body_low / body_high
        eq = (last_sweep.sweep_price + range_opposite) / 2
        if fvg.top > eq: continue   (bullish sweep, long setup)
        if fvg.bottom < eq: continue (bearish sweep, short setup)

    PURE D EQ:
        d_eq = (leg_low + leg_high) / 2
        if fvg.top > d_eq: continue   (bullish FVG, long setup)
        if fvg.bottom < d_eq: continue (bearish FVG, short setup)

    Every other line — sweep, FVG detection, freshness, touch check,
    entry timing, SL/TP, trailing, exit, stats — is verbatim canonical.

    Returns (trades, audits, audit_counters).
    """
    if len(bars_15m) < 100:
        return [], {}, {"fvg_candidates": 0, "d_eq_accepted": 0, "d_eq_rejected": 0}

    warmup = min(100, len(bars_15m) - 10)
    atr_val = _canon_compute_atr(bars_15m[:warmup], period=ATR_PERIOD)
    if atr_val <= 0:
        return [], {}, {"fvg_candidates": 0, "d_eq_accepted": 0, "d_eq_rejected": 0}

    session = _canon.SessionManager(
        symbol=symbol,
        start_hour=SESSION_START_HOUR,
        end_hour=SESSION_END_HOUR,
        atr=atr_val,
        sweep_atr_tolerance_mult=0.5,
        sweep_default_tolerance=10.0,
    )

    sweep_detected = False
    last_sweep = None
    active_trade: Optional[dict] = None
    trades: List[BenchmarkTrade] = []
    trade_counter = 0

    # Pre-build full nexus_bars list once — O(n), not O(n²)
    nexus_bars_full = [_canon_to_nexus_bar(b) for b in bars_15m]

    fvg_candidates = 0
    d_eq_accepted = 0
    d_eq_rejected = 0
    audits: Dict[Tuple[str, int], DAudit] = {}

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
                    test_type="PURE_D_FVG_ORIGIN_EQ",
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

        # ─── canonical sweep_direction (verbatim) ───
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

        for fvg in fvgs:
            if fvg.real_index <= last_sweep.bar_index:
                continue
            if fvg.direction != sweep_direction:
                continue
            if fvg.invalidated:
                continue
            if not _canon_is_fresh_fvg(fvg, bars_15m, i):
                continue

            # ────────────────────────────────────────────────────────────
            #  PURE D EQ  (replaces canonical Frozen EQ block)
            #
            #  Canonical (gemini_benchmark_eq.py ~lines 352-364):
            #    range_opposite = session.cbdr.body_low  (bearish sweep)
            #                  or session.cbdr.body_high (bullish sweep)
            #    eq = (last_sweep.sweep_price + range_opposite) / 2
            #    if last_sweep.direction == Direction.BULLISH:
            #        if fvg.top > eq:  eq_rejected += 1; continue
            #    else:
            #        if fvg.bottom < eq: eq_rejected += 1; continue
            #
            #  PURE D replacement:
            #    d_eq = (leg_low + leg_high) / 2
            #    if fvg.top > d_eq:  REJECT  (bullish FVG, long setup)
            #    if fvg.bottom < d_eq: REJECT (bearish FVG, short setup)
            # ────────────────────────────────────────────────────────────

            key = (symbol, fvg.real_index)

            # D decision is computed ONCE per unique FVG and then reused.
            # IMPORTANT:
            # Audit dedup must NEVER suppress canonical touch/entry evaluation
            # on later bars. A previously accepted FVG must remain eligible for
            # canonical touch/entry checks until the canonical loop naturally
            # invalidates/exits it.
            audit = audits.get(key)

            if audit is None:
                fvg_candidates += 1

                audit = compute_d_eq(
                    fvg.real_index,
                    fvg.direction,
                    he,
                    hk,
                    le,
                    lk,
                    bars_15m,
                )

                audit.symbol = symbol
                audit.fvg_top = fvg.top
                audit.fvg_bottom = fvg.bottom

                audit = _d_position_filter(
                    audit,
                    fvg.top,
                    fvg.bottom,
                )

                audits[key] = audit

                if audit.decision == "ACCEPT":
                    d_eq_accepted += 1
                else:
                    d_eq_rejected += 1

            # D rejection is permanent for this FVG.
            # But D acceptance does NOT create an execution trade by itself.
            # The canonical touch/entry chain must still be evaluated on every
            # later bar exactly as canonical run_test_a() does.
            if audit.decision == "REJECT":
                continue

            # DO NOT continue here for ACCEPT.
            # Fall through to canonical touch/entry logic.

            # ─── canonical touch check (verbatim) ───
            if fvg.direction == "bullish":
                if not (bar.low <= fvg.top and bar.low >= fvg.bottom - atr_val * 0.1):
                    continue
            else:
                if not (bar.high >= fvg.bottom and bar.high <= fvg.top + atr_val * 0.1):
                    continue

            # ─── canonical entry timing: next-bar-open (verbatim) ───
            if i + 1 >= len(bars_15m):
                continue
            entry_price = bars_15m[i + 1].open

            # ─── canonical SL/TP calculation (verbatim) ───
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

            # ─── canonical active_trade dict (verbatim) ───
            trade_counter += 1
            active_trade = {
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

    # ─── canonical close open trade at end (verbatim) ───
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
            test_type="PURE_D_FVG_ORIGIN_EQ",
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

    return (
        trades,
        audits,
        {
            "fvg_candidates": fvg_candidates,
            "d_eq_accepted": d_eq_accepted,
            "d_eq_rejected": d_eq_rejected,
        },
    )


# ═══════════════════════════════════════════════════════════════════════════════
# WORKER
# ═══════════════════════════════════════════════════════════════════════════════


def _run_symbol(sym: str, dry_run: bool) -> dict:
    print(f"  [WORKER] {sym}: starting...", flush=True)
    feather = _PROJECT_ROOT / "data" / "icmarket_feather" / f"{sym}_15m.feather"
    df = pd.read_feather(feather)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    bars: List[Bar] = [
        Bar(
            index=i,
            timestamp=pd.Timestamp(df["timestamp"].iloc[i]),
            open=float(df["open"].iloc[i]),
            high=float(df["high"].iloc[i]),
            low=float(df["low"].iloc[i]),
            close=float(df["close"].iloc[i]),
            volume=float(df["volume"].iloc[i]),
        )
        for i in range(len(df))
    ]
    print(f"  [WORKER] {sym}: loaded {len(bars)} 15m bars", flush=True)
    if dry_run:
        bars = bars[:3000]

    t0 = time.time()
    he, hk, le, lk = _build_1h_swing_timeline(bars)
    trades, audits, counters = run_test_a_pure_d(sym, bars, he, hk, le, lk)
    elapsed = time.time() - t0

    print(
        f"  [WORKER] {sym}: candidates={counters['fvg_candidates']} "
        f"accepted={counters['d_eq_accepted']} "
        f"rejected={counters['d_eq_rejected']} "
        f"trades={len(trades)} | {elapsed:.1f}s",
        flush=True,
    )
    return {
        "symbol": sym,
        "trades": [asdict(t) for t in trades],
        "audits": [asdict(a) for a in audits.values()],
        "counters": counters,
        "elapsed": elapsed,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# MARKDOWN REPORT (APPEND-ONLY)
# ═══════════════════════════════════════════════════════════════════════════════


def _append_markdown_report(
    out_dir: Path,
    symbols: List[str],
    stats: dict,
    total_cand: int,
    total_acc: int,
    total_rej: int,
    elapsed: float,
    per_symbol: List[Tuple[str, dict]],
) -> None:
    report_path = out_dir / "variant_D_fvg_origin_eq_summary.md"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    accept_rate = f"{total_acc / total_cand * 100:.1f}%" if total_cand > 0 else "n/a"
    section = f"""## RUN — {now}

**Engine:** experiment/gemini_benchmark_eq.py
**Variant:** D — PURE FVG-Origin EQ
**Canonical Engine Modified:** NO
**Test Type:** Pure EQ variant comparison

### Universe & Data

- Symbols: {", ".join(symbols)}
- Period: 2024-01-01 → 2026-08-21
- FVG TF: 15m
- EQ TF: 1H

### EQ Definition

`d_eq = (leg_low + leg_high) / 2`

where the leg is anchored at the latest confirmed 1H structural swing available at FVG formation.

### Performance

| Metric | Value |
|---|---:|
| Trades | {stats.get("trades", 0)} |
| WR | {stats.get("win_rate", 0.0):.1f}% |
| AvgR | {stats.get("avg_r", 0.0):+.4f} |
| TotalR | {stats.get("total_pnl", 0.0):+.2f}R |
| PF | {stats.get("profit_factor", 0.0):.2f} |
| MaxDD R | {stats.get("max_dd", 0.0):.2f}R |
| MaxDD % | {stats.get("max_dd_pct", 0.0):.2f}% |

### EQ Audit

| Metric | Value |
|---|---:|
| FVG candidates evaluated | {total_cand} |
| D EQ accepted | {total_acc} |
| D EQ rejected | {total_rej} |
| Acceptance rate | {accept_rate} |

### No-Lookahead

- Violations: 0 (4·(h+4)-1 ≤ f guaranteed by design)

### Architecture

- Canonical engine modified: NO
- Frozen EQ pre-filter: NO
- Secondary-veto logic: NO
- Fallback logic: NO
- Pure D EQ comparison: YES

---
"""
    with open(report_path, "a", encoding="utf-8") as f:
        f.write(section)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

UNIVERSE = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "GBPJPY"]


def main():
    parser = argparse.ArgumentParser(description="Variant D — PURE FVG-Origin EQ")
    parser.add_argument("symbols", nargs="*", help="Symbols (default: 6 majors)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Smoke test (writes to _pure_dryrun suffix)",
    )
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    symbols = [s.upper() for s in args.symbols] if args.symbols else UNIVERSE

    print("=== VARIANT D — PURE FVG-ORIGIN EQ ===")
    print(f"Universe: {symbols}")
    print("Engine: experiment/gemini_benchmark_eq.py (canonical, UNCHANGED)")
    print("Approach: canonical FVG eval loop with ONLY the EQ source swapped")
    print("  Frozen EQ  →  D FVG-Origin EQ")
    print(f"{'DRY RUN' if args.dry_run else 'FULL RUN'}")
    print()

    t0 = time.time()
    all_trades: List[BenchmarkTrade] = []
    all_audits: List[DAudit] = []
    total_cand = 0
    total_acc = 0
    total_rej = 0

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(_run_symbol, s, args.dry_run): s for s in symbols}
        pbar = tqdm(total=len(symbols), desc="Processing", unit="sym", ncols=80)
        for future in as_completed(futures):
            sym = futures[future]
            try:
                res = future.result()
                for td in res["trades"]:
                    all_trades.append(BenchmarkTrade(**td))
                for ad in res["audits"]:
                    all_audits.append(DAudit(**ad))
                total_cand += res["counters"]["fvg_candidates"]
                total_acc += res["counters"]["d_eq_accepted"]
                total_rej += res["counters"]["d_eq_rejected"]
            except Exception as e:
                import traceback

                print(f"  ERROR {sym}: {e}")
                traceback.print_exc()
            pbar.update(1)
        pbar.close()

    elapsed = time.time() - t0

    # Stats via canonical compute_stats
    stats = _canon_compute_stats(all_trades, starting_balance=STARTING_BALANCE_R)

    completed = [t for t in all_trades if t.result in ("TP", "PROFIT_TRAIL", "LOSS")]
    open_n = len(all_trades) - len(completed)

    print("\n=== PURE D RESULTS ===")
    print(
        f"  Trades: {stats['trades']} | WR: {stats['win_rate']:.1f}% | "
        f"PnL: {stats['total_pnl']:+.2f}R | PF: {stats['profit_factor']:.2f} | "
        f"DD: {stats['max_dd']:.2f}R ({stats['max_dd_pct']:.2f}%) | "
        f"OPEN: {open_n} | {elapsed:.1f}s"
    )

    # Per-symbol
    print("\n=== PER-SYMBOL ===")
    syms: Dict[str, List[BenchmarkTrade]] = {}
    for t in all_trades:
        syms.setdefault(t.symbol, []).append(t)
    per_sym_stats: List[Tuple[str, dict]] = []
    print(f"{'Symbol':<12} {'N':>5} {'WR%':>6} {'PnL':>10} {'AvgR':>8} {'PF':>6}")
    print("-" * 50)
    for sym in sorted(syms):
        s = _canon_compute_stats(syms[sym], starting_balance=STARTING_BALANCE_R)
        print(
            f"{sym:<12} {s['trades']:>5} {s['win_rate']:>6.1f}% "
            f"{s['total_pnl']:>+10.2f}R {s['avg_r']:>8.4f} {s['profit_factor']:>6.2f}"
        )
        per_sym_stats.append((sym, s))

    print("\n=== EQ DECISION AUDIT ===")
    print(f"  FVG candidates evaluated: {total_cand}")
    print(f"  Accepted by D EQ: {total_acc}")
    print(f"  Rejected by D EQ: {total_rej}")
    if total_cand != total_acc + total_rej:
        print(f"  ⚠️  AUDIT MISMATCH: {total_cand} != {total_acc} + {total_rej}")
    else:
        print(f"  ✓ audit counter consistent: {total_cand} = {total_acc} + {total_rej}")

    # ── Artifacts (DRY-RUN writes to separate suffix) ─────────────────────
    out_dir = _PROJECT_ROOT / "results" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "_pure_dryrun" if args.dry_run else "_pure"

    summary = {
        "variant": "D — PURE FVG-Origin EQ",
        "engine": "experiment/gemini_benchmark_eq.py",
        "variant_file": "experiment/research_variant_D_fvg_origin_eq_pure.py",
        "approach": "canonical FVG eval/exec loop with ONLY the EQ source "
        "swapped: Frozen EQ → D FVG-Origin EQ. No pre-filter, "
        "no post-filter, no fallback.",
        "eq_type": "FVG-origin displacement leg midpoint",
        "eq_timeframe": "1H",
        "eq_time_reference": "f = fvg.real_index (FVG formation bar)",
        "fvg_timeframe": "15m",
        "no_lookahead": "4·(h+4)-1 ≤ f, enforced by design",
        "frozen_eq_pre_filter": False,
        "frozen_eq_post_filter": False,
        "fallback_logic": False,
        "secondary_veto": False,
        "symbols": symbols,
        "data_start": "2024-01-01",
        "data_end": "2026-08-21",
        "starting_balance": STARTING_BALANCE_R,
        "stats": stats,
        "eq_audit": {
            "fvg_candidates": total_cand,
            "d_eq_accepted": total_acc,
            "d_eq_rejected": total_rej,
        },
        "canonical_engine_modified": False,
        "elapsed_seconds": round(elapsed, 1),
    }
    with open(
        out_dir / f"variant_D_fvg_origin_eq{suffix}_summary.json", "w", encoding="utf-8"
    ) as f:
        json.dump(summary, f, indent=2, default=str)

    trade_audit = []
    for t in all_trades:
        trade_audit.append(
            {
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "direction": t.direction,
                "entry_price": t.entry_price,
                "sl": t.sl,
                "tp": t.tp,
                "result": t.result,
                "pnl_r": t.pnl_r,
                "zone_top": t.zone_top,
                "zone_bottom": t.zone_bottom,
                "zone_index": t.zone_index,
                "zone_creation_bar": t.zone_creation_bar,
                "exit_price": t.exit_price,
                "exit_bar_index": t.exit_bar_index,
                "exit_timestamp": (
                    t.exit_timestamp.timestamp()
                    if hasattr(t.exit_timestamp, "timestamp")
                    else float(t.exit_timestamp)
                    if t.exit_timestamp
                    else 0.0
                ),
                "hold_bars": t.hold_bars,
                "max_favorable": t.max_favorable,
                "max_adverse": t.max_adverse,
                "trailing_count": t.trailing_count,
            }
        )
    with open(
        out_dir / f"variant_D_fvg_origin_eq{suffix}_trades.json", "w", encoding="utf-8"
    ) as f:
        json.dump(trade_audit, f, indent=2, default=str)

    # FVG-candidate audit
    candidate_audit = []
    for a in all_audits:
        candidate_audit.append(
            {
                "symbol": a.symbol,
                "direction": a.direction,
                "fvg_real_index": a.fvg_real_index,
                "fvg_confirm_bar": a.fvg_confirm_bar,
                "fvg_top": a.fvg_top,
                "fvg_bottom": a.fvg_bottom,
                "pivot_1h_index": a.pivot_1h_index,
                "pivot_1h_kind": a.pivot_1h_kind,
                "pivot_1h_price": a.pivot_1h_price,
                "pivot_confirmation_1h": a.pivot_confirmation_1h,
                "leg_high": a.leg_high,
                "leg_low": a.leg_low,
                "d_eq": a.d_eq,
                "decision": a.decision,
                "reject_reason": a.reject_reason,
            }
        )
    with open(
        out_dir / f"variant_D_fvg_origin_eq{suffix}_candidates.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(candidate_audit, f, indent=2, default=str)

    # Append markdown (only full runs append to canonical artifact)
    if not args.dry_run:
        _append_markdown_report(
            out_dir=out_dir,
            symbols=symbols,
            stats=stats,
            total_cand=total_cand,
            total_acc=total_acc,
            total_rej=total_rej,
            elapsed=elapsed,
            per_symbol=per_sym_stats,
        )

    print(f"\nResults saved to {out_dir}")
    if args.dry_run:
        print(
            "  (DRY-RUN artifacts use '_pure_dryrun' suffix; "
            "previous artifacts NOT overwritten)"
        )


if __name__ == "__main__":
    main()
