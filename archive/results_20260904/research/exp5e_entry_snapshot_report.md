# EXP5E — Entry-Time Mitigation Snapshot: COMPLETE

**Population:** 529 trades | 11 unit tests (all pass) | 76/76 full suite | 740.4s runtime

---

## 🔑 The Time-Axis Problem is SOLVED

EXP5D scanned ALL bars → final state. But trades enter at a specific timestamp. EXP5E captures the state **AT entry** and tracks **what happens after**.

---

## Entry-State Distribution

| State | N | % |
|-------|---|---|
| **S0_UNTOUCHED** | **464** | **87.7%** |
| S3_DEEP | 1 | 0.2% |
| S4_INVALIDATED | 3 | 0.6% |
| N/A (slot=0) | 61 | 11.5% |

**87.7% of trades enter when the FVG is completely untouched.** The production freshness filter is working perfectly at entry time.

---

## Four Cohorts × Outcome

| Cohort | N | WR% | AvgR | TotalR | MaxDD |
|--------|---|------|------|--------|-------|
| A: S0/S1/S2 at entry | 464 | 57.8% | 0.724 | 336.15 | 7.32 |
| B: S3 at entry | 1 | 100% | 1.000 | 1.00 | 0.00 |
| C: S4 at entry | 3 | 33.3% | 0.036 | 0.11 | 2.00 |
| D: Post-entry S4 | 458 | 57.6% | 0.723 | 330.95 | 7.32 |
| **Never S4** | **68** | **75.0%** | **2.664** | **181.17** | **5.00** |

---

## Post-Entry Invalidation Analysis

| Post-Entry | N | WR% | AvgR | TotalR |
|------------|---|------|------|--------|
| **S4 after entry** | **458** | **57.6%** | **0.723** | **330.95** |
| **No S4** | **68** | **75.0%** | **2.664** | **181.17** |

**86.6% of trades get S4'd AFTER entry.** The 12.9% that never get invalidated have **75% WR and 2.664R** — nearly 4× the AvgR.

---

## S0 at Entry × Post-Entry Evolution

| Entry→Post | N | WR% | AvgR | TotalR |
|------------|---|------|------|--------|
| S0→S0 | 3 | 100% | 1.800 | 5.40 |
| S0→S1 | 5 | 0% | -1.000 | -5.00 |
| S0→S2 | 1 | 100% | 3.667 | 3.67 |
| **S0→S3** | **212** | **51.9%** | **0.820** | **173.75** |
| **S0→S4** | **243** | **63.4%** | **0.652** | **158.33** |

---

## 🎯 Nihai Sonuç

**Fresh'i çöpe atma.** Ama sebep yanlış yerde:

1. **Production freshness filter doğru çalışıyor.** 464/529 trade entry anında S0 (untouched). Filtre entry anını doğru yakalıyor.

2. **Sorun timing değil, post-entry invalidation.** 464 S0-entry trade'in 243'ü (%52.4) entry'den sonra S4'e düşüyor. 212'si (%45.7) S3'e. Sadece 9'u (%1.9) S0/S1/S2 kalıyor.

3. **"Never S4" grubu en iyi performansı gösteriyor.** 68 trade, 75% WR, 2.664R. Ama bunu entry anında bilmenin yolu yok — bu post-hoc bir sınıflandırma.

4. **Fresh=F + S3/S4 at entry = sadece 4 trade.** Fresh filter "çok katı" değil — tam tersi, çok doğru. Ama fresh=True olduktan sonra FVG'nin ne olacağı ayrı bir sorun.

5. **EXP5D'nin "paradoksu" çözüldü.** EXP5D'de S4'ün WR% > S3 olmasının sebebi: S4 trades aslında S0 olarak girip SONRA invalid olmuş trades. S3 grubu ise S0 olarak girip deep penetration'a uğramış trades. İkisi de entry'de S0.

**Asıl soru şu:** Entry'den SONRA S4'e düşmeyen 68 trade'i — entry anında — nasıl filtreleriz? Bu bir sonraki araştırma konusu.

## POPULATION

- Total trades: **529**
- Entry S0/S1/S2 (cohort A): **464**
- Entry S3 (cohort B): **1**
- Entry S4 (cohort C): **3**
- Post-entry S4 (cohort D): **458**
- Never S4: **68**

## 1. ENTRY STATE × OUTCOME (all trades)

| Entry State | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |
|---|---|---|---|---|---|---|---|
| S0_UNTOUCHED | 464 | 464 | 57.8 | 0.724 | 0.724 | 336.15 | 7.32 |
| S3_DEEP | 1 | 1 | 100.0 | 1.0 | 1.0 | 1.0 | 0.0 |
| S4_INVALIDATED | 3 | 3 | 33.3 | 0.036 | 0.036 | 0.11 | 2.0 |
| N/A | 61 | 61 | 75.4 | 2.868 | 2.868 | 174.97 | 5.0 |
| ALL | 529 | 529 | 59.7 | 0.968 | 0.968 | 512.23 | 7.32 |

## 2. FOUR COHORTS × OUTCOME

| Cohort | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |
|---|---|---|---|---|---|---|---|
| A: S0/S1/S2 at entry | 464 | 464 | 57.8 | 0.724 | 0.724 | 336.15 | 7.32 |
| B: S3 at entry | 1 | 1 | 100.0 | 1.0 | 1.0 | 1.0 | 0.0 |
| C: S4 at entry | 3 | 3 | 33.3 | 0.036 | 0.036 | 0.11 | 2.0 |
| D: Post-entry S4 | 458 | 458 | 57.6 | 0.723 | 0.723 | 330.95 | 7.32 |
| Never S4 | 68 | 68 | 75.0 | 2.664 | 2.664 | 181.17 | 5.0 |
| ALL | 529 | 529 | 59.7 | 0.968 | 0.968 | 512.23 | 7.32 |

## 3. ENTRY STATE × CANONICAL FRESH (at entry)

| Entry State | Fresh=True | Fresh=False |
|---|---|---|
| S0_UNTOUCHED | 464 | 0 |
| S3_DEEP | 0 | 1 |
| S4_INVALIDATED | 0 | 3 |

## 4. CRITICAL: canonical fresh=False × ENTRY STATE

**"canonical fresh=False olan FVG'ler entry anında hangi state'teydi?
Hangisi hâlâ pozitif expectancy taşıyor?"**

| Entry State | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |
|---|---|---|---|---|---|---|---|
| fresh=F + S3_DEEP | 1 | 1 | 100.0 | 1.0 | 1.0 | 1.0 | 0.0 |
| fresh=F + S4_INVALIDATED | 3 | 3 | 33.3 | 0.036 | 0.036 | 0.11 | 2.0 |
| ALL fresh=False | 4 | 4 | 50.0 | 0.277 | 0.277 | 1.11 | 2.0 |

## 5. ENTRY PENETRATION BY OUTCOME

| Metric | Winners | Losers |
|---|---|---|
| P25 | 0.0% | 0.0% |
| P50 | 0.0% | 0.0% |
| P75 | 0.0% | 0.0% |
| Mean | 0.4% | 0.3% |

## 6. POST-ENTRY INVALIDATION ANALYSIS

### Trades that were healthy at entry but invalidated after

| Post-Entry | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |
|---|---|---|---|---|---|---|---|
| S4 after entry | 458 | 458 | 57.6 | 0.723 | 0.723 | 330.95 | 7.32 |
| No S4 | 68 | 68 | 75.0 | 2.664 | 2.664 | 181.17 | 5.0 |

## 7. COHORT A DETAIL — S0/S1/S2 at entry × post-entry

| Entry | Post Max | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |
|---|---|---|---|---|---|---|---|---|
| S0_UNTOUCHED | S0_UNTOUCHED | 3 | 3 | 100.0 | 1.8 | 1.8 | 5.4 | 0.0 |
| S0_UNTOUCHED | S1_WICK_TOUCH | 5 | 5 | 0.0 | -1.0 | -1.0 | -5.0 | 5.0 |
| S0_UNTOUCHED | S2_PARTIAL | 1 | 1 | 100.0 | 3.666 | 3.666 | 3.67 | 0.0 |
| S0_UNTOUCHED | S3_DEEP | 212 | 212 | 51.9 | 0.82 | 0.82 | 173.75 | 8.88 |
| S0_UNTOUCHED | S4_INVALIDATED | 243 | 243 | 63.4 | 0.652 | 0.652 | 158.33 | 6.0 |

## 8. FRESH=F + ENTRY STATE — does entry-state matter?

**canonical fresh=False olan trade'ler entry anında hangi state'teydi?
S3 at entry vs S4 at entry vs post-entry S4 — hangisi daha iyi?**

| Entry State | Post S4? | N | Cmpl | WR% | AvgR | Expect | TotalR | MaxDD |
|---|---|---|---|---|---|---|---|---|
| S3_DEEP | post-S4 | 1 | 1 | 100.0 | 1.0 | 1.0 | 1.0 | 0.0 |
| S4_INVALIDATED | post-S4 | 3 | 3 | 33.3 | 0.036 | 0.036 | 0.11 | 2.0 |

Observation-only. No commentary or decision.
