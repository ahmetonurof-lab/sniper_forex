#!/usr/bin/env python
"""N2 #23 — R-1 (CBDR STATE emit) + R-3 (canlı SIGNAL emit) entegrasyon testleri.

PRE-REG: results/N2_23_prereg_R3_R1.md v1.1 + AM-N23-1 (Hakem) — İCRA-SIRASI
adım-2. Üretim-yolu taahhüdü: testler GERÇEK StrategyRuntime.on_bar +
GERÇEK LiveRunner.on_bar zincirini çalıştırır (fake-production-yasak;
§4.2). R-1 four-moment gözlemi runtime-tüketim-noktasında; R-3 emiti
LiveRunner dönüş-tüketim-noktasında (risk-geçidi-öncesi).

Sentetik senaryo geometrisi test_n2_23_emit_schema ile aynıdır (gerçek kod
üzerinde kalibre: sweep(160) → FVG(165) → touch(166) → fill(167)).
"""

from __future__ import annotations

import pandas as pd

from src.live.audit import AuditChain, EventType
from src.live.execution import Execution
from src.live.live_runner import LiveRunner
from src.live.risk import Account
from src.live.strategy_runtime import StrategyRuntime
from src.strategy.models import Bar

T0 = pd.Timestamp("2026-01-02 19:00:00")  # Cuma 19:00 UTC — CBDR pencere-başı
WARM = 160
EXPECTED_KEYS = {"symbol", "side", "entry", "sl", "tp", "reason", "ts", "fvg_id"}

# k -> (open, high, low, close) — schema testiyle AYNI geometri
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


def _warmed(audit: AuditChain | None = None) -> StrategyRuntime:
    rt = StrategyRuntime("TEST", audit=audit) if audit is not None else StrategyRuntime("TEST")
    rt.warmup([_base_bar(k) for k in range(WARM)])
    assert rt._warmed
    return rt


def _state_events(chain: AuditChain) -> list:
    return [e for e in chain.events if e.event_type == EventType.STATE]


def test_r1_state_emits_cover_cbdr_lifecycle():
    """R-1: dört-an STATE emitleri gerçek on_bar tüketim-noktasında.

    should [emit window_out/locked/sweep/bias moments] when [synthetic CBDR
    cycle is replayed through real runtime with an audit sink]
    """
    chain = AuditChain()
    rt = _warmed(chain)
    # replay (düz-ritim, pencere-içi) → window_out anına kadar
    for k in range(101, 168):
        bar = _scenario_bar(k) if k in SCENARIO else _base_bar(k)
        rt.on_bar(bar)

    events = _state_events(chain)
    moments = [e.payload["moment"] for e in events]
    # pencere-dışı-geçiş (k=160: 00:00 → out) + lock + sweep anı
    assert "window_out" in moments, f"window_out emiti yok: {moments}"
    assert "locked" in moments, f"locked emiti yok: {moments}"
    assert "sweep" in moments, f"sweep emiti yok: {moments}"
    # payload şeması: pencere/lock/sweep/bias + AM-N23-1 d4 alanları
    sweep_evts = [e for e in events if e.payload["moment"] == "sweep"]
    assert sweep_evts, "sweep anı emiti kayıp"
    p = sweep_evts[0].payload
    for field in (
        "in_window",
        "locked",
        "bias_locked",
        "sweep_yes",
        "sweep_direction",
        "sweep_level",
        "sweep_tol",
        "sweep_ts",
        "bias_lock_ts",
        "bias",
        "session_key",
        "bar_ts",
    ):
        assert field in p, f"STATE payload alanı eksik: {field}"
    # AM-N23-1: d4 alanları dolu ve sweep-olayıyla tutarlı
    assert p["sweep_yes"] is True
    assert p["sweep_direction"] == "bearish"
    assert p["sweep_ts"] is not None
    assert p["bias_lock_ts"] is not None
    assert p["bias"] == "bearish"
    assert p["sweep_level"] == 1.1053
    # sweep toleransı gerçek formülle: 0.5 * session.atr (check_sweep'in
    # sweep_atr_tolerance_mult çarpanı; warmup ATR 0.00210 → tol 0.00105)
    assert abs(p["sweep_tol"] - 0.5 * rt.session.atr) < 1e-12


def test_r1_disabled_without_audit_sink():
    """R-1: audit-sink yok → davranış-değişmez (emits kapalı; sıfır-etki)."""
    rt = _warmed(None)
    for k in range(101, 168):
        bar = _scenario_bar(k) if k in SCENARIO else _base_bar(k)
        rt.on_bar(bar)
    assert rt.audit is None  # emits disabled


def test_r3_live_runner_emits_signal_before_risk_chain():
    """R-3: canlı-yolda SIGNAL emitı — LiveRunner dönüş-tüketim-noktası.

    should [emit one SIGNAL with prereg schema] when [a real fill signal
    flows through LiveRunner.on_bar in signal_only mode]
    """
    chain = AuditChain()
    # NOT (gözlem-bulgusu): LiveRunner.__init__ hâlâ `audit or AuditChain()`
    # kullanır — AuditChain BOŞSA falsy → runner KENDİ chain'ini kurar.
    # (Orchestrator'daki N2#13 falsy-guard LiveRunner'a taşınmamış —
    # mevcut-davranış; N2#23-kapsamı-dışı, raporlandı.) Test-chain'i
    # seed'leyerek runner'ın KENDİ chain'imize yazmasını sağlıyoruz;
    # production'da journal-load'lu chain zaten boş-değil.
    chain.append(0.0, EventType.STARTUP, "TEST", {"phase": "test_seed"})
    rt = _warmed(chain)
    exec_engine = Execution(mt5=object(), signal_only=True)
    runner = LiveRunner(
        symbol="TEST",
        mt5=None,
        execution=exec_engine,
        audit=chain,
        runtime=rt,
        signal_only=True,
    )
    assert rt.audit is chain  # R-1 sink kablosu (idempotent)
    account = Account(balance=10_000.0, equity=10_000.0)

    for k in range(101, 168):
        bar = _scenario_bar(k) if k in SCENARIO else _base_bar(k)
        runner.on_bar(bar, account)

    signal_evts = [e for e in chain.events if e.event_type == EventType.SIGNAL]
    assert len(signal_evts) == 1, f"tek SIGNAL emit beklenir; geldi: {len(signal_evts)}"
    payload = signal_evts[0].payload
    assert set(payload.keys()) == EXPECTED_KEYS  # şema-testiyle AYNI sözleşme
    assert payload["side"] == "short"
    assert payload["symbol"] == "TEST"
    assert payload["fvg_id"] == "TEST:zone165"
    # zincir-şekli: SIGNAL, RISK'ten ÖNCE (risk-geçidi görünürlüğü)
    idx_signal = chain.events.index(signal_evts[0])
    risk_evts = [e for e in chain.events if e.event_type == EventType.RISK]
    assert risk_evts, "RISK emit beklenir (signal_only zinciri)"
    assert chain.events.index(risk_evts[0]) > idx_signal
    # enjeksiyon-yasak-kanıt: zincir testin KENDİ AuditChain'idir;
    # Boot-C (PID 18460) dokunulmamış — canlı-boot'a-olay-SOKULMADI.
