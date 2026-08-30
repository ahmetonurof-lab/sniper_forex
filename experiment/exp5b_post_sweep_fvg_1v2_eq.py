"""
EXP 5B - 6 Aylik Research EQ + FVG #1/#2 Forensic Backtest
============================================================

Amaç: Production koduna dokunmadan, confirmed swing high/low tabanli
evolving Research EQ uzerine FVG #1/#2 forensic backtest.

Ana soru:
> CBDR Sweep sonrasi olusan FVG #1 ve FVG #2, confirmed swing high/low
  tabanli evolving Research EQ karsisinda nasil davraniyor ve hangi yapi
  daha anlamli?

Kurallar:
- Production EQ (eq = (sweep_price + range_opposite) / 2) DEGISMEZ; Research
  EQ sadece telemetry/research katmaninda hesaplanir.
- Canonical NEXUS pivots: find_swing_highs/lows(left=3, right=3), confirmed
  only (pivot p, right=3 kapanis barindan sonra konfirm olur → confirm=p+3).
  Timeline precompute O(n) bir kez; pivot gecerligi [p-left, p+right]
  penceresine baglidir → full-array tarama prefix cagrisi ile birebir ayni
  kumedir (future-safe).
- EQ position (exp5 / production EQ gate ile AYNI konvansiyon, whole-zone):
    bullish  -> CORRECT_SIDE iff FVG tamami EQ ALTINDA (discount)
    bearish  -> CORRECT_SIDE iff FVG tamami EQ USTUNDE (premium)
    CROSSES_EQ -> zone EQ'yu boler; NO_SWING_YET -> swing yok
- FIRST CORRECT SIDE ana metrik: formation'da correct ise swings=0; degilse
  confirmed swing UPDATE eventleri sirayla oynatilir, ilk CORRECT_SIDE'da
  durulur. Ayni bar'da konfirm olan coklu swing birlikte uygulanir.
- Freshness: canonical _is_fresh_fvg semantigi ([ri+2, c) dokunma yok).
- OB/Breaker: N/A (canonical detector yok, yenisi icat edilmez).
  Outcome attribution: KNOWN-GOOD run_test_a (main_research_c_v1_0) +
  zone_index eslestirme; raporlama amacli, entry kurali uretmez.

Reference: exp5_post_sweep_fvg_1v2.py immutable (structural research)
"""

from __future__ import annotations

import json
import multiprocessing as mp
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

_NEXUS_SNIPER_SRC = str(Path("C:/Users/Administrator/Desktop/nexus-mcp/sniper/src"))
if _NEXUS_SNIPER_SRC not in sys.path:
    sys.path.insert(0, _NEXUS_SNIPER_SRC)

# ── Canonical imports (reused, not reimplemented — same skeleton as exp5) ──
from fvg import detect_fvgs as _nexus_detect_fvgs
from models import FVG as NexusFVG
from models import Bar as NexusBar
from models import SwingPoint
from pivot import find_swing_highs, find_swing_lows

from experiment.config import (
    ATR_PERIOD,
    FVG_MIN_SIZE_ATR_MULT,
    FVG_WICK_RATIO_MAX,
    SESSION_END_HOUR,
    SESSION_START_HOUR,
)
from experiment.gemini_benchmark import _is_fresh_fvg, _to_nexus_bar, compute_atr

# KNOWN-GOOD frozen pipeline (main_research_c_v1_0.py; byte-identical to
# gemini_benchmark.py — verified by diff — exp5 uses the _eq module)
from experiment.main_research_c_v1_0 import resample_15m, run_test_a
from src.strategy.data_loader import DataLoader
from src.strategy.models import Bar, Direction
from src.strategy.session import SessionManager

ICMARKET_FEATHER = _PROJECT_ROOT / "data" / "icmarket_feather"
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "GBPJPY"]
WINDOW_DAYS = 180  # Full 6 months


@dataclass
class FvgResearchTelemetry:
    """Raw structural telemetry for one FVG (slot 1 or 2) of one sweep."""

    symbol: str
    sweep_index: int
    sweep_timestamp: str
    fvg_slot: int
    direction: str
    fvg_bar_index: int
    fvg_timestamp: str
    bars_from_sweep: int
    top: float
    bottom: float
    midpoint: float
    size: float
    size_atr: float
    fresh: bool
    eq_position: str
    research_eq: Optional[float]
    confirmed_swing_high_index: Optional[int]
    confirmed_swing_high_price: Optional[float]
    confirmed_swing_low_index: Optional[int]
    confirmed_swing_low_price: Optional[float]
    first_correct_side_bar_index: Optional[int]
    first_correct_side_timestamp: Optional[str]
    first_correct_side_swings: int
    still_fresh_at_first_correct: Optional[bool]
    invalidated_at_first_correct: bool
    stale_bar_index: Optional[int]  # first bar that touched the zone (canonical freshness)
    sweep_to_first_correct_min: Optional[float]
    formation_to_first_correct_min: Optional[float]
    ob_nearby: str = "N/A"
    breaker_nearby: str = "N/A"


@dataclass
class EvolvingEqRecord:
    """Record of EQ position evolution for an FVG."""

    bar_index: int
    timestamp: str
    swing_high_index: Optional[int]
    swing_high_price: Optional[float]
    swing_low_index: Optional[int]
    swing_low_price: Optional[float]
    research_eq: Optional[float]
    eq_position: str


def _get_latest_confirmed_swing(
    bars: List[Bar],
    up_to_index: int,
    is_high: bool = True,
    left: int = 3,
    right: int = 3,
) -> Optional[SwingPoint]:
    check_slice = bars[: up_to_index + 1]

    if len(check_slice) < left + right + 1:
        return None

    # Convert to NexusBar format (find_swing_* expects is_closed attribute)
    nexus_slice = [_to_nexus_bar(b) for b in check_slice]

    if is_high:
        swings = find_swing_highs(nexus_slice, left=left, right=right)
    else:
        swings = find_swing_lows(nexus_slice, left=left, right=right)

    valid_swings = [s for s in swings if s.bar_index <= up_to_index]

    if valid_swings:
        return valid_swings[-1]
    return None


def _compute_research_eq(
    swing_high: Optional[SwingPoint],
    swing_low: Optional[SwingPoint],
) -> Optional[float]:
    if swing_high is None or swing_low is None:
        return None
    return (swing_high.price + swing_low.price) / 2.0


# ─────────────────────────────────────────────────────────────────────────────
# Swing timeline fast path (O(n) once per symbol instead of O(n) per query)
# ─────────────────────────────────────────────────────────────────────────────
def _build_swing_timeline(
    bars_15m: List[Bar],
    left: int = 3,
    right: int = 3,
) -> Tuple[List[Tuple[int, int, float]], List[Tuple[int, int, float]]]:
    """Precompute ALL confirmed swing high/low events ONCE per symbol.

    Canonical pivot validity (pivot.py) depends ONLY on bars[p-left .. p+right]
    and requires `right` closed bars after the pivot → a pivot at index p is
    CONFIRMED at bar p+right and can never be revoked later. Therefore running
    find_swing_* over the full array yields exactly the same pivot set as any
    prefix call with len >= p+right+1 — future-safe by construction.

    Returns (high_events, low_events); each event is
    (confirm_index, pivot_index, price), sorted by confirm_index ascending.
    """
    nexus_bars = [_to_nexus_bar(b) for b in bars_15m]
    highs = [
        (sp.bar_index + right, sp.bar_index, sp.price)
        for sp in find_swing_highs(nexus_bars, left=left, right=right)
    ]
    lows = [
        (sp.bar_index + right, sp.bar_index, sp.price)
        for sp in find_swing_lows(nexus_bars, left=left, right=right)
    ]
    highs.sort(key=lambda e: e[0])
    lows.sort(key=lambda e: e[0])
    return highs, lows


def _latest_swing_from_timeline(
    events: List[Tuple[int, int, float]],
    up_to_index: int,
) -> Optional[Tuple[int, int, float]]:
    """Latest swing CONFIRMED at or before up_to_index (bisect).

    Exactly mirrors _get_latest_confirmed_swing(bars, up_to_index):
    a pivot p is visible as-of bar u iff p + right <= u.
    """
    lo, hi = 0, len(events)
    while lo < hi:
        mid = (lo + hi) // 2
        if events[mid][0] <= up_to_index:
            lo = mid + 1
        else:
            hi = mid
    return events[lo - 1] if lo > 0 else None


def _determine_eq_position(
    fvg_top: float,
    fvg_bottom: float,
    research_eq: Optional[float],
    direction: str,
) -> str:
    """Whole-zone Research EQ position — SAME convention as exp5 and the
    production EQ gate:

      bullish (long intent)  -> CORRECT_SIDE iff entire FVG BELOW EQ (discount)
      bearish (short intent) -> CORRECT_SIDE iff entire FVG ABOVE EQ (premium)

    CROSSES_EQ = zone straddles the EQ (meaningful label, unlike a midpoint
    equality which is measure-zero). NO_SWING_YET when either confirmed swing
    is missing so far.
    """
    if research_eq is None:
        return "NO_SWING_YET"

    if direction == "bullish":
        if fvg_top <= research_eq:
            return "CORRECT_SIDE"
        if fvg_bottom >= research_eq:
            return "WRONG_SIDE"
        return "CROSSES_EQ"
    else:
        if fvg_bottom >= research_eq:
            return "CORRECT_SIDE"
        if fvg_top <= research_eq:
            return "WRONG_SIDE"
        return "CROSSES_EQ"


def _check_fvg_invalidated(
    fvg: NexusFVG,
    bars: List[Bar],
    start_index: int,
    end_index: int,
) -> bool:
    """Reference touch-based invalidation (same zone-touch semantics as the
    canonical _is_fresh_fvg). Kept for tests/reference; production path uses
    _evolving_eq_first_correct which derives it from the freshness timeline."""
    for b in bars:
        if b.index < start_index or b.index > end_index:
            continue
        if fvg.direction == "bullish":
            if b.low <= fvg.top:
                return True
        else:
            if b.high >= fvg.bottom:
                return True
    return False


def _evolving_eq_first_correct(
    fvg_top: float,
    fvg_bottom: float,
    direction: str,
    fvg_real_index: int,
    bars_15m: List[Bar],
    high_events: List[Tuple[int, int, float]],
    low_events: List[Tuple[int, int, float]],
    left: int = 3,
    right: int = 3,
) -> Dict[str, Any]:
    """FIRST-CORRECT-SIDE evolving Research EQ analysis for one FVG.

    Semantics (spec section 4):
      • Formation state evaluated as-of fvg_real_index INCLUSIVE — only bars
        [0 .. fvg_real_index] are visible (no future leak).
      • Confirmed swing UPDATE events with confirm_index > fvg_real_index are
        replayed in order. Events sharing a confirm bar are applied together
        (state as-of that bar), each counting as one swing update.
      • The walk stops at the FIRST bar where the FVG sits CORRECT_SIDE.
        first_correct_side_swings = number of swing updates since formation.
      • Freshness reuses canonical _is_fresh_fvg semantics: fresh at bar c iff
        no bar in [fvg_real_index+2, c) touched the zone.

    Returns dict with:
      formation_position, formation_research_eq,
      formation_swing_high/low  (confirm_idx, pivot_idx, price) | None,
      first_touch_index         (first zone-touch bar, None = never touched),
      first_correct             dict(bar_index, timestamp, swings,
                                    still_fresh, invalidated) | None
    """
    # Canonical freshness timeline: first bar that touches the zone
    first_touch_index: Optional[int] = None
    scan_from = fvg_real_index + 2
    for b in bars_15m[scan_from:]:
        if b.index < scan_from:
            continue
        if direction == "bullish":
            if b.low <= fvg_top:
                first_touch_index = b.index
                break
        else:
            if b.high >= fvg_bottom:
                first_touch_index = b.index
                break

    sh = _latest_swing_from_timeline(high_events, fvg_real_index)
    sl = _latest_swing_from_timeline(low_events, fvg_real_index)

    def _position(sh_e, sl_e) -> Tuple[Optional[float], str]:
        eq = None
        if sh_e is not None and sl_e is not None:
            eq = (sh_e[2] + sl_e[2]) / 2.0
        return eq, _determine_eq_position(fvg_top, fvg_bottom, eq, direction)

    formation_eq, formation_pos = _position(sh, sl)

    first_correct: Optional[Dict[str, Any]] = None
    if formation_pos == "CORRECT_SIDE":
        # Freshness window [ri+2, ri) is empty at formation → trivially fresh
        first_correct = {
            "bar_index": fvg_real_index,
            "timestamp": str(bars_15m[fvg_real_index].timestamp),
            "swings": 0,
            "still_fresh": True,
            "invalidated": False,
        }
    else:
        updates = 0
        cur_sh, cur_sl = sh, sl
        ph = 0
        while ph < len(high_events) and high_events[ph][0] <= fvg_real_index:
            ph += 1
        pl = 0
        while pl < len(low_events) and low_events[pl][0] <= fvg_real_index:
            pl += 1

        while (ph < len(high_events) or pl < len(low_events)) and first_correct is None:
            # Take ALL events sharing the next confirm bar together
            next_c = min(
                high_events[ph][0] if ph < len(high_events) else float("inf"),
                low_events[pl][0] if pl < len(low_events) else float("inf"),
            )
            while ph < len(high_events) and high_events[ph][0] == next_c:
                cur_sh = high_events[ph]
                ph += 1
                updates += 1
            while pl < len(low_events) and low_events[pl][0] == next_c:
                cur_sl = low_events[pl]
                pl += 1
                updates += 1

            _, pos = _position(cur_sh, cur_sl)
            if pos == "CORRECT_SIDE":
                still_fresh = first_touch_index is None or first_touch_index >= next_c
                first_correct = {
                    "bar_index": int(next_c),
                    "timestamp": str(bars_15m[int(next_c)].timestamp),
                    "swings": updates,
                    "still_fresh": bool(still_fresh),
                    "invalidated": not bool(still_fresh),
                }

    return {
        "formation_position": formation_pos,
        "formation_research_eq": formation_eq,
        "formation_swing_high": sh,
        "formation_swing_low": sl,
        "first_touch_index": first_touch_index,
        "first_correct": first_correct,
    }


def _analyze_symbol(symbol: str) -> Dict[str, Any]:
    loader = DataLoader(feather_dir=ICMARKET_FEATHER)
    bars_1m = loader.load(symbol)

    if bars_1m:
        max_ts = bars_1m[-1].timestamp
        cutoff = max_ts - pd.Timedelta(days=WINDOW_DAYS)
        bars_1m = [b for b in bars_1m if b.timestamp >= cutoff]

    bars_15m = resample_15m(bars_1m)

    if len(bars_15m) < 100:
        return {
            "symbol": symbol,
            "telemetry": [],
            "trades": [],
            "n_sweeps": 0,
            "date_range": [],
        }

    warmup = min(100, len(bars_15m) - 10)
    atr_val = compute_atr(bars_15m[:warmup], period=ATR_PERIOD)
    if atr_val <= 0:
        return {
            "symbol": symbol,
            "telemetry": [],
            "trades": [],
            "n_sweeps": 0,
            "date_range": [],
        }

    session = SessionManager(
        symbol=symbol,
        start_hour=SESSION_START_HOUR,
        end_hour=SESSION_END_HOUR,
        atr=atr_val,
        sweep_atr_tolerance_mult=0.5,
        sweep_default_tolerance=10.0,
    )

    min_fvg_size = max(atr_val * FVG_MIN_SIZE_ATR_MULT, 1e-8)

    sweep_contexts: List[Dict[str, Any]] = []
    active_context: Optional[Dict[str, Any]] = None
    sweep_counter = 0
    nexus_bars: List[NexusBar] = []

    for i in range(warmup + 1, len(bars_15m)):
        bar = bars_15m[i]
        nexus_bars.append(_to_nexus_bar(bar))

        if i > warmup + 1:
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
            sweep_counter += 1
            active_context = {
                "sweep": sweep,
                "sweep_index": sweep_counter,
                "direction": "bullish" if sweep.direction == Direction.BULLISH else "bearish",
                "fvgs": [],
                "real_indices": set(),
                "complete": False,
            }
            sweep_contexts.append(active_context)

        if active_context is not None and not active_context["complete"]:
            fvgs = _nexus_detect_fvgs(
                nexus_bars,
                lookback=min(100, len(nexus_bars)),
                timeframe="15m",
                min_fvg_size=min_fvg_size,
                max_wick_ratio=FVG_WICK_RATIO_MAX,
            )
            for fvg in fvgs:
                if fvg.real_index <= active_context["sweep"].bar_index:
                    continue
                if fvg.direction != active_context["direction"]:
                    continue
                if fvg.invalidated:
                    continue
                if not _is_fresh_fvg(fvg, bars_15m, i):
                    continue
                if fvg.real_index in active_context["real_indices"]:
                    continue
                active_context["real_indices"].add(fvg.real_index)
                active_context["fvgs"].append(fvg)
                if len(active_context["fvgs"]) >= 2:
                    active_context["complete"] = True
                    break

    telemetry: List[FvgResearchTelemetry] = []
    # Research EQ layer: precompute confirmed swing timeline ONCE per symbol
    timeline_highs, timeline_lows = _build_swing_timeline(bars_15m, left=3, right=3)

    for ctx in sweep_contexts:
        sweep = ctx["sweep"]
        direction = ctx["direction"]
        sweep_ts = str(bars_15m[sweep.bar_index].timestamp)

        for slot, fvg in enumerate(ctx["fvgs"], start=1):
            ev = _evolving_eq_first_correct(
                fvg.top,
                fvg.bottom,
                direction,
                fvg.real_index,
                bars_15m,
                timeline_highs,
                timeline_lows,
                left=3,
                right=3,
            )
            fc = ev["first_correct"]
            sh_e = ev["formation_swing_high"]
            sl_e = ev["formation_swing_low"]

            telemetry.append(
                FvgResearchTelemetry(
                    symbol=symbol,
                    sweep_index=ctx["sweep_index"],
                    sweep_timestamp=sweep_ts,
                    fvg_slot=slot,
                    direction=direction,
                    fvg_bar_index=fvg.real_index,
                    fvg_timestamp=str(bars_15m[fvg.real_index].timestamp),
                    bars_from_sweep=fvg.real_index - sweep.bar_index,
                    top=fvg.top,
                    bottom=fvg.bottom,
                    midpoint=fvg.midpoint,
                    size=fvg.size,
                    size_atr=fvg.size / atr_val if atr_val > 0 else 0.0,
                    # fresh = never touched since formation (canonical freshness)
                    fresh=ev["first_touch_index"] is None,
                    eq_position=ev["formation_position"],
                    research_eq=ev["formation_research_eq"],
                    confirmed_swing_high_index=sh_e[1] if sh_e else None,
                    confirmed_swing_high_price=sh_e[2] if sh_e else None,
                    confirmed_swing_low_index=sl_e[1] if sl_e else None,
                    confirmed_swing_low_price=sl_e[2] if sl_e else None,
                    first_correct_side_bar_index=fc["bar_index"] if fc else None,
                    first_correct_side_timestamp=fc["timestamp"] if fc else None,
                    first_correct_side_swings=fc["swings"] if fc else 0,
                    still_fresh_at_first_correct=(fc["still_fresh"] if fc else None),
                    invalidated_at_first_correct=(fc["invalidated"] if fc else False),
                    stale_bar_index=ev["first_touch_index"],
                    sweep_to_first_correct_min=((fc["bar_index"] - sweep.bar_index) * 15.0)
                    if fc
                    else None,
                    formation_to_first_correct_min=((fc["bar_index"] - fvg.real_index) * 15.0)
                    if fc
                    else None,
                    ob_nearby="N/A",
                    breaker_nearby="N/A",
                )
            )

    trades = run_test_a(symbol, bars_15m)

    sweep_fvg_map: Dict[int, Tuple[Optional[int], Optional[int]]] = {}
    for ctx in sweep_contexts:
        fvgs = ctx["fvgs"]
        f1 = fvgs[0].real_index if len(fvgs) >= 1 else None
        f2 = fvgs[1].real_index if len(fvgs) >= 2 else None
        sweep_fvg_map[ctx["sweep"].bar_index] = (f1, f2)

    trade_attr = []
    for t in trades:
        f1, f2 = sweep_fvg_map.get(t.sweep_bar_index, (None, None))
        if t.zone_index == f1:
            slot = 1
        elif t.zone_index == f2:
            slot = 2
        else:
            slot = 0
        trade_attr.append(
            {
                "symbol": t.symbol,
                "result": t.result,
                "pnl_r": t.pnl_r,
                "direction": t.direction,
                "slot": slot,
                "zone_index": t.zone_index,
                "sweep_bar_index": t.sweep_bar_index,
                "entry_bar_index": t.entry_bar_index,
                "exit_bar_index": t.exit_bar_index,
            }
        )

    return {
        "symbol": symbol,
        "telemetry": telemetry,
        "trades": trade_attr,
        "n_sweeps": len(sweep_contexts),
        "date_range": [str(bars_15m[0].timestamp), str(bars_15m[-1].timestamp)],
    }


def _worker(symbol: str) -> Dict[str, Any]:
    try:
        return _analyze_symbol(symbol)
    except Exception as e:
        return {
            "symbol": symbol,
            "telemetry": [],
            "trades": [],
            "n_sweeps": 0,
            "date_range": [],
            "error": str(e),
        }


def _compute_research_eq_metrics(
    records: List[FvgResearchTelemetry],
) -> Dict[str, Dict[int, int]]:
    """FVG #1 vs #2 Research EQ metrics.

    Classification is mutually exclusive (no double counting):
      • correct_at_formation  — CORRECT_SIDE at formation (first correct = formation,
                                0 swing updates; counted fresh trivially)
      • later_becomes_correct — NOT correct at formation, but first-correct exists
                                (swings >= 1 by construction)
      • never_correct         — NOT correct at formation and no first-correct
    """
    metrics = {
        "total": {1: 0, 2: 0},
        "correct_at_formation": {1: 0, 2: 0},
        "crosses_eq": {1: 0, 2: 0},
        "wrong_at_formation": {1: 0, 2: 0},
        "no_swing_yet": {1: 0, 2: 0},
        "later_becomes_correct": {1: 0, 2: 0},
        "never_correct": {1: 0, 2: 0},
        "correct_after_1_swing": {1: 0, 2: 0},
        "correct_after_2_swings": {1: 0, 2: 0},
        "correct_after_3plus_swings": {1: 0, 2: 0},
        # fresh at first correct — over the LATER cohort only (spec metric #4)
        "fresh_when_first_correct": {1: 0, 2: 0},
        # fresh at first correct — over ALL first-correct events
        "fresh_when_first_correct_all": {1: 0, 2: 0},
    }

    for r in records:
        s = r.fvg_slot
        metrics["total"][s] += 1

        formation_correct = r.eq_position == "CORRECT_SIDE"

        # Position bucket (mutually exclusive)
        if formation_correct:
            metrics["correct_at_formation"][s] += 1
            # first correct = formation (0 updates); freshness trivially True
            if r.still_fresh_at_first_correct:
                metrics["fresh_when_first_correct_all"][s] += 1
        elif r.eq_position == "CROSSES_EQ":
            metrics["crosses_eq"][s] += 1
        elif r.eq_position == "WRONG_SIDE":
            metrics["wrong_at_formation"][s] += 1
        else:
            metrics["no_swing_yet"][s] += 1

        if formation_correct:
            continue  # never double-counted as "later"

        if r.first_correct_side_bar_index is not None:
            metrics["later_becomes_correct"][s] += 1
            k = r.first_correct_side_swings
            if k == 1:
                metrics["correct_after_1_swing"][s] += 1
            elif k == 2:
                metrics["correct_after_2_swings"][s] += 1
            else:
                metrics["correct_after_3plus_swings"][s] += 1
            if r.still_fresh_at_first_correct:
                metrics["fresh_when_first_correct"][s] += 1
                metrics["fresh_when_first_correct_all"][s] += 1
        else:
            metrics["never_correct"][s] += 1

    return metrics


def _outcome_stats(trades: List[Dict[str, Any]], label: str) -> Dict[str, Any]:
    completed = [t for t in trades if t["result"] in ("TP", "PROFIT_TRAIL", "LOSS")]
    wins = [t for t in completed if t["result"] in ("TP", "PROFIT_TRAIL")]
    losses = [t for t in completed if t["result"] == "LOSS"]
    opens = [t for t in trades if t["result"] == "OPEN"]
    n = len(trades)
    wr = len(wins) / len(completed) * 100 if completed else 0.0
    rs = [t["pnl_r"] for t in completed]
    total_r = sum(rs)
    avg_r = total_r / len(completed) if completed else 0.0
    cum = peak = maxdd = 0.0
    for t in sorted(completed, key=lambda x: x["exit_bar_index"]):
        cum += t["pnl_r"]
        peak = max(peak, cum)
        maxdd = max(maxdd, peak - cum)
    return {
        "label": label,
        "N": n,
        "completed": len(completed),
        "WR%": round(wr, 2),
        "total_R": round(total_r, 2),
        "avg_R": round(avg_r, 4),
        "MaxDD": round(maxdd, 2),
        "TP": len([t for t in completed if t["result"] == "TP"]),
        "PROFIT_TRAIL": len([t for t in completed if t["result"] == "PROFIT_TRAIL"]),
        "LOSS": len(losses),
        "OPEN": len(opens),
    }


def main():
    t0 = time.time()
    print("=== EXP 5B - 6 Aylik Research EQ + FVG #1/#2 Forensic Backtest ===")
    print(f"Symbols: {SYMBOLS} | 6 parallel workers | data: {ICMARKET_FEATHER}")
    print(f"Window: {WINDOW_DAYS} days | left=3, right=3 swing detection | Research EQ only")
    print()

    with mp.Pool(processes=6) as pool:
        results = pool.map(_worker, SYMBOLS)

    all_telemetry: List[FvgResearchTelemetry] = []
    all_trades: List[Dict[str, Any]] = []
    per_symbol: Dict[str, Dict[str, Any]] = {}
    for sym, res in zip(SYMBOLS, results):
        if "error" in res and res.get("error"):
            print(f"  {sym:10s}: ERROR -> {res['error']}")
            continue
        per_symbol[sym] = res
        all_telemetry.extend(res["telemetry"])
        all_trades.extend(res["trades"])
        print(
            f"  {sym:10s}: sweeps={res['n_sweeps']:3d} | "
            f"FVG#1={sum(1 for t in res['telemetry'] if t.fvg_slot == 1)} | "
            f"FVG#2={sum(1 for t in res['telemetry'] if t.fvg_slot == 2)} | "
            f"trades={len(res['trades'])} | range={res['date_range']}"
        )

    print(f"\nTotal sweeps: {sum(r['n_sweeps'] for r in per_symbol.values())}")
    print(
        f"Total FVG telemetry records: {len(all_telemetry)} "
        f"(#1={sum(1 for t in all_telemetry if t.fvg_slot == 1)}, "
        f"#2={sum(1 for t in all_telemetry if t.fvg_slot == 2)})"
    )
    print(f"Total historical trades: {len(all_trades)}")
    print(f"elapsed {time.time() - t0:.1f}s")

    metrics = _compute_research_eq_metrics(all_telemetry)

    from experiment.config import SL_ATR_MULT, TP_RR  # report-only

    L: List[str] = []
    L.append("# EXP 5B — Research EQ + FVG #1/#2 Forensic Backtest")
    L.append("")
    L.append("## CONFIG & COMMANDS")
    L.append("")
    L.append("- Test command: `python -m pytest tests/ -v`")
    L.append("- Backtest command: `python run_exp5b.py`")
    L.append("- Workers: **6** (multiprocessing.Pool, one symbol per worker)")
    L.append(f"- Window: last **{WINDOW_DAYS} days** of the dataset (real ranges below)")
    L.append("- Data: canonical IC Markets 1m Feather → `resample_15m` (<3-bar buckets dropped)")
    L.append(
        f"- Timeframe: 15m detection | TP_RR={TP_RR} | SL_ATR_MULT={SL_ATR_MULT} | "
        f"FVG_MIN={FVG_MIN_SIZE_ATR_MULT}*ATR | WICK<={FVG_WICK_RATIO_MAX} | ATR_PERIOD={ATR_PERIOD}"
    )
    L.append(
        f"- Session: CBDR {SESSION_START_HOUR}:00→{SESSION_END_HOUR}:00 (server time), sweep tol=0.5*ATR"
    )
    L.append(
        "- Swing: canonical NEXUS `find_swing_highs/lows(left=3, right=3)`, confirmed pivots only"
    )
    L.append(
        "- Research EQ = (latest confirmed swing high + latest confirmed swing low) / 2 — telemetry ONLY"
    )
    L.append(
        "- Production EQ `(sweep_price + range_opposite)/2` and KNOWN-GOOD `run_test_a`: UNCHANGED"
    )
    L.append(
        "- CORRECT_SIDE convention (= exp5 / production EQ gate): bullish→FVG entirely BELOW EQ, "
        "bearish→entirely ABOVE EQ; whole-zone test"
    )
    L.append("- OB / Breaker: N/A (no canonical detector — none invented)")
    L.append("")
    L.append("## POPULATION")
    L.append("")
    L.append(f"- Total CBDR sweeps: **{sum(r['n_sweeps'] for r in per_symbol.values())}**")
    L.append(f"- FVG #1 count: **{sum(1 for t in all_telemetry if t.fvg_slot == 1)}**")
    L.append(f"- FVG #2 count: **{sum(1 for t in all_telemetry if t.fvg_slot == 2)}**")
    L.append(f"- Historical trades: **{len(all_trades)}**")
    L.append("")
    L.append("### Per-symbol real date ranges (15m bars)")
    L.append("")
    L.append("| Symbol | Sweeps | From | To |")
    L.append("|---|---|---|---|")
    for sym in SYMBOLS:
        r = per_symbol.get(sym)
        if r is None:
            L.append(f"| {sym} | ERROR | — | — |")
        else:
            dr = r["date_range"]
            L.append(f"| {sym} | {r['n_sweeps']} | {dr[0]} | {dr[1]} |")
    L.append("")

    L.append("## RESEARCH EQ — FVG #1 vs #2")
    L.append("")
    L.append("| Metric | FVG #1 | FVG #2 |")
    L.append("|---|---|---|")
    L.append(
        f"| Correct at formation | {metrics['correct_at_formation'][1]} | {metrics['correct_at_formation'][2]} |"
    )
    L.append(f"| Crosses EQ | {metrics['crosses_eq'][1]} | {metrics['crosses_eq'][2]} |")
    L.append(
        f"| Wrong at formation | {metrics['wrong_at_formation'][1]} | {metrics['wrong_at_formation'][2]} |"
    )
    L.append(f"| NO_SWING_YET | {metrics['no_swing_yet'][1]} | {metrics['no_swing_yet'][2]} |")
    L.append(
        f"| Later becomes correct | {metrics['later_becomes_correct'][1]} | {metrics['later_becomes_correct'][2]} |"
    )
    L.append(
        f"| Never becomes correct | {metrics['never_correct'][1]} | {metrics['never_correct'][2]} |"
    )
    L.append(
        f"| Correct after 1 swing | {metrics['correct_after_1_swing'][1]} | {metrics['correct_after_1_swing'][2]} |"
    )
    L.append(
        f"| Correct after 2 swings | {metrics['correct_after_2_swings'][1]} | {metrics['correct_after_2_swings'][2]} |"
    )
    L.append(
        f"| Correct after 3+ swings | {metrics['correct_after_3plus_swings'][1]} | {metrics['correct_after_3plus_swings'][2]} |"
    )
    L.append(
        f"| Fresh when first correct (later cohort) | {metrics['fresh_when_first_correct'][1]} | {metrics['fresh_when_first_correct'][2]} |"
    )
    L.append(
        f"| Fresh when first correct (all first-correct) | {metrics['fresh_when_first_correct_all'][1]} | {metrics['fresh_when_first_correct_all'][2]} |"
    )
    L.append("")

    L.append("### Percentages")
    L.append("")
    for slot, label in [(1, "FVG #1"), (2, "FVG #2")]:
        total = metrics["total"][slot]
        if total > 0:
            correct = metrics["correct_at_formation"][slot]
            wrong = metrics["wrong_at_formation"][slot]
            later = metrics["later_becomes_correct"][slot]
            never = metrics["never_correct"][slot]
            fresh = metrics["fresh_when_first_correct"][slot]
            fresh_all = metrics["fresh_when_first_correct_all"][slot]
            n_first_correct = correct + later
            L.append(f"**{label}** (total={total})")
            L.append(f"- Formation CORRECT_SIDE: {correct / total * 100:.1f}%")
            L.append(f"- Formation WRONG_SIDE: {wrong / total * 100:.1f}%")
            L.append(
                f"- Later becomes correct: {later / total * 100:.1f}% (of non-correct-at-formation)"
            )
            L.append(f"- Never becomes correct: {never / total * 100:.1f}%")
            if later > 0:
                L.append(
                    f"- Fresh when first correct (later cohort): {fresh / later * 100:.1f}% (of {later})"
                )
            L.append(
                f"- Fresh when first correct (all {n_first_correct} first-correct events): "
                f"{fresh_all / n_first_correct * 100:.1f}%"
                if n_first_correct > 0
                else "- No first-correct events"
            )
            L.append("")

    L.append("## OUTCOME ATTRIBUTION")
    L.append("")
    L.append("| FVG | N | WR% | Avg R | Expectancy | Total R | MaxDD | TP | PT | LOSS | OPEN |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for slot, label in [(1, "FVG #1"), (2, "FVG #2"), (0, "Later/Unknown")]:
        st = _outcome_stats([t for t in all_trades if t["slot"] == slot], label)
        L.append(
            f"| {label} | {st['N']} | {st['WR%']:.1f} | {st['avg_R']:.3f} | {st['avg_R']:.3f} | {st['total_R']:.2f} | {st['MaxDD']:.2f} | {st['TP']} | {st['PROFIT_TRAIL']} | {st['LOSS']} | {st['OPEN']} |"
        )
    L.append("")

    L.append("## INTERPRETATION")
    L.append("")
    L.append("Yalnızca gözlenen veriyi yorumlar (observation-only).")
    L.append("")

    total = {1: metrics["total"][1], 2: metrics["total"][2]}
    total_correct = {
        1: metrics["correct_at_formation"][1] + metrics["later_becomes_correct"][1],
        2: metrics["correct_at_formation"][2] + metrics["later_becomes_correct"][2],
    }
    later = {
        1: metrics["later_becomes_correct"][1],
        2: metrics["later_becomes_correct"][2],
    }
    fresh_later = {
        1: metrics["fresh_when_first_correct"][1],
        2: metrics["fresh_when_first_correct"][2],
    }

    for s, label in [(1, "FVG #1"), (2, "FVG #2")]:
        if total[s] > 0:
            L.append(
                f"{label}: Toplam {total[s]} FVG, {total_correct[s]} tanesi en bir noktada "
                f"correct EQ tarafında ({total_correct[s] / total[s] * 100:.1f}%); "
                f"formation'da correct: {metrics['correct_at_formation'][s]}, "
                f"sonradan correct: {later[s]}."
            )
    L.append("")
    L.append("Ana sorulara cevap:")
    L.append("")
    L.append(
        '1. "İlk FVG yanlış EQ\'da oluştuğunda, market structure geliştikçe aynı FVG gerçekten doğru EQ tarafına oturuyor mu; oturuyorsa ne kadar sürede ve fresh kalma oranı nedir?"'
    )
    L.append("")
    for s, label in [(1, "FVG #1"), (2, "FVG #2")]:
        later_rows = [
            t
            for t in all_telemetry
            if t.fvg_slot == s
            and t.eq_position != "CORRECT_SIDE"
            and t.first_correct_side_bar_index is not None
        ]
        if later_rows:
            avg_sw = sum(t.first_correct_side_swings for t in later_rows) / len(later_rows)
            mins = sorted(
                t.formation_to_first_correct_min
                for t in later_rows
                if t.formation_to_first_correct_min is not None
            )
            med_min = mins[len(mins) // 2] if mins else float("nan")
            fr = fresh_later[s] / len(later_rows) * 100
            L.append(
                f"- **{label}**: {len(later_rows)} FVG sonradan correct oldu; "
                f"ort. {avg_sw:.1f} swing update / medyan {med_min:.0f} dk (15m bar × 15); "
                f"first-correct anında hâlâ fresh: {fr:.1f}%."
            )
        else:
            L.append(f"- **{label}**: Formation dışında hiçbir FVG correct tarafa oturmadı.")
    L.append("")
    L.append('2. "Bu davranış FVG #1 ile FVG #2 arasında sistematik olarak farklı mı?"')
    L.append("")
    if total[1] > 0 and total[2] > 0:
        diff_ever = abs((total_correct[1] / total[1]) - (total_correct[2] / total[2]))
        diff_form = abs(
            (metrics["correct_at_formation"][1] / total[1])
            - (metrics["correct_at_formation"][2] / total[2])
        )
        diff_later_rate = 0.0
        denom = {
            1: total[1] - metrics["correct_at_formation"][1],
            2: total[2] - metrics["correct_at_formation"][2],
        }
        if denom[1] > 0 and denom[2] > 0:
            diff_later_rate = abs((later[1] / denom[1]) - (later[2] / denom[2]))
        L.append(f"- Hiçbir noktada correct oran farkı (#1 vs #2): {diff_ever * 100:.1f} puan.")
        L.append(f"- Formation-correct oran farkı: {diff_form * 100:.1f} puan.")
        L.append(
            f"- Sonradan-correct oran farkı (non-correct kohort): {diff_later_rate * 100:.1f} puan."
        )
        L.append("- Not: Bu experiment istatistiksel test üretmez; farklar gözlemseldir.")
    L.append("")
    L.append("Decision threshold: Bu iki cevap netleşmeden yeni entry kuralı geliştirilmez.")

    report = "\n".join(L)
    out_dir = _PROJECT_ROOT / "results" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "exp5b_post_sweep_fvg_1v2_eq_report.md"
    report_path.write_text(report, encoding="utf-8")

    telemetry_path = out_dir / "exp5b_post_sweep_fvg_1v2_eq_telemetry.json"
    telemetry_path.write_text(
        json.dumps([asdict(t) for t in all_telemetry], indent=2, default=str),
        encoding="utf-8",
    )

    print(f"\nReport : {report_path}")
    print(f"JSON   : {telemetry_path}")


if __name__ == "__main__":
    mp.freeze_support()
    main()
