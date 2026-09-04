"""N2 #17 acceptance tests — lock in-place write + dual-instance guard.

T0#5/T0#6 forensics FALSIFIED the AV-race hypothesis: T0#6 crashed with
the SAME WinError 5 rename signature WHILE the Defender exclusion was
ACTIVE (Event-5007 @ 18:05:16, boot 18:15, crash ~18:23). Hakem's N2 #17
spec changes the LOCK write strategy:

  ANA-FIX  Lock._write is IN-PLACE (open/truncate/write/fsync) — the
           rename-overwrite mechanism is removed from the lock hot path.
           K1 retry ladder + K3 on_block contract PRESERVED (N2 #15-b
           semantics survive on the new mechanism).
  K2       _atomic_write_text (audit/state/safe-mode files still rename-
           based) routes an exhausted budget to state/crash_log.txt
           BEFORE re-raising — the flush-independent forensic floor for
           the T0#5/T0#6 terminal-event blind spot. Gated by the frozen
           boolean _ATOMIC_WRITE_RUNTIME=False (rollback/diagnostic
           switch, pinned by tests).
  EK-FIX   run_production.main() dual-instance pre-guard: an existing
           lock whose owner PID is ALIVE (Hakem spec verbatim — no
           self-PID exemption) exits with code 0 BEFORE any heavy
           construction. Stale/corrupt/dead-PID locks stay on the
           canonical takeover path.
  DIAG     Lock._write appends a one-shot writer_diagnostic (self + parent
           process identity) to the crash log — Hakem's dual-instance
           probe: two writer_diagnostic lines with run_production argv in
           one boot log == dual-instance CONFIRMED.

D35 ownership semantics are UNCHANGED: _owned gating, PID-in-lock
verification, PID-dead takeover, LOCK_STALE_SEC window.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from src.live import atomic_write as aw_mod
from src.live import orchestrator as orch_mod
from src.live import run_production as rp_mod
from src.live.orchestrator import _ATOMIC_WRITE_RUNTIME, Lock, _atomic_write_text


def _fail_lock_opens(monkeypatch, fail_times: int) -> dict:
    """Route PermissionError(5) at LOCK-file opens only (first N times).

    Other opens (the K2 crash-log append inside the writer diagnostic,
    pytest internals) pass through to the real os.open untouched.
    """
    real_open = os.open
    calls = {"n": 0}

    def flaky_open(path, flags, *a, **k):
        if str(path).endswith("orchestrator.lock") and calls["n"] < fail_times:
            calls["n"] += 1
            raise PermissionError(5, "Access is denied")
        return real_open(path, flags, *a, **k)

    monkeypatch.setattr(os, "open", flaky_open)
    monkeypatch.setattr(orch_mod.time, "sleep", lambda s: None)
    return calls


@pytest.fixture
def crash_log(tmp_path, monkeypatch) -> Path:
    """Explicit crash-log redirect for tests that READ the log.

    N2 #21 madde-8: the K2 floor lives in atomic_write.py — patch the
    canonical location (and the orchestrator re-export) together."""
    log = tmp_path / "crash_log.txt"
    monkeypatch.setattr(orch_mod, "_CRASH_LOG", log)
    monkeypatch.setattr(aw_mod, "_CRASH_LOG", log)
    return log


# ══════════════════════════════════════════════════════════════════
# ANA-FIX — Lock._write is in-place (no tmp, no rename)
# ══════════════════════════════════════════════════════════════════


class TestLockInplaceWrite:
    def test_acquire_and_heartbeats_leave_no_tmp_siblings(self, tmp_path):
        """The lock path must not create tmp siblings at all — the rename
        mechanism is gone, so there is nothing to clean up."""
        lock = Lock(tmp_path / "orchestrator.lock")
        lock.acquire()
        lock.heartbeat()
        lock.heartbeat()
        leftovers = [f.name for f in tmp_path.iterdir() if f.name.endswith(".tmp")]
        assert leftovers == []

    def test_lock_content_is_our_pid_after_heartbeat(self, tmp_path):
        lock = Lock(tmp_path / "orchestrator.lock")
        lock.acquire()
        lock.heartbeat()
        data = json.loads((tmp_path / "orchestrator.lock").read_text(encoding="utf-8"))
        assert data["pid"] == os.getpid()
        assert data["created_at"] > 0

    def test_heartbeat_recovers_from_transient_open_permission_error(self, tmp_path, monkeypatch):
        """K1 semantics on the new mechanism: one transient WinError 5 at
        the in-place open is retried and the heartbeat succeeds."""
        lock = Lock(tmp_path / "orchestrator.lock")
        lock.acquire()
        calls = _fail_lock_opens(monkeypatch, fail_times=1)
        lock.heartbeat()  # must not raise
        assert calls["n"] == 1
        data = json.loads((tmp_path / "orchestrator.lock").read_text(encoding="utf-8"))
        assert data["pid"] == os.getpid()

    def test_heartbeat_exhaustion_nonfatal_but_write_raises(self, tmp_path, monkeypatch):
        """N2 #17 Katman-4 (FIX-SPEC v1.2): heartbeat exhaustion is
        NONFATAL (degraded latch, retry next tick — liveness is an
        advertisement, not trade-book integrity), while the K1 ladder
        itself still raises from _write() — both facets stay pinned.
        K3 fires exactly once per _write call, with the lock target."""
        seen: list = []
        lock = Lock(tmp_path / "orchestrator.lock", on_block=seen.append)
        lock.acquire()
        _fail_lock_opens(monkeypatch, fail_times=10**9)
        # Policy: the heartbeat survives exhaustion.
        lock.heartbeat()
        assert lock._write_degraded is True
        assert len(seen) == 1
        # Mechanism: the write itself still fails hard (D35 evidence).
        with pytest.raises(PermissionError):
            lock._write()
        assert len(seen) == 2
        assert seen[0]["file"].endswith("orchestrator.lock")
        assert seen[0]["retries"] == orch_mod._TMP_WRITE_RETRIES
        assert "PermissionError" in seen[0]["error"]

    def test_heartbeat_backoff_budget_under_stale_window(self, tmp_path, monkeypatch):
        """§7.4 invariant on the in-place path: worst-case total sleep is
        the shared 6.35s budget (0.7% of LOCK_STALE_SEC=900)."""
        sleeps: list = []
        lock = Lock(tmp_path / "orchestrator.lock")
        lock.acquire()
        real_open = os.open

        def always_fail(path, flags, *a, **k):
            if str(path).endswith("orchestrator.lock"):
                raise PermissionError(5, "Access is denied")
            return real_open(path, flags, *a, **k)

        monkeypatch.setattr(os, "open", always_fail)
        monkeypatch.setattr(orch_mod.time, "sleep", sleeps.append)
        # N2 #17 Katman-4: the ladder now lives under _write() (the
        # heartbeat wraps it nonfatally) — the budget is pinned there.
        with pytest.raises(PermissionError):
            lock._write()
        total = sum(sleeps)
        assert total == pytest.approx(6.35)
        assert total < orch_mod.LOCK_STALE_SEC

    def test_writer_diagnostic_appended_exactly_once(self, crash_log):
        """DIAG: the first successful write appends the writer_diagnostic
        line (self + parent identity); the heartbeat must not repeat it."""
        lock = Lock(crash_log.parent / "orchestrator.lock")
        lock.acquire()
        lock.heartbeat()
        lines = [json.loads(l) for l in crash_log.read_text(encoding="utf-8").splitlines()]
        diag = [l for l in lines if l["kind"] == "writer_diagnostic"]
        assert len(diag) == 1
        assert diag[0]["self"].startswith(f"{os.getpid()}:")
        assert diag[0]["parent"]  # parent identity field present


# ══════════════════════════════════════════════════════════════════
# K2 — crash-log forensics on the rename-based shared helper
# ══════════════════════════════════════════════════════════════════


class TestK2CrashLog:
    def test_exhaustion_appends_crash_log_before_raise(self, tmp_path, monkeypatch, crash_log):
        """The T0#5/T0#6 blind spot: terminal audit events were lost when
        the audit flush itself was blocked. The K2 append is flush-
        independent and must land before the raise."""
        monkeypatch.setattr(
            Path,
            "replace",
            lambda *a, **k: (_ for _ in ()).throw(PermissionError(5, "denied")),
        )
        monkeypatch.setattr(time, "sleep", lambda s: None)
        with pytest.raises(PermissionError):
            _atomic_write_text(tmp_path / "x.json", "x")
        lines = [json.loads(l) for l in crash_log.read_text(encoding="utf-8").splitlines()]
        assert lines[-1]["kind"] == "atomic_write_exhausted"
        assert lines[-1]["file"].endswith("x.json")
        assert lines[-1]["retries"] == orch_mod._TMP_WRITE_RETRIES

    def test_runtime_true_skips_crash_log(self, tmp_path, monkeypatch, crash_log):
        """The frozen boolean is the diagnostic/rollback switch: when it is
        True the K2 append is skipped (legacy posture, forensics off).

        N2 #21 madde-8: the flag lives in atomic_write.py (the primitive
        reads its own module global) — patch the canonical location."""
        monkeypatch.setattr(aw_mod, "_ATOMIC_WRITE_RUNTIME", True)
        monkeypatch.setattr(
            Path,
            "replace",
            lambda *a, **k: (_ for _ in ()).throw(PermissionError(5, "denied")),
        )
        monkeypatch.setattr(time, "sleep", lambda s: None)
        with pytest.raises(PermissionError):
            _atomic_write_text(tmp_path / "x.json", "x")
        assert not crash_log.exists()

    def test_runtime_flag_frozen_false(self):
        """Production posture: K2 crash-log routing is ACTIVE. Flipping
        this must be an explicit, reviewed decision — never silent."""
        assert _ATOMIC_WRITE_RUNTIME is False
        # N2 #21 madde-8: the orchestrator re-exports the SAME flag object
        # from the primitive module — one pin covers both names.
        assert aw_mod._ATOMIC_WRITE_RUNTIME is _ATOMIC_WRITE_RUNTIME

    def test_crash_log_append_never_raises(self, tmp_path, monkeypatch):
        """Forensics must never mask the original failure nor break the
        caller — even with the log itself unwritable."""

        def boom(*a, **k):
            raise OSError(5, "Access is denied")

        monkeypatch.setattr(os, "open", boom)
        orch_mod._crash_log_append(tmp_path / "c.txt", {"kind": "x"})  # no raise


# ══════════════════════════════════════════════════════════════════
# EK-FIX — dual-instance pre-guard in run_production.main()
# ══════════════════════════════════════════════════════════════════


def _seed_lock(state_dir: Path, payload: str) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / "orchestrator.lock"
    lock_path.write_text(payload, encoding="utf-8")
    return lock_path


class _StopHere(Exception):
    pass


class _FakeOrch:
    def __init__(self, *a, **k):
        raise _StopHere("passed the guard")


class TestDualInstanceGuard:
    def test_main_exits_zero_when_live_owner_holds_lock(self, tmp_path, monkeypatch, capsys):
        """A second instance under a live owner exits 0 BEFORE MT5 — the
        dual-process lock-write contention can never be reached."""
        state_dir = tmp_path / "state"
        _seed_lock(
            state_dir,
            json.dumps({"pid": os.getpid(), "created_at": time.time(), "phase": "x"}),
        )
        monkeypatch.setenv("SNIPER_STATE_DIR", str(state_dir))

        class _MustNotConstruct:
            def __init__(self, *a, **k):
                raise AssertionError("MT5Connection built despite live lock owner")

        monkeypatch.setattr(rp_mod, "MT5Connection", _MustNotConstruct)
        assert rp_mod.main() == 0
        assert "Already running" in capsys.readouterr().err

    @pytest.mark.parametrize(
        "payload",
        [
            '{"pid": 999999, "created_at": 1, "phase": "x"}',  # dead PID
            "not json at all",  # corrupt
        ],
        ids=["dead-pid", "corrupt"],
    )
    def test_main_proceeds_when_lock_not_live(self, tmp_path, monkeypatch, payload):
        """Stale (dead-PID) and corrupt locks stay on the canonical
        Lock/PID-dead-takeover path — the guard must not swallow them."""
        state_dir = tmp_path / "state"
        _seed_lock(state_dir, payload)
        monkeypatch.setenv("SNIPER_STATE_DIR", str(state_dir))
        monkeypatch.setattr(rp_mod, "MT5Connection", lambda: object())
        monkeypatch.setattr(rp_mod, "Orchestrator", _FakeOrch)
        with pytest.raises(_StopHere):
            rp_mod.main()

    def test_main_proceeds_when_no_lock(self, tmp_path, monkeypatch):
        state_dir = tmp_path / "state"
        monkeypatch.setenv("SNIPER_STATE_DIR", str(state_dir))
        monkeypatch.setattr(rp_mod, "MT5Connection", lambda: object())
        monkeypatch.setattr(rp_mod, "Orchestrator", _FakeOrch)
        with pytest.raises(_StopHere):
            rp_mod.main()
