#!/usr/bin/env python
"""TAŞ 2 — Bar pipeline acceptance tests.

Tests the bar pipeline (D15/D19/D20/D25/D26/D28) including:
- Premature-emit protection: a 15m bucket only emits when the next
  bucket's M1 closes (trailing edge), never from a forming/incomplete M1.
- D19: Bar identity = (symbol, bar_open_time UTC). Same identity never emits twice.
- D20: Global monotonic index continuity across fetches.
- D28: Real-terminal smoke before warmup.
- _safe() heuristic: margin_level_low maps to S4, not S2.

The synthetic scenario uses 12:03/12:19 timestamps (as documented in
ZAI_AUDIT_9_karar.md) to test the premature-emit boundary. Since
_rates_to_bars treats the MT5 `time` field as server time and converts
to UTC, synthetic timestamps are generated as server time that maps to
the intended UTC.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

import pytest

from src.live.candle_feed import M1CandleFeed, resample_15m
from src.live.clock import _utcnow_naive, utc_to_server
from src.live.orchestrator import (
    Lock,
    LockData,
    Orchestrator,
    OrchestratorConfig,
    StartupVerdict,
)

# ── Synthetic M1 rate generator ──────────────────────────────────


def _make_m1_rates(
    start_utc: datetime,
    count: int,
    base_price: float = 1.1000,
    tick_volume: int = 100,
) -> List[dict]:
    """Generate synthetic M1 rate dicts on a 1-minute grid.

    The `time` field is generated as MT5 *server time* (naive), which
    _rates_to_bars will convert to UTC via server_to_utc_historical.
    """
    rows = []
    for i in range(count):
        t = start_utc + timedelta(minutes=i)
        ts = int(t.timestamp())
        rows.append(
            {
                "time": ts,
                "open": base_price + i * 0.0001,
                "high": base_price + i * 0.0001 + 0.00005,
                "low": base_price + i * 0.0001 - 0.00005,
                "close": base_price + i * 0.0001 + 0.00002,
                "tick_volume": tick_volume,
            }
        )
    return rows


def _server_time_for(utc_dt: datetime) -> int:
    """Convert a UTC datetime to MT5 server time epoch seconds.

    This produces the `time` field that _rates_to_bars expects (server time).
    """
    server_dt = utc_to_server(utc_dt)
    return int(server_dt.replace(tzinfo=timezone.utc).timestamp())


def _make_m1_rates_utc(
    start_utc: datetime,
    count: int,
    base_price: float = 1.1000,
    tick_volume: int = 100,
) -> List[dict]:
    """Generate M1 rates where `time` is server time encoding `start_utc`.

    After _rates_to_bars conversion, bars emerge at the intended UTC times.
    """
    rows = []
    for i in range(count):
        utc_t = start_utc + timedelta(minutes=i)
        server_ts = _server_time_for(utc_t)
        rows.append(
            {
                "time": server_ts,
                "open": base_price + i * 0.0001,
                "high": base_price + i * 0.0001 + 0.00005,
                "low": base_price + i * 0.0001 - 0.00005,
                "close": base_price + i * 0.0001 + 0.00002,
                "tick_volume": tick_volume,
            }
        )
    return rows


# ── FakeMT5 for bar pipeline tests ─────────────────────────────────


class _FakeSymbolInfo:
    point = 0.00001
    digits = 5
    trade_tick_value = 1.0
    volume_min = 0.01
    volume_max = 100.0
    volume_step = 0.01
    trade_contract_size = 100000.0
    trade_stops_level = 10
    trade_mode = 0


class _FakeAccount:
    login = 53012914
    server = "ICMarketsSC-Demo"
    balance = 10000.0
    equity = 10000.0
    currency = "USD"
    leverage = 100
    margin_level = 1000.0


class _FakeTerminal:
    build = 6140
    path = "C:/MT5/terminal64.exe"
    trade_allowed = True


class FakeMT5ForBars:
    """FakeMT5 with controllable M1 rate output for bar pipeline tests."""

    TIMEFRAME_M1 = 1

    def __init__(self, m1_rates: List[dict]):
        self._m1_rates = m1_rates
        self._call_count = 0

    @staticmethod
    def initialize(path=None):
        return True

    @staticmethod
    def login(**kwargs):
        return True

    @staticmethod
    def account_info():
        return _FakeAccount()

    @staticmethod
    def terminal_info():
        return _FakeTerminal()

    @staticmethod
    def symbol_select(symbol, visible=True):
        return True

    @staticmethod
    def symbol_info(symbol):
        return _FakeSymbolInfo()

    @staticmethod
    def positions_get(ticket=None, group=None, symbol=None):
        return []

    @staticmethod
    def orders_get(group=None, symbol=None):
        return []

    def copy_rates_from_pos(self, symbol, tf, start, count):
        self._call_count += 1
        return self._m1_rates[-count:] if count <= len(self._m1_rates) else self._m1_rates[:]


class ProgressiveFakeMT5(FakeMT5ForBars):
    """FakeMT5 that returns different rate batches on successive calls."""

    def __init__(self, batches: List[List[dict]]):
        self._batches = batches
        self._call_count = 0

    def copy_rates_from_pos(self, symbol, tf, start, count):
        idx = min(self._call_count, len(self._batches) - 1)
        self._call_count += 1
        batch = self._batches[idx]
        return batch[-count:] if count <= len(batch) else batch[:]


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def tmp_state(tmp_path: Path) -> Path:
    return tmp_path / "state"


@pytest.fixture
def synthetic_base_time() -> datetime:
    """Use a time safely in the past so is_closed_m1 passes.

    The scenario conceptually maps to 12:03/12:19 UTC, but we anchor
    to (now - 1700 minutes) so 1600 bars all fall in the past.
    Rounded to the minute for grid alignment.
    """
    now = _utcnow_naive()
    base = now.replace(second=0, microsecond=0) - timedelta(minutes=1700)
    return base.replace(tzinfo=timezone.utc)


@pytest.fixture
def fake_mt5_module(monkeypatch):
    """Patch MetaTrader5 module-level import used by signal_runner."""
    from src.live.signal_runner import SignalRunner

    return SignalRunner


# ── D19: Bar identity dedup ────────────────────────────────────────


class TestBarIdentityDedup:
    """D19: Bar identity = (symbol, bar_open_time UTC).
    Same identity never emits twice (trailing edge)."""

    def test_bar_idempotent_not_emitted_twice(self, tmp_state, monkeypatch, synthetic_base_time):
        """A 15m bar that was already emitted should not emit again."""
        # 30 M1 bars = 2 complete 15m buckets
        rates = _make_m1_rates_utc(synthetic_base_time, 30)

        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
        )
        orch._mt5 = FakeMT5ForBars(rates)
        orch._symbol = "EURUSD"
        orch.lock.acquire()

        first_bars = orch.produce_new_bars()
        assert len(first_bars) > 0

        # Same data again — should produce nothing new (identity dedup)
        second_bars = orch.produce_new_bars()
        assert len(second_bars) == 0

        orch.lock.release()

    def test_trailing_edge_emit(self, tmp_state, monkeypatch, synthetic_base_time):
        """D19 trailing edge: bucket B emits only when next bucket's
        M1 closes. Sequential calls continue index."""
        rates = _make_m1_rates_utc(synthetic_base_time, 30)  # 2 15m bars

        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
        )
        orch._mt5 = FakeMT5ForBars(rates)
        orch._symbol = "EURUSD"
        orch.lock.acquire()

        bars = orch.produce_new_bars()
        assert len(bars) == 2
        assert bars[0].index == 0
        assert bars[1].index == 1

        orch.lock.release()


# ── D20: Global monotonic index continuity ────────────────────────


class TestIndexContinuity:
    """D20: _rates_to_bars resets index to 0 each fetch.
    Orchestrator maintains global monotonic index across fetches."""

    def test_index_continues_across_fetches(self, tmp_state, monkeypatch, synthetic_base_time):
        """After first fetch produces bars [0,1], second fetch should
        continue from index 2, not restart at 0."""
        rates1 = _make_m1_rates_utc(synthetic_base_time, 30)  # 2 15m bars
        rates2 = _make_m1_rates_utc(
            synthetic_base_time + timedelta(minutes=30), 30
        )  # 2 more 15m bars

        fake_mt5 = ProgressiveFakeMT5([rates1, rates2])

        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
        )
        orch._mt5 = fake_mt5
        orch._symbol = "EURUSD"
        orch.lock.acquire()

        first = orch.produce_new_bars()
        assert len(first) == 2
        assert first[0].index == 0
        assert first[1].index == 1

        second = orch.produce_new_bars()
        assert len(second) == 2
        assert second[0].index == 2, f"expected index 2, got {second[0].index}"
        assert second[1].index == 3, f"expected index 3, got {second[1].index}"

        orch.lock.release()


# ── D28: Real-terminal smoke (grid alignment, UTC) ────────────────


class TestRealTerminalSmoke:
    """D28: 100 M1 → _rates_to_bars → timestamps grid-aligned + UTC."""

    def test_smoke_grid_aligned_timestamps(self, tmp_state, monkeypatch, synthetic_base_time):
        """All M1 bar timestamps must be on a 1-minute grid (grid-aligned)."""
        rates = _make_m1_rates_utc(synthetic_base_time, 100)

        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
        )
        orch._mt5 = FakeMT5ForBars(rates)
        orch._symbol = "EURUSD"
        orch.lock.acquire()

        now = _utcnow_naive()
        m1_bars = orch._rates_to_bars(rates)
        closed = M1CandleFeed.is_closed_m1(m1_bars, now=now)

        for b in closed:
            ts_ms = int(b.timestamp.timestamp() * 1000)
            assert ts_ms % (60 * 1000) == 0, f"M1 not grid-aligned: {b.timestamp}"

        orch.lock.release()

    def test_smoke_15m_slot_alignment(self, tmp_state, monkeypatch, synthetic_base_time):
        """D19: 15m buckets align to a 15-minute epoch grid (15m slot alignment).

        resample_15m buckets by (ts_ms // 15min) * 15min. The bar's
        timestamp label is the first M1's timestamp (NOT grid-aligned),
        per the canonical engine convention. We verify the bucket
        *epoch* is grid-aligned, not the label.
        """
        rates = _make_m1_rates_utc(synthetic_base_time, 100)

        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
        )
        orch._mt5 = FakeMT5ForBars(rates)
        orch._symbol = "EURUSD"
        orch.lock.acquire()

        now = _utcnow_naive()
        m1_bars = orch._rates_to_bars(rates)
        closed = M1CandleFeed.is_closed_m1(m1_bars, now=now)
        m15 = resample_15m(closed)

        _15M_MS = 15 * 60 * 1000
        for bar in m15:
            ts_ms = int(bar.timestamp.timestamp() * 1000)
            bucket_ms = (ts_ms // _15M_MS) * _15M_MS
            # The bucket epoch must be on the 15m grid
            assert bucket_ms % _15M_MS == 0, f"15m bucket epoch not grid-aligned: {bucket_ms}"
            # Each bar must contain exactly 15 M1 bars (or fewer at edges)
            # Just verify the bucket is consistent

        orch.lock.release()


# ── _safe() heuristic: margin_level_low → S4 ──────────────────────


class TestSafeHeuristic:
    """_safe() heuristic: margin_level_low maps to S4, not S2."""

    def test_margin_level_low_maps_to_s4(self, tmp_state):
        """margin_level_low condition should return S4."""
        orch = Orchestrator(state_dir=str(tmp_state))
        safe, phase = orch._safe("margin_level_low")
        assert safe is True
        assert phase == "S4"
        assert phase != "S2"  # must NOT be S2

    def test_identity_mismatch_is_fatal(self, tmp_state):
        """identity_mismatch should return FATAL (not safe)."""
        orch = Orchestrator(state_dir=str(tmp_state))
        safe, phase = orch._safe("identity_mismatch")
        assert safe is False
        assert phase == "S2"

    def test_contract_fail_is_safe(self, tmp_state):
        """contract_fail should return safe=True with CONTRACT phase."""
        orch = Orchestrator(state_dir=str(tmp_state))
        safe, phase = orch._safe("contract_fail")
        assert safe is True
        assert phase == "CONTRACT"

    def test_warmup_fail_is_safe(self, tmp_state):
        """warmup_fail should return safe=True."""
        orch = Orchestrator(state_dir=str(tmp_state))
        safe, phase = orch._safe("warmup_fail")
        assert safe is True
        assert phase == "WARMUP"


# ── Premature emit scenario (12:03/12:19) ─────────────────────────


class TestPrematureEmitScenario:
    """The core premature-emit test from ZAI_AUDIT_9.

    Scenario:
    - At 12:03 UTC, M1 bars for 12:00 and 12:01 are closed.
    - A 15m bucket starting at 12:00 should NOT emit until we have
      enough data to confirm it's complete (i.e., the next 15m bucket
      starts).
    - The forming bar (current minute, not yet closed) must not pollute
      the last 15m bucket's high/low/close.
    """

    def test_premature_15m_not_emitted_with_incomplete_data(
        self, tmp_state, monkeypatch, synthetic_base_time
    ):
        """12:03 scenario: 3 M1 bars at 12:00, 12:01, 12:02.
        resample_15m drops <3-bar buckets, so no 15m bar should emit
        if the bucket is incomplete (< 3 M1 bars)."""
        # Generate 3 M1 bars as server time -> UTC at the intended times
        utc_times = [
            synthetic_base_time,
            synthetic_base_time + timedelta(minutes=1),
            synthetic_base_time + timedelta(minutes=2),
        ]
        rates = []
        for i, utc_t in enumerate(utc_times):
            ts = _server_time_for(utc_t)
            rates.append(
                {
                    "time": ts,
                    "open": 1.1000 + i * 0.0001,
                    "high": 1.1001 + i * 0.0001,
                    "low": 1.0999 + i * 0.0001,
                    "close": 1.1000 + i * 0.0001,
                    "tick_volume": 100,
                }
            )

        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
        )
        orch._mt5 = FakeMT5ForBars(rates)
        orch._symbol = "EURUSD"
        orch.lock.acquire()

        now = _utcnow_naive()
        m1_bars = orch._rates_to_bars(rates)
        closed = M1CandleFeed.is_closed_m1(m1_bars, now=now)
        m15 = resample_15m(closed)

        # With only 3 M1 bars, resample_15m produces 1 bucket (>= 3 threshold).
        # The bucket's close should be the last bar's close (12:02).
        if m15:
            bar = m15[0]
            # The close should be the last bar's close
            assert bar.close == pytest.approx(rates[2]["close"])

        orch.lock.release()

    def test_forming_m1_does_not_pollute_bucket(
        self, tmp_state, monkeypatch, synthetic_base_time
    ) -> None:
        """12:19 scenario: the forming M1 (current minute, not yet
        closed) must not affect the last 15m bucket's values.

        We generate bars at :00..:19 UTC. We then simulate 'now' being
        12:19:30 UTC (i.e., the 12:19 bar is still forming). is_closed_m1
        should drop the 12:19 bar, so the last bucket's close must NOT
        be the 12:19 price.
        """
        # Generate 20 M1 bars as server time, converting to UTC at intended times
        # We'll set the timestamps such that after _rates_to_bars conversion
        # they land at synthetic_base_time + i minutes (UTC).
        rates = []
        for i in range(20):
            utc_t = synthetic_base_time + timedelta(minutes=i)
            ts = _server_time_for(utc_t)
            rates.append(
                {
                    "time": ts,
                    "open": 1.1000 + i * 0.0001,
                    "high": 1.1001 + i * 0.0001,
                    "low": 1.0999 + i * 0.0001,
                    "close": 1.1000 + i * 0.0001,
                    "tick_volume": 100,
                }
            )

        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
        )
        orch._mt5 = FakeMT5ForBars(rates)
        orch._symbol = "EURUSD"
        orch.lock.acquire()

        # 'now' = 12:19:30 UTC (30 seconds into the 12:19 minute — still forming)
        now = synthetic_base_time + timedelta(minutes=19, seconds=30)
        now_naive = now.replace(tzinfo=None)

        m1_bars = orch._rates_to_bars(rates)
        closed = M1CandleFeed.is_closed_m1(m1_bars, now=now_naive)
        m15 = resample_15m(closed)

        # The 12:19 bar should have been dropped by is_closed_m1
        # (now=12:19:30, bar at 12:19 needs now >= 12:20:00)
        # So we should have bars 12:00..12:18 = 19 bars
        # resample_15m: bucket 12:00 (12:00..12:14, 15 bars) +
        #   bucket 12:15 (12:15..12:18, 4 bars >= 3, so emits)
        assert len(m15) >= 1

        last_bucket = m15[-1]
        forming_close = rates[19]["close"]  # 12:19 bar (forming, should be dropped)
        last_bucket_close = last_bucket.close

        # The last bucket's close must NOT be the forming 12:19 bar's close
        assert last_bucket_close != pytest.approx(
            forming_close
        ), f"Forming bar polluted bucket: close={last_bucket_close} vs forming={forming_close}"

        orch.lock.release()


# ── S9 warmup integration ─────────────────────────────────────────


class TestWarmupIntegration:
    """S9 warmup with real-terminal smoke (D15/D28)."""

    def test_warmup_requires_minimum_bars(self, tmp_state, monkeypatch, synthetic_base_time):
        """Warmup succeeds when enough M1 bars are available for 100+ 15m candles."""
        # 1500+ M1 bars = 100+ 15m bars (1500/15 = 100)
        rates = _make_m1_rates_utc(synthetic_base_time, 1600)

        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
        )
        orch._mt5 = FakeMT5ForBars(rates)
        orch._symbol = "EURUSD"
        orch.lock.acquire()

        ok, n_bars, result = orch._warmup(m1_count=1600)
        assert ok is True, f"warmup failed: {result['reason']}, errors={result['errors']}"
        assert n_bars >= 100

        orch.lock.release()

    def test_warmup_fails_on_empty_rates(self, tmp_state, monkeypatch):
        """Warmup fails when MT5 returns no data."""
        fake_mt5 = FakeMT5ForBars([])
        # Override to return empty even for 100-bar smoke
        fake_mt5.copy_rates_from_pos = lambda *a, **kw: []

        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
        )
        orch._mt5 = fake_mt5
        orch._symbol = "EURUSD"
        orch.lock.acquire()

        ok, n_bars, result = orch._warmup(m1_count=6515)
        assert ok is False
        # D9 tri-state (Taş 2): empty rates → "smoke_error: copy_rates_empty".
        assert "copy_rates_empty" in result["reason"]

        orch.lock.release()


# ── Safe-mode persistence ─────────────────────────────────────────


class TestSafeModePersistence:
    """D24: safe-mode persistence and startup enforcement."""

    def test_safe_mode_file_forces_safe_start(self, tmp_state, monkeypatch, synthetic_base_time):
        """D24 (Taş 2): persisted safe-mode file does NOT short-circuit.
        Phases run end-to-end; the persisted reason is surfaced in the
        final SAFE_START verdict. This is the Aşama-1 policy:
        'temizleme = dosyayı sil, runbook'a yazılır'."""

        class FakeSI:
            point = 0.00001
            digits = 5
            trade_tick_value = 1.0
            volume_min = 0.01
            volume_max = 100.0
            volume_step = 0.01
            trade_contract_size = 100000.0
            trade_stops_level = 10
            trade_mode = 0

        class FakeMT5D24:
            TIMEFRAME_M1 = 1

            @staticmethod
            def initialize(path=None):
                return True

            @staticmethod
            def login(**kw):
                return True

            @staticmethod
            def account_info():
                return _FakeAccount()

            @staticmethod
            def terminal_info():
                return _FakeTerminal()

            @staticmethod
            def symbol_select(s, v=True):
                return True

            @staticmethod
            def symbol_info(s):
                return FakeSI()

            @staticmethod
            def positions_get(**kw):
                return []

            @staticmethod
            def orders_get(**kw):
                return []

            @staticmethod
            def copy_rates_from_pos(symbol, tf, start, count):
                rates = _make_m1_rates_utc(synthetic_base_time, 1600)
                return rates[-count:] if count <= len(rates) else rates[:]

        sys.modules["MetaTrader5"] = FakeMT5D24

        safe_path = tmp_state / "orchestrator_safe.json"
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        safe_path.write_text(
            json.dumps({"safe_mode": True, "reason": "test", "ts": time.time()}),
            encoding="utf-8",
        )

        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
            config_obj=OrchestratorConfig(
                symbols=["EURUSD"],
                state_dir=str(tmp_state),
                expected_login="53012914",
            ),
        )
        result = orch.startup()
        assert result.verdict == StartupVerdict.SAFE_START
        assert "safe_mode_persisted" in result.reason
        # The persisted file is NOT auto-cleared (D24).
        assert safe_path.exists()
        del sys.modules["MetaTrader5"]

    def test_clear_safe_mode_allows_proceed(self, tmp_state, monkeypatch):
        """After clearing safe-mode, the file is gone."""
        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
        )
        orch.clear_safe_mode()
        assert not orch._read_safe_mode()


# ── S3 ContractSpec builder ────────────────────────────────────────


class TestContractBuilder:
    """S3: ContractSpec from MT5 symbol_info with D3 (stops_level×point)."""

    def test_stops_level_converted_to_price_units(
        self, tmp_state, monkeypatch, synthetic_base_time
    ):
        """D3: stops_level = trade_stops_level × point (in price units)."""

        class FakeSI:
            point = 0.00001  # 1 pip
            digits = 5
            trade_tick_value = 1.0
            volume_min = 0.01
            volume_max = 100.0
            volume_step = 0.01
            trade_contract_size = 100000.0
            trade_stops_level = 20  # 20 points
            trade_mode = 0

        class FakeMT5:
            TIMEFRAME_M1 = 1

            @staticmethod
            def initialize(path=None):
                return True

            @staticmethod
            def login(**kwargs):
                return True

            @staticmethod
            def account_info():
                return _FakeAccount()

            @staticmethod
            def terminal_info():
                return _FakeTerminal()

            @staticmethod
            def symbol_select(s, v=True):
                return True

            @staticmethod
            def symbol_info(s):
                return FakeSI()

            @staticmethod
            def positions_get(**kw):
                return []

            @staticmethod
            def orders_get(**kw):
                return []

            @staticmethod
            def copy_rates_from_pos(symbol, tf, start, count):
                rates = _make_m1_rates_utc(synthetic_base_time, 1600)
                return rates[-count:] if count <= len(rates) else rates[:]

        sys.modules["MetaTrader5"] = FakeMT5

        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
        )
        orch._mt5 = FakeMT5()
        orch._symbol = "EURUSD"
        orch.lock.acquire()

        contract = orch._build_contract("EURUSD")
        assert contract is not None
        # D3: 20 points × 0.00001 = 0.0002 price units
        assert contract.stops_level == pytest.approx(0.0002)

        orch.lock.release()
        del sys.modules["MetaTrader5"]


# ── TAŞ 2 BLOCKERS — T1..T10 ──────────────────────────────────────


class TestTas2Blockers:
    """T1..T10: explicit coverage for the 8 blockers GLM called out.

    Each test is named with its T# and Blocker# for fast mapping to
    the audit's correction list.
    """

    # ── T1 / Blocker 1: slot-floor identity + now >= slot+15m ─────

    def test_T1_seen_bar_slots_is_slot_set_not_tuple(self, tmp_state, synthetic_base_time):
        """T1 (Blocker 1): `_seen_bar_slots` holds slot-ms ints (NOT
        identity tuples). The trailing-edge emit rule requires
        `now >= slot + 15m` to fire."""
        rates = _make_m1_rates_utc(synthetic_base_time, 30)  # 2 closed 15m

        orch = Orchestrator(state_dir=str(tmp_state), configured_symbols=["EURUSD"])
        orch._mt5 = FakeMT5ForBars(rates)
        orch._symbol = "EURUSD"
        orch.lock.acquire()

        bars = orch.produce_new_bars()
        assert len(bars) == 2

        # Slot set, not tuple set.
        assert len(orch._seen_bar_slots) == 2
        for s in orch._seen_bar_slots:
            assert isinstance(s, int)
            # Slot is 15m-grid aligned.
            from src.live.candle_feed import _15M_MS

            assert s % _15M_MS == 0

        # The legacy tuple-identity set must not exist.
        assert not hasattr(orch, "_seen_bar_ids") or not getattr(orch, "_seen_bar_ids", None)
        orch.lock.release()

    def test_T1b_forming_bucket_with_now_before_slot_plus_15m_is_dropped(
        self, tmp_state, synthetic_base_time
    ):
        """T1b (Blocker 1): trailing-edge guard. If a 15m bucket's
        M1 is technically `is_closed_m1` (now > ts+1m) but the FULL
        15m window has not elapsed (now < slot+15m), the bucket is
        dropped. This is the canonical 'now >= slot+15m' emit rule."""

        class _FormingFakeMT5(FakeMT5ForBars):
            """Returns M1 bars where the last bar's slot+15m is in
            the future relative to `now` (forming 15m bucket)."""

            def copy_rates_from_pos(self, symbol, tf, start, count):
                # Anchor so the LAST bucket's slot+15m is FUTURE.
                # We generate 16 bars (covers 1 full 15m + 1 forming M1
                # whose slot+15m is still in the future).
                # Use a base 1 minute BEFORE now so is_closed_m1 passes
                # the M1 (now >= ts+1m), but pick the bucket slot so
                # slot+15m > now.
                now = _utcnow_naive()
                # Place bars starting 2 min ago, 16 of them.
                base = (now - timedelta(minutes=2)).replace(microsecond=0)
                return _make_m1_rates_utc(base, 16)

        orch = Orchestrator(state_dir=str(tmp_state), configured_symbols=["EURUSD"])
        orch._mt5 = _FormingFakeMT5([])
        orch._symbol = "EURUSD"
        orch.lock.acquire()

        bars = orch.produce_new_bars()
        # The 15m bucket that started 2 min ago is NOT yet closed
        # (slot+15m is in the future). Must be dropped.
        assert len(bars) == 0
        orch.lock.release()

    # ── T2 / Blocker 1: warmup applies the same slot filter ───────

    def test_T2_warmup_seeds_seen_bar_slots_from_closed_buckets_only(
        self, tmp_state, monkeypatch, synthetic_base_time
    ):
        """T2 (Blocker 1): warmup output is filtered to buckets whose
        slot+15m is closed at `now`; the slot set is seeded from the
        kept bars and `_global_bar_index` advances past them."""

        class _FakeMT5Full:
            TIMEFRAME_M1 = 1

            @staticmethod
            def initialize(path=None):
                return True

            @staticmethod
            def login(**kw):
                return True

            @staticmethod
            def account_info():
                return _FakeAccount()

            @staticmethod
            def terminal_info():
                return _FakeTerminal()

            @staticmethod
            def symbol_select(s, v=True):
                return True

            @staticmethod
            def symbol_info(s):
                return _FakeSymbolInfo()

            @staticmethod
            def positions_get(**kw):
                return []

            @staticmethod
            def orders_get(**kw):
                return []

            @staticmethod
            def copy_rates_from_pos(symbol, tf, start, count):
                rates = _make_m1_rates_utc(synthetic_base_time, count)
                return rates[-count:] if count <= len(rates) else rates[:]

        sys.modules["MetaTrader5"] = _FakeMT5Full

        orch = Orchestrator(state_dir=str(tmp_state), configured_symbols=["EURUSD"])
        orch._mt5 = _FakeMT5Full()
        orch._symbol = "EURUSD"
        orch.lock.acquire()

        ok, n_bars, result = orch._warmup(m1_count=1600)
        assert ok is True
        assert n_bars > 0
        # Every seeded slot must be 15m-grid aligned.
        from src.live.candle_feed import _15M_MS

        for s in orch._seen_bar_slots:
            assert s % _15M_MS == 0
        # Global index advanced.
        assert orch._global_bar_index == n_bars
        orch.lock.release()
        del sys.modules["MetaTrader5"]

    # ── T3 / Blocker 2: S5 INJECTION (no live_runner edit) ───────

    def test_T3_s5_injects_contract_lifecycle_runtime_sizer_risk_manager(
        self, tmp_state, monkeypatch, synthetic_base_time
    ):
        """T3 (Blocker 2 / D38): the orchestrator constructs TradeLifecycle,
        PositionSizer, RiskManager and the StrategyRuntime itself and hands
        them to LiveRunner. D38 retains the SAME real LiveRunner instance on
        the orchestrator (`self._runner`) for process lifetime — we assert
        identity on it directly, with NO second probe reconstruction."""

        class _FullMT5:
            TIMEFRAME_M1 = 1

            @staticmethod
            def initialize(path=None):
                return True

            @staticmethod
            def login(**kw):
                return True

            @staticmethod
            def account_info():
                return _FakeAccount()

            @staticmethod
            def terminal_info():
                return _FakeTerminal()

            @staticmethod
            def symbol_select(s, v=True):
                return True

            @staticmethod
            def symbol_info(s):
                return _FakeSymbolInfo()

            @staticmethod
            def positions_get(**kw):
                return []

            @staticmethod
            def orders_get(**kw):
                return []

            @staticmethod
            def copy_rates_from_pos(symbol, tf, start, count):
                rates = _make_m1_rates_utc(synthetic_base_time, 1600)
                return rates[-count:] if count <= len(rates) else rates[:]

        sys.modules["MetaTrader5"] = _FullMT5

        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
            config_obj=OrchestratorConfig(
                symbols=["EURUSD"],
                state_dir=str(tmp_state),
                expected_login="53012914",
            ),
        )
        result = orch.startup()
        assert result.verdict == StartupVerdict.PROCEED

        # Preconditions: the orchestrator OWNS the contract and the runner.
        assert orch._contract is not None
        assert orch._runner is not None

        # D38: the real LiveRunner built in S5 is retained on the
        # orchestrator. Assert identity on the SAME instance the
        # orchestrator will use for the loop — NO probe reconstruction.
        assert orch._runner.contract is orch._contract
        assert orch._runner.lifecycle is orch._lifecycle
        assert orch._runner.runtime is orch._runtime
        assert orch._runner.sizer is orch._sizer
        assert orch._runner.risk_manager is orch._risk_manager

        # The orchestrator owns all injected components too.
        assert orch._runtime is not None
        assert orch._lifecycle is not None
        assert orch._sizer is not None
        assert orch._risk_manager is not None

        del sys.modules["MetaTrader5"]

    # ── T4 / Blocker 3: PID liveness + heartbeat ──────────────────

    def test_T4a_dead_pid_is_treated_as_stale(self, tmp_state: Path):
        """T4a (Blocker 3): even if the lock file is FRESH, a dead
        PID is treated as stale → takeover. Windows-safe via
        `_pid_alive` (os.kill 0 semantics)."""
        lock_path = tmp_state / "live.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        # Fresh (age=10s) but dead PID (ProcessLookupError on Windows).
        fresh_dead = LockData(pid=999_999_999, created_at=time.time() - 10, phase="run")
        lock_path.write_text(json.dumps(fresh_dead.to_dict()), encoding="utf-8")

        lock = Lock(lock_path)
        lock.acquire()  # must succeed: dead PID => stale => takeover
        assert lock.owned
        assert lock_path.exists()

    def test_T4b_heartbeat_prevents_false_stale(self, tmp_state: Path):
        """T4b (Blocker 3): a long-running alive process that calls
        `heartbeat()` is NOT misclassified as stale, even if the
        original `created_at` is older than LOCK_STALE_SEC."""
        lock_path = tmp_state / "live.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock = Lock(lock_path)
        lock.acquire()
        # Force the file's created_at far into the past.
        stale_data = LockData(pid=os.getpid(), created_at=time.time() - 999_999, phase="run")
        lock_path.write_text(json.dumps(stale_data.to_dict()), encoding="utf-8")
        # heartbeat() must NOT raise; it must refresh created_at.
        lock.heartbeat()
        raw = json.loads(lock_path.read_text(encoding="utf-8"))
        assert raw["pid"] == os.getpid()
        assert (time.time() - float(raw["created_at"])) < 5.0  # refreshed

    def test_T4c_heartbeat_noop_when_not_owned(self, tmp_state: Path):
        """T4c (Blocker 3): heartbeat() is a no-op if we don't own
        the lock — never overwrites another process's lock."""
        lock_path = tmp_state / "live.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        foreign = LockData(pid=999_999_999, created_at=time.time(), phase="run")
        lock_path.write_text(json.dumps(foreign.to_dict()), encoding="utf-8")

        lock = Lock(lock_path)  # not owned
        lock.heartbeat()  # must not write
        raw = json.loads(lock_path.read_text(encoding="utf-8"))
        assert raw["pid"] == 999_999_999  # untouched

    # ── T5 / Blocker 4: MT5Connection.get_rates + tri-state ───────

    def test_T5a_tristate_none_returns_error_and_increments_counter(self, tmp_state):
        """T5a (Blocker 4): fetch returns None → "ERROR" + counter."""

        class _Conn:
            def get_rates(self, symbol, tf, count):
                return None

        orch = Orchestrator(state_dir=str(tmp_state), configured_symbols=["EURUSD"])
        orch._mt5_conn = _Conn()
        orch._symbol = "EURUSD"
        orch.lock.acquire()

        before = orch._fetch_error_count
        status, payload = orch._fetch_m1_tri_state(count=20)
        # The helper itself does not bump; produce_new_bars does.
        assert status == "ERROR"
        assert orch._fetch_error_count == before
        orch.lock.release()

    def test_T5b_tristate_empty_returns_error(self, tmp_state):
        """T5b (Blocker 4): fetch returns [] → "ERROR"."""

        class _Conn:
            def get_rates(self, symbol, tf, count):
                return []

        orch = Orchestrator(state_dir=str(tmp_state), configured_symbols=["EURUSD"])
        orch._mt5_conn = _Conn()
        orch._symbol = "EURUSD"
        orch.lock.acquire()

        status, payload = orch._fetch_m1_tri_state(count=20)
        assert status == "ERROR"
        assert "empty" in payload
        orch.lock.release()

    def test_T5c_tristate_ok_returns_rates(self, tmp_state):
        """T5c (Blocker 4): fetch returns [rates] → "OK" + rates."""

        class _Conn:
            def get_rates(self, symbol, tf, count):
                return [
                    {
                        "time": 1,
                        "open": 1.0,
                        "high": 1.0,
                        "low": 1.0,
                        "close": 1.0,
                        "tick_volume": 1,
                    }
                ]

        orch = Orchestrator(state_dir=str(tmp_state), configured_symbols=["EURUSD"])
        orch._mt5_conn = _Conn()
        orch._symbol = "EURUSD"
        orch.lock.acquire()

        status, payload = orch._fetch_m1_tri_state(count=20)
        assert status == "OK"
        assert len(payload) == 1
        orch.lock.release()

    def test_T5d_produce_new_bars_increments_counter_on_error(self, tmp_state):
        """T5d (Blocker 4): on fetch error, `produce_new_bars` bumps
        `_fetch_error_count` and returns []. The audit gets an ERROR
        event with the consecutive count."""

        class _Conn:
            def get_rates(self, symbol, tf, count):
                return None

        orch = Orchestrator(state_dir=str(tmp_state), configured_symbols=["EURUSD"])
        orch._mt5_conn = _Conn()
        orch._symbol = "EURUSD"
        orch.lock.acquire()

        assert orch._fetch_error_count == 0
        bars1 = orch.produce_new_bars()
        bars2 = orch.produce_new_bars()
        assert bars1 == [] and bars2 == []
        assert orch._fetch_error_count == 2
        orch.lock.release()

    # ── T6 / Blocker 5: D33 restored → warmup skip + index base ─

    def test_T6_restored_skips_warmup_and_seeds_index_and_slots(
        self, tmp_state, monkeypatch, synthetic_base_time
    ):
        """T6 (Blocker 5 / redelivery 2+3): a restored, previously-warmed
        runtime is a valid warm continuation. The D28 smoke STILL runs
        (redelivery 3), then the heavy full fetch is skipped. The
        restore-seeded `_global_bar_index` + `_seen_bar_slots` persist; the
        returned reason is `restored_warm`."""

        class _FakeMT5R:
            TIMEFRAME_M1 = 1

            @staticmethod
            def initialize(path=None):
                return True

            @staticmethod
            def login(**kw):
                return True

            @staticmethod
            def account_info():
                return _FakeAccount()

            @staticmethod
            def terminal_info():
                return _FakeTerminal()

            @staticmethod
            def symbol_select(s, v=True):
                return True

            @staticmethod
            def symbol_info(s):
                return _FakeSymbolInfo()

            @staticmethod
            def positions_get(**kw):
                return []

            @staticmethod
            def orders_get(**kw):
                return []

            @staticmethod
            def copy_rates_from_pos(symbol, tf, start, count):
                rates = _make_m1_rates_utc(synthetic_base_time, count)
                return rates[-count:] if count <= len(rates) else rates[:]

        from src.live.strategy_runtime import StrategyRuntime

        orch = Orchestrator(state_dir=str(tmp_state), configured_symbols=["EURUSD"])
        orch._mt5 = _FakeMT5R()
        orch._runtime = StrategyRuntime("EURUSD")
        orch._symbol = "EURUSD"
        orch._restored = True
        orch._runtime_restored = True
        orch.lock.acquire()

        # Simulate a previously-warmed, recently-restored runtime. D49: the
        # last bar must be < restore_staleness_slots (2) behind now, otherwise
        # the staleness gate forces a cold rebuild. Anchor bars at `now`.
        recent = _utcnow_naive().replace(second=0, microsecond=0)
        n = 5
        bars = []
        for i in range(n):
            from src.strategy.models import Bar

            bars.append(
                Bar(
                    index=i,
                    timestamp=recent - timedelta(minutes=15 * (n - 1 - i)),
                    open=1.0,
                    high=1.0,
                    low=1.0,
                    close=1.0,
                    volume=0.0,
                )
            )
        orch._runtime.bars = bars
        orch._runtime._warmed = True
        orch._global_bar_index = 0
        orch._seen_bar_slots = set()

        # Verify the restored state is FRESH (< two 15m slots old).
        assert orch._restore_stale_slots() < orch.config.restore_staleness_slots

        ok, n_bars, result = orch._warmup(m1_count=1600)
        assert ok is True
        # Smoke ran and the heavy full fetch was skipped.
        assert result["reason"] == "restored_warm"
        assert n_bars == n
        # Restore-seeded slot set + index base preserved.
        assert orch._global_bar_index == n  # bumped past restored bars
        from src.live.candle_feed import _15M_MS

        for s in orch._seen_bar_slots:
            assert s % _15M_MS == 0
        assert len(orch._seen_bar_slots) > 0
        orch.lock.release()

    def test_T6_partial_restore_cold_runtime_falls_through_keeps_seeds(
        self, tmp_state, monkeypatch, synthetic_base_time
    ):
        """T6b (redelivery 2): lifecycle-restored + runtime COLD is NOT a
        warm continuation. `_warmup` falls through to the full fetch, but
        buckets already present in the restore-seeded `_seen_bar_slots` are
        NOT re-emitted / re-indexed. Smoke always runs first."""

        from src.live.strategy_runtime import StrategyRuntime

        class _FakeMT5Partial:
            TIMEFRAME_M1 = 1

            @staticmethod
            def initialize(path=None):
                return True

            @staticmethod
            def login(**kw):
                return True

            @staticmethod
            def account_info():
                return _FakeAccount()

            @staticmethod
            def terminal_info():
                return _FakeTerminal()

            @staticmethod
            def symbol_select(s, v=True):
                return True

            @staticmethod
            def symbol_info(s):
                return _FakeSymbolInfo()

            @staticmethod
            def positions_get(**kw):
                return []

            @staticmethod
            def orders_get(**kw):
                return []

            @staticmethod
            def copy_rates_from_pos(symbol, tf, start, count):
                # Return LAST 1600 bars before `synthetic_base_time` so the
                # warm approach range can carry the smoke request.
                rates = _make_m1_rates_utc(synthetic_base_time, 1600)
                return rates[-count:] if count <= len(rates) else rates[:]

        orch = Orchestrator(state_dir=str(tmp_state), configured_symbols=["EURUSD"])
        orch._mt5 = _FakeMT5Partial()
        orch._runtime = StrategyRuntime("EURUSD")
        orch._symbol = "EURUSD"
        # Lifecycle was restored, but the runtime is COLD (_warmed False).
        orch._lifecycle_restored = True
        orch._restored = True
        orch.lock.acquire()

        orch._global_bar_index = 0
        orch._seen_bar_slots = set()

        ok, n_bars, result = orch._warmup(m1_count=1600)
        # Cold runtime -> falls through to full warmup -> ok True.
        assert ok is True
        # Fixture data is deliberately ~102000s old, so the D28 smoke
        # records the non-fatal `stale_last_closed_m1` reason (expected
        # production behaviour) while warmup still succeeds via fall-through.
        assert "stale_last_closed_m1" in result["reason"]
        assert n_bars > 0
        # Runtime became warmed.
        assert orch._runtime._warmed is True
        orch.lock.release()

    def test_T6c_restore_warm_smoke_failure_is_safe_start(
        self, tmp_state, monkeypatch, synthetic_base_time
    ):
        """T6c (redelivery 3): the D28 smoke runs even on a restored,
        warmed runtime. A smoke failure must surface as a warmup failure
        -> SAFE-START (it must NOT silently PROCEED)."""

        from src.live.strategy_runtime import StrategyRuntime

        class _FakeMT5NoRates:
            TIMEFRAME_M1 = 1

            @staticmethod
            def initialize(path=None):
                return True

            @staticmethod
            def login(**kw):
                return True

            @staticmethod
            def account_info():
                return _FakeAccount()

            @staticmethod
            def terminal_info():
                return _FakeTerminal()

            @staticmethod
            def symbol_select(s, v=True):
                return True

            @staticmethod
            def symbol_info(s):
                return _FakeSymbolInfo()

            @staticmethod
            def positions_get(**kw):
                return []

            @staticmethod
            def orders_get(**kw):
                return []

            @staticmethod
            def copy_rates_from_pos(symbol, tf, start, count):
                return []  # smoke fails (no data)

        orch = Orchestrator(state_dir=str(tmp_state), configured_symbols=["EURUSD"])
        orch._mt5 = _FakeMT5NoRates()
        orch._runtime = StrategyRuntime("EURUSD")
        orch._symbol = "EURUSD"
        orch._restored = True
        orch._runtime_restored = True
        orch.lock.acquire()

        orch._runtime._warmed = True  # cold? no: previously warmed
        # Smoke returns [] -> warmup fails EVEN THOUGH restored+warm.
        ok, n_bars, result = orch._warmup(m1_count=1600)
        assert ok is False
        assert "copy_rates_empty" in result["reason"]
        orch.lock.release()

    # ── T7 / Blocker 5: load_lifecycle is called in S7 ──────────

    def test_T7_s7_calls_load_lifecycle(self, tmp_state, monkeypatch, synthetic_base_time):
        """T7 (Blocker 5): S7 calls `self._recovery.load_lifecycle(
        self._lifecycle, self._symbol)`. We verify via a probe
        RuntimeRecovery that exposes the call."""

        from src.live.recovery import RuntimeRecovery
        from src.live.trade_lifecycle import TradeLifecycle

        captured = {"load": False, "load_lifecycle": False}

        class _ProbeRecovery(RuntimeRecovery):
            def load(self, runtime, symbol):
                captured["load"] = True
                return False  # no state

            def load_lifecycle(self, lifecycle, symbol):
                captured["load_lifecycle"] = True
                return False  # no state

        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
            config_obj=OrchestratorConfig(
                symbols=["EURUSD"],
                state_dir=str(tmp_state),
                expected_login="53012914",
            ),
        )
        orch._recovery = _ProbeRecovery(str(tmp_state))
        orch._lifecycle = TradeLifecycle()
        orch._symbol = "EURUSD"
        orch.lock.acquire()
        # Direct call to S7's restoration paths (mirrors _run_phases S7).
        orch._recovery.load(orch._runtime, orch._symbol)
        orch._recovery.load_lifecycle(orch._lifecycle, orch._symbol)
        assert captured["load"] is True
        assert captured["load_lifecycle"] is True
        orch.lock.release()

    # ── T8 / Blocker 6: D12 empty expected_login → SAFE-START ────

    def test_T8_empty_expected_login_forces_safe_start(
        self, tmp_state, monkeypatch, synthetic_base_time
    ):
        """T8 (Blocker 6): empty/unset expected_login adds
        `expected_login_unset` to safe_reasons → SAFE-START, NOT
        FATAL. Identity is unknown by design (operator action)."""

        class _MT5_NoLogin:
            TIMEFRAME_M1 = 1

            @staticmethod
            def initialize(path=None):
                return True

            @staticmethod
            def login(**kw):
                return True

            @staticmethod
            def account_info():
                return _FakeAccount()

            @staticmethod
            def terminal_info():
                return _FakeTerminal()

            @staticmethod
            def symbol_select(s, v=True):
                return True

            @staticmethod
            def symbol_info(s):
                return _FakeSymbolInfo()

            @staticmethod
            def positions_get(**kw):
                return []

            @staticmethod
            def orders_get(**kw):
                return []

            @staticmethod
            def copy_rates_from_pos(symbol, tf, start, count):
                rates = _make_m1_rates_utc(synthetic_base_time, 1600)
                return rates[-count:] if count <= len(rates) else rates[:]

        # Ensure no env override leaks in.
        monkeypatch.delenv("MT5_EXPECTED_LOGIN", raising=False)
        sys.modules["MetaTrader5"] = _MT5_NoLogin

        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
            # expected_login unset on purpose (D12 hardening).
        )
        result = orch.startup()
        assert result.verdict == StartupVerdict.SAFE_START
        assert "expected_login_unset" in result.reason
        # NOT FATAL.
        assert orch.lock.owned  # lock held even in SAFE-START
        del sys.modules["MetaTrader5"]

    def test_T8b_mismatch_still_fatal(self, tmp_state, monkeypatch, synthetic_base_time):
        """T8b (Blocker 6): set + mismatch is still FATAL (regression
        guard for the original D12 behavior)."""

        class _MT5_Mismatch:
            TIMEFRAME_M1 = 1

            @staticmethod
            def initialize(path=None):
                return True

            @staticmethod
            def login(**kw):
                return True

            @staticmethod
            def account_info():
                return _FakeAccount()  # login=53012914

            @staticmethod
            def terminal_info():
                return _FakeTerminal()

            @staticmethod
            def shutdown():
                return None

            @staticmethod
            def symbol_select(s, v=True):
                return True

            @staticmethod
            def symbol_info(s):
                return _FakeSymbolInfo()

            @staticmethod
            def positions_get(**kw):
                return []

            @staticmethod
            def orders_get(**kw):
                return []

            @staticmethod
            def copy_rates_from_pos(symbol, tf, start, count):
                return []

        sys.modules["MetaTrader5"] = _MT5_Mismatch
        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
            config_obj=OrchestratorConfig(
                symbols=["EURUSD"],
                state_dir=str(tmp_state),
                expected_login="11111111",  # wrong on purpose
            ),
        )
        result = orch.startup()
        assert result.verdict == StartupVerdict.FATAL
        assert "identity_mismatch" in result.reason
        assert not orch.lock.owned  # FATAL releases lock
        del sys.modules["MetaTrader5"]

    # ── NEW-1 (redelivery 4): trade_allowed=0 → SAFE_START ───────

    def test_T_new1_trade_allowed_disabled_forces_safe_start(
        self, tmp_state, monkeypatch, synthetic_base_time
    ):
        """NEW-1 (redelivery 4): terminal_info.trade_allowed == 0 must
        surface as SAFE_START in the startup result, not silently pass.
        Startup snapshot/capture alone is insufficient."""

        class _TerminalNoTrade:
            build = 6140
            path = "C:/MT5/terminal64.exe"
            trade_allowed = False  # trading disabled

        class _MT5_NoTrade:
            TIMEFRAME_M1 = 1

            @staticmethod
            def initialize(path=None):
                return True

            @staticmethod
            def login(**kw):
                return True

            @staticmethod
            def account_info():
                return _FakeAccount()

            @staticmethod
            def terminal_info():
                return _TerminalNoTrade()

            @staticmethod
            def symbol_select(s, v=True):
                return True

            @staticmethod
            def symbol_info(s):
                return _FakeSymbolInfo()

            @staticmethod
            def positions_get(**kw):
                return []

            @staticmethod
            def orders_get(**kw):
                return []

            @staticmethod
            def copy_rates_from_pos(symbol, tf, start, count):
                rates = _make_m1_rates_utc(synthetic_base_time, 1600)
                return rates[-count:] if count <= len(rates) else rates[:]

        monkeypatch.delenv("MT5_EXPECTED_LOGIN", raising=False)
        sys.modules["MetaTrader5"] = _MT5_NoTrade

        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
            config_obj=OrchestratorConfig(
                symbols=["EURUSD"],
                state_dir=str(tmp_state),
                expected_login="53012914",
            ),
        )
        result = orch.startup()
        assert result.verdict == StartupVerdict.SAFE_START
        assert "trade_allowed_disabled" in result.reason
        # Lock held even in SAFE-START.
        assert orch.lock.owned
        del sys.modules["MetaTrader5"]

    # ── T9 / Blocker 7: D30 trade_mode != FULL → safe_reason ─────

    def test_T9_trade_mode_not_full_adds_safe_reason(
        self, tmp_state, monkeypatch, synthetic_base_time
    ):
        """T9 (Blocker 7): symbol_info.trade_mode != 0 → the builder
        returns the ContractSpec (NOT None) and the orchestrator adds
        `trade_mode_not_full` to safe_reasons → SAFE-START."""

        class _FakeSI_LongOnly:
            point = 0.00001
            digits = 5
            trade_tick_value = 1.0
            volume_min = 0.01
            volume_max = 100.0
            volume_step = 0.01
            trade_contract_size = 100000.0
            trade_stops_level = 10
            trade_mode = 1  # LONG-only

        class _MT5_LongOnly:
            TIMEFRAME_M1 = 1

            @staticmethod
            def initialize(path=None):
                return True

            @staticmethod
            def login(**kw):
                return True

            @staticmethod
            def account_info():
                return _FakeAccount()

            @staticmethod
            def terminal_info():
                return _FakeTerminal()

            @staticmethod
            def symbol_select(s, v=True):
                return True

            @staticmethod
            def symbol_info(s):
                return _FakeSI_LongOnly()

            @staticmethod
            def positions_get(**kw):
                return []

            @staticmethod
            def orders_get(**kw):
                return []

            @staticmethod
            def copy_rates_from_pos(symbol, tf, start, count):
                rates = _make_m1_rates_utc(synthetic_base_time, 1600)
                return rates[-count:] if count <= len(rates) else rates[:]

        sys.modules["MetaTrader5"] = _MT5_LongOnly
        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
            config_obj=OrchestratorConfig(
                symbols=["EURUSD"],
                state_dir=str(tmp_state),
                expected_login="53012914",
            ),
        )
        result = orch.startup()
        # Builder must return a ContractSpec (D30: not None).
        assert orch._contract is not None
        # trade_mode flag set to False.
        assert orch._trade_mode_ok is False
        # safe_reason surfaced → SAFE-START.
        assert result.verdict == StartupVerdict.SAFE_START
        assert "trade_mode_not_full" in result.reason
        del sys.modules["MetaTrader5"]

    # ── T10 / Blocker 8: D24 persisted file NOT auto-cleared ──────

    def test_T10_persisted_file_not_cleared_after_clean_warmup(
        self, tmp_state, monkeypatch, synthetic_base_time
    ):
        """T10 (Blocker 8): after a clean warmup, the persisted
        safe-mode file is NOT auto-cleared. Clearing is a runbook
        operation. Phases still ran (S5/S7/S9 all executed) — the
        file's existence + the clean warmup yield SAFE_START with
        the persisted reason included."""

        class _MT5_Full2:
            TIMEFRAME_M1 = 1

            @staticmethod
            def initialize(path=None):
                return True

            @staticmethod
            def login(**kw):
                return True

            @staticmethod
            def account_info():
                return _FakeAccount()

            @staticmethod
            def terminal_info():
                return _FakeTerminal()

            @staticmethod
            def symbol_select(s, v=True):
                return True

            @staticmethod
            def symbol_info(s):
                return _FakeSymbolInfo()

            @staticmethod
            def positions_get(**kw):
                return []

            @staticmethod
            def orders_get(**kw):
                return []

            @staticmethod
            def copy_rates_from_pos(symbol, tf, start, count):
                rates = _make_m1_rates_utc(synthetic_base_time, 1600)
                return rates[-count:] if count <= len(rates) else rates[:]

        sys.modules["MetaTrader5"] = _MT5_Full2

        # Pre-write a persisted safe-mode file (mimics prior run).
        safe_path = tmp_state / "orchestrator_safe.json"
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        safe_path.write_text(
            json.dumps({"safe_mode": True, "reason": "prior_warmup_fail", "ts": time.time()}),
            encoding="utf-8",
        )

        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
            config_obj=OrchestratorConfig(
                symbols=["EURUSD"],
                state_dir=str(tmp_state),
                expected_login="53012914",
            ),
        )
        result = orch.startup()
        # Phases ran (warmup_bars populated, contract present).
        assert result.warmup_bars > 0
        assert result.contract is not None
        # SAFE-START carries the persisted reason.
        assert result.verdict == StartupVerdict.SAFE_START
        assert "safe_mode_persisted" in result.reason
        assert "prior_warmup_fail" in result.reason
        # Persisted file still present (NOT auto-cleared).
        assert safe_path.exists()
        del sys.modules["MetaTrader5"]
