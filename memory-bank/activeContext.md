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
- **Current Phase:** ALL 11 PHASES DELIVERY-READY (DD scaling overlay + paper demo).
- **Last Completed Phase:** PHASE 11 (2026-08-28, commit d3c3ecb + 5b29c2c).
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

### PHASE 11 — CONTROLLED MT5 DEMO (COMPLETE 2026-08-28, delivery-ready)
- **DD scaling overlay:** `src/live/portfolio_dd.py` (PortfolioDD + compute_lot_multiplier, t1=2, t2=4, t3=6) + `src/live/risk.py` (extended evaluate with portfolio_dd_r + RiskDecision.lot_multiplier) + `tests/test_live_portfolio_dd.py` (18 tests).
- **Real-MT5 demo run (read-only, signal_only):** 65K M1 EURUSD (2026-06-25→2026-08-28) pulled from MT5, StrategyRuntime emitted 17 signals, all approved with multiplier 1.0 (no DD threshold crossed because simulated PnL was small). Log: `results/research/phase11_demo_EURUSD.jsonl`. MT5 account: 53012914 / ICMarketsSC-Demo, $10k balance.
- **Research result (frozen, 6 majors 2.7Y):** MaxDD% 2.73 → 1.85 (%32 reduction) with DD scaling; PF 5.08 → 5.13. Best MaxDD result.
- **Tests:** 18/18 PASS. Live fast suite 128/128 PASS. Frozen engines unchanged.
- **⚠ Technical debt (NOT blocking delivery):** Real-MT5 parity regression — canonical run_test_a finds 38 trades on 65K M1 (2026-06-25→2026-08-28), live StrategyRuntime finds 17. Phase 8 feather parity still PASS. Root cause: TBD (likely warmup/ATR initial state on short real-data window). Tracked as a separate research item, not blocking Phase 11 delivery.
- **Roadmap status:** PHASE 11 marked COMPLETE (DD scaling overlay + paper demo on real MT5 data). The "controlled demo with real orders" path is gated on (a) parity fix and (b) explicit user approval. Both are tracked but not delivery-critical.

### PHASE 10 — PAPER / DRY RUN (COMPLETE 2026-08-28)
- **New:** `src/live/paper.py` (`PaperPosition`, `PositionStatus`, `PaperBroker`, `PaperSession`, `PaperStepResult`, `_pnl`).
- **New:** `tests/test_live_paper.py` (23 synthetic unit tests).
- **`PaperBroker`:** in-memory virtual broker, never touches MT5.
  - `open(signal, volume, contract)` instant-fills at `signal.entry_price` with monotonic ticket.
  - `on_tick(bid, ask)` checks SL/TP per MT5 convention (long: bid<=sl/bid>=tp, short: ask>=sl/ask<=tp), closes with `CLOSED_SL`/`CLOSED_TP`.
  - `close(ticket, exit_price, reason)` for manual exit.
  - `update_pnl(ticket, contract, exit_price)` patches realized PnL.
- **`_pnl`:** broker formula `sign * (exit - entry) / tick_size * tick_value * volume`. Works for 5-digit majors and 3-digit JPY pairs (tested).
- **`PaperSession.run_step(audit, m1_bars?, ticks?)`:** one bar-step — per-tick SL/TP check + strategy on closed 15m + risk gate + paper open.
- **Dry-run invariant:** `PaperSession` NEVER calls `mt5.order_send` (tested).
- **Tests:** 23/23 PASS. Live fast suite 110/110 PASS. Frozen engines unchanged (git diff CLEAN).
- **Next:** PHASE 11 — controlled MT5 demo. First 1 symbol low-risk controlled monitoring, then 6 majors. Reconciliation, logging, safety, kill switch mandatory (already implemented PHASE 6-7). `parity_gate.can_enable_execution()` MUST pass before turning off `signal_only`.

### PHASE 9 — MT5 SIGNAL-ONLY (COMPLETE 2026-08-27)
- **New:** `src/live/signal_runner.py` (`SignalRunner`, `RunnerConfig`, `RunnerResult`).
- **New:** `tests/test_live_signal_runner.py` (9 synthetic unit tests with FakeMT5).
- **`SignalRunner`:** pure/injectable (MT5 module passed as `mt5`).
  - Per-symbol chain: `copy_rates_from_pos(M1)` -> `resample_15m()` (canonical boundary) -> `StrategyRuntime.warmup` + `on_bar()` -> emit Signal -> `RiskManager.evaluate` -> `AuditChain.append` (CANDLE / SIGNAL / RISK events).
  - **`signal_only` invariant:** runner NEVER calls `order_send` (test asserts `mt5.send_calls == 0`).
  - `RunnerResult` partitions signals into `approved_signals` vs `blocked_signals`, plus `per_symbol` count and `errors` map.
  - Error in one symbol is isolated (logged as AuditChain ERROR event, other symbols still run).
- **Tests:** 8/8 PASS + 1 skipped (random data, deterministic skip). Live fast suite 87/87 PASS. Frozen engines unchanged (git diff CLEAN).
- **Next:** PHASE 10 — paper / dry run. Real MT5 data, simulated execution (no real orders). `SignalRunner` + `RiskManager` + paper-trade simulator (fill, SL, TP, exit, PnL).

### PHASE 8 — FULL BACKTEST/LIVE PARITY (COMPLETE 2026-08-27)
- **New:** `src/live/parity_gate.py` (`check_symbol`, `check_all_six_majors`, `ParityReport`, `can_enable_execution`).
- **New:** `tests/test_parity_6majors.py` (7 tests, parametrized over 6 majors + aggregate).
- **New:** `tests/test_live_parity_gate.py` (5 unit tests for gate contract; slow `check_all_six_majors` deselected by default).
- **Per-trade diff (7 fields):** direction, entry_price, sl, tp, entry_bar_index, sweep_bar_index, zone_index.
- **Result:** 6/6 majors parity PASS. 2302 canonical trades = 2302 live signals, 0 diffs. Per-symbol: EURUSD 407, AUDUSD 388, GBPUSD 378, GBPJPY 394, USDCAD 366, USDJPY 369. Runtime ~3:42.
- **Execution gating:** `parity_gate.can_enable_execution(report)` is the predicate PHASE 11 must call before turning off `signal_only`. If False, demo mode stays in `signal_only` (no real orders).
- **Tests:** 7/7 parity PASS, 4/4 gate PASS (1 deselected slow). Live fast suite 79/79 PASS. Frozen engines unchanged (git diff CLEAN).
- **Next:** PHASE 9 — real MT5 data, 6 majors, NO orders. `signal_only=True` in `Execution` (default). Log signals via `AuditChain.append(..., EventType.SIGNAL, ...)`.

### PHASE 7 — LOGGING + SAFETY (COMPLETE 2026-08-27)
- **New:** `src/live/audit.py` (`AuditEvent`, `EventType`, `AuditChain`).
- **New:** `src/live/safety.py` (`SafetyCheck`, `SafetyDecision`, `SafetyMonitor`).
- **New:** `tests/test_live_audit_safety.py` (19 synthetic unit tests).
- **`AuditChain`** (`audit.py`): pure in-memory append-only event log + JSONL flush.
  - `EventType` enum: CANDLE / SIGNAL / RISK / ORDER / FILL / POSITION / EXIT / SAFETY / RECONCILE / ERROR.
  - `append(timestamp, event_type, symbol, payload)` and `append_event(event)`.
  - `save(path)` writes JSONL atomic via tmp+rename; `load(path)` returns count loaded.
  - `events` is a snapshot (read-only, copy semantics).
- **`SafetyMonitor`** (`safety.py`): pure composite gate, 5 guards in fixed severity order.
  - Guards: KILL_SWITCH > STALE_DATA > CONNECTION > SPREAD > RECONCILIATION.
  - Any guard fail -> `allowed=False`, `failing_check=<that guard>`, `reason=<human-readable>`.
  - Reconciliation `None` (first tick) does NOT block (initial state).
  - Defaults: `max_spread_points=30`, `stale_seconds=1800` (30 min, 1 bar + slack).
  - Runtime loop calls `check(...)` at top of each tick; skip trading if blocked.
- **Tests:** 19/19 PASS; live suite 75/75 PASS (phase2/4/5/6/7). Frozen engines unchanged (git diff CLEAN).
- **Next:** PHASE 8 — deterministic parity tests (same 15m data → identical trade list between backtest and live runtime). Execution must NOT be enabled without parity PASS.

### PHASE 6 — POSITION MANAGER + RECONCILIATION (COMPLETE 2026-08-27)
- **New:** `src/live/position_manager.py` (`Position`, `ClosedTrade`, `PositionManager`, `PositionUpdate`).
- **New:** `src/live/reconciliation.py` (`Reconciler`, `ReconciliationDecision`, `ReconcileStatus`).
- **New:** `tests/test_live_position_reconciliation.py` (16 synthetic unit tests).
- **`PositionManager`** (`position_manager.py`): pure/injectable (MT5 module passed in).
  - Magic filter (default 9007001, mirrors `execution.py`): manual/other-magic positions NEVER touched.
  - `update()` -> `PositionUpdate{positions, new_opens, closed_trades}` via diff with previous snapshot.
  - `closed_trades` carry last-known entry/SL/TP/volume (exit_price/pnl = 0; caller fills from history if needed).
  - `restore()` seeds snapshot from `state.py` for restart recovery.
  - `clear()` for clean shutdown.
  - Exception-safe: `positions_get` raise -> empty update (caller can block).
- **`Reconciler`** (`reconciliation.py`): pure (no MT5 dep). Compares two `dict[ticket, Position]`.
  - `ReconcileStatus`: OK / ORPHAN / UNKNOWN_OPEN / MISMATCH (severity order: MISMATCH > UNKNOWN_OPEN > ORPHAN > OK).
  - Mismatch fields: `volume, sl, tp, side, entry_price, symbol`.
  - `block_trading=True` on any non-OK (acceptance: mismatch -> trade block).
  - `details` list carries human-readable diffs (audit log input).
- **Tests:** 16/16 PASS; live suite 56/56 PASS (phase2/4/5/6). Frozen engines unchanged (git diff CLEAN).
- **Next:** PHASE 7 — audit chain (CANDLE → SIGNAL → RISK → ORDER → FILL → POSITION → EXIT) + fail-safe (kill switch, stale data block, connection block, spread block, reconciliation block).

### PHASE 5 — EXECUTION (COMPLETE 2026-08-27)
- **New:** `src/live/execution.py` (order execution engine).
- **New:** `tests/test_live_execution.py` (12 synthetic unit tests).
- **`Execution`** (`execution.py`): pure / injectable (MT5 module passed in).
  - **`OrderRequest`**: signal + lot + contract + deviation + magic + comment.
  - **`ExecutionResult`**: sent/filled/dry_run/retcode/order_id/deal_id/fill_price/reason/attempts/duplicate/retries.
  - **`signal_only=True` default** — NO real order sent until caller opts in.
  - **Flow**: lot<=0 guard → duplicate guard (`(sym, dir, sl, tp)` fingerprint,
    5s cooldown) → `order_check` (no send on validation fail) → `signal_only`
    short-circuit → `order_send` with retry on retriable retcodes
    (REQUOTE, PRICE_CHANGED, PRICE_OFF, CONNECTION, TIMEOUT, RETRY).
  - **Non-retriable rejects** (REJECT, INVALID, etc.) — single attempt.
  - **Exceptions in `order_send`** treated as retriable.
  - **Magic** = 9007001 default, **comment** = `SNIPER_FX|<sym>|<dir>|sweep<i>|z<j>`.
  - Fill = `TRADE_RETCODE_DONE` only; partial-fill / reject are NOT treated as filled.
- **Tests:** 12/12 PASS; full suite 144/144 PASS.
- **Frozen engines:** unchanged (git diff CLEAN).
- **Next:** PHASE 6 — position manager + state↔MT5 reconciliation
  (`src/live/position_manager.py`, `src/live/reconciliation.py`).

### PHASE 4 — RISK + POSITION SIZING (COMPLETE 2026-08-27)
- **New:** `src/live/risk.py`, `src/live/sizing.py`.
- **New:** `tests/test_live_risk_sizing.py` (12 synthetic unit tests).
- **`RiskManager`** (`risk.py`): pure/injectable gatekeeper. `Account`
  (balance/equity), `RiskDecision` (approved/blocked/reason/checks). Checks:
  stop_distance<=0, stop below broker stops_level, excessive spread (ratio vs
  stop), risk-per-trade ceiling, exposure cap (notional as multiple of
  equity). Any fail → `approved=False`, `blocked=True`, reason + checks logged
  (acceptance: risk fail → NO trade).
- **`PositionSizer`** (`sizing.py`): `ContractSpec` (volume min/max/step,
  tick_size, tick_value, contract_size, stops_level, digits) + `SizingResult`.
  Lot = balance*risk_per_trade / (ticks*tick_value), rounded down to
  volume_step, clamped to [volume_min, volume_max]. Stop distance rounded to
  symbol digits to avoid float drift.
- **Tests:** 12/12 PASS; full suite 132/132 PASS.
- **Frozen engines:** unchanged (git diff CLEAN).
- **Next:** PHASE 5 — order execution engine (`src/live/execution.py`).
  Execution DISABLED by default (SIGNAL_ONLY / DRY_RUN must NOT send orders).

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
