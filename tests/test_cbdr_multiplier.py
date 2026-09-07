#!/usr/bin/env python
"""D152 — CBDR multiplier gerçek-implementasyon testi (D129 §3 → D150/152).

Reis-onaylı rejim-tablosu (D150: "3 de uygun 1.-2.-3 OK"):
  sikisma (w < p25)   -> 0.0   (trade yok, fail-closed)
  tipik               -> 1.0
  yukselmis           -> 1.2
  makro   (w >= p90)  -> 1.5

Sınır-değerleri per-pair percentile-bantlarından (cbdr_band_config) türetilir
— donuk-sabit değil, tek-kaynak (§2.2). Bilinmeyen-sembol fail-loud (§19).
"""

import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\sniper_forex")

import pytest

from src.config.cbdr_band_config import CBDR_BAND_PERCENTILES
from src.live.risk import CBDR_REGIME_MULTIPLIER, get_cbdr_multiplier

# Rey-onaylı tablo (D150) — test, implementasyonun sözleşmesi.
EXPECTED = {"sikisma": 0.0, "tipik": 1.0, "yukselmis": 1.2, "makro": 1.5}


def test_reis_approved_table_matches_implementation():
    """Implementasyon-tablosu Reis-onaylı değerlere birebir eşit."""
    assert CBDR_REGIME_MULTIPLIER == EXPECTED


@pytest.mark.parametrize("symbol", sorted(CBDR_BAND_PERCENTILES))
def test_band_boundaries_per_pair(symbol):
    """Her çift için bant-sınırları doğru multiplier üretir (per-pair)."""
    p = CBDR_BAND_PERCENTILES[symbol]
    eps = 1e-9
    # Sikisma: p25 altı — iç nokta + üst-sınır (açık: w < p25)
    assert get_cbdr_multiplier(symbol, p.p25 - eps) == 0.0
    # Tipik: p25 <= w < p75 — her iki iç-sınır
    assert get_cbdr_multiplier(symbol, p.p25) == 1.0
    assert get_cbdr_multiplier(symbol, p.p75 - eps) == 1.0
    # Yukselmis: p75 <= w < p90
    assert get_cbdr_multiplier(symbol, p.p75) == 1.2
    assert get_cbdr_multiplier(symbol, p.p90 - eps) == 1.2
    # Makro: w >= p90 (kapalı-alt)
    assert get_cbdr_multiplier(symbol, p.p90) == 1.5


def test_verified_pairs_sample_midpoints():
    """Verified-çiftler için tablo-orta-noktaları beklenen-rejimde."""
    # EURUSD: p25=0.0866, p75=0.166 — 0.12 tipik bölge ortası
    assert get_cbdr_multiplier("EURUSD", 0.12) == 1.0
    # GBPUSD: p90=0.281 — 0.30 makro bölgesi
    assert get_cbdr_multiplier("GBPUSD", 0.30) == 1.5
    # USDCAD: p25=0.0841 — 0.05 sıkışma bölgesi (trade yok)
    assert get_cbdr_multiplier("USDCAD", 0.05) == 0.0


def test_unknown_symbol_fails_loud():
    """Bilinmeyen sembol KeyError — sessiz-fallback YOK (§19)."""
    with pytest.raises(KeyError):
        get_cbdr_multiplier("USDBRL", 0.10)


def test_zero_and_large_widths():
    """w=0 → sıkışma; çok-büyük w → makro (uç-değerler fail-closed değil, tablo-yolu)."""
    assert get_cbdr_multiplier("EURUSD", 0.0) == 0.0
    assert get_cbdr_multiplier("EURUSD", 10.0) == 1.5


if __name__ == "__main__":
    test_reis_approved_table_matches_implementation()
    print("PASS: test_reis_approved_table_matches_implementation")
    test_band_boundaries_per_pair()
    print("PASS: test_band_boundaries_per_pair (7 pairs × 6 boundaries)")
    test_verified_pairs_sample_midpoints()
    print("PASS: test_verified_pairs_sample_midpoints")
    test_unknown_symbol_fails_loud()
    print("PASS: test_unknown_symbol_fails_loud")
    test_zero_and_large_widths()
    print("PASS: test_zero_and_large_widths")
