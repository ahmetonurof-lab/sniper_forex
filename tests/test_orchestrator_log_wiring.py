"""DEBT-W1 wiring acceptance: orchestrator ← log modules (D129 B.1-B.4).

Scope (commit-message kanıtı, commit 521c7f0):
  "Known debt: DEBT-W1 wiring (connect modules to Orchestrator/LiveRunner)
   mandatory before Step-C"

Wired modules (§2.2 — reuse, no parallel mechanisms):
  - console_reporter.ConsoleReporter  → gate-transition line (dedup'lu)
  - canli_trade_log.setup_canli_trade_log → daily file `logs/canli_trade_YYYY-MM-DD.log`
  - trade_history.TradeHistoryWriter + make_trade_record → exit records (JSONL)
  - audit_rotation paths              → log_dir resolution (daily audit layer)

Tests exercise the REAL production path: Orchestrator.run() loop with the
tas3 fixture pattern (FakeConn/FakeMT5/FakeRunner) — no fake wiring layer.
"""

import logging
from types import SimpleNamespace

import pytest
from test_orchestrator_tas3 import FakeRunner, kill_after, make_orch

from src.live.audit import EventType
from src.live.canli_trade_log import current_daily_path


@pytest.fixture(autouse=True)
def identity_tz(monkeypatch):
    monkeypatch.setattr("src.live.signal_runner.server_to_utc_historical", lambda dt: dt)


@pytest.fixture(autouse=True)
def _clean_canli_logger():
    """Singleton guard: setup_canli_trade_log early-returns when handlers
    exist. Tests must reset the logger BEFORE and AFTER each case, so a
    stale handler pointing at another tmp log_dir never survives (its
    stream would silently write to the PREVIOUS test's file)."""

    def _reset():
        lg = logging.getLogger("sniper_forex.canli_trade")
        for h in list(lg.handlers):
            try:
                h.close()
            except Exception:
                pass
        lg.handlers.clear()

    _reset()
    yield
    _reset()


def ctx_like(position_id=555, side="long", entry=1.10000, sl=1.09900):
    """Lifecycle OpenTradeContext-like object (duck-typed fields only)."""
    return SimpleNamespace(
        position_id=position_id,
        symbol="EURUSD",
        side=side,
        entry_price=entry,
        initial_sl=sl,
        filled_volume=0.01,
        initial_risk_cash_total=12.0,
        realized_r_accumulated=0.0,
    )


def exit_deal(deal_id=1, position_id=555, status="recorded", cash=-12.0, pnl_r=-1.0):
    return {
        "deal_id": deal_id,
        "position_id": position_id,
        "status": status,
        "cash": cash,
        "pnl_r": pnl_r,
    }


def read_canli_log(tmp_path):
    p = current_daily_path(str(tmp_path / "logs"))
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def read_trade_history(tmp_path):
    p = tmp_path / "logs" / "trade_history.json"
    if not p.exists():
        return []
    import json

    with open(p, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# ── 1. gate transition → canli log + console ────────────────────────


def test_gate_transition_writes_canli_log_line(tmp_path):
    orch = make_orch(tmp_path, runner=FakeRunner())
    orch.run(kill_switch_fn=kill_after(1), sleep_fn=lambda s: None)
    text = read_canli_log(tmp_path)
    # PROCEED verdict: first tick transitions None -> OPEN
    assert "GATE" in text and "OPEN" in text


def test_gate_line_contains_reason(tmp_path):
    orch = make_orch(tmp_path, runner=FakeRunner())
    orch.run(kill_switch_fn=kill_after(1), sleep_fn=lambda s: None)
    text = read_canli_log(tmp_path)
    assert "GATE OPEN" in text


# ── 2. exit deal → canli log + trade_history record ────────────────


def test_exit_deal_logged_and_recorded(tmp_path):
    r = FakeRunner()
    r.lifecycle = SimpleNamespace(open_trades={555: ctx_like()})
    r.poll_result = [exit_deal()]
    orch = make_orch(tmp_path, runner=r)
    orch.run(kill_switch_fn=kill_after(1), sleep_fn=lambda s: None)

    text = read_canli_log(tmp_path)
    assert "EXIT" in text and "555" in text

    records = read_trade_history(tmp_path)
    assert len(records) == 1  # seed-poll + tick-poll → dedup'd to ONE
    rec = records[0]
    assert rec["symbol"] == "EURUSD"
    assert rec["direction"] == "LONG"
    assert rec["r_realized"] == pytest.approx(-1.0)
    assert rec["initial_sl"] == pytest.approx(1.09900)
    assert rec["exit"]["reason"] == "unknown"  # exit trigger not in poll payload
    assert rec["source"] == "DEBT-W1-wiring"


def test_exit_deal_line_logged_once_across_polls(tmp_path):
    r = FakeRunner()
    r.lifecycle = SimpleNamespace(open_trades={555: ctx_like()})
    r.poll_result = [exit_deal()]
    orch = make_orch(tmp_path, runner=r)
    orch.run(kill_switch_fn=kill_after(2), sleep_fn=lambda s: None)
    text = read_canli_log(tmp_path)
    assert text.count("EXIT") == 1  # 3 polls (seed + 2 ticks), dedup'd


def test_quarantined_exit_logged_but_not_recorded(tmp_path):
    r = FakeRunner()
    r.lifecycle = SimpleNamespace(open_trades={})  # unmapped position
    r.poll_result = [exit_deal(deal_id=9, position_id=999, status="quarantined")]
    orch = make_orch(tmp_path, runner=r)
    orch.run(kill_switch_fn=kill_after(1), sleep_fn=lambda s: None)
    assert "EXIT" in read_canli_log(tmp_path)  # line still logged (honest)
    assert read_trade_history(tmp_path) == []  # no trade record (no ctx)


# ── 3. shutdown → final line ────────────────────────────────────────


def test_shutdown_line_logged(tmp_path):
    orch = make_orch(tmp_path, runner=FakeRunner())
    orch.run(kill_switch_fn=kill_after(1), sleep_fn=lambda s: None)
    text = read_canli_log(tmp_path)
    assert "SHUTDOWN" in text and "exit=0" in text


# ── 4. wiring init: audit event + log_dir resolution ───────────────


def test_wiring_init_audit_event(tmp_path):
    orch = make_orch(tmp_path, runner=FakeRunner())
    orch.run(kill_switch_fn=kill_after(1), sleep_fn=lambda s: None)
    init_events = [
        e
        for e in orch.audit.events
        if e.event_type == EventType.STARTUP and e.payload.get("phase") == "live_logging_init"
    ]
    assert len(init_events) == 1


def test_log_dir_default_resolves_to_state_sibling(tmp_path):
    orch = make_orch(tmp_path, runner=FakeRunner())
    orch.run(kill_switch_fn=kill_after(1), sleep_fn=lambda s: None)
    assert str(orch._log_dir) == str(tmp_path / "logs")
    # TradeHistoryWriter is lazy: the JSONL file appears on first write(),
    # but the wired path must already resolve to the log-dir convention.
    assert orch._trade_writer is not None
    assert str(orch._trade_writer._path) == str(tmp_path / "logs" / "trade_history.json")
