# EXP5C — Research EQ Cohort Analysis: COMPLETE

**55/55 unit tests passed (9.75s)**

---

## Tanım

Research EQ tanımı: `research_eq = (swing_high + swing_low) / 2`

Her trade, 6 cohort'tan birine atanır:
- **CORRECT_AT_FORMATION + FRESH** — EQ formation'da doğru, fresh
- **CORRECT_AT_FORMATION + STALE** — EQ formation'da doğru, stale
- **WRONG_LATER_CORRECT + FRESH** — Başta yanlış, sonra düzeldi, fresh
- **WRONG_LATER_CORRECT + STALE** — Başta yanlış, sonra düzeldi, stale
- **NEVER_CORRECT** — EQ hiç düzelmedi
- **LATER_UNKNOWN_NO_EQ** — Slot=0 (sonra oluşan FVG)

---

## Research EQ Cohort × Outcome

| Cohort | N | WR% | AvgR | TotalR | MaxDD |
|--------|---|------|------|--------|-------|
| CORRECT_AT_FORMATION + FRESH | 1 | 100.0 | 1.800 | 1.80 | 0.0 |
| CORRECT_AT_FORMATION + STALE | 239 | 66.9 | 0.814 | 194.51 | 5.0 |
| WRONG_LATER_CORRECT + FRESH | 76 | 65.8 | 1.772 | 134.67 | 4.78 |
| WRONG_LATER_CORRECT + STALE | 150 | 39.3 | 0.055 | 8.28 | 7.99 |
| NEVER_CORRECT | 1 | 0.0 | -1.000 | -1.00 | 1.0 |
| LATER_UNKNOWN_NO_EQ | 62 | 74.2 | 2.806 | 173.97 | 5.0 |

---

## Cohort × FVG Slot

| Cohort | Slot | N | WR% | AvgR | TotalR |
|--------|------|---|------|------|--------|
| CORRECT_AT_FORMATION + FRESH | #1 | 1 | 100.0 | 1.800 | 1.80 |
| CORRECT_AT_FORMATION + STALE | #1 | 216 | 67.1 | 0.865 | 186.75 |
| CORRECT_AT_FORMATION + STALE | #2 | 23 | 65.2 | 0.338 | 7.77 |
| WRONG_LATER_CORRECT + FRESH | #1 | 72 | 66.7 | 1.863 | 134.10 |
| WRONG_LATER_CORRECT + FRESH | #2 | 4 | 50.0 | 0.142 | 0.57 |
| WRONG_LATER_CORRECT + STALE | #1 | 144 | 41.0 | 0.099 | 14.28 |
| WRONG_LATER_CORRECT + STALE | #2 | 6 | 0.0 | -1.000 | -6.00 |
| LATER_UNKNOWN_NO_EQ | Later | 62 | 74.2 | 2.806 | 173.97 |

---

## Cohort × OB Context (FVG #1 + #2)

| Cohort | OB | N | WR% | AvgR | TotalR |
|--------|----|---|------|------|--------|
| CORRECT_AT_FORMATION + FRESH | OB | 1 | 100.0 | 1.800 | 1.80 |
| CORRECT_AT_FORMATION + STALE | OB | 135 | 63.7 | 0.634 | 85.62 |
| CORRECT_AT_FORMATION + STALE | no OB | 104 | 71.2 | 1.047 | 108.89 |
| WRONG_LATER_CORRECT + FRESH | OB | 67 | 67.2 | 1.967 | 131.80 |
| WRONG_LATER_CORRECT + FRESH | no OB | 9 | 55.6 | 0.318 | 2.86 |
| WRONG_LATER_CORRECT + STALE | OB | 135 | 37.8 | 0.045 | 6.10 |
| WRONG_LATER_CORRECT + STALE | no OB | 15 | 53.3 | 0.145 | 2.18 |

---

## Cohort × Breaker Context (FVG #1 + #2)

| Cohort | BB | N | WR% | AvgR | TotalR |
|--------|----|---|------|------|--------|
| CORRECT_AT_FORMATION + FRESH | BB | 1 | 100.0 | 1.800 | 1.80 |
| CORRECT_AT_FORMATION + STALE | BB | 235 | 67.2 | 0.825 | 193.89 |
| CORRECT_AT_FORMATION + STALE | no BB | 4 | 50.0 | 0.156 | 0.62 |
| WRONG_LATER_CORRECT + FRESH | BB | 72 | 68.1 | 1.898 | 136.67 |
| WRONG_LATER_CORRECT + FRESH | no BB | 4 | 25.0 | -0.500 | -2.00 |
| WRONG_LATER_CORRECT + STALE | BB | 144 | 39.6 | 0.060 | 8.68 |
| WRONG_LATER_CORRECT + STALE | no BB | 6 | 33.3 | -0.067 | -0.40 |

---

## Later/Unknown Deep-Dive (N=62)

| Metrik | Değer |
|--------|-------|
| Slot | 62/62 = Later (slot=0) |
| WR | 74.2% (46W / 16L) |
| AvgR | 2.806 |
| TotalR | 173.97 |
| MaxDD | 5.0 |
| Avg win | 4.130R |
| Avg loss | -1.000R |

**Top symbols:** USDCAD: 13, GBPUSD: 12, AUDUSD: 11

**Sonuç:** Bu trade'lerin `zone_index`'i mevcut FVG #1/#2 listesiyle eşleşmemiş. OB/BB context'i None olarak kalmış.

---

## Dosyalar

| Dosya | Açıklama |
|-------|----------|
| `exp5c_research_eq_cohort.py` | Cohort attribution modülü |
| `test_exp5c_cohort.py` | 10 test |
| `exp5c_research_eq_cohort.json` | 529 enriched kayıt |
| `exp5c_ob_breaker_forensics.py` | OB/BB forensic modülü |
| `test_exp5c_ob_breaker.py` | OB/BB testleri |
| `exp5c_outcome_attribution.py` | Outcome attribution modülü |
| `test_exp5c_outcome.py` | Outcome testleri |

**Hiçbir entry kuralı, EXP5B, Research EQ, production veya canonical benchmark'a dokunulmadı.**
