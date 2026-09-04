#!/usr/bin/env python
"""N2 #23-b — fvg_armed emit + AM-N23-2/3 testleri (sentetik; pre-reg icra-sırası adım-1).

PRE-REG: results/N2_23b_prereg_fvg_armed.md v1 (D92-ratifiye; Reis-✓ ile icra).
Taahhüt-testleri (GERÇEK StrategyRuntime + GERÇEK LiveRunner zinciri; §4.2):
  T1 lifecycle: sweep-STATE → fvg_armed-STATE → SIGNAL sırası tek-zincirde.
  T2 AM-N23-3: SIGNAL payload KAPALI-set (12 alan) + değer-tutarlılığı.
  T3 AM-N23-2: ts-kanat — satır-ts epoch-float + monoton; bar_ts=içerik-
     momenti, satır-ts=olay-momenti (ayrık-by-design); SIGNAL ts round-trip.
  T4 güvenlik: audit yok → emit-kapalı, akış-değişmez (R-1 desen-paritesi).

Geometri: test_n2_23_emit_schema ile AYNI kalibre senaryo — sweep(160) →
FVG(165) → touch/ARM(166) → fill/SIGNAL(167).
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.live.audit import AuditChain, EventType
from src.live.execution import Execution
from src.live.live_runner import LiveRunner
from src.live.risk import Account
from src.live.strategy_runtime import StrategyRuntime, signal_audit_payload
from src.strategy.models import Bar

T0 = pd.Timestamp("2026-01-02 19:00:00")  # Cuma 19:00 UTC — CBDR pencere-başı
WARM = 160
REPLAY_FROM = 101
EXPECT_ENTRY_BAR = 167

SIGNAL_KEYS = {
    "symbol",
    "side",
    "entry",
    "sl",
    "tp",
    "reason",
    "ts",
    "fvg_id",
    "fvg_top",
    "fvg_bottom",
    "fvg_size_pip",
    "direction",
}
ARMED_KEYS = {
    "moment",
    "fvg_top",
    "fvg_bottom",
    "fvg_size_pip",
    "direction",
    "sweep_bar_index",
    "sweep_price",
    "touch_bar_index",
    "entry_bar_index",
    "sl_pre",
    "bar_ts",
    "bar_index",
}

# k -> (open, high, low, close) — schema-testiyle AYNI geometri
SCENARIO: dict = {
    160: (1.10300, 1.10530, 1.10195, 1.10195),
    161: (1.10195, 1.10305, 1.10190, 1.10300),
    162: (1.10300, 1.10425, 1.10295, 1.10420),
    163: (1.10420, 1.10525, 1.10415, 1.10520),
    164: (1.10520, 1.10605, 1.10515, 1.10600),
    165: (1.10580, 1.10585, 1.10355, 1.10360),
    166: (1.10470, 1.10475, 1.10350, 1.10350),
    167: (1.10300, 1.10310, 1.10180, 1.10200),
}


def _base_bar(k: int) -> Bar:
    """Düz-ritim barlar: asla sweep, asla FVG."""
    if k % 2 == 0:
        o, c, h, l = 1.10000, 1.10200, 1.10205, 1.09995
    else:
        o, c, h, l = 1.10200, 1.10000, 1.10205, 1.09995
    return Bar(
        index=k,
        timestamp=T0 + pd.Timedelta(minutes=15 * k),
        open=o,
        high=h,
        low=l,
        close=c,
        volume=1.0,
    )


def _scenario_bar(k: int) -> Bar:
    o, h, l, c = SCENARIO[k]
    return Bar(
        index=k,
        timestamp=T0 + pd.Timedelta(minutes=15 * k),
        open=o,
        high=h,
        low=l,
        close=c,
        volume=1.0,
    )


def _runner(audit: AuditChain) -> LiveRunner:
    """GERÇEK LiveRunner + StrategyRuntime zinciri (wiring-testi deseni).

    NOT: LiveRunner.__init__ `audit or AuditChain()` falsy-guard'ı nedeniyle
    chain seed'lenir (bkz. test_n2_23_emit_wiring gözlem-notu).
    """
    audit.append(0.0, EventType.STARTUP, "TEST", {"phase": "test_seed"})
    rt = StrategyRuntime("TEST", audit=audit)
    rt.warmup([_base_bar(k) for k in range(WARM)])
    assert rt._warmed
    return LiveRunner(
        symbol="TEST",
        mt5=None,
        execution=Execution(mt5=object(), signal_only=True),
        audit=audit,
        runtime=rt,
        signal_only=True,
    )


def _run_runtime_only() -> tuple[StrategyRuntime, list]:
    """Audit-siz gerçek-koşum → dönen Signal listesi (tek-eleman)."""
    rt = StrategyRuntime("TEST")
    rt.warmup([_base_bar(k) for k in range(WARM)])
    assert rt._warmed
    sigs: list = []
    for k in range(REPLAY_FROM, EXPECT_ENTRY_BAR + 1):
        bar = _scenario_bar(k) if k in SCENARIO else _base_bar(k)
        s = rt.on_bar(bar)
        if s is not None:
            sigs.append(s)
    return rt, sigs


# --- TESTS ---


def test_fvg_armed_lifecycle_sweep_then_armed_then_signal():
    """should [emit sweep STATE then fvg_armed STATE then SIGNAL in order]
    when [the calibrated synthetic cycle flows through real runtime+runner]"""
    chain = AuditChain()
    runner = _runner(chain)
    account = Account(balance=10_000.0, equity=10_000.0)
    for k in range(REPLAY_FROM, EXPECT_ENTRY_BAR + 1):
        bar = _scenario_bar(k) if k in SCENARIO else _base_bar(k)
        runner.on_bar(bar, account)

    states = [e for e in chain.events if e.event_type == EventType.STATE]
    moments = [e.payload["moment"] for e in states]
    armed = [e for e in states if e.payload["moment"] == "fvg_armed"]
    assert len(armed) == 1, f"tek fvg_armed emit beklenir; moments: {moments}"
    assert "sweep" in moments, f"sweep anı yok: {moments}"

    sig_evts = [e for e in chain.events if e.event_type == EventType.SIGNAL]
    assert len(sig_evts) == 1, "tek SIGNAL emit beklenir"
    # sıra: sweep < fvg_armed < SIGNAL (tek-zincirde gözlem)
    assert moments.index("sweep") < moments.index("fvg_armed")
    assert chain.events.index(armed[0]) < chain.events.index(sig_evts[0])

    p = armed[0].payload
    assert set(p.keys()) == ARMED_KEYS, f"armed payload şeması: {sorted(p.keys())}"
    assert p["fvg_top"] == pytest.approx(1.10515)
    assert p["fvg_bottom"] == pytest.approx(1.10475)
    assert p["fvg_size_pip"] == pytest.approx(4.0)
    assert p["direction"] == "bearish"
    assert p["sweep_bar_index"] == 160
    assert p["sweep_price"] == pytest.approx(1.10530)
    assert p["touch_bar_index"] == 166
    assert p["entry_bar_index"] == EXPECT_ENTRY_BAR
    assert p["bar_index"] == 166
    # sl_pre: pre-fill SL tahmini (fh>0 dalı → final sl ile aynı; kalibre-değer)
    assert p["sl_pre"] == pytest.approx(1.1054483, rel=1e-5)


def test_signal_payload_am_n23_3_extended_closed_set():
    """should [pin the 12-field closed SIGNAL schema with fvg measures
    beside fvg_id] when [the real fill Signal is mapped by the builder]"""
    _, sigs = _run_runtime_only()
    assert len(sigs) == 1
    payload = signal_audit_payload(sigs[0])
    assert set(payload.keys()) == SIGNAL_KEYS, f"şema: {sorted(payload.keys())}"
    assert payload["fvg_top"] == sigs[0].zone_top == pytest.approx(1.10515)
    assert payload["fvg_bottom"] == sigs[0].zone_bottom == pytest.approx(1.10475)
    assert payload["fvg_size_pip"] == pytest.approx(4.0)
    assert payload["direction"] == sigs[0].direction == "bearish"
    # fvg_id trace-bağı KALIR (ölçüler id-yanda; AM-N23-3)
    assert payload["fvg_id"] == "TEST:zone165"


def test_am_n23_2_ts_wing_event_time_discipline():
    """should [carry epoch event-ts on every row, keep bar_ts as content
    moment, and round-trip SIGNAL ts] when [the synthetic cycle is audited]"""
    chain = AuditChain()
    runner = _runner(chain)
    account = Account(balance=10_000.0, equity=10_000.0)
    for k in range(REPLAY_FROM, EXPECT_ENTRY_BAR + 1):
        bar = _scenario_bar(k) if k in SCENARIO else _base_bar(k)
        runner.on_bar(bar, account)

    events = [e for e in chain.events if e.event_type in (EventType.STATE, EventType.SIGNAL)]
    assert events, "STATE+SIGNAL satırları beklenir"
    ts_list = [e.timestamp for e in events]
    # AM-N23-2: her satır epoch-float event-ts taşır; zincir monoton-değişmez
    assert all(isinstance(t, float) and t > 0 for t in ts_list)
    assert ts_list == sorted(ts_list), "audit satır-ts monoton-değişmelidir"

    armed = [
        e
        for e in events
        if e.event_type == EventType.STATE and e.payload.get("moment") == "fvg_armed"
    ]
    assert len(armed) == 1
    bar_ts = pd.Timestamp(armed[0].payload["bar_ts"])
    # bar_ts = içerik-momenti (touch bar 166) — replay-semantiği belgeli
    assert bar_ts == T0 + pd.Timedelta(minutes=15 * 166)
    # ayrık-by-design: satır-ts (emit-anı epoch) ≠ bar_ts epoch
    assert abs(armed[0].timestamp - bar_ts.timestamp()) > 60.0

    sig_payload = [e for e in events if e.event_type == EventType.SIGNAL][0].payload
    # SIGNAL ts round-trip: fill-bar içerik-momenti (167)
    assert pd.Timestamp(sig_payload["ts"]) == T0 + pd.Timedelta(minutes=15 * 167)


def test_emit_disabled_without_audit_sink():
    """should [keep flow unchanged and raise nothing] when [no audit sink]"""
    rt, sigs = _run_runtime_only()
    assert rt.audit is None  # emits disabled (R-1 desen-paritesi)
    assert len(sigs) == 1 and sigs[0].entry_bar_index == EXPECT_ENTRY_BAR
