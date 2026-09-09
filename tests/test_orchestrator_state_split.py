"""SOAK-EYE-1 (Hakem-kararı 2026-09-09): §7.2 state/entry ayrıştırma testleri.

Kanonik iddia: gate CLOSED iken bile state-advancement (CBDR/sweep/V6/FVG)
ilerler; entry-execution (runner.on_bar → risk/execution) gate'e bağlı
kalır. Testler gerçek run() döngüsünü ve gerçek _advance_state_only
seam'ini çalıştırır (fake-duplicate değil, §4.2).
"""

from __future__ import annotations

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


@pytest.fixture(autouse=True)
def identity_tz(monkeypatch):
    """tas3 deseni: server→UTC kayması test clock'uyla bar yaşını
    sahteleştirmesin (gate stale olmasın) — no-op. Canlı bar üretimi
    SignalRunner._rates_to_bars üzerinden geçtiği için HER İKİ modül de
    patch'lenir (orchestrator fallback yolu, signal_runner kanonik yolu)."""
    monkeypatch.setattr("src.live.orchestrator.server_to_utc_historical", lambda dt: dt)
    monkeypatch.setattr("src.live.signal_runner.server_to_utc_historical", lambda dt: dt)


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


RATES_15 = m1_rates([ep(12, m) for m in range(0, 15)])  # slot 12:00 closed


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

    def shutdown(self):
        pass


class FakeRunner:
    """Entry path — on_bar çağrılırsa ENTRY açılmış sayılır (kayıt tutar)."""

    def __init__(self):
        self.on_bar_calls = []
        self.poll_calls = 0
        self.trailing_calls = 0
        self.result = SimpleNamespace(
            order_sent=False,
            fill=None,
            context_registered=None,
            approved=False,
            blocked_reason="no_signal",
        )
        self.poll_result = []

    def on_bar(self, bar, account):
        self.on_bar_calls.append((bar, account))
        return self.result

    def poll_deals(self):
        self.poll_calls += 1
        return list(self.poll_result)

    def sync_trailing(self):
        self.trailing_calls += 1
        return []


class FakeStateRuntime:
    """StrategyRuntime seam'i: on_bar'ı kaydeder, signal üretebilir."""

    def __init__(self, signal=False, boom=False):
        self.bars = []
        self._next_idx = 0
        self._warmed = True
        self.active_trade = None
        self.on_bar_calls = []
        self._signal = signal
        self._boom = boom

    def on_bar(self, bar):
        if self._boom:
            raise RuntimeError("boom")
        self.on_bar_calls.append(bar)
        return SimpleNamespace(symbol="EURUSD") if self._signal else None


def make_orch(tmp_path, runner=None, verdict=StartupVerdict.PROCEED, recon="OK"):
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
        mt5=FakeMT5(),
        mt5_conn=FakeConn(),
    )
    orch._now_fn = lambda: NOW
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
    orch.lock.acquire()
    orch._sleeps = []
    return orch


def kill_after(n):
    state = {"i": 0}

    def fn():
        state["i"] += 1
        return state["i"] > n

    return fn


# ── run()-döngüsü: gate CLOSED → state yürür, entry YÜRÜMEZ ─────────


def test_safe_start_advances_state_but_never_entries(tmp_path):
    """SOAK-EYE-1 çekirdek kanıtı: SAFE_START'ta bar geldi → runtime.on_bar
    ÇAĞRILIR (motor ilerler), runner.on_bar ÇAĞRILMAZ (para risksiz)."""
    r = FakeRunner()
    rt = FakeStateRuntime()
    orch = make_orch(tmp_path, runner=r, verdict=StartupVerdict.SAFE_START, recon="MISMATCH")
    orch._runtime = rt
    orch.run(kill_switch_fn=kill_after(1), sleep_fn=lambda s: None)
    assert len(rt.on_bar_calls) >= 1  # §7.2: state advanced despite closed gate
    assert r.on_bar_calls == []  # entry-execution stays gated (para-riski yok)
    assert orch._pending_feed == []  # backlog state yoluyla tüketildi


def test_proceed_path_unchanged_entries_run_state_via_runner(tmp_path):
    """Davranış-nötrlük (gate-OPEN): runner.on_bar tek-ilerleme-yoludur;
    state-ayak ÇAĞRILMAZ (if/elif exactly-once — çift-ilerleme yok)."""
    r = FakeRunner()
    rt = FakeStateRuntime()
    orch = make_orch(tmp_path, runner=r)  # PROCEED + recon OK
    orch._runtime = rt
    orch.run(kill_switch_fn=kill_after(1), sleep_fn=lambda s: None)
    assert len(r.on_bar_calls) >= 1
    assert rt.on_bar_calls == []  # entry-yolu runtime'ı kendi içinde ilerletir


# ── _advance_state_only birim semantiği ─────────────────────────────


def test_state_foot_discarded_signal_is_visible(tmp_path):
    """Gate kapalıyken üretilen signal ATILIR ama GÖRÜNÜRDÜR (SIGNAL audit,
    signals_discarded>0) — sessizlik yok (R-3 census dersi)."""
    rt = FakeStateRuntime(signal=True)
    orch = make_orch(tmp_path, runner=None, verdict=StartupVerdict.SAFE_START, recon="MISMATCH")
    orch._runtime = rt
    code = orch._advance_state_only([object(), object()])
    assert code is None
    assert len(rt.on_bar_calls) == 2
    sig_events = [
        e.payload
        for e in orch.audit.events
        if e.event_type == EventType.SIGNAL and e.payload.get("phase") == "state_only"
    ]
    assert sig_events and sig_events[-1]["signals_discarded"] == 2


def test_state_foot_exception_keeps_d6_semantics(tmp_path):
    """Strategy exception → D6 ile birebir: safe-mode persist + ERROR audit
    + CRITICAL alert + exit 2 (döngü düşmez, kontrollü durur)."""
    rt = FakeStateRuntime(boom=True)
    orch = make_orch(tmp_path, runner=None, verdict=StartupVerdict.SAFE_START, recon="MISMATCH")
    orch._runtime = rt
    code = orch._advance_state_only([object()])
    assert code == 2
    saved = SafeModeStore(str(orch.state_dir)).load()
    assert saved is not None and "strategy_exception" in saved["reason"]
    assert any(e.event_type == EventType.ERROR for e in orch.audit.events)


def test_state_foot_skips_when_runtime_not_warmed(tmp_path):
    """on_new_bar guard'ı korunur: _warmed=False → sessiz no-op (güvenlik)."""
    rt = FakeStateRuntime()
    rt._warmed = False
    orch = make_orch(tmp_path, runner=None, verdict=StartupVerdict.SAFE_START, recon="MISMATCH")
    orch._runtime = rt
    code = orch._advance_state_only([object()])
    assert code is None
    assert rt.on_bar_calls == []
