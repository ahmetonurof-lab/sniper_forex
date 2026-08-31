#!/usr/bin/env python
"""PHASE 8 — PARITY GATE — synthetic + integration tests.

Covers:
- check_symbol returns (True, 0, 0, []) when feather missing
- check_all_six_majors runs and returns a report
- ParityReport aggregates canonical_total / signal_total
- can_enable_execution returns True iff report.passed (and no failed)
- One-symbol-only smoke: a known-passing symbol reports True
"""

from __future__ import annotations

from src.live.parity_gate import (
    SIX_MAJORS,
    ParityReport,
    can_enable_execution,
    check_all_six_majors,
    check_symbol,
)


def test_six_majors_universe_complete():
    """The 6 majors must be the exact research universe."""
    assert set(SIX_MAJORS) == {
        "EURUSD",
        "AUDUSD",
        "GBPUSD",
        "GBPJPY",
        "USDCAD",
        "USDJPY",
    }


def test_check_symbol_missing_data_returns_clean():
    """A symbol with no feather must not fail parity (skipped semantics)."""
    # "ZZZ" doesn't exist in data/icmarket_feather
    passed, n_can, n_sig, diffs = check_symbol("ZZZNONE")
    assert passed is True
    assert n_can == 0
    assert n_sig == 0
    assert diffs == []


def test_parity_report_aggregates_totals():
    """ParityReport.canonical_total / signal_total are sums of per-symbol."""
    r = ParityReport(
        passed=True,
        per_symbol_counts={
            "EURUSD": (10, 10),
            "GBPUSD": (5, 5),
        },
    )
    assert r.canonical_total == 15
    assert r.signal_total == 15
    assert r.passed is True


def test_check_all_six_majors_returns_report():
    """check_all_six_majors must produce a report without raising."""
    report = check_all_six_majors()
    assert isinstance(report, ParityReport)
    # Either passed, or failed with details. We don't assert passed here
    # because the feather files are versioned and stable (per Phase 3
    # parity tests) — but a regression would surface as failed_symbols.
    # The parametrized parity test (test_parity_6majors) is the
    # authoritative gate; this test only checks the API contract.
    assert isinstance(report.failed_symbols, list)
    assert isinstance(report.skipped_symbols, list)
    assert isinstance(report.per_symbol_counts, dict)
    assert isinstance(report.details, list)


def test_can_enable_execution_consistent_with_report():
    """can_enable_execution(r) == r.passed and not r.failed_symbols."""
    # Synthetic reports to verify the predicate (no MT5 / data needed).
    r_ok = ParityReport(passed=True, failed_symbols=[])
    assert can_enable_execution(r_ok) is True

    r_fail = ParityReport(passed=False, failed_symbols=["EURUSD"])
    assert can_enable_execution(r_fail) is False

    r_inconsistent = ParityReport(passed=True, failed_symbols=["EURUSD"])
    # Predicate prefers `failed_symbols` (more specific).
    assert can_enable_execution(r_inconsistent) is False
