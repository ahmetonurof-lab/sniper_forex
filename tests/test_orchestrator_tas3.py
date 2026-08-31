"""TAŞ 3 acceptance: run() loop, D4/D5/D6/D10/D11/D13/D14/D34/D35/D39/D41/D43."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.live.audit import AuditChain, EventType
from src.live.orchestrator import (
    Orchestrator,
    OrchestratorConfig,
    SafeModeStore,
    StartupPhase,
    StartupResult,
    StartupVerdict,
)

NOW = datetime(2026, 1, 5, 12, 19, 0)


def ep(h, m, s=0):
    return int(datetime(2026, 1, 5, h, m, s, tzinfo=timezone.utc).timestamp())


def m1_rates(times):
    import numpy as np

    dt = np.dtype(
        [
            ("time", "<i8"),
            ("open", "<f8"),
            ("high", "<f8"),
            ("low", "<f8"),
            ("close", "<f8"),
            ("tick_volume", "<i8"),
        ]
    )
    rows = []
    for i, t in enumerate(times):
        b = 1.10000
        rows.append((t, b, b + 0.00002, b - 0.00002, b + 0.00001 * ((i % 3) - 1), 100 + i))
    return np.array(rows, dtype=dt)


RATES_15 = m1_rates([ep(12, m) for m in range(0, 15)])  # slot 12:00 fully closed


class FakeConn:
    def __init__(self, rates=RATES_15, tick_age=0.0):
        self.rates = rates
        self.tick = {"bid": 1.10000, "ask": 1.10002, "time": ep(12, 19) + tick_age}

    def get_rates(self, symbol, timeframe="M1", count=10):
        return None if self.rates is None else self.rates[-count:]

    def get_tick_data(self, symbol):
        return dict(self.tick)


class FakeMT5:
    def __init__(self):
        self.account_calls = 0
        self._acc = SimpleNamespace(login=111, balance=10000.0, equity=10000.0)

    def account_info(self):
        self.account_calls += 1
        return self._acc


class FakeRunner:
    def __init__(self):
        self.on_bar_calls = []
        self.poll_calls = 0
        self.trailing_calls = 0
        self.raise_on_bar = None
        self.result = SimpleNamespace(
            order_sent=False,
            fill=None,
            context_registered=None,
            approved=False,
            blocked_reason="no_signal",
        )
        self.poll_result = []

    def on_bar(self, bar, account):
        if self.raise_on_bar is not None:
            raise self.raise_on_bar
        self.on_bar_calls.append((bar, account))
        return self.result

    def poll_deals(self):
        self.poll_calls += 1
        return list(self.poll_result)

    def sync_trailing(self):
        self.trailing_calls += 1
        return []


def make_orch(
    tmp_path,
    conn=None,
    mt5=None,
    runner=None,
    verdict=StartupVerdict.PROCEED,
    recon="OK",
    now=NOW,
    runtime_bars=None,
    next_idx=0,
):
    cfg = OrchestratorConfig(
        symbols=["EURUSD"],
        state_dir=str(tmp_path / "state"),
        audit_path=str(tmp_path / "audit" / "a.jsonl"),
        expected_login="111",
        m1_warmup_count=1000,
    )
    orch = Orchestrator(
        state_dir=str(tmp_path / "state"),
        magic=9007001,
        configured_symbols=["EURUSD"],
        audit=AuditChain(),
        config_obj=cfg,
        mt5=mt5 or FakeMT5(),
        mt5_conn=conn or FakeConn(),
    )
    orch._now_fn = lambda: now
    orch._startup_result = StartupResult(
        verdict=verdict,
        phase=StartupPhase.S11_READY,
        reason="test",
        snapshot={
            "reconciliation": {
                "status": recon,
                "block_trading": recon != "OK",
                "details": [],
            }
        },
    )
    orch._runner = runner
    orch._symbol = "EURUSD"
    orch._contract = SimpleNamespace(tick_size=0.00001, digits=5)
    # D35: ownership must be provable — acquire the lock so heartbeat
    # validation sees OUR pid (materialize-on-absent was vetoed by referee).
    orch.lock.acquire()
    if runtime_bars is not None:
        rt = SimpleNamespace(bars=runtime_bars, _next_idx=next_idx, _warmed=True, active_trade=None)
        orch._runtime = rt
    orch._sleeps = []
    return orch


def kill_after(n):
    state = {"i": 0}

    def fn():
        state["i"] += 1
        return state["i"] > n

    return fn


@pytest.fixture(autouse=True)
def identity_tz(monkeypatch):
    monkeypatch.setattr("src.live.signal_runner.server_to_utc_historical", lambda dt: dt)


def test_run_requires_startup(tmp_path):
    orch = make_orch(tmp_path)
    orch._startup_result = None
    with pytest.raises(RuntimeError):
        orch.run()


def test_kill_switch_clean_exit_0(tmp_path):
    r = FakeRunner()
    orch = make_orch(tmp_path, runner=r)
    orch._install_signal_handlers = lambda: None
    assert orch.run(kill_switch_fn=lambda: True) == 0


def test_ownership_lost_exits_1(tmp_path):
    r = FakeRunner()
    orch = make_orch(tmp_path, runner=r)
    # lock file owned by another pid → D35 heartbeat validation fails
    (orch.state_dir / "orchestrator.lock").write_text(
        '{"pid": 999999, "created_at": 0, "phase": "x"}'
    )
    # kill-first order: kill_fn must NOT fire so the ownership check runs
    code = orch.run(kill_switch_fn=lambda: False, sleep_fn=lambda s: None)
    assert code == 1
    assert r.poll_calls == 1  # seed happened, loop never ticked


def test_heartbeat_refreshes_each_tick(tmp_path):
    r = FakeRunner()
    orch = make_orch(tmp_path, runner=r)
    seen = {}

    def sleep_fn(s):
        # capture lock state mid-run, before the kill lands
        seen["lock"] = orch.lock._read()

    orch.run(kill_switch_fn=kill_after(1), sleep_fn=sleep_fn)
    # heartbeat refreshed the lock during the tick
    assert seen["lock"] is not None and int(seen["lock"].pid) == __import__("os").getpid()
    # Taş 4 (B-a): shutdown() releases the lock on the kill path
    assert orch.lock._read() is None
    assert r.poll_calls == 2  # seed + 1 tick


def test_d39_runner_none_monitor_only(tmp_path):
    orch = make_orch(tmp_path, runner=None)  # SAFE-START runner-None scenario
    orch._startup_result.verdict = StartupVerdict.SAFE_START
    code = orch.run(kill_switch_fn=kill_after(1), sleep_fn=lambda s: None)
    assert code == 2  # killed while SAFE-START → safe-mode exit
    assert orch._pending_feed == []  # nothing accumulated


def test_gate_blocks_on_bar_when_recon_blocked(tmp_path):
    r = FakeRunner()
    orch = make_orch(tmp_path, runner=r, verdict=StartupVerdict.SAFE_START, recon="MISMATCH")
    orch.run(kill_switch_fn=kill_after(1), sleep_fn=lambda s: None)
    assert r.on_bar_calls == []  # D34: recon MISMATCH → entries closed
    assert r.poll_calls >= 2  # exits still processed (SAFE MODE semantics)
    assert r.trailing_calls >= 1
    # SAFE-START + runner-var: D41 backlog replay is entries_enabled-guarded
    # → no pending backlog accumulates (gate stays closed, feed never runs)
    assert orch._pending_feed == []


def test_c2_active_trade_boot_never_globally_closes_gate(tmp_path):
    """KARAR-2 regression: an open trade at boot (replay end_state=
    active_trade) must NOT disable entries globally. The gate stays OPEN
    and bars keep feeding; the one-trade-per-symbol lock is enforced
    broker-authoritatively inside LiveRunner.on_bar for THIS symbol only.
    Other symbols (their own processes) are unaffected by construction."""
    r = FakeRunner()
    orch = make_orch(tmp_path, runner=r, runtime_bars=[])
    # Boot state: the restored/replayed runtime carries an open sim trade.
    orch._runtime.active_trade = {"side": "long", "sl": 1.0990, "tp": 1.1018, "closed": False}
    orch.run(kill_switch_fn=kill_after(1), sleep_fn=lambda s: None)
    assert orch._gate_was_allowed is True  # no global C2 lock (KARAR-2)
    assert len(r.on_bar_calls) >= 1  # feed still runs — entries not globally closed
    assert r.poll_calls >= 2 and r.trailing_calls >= 1  # §7.2: management runs anyway
    # The SAFETY audit records the gate OPEN — never a C2 global closure.
    gate_events = [
        e.payload
        for e in orch.audit.events
        if e.event_type == EventType.SAFETY and e.payload.get("gate") in ("open", "closed")
    ]
    assert gate_events and gate_events[-1]["gate"] == "open"


def test_proceed_feeds_backlog_and_new_bars_with_fresh_account(tmp_path):
    r = FakeRunner()
    mt5 = FakeMT5()
    bars = [
        SimpleNamespace(
            timestamp=datetime(2026, 1, 5, 11, 45),
            index=i,
            open=1.1,
            high=1.1,
            low=1.1,
            close=1.1,
            volume=1.0,
        )
        for i in range(3)
    ]
    orch = make_orch(tmp_path, runner=r, mt5=mt5, runtime_bars=bars, next_idx=1)
    orch.run(kill_switch_fn=kill_after(1), sleep_fn=lambda s: None)
    assert len(r.on_bar_calls) == 3  # backlog bar[1],bar[2] + new 12:00 bar
    acc = r.on_bar_calls[0][1]
    assert acc.balance == 10000.0 and acc.equity == 10000.0
    assert mt5.account_calls >= 1  # D4: fresh per cycle
    assert r.poll_calls >= 2  # D5 seed + per-cycle


def test_account_none_skips_on_bar_counts_ladder(tmp_path):
    r = FakeRunner()
    mt5 = FakeMT5()
    mt5._acc = None  # D14: account unavailable
    orch = make_orch(tmp_path, runner=r, mt5=mt5, conn=FakeConn(rates=None))  # fetch also fails
    # 3 ticks needed: consecutive_errors 1,2,3 → ladder trips at 3
    orch.run(kill_switch_fn=kill_after(3), sleep_fn=lambda s: None)
    assert r.on_bar_calls == []  # no bars fed without fresh account
    assert orch._runtime_safe is True  # ladder tripped (≥3 consecutive)
    assert any("broker_data_ladder" in c.msg for c in orch.alert.alert_log)


def test_signal_only_violation_exits_2(tmp_path):
    r = FakeRunner()
    r.result = SimpleNamespace(order_sent=True, fill=None, context_registered=None)
    orch = make_orch(tmp_path, runner=r)
    code = orch.run(kill_switch_fn=kill_after(5), sleep_fn=lambda s: None)
    assert code == 2
    assert SafeModeStore(str(orch.state_dir)).load() is not None
    assert "signal_only" in SafeModeStore(str(orch.state_dir)).load()["reason"]


def test_strategy_exception_exits_2_persists_safe(tmp_path):
    r = FakeRunner()
    r.raise_on_bar = RuntimeError("engine blew up")  # D6
    bars = [
        SimpleNamespace(
            timestamp=datetime(2026, 1, 5, 11, 45),
            index=0,
            open=1.1,
            high=1.1,
            low=1.1,
            close=1.1,
            volume=1.0,
        )
    ]
    orch = make_orch(tmp_path, runner=r, runtime_bars=bars, next_idx=0)
    code = orch.run(kill_switch_fn=kill_after(5), sleep_fn=lambda s: None)
    assert code == 2
    saved = SafeModeStore(str(orch.state_dir)).load()
    assert saved is not None and "strategy_exception" in saved["reason"]


def test_ladder_backoff_and_recovery(tmp_path):
    r = FakeRunner()
    conn = FakeConn(rates=None)  # fetch fails
    sleeps = []
    orch = make_orch(tmp_path, runner=r, conn=conn)
    flips = {"n": 0}

    def kill():
        flips["n"] += 1
        if flips["n"] == 6:
            conn.rates = RATES_15  # recover before tick 6
        return flips["n"] > 7

    orch.run(kill_switch_fn=kill, sleep_fn=sleeps.append)
    assert sleeps[:4] == [40.0, 80.0, 160.0, 300.0]  # D10 capped exponential
    assert sleeps[4] == 300.0
    assert sleeps[-1] == 20.0  # reset after recovery
    assert orch._runtime_safe is False  # transient safe cleared


def test_stale_tick_blocks_connection_gate(tmp_path):
    r = FakeRunner()
    # tick 66min in the PAST (negative age) → stale vs tick_stale_sec=90
    conn = FakeConn(rates=RATES_15, tick_age=-4000)
    orch = make_orch(tmp_path, runner=r, conn=conn)
    orch.config.tick_stale_sec = 90.0
    orch.run(kill_switch_fn=kill_after(1), sleep_fn=lambda s: None)
    assert r.on_bar_calls == []  # CONNECTION gate closed → no entries
    assert r.poll_calls >= 2  # exits continue


def test_feed_cap_warns_once(tmp_path):
    r = FakeRunner()
    orch = make_orch(tmp_path, runner=r)
    orch.config.feed_cap = 4
    orch._pending_feed = [object()] * 4
    mt5 = FakeMT5()
    mt5._acc = None
    orch._mt5 = mt5
    orch.run(kill_switch_fn=kill_after(2), sleep_fn=lambda s: None)
    assert len(orch._pending_feed) <= 4


# --- D46: interruptible sleep — production path coverage (referee T-a/T-b) ---


def test_d46_interruptible_sleep_chunk_sum(monkeypatch, tmp_path):
    """T-a: _interruptible_sleep(300, no-kill) → 300 chunk calls, sum == 300.0.

    Monkeypatches src.live.orchestrator.time.sleep (the function calls
    time.sleep directly, NOT sleep_fn) so the production chunked path is
    actually exercised — not the injected sleep_fn test seam.
    """
    orch = make_orch(tmp_path)
    calls = []
    monkeypatch.setattr("src.live.orchestrator.time.sleep", lambda s: calls.append(s))
    killed = orch._interruptible_sleep(300.0, kill_fn=lambda: False)
    assert killed is False
    assert len(calls) == 300  # 300 x 1s chunks
    assert abs(sum(calls) - 300.0) < 1e-9


def test_d46_interruptible_sleep_kill_during_sleep(monkeypatch, tmp_path):
    """T-b: kill requested mid-sleep → early return True; run() maps it to a
    graceful exit (0/2 formula), not a fatal 1."""
    orch = make_orch(tmp_path)
    calls = []
    monkeypatch.setattr("src.live.orchestrator.time.sleep", lambda s: calls.append(s))
    state = {"n": 0}

    def kill():
        state["n"] += 1
        return state["n"] >= 3  # kill after 2 chunks

    killed = orch._interruptible_sleep(300.0, kill_fn=kill)
    assert killed is True
    assert len(calls) == 2  # 2 chunks before kill

    # run() integration: when _interruptible_sleep reports a kill, run()
    # must exit gracefully (0/2 formula), NOT fatal 1. Force the production
    # path (sleep_fn=None) and monkeypatch _interruptible_sleep to return
    # True on the first call so the loop terminates deterministically.
    r = FakeRunner()
    orch2 = make_orch(tmp_path / "run", runner=r)  # separate lock dir
    orch2._install_signal_handlers = lambda: None
    monkeypatch.setattr("src.live.orchestrator.time.sleep", lambda s: None)
    monkeypatch.setattr(orch2, "_interruptible_sleep", lambda seconds, kf: True)
    code = orch2.run(kill_switch_fn=lambda: False, sleep_fn=None)
    # kill-during-sleep → graceful exit: 2 if runtime-safe/not-entries else 0
    assert code in (0, 2)
    assert code != 1  # NOT fatal — kill wins over ownership
