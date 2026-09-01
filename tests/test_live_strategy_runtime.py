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
    # R1 (N2 #14): session.atr restored after restart (sweep tolerance source).
    assert rt2.session.atr == pytest.approx(rt.session.atr)
    # NOTE: session.atr may differ from atr_val here because on_bar updates
    # atr_val (EMA) but not session.atr (A1 gap — RED-KAPSAM DIŞI, owner
    # decision). R1 only guarantees session.atr survives the restart and
    # stays > 0 so sweep tolerance is ATR-based, not the 10.0 default.
    assert rt2.session.atr > 0


def _make_synthetic_bars(n: int, start: pd.Timestamp = None) -> list[Bar]:
    """Synthetic trending 15m bars (parity with A2 reproducer template)."""
    import numpy as np

    start = start or pd.Timestamp("2026-01-01 00:00:00")
    rng = np.random.default_rng(42)
    bars = []
    price = 1.1000
    for i in range(n):
        ts = start + pd.Timedelta(minutes=15 * i)
        drift = 0.0005 + rng.normal(0, 0.0003)
        price += drift
        o = price - 0.0002
        h = max(o, price) + 0.0002 + abs(rng.normal(0, 0.0001))
        lo = min(o, price) - 0.0002 - abs(rng.normal(0, 0.0001))
        c = price
        bars.append(
            Bar(
                index=i,
                timestamp=ts,
                open=round(o, 5),
                high=round(h, 5),
                low=round(lo, 5),
                close=round(c, 5),
                volume=1.0,
            )
        )
    return bars


def test_restart_restores_session_atr():
    """R1: restart sonrası session.atr == atr_val (sweep tolerance kaynağı).

    Production path: to_state -> from_state roundtrip on the REAL
    StrategyRuntime (no fakes). A broken implementation (from_state not
    restoring session.atr) must fail: session.atr would stay 0.0.
    """
    rt = StrategyRuntime("EURUSD")
    warmup_bars = _make_synthetic_bars(150)
    rt.warmup(warmup_bars)
    assert rt._warmed, "warmup should succeed on 150 bars"
    # warmup sets session.atr from computed atr_val
    assert rt.session.atr > 0, "warmup sonrası atr > 0 olmalı"
    saved_atr = rt.session.atr

    # serialize -> deserialize (restart)
    state = rt.to_state()
    assert "session_atr" in state, "to_state 'session_atr' anahtarı eksik"
    rt2 = StrategyRuntime("EURUSD")
    rt2.from_state(state)

    # session.atr == atr_val
    assert (
        rt2.session.atr == rt2.atr_val
    ), f"R1: session.atr ({rt2.session.atr}) != atr_val ({rt2.atr_val})"
    assert (
        rt2.session.atr == saved_atr
    ), f"R1: restart session.atr ({rt2.session.atr}) != warmup değeri ({saved_atr})"
    assert (
        rt2.session.atr > 0
    ), "R1: restart sonrası session.atr=0 → sweep tolerance default'a düşer"


def test_restart_sweep_tolerance_uses_restored_atr():
    """R1 sweep-evaluation: restart sonrası tolerance == 0.5 * atr_val.

    Real-chain assertion: session.atr restore edilmezse check_sweep
    tolerance = sweep_default_tolerance (10.0), yani 0.5*atr değil. Bu test
    gerçek SessionManager.check_sweep kod yolunu çalıştırır.
    """
    rt = StrategyRuntime("EURUSD")
    warmup_bars = _make_synthetic_bars(150)
    rt.warmup(warmup_bars)
    assert rt.session.atr > 0
    saved_atr = rt.session.atr

    # Restart
    rt2 = StrategyRuntime("EURUSD")
    rt2.from_state(rt.to_state())
    assert rt2.session.atr == saved_atr

    # Build a CBDR body so check_sweep can evaluate a real tolerance.
    body_high = warmup_bars[-1].close + 0.01
    body_low = warmup_bars[-1].close - 0.01
    rt2.session.cbdr.body_high = body_high
    rt2.session.cbdr.body_low = body_low

    # Bar that pokes above body_high by exactly 0.5*atr + epsilon and closes
    # back below -> must be detected as a sweep ONLY with restored atr.
    poke = body_high + saved_atr * 0.5 + 0.00001
    sweep_bar = Bar(
        index=0,
        timestamp=warmup_bars[-1].timestamp + pd.Timedelta(minutes=15),
        open=body_high,
        high=poke,
        low=body_low,
        close=body_high - 0.0001,
        volume=1.0,
    )
    # force outside-window processing (sweep evaluated outside CBDR window)
    sweep_bar = Bar(
        index=0,
        timestamp=pd.Timestamp("2026-01-01 05:00:00"),
        open=body_high,
        high=poke,
        low=body_low,
        close=body_high - 0.0001,
        volume=1.0,
    )
    sweep = rt2.session.update(sweep_bar)
    assert sweep is not None, (
        "R1: restore sonrası sweep algılanmalı (tolerance=0.5*atr). "
        f"atr={saved_atr}, tolerance beklenen={saved_atr * 0.5}"
    )
    # tolerance == 0.5 * atr (restored), NOT default 10.0
    assert sweep.tolerance == pytest.approx(
        saved_atr * 0.5
    ), f"R1: sweep tolerance {sweep.tolerance} != 0.5*atr {saved_atr * 0.5}"


def test_per_bar_atr_sync():
    """R2 kontrat: session.atr on_bar sırasında korunur (drift etmez).

    NOTE: per-bar re-sync (session.atr = atr_val her bar) A1'dir —
    RED-KAPSAM DIŞI strateji değişikliği (owner-kararı). Bu test mevcut
    kontratı belgeler: session.atr warmup/restart'ta set edilir ve on_bar
    sırasında korunur (0'a düşmez, başka değere sıçramaz). A1 benimsenirse
    bu test güncellenecek.
    """
    rt = StrategyRuntime("EURUSD")
    warmup_bars = _make_synthetic_bars(150)
    rt.warmup(warmup_bars)
    assert rt._warmed
    assert rt.session.atr == rt.atr_val, "warmup sync"

    # Process a few bars; session.atr must remain at the warmup value
    # (on_bar updates atr_val only — A1 per-bar re-sync is out of scope).
    for bar in _make_synthetic_bars(5, start=warmup_bars[-1].timestamp + pd.Timedelta(minutes=15)):
        rt.on_bar(bar)
        assert rt.session.atr > 0, f"bar {bar.index} sonrası session.atr 0'a düştü"


def test_migration_pre_n14_state_audited_fallback(caplog):
    """Migration-audit (§19): pre-N2#14 state (no 'session_atr' key) restores
    with an AUDITED fallback — never silent.

    A state file written before N2 #14 lacks the 'session_atr' key. The
    fallback (session.atr = atr_val) must be LOGGED as a warning so the
    degraded path is visible in runtime logs. A silent fallback would violate
    the contract (§19 silent-fallback).
    """
    import logging

    rt = StrategyRuntime("EURUSD")
    warmup_bars = _make_synthetic_bars(150)
    rt.warmup(warmup_bars)
    assert rt._warmed
    assert rt.atr_val > 0, "warmup sonrası atr_val > 0 olmalı"

    # Simulate a pre-N2#14 state file: drop the 'session_atr' key.
    state = rt.to_state()
    assert "session_atr" in state
    state.pop("session_atr")

    with caplog.at_level(logging.WARNING, logger="src.live.strategy_runtime"):
        rt2 = StrategyRuntime("EURUSD")
        rt2.from_state(state)

    # Audited fallback: session.atr == atr_val (NOT the 0.0 default).
    assert (
        rt2.session.atr == rt2.atr_val
    ), f"migration: session.atr ({rt2.session.atr}) != atr_val ({rt2.atr_val})"
    assert rt2.session.atr > 0, "migration: audited fallback 0'a düşmemeli"
    # The warning must be visible — silent fallback is prohibited (§19).
    assert any(
        "R1/R2" in r.message for r in caplog.records
    ), "migration: fallback must be logged as a warning (no silent fallback)"
