# Progress — Per-Experiment Log

> Companion to `memory-bank/activeContext.md` (the control panel).
> This file is the chronological per-experiment log for the MaxDD research
> line. Every experiment entry MUST contain: what was tested, which engine,
> which dataset, isolated variable, result, decision, next test.
> Last updated: 2026-08-27.

---

## PRODUCTION IMPLEMENTATION LOG (MT5 DEMO)

> Master task list: `docs/MT5_IMPLEMENTATION_ROADMAP.md`.
> This section logs production-transition milestones (separate from research).

### PHASE 1 — MT5 FOUNDATION (COMPLETE 2026-08-27)

- **What was done:** Hardened the MT5 connection + data layer for production.
- **Files changed:**
  - `src/trading/mt5_connection.py` — added path-based initialize, `last_error`
    capture, `is_connected()`, `reconnect()`, `ensure_connected()`, robust error
    handling on all data-access methods.
  - `src/data/mt5_data.py` — added `last_error` capture + robust error handling.
  - `tests/test_mt5_connection_hardening.py` — NEW, 10 synthetic unit tests
    (mock MetaTrader5; no real terminal required).
- **Tests run:**
  - `python -m src.test_mt5_connection` → 7/7 PASS.
  - `python -m pytest tests/test_mt5_connection_hardening.py` → 10/10 PASS.
  - `python -m pytest tests/` → 100/100 PASS.
- **Result:** Connection, failure handling, reconnect, tick/rates access all PASS.
- **Frozen engines:** `main_research_c_v1_0.py` + `main_research_d_v1_0.py` git
  diff CLEAN (verified). No strategy behavior changed.
- **Decision:** PHASE 1 COMPLETE. Proceed to PHASE 2.
- **Next task:** PHASE 2 — MARKET DATA / 15M CANDLE FEED (M1 feed, forming vs
  closed candle, dup/missing detection, warmup, timezone, canonical 15m
  aggregation parity with `resample_15m()`).

### PHASE 2 — MARKET DATA / 15M CANDLE FEED (COMPLETE 2026-08-27)

- **What was done:** Built the live M1 feed → canonical 15m closed candle
  production under the new `src/live/` package.
- **Files changed:**
  - `src/live/__init__.py` — NEW, live runtime package.
  - `src/live/clock.py` — NEW, server-time UTC offset (summer +3 / winter +2),
    session window 19:00→01:00, server↔UTC conversion.
  - `src/live/candle_feed.py` — NEW, `M1CandleFeed` (fetch_m1, find_duplicates,
    find_missing, is_closed_m1, warmup, update) + `resample_15m()` parity.
  - `tests/test_live_candle_feed.py` — NEW, 16 synthetic unit tests.
- **Key design decisions:**
  - `resample_15m()` re-implemented to match the frozen engine EXACTLY
    (epoch//15min slot, first-bar label, drop <3-bar buckets) — live runtime
    does NOT import from the frozen research engine.
  - Server-time → UTC conversion uses the CURRENT server offset (one offset per
    live session), not each bar's own date — matches how MT5 reports time.
- **Tests run:**
  - `python -m pytest tests/test_live_candle_feed.py` → 16/16 PASS.
  - `python -m pytest tests/` → 116/116 PASS.
- **Result:** Same M1 input → same 15m OHLC/timestamp as canonical backtest
  (parity verified). Dup/missing detection, forming-vs-closed, warmup, timezone
  all PASS.
- **Frozen engines:** `main_research_c_v1_0.py` + `main_research_d_v1_0.py` git
  diff CLEAN (verified). No strategy behavior changed.
- **Decision:** PHASE 2 COMPLETE. Proceed to PHASE 3.
- **Next task:** PHASE 3 — STRATEGY RUNTIME (port backtest strategy behavior to
  live runtime: SessionManager → CBDR → Sweep → Bias → FVG → EQ → First FVG →
  First Touch → Signal; per-symbol state; candle event loop; restart recovery).

### PHASE 3 — STRATEGY RUNTIME (COMPLETE 2026-08-27)

- **What was done:** Ported the backtest strategy entry/SL/TP core to a live
  runtime with per-symbol state and restart recovery.
- **Files changed:**
  - `src/live/strategy_runtime.py` — NEW, `StrategyRuntime` + `Signal`. Ports
    `run_test_a` entry/SL/TP core. Reuses `SessionManager`,
    `apply_trailing`/`check_exit`/`_norm_side`, nexus `detect_fvgs`.
  - `src/live/state.py` — NEW, `StateStore` atomic JSON persistence
    (`state/<SYMBOL>.json`) for restart recovery.
  - `tests/test_live_strategy_runtime.py` — NEW, 4 replay parity tests.
- **Key design decisions:**
  - Pending-entry model: touch on closed bar i → pending (SL/TP at bar i) →
    fill at next bar open → active trade + Signal.
  - Live runtime does NOT import from the frozen research engine — it reuses
    shared modules (`SessionManager`, `trailing_adapter`) and nexus FVG.
- **Parity bug fixed (EURUSD 406 vs 407 signals):**
  1. Entry bar must be processed immediately (apply_trailing + check_exit on
     the fill bar) — otherwise a trade that trails+exits on its own entry bar
     is missed.
  2. Sweep must NOT be reset at pending/touch time. Reset only after a trade is
     created. MIN_RISK_DIST failure must fall through to re-scan FVGs with the
     same sweep (canonical `continue`s).
- **Tests run:**
  - `python -m pytest tests/test_live_strategy_runtime.py` → 4/4 PASS.
  - `python -m pytest tests/` → 120/120 PASS.
- **Result:** EURUSD + GBPUSD replay parity with canonical engine
  (signal/SL/TP). State roundtrip preserves runtime.
- **Frozen engines:** `main_research_c_v1_0.py` + `main_research_d_v1_0.py` git
  diff CLEAN (verified). No strategy behavior changed.
- **Decision:** PHASE 3 COMPLETE. Proceed to PHASE 4.
- **Next task:** PHASE 4 — RISK + POSITION SIZING (risk engine + lot sizing:
  account balance/equity, risk per trade, lot calc, contract specs, volume
  min/max/step, stop distance, spread, exposure, broker constraints;
  `src/live/risk.py`, `src/live/sizing.py`; RISK_PER_TRADE=0.003 reference).

---

## MAXDD RESEARCH LINE — Per-Experiment Log

### Exp A — Concurrent Exposure Cap = 3 (C v1.0)

- **What tested:** cap the maximum number of concurrently open positions
  across the 6-major portfolio to 3.
- **Engine:** C v1.0 (`experiment/main_research_c_v1_0.py`, UNTOUCHED).
- **Dataset:** 6 majors (EURUSD, GBPUSD, GBPJPY, USDJPY, AUDUSD, USDCAD),
  2.7Y, 15m bars, full.
- **Isolated variable:** post-hoc portfolio overlay that rejects new
  entries when open-position count >= 3. Single lever.
- **Result:** 0 blocked entries. C2 baseline (2302T / +2875.00R / MaxDD
  8.00R / 2.73%) unchanged on every metric. Cap=3 never binding because
  max concurrent positions across the 6 majors never reached 3.
- **Decision:** **REJECT — non-binding / no strategic impact.**
- **Next test:** Exp B (3-loss circuit breaker).
- **File:** `experiment/exp_maxdd_A_concurrent_cap.py`.
- **Outputs:** `results/research/expA_concurrent_cap_summary.json`,
  `results/research/expA_concurrent_cap_trades.json`.

### Exp B — 3-Loss / 12-bar Circuit Breaker (C v1.0)

- **What tested:** after 3 consecutive CLOSED losses, block new entries
  for the next 12 x 15m bars (3 hours) on that symbol.
- **Engine:** C v1.0 (`experiment/main_research_c_v1_0.py`, UNTOUCHED).
- **Dataset:** 6 majors, 2.7Y, 15m bars, full.
- **Isolated variable:** entry-acceptance gate (per-symbol pause window
  after a 3-loss streak). Single lever.
- **Result:** 105 triggers, 0 blocked entries. All metrics identical to
  baseline (2302T / +2875.00R / MaxDD 8.00R / 2.73%). Per-trigger
  next-entry distance: min=26 bars, median=135, max=653; **zero** triggers
  had their next entry in (L_exit, L_exit+12]. The 12-bar (3-hour) pause
  window never coincides with a real entry signal because entry signals
  are sparse (~60+ bars between entries on the 6 majors).
- **Decision:** **REJECT — non-binding / no strategic impact.**
  Mechanically verified: 5/5 synthetic invariants PASS; function
  reproduces saved summary exactly per-symbol. Replay mechanism is
  correct; the lever is simply non-effective on this data/engine.
- **Next test:** Exp C (DD-based risk scaling).
- **File:** `experiment/exp_maxdd_B_streak_breaker.py`.
- **Outputs:** `results/research/expB_streak_breaker_summary.json`,
  `results/research/expB_streak_breaker_trades.json`.
- **Audit:** `experiment/audit_expB_replay.py` (5/5 synthetic PASS;
  per-symbol function output matches saved summary; 105/0 verified).
- **Replay causality note:** event stream sorts EXIT-before-ENTRY at the
  same bar. For `entry_bar == exit_bar` (hold_bars=0) trades, the EXIT is
  processed before that trade's ENTRY, so `t.trade_id in accepted` is
  False and the EXIT is excluded from the streak. Conscious causality
  rule, not a bug. Function's accepted-aware walk gives 105 triggers
  (authoritative); pure-EXIT walk gives 42.

### Exp C — DD-Based Risk Scaling (C v1.0)

- **What tested:** scale per-trade risk by current realized portfolio DD
  (post-hoc overlay). Thresholds: DD>2R x0.50, DD>4R x0.25, DD>6R pause.
- **Engine:** C v1.0 (`experiment/main_research_c_v1_0.py`, UNTOUCHED).
- **Dataset:** 6 majors, 2.7Y, 15m bars, full.
- **Isolated variable:** post-hoc per-trade pnl_r multiplier based on
  realized portfolio drawdown at trade entry. NO lookahead (DD from
  realized exits only). Single lever.
- **Result:** 0 paused. 2302T / +2827.55R / AvgR +1.2283 / PF 5.13 /
  MaxDD(R) 8.00 / **MaxDD(%) 1.85**. MaxDD(R) unchanged because the 8.00R
  drawdown is a single-trade loss step intrinsic to the engine; scaling
  the next trade's risk cannot shrink a pre-existing peak-to-trough.
  MaxDD% improved 2.73 → 1.85 (−32%) because the same 8.00R step is a
  smaller fraction of a higher equity peak after scaling. TotalR −1.65%
  (cost of the DD-scale leg). PF ticks up 5.08 → 5.13.
- **Decision:** **MaxDD% lever — PENDING PROMOTION to C v1.1.**
  Not auto-accepted: promotion requires a separate decision after
  standalone validation. MaxDD(R) is NOT reduced; only MaxDD(%) moves.
- **Next test:** Exp D (Open Exposure / Total-Risk Cap).
- **File:** `experiment/exp_maxdd_C_dd_risk_scaling.py`.
- **Outputs:** `results/research/expC_dd_risk_scaling_summary.json`,
  `results/research/expC_dd_risk_scaling_trades.json`.

### Exp D — Open Exposure / Total-Risk Cap (C v1.0) (REJECT — non-impact)
- **What tested:** cap the total open R exposure of accepted trades at
  3R. Each accepted trade contributes its initial R risk (1R in the C2
  engine, since pnl_r is normalised to the initial SL). When a new entry
  would push the open-exposure sum above 3R, the entry is BLOCKED.
- **Engine:** C v1.0 (`experiment/main_research_c_v1_0.py`, UNTOUCHED).
- **Dataset:** 6 majors, 2.7Y, 15m bars, full.
- **Isolated variable:** post-hoc portfolio overlay with global open-R
  cap = 3R. NO lookahead. Single lever.
- **Result (full 2.7Y 6-major):**
  | Metric | Baseline | D (3R cap) |
  |---|---|---|
  | Trades | 2302 | 2300 |
  | Blocked | 0 | 2 |
  | WR% | 69.37 | 69.35 |
  | TotalR | +2875.00 | +2873.59 |
  | AvgR | +1.2489 | +1.2494 |
  | PF | 5.08 | 5.08 |
  | MaxDD(R) | 8.00 | 8.00 |
  | MaxDD(%) | 2.73 | 2.73 |
  | Max open count | — | 3 |
  | Max open R | — | 3.00R |
  | Cap ever reached | — | YES (but only 2 blocks) |
  | MaxDD-episode open exposure at trough | — | 0R (cap NOT binding at MaxDD) |
- **Blocked trade distribution:** 1 GBPUSD bearish (would-be WIN +1.0R),
  1 EURUSD bullish (would-be WIN +0.41R). Both would-be WINNERS blocked
  (cap cost = −1.41R TotalR). Zero would-be losses blocked.
- **Mechanically equivalent to Experiment A** under the C2 engine's 1R-
  per-trade normalisation (initial risk = 1R for every trade). The
  difference is the framing (sum of R risks vs concurrent count). Filed
  as a separate experiment because the user spec frames the lever as
  "total R exposure" and the audit + MaxDD-episode binding analysis are
  distinct deliverables.
- **Cross-symbol same-bar determinism:** the overlay sorts by
  `(entry_timestamp, trade_id)` so the cap evaluation is reproducible
  across runs (a tie-breaker is required because the per-symbol data
  loader uses a thread pool and the aggregation order is otherwise non-
  deterministic). Without the tie-breaker, run-to-run results varied
  (0, 1, or 2 blocks) due to the same-bar cross-symbol ordering.
- **DECISION: REJECT — non-impact.** The cap (3R) was reached (max
  concurrent = 3) and 2 trades were blocked, but BOTH blocked trades
  were winners (the cap selectively removed wins). MaxDD(R) unchanged at
  8.00R; MaxDD(%) unchanged at 2.73%. TotalR cost −1.41R (−0.05%). The
  cap was NOT binding during the MaxDD episode (open exposure at the
  trough entry was 0R). The 8.00R MaxDD is a single-trade step
  intrinsic to the engine; an open-exposure cap on entry cannot reduce
  it. NOT a useful MaxDD lever.
- **Next test:** Exp E (Time-of-Day Quality Filter).
- **File:** `experiment/exp_maxdd_D_open_exposure_cap.py`.
- **Outputs:** `results/research/expD_open_exposure_cap_summary.json`,
  `expD_open_exposure_cap_trades.json`,
  `expD_open_exposure_cap_blocked.json`.
### Exp E — Time-of-Day Quality Filter (C v1.0) (REJECT — non-impact)

- **What tested:** post-hoc entry-time filter allowing only London
  (10:00–13:00) and NY AM (15:30–18:00) server-time windows. All
  entries outside these windows are BLOCKED (trade excluded from
  equity curve entirely). NO lookahead — only `entry_timestamp` used.
- **Engine:** C v1.0 (`experiment/main_research_c_v1_0.py`, UNTOUCHED).
- **Dataset:** 6 majors, 2.7Y, 15m bars, full.
- **Isolated variable:** entry-acceptance time-of-day gate (post-hoc
  overlay). Two windows tested simultaneously as a single lever.
- **Synthetic tests:** 15/15 PASS (boundary + full datetime shapes).
- **Result (full 2.7Y 6-major):**

  | Metric | Baseline | E (ToD) | Delta |
  |---|---|---|---|
  | Trades | 2302 | 745 | −1557 |
  | Blocked | 0 | 1557 | +1557 |
  | Blocked % | — | 67.64% | — |
  | WR% | 69.37 | 70.60 | +1.23 |
  | TotalR | +2875.00 | +791.12 | −2083.88 |
  | AvgR | +1.2489 | +1.0619 | −0.1870 |
  | PF | 5.08 | 4.61 | −0.47 |
  | MaxDD(R) | 8.00 | 4.77 | −3.23 |
  | MaxDD(%) | 2.73 | 3.03 | +0.30 |

- **Window attribution (all baseline trades):**

  | Window | Trades | WR% | TotalR | AvgR | PF |
  |---|---|---|---|---|---|
  | London 10:00–13:00 | 441 | 69.84% | +413.65 | 0.9380 | 4.11 |
  | NY AM 15:30–18:00 | 304 | 71.71% | +377.47 | 1.2417 | 5.39 |
  | Outside (blocked) | 1557 | 68.79% | +2083.88 | 1.3384 | 5.29 |

- **MaxDD episode analysis:** 9 trades in the episode (8.00R MaxDD).
  7/9 outside windows (would be blocked, −7.00R); 2/9 ny_am (+1.04R
  survived). The filter would have reduced the episode to +1.04R but
  at the cost of removing 67.6% of ALL trades and −2084R TotalR.

- **Root cause of failure:** the "outside" window carries the highest
  AvgR (1.3384) and PF (5.29) — better than both accepted windows
  combined. The filter selectively removes the BEST-performing session
  hours. London has the weakest AvgR (0.9380); NY AM is mid-range.
  Blocking outside entries destroys more value than it saves.

- **DECISION: REJECT — non-impact.** MaxDD(R) reduced 8.00→4.77 but
  MaxDD% WORSENED 2.73→3.03 (filtered equity curve peaks lower).
  TotalR catastrophic loss −2084R (−72.5%). PF degraded 5.08→4.61.
  The filter is far too aggressive and removes the strategy's highest-
  quality session hours. NOT a useful MaxDD lever.

- **Next test:** Phase 1 complete. All single-variable overlays (A–E)
  resolved. Only C (DD Risk Scaling) is a KEEP candidate. Next:
  combination tests or Phase 2 (D v1.0 line).
- **File:** `experiment/exp_maxdd_E_time_of_day.py`.
- **Outputs:** `results/research/expE_time_of_day_summary.json`,
  `results/research/expE_time_of_day_trades.json`.

### Exp F — D v1.0 + DD Risk Scaling (D v1.0) (REJECT — non-impact)

- **What tested:** post-hoc DD-based risk scaling overlay (identical
  thresholds/multipliers to Experiment C) applied to the D v1.0 (PURE D EQ)
  engine trade stream.
- **Engine:** D v1.0 (`experiment/main_research_d_v1_0.py`, UNTOUCHED).
  Canonical compute_stats from C engine (shared).
- **Dataset:** 6 majors, 2.7Y, 15m bars, full.
- **Isolated variable:** post-hoc per-trade pnl_r multiplier based on
  realized portfolio drawdown at trade entry. NO lookahead. Single lever.
- **Synthetic tests:** 9/9 PASS (3 scenarios: 5 losses, 8 losses, mixed).
- **Result (full 2.7Y 6-major):**

  | Metric | Baseline | F (Scaled) | Delta |
  |---|---|---|---|
  | Trades | 2849 | 2843 | −6 |
  | Blocked (paused) | 0 | 6 | +6 |
  | WR% | 66.09 | 66.09 | −0.00 |
  | TotalR | +2946.23 | +2711.52 | −234.70 |
  | AvgR | 1.0341 | 0.9538 | −0.0803 |
  | PF | 4.05 | 4.12 | +0.07 |
  | MaxDD(R) | 7.36 | 7.36 | +0.00 |
  | MaxDD(%) | 2.76 | 2.86 | +0.10 |

- **Risk scaling event distribution:**

  | Multiplier | Count |
  |---|---|
  | x1.00 (DD≤2R) | 2316 |
  | x0.50 (DD>2R) | 486 |
  | x0.25 (DD>4R) | 41 |
  | PAUSE (DD>6R) | 6 |

- **Root cause of failure:** Same as C engine. The 7.36R MaxDD on D is
  dominated by a single-trade loss step. Scaling subsequent trades' risk
  cannot retroactively reduce a peak-to-trough that already occurred.
  533 trades were scaled (486 at x0.50, 41 at x0.25), 6 paused — but
  the MaxDD episode's core loss step is intrinsic to the engine. MaxDD%
  WORSENED (2.76→2.86) because the scaled equity curve peaks lower.
  TotalR cost −234.70R (−7.97%) for zero MaxDD improvement.

- **DECISION: REJECT — non-impact.** Scaling triggered on 533/2849 trades
  (18.7%), 6 paused, but MaxDD(R) unchanged at 7.36R. MaxDD% worsened
  2.76→2.86. TotalR cost −234.70R (−7.97%). PF ticks up 4.05→4.12.
  Same pattern as C engine: the MaxDD is a structural single-trade step
  that post-hoc risk scaling cannot address. NOT a useful MaxDD lever
  on D v1.0.

- **Next test:** Continue Phase 2 (D v1.0 line) with remaining overlays
  (A, B, D, E) or move to combination tests.
- **File:** `experiment/exp_maxdd_F_d_risk_scaling.py`.
- **Outputs:** `results/research/expF_d_risk_scaling_summary.json`,
  `results/research/expF_d_risk_scaling_trades.json`.

---

## HISTORICAL CONTEXT (preserved from earlier phases)

The sections below are kept for project history. They are not part of the
MaxDD research line but document earlier completed work (bootstrap, data
acquisition, LIVE↔BACKTEST parity, known-good benchmark freeze, etc.).

### C2 Baseline (full 2.7Y, 6-major) — AUTHORITATIVE

| Metric | Value |
|---|---|
| Trades | 2302 |
| WR | 69.37% |
| TotalR | +2875.00R |
| AvgR | +1.2489 |
| PF | 5.08 |
| MaxDD | 8.00R |
| MaxDD% | 2.73% |

### KNOWN-GOOD FROZEN BENCHMARK — PURE D (2026-08-26)

- Benchmark ID: `PURE_D_FVG_ORIGIN_EQ`
- Artifact: `results/benchmark/PURE_D_FVG_ORIGIN_EQ_benchmark.json`
- Canonical engine: `experiment/main_research_d_v1_0.py` (UNCHANGED)
- Promotion rule: a new variant must beat this in head-to-head; if
  superseded it is archived, not deleted.

| Metric | Value |
|---|---|
| Trades | 2847 |
| WR | 66.1% |
| TotalR | +2949.05R |
| AvgR | +1.0358 |
| PF | 4.05 |
| MaxDD | 7.36R |
| MaxDD% | 2.76% |

### MaxDD CHRONOLOGY FIX (2026-08-25) — COMPLETE

- Old `compute_stats()` sorted by `exit_bar_index` (symbol-local, not
  chronological across the portfolio). Fixed: sort by `exit_timestamp`.
- `BenchmarkTrade` got `exit_timestamp: float`; four close points now
  populate it. `compute_stats()` returns `max_dd_pct`. No strategy change.

### MaxDD STARTING_BALANCE FIX (2026-08-26) — COMPLETE

- MaxDD% was 100% because `equity` initialized at 0. Fixed: start at
  100R (`STARTING_BALANCE_R`). Affected: `main_research_c_v1_0.py`,
  `exp5f_frozen_vs_dynamic_eq.py`, `gemini_benchmark.py`. Commit 0561b22.

### DOCUMENTATION / NAMING — EQ C vs EQ D (2026-08-26) — COMPLETE

- Renames: `gemini_benchmark_eq.py` → `main_research_c_v1_0.py` (C = C2 EQ);
  `research_variant_D_fvg_origin_eq_pure.py` → `main_research_d_v1_0.py`
  (D = PURE D EQ). Created `docs/EQ_C_vs_EQ_D.md`. No logic changes.

### LIVE ↔ BACKTEST PARITY AUDIT (2026-08-22) — PASS

- TIME / DATA / EVENT / TRADE parity all PASS. Reference: dataset = naive
  MT5 server time; ICMarketsSC-Demo live server verified against dataset
  (account 53012914); period maps to UTC+3.
- Permanent rule: LIVE MT5 is the ground truth; backtest must reproduce it
  deterministically, not approximate it.

### INTERNAL SWEEP RESEARCH (2026-08-22) — CLOSED, BOTH VARIANTS REJECTED

- v1 (loose): 1262/1262 replayed, pass rate 97.62% (non-binding), p=0.075,
  H1/H2 sign flip → REJECT.
- v2 (MSS-anchored): chain ordering INVERTED vs hypothesis, p=0.75,
  filter would remove ~38% total R → REJECT.
- Permanent conclusion: minor HH/LL internal-sweep + MSS chain carries
  no incremental information in the NEXUS 15m entry structure. Line closed.

### KNOWN-GOOD BENCHMARK FREEZE (2026-08-22) — COMPLETE

- Direction-dispatch bug fixed (bullish/bearish normalized to long/short at
  execution boundary via `_norm_side()` in `trailing_adapter.py`).
  17/17 validation PASS. `src/` not modified.
- Frozen benchmark (98 symbols, 15m): 1471 → 1262 trades, WR 51.1% → 58.2%,
  +577.02R → +722.72R, PF 1.80 → 2.37, DD 27.17R → 12.73R (~53% reduction).
- Reference: `docs/KNOWN_GOOD_BENCHMARK.md`. **CRITICAL:** pre-fix
  execution numbers are INVALID as execution-behavior benchmarks.

### DD UNIVERSE AUDIT (2026-08-22) — COMPLETE (read-only)

- No symbol meets >=500-trade threshold. Max trades/symbol = 25, median ~16.
  Primary universe (MaxDD>=1.0% AND >=500 trades): 0 symbols.
- Audit: `scripts/audit_dd_universe.py` (read-only).

### Phase 0–4 (Bootstrap → Sweep Lifecycle) — COMPLETE

- Phase 0: Bootstrap (7/7 architecture validation, .env fix).
- Phase 1: MT5 real data probe.
- Phase 2A: Strategy spec (`docs/SNIPER_FOREX_STRATEGY_SPEC.md`, 377 lines).
- Phase 2B.2: Forex backtest infra (`src/backtest/`, 22 tests passing).
- Data: 98 symbols from MT5, 3,085,613 M1 bars, 2026-07-21 → 2026-08-20.
- Phase 3: Real-data strategy baseline (1845T, 59.3% WR, +1221R).
- Phase 3.2: Liquidity source forensics (CBDR vs SESSION_HL vs SWING_HL).
  SWING_HL highest WR/PF; CBDR NOT proven uniquely superior; 1-month data
  insufficient.
- Phase 4: Sweep lifecycle forensics — 1 sweep = 1 trade (100%).

### IC MARKET RAW → SERVER TIME CONVERSION (2026-08-23) — COMPLETE

- User-provided 6 majors in `data/icmarket_raw/` (UTC+0, cTrader).
  Converted to server time (UTC+2/3 DST-aware) in `data/icmarket_server/`.
  99.997% time-aligned vs MT5 feather pipeline; ~31% exact OHLC match
  (rest = feed/precision differences, expected).
- Scripts: `data/icmarket_raw/audit_icmarket_raw.py`,
  `data/icmarket_raw/cross_check_tz.py`,
  `data/icmarket_raw/convert_icmarket_utc_to_server.py`.

### RAW 1m DATA SOURCE INVESTIGATION (2026-08-22) — CANCELLED

- Dukascopy: fully blocked (network). HistData: bot-block. Yahoo: 7-day
  1m cap. MT5 demo: ~47-day cap. Twelve Data: chosen then cancelled.
  FXCM candledata: DNS dead. Resolution: user-provided ICMarkets raw
  (`data/icmarket_raw/`).
