"""N2 #17 FIX-SPEC v1.2 lock tests (Hakem-ratifiye fixture seti).

Six mandated fixtures (spec §4.2 + v1.2-A7) + one Katman-1 evidence
probe test. Existing suites must stay green (freeze discipline):
this file only ADDS behaviour-pinning tests.
"""

import ctypes
import json
import os
import time
from types import SimpleNamespace

import pytest

import src.live.orchestrator as orch_mod
from src.live.audit import AuditChain, EventType
from src.live.orchestrator import (
    LOCK_STALE_SEC,
    Lock,
    LockError,
    Orchestrator,
    OrchestratorConfig,
    StartupPhase,
    StartupResult,
    StartupVerdict,
    find_file_holders,
)


# ── minimal orch harness (mirrors tas3 make_orch, runner-only) ──────
class FakeConn:
    def __init__(self):
        self.tick = {"bid": 1.1, "ask": 1.10002, "time": 0}

    def get_rates(self, symbol, timeframe="M1", count=10):
        return None

    def get_tick_data(self, symbol):
        return dict(self.tick)


class FakeMT5:
    def __init__(self):
        self._acc = SimpleNamespace(login=111, balance=10000.0, equity=10000.0)

    def account_info(self):
        return self._acc


class FakeRunner:
    def __init__(self):
        self.poll_calls = 0
        self.poll_result = []

    def on_bar(self, bar, account):
        return SimpleNamespace(
            order_sent=False,
            fill=None,
            context_registered=None,
            approved=False,
            blocked_reason="no_signal",
        )

    def poll_deals(self):
        self.poll_calls += 1
        return list(self.poll_result)

    def sync_trailing(self):
        return []


def make_orch(tmp_path):
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
        mt5=FakeMT5(),
        mt5_conn=FakeConn(),
    )
    orch._startup_result = StartupResult(
        verdict=StartupVerdict.PROCEED,
        phase=StartupPhase.S11_READY,
        reason="test",
        snapshot={"reconciliation": {"status": "OK", "block_trading": False, "details": []}},
    )
    orch._runner = FakeRunner()
    orch._symbol = "EURUSD"
    orch._contract = SimpleNamespace(tick_size=0.00001, digits=5)
    orch.lock.acquire()
    return orch


def kill_after(n):
    state = {"i": 0}

    def fn():
        state["i"] += 1
        return state["i"] > n

    return fn


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Pin the K1 retry-ladder sleeps (tests must not pay ~6.4s)."""
    monkeypatch.setattr(orch_mod.time, "sleep", lambda s: None)


@pytest.fixture(autouse=True)
def _crash_log_to_tmp(monkeypatch, tmp_path):
    """Route the K2 crash-log into the test tmp dir (no repo pollution)."""
    monkeypatch.setattr(orch_mod, "_CRASH_LOG", tmp_path / "state" / "crash_log.txt")


# ── Fixture 1: test_lock_collision — hold handle → degraded, alive ──
def test_lock_collision_degraded_mode(tmp_path, monkeypatch):
    lock = Lock(tmp_path / "state" / "orchestrator.lock")
    lock.acquire()
    events = []
    lock2 = Lock(lock.lock_path, on_block=lambda info: events.append(info))
    real_open = os.open

    def blocked_open(path, flags, *a, **k):
        if str(path) == str(lock2.lock_path):
            raise PermissionError(5, "Access is denied", str(path))
        return real_open(path, flags, *a, **k)

    monkeypatch.setattr(orch_mod.os, "open", blocked_open)
    lock2._owned = True  # refresh-path (heartbeat) scenario
    lock2.heartbeat()  # Katman-4: MUST NOT raise — the process lives
    assert lock2._write_degraded is True
    # Katman-1: the WRITE_BLOCK event names the probe + holder fields
    assert events and events[0]["file"].endswith("orchestrator.lock")
    assert events[0]["probe"] == "restart_manager"
    assert "holder_pids" in events[0] and "holder_names" in events[0]
    # probe errors are never silent — a healthy probe yields an empty list
    assert events[0]["probe_errors"] == []
    # next tick after unblocking: degraded latches clear
    monkeypatch.setattr(orch_mod.os, "open", real_open)
    lock2.heartbeat()
    assert lock2._write_degraded is False


# ── Fixture 2: test_torn_lock — fresh waits, stale takeover ─────────
def test_torn_lock_fresh_waits_stale_takeover(tmp_path):
    p = tmp_path / "state" / "orchestrator.lock"
    p.parent.mkdir(parents=True, exist_ok=True)
    corrupt = []
    lock = Lock(p, on_corrupt=lambda info: corrupt.append(info))
    p.write_text('{"pid": 424242, "created_at": 12')  # torn JSON, mtime NOW
    with pytest.raises(LockError):
        lock.acquire()  # fresh-torn → WAIT (Katman-3.2)
    assert corrupt and corrupt[0]["stale_eligible"] is False
    assert corrupt[0]["file"].endswith("orchestrator.lock")
    old = time.time() - LOCK_STALE_SEC - 5
    os.utime(p, (old, old))  # mtime ≥ 900s → abandoned torn lock
    lock.acquire()  # stale-torn → takeover
    data = lock._read()
    assert lock._owned and data is not None and data.pid == os.getpid()
    # the takeover write HEALED the torn body (in-place rewrite)
    assert json.loads(p.read_text(encoding="utf-8"))["pid"] == os.getpid()


# ── Fixture 3: test_ownership_loss_fatal — D11 path preserved ───────
def test_ownership_loss_fatal(tmp_path):
    orch = make_orch(tmp_path)
    (orch.state_dir / "orchestrator.lock").write_text(
        '{"pid": 999999, "created_at": 0, "phase": "x"}'
    )
    code = orch.run(kill_switch_fn=lambda: False, sleep_fn=lambda s: None)
    assert code == 1  # ownership loss stays FATAL (Katman-4 boundary)


# ── Fixture 4 (A7): degraded tick recovery after holder release ─────
def test_degraded_recovery_after_holder_release(tmp_path, monkeypatch):
    lock = Lock(tmp_path / "state" / "orchestrator.lock")
    lock.acquire()
    real_open = os.open

    def blocked_open(path, flags, *a, **k):
        if str(path) == str(lock.lock_path):
            raise PermissionError(5, "Access is denied", str(path))
        return real_open(path, flags, *a, **k)

    monkeypatch.setattr(orch_mod.os, "open", blocked_open)
    lock.heartbeat()
    assert lock._write_degraded is True
    monkeypatch.setattr(orch_mod.os, "open", real_open)
    lock.heartbeat()  # next tick retries — recovery without restart
    assert lock._write_degraded is False
    assert json.loads(lock.lock_path.read_text(encoding="utf-8"))["pid"] == os.getpid()


# ── Fixture 5 (A7): read-path degraded — torn own-pid survives ──────
def test_read_path_degraded_torn_own_pid_survives(tmp_path):
    orch = make_orch(tmp_path)
    # Torn in-place write that still names OUR pid (B1 scenario shape)
    (orch.state_dir / "orchestrator.lock").write_text('{"pid": %d, "created_at": 123' % os.getpid())
    seen = {}

    def sleep_fn(s):
        # capture the lock mid-run: heartbeat must have REPAIRED the body
        seen["data"] = orch.lock._read()

    code = orch.run(kill_switch_fn=kill_after(1), sleep_fn=sleep_fn)
    assert code == 0  # A2 triage: salvage → refresh → the process lives
    # the heartbeat REPAIRED the torn body (captured before shutdown-release)
    data = seen["data"]
    assert data is not None and data.pid == os.getpid()
    # LOCK_CORRUPT evidence was recorded (A9)
    assert any(e.event_type == EventType.LOCK_CORRUPT for e in orch.audit.events)


# ── Fixture 6 (A7): audit sync-flush fallback on blocked target ─────
def test_audit_syncflush_fallback(tmp_path, monkeypatch):
    orch = make_orch(tmp_path)
    orch.audit.append(time.time(), EventType.ERROR, "EURUSD", {"p": 1})

    def boom(self):
        raise PermissionError(5, "audit target blocked")

    monkeypatch.setattr(AuditChain, "shutdown", boom)
    orch.shutdown(exit_code=1, reason="katman5_test")
    # A8/Katman-5: the terminal events survive by the crash-log channel
    crash = tmp_path / "state" / "crash_log.txt"
    assert crash.exists()
    lines = [json.loads(x) for x in crash.read_text(encoding="utf-8").splitlines()]
    dumps = [x for x in lines if x.get("kind") == "AUDIT_FALLBACK_DUMP"]
    assert dumps and dumps[0]["phase"] == "shutdown_flush"
    # events are JSON-encoded lines (crash-log line format)
    dumped_events = [json.loads(ev) for ev in dumps[0]["events"]]
    assert any(ev.get("event_type") == "ERROR" for ev in dumped_events)


# ── Katman-2: file ops are sync open/close (rename works right after) ─
def test_katman2_file_ops_sync_close_no_handle_leak(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(orch_mod, "_crash_log_append", lambda p, info: calls.append(info))
    lock = Lock(tmp_path / "s" / "orchestrator.lock")
    lock.acquire()
    # L1 invariant: after every op returns, no handle is held — a rename
    # (the exact WinError 5 detector) must succeed immediately.
    renamed = tmp_path / "s" / "renamed.lock"
    os.replace(lock.lock_path, renamed)
    assert renamed.exists()
    os.replace(renamed, lock.lock_path)
    # anomaly channels are LOUD: missing file → OSError triage record
    lock2 = Lock(tmp_path / "s" / "missing.lock")
    assert lock2._read() is None
    assert any(c.get("op") == "read" for c in calls)
    # schema gap → KeyError triage record
    schema_gap = tmp_path / "s" / "gap.lock"
    schema_gap.parent.mkdir(parents=True, exist_ok=True)
    schema_gap.write_text('{"created_at": 1.0}')
    lock3 = Lock(schema_gap)
    assert lock3._read() is None
    assert any(c.get("op") == "read_schema" for c in calls)


# ── Katman-1 evidence: RM probe names OUR pid on a real handle ──────
@pytest.mark.skipif(os.name != "nt", reason="Restart-Manager is Windows-only")
def test_rm_probe_lists_self_on_real_handle(tmp_path, monkeypatch):
    p = tmp_path / "probe_target.txt"
    p.write_text("x")
    k32 = ctypes.windll.kernel32
    GENERIC_READ = 0x80000000
    OPEN_EXISTING = 3
    h = k32.CreateFileW(str(p), GENERIC_READ, 0, None, OPEN_EXISTING, 0, None)
    assert h not in (0, -1)  # exclusive handle held by THIS process
    try:
        holders = find_file_holders(str(p))
        pids = [h_["pid"] for h_ in holders if "pid" in h_]
        assert os.getpid() in pids  # Ek-A Cline-notu (1): self-PID sabitleme
        # correct 4-byte-BOOL struct layout → strAppName is populated
        names = [h_["name"] for h_ in holders if "name" in h_]
        assert any(n.strip() for n in names)
    finally:
        k32.CloseHandle(h)
    # no-holder legitimate result (rc=0, empty) — file must EXIST with
    # no open handles; RM reports a non-existent resource as rc=0/[] too.
    p2 = tmp_path / "held_by_nobody.txt"
    p2.write_text("y")
    assert find_file_holders(str(p2)) == []
    assert find_file_holders(str(tmp_path / "does_not_exist.bin")) == []

    # probe FAILURE is never silent — a load failure yields a named
    # probe_error dict, never an empty list (hüküm-disiplini)
    def _no_rm(*a, **k):
        raise OSError(2, "no rstrtmgr")

    monkeypatch.setattr(ctypes, "WinDLL", _no_rm)
    failed = find_file_holders(str(p2))
    assert failed and "probe_error" in failed[0]
