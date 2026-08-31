"""D53 acceptance: TelegramAlert transport + visible console fallback.

Referee spec (binding):
  - urllib POST sendMessage, timeout <= 3 s, try/except -> NEVER raises
    (the trading loop must not be blocked or broken by alerting).
  - env TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID -> TelegramAlert.
  - otherwise ConsoleAlert fallback + exactly ONE audit WARN
    (silent fallback forbidden - S5 lesson).
"""

import urllib.request

import pytest

from src.live.audit import AuditChain, EventType
from src.live.orchestrator import (
    ConsoleAlert,
    Orchestrator,
    TelegramAlert,
    _build_alert_transport,
)


@pytest.fixture(autouse=True)
def _clean_telegram_env(monkeypatch):
    """Production .env has no TELEGRAM keys; guarantee tests don't inherit any."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)


# ── factory selection ───────────────────────────────────────────────


def test_factory_telegram_env_values_bound(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "456")
    alert = _build_alert_transport("SNIPER_ALERT", AuditChain())
    assert isinstance(alert, TelegramAlert)
    assert alert.bot_token == "123:abc"
    assert alert.chat_id == "456"


def test_factory_telegram_no_fallback_warn(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "456")
    audit = AuditChain()
    alert = _build_alert_transport("SNIPER_ALERT", audit)
    assert isinstance(alert, TelegramAlert)
    warn = [
        e
        for e in audit.events
        if e.payload.get("phase") == "alerting" and e.payload.get("verdict") == "CONSOLE_FALLBACK"
    ]
    assert not warn, "configured transport must not emit a fallback WARN"


def test_factory_console_fallback_single_audit_warn():
    audit = AuditChain()
    alert = _build_alert_transport("SNIPER_ALERT", audit)
    assert isinstance(alert, ConsoleAlert)
    assert not isinstance(alert, TelegramAlert)
    warn = [
        e
        for e in audit.events
        if e.payload.get("phase") == "alerting" and e.payload.get("verdict") == "CONSOLE_FALLBACK"
    ]
    assert len(warn) == 1, "fallback must be visible via exactly ONE audit WARN"
    assert warn[0].payload.get("reason") == "telegram_env_unset"
    assert warn[0].event_type == EventType.STARTUP


def test_factory_partial_env_is_fallback(monkeypatch):
    """Half-configured credentials (token XOR chat) must NOT fake Telegram."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    audit = AuditChain()
    alert = _build_alert_transport("SNIPER_ALERT", audit)
    assert not isinstance(alert, TelegramAlert)
    assert any(e.payload.get("phase") == "alerting" for e in audit.events)


# ── orchestrator wiring (production construction path) ─────────────


def test_orchestrator_uses_telegram_when_env_set(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "456")
    orch = Orchestrator(
        state_dir=str(tmp_path / "state"),
        configured_symbols=["EURUSD"],
    )
    assert isinstance(orch.alert, TelegramAlert)


def test_orchestrator_fallback_warn_visible_in_audit(tmp_path):
    orch = Orchestrator(
        state_dir=str(tmp_path / "state"),
        configured_symbols=["EURUSD"],
    )
    assert isinstance(orch.alert, ConsoleAlert)
    assert not isinstance(orch.alert, TelegramAlert)
    warn = [
        e
        for e in orch.audit.events
        if e.payload.get("phase") == "alerting" and e.payload.get("verdict") == "CONSOLE_FALLBACK"
    ]
    assert len(warn) == 1


# ── transport behaviour (patched urlopen - no network) ──────────────


class _Captured:
    def __init__(self):
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append((req, timeout))

        class _Resp:
            def read(self_inner):
                return b'{"ok":true}'

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

        return _Resp()


def test_telegram_posts_correct_url_and_payload(monkeypatch):
    cap = _Captured()
    monkeypatch.setattr(urllib.request, "urlopen", cap)
    alert = TelegramAlert("123:ABC", "999", env="SNIPER_ALERT")
    alert.send("WARN", "hello soak")
    assert len(cap.requests) == 1
    req, timeout = cap.requests[0]
    assert req.full_url == "https://api.telegram.org/bot123:ABC/sendMessage"
    assert req.get_method() == "POST"
    body = req.data.decode("utf-8")
    assert "chat_id=999" in body
    assert "hello+soak" in body
    assert "WARN" in body
    assert timeout <= 3.0, "spec: timeout cap 3s"
    # Console sink stays canonical: entry observable in alert_log.
    assert any(c.msg == "hello soak" and c.level == "WARN" for c in alert.alert_log)


def test_telegram_timeout_never_raises(monkeypatch):
    def _boom(req, timeout=None):
        raise TimeoutError("simulated network stall")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    alert = TelegramAlert("t", "c")
    alert.send("CRITICAL", "ladder fired")  # must NOT raise
    msgs = [(c.level, c.msg) for c in alert.alert_log]
    assert ("CRITICAL", "ladder fired") in msgs
    assert any(
        lvl == "WARN" and "telegram transport disabled" in m for lvl, m in msgs
    ), "degradation must be visible"
    assert alert._dead is True


def test_telegram_exception_never_raises(monkeypatch):
    def _boom(req, timeout=None):
        raise OSError("simulated DNS failure")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    alert = TelegramAlert("t", "c")
    alert.send("WARN", "first")  # must NOT raise
    # One-time disable: second send must not retry the network (no spam).
    calls = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: calls.append(1))
    alert.send("WARN", "second")
    assert calls == [], "disabled transport must stop posting"
    assert any(c.msg == "second" for c in alert.alert_log)  # console keeps flowing


def test_alert_failure_never_raises_integration(tmp_path, monkeypatch):
    """Real Orchestrator seam: a raising transport cannot break send callers."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")

    def _boom(req, timeout=None):
        raise RuntimeError("any network error shape")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    orch = Orchestrator(
        state_dir=str(tmp_path / "state"),
        configured_symbols=["EURUSD"],
    )
    assert isinstance(orch.alert, TelegramAlert)
    orch.alert.send("CRITICAL", "simulated production alert")  # no raise
    assert any("simulated production alert" in c.msg for c in orch.alert.alert_log)


def test_timeout_cap_enforced():
    alert = TelegramAlert("t", "c", timeout_sec=30.0)
    assert alert.timeout_sec <= 3.0
