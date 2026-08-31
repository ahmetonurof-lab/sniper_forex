"""Shared test helpers (Taş 4 seremoni: cross-import resolution).

`FakeRunner` and `kill_after` previously lived only in
test_orchestrator_tas3.py and were imported across test modules
(`from tests.test_orchestrator_tas3 import ...`), which depends on
tests/ being a package. Moving them here kills that packaging question.
"""

from types import SimpleNamespace

import pytest

# D53 hermeticity guard: the production .env carries real TELEGRAM_*
# credentials and mt5_config loads .env into os.environ at import time
# (during collection, i.e. AFTER this file is imported). A module-level
# pop here would run too late-to-be-useless: it happens before the .env
# load and is then overwritten. The guard must therefore be a
# session-scoped autouse FIXTURE — fixtures run after all imports, so
# the pop sticks for the whole session. Without it, every
# Orchestrator-constructing test would build a live TelegramAlert and
# POST real DMs to the operator. Tests that *want* the env (D53 file)
# inject it per-test via monkeypatch.setenv.


@pytest.fixture(autouse=True, scope="session")
def _no_telegram_env_for_session():
    import os

    saved = {
        k: os.environ.pop(k) for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") if k in os.environ
    }
    yield
    os.environ.update(saved)


class FakeRunner:
    """Minimal SignalRunner stand-in: records on_bar/poll/trailing calls."""

    def __init__(self):
        self.on_bar_calls = []
        self.poll_calls = 0
        self.trailing_calls = 0
        self.poll_result = []

    def on_bar(self, bar, account):
        self.on_bar_calls.append((bar, account))
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
        self.trailing_calls += 1
        return []


def kill_after(n):
    """Kill-switch fn that flips True after n calls (n ticks survive)."""
    state = {"i": 0}

    def fn():
        state["i"] += 1
        return state["i"] > n

    return fn


@pytest.fixture
def fake_runner():
    return FakeRunner()
