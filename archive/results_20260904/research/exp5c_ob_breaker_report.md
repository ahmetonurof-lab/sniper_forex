# EXP5C — OB/Breaker Forensic Rapor

**Data:** 6 pair × 180 gün = EXP5B penceresi. 630 sweep, 1251 FVG (#1=630, #2=621). 46 saniye.

---

## Tanımlar

### Order Block Kuralları
- **Bullish OB:** Son ayı mumu c (close<open), c < FVG_FIRST, c >= FVG_FIRST-W_OB, displacement onayı: bazı d, c < d <= FVG_FIRST: close[d] > high[c]
- **Bearish OB:** Ayna (bullish'in tersi)

### Breaker Block Kuralları
- **Bullish Breaker:** Ayı mumu z; FAILURE close[f] < low[z] (z<f<FVG_FIRST); FLIP close[g] > high[z] (f<g<FVG_FIRST); en son flip kazanır
- **Bearish Breaker:** Ayna (bullish'in tersi)

### Window'lar
- `W_OB = 10` — OB-R1 search window (bars before FVG_FIRST)
- `W_BB = 50` — BB-R1 search window

---

## Popülasyon Sonuçları

| Metrik | FVG #1 (n=630) | FVG #2 (n=621) |
|--------|-----------------|-----------------|
| **OB bulundu** | 490 (77.8%) | 545 (87.8%) |
| OB medyan mesafe | 5 bar | 4 bar |
| OB FVG ile kesişim | 104 (21.2%) | 90 (16.5%) |
| OB FVG öncesi mitigation | 443 (90.4%) | 468 (85.9%) |
| **Breaker bulundu** | 616 (97.8%) | 609 (98.1%) |
| BB medyan flip→FVG | 9 bar | 7 bar |
| BB FVG ile kesişim | 135 (21.9%) | 147 (24.1%) |

---

## Gözlemler (telemetry-only, outcome yok)

- **OB çok yaygın** (%78–88): Her FVG'nin önünde kısa mesafede (4–5 bar) bir ayı/bası mumu var — beklenen yapı.
- **Mitigation çok yüksek** (%86–90): OB'lerin büyük çoğunluğu FVG_first'den önce zaten geri döndürülmüş — bu OB'ler *"artık dokunulmamış"* (unmitigated) değil, FVG'ye giderken zaten piyasayı emmiş.
- **Breaker neredeyse evrensel** (%98): 50-bar pencerede failure+flip sekansı bulmak çok kolay; bu sinyal doğası gereği bol üretiyor.
- **Kesişim düşük** (%16–24): OB/Breaker bölgeleri ile FVG boşluğu çoğunlukla ayrık — bereberler ama bitişik değiller.

---

## dosyalar

| Dosya | Açıklama |
|--------|----------|
| `exp5c_ob_breaker_forensics.py` | Modül |
| `test_exp5c_ob_breaker.py` | 13 test |
| `exp5c_ob_breaker_telemetry.json` | 1251 kayıt |

**Kural**: EXP5B, Research EQ, production entry ve canonical benchmark'a dokunulmadı.
