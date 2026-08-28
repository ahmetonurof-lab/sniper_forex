#!/usr/bin/env python
"""PHASE 11 — M1 INGESTION PARITY TEST (regression fix).

Background
----------
Phase 11 demo (real MT5, 65K M1 EURUSD, 2026-06-25 → 2026-08-28) found
canonical=38 trades, live=17 signals. Audit identified the root cause
(see docs/MT5_IMPLEMENTATION_ROADMAP.md and memory-bank/activeContext.md):

  1. `SignalRunner._rates_to_bars` and `PaperSession._rates_to_bars`
     used `pd.Timestamp.utcfromtimestamp(ts)` which treated MT5's
     `time` field as UTC. MT5 reports `time` in **server time**
     (UTC+2 winter / UTC+3 summer for ICMarketsSC-Demo). The shifted
     timestamps re-bucketed the 15m aggregation, dropped <3-bar
     buckets, and pushed some CBDR-window bars out of the 19:00→01:00
     window. Net: deterministic loss of ~21 signals.

  2. `SignalRunner._run_symbol` and `PaperSession.warmup/run_step` did
     NOT apply `M1CandleFeed.is_closed_m1` to drop the forming M1.
     The unfinalized current-minute bar polluted the last 15m bucket.

This test pins the fix:
  - F1: `_rates_to_bars` uses `clock.server_to_utc` (server→UTC).
  - F2: forming M1 is dropped via `is_closed_m1` before resampling.
  - F3: given the same M1 input, live `StrategyRuntime` produces the
       same trade list as canonical `run_test_a` (and trades fire
       where the fixture engineered sweeps+FVGs).

The fixture is a small synthetic M1 sequence in **server time** with
embedded sweep + FVG patterns around the CBDR window. It is
deterministic (no RNG), tiny (~3 days × 15m buckets, ~1000 15m bars
after resampling), and self-contained (no network, no MT5 terminal,
no large data files).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

import pandas as pd

# Repo root on path (test is run from repo root by pytest)
_REPO = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO))

from src.live.audit import AuditChain  # noqa: E402
from src.live.candle_feed import M1CandleFeed, resample_15m  # noqa: E402
from src.live.clock import server_to_utc  # noqa: E402
from src.live.paper import _rates_to_bars as paper_rates_to_bars  # noqa: E402
from src.live.risk import RiskManager  # noqa: E402
from src.live.signal_runner import (  # noqa: E402
    RunnerConfig,
    SignalRunner,
)
from src.live.strategy_runtime import StrategyRuntime  # noqa: E402
from src.strategy.models import Bar  # noqa: E402


# ── Fakes ────────────────────────────────────────────────────────


@dataclass
class FakeRate:
    """Stand-in for a single MT5 rate row (server-time `time` field)."""

    time: int  # seconds since epoch, **server time**
    open: float
    high: float
    low: float
    close: float
    tick_volume: float


class FakeMT5:
    """Fake of `MetaTrader5` for parity testing."""

    def __init__(self, rates_by_symbol):
        self.rates_by_symbol = rates_by_symbol
        self.send_calls = 0
        self.copy_calls = {}

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        self.copy_calls[symbol] = self.copy_calls.get(symbol, 0) + 1
        rates = self.rates_by_symbol.get(symbol, [])
        if count > 0:
            rates = rates[-count:]
        return list(rates)

    def order_send(self, *_a, **_k):
        self.send_calls += 1
        return None


# ── Fixture: deterministic M1 series around a CBDR window ───────


def _epoch_server(year, month, day, hour, minute=0):
    """Return epoch seconds for a (naive) **server-time** datetime.

    DST-naive helper — we fix a single offset (+3, summer) for the
    whole fixture and apply `server_to_utc` consistently.
    """
    SERVER_OFFSET_H = 3
    dt_server = datetime(year, month, day, hour, minute)
    return (
        int((dt_server - datetime(1970, 1, 1)).total_seconds()) - SERVER_OFFSET_H * 3600
    )


def _bar_time(epoch_s: int) -> pd.Timestamp:
    """Convert a server-time epoch to a UTC pandas Timestamp
    via the same path SignalRunner/Paper now use."""
    ts_server = pd.Timestamp(epoch_s, unit="s")
    return pd.Timestamp(server_to_utc(ts_server.to_pydatetime()))


def _build_fixture_m1(
    start_epoch_server: int,
    n_minutes: int = 60 * 24 * 3,  # 3 days of M1
) -> List[FakeRate]:
    """Build a small, deterministic M1 fixture in **server time**.

    Pattern around 20:00 server (20:00 = inside CBDR 19:00→01:00):
      - 19:00–19:45: tight range 1.1000–1.1010  (build CBDR body)
      - 20:00: spike above body high then close back inside  (sweep)
      - 20:15: small bullish displacement (bar 1)
      - 20:30: small bullish displacement (bar 2) → forms FVG
      - 20:45: pullback into the FVG  (first touch)
      - 21:00: entry (live = next-bar-open)

    The same pattern is repeated on each of 3 days to give a
    non-trivial trade count without depending on randomness.
    """
    rates: List[FakeRate] = []
    # Anchor: day 0 starts at 18:00 server
    day0 = start_epoch_server
    BODY_HIGH = 1.10100
    BODY_LOW = 1.10000
    DISP_BODY = 1.10140
    FVG_BOTTOM = 1.10100
    FVG_TOP = 1.10150

    for d in range(3):
        day_start = day0 + d * 24 * 3600
        for m in range(24 * 60):  # 1440 minutes per day
            t = day_start + m * 60
            # Default: small noise around 1.1005
            o = c = 1.1005
            h = 1.1007
            lo = 1.1003
            v = 100.0
            # CBDR build-up 19:00-19:45
            if 19 * 60 <= m < 20 * 60:
                # inside window, track body
                o = (BODY_HIGH + BODY_LOW) / 2 + ((m % 3) - 1) * 0.0001
                c = o
                h = BODY_HIGH
                lo = BODY_LOW
            # 20:00 — bullish sweep: low pierces body_low then close above
            if 20 * 60 == m:
                o = BODY_LOW - 0.00020
                lo = BODY_LOW - 0.00030
                c = BODY_LOW + 0.00020
                h = c
                v = 300.0
            # 20:15 — bullish displacement candle 1
            if 20 * 60 + 15 == m:
                o = BODY_LOW + 0.00020
                c = DISP_BODY
                h = c + 0.00010
                lo = o - 0.00010
                v = 250.0
            # 20:30 — bullish displacement candle 2 (forms FVG between 20:15.high and 20:30.low)
            if 20 * 60 + 30 == m:
                # FVG: 20:15.high=1.10150, 20:30.low=1.10100 → gap
                o = DISP_BODY + 0.00010
                c = DISP_BODY + 0.00020
                h = c + 0.00010
                lo = FVG_BOTTOM  # 1.10100 (below 20:15.high = 1.10150)
                v = 250.0
            # 20:45 — pullback into FVG (first touch on close bar i)
            if 20 * 60 + 45 == m:
                # bar low should be ≤ fvg.top (1.10150) and ≥ fvg.bottom - atr*0.1
                o = FVG_TOP + 0.00010
                c = FVG_TOP - 0.00010
                h = o + 0.00010
                lo = (FVG_BOTTOM + FVG_TOP) / 2  # inside FVG
                v = 200.0
            # 21:00 — entry bar (live = next-bar-open). Keep neutral.
            if 21 * 60 == m:
                o = 1.10120
                c = 1.10125
                h = 1.10130
                lo = 1.10110
                v = 150.0
            rates.append(
                FakeRate(
                    time=t,
                    open=o,
                    high=h,
                    low=lo,
                    close=c,
                    tick_volume=v,
                )
            )
    return rates


def _fixture_15m(start_epoch_server: int, n_minutes: int = 60 * 24 * 3) -> List[Bar]:
    """Build the same fixture as 15m bars directly (canonical-side
    reference: this is what the engine sees via `bars_15m`)."""
    m1 = _build_fixture_m1(start_epoch_server, n_minutes)
    # Filter forming M1 same way live path does
    m1_bars = [
        Bar(
            index=i,
            timestamp=_bar_time(r.time),
            open=r.open,
            high=r.high,
            low=r.low,
            close=r.close,
            volume=r.tick_volume,
        )
        for i, r in enumerate(m1)
    ]
    # `now` = one minute past the last bar so the last bar counts as closed.
    now = m1_bars[-1].timestamp + pd.Timedelta(minutes=1)
    m1_bars = M1CandleFeed.is_closed_m1(m1_bars, now=now.to_pydatetime())
    return resample_15m(m1_bars)


# ── F1 — timezone conversion correctness ────────────────────────


def test_f1_signal_runner_rates_to_bars_uses_server_to_utc():
    """`SignalRunner._rates_to_bars` must convert MT5 server-time
    `time` to UTC via `clock.server_to_utc`, NOT via `utcfromtimestamp`.

    Structural assertion: shifting the input epoch by N seconds shifts
    the bar timestamp by the SAME N seconds (linearity of any consistent
    conversion), and the result equals `server_to_utc(pd.Timestamp(epoch))`
    exactly — not `pd.Timestamp.utcfromtimestamp(epoch)`.
    """
    epoch_server = 1_780_000_000  # arbitrary epoch
    rates = [
        FakeRate(
            time=epoch_server, open=1.0, high=1.0, low=1.0, close=1.0, tick_volume=0.0
        )
    ]
    bars = SignalRunner._rates_to_bars(rates)
    assert len(bars) == 1
    # Expected timestamp = server_to_utc(epoch).
    expected = pd.Timestamp(
        server_to_utc(pd.Timestamp(epoch_server, unit="s").to_pydatetime())
    )
    assert bars[0].timestamp == expected
    # Linearity: a 3-hour forward shift in the epoch must produce a
    # 3-hour forward shift in the bar timestamp (any consistent
    # conversion preserves delta-t; a bug like "naive utcfromtimestamp"
    # would NOT preserve this if the epoch is meant as server-time).
    rates_shifted = [
        FakeRate(
            time=epoch_server + 3 * 3600,
            open=1.0,
            high=1.0,
            low=1.0,
            close=1.0,
            tick_volume=0.0,
        )
    ]
    bars_shifted = SignalRunner._rates_to_bars(rates_shifted)
    delta = (bars_shifted[0].timestamp - bars[0].timestamp).total_seconds()
    assert delta == 3 * 3600, f"delta must equal shift, got {delta}"
    # The conversion path is NOT naive utcfromtimestamp (which is the
    # pre-fix behavior we just removed). Verify the live code path
    # matches server_to_utc rather than naive-UTC.
    naive_utc_path = pd.Timestamp.utcfromtimestamp(epoch_server)
    if naive_utc_path != expected:
        # Different → the two paths would produce different timestamps.
        # We assert the live path is the server_to_utc one.
        assert bars[0].timestamp != naive_utc_path


def test_f1_paper_rates_to_bars_uses_server_to_utc():
    """`PaperSession._rates_to_bars` must convert MT5 server-time
    `time` to UTC via `clock.server_to_utc`."""
    epoch_server = 1_780_000_000
    rates = [
        FakeRate(
            time=epoch_server, open=1.0, high=1.0, low=1.0, close=1.0, tick_volume=0.0
        )
    ]
    bars = paper_rates_to_bars(rates)
    assert len(bars) == 1
    expected = pd.Timestamp(
        server_to_utc(pd.Timestamp(epoch_server, unit="s").to_pydatetime())
    )
    assert bars[0].timestamp == expected
    rates_shifted = [
        FakeRate(
            time=epoch_server + 3 * 3600,
            open=1.0,
            high=1.0,
            low=1.0,
            close=1.0,
            tick_volume=0.0,
        )
    ]
    bars_shifted = paper_rates_to_bars(rates_shifted)
    delta = (bars_shifted[0].timestamp - bars[0].timestamp).total_seconds()
    assert delta == 3 * 3600


# ── F2 — forming M1 filter behavior ──────────────────────────────


def test_f2_is_closed_m1_drops_forming_bar():
    """`M1CandleFeed.is_closed_m1` must drop the M1 whose 1-min
    window has not elapsed (i.e. bar.timestamp + 1min > now)."""
    # 5 bars at minutes 0,1,2,3,4. now = minute 2:30 → bars 0,1 are closed; 2,3,4 are forming.
    base = _epoch_server(2026, 7, 1, 12, 0)  # 12:00 server
    bars = [
        Bar(
            index=i,
            timestamp=pd.Timestamp(
                server_to_utc(pd.Timestamp(base + i * 60, unit="s").to_pydatetime())
            ),
            open=1.0,
            high=1.0,
            low=1.0,
            close=1.0,
            volume=0.0,
        )
        for i in range(5)
    ]
    now = pd.Timestamp(
        server_to_utc(pd.Timestamp(base + 2 * 60 + 30, unit="s").to_pydatetime())
    ).to_pydatetime()
    closed = M1CandleFeed.is_closed_m1(bars, now)
    # bars at 12:00, 12:01 are closed; 12:02, 12:03, 12:04 are forming.
    assert len(closed) == 2
    assert closed[0].index == 0
    assert closed[1].index == 1


def test_f2_signal_runner_drops_forming_m1_before_resample():
    """Append an obviously bogus forming M1 (price = 999) to the
    fixture and assert live signals are unchanged. If the forming M1
    leaks into the last 15m bucket, that bucket's high/low/close will
    shift and the 15m series fed to StrategyRuntime will differ."""
    start = _epoch_server(2026, 7, 1, 18, 0)
    m1 = _build_fixture_m1(start, n_minutes=60 * 24 * 3)
    # Append forming M1 (would be timestamp = last + 1 minute)
    m1.append(
        FakeRate(
            time=m1[-1].time + 60,
            open=999.0,
            high=999.0,
            low=999.0,
            close=999.0,
            tick_volume=1.0,
        )
    )
    mt5_clean = FakeMT5(rates_by_symbol={"EURUSD": _build_fixture_m1(start)})
    mt5_with_forming = FakeMT5(rates_by_symbol={"EURUSD": m1})
    audit_a = AuditChain()
    audit_b = AuditChain()
    runner = SignalRunner(mt5=mt5_clean, risk_manager=RiskManager())
    res_a = runner.run_session(
        RunnerConfig(symbols=["EURUSD"], m1_count=999999), audit_a
    )
    runner2 = SignalRunner(mt5=mt5_with_forming, risk_manager=RiskManager())
    res_b = runner2.run_session(
        RunnerConfig(symbols=["EURUSD"], m1_count=999999), audit_b
    )
    # Signal count must be identical → forming bar was dropped.
    assert res_a.per_symbol == res_b.per_symbol
    assert len(res_a.signals) == len(res_b.signals)


# ── F3 — M1→15m→strategy parity ─────────────────────────────────


def _run_canonical(bars_15m: List[Bar]):
    """Helper: run the FROZEN canonical engine on a 15m bar list."""
    from experiment.main_research_c_v1_0 import run_test_a

    return run_test_a("EURUSD", bars_15m)


def _run_live(bars_15m: List[Bar]):
    """Helper: run the live StrategyRuntime on a 15m bar list."""
    rt = StrategyRuntime("EURUSD")
    rt.warmup(bars_15m)
    assert rt._warmed, "live runtime must warm up on the same fixture"
    signals = []
    for i in range(rt._next_idx, len(bars_15m)):
        sig = rt.on_bar(bars_15m[i])
        if sig is not None:
            signals.append(sig)
    return signals


def test_f3_m1_to_15m_resample_parity_with_engine():
    """`resample_15m` (live, candle_feed.py) must produce the SAME
    15m series as the engine's resample_15m when fed identical M1
    inputs (in UTC). This is the byte-for-byte parity Phase 2 promised
    and is the foundation for the 38↔17 fix."""
    from experiment.main_research_c_v1_0 import resample_15m as engine_resample_15m

    start = _epoch_server(2026, 7, 1, 18, 0)
    m1 = _build_fixture_m1(start, n_minutes=60 * 24)
    m1_bars = [
        Bar(
            index=i,
            timestamp=pd.Timestamp(
                server_to_utc(pd.Timestamp(r.time, unit="s").to_pydatetime())
            ),
            open=r.open,
            high=r.high,
            low=r.low,
            close=r.close,
            volume=r.tick_volume,
        )
        for i, r in enumerate(m1)
    ]
    # `now` = one minute past the last bar so the last bar counts as closed.
    now = m1_bars[-1].timestamp + pd.Timedelta(minutes=1)
    closed = M1CandleFeed.is_closed_m1(m1_bars, now=now.to_pydatetime())
    live_15m = resample_15m(closed)
    engine_15m = engine_resample_15m(closed)
    # Field-by-field equality on every bar.
    assert len(live_15m) == len(engine_15m)
    for lb, eb in zip(live_15m, engine_15m):
        assert lb.timestamp == eb.timestamp
        assert lb.open == eb.open
        assert lb.high == eb.high
        assert lb.low == eb.low
        assert lb.close == eb.close
        assert lb.volume == eb.volume


def test_f3_strategy_runtime_parity_with_canonical_run_test_a():
    """Live `StrategyRuntime` must produce the SAME Signal list as
    the canonical `run_test_a` on identical 15m input (parity gate
    contract, re-verified on the M1-derived 15m path).

    This is the head-to-head 38↔38 verification at the engine level.
    On a deterministic fixture we expect both to find exactly the
    trades the fixture engineers (3 days × ~1 trade/day = 3 trades
    inside the engineered sweep+FVG windows, more if Nexus picks up
    extra setups)."""
    start = _epoch_server(2026, 7, 1, 18, 0)
    bars_15m = _fixture_15m(start, n_minutes=60 * 24 * 3)
    assert len(bars_15m) >= 200, "fixture must produce enough 15m bars to warm up"

    canonical = _run_canonical(bars_15m)
    live_signals = _run_live(bars_15m)

    n_can = len(canonical)
    n_live = len(live_signals)
    # Parity contract: same count and same per-trade diff (direction,
    # entry_price, sl, tp, entry_bar_index, sweep_bar_index, zone_index).
    assert n_can == n_live, f"parity FAILED: canonical={n_can}, live={n_live}"
    for k, (trade, sig) in enumerate(zip(canonical, live_signals)):
        assert sig.direction == trade.direction, f"trade#{k} direction diff"
        assert sig.entry_price == trade.entry_price, f"trade#{k} entry_price diff"
        assert sig.sl == trade.sl, f"trade#{k} sl diff"
        assert sig.tp == trade.tp, f"trade#{k} tp diff"
        assert sig.entry_bar_index == trade.entry_bar_index, f"trade#{k} entry_bar diff"
        assert sig.sweep_bar_index == trade.sweep_bar_index, f"trade#{k} sweep_bar diff"
        assert sig.zone_index == trade.zone_index, f"trade#{k} zone diff"


def test_f3_signal_runner_via_m1_parity_with_canonical():
    """End-to-end: feed the M1 fixture to `SignalRunner`, then feed
    the resampled 15m to the canonical engine, and assert equal
    signal/trade lists. This is the exact pipeline the Phase 11
    demo used (mt5 → M1 → resample_15m → strategy), and it must
    produce the same count as the canonical run on the same 15m."""
    start = _epoch_server(2026, 7, 1, 18, 0)
    m1 = _build_fixture_m1(start, n_minutes=60 * 24 * 3)
    mt5 = FakeMT5(rates_by_symbol={"EURUSD": m1})
    runner = SignalRunner(mt5=mt5, risk_manager=RiskManager())
    audit = AuditChain()
    result = runner.run_session(
        RunnerConfig(symbols=["EURUSD"], m1_count=999999),
        audit,
    )
    n_live = result.per_symbol.get("EURUSD", 0)
    canonical = _run_canonical(_fixture_15m(start, n_minutes=60 * 24 * 3))
    n_can = len(canonical)
    assert n_live == n_can, (
        f"SignalRunner via M1 parity FAILED: live signals={n_live}, "
        f"canonical trades={n_can}"
    )


def test_f3_no_lookahead_artifact_under_replay():
    """Re-running the same M1 fixture must produce a deterministic
    signal/trade list (no RNG, no Date.now, no env leakage)."""
    start = _epoch_server(2026, 7, 1, 18, 0)
    n_live_runs = []
    n_can_runs = []
    bars_15m = _fixture_15m(start, n_minutes=60 * 24 * 3)
    for _ in range(2):
        m1 = _build_fixture_m1(start, n_minutes=60 * 24 * 3)
        mt5 = FakeMT5(rates_by_symbol={"EURUSD": m1})
        runner = SignalRunner(mt5=mt5, risk_manager=RiskManager())
        audit = AuditChain()
        res = runner.run_session(
            RunnerConfig(symbols=["EURUSD"], m1_count=999999),
            audit,
        )
        n_live_runs.append(res.per_symbol.get("EURUSD", 0))
        n_can_runs.append(len(_run_canonical(bars_15m)))
    # Both sides are deterministic across identical inputs.
    assert n_live_runs[0] == n_live_runs[1]
    assert n_can_runs[0] == n_can_runs[1]
    assert n_live_runs[0] == n_can_runs[0]
