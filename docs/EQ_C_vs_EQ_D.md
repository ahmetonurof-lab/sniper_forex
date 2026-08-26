# EQ C vs EQ D — Research Checkpoint

**Date:** 2026-08-26
**Status:** Documentation checkpoint — no logic changes
**Canonical trailing:** 1.8R (TP 2.0 documented as separate experiment, not canonical)

---

## 1. Canonical Engines

| Engine | File | EQ Type | Purpose |
|---|---|---|---|
| **Research C** | `experiment/main_research_c.py` | C2 EQ — Post-Sweep Displacement EQ | Primary benchmark engine, sharp candidate |
| **Research D** | `experiment/main_research_d.py` | PURE D — FVG-Origin EQ | Pure comparison engine, primary candidate |

### Previous Names (renamed 2026-08-26)
- `gemini_benchmark_eq.py` → `main_research_c.py`
- `research_variant_D_fvg_origin_eq_pure.py` → `main_research_d.py`

---

## 2. EQ Formulas

### C2 EQ (Post-Sweep Displacement EQ)
```
eq = (sweep_price + leg_mid) / 2.0
where:
  leg_mid = (max(b.high) + min(b.low)) / 2.0
  window  = bars from sweep_bar to current bar
```
- Anchors EQ toward the sweep price via averaging with the displacement leg midpoint.
- Produces fewer trades (2302 vs 2847) — tighter filtering.
- Higher win rate (69.4% vs 66.1%) — better trade selection.

### PURE D EQ (FVG-Origin EQ)
```
d_eq = (leg_low + leg_high) / 2
where:
  leg = 1H structural swing at FVG formation time
```
- Pure midpoint of the 1H swing leg — no sweep price influence.
- Higher trade count (2847 vs 2302) — more permissive.
- Higher TotalR (+2949R vs +2875R) — more trades contribute to PnL.

---

## 3. Dataset & Configuration

| Parameter | Value |
|---|---|
| Symbols | EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, GBPJPY |
| Timeframe | 15m bars |
| Period | ~2.7 years (2024-01-01 to 2026-08-21) |
| Data source | ICMarket feather files |
| TP_RR | 1.8 (canonical) |
| SL_ATR_MULT | 1.5 |
| ATR_PERIOD | 14 |
| SESSION_START | 19:00 |
| SESSION_END | 01:00 |
| RISK_PER_TRADE | 0.003 |
| Starting Balance | 100.0R |
| Parallelism | ThreadPoolExecutor, 6 workers |

---

## 4. Results Comparison

### Triple Comparison Table

| Metric | Frozen Baseline | C2 EQ | PURE D |
|---|---:|---:|---:|
| Trades | 2904 | **2302** | **2847** |
| WR% | — | **69.4%** | 66.1% |
| TotalR | — | +2875R | **+2949R** |
| PF | — | **5.08** | 4.05 |
| AvgR | — | +1.25R | +1.04R |
| MaxDD (R) | — | 8.00R | **7.36R** |
| MaxDD% | 2.90% | 2.73% | **2.76%** |

### Key Differences

| Dimension | C2 EQ | PURE D |
|---|---|---|
| **Trade count** | 2302 (−21%) | 2847 (baseline) |
| **Win rate** | 69.4% (+3.3pp) | 66.1% |
| **Profit Factor** | 5.08 (+25%) | 4.05 |
| **MaxDD (R)** | 8.00R (+8.7%) | **7.36R** |
| **TotalR** | +2875R | **+2949R** |
| **EQ anchoring** | sweep_price + leg_mid avg | pure 1H swing midpoint |
| **Character** | Sharper, fewer but better trades | More trades, lower PF, lower DD |

### Interpretation
- **C2 EQ** is the **sharp candidate** — higher quality per trade, better PF, but slightly higher MaxDD.
- **PURE D** is the **primary candidate** — more trades, lower MaxDD, lower PF. KNOWN-GOOD FROZEN BENCHMARK status.
- C2 trades are a subset of D trades (D is more permissive).
- Future experiments will keep both EQ formulas fixed — research moves to MaxDD reduction strategies.

---

## 5. Research Status

### Completed
- ✅ C1 (Plain Displacement Midpoint) — REJECTED (too many trades, high DD)
- ✅ C2 (Post-Sweep Displacement EQ) — Implemented, tested, documented
- ✅ PURE D (FVG-Origin EQ) — Implemented, tested, KNOWN-GOOD FROZEN BENCHMARK
- ✅ TP 1.8 vs 2.0 comparison — 1.8 is canonical (trailing dominates)
- ✅ Engine renames — `main_research_c.py` and `main_research_d.py`
- ✅ Documentation checkpoint — this file

### Pending
- MaxDD reduction strategies (A: Concurrent Cap, B: DD Scaling, C: Correlation, D: Streak Breaker, E: Time Filter)
- Recommended: A+D combo for potential MaxDD reduction from 8.00R/7.36R → ~5-6R

---

## 6. Promotion Rules

- PURE D is the **KNOWN-GOOD FROZEN BENCHMARK** — any new variant must beat it head-to-head.
- C2 EQ is a **parallel research candidate** — not frozen, can be evolved.
- A new variant must not only improve PnL but also demonstrate drawdown reduction.
- This benchmark is not deleted if superseded — it is archived.

---

## 7. Canonical Parameters

- **Trailing:** 1.8R canonical — DO NOT CHANGE without explicit research justification.
- **TP 2.0:** Documented as separate experiment (2298T, 68.7% WR, +2886R, PF 5.01, DD 8.00R/2.70%). No material improvement — trailing dominates exit logic.
- **EQ formulas:** Both C2 and D formulas are now frozen for the current research phase.
