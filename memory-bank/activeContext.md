# Active Context

## CHECKPOINT: MaxDD CHRONOLOGY FIX — COMPLETE (2026-08-25)

### Problem Identified
Old `compute_stats()` sorted completed trades by `exit_bar_index` for portfolio equity curve construction. This was INCORRECT because `exit_bar_index` is a symbol-local index, not a global chronological position.

**Why this matters for multi-symbol portfolios:**
- Symbol A might have `exit_bar_index=150` at timestamp 2026-07-25 14:00
- Symbol B might have `exit_bar_index=50` at timestamp 2026-08-01 09:00
- Sorting by `exit_bar_index` would incorrectly place B's trade before A's even though B's trade happened 7 days LATER
- This corrupts the portfolio equity curve order and produces incorrect MaxDD values

### Correct Methodology
```
1. completed/realized trades only (OPEN trades excluded from equity curve)
2. sort by actual exit_timestamp (from bars_15m data)
3. build single portfolio equity curve chronologically
4. running peak tracking
5. peak-to-trough MaxDD calculation
```

### MaxDD_R Formula
```
equity_t = equity_(t-1) + pnl_r_t
peak_t = max(peak_(t-1), equity_t)
DD_t = peak_t - equity_t
MaxDD_R = max(DD_t)  [across all t]
```

### MaxDD% Formula
```
DD%_t = DD_t / peak_t * 100
MaxDD% = max(DD%_t)  [across all t where peak_t > 0]
```

### Changes Made (experiment/gemini_benchmark_eq.py)
1. `BenchmarkTrade` dataclass: added `exit_timestamp: float = 0.0`
2. Four trade closing points now populate `exit_timestamp`:
   - `run_test_a` normal exit: `bar.timestamp` (the bar where exit occurred)
   - `run_test_a` OPEN trade: `last_bar.timestamp` (final bar of dataset)
   - `run_test_b` normal exit: `bar.timestamp`
   - `run_test_b` OPEN trade: `last_bar.timestamp`
3. `compute_stats()` now sorts by `exit_timestamp` instead of `exit_bar_index`
4. MaxDD% field added to return dict

### What Was NOT Changed
- Strategy/trade generation logic unchanged (entry, exit, TP, SL, FVG, sweep, config)
- `apply_trailing()`, `check_exit()`, PnL calculation all unchanged
- Old benchmark result files not modified
- No backtest run during this fix session

### Known Old Values (DO NOT USE AS TARGET)
- Old reports showed 7.32R (EXP5F, 529 trades) and 12.73R (KNOWN-GOOD, 1262 trades)
- These used `exit_bar_index` sorting → incorrect chronology
- New correct implementation will produce different values
- Real results from new backtest run will be the legitimate values

### Next Step
- Run new benchmark/backtest with the corrected code
- Compare new MaxDD_R and MaxDD% against old values
- Validate that the fix produces correct chronological ordering

---

## CHECKPOINT: MaxDD STARTING_BALANCE FIX — COMPLETE (2026-08-26)

### Problem
MaxDD% was showing 100% for all runs because `equity = 0.0; peak = 0.0`.
First losing trade created `dd = peak - equity = 0 - (-R) = R/R = 100%`.

### Root Cause
`compute_stats()` initialized equity at 0 instead of `STARTING_BALANCE_R`.

### Fix Applied
- `gemini_benchmark_eq.py`: `equity = peak = starting_balance = 100.0`, `compute_stats(trades, starting_balance=100.0)`
- `exp5f_frozen_vs_dynamic_eq.py`: `cum = peak = STARTING_BALANCE_R = 100.0`, `dd_pct / peak_pct * 100`
- `gemini_benchmark.py`: `_is_fresh_fvg` O(n) slice `bars_15m[scan_from:current_index]`

### Verified Results
| Script | Trades | MaxDD% |
|--------|--------|--------|
| gemini_benchmark_eq.py (full 2.7yr) | 2904 | 2.90% |
| exp5f_frozen_vs_dynamic_eq.py (180d) | 529/469 | 1.8–5.1% |

### Dual Benchmark Architecture (2026-08-26)
| Script | Purpose | Data Window |
|--------|---------|-------------|
| gemini_benchmark_eq.py | Full-data research motoru | Full (2.7yr) |
| exp5f_frozen_vs_dynamic_eq.py | 180-day kontrollü karşılaştırma | 180-day sliding |

### Commit
- `0561b22` — fix: MaxDD%=100% bug — equity starts at 100R not 0
- 3 files: gemini_benchmark_eq.py + exp5f_frozen_vs_dynamic_eq.py + gemini_benchmark.py
- Pushed to origin/main

---

## LIVE ↔ BACKTEST PARITY AUDIT — PASS (2026-08-22, read-only)

### 1. TIME SOURCE
- Dataset timestamps are naive MT5 server time.
- ICMarketsSC-Demo live server verified against the dataset (same terminal,
  same account 53012914 as manifest).
- Current dataset period maps to UTC+3.
- Active strategy uses server-time directly; NO timezone conversion anywhere
  in the active pipeline (DataLoader / SessionManager / resample_15m).

### 2. DATA PARITY — PASS
- EURUSD: 4479/4479 overlapping bars vs live MT5, exact OHLC within float epsilon.
- BTCUSD: 4479/4479 exact OHLC; tick_volume exact on both symbols.
- Weekend/session structure matches (0 Sat/Sun FX bars on both axes).

### 3. EVENT PARITY — PASS
- 24 representative events reconstructed successfully (multi-symbol,
  both directions, CBDR + day sessions, winners + losers).
- BASE∩EQ shared 987 events: direction / zone / entry / risk = 100% agreement.
- The 4/150 CBDR-window anomaly and 2/987 sweep_bar_index anomaly were traced
  to the comparison mapping/resampling method (resample_15m drops <3-bar
  buckets), NOT to strategy behavior. Re-check with faithful mapping: 0 anomalies.

### 4. TRADE PARITY — PASS
- Frozen direction-fix benchmark verified (results/benchmark/abfix_*).
- PROFIT_TRAIL direction: 812/812 correct (long exits above, short below entry).
- SL/TP geometry and expected R behavior verified (LOSS = -1.000R exact,
  TP median = 1.800R exact); trailing lock-in beyond entry confirmed legitimate.
- hold_bars parity confirmed within expected OPEN-trade exceptions.

### 5. PERMANENT ARCHITECTURAL RULE
LIVE MT5 behavior is now the ground truth. The backtest/execution system must
deterministically reproduce live MT5 behavior rather than merely approximate it.

### 6. FUTURE WORK RULE
Any future strategy/backtest/execution change must preserve LIVE ↔ BACKTEST
parity unless the deviation is explicitly intended, isolated, measured,
and documented.

## INTERNAL SWEEP RESEARCH — CLOSED, BOTH VARIANTS REJECTED (2026-08-22)

Detection-only counterfactual on frozen EQ benchmark (read-only; no code,
benchmark or execution changes; single disposable script, deleted after run).

### v1 — Loose internal sweep (20-bar lookback, pivot 1/1)
- 1262/1262 trades replayed via `detect_internal_sweep` at recorded zone_index.
- Pass rate 97.62% (1232/1262) → nearly non-binding filter.
- Filtering the FALSE group (n=30, +36.9R) would WORSEN total performance.
- Permutation p=0.075 (not significant); advantage flips sign H1 vs H2
  (chronologically unstable).
- **DECISION: REJECT.**

### v2 — MSS-anchored internal sweep (sweep → MSS(body-close) → minor HH/LL → ISW → FVG)
- Exact anchor reconstruction: 1262/1262 sweep anchors reproduced (replay rules:
  session.update() from warmup+1 only; skipped during open trades [entry..exit];
  session ATR frozen at warmup value). MSS = system's own body-close proxy.
- All chain events bounded ≤ zone_index−1 (no post-FVG data used).
- Coverage: MSS found 90.1%; FULL_CHAIN 63.8%.
- avg R: FULL_CHAIN 0.559 < MSS_ONLY 0.610; NO_MSS best WR (64.8%) — chain
  ordering INVERTED vs hypothesis. Permutation p=0.75 (no signal).
- Applying the filter would remove ~38% of total R (~722R → ~449R).
- Chronologically unstable (H1/H2 sign flip; F3 anomaly).
- **DECISION: REJECT.**

### Permanent research conclusion
- In the current NEXUS 15m entry structure, the minor HH/LL internal-sweep +
  MSS chain carries NO incremental information for EQ-selected entries.
- This research line is CLOSED. No parameter sweeps will be run on it.

### Preserved state
- Parity checkpoint above remains valid: DATA / EVENT / TRADE PARITY = PASS.
- Frozen benchmark (results/benchmark/abfix_*) remains KNOWN-GOOD reference.

## Current Phase: KNOWN-GOOD BENCHMARK FREEZE (2026-08-22)

### Direction-Dispatch Bug — FIXED (current reference)
- Trade direction values reached execution as "bullish"/"bearish" while
  execution/trailing branching expected "long"/"short" → LONG trades were
  managed as SHORT (instant bar.high>=sl kill, TP unreachable, fake wins).
- Normalization at execution boundary in experiment/ adapter layer:
  `bullish → long`, `bearish → short` (`_norm_side()` in trailing_adapter.py).
  Trade records keep direction labels; `src/` was NOT modified by this fix.
- Validation: validate_direction_fix.py = **17/17 PASS**
- Reference ADAUSD trade: entry=0.16620 SL=0.16537 TP=0.16768
  → PROFIT_TRAIL @ 0.16813, +2.344R.

### Frozen benchmark (98 symbols, full data, 15m) — CURRENT REFERENCE
EQ vs BASELINE:
- 1471 → 1262 trades
- WR 51.1% → 58.2%
- +577.02R → +722.72R (+145.70R delta)
- PF 1.80 → 2.37
- DD 27.17R → 12.73R (~53% reduction)
- EQ rejected candidates: 29,925
Directional:
- BASELINE bull 628T/305W/321L WR48.7% +316.67R PF1.99 | bear 843T/445W/398L WR52.8% +260.36R PF1.65
- EQ bull 528T/290W/236L WR55.1% +414.44R PF2.76 | bear 734T/443W/290L WR60.4% +308.27R PF2.06

### CRITICAL HISTORICAL WARNING
Pre-fix execution results are INVALID as execution-behavior benchmarks because
the direction-dispatch bug corrupted trailing behavior.
Do NOT use old pre-fix benchmark numbers for future comparisons.
Reference doc: docs/KNOWN_GOOD_BENCHMARK.md

### Repository state (sterilization inventory completed)
- No files deleted, no files moved, no code cleanup performed yet.
- `src/` diff remains empty.
- `index.json` is modified by an external indexing operation and remains
  pending user decision.
- No commit. No push.

## DD UNIVERSE AUDIT — COMPLETE (2026-08-22, read-only)

Analyzed frozen EQ benchmark (abfix_eq_trades.json, 1262 trades, 97/98 symbols).

### Key finding: No symbol meets the >=500-trade threshold
- Max trades per symbol in current benchmark: 25 (variant_B, ACAD.NAS-24 / similar)
- Median trades per symbol: ~16
- The >=500-trade research universe requires longer data period or expanded symbol set

### Primary universe (MaxDD >= 1.0% AND >=500 trades): 0 symbols
### Near-target (0.75% <= MaxDD < 1.0% AND >=500 trades): 0 symbols

### DD distribution (all symbols with trades):
- Min MaxDD%: 0.30%
- Median MaxDD%: 0.66%
- Max MaxDD%: 2.08%

### Top 5 by MaxDD% (any trade count):
- EURHKD: 2.08%, 17 trades
- USDHKD: 2.01%, 10 trades
- SGDJPY: 1.73%, 15 trades
- ADAUSD: 1.52%, 20 trades
- USDSGD: 1.49%, 16 trades

### Symbols with MaxDD >= 1.0%: 26 / 97
### Symbols with MaxDD >= 2.0%: 2 / 97

Audit script: scripts/audit_dd_universe.py (read-only, does not modify benchmark)

## Previous Phase: POST-PHASE 4 -- OPEN INVESTIGATION

## Completed Phases

### Phase 0: Bootstrap - COMPLETE
- 7/7 architecture validation passed
- Project structure verified
- Minimal dependencies (MetaTrader5, python-dotenv)
- Architecture: config -> data/trading -> strategy -> main
- .env loading fixed from project root
- No credentials hardcoded or committed

### Phase 1: MT5 Real Data Probe - COMPLETE
- Created src/test_mt5_data.py probe module
- Probes real market data from IC Markets MT5 terminal
- Symbol information, live tick data, OHLC bars (M1/M5/M15/H1)
- Data quality validation (chronological, OHLC validity, bid/ask)
- Clean shutdown lifecycle

### Phase 2A: Strategy Specification - COMPLETE
- Created docs/SNIPER_FOREX_STRATEGY_SPEC.md (377 lines)
- 17-section comprehensive strategy specification
- All SNIPER strategy concepts documented
- No strategy code implemented (preserved conceptually)
- All unresolved decisions explicitly marked as UNRESOLVED

### Phase 2A.1: Spec Hardening - COMPLETE
- Added clarification to Section 4 (Bias Rejection)
- CBDR time window explicitly unresolved
- Retrace terminology resolved (NO-FVG HOLD vs ATR FALLBACK)
- Rejection paths documented
- Per-symbol state isolation explicit
- Daily reset/open-position interaction explicit
- Timestamp timezone policy explicit

### Phase 2B.2: Forex Backtest Infrastructure - COMPLETE
- Created src/backtest/ module with 9 components
- 22 comprehensive tests all passing

### Data Acquisition - COMPLETE
- 98 symbols from MT5, 3,085,613 M1 bars
- Date range: 2026-07-21 to 2026-08-20
- Raw: 165 MB CSV, Feather: 73.5 MB
- Duplicates: 0, Invalid OHLC: 0
- MT5 fix: initialize() requires explicit login/password/server

### Phase 3: Real Data Strategy Baseline - COMPLETE
- Baseline: CBDR sweep + FVG + first-touch + 1.8R TP
- Full 98-symbol backtest: 1,845 trades, 59.3% WR, +1,221R
- DataLoader optimized 15x
- No-lookahead invariant enforced
- Key: bias_locked mechanism = 1 sweep -> 1 trade per CBDR cycle

### Phase 3.2: Liquidity Source Forensics - COMPLETE
- Compared CBDR vs SESSION_HL vs SWING_HL (same dataset)
- SESSION_HL and SWING_HL NEWLY DEFINED for this analysis

| Source | Events | Trades | WR | PF | Avg R | Max DD |
|--------|--------|--------|-----|-----|-------|--------|
| CBDR | 1,826 | 1,826 | 76.2% | 5.77 | +1.13R | 4.0R |
| SESSION_HL | 7,558 | 7,558 | 75.4% | 5.52 | +1.11R | 25.8R |
| SWING_HL | 6,932 | 6,873 | 83.6% | 9.15 | +1.34R | 34.2R |

Key finding: SWING_HL highest WR/PF. CBDR NOT proven uniquely superior.
1-month data insufficient for statistical significance.

### Phase 4: Sweep Lifecycle Forensics - COMPLETE

Core Finding: 1 sweep = 1 trade (100%). CURRENT = ONE-SHOT = FRESH-SWEEP (all identical).
Results: 1,845T, 59.35% WR, PF 2.628, +1,221R.
All FVGs after sweep (100%), no sweep produces 2+ trades.
Median ~20 bars sweep-to-FVG, entry 1 bar after FVG.
bias_locked prevents multiple sweeps per CBDR cycle.

## OPEN INVESTIGATION: CBDR Sweep vs FVG Origin

Status: **HYPOTHESIS -- NOT VALIDATED**

Question: Is CBDR sweep the CAUSE of subsequent FVG,
or does FVG form independently after sweeps?

What We Know:
- 100% FVGs appear AFTER sweep bars
- Median ~20 bars between sweep and FVG
- Edge (59.35% WR) exists
- CBDR sweep is current mandatory gate

What We Do NOT Know:
- Whether FVGs form at same rate WITHOUT preceding sweep
- Whether FVG is caused by sweep displacement or independent continuation
- Whether FVG is reversal or continuation pattern
- Whether sweep-to-FVG distance correlates with edge
- Whether CBDR is necessary or any sweep suffices

Hypothesis (UNVALIDATED):
Real edge may not be "sweep triggers FVG" but rather:
- Bias + FVG continuation pattern
- Sweep just confirms bias direction
- FVG forms from independent price displacement
- CBDR is useful bias filter, not cause of setup

What Would Validate/Refute:
- Test FVGs WITHOUT preceding sweep -> similar WR?
- Measure FVG quality by sweep-to-FVG distance
- Compare CBDR-gated vs unfiltered FVGs
- Measure FVG size/distance vs PnL correlation

Decision Status:
- NOT DECIDED: remove CBDR as mandatory gate
- NOT DECIDED: FVG reversal vs continuation
- NOT DECIDED: sweep-to-FVG distance as quality signal
- NOT DECIDED: CBDR necessary vs just convenient

## NEXT STEPS
1. Test FVG quality without CBDR gate (open investigation)
2. Multi-source sweep integration
3. Remove bias_locking constraint
4. Download 3-6 month data for majors
5. Validate 59.35% WR over longer period

## Current Git Baseline
- Repository: ahmetonurof-lab/sniper_forex
- Branch: main

## Strategy Layer Rules
- Strategy must not directly import/call MT5
- .env credentials are never committed
- Strategy must be independently testable without MT5
- Per-symbol strategy state isolation required
- Do not invent unresolved strategy rules
- Tests are behavioral contracts
- No-lookahead invariant: decision at time T uses only data <= T

## Tech Stack
- Python 3.12.2
- MetaTrader5 5.0.6090
- python-dotenv
- pandas, numpy
- MT5 IC Markets demo environment
- MT5 Server Time (timezone unverified)
