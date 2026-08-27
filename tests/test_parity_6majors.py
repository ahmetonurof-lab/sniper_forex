#!/usr/bin/env python
"""PHASE 8 — FULL BACKTEST/LIVE PARITY (6 majors).

Roadmap acceptance: same 15m data -> identical trade list between the
frozen canonical engine (`experiment/main_research_c_v1_0.run_test_a`)
and the live runtime (`src.live.strategy_runtime.StrategyRuntime`).

Compares per-trade:
    - direction (long/short)
    - entry_price (approx, rel=1e-9)
    - sl (approx, rel=1e-9)
    - tp (approx, rel=1e-9)
    - entry_bar_index
    - sweep_bar_index
    - zone_index

A failure on any of the 6 majors means execution must NOT be enabled
on the live runtime. The `parity_gate.py` helper in this phase exposes
the same checks as a runtime-callable function (so PHASE 11 demo run
can call it before each session).

Data path: `data/icmarket_feather/<SYM>_15m.feather` (the same data
the frozen engine consumes). Tests are skipped (not failed) if the
feather file is missing on disk.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import pandas as pd
import pytest

from src.strategy.models import Bar
from src.live.strategy_runtime import StrategyRuntime

_PROJECT_ROOT = Path(__file__).parent.parent
_FEATHER_DIR = _PROJECT_ROOT / "data" / "icmarket_feather"

# All 6 majors covered by the research universe.
SIX_MAJORS = ("EURUSD", "AUDUSD", "GBPUSD", "GBPJPY", "USDCAD", "USDJPY")


# ── Helpers (mirror test_live_strategy_runtime.py, kept self-contained) ──


def _load_15m(symbol: str) -> List[Bar]:
    """Load 15m feather as Bar list. Index == position (parity with engine)."""
    path = _FEATHER_DIR / f"{symbol}_15m.feather"
    if not path.exists():
        pytest.skip(f"No 15m feather for {symbol}: {path}")
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
    """Run the frozen `run_test_a`; returns list of BenchmarkTrade."""
    from experiment.main_research_c_v1_0 import run_test_a

    return run_test_a(symbol, bars_15m)


def _run_runtime(symbol: str, bars_15m: List[Bar]):
    """Run StrategyRuntime incrementally; returns list of Signal."""
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
    """Return a list of human-readable diff strings (empty if identical)."""
    diffs: List[str] = []
    if len(signals) != len(canonical):
        diffs.append(
            f"{symbol}: trade count signal={len(signals)} canonical={len(canonical)}"
        )
    # Compare up to min length; extra entries are reported individually.
    n = min(len(signals), len(canonical))
    for k in range(n):
        sig = signals[k]
        trade = canonical[k]
        if sig.direction != trade.direction:
            diffs.append(
                f"{symbol} trade#{k}: direction signal={sig.direction} "
                f"canonical={trade.direction}"
            )
        if sig.entry_price != pytest.approx(trade.entry_price, rel=1e-9):
            diffs.append(
                f"{symbol} trade#{k}: entry_price signal={sig.entry_price} "
                f"canonical={trade.entry_price}"
            )
        if sig.sl != pytest.approx(trade.sl, rel=1e-9):
            diffs.append(f"{symbol} trade#{k}: sl signal={sig.sl} canonical={trade.sl}")
        if sig.tp != pytest.approx(trade.tp, rel=1e-9):
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
                f"{symbol} trade#{k}: zone signal={sig.zone_index} "
                f"canonical={trade.zone_index}"
            )
    return diffs


# ── Per-symbol parity ───────────────────────────────────────────


@pytest.mark.parametrize("symbol", SIX_MAJORS)
def test_parity_per_symbol(symbol: str):
    """Live runtime must produce the IDENTICAL trade list as the frozen
    canonical engine on the same 15m feather, for every covered symbol."""
    bars_15m = _load_15m(symbol)
    if len(bars_15m) < 100:
        pytest.skip(f"{symbol}: too few bars ({len(bars_15m)})")
    canonical = _run_canonical(symbol, bars_15m)
    signals = _run_runtime(symbol, bars_15m)
    diffs = _diff_trades(symbol, canonical, signals)
    assert not diffs, "Parity failed:\n  " + "\n  ".join(diffs)


# ── Aggregate parity summary (one-shot diagnostic) ──────────────


def test_parity_summary_all_six_majors():
    """Aggregate summary: total canonical vs live trades across all 6 majors.

    A regression that changes the engine but keeps the per-symbol
    identity would still pass the per-symbol test; this summary gives
    a quick aggregate view. Acceptance: signal count per symbol must
    match canonical exactly (so the aggregate is implicitly correct).
    """
    summary: List[Tuple[str, int, int]] = []
    for symbol in SIX_MAJORS:
        bars_15m = _load_15m(symbol)
        if len(bars_15m) < 100:
            continue
        canonical = _run_canonical(symbol, bars_15m)
        signals = _run_runtime(symbol, bars_15m)
        summary.append((symbol, len(canonical), len(signals)))
        # Equality per symbol is already asserted in the parametrized test;
        # this test is purely a documentation-friendly aggregate.
    assert summary, "No symbols had sufficient data for parity"
    # Every per-symbol pair must be equal.
    for sym, n_can, n_sig in summary:
        assert (
            n_can == n_sig
        ), f"{sym}: aggregate mismatch canonical={n_can} signal={n_sig}"
