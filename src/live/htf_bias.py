#!/usr/bin/env python
"""N2 #24 — HTF (Higher-Timeframe) bias provider — D95-birebir-port.

Kaynak: /tmp/n2_22_fazA/v6i_census.py :110-180 (FAZ-A3 pass-1 census
makinelerinden birebir alinmistir; tek-fark: use_body parametresi korunur
ama URETIM-yolunda use_body=False ZORUNLUDUR — V6b/use_body=True URETIMDE
YASAK (FAZ-A2-RED-muhurlu; D96-2).

AM-N24-1: build_daily 19:00-rollover tanimi, session.cbdr_day_key ile
AYNI fonksiyon-semantigidir (hour>=19 -> ertesi-gun anahtari). Canli
yolda CandleFeed-bagimliligi yoktur: YALNIZCA runtime'in zaten
beslenen 15m Bar listesinden uretilir — yeni-fetch YOK, feather YOK.

AM-N24-2 (D96-2): Bu modul JEN-htf-bias-saglayicidir ve yalnizca
hibrit-junction (strategy_runtime) icindeki fallback-dalindan
cagrilabilir. Izole-uretim yolu (V6-IZOLE bir tam bias-kaynagi
olarak canli) yasaktir; cagri-grafi kaniti testlerde sabitlenir.

Sinif-1 pre-reg: results/N2_24_v6_hybrid_prod_prereg.md (31a6caf0).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pandas as pd

from src.strategy.models import Bar

# 19:00-rollover esigi: session.py'deki SESSION_START_HOUR ile ayni sabit.
# D95-birebir: hour >= 19 -> day_key ertesi gun; aksi bugun.
SESSION_ROLLOVER_HOUR = 19

# D95-birebir n-esigi: bir gunluk-mumun gecerli sayilabilmesi icin
# minimum 15m-bar sayisi (her ikisi D-1 VE D-2 icin uygulanir).
HTF_MIN_BARS_PER_DAY = 40


def fold_bar_into(daily: Dict[str, Dict[str, float]], b: Bar) -> None:
    """Tek-15m-bar'i gunluk-OHLC fold'una ekle (build_daily dongu-govdesi).

    N2 #24 icra-turu duzeltmesi: build_daily'nin dongu govdesi buraya
    ekstre edildi — build_daily kendisi bu fonksiyonu cagirir (tek-kaynak;
    paralel-implementasyon YOK, AGENTS §2.2). strategy_runtime gun-
    degisimlerinde tum bar-listesini bastan kurmak yerine yalniz YENI
    barlari fold eder (O(N) toplam; O(D×N) degil — tam-suit parity-gate
    replay'inde tespit edilen donma kok-nedeni).

    Fold saf ve siraya-duyarsiz-degil-ama-associatif: inkremental fold
    ile tam-rebuild matematiksel olarak OZDESDIR (open/high/low/n siradan
    bagimsiz; close = son fold edilen barin close'u). Ozdeslik test ile
    sabitlenir (test_n2_24_v6_junction.py::test_incremental_fold_equals_
    full_rebuild).
    """
    dt = b.timestamp.to_pydatetime()
    if dt.hour >= SESSION_ROLLOVER_HOUR:
        key = (dt + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        key = dt.strftime("%Y-%m-%d")
    d = daily.get(key)
    if d is None:
        daily[key] = {"open": b.open, "high": b.high, "low": b.low, "close": b.close, "n": 1}
    else:
        d["high"] = max(d["high"], b.high)
        d["low"] = min(d["low"], b.low)
        d["close"] = b.close
        d["n"] += 1


def build_daily(bars: List[Bar]) -> Dict[str, Dict[str, float]]:
    """15m-barlardan gunluk-OHLC aggregate (cbdr_day_key-19:00-rollover).

    D95-birebir (v6i_census.py :110-131). Donus:
    ``{day_key: {"open","high","low","close","n"}}`` — day_key
    hour>=19 -> ertesi gun; aksi bugun (session.cbdr_day_key-semantigi).

    AM-N24-1: canli-yolda bagimlilik YOK (CandleFeed/feather yok) —
    girdi yalnizca runtime'in beslenen 15m Bar listesidir.
    """
    daily: Dict[str, Dict[str, float]] = {}
    for b in bars:
        fold_bar_into(daily, b)
    return daily


def htf_wick_bias(
    daily: Dict[str, Dict[str, float]],
    day_key: str,
    use_body: bool = False,
) -> Tuple[Optional[str], str]:
    """V6 HTF-capa: D-1 mumu + PDH/PDL (D-2 wick ekstremleri).

    D95-birebir (v6i_census.py :133-180). use_body=True -> sensitivite-
    sutunu (V6b): PDH/PDL yerine D-2 BODY (max(open,close)/min(open,close))
    kullanilir; D-1-close her iki durumda da close.

    URETIM-KURALI (AM-N24-2 / D96-2): canli-yolda use_body=False ZORUNLU.
    use_body=True yalnizca FAZ-A2 sensitivite-census'unda kullanildi ve
    URETIMDE YASAKTIR (FAZ-A2-RED-muhurlu). Bu kisit test ile sabitlenir.

    Donus: ("bullish"|"bearish"|None, senaryo) — senaryo:
    "A"|"B"|"C"|"conflict"|"C_edge"|"insufficient".
    """
    keys = sorted(daily.keys())
    if day_key not in daily:
        return None, "insufficient"
    idx = keys.index(day_key)
    if idx < 2:
        return None, "insufficient"
    d1 = daily[keys[idx - 1]]
    d2 = daily[keys[idx - 2]]
    if d1["n"] < HTF_MIN_BARS_PER_DAY or d2["n"] < HTF_MIN_BARS_PER_DAY:
        return None, "insufficient"
    if use_body:
        pdh = max(d2["open"], d2["close"])
        pdl = min(d2["open"], d2["close"])
    else:
        pdh = d2["high"]
        pdl = d2["low"]
    c1 = d1["close"]
    # Senaryo-A: trend-devam (close PDH ustunde / PDL altinda)
    if c1 > pdh:
        return "bullish", "A"
    if c1 < pdl:
        return "bearish", "A"
    # Senaryo-B: reversal/igne (D-1 PDH'yi igneledi + altinda kapatti; simetrik)
    b_bear = d1["high"] >= pdh and c1 < pdh
    b_bull = d1["low"] <= pdl and c1 > pdl
    if b_bear and b_bull:
        return None, "conflict"  # cift-igne: HTF-celiski -> NEUTRAL
    if b_bear:
        return "bearish", "B"
    if b_bull:
        return "bullish", "B"
    # Senaryo-C: inside-bar (D-1 range D-2 range icinde) -> NEUTRAL
    if d1["high"] < pdh and d1["low"] > pdl:
        return None, "C"
    # sinir-esitligi artiklari (nadir; orn. close == PDH/PDL) -> NEUTRAL
    return None, "C_edge"
