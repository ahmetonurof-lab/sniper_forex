"""
Static validation for Variant D — pre-flight checks per spec item #18.

Checks (must all PASS before any full run):
  1. Canonical engine file mtime + content unchanged vs HEAD
  2. D formula present in variant file
  3. f = fvg.real_index reference is used
  4. No-lookahead guard: 4·(h+3) ≤ f enforced
  5. Bullish pivot = low, bearish pivot = high
  6. D position filter direction (bullish: top<eq, bearish: bottom>eq)
  7. Summary.md append-only (no overwrite of existing content)
  8. Audit fields coverage: rejected candidates also recorded
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
CANON = REPO / "experiment" / "main_research_c.py"
VARIANT = REPO / "experiment" / "research_variant_D_fvg_origin_eq.py"
SUMMARY_MD = REPO / "results" / "research" / "variant_D_fvg_origin_eq_summary.md"

results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    results.append((status, name, detail))
    print(f"  [{status}] {name}{(' — ' + detail) if detail else ''}")


def main():
    print("=== VARIANT D STATIC VALIDATION ===\n")

    # 1. Canonical engine unchanged
    print("[1] Canonical engine unchanged")
    diff = subprocess.run(
        ["git", "diff", "--no-color", "--", "experiment/main_research_c.py"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )
    status_out = subprocess.run(
        ["git", "status", "--short", "--", "experiment/main_research_c.py"],
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

    # 2. D formula presence
    print("\n[2] D formula in variant")
    src = VARIANT.read_text(encoding="utf-8")
    has_d_eq_def = "def compute_d_eq" in src
    has_pivot_1h = "pivot_1h" in src
    has_leg_high_low = "leg_high" in src and "leg_low" in src
    has_d_eq_var = "d_eq" in src
    check("compute_d_eq() defined", has_d_eq_def)
    check("pivot_1h present", has_pivot_1h)
    check("leg_high/leg_low present", has_leg_high_low)
    check("d_eq variable present", has_d_eq_var)

    # 3. f = fvg.real_index reference
    print("\n[3] f = fvg.real_index")
    uses_f = "fvg.real_index" in src
    check("fvg.real_index used", uses_f)

    # 4. No-lookahead guard
    print("\n[4] No-lookahead (4·(h+3) ≤ f)")
    has_lookahead_check = "confirm_15m > f" in src or "pivot_1h + PIVOT_RIGHT" in src
    has_lookahead_doc = (
        "4·(h+3) ≤ f" in src or "4*(h+3) <= f" in src or "4×(h+3)" in src
    )
    check("future_pivot rejection present", has_lookahead_check)
    check("no-lookahead doc/audit present", has_lookahead_doc)

    # 5. Bullish = low, bearish = high
    print("\n[5] Bullish→low, Bearish→high pivot selection")
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

    # 6. D position filter
    print("\n[6] D position filter direction")
    bull_filter = "fvg_top >= audit.d_eq" in src or "fvg.top >= d_eq" in src
    bear_filter = "fvg_bottom <= audit.d_eq" in src or "fvg.bottom <= d_eq" in src
    check("bullish filter: fvg.top ≥ d_eq → REJECT", bull_filter)
    check("bearish filter: fvg.bottom ≤ d_eq → REJECT", bear_filter)

    # 7. Append-only
    print("\n[7] Summary.md append-only")
    # Check that the file is opened in 'a' mode
    uses_append_mode = re.search(r"open\([^)]*\"a\"[^)]*\)", src) is not None
    check("file opened in 'a' (append) mode", uses_append_mode)
    # Also check the existing summary.md is not clobbered by the dry-run path
    if SUMMARY_MD.exists():
        before = SUMMARY_MD.read_text(encoding="utf-8")
        if "## RUN —" in before:
            check("Existing summary.md has prior runs (won't be clobbered)", True)
        else:
            check("Existing summary.md has prior runs", False, "no prior runs found")

    # 8. Audit fields coverage
    print("\n[8] Audit fields")
    has_audit_class = "class DAudit" in src
    has_candidates_json = "variant_D_fvg_origin_eq_candidates" in src
    has_d_rejected_path = "d_rejected" in src
    check("DAudit class defined", has_audit_class)
    check("candidate-level JSON artifact", has_candidates_json)
    check("rejected candidates tracked", has_d_rejected_path)

    # 9. Banned patterns
    print("\n[9] Banned patterns (no _CbdrInjector, no body_low proxy)")
    has_injector = "_CbdrInjector" in src
    has_body_proxy = re.search(r"def\s+body_low\s*\(", src) is not None
    has_sm_patch = "_D_EQ_SessionManager" in src
    check("No _CbdrInjector", not has_injector)
    check("No body_low property proxy", not has_body_proxy)
    check("No SessionManager monkey-patch subclass", not has_sm_patch)

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
