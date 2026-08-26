# CANONICAL BENCHMARK REFERENCE

**Last Updated:** 2026-08-26
**Status:** ACTIVE — benchmarks below are mechanically validated

---

## ⚠️ ABSOLUTE RULE

> **"OLDER RESULTS BEFORE THE DIRECTION-DISPATCH FIX
> ARE INVALID AS EXECUTION-BEHAVIOR BENCHMARKS."**
>
> Pre-fix results MUST NOT be used as execution-behavior benchmarks.
> Future experiments MUST compare against this canonical benchmark only.

---

## 1. DIRECTION-DISPATCH BUG (Historical — Fixed)

- Trade direction values reached the execution layer as `"bullish"` / `"bearish"`.
- Execution/trailing branching expected `"long"` / `"short"`.
- As a result, LONG trades were managed as SHORT trades.

### Fix Applied

Normalized at the execution boundary in `experiment/trailing_adapter.py` via
`_norm_side()`:

- `bullish → long`
- `bearish → short`

- Trade records keep their original direction labels for reporting.
- `src/` was NOT modified by this fix (`git diff -- src/` = empty).
- No strategy rules, sweep/FVG detection, EQ filter, entry logic, SL/TP
  placement or trailing parameters were changed.

---

## 2. VALIDATION (Historical)

`validate_direction_fix.py`: **17/17 PASS**

Reference ADAUSD trade:

| Field | Value |
|---|---|
| Entry | `0.16620` |
| SL | `0.16537` |
| TP | `0.16768` |
| Exit | `PROFIT_TRAIL @ 0.16813` |
| Result | `+2.344R` |

---

## 3. CANONICAL BENCHMARK UNIVERSE

### Tier 1 — CORE / CANONICAL

```
EURUSD
GBPUSD
USDJPY
AUDUSD
USDCAD
GBPJPY
```

- **Horizon:** Full available dataset (~2.7 years, 2024-01-01 to 2026-08-21)
- **Engine:** `experiment/main_research_c_v1_0.py`
- **EQ Mode:** Frozen / Real EQ — `eq = (sweep_price + range_opposite) / 2`
- **Status:** CANONICAL REFERENCE

### Tier 2 — Liquidity Expansion

```
USDCHF
NZDUSD
EURJPY
AUDJPY
EURGBP
NZDJPY
```

- **Status:** Future expansion universe. Not part of canonical benchmark at this time.
- No canonical benchmark results exist for Tier 2 pairs.

### Results — Tier 1 Canonical (FROZEN — PURE D)

> **This is the KNOWN-GOOD FROZEN BENCHMARK.**
> Engine: `experiment/main_research_c_v1_0.py` (UNCHANGED)
> Variant: D — PURE FVG-Origin EQ
> Artifact: `results/benchmark/PURE_D_FVG_ORIGIN_EQ_benchmark.json`

| Metric | Value |
|---|---:|
| Trades | **2847** |
| Wins | **1881** |
| Losses | **966** |
| WR | **66.1%** |
| Total R | **+2949.05R** |
| Avg R | **+1.0358** |
| PF | **4.05** |
| MaxDD R | **7.36R** |
| MaxDD % | **2.76%** |

| Symbol | N | WR% | PnL | AvgR | PF |
|---|---:|---:|---:|---:|---:|
| EURUSD | 503 | 68.6% | +578.81R | +1.1507 | 4.66 |
| USDJPY | 465 | 68.2% | +515.16R | +1.1079 | 4.48 |
| GBPJPY | 472 | 66.7% | +457.50R | +0.9693 | 3.91 |
| AUDUSD | 481 | 64.9% | +450.15R | +0.9359 | 3.66 |
| USDCAD | 454 | 63.4% | +572.46R | +1.2609 | 4.45 |
| GBPUSD | 472 | 64.4% | +374.97R | +0.7944 | 3.23 |

> EQ Definition: `d_eq = (leg_low + leg_high) / 2`
> Canonical engine modified: NO
> No-lookahead violations: 0
> Promotion rule: a new variant must beat this benchmark in a head-to-head comparison.

---

## 4. BENCHMARK ENGINE REFERENCE

### Canonical Motor

| Field | Value |
|---|---|
| **Script** | `experiment/main_research_c_v1_0.py` |
| **Test** | `run_test_a` (POST_SWEEP_FVG) |
| **Data** | `data/icmarket_feather/{SYMBOL}_15m.feather` |
| **Symbols** | 6 majors (Tier 1) |
| **Horizon** | Full feather data (~2.7 years) |
| **EQ (Frozen Benchmark)** | D FVG-Origin EQ: `d_eq = (leg_low + leg_high) / 2` |
| **EQ (Original)** | Frozen EQ: `eq = (sweep_price + range_opposite) / 2` |
| **Starting Balance** | 100.0 R |
| **MaxDD Method** | Chronological `exit_timestamp` sort, `peak = starting_balance` |
| **Frozen Benchmark ID** | `PURE_D_FVG_ORIGIN_EQ` |
| **Frozen Benchmark Artifact** | `results/benchmark/PURE_D_FVG_ORIGIN_EQ_benchmark.json` |
| **Canonical Engine Modified** | NO (byte/semantic identical to origin/main) |

### Research Variant

| Field | Value |
|---|---|
| **Script** | `experiment/exp5f_frozen_vs_dynamic_eq.py` |
| **Variant** | Dynamic / Research EQ |
| **Formula** | `research_eq = (swing_high + swing_low) / 2` |
| **Window** | 180-day sliding |
| **Symbols** | 6 majors |
| **Status** | Research only — NOT CANONICAL |
| **Artifact** | `results/research/exp5f_frozen_vs_dynamic.json` |

### Non-Canonical Motor

`experiment/gemini_benchmark.py` is the original dual-test benchmark script
(runs both `run_test_a` and `run_test_b`). It is used for variant comparison
(A/B/C) but is NOT the canonical benchmark motor. Do not use its outputs as
the canonical reference.

---

## 5. LEGACY BENCHMARK (Historical — Superseded)

> The following numbers are from a **superseded benchmark run** on a different
> universe (98 symbols). These are kept for historical reference only and must
> NOT be used as canonical benchmark comparisons.

| Metric | BASELINE (98 sym) | EQ (98 sym) |
|---|---|---|
| Trades | 1471 | 1262 |
| WR | 51.1% | 58.2% |
| Total R | +577.02R | +722.72R |
| Avg R | +0.39 | +0.57 |
| PF | 1.80 | 2.37 |
| DD | 27.17R | 12.73R |

- **Universe:** 98 symbols (6 majors + 12 minors + additional pairs)
- **Period:** Full feather data (~2.7 years)
- **Direction-dispatch fix:** Applied in `0561b22`
- **Status:** Superseded by Tier 1 6-major canonical definition

---

## 6. FILE REFERENCE

### Canonical Benchmark Chain

- `experiment/main_research_c_v1_0.py` — canonical motor (Research C: C2 EQ)
- `experiment/trailing_adapter.py` — direction normalization (`_norm_side()`)
- `experiment/config.py` — strategy parameters
- `src/strategy/data_loader.py` — feather data loading
- `src/strategy/session.py` — CBDR/sweep session management
- `src/strategy/models.py` — Bar, SweepEvent, Direction models

### External Dependencies

- `C:/Users/Administrator/Desktop/nexus-mcp/sniper/src/fvg.py`
- `C:/Users/Administrator/Desktop/nexus-mcp/sniper/src/models.py`
- `C:/Users/Administrator/Desktop/nexus-mcp/sniper/src/pivot.py`

### Research Variant

- `experiment/exp5f_frozen_vs_dynamic_eq.py` — Dynamic EQ research motor
- `results/research/exp5f_frozen_vs_dynamic.json` — 180-day Dynamic EQ trades (469T)

### Legacy (Superseded)

- `experiment/gemini_benchmark.py` — original dual-test script
- `results/benchmark/abfix_eq_trades.json` — 1262 trades, 98 symbols
- `results/benchmark/abfix_summary.json` — legacy summary

---

## 7. KNOWN-GOOD FROZEN BENCHMARK — PURE D FVG-ORIGIN EQ

**Status:** KNOWN-GOOD FROZEN BENCHMARK
**Benchmark ID:** `PURE_D_FVG_ORIGIN_EQ`
**Created:** 2026-08-26
**Canonical Engine Modified:** NO

### Definition

- **Variant:** D — PURE FVG-Origin EQ
- **Engine:** `experiment/main_research_c_v1_0.py` (UNCHANGED)
- **Variant File:** `experiment/main_research_d_v1_0.py`
- **EQ Type:** FVG-origin displacement leg midpoint
- **EQ Timeframe:** 1H
- **EQ Formula:** `d_eq = (leg_low + leg_high) / 2`
- **Leg Anchor:** latest confirmed 1H structural swing at FVG formation
- **Position Filter:** bullish: `fvg_top > d_eq` → REJECT; bearish: `fvg_bottom < d_eq` → REJECT
- **No-Lookahead:** `confirm_15m = 4*(pivot_1h+4)-1 ≤ f`, guaranteed by design
- **Chronology:** CORRECT-CHRONOLOGY (FIFO via bar iteration)

### Universe

- **Symbols:** EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, GBPJPY
- **Tier:** Tier 1 — CORE / CANONICAL
- **Period:** 2024-01-01 → 2026-08-21
- **Timeframe:** 15m
- **Horizon:** ~2.7 years

### Overall Results

| Metric | Value |
|---|---:|
| Trades | 2847 |
| Wins | 1881 |
| Losses | 966 |
| WR | 66.1% |
| TotalR | +2949.05R |
| AvgR | +1.0358 |
| PF | 4.05 |
| MaxDD | 7.36R |
| MaxDD% | 2.76% |

### Per-Symbol

| Symbol | N | WR% | PnL | AvgR | PF |
|---|---:|---:|---:|---:|---:|
| EURUSD | 503 | 68.6% | +578.81R | +1.1507 | 4.66 |
| USDJPY | 465 | 68.2% | +515.16R | +1.1079 | 4.48 |
| GBPJPY | 472 | 66.7% | +457.50R | +0.9693 | 3.91 |
| AUDUSD | 481 | 64.9% | +450.15R | +0.9359 | 3.66 |
| USDCAD | 454 | 63.4% | +572.46R | +1.2609 | 4.45 |
| GBPUSD | 472 | 64.4% | +374.97R | +0.7944 | 3.23 |

### EQ Audit

| Metric | Value |
|---|---:|
| FVG candidates | 10397 |
| Accepted by D EQ | 2869 |
| Rejected by D EQ | 7528 |
| Acceptance rate | 27.6% |

### Artifact

- **Benchmark JSON:** `results/benchmark/PURE_D_FVG_ORIGIN_EQ_benchmark.json`
- **Run Summary:** `results/research/variant_D_fvg_origin_eq_summary.md`
- **Full Summary JSON:** `results/research/variant_D_fvg_origin_eq_pure_summary.json`
- **Trade-Level:** `results/research/variant_D_fvg_origin_eq_pure_trades.json`
- **Candidate Audit:** `results/research/variant_D_fvg_origin_eq_pure_candidates.json`

### Immutability

- Do not modify this benchmark artifact.
- Do not add strategy rules, filters, or execution changes.
- This is a frozen reference for future regression/comparison.
- Promotion rule: a new variant must beat this benchmark in a head-to-head comparison via a separate process.
- This benchmark is not deleted if superseded; it is archived.
