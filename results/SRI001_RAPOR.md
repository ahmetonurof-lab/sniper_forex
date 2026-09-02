# SRI-001 — BREAKOUT-CONTINUATION VARIANT ARAŞTIRMA RAPORU

**Tarih:** 2026-09-02 | **İcra:** Cline | **Hakem:** Luna | **Owner karar:** Forexçi
**Freeze:** §17 @ `c42040a` — src/, tests/, index.json, experiment/-mevcut **dokunulmadı**
**Script:** `experiment/exp_sri001_breakout_variant.py` (YENİ) | **Ham:** `results/exp_sri001_breakout_variant.json`

## 0. KONTROL-ÇAPASI (DENEY-3, FROZEN `run_test_a` as-is import)

```text
expected: 2302T +2875.00R WR 69.37%
actual:   2302T +2875.00R WR 69.37%   → MATCH: YES (birebir; per-symbol dahil)
```

Pipeline-paritesi kanıtlandı; aşağıdaki tüm sayılar exact run-çıktısıdır.

## 1. ÜÇ DENEY × 6 SEMBOL (sekiz metrik seti; tam dağılım JSON'da)

### DENEY-1a — ZİNCİR-4 (variant-only)
| Sembol | N | WR% | PnL(R) | AvgR | PF | MaxDD(R) | MaxDD% |
|---|---|---|---|---|---|---|---|
| EURUSD | 347 | 32.0 | −36.20 | −0.104 | 0.85 | 54.00 | 54.00 |
| AUDUSD | 337 | 34.7 | −9.40 | −0.028 | 0.96 | 22.20 | 21.39 |
| GBPUSD | 379 | 36.1 | +4.60 | +0.012 | 1.02 | 21.00 | 19.53 |
| GBPJPY | 346 | 35.5 | −1.60 | −0.005 | 0.99 | 24.80 | 22.46 |
| USDCAD | 407 | 31.2 | −51.40 | −0.126 | 0.82 | 70.40 | 68.62 |
| USDJPY | 325 | 36.6 | +8.20 | +0.025 | 1.04 | 22.60 | 17.52 |
| **TOPLAM** | **2141** | **34.3** | **−85.80** | | | | |

### DENEY-1b — ZİNCİR-6 (variant-only)
| Sembol | N | WR% | PnL(R) | AvgR | PF | MaxDD(R) | MaxDD% |
|---|---|---|---|---|---|---|---|
| EURUSD | 74 | 70.3 | +71.60 | +0.968 | 4.25 | 2.00 | 1.58 |
| AUDUSD | 80 | 63.7 | +62.80 | +0.785 | 3.17 | 3.00 | 2.11 |
| GBPUSD | 96 | 66.7 | +83.20 | +0.867 | 3.60 | 4.00 | 3.80 |
| GBPJPY | 84 | 66.7 | +72.80 | +0.867 | 3.60 | 6.20 | 4.30 |
| USDCAD | 89 | 64.0 | +70.60 | +0.793 | 3.21 | 4.20 | 3.80 |
| USDJPY | 89 | 56.2 | +51.00 | +0.573 | 2.31 | 5.00 | 4.13 |
| **TOPLAM** | **512** | **64.5** | **+412.00** | | | | |

### DENEY-3 — Kanonik kontrol (fakeout-only)
2302T / 69.4% / +2875.00R / PF 5.08 / MaxDD 8.00R (2.73%) — birebir çapa.

### DENEY-2 — Combined (kanonik + variant)
| Kit | N | WR% | PnL(R) | MaxDD(R) | MaxDD% |
|---|---|---|---|---|---|
| Kanonik + ZİNCİR-4 | 4443 | 52.5 | +2789.20 (−85.8) | 15.00 | 8.44 |
| Kanonik + ZİNCİR-6 | 2814 | 68.5 | +3287.00 (+412.0) | 9.00 | 3.98 |

## 2. OVERLAP ANALİZİ (aynı CBDR-günü + aynı yön; net-R)

| Sembol | C4 gün | C4 var_R | C6 gün | C6 var_R | C6 combined_R |
|---|---|---|---|---|---|
| EURUSD | 16 | −7.60 | 4 | +4.40 | +10.27 |
| AUDUSD | 17 | −5.80 | 6 | +5.20 | +11.79 |
| GBPUSD | 18 | +7.20 | 6 | +10.80 | +15.55 |
| GBPJPY | 18 | −4.00 | 8 | +3.20 | +9.80 |
| USDCAD | 16 | −4.80 | 3 | +5.40 | +5.75 |
| USDJPY | 11 | −8.20 | 6 | +2.40 | +16.57 |

ZİNCİR-4 overlap-katkısı **5/6 sembolde negatif** (fakeout-günlerinde aleyhte dublör).
ZİNCİR-6 overlap-katkısı **6/6 pozitif**.

## 3. 2026-09-02 CASE-STUDY (EURUSD, canlı MT5 M1→15m, live-restored band)

- Band: body_high 1.15953 / body_low 1.15833 / tol 0.00029785 (0.5 × live-restored session_atr 0.0005957; state/EURUSD.json 20:30 UTC parity-verified)
- **Break:** 01:30 UTC (04:30 server, DST+3) — low 1.1577 / close 1.1578 → pierce+acceptance OK
- **Displacement b+1..b+4:** closes 1.1579 / 1.15801 / 1.15802 / 1.15816 — reclaim YOK
- **ZİNCİR-4:** entry 1.15816 @ 02:30 UTC → SL 1.15833 (risk 1.7 pip) → **TP +1.8R**
- **MSS:** penetrasyon 0.00071 / range 0.0012 = %59.2 → PASS
- **ZİNCİR-6:** bearish FVG (top 1.15802 / bottom 1.15794) tamamlanma 03:30 UTC → retest entry 1.15799 @ 03:45 UTC → SL 1.15833 (risk 3.4 pip) → **TP 1.157378 +1.8R**
- Karşılaştırma: canlı-chart (önceki cevap) — motor fakeout aradı, bulamadı, sinyal yok; o gün ~350 pip düştü. Breakout-variant O GÜNÜ **iki zincirle de yakaladı** (+3.6R toplam kağıt-üstü).

## 4. ZİNCİR KARŞILAŞTIRMASI

| Boyut | ZİNCİR-4 | ZİNCİR-6 |
|---|---|---|
| Net R (2.7Y, 6 major) | −85.8R | **+412.0R** |
| WR | 34.3% | 64.5% |
| MaxDD | 70.4R (USDCAD) | 6.2R |
| Overlap güvenliği | 5/6 negatif | 6/6 pozitif |
| Karar | **RED — güvenli değil** | **ADAY — daha iyi ve daha güvenli** |

Filtre-hunisi (chain-6, 6-symbol ort.): 678 break → 48.7% reclaim@displacement → %18.2 no-MSS → %2.4 no-FVG → %7.1 reclaim@wait → %15.2 no-retest → %0.6 min-risk → **12.7% entry**.

## 5. OWNER-DECISION-READY ÖZZET (hakem arbitrajı öncesi ham durum)

1. ZİNCİR-4 (displacement-only) **pozitif-kenar taşımıyor**: 6-symbol −85.8R, fakeout-günlerinde aleyhte overlap. Breakout "acceptance+displacement" tek-başına edge değil.
2. ZİNCİR-6 (MSS+FVG+retest) **kenar gösteriyor**: +412R / 6445R kanonik-paralel, MaxDD 6.2R, combined +3287R. AMA: disclosed-assumptions (aşağıda) ve 15m-granülerlik sınırları geçerli; kanonik listede bir setup-ADAYI olarak §2.1 araştırma-topu — promote-değil.
3. Birleşik kit DD-profili: chain-6 eklenince MaxDD 8R→9R'ye (USDJPY) zarif biçimde bozuluyor; chain-4 eklenince 15R'ye patlıyor.

### Disclosed assumptions (direktifin sessiz kaldığı noktalar — JSON provenance'da)
- tolerance = 0.5 × session.atr (engine-parite: run_test_a kurulum-ATR, döngüde güncellenmez)
- SL = band-kıyısı (body_high/low); "bandına dönen fiyat" yorumu
- Chain-6 zaman-bound'ları: FVG tamamlanma ≤ break+8; retest ≤ 12 bar; MSS = maks-penetrasyon ≥ 0.5×range (break..break+4)
- Tek-pozisyon/sembol; döngü-başına 1 deneme; SL-önce exit; trailing YOK; entry kapanışta, exit sonraki bardan
