"""N2 #15-b acceptance tests (K1 retry budget + K3 WRITE_BLOCK forensic event).

T0#4 forensics: the N2 #15 PID-unique tmp fix cleared the *contention*
layer (crash trace showed ``orchestrator.lock.<pid>.tmp``), but the rename
still died with WinError 5 on BOTH the lock and the audit target in one
window — a transient EXTERNAL handle (AV/Defender on-access scan) locking
the TARGET file. The original ~0.35s retry budget was too small for a
seconds-long scan handle.

This module locks in the two-part fix:

  K1  retry budget raised 3→8 (~6.4s worst case, still 0.7% of
      LOCK_STALE_SEC=900 — §7.4 invariant preserved);
  K3  a WRITE_BLOCK audit event fired once per file per blocked write,
      routed through a single forensic sink shared by Lock / AuditChain /
      StateStore (via RuntimeRecovery) / safe-mode writes.

D35 invariant (exhaustion stays fatal) is asserted explicitly: exhausting
the budget re-raises the original OSError and cleans up the tmp sibling —
the retry layer must never launder a real failure into a silent success.

N2 #17: the LIVE LOCK moved to in-place writes (see
test_orchestrator_n2_17.py) — the rename-path tests here now exercise the
audit/state/safe-mode helpers; the lock-path test was retargeted to the
in-place mechanism with identical D35/K3 semantics.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from src.live import audit as audit_mod
from src.live import orchestrator as orch_mod
from src.live import state as state_mod
from src.live.audit import AuditChain, EventType
from src.live.orchestrator import (
    LOCK_STALE_SEC,
    Orchestrator,
)
from src.live.orchestrator import (
    _atomic_write_text as orch_atomic,
)
from src.live.recovery import RuntimeRecovery
from src.live.state import StateStore

# ══════════════════════════════════════════════════════════════════
# K1 — retry budget arithmetic (§7.4 invariant)
# ══════════════════════════════════════════════════════════════════


class TestRetryBudget:
    def test_all_three_helpers_share_budget(self):
        """§2.2: the three local helper copies stay on the same budget."""
        assert audit_mod._TMP_WRITE_RETRIES == 8
        assert orch_mod._TMP_WRITE_RETRIES == 8
        assert state_mod._TMP_WRITE_RETRIES == 8
        assert audit_mod._TMP_RETRY_BASE_SLEEP == 0.05
        assert orch_mod._TMP_RETRY_BASE_SLEEP == 0.05
        assert state_mod._TMP_RETRY_BASE_SLEEP == 0.05

    def test_worst_case_sleep_under_stale_window(self):
        """§7.4: total backoff (0.05·(2^0..2^6)=6.35s) << LOCK_STALE_SEC."""
        retries = orch_mod._TMP_WRITE_RETRIES
        base = orch_mod._TMP_RETRY_BASE_SLEEP
        worst = sum(base * (2**i) for i in range(retries - 1))
        assert worst == pytest.approx(6.35)
        assert worst < LOCK_STALE_SEC
        # and it is a small fraction — the retry layer cannot orphan the lock
        assert worst / LOCK_STALE_SEC < 0.01

    def test_recovers_from_seven_transient_failures(self, tmp_path, monkeypatch):
        """A seconds-long external handle (7 failed renames) is now cleared
        by the raised budget where the old 3-attempt budget died."""
        real_replace = Path.replace
        calls = {"n": 0}

        def flaky(self, target, *a, **k):
            calls["n"] += 1
            if calls["n"] <= 7:  # fails 7×, succeeds on the 8th attempt
                raise PermissionError(5, "Access is denied")
            return real_replace(self, target, *a, **k)

        monkeypatch.setattr(Path, "replace", flaky)
        monkeypatch.setattr(time, "sleep", lambda s: None)  # no real backoff

        target = tmp_path / "f.json"
        orch_atomic(target, '{"ok": true}', encoding="utf-8")
        assert target.exists()
        assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}
        assert calls["n"] == 8
        # PID-unique tmp cleaned up on success
        leftovers = [f.name for f in tmp_path.iterdir() if f.name.endswith(".tmp")]
        assert leftovers == []


# ══════════════════════════════════════════════════════════════════
# D35 invariant — exhaustion stays FATAL (never laundered to success)
# ══════════════════════════════════════════════════════════════════


class TestExhaustionFatal:
    def test_exhaustion_raises_and_cleans_tmp(self, tmp_path, monkeypatch):
        """All 8 renames fail → original OSError re-raised, tmp removed,
        target never created. The retry layer must not hide a real failure."""
        calls = {"n": 0}

        def always_fail(self, target, *a, **k):
            calls["n"] += 1
            raise PermissionError(5, "Access is denied")

        monkeypatch.setattr(Path, "replace", always_fail)
        monkeypatch.setattr(time, "sleep", lambda s: None)

        target = tmp_path / "dead.json"
        with pytest.raises(PermissionError):
            orch_atomic(target, "x", encoding="utf-8")
        assert calls["n"] == orch_mod._TMP_WRITE_RETRIES
        assert not target.exists()
        leftovers = [f.name for f in tmp_path.iterdir() if f.name.endswith(".tmp")]
        assert leftovers == [], f"tmp must be cleaned on exhaustion: {leftovers}"

    def test_exhaustion_fires_on_block_once(self, tmp_path, monkeypatch):
        """The forensic sink fires exactly once per blocked file (the helper
        dedups — one signal per file, not per-retry noise)."""
        monkeypatch.setattr(
            Path, "replace", lambda *a, **k: (_ for _ in ()).throw(PermissionError(5, "denied"))
        )
        monkeypatch.setattr(time, "sleep", lambda s: None)
        seen = []
        target = tmp_path / "dead.json"
        with pytest.raises(PermissionError):
            orch_atomic(target, "x", encoding="utf-8", on_block=lambda info: seen.append(info))
        assert len(seen) == 1  # once per file, not per attempt
        assert seen[0]["retries"] == orch_mod._TMP_WRITE_RETRIES
        assert "PermissionError" in seen[0]["error"]
        assert seen[0]["file"] == str(target)

    def test_on_block_exception_never_masks_original(self, tmp_path, monkeypatch):
        """A crashing forensic sink must not replace the real OSError."""

        def boom(info):
            raise RuntimeError("sink exploded")

        monkeypatch.setattr(
            Path, "replace", lambda *a, **k: (_ for _ in ()).throw(PermissionError(5, "denied"))
        )
        monkeypatch.setattr(time, "sleep", lambda s: None)
        target = tmp_path / "dead.json"
        with pytest.raises(PermissionError):  # NOT RuntimeError
            orch_atomic(target, "x", encoding="utf-8", on_block=boom)


# ══════════════════════════════════════════════════════════════════
# K3 — WRITE_BLOCK sink wiring (single shared forensic sink)
# ══════════════════════════════════════════════════════════════════


class TestSinkWiring:
    def test_orchestrator_wires_lock_and_audit(self, tmp_path):
        """Lock and AuditChain share the Orchestrator's single sink (§2.2)."""
        orch = Orchestrator(state_dir=str(tmp_path / "state"))
        assert orch.lock._on_block is orch._on_write_block
        assert orch.audit.on_block is orch._on_write_block

    def test_recovery_threads_sink_to_state_store(self, tmp_path):
        """RuntimeRecovery forwards on_block to its StateStore so per-symbol
        state saves emit WRITE_BLOCK too."""
        calls = []
        rec = RuntimeRecovery(str(tmp_path / "state"), on_block=lambda i: calls.append(i))
        assert isinstance(rec.store, StateStore)
        assert rec.store.on_block is not None

    def test_state_store_save_uses_sink(self, tmp_path, monkeypatch):
        """A blocked EURUSD.json rename fires the sink exactly once."""
        monkeypatch.setattr(
            Path, "replace", lambda *a, **k: (_ for _ in ()).throw(PermissionError(5, "denied"))
        )
        monkeypatch.setattr(time, "sleep", lambda s: None)
        seen = []
        store = StateStore(str(tmp_path / "state"), on_block=lambda i: seen.append(i))
        with pytest.raises(PermissionError):
            store.save("EURUSD", {"x": 1})
        assert len(seen) == 1  # helper fires once per file
        assert seen[0]["file"].endswith("EURUSD.json")


class TestWriteBlockSink:
    def _orch(self, tmp_path):
        return Orchestrator(state_dir=str(tmp_path / "state"))

    def test_sink_emits_once_per_file(self, tmp_path):
        """The helper fires once per file → exactly one buffered WRITE_BLOCK
        event (no per-retry spam)."""
        orch = self._orch(tmp_path)
        orch._on_write_block({"file": "x.lock", "retries": 8, "error": "PermissionError: 5"})
        wb = [e for e in orch.audit.events if e.event_type == EventType.WRITE_BLOCK]
        assert len(wb) == 1
        assert wb[0].payload["file"] == "x.lock"
        assert wb[0].payload["retries"] == 8
        assert "PermissionError" in wb[0].payload["error"]

    def test_sink_records_distinct_files(self, tmp_path):
        """T0#4 shape: lock AND audit blocked in one window → two events."""
        orch = self._orch(tmp_path)
        orch._on_write_block({"file": "orchestrator.lock", "retries": 8, "error": "e"})
        orch._on_write_block({"file": "audit.jsonl", "retries": 8, "error": "e"})
        files = sorted(
            e.payload["file"] for e in orch.audit.events if e.event_type == EventType.WRITE_BLOCK
        )
        assert files == ["audit.jsonl", "orchestrator.lock"]

    def test_lock_heartbeat_blocked_emits_write_block(self, tmp_path, monkeypatch):
        """End-to-end: a blocked IN-PLACE lock write (N2 #17 mechanism)
        surfaces a WRITE_BLOCK event through the wired sink."""
        orch = self._orch(tmp_path)
        orch.lock.acquire()  # real in-place write, before we poison os.open
        real_open = os.open

        def always_fail(path, flags, *a, **k):
            if str(path).endswith("orchestrator.lock"):
                raise PermissionError(5, "denied")
            return real_open(path, flags, *a, **k)

        monkeypatch.setattr(os, "open", always_fail)
        monkeypatch.setattr(time, "sleep", lambda s: None)
        # N2 #17 Katman-4 (FIX-SPEC v1.2): the heartbeat refresh is
        # NONFATAL — the process lives, the degraded flag latches and
        # the next tick retries. The WRITE_BLOCK evidence contract is
        # UNCHANGED: exactly one event, naming the lock target.
        orch.lock.heartbeat()
        assert orch.lock._write_degraded is True
        wb = [e for e in orch.audit.events if e.event_type == EventType.WRITE_BLOCK]
        assert len(wb) == 1
        assert wb[0].payload["file"].endswith("orchestrator.lock")


# ══════════════════════════════════════════════════════════════════
# K3 — AuditChain self-save re-entrancy guard (T0#4 death-spiral)
# ══════════════════════════════════════════════════════════════════


class TestAuditChainReentrancy:
    def test_write_block_during_save_does_not_recurse(self, tmp_path, monkeypatch):
        """A WRITE_BLOCK append fired from inside save() must NOT trigger a
        nested flush→save recursion; it buffers and lands on the next flush."""
        audit_path = tmp_path / "audit" / "a.jsonl"
        chain = AuditChain(auto_flush_path=str(audit_path), flush_threshold=1, flush_interval_sec=0)
        # Seed one event so save() has content.
        chain.append(time.time(), EventType.STARTUP, "EURUSD", {})
        chain.clear()
        chain.append(time.time(), EventType.STARTUP, "EURUSD", {})

        real_replace = Path.replace
        state = {"n": 0}

        def flaky(self, target, *a, **k):
            state["n"] += 1
            if state["n"] == 1:  # only the first save's rename fails
                raise PermissionError(5, "Access is denied")
            return real_replace(self, target, *a, **k)

        monkeypatch.setattr(Path, "replace", flaky)
        monkeypatch.setattr(time, "sleep", lambda s: None)

        # Wire the sink to append a WRITE_BLOCK event into this same chain.
        def sink(info):
            chain.append(time.time(), EventType.WRITE_BLOCK, None, {"file": info["file"]})

        chain.on_block = sink
        # save() with a transient failure: the sink append must not recurse.
        chain.save(str(audit_path))  # first rename fails → WRITE_BLOCK buffered
        # The buffered WRITE_BLOCK was NOT flushed during save (guard);
        # it is in memory and lands on the next successful flush.
        assert len([e for e in chain.events if e.event_type == EventType.WRITE_BLOCK]) == 1
        # Next flush writes both events to disk.
        chain.flush()
        lines = [json.loads(l) for l in audit_path.read_text(encoding="utf-8").splitlines()]
        types = [l["event_type"] for l in lines]
        assert EventType.WRITE_BLOCK.value in types

    def test_saving_flag_resets_after_success(self, tmp_path):
        """_saving must be False again after a clean save (no sticky guard)."""
        audit_path = tmp_path / "a.jsonl"
        chain = AuditChain(auto_flush_path=str(audit_path))
        chain.append(time.time(), EventType.STARTUP, "EURUSD", {})
        assert chain._saving is False
        chain.save(str(audit_path))
        assert chain._saving is False

    def test_saving_flag_resets_after_failure(self, tmp_path, monkeypatch):
        """Even when save() raises, the guard is released (finally)."""
        monkeypatch.setattr(
            Path, "replace", lambda *a, **k: (_ for _ in ()).throw(PermissionError(5, "denied"))
        )
        monkeypatch.setattr(time, "sleep", lambda s: None)
        audit_path = tmp_path / "a.jsonl"
        chain = AuditChain(auto_flush_path=str(audit_path))
        chain.append(time.time(), EventType.STARTUP, "EURUSD", {})
        with pytest.raises(PermissionError):
            chain.save(str(audit_path))
        assert chain._saving is False
