## RUN — 2026-08-26 14:52:24

**Engine:** experiment/gemini_benchmark_eq.py (canonical, UNCHANGED)
**Variant:** D — FVG-Origin EQ
**Wrapper:** thin monkey-patch (NO pipeline copy)
**EQ Type:** FVG-origin displacement leg midpoint
**EQ TF:** 1H | **EQ Ref:** f = fvg.real_index
**FVG TF:** 15m

### Universe & Data
- **Symbols:** EURUSD
- **Period:** 2024-01-01 → 2026-08-21

### Performance
| Metric | Value |
|--------|-------|
| Trades | 1 |
| WR | 100.0% |
| AvgR | 1.0000 |
| TotalR | +1.00R |
| PF | inf |
| MaxDD | 0.00R |
| MaxDD% | 0.00% |
| Open | 0 |
| Runtime | 11.5s |

### EQ Audit
| Metric | Value |
|--------|-------|
| FVG candidates | 2360 |
| Accepted by D EQ | 879 |
| Rejected by D EQ | 1481 |
| Acceptance rate | 37.2% if total_cand > 0 else 0.0% |

### No-Lookahead Violations
**0** (guaranteed by design: 4×(h+3) ≤ f < f+1)

---

## RUN — 2026-08-26 14:56:09

**Engine:** experiment/gemini_benchmark_eq.py (canonical, UNCHANGED)
**Variant:** D — FVG-Origin EQ
**Wrapper:** thin monkey-patch (NO pipeline copy)
**EQ Type:** FVG-origin displacement leg midpoint
**EQ TF:** 1H | **EQ Ref:** f = fvg.real_index
**FVG TF:** 15m

### Universe & Data
- **Symbols:** EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, GBPJPY
- **Period:** 2024-01-01 → 2026-08-21

### Performance
| Metric | Value |
|--------|-------|
| Trades | 3 |
| WR | 66.7% |
| AvgR | 1.2199 |
| TotalR | +3.66R |
| PF | 4.66 |
| MaxDD | 1.00R |
| MaxDD% | 0.99% |
| Open | 0 |
| Runtime | 174.4s |

### EQ Audit
| Metric | Value |
|--------|-------|
| FVG candidates | 397948 |
| Accepted by D EQ | 111490 |
| Rejected by D EQ | 286458 |
| Acceptance rate | 28.0% |

### No-Lookahead Violations
**0** (guaranteed by design: 4×(h+3) ≤ f < f+1)

---

## RUN — 2026-08-26 15:48:41

**Engine:** experiment/gemini_benchmark_eq.py
**Variant:** D — FVG-Origin EQ
**Canonical Engine Modified:** NO

### Universe & Data
- **Symbols:** EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, GBPJPY
- **Period:** 2024-01-01 → 2026-08-21

### Performance
| Metric | Value |
|--------|------:|
| Trades | 2010 |
| WR | 68.1% |
| AvgR | +1.1192 |
| TotalR | +2249.61R |
| PF | 4.51 |
| MaxDD | 6.61R |
| MaxDD% | 2.93% |

### EQ Audit
| Metric | Value |
|--------|------:|
| FVG candidates | 32735 |
| Accepted | 9143 |
| Rejected | 23592 |
| Acceptance rate | 27.9% |

### Per-Symbol
| Symbol | N | WR% | PnL | AvgR | PF |
|--------|--:|----:|----:|-----:|---:|
| AUDUSD | 330 | 64.2 | +332.15R | +1.0065 | 3.81 |
| EURUSD | 340 | 72.1 | +358.77R | +1.0552 | 4.78 |
| GBPJPY | 327 | 66.7 | +317.29R | +0.9703 | 3.91 |
| GBPUSD | 343 | 68.5 | +361.32R | +1.0534 | 4.35 |
| USDCAD | 328 | 65.2 | +452.73R | +1.3803 | 4.97 |
| USDJPY | 342 | 71.6 | +427.35R | +1.2496 | 5.41 |

### No-Lookahead
- Violations: 0 (4·(h+3) ≤ f guaranteed by design)

### Trade-Level Attribution vs Canonical Frozen
- Common (Frozen ∩ D): 2010
- Frozen-only: 894
- D-only: 0

### Canonical Equivalence
- Canonical engine modified: NO
- Pipeline logic duplicated: NO (uses canonical compute_atr, SessionManager, _nexus_detect_fvgs, _is_fresh_fvg, run_test_a, compute_stats)

---
## RUN — 2026-08-26 16:15:05

**Engine:** experiment/gemini_benchmark_eq.py
**Variant:** D — PURE FVG-Origin EQ
**Canonical Engine Modified:** NO
**Test Type:** Pure EQ variant comparison

### Universe & Data

- Symbols: EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, GBPJPY
- Period: 2024-01-01 → 2026-08-21
- FVG TF: 15m
- EQ TF: 1H

### EQ Definition

`d_eq = (leg_low + leg_high) / 2`

where the leg is anchored at the latest confirmed 1H structural swing available at FVG formation.

### Performance

| Metric | Value |
|---|---:|
| Trades | 2784 |
| WR | 66.5% |
| AvgR | +1.0468 |
| TotalR | +2914.16R |
| PF | 4.12 |
| MaxDD R | 7.36R |
| MaxDD % | 2.73% |

### EQ Audit

| Metric | Value |
|---|---:|
| FVG candidates evaluated | 11092 |
| D EQ accepted | 2809 |
| D EQ rejected | 8283 |
| Acceptance rate | 25.3% |

### No-Lookahead

- Violations: 0 (4·(h+3) ≤ f guaranteed by design)

### Architecture

- Canonical engine modified: NO
- Frozen EQ pre-filter: NO
- Secondary-veto logic: NO
- Fallback logic: NO
- Pure D EQ comparison: YES

---

## RUN — 2026-08-26 16:15:00 — PURE D (Sole EQ Criterion)

**Engine:** experiment/gemini_benchmark_eq.py (canonical, UNCHANGED)
**Variant:** D — PURE FVG-Origin EQ
**Approach:** canonical FVG eval loop with ONLY the EQ source swapped: Frozen EQ → D FVG-Origin EQ. No pre-filter, no post-filter, no fallback.
**EQ Type:** FVG-origin displacement leg midpoint
**EQ TF:** 1H | **EQ Ref:** f = fvg.real_index
**FVG TF:** 15m
**Canonical Engine Modified:** NO

### Universe & Data
- **Symbols:** EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, GBPJPY
- **Period:** 2024-01-01 → 2026-08-21

### Performance
| Metric | Value |
|--------|------:|
| Trades | 2784 |
| WR | 66.5% |
| AvgR | +1.0468 |
| TotalR | +2914.16R |
| PF | 4.12 |
| MaxDD | 7.36R |
| MaxDD% | 2.73% |
| Trailing Trades | 1873 |
| Total Hops | 2524 |
| Avg Hops | 1.35 |
| Avg MFE | +3.2823R |
| Avg MAE | -0.8354R |

### EQ Audit
| Metric | Value |
|--------|------:|
| FVG candidates | 11092 |
| Accepted by D EQ | 2809 |
| Rejected by D EQ | 8283 |
| Acceptance rate | 25.3% |

### Per-Symbol
| Symbol | N | WR% | PnL | AvgR | PF |
|--------|--:|----:|----:|-----:|---:|
| AUDUSD | 471 | 65.2% | +457.17R | +0.9706 | 3.79 |
| EURUSD | 488 | 69.5% | +609.39R | +1.2488 | 5.09 |
| GBPJPY | 459 | 66.7% | +435.04R | +0.9478 | 3.84 |
| GBPUSD | 463 | 64.4% | +363.40R | +0.7849 | 3.20 |
| USDCAD | 447 | 64.2% | +529.12R | +1.1837 | 4.31 |
| USDJPY | 456 | 68.9% | +520.04R | +1.1404 | 4.66 |

### No-Lookahead
- Violations: 0 (4·(h+3) ≤ f guaranteed by design)

### Comparison vs Frozen Baseline
| Metric | Frozen | PURE D | Delta |
|--------|-------:|-------:|------:|
| Trades | 2904 | 2784 | −120 |
| WR | 63.8% | 66.5% | +2.7pp |
| TotalR | +2712.84R | +2914.16R | +201.32R |
| AvgR | +0.9342 | +1.0468 | +0.1126 |
| PF | 3.58 | 4.12 | +0.54 |
| MaxDD | 9.00R | 7.36R | −1.64R |
| MaxDD% | 2.90% | 2.73% | −0.17pp |

### Key Observations
1. **DD reduction: 9.00R → 7.36R (−18.2%)** — primary objective achieved
2. **PnL improved: +2914.16R vs +2712.84R** — rare: lower DD AND higher PnL
3. **Win rate improved: 66.5% vs 63.8%** — D EQ is better quality
4. **Fewer trades: 2784 vs 2904** — D EQ filters out lower-quality candidates
5. **PF improved: 4.12 vs 3.58** — significant improvement
6. **Audit balanced: 11092 = 2809 + 8283** ✓
## RUN — 2026-08-26 17:25:17

**Engine:** experiment/gemini_benchmark_eq.py
**Variant:** D — PURE FVG-Origin EQ
**Canonical Engine Modified:** NO
**Test Type:** Pure EQ variant comparison

### Universe & Data

- Symbols: EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, GBPJPY
- Period: 2024-01-01 → 2026-08-21
- FVG TF: 15m
- EQ TF: 1H

### EQ Definition

`d_eq = (leg_low + leg_high) / 2`

where the leg is anchored at the latest confirmed 1H structural swing available at FVG formation.

### Performance

| Metric | Value |
|---|---:|
| Trades | 2847 |
| WR | 66.1% |
| AvgR | +1.0358 |
| TotalR | +2949.05R |
| PF | 4.05 |
| MaxDD R | 7.36R |
| MaxDD % | 2.76% |

### EQ Audit

| Metric | Value |
|---|---:|
| FVG candidates evaluated | 10397 |
| D EQ accepted | 2869 |
| D EQ rejected | 7528 |
| Acceptance rate | 27.6% |

### No-Lookahead

- Violations: 0 (4·(h+3) ≤ f guaranteed by design)

### Architecture

- Canonical engine modified: NO
- Frozen EQ pre-filter: NO
- Secondary-veto logic: NO
- Fallback logic: NO
- Pure D EQ comparison: YES

---
