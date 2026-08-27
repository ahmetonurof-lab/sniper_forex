# Active Context — Research Control Panel

> Single source of truth for the MaxDD research line.
> Last updated: 2026-08-27.
> Canonical engines (`main_research_c_v1_0.py`, `main_research_d_v1_0.py`) are NEVER
> edited for experiments. New behaviour lives in `experiment/exp_maxdd_*.py`
> overlays until it is promoted to a new engine version.

---

## PRODUCTION IMPLEMENTATION (MT5 DEMO) — STATUS

> Companion to `docs/MT5_IMPLEMENTATION_ROADMAP.md` (master task list).
> This section reflects production-transition state only. Research state below.

- **Master roadmap:** `docs/MT5_IMPLEMENTATION_ROADMAP.md` (persistent cross-agent source of truth).
- **Current Phase:** PHASE 4 — RISK + POSITION SIZING.
- **Last Completed Phase:** PHASE 3 — STRATEGY RUNTIME (2026-08-27, commit 18ba794).
- **Frozen engines:** `main_research_c_v1_0.py` + `main_research_d_v1_0.py` — git diff CLEAN (verified).
- **DD Risk Scaling:** OUT OF SCOPE for production (research: C candidate / D REJECT). Optional future module.
- **C/D engine selection:** NOT locked. Production runtime stays separate from research.

### PHASE 1 — MT5 FOUNDATION (COMPLETE 2026-08-27)
- **Changed:** `src/trading/mt5_connection.py`, `src/data/mt5_data.py` (hardened).
- **New:** `tests/test_mt5_connection_hardening.py` (10 synthetic unit tests).
- **Added to `MT5Connection`:** path-based initialize, `last_error` capture,
  `is_connected()`, `reconnect()`, `ensure_connected()`, robust error handling.
- **Added to `MT5DataLayer`:** `last_error` capture, robust error handling.
- **Tests:** architecture 7/7 PASS; hardening unit tests 10/10 PASS; full suite 100/100 PASS.
- **Frozen engines:** unchanged (git diff CLEAN).
- **Next:** PHASE 2 — M1 feed + 15m candle aggregation (parity with `resample_15m()`).

### PHASE 2 — MARKET DATA / 15M CANDLE FEED (COMPLETE 2026-08-27)
- **New:** `src/live/` package — `candle_feed.py`, `clock.py`.
- **New:** `tests/test_live_candle_feed.py` (16 synthetic unit tests).
- **`M1CandleFeed`:** `fetch_m1` (server-time→UTC), `find_duplicates`,
  `find_missing`, `is_closed_m1` (forming vs closed), `warmup`, `update`.
- **`resample_15m()`:** re-implemented canonical boundary (epoch//15min slot,
  first-bar label, drop <3-bar buckets) — parity with frozen engine.
- **`clock.py`:** server UTC offset (summer +3 / winter +2), session window
  19:00→01:00. Server→UTC uses CURRENT offset (one offset per live session).
- **Tests:** 16/16 PASS; full suite 116/116 PASS.
- **Frozen engines:** unchanged (git diff CLEAN).
- **Next:** PHASE 3 — strategy runtime port.

### PHASE 3 — STRATEGY RUNTIME (COMPLETE 2026-08-27)
- **New:** `src/live/strategy_runtime.py`, `src/live/state.py`.
- **New:** `tests/test_live_strategy_runtime.py` (4 replay parity tests).
- **`StrategyRuntime`:** ports `run_test_a` entry/SL/TP core. Reuses
  `SessionManager`, `apply_trailing`/`check_exit`/`_norm_side`, nexus
  `detect_fvgs`. Pending-entry model: touch on closed bar → pending (SL/TP at
  bar i) → fill at next bar open → active trade + Signal.
- **`StateStore`:** atomic JSON persistence (`state/<SYMBOL>.json`) for restart
  recovery; `save`/`load`/`exists`/`clear`.
- **Parity:** EURUSD + GBPUSD replay match canonical signal/SL/TP.
- **Two parity gotchas fixed:**
  1. Entry bar must be processed immediately (apply_trailing + check_exit on
     the fill bar) — otherwise a trade that trails+exits on its own entry bar
     is missed.
  2. Sweep must NOT be reset at pending/touch time. Reset only after a trade is
     created. MIN_RISK_DIST failure must fall through to re-scan FVGs with the
     same sweep (canonical `continue`s).
- **Tests:** 4/4 PASS; full suite 120/120 PASS.
- **Frozen engines:** unchanged (git diff CLEAN).
- **Next:** PHASE 4 — risk engine + lot sizing (`src/live/risk.py`,
  `src/live/sizing.py`). RISK_PER_TRADE=0.003 reference.

---

## CURRENT STATE

### Main Research Engines (frozen baselines)

| Engine | File | Version | Status |
|---|---|---|---|
| C | `experiment/main_research_c_v1_0.py` | **v1.0** — C2 EQ | FROZEN baseline |
| D | `experiment/main_research_d_v1_0.py` | **v1.0** — PURE D EQ | FROZEN baseline |

> Old versions are never deleted. A new version (v1.x) is only created
> when a verified change is promoted from an experiment overlay to the
> research engine.

### Confirmed C (C2) Results — 6 majors, 2.7Y, 15m

| Variant | Trades | WR% | TotalR | AvgR | PF | MaxDD(R) | MaxDD(%) |
|---|---:|---:|---:|---:|---:|---:|---:|
| C1 Displacement (tested) | — | — | weaker than C2 | — | — | — | — |
| **C2 baseline (C v1.0)** | 2302 | 69.37 | +2875.00 | +1.2489 | 5.08 | 8.00 | 2.73 |
| C2 + DD Risk Scaling (overlay) | 2302 | 69.37 | +2827.55 | +1.2283 | 5.13 | 8.00 | **1.85** |

- DD Risk Scaling is a **post-hoc overlay** (`experiment/exp_maxdd_C_dd_risk_scaling.py`).
  It has NOT been promoted to **C v1.1** — promotion requires a separate
  decision after standalone validation.
- C2 baseline numbers are the authoritative reference for every C-family
  comparison. `main_research_c_v1_0.py` git diff is empty across all experiments.

### Confirmed D (PURE D) Results — 6 majors, 2.7Y, 15m

| Variant | Trades | WR% | TotalR | AvgR | PF | MaxDD(R) | MaxDD(%) |
|---|---:|---:|---:|---:|---:|---:|---:|
| **D v1.0 baseline** | 2847 | 66.1 | +2949.05 | +1.0358 | 4.05 | 7.36 | 2.76 |

- Artifact: `results/benchmark/PURE_D_FVG_ORIGIN_EQ_benchmark.json`
- KNOWN-GOOD FROZEN BENCHMARK. Promotion rule: a new variant must beat
  this in a head-to-head comparison to supersede it.

### Rejected Experiments (C v1.0 line)

| ID | Experiment | Decision | Reason |
|---|---|---|---|
| A | Concurrent Exposure Cap = 3 | **REJECT** | non-binding (cap never reached); 0 blocked; no PnL/MaxDD change |
| B | 3-Loss / 12-bar Circuit Breaker | **REJECT** | non-binding (mechanism verified; 105 triggers but 0 blocked — pause window never overlaps a real entry); 0 PnL/MaxDD change |

Both: mechanically verified, file = `experiment/exp_maxdd_*.py`. See
`memory-bank/progress.md` for full per-experiment log.

---

## ROADMAP / TODO

### Phase 1 — C v1.0 MaxDD Research (single-variable overlays)

- [x] **A** — Concurrent Exposure Cap (REJECT / non-binding)
- [x] **B** — 3-Loss / 12-bar Circuit Breaker (REJECT / non-binding)
- [x] **C** — DD-Based Risk Scaling (MaxDD% 2.73 → 1.85; awaiting promotion decision)
- [x] **D** — Open Exposure / Total-Risk Cap (REJECT / cap reached but only 2 blocked, no MaxDD impact; mechanically ≡ A under 1R/trade)
- [x] **E** — Time-of-Day Quality Filter (REJECT / non-impact — 67.6% blocked, TotalR −72.5%, MaxDD% worsened)
- [ ] **Combination tests** — only after all single-variable experiments resolve

### Phase 2 — D v1.0 MaxDD Research (mirror of Phase 1)

- [x] **C** — DD-Based Risk Scaling (REJECT / non-impact — 6 paused, MaxDD unchanged 7.36R, MaxDD% worsened 2.76→2.86, TotalR −234.70R)
- [ ] A — Concurrent Exposure Cap
- [ ] B — 3-Loss / 12-bar Circuit Breaker
- [ ] D — Open Exposure / Total-Risk Cap
- [ ] E — Time-of-Day Quality Filter

### Phase 3 — Champion Selection

- [ ] Score C and D variants on a single objective score (MaxDD-first, then
      PF / AvgR / WR / TotalR preservation)
- [ ] Decide champion
- [ ] OOS validation if needed
- [ ] Promote winning engine to new version (C v1.x or D v1.x) — old
      version preserved, new version created

---

## NEXT ACTION

**NEXT = Phase 1 — all single-variable overlays complete (A/B/C/D/E).**

Phase 1 Summary:
| ID | Decision | MaxDD(R) | MaxDD(%) | TotalR |
|---|---|---|---|---|
| A | REJECT (non-binding) | 8.00 → 8.00 | 2.73 → 2.73 | unchanged |
| B | REJECT (non-binding) | 8.00 → 8.00 | 2.73 → 2.73 | unchanged |
| C | KEEP candidate | 8.00 → 8.00 | 2.73 → 1.85 | −47R (−1.65%) |
| D | REJECT (non-impact) | 8.00 → 8.00 | 2.73 → 2.73 | −1.41R |
| E | REJECT (non-impact) | 8.00 → 4.77 | 2.73 → 3.03 | −2084R (−72.5%) |

Only **C (DD Risk Scaling)** is a candidate for promotion. All others are REJECT.

**NEXT ACTION:** Continue Phase 2 D v1.0 mirror experiments (A, B, D, E) or
combination tests. D + DD Risk Scaling (Exp F) confirmed non-impact — scaling
triggered on 533 trades but MaxDD unchanged.

Awaiting user direction on next step.

---

## EXPERIMENT LOG (this research line)

| ID | Status | Decision | Key result | File |
|---|---|---|---|---|
| A | done | REJECT (non-binding) | 0 blocked; baseline unchanged | `experiment/exp_maxdd_A_concurrent_cap.py` |
| B | done | REJECT (non-binding) | 105 triggers, 0 blocked; mechanically verified | `experiment/exp_maxdd_B_streak_breaker.py` |
| C | done | MaxDD% 1.85 (pending promotion) | MaxDD% 2.73→1.85, TotalR −1.65% | `experiment/exp_maxdd_C_dd_risk_scaling.py` |
| D | done | REJECT (non-impact) | cap 3R reached (max_open=3) but only 2 blocked wins; MaxDD 8.00R unchanged | `experiment/exp_maxdd_D_open_exposure_cap.py` |
| E | done | REJECT (non-impact) | 1557 blocked (67.6%), MaxDD(R) 8.00→4.77 but TotalR −2084 (−72.5%), MaxDD% 2.73→3.03 worse, PF 5.08→4.61 | `experiment/exp_maxdd_E_time_of_day.py` |
| F | done | REJECT (non-impact) | D v1.0 + DD Risk Scaling: 6 paused, MaxDD 7.36R unchanged, MaxDD% 2.76→2.86 worse, TotalR −234.70R (−7.97%) | `experiment/exp_maxdd_F_d_risk_scaling.py` |

Full per-experiment detail (what tested, engine, dataset, isolated
variable, result, decision, next test) lives in `memory-bank/progress.md`.

---

## FILE MAP (active research files)

```text
# Frozen baselines (NEVER edited for experiments)
experiment/main_research_c_v1_0.py        = C v1.0  / C2 EQ baseline
experiment/main_research_d_v1_0.py        = D v1.0  / PURE D EQ baseline

# C v1.0 MaxDD experiment overlays (Phase 1)
experiment/exp_maxdd_A_concurrent_cap.py
experiment/exp_maxdd_B_streak_breaker.py
experiment/exp_maxdd_C_dd_risk_scaling.py
experiment/exp_maxdd_D_open_exposure_cap.py
experiment/exp_maxdd_E_time_of_day.py

# D v1.0 MaxDD experiment overlays (Phase 2)
experiment/exp_maxdd_F_d_risk_scaling.py

# B replay audit
experiment/audit_expB_replay.py      = Experiment B mechanism audit
```

New experiment files are appended to the overlay list as they are created.
Baseline files are never modified by experiments.

---

## WORKING RULE (enforced every turn)

When an experiment is finished, in the SAME turn, update memory-bank:

1. `memory-bank/activeContext.md` — mark todo `[ ]` → `[x]`, append result
   row to the experiment log table, set NEXT ACTION to the next pending
   item, update FILE MAP if a new file was created.
2. `memory-bank/progress.md` — append a per-experiment entry with the
   required fields:
   - what was tested
   - which engine (C v1.0 / D v1.0)
   - which dataset (6 majors, 2.7Y, 15m, full)
   - isolated variable (one)
   - result (numbers)
   - decision (KEEP / REJECT / INCONCLUSIVE / pending)
   - next test

Canonical engines are NEVER edited for experiments. Verified promotions
create a new version (C v1.x, D v1.x); the old version is preserved.

---

## Replay causality note (carry-over)

The Exp B replay sorts EXIT-before-ENTRY at the same bar. For trades with
`entry_bar == exit_bar` (hold_bars=0, same-bar fill+exit), the EXIT is
processed before that trade's ENTRY, so `if t.trade_id in accepted` is
False and the EXIT is excluded from the loss streak. This is a **conscious
causality rule** (a trade's result cannot be used to make decisions on the
same bar it opened), not a bug. A pure-EXIT walk on the same data gives
42 triggers; the function's accepted-aware walk gives 105 (authoritative).
This note applies to any future replay that reuses the same event-stream
pattern.
