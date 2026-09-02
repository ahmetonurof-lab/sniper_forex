#!/usr/bin/env python
"""PHASE 7 — AUDIT CHAIN + SAFETY MONITOR — synthetic unit tests.

Covers:
- AuditChain.append: basic + typed event
- AuditChain.append_event: pre-built event
- AuditChain.events: read-only snapshot
- AuditChain.__len__: length reflects appends
- AuditChain.clear: empties
- AuditChain.save+load: round-trip preserves all events
- AuditChain.save: atomic (tmp+rename)
- AuditEvent.to_dict: event_type -> str
- SafetyMonitor.check: clean (all checks pass) -> allowed=True
- SafetyMonitor.check: KILL_SWITCH -> blocked
- SafetyMonitor.check: STALE_DATA (old candle) -> blocked
- SafetyMonitor.check: STALE_DATA (no candle) -> blocked
- SafetyMonitor.check: CONNECTION down -> blocked
- SafetyMonitor.check: SPREAD too high -> blocked
- SafetyMonitor.check: RECONCILIATION not OK -> blocked
- SafetyMonitor.check: fails on first failing check (order respected)
- SafetyMonitor.check: reconciliation None does NOT block
- SafetyDecision: checks list aligns with SafetyCheck enum order
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from src.live.audit import AuditChain, AuditEvent, EventType
from src.live.reconciliation import (
    ReconcileStatus,
    ReconciliationDecision,
)
from src.live.safety import SafetyCheck, SafetyMonitor

# ── AuditChain ──────────────────────────────────────────────────


def test_audit_chain_append_basic():
    chain = AuditChain()
    e = chain.append(time.time(), EventType.SIGNAL, "EURUSD", {"entry": 1.1})
    assert isinstance(e, AuditEvent)
    assert e.event_type == EventType.SIGNAL
    assert e.symbol == "EURUSD"
    assert e.payload == {"entry": 1.1}
    assert len(chain) == 1


def test_audit_chain_append_pre_built_event():
    chain = AuditChain()
    evt = AuditEvent(
        timestamp=1.0,
        event_type=EventType.ORDER,
        symbol="GBPUSD",
        payload={"ticket": 42},
    )
    chain.append_event(evt)
    assert len(chain) == 1
    assert chain.events[0].event_type == EventType.ORDER
    assert chain.events[0].payload["ticket"] == 42


def test_audit_chain_events_returns_snapshot():
    chain = AuditChain()
    chain.append(time.time(), EventType.SIGNAL, "EURUSD")
    snap = chain.events
    # Snapshot must be a copy (mutating the list doesn't affect chain)
    snap.clear()
    assert len(chain) == 1


def test_audit_chain_clear():
    chain = AuditChain()
    chain.append(time.time(), EventType.SIGNAL, "EURUSD")
    chain.append(time.time(), EventType.RISK, "EURUSD")
    assert len(chain) == 2
    chain.clear()
    assert len(chain) == 0


def test_audit_event_to_dict_serializes_enum_as_string():
    evt = AuditEvent(
        timestamp=1.0,
        event_type=EventType.FILL,
        symbol="EURUSD",
        payload={"price": 1.1, "ticket": 1},
    )
    d = evt.to_dict()
    assert d["event_type"] == "FILL"
    assert d["symbol"] == "EURUSD"
    assert d["payload"]["price"] == 1.1
    # JSON-serializable
    json.dumps(d)


def test_audit_chain_save_load_roundtrip(tmp_path: Path):
    chain = AuditChain()
    ts = time.time()
    chain.append(ts, EventType.CANDLE, "EURUSD", {"close": 1.1})
    chain.append(ts + 0.1, EventType.SIGNAL, "EURUSD", {"entry": 1.1})
    chain.append(ts + 0.2, EventType.FILL, "EURUSD", {"ticket": 1})
    path = str(tmp_path / "audit.jsonl")
    chain.save(path)

    assert os.path.exists(path)
    # Each line is a self-contained JSON object
    with open(path, "r", encoding="utf-8") as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    assert len(lines) == 3
    obj = json.loads(lines[0])
    assert obj["event_type"] == "CANDLE"

    # Load into a fresh chain
    chain2 = AuditChain()
    n = chain2.load(path)
    assert n == 3
    assert len(chain2) == 3
    assert chain2.events[2].event_type == EventType.FILL


def test_audit_chain_load_missing_file_returns_zero(tmp_path: Path):
    chain = AuditChain()
    n = chain.load(str(tmp_path / "does_not_exist.jsonl"))
    assert n == 0
    assert len(chain) == 0


def test_audit_save_no_tmp_leftover_and_recovers(tmp_path: Path, monkeypatch):
    """N2 #15: audit save uses a PID-unique tmp + retry.

    - After a successful save no *.tmp sibling remains (the secondary
      WinError 5 crash site, audit.py:184).
    - A transient PermissionError on the rename is retried and the save
      still lands the full event set on disk.
    """
    chain = AuditChain()
    ts = time.time()
    chain.append(ts, EventType.CANDLE, "EURUSD", {"close": 1.1})
    path = str(tmp_path / "audit.jsonl")
    chain.save(path)
    assert os.path.exists(path)
    leftovers = [f.name for f in tmp_path.iterdir() if f.name.endswith(".tmp")]
    assert leftovers == [], f"leftover tmp files: {leftovers}"

    # Transient rename failure -> retried -> success.
    real_replace = Path.replace
    calls = {"n": 0}

    def flaky_replace(self, target, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(5, "Access is denied")
        return real_replace(self, target, *a, **k)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    chain2 = AuditChain()
    chain2.append(ts, EventType.SIGNAL, "EURUSD", {"entry": 1.1})
    chain2.save(path)
    lines = [ln for ln in Path(path).read_text().splitlines() if ln.strip()]
    assert any('"event_type": "SIGNAL"' in ln for ln in lines)


def test_audit_chain_load_skips_malformed_lines(tmp_path: Path):
    path = tmp_path / "audit.jsonl"
    path.write_text(
        '{"timestamp": 1.0, "event_type": "CANDLE"}\n'
        "NOT JSON\n"
        '{"timestamp": 2.0, "event_type": "SIGNAL", "symbol": "EURUSD"}\n',
        encoding="utf-8",
    )
    chain = AuditChain()
    n = chain.load(str(path))
    assert n == 2  # malformed skipped
    assert chain.events[0].event_type == EventType.CANDLE
    assert chain.events[1].event_type == EventType.SIGNAL


# ── SafetyMonitor: clean ────────────────────────────────────────


def test_safety_check_all_clean_allowed():
    mon = SafetyMonitor()
    now = 1000.0
    d = mon.check(
        kill_switch=False,
        connection_ok=True,
        last_candle_time=now - 60.0,  # 1 min old -> fresh
        now=now,
        spread_points=10.0,
        reconciliation=ReconciliationDecision(status=ReconcileStatus.OK),
    )
    assert d.allowed is True
    assert d.is_clean is True
    assert d.failing_check is None
    assert d.reason == ""
    assert d.checks == [True, True, True, True, True]


# ── Per-check failure ───────────────────────────────────────────


def test_safety_kill_switch_blocks():
    mon = SafetyMonitor()
    d = mon.check(
        kill_switch=True,
        connection_ok=True,
        last_candle_time=time.time() - 60.0,
        spread_points=10.0,
        reconciliation=ReconciliationDecision(status=ReconcileStatus.OK),
    )
    assert d.allowed is False
    assert d.failing_check == SafetyCheck.KILL_SWITCH
    assert "kill switch" in d.reason.lower()


def test_safety_stale_data_old_candle_blocks():
    mon = SafetyMonitor(stale_seconds=30.0 * 60.0)
    now = 10000.0
    d = mon.check(
        connection_ok=True,
        last_candle_time=now - (40.0 * 60.0),  # 40 min old > 30 min threshold
        now=now,
        spread_points=10.0,
        reconciliation=ReconciliationDecision(status=ReconcileStatus.OK),
    )
    assert d.allowed is False
    assert d.failing_check == SafetyCheck.STALE_DATA
    assert "candle age" in d.reason.lower() or "stale" in d.reason.lower()


def test_safety_stale_data_no_candle_blocks():
    mon = SafetyMonitor()
    d = mon.check(
        connection_ok=True,
        last_candle_time=None,  # no data yet
        spread_points=10.0,
        reconciliation=ReconciliationDecision(status=ReconcileStatus.OK),
    )
    assert d.allowed is False
    assert d.failing_check == SafetyCheck.STALE_DATA


def test_safety_connection_down_blocks():
    mon = SafetyMonitor()
    d = mon.check(
        connection_ok=False,
        last_candle_time=time.time() - 60.0,
        spread_points=10.0,
        reconciliation=ReconciliationDecision(status=ReconcileStatus.OK),
    )
    assert d.allowed is False
    assert d.failing_check == SafetyCheck.CONNECTION


def test_safety_spread_too_high_blocks():
    mon = SafetyMonitor(max_spread_points=30.0)
    d = mon.check(
        connection_ok=True,
        last_candle_time=time.time() - 60.0,
        spread_points=50.0,
        reconciliation=ReconciliationDecision(status=ReconcileStatus.OK),
    )
    assert d.allowed is False
    assert d.failing_check == SafetyCheck.SPREAD
    assert "spread" in d.reason.lower()


def test_safety_reconciliation_not_ok_blocks():
    mon = SafetyMonitor()
    bad = ReconciliationDecision(
        status=ReconcileStatus.ORPHAN,
        orphans=[1],
        block_trading=True,
    )
    d = mon.check(
        connection_ok=True,
        last_candle_time=time.time() - 60.0,
        spread_points=10.0,
        reconciliation=bad,
    )
    assert d.allowed is False
    assert d.failing_check == SafetyCheck.RECONCILIATION


def test_safety_reconciliation_none_does_not_block():
    """First tick before any reconciliation: do NOT block (initial state)."""
    mon = SafetyMonitor()
    d = mon.check(
        connection_ok=True,
        last_candle_time=time.time() - 60.0,
        spread_points=10.0,
        reconciliation=None,
    )
    assert d.allowed is True
    assert d.checks[-1] is True  # RECONCILIATION = True (None -> ok)


# ── Compound failures + order ───────────────────────────────────


def test_safety_first_failing_check_reported_by_severity():
    """When multiple checks fail, the first in `_CHECK_ORDER` is reported."""
    mon = SafetyMonitor()
    now = 1000.0
    d = mon.check(
        kill_switch=True,  # 1st
        connection_ok=False,  # 3rd
        last_candle_time=None,  # 2nd
        now=now,
        spread_points=999.0,  # 4th
        reconciliation=ReconciliationDecision(status=ReconcileStatus.MISMATCH),  # 5th
    )
    assert d.allowed is False
    # KILL_SWITCH is first in severity order
    assert d.failing_check == SafetyCheck.KILL_SWITCH


def test_safety_checks_list_aligned_with_enum():
    """`checks` list order matches SafetyCheck order (KILL..RECONCILE)."""
    mon = SafetyMonitor()
    d = mon.check()
    assert len(d.checks) == len(list(SafetyCheck))
    # If we make a check fail deliberately, that index becomes False
    d_fail = mon.check(
        connection_ok=False,
        last_candle_time=time.time(),
        spread_points=0.0,
    )
    # CONNECTION is index 2
    assert d_fail.checks[2] is False
    # Other checks pass (kill switch off, candle fresh, spread ok, recon None)
    assert d_fail.checks[0] is True
    assert d_fail.checks[1] is True
    assert d_fail.checks[3] is True
    assert d_fail.checks[4] is True


def test_safety_spread_at_threshold_allows():
    """Spread == max_spread_points is allowed (boundary)."""
    mon = SafetyMonitor(max_spread_points=30.0)
    d = mon.check(
        connection_ok=True,
        last_candle_time=time.time() - 60.0,
        spread_points=30.0,  # exactly at threshold
        reconciliation=ReconciliationDecision(status=ReconcileStatus.OK),
    )
    assert d.allowed is True
    assert d.checks[3] is True
