"""TAŞ 4 acceptance: shutdown() (B-a), D18 absolute-path, atomic
_write_safe_mode, D42 gap check, run_production entry-point mapping."""

import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.live.audit import AuditChain, EventType
from src.live.orchestrator import (
    Orchestrator,
    OrchestratorConfig,
    StartupPhase,
    StartupResult,
    StartupVerdict,
)

NOW = datetime(2026, 1, 5, 12, 19, 0)


def ep(h, m, s=0):
    return int(datetime(2026, 1, 5, h, m, s, tzinfo=timezone.utc).timestamp())


def m1_rates(times):
    import numpy as np

    dt = np.dtype(
        [
            ("time", "<i8"),
            ("open", "<f8"),
            ("high", "<f8"),
            ("low", "<f8"),
            ("close", "<f8"),
            ("tick_volume", "<i8"),
        ]
    )
    rows = []
    for i, t in enumerate(times):
        b = 1.10000
        rows.append((t, b, b + 0.00002, b - 0.00002, b + 0.00001 * ((i % 3) - 1), 100 + i))
    return np.array(rows, dtype=dt)


RATES_15 = m1_rates([ep(12, m) for m in range(0, 15)])  # slot 12:00 fully closed


class FakeConn:
    def __init__(self, rates=RATES_15, tick_age=0.0):
        self.rates = rates
        self.tick = {"bid": 1.10000, "ask": 1.10002, "time": ep(12, 19) + tick_age}

    def get_rates(self, symbol, timeframe="M1", count=10):
        return None if self.rates is None else self.rates[-count:]

    def get_tick_data(self, symbol):
        return dict(self.tick)


class FakeMT5:
    def __init__(self):
        self.account_calls = 0
        self.shutdown_calls = 0
        self._acc = SimpleNamespace(login=111, balance=10000.0, equity=10000.0)

    def account_info(self):
        self.account_calls += 1
        return self._acc

    def shutdown(self):
        self.shutdown_calls += 1


class FakeRunner:
    def __init__(self):
        self.on_bar_calls = []
        self.poll_calls = 0
        self.trailing_calls = 0
        self.result = SimpleNamespace(
            order_sent=False,
            fill=None,
            context_registered=None,
            approved=False,
            blocked_reason="no_signal",
        )
        self.poll_result = []

    def on_bar(self, bar, account):
        self.on_bar_calls.append((bar, account))
        return self.result

    def poll_deals(self):
        self.poll_calls += 1
        return list(self.poll_result)

    def sync_trailing(self):
        self.trailing_calls += 1
        return []


def make_orch(
    tmp_path,
    conn=None,
    mt5=None,
    runner=None,
    verdict=StartupVerdict.PROCEED,
    recon="OK",
    now=NOW,
):
    cfg = OrchestratorConfig(
        symbols=["EURUSD"],
        state_dir=str(tmp_path / "state"),
        audit_path=str(tmp_path / "audit" / "a.jsonl"),
        expected_login="111",
        m1_warmup_count=1000,
    )
    orch = Orchestrator(
        state_dir=str(tmp_path / "state"),
        magic=9007001,
        configured_symbols=["EURUSD"],
        audit=AuditChain(),
        config_obj=cfg,
        mt5=mt5 or FakeMT5(),
        mt5_conn=conn or FakeConn(),
    )
    orch._now_fn = lambda: now
    orch._startup_result = StartupResult(
        verdict=verdict,
        phase=StartupPhase.S11_READY,
        reason="test",
        snapshot={
            "reconciliation": {
                "status": recon,
                "block_trading": recon != "OK",
                "details": [],
            }
        },
    )
    orch._runner = runner
    orch._symbol = "EURUSD"
    orch._contract = SimpleNamespace(tick_size=0.00001, digits=5)
    orch.lock.acquire()
    return orch


@pytest.fixture(autouse=True)
def identity_tz(monkeypatch):
    monkeypatch.setattr("src.live.signal_runner.server_to_utc_historical", lambda dt: dt)


# ── B-a: shutdown() on every exit path ─────────────────────────────


def test_shutdown_records_shutdown_event_and_flushes(tmp_path):
    """B-a: shutdown() writes a SHUTDOWN event when none exists, flushes."""
    orch = make_orch(tmp_path)
    orch.shutdown(exit_code=1, reason="ownership_lost")
    types = [getattr(e, "event_type", None) for e in orch.audit.events]
    assert EventType.SHUTDOWN in types
    # lock released
    assert orch.lock.owned is False


def test_shutdown_idempotent_single_event(tmp_path):
    """B-a: calling shutdown() twice records exactly one SHUTDOWN event."""
    orch = make_orch(tmp_path)
    orch.shutdown(exit_code=0, reason="kill_switch")
    orch.shutdown(exit_code=0, reason="kill_switch")
    types = [getattr(e, "event_type", None) for e in orch.audit.events]
    assert types.count(EventType.SHUTDOWN) == 1


def test_shutdown_does_not_duplicate_existing_shutdown(tmp_path):
    """B-a: if run() already wrote a SHUTDOWN event, shutdown() won't dup."""
    orch = make_orch(tmp_path)
    orch.audit.append(time.time(), EventType.SHUTDOWN, "EURUSD", {"exit": 0})
    orch.shutdown(exit_code=0, reason="kill_switch")
    types = [getattr(e, "event_type", None) for e in orch.audit.events]
    assert types.count(EventType.SHUTDOWN) == 1


def test_shutdown_releases_mt5(tmp_path):
    """B-a: shutdown() calls mt5.shutdown() when the handle exists."""
    mt5 = FakeMT5()
    orch = make_orch(tmp_path, mt5=mt5)
    orch.shutdown(exit_code=0, reason="kill_switch")
    assert mt5.shutdown_calls == 1


def test_ownership_lost_path_records_shutdown(tmp_path):
    """B-a: run() ownership-lost (exit 1) now records a SHUTDOWN event."""
    r = FakeRunner()
    orch = make_orch(tmp_path, runner=r)
    (orch.state_dir / "orchestrator.lock").write_text(
        '{"pid": 999999, "created_at": 0, "phase": "x"}'
    )
    code = orch.run(kill_switch_fn=lambda: False, sleep_fn=lambda s: None)
    assert code == 1
    types = [getattr(e, "event_type", None) for e in orch.audit.events]
    assert EventType.SHUTDOWN in types  # B-a: previously only ERROR


# ── D18 absolute-path + atomic _write_safe_mode ────────────────────


def test_safe_path_is_absolute(tmp_path):
    """D18: _safe_path() resolves to an absolute path regardless of cwd."""
    orch = make_orch(tmp_path)
    p = orch._safe_path()
    assert p.is_absolute()
    assert p.name == "orchestrator_safe.json"


def test_write_safe_mode_atomic_no_tmp_leftover(tmp_path):
    """Atomic write: no tmp sibling remains after a successful write.

    N2 #15: tmp naming is now PID-unique (``<name>.<pid>.tmp``), so the
    assertion covers both the legacy fixed suffix and any per-pid leftovers.
    """
    orch = make_orch(tmp_path)
    orch._write_safe_mode("test_reason")
    p = orch._safe_path()
    assert p.exists()
    assert not p.with_suffix(p.suffix + ".tmp").exists()
    leftovers = [f.name for f in p.parent.iterdir() if f.name.endswith(".tmp")]
    assert leftovers == [], f"leftover tmp files: {leftovers}"
    data = orch._read_safe_mode()
    assert data is not None and data["reason"] == "test_reason"


# ── D42 gap check ──────────────────────────────────────────────────


def test_d42_gap_detected(tmp_path):
    """D42: a skipped 15m slot between new bars is surfaced via audit."""
    orch = make_orch(tmp_path)
    # Two bars whose slots are 30m apart → one missing 15m slot.
    b1 = SimpleNamespace(timestamp=datetime(2026, 1, 5, 12, 0))
    b2 = SimpleNamespace(timestamp=datetime(2026, 1, 5, 12, 30))
    orch._check_bar_gaps([b1, b2])
    safety = [e for e in orch.audit.events if getattr(e, "event_type", None) == EventType.SAFETY]
    assert safety, "expected a SAFETY audit event for the gap"
    gap_slots = safety[-1].payload.get("gap_slots", [])
    assert len(gap_slots) == 1
    assert gap_slots[0][2] == 1  # exactly one missing slot
    assert any("D42" in c.msg for c in orch.alert.alert_log)


def test_d42_no_gap_no_alert(tmp_path):
    """D42: consecutive slots → no gap, no audit/alert."""
    orch = make_orch(tmp_path)
    b1 = SimpleNamespace(timestamp=datetime(2026, 1, 5, 12, 0))
    b2 = SimpleNamespace(timestamp=datetime(2026, 1, 5, 12, 15))
    orch._check_bar_gaps([b1, b2])
    safety = [e for e in orch.audit.events if getattr(e, "event_type", None) == EventType.SAFETY]
    assert not safety
    assert not any("D42" in c.msg for c in orch.alert.alert_log)


# ── run_production entry-point mapping ─────────────────────────────


def test_run_production_fatal_maps_to_1(monkeypatch, tmp_path):
    """Entry point: FATAL startup → exit code 1."""
    import src.live.run_production as rp

    calls = {"shutdown": 0}

    class FakeOrch:
        def __init__(self, *a, **k):
            pass

        def startup(self):
            return StartupResult(
                verdict=StartupVerdict.FATAL,
                phase=StartupPhase.S1_CONNECT,
                reason="initialize_failed",
            )

        def shutdown(self, exit_code=0, reason="shutdown"):
            calls["shutdown"] += 1

    monkeypatch.setattr(rp, "Orchestrator", FakeOrch)
    monkeypatch.setattr(rp, "MT5Connection", lambda: object())
    assert rp.main() == 1
    # K5 move: the finally belt-and-braces now covers the FATAL path too —
    # one idempotent shutdown() call (no-op on real lock state).
    assert calls["shutdown"] == 1  # finally only (startup released lock already)


def test_run_production_proceed_maps_run_code(monkeypatch, tmp_path):
    """Entry point: PROCEED → run() exit code is returned verbatim."""
    import src.live.run_production as rp

    class FakeOrch:
        def __init__(self, *a, **k):
            pass

        def startup(self):
            return StartupResult(
                verdict=StartupVerdict.PROCEED,
                phase=StartupPhase.S11_READY,
                reason="ok",
            )

        def run(self, kill_switch_fn=None, sleep_fn=None):
            # production path: sleep_fn must be None
            assert sleep_fn is None
            return 2

        def shutdown(self, exit_code=0, reason="shutdown"):
            pass

    monkeypatch.setattr(rp, "Orchestrator", FakeOrch)
    monkeypatch.setattr(rp, "MT5Connection", lambda: object())
    assert rp.main() == 2


def test_run_production_injects_mt5_conn(monkeypatch, tmp_path):
    """Entry point: MT5Connection is always injected (mt5_conn wiring)."""
    import src.live.run_production as rp

    captured = {}

    class FakeOrch:
        def __init__(self, *a, **k):
            captured["mt5_conn"] = k.get("mt5_conn")

        def startup(self):
            return StartupResult(
                verdict=StartupVerdict.PROCEED,
                phase=StartupPhase.S11_READY,
                reason="ok",
            )

        def run(self, kill_switch_fn=None, sleep_fn=None):
            return 0

        def shutdown(self, exit_code=0, reason="shutdown"):
            pass

    monkeypatch.setattr(rp, "Orchestrator", FakeOrch)
    monkeypatch.setattr(rp, "MT5Connection", lambda: "REAL_CONN")
    rp.main()
    assert captured["mt5_conn"] == "REAL_CONN"


def test_run_production_run_raises_calls_shutdown(monkeypatch, tmp_path):
    """T-d (S1): run() raising → shutdown(exit_code=1) called, exit 1."""
    import src.live.run_production as rp

    calls = {"shutdown": []}

    class FakeOrch:
        def __init__(self, *a, **k):
            pass

        def startup(self):
            return StartupResult(
                verdict=StartupVerdict.PROCEED,
                phase=StartupPhase.S11_READY,
                reason="ok",
            )

        def run(self, kill_switch_fn=None, sleep_fn=None):
            raise RuntimeError("boom")

        def shutdown(self, exit_code=0, reason="shutdown"):
            calls["shutdown"].append((exit_code, reason))

    monkeypatch.setattr(rp, "Orchestrator", FakeOrch)
    monkeypatch.setattr(rp, "MT5Connection", lambda: object())
    assert rp.main() == 1
    # shutdown fires twice: except-branch + finally belt-and-braces
    # (idempotent in the real Orchestrator — single event, double call OK).
    assert calls["shutdown"] == [
        (1, "run_exception:RuntimeError"),
        (1, "entry_point_finally"),
    ]


def _ki_orch(
    shutdown_sink,
    verdict=StartupVerdict.PROCEED,
    runtime_safe=False,
):
    class FakeOrch:
        def __init__(self, *a, **k):
            self._startup_result = StartupResult(
                verdict=verdict, phase=StartupPhase.S11_READY, reason="ok"
            )
            self._runtime_safe = runtime_safe

        def startup(self):
            return self._startup_result

        def run(self, kill_switch_fn=None, sleep_fn=None):
            raise KeyboardInterrupt()

        def shutdown(self, exit_code=0, reason="shutdown"):
            shutdown_sink.append((exit_code, reason))

    return FakeOrch


def test_run_production_keyboard_interrupt_maps_to_0(monkeypatch, tmp_path):
    """K2: KI with PROCEED startup + not runtime-safe -> clean exit 0
    (same semantics as the kill_fn healthy path)."""
    import src.live.run_production as rp

    calls = []
    monkeypatch.setattr(rp, "Orchestrator", _ki_orch(calls))
    monkeypatch.setattr(rp, "MT5Connection", lambda: object())
    assert rp.main() == 0
    assert calls[0][0] == 0 and calls[0][1] == "keyboard_interrupt"
    assert len(calls) == 2  # except-branch + finally (idempotent)


def test_run_production_keyboard_interrupt_safe_start_maps_to_2(monkeypatch, tmp_path):
    """K2: KI while SAFE-START -> exit 2 (state-dependent, NOT unconditional
    0 — matches kill_fn: 2 if runtime_safe or not entries_enabled else 0)."""
    import src.live.run_production as rp

    calls = []
    monkeypatch.setattr(rp, "Orchestrator", _ki_orch(calls, verdict=StartupVerdict.SAFE_START))
    monkeypatch.setattr(rp, "MT5Connection", lambda: object())
    assert rp.main() == 2
    assert calls[0][0] == 2 and calls[0][1] == "keyboard_interrupt"


def test_run_production_keyboard_interrupt_runtime_safe_maps_to_2(monkeypatch, tmp_path):
    """K2: KI with PROCEED startup but _runtime_safe=True -> exit 2."""
    import src.live.run_production as rp

    calls = []
    monkeypatch.setattr(rp, "Orchestrator", _ki_orch(calls, runtime_safe=True))
    monkeypatch.setattr(rp, "MT5Connection", lambda: object())
    assert rp.main() == 2
    assert calls[0][0] == 2


def test_run_production_keyboard_interrupt_during_startup(monkeypatch, tmp_path):
    """K5: KI raised INSIDE startup() (e.g. S9 65k-bar warmup — the longest
    window) must hit the graceful path: shutdown() called with exit 0,
    main returns 0. Before the K5 move startup() sat OUTSIDE the try."""
    import src.live.run_production as rp

    calls = []

    class FakeOrch:
        def __init__(self, *a, **k):
            self._startup_result = None  # killed before startup completed

        def startup(self):
            raise KeyboardInterrupt()  # mid-warmup

        def run(self, kill_switch_fn=None, sleep_fn=None):
            raise AssertionError("run() must not be reached")

        def shutdown(self, exit_code=0, reason="shutdown"):
            calls.append((exit_code, reason))

    monkeypatch.setattr(rp, "Orchestrator", FakeOrch)
    monkeypatch.setattr(rp, "MT5Connection", lambda: object())
    assert rp.main() == 0
    # except-branch + finally belt-and-braces (idempotent double-call OK)
    assert calls == [
        (0, "keyboard_interrupt"),
        (0, "entry_point_finally"),
    ]


def test_shutdown_writes_runtime_and_lifecycle_snapshots(tmp_path):
    """S2 / D48: shutdown() persists runtime + lifecycle via
    schedule_snapshot BEFORE releasing the lock — the next boot must be
    able to restore warm state instead of paying full warmup."""
    orch = make_orch(tmp_path)
    # Use the REAL runtime/lifecycle types — recovery.save reads internal
    # fields (bars / _next_idx / open_trades), fakes would raise and the
    # best-effort try/except in shutdown() would swallow it silently.
    from src.live.strategy_runtime import StrategyRuntime
    from src.live.trade_lifecycle import TradeLifecycle

    orch._runtime = StrategyRuntime("EURUSD")
    orch._lifecycle = TradeLifecycle()
    orch.shutdown(exit_code=0, reason="kill_switch")
    state = tmp_path / "state"
    files = {p.name for p in state.iterdir()} if state.exists() else set()
    # RuntimeRecovery naming: "{SYMBOL}.json" (runtime) + "{SYMBOL}_lifecycle.json"
    assert "EURUSD.json" in files, f"runtime snapshot missing: {files}"
    assert "EURUSD_lifecycle.json" in files, f"lifecycle snapshot missing: {files}"
    # lock released AFTER the snapshot (teardown order)
    assert orch.lock.owned is False


def test_d18_state_dir_policy(monkeypatch, tmp_path):
    """S4: D18 binary rule — explicit relative SNIPER_STATE_DIR is FATAL;
    unset SNIPER_STATE_DIR resolves to an absolute path (CWD-pinned)."""
    import src.live.run_production as rp

    # (a) explicit relative → SystemExit (FATAL)
    monkeypatch.setenv("SNIPER_STATE_DIR", "relative_state")
    with pytest.raises(SystemExit):
        rp._build_config()

    # (b) unset → resolved absolute
    monkeypatch.delenv("SNIPER_STATE_DIR", raising=False)
    monkeypatch.delenv("SNIPER_AUDIT_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    cfg = rp._build_config()
    assert Path(cfg.state_dir).is_absolute()
    assert Path(cfg.audit_path).is_absolute()

    # (c) explicit absolute → accepted verbatim
    abs_dir = str(tmp_path / "state_abs")
    monkeypatch.setenv("SNIPER_STATE_DIR", abs_dir)
    cfg = rp._build_config()
    assert Path(cfg.state_dir) == Path(abs_dir)


def test_run_chunked_path_real_orchestrator(monkeypatch, tmp_path):
    """K1 / S3 / T-c: the REAL Orchestrator.run() with sleep_fn=None takes
    the elif self._interruptible_sleep branch and sleeps via
    orchestrator.time.sleep in <=1s chunks. Kill arrives mid-sleep -> loop
    breaks within one chunk (systemd-stop responsiveness proof at source).

    _interruptible_sleep uses call-time `time.sleep(...)` module lookup, so
    monkeypatching src.live.orchestrator.time.sleep hits the REAL branch.
    """
    from tests.conftest import FakeRunner, kill_after

    orch = make_orch(tmp_path, runner=FakeRunner())
    calls = []
    monkeypatch.setattr("src.live.orchestrator.time.sleep", lambda s: calls.append(s))
    code = orch.run(kill_switch_fn=kill_after(2), sleep_fn=None)  # elif dali
    assert code in (0, 2)
    assert calls, "chunked path must call orchestrator.time.sleep"
    assert all(0 < c <= 1.0 for c in calls), calls
