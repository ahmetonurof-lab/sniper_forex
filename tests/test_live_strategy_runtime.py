#!/usr/bin/env python
"""PHASE 3 — STRATEGY RUNTIME — deterministic replay parity tests.

Acceptance criteria: Historical replay parity with canonical engine
(signal/SL/TP). Given the same 15m data, the live `StrategyRuntime` must
produce the same entry signals (direction, entry_price, sl, tp,
entry_bar_index, sweep_bar_index, zone_index) as the frozen `run_test_a`
engine.

Uses real 15m feather data (data/icmarket_feather) so the comparison is
against the actual canonical engine output, not synthetic data.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.live.strategy_runtime import StrategyRuntime
from src.strategy.models import Bar

_PROJECT_ROOT = Path(__file__).parent.parent
_FEATHER_DIR = _PROJECT_ROOT / "data" / "icmarket_feather"


def _load_15m(symbol: str) -> list[Bar]:
    """Load 15m feather as Bar list (index == position, parity with engine)."""
    path = _FEATHER_DIR / f"{symbol}_15m.feather"
    if not path.exists():
        pytest.skip(f"No 15m feather for {symbol}: {path}")
    df = pd.read_feather(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    bars = [
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
    return bars


def _run_canonical(symbol: str, bars_15m: list[Bar]):
    """Run frozen run_test_a; return list of BenchmarkTrade."""
    from experiment.main_research_c_v1_0 import run_test_a

    return run_test_a(symbol, bars_15m)


def _run_runtime(symbol: str, bars_15m: list[Bar]):
    """Run StrategyRuntime incrementally; return list of Signal."""
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


def _assert_parity(symbol: str, bars_15m: list[Bar]):
    canonical = _run_canonical(symbol, bars_15m)
    signals = _run_runtime(symbol, bars_15m)

    # Every canonical trade was entered once -> one signal each.
    assert len(signals) == len(
        canonical
    ), f"{symbol}: signal count {len(signals)} != canonical trades {len(canonical)}"

    for sig, trade in zip(signals, canonical):
        assert (
            sig.direction == trade.direction
        ), f"{symbol}: direction {sig.direction} != {trade.direction}"
        assert sig.entry_price == pytest.approx(
            trade.entry_price, rel=1e-9
        ), f"{symbol}: entry {sig.entry_price} != {trade.entry_price}"
        assert sig.sl == pytest.approx(trade.sl, rel=1e-9), f"{symbol}: sl {sig.sl} != {trade.sl}"
        assert sig.tp == pytest.approx(trade.tp, rel=1e-9), f"{symbol}: tp {sig.tp} != {trade.tp}"
        assert (
            sig.entry_bar_index == trade.entry_bar_index
        ), f"{symbol}: entry_bar {sig.entry_bar_index} != {trade.entry_bar_index}"
        assert (
            sig.sweep_bar_index == trade.sweep_bar_index
        ), f"{symbol}: sweep_bar {sig.sweep_bar_index} != {trade.sweep_bar_index}"
        assert (
            sig.zone_index == trade.zone_index
        ), f"{symbol}: zone {sig.zone_index} != {trade.zone_index}"


@pytest.mark.parametrize("symbol", ["EURUSD", "GBPUSD"])
def test_replay_parity_with_canonical_engine(symbol: str):
    bars_15m = _load_15m(symbol)
    if len(bars_15m) < 100:
        pytest.skip(f"{symbol}: too few bars")
    _assert_parity(symbol, bars_15m)


def test_runtime_produces_signals_on_real_data():
    """Sanity: runtime emits at least one signal on real EURUSD data."""
    bars_15m = _load_15m("EURUSD")
    if len(bars_15m) < 100:
        pytest.skip("EURUSD: too few bars")
    signals = _run_runtime("EURUSD", bars_15m)
    assert len(signals) > 0, "Expected at least one signal on EURUSD"


def test_state_roundtrip_preserves_runtime():
    """to_state/from_state roundtrip preserves recoverable runtime state."""
    bars_15m = _load_15m("EURUSD")
    if len(bars_15m) < 100:
        pytest.skip("EURUSD: too few bars")
    rt = StrategyRuntime("EURUSD")
    rt.warmup(bars_15m)
    if not rt._warmed:
        pytest.skip("EURUSD: warmup failed")
    # Advance a few bars
    for i in range(rt._next_idx, min(rt._next_idx + 50, len(bars_15m))):
        rt.on_bar(bars_15m[i])

    state = rt.to_state()
    rt2 = StrategyRuntime("EURUSD")
    rt2.from_state(state)

    assert rt2.symbol == rt.symbol
    assert rt2.atr_val == pytest.approx(rt.atr_val)
    assert rt2._next_idx == rt._next_idx
    assert rt2._start_idx == rt._start_idx
    assert rt2._warmed == rt._warmed
    assert rt2.trade_counter == rt.trade_counter
    assert rt2.session.cbdr.body_high == rt.session.cbdr.body_high
    assert rt2.session.cbdr.body_low == rt.session.cbdr.body_low
    assert rt2.session.cbdr.locked == rt.session.cbdr.locked
    assert rt2.session.cbdr.daily_bias == rt.session.cbdr.daily_bias
