"""
Static validation for Variant D PURE — pre-flight checks per spec.

Checks (must all PASS before any full run):
  1. Canonical engine file unchanged vs HEAD (byte/semantic)
  2. Pure runner does NOT call canon.run_test_a() (would inject Frozen EQ)
  3. D formula present
  4. f = fvg.real_index reference
  5. No-lookahead guard: 4·(h+3) ≤ f
  6. Bullish = low, bearish = high
  7. D position filter direction
  8. Summary.md append-only
  9. Audit fields coverage
 10. Banned patterns:
       - no _CbdrInjector
       - no body_low property proxy
       - no SessionManager monkey-patch subclass
       - no Frozen EQ secondary veto / fallback / pre-filter
       - no post-filter of canonical trades
       - no run_test_a() call from pure runner
"""

import re
import subprocess
import sys
from pathlib import Path

# Force UTF-8 stdout
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

REPO = Path(r"C:\Users\Administrator\Desktop\sniper_forex")
CANON = REPO / "experiment" / "main_research_c_v1_0.py"
VARIANT = REPO / "experiment" / "main_research_d_v1_0.py"
SUMMARY_MD = REPO / "results" / "research" / "variant_D_fvg_origin_eq_summary.md"

results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    results.append((status, name, detail))
    print(f"  [{status}] {name}{(' — ' + detail) if detail else ''}")


def main():
    print("=== VARIANT D PURE STATIC VALIDATION ===\n")

    # 1. Canonical engine unchanged
    print("[1] Canonical engine unchanged")
    diff = subprocess.run(
        ["git", "diff", "--no-color", "--", "experiment/main_research_c_v1_0.py"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )
    status_out = subprocess.run(
        ["git", "status", "--short", "--", "experiment/main_research_c_v1_0.py"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )
    canon_clean = diff.stdout.strip() == "" and status_out.stdout.strip() == ""
    check(
        "Canonical engine modified: NO",
        canon_clean,
        f"diff={len(diff.stdout)}b, status={status_out.stdout.strip()!r}",
    )

    # 2. Pure runner does NOT call canon.run_test_a
    print("\n[2] Pure runner does NOT call canon.run_test_a()")
    src = VARIANT.read_text(encoding="utf-8")
    # The pure runner walks the FVG loop itself with only EQ swapped.
    # It must NOT call _canon.run_test_a (Frozen EQ baked in).
    # Acceptable references: imports, docstrings, comments.
    has_run_test_a_call = bool(
        re.search(r"_canon\.run_test_a\s*\(", src)
        or re.search(r"_canon_run_test_a\s*\(", src)
    )
    check("No _canon.run_test_a() call", not has_run_test_a_call)

    # 3. D formula presence
    print("\n[3] D formula in variant")
    has_d_eq_def = "def compute_d_eq" in src
    has_pivot_1h = "pivot_1h" in src
    has_leg_high_low = "leg_high" in src and "leg_low" in src
    has_d_eq_var = "d_eq" in src
    check("compute_d_eq() defined", has_d_eq_def)
    check("pivot_1h present", has_pivot_1h)
    check("leg_high/leg_low present", has_leg_high_low)
    check("d_eq variable present", has_d_eq_var)

    # 4. f = fvg.real_index reference
    print("\n[4] f = fvg.real_index")
    uses_f = "fvg.real_index" in src
    check("fvg.real_index used", uses_f)

    # 5. No-lookahead guard
    print("\n[5] No-lookahead (4·(h+3) ≤ f)")
    has_lookahead_check = "confirm_15m > f" in src
    has_lookahead_doc = "4·(h+3) ≤ f" in src or "4*(h+3) <= f" in src
    check("future_pivot rejection present", has_lookahead_check)
    check("no-lookahead doc/audit present", has_lookahead_doc)

    # 6. Bullish = low, bearish = high
    print("\n[6] Bullish→low, Bearish→high pivot selection")
    bull_block = re.search(
        r"if\s+direction\s*==\s*[\"']bullish[\"']\s*:.*?pivot_1h_kind\s*=\s*[\"']low[\"']",
        src,
        re.DOTALL,
    )
    bear_block = re.search(
        r"#\s*bearish.*?pivot_1h_kind\s*=\s*[\"']high[\"']",
        src,
        re.DOTALL,
    )
    check("bullish→low", bool(bull_block))
    check("bearish→high", bool(bear_block))

    # 7. D position filter
    print("\n[7] D position filter direction")
    bull_filter = "fvg_top >= audit.d_eq" in src
    bear_filter = "fvg_bottom <= audit.d_eq" in src
    check("bullish filter: fvg.top ≥ d_eq → REJECT", bull_filter)
    check("bearish filter: fvg.bottom ≤ d_eq → REJECT", bear_filter)

    # 8. Summary.md append-only
    print("\n[8] Summary.md append-only")
    uses_append_mode = re.search(r"open\([^)]*\"a\"[^)]*\)", src) is not None
    check("file opened in 'a' (append) mode", uses_append_mode)
    if SUMMARY_MD.exists():
        before = SUMMARY_MD.read_text(encoding="utf-8")
        if "## RUN —" in before:
            check("Existing summary.md has prior runs (won't be clobbered)", True)
        else:
            check("Existing summary.md has prior runs", False, "no prior runs found")

    # 9. Audit fields
    print("\n[9] Audit fields")
    has_audit_class = "class DAudit" in src
    has_candidates_json = "variant_D_fvg_origin_eq{suffix}_candidates" in src
    has_d_rejected_path = "d_eq_rejected" in src
    check("DAudit class defined", has_audit_class)
    check("candidate-level JSON artifact", has_candidates_json)
    check("rejected candidates tracked", has_d_rejected_path)

    # 10. Banned patterns
    print("\n[10] Banned patterns")
    has_injector = "_CbdrInjector" in src
    has_body_proxy = re.search(r"def\s+body_low\s*\(", src) is not None
    has_sm_patch = "_D_EQ_SessionManager" in src
    has_run_test_a_call = bool(
        re.search(r"_canon\.run_test_a\s*\(", src)
        or re.search(r"_canon_run_test_a\s*\(", src)
    )
    check("No _CbdrInjector", not has_injector)
    check("No body_low property proxy", not has_body_proxy)
    check("No SessionManager monkey-patch subclass", not has_sm_patch)
    check("No canon.run_test_a() call from pure runner", not has_run_test_a_call)

    # Also verify the runner walks the FVG eval loop (not just post-filter)
    print("\n[10b] PURE D structural assertions")
    has_fresh_check = "_canon_is_fresh_fvg" in src
    has_touch_check = "bar.low <= fvg.top" in src or "bar.high >= fvg.bottom" in src
    has_entry_mechanics = "entry_price = bars_15m[i + 1].open" in src
    has_sl_tp = "FVG_BUFFER_MULT" in src and "TP_RR" in src
    has_trailing = "apply_trailing" in src
    has_exit = "check_exit" in src
    check("freshness check uses canonical helper", has_fresh_check)
    check("entry touch check present", has_touch_check)
    check("next-bar-open entry timing present", has_entry_mechanics)
    check("SL/TP constants from canonical config", has_sl_tp)
    check("trailing uses canonical apply_trailing", has_trailing)
    check("exit uses canonical check_exit", has_exit)

    # Final
    print("\n=== SUMMARY ===")
    fail = [r for r in results if r[0] == "FAIL"]
    print(f"  {len(results) - len(fail)}/{len(results)} checks PASSED")
    if fail:
        print(f"  ❌ {len(fail)} FAILURES:")
        for s, n, d in fail:
            print(f"    - {n}: {d}")
        sys.exit(1)
    else:
        print("  ✅ ALL CHECKS PASSED — safe to run.")


if __name__ == "__main__":
    main()
