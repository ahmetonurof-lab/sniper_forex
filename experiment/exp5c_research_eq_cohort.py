"""
EXP 5C — Research EQ Cohort Attribution
==========================================

Amaç: 529 historical trade'i Research EQ cohort'larına sınıflandırıp
her cohort için outcome istatistiği üretmek.

Cohort tanımı:
  1. CORRECT_AT_FORMATION + FRESH   (eq_position=CORRECT_SIDE, fresh=True)
  2. CORRECT_AT_FORMATION + STALE   (eq_position=CORRECT_SIDE, fresh=False)
  3. WRONG_LATER_CORRECT + FRESH    (eq≠CORRECT, first_correct exists, still_fresh=True)
  4. WRONG_LATER_CORRECT + STALE    (eq≠CORRECT, first_correct exists, still_fresh=False)
  5. NEVER_CORRECT                  (eq≠CORRECT, first_correct=None)

Merge stratejisi:
  EXP5B telemetry: (symbol, fvg_bar_index) → {eq_position, fresh, first_correct, ...}
  EXP5C outcome:   (symbol, zone_index)    → trade {result, pnl_r, ob_found, ...}
  Bridge: zone_index == fvg_bar_index

DISIPLIN:
- Entry filtreleri DEGISTIRILMEZ.
- KNOWN-GOOD run_test_a, EXP5B, Research EQ ve production'a dokunulmaz.
- Yeni backtest framework YAZILMAZ.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

_PROJECT_ROOT = Path(__file__).parent.parent


def _outcome_stats(trades: List[Dict], label: str) -> Dict[str, Any]:
    """Same stats helper as exp5c_outcome_attribution."""
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


def _fmt_row(st: Dict) -> str:
    return (
        f"| {st['label']} | {st['N']} | {st['completed']} | "
        f"{st['WR%']} | {st['AvgR']} | {st['Expectancy']} | "
        f"{st['TotalR']} | {st['MaxDD']} |"
    )


def _classify_cohort(tel: Dict[str, Any]) -> str:
    """Classify an EXP5B telemetry record into one of 5 cohorts."""
    eq = tel["eq_position"]
    has_first_correct = tel["first_correct_side_bar_index"] is not None

    if eq == "CORRECT_SIDE":
        return "CORRECT_AT_FORMATION + FRESH" if tel["fresh"] else "CORRECT_AT_FORMATION + STALE"
    elif has_first_correct:
        sf = tel.get("still_fresh_at_first_correct")
        return "WRONG_LATER_CORRECT + FRESH" if sf else "WRONG_LATER_CORRECT + STALE"
    else:
        return "NEVER_CORRECT"


def main():
    # ── Load data ──
    tel5b_path = (
        _PROJECT_ROOT / "results" / "research" / "exp5b_post_sweep_fvg_1v2_eq_telemetry.json"
    )
    oc_path = _PROJECT_ROOT / "results" / "research" / "exp5c_outcome_attribution.json"

    tel5b = json.loads(tel5b_path.read_text(encoding="utf-8"))
    trades = json.loads(oc_path.read_text(encoding="utf-8"))

    print("=== EXP 5C — Research EQ Cohort Attribution ===")
    print(f"EXP5B telemetry: {len(tel5b)} records | EXP5C trades: {len(trades)}")
    print()

    # ── Build bridge: (symbol, fvg_bar_index) → EXP5B telemetry ──
    tel_lookup: Dict[tuple, Dict] = {}
    for r in tel5b:
        key = (r["symbol"], r["fvg_bar_index"])
        tel_lookup[key] = r

    # ── Classify each trade ──
    enriched = []
    unmatched = 0
    for t in trades:
        sym = t["symbol"]
        zone_idx = t["zone_index"] if "zone_index" in t else None

        # For slot=0 (Later/Unknown), zone_index isn't in the outcome JSON
        # We need to reconstruct it. The outcome JSON has sweep_bar_index
        # but not zone_index. We can look up via (symbol, sweep_bar_index)
        # but that's the SWEEP, not the FVG. For slot=0, we skip EQ lookup.
        slot = t["slot"]

        tel = None
        if slot in (1, 2) and zone_idx is not None:
            tel = tel_lookup.get((sym, zone_idx))
        elif slot == 0:
            # slot=0: trade's zone_index doesn't match f1 or f2
            # No direct EQ lookup — classify as UNKNOWN
            tel = None

        if tel is not None:
            cohort = _classify_cohort(tel)
            enriched.append(
                {
                    **t,
                    "cohort": cohort,
                    "eq_position": tel["eq_position"],
                    "fresh": tel["fresh"],
                    "research_eq": tel["research_eq"],
                    "first_correct_swings": tel["first_correct_side_swings"],
                    "still_fresh_at_correct": tel["still_fresh_at_first_correct"],
                }
            )
        else:
            enriched.append(
                {
                    **t,
                    "cohort": "LATER_UNKNOWN_NO_EQ",
                    "eq_position": None,
                    "fresh": None,
                    "research_eq": None,
                    "first_correct_swings": None,
                    "still_fresh_at_correct": None,
                }
            )
            unmatched += 1

    print(
        f"Matched to EXP5B telemetry: {len(enriched) - unmatched}/{len(enriched)} | "
        f"Unmatched (slot=0): {unmatched}"
    )
    print()

    # ── Save enriched JSON ──
    out_dir = _PROJECT_ROOT / "results" / "research"
    enriched_path = out_dir / "exp5c_research_eq_cohort.json"
    enriched_path.write_text(json.dumps(enriched, indent=2, default=str), encoding="utf-8")
    print(f"Enriched JSON: {enriched_path}")

    # ── Report ──
    L: List[str] = []
    L.append("# EXP 5C — Research EQ Cohort × Outcome Attribution")
    L.append("")
    L.append("## TANIM")
    L.append("")
    L.append("Cohort sınıflandırması EXP5B Research EQ telemetry üzerine kuruludur:")
    L.append(
        "- **CORRECT_AT_FORMATION + FRESH**: FVG formation'da EQ correct tarafında, hiç dokunulmamış"
    )
    L.append(
        "- **CORRECT_AT_FORMATION + STALE**: FVG formation'da EQ correct tarafında, sonra dokunulmuş"
    )
    L.append(
        "- **WRONG_LATER_CORRECT + FRESH**: Formation'da wrong taraf, sonra confirmed swing ile correct'e geçmiş, hâlâ fresh"
    )
    L.append(
        "- **WRONG_LATER_CORRECT + STALE**: Formation'da wrong taraf, correct'e geçmiş ama artık stale"
    )
    L.append("- **NEVER_CORRECT**: Hiçbir confirmed swing ile correct tarafa geçmemiş")
    L.append("- **LATER_UNKNOWN_NO_EQ**: Later/Unknown slot (zone_index FVG #1/#2 ile eşleşmemiş)")
    L.append("")
    L.append("Entry rules: UNCHANGED (KNOWN-GOOD run_test_a). OB/BB = forensic context.")
    L.append("")
    L.append("## POPULATION")
    L.append("")
    L.append(
        f"- Total trades: **{len(trades)}** | Completed: **{sum(1 for t in trades if t['result'] in ('TP', 'PROFIT_TRAIL', 'LOSS'))}**"
    )
    L.append("")

    # ── Table 1: Cohort breakdown ──
    cohort_order = [
        "CORRECT_AT_FORMATION + FRESH",
        "CORRECT_AT_FORMATION + STALE",
        "WRONG_LATER_CORRECT + FRESH",
        "WRONG_LATER_CORRECT + STALE",
        "NEVER_CORRECT",
        "LATER_UNKNOWN_NO_EQ",
    ]
    L.append("## 1. RESEARCH EQ COHORT")
    L.append("")
    L.append("| Cohort | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |")
    L.append("|---|---|---|---|---|---|---|---|")
    for c in cohort_order:
        subset = [t for t in enriched if t["cohort"] == c]
        if subset:
            st = _outcome_stats(subset, c)
            L.append(_fmt_row(st))
    L.append("")

    # ── Table 2: Cohort × FVG Slot ──
    L.append("## 2. COHORT × FVG SLOT")
    L.append("")
    L.append("| Cohort | Slot | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for c in cohort_order:
        for slot, slabel in [(1, "#1"), (2, "#2"), (0, "Later")]:
            subset = [t for t in enriched if t["cohort"] == c and t["slot"] == slot]
            if subset:
                st = _outcome_stats(subset, f"{c} [{slabel}]")
                L.append(
                    f"| {c} | {slabel} | {st['N']} | {st['completed']} | "
                    f"{st['WR%']} | {st['AvgR']} | {st['Expectancy']} | "
                    f"{st['TotalR']} | {st['MaxDD']} |"
                )
    L.append("")

    # ── Table 3: Cohort × OB context ──
    fvg_enriched = [t for t in enriched if t["slot"] in (1, 2)]
    L.append("## 3. COHORT × OB CONTEXT (FVG #1 + #2)")
    L.append("")
    L.append("| Cohort | OB | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for c in cohort_order:
        for ob_label, ob_filt in [("OB", True), ("no OB", False)]:
            subset = [t for t in fvg_enriched if t["cohort"] == c and t["ob_found"] == ob_filt]
            if subset:
                st = _outcome_stats(subset, f"{c} [{ob_label}]")
                L.append(
                    f"| {c} | {ob_label} | {st['N']} | {st['completed']} | "
                    f"{st['WR%']} | {st['AvgR']} | {st['Expectancy']} | "
                    f"{st['TotalR']} | {st['MaxDD']} |"
                )
    L.append("")

    # ── Table 4: Cohort × Breaker context ──
    L.append("## 4. COHORT × BREAKER CONTEXT (FVG #1 + #2)")
    L.append("")
    L.append("| Cohort | Breaker | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for c in cohort_order:
        for bb_label, bb_filt in [("BB", True), ("no BB", False)]:
            subset = [t for t in fvg_enriched if t["cohort"] == c and t["breaker_found"] == bb_filt]
            if subset:
                st = _outcome_stats(subset, f"{c} [{bb_label}]")
                L.append(
                    f"| {c} | {bb_label} | {st['N']} | {st['completed']} | "
                    f"{st['WR%']} | {st['AvgR']} | {st['Expectancy']} | "
                    f"{st['TotalR']} | {st['MaxDD']} |"
                )
    L.append("")

    # ── Deep-dive: 62 Later/Unknown trades ──
    later = [t for t in enriched if t["cohort"] == "LATER_UNKNOWN_NO_EQ"]
    L.append("## 5. LATER/UNKNOWN TRADES DEEP-DIVE (N=62)")
    L.append("")
    L.append("Bu trade'lerin zone_index'i FVG #1 veya #2 ile eşleşmemiş.")
    L.append("Research EQ cohort sınıflandırması bu trade'lere uygulanamaz.")
    L.append("")

    # 5a. Slot distribution (should all be slot=0)
    slot_dist = {}
    for t in later:
        slot_dist[t["slot"]] = slot_dist.get(t["slot"], 0) + 1
    L.append("### 5a. Slot Distribution")
    L.append("")
    L.append(f"- Slot 0 (Later/Unknown): {slot_dist.get(0, 0)}")
    L.append("")

    # 5b. Result distribution
    result_dist = {}
    for t in later:
        r = t["result"]
        result_dist[r] = result_dist.get(r, 0) + 1
    L.append("### 5b. Result Distribution")
    L.append("")
    L.append("| Result | Count |")
    L.append("|---|---|")
    for r, c in sorted(result_dist.items(), key=lambda x: -x[1]):
        L.append(f"| {r} | {c} |")
    L.append("")

    # 5c. PnL distribution
    pnls = [t["pnl_r"] for t in later if t["result"] in ("TP", "PROFIT_TRAIL", "LOSS")]
    if pnls:
        wins_pnl = [p for p in pnls if p > 0]
        loss_pnl = [p for p in pnls if p < 0]
        L.append("### 5c. PnL Distribution (completed trades)")
        L.append("")
        L.append(
            f"- Total completed: {len(pnls)} | Wins: {len(wins_pnl)} | Losses: {len(loss_pnl)}"
        )
        L.append(
            f"- Avg win: {sum(wins_pnl) / len(wins_pnl):.3f}R" if wins_pnl else "- Avg win: N/A"
        )
        L.append(
            f"- Avg loss: {sum(loss_pnl) / len(loss_pnl):.3f}R" if loss_pnl else "- Avg loss: N/A"
        )
        L.append(f"- Total R: {sum(pnls):.2f}R")
        L.append("")

    # 5d. Per-symbol breakdown
    sym_dist = {}
    for t in later:
        sym_dist[t["symbol"]] = sym_dist.get(t["symbol"], 0) + 1
    L.append("### 5d. Per-Symbol Distribution")
    L.append("")
    L.append("| Symbol | Count |")
    L.append("|---|---|")
    for s, c in sorted(sym_dist.items(), key=lambda x: -x[1]):
        L.append(f"| {s} | {c} |")
    L.append("")

    # 5e. Sample records (first 10)
    L.append("### 5e. Sample Records (first 10)")
    L.append("")
    L.append("| Symbol | Result | PnL(R) | OB | Mitigated | BB | BB Ovlp |")
    L.append("|---|---|---|---|---|---|---|")
    for t in later[:10]:
        ob = "✓" if t["ob_found"] else "—" if t["ob_found"] is None else "✗"
        mit = "✓" if t["ob_mitigated"] else "—" if t["ob_mitigated"] is None else "✗"
        bb = "✓" if t["breaker_found"] else "—" if t["breaker_found"] is None else "✗"
        bbo = "✓" if t["breaker_overlaps"] else "—" if t["breaker_overlaps"] is None else "✗"
        pnl = f"{t['pnl_r']:.2f}"
        L.append(f"| {t['symbol']} | {t['result']} | {pnl} | {ob} | {mit} | {bb} | {bbo} |")
    L.append("")

    L.append("Observation-only. No commentary or decision.")
    L.append("")

    report_path = out_dir / "exp5c_research_eq_cohort_report.md"
    report_path.write_text("\n".join(L), encoding="utf-8")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
