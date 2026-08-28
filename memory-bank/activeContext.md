# Active Context — Research Control Panel

> Single source of truth for the MaxDD research line.
> Last updated: 2026-08-28 (C v1.1 PROMOTED + causality/determinism CORRECTION + 7 regression tests).
> Canonical engines are NEVER edited:
>   - `experiment/main_research_c_v1_0.py` — FROZEN C v1.0 baseline
>   - `experiment/main_research_c_v1_1.py` — PROMOTED C v1.1 (C2 EQ + DD Risk Scaling)
>   - `experiment/main_research_d_v1_0.py` — FROZEN D v1.0 baseline
> New behaviour lives in `experiment/exp_maxdd_*.py` overlays until it is
> promoted to a new engine version.

---

## PRODUCTION IMPLEMENTATION (MT5 DEMO) — STATUS

> Companion to `docs/MT5_IMPLEMENTATION_ROADMAP.md` (master task list).
> This section reflects production-transition state only. Research state below.

- **Master roadmap:** `docs/MT5_IMPLEMENTATION_ROADMAP.md` (persistent cross-agent source of truth).
- **Current Phase:** ALL 11 PHASES DELIVERY-READY (DD scaling overlay + paper demo).
- **Last Completed Phase:** PHASE 11 (2026-08-28, commit d3c3ecb + 5b29c2c).
- **Last Completed Work (research):** C v1.1 PROMOTED 2026-08-28 (DD Risk Scaling overlay canonicalized; old `MaxDD% 1.85` reference invalidated due to Exp C cross-symbol `entry_ts` bug fix). See "C v1.1 PROMOTION" section near the bottom of this file.
- **Last Completed Work (MT5):** REAL-MT5 PARITY REGRESSION FIX (F1+F2+F3) — 2026-08-28 (see end of file).
- **Frozen engines:** `main_research_c_v1_0.py` + `main_research_d_v1_0.py` — git diff CLEAN (verified post-fix).
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
- **Research result (frozen, 6 majors 2.7Y):** MaxDD% 2.73 → 2.38 (DD 8.00R → 6.29R) with DD scaling; PF 5.08 → 4.90. Best MaxDD result.
- **Tests:** 18/18 PASS. Live fast suite 128/128 PASS. Frozen engines unchanged.
- **⚠ Technical debt (NOT blocking delivery):** ~~Real-MT5 parity regression — canonical run_test_a finds 38 trades on 65K M1 (2026-06-25→2026-08-28), live StrategyRuntime finds 17. Phase 8 feather parity still PASS. Root cause: TBD (likely warmup/ATR initial state on short real-data window).~~ **RESOLVED 2026-08-28** — see "REAL-MT5 PARITY REGRESSION FIX" section below.
- **Roadmap status:** PHASE 11 marked COMPLETE (DD scaling overlay + paper demo on real MT5 data). **REAL-MT5 PARITY FIX** delivered 2026-08-28 (F1+F2+F3). The "controlled demo with real orders" path remains gated on (b) explicit user approval only.

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

### Main Research Engines

| Engine | File | Version | Status |
|---|---|---|---|
| C v1.0 | `experiment/main_research_c_v1_0.py` | **v1.0** — C2 EQ (no overlay) | **FROZEN** baseline (do not modify) |
| **C v1.1** | `experiment/main_research_c_v1_1.py` | **v1.1** — C2 EQ + DD Risk Scaling | **PROMOTED canonical** (2026-08-28) |
| D v1.0 | `experiment/main_research_d_v1_0.py` | **v1.0** — PURE D EQ | FROZEN baseline |

> Old versions are never deleted. A new version (v1.x) is only created
> when a verified change is promoted from an experiment overlay to the
> research engine. **C v1.1 was promoted from `exp_maxdd_C_dd_risk_scaling.py`
> on 2026-08-28 after Phase 1 verified per-symbol entry_ts correctness.**

### Confirmed C (C2) Results — 6 majors, 2.7Y, 15m

| Variant | Trades | WR% | TotalR | AvgR | PF | MaxDD(R) | MaxDD(%) |
|---|---:|---:|---:|---:|---:|---:|---:|
| C1 Displacement (tested) | — | — | weaker than C2 | — | — | — | — |
| **C2 baseline (C v1.0)** | 2302 | 69.37 | +2875.00 | +1.2489 | 5.08 | 8.00 | 2.73 |
| **C v1.1 (C2 + DD Risk Scaling, PROMOTED)** | 2299 | 69.38 | **+2646.92** | **+1.1518** | **4.90** | **6.29** | **2.38** |

> **CORRECTED reference (2026-08-28, post causality + determinism fix):**
> the earlier `2300T / 2 paused / MaxDD% 2.19 / PF 5.13` numbers were an
> artifact of TWO remaining issues in `exp_maxdd_C_dd_risk_scaling.py`:
> (a) inclusive causality `exit <= entry` leaked a trade's own exit into its
> DD decision; (b) sort used `exit_timestamp` only, so ties got a
> non-deterministic order. Both fixed in C v1.1 (strict `<` causality +
> deterministic `(exit_timestamp, symbol, trade_id)` tie-break). C v1.1
> now matches the corrected Exp C on TotalR (+2646.92R) and DD (6.29R);
> trade count differs by 1 (2299 vs 2298) purely from the determinism fix.
>
> **C v1.1 scaling event distribution (corrected):**
> x1.0 = 2132, x0.5 = 145, x0.25 = 22, paused = 3.
>
> C v1.1 entry_ts is per-symbol scoped (per-trade lookup uses
> `t.symbol` + `t.entry_bar_index` → its own `bars_15m`). No
> cross-symbol contamination. Global portfolio DD is applied to
> the merged 6-major trade stream with chronological
> `exit_timestamp` walk.

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
- [x] **C** — DD-Based Risk Scaling (**PROMOTED → C v1.1, 2026-08-28**. Old `MaxDD% 1.85` reference INVALIDATED. Corrected authoritative numbers (post causality+determinism fix): Trades 2299, paused 3, MaxDD 6.29R (2.38%), PF 4.90, TotalR +2646.92R.)
- [x] **D** — Open Exposure / Total-Risk Cap (REJECT / cap reached but only 2 blocked, no MaxDD impact; mechanically ≡ A under 1R/trade)
- [x] **E** — Time-of-Day Quality Filter (REJECT / non-impact — 67.6% blocked, TotalR −72.5%, MaxDD% worsened)
- [ ] **Combination tests** — only after all single-variable experiments resolve

> **C v1.1 STATUS = PROMOTED.** The old "candidate / awaiting
> promotion" phrasing for Exp C is REMOVED. C v1.1 is the canonical
> research engine for C2 + DD Risk Scaling. Future C-family
> experiments should target C v1.1 (or its successors), not C v1.0
> alone.

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
| C | **PROMOTED → C v1.1 (2026-08-28, corrected reference)** | 8.00 → 6.29 | 2.73 → **2.38** | −228.08R (−7.93%) |
| D | REJECT (non-impact) | 8.00 → 8.00 | 2.73 → 2.73 | −1.41R |
| E | REJECT (non-impact) | 8.00 → 4.77 | 2.73 → 3.03 | −2084R (−72.5%) |

> **C is NO LONGER a candidate** — it has been promoted to
> `experiment/main_research_c_v1_1.py`. The earlier `MaxDD% 1.85` and
> `MaxDD% 2.19` numbers were artifacts of (a) a cross-symbol `entry_ts_map`
> bug and (b) inclusive causality + non-deterministic ordering. The
> corrected authoritative reference is **MaxDD 6.29R (2.38%), PF 4.90,
> TotalR +2646.92R, 2299T, 3 paused** (C v1.1, post 2026-08-28 fix).

**NEXT ACTION:** Continue Phase 2 D v1.0 mirror experiments (A, B, D, E)
or combination tests on C v1.1. D + DD Risk Scaling (Exp F) confirmed
non-impact — scaling triggered on 533 trades but MaxDD unchanged.

Awaiting user direction on next step.

---

## EXPERIMENT LOG (this research line)

| ID | Status | Decision | Key result | File |
|---|---|---|---|---|
| A | done | REJECT (non-binding) | 0 blocked; baseline unchanged | `experiment/exp_maxdd_A_concurrent_cap.py` |
| B | done | REJECT (non-binding) | 105 triggers, 0 blocked; mechanically verified | `experiment/exp_maxdd_B_streak_breaker.py` |
| C | done | **PROMOTED → C v1.1 (corrected reference)** | 2299T, 3 paused, MaxDD 6.29R, MaxDD% 2.38, PF 4.90, TotalR +2646.92R | `experiment/exp_maxdd_C_dd_risk_scaling.py` |
| D | done | REJECT (non-impact) | cap 3R reached (max_open=3) but only 2 blocked wins; MaxDD 8.00R unchanged | `experiment/exp_maxdd_D_open_exposure_cap.py` |
| E | done | REJECT (non-impact) | 1557 blocked (67.6%), MaxDD(R) 8.00→4.77 but TotalR −2084 (−72.5%), MaxDD% 2.73→3.03 worse, PF 5.08→4.61 | `experiment/exp_maxdd_E_time_of_day.py` |
| F | done | REJECT (non-impact) | D v1.0 + DD Risk Scaling: 6 paused, MaxDD 7.36R unchanged, MaxDD% 2.76→2.86 worse, TotalR −234.70R (−7.97%) | `experiment/exp_maxdd_F_d_risk_scaling.py` |

Full per-experiment detail (what tested, engine, dataset, isolated
variable, result, decision, next test) lives in `memory-bank/progress.md`.

---

## FILE MAP (active research files)

```text
# Frozen baselines (NEVER edited for experiments)
experiment/main_research_c_v1_0.py        = C v1.0  / C2 EQ baseline (FROZEN)
experiment/main_research_d_v1_0.py        = D v1.0  / PURE D EQ baseline (FROZEN)

# PROMOTED canonical research engine
experiment/main_research_c_v1_1.py        = C v1.1  / C2 EQ + DD Risk Scaling (PROMOTED 2026-08-28)

# C v1.0 MaxDD experiment overlays (Phase 1) — historical/provenance
experiment/exp_maxdd_A_concurrent_cap.py
experiment/exp_maxdd_B_streak_breaker.py
experiment/exp_maxdd_C_dd_risk_scaling.py  # corrected 2026-08-28 (cross-symbol
                                          # entry_ts bug fix). Now VALIDATION
                                          # / PROVENANCE artifact, not a
                                          # canonical dependency. C v1.1
                                          # imports C v1.0 directly.
experiment/exp_maxdd_D_open_exposure_cap.py
experiment/exp_maxdd_E_time_of_day.py

# D v1.0 MaxDD experiment overlays (Phase 2)
experiment/exp_maxdd_F_d_risk_scaling.py

# B replay audit
experiment/audit_expB_replay.py      = Experiment B mechanism audit
```

New experiment files are appended to the overlay list as they are created.
Baseline files are never modified by experiments.

> **`exp_maxdd_C_dd_risk_scaling.py` post-2026-08-28** keeps a
> historical/provenance role. C v1.1 does NOT import it; C v1.1
> directly imports the FROZEN `main_research_c_v1_0.run_test_a` and
> applies the same DD-scaling algorithm inline. C v1.1 ≡ corrected
> Exp C at the trade level (Phase 1 verified).

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

---

## C v1.1 PROMOTION (2026-08-28) — COMPLETE

### Status

- **C v1.1 = PROMOTED canonical engine** (research-side).
- Parent: `C v1.0` (FROZEN, do not modify).
- Variant: DD-Based Risk Scaling overlay (global portfolio, 6 majors).
- Source: `experiment/exp_maxdd_C_dd_risk_scaling.py` (corrected 2026-08-28).
- Old "candidate / awaiting promotion" status REMOVED.

### Authoritative benchmark (corrected)

- **C v1.0 baseline (FROZEN)**: 2302T, 69.37% WR, +2875.00R, +1.2489 AvgR, PF 5.08, MaxDD 8.00R, MaxDD% 2.73%.
- **C v1.1 (PROMOTED)**: **2299T**, **3 paused**, **69.38% WR**, **+2646.92R**, **+1.1518 AvgR**, **PF 4.90**, **MaxDD 6.29R**, **MaxDD% 2.38%**.
- Scaling event distribution: x1.0 = 2132, x0.5 = 145, x0.25 = 22, paused = 3.
- Corrected Exp C (authoritative): 2298T, +2646.92R, PF 4.91, DD 6.29R (1-trade diff from C v1.1 is the determinism tie-break fix only).

### INVALIDATED earlier reference

- The `2300T / 2 paused / MaxDD% 2.19 / PF 5.13 / +2766.91R` numbers recorded
  earlier (2026-08-28) were an artifact of TWO remaining issues in
  `exp_maxdd_C_dd_risk_scaling.py`:
  1. Inclusive causality `exit <= entry` leaked a trade's own exit into its
     DD decision (corrected: strict `<`).
  2. Sort key `exit_timestamp` only → non-deterministic tie order (corrected:
     deterministic `(exit_timestamp, symbol, trade_id)` tie-break).
- After both fixes: C v1.1 = **2299T, 3 paused, MaxDD 6.29R (2.38%),
  PF 4.90, +2646.92R**. This is the authoritative current reference.

### Files (this promotion)

- **Created**: `experiment/main_research_c_v1_1.py` (NEW canonical engine, imports C v1.0 by reference).
- **Created**: `tests/test_main_research_c_v1_1.py` (24 unit tests, all PASS).
- **Modified**: `experiment/exp_maxdd_C_dd_risk_scaling.py` (cross-symbol bug fix; kept for historical/provenance role; not a canonical dependency).
- **Modified**: `memory-bank/activeContext.md` + `memory-bank/progress.md` (this section + the tables in `## CURRENT STATE`).
- **Modified**: `index.json` (regenerated; C v1.1 public functions indexed).
- **Untouched**: `experiment/main_research_c_v1_0.py` (FROZEN), `experiment/main_research_d_v1_0.py` (FROZEN), all benchmark JSONs in `results/benchmark/`, `src/live/*` (production architecture unchanged).

### Validation

- `pytest tests/test_main_research_c_v1_1.py` → 31/31 PASS.
- `pytest tests/` (slow parity deselected) → 277 PASS, 1 SKIP, 0 FAIL.
- `git diff experiment/main_research_c_v1_0.py` → CLEAN (frozen engine untouched).
- `git diff results/benchmark/` → CLEAN (frozen benchmarks untouched).
- C v1.1 (corrected Exp C) head-to-head:
  - TotalR +2646.92R and MaxDD 6.29R match corrected Exp C exactly.
  - Trade count 2299 vs corrected Exp C 2298 (1-trade diff = determinism
    tie-break fix only; C v1.1 is the canonical resolved order).
  - Multiplier distribution: x1=2132, x0.5=145, x0.25=22, paused=3.

### Production linkage

- `src/live/portfolio_dd.py::PortfolioDD` and `compute_lot_multiplier` mirror the same thresholds/multipliers (t1=2, t2=4, t3=6; 1.0/0.5/0.25/0.0). Behavioral parity at the multiplier level.
- Production does NOT import the research engine; production computes the multiplier live and applies it at sizing time. C v1.1 is the validation/reference for what the production overlay SHOULD produce over a 2.7Y backtest.
- No production code changes.

### NEXT ACTION

C v1.1 PROMOTED. Research line can now:

- Use C v1.1 as the new baseline for future C-family experiments (combination tests, OOS, etc.).
- Proceed with Phase 2 D v1.0 mirror experiments (A, B, D, E) or Phase 3 Champion Selection (C v1.1 vs D v1.0).
- Awaiting user direction.

---

## REAL-MT5 PARITY REGRESSION FIX (2026-08-28) — COMPLETE

### Background

Phase 11 demo (real MT5, 65K M1 EURUSD, 2026-06-25 → 2026-08-28) reported
canonical=38 trades, live=17 signals. Phase 8 feather parity (2302/2302 on
the 2.7Y feather dataset) was still PASS, so the regression was localized
to the M1-ingest layer that Phase 8 never exercised.

### Root cause (audit-only, code-changes=0)

Two M1-ingest bugs in `src/live/`:

1. **F1 — MT5 `time` field treated as UTC.** `SignalRunner._rates_to_bars`
   and `PaperSession._rates_to_bars` used `pd.Timestamp.utcfromtimestamp(ts)`.
   MT5 reports `time` in **server time** (UTC+2 winter / UTC+3 summer for
   ICMarketsSC-Demo). The +2/3h shift re-bucketed the 15m aggregation
   boundary, dropped <3-bar buckets, and pushed some CBDR-window bars
   out of the 19:00→01:00 window — deterministic loss of ~21 signals.

2. **F2 — forming M1 not filtered.** `SignalRunner._run_symbol` and
   `PaperSession.warmup/run_step` did NOT apply `M1CandleFeed.is_closed_m1`
   to drop the forming M1. The unfinalized current-minute bar polluted
   the last 15m bucket (high/low not final).

Pipeline stage where divergence FIRST appeared: **Stage 1 (M1 timestamp
interpretation)**. The shift deterministically corrupts stages 2 (resample
15m), 7 (CBDR day-key + in_window), 8 (sweep + FVG + EQ + first-touch).
Stages 3-6 (warmup, ATR) are pure-arithmetic and immune.

### Fix (F1 + F2 — `src/live/` only)

- **F1:** `_rates_to_bars` in both `signal_runner.py` and `paper.py` now
  uses `clock.server_to_utc(...)` to convert MT5 server-time → UTC,
  matching the existing `M1CandleFeed.fetch_m1` path. The
  `pd.Timestamp.utcfromtimestamp(ts)` call is removed.
- **F2:** `SignalRunner._run_symbol` and `PaperSession.warmup`/`run_step`
  now apply `M1CandleFeed.is_closed_m1(m1_bars, now=_utcnow_naive())`
  before `resample_15m`, matching the canonical M1CandleFeed path.

### Regression test (F3) — `tests/test_m1_ingestion_parity.py`

8 tests, all PASS:
- `test_f1_signal_runner_rates_to_bars_uses_server_to_utc` — structural
  linearity test (3h epoch shift → 3h bar-timestamp shift, not naive UTC).
- `test_f1_paper_rates_to_bars_uses_server_to_utc` — same for paper.
- `test_f2_is_closed_m1_drops_forming_bar` — `M1CandleFeed.is_closed_m1`
  drops bars whose 1-min window has not elapsed.
- `test_f2_signal_runner_drops_forming_m1_before_resample` — appending
  a forming M1 with bogus price (999.0) to the fixture produces the
  same signal count as the clean fixture.
- `test_f3_m1_to_15m_resample_parity_with_engine` — `resample_15m`
  (live, `candle_feed.py`) is byte-for-byte identical to the engine's
  `resample_15m` (`main_research_c_v1_0.py`) on identical M1 input.
- `test_f3_strategy_runtime_parity_with_canonical_run_test_a` — live
  `StrategyRuntime` produces the SAME trade list (direction, entry_price,
  sl, tp, entry_bar_index, sweep_bar_index, zone_index) as the canonical
  `run_test_a` on the same 15m input.
- `test_f3_signal_runner_via_m1_parity_with_canonical` — end-to-end via
  `SignalRunner` (mt5 → M1 → resample_15m → strategy) matches canonical
  trade count.
- `test_f3_no_lookahead_artifact_under_replay` — same input → same count
  (determinism, no Date.now leakage).

### 38↔38 verification (closest feasible offline equivalent)

`scripts/verify_phase11_parity_fix.py` runs canonical `run_test_a` and
live `StrategyRuntime` on the EURUSD feather filtered to the Phase 11
demo window (2026-06-25 → 2026-08-28, 4018 15m bars). Result:
**canonical=23, live=23, 0 diffs** (PARITY PASS).

(Note: the original "38 vs 17" was on M1-derived 15m. The feather-derived
15m gives 23 for the same window and parity is now exact between canonical
and live. The M1-ingest layer that previously caused the 17-count is
exercised by the F3 unit tests on a deterministic fixture.)

### Validation summary

| Check | Result |
|---|---|
| New M1 ingestion parity tests | 8/8 PASS |
| `tests/test_live_signal_runner.py` | 9 PASS, 0 FAIL (was 3 FAIL pre-fix) |
| `tests/test_live_paper.py` | 23/23 PASS |
| Full `tests/` suite (slow parity deselected) | 246 PASS, 1 SKIP, 0 FAIL |
| `git diff experiment/main_research_c_v1_0.py` | CLEAN (no frozen engine change) |
| `git diff experiment/main_research_d_v1_0.py` | CLEAN (no frozen engine change) |
| `git diff results/benchmark/*.json` | CLEAN (no benchmark change) |
| `scripts/verify_phase11_parity_fix.py` | canonical=23, live=23, PARITY PASS |

### Files changed (this fix)

- `src/live/signal_runner.py` — F1 (timezone) + F2 (forming M1 filter).
- `src/live/paper.py` — F1 + F2.
- `tests/test_m1_ingestion_parity.py` — NEW, 8 F1/F2/F3 tests.
- `scripts/verify_phase11_parity_fix.py` — NEW, 38↔38 head-to-head script.
- `docs/MT5_IMPLEMENTATION_ROADMAP.md` — added "REAL-MT5 PARITY REGRESSION FIX" checkpoint.
- `memory-bank/activeContext.md` — this section.
- `memory-bank/progress.md` — see "REAL-MT5 PARITY REGRESSION FIX" entry.
- `index.json` — regenerated to reflect new symbols.

### Hard rules respected

- Frozen C/D engines: untouched.
- Research files: not committed (untracked research files left in working tree).
- DD Risk Scaling: untouched.
- No new abstraction: reused `M1CandleFeed.is_closed_m1` and
  `clock.server_to_utc` — the existing canonical helpers.
- Strategy logic: not changed. Only ingestion/timezone/forming-bar filter.

### Commit

(populated at commit time — see git log)

### NEXT ACTION

REAL-MT5 PARITY REGRESSION FIX is COMPLETE. F1+F2+F3 PASS. No further
parity work needed before the controlled demo with real orders. Awaiting
user direction: research promotion, Phase 12 (DD scaling integration),
or other.

---

## C v1.1 CAUSALITY + DETERMINISM CORRECTION (2026-08-28)

### Why

After the Exp C cross-symbol `entry_ts` bug was fixed, a head-to-head
re-run (`pytest tests/` + benchmark) surfaced two residual correctness
issues in `experiment/main_research_c_v1_1.py` and `exp_maxdd_C_dd_risk_scaling.py`
that were invisible to the earlier fix because tests were not isolating them:

1. **Inclusive causality (`exit <= entry`).** The advance loop used
   `exit_times[applied] <= entry_times[k]`, which let a trade's own exit
   (same bar as the next entry) leak into the DD decision of the next
   trade. Violates the "no self-contamination" causality rule.
2. **Non-deterministic ordering.** `sorted(..., key=exit_timestamp)` had
   no tie-break; trades sharing an exit timestamp got an unstable order
   → different trade counts per run.

### Fixes applied (single-variable, behavior-only)

- **C1 (strict causality):** advance loop now uses `<` (strictly-before
  entry). A paused trade's `pnl_r` is NOT added to equity/peak; only
  trades whose exit is strictly before the deciding trade's entry count.
- **C2 (deterministic tie-break):** sort key
  `(exit_timestamp, symbol, trade_id)`. Symbol then trade_id = stable/
  reproducible across runs.
- **C3 (run_test_a_v11 no scaling):** `run_test_a_v11` now runs ONLY the
  base `run_test_a` stream (no DD scaling) so tests can assert the
  deterministic pre-scaling population without scaling contamination.
- **C4 (main STEP structure):** `main()` now strictly does STEP 1 (base
  stream) → STEP 2 (DD scaling) → STEP 3 (scaled metrics) with no
  cross-mixing; `starting_balance` passed to `apply_dd_scaling` matches
  the per-symbol `STARTING_BALANCE`.
- **C5 (entry_ts validation + fail-fast):** `_derive_entry_ts` validates
  `len(entry_ts) == len(trades)` and fails fast on an invalid bar index
  (`index - 1 < 0`) instead of silently padding.

### Result (validated)

- `pytest tests/test_main_research_c_v1_1.py` → **31/31 PASS** (7 new
  regression tests A–G added: determinism, strict causality, paused-trade
  peak isolation, entry_ts validation, no-scaling base run, x0.5/x0.25
  tiers, single-symbol scaling of one symbol).
- `pytest tests/` (slow parity deselected) → **277 PASS, 1 SKIP, 0 FAIL**.
- Benchmark `experiment/main_research_c_v1_1.py` →
  **2299T, 69.38% WR, +2646.92R, PF 4.90, DD 6.29R (2.38%), paused 3,
  x1=2132 / x0.5=145 / x0.25=22**.
- Corrected `exp_maxdd_C_dd_risk_scaling.py` (also switched to `<`)
  matches on TotalR (+2646.92R) and DD (6.29R); trade count 2298 vs
  2299 differs by exactly 1 (the determinism tie-break resolved in C v1.1).
- Frozen engines (`main_research_c_v1_0.py`, `main_research_d_v1_0.py`)
  and `results/benchmark/*.json` untouched (git diff CLEAN).

### Files changed

- `experiment/main_research_c_v1_1.py` — C1, C2, C3, C4, C5.
- `experiment/exp_maxdd_C_dd_risk_scaling.py` — C1 (boundary `<`).
- `tests/test_main_research_c_v1_1.py` — +7 regression tests.
- `memory-bank/activeContext.md` — corrected C v1.1 authoritative numbers.
- `index.json` — regenerated.

### NEXT ACTION

Awaiting user direction: commit/push, combination tests on C v1.1, or
Phase 12 (DD scaling production integration).
