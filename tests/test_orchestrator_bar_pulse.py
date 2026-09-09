"""AM-1 (SOAK-D4): Adım-6 "Why No Signal" bar-pulse birim-testleri.

Kapsam (Hakem-şartı: bar-bazlı, poll-bazlı değil):
- bar-bazlı tetik: boş-tick (new_bars=[]) → pulse-YOK.
- dolu-tick: audit-STATE (moment=bar_pulse) + canli-log-satırı.
- davranış-nötr: gate-reason-hesabı-transition-blok-mantığıyla-uyumlu;
  pulse-gate-akışını-değiştirmez (fail-safe).
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.live.audit import EventType
from src.live.orchestrator import Orchestrator


@pytest.fixture()
def orch(tmp_path):
    """Minimal-orchestrator: log-wired-bayrağı-elde-kurulur; audit-spy."""
    o = Orchestrator(state_dir=str(tmp_path / "state"))
    o._log_wired = True
    o._console = None
    o._canli_log = None  # _canli_info-guard: None → sessiz no-op

    class _SpyAudit:
        def __init__(self):
            self.events = []

        def append(self, ts, event_type, symbol, payload):
            self.events.append(
                SimpleNamespace(timestamp=ts, event_type=event_type, symbol=symbol, payload=payload)
            )

    o.audit = _SpyAudit()
    o._symbol = "EURUSD"
    return o


def _bar(idx: int = 4242):
    return SimpleNamespace(index=idx, timestamp=datetime(2026, 9, 9, 15, 15))


def test_pulse_silent_when_no_new_bars(orch):
    """BAR-BAZLI kanıt: boş-tick (poll'da-new_bar-yok) → pulse-YOK."""
    orch._emit_bar_pulse([], gate_allowed=False, reason="startup_SAFE_START")
    assert orch.audit.events == []  # audit-yazılmadı


def test_pulse_emits_state_event_and_reason(orch):
    """Dolu-tick: STATE bar_pulse-event + reason-taşınır."""
    b = _bar(4242)
    orch._emit_bar_pulse([b], gate_allowed=False, reason="startup_SAFE_START")
    ev = orch.audit.events
    assert len(ev) == 1
    p = ev[0].payload
    assert ev[0].event_type == EventType.STATE
    assert p["moment"] == "bar_pulse"
    assert p["bar_index"] == 4242
    assert p["gate"] == "closed"
    assert p["reason"] == "startup_SAFE_START"


def test_pulse_gate_open_label(orch):
    """gate=OPEN-dalı — reason='ok'-fallback."""
    orch._emit_bar_pulse([_bar(1)], gate_allowed=True, reason="")
    p = orch.audit.events[-1].payload
    assert p["gate"] == "open"
    assert p["reason"] == "ok"


def test_pulse_exception_never_raises(orch, caplog):
    """Fail-safe: audit/canli-log-patlaması-döngüyü-düşürmez."""
    with patch.object(
        type(orch.audit),
        "append",
        side_effect=RuntimeError("boom"),
    ):
        # bozulmamış-akış: exception-yutulur
        orch._emit_bar_pulse([_bar(1)], gate_allowed=False, reason="x")
    assert True  # raise-yok = test-geçti


# ── B1 (OBS-P0, 2026-09-09 karar-kilidi): audit-append `_log_wired`-BAĞIMSIZ ──


def test_pulse_audit_survives_unwired_human_logging(orch):
    """KIRMIZI-TEST B1: insan-logu wiring'i BAŞARISIZ olsa bile (`_log_wired
    =False` — `_wire_live_logging` hatası, orchestrator.py:1233-1241), bar_pulse
    STATE-event'i makine-journal'ına (audit) YAZILMALIDIR. SOAK-D2 sessizliği
    wiring-hatasıyla geri gelmemeli; guard-yarılması §EK-1/K2-B1.
    Konsol/canli-insan-satırı guard'lı kalabilir; audit guard'lı KALAMAZ."""
    orch._log_wired = False  # wiring-failure durumu (canlı-log/console yok)
    orch._console = None
    orch._canli_log = None
    b = _bar(4242)
    orch._emit_bar_pulse([b], gate_allowed=False, reason="startup_SAFE_START")
    ev = orch.audit.events
    assert len(ev) == 1, "audit bar_pulse append'i _log_wired=False iken de olmalı"
    p = ev[0].payload
    assert ev[0].event_type == EventType.STATE
    assert p["moment"] == "bar_pulse"
    assert p["bar_index"] == 4242
    assert p["reason"] == "startup_SAFE_START"


def test_pulse_still_silent_when_unwired_and_no_bars(orch):
    """B1 davranış-nötrlük bekçisi: kural yalnız guard-kaynağını değiştirir —
    bar-YOKSA (boş-tick) `_log_wired` değeri ne olursa olsun pulse-YOK
    (bar-bazlılık, poll-bazlı gürültüye dönüşmez)."""
    orch._log_wired = False
    orch._emit_bar_pulse([], gate_allowed=False, reason="x")
    assert orch.audit.events == []
