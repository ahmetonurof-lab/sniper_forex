# EXP 5C — OB/Breaker Context × Outcome Attribution

**Definitions:** Order Block ve Breaker Block kuralları
**Entry rules:** UNCHANGED (KNOWN-GOOD run_test_a). OB/BB = forensic context only.

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

## POPULATION

- Total trades: **529** | Completed: **529**
- FVG #1: 434 | FVG #2: 33 | Later/Unknown: 62

## 1. FVG SLOT

| Context | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |
|---|---|---|---|---|---|---|---|
| FVG #1 | 434 | 434 | 58.3 | 0.774 | 0.774 | 335.92 | 6.2 |
| FVG #2 | 33 | 33 | 51.5 | 0.071 | 0.071 | 2.33 | 7.0 |
| Later/Unknown | 62 | 62 | 74.2 | 2.806 | 2.806 | 173.97 | 5.0 |

## 2. OB CONTEXT (FVG #1 + #2)

| Context | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |
|---|---|---|---|---|---|---|---|
| FVG #1 + OB | 314 | 314 | 53.8 | 0.706 | 0.706 | 221.59 | 6.2 |
| FVG #1 + no OB | 120 | 120 | 70.0 | 0.953 | 0.953 | 114.34 | 6.0 |
| FVG #2 + OB | 25 | 25 | 56.0 | 0.109 | 0.109 | 2.73 | 5.0 |
| FVG #2 + no OB | 8 | 8 | 37.5 | -0.05 | -0.05 | -0.4 | 3.2 |

## 3. OB MITIGATION (FVG #1 + #2, OB found only)

| Context | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |
|---|---|---|---|---|---|---|---|
| OB mitigated | 309 | 309 | 53.1 | 0.676 | 0.676 | 208.77 | 8.54 |
| OB unmitigated | 30 | 30 | 63.3 | 0.518 | 0.518 | 15.55 | 2.0 |

### OB Mitigation × Slot

| Context | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |
|---|---|---|---|---|---|---|---|
| OB mitigated #1 | 293 | 293 | 53.2 | 0.713 | 0.713 | 208.81 | 7.0 |
| OB unmitigated #1 | 21 | 21 | 61.9 | 0.609 | 0.609 | 12.78 | 3.0 |
| OB mitigated #2 | 16 | 16 | 50.0 | -0.002 | -0.002 | -0.03 | 6.0 |
| OB unmitigated #2 | 9 | 9 | 66.7 | 0.307 | 0.307 | 2.77 | 1.23 |

## 4. BREAKER CONTEXT (FVG #1 + #2)

| Context | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |
|---|---|---|---|---|---|---|---|
| FVG #1 + Breaker | 421 | 421 | 59.1 | 0.805 | 0.805 | 338.7 | 6.2 |
| FVG #1 + no Breaker | 13 | 13 | 30.8 | -0.214 | -0.214 | -2.78 | 4.58 |
| FVG #2 + Breaker | 32 | 32 | 50.0 | 0.042 | 0.042 | 1.33 | 7.0 |
| FVG #2 + no Breaker | 1 | 1 | 100.0 | 1.0 | 1.0 | 1.0 | 0.0 |

## 5. BREAKER OVERLAP (FVG #1 + #2, Breaker found only)

| Context | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |
|---|---|---|---|---|---|---|---|
| Breaker + overlap FVG | 93 | 93 | 51.6 | 1.135 | 1.135 | 105.58 | 11.0 |
| Breaker + no overlap | 360 | 360 | 60.3 | 0.651 | 0.651 | 234.45 | 7.11 |

### Breaker Overlap × Slot

| Context | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |
|---|---|---|---|---|---|---|---|
| BB overlap #1 | 87 | 87 | 51.7 | 1.223 | 1.223 | 106.42 | 11.39 |
| BB no overlap #1 | 334 | 334 | 61.1 | 0.695 | 0.695 | 232.28 | 7.0 |
| BB overlap #2 | 6 | 6 | 50.0 | -0.139 | -0.139 | -0.83 | 3.0 |
| BB no overlap #2 | 26 | 26 | 50.0 | 0.083 | 0.083 | 2.17 | 4.0 |

## 6. COMBINED OB × BREAKER MATRIX (FVG #1 + #2)

| Context | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |
|---|---|---|---|---|---|---|---|
| OB + BB | 331 | 331 | 54.7 | 0.685 | 0.685 | 226.9 | 7.0 |
| OB + no BB | 8 | 8 | 25.0 | -0.322 | -0.322 | -2.58 | 4.38 |
| no OB + BB | 122 | 122 | 68.9 | 0.927 | 0.927 | 113.14 | 5.0 |
| no OB + no BB | 6 | 6 | 50.0 | 0.133 | 0.133 | 0.8 | 2.0 |

Observation-only. No commentary or decision.
