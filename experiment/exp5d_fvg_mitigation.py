"""
EXP 5D — FVG Mitigation State Research
========================================

Amaç: FVG'ye ilk temas/penetration derecesine göre mitigation state
sınıflandırması yapıp outcome attribution ile birleştirmek.

Mitigation States:
  S0 — UNTOUCHED:      FVG zone'una hiç temas yok
  S1 — WICK_TOUCH:     Wick teması, body FVG'ye girmemiş
  S2 — PARTIAL:        Body FVG'ye girmiş ama zone tüketilmemiş + far-side close yok
  S3 — DEEP:           Zone'un büyük kısmı tüketilmiş + far-side close yok
  S4 — INVALIDATED:    Far-side close gerçekleşmiş (en robust "dead" sinyal)

S4 = far-side close (wick touch ≠ invalidation → S1/S2/S3 ayrımı için fırsat).

DISIPLIN:
- Production freshness DEGISTIRILMEZ.
- Yeni backtest window OLUSTURULMAZ.
- KNOWN-GOOD run_test_a unchanged.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

_NEXUS_SNIPER_SRC = str(Path("C:/Users/Administrator/Desktop/nexus-mcp/sniper/src"))
if _NEXUS_SNIPER_SRC not in sys.path:
    sys.path.insert(0, _NEXUS_SNIPER_SRC)

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
from experiment.main_research_c_v1_0 import resample_15m, run_test_a
from src.strategy.data_loader import DataLoader
from src.strategy.models import Bar, Direction
from src.strategy.session import SessionManager

ICMARKET_FEATHER = _PROJECT_ROOT / "data" / "icmarket_feather"
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "GBPJPY"]
WINDOW_DAYS = 180

# Mitigation state constants
S0 = "S0_UNTOUCHED"
S1 = "S1_WICK_TOUCH"
S2 = "S2_PARTIAL"
S3 = "S3_DEEP"
S4 = "S4_INVALIDATED"


def _classify_mitigation_state(
    bars_15m: List[Bar],
    fvg_top: float,
    fvg_bottom: float,
    direction: str,
    fvg_real_index: int,
) -> Dict[str, Any]:
    """Scan bars after FVG formation → classify mitigation state + measure penetration.

    S4 = far-side close (not just wick touch).
    Wick-only touch = S1; body entry = S2/S3 depending on depth.
    """
    fvg_size = fvg_top - fvg_bottom
    if fvg_size <= 0:
        return {
            "state": S0,
            "max_pen_pct": 0.0,
            "first_touch_index": None,
            "invalidation_index": None,
        }

    scan_start = fvg_real_index + 2
    first_touch_index: Optional[int] = None
    invalidation_index: Optional[int] = None
    max_penetration = 0.0
    state = S0

    for b in bars_15m:
        if b.index < scan_start:
            continue

        # Check any interaction with zone
        if direction == "bullish":
            touches_zone = b.low <= fvg_top
            wick_below_bottom = b.low < fvg_bottom
        else:
            touches_zone = b.high >= fvg_bottom
            wick_above_top = b.high > fvg_top

        if not touches_zone:
            continue

        # First touch
        if first_touch_index is None:
            first_touch_index = b.index

        # Penetration depth (how deep into the zone)
        if direction == "bullish":
            pen = max(0.0, fvg_top - max(b.low, fvg_bottom))
        else:
            pen = max(0.0, min(b.high, fvg_top) - fvg_bottom)

        pen_pct = (pen / fvg_size * 100.0) if fvg_size > 0 else 0.0
        max_penetration = max(max_penetration, pen_pct)

        # Body entry check
        body_top = max(b.open, b.close)
        body_bottom = min(b.open, b.close)
        if direction == "bullish":
            body_enters = body_bottom < fvg_top
        else:
            body_enters = body_top > fvg_bottom

        # Far-side close check (S4 invalidation)
        if direction == "bullish":
            far_side_close = b.close > fvg_top
        else:
            far_side_close = b.close < fvg_bottom

        if far_side_close and invalidation_index is None:
            invalidation_index = b.index

        # Classify: first meaningful interaction determines state
        if state == S0:
            if far_side_close:
                state = S4
            elif body_enters:
                state = S2  # might upgrade to S3 later
            else:
                state = S1  # wick-only touch

        # Upgrade S2 → S3 if penetration > 70%
        if state == S2 and pen_pct > 70.0:
            state = S3

    # If S4 never happened but was set, keep it
    # If first touch was far-side close, state is already S4

    return {
        "state": state,
        "max_pen_pct": round(max_penetration, 2),
        "first_touch_index": first_touch_index,
        "invalidation_index": invalidation_index,
    }


def _analyze_symbol(symbol: str) -> Dict[str, Any]:
    """Per-symbol: collection loop + mitigation scan + run_test_a."""
    loader = DataLoader(feather_dir=ICMARKET_FEATHER)
    bars_1m = loader.load(symbol)

    if bars_1m:
        max_ts = bars_1m[-1].timestamp
        cutoff = max_ts - pd.Timedelta(days=WINDOW_DAYS)
        bars_1m = [b for b in bars_1m if b.timestamp >= cutoff]

    bars_15m = resample_15m(bars_1m)
    if len(bars_15m) < 100:
        return {"symbol": symbol, "mitigation": [], "trades": [], "n_sweeps": 0}

    warmup = min(100, len(bars_15m) - 10)
    atr_val = compute_atr(bars_15m[:warmup], period=ATR_PERIOD)
    if atr_val <= 0:
        return {"symbol": symbol, "mitigation": [], "trades": [], "n_sweeps": 0}

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

    # ── BEGIN: verbatim collection loop ──
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
    # ── END: verbatim collection loop ──

    # Sweep → FVG map (for trade matching)
    sweep_fvg_map: Dict[int, Tuple[Optional[int], Optional[int]]] = {}
    for ctx in sweep_contexts:
        fvgs = ctx["fvgs"]
        f1 = fvgs[0].real_index if len(fvgs) >= 1 else None
        f2 = fvgs[1].real_index if len(fvgs) >= 2 else None
        sweep_fvg_map[ctx["sweep"].bar_index] = (f1, f2)

    # Mitigation scan for each FVG
    mitigation: List[Dict[str, Any]] = []
    for ctx in sweep_contexts:
        sweep = ctx["sweep"]
        sweep_idx = ctx["sweep_index"]
        direction = ctx["direction"]
        sweep_ts = str(bars_15m[sweep.bar_index].timestamp)

        for slot, fvg in enumerate(ctx["fvgs"], start=1):
            result = _classify_mitigation_state(
                bars_15m,
                fvg.top,
                fvg.bottom,
                direction,
                fvg.real_index,
            )
            canonical_fresh = _is_fresh_fvg(fvg, bars_15m, len(bars_15m))

            mitigation.append(
                {
                    "symbol": symbol,
                    "sweep_index": sweep_idx,
                    "sweep_timestamp": sweep_ts,
                    "fvg_slot": slot,
                    "direction": direction,
                    "fvg_bar_index": fvg.real_index,
                    "fvg_timestamp": str(bars_15m[fvg.real_index].timestamp),
                    "fvg_top": fvg.top,
                    "fvg_bottom": fvg.bottom,
                    "fvg_size": fvg.size,
                    "mitigation_state": result["state"],
                    "max_penetration_pct": result["max_pen_pct"],
                    "first_touch_index": result["first_touch_index"],
                    "invalidation_index": result["invalidation_index"],
                    "canonical_fresh": canonical_fresh,
                }
            )

    # Run KNOWN-GOOD pipeline for trade outcomes
    trades = run_test_a(symbol, bars_15m)
    trade_list = []
    for t in trades:
        f1, f2 = sweep_fvg_map.get(t.sweep_bar_index, (None, None))
        if t.zone_index == f1:
            slot = 1
        elif t.zone_index == f2:
            slot = 2
        else:
            slot = 0
        trade_list.append(
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
        "mitigation": mitigation,
        "trades": trade_list,
        "n_sweeps": len(sweep_contexts),
    }


def _worker(symbol: str) -> Dict[str, Any]:
    try:
        return _analyze_symbol(symbol)
    except Exception as e:
        return {
            "symbol": symbol,
            "mitigation": [],
            "trades": [],
            "n_sweeps": 0,
            "error": str(e),
        }


def _outcome_stats(trades: List[Dict], label: str) -> Dict[str, Any]:
    completed = [t for t in trades if t["result"] in ("TP", "PROFIT_TRAIL", "LOSS")]
    wins = [t for t in completed if t["result"] in ("TP", "PROFIT_TRAIL")]
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
        "WR%": round(wr, 1),
        "AvgR": round(avg_r, 3),
        "Expectancy": round(avg_r, 3),
        "TotalR": round(total_r, 2),
        "MaxDD": round(maxdd, 2),
    }


def _fmt(st: Dict) -> str:
    return (
        f"| {st['label']} | {st['N']} | {st['completed']} | "
        f"{st['WR%']} | {st['AvgR']} | {st['Expectancy']} | "
        f"{st['TotalR']} | {st['MaxDD']} |"
    )


def main():
    t0 = time.time()
    print("=== EXP 5D — FVG Mitigation State Research ===")
    print(f"Symbols: {SYMBOLS} | 6 workers | window={WINDOW_DAYS}d")
    print()

    with mp.Pool(processes=6) as pool:
        results = pool.map(_worker, SYMBOLS)

    all_mit: List[Dict] = []
    all_trades: List[Dict] = []
    for sym, res in zip(SYMBOLS, results):
        if res.get("error"):
            print(f"  {sym:10s}: ERROR -> {res['error']}")
            continue
        all_mit.extend(res["mitigation"])
        all_trades.extend(res["trades"])
        n_mit = len(res["mitigation"])
        n_tr = len(res["trades"])
        print(f"  {sym:10s}: FVGs={n_mit:3d} | trades={n_tr:3d} | sweeps={res['n_sweeps']:3d}")

    elapsed = time.time() - t0
    print(f"\nTotal FVGs: {len(all_mit)} | Trades: {len(all_trades)} | elapsed {elapsed:.1f}s")
    print()

    # ── State distribution ──
    state_dist: Dict[str, int] = {}
    for m in all_mit:
        s = m["mitigation_state"]
        state_dist[s] = state_dist.get(s, 0) + 1
    print("Mitigation state distribution:")
    for s in [S0, S1, S2, S3, S4]:
        n = state_dist.get(s, 0)
        print(f"  {s}: {n} ({100 * n / len(all_mit):.1f}%)")

    # ── Penetration stats ──
    pens = sorted(m["max_penetration_pct"] for m in all_mit)
    pcts = [25, 50, 75, 90, 95]
    print("\nPenetration % distribution (all FVGs):")
    for p in pcts:
        idx = int(len(pens) * p / 100)
        idx = min(idx, len(pens) - 1)
        print(f"  P{p}: {pens[idx]:.1f}%")
    print(f"  Max: {pens[-1]:.1f}%")
    print()

    # ── Save outputs ──
    out_dir = _PROJECT_ROOT / "results" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)

    mit_path = out_dir / "exp5d_mitigation.json"
    mit_path.write_text(json.dumps(all_mit, indent=2, default=str), encoding="utf-8")

    # ── Merge mitigation ↔ trades ──
    mit_lookup: Dict[tuple, Dict] = {}
    for m in all_mit:
        key = (m["symbol"], m["fvg_bar_index"])
        mit_lookup[key] = m

    enriched = []
    for t in all_trades:
        key = (t["symbol"], t["zone_index"])
        m = mit_lookup.get(key)
        enriched.append(
            {
                **t,
                "mitigation_state": m["mitigation_state"] if m else None,
                "max_penetration_pct": m["max_penetration_pct"] if m else None,
                "canonical_fresh": m["canonical_fresh"] if m else None,
                "fvg_size": m["fvg_size"] if m else None,
                "invalidation_index": m["invalidation_index"] if m else None,
            }
        )

    enrich_path = out_dir / "exp5d_enriched_trades.json"
    enrich_path.write_text(json.dumps(enriched, indent=2, default=str), encoding="utf-8")

    # ── Load cohort data ──
    cohort_path = out_dir / "exp5c_research_eq_cohort.json"
    if cohort_path.exists():
        cohort_data = json.loads(cohort_path.read_text(encoding="utf-8"))
        cohort_lookup = {(c["symbol"], c["zone_index"]): c for c in cohort_data}
        for e in enriched:
            c = cohort_lookup.get((e["symbol"], e["zone_index"]))
            e["cohort"] = c["cohort"] if c else "UNKNOWN"
    else:
        for e in enriched:
            e["cohort"] = "UNKNOWN"

    # ── Report ──
    L: List[str] = []
    L.append("# EXP 5D — FVG Mitigation State Research")
    L.append("")
    L.append("## TANIM")
    L.append("")
    L.append(
        "Mitigation state = FVG oluşumundan sonraki ilk meaningful interaction'a göre sınıflandırma:"
    )
    L.append("- **S0 UNTOUCHED**: Hiç temas yok")
    L.append("- **S1 WICK_TOUCH**: Wick teması, body FVG'ye girmemiş")
    L.append("- **S2 PARTIAL**: Body FVG'ye girmiş ama zone tüketilmemiş + far-side close yok")
    L.append("- **S3 DEEP**: Zone'un büyük kısmı tüketilmiş (>70%) + far-side close yok")
    L.append('- **S4 INVALIDATED**: Far-side close gerçekleşmiş (en robust "dead" sinyal)')
    L.append("")
    L.append("**S4 = far-side close. Wick touch ≠ invalidation → S1/S2/S3 ayrımı için fırsat.**")
    L.append("")
    L.append("Entry rules: UNCHANGED (KNOWN-GOOD run_test_a). Observation-only.")
    L.append("")

    # ── Population ──
    L.append("## POPULATION")
    L.append("")
    L.append(f"- Total FVGs: **{len(all_mit)}** | Trades: **{len(all_trades)}**")
    L.append("")

    # ── Table 1: State distribution ──
    L.append("## 1. MITIGATION STATE DISTRIBUTION")
    L.append("")
    L.append("| State | N | % |")
    L.append("|---|---|---|")
    for s in [S0, S1, S2, S3, S4]:
        n = state_dist.get(s, 0)
        L.append(f"| {s} | {n} | {100 * n / len(all_mit):.1f}% |")
    L.append("")

    # ── Table 2: Penetration distribution ──
    L.append("## 2. PENETRATION % DISTRIBUTION")
    L.append("")
    L.append("| Percentile | Penetration % |")
    L.append("|---|---|")
    for p in pcts:
        idx = min(int(len(pens) * p / 100), len(pens) - 1)
        L.append(f"| P{p} | {pens[idx]:.1f}% |")
    L.append(f"| Max | {pens[-1]:.1f}% |")
    L.append("")

    # ── Table 3: Mitigation state × outcome ──
    L.append("## 3. MITIGATION STATE × OUTCOME (all trades)")
    L.append("")
    L.append("| State | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |")
    L.append("|---|---|---|---|---|---|---|---|")
    for s in [S0, S1, S2, S3, S4]:
        subset = [t for t in enriched if t["mitigation_state"] == s]
        if subset:
            st = _outcome_stats(subset, s)
            L.append(_fmt(st))
    # All
    st = _outcome_stats(enriched, "ALL")
    L.append(_fmt(st))
    L.append("")

    # ── Table 4: Canonical Freshness × Research State ──
    L.append("## 4. CANONICAL FRESHNESS × RESEARCH STATE")
    L.append("")
    L.append("| Freshness | State | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for fresh_val, fresh_label in [(True, "True"), (False, "False")]:
        for s in [S0, S1, S2, S3, S4]:
            subset = [
                t
                for t in enriched
                if t["canonical_fresh"] == fresh_val and t["mitigation_state"] == s
            ]
            if subset:
                st = _outcome_stats(subset, f"fresh={fresh_label} {s}")
                L.append(
                    f"| {fresh_label} | {s} | {st['N']} | {st['completed']} | "
                    f"{st['WR%']} | {st['AvgR']} | {st['Expectancy']} | "
                    f"{st['TotalR']} | {st['MaxDD']} |"
                )
    L.append("")

    # ── Table 5: Research EQ Cohort × Mitigation ──
    L.append("## 5. RESEARCH EQ COHORT × MITIGATION STATE")
    L.append("")

    # 5a. CORRECT_AT_FORMATION
    L.append("### CORRECT_AT_FORMATION")
    L.append("")
    L.append("| State | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |")
    L.append("|---|---|---|---|---|---|---|---|")
    for s in [S0, S1, S2, S3, S4]:
        subset = [
            t
            for t in enriched
            if "CORRECT_AT_FORMATION" in t.get("cohort", "") and t["mitigation_state"] == s
        ]
        if subset:
            st = _outcome_stats(subset, s)
            L.append(_fmt(st))
    L.append("")

    # 5b. WRONG_LATER_CORRECT
    L.append("### WRONG_LATER_CORRECT")
    L.append("")
    L.append("| State | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |")
    L.append("|---|---|---|---|---|---|---|---|")
    for s in [S0, S1, S2, S3, S4]:
        subset = [
            t
            for t in enriched
            if "WRONG_LATER_CORRECT" in t.get("cohort", "") and t["mitigation_state"] == s
        ]
        if subset:
            st = _outcome_stats(subset, s)
            L.append(_fmt(st))
    L.append("")

    # ── Table 6: Canonical fresh=False breakdown (THE KEY QUESTION) ──
    L.append("## 6. CRITICAL: canonical fresh=False × RESEARCH STATE")
    L.append("")
    L.append("**\"Canonical fresh=False olan ama research S1/S2 durumunda kalan FVG'ler")
    L.append('historical trades içinde hâlâ pozitif expectancy taşıyor mu?"**')
    L.append("")
    L.append("| State | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    fresh_false = [t for t in enriched if t["canonical_fresh"] is False]
    for s in [S0, S1, S2, S3, S4]:
        subset = [t for t in fresh_false if t["mitigation_state"] == s]
        if subset:
            st = _outcome_stats(subset, f"fresh=False + {s}")
            L.append(_fmt(st))
    # Reference: all fresh=False
    st = _outcome_stats(fresh_false, "ALL fresh=False")
    L.append(_fmt(st))
    L.append("")

    # ── Table 7: Penetration quantiles by outcome ──
    L.append("## 7. PENETRATION BY OUTCOME (completed trades)")
    L.append("")
    wins = [
        t
        for t in enriched
        if t["result"] in ("TP", "PROFIT_TRAIL") and t["max_penetration_pct"] is not None
    ]
    losses = [t for t in enriched if t["result"] == "LOSS" and t["max_penetration_pct"] is not None]
    if wins and losses:
        w_pens = sorted(t["max_penetration_pct"] for t in wins)
        l_pens = sorted(t["max_penetration_pct"] for t in losses)
        L.append("| Metric | Winners | Losers |")
        L.append("|---|---|---|")
        for label, p in [("P25", 25), ("P50", 50), ("P75", 75), ("Mean", None)]:
            if p is not None:
                wi = min(int(len(w_pens) * p / 100), len(w_pens) - 1)
                li = min(int(len(l_pens) * p / 100), len(l_pens) - 1)
                L.append(f"| {label} | {w_pens[wi]:.1f}% | {l_pens[li]:.1f}% |")
            else:
                L.append(
                    f"| {label} | {sum(w_pens) / len(w_pens):.1f}% | {sum(l_pens) / len(l_pens):.1f}% |"
                )
    L.append("")

    L.append("Observation-only. No commentary or decision.")
    L.append("")

    report_path = out_dir / "exp5d_mitigation_report.md"
    report_path.write_text("\n".join(L), encoding="utf-8")

    print(f"Mitigation JSON : {mit_path}")
    print(f"Enriched JSON   : {enrich_path}")
    print(f"Report          : {report_path}")


if __name__ == "__main__":
    mp.freeze_support()
    main()
