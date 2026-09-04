#!/usr/bin/env python
"""N2 #23 — R-3 SIGNAL payload ŞEMA testi (sentetik-şema-testi; İCRA-SIRASI adım-1).

PRE-REG: results/N2_23_prereg_R3_R1.md v1.1 (Hakem RATIFY-WITH-NOTES +
AM-N23-1; Reis charter-✓). Şema KOD'u sabitler (schema-first):
    {"symbol","side","entry","sl","tp","reason","ts","fvg_id"} — KAPALI set.

Sentetik koşum GERÇEK StrategyRuntime yolu: warmup(160) → replay(101..159)
→ bearish sweep(160) → ralli → bearish FVG(real=165) → touch(166) →
fill(167) = TEK Signal. Geometri gerçek kodda kalibre edildi
(state/n2_23_scratch_scenario.py, 2026-09-04): body [1.10000,1.10200],
ATR 0.00210 → sweep-tol 0.00105, poke 1.10530, EQ → gap-high 1.10475,
nexus inside-bar şartı (166.l < 165.l), min-size 0.06·ATR < 0.00040,
MIN_RISK_DIST ok. Kısıtlar gerçek kodda doğrulandı.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from experiment.config import TP_RR
from src.live.strategy_runtime import StrategyRuntime, signal_audit_payload
from src.strategy.models import Bar

T0 = pd.Timestamp("2026-01-02 19:00:00")  # Cuma 19:00 UTC — CBDR pencere-başı
WARM = 160
REPLAY_FROM = 101
EXPECTED_ZONE_INDEX = 165
EXPECTED_ENTRY_BAR = 167

# k -> (open, high, low, close)
SCENARIO: dict = {
    160: (1.10300, 1.10530, 1.10195, 1.10195),  # sweep: poke > 1.10305; close < body_high
    161: (1.10195, 1.10305, 1.10190, 1.10300),
    162: (1.10300, 1.10425, 1.10295, 1.10420),
    163: (1.10420, 1.10525, 1.10415, 1.10520),
    164: (1.10520, 1.10605, 1.10515, 1.10600),  # ralli tepesi; l(164) = FVG top
    165: (1.10580, 1.10585, 1.10355, 1.10360),  # FVG orta mumu (166.l < 165.l şartı)
    166: (1.10470, 1.10475, 1.10350, 1.10350),  # gap-bar + touch (high == FVG bottom)
    167: (1.10300, 1.10310, 1.10180, 1.10200),  # fill bar (open = entry)
}

EXPECTED_KEYS = {"symbol", "side", "entry", "sl", "tp", "reason", "ts", "fvg_id"}


def _base_bar(k: int) -> Bar:
    """Düz-ritim barlar: body [1.10000,1.10200] alternating; asla sweep, asla FVG."""
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


def _run_scenario():
    """GERÇEK StrategyRuntime yolu: warmup → replay → senaryo. Tek Signal döner."""
    rt = StrategyRuntime("TEST")
    rt.warmup([_base_bar(k) for k in range(WARM)])
    assert rt._warmed, "warmup 160 bar ile başarılı olmalı"
    signals: list = []
    for k in range(REPLAY_FROM, EXPECTED_ENTRY_BAR + 1):
        bar = _scenario_bar(k) if k in SCENARIO else _base_bar(k)
        sig = rt.on_bar(bar)
        if sig is not None:
            signals.append(sig)
    return rt, signals


def test_scenario_produces_exactly_one_signal():
    """Sentetik koşum gerçek runtime'da TEK Signal üretmeli (şema-zemini)."""
    rt, signals = _run_scenario()
    assert len(signals) == 1, f"tek Signal beklenir; geldi: {len(signals)}"
    sig = signals[0]
    assert sig.side == "short"
    assert sig.direction == "bearish"
    assert sig.entry_bar_index == EXPECTED_ENTRY_BAR
    assert sig.sweep_bar_index == 160
    assert sig.zone_index == EXPECTED_ZONE_INDEX
    assert sig.entry_price == pytest.approx(1.10300)
    # fill sonrası trade aktif, sweep tüketildi (canonical parity)
    assert rt.active_trade is not None
    assert rt.sweep_detected is False


def test_signal_payload_schema_pins_prereg_contract():
    """R-3 şeması KAPALI set — gerçek-runtime Signal'i üzerinden sabitlenir."""
    _, signals = _run_scenario()
    assert len(signals) == 1
    sig = signals[0]
    payload = signal_audit_payload(sig)

    assert (
        set(payload.keys()) == EXPECTED_KEYS
    ), f"R-3 SIGNAL payload şeması pre-reg ile çelişiyor: {sorted(payload.keys())}"
    # değer-tutarlılığı: payload, gerçek Signal alanlarının birebir yansıması
    assert payload["symbol"] == sig.symbol == "TEST"
    assert payload["side"] == sig.side == "short"
    assert payload["entry"] == sig.entry_price == pytest.approx(1.10300)
    # kalibre-ölçülen değerler (scratch-koşumu, gerçek-kod): sl = zone_top +
    # 0.1·SL_ATR_MULT·ATR ≈ 1.1054483, tp = entry − 1.8·rd ≈ 1.0985931
    assert payload["sl"] == sig.sl == pytest.approx(1.10545, rel=1e-5)
    assert payload["tp"] == sig.tp == pytest.approx(1.09859, rel=1e-5)
    # short ilişki kuralı: tp = entry − TP_RR·(sl−entry) (engine sabiti)
    assert payload["tp"] == pytest.approx(sig.entry_price - TP_RR * (sig.sl - sig.entry_price))
    assert isinstance(payload["reason"], str) and payload["reason"]
    # ts: ISO-çözümlenebilir (audit JSONL round-trip güvenliği)
    assert pd.Timestamp(payload["ts"]) == sig.timestamp
    # fvg_id (Hakem AM-v1.1): trace-bağlanabilirliği — sembol + zone kimliği
    assert payload["fvg_id"] == f"{sig.symbol}:zone{sig.zone_index}"
    assert str(EXPECTED_ZONE_INDEX) in payload["fvg_id"]


def test_signal_payload_json_serializable_roundtrip():
    """Audit save() json.dumps(default=str) kullanır — şema round-trip'e dayanmalı."""
    _, signals = _run_scenario()
    assert len(signals) == 1
    payload = signal_audit_payload(signals[0])
    roundtrip = json.loads(json.dumps(payload))
    assert set(roundtrip.keys()) == EXPECTED_KEYS
    assert roundtrip["side"] == "short"
    assert roundtrip["entry"] == pytest.approx(1.10300)
    assert roundtrip["fvg_id"]
    assert roundtrip["ts"]
