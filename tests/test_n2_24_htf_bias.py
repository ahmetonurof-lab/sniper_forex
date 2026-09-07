#!/usr/bin/env python
"""N2 #24 — HTF-provider (src/live/htf_bias.py) unit testleri.

PRE-REG: results/N2_24_v6_hybrid_prod_prereg.md (31a6caf0) §2a + §4.
AM-N24-1: build_daily 19:00-rollover tanımı session.cbdr_day_key ile
birebir pinlenir (CandleFeed-bağımlılık-ölçüsü: SIFIR — girdi yalnızca
runtime 15m Bar listesi).
AM-N24-2 (D96-2): use_body=False üretim-kuralı modül-sabitleriyle pinlenir.
D95-birebir-parity, icra-turunda AST-ekstre-karşılaştırmayla ayrıca
kanıtlandı (build_daily + htf_wick_bias tüm günler × iki-variant).
"""

from __future__ import annotations

import pandas as pd

from experiment.config import SESSION_START_HOUR
from src.live.htf_bias import (
    HTF_MIN_BARS_PER_DAY,
    SESSION_ROLLOVER_HOUR,
    build_daily,
    htf_wick_bias,
)
from src.strategy.models import Bar
from src.strategy.session import SessionManager

# ── Sabit-pinleri (AM-N24-1 / D95-birebir) ──────────────────────────


def test_rollover_threshold_pinned_to_session_start_hour():
    """AM-N24-1: build_daily rollover eşiği == session pencere-başı.

    should [pin rollover hour to SESSION_START_HOUR] when [module constants
    are compared with the canonical session window]
    """
    assert SESSION_ROLLOVER_HOUR == 19
    assert SESSION_ROLLOVER_HOUR == SESSION_START_HOUR


def test_min_bars_gate_pinned():
    """D95-birebir: n≥40 eşiği sabitlenir (her iki D-1 VE D-2 için)."""
    assert HTF_MIN_BARS_PER_DAY == 40


# ── Bar-üretici ─────────────────────────────────────────────────────


def _bars_from_ohlc(rows: list[tuple[pd.Timestamp, float, float, float, float]]) -> list[Bar]:
    return [
        Bar(index=i, timestamp=ts, open=o, high=h, low=lo, close=c, volume=100.0)
        for i, (ts, o, h, lo, c) in enumerate(rows)
    ]


def _day_bars(day: pd.Timestamp, o: float, h: float, lo: float, c: float) -> list:
    """Bir günü temsil edensentetik 15m barlar (96 bar; 00:00-23:45).

    Tüm barlar günün OHLC aralığında; gün kapanışı `c` ile biter.
    """
    rows = []
    for slot in range(96):
        ts = day + pd.Timedelta(minutes=15 * slot)
        frac = slot / 95.0
        # open→close lineer içi değerler; high/low uçlarına dokunur
        body = o + (c - o) * frac
        hi = min(h, body + (h - max(o, c)) * (0.5 if slot % 2 else 0.0))
        llo = max(lo, body - (min(o, c) - lo) * (0.5 if slot % 2 else 0.0))
        rows.append((ts, body, max(hi, body, c), min(llo, body, c), body if slot < 95 else c))
    # son bar günün gerçek kapanışını taşır
    ts_last, o_last, h_last, l_last, _ = rows[-1]
    rows[-1] = (ts_last, o_last, max(h_last, h), min(l_last, lo), c)
    return rows


# ── build_daily: 19:00-rollover + cbdr_day_key paritesi ─────────────


def test_build_daily_rollover_matches_cbdr_day_key():
    """AM-N24-1: build_daily anahtarları cbdr_day_key ile birebir aynı.

    should [aggregate daily OHLC under 19:00 rollover identical to
    session.cbdr_day_key] when [bars cross both the 19:00 boundary and
    midnight]
    """
    # 18:45 (önceki-gün anahtarı) + 19:00 (ertesi-gün anahtarı) + 00:15
    rows = [
        (pd.Timestamp("2026-01-05 18:30:00"), 1.1000, 1.1010, 1.0990, 1.1005),
        (pd.Timestamp("2026-01-05 18:45:00"), 1.1005, 1.1015, 1.0995, 1.1008),
        (pd.Timestamp("2026-01-05 19:00:00"), 1.1008, 1.1020, 1.1000, 1.1015),
        (pd.Timestamp("2026-01-05 23:45:00"), 1.1015, 1.1030, 1.1010, 1.1025),
        (pd.Timestamp("2026-01-06 00:15:00"), 1.1025, 1.1040, 1.1020, 1.1035),
    ]
    bars = _bars_from_ohlc(rows)
    daily = build_daily(bars)

    # cbdr_day_key ile elle-gruplama (SessionManager örneği üzerinden)
    sm = SessionManager(symbol="TEST")
    expected: dict[str, list[Bar]] = {}
    for b in bars:
        key = sm.cbdr_day_key(b.timestamp.to_pydatetime())
        expected.setdefault(key, []).append(b)

    assert set(daily.keys()) == set(expected.keys())
    assert sorted(daily.keys()) == ["2026-01-05", "2026-01-06"]
    for key, group in expected.items():
        d = daily[key]
        assert d["n"] == len(group)
        assert d["open"] == group[0].open
        assert d["high"] == max(b.high for b in group)
        assert d["low"] == min(b.low for b in group)
        assert d["close"] == group[-1].close


def test_build_daily_last_close_wins():
    """Gün-kapanışı = günün SON barının close'u (D95-birebir)."""
    rows = [
        (pd.Timestamp("2026-01-05 10:00:00"), 1.1000, 1.1050, 1.0990, 1.1040),
        (pd.Timestamp("2026-01-05 11:00:00"), 1.1040, 1.1060, 1.1030, 1.0995),
    ]
    daily = build_daily(_bars_from_ohlc(rows))
    d = daily["2026-01-05"]
    assert d["close"] == 1.0995
    assert d["high"] == 1.1060
    assert d["low"] == 1.0990


# ── htf_wick_bias: senaryo-sentisi (D95-birebir matrisi) ────────────


def _daily3(d2: dict, d1: dict, k: dict) -> dict:
    """3 günlük daily dict (k = sorgu-günü; d1 = D-1; d2 = D-2).

    Anahtar-adları sorted-sırada D-2 → D-1 → k olacak şekilde: "a" (D-2),
    "b" (D-1), "k" (sorgu). htf_wick_bias sorted(keys) ile idx-1/idx-2
    seçer — alfabetik-sıra tuzağına karşı pinlenmiş adlandırma.
    """
    return {"a": d2, "b": d1, "k": k}


D2 = {"open": 1.1000, "high": 1.1050, "low": 1.0950, "close": 1.1040, "n": 96}


def test_scenario_a_bullish_and_bearish():
    """Senaryo-A: D-1 close PDH üstünde → bullish / PDL altında → bearish."""
    d1_bull = {"open": 1.1040, "high": 1.1070, "low": 1.1030, "close": 1.1060, "n": 96}
    d1_bear = {"open": 1.1010, "high": 1.1020, "low": 1.0900, "close": 1.0910, "n": 96}
    assert htf_wick_bias(_daily3(D2, d1_bull, {}), "k") == ("bullish", "A")
    assert htf_wick_bias(_daily3(D2, d1_bear, {}), "k") == ("bearish", "A")


def test_scenario_b_pin_and_reversal():
    """Senaryo-B: D-1 PDH'yi igneledi + altında kapattı → bearish (simetrik)."""
    d1_bear = {"open": 1.1060, "high": 1.1060, "low": 1.1010, "close": 1.1030, "n": 96}
    d1_bull = {"open": 1.0990, "high": 1.1040, "low": 1.0940, "close": 1.0970, "n": 96}
    # PDH=1.1050: high 1.1060 >= pdh, close 1.1030 < pdh → B-bearish
    assert htf_wick_bias(_daily3(D2, d1_bear, {}), "k") == ("bearish", "B")
    # PDL=1.0950: low 1.0940 <= pdl, close 1.0970 > pdl → B-bullish
    assert htf_wick_bias(_daily3(D2, d1_bull, {}), "k") == ("bullish", "B")


def test_scenario_conflict_double_pin():
    """Çift-igne (hem B-bear hem B-bull) → NEUTRAL/conflict."""
    d1 = {"open": 1.1000, "high": 1.1060, "low": 1.0940, "close": 1.1000, "n": 96}
    assert htf_wick_bias(_daily3(D2, d1, {}), "k") == (None, "conflict")


def test_scenario_c_inside_bar():
    """Senaryo-C: D-1 range D-2 range içinde → NEUTRAL."""
    d1 = {"open": 1.1000, "high": 1.1040, "low": 1.0960, "close": 1.1030, "n": 96}
    assert htf_wick_bias(_daily3(D2, d1, {}), "k") == (None, "C")


def test_scenario_c_edge_boundary():
    """C_edge: close == PDH (sınır-eşitliği) → NEUTRAL."""
    d1 = {"open": 1.1000, "high": 1.1050, "low": 1.0960, "close": 1.1050, "n": 96}
    assert htf_wick_bias(_daily3(D2, d1, {}), "k") == (None, "C_edge")


def test_insufficient_missing_day_and_index():
    """insufficient: gün-yok veya idx<2."""
    daily = _daily3(D2, D2, {})
    assert htf_wick_bias(daily, "yok") == (None, "insufficient")
    # "d1" günü idx=1 → yetersiz
    assert htf_wick_bias(daily, "d1") == (None, "insufficient")


def test_n40_gate_both_days():
    """n≥40 gate: D-1 VEYA D-2 n<40 → insufficient; 40 → değerlendirilir."""
    d1 = {"open": 1.1040, "high": 1.1070, "low": 1.1030, "close": 1.1060, "n": 96}
    k = {}
    d2_39 = dict(D2, n=39)
    d2_40 = dict(D2, n=40)
    assert htf_wick_bias(_daily3(d2_39, d1, k), "k") == (None, "insufficient")
    r = htf_wick_bias(_daily3(d2_40, d1, k), "k")
    assert r == ("bullish", "A")
    d1_39 = dict(d1, n=39)
    assert htf_wick_bias(_daily3(d2_40, d1_39, k), "k") == (None, "insufficient")


def test_use_body_sensitivity_column():
    """use_body=True (V6b sensitivite-sütunu): PDH/PDL → D-2 body.

    Üretim-kuralı: varsayılan use_body=False (wick); V6b üretimde YASAK
    (FAZ-A2-RED). Bu test sensitivite-sütununun tanımını sabitler.
    """
    d2 = {"open": 1.1000, "high": 1.1200, "low": 1.0800, "close": 1.1010, "n": 96}
    # D-2 body: [1.1000, 1.1010] → PDH_body=1.1010, PDL_body=1.1000
    d1 = {"open": 1.1005, "high": 1.1015, "low": 1.0995, "close": 1.1012, "n": 96}
    # wick-yolu: c1=1.1012 < pdh(1.1200) ve > pdl(1.0800); b_bear: high
    # 1.1015 >= 1.1200? hayır; b_bull: low 1.0995 <= 1.0800? hayır → C
    assert htf_wick_bias(_daily3(d2, d1, {}), "k", use_body=False) == (None, "C")
    # body-yolu: c1=1.1012 > pdh_body(1.1010) → A-bullish
    assert htf_wick_bias(_daily3(d2, d1, {}), "k", use_body=True) == ("bullish", "A")
    # varsayılan = wick (False)
    assert htf_wick_bias(_daily3(d2, d1, {}), "k") == (None, "C")


def test_build_daily_full_day_pipeline_reaches_scenario_a():
    """Uç-uç: build_daily çıktısı htf_wick_bias'a beslenir; A-senaryosu.

    should [derive bullish scenario from raw bars] when [three complete
    days of 15m bars are aggregated and queried]
    """
    base = pd.Timestamp("2026-08-20 00:00:00")
    rows = []
    rows += _day_bars(base, 1.1000, 1.1010, 1.0990, 1.1005)  # D-2 (PDH=1.1010)
    rows += _day_bars(base + pd.Timedelta(days=1), 1.1005, 1.1020, 1.0985, 1.1015)
    # D-1: PDH(1.1010) üstünde kapatır → A-bullish
    rows += _day_bars(base + pd.Timedelta(days=2), 1.1010, 1.1030, 1.1005, 1.1020)
    daily = build_daily(_bars_from_ohlc(rows))
    keys = sorted(daily.keys())
    # 19:00-rollover: her girilen günün 19:00+ barları SONRAKİ gün-anahtarına
    # taşınır → 3 girilen gün → 4 anahtar; son anahtar 20-bar spill (n<40).
    # Sorgu-günü TAMAMLANMIŞ son gün = keys[-2] (D-1/D-2'si de tamamlanmış).
    assert len(keys) == 4
    assert daily[keys[-1]]["n"] < HTF_MIN_BARS_PER_DAY
    assert all(daily[k]["n"] >= HTF_MIN_BARS_PER_DAY for k in keys[:-1])
    assert htf_wick_bias(daily, keys[-2]) == ("bullish", "A")
    # D95-semantiği-pin: n-gate sorgu-gününe DEĞİL D-1/D-2'ye uygulanır —
    # spill-gün (n=20) sorgusu bile D-1/D-2'si ≥40 olduğu için değerlendirilir.
    assert htf_wick_bias(daily, keys[-1]) == ("bullish", "A")
