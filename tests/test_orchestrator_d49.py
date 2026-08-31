"""D49 / O2 — boot-time synchronous replay acceptance tests.

Covers the referee's required test list (8 tests). All runtime tests use
the REAL StrategyRuntime — fake-runtime assertions are meaningless for
the bias/window contract. runtime.warmup is NOT monkeypatched; the
prefix-only semantics of the engine are an invariant the orchestrator
must respect (C4).

Time control goes through Orchestrator(now_fn=...) — no time.sleep.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

import pytest

from src.live.audit import EventType
from src.live.candle_feed import _15M_MS
from src.live.clock import _utcnow_naive, utc_to_server
from src.live.orchestrator import (
    Orchestrator,
    OrchestratorConfig,
    StartupVerdict,
    _naive_utc_epoch,
    _slot_floor_ms,
)
from src.live.recovery import RuntimeRecovery
from src.live.strategy_runtime import StrategyRuntime
from src.live.trade_lifecycle import OpenTradeContext, TradeLifecycle
from src.strategy.models import Bar

# ── Synthetic M1 rate generator (mirror test_orchestrator_tas2 helper) ──


def _make_m1_rates_utc(start_utc: datetime, count: int, base: float = 1.1000) -> List[dict]:
    """Return `count` synthetic M1 bars; timestamps encoded as server time so
    that orchestrator._rates_to_bars() round-trips them to the intended UTC.
    """
    rows = []
    for i in range(count):
        utc_t = start_utc + timedelta(minutes=i)
        server = utc_to_server(utc_t)
        ts = int(server.replace(tzinfo=timezone.utc).timestamp())
        rows.append(
            {
                "time": ts,
                "open": base + i * 0.0001,
                "high": base + i * 0.0001 + 0.00005,
                "low": base + i * 0.0001 - 0.00005,
                "close": base + i * 0.0001 + 0.00002,
                "tick_volume": 100,
            }
        )
    return rows


# ── Full-MT5 fake (instance with per-test history anchor) ──────────────


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


class _FakeSymbolInfo:
    point = 0.00001
    digits = 5
    trade_tick_value = 1.0
    volume_min = 0.01
    volume_max = 100.0
    volume_step = 0.01
    trade_contract_size = 100000.0
    trade_stops_level = 10
    trade_mode = 0  # FULL


class FakeMT5Full:
    """FakeMT5 instance returning M1 history anchored at `history_anchor`."""

    TIMEFRAME_M1 = 1

    def __init__(self, history_anchor: datetime, length_minutes: int = 1600):
        self._anchor = history_anchor
        self._length = length_minutes

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

    def copy_rates_from_pos(self, symbol, tf, start, count):
        rates = _make_m1_rates_utc(self._anchor, self._length)
        return rates[-count:] if count <= len(rates) else rates[:]


# ── Helpers ──────────────────────────────────────────────────────────────


def _recent_naive() -> datetime:
    """Naive-UTC 'now' rounded to the minute."""
    return _utcnow_naive().replace(second=0, microsecond=0)


def _bar_at(naive_utc: datetime, index: int = 0) -> Bar:
    return Bar(
        index=index,
        timestamp=naive_utc,
        open=1.1000,
        high=1.1001,
        low=1.0999,
        close=1.1000,
        volume=0.0,
    )


@pytest.fixture
def tmp_state(tmp_path: Path) -> Path:
    return tmp_path / "state"


def _assert_no_slot_gaps(runtime_bars: List[Bar]) -> None:
    """D49 B-1 hole-guard: every consecutive pair of 15m slots in the
    runtime's bar set must be exactly one slot apart. A skipped slot means
    the rebuild fed a gapped history (restored slots leaking into the
    seen-skip guard) — the exact defect B-1 was written to kill."""
    slots = sorted(
        {_slot_floor_ms(int(_naive_utc_epoch(b.timestamp) * 1000)) for b in runtime_bars}
    )
    assert len(slots) > 1, "hole-guard needs >1 slot"
    for a, b in zip(slots, slots[1:]):
        assert b - a == _15M_MS, (
            f"delikli rebuild: slot gap {(b - a) // 60000}min between "
            f"{a} and {b} — restored slots were skipped by the rebuild"
        )


def _warmed_runtime_with_last_bar_at(stale_slots: int) -> StrategyRuntime:
    """Build a warmed StrategyRuntime whose last bar is exactly
    `stale_slots` 15m slots behind now. Returns the real runtime; the
    caller assigns it to `orch._runtime`.
    """
    now = _recent_naive()
    slot_now_ms = _slot_floor_ms(int(_naive_utc_epoch(now) * 1000))
    target_ms = slot_now_ms - stale_slots * _15M_MS
    last_ts = datetime.fromtimestamp(target_ms / 1000, tz=timezone.utc).replace(tzinfo=None)
    rt = StrategyRuntime("EURUSD")
    rt.bars = [_bar_at(last_ts, index=0)]
    rt._warmed = True
    return rt


# ── T1: stale restore triggers cold rebuild (D49 O2) ───────────────────


class TestStaleRestoreTriggersColdRebuild:
    """A restored-warm runtime whose last bar is >2 slots behind now is
    NOT a valid warm continuation. The orchestrator must:
      1. downgrade warm_skip to False
      2. set _cold_rebuild_needed
      3. fetch full history
      4. warmup + O2 sync replay
      5. reach a valid bias / session_key end-state
    """

    def test_stale_restore_triggers_cold_rebuild(
        self, tmp_state: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MT5_EXPECTED_LOGIN", raising=False)

        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
            config_obj=OrchestratorConfig(
                symbols=["EURUSD"],
                state_dir=str(tmp_state),
                expected_login="53012914",
            ),
        )
        # Direct _warmup call: set the fetch seam (self._mt5) directly.
        # length_minutes=1700 so the synthetic history extends up to NOW —
        # like a real full fetch — otherwise the restored slot (now-45m)
        # is genuinely absent from the data and the hole-guard is vacuous.
        orch._mt5 = FakeMT5Full(_recent_naive() - timedelta(minutes=1700), length_minutes=1700)
        orch._runtime = _warmed_runtime_with_last_bar_at(stale_slots=3)
        orch._symbol = "EURUSD"
        orch.lock.acquire()

        assert orch._restore_stale_slots() == 3
        assert orch._restore_stale_slots() > orch.config.restore_staleness_slots

        ok, n_bars, result = orch._warmup(m1_count=1600)
        assert ok is True, f"warmup failed: {result}"
        # Cold-rebuild path: heavy full fetch ran (not the warm_skip path).
        assert (
            result["reason"] != "restored_warm"
        ), f"stale restore must NOT warm-skip; got reason={result['reason']!r}"
        assert result["reason"] != "restored_warm_no_mt5"
        assert orch._cold_rebuild_needed is True
        assert n_bars > 0
        # D49 O2: replay advanced _next_idx to the end of reindexed.
        assert orch._replay_report is not None
        assert orch._replay_report["replay_bars"] > 0
        assert orch._runtime._next_idx == len(orch._runtime.bars)
        # D49: bias / session_key established by the cold rebuild.
        assert orch._replay_report["bias"] is not None
        assert orch._replay_report["session_key"] is not None
        # D49 B-1 hole-guard: the restored slot (3 slots behind now) must be
        # PRESENT in the rebuilt runtime.bars — never skipped by the
        # seen-skip guard — and the bar stream must be gap-free.
        restored_slot = _slot_floor_ms(int(_naive_utc_epoch(_recent_naive()) * 1000)) - 3 * _15M_MS
        assert any(
            _slot_floor_ms(int(_naive_utc_epoch(b.timestamp) * 1000)) == restored_slot
            for b in orch._runtime.bars
        ), "delikli rebuild: restored slot missing from runtime.bars"
        _assert_no_slot_gaps(orch._runtime.bars)

        orch.lock.release()


# ── T2: fresh restore keeps warm_skip (D49 staleness) ───────────────────


class TestFreshRestoreKeepsWarmSkip:
    """A restored-warm runtime whose last bar is <=2 slots old keeps the
    warm-skip path (no fetch, no replay). Behavior preserved from Taş 2.
    """

    def test_fresh_restore_keeps_warm_skip(
        self, tmp_state: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MT5_EXPECTED_LOGIN", raising=False)

        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
            config_obj=OrchestratorConfig(
                symbols=["EURUSD"],
                state_dir=str(tmp_state),
                expected_login="53012914",
            ),
        )
        # Direct _warmup call: set the fetch seam directly so the smoke
        # path can run. The restore is recent, so warm_skip should fire.
        orch._mt5 = FakeMT5Full(_recent_naive() - timedelta(minutes=1700), length_minutes=1600)
        now = _recent_naive()
        bars: List[Bar] = []
        for i in range(5):
            bars.append(_bar_at(now - timedelta(minutes=15 * (4 - i)), index=i))
        orch._runtime = StrategyRuntime("EURUSD")
        orch._runtime.bars = bars
        orch._runtime._warmed = True
        orch._symbol = "EURUSD"
        orch.lock.acquire()

        # Pre-condition: staleness is < threshold (recent).
        assert orch._restore_stale_slots() <= orch.config.restore_staleness_slots
        assert orch._cold_rebuild_needed is False

        ok, n_bars, result = orch._warmup(m1_count=1600)
        assert ok is True, f"warmup failed: {result}"
        # Warm-skip path is preserved: reason = "restored_warm".
        assert result["reason"] == "restored_warm"
        # No replay on a fresh restore.
        assert orch._replay_report["replay_bars"] == 0

        orch.lock.release()


# ── T3: lifecycle survives cold rebuild (D6 invariant) ─────────────────


class TestLifecycleSurvivesColdRebuild:
    """A persisted TradeLifecycle (DD / journal) must survive a cold
    rebuild. D6: invalidation only on broker-side anomalies, not on
    orchestrator-side restart.
    """

    def test_lifecycle_survives_cold_rebuild(
        self, tmp_state: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Build a lifecycle with a known realized journal entry.
        lifecycle = TradeLifecycle()
        ctx = OpenTradeContext(
            position_id=42,
            order_id=1,
            entry_deal_id=100,
            symbol="EURUSD",
            side="long",
            entry_price=1.1000,
            initial_sl=1.0990,
            base_lot=0.10,
            final_lot=0.10,
            filled_volume=0.10,
            remaining_volume=0.0,
            initial_risk_cash_total=10.0,
            initial_risk_cash_per_lot_or_unit=100.0,
        )
        lifecycle.register_open_context(ctx)
        assert (
            lifecycle.record_exit_deal(
                deal_id=200, position_id=42, net_realized_cash=15.0, pnl_r=1.5
            )
            == "recorded"
        )
        # Sanity: realized journal populated, DD has the realization.
        assert len(lifecycle.realized_journal) == 1
        pre_rebuild_realized = lifecycle.portfolio_dd.realized_pnl_r
        assert abs(pre_rebuild_realized - 1.5) < 1e-9

        recovery = RuntimeRecovery(str(tmp_state))
        recovery.save_lifecycle(lifecycle, "EURUSD")

        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
            config_obj=OrchestratorConfig(
                symbols=["EURUSD"],
                state_dir=str(tmp_state),
                expected_login="53012914",
            ),
        )
        # Cold path: real StrategyRuntime, lifecycle pre-loaded.
        orch._mt5 = FakeMT5Full(_recent_naive() - timedelta(minutes=1700), length_minutes=1600)
        orch._runtime = StrategyRuntime("EURUSD")
        orch._lifecycle = TradeLifecycle()
        orch._recovery = recovery
        orch._symbol = "EURUSD"
        orch.lock.acquire()

        orch._lifecycle_restored = bool(orch._recovery.load_lifecycle(orch._lifecycle, "EURUSD"))
        orch._runtime_restored = bool(orch._recovery.load(orch._runtime, "EURUSD"))
        assert orch._lifecycle_restored is True
        assert orch._runtime._warmed is False
        orch._cold_rebuild_needed = True  # mirrors S7 visibility

        ok, _, result = orch._warmup(m1_count=1600)
        assert ok is True, f"warmup failed: {result}"
        assert orch._cold_rebuild_needed is True

        # D6: lifecycle state survived; realized R remains in DD.
        assert orch._lifecycle.dd_reliable is True
        assert (
            abs(orch._lifecycle.portfolio_dd.realized_pnl_r - 1.5) < 1e-9
        ), f"D6 violated: realized_pnl_r drifted to {orch._lifecycle.portfolio_dd.realized_pnl_r!r}"

        orch.lock.release()


# ── T4: replay establishes yesterday's window (fresh boot) ──────────────


class TestReplayEstablishesYesterdaysWindow:
    """A FRESH boot (no restore) must replay the full history so the runtime
    ends with yesterday's window established: bias, session, ATR. Without
    D49 the runtime would stop at the warmup prefix (only 101 bars seen).
    """

    def test_replay_establishes_yesterdays_window_fresh_boot(
        self, tmp_state: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MT5_EXPECTED_LOGIN", raising=False)

        history_anchor = _recent_naive() - timedelta(minutes=1700)
        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
            config_obj=OrchestratorConfig(
                symbols=["EURUSD"],
                state_dir=str(tmp_state),
                expected_login="53012914",
            ),
        )
        orch._mt5 = FakeMT5Full(history_anchor, length_minutes=1600)
        orch._runtime = StrategyRuntime("EURUSD")  # cold
        orch._symbol = "EURUSD"
        orch.lock.acquire()

        ok, n_bars, result = orch._warmup(m1_count=1600)
        assert ok is True, f"warmup failed: {result}"

        report = orch._replay_report
        assert report is not None
        assert report["replay_bars"] > 0, "fresh boot must replay >0 bars"
        assert report["signals_discarded"] >= 0
        assert report["end_state"] in ("flat", "active_trade")
        assert report["next_idx"] == len(orch._runtime.bars), (
            f"C1: _next_idx ({report['next_idx']}) must equal len(runtime.bars) "
            f"({len(orch._runtime.bars)})"
        )
        assert report["bias"] is not None
        assert report["session_key"] is not None
        assert len(orch._runtime.bars) == n_bars
        # D49 B-1 completeness: warmup prefix + replay must have seen the
        # FULL reindexed set, and the bar stream must be contiguous.
        assert (
            report["replay_bars"] + (report["next_idx"] - report["replay_bars"])
            == report["next_idx"]
        )  # identity guard (prefix + replay == next_idx)
        assert report["replay_bars"] <= report["next_idx"]
        # Full-coverage guard: the oldest rebuilt bar matches the OLDEST
        # slot the fake feed can deliver — i.e. warmup+replay consumed the
        # full fetch window from its very first bar (no leading hole).
        # The fake feed's OLDEST deliverable bar is `history_anchor` (the
        # anchor is fixed once at test start — do NOT re-derive from a fresh
        # _recent_naive(), which drifts with test runtime).
        feed_first_slot = _slot_floor_ms(int(_naive_utc_epoch(history_anchor) * 1000))
        first_slot = _slot_floor_ms(int(_naive_utc_epoch(orch._runtime.bars[0].timestamp) * 1000))
        assert first_slot == feed_first_slot, (
            f"rebuild did not cover the full fetch window: oldest slot "
            f"{first_slot} != expected {feed_first_slot}"
        )
        _assert_no_slot_gaps(orch._runtime.bars)

        orch.lock.release()


# ── T5: eşik boundary (2 keep / 3 rebuild) ──────────────────────────────


class TestStalenessBoundary:
    """restore_staleness_slots=2; rebuild when stale > 2 (2 keep / 3 rebuild)."""

    def test_boundary_2_keep_3_rebuild(
        self, tmp_state: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MT5_EXPECTED_LOGIN", raising=False)

        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
            config_obj=OrchestratorConfig(
                symbols=["EURUSD"],
                state_dir=str(tmp_state),
                expected_login="53012914",
            ),
        )
        orch._runtime = StrategyRuntime("EURUSD")
        orch._symbol = "EURUSD"
        orch.lock.acquire()

        # stale=1: KEEP
        orch._runtime.bars = _warmed_runtime_with_last_bar_at(1).bars
        orch._runtime._warmed = True
        assert orch._restore_stale_slots() == 1
        assert orch._restore_stale_slots() <= orch.config.restore_staleness_slots

        # stale=2: KEEP (boundary inclusive)
        orch._runtime.bars = _warmed_runtime_with_last_bar_at(2).bars
        orch._runtime._warmed = True
        assert orch._restore_stale_slots() == 2
        assert orch._restore_stale_slots() <= orch.config.restore_staleness_slots

        # stale=3: REBUILD (> 2)
        orch._runtime.bars = _warmed_runtime_with_last_bar_at(3).bars
        orch._runtime._warmed = True
        assert orch._restore_stale_slots() == 3
        assert orch._restore_stale_slots() > orch.config.restore_staleness_slots

        # No-bars runtime: unknown → force rebuild.
        orch._runtime.bars = []
        orch._runtime._warmed = True
        assert orch._restore_stale_slots() > orch.config.restore_staleness_slots

        orch.lock.release()


# ── T6: C1 double-delivery (backlog empty after replay) ─────────────────


class TestC1DoubleDeliveryBacklogEmpty:
    """After O2 replay, runtime.bars contains the full reindexed set and
    _next_idx is at len(bars). In run() the D41 backlog (rt_bars[nxt:])
    MUST be empty on the first tick — otherwise the loop would feed the
    same historical bars a second time.
    """

    def test_c1_double_delivery_backlog_empty(
        self, tmp_state: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MT5_EXPECTED_LOGIN", raising=False)

        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
            config_obj=OrchestratorConfig(
                symbols=["EURUSD"],
                state_dir=str(tmp_state),
                expected_login="53012914",
            ),
        )
        orch._mt5 = FakeMT5Full(_recent_naive() - timedelta(minutes=1700), length_minutes=1600)
        orch._runtime = StrategyRuntime("EURUSD")
        orch._symbol = "EURUSD"
        orch.lock.acquire()

        ok, _, _ = orch._warmup(m1_count=1600)
        assert ok is True

        rt_bars = list(getattr(orch._runtime, "bars", []) or [])
        nxt = int(getattr(orch._runtime, "_next_idx", 0) or 0)
        assert 0 <= nxt <= len(rt_bars)
        assert rt_bars[nxt:] == [], (
            f"C1 violated: D41 backlog non-empty ({len(rt_bars[nxt:])} bars); "
            "loop would double-deliver historical bars"
        )

        orch.lock.release()


# ── T7: C2 end-state report (boot audit event fields) ───────────────────


class TestC2EndStateReport:
    """The boot audit event must carry a SINGLE summary with replay_bars,
    signals_discarded, end_state, session_key, bias. No per-signal spam.
    """

    def test_c2_end_state_report(self, tmp_state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MT5_EXPECTED_LOGIN", raising=False)

        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
            config_obj=OrchestratorConfig(
                symbols=["EURUSD"],
                state_dir=str(tmp_state),
                expected_login="53012914",
            ),
        )
        orch._mt5 = FakeMT5Full(_recent_naive() - timedelta(minutes=1700), length_minutes=1600)
        orch._runtime = StrategyRuntime("EURUSD")
        orch._symbol = "EURUSD"
        orch.lock.acquire()

        ok, _, _ = orch._warmup(m1_count=1600)
        assert ok is True

        replay_events = [
            e
            for e in orch.audit.events
            if e.event_type == EventType.STARTUP
            and isinstance(e.payload, dict)
            and e.payload.get("verdict") == "REPLAY"
        ]
        assert (
            len(replay_events) == 1
        ), f"C2 violated: expected exactly ONE REPLAY audit event, got {len(replay_events)}"
        payload = replay_events[0].payload["payload"]
        for field in (
            "replay_bars",
            "signals_discarded",
            "end_state",
            "next_idx",
            "session_key",
            "bias",
        ):
            assert field in payload, f"C2: missing field {field!r} in audit payload"
        assert payload["replay_bars"] > 0
        assert payload["end_state"] in ("flat", "active_trade")
        assert payload["next_idx"] == int(getattr(orch._runtime, "_next_idx", 0) or 0)

        orch.lock.release()


# ── T8: C3 PROCEED-semantics (partial restore + successful rebuild) ──────


class TestC3ProceedSemanticsAfterRebuild:
    """A partial restore (lifecycle survived, runtime cold) requires a cold
    rebuild. When the rebuild SUCCEEDS the verdict is PROCEED (not
    SAFE_START). The cold-rebuild requirement is VISIBLE (WARN + alert)
    but does not demote a successful boot.
    """

    def test_c3_proceed_semantics_after_successful_rebuild(
        self, tmp_state: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sys

        # Step 1: persist a STALE warmed runtime + lifecycle. Simulates a
        # prior run that shut down with old in-memory state on disk.
        history_anchor = _recent_naive() - timedelta(minutes=4000)
        warm_helper = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
        )
        # length_minutes must yield >= 100 closed 15m bars so warmup() actually
        # warms the runtime (>= ~1500 M1). 1700 -> ~113 closed 15m bars.
        warm_helper._mt5 = FakeMT5Full(history_anchor, length_minutes=1700)
        warm_helper._runtime = StrategyRuntime("EURUSD")
        warm_helper._symbol = "EURUSD"
        warm_helper.lock.acquire()
        ok, _, _ = warm_helper._warmup(m1_count=1700)
        assert ok is True
        warm_helper.lock.release()
        assert len(warm_helper._runtime.bars) > 0

        rec = RuntimeRecovery(str(tmp_state))
        rec.save(warm_helper._runtime, "EURUSD")
        rec.save_lifecycle(TradeLifecycle(), "EURUSD")

        # Step 2: boot a fresh orchestrator. _run_phases does
        # `import MetaTrader5 as mt5_mod` at S1. We must patch sys.modules with
        # an INSTANCE (not the class) so copy_rates_from_pos binds correctly.
        second_boot_anchor = _recent_naive() - timedelta(minutes=1700)
        sys.modules["MetaTrader5"] = FakeMT5Full(second_boot_anchor, length_minutes=1700)
        monkeypatch.delenv("MT5_EXPECTED_LOGIN", raising=False)

        orch = Orchestrator(
            state_dir=str(tmp_state),
            configured_symbols=["EURUSD"],
            config_obj=OrchestratorConfig(
                symbols=["EURUSD"],
                state_dir=str(tmp_state),
                expected_login="53012914",
            ),
        )
        try:
            result = orch.startup()

            # C3: successful rebuild → PROCEED, not SAFE_START.
            assert result.verdict == StartupVerdict.PROCEED, (
                f"C3 violated: partial-restore + successful rebuild must yield "
                f"PROCEED, got {result.verdict.value} (reason={result.reason!r})"
            )
            # C3 visibility: cold rebuild was observed (flag + audit).
            assert orch._cold_rebuild_needed is True
            cold_rebuild_events = [
                e
                for e in orch.audit.events
                if e.event_type == EventType.STARTUP
                and isinstance(e.payload, dict)
                and e.payload.get("verdict") == "COLD_REBUILD_OK"
            ]
            assert len(cold_rebuild_events) == 1, (
                f"C3: expected exactly one COLD_REBUILD_OK event, "
                f"got {len(cold_rebuild_events)}"
            )
            # D6: lifecycle was loaded and survived the rebuild.
            assert orch._lifecycle_restored is True
        finally:
            del sys.modules["MetaTrader5"]
