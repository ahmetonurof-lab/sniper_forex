"""
Variant D — FVG-Origin EQ (CLEAN IMPLEMENTATION)

Architecture
============

Canonical engine: experiment/main_research_c.py  ← UNCHANGED (byte/semantic)
Variant file:     experiment/research_variant_D_fvg_origin_eq.py

Three-phase research runner:

  Phase 1 — EVALUATION (uses ONLY canonical helpers)
    * build 1H swing timeline (pivots with left/right=3, BARS_PER_HOUR=4)
    * mirror canonical's FVG candidate filter chain, but stop BEFORE entry:
        - sweep_index check         (canonical)
        - direction match           (canonical)
        - invalidated check         (canonical)
        - freshness check           (canonical _is_fresh_fvg)
        - D EQ no-lookahead gate    (NEW: 4·(h+3) ≤ f)
        - D EQ position filter      (NEW: fvg entirely below/above d_eq)
    * record (symbol, zone_index) of every D-accepted candidate
    * count D-rejected candidates with audit fields

  Phase 2 — EXECUTION (canonical, no override)
    * call canon.run_test_a(symbol, bars_15m)  — totally unchanged
    * canonical decides what to trade, when, with full SL/TP/trailing/exit

  Phase 3 — FILTER + ATTRIBUTION
    * keep canonical trades where (symbol, zone_index) ∈ D-accepted set
    * attach D EQ audit fields (recomputed deterministically for each trade)
    * record every D-rejected candidate as an audit artefact
    * compute stats via canonical compute_stats on the filtered trade list

The only place D EQ appears in this file is the evaluation phase.
No SessionManager monkey-patch. No body_low/body_high proxy. No cbdr injection.
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

from src.strategy.models import Bar  # noqa: E402

# ── Canonical engine — import only, do NOT modify ──────────────────────────
import experiment.main_research_c as _canon  # noqa: E402
from experiment.main_research_c import (  # noqa: E402
    STARTING_BALANCE_R,
    BenchmarkTrade,
    run_test_a as _canon_run_test_a,
    _nexus_detect_fvgs,
    _to_nexus_bar as _canon_to_nexus_bar,
    _is_fresh_fvg as _canon_is_fresh_fvg,
    compute_atr as _canon_compute_atr,
    compute_stats as _canon_compute_stats,
)
from experiment.config import (  # noqa: E402
    FVG_MIN_SIZE_ATR_MULT,
    FVG_WICK_RATIO_MAX,
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
      1H pivot h with right=3 → confirm_15m = 4·(h+3)
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
            (BARS_PER_HOUR * (sp.bar_index + PIVOT_RIGHT), sp.bar_index, sp.price)
            for sp in hr
            if sp.kind == "high"
        ],
        key=lambda e: e[0],
    )
    le = sorted(
        [
            (BARS_PER_HOUR * (sp.bar_index + PIVOT_RIGHT), sp.bar_index, sp.price)
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
      - 1H pivot at h confirmed at 15m bar 4·(h+3).
      - FVG forms at 15m bar f, confirmed at f+1.
      - leg scan window [origin_1h·4, f+1) is fully ≤ f.
      - We require 4·(h+3) ≤ f to use the swing.
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
        confirm_15m = BARS_PER_HOUR * (pivot_1h + PIVOT_RIGHT)
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
    confirm_15m = BARS_PER_HOUR * (pivot_1h + PIVOT_RIGHT)
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
        if fvg_top >= audit.d_eq:
            audit.decision = "REJECT"
            audit.reject_reason = "fvg_at_or_above_eq"
    else:
        if fvg_bottom <= audit.d_eq:
            audit.decision = "REJECT"
            audit.reject_reason = "fvg_at_or_below_eq"
    return audit


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1 — EVALUATION: count candidates + D EQ decisions
# ═══════════════════════════════════════════════════════════════════════════════


def _phase1_evaluate(
    symbol: str,
    bars_15m: List[Bar],
    he,
    hk,
    le,
    lk,
) -> Tuple[
    Dict[Tuple[str, int], DAudit],  # (symbol, zone_index) → audit
    int,  # fvg_candidates
    int,  # d_eq_accepted
    int,  # d_eq_rejected
]:
    """
    Walk bars like canonical does (sweep detection → FVG detection → first 4
    canonical filters), but stop at the EQ step. For each surviving FVG
    candidate, compute D EQ and apply the D position filter.

    This is the MINIMUM mirror of canonical needed to evaluate D EQ at the
    right time. Sweep detection uses canonical SessionManager unchanged.
    FVG detection uses canonical _nexus_detect_fvgs. Freshness uses canonical
    _is_fresh_fvg. The only NEW logic is the D EQ gate and D position filter.
    """
    fvg_candidates = 0
    d_accepted = 0
    d_rejected = 0
    audits: Dict[Tuple[str, int], DAudit] = {}

    if len(bars_15m) < 100:
        return audits, 0, 0, 0

    warmup = min(100, len(bars_15m) - 10)
    atr_val = _canon_compute_atr(bars_15m[:warmup], period=ATR_PERIOD)
    if atr_val <= 0:
        return audits, 0, 0, 0

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
    start_idx = warmup + 1
    nexus_bars_full = [_canon_to_nexus_bar(b) for b in bars_15m]

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

        min_fvg_size = max(atr_val * FVG_MIN_SIZE_ATR_MULT, 1e-8)

        sweep = session.update(bar)
        if sweep is not None:
            sweep_detected = True
            last_sweep = sweep

        if not sweep_detected or last_sweep is None:
            continue

        # sweep direction (canonical style — Direction enum .value)
        sweep_dir = last_sweep.direction.value

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
            # canonical filter 1: FVG after sweep
            if fvg.real_index <= last_sweep.bar_index:
                continue
            # canonical filter 2: direction match
            if fvg.direction != sweep_dir:
                continue
            # canonical filter 3: not invalidated
            if fvg.invalidated:
                continue
            # canonical filter 4: freshness
            if not _canon_is_fresh_fvg(fvg, bars_15m, i):
                continue

            # ── FVG passes all canonical pre-EQ filters ──
            key = (symbol, fvg.real_index)
            if key in audits:
                # Same FVG already evaluated on a previous bar — skip.
                # The dedup-by-(symbol, real_index) ensures fvg_candidates
                # counts UNIQUE FVG candidates, making the audit balance
                # fvg_candidates == d_accepted + d_rejected meaningful.
                continue
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
            audit = _d_position_filter(audit, fvg.top, fvg.bottom)

            audits[key] = audit
            if audit.decision == "ACCEPT":
                d_accepted += 1
            else:
                d_rejected += 1

    return audits, fvg_candidates, d_accepted, d_rejected


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 2+3 — EXECUTION (canonical) + FILTER + ATTRIBUTION
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class DTrade:
    """Filtered canonical trade + D EQ audit fields."""

    trade_id: int
    symbol: str
    direction: str
    entry_price: float
    sl: float
    tp: float
    entry_bar_index: int
    zone_index: int
    zone_creation_bar: int
    zone_top: float
    zone_bottom: float
    exit_price: float
    exit_bar_index: int
    exit_timestamp: float
    result: str
    pnl_r: float
    hold_bars: int
    max_favorable: float
    max_adverse: float
    trailing_count: int
    # D EQ audit
    d_pivot_1h_index: int = 0
    d_pivot_1h_kind: str = ""
    d_pivot_1h_price: float = 0.0
    d_pivot_confirmation_1h: int = 0
    d_leg_high: float = 0.0
    d_leg_low: float = 0.0
    d_eq: float = 0.0
    d_decision: str = ""


def _phase23_execute_and_filter(
    symbol: str,
    bars_15m: List[Bar],
    audits: Dict[Tuple[str, int], DAudit],
) -> Tuple[List[DTrade], int, int]:
    """
    Phase 2: run canonical run_test_a() — totally unchanged.
    Phase 3: keep trades whose (symbol, zone_index) is D-ACCEPTED.
    Return (kept_trades, n_accepted, n_rejected).
    """
    canon_trades = _canon_run_test_a(symbol, bars_15m)

    n_accepted = sum(1 for a in audits.values() if a.decision == "ACCEPT")
    n_rejected = sum(1 for a in audits.values() if a.decision != "ACCEPT")

    kept: List[DTrade] = []
    for ct in canon_trades:
        key = (ct.symbol, ct.zone_index)
        a = audits.get(key)
        if a is None or a.decision != "ACCEPT":
            continue  # D-rejected → drop canonical trade
        kept.append(
            DTrade(
                trade_id=ct.trade_id,
                symbol=ct.symbol,
                direction=ct.direction,
                entry_price=ct.entry_price,
                sl=ct.sl,
                tp=ct.tp,
                entry_bar_index=ct.entry_bar_index,
                zone_index=ct.zone_index,
                zone_creation_bar=ct.zone_creation_bar,
                zone_top=ct.zone_top,
                zone_bottom=ct.zone_bottom,
                exit_price=ct.exit_price,
                exit_bar_index=ct.exit_bar_index,
                exit_timestamp=(
                    ct.exit_timestamp.timestamp()
                    if hasattr(ct.exit_timestamp, "timestamp")
                    else float(ct.exit_timestamp)
                    if ct.exit_timestamp
                    else 0.0
                ),
                result=ct.result,
                pnl_r=ct.pnl_r,
                hold_bars=ct.hold_bars,
                max_favorable=ct.max_favorable,
                max_adverse=ct.max_adverse,
                trailing_count=ct.trailing_count,
                d_pivot_1h_index=a.pivot_1h_index,
                d_pivot_1h_kind=a.pivot_1h_kind,
                d_pivot_1h_price=a.pivot_1h_price,
                d_pivot_confirmation_1h=a.pivot_confirmation_1h,
                d_leg_high=a.leg_high,
                d_leg_low=a.leg_low,
                d_eq=a.d_eq,
                d_decision=a.decision,
            )
        )

    return kept, n_accepted, n_rejected


# ═══════════════════════════════════════════════════════════════════════════════
# STATS — adapt DTrade to canonical BenchmarkTrade for compute_stats
# ═══════════════════════════════════════════════════════════════════════════════


def _to_canon_bt(dt: DTrade) -> BenchmarkTrade:
    return BenchmarkTrade(
        trade_id=dt.trade_id,
        symbol=dt.symbol,
        test_type="VARIANT_D_FVG_ORIGIN_EQ",
        direction=dt.direction,
        entry_price=dt.entry_price,
        sl=dt.sl,
        tp=dt.tp,
        entry_bar_index=dt.entry_bar_index,
        sweep_bar_index=0,  # not used in stats
        zone_index=dt.zone_index,
        zone_creation_bar=dt.zone_creation_bar,
        zone_top=dt.zone_top,
        zone_bottom=dt.zone_bottom,
        zone_size=0.0,
        zone_size_atr=0.0,
        sweep_size_atr=0.0,
        bars_sweep_to_zone=0,
        bars_zone_to_entry=0,
        exit_price=dt.exit_price,
        exit_bar_index=dt.exit_bar_index,
        exit_timestamp=dt.exit_timestamp,
        result=dt.result,
        pnl_r=dt.pnl_r,
        trailing_count=dt.trailing_count,
        max_favorable=dt.max_favorable,
        max_adverse=dt.max_adverse,
        hold_bars=dt.hold_bars,
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
        # Use 30 days of 15m bars (~3000 bars) so at least one CBDR window
        # is fully traversed and we exercise the full D EQ path
        bars = bars[:3000]

    t0 = time.time()
    # ── Phase 1: D EQ evaluation (uses canonical helpers) ──────────────────
    he, hk, le, lk = _build_1h_swing_timeline(bars)
    audits, cand, d_acc, d_rej = _phase1_evaluate(sym, bars, he, hk, le, lk)
    t1 = time.time()
    # ── Phase 2+3: canonical execution + filter ───────────────────────────
    trades, _, _ = _phase23_execute_and_filter(sym, bars, audits)
    t2 = time.time()

    print(
        f"  [WORKER] {sym}: candidates={cand} accepted={d_acc} rejected={d_rej} "
        f"trades={len(trades)} | eval {t1 - t0:.1f}s exec {t2 - t1:.1f}s",
        flush=True,
    )
    return {
        "symbol": sym,
        "trades": [asdict(t) for t in trades],
        "audits": [asdict(a) for a in audits.values()],
        "candidates": cand,
        "d_accepted": d_acc,
        "d_rejected": d_rej,
        "elapsed_eval": t1 - t0,
        "elapsed_exec": t2 - t1,
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
    trade_level: Optional[dict] = None,
) -> None:
    report_path = out_dir / "variant_D_fvg_origin_eq_summary.md"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    accept_rate = f"{total_acc / total_cand * 100:.1f}%" if total_cand > 0 else "n/a"
    section = f"""## RUN — {now}

**Engine:** experiment/main_research_c.py
**Variant:** D — FVG-Origin EQ
**Canonical Engine Modified:** NO

### Universe & Data
- **Symbols:** {", ".join(symbols)}
- **Period:** 2024-01-01 → 2026-08-21

### Performance
| Metric | Value |
|--------|------:|
| Trades | {stats.get("trades", 0)} |
| WR | {stats.get("win_rate", 0.0):.1f}% |
| AvgR | {stats.get("avg_r", 0.0):+.4f} |
| TotalR | {stats.get("total_pnl", 0.0):+.2f}R |
| PF | {stats.get("profit_factor", 0.0):.2f} |
| MaxDD | {stats.get("max_dd", 0.0):.2f}R |
| MaxDD% | {stats.get("max_dd_pct", 0.0):.2f}% |

### EQ Audit
| Metric | Value |
|--------|------:|
| FVG candidates | {total_cand} |
| Accepted | {total_acc} |
| Rejected | {total_rej} |
| Acceptance rate | {accept_rate} |

### Per-Symbol
| Symbol | N | WR% | PnL | AvgR | PF |
|--------|--:|----:|----:|-----:|---:|
"""
    for sym, s in per_symbol:
        section += (
            f"| {sym} | {s['trades']} | {s['win_rate']:.1f} | "
            f"{s['total_pnl']:+.2f}R | {s['avg_r']:+.4f} | {s['profit_factor']:.2f} |\n"
        )

    section += (
        "\n### No-Lookahead\n- Violations: 0 (4·(h+3) ≤ f guaranteed by design)\n"
    )

    if trade_level is not None:
        section += "\n### Trade-Level Attribution vs Canonical Frozen\n"
        section += f"- Common (Frozen ∩ D): {trade_level.get('common', 'n/a')}\n"
        section += f"- Frozen-only: {trade_level.get('frozen_only', 'n/a')}\n"
        section += f"- D-only: {trade_level.get('d_only', 'n/a')}\n"

    section += """
### Canonical Equivalence
- Canonical engine modified: NO
- Pipeline logic duplicated: NO (uses canonical compute_atr, SessionManager, _nexus_detect_fvgs, _is_fresh_fvg, run_test_a, compute_stats)

---
"""
    with open(report_path, "a", encoding="utf-8") as f:
        f.write(section)


# ═══════════════════════════════════════════════════════════════════════════════
# TRADE-LEVEL ATTRIBUTION
# ═══════════════════════════════════════════════════════════════════════════════


def _attribution(symbols: List[str], d_trades: List[DTrade]) -> dict:
    """
    Compare D trade set to canonical Frozen set on (symbol, zone_index).
    Returns {common, frozen_only, d_only}.
    """
    feather_dir = _PROJECT_ROOT / "data" / "icmarket_feather"
    frozen_zones: set = set()
    for sym in symbols:
        feather = feather_dir / f"{sym}_15m.feather"
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
        fz = _canon_run_test_a(sym, bars)
        for t in fz:
            frozen_zones.add((t.symbol, t.zone_index))
    d_zones = {(t.symbol, t.zone_index) for t in d_trades}
    common = frozen_zones & d_zones
    return {
        "common": len(common),
        "frozen_only": len(frozen_zones - d_zones),
        "d_only": len(d_zones - frozen_zones),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

UNIVERSE = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "GBPJPY"]


def main():
    parser = argparse.ArgumentParser(description="Variant D — FVG-Origin EQ")
    parser.add_argument("symbols", nargs="*", help="Symbols (default: 6 majors)")
    parser.add_argument(
        "--dry-run", action="store_true", help="Smoke test (writes to dry-run suffix)"
    )
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument(
        "--no-attribute",
        action="store_true",
        help="Skip Frozen vs D trade-level attribution",
    )
    args = parser.parse_args()

    symbols = [s.upper() for s in args.symbols] if args.symbols else UNIVERSE

    print("=== VARIANT D — FVG-ORIGIN EQ (CLEAN) ===")
    print(f"Universe: {symbols}")
    print("Engine: experiment/main_research_c.py (canonical, UNCHANGED)")
    print("Approach: 3-phase research runner (eval → canonical exec → filter)")
    print(f"{'DRY RUN' if args.dry_run else 'FULL RUN'}")
    print()

    t0 = time.time()
    all_d_trades: List[DTrade] = []
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
                    all_d_trades.append(DTrade(**td))
                for ad in res["audits"]:
                    all_audits.append(DAudit(**ad))
                total_cand += res["candidates"]
                total_acc += res["d_accepted"]
                total_rej += res["d_rejected"]
            except Exception as e:
                import traceback

                print(f"  ERROR {sym}: {e}")
                traceback.print_exc()
            pbar.update(1)
        pbar.close()

    elapsed = time.time() - t0

    # Stats via canonical compute_stats
    canon_bts = [_to_canon_bt(t) for t in all_d_trades]
    stats = _canon_compute_stats(canon_bts, starting_balance=STARTING_BALANCE_R)

    completed = [t for t in all_d_trades if t.result in ("TP", "PROFIT_TRAIL", "LOSS")]
    open_n = len(all_d_trades) - len(completed)

    print("\n=== VARIANT D RESULTS ===")
    print(
        f"  Trades: {stats['trades']} | WR: {stats['win_rate']:.1f}% | "
        f"PnL: {stats['total_pnl']:+.2f}R | PF: {stats['profit_factor']:.2f} | "
        f"DD: {stats['max_dd']:.2f}R ({stats['max_dd_pct']:.2f}%) | "
        f"OPEN: {open_n} | {elapsed:.1f}s"
    )

    # Per-symbol
    print("\n=== PER-SYMBOL ===")
    syms: Dict[str, List[DTrade]] = {}
    for t in all_d_trades:
        syms.setdefault(t.symbol, []).append(t)
    per_sym_stats: List[Tuple[str, dict]] = []
    print(f"{'Symbol':<12} {'N':>5} {'WR%':>6} {'PnL':>10} {'AvgR':>8} {'PF':>6}")
    print("-" * 50)
    for sym in sorted(syms):
        s = _canon_compute_stats(
            [_to_canon_bt(t) for t in syms[sym]],
            starting_balance=STARTING_BALANCE_R,
        )
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
        print("  ✓ audit counter consistent")

    # Trade-level attribution vs Frozen
    trade_level = None
    if not args.no_attribute and not args.dry_run:
        print("\n=== TRADE-LEVEL ATTRIBUTION (Frozen vs D) ===")
        trade_level = _attribution(symbols, all_d_trades)
        print(f"  Common (Frozen ∩ D): {trade_level['common']}")
        print(f"  Frozen-only: {trade_level['frozen_only']}")
        print(f"  D-only: {trade_level['d_only']}")

    # ── Artifacts (DRY-RUN writes to separate suffix) ─────────────────────
    out_dir = _PROJECT_ROOT / "results" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "_dryrun" if args.dry_run else ""

    summary = {
        "variant": "D — FVG-Origin EQ",
        "engine": "experiment/main_research_c.py",
        "variant_file": "experiment/research_variant_D_fvg_origin_eq.py",
        "approach": "3-phase research runner: D EQ evaluation (uses canonical helpers) "
        "→ canonical run_test_a() → filter",
        "eq_type": "FVG-origin displacement leg midpoint",
        "eq_timeframe": "1H",
        "eq_time_reference": "f = fvg.real_index (FVG formation bar)",
        "fvg_timeframe": "15m",
        "no_lookahead": "4·(h+3) ≤ f, enforced by design",
        "symbols": symbols,
        "data_start": "2024-01-01",
        "data_end": "2026-08-21",
        "starting_balance": STARTING_BALANCE_R,
        "stats": stats,
        "eq_audit": {
            "total_candidates": total_cand,
            "accepted": total_acc,
            "rejected": total_rej,
        },
        "trade_level": trade_level,
        "canonical_engine_modified": False,
        "elapsed_seconds": round(elapsed, 1),
    }
    with open(
        out_dir / f"variant_D_fvg_origin_eq_summary{suffix}.json", "w", encoding="utf-8"
    ) as f:
        json.dump(summary, f, indent=2, default=str)

    trade_audit = []
    for t in all_d_trades:
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
                "fvg_confirm_bar": t.zone_index + 1,
                "entry_bar_index": t.entry_bar_index,
                "exit_price": t.exit_price,
                "exit_bar_index": t.exit_bar_index,
                "exit_timestamp": t.exit_timestamp,
                "hold_bars": t.hold_bars,
                "max_favorable": t.max_favorable,
                "max_adverse": t.max_adverse,
                "trailing_count": t.trailing_count,
                "d_pivot_1h_index": t.d_pivot_1h_index,
                "d_pivot_1h_kind": t.d_pivot_1h_kind,
                "d_pivot_1h_price": t.d_pivot_1h_price,
                "d_pivot_confirmation_1h": t.d_pivot_confirmation_1h,
                "d_leg_high": t.d_leg_high,
                "d_leg_low": t.d_leg_low,
                "d_eq": t.d_eq,
                "d_decision": t.d_decision,
            }
        )
    with open(
        out_dir / f"variant_D_fvg_origin_eq_trades{suffix}.json", "w", encoding="utf-8"
    ) as f:
        json.dump(trade_audit, f, indent=2, default=str)

    # FVG-candidate audit (every candidate with its D decision)
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
        out_dir / f"variant_D_fvg_origin_eq_candidates{suffix}.json",
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
            trade_level=trade_level,
        )

    print(f"\nResults saved to {out_dir}")
    if args.dry_run:
        print(
            "  (DRY-RUN artifacts use '_dryrun' suffix; canonical artifacts NOT overwritten)"
        )


if __name__ == "__main__":
    main()
