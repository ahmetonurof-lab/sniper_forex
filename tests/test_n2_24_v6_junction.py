#!/usr/bin/env python
"""N2 #24 — V6-hibrit junction entegrasyon testleri (GERÇEK StrategyRuntime).

PRE-REG: results/N2_24_v6_hybrid_prod_prereg.md (31a6caf0) §2c/§2d/§4.
Junction-matrisi (D93-birebir-parity hedefi):
    sweep-gün            → V0-aynen (fallback devreye girmez)
    sweep-yok + brk==htf → fallback-kilit (htf_fallback_breakout)
    fallback-sonra-sweep → rollback (V6-kilidi geri alınır; sayaç)
    brk != htf           → ignored (sayac)
    brk == both          → pathological (sayac; beyaz-kutu — aşağıda)
    htf NEUTRAL          → NEUTRAL (breakout işlenmez)

KALİBRASYON (N2#23-aynı; probe-ile doğrulandı 2026-09-05): T0 = 2026-01-02
19:00 UTC (CBDR pencere-başı), WARM=160, düz-ritim body [1.10000,1.10200],
ATR≈0.00210 → tol≈0.00105. Gün-anahtarları (19:00-rollover):
    k=0..95 → 01-03 · k=96..191 → 01-04 · k=192..287 → 01-05 · k=288+ → 01-06
HTF-şekillendirme (SHAPED k=188..191 ayı-düşüş-barları):
    gün-01-05: D-1(01-04) close=1.09500 < PDL(01-03 low=1.09995) → bearish (A)
    gün-01-06: d1=01-05 igne (high≥PDH, close<PDH) → bearish (B)
    gün-01-04: D-2-yok → insufficient → NEUTRAL (NEUTRAL-günü testi bunu kullanır)

AM-N24-2 kanıtı: fallback dali YALNIZ sweep-yok günlerde ulaşılabilir.
AM-N24-3 kanıtı: STATE payload V6 EK-alanları; mevcut 16 alan AYNEN.
PATHOLOGICAL NOTU: BH≥BL invaryantı (body-extremeler aynı bar-kümesinden)
close>BH ∧ close<BL'i gerçek-geometride YAPISAL-İMKANSIZ yapar — FAZ-A3
census: pathological=0 (tüm-sembole, tüm-günler; N2_22_v6*_pass1_census.json).
Dal D93-portunun savunma-koludur; üretim-invaryantı DEĞİŞTİRİLMEDEN, yalnız
test-durumunda BH<BL enjeksiyonu ile birim-kapsanır.
"""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from src.live.audit import AuditChain, EventType
from src.live.strategy_runtime import StrategyRuntime
from src.strategy.models import Bar

# N2#23-aynı kalibrasyon: T0 = CBDR pencere-başı (Cuma 19:00 UTC).
T0 = pd.Timestamp("2026-01-02 19:00:00")
WARM = 160

# HTF-şekillendirme: k=188..191 (gün-01-04 sonu) ayı-düşüş-barları.
SHAPED = {188, 189, 190, 191}

# Sentetik-geometri sabitleri (probe-kalibre; gerçek StrategyRuntime yolu):
#   ayı-breakout → fallback-kilit (sweep_price=bar.low, ref=BL)
#   ayı-sweep (N2#23 poke-geometrisi) → rollback / sweep-kilit
BRK_BEAR = (1.09900, 1.09910, 1.09600, 1.09700)
BRK_BULL = (1.10300, 1.10500, 1.10290, 1.10400)
SWEEP_BEAR = (1.10300, 1.10530, 1.10195, 1.10195)


def _mk_bar(k: int, o: float, h: float, l: float, c: float) -> Bar:
    return Bar(
        index=k,
        timestamp=T0 + pd.Timedelta(minutes=15 * k),
        open=o,
        high=h,
        low=l,
        close=c,
        volume=1.0,
    )


def _base_bar(k: int) -> Bar:
    """Düz-ritim barlar: body [1.10000,1.10200]; asla sweep, asla breakout."""
    if k % 2 == 0:
        o, c, h, l = 1.10000, 1.10200, 1.10205, 1.09995
    else:
        o, c, h, l = 1.10200, 1.10000, 1.10205, 1.09995
    return _mk_bar(k, o, h, l, c)


def _day_bar(k: int) -> Bar:
    """Replay-barı: k=188..191 şekilli (ayı-düşüş); diğerleri düz-ritim."""
    if k in SHAPED:
        return _mk_bar(k, 1.09600, 1.09610, 1.09400, 1.09500)
    return _base_bar(k)


def _warmed(audit: AuditChain | None = None) -> StrategyRuntime:
    rt = StrategyRuntime("TEST", audit=audit) if audit is not None else StrategyRuntime("TEST")
    rt.warmup([_base_bar(k) for k in range(WARM)])
    assert rt._warmed
    return rt


def _replay(rt: StrategyRuntime, lo: int, hi: int) -> None:
    """k=[lo,hi) aralığını gerçek-yolda besler (_day_bar ile)."""
    for k in range(lo, hi):
        rt.on_bar(_day_bar(k))


def _state_events(chain: AuditChain) -> list:
    return [e for e in chain.events if e.event_type == EventType.STATE]


# ── AM-N24-2: fallback-dalı yalnız sweep-yok günlerde ───────────────


def test_am_n24_2_fallback_only_on_sweepless_days():
    """AM-N24-2: fallback-kilit yalnız sweep-yok günlerde kurulur.

    should [lock fallback bias only on sweepless days] when [a sweepless
    day with a conforming breakout and a sweep day are replayed through
    the real runtime]
    """
    rt = _warmed()
    # Gün-01-05 (k=192..287): sweep-yok; ayı-breakout k=220 → fallback-kilit
    _replay(rt, 101, 220)  # k=101..219 (220 hariç)
    rt.on_bar(_mk_bar(220, *BRK_BEAR))  # ayı-breakout → fallback-kilit
    assert rt.session.current_cbdr_key == "2026-01-05"
    assert rt.sweep_detected is False  # sweep-yok gün
    assert rt._v6_est is True
    assert rt._v6_source == "htf_fallback_breakout"
    assert rt._v6_dir == "bearish"
    # Gün-01-06 (k=288..316): sweep-günü — sweep-onay sonrası kaynak sweep
    _replay(rt, 221, 316)
    rt.on_bar(_mk_bar(316, *SWEEP_BEAR))
    assert rt.sweep_detected is True
    assert rt._v6_source == "sweep"  # fallback ASLA sweep-günde
    assert rt._v6_rollback_count == 0  # gün-01-06 fallback-kilitsizdi


def test_am_n24_2_sweep_day_never_fallback():
    """Sweep-gün: V0-aynen — fallback devreye girmez (D93 gate).

    should [keep sweep as sole bias source] when [a sweep is confirmed on
    a day and a further breakout also occurs]
    """
    rt = _warmed()
    _replay(rt, 101, 316)  # gün-01-06'ya kadar; fallback-kilidi YOK
    assert rt.session.current_cbdr_key == "2026-01-06"
    assert rt._v6_est is False  # gün-01-06 henüz kilitlenmedi
    # sweep k=316: session._confirm_sweep → V6 sweep-kaydı (V0-aynen)
    rt.on_bar(_mk_bar(316, *SWEEP_BEAR))
    assert rt.sweep_detected is True
    assert rt.last_sweep is not None
    assert rt._v6_est is True
    assert rt._v6_source == "sweep"
    assert rt._v6_dir == "bearish"
    # aynı gün içinde breakout-barı gelse bile fallback kurulamaz
    # (_v6_est True → fallback-dalı return; D93 sweep-önceliği)
    brk_bar = _mk_bar(317, *BRK_BEAR)
    rt.on_bar(brk_bar)
    assert rt._v6_source == "sweep"  # değişmedi
    assert rt._v6_rollback_count == 0  # sweep-sonrası-sweep yok


# ── Fallback-kilit + rollback matrisi ────────────────────────────────


def test_fallback_lock_then_sweep_rollback():
    """Rollback (D93-aynen): fallback-kilitli-güne sweep gelirse V6-geri-alınır.

    should [revert fallback lock and count rollback] when [a sweep arrives
    on a day already locked by htf_fallback_breakout]
    """
    rt = _warmed()
    _replay(rt, 101, 220)  # gün-01-05: sweep-yok; HTF bearish(A)
    assert rt._htf_dir == "bearish"
    assert rt._htf_senaryo == "A"
    # ayı-breakout k=220 → fallback-kilit (sweep_price=bar.low, ref=BL)
    rt.on_bar(_mk_bar(220, *BRK_BEAR))
    assert rt._v6_est is True
    assert rt._v6_source == "htf_fallback_breakout"
    assert rt._v6_dir == "bearish"
    assert rt._v6_sweep_price == pytest.approx(1.09600)
    assert rt._v6_ref_level == pytest.approx(1.10000)
    # rollback: aynı güne ayı-sweep gelir (D93: V6-kilidi geri alınır)
    rt.on_bar(_mk_bar(221, *SWEEP_BEAR))
    assert rt.sweep_detected is True
    assert rt.last_sweep is not None
    assert rt._v6_source == "sweep"
    assert rt._v6_dir == "bearish"
    assert rt._v6_rollback_count == 1
    assert rt._v6_est is True  # sweep-kilidiyle yeniden est


def test_breakout_against_htf_is_ignored():
    """brk != htf_dir → ignored (sayac; kilit kurulmaz).

    should [count ignored and not lock] when [breakout direction opposes
    the HTF bias]
    """
    rt = _warmed()
    _replay(rt, 101, 220)
    assert rt._htf_dir == "bearish"
    # boğa-breakout (htf=bearish'e ters) → ignored
    rt.on_bar(_mk_bar(220, *BRK_BULL))
    assert rt._v6_est is False
    assert rt._v6_source is None
    assert rt._v6_ignored_count == 1


def test_both_side_breakout_is_pathological():
    """brk == both → pathological (sayac; kilit kurulmaz).

    should [count pathological and not lock] when [a single bar breaks
    both body_high and body_low bands]

    BEYAZ-KUTU NOTU: BH≥BL invaryantı (body-extremeler aynı bar-kümesinden
    birikir) close>BH ∧ close<BL'i gerçek-geometride imkansız kılar —
    FAZ-A3 census: pathological=0 (tüm-sembole). Dal D93-portunun
    savunma-koludur; üretim-invaryantı DEĞİŞTİRİLMEDEN, yalnız testte
    cbdr.body_high'a BH<BL enjeksiyonu ile kapsanır.
    """
    rt = _warmed()
    _replay(rt, 101, 220)
    assert rt.session.cbdr.locked
    # enjeksiyon: BH'yi BL'nin altına çek (yalnız test-durumu; BH<BL)
    rt.session.cbdr.body_high = 1.09000
    # bar: low<BL-tol (1.09895) ve close<BL; high>BH+tol (1.09105) ve close>BH
    brk = _mk_bar(220, 1.09900, 1.09910, 1.09400, 1.09700)
    rt.on_bar(brk)
    assert rt._v6_est is False
    assert rt._v6_source is None
    assert rt._v6_pathological_count == 1


def test_htf_neutral_day_breakout_not_processed():
    """htf NEUTRAL → breakout işlenmez (gün NEUTRAL).

    should [stay neutral] when [HTF bias is None and a breakout occurs]
    """
    rt = _warmed()
    # Şekillendirme-YOK: saf düz-ritim günler D-1 igne-çifti (high≥PDH ∧
    # low≤PDL) üretir → conflict → NEUTRAL (D95-birebir senaryo-dagilimi).
    for k in range(101, 220):
        rt.on_bar(_base_bar(k))
    assert rt._htf_dir is None
    assert rt._htf_senaryo == "conflict"
    rt.on_bar(_mk_bar(220, *BRK_BEAR))
    assert rt._v6_est is False
    assert rt._v6_source is None


# ── STATE-payload: AM-N24-3 (V6 EK-alanları; 16-alan AYNEN) ─────────


def test_state_payload_v6_fields_additive():
    """AM-N24-3: STATE payload V6 EK-alanları; mevcut alanlar AYNEN.

    should [include v6 additive fields] when [a state emit fires on a day
    with fallback lock]
    """
    chain = AuditChain()
    rt = _warmed(chain)
    _replay(rt, 101, 220)  # fallback-kilit k=220 → v6_fallback_lock emit
    rt.on_bar(_mk_bar(220, *BRK_BEAR))
    events = _state_events(chain)
    assert events, "STATE-emiti beklenirdi (v6_fallback_lock)"
    # v6_fallback_lock-momentini hedefle (window_out gibi erken-emitler
    # önce gelebilir; AM-N24-3 kanıtı lock-momentindedir)
    p = next(e.payload for e in events if e.payload.get("moment") == "v6_fallback_lock")
    # mevcut 16-alan AYNEN (D94-AM-N23-1 d4 alanları dahil)
    for field in (
        "moment",
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
        "body_high",
        "body_low",
        "session_key",
        "bar_ts",
        "bar_index",
    ):
        assert field in p, f"mevcut-STATE-alanı eksik: {field}"
    # V6 EK-alanları (aynı payload-dili)
    for field in ("htf_source", "htf_dir", "htf_senaryo", "rollback_count"):
        assert field in p, f"V6-EK-alanı eksik: {field}"
    assert p["htf_source"] == "htf_fallback_breakout"
    assert p["htf_dir"] == "bearish"
    assert p["htf_senaryo"] == "A"
    assert p["rollback_count"] == 0


def test_v6_moments_emitted():
    """v6_fallback_lock + v6_rollback momentleri gerçek-yolda emitedilir.

    should [emit v6 moments] when [fallback lock and rollback occur]
    """
    chain = AuditChain()
    rt = _warmed(chain)
    _replay(rt, 101, 220)
    rt.on_bar(_mk_bar(220, *BRK_BEAR))  # fallback-kilit → v6_fallback_lock
    rt.on_bar(_mk_bar(221, *SWEEP_BEAR))  # sweep → rollback → v6_rollback
    assert rt._v6_rollback_count == 1
    moments = [e.payload["moment"] for e in _state_events(chain)]
    assert "v6_fallback_lock" in moments
    assert "v6_rollback" in moments


# ── State-roundtrip: V6-alanları deterministik-reconstruction ────────


def test_state_roundtrip_preserves_v6_fields():
    """to_state/from_state V6-alanları korur (deterministik-reconstruction).

    should [restore v6 junction state] when [state is persisted and
    restored on a fresh runtime]
    """
    rt = _warmed()
    _replay(rt, 101, 220)
    rt.on_bar(_mk_bar(220, *BRK_BEAR))
    assert rt._v6_est is True

    state = rt.to_state()
    assert "v6" in state, "to_state 'v6' anahtarı eksik"
    v6 = state["v6"]
    assert v6["est"] is True
    assert v6["source"] == "htf_fallback_breakout"
    assert v6["dir"] == "bearish"

    rt2 = StrategyRuntime("TEST")
    rt2.from_state(state)
    assert rt2._v6_day_key == rt._v6_day_key
    assert rt2._v6_est is True
    assert rt2._v6_dir == rt._v6_dir
    assert rt2._v6_source == rt._v6_source
    assert rt2._v6_ev_bar == rt._v6_ev_bar
    assert rt2._v6_ev_ts == rt._v6_ev_ts
    assert rt2._v6_sweep_price == pytest.approx(rt._v6_sweep_price)
    assert rt2._v6_ref_level == pytest.approx(rt._v6_ref_level)
    assert rt2._htf_dir == rt._htf_dir
    assert rt2._htf_senaryo == rt._htf_senaryo
    assert rt2._v6_rollback_count == rt._v6_rollback_count
    # _htf_daily persist EDILMEZ (deterministik-reconstruction: bir sonraki
    # gün-değişiminde runtime-barlarından kurulur)
    assert "htf_daily" not in v6


def test_from_state_pre_n2_24_format_audited_fallback(caplog):
    """Pre-N2#24 format: 'v6' anahtarı yok → audited fallback (sessiz-değil).

    should [log audited fallback] when [state lacks the v6 key]
    """
    rt = _warmed()
    state = rt.to_state()
    del state["v6"]
    rt2 = StrategyRuntime("TEST")
    with caplog.at_level(logging.WARNING, logger="src.live.strategy_runtime"):
        rt2.from_state(state)
    assert rt2._v6_est is False
    assert rt2._v6_rollback_count == 0
    assert any("v6" in r.message.lower() for r in caplog.records), "audited-fallback uyarısı kayıp"


# ── V0-parite: junction mevcut davranışı değiştirmez ─────────────────


def test_v0_parity_sweep_day_signal_flow_unchanged():
    """V0-parite: sweep-gün sinyal-akışı junction-öncesiyle aynı.

    should [produce identical signal flow] when [the N2#23 sweep→FVG→fill
    scenario is replayed through the junction-amended runtime]
    """
    # N2#23 şema-senaryosu (test_n2_23_emit_schema kalibrasyonu): sweep(160)
    # → FVG(165) → touch(166) → fill(167) = TEK Signal. Junction bu akışı
    # DEĞİŞTİRMEMELİ (motor-kararına dokunmaz; pre-reg §2d).
    from tests.test_n2_23_emit_schema import SCENARIO, _scenario_bar
    from tests.test_n2_23_emit_schema import _base_bar as schema_base

    rt = _warmed()
    signals = []
    for k in range(101, 168):
        bar = _scenario_bar(k) if k in SCENARIO else schema_base(k)
        sig = rt.on_bar(bar)
        if sig is not None:
            signals.append(sig)
    assert len(signals) == 1, f"V0-parite bozuldu: {len(signals)} sinyal"
    sig = signals[0]
    assert sig.side == "short"
    assert sig.direction == "bearish"
    assert sig.entry_bar_index == 167
    assert sig.sweep_bar_index == 160
    # junction sweep-günü kaydetti (V0-aynen)
    assert rt._v6_source == "sweep"
    assert rt._v6_rollback_count == 0


# ── N2 #24 icra-turu: inkremental-fold ≡ tam-rebuild özdeşliği ────────


def test_incremental_fold_equals_full_rebuild():
    """İnkremental-fold düzeltmesinin matematiksel özdeşliği.

    should [produce identical _htf_daily] when [a multi-day replay is
    compared against build_daily(self.bars) full rebuild]
    """
    from src.live.htf_bias import build_daily

    rt = _warmed()
    # 3-gün-replay (k=101..320): gün-01-04/01-05/01-06; SHAPED barlar dahil.
    _replay(rt, 101, 320)
    # Referans: fold-invariant araligi — _htf_daily, bars[0:folded_count]
    # araligini kapsar (guncel-gunun barlari sorguya girmez; gun-K sorgusu
    # yalniz D-1/D-2 okur — D95-birebir-semantik).
    reference = build_daily(rt.bars[: rt._v6_folded_count])
    # Özdeşlik: inkremental-fold durumu ≡ tam-rebuild (TÜM-günler).
    assert rt._htf_daily is not None
    assert (
        rt._htf_daily.keys() == reference.keys()
    ), f"gün-anahtarı-seti-farklı: {sorted(rt._htf_daily.keys())} vs {sorted(reference.keys())}"
    for key in reference:
        got = rt._htf_daily[key]
        want = reference[key]
        assert got["open"] == want["open"], f"{key}-open-farklı"
        assert got["high"] == want["high"], f"{key}-high-farklı"
        assert got["low"] == want["low"], f"{key}-low-farklı"
        assert got["close"] == want["close"], f"{key}-close-farklı"
        assert got["n"] == want["n"], f"{key}-n-farklı"
    # Fold-invariant: folded_count, SON gun-degisimindeki len(bars)'dir;
    # guncel-gunun sonraki barlari tasarim geregi henuz fold edilmez
    # (gun-K sorgusu yalniz D-1/D-2 okur — D95-birebir-semantik).
    assert 0 < rt._v6_folded_count <= len(rt.bars)
    # SEMANTIK-KRITIK: sorgu-anindaki D-1 gunu TAMAMLANMIS olmali —
    # gun-01-05 = k=192..287 = 96 bar (15m-gun); _htf_daily'de n=96.
    assert (
        rt._htf_daily["2026-01-05"]["n"] == 96
    ), f"D-1-tamligi-bozuk: n={rt._htf_daily['2026-01-05']['n']} != 96"
