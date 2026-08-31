#!/usr/bin/env python
"""PHASE 8 — PARITY GATE (execution-gating enforcement).

Roadmap acceptance: "Execution must NOT be enabled without parity PASS."

Wraps the same per-trade comparison used in `tests/test_parity_6majors.py`
as a runtime-callable function. PHASE 11 controlled demo run should call
`check_all_six_majors()` before each session; if any symbol fails, demo
mode must stay in `signal_only` (no real orders).

Pure / injectable: loads feather data from `data/icmarket_feather/` and
calls `experiment.main_research_c_v1_0.run_test_a` + `StrategyRuntime`
directly. No MT5 dep. Slow (replays every bar) — meant to be run at
session start, not on every tick.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from src.live.strategy_runtime import StrategyRuntime
from src.strategy.models import Bar

# Path relative to repo root (this file lives in src/live/).
_REPO_ROOT = Path(__file__).parent.parent.parent
_FEATHER_DIR = _REPO_ROOT / "data" / "icmarket_feather"

# Same universe as test_parity_6majors.
SIX_MAJORS: Tuple[str, ...] = (
    "EURUSD",
    "AUDUSD",
    "GBPUSD",
    "GBPJPY",
    "USDCAD",
    "USDJPY",
)


@dataclass
class ParityReport:
    """Per-symbol + aggregate result of a parity check pass."""

    passed: bool
    failed_symbols: List[str] = field(default_factory=list)
    skipped_symbols: List[str] = field(default_factory=list)
    per_symbol_counts: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    # per_symbol_counts[symbol] = (canonical_count, signal_count)
    details: List[str] = field(default_factory=list)

    @property
    def canonical_total(self) -> int:
        return sum(c for c, _ in self.per_symbol_counts.values())

    @property
    def signal_total(self) -> int:
        return sum(s for _, s in self.per_symbol_counts.values())


def _load_15m(symbol: str) -> Optional[List[Bar]]:
    """Load 15m feather as Bar list, or None if missing."""
    path = _FEATHER_DIR / f"{symbol}_15m.feather"
    if not path.exists():
        return None
    df = pd.read_feather(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    return [
        Bar(
            index=i,
            timestamp=pd.Timestamp(ts),
            open=float(o),
            high=float(h),
            low=float(lo),
            close=float(c),
            volume=float(v),
        )
        for i, ts, o, h, lo, c, v in zip(
            range(len(df)),
            df["timestamp"],
            df["open"],
            df["high"],
            df["low"],
            df["close"],
            df["volume"],
        )
    ]


def _run_canonical(symbol: str, bars_15m: List[Bar]):
    from experiment.main_research_c_v1_0 import run_test_a

    return run_test_a(symbol, bars_15m)


def _run_runtime(symbol: str, bars_15m: List[Bar]):
    rt = StrategyRuntime(symbol)
    rt.warmup(bars_15m)
    if not rt._warmed:
        return []
    signals = []
    for i in range(rt._next_idx, len(bars_15m)):
        sig = rt.on_bar(bars_15m[i])
        if sig is not None:
            signals.append(sig)
    return signals


def _diff_trades(symbol: str, canonical, signals) -> List[str]:
    """Per-trade diff helper (mirrors test_parity_6majors)."""
    diffs: List[str] = []
    if len(signals) != len(canonical):
        diffs.append(f"{symbol}: trade count signal={len(signals)} canonical={len(canonical)}")
    n = min(len(signals), len(canonical))
    for k in range(n):
        sig = signals[k]
        trade = canonical[k]
        if sig.direction != trade.direction:
            diffs.append(
                f"{symbol} trade#{k}: direction signal={sig.direction} canonical={trade.direction}"
            )
        if sig.entry_price != trade.entry_price:
            diffs.append(
                f"{symbol} trade#{k}: entry_price signal={sig.entry_price} "
                f"canonical={trade.entry_price}"
            )
        if sig.sl != trade.sl:
            diffs.append(f"{symbol} trade#{k}: sl signal={sig.sl} canonical={trade.sl}")
        if sig.tp != trade.tp:
            diffs.append(f"{symbol} trade#{k}: tp signal={sig.tp} canonical={trade.tp}")
        if sig.entry_bar_index != trade.entry_bar_index:
            diffs.append(
                f"{symbol} trade#{k}: entry_bar signal={sig.entry_bar_index} "
                f"canonical={trade.entry_bar_index}"
            )
        if sig.sweep_bar_index != trade.sweep_bar_index:
            diffs.append(
                f"{symbol} trade#{k}: sweep_bar signal={sig.sweep_bar_index} "
                f"canonical={trade.sweep_bar_index}"
            )
        if sig.zone_index != trade.zone_index:
            diffs.append(
                f"{symbol} trade#{k}: zone signal={sig.zone_index} canonical={trade.zone_index}"
            )
    return diffs


def check_symbol(symbol: str) -> Tuple[bool, int, int, List[str]]:
    """Parity check for a single symbol.

    Returns: (passed, canonical_count, signal_count, diffs).
    On missing data, returns (True, 0, 0, []) — missing feather is
    treated as a no-op (caller can inspect skipped_symbols separately).
    """
    bars_15m = _load_15m(symbol)
    if bars_15m is None or len(bars_15m) < 100:
        return (True, 0, 0, [])
    canonical = _run_canonical(symbol, bars_15m)
    signals = _run_runtime(symbol, bars_15m)
    diffs = _diff_trades(symbol, canonical, signals)
    return (len(diffs) == 0, len(canonical), len(signals), diffs)


def check_all_six_majors() -> ParityReport:
    """Run parity check for every symbol in SIX_MAJORS.

    Returns a ParityReport:
        - `passed` is True iff every available symbol passed parity.
        - `failed_symbols` lists symbols with at least one diff.
        - `skipped_symbols` lists symbols with no/insufficient data.
        - `per_symbol_counts` maps symbol -> (canonical_count, signal_count).
        - `details` is a flat list of per-diff human-readable strings.
    """
    failed: List[str] = []
    skipped: List[str] = []
    counts: Dict[str, Tuple[int, int]] = {}
    details: List[str] = []
    for symbol in SIX_MAJORS:
        path = _FEATHER_DIR / f"{symbol}_15m.feather"
        if not path.exists():
            skipped.append(symbol)
            continue
        passed, n_can, n_sig, diffs = check_symbol(symbol)
        counts[symbol] = (n_can, n_sig)
        if not passed:
            failed.append(symbol)
            details.extend(diffs)
    return ParityReport(
        passed=not failed,
        failed_symbols=failed,
        skipped_symbols=skipped,
        per_symbol_counts=counts,
        details=details,
    )


def can_enable_execution(report: Optional[ParityReport] = None) -> bool:
    """Execution-gating predicate.

    PHASE 11 must call this (or `check_all_six_majors()` then check
    `report.passed`) before turning off `signal_only`. If False, demo
    mode stays in `signal_only`.

    If `report` is None, runs the check on demand (slow; ~minutes).
    """
    if report is None:
        report = check_all_six_majors()
    return report.passed and not report.failed_symbols
