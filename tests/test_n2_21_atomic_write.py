#!/usr/bin/env python
"""N2 #21 — madde-8 (tek atomic_write modülü) + madde-1 (audit delta-append
+ boot-load) acceptance tests — Hakem dört-nokta-hüküm kanıt-planı.

Kanıt-planı (ruling verbatim, suite-katmanı):
  1. cascade-crash-testi — monkeypatch fault-injection ile (gerçek-branch
     §4.2-uyumlu, mevcut audit-safety testleriyle aynı usul):
     boot → flush-fail → shutdown → boot-2 → load → devamlılık-kanıtı.
  2. torn-line fikstürü (N1-b): torn-son-satır + öncekiler-sağlam →
     öncekiler-kurtarılır.
  3. floor üç-yolda-ateş fikstürü (BULGU-14 tersten-kriteri):
     exhausted-log artık üç-yolda DA-YAZAR (audit-append / state-rename /
     safe-mode-rename; lock-in-place kanadı n2_17'de zaten pinli).

Hüküm referansları: N1 delta-append (5-koşul: a-delta, b-torn, c-tek-writer,
d-fsync-YOK, e-komşu-fonksiyon) · N2 tek-dokunuş (8+1+9A-audit-bacağı;
telemetri AYRI commit) · N3 koruma=kod-değil · N4 üç-yol-tablosu.
Canlı-katman (iki-boot-continuity) Reis-bildirimli, T0#10'da mühürlenir.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from src.live.atomic_write import append_line
from src.live.audit import AuditChain, EventType
from src.live.orchestrator import Orchestrator, OrchestratorConfig
from src.live.state import StateStore


def _boot(tmp_path: Path):
    """A REAL Orchestrator on an isolated state dir + journal path —
    production wiring (config.audit_path → AuditChain → boot-load)."""
    state_dir = tmp_path / "state"
    audit_path = state_dir / "audit.jsonl"
    config = OrchestratorConfig(
        symbols=["EURUSD"],
        state_dir=str(state_dir),
        audit_path=str(audit_path),
    )
    orch = Orchestrator(state_dir=str(state_dir), config_obj=config)
    return orch, audit_path


def _line(ts: float, etype: str, payload: dict) -> str:
    return json.dumps(
        {"timestamp": ts, "event_type": etype, "symbol": "EURUSD", "payload": payload},
        sort_keys=True,
    )


# ══════════════════════════════════════════════════════════════════
# Kanıt-planı-1 — cascade-crash continuity (real boot/shutdown branch)
# ══════════════════════════════════════════════════════════════════


def test_cascade_crash_continuity_real_boot_shutdown_boot(tmp_path, monkeypatch):
    """boot → flush-fail → shutdown → boot-2 → load → devamlılık-kanıtı.

    REAL Orchestrator, REAL shutdown branch (§4.2: production path — no
    fake run()). The flush fault is injected at the append primitive,
    same monkeypatch usul as the existing audit-safety tests."""
    from src.live import audit as audit_mod

    real_append = audit_mod.append_line
    fault = {"fail": False}

    def flaky_append(path, text, *a, **k):
        if fault["fail"]:
            raise PermissionError(5, "Access is denied")
        return real_append(path, text, *a, **k)

    monkeypatch.setattr(audit_mod, "append_line", flaky_append)

    # Boot-1: events flushed to disk (delta includes __init__'s own
    # post-load seam event — they belong to this boot's delta).
    orch1, audit_path = _boot(tmp_path)
    orch1.audit.append(0.0, EventType.STARTUP, "EURUSD", {"phase": "boot1-survivor"})
    orch1.audit.flush()
    n_on_disk = len(orch1.audit)
    lines = audit_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == n_on_disk
    assert "boot1-survivor" in lines[-1]
    orch1.audit.append(1.0, EventType.ERROR, "EURUSD", {"phase": "lost-in-flight-1"})
    orch1.audit.append(2.0, EventType.ERROR, "EURUSD", {"phase": "lost-in-flight-2"})

    # Crash window: the shutdown flush itself fails → A8 fallback dump.
    fault["fail"] = True
    orch1.shutdown(reason="test-crash")
    fault["fail"] = False

    # The flushed lines SURVIVE (the old whole-file tmp+rename overwrite
    # is what erased prior boots' chains — BULGU-1 / D77 / T0#9 κ).
    lines = audit_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == n_on_disk
    assert "boot1-survivor" in lines[-1]
    # The in-flight events died with the process by SOME channel — the
    # K2 crash-log fallback (A8), never silently (§18).
    crash_log = tmp_path / "crash_log.txt"
    assert crash_log.exists()
    dump = crash_log.read_text(encoding="utf-8")
    assert "AUDIT_FALLBACK_DUMP" in dump and "lost-in-flight-1" in dump

    # Boot-2: the journal is LOADED into the fresh chain (madde-1) —
    # prior events rejoin the runtime; the next flush delta-appends
    # AFTER them on disk (no overwrite, no dupe). __init__ also buffers
    # its own post-load events (e.g. the S1 mt5_conn seam warning) —
    # they belong to the new boot's delta and land AFTER the history.
    orch2, audit_path2 = _boot(tmp_path)
    assert audit_path2 == audit_path
    assert any(e.payload.get("phase") == "boot1-survivor" for e in orch2.audit.events)
    orch2.audit.append(3.0, EventType.STARTUP, "EURUSD", {"phase": "boot2"})
    orch2.audit.flush()
    lines2 = [ln for ln in audit_path2.read_text(encoding="utf-8").splitlines() if ln.strip()]
    # Disk holds exactly the chain: loaded history + every post-load event.
    assert len(lines2) == len(orch2.audit)
    assert "boot2" in lines2[-1]
    assert sum("boot1-survivor" in ln for ln in lines2) == 1  # no dupe
    assert sum("lost-in-flight-1" in ln for ln in lines2) == 0  # crashed, not re-flushed


def test_boot_load_initializes_delta_counter(tmp_path):
    """madde-1 (Hakem N1-a): load sonrası sayaç başlar — a fresh boot's
    chain carries the loaded history and appends ONLY new events."""
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    audit_path = state_dir / "audit.jsonl"
    audit_path.write_text(_line(0.0, "CANDLE", {"i": 0}) + "\n", encoding="utf-8")

    orch, _ = _boot(tmp_path)
    # The loaded history is IN the chain (first event = the seed line;
    # __init__ may buffer additional post-load events, e.g. the S1 seam
    # warning — they belong to the new boot's delta, not the history).
    assert orch.audit.events[0].payload["i"] == 0
    orch.audit.append(1.0, EventType.CANDLE, "EURUSD", {"i": 1})
    orch.audit.flush()
    lines = audit_path.read_text(encoding="utf-8").splitlines()
    # Disk holds exactly the chain: 1 loaded line + every post-load event.
    assert len(lines) == len(orch.audit)
    assert json.loads(lines[0])["payload"]["i"] == 0
    assert json.loads(lines[-1])["payload"]["i"] == 1


# ══════════════════════════════════════════════════════════════════
# Kanıt-planı-2 — torn-line tolerance (N1-b)
# ══════════════════════════════════════════════════════════════════


def test_torn_last_line_prior_lines_recovered_then_append_continues(tmp_path):
    """torn-son-satır + öncekiler-sağlam → öncekiler kurtarılır; the next
    append continues AFTER the torn line without merging with it."""
    path = tmp_path / "audit.jsonl"
    torn = _line(3.0, "CANDLE", {"i": 3})[:20]  # truncated mid-JSON, NO newline
    path.write_text(
        _line(1.0, "CANDLE", {"i": 1}) + "\n" + _line(2.0, "CANDLE", {"i": 2}) + "\n" + torn,
        encoding="utf-8",
    )

    chain = AuditChain()
    n = chain.load(str(path))
    assert n == 2  # torn tail dropped, prior lines recovered

    chain.append(4.0, EventType.STARTUP, "EURUSD", {"phase": "after-crash"})
    chain.save(str(path))

    fresh = AuditChain()
    n2 = fresh.load(str(path))
    assert n2 == 3  # 2 recovered + 1 new; the torn line never merged
    assert [e.payload.get("i") for e in fresh.events[:2]] == [1, 2]
    assert fresh.events[2].payload["phase"] == "after-crash"


def test_append_line_repairs_missing_trailing_newline(tmp_path):
    """A torn-but-complete last line (valid JSON, missing "\\n") must not
    merge with the first appended line — append_line repairs it."""
    path = tmp_path / "log.jsonl"
    path.write_text('{"a": 1}', encoding="utf-8")
    append_line(path, '{"b": 2}\n')
    assert path.read_text(encoding="utf-8").splitlines() == ['{"a": 1}', '{"b": 2}']


def test_delta_append_repeated_flush_never_duplicates(tmp_path):
    """Delta-append: a second flush with an empty delta must not rewrite
    or duplicate; later appends land strictly after existing lines."""
    path = tmp_path / "audit.jsonl"
    chain = AuditChain()
    chain.append(0.0, EventType.CANDLE, "EURUSD", {"i": 1})
    chain.append(1.0, EventType.CANDLE, "EURUSD", {"i": 2})
    chain.save(str(path))
    chain.save(str(path))  # empty delta — file untouched
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
    chain.append(2.0, EventType.CANDLE, "EURUSD", {"i": 3})
    chain.save(str(path))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(ln)["payload"]["i"] for ln in lines] == [1, 2, 3]


# ══════════════════════════════════════════════════════════════════
# Kanıt-planı-3 — K2 floor üç-yolda-ateş (BULGU-14 ters-kriteri)
# ══════════════════════════════════════════════════════════════════


def test_floor_fires_audit_append_open_exhausted(tmp_path, monkeypatch):
    """Yol 1/3 AUDIT: an exhausted append open writes the exhausted-log
    to the K2 crash-log AND re-raises (D35) — never a blind death."""
    real_open = os.open

    def deny_audit(path, flags, *a, **k):
        if str(path).endswith("audit.jsonl"):
            raise PermissionError(5, "Access is denied")
        return real_open(path, flags, *a, **k)

    monkeypatch.setattr(os, "open", deny_audit)
    monkeypatch.setattr(time, "sleep", lambda s: None)

    chain = AuditChain()
    chain.append(0.0, EventType.CANDLE, "EURUSD", {"i": 1})
    with pytest.raises(PermissionError):
        chain.save(str(tmp_path / "audit.jsonl"))
    # conftest autouse redirects the K2 floor (atomic_write._CRASH_LOG).
    log = tmp_path / "crash_log.txt"
    assert log.exists()
    entry = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert entry["kind"] == "atomic_write_exhausted"
    assert entry["op"] == "append_open"


def test_floor_fires_state_rename_exhausted(tmp_path, monkeypatch):
    """Yol 2/3 STATE (tmp+rename KALIR — Hakem N4): an exhausted rename
    writes the exhausted-log to the K2 crash-log AND re-raises."""
    monkeypatch.setattr(
        Path, "replace", lambda *a, **k: (_ for _ in ()).throw(PermissionError(5, "denied"))
    )
    monkeypatch.setattr(time, "sleep", lambda s: None)
    store = StateStore(str(tmp_path / "state"))
    with pytest.raises(PermissionError):
        store.save("EURUSD", {"phase": "x"})
    log = tmp_path / "crash_log.txt"
    assert log.exists()
    entry = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert entry["kind"] == "atomic_write_exhausted"


def test_floor_fires_safe_mode_write_exhausted(tmp_path, monkeypatch):
    """Yol 2b/3 SAFE-MODE: the REAL _write_safe_mode branch through the
    shared primitive — exhausted rename → K2 crash-log + re-raise."""
    monkeypatch.setattr(
        Path, "replace", lambda *a, **k: (_ for _ in ()).throw(PermissionError(5, "denied"))
    )
    monkeypatch.setattr(time, "sleep", lambda s: None)
    orch = Orchestrator(state_dir=str(tmp_path / "state"))
    with pytest.raises(PermissionError):
        orch._write_safe_mode("test-reason")
    log = tmp_path / "crash_log.txt"
    assert log.exists()
    entry = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert entry["kind"] == "atomic_write_exhausted"
    assert "safe_mode" in entry["file"]
