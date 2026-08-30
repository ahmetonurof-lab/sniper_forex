"""Shared test helpers (Taş 4 seremoni: cross-import resolution).

`FakeRunner` and `kill_after` previously lived only in
test_orchestrator_tas3.py and were imported across test modules
(`from tests.test_orchestrator_tas3 import ...`), which depends on
tests/ being a package. Moving them here kills that packaging question.
"""

from types import SimpleNamespace

import pytest


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
