"""
EXP 5C - OB & Breaker Block Forensic Pass (TELEMETRY ONLY)
===========================================================

Amaç: EXP 5B'nin FVG #1/#2 popülasyonu üzerinde, Order Block ve Breaker
Block context'ini ayrı bir forensic pass ile tespit etmek.

DISIPLIN:
- Bu modul EXP 5B'yi ve Research EQ sonuclarini DEGISTIRMEZ; production entry
  ve canonical benchmark'a dokunmaz. Outcome attribution / entry kurali YOK.
- OB/Breaker tanimlari results/research/exp5c_ob_breaker_definitions.md
  icinde ACIK KURALLAR olarak bildirilmistir; asagidaki fonksiyonlar o
  kurallarin birebir uygulamasidir (OB-R1..R3, BB-R1..R5).

Kurallar (özet — tam metin için definitions dosyasına bak):
- FVG_FIRST = fvg.real_index - 1   (NEXUS real_index = orta mum)
- Bullish OB: son ayi mumu c (close<open), c < FVG_FIRST, c >= FVG_FIRST-W_OB,
  displacement onaji: bazı d, c < d <= FVG_FIRST: close[d] > high[c].
- Bearish OB: ayna.
- Bullish Breaker: ayi mumu z; FAILURE close[f] < low[z] (z<f<FVG_FIRST);
  FLIP close[g] > high[z] (f<g<FVG_FIRST); en son flip kazanir.
- Bearish Breaker: ayna.
- Aday yok -> None (JSON null).

FVG #1/#2 toplama dongusu, exp5b_post_sweep_fvg_1v2_eq._analyze_symbol
icindeki dongunun birebir kopyasidir (exp5b immutable kaldigi icin
kopyalama zorunlu; kanonik bilesenler ayni importlardan gelir).
"""

from __future__ import annotations

import json
import multiprocessing as mp
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

_NEXUS_SNIPER_SRC = str(Path("C:/Users/Administrator/Desktop/nexus-mcp/sniper/src"))
if _NEXUS_SNIPER_SRC not in sys.path:
    sys.path.insert(0, _NEXUS_SNIPER_SRC)

# ── Canonical imports (same sources as exp5b) ──
from fvg import detect_fvgs as _nexus_detect_fvgs
from models import Bar as NexusBar

from experiment.config import (
    ATR_PERIOD,
    FVG_MIN_SIZE_ATR_MULT,
    FVG_WICK_RATIO_MAX,
    SESSION_END_HOUR,
    SESSION_START_HOUR,
)
from experiment.gemini_benchmark import _is_fresh_fvg, _to_nexus_bar, compute_atr
from experiment.main_research_c_v1_0 import resample_15m
from src.strategy.data_loader import DataLoader
from src.strategy.models import Bar, Direction
from src.strategy.session import SessionManager

ICMARKET_FEATHER = _PROJECT_ROOT / "data" / "icmarket_feather"
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "GBPJPY"]
WINDOW_DAYS = 180  # same 6-month window as EXP 5B

W_OB = 10  # OB-R1 search window (bars before FVG_FIRST)
W_BB = 50  # BB-R1 search window


@dataclass
class ObBreakerTelemetry:
    """OB / Breaker context for one post-sweep FVG (slot 1 or 2)."""

    symbol: str
    sweep_index: int
    sweep_timestamp: str
    fvg_slot: int
    direction: str
    fvg_bar_index: int  # NEXUS real_index (middle candle)
    fvg_first_index: int  # fvg.real_index - 1
    fvg_timestamp: str
    fvg_top: float
    fvg_bottom: float
    bars_from_sweep: int
    # Order Block
    ob_found: bool
    ob_index: Optional[int]
    ob_timestamp: Optional[str]
    ob_top: Optional[float]  # full-candle high
    ob_bottom: Optional[float]  # full-candle low
    ob_body_top: Optional[float]
    ob_body_bottom: Optional[float]
    ob_bars_from_fvg: Optional[int]
    ob_overlaps_fvg: Optional[bool]
    ob_mitigated_before_fvg: Optional[bool]
    # Breaker Block
    breaker_found: bool
    breaker_index: Optional[int]
    breaker_timestamp: Optional[str]
    breaker_top: Optional[float]
    breaker_bottom: Optional[float]
    breaker_bars_from_fvg: Optional[int]
    breaker_overlaps_fvg: Optional[bool]
    breaker_failure_index: Optional[int]
    breaker_flip_index: Optional[int]
    breaker_flip_to_fvg_bars: Optional[int]


# ─────────────────────────────────────────────────────────────────────────────
# Rule implementations (definitions file: OB-R1..R3, BB-R1..R5)
# ─────────────────────────────────────────────────────────────────────────────
def find_order_block(
    bars_15m: List[Bar],
    direction: str,
    fvg_first: int,
    window: int = W_OB,
) -> Optional[Dict[str, Any]]:
    """OB-R1..R3. Returns dict or None."""
    if direction not in ("bullish", "bearish"):
        raise ValueError(direction)

    scan_hi = fvg_first - 1  # latest candidate candle index
    scan_lo = max(0, fvg_first - window)

    for c in range(scan_hi, scan_lo - 1, -1):  # nearest first (OB-R3)
        cb = bars_15m[c]

        if direction == "bullish":
            if not (cb.close < cb.open):  # OB-R1: bearish candle
                continue
            # OB-R2: close-based displacement through the candle high
            confirmed = any(bars_15m[d].close > cb.high for d in range(c + 1, fvg_first + 1))
            if not confirmed:
                continue
            mitigated = any(bars_15m[e].low <= cb.high for e in range(c + 1, fvg_first))
        else:
            if not (cb.close > cb.open):  # OB-R1 mirror: bullish candle
                continue
            confirmed = any(bars_15m[d].close < cb.low for d in range(c + 1, fvg_first + 1))
            if not confirmed:
                continue
            mitigated = any(bars_15m[e].high >= cb.low for e in range(c + 1, fvg_first))

        return {
            "index": c,
            "timestamp": str(cb.timestamp),
            "top": cb.high,
            "bottom": cb.low,
            "body_top": max(cb.open, cb.close),
            "body_bottom": min(cb.open, cb.close),
            "bars_from_fvg": fvg_first - c,
            "mitigated_before_fvg": bool(mitigated),
        }
    return None


def find_breaker_block(
    bars_15m: List[Bar],
    direction: str,
    fvg_first: int,
    window: int = W_BB,
) -> Optional[Dict[str, Any]]:
    """BB-R1..R5. Returns dict or None."""
    if direction not in ("bullish", "bearish"):
        raise ValueError(direction)

    scan_lo = max(0, fvg_first - window)
    best: Optional[Dict[str, Any]] = None

    for z in range(fvg_first - 1, scan_lo - 1, -1):
        zb = bars_15m[z]

        if direction == "bullish":
            if not (zb.close < zb.open):  # BB-R1: bearish candle
                continue
            failure_idx = next(
                (f for f in range(z + 1, fvg_first) if bars_15m[f].close < zb.low), None
            )  # BB-R2
            if failure_idx is None:
                continue
            flip_idx = next(
                (g for g in range(failure_idx + 1, fvg_first) if bars_15m[g].close > zb.high),
                None,
            )  # BB-R3
        else:
            if not (zb.close > zb.open):  # BB-R1 mirror
                continue
            failure_idx = next(
                (f for f in range(z + 1, fvg_first) if bars_15m[f].close > zb.high),
                None,
            )
            if failure_idx is None:
                continue
            flip_idx = next(
                (g for g in range(failure_idx + 1, fvg_first) if bars_15m[g].close < zb.low),
                None,
            )

        if flip_idx is None:
            continue

        cand = {
            "index": z,
            "timestamp": str(zb.timestamp),
            "top": zb.high,
            "bottom": zb.low,
            "failure_index": failure_idx,
            "flip_index": flip_idx,
            "flip_to_fvg_bars": fvg_first - flip_idx,
        }
        # BB-R5: latest completed flip wins; tie-break nearest z
        if best is None or (cand["flip_index"], cand["index"]) > (
            best["flip_index"],
            best["index"],
        ):
            best = cand
    return best


def _zones_overlap(top_a: float, bottom_a: float, top_b: float, bottom_b: float) -> bool:
    """Strict intersection; touching does not count."""
    return bool((bottom_a < top_b) and (bottom_b < top_a))


# ─────────────────────────────────────────────────────────────────────────────
# Per-symbol analysis — collection loop identical to exp5b (provenance comment)
# ─────────────────────────────────────────────────────────────────────────────
def _analyze_symbol(symbol: str) -> Dict[str, Any]:
    loader = DataLoader(feather_dir=ICMARKET_FEATHER)
    bars_1m = loader.load(symbol)

    if bars_1m:
        max_ts = bars_1m[-1].timestamp
        cutoff = max_ts - pd.Timedelta(days=WINDOW_DAYS)
        bars_1m = [b for b in bars_1m if b.timestamp >= cutoff]

    bars_15m = resample_15m(bars_1m)

    if len(bars_15m) < 100:
        return {"symbol": symbol, "telemetry": [], "n_sweeps": 0, "date_range": []}

    warmup = min(100, len(bars_15m) - 10)
    atr_val = compute_atr(bars_15m[:warmup], period=ATR_PERIOD)
    if atr_val <= 0:
        return {"symbol": symbol, "telemetry": [], "n_sweeps": 0, "date_range": []}

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

    # ── BEGIN: verbatim collection loop from exp5b (immutable reference) ──
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
    # ── END: verbatim collection loop from exp5b ──

    telemetry: List[ObBreakerTelemetry] = []
    for ctx in sweep_contexts:
        sweep = ctx["sweep"]
        direction = ctx["direction"]
        sweep_ts = str(bars_15m[sweep.bar_index].timestamp)

        for slot, fvg in enumerate(ctx["fvgs"], start=1):
            fvg_first = fvg.real_index - 1

            ob = find_order_block(bars_15m, direction, fvg_first, W_OB)
            bb = find_breaker_block(bars_15m, direction, fvg_first, W_BB)

            telemetry.append(
                ObBreakerTelemetry(
                    symbol=symbol,
                    sweep_index=ctx["sweep_index"],
                    sweep_timestamp=sweep_ts,
                    fvg_slot=slot,
                    direction=direction,
                    fvg_bar_index=fvg.real_index,
                    fvg_first_index=fvg_first,
                    fvg_timestamp=str(bars_15m[fvg.real_index].timestamp),
                    fvg_top=fvg.top,
                    fvg_bottom=fvg.bottom,
                    bars_from_sweep=fvg.real_index - sweep.bar_index,
                    ob_found=ob is not None,
                    ob_index=(ob["index"] if ob else None),
                    ob_timestamp=(ob["timestamp"] if ob else None),
                    ob_top=(ob["top"] if ob else None),
                    ob_bottom=(ob["bottom"] if ob else None),
                    ob_body_top=(ob["body_top"] if ob else None),
                    ob_body_bottom=(ob["body_bottom"] if ob else None),
                    ob_bars_from_fvg=(ob["bars_from_fvg"] if ob else None),
                    ob_overlaps_fvg=(
                        _zones_overlap(ob["top"], ob["bottom"], fvg.top, fvg.bottom) if ob else None
                    ),
                    ob_mitigated_before_fvg=(ob["mitigated_before_fvg"] if ob else None),
                    breaker_found=bb is not None,
                    breaker_index=(bb["index"] if bb else None),
                    breaker_timestamp=(bb["timestamp"] if bb else None),
                    breaker_top=(bb["top"] if bb else None),
                    breaker_bottom=(bb["bottom"] if bb else None),
                    breaker_bars_from_fvg=(fvg_first - bb["index"] if bb else None),
                    breaker_overlaps_fvg=(
                        _zones_overlap(bb["top"], bb["bottom"], fvg.top, fvg.bottom) if bb else None
                    ),
                    breaker_failure_index=(bb["failure_index"] if bb else None),
                    breaker_flip_index=(bb["flip_index"] if bb else None),
                    breaker_flip_to_fvg_bars=(bb["flip_to_fvg_bars"] if bb else None),
                )
            )

    return {
        "symbol": symbol,
        "telemetry": telemetry,
        "n_sweeps": len(sweep_contexts),
        "date_range": [str(bars_15m[0].timestamp), str(bars_15m[-1].timestamp)],
    }


def _worker(symbol: str) -> Dict[str, Any]:
    try:
        return _analyze_symbol(symbol)
    except Exception as e:  # surface worker errors without killing the pool
        return {
            "symbol": symbol,
            "telemetry": [],
            "n_sweeps": 0,
            "date_range": [],
            "error": str(e),
        }


def main():
    t0 = time.time()
    print("=== EXP 5C - OB & Breaker Forensic Pass (telemetry only) ===")
    print(f"Symbols: {SYMBOLS} | 6 workers | window={WINDOW_DAYS}d | W_OB={W_OB} W_BB={W_BB}")
    print()

    with mp.Pool(processes=6) as pool:
        results = pool.map(_worker, SYMBOLS)

    all_tel: List[ObBreakerTelemetry] = []
    per_symbol: Dict[str, Dict[str, Any]] = {}
    for sym, res in zip(SYMBOLS, results):
        if res.get("error"):
            print(f"  {sym:10s}: ERROR -> {res['error']}")
            continue
        per_symbol[sym] = res
        all_tel.extend(res["telemetry"])
        n_ob = sum(1 for t in res["telemetry"] if t.ob_found)
        n_bb = sum(1 for t in res["telemetry"] if t.breaker_found)
        print(
            f"  {sym:10s}: sweeps={res['n_sweeps']:3d} | FVG tel={len(res['telemetry']):3d} | "
            f"OB found={n_ob} | Breaker found={n_bb} | range={res['date_range']}"
        )

    total = len(all_tel)
    s1 = [t for t in all_tel if t.fvg_slot == 1]
    s2 = [t for t in all_tel if t.fvg_slot == 2]

    def pct(n: int, d: int) -> str:
        return f"{n / d * 100:.1f}%" if d else "—"

    L: List[str] = []
    L.append("# EXP 5C — OB & Breaker Block Forensic Telemetry")
    L.append("")
    L.append(
        "Definitions: `results/research/exp5c_ob_breaker_definitions.md` "
        "(rules OB-R1..R3, BB-R1..R5 — code is their literal implementation)."
    )
    L.append("")
    L.append("## POPULATION")
    L.append("")
    L.append(
        f"- Sweeps: **{sum(r['n_sweeps'] for r in per_symbol.values())}** | "
        f"FVG telemetry: **{total}** (#1={len(s1)}, #2={len(s2)})"
    )
    L.append(f"- Window: last {WINDOW_DAYS} days of the same dataset as EXP 5B")
    L.append("")
    for slot, label in [(1, "FVG #1"), (2, "FVG #2")]:
        rows = [t for t in all_tel if t.fvg_slot == slot]
        n = len(rows)
        ob_hits = sum(1 for t in rows if t.ob_found)
        bb_hits = sum(1 for t in rows if t.breaker_found)
        ob_ov = sum(1 for t in rows if t.ob_overlaps_fvg)
        bb_ov = sum(1 for t in rows if t.breaker_overlaps_fvg)
        ob_mit = sum(1 for t in rows if t.ob_mitigated_before_fvg)
        dists = sorted(t.ob_bars_from_fvg for t in rows if t.ob_found)
        bb_dists = sorted(t.breaker_flip_to_fvg_bars for t in rows if t.breaker_found)
        med_ob = dists[len(dists) // 2] if dists else float("nan")
        med_bb = bb_dists[len(bb_dists) // 2] if bb_dists else float("nan")
        L.append(f"## {label} (n={n})")
        L.append("")
        L.append(
            f"- OB found: **{ob_hits} ({pct(ob_hits, n)})** | median distance "
            f"{med_ob:.0f} bar | overlaps FVG: {ob_ov} ({pct(ob_ov, ob_hits)} of found) | "
            f"mitigated before FVG: {ob_mit} ({pct(ob_mit, ob_hits)} of found)"
        )
        L.append(
            f"- Breaker found: **{bb_hits} ({pct(bb_hits, n)})** | median flip→FVG "
            f"{med_bb:.0f} bar | overlaps FVG: {bb_ov} ({pct(bb_ov, bb_hits)} of found)"
        )
        L.append("")
    L.append("Observation-only. No outcome attribution, no entry rule.")

    out_dir = _PROJECT_ROOT / "results" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "exp5c_ob_breaker_report.md"
    report_path.write_text("\n".join(L), encoding="utf-8")

    tel_path = out_dir / "exp5c_ob_breaker_telemetry.json"
    tel_path.write_text(
        json.dumps([asdict(t) for t in all_tel], indent=2, default=str),
        encoding="utf-8",
    )

    print(f"\nTotal FVG telemetry: {total} | elapsed {time.time() - t0:.1f}s")
    print(f"Report : {report_path}")
    print(f"JSON   : {tel_path}")


if __name__ == "__main__":
    mp.freeze_support()
    main()
