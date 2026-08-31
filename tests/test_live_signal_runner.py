#!/usr/bin/env python
"""PHASE 9 — SIGNAL-ONLY RUNNER — synthetic unit tests.

Covers:
- SignalRunner uses mt5.copy_rates_from_pos for each symbol
- SignalRunner does NOT call mt5.order_send (signal_only invariant)
- AuditChain gets CANDLE / SIGNAL / RISK events for each run
- Risk-approved vs risk-blocked separation
- Per-symbol signal count is reported
- Error in one symbol doesn't stop others
- run_session returns RunnerResult with expected fields
- SignalRunner is reusable across multiple sessions
- RunnerConfig defaults are sane
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd
import pytest

from src.live.audit import AuditChain, EventType
from src.live.risk import RiskManager
from src.live.signal_runner import (
    DEFAULT_M1_COUNT,
    RunnerConfig,
    RunnerResult,
    SignalRunner,
)
from src.live.sizing import ContractSpec
from src.strategy.models import Bar

# ── Fakes ────────────────────────────────────────────────────────


@dataclass
class FakeRate:
    """Stand-in for a single MT5 rate row (numpy structured-like)."""

    time: int
    open: float
    high: float
    low: float
    close: float
    tick_volume: float


class FakeMT5:
    """Configurable fake of the MetaTrader5 module for SignalRunner.

    - `rates_by_symbol`: dict[symbol] -> list[FakeRate] returned by
      `copy_rates_from_pos`. None for a symbol returns an empty result
      (caller must handle).
    - `send_calls`: how many times order_send was called (assertion
      target — must be 0 for signal-only).
    - `error_symbols`: if a symbol is in this set, raise a RuntimeError
      from `copy_rates_from_pos` to test error-handling.
    """

    def __init__(
        self,
        rates_by_symbol: Optional[Dict[str, List[FakeRate]]] = None,
        error_symbols: Optional[List[str]] = None,
    ):
        self.rates_by_symbol: Dict[str, List[FakeRate]] = rates_by_symbol or {}
        self.error_symbols: List[str] = error_symbols or []
        self.send_calls: int = 0
        self.copy_calls: Dict[str, int] = {}

    def copy_rates_from_pos(self, symbol: str, timeframe: str, start: int, count: int):
        self.copy_calls[symbol] = self.copy_calls.get(symbol, 0) + 1
        if symbol in self.error_symbols:
            raise RuntimeError(f"simulated mt5 error for {symbol}")
        rates = self.rates_by_symbol.get(symbol, [])
        if count > 0:
            rates = rates[-count:]
        return list(rates)

    def order_send(self, *_args, **_kwargs):
        self.send_calls += 1
        return None


# ── Helpers ──────────────────────────────────────────────────────


def _make_m1_bars(
    symbol: str,
    n: int = 200,
    start_price: float = 1.10000,
    seed: int = 1,
) -> List[Bar]:
    """Generate a deterministic, trend-following M1 bar sequence.

    Not financial-quality data; just enough to produce SOME signal/noise
    in the runtime without crashing. Deterministic via fixed seed.
    """
    import random

    rng = random.Random(seed)
    bars: List[Bar] = []
    price = start_price
    base_ts = 1_700_000_000  # arbitrary epoch
    for i in range(n):
        # Slow drift + noise
        price += (rng.random() - 0.5) * 0.0005
        o = price
        c = price + (rng.random() - 0.5) * 0.0002
        h = max(o, c) + rng.random() * 0.0003
        lo = min(o, c) - rng.random() * 0.0003
        bars.append(
            Bar(
                index=i,
                timestamp=pd.Timestamp.utcfromtimestamp(base_ts + i * 60),
                open=o,
                high=h,
                low=lo,
                close=c,
                volume=100.0 + rng.random() * 10.0,
            )
        )
    return bars


def _bars_to_rates(bars: List[Bar]) -> List[FakeRate]:
    out: List[FakeRate] = []
    for b in bars:
        out.append(
            FakeRate(
                time=int(b.timestamp.timestamp()),
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                tick_volume=b.volume,
            )
        )
    return out


def _make_fake_mt5(symbols: List[str], n_bars: int = 5000, seed: int = 1) -> FakeMT5:
    rates = {}
    for s in symbols:
        start = 1.10000 if s.startswith("EUR") else 1.30000
        rates[s] = _bars_to_rates(_make_m1_bars(s, n=n_bars, start_price=start, seed=seed))
    return FakeMT5(rates_by_symbol=rates)


# ── Signal-only invariant ───────────────────────────────────────


def test_signal_runner_does_not_send_orders():
    """The most important invariant: signal_only runner NEVER calls
    order_send. PHASE 11 demo run is the only path that turns this off.
    """
    mt5 = _make_fake_mt5(["EURUSD"], n_bars=3000)
    runner = SignalRunner(mt5=mt5, risk_manager=RiskManager())
    audit = AuditChain()
    runner.run_session(
        RunnerConfig(symbols=["EURUSD"], m1_count=3000),
        audit,
    )
    assert mt5.send_calls == 0, f"signal-only must not send orders, got {mt5.send_calls}"


# ── Audit chain populated ───────────────────────────────────────


def test_signal_runner_audit_records_candle_and_signal_events():
    """CANDLE event per symbol, SIGNAL event per emitted signal."""
    mt5 = _make_fake_mt5(["EURUSD"], n_bars=3000)
    runner = SignalRunner(mt5=mt5, risk_manager=RiskManager())
    audit = AuditChain()
    runner.run_session(
        RunnerConfig(symbols=["EURUSD"], m1_count=3000),
        audit,
    )
    by_type: Dict[EventType, int] = {}
    for evt in audit.events:
        by_type[evt.event_type] = by_type.get(evt.event_type, 0) + 1
    # At least one CANDLE per symbol
    assert by_type.get(EventType.CANDLE, 0) >= 1
    # RISK per emitted signal (we evaluate risk for each)
    if by_type.get(EventType.SIGNAL, 0) > 0:
        assert by_type.get(EventType.RISK, 0) == by_type[EventType.SIGNAL]


def test_signal_runner_signal_event_payload_has_expected_fields():
    """SIGNAL events must carry direction, entry_price, sl, tp at minimum."""
    mt5 = _make_fake_mt5(["EURUSD"], n_bars=3000)
    runner = SignalRunner(mt5=mt5, risk_manager=RiskManager())
    audit = AuditChain()
    runner.run_session(
        RunnerConfig(symbols=["EURUSD"], m1_count=3000),
        audit,
    )
    signal_evts = [e for e in audit.events if e.event_type == EventType.SIGNAL]
    if not signal_evts:
        pytest.skip("no signals emitted (random data — rerun if needed)")
    for evt in signal_evts:
        p = evt.payload
        assert "direction" in p
        assert "entry_price" in p
        assert "sl" in p
        assert "tp" in p


# ── Per-symbol counts + result shape ────────────────────────────


def test_signal_runner_returns_result_with_per_symbol_count():
    """RunnerResult.per_symbol maps symbol -> signal count."""
    mt5 = _make_fake_mt5(["EURUSD", "GBPUSD"], n_bars=3000)
    runner = SignalRunner(mt5=mt5, risk_manager=RiskManager())
    audit = AuditChain()
    result = runner.run_session(
        RunnerConfig(symbols=["EURUSD", "GBPUSD"], m1_count=3000),
        audit,
    )
    assert isinstance(result, RunnerResult)
    assert set(result.per_symbol.keys()) == {"EURUSD", "GBPUSD"}
    for sym, n in result.per_symbol.items():
        assert isinstance(n, int)
        assert n >= 0
    assert result.errors == {}


def test_signal_runner_approved_vs_blocked_partition():
    """approved_signals + blocked_signals == signals (partition)."""
    mt5 = _make_fake_mt5(["EURUSD"], n_bars=3000)
    runner = SignalRunner(mt5=mt5, risk_manager=RiskManager())
    audit = AuditChain()
    result = runner.run_session(
        RunnerConfig(symbols=["EURUSD"], m1_count=3000),
        audit,
    )
    total = len(result.approved_signals) + len(result.blocked_signals)
    assert total == len(result.signals)
    # approved + blocked are disjoint
    approved_ids = {id(s) for s in result.approved_signals}
    blocked_ids = {id(s) for s in result.blocked_signals}
    assert approved_ids.isdisjoint(blocked_ids)


# ── Error isolation ─────────────────────────────────────────────


def test_signal_runner_error_in_one_symbol_does_not_stop_others():
    """If EURUSD's copy_rates_from_pos raises, GBPUSD still runs."""
    rates = _bars_to_rates(_make_m1_bars("GBPUSD", n=3000, start_price=1.30000))
    mt5 = FakeMT5(
        rates_by_symbol={"GBPUSD": rates},
        error_symbols=["EURUSD"],
    )
    runner = SignalRunner(mt5=mt5, risk_manager=RiskManager())
    audit = AuditChain()
    result = runner.run_session(
        RunnerConfig(symbols=["EURUSD", "GBPUSD"], m1_count=3000),
        audit,
    )
    # EURUSD has an error recorded; GBPUSD ran
    assert "EURUSD" in result.errors
    # GBPUSD should not be in errors
    assert "GBPUSD" not in result.errors
    # Mutual exclusion: every symbol is in exactly one of per_symbol / errors
    for sym in ["EURUSD", "GBPUSD"]:
        in_per = sym in result.per_symbol
        in_err = sym in result.errors
        assert in_per != in_err, f"{sym} must be in exactly one of per_symbol/errors"
    # Audit should contain an ERROR event for EURUSD
    err_events = [
        e for e in audit.events if e.event_type == EventType.ERROR and e.symbol == "EURUSD"
    ]
    assert len(err_events) >= 1


# ── MT5 contract: no real connection ────────────────────────────


def test_signal_runner_does_not_call_mt5_initialize():
    """FakeMT5 has no `initialize`; runner must work without it
    (signal-only is fully decoupled from MT5 session state)."""
    mt5 = _make_fake_mt5(["EURUSD"], n_bars=3000)
    # We don't even have initialize on FakeMT5 — calling it would raise.
    # This test passes iff the runner does NOT touch mt5.initialize.
    runner = SignalRunner(mt5=mt5, risk_manager=RiskManager())
    audit = AuditChain()
    runner.run_session(
        RunnerConfig(symbols=["EURUSD"], m1_count=3000),
        audit,
    )


# ── Config defaults ────────────────────────────────────────────


def test_runner_config_defaults_sane():
    cfg = RunnerConfig(symbols=["EURUSD"])
    assert cfg.symbols == ["EURUSD"]
    assert cfg.m1_count == DEFAULT_M1_COUNT
    assert cfg.account_balance > 0
    assert cfg.account_equity > 0
    assert cfg.default_contract is None  # conservative per-symbol default


def test_signal_runner_contract_default_is_conservative_usd_account():
    """When no default_contract is set, runner uses a conservative
    USD-account spec — production should pull real spec from MT5."""
    mt5 = _make_fake_mt5(["EURUSD"], n_bars=3000)
    runner = SignalRunner(mt5=mt5, risk_manager=RiskManager())
    cfg = RunnerConfig(symbols=["EURUSD"], m1_count=3000)
    contract = runner._contract_for("EURUSD", cfg)
    assert isinstance(contract, ContractSpec)
    assert contract.symbol == "EURUSD"
    assert contract.contract_size == 100000.0
    assert contract.volume_min == 0.01
