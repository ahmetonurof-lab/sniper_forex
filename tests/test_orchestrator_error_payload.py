"""A1 (OBS-P0 karar-kilidi EK-2): ERROR payload'unda gercek exception type +
sinirli traceback kalici olmali.

Kirmizi-test-once disiplini:
- fix oncesi ``error_payload`` audit.py'de YOK -> import FAIL (red).
- fix oncesi emit-site'ler yalniz ``str(e)`` tasiyor -> ``error_type``/
  ``traceback`` assert'leri FAIL (red).
Crypto-audit iddiasindan bagimsiz, guncel Forex kodu uzerinden kanit:
16 ERROR emit noktasinin tamaminda traceback yoktu (DECISION_OBSERVABILITY_P0
2026-09-09, 4). Buradaki testler o koruk noktayi kapatir.
"""

from __future__ import annotations

from src.live.audit import AuditChain, EventType, error_payload

# ── Helper birim semantigi ────────────────────────────────────


def test_error_payload_carries_type_message_and_traceback():
    try:
        raise ValueError("boom-123")
    except ValueError as e:
        p = error_payload(e, phase="unit")
    assert p["error_type"] == "ValueError"
    assert p["error"] == "boom-123"
    assert "traceback" in p
    assert "ValueError: boom-123" in p["traceback"]
    # taban payload alanlari korunur
    assert p["phase"] == "unit"


def test_error_payload_traceback_is_bounded():
    def deep(n):
        if n:
            deep(n - 1)
        raise RuntimeError("deep-boom")

    try:
        deep(60)
    except RuntimeError as e:
        p = error_payload(e, tb_limit=4)
    # format_exception 'File ...' kare satirlari; limit ~kare sayisini sinirlar
    frames = p["traceback"].count('File "')
    assert frames <= 6, f"traceback sinirsiz kaldi: {frames} kare"


def test_error_payload_preserves_extra_fields():
    try:
        raise KeyError("k1")
    except KeyError as e:
        p = error_payload(e, phase="poll", consecutive_errors=3)
    assert p["phase"] == "poll"
    assert p["consecutive_errors"] == 3
    assert p["error_type"] == "KeyError"


def test_error_payload_does_not_mutate_when_error_given_explicitly():
    try:
        raise ValueError("orig")
    except ValueError as e:
        p = error_payload(e, error="override")
    assert p["error"] == "override"  # setdefault: cagiranin degeri kazanir
    assert p["error_type"] == "ValueError"


# ── Emit-site entegrasyonu: gercek _wire_live_logging degraded yolu ──


def test_wire_live_logging_degraded_error_has_traceback(tmp_path, monkeypatch):
    """_wire_live_logging hatasinda yazilan ERROR artik exception-type +
    traceback tasimali (str(e)-only degil). Gercek üretim kod-yolu (§3/§4.2)."""
    from src.live.orchestrator import Orchestrator

    o = Orchestrator(state_dir=str(tmp_path / "state"))
    o.audit = AuditChain()  # gercek spy'suz chain -> .events okunabilir
    o._symbol = "EURUSD"

    def _boom(*a, **k):
        raise OSError("no console for you")

    monkeypatch.setattr("src.live.orchestrator.ConsoleReporter", _boom)
    o._wire_live_logging()  # hata yakalanir -> degraded ERROR emit
    errs = [e for e in o.audit.events if e.event_type == EventType.ERROR]
    assert errs, "wiring-failure ERROR event'i beklenir"
    p = errs[-1].payload
    assert p["phase"] == "live_logging_init"
    assert p["status"] == "degraded"
    assert p.get("error_type") == "OSError", f"error_type yok: {p}"
    assert "no console for you" in p.get("traceback", ""), f"traceback yok: {p}"
