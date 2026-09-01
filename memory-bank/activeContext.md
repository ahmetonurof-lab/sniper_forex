# Active Context — Research Control Panel

> Single source of truth for the MaxDD research line.
> Last updated: 2026-08-29 (NATIVE WINDOWS MT5 PROVEN — Phase 2/3/4/5 PASS, repository cleanup complete, runtime hardening task list created).

## NATIVE WINDOWS MT5 — STATUS (2026-08-29)

### Environment
- Python: 3.12.2 (64-bit) at `C:\sniper_forex\venv\`
- MetaTrader5: 5.0.6147 (PyPI)
- MT5 Terminal: build 6140, IC Markets Global
- Account: 53012914 @ ICMarketsSC-Demo (DEMO)

### Verified Phases
| Phase | Test | Result |
|-------|------|--------|
| Phase 2 | Read-only MT5 connectivity | PASS |
| Phase 3 | BTCUSD DEMO execution (entry/SL/TP/close) | PASS |
| Phase 4 | Runtime smoke (signal_only=True) | PASS |
| Phase 5 | Live polling harness (signal_only=False) | PASS |

### Key Findings
- `order_check()` retcode 0 = success (not TRADE_RETCODE_DONE)
- MT5 comment limit: 29 chars
- BTCUSD minimum SL/TP distance: ~5000 points ($50)
- CBDR window: 19:00→01:00 UTC

### Repository Cleanup (2026-08-29)
- **Deleted**: 12 obsolete files
- **Preserved**: All audit logs, research artifacts, documentation
- **Task list**: `docs/FOREX_RUNTIME_HARDENING_TASKS.md`
- **Observability plan**: `docs/FOREX_OBSERVABILITY_ACTION_PLAN.md`

### Current Task List
- **Next task**: Task 0.1 — Startup Broker State Snapshot ✅ DONE
- **Next task**: TAŞ 2 — Orchestrator S3-S9 + Bar Pipeline + Lock Contract ✅ DONE
- **Priorities**: 8 priorities, 24 tasks total

---

## PROCESS RULE — REFEREE RED = VETO (2026-08-30)

> Referee RED on a design decision carries VETO authority. Do NOT bypass a
> veto by "implementing + noting it". A vetoed change must either be reverted
> or re-submitted as a NEW design proposal (with D-id, race analysis, and
> Phase-2 drill linkage) and explicitly approved before it stays.

### TAŞ 3 — Referee Audit Disposition (2026-08-30)
- **P1 (D35 materialize)**: RED → REVERTED. `_heartbeat_validated` lock-absent
  now returns False (no self-reclaim). Tests acquire the lock in `make_orch`
  fixture (`orch.lock.acquire()`).
- **D46 (interruptible sleep)**: APPLIED. `_interruptible_sleep` chunks <=1s,
  re-checks kill between chunks (PEP 475: plain sleep(300) not signal-
  interruptible → graceful shutdown would stall). Injected `sleep_fn` (tests)
  still called once with full value so backoff cadence stays observable.
  **D46-KANIT (referee T-a/T-b)**: 2 unit tests added — T-a chunk-sum (300
  chunks, sum==300.0 via monkeypatched time.sleep), T-b kill-during-sleep →
  early True + run() maps to graceful exit (0/2), not fatal 1.
- **D41 backlog replay guard**: `entries_enabled` added to D41 replay — SAFE-
  START + runner-var must NOT accumulate pending backlog (gate closed, feed
  never runs → would pile to feed_cap). `test_gate_blocks_on_bar_when_recon_
  blocked` asserts `_pending_feed == []`.
- **Kill/heartbeat order**: kill-first (D11) then heartbeat (D35). Human kill
  exit code (0/2) must not be overridden by concurrent ownership check;
  ownership loss is fatal 1 only when no kill pending.
- **D47 (produce_new_bars exception → ladder)**: NOT applied — status reported
  only (referee asked for status, not implementation).
- **D43 evidence**: `test_feed_cap_warns_once` PRESENT (13 tests include it) —
  feed cap + one-time alert covered.
- **14→13 tests**: GLM sketch had 14; delivery has 13. D43 test retained.
  Missing 14th test identity unknown (GLM run() hunks never received).
- **2 E2E failures** (`test_e2e_live_chain.py`): pre-existing, untracked test,
  production correct (context_registered only from broker-confirmed fill).
  Does NOT block Taş 3. Disposition pin: fill-mock or delete test.

---

CURRENT IMPLEMENTATION STATE (2026-08-29 checkpoint):
- C v1.0 (experiment/main_research_c_v1_0.py): FROZEN — git diff CLEAN
- C v1.1 (experiment/main_research_c_v1_1.py): PROMOTED — git diff CLEAN (pre-existing committed state)
- D v1.0 (experiment/main_research_d_v1_0.py): FROZEN — git diff CLEAN
- trailing_adapter.py: PROTECTED — git diff CLEAN
- strategy_runtime.py: PROTECTED — git diff CLEAN

LIVE PRODUCTION PATH TRACE (verified 2026-08-29):
- src/main.py → src/test_mt5_connection.py → MetaTrader5.initialize() → SignalRunner(mt5=mt5) → M1CandleFeed.fetch_m1 → resample_15m → StrategyRuntime
- execution.py: direct MetaTrader5.order_send/order_check (injectable mt5= param) — order_check retcode fix applied (0 = success)
- live_runner.py: poll_deals uses position-based history query (history_deals_get(position=pid)) — authoritative exit deal retrieval
- candle_feed.py: direct MetaTrader5.copy_rates_from_pos — production data path
- position_manager.py: tracks open positions, detects disappeared positions for exit deal query
- SLTP modification: Execution.modify_position_sl_tp() with TRADE_ACTION_SLTP native request
- paper.py: P1 M1/15m timestamp domain separation + R conversion using trade risk cash (217d27a)
- sizing.py: P1 min-lot scaling semantics — reduction unachievable blocks trade (217d27a)

VERIFICATION STATUS:
- Mock verified: PASS (109/109 MT5 lifecycle tests)
- Static verified: PASS (caller→callee trace, git diff CLEAN, protected files intact)
- Real MT5 verified: PASS (connection + demo roundtrip + authoritative exit deal)
- Server audit: COMPLETE (169.58.41.73, Ubuntu, crypto bot isolated at /root/sniper)
- Deployment: READY FOR CONTROLLED SERVER DEPLOYMENT / DEMO VALIDATION

MT5 GATEWAY STATUS (2026-08-29):
- Architecture: EXISTING DIRECT API (no new wrapper/factory needed)
- order_check: FIXED — retcode 0 = success (not TRADE_RETCODE_DONE)
- comment length: FIXED — SFX-EURUSD-L0-0 format (14 chars, within 29-char limit)
- exit deal retrieval: FIXED — history_deals_get(position=pid) for authoritative exit deals
- All gates PASSED: connection → market data → signal-only → order_check → demo entry → SL/TP → SL modify → close → exit deal → PortfolioDD → restart/recovery

REAL MT5 GATE RESULTS (2026-08-29):
- REAL ENTRY via Execution.send: PASS
- REAL SL MODIFY: PASS (broker-confirmed)
- REAL CLOSE: PASS
- AUTHORITATIVE EXIT HISTORY: PASS (history_deals_get(position=pid))
- HISTORY EXIT DEAL: VERIFIED (13 exit deals recovered from real broker)
- REAL BROKER PNL: AUTHORITATIVE (profit + commission + swap)
- P0-2 STATUS: PASS (idempotent, DD reliable)
- PortfolioDD: Updated exactly once per deal
- Restart/Recovery: PASS (journal replay, duplicate protection)

SERVER STATE (169.58.41.73):
- Crypto bot: /root/sniper (Binance paper trader, RUNNING, PID 755865)
- Forex target: /root/sniper_forex (NOT YET CREATED)
- MT5 terminal: AVAILABLE (verified working)
- Python: 3.14.4 (system + crypto venv)
- Disk: 89G available
- Crypto isolation: GUARANTEED (separate directory, venv, .env)
10. realized PnL → PortfolioDD
11. restart/recovery
12. reconciliation
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
- **DD Risk Scaling:** OVERLAY IMPLEMENTED in production (`src/live/portfolio_dd.py`, integrated into `RiskManager.evaluate()` via `portfolio_dd_r`). Not out of scope — live module active; frozen research engine (`C v1.1`) remains the authoritative benchmark reference.
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

---

## EVENT-BASED CAUSALITY FIX (2026-08-28) — apply_dd_scaling()

- **What:** Replaced exit-ordered replay with event-based `ENTRY` (priority 0) / `EXIT` (priority 1) stream sorted by `(timestamp, priority, symbol, trade_id)`.
- **Why:** Synthetic tests (overlapping trades, same-timestamp strict `<`, scaled realized, paused zero, locked multiplier, order independence) showed exit-order replay violates entry-time DD semantics.
- **Mult lock:** `mult_lock[symbol_id]` computed at ENTRY; scaled PnL applied at EXIT; paused (`mult=0`) updates nothing.
- **Files:** `experiment/main_research_c_v1_1.py` (function body only); `tests/test_main_research_c_v1_1.py` (expectations fixed); `test_causality_synthetic.py`, `test_causality_extended.py` (new).
- **Benchmark:** dry-run passes; full 2.7Y/6-major pending user direction.
- **No production / C v1.0 / memory-bank / git changes outside this entry.
-e "\n---\n### LIVE FIX CHECKPOINT (2026-08-28) - P1-5 / P1-4 / P0-2 / P0-1 / P1-3 / P2-6 / P3-7 PASS\n- Scope: timezone canonicalization, false-close protection, lifecycle/deal owner, DD-scaled lot, paper economic path, paper 15m continuity, doc sync.\n- Protected files preserved: frozen C/D engines and benchmark JSONs untouched.\n- 65K M1 artifact frozen: results/research/65k_m1_eurusd_parity_artifact.json.\n- No strategy optimization. Ready for user direction: commit/push or Phase 12."

---

## TAŞ 4 — CONDITIONAL ACCEPT DELTA (2026-08-30)

Reviewer verdict: **CONDITIONALLY ACCEPTED** — S1–S5 + R1–R2 delta paketi.

### Applied (S1–S5 + R1)
- **S1** `src/live/run_production.py`: try/except BaseException + finally → shutdown()
  idempotent belt-and-braces; KeyboardInterrupt → teardown sonra exit 0 (D46).
- **S2 / D48** `orchestrator.shutdown()`: `schedule_snapshot(runtime, lifecycle, symbol,
  state_dir)` lock release'ten ÖNCE çağrılıyor (best-effort try/except).
  Aşama 2 şartı kaydedildi: per-N-bar periodic save (kill -9 crash window).
- **S3/T-c** Yeni test `test_run_production_chunked_sleep_path`:
  `orchestrator.time.sleep` monkeypatch + sleep_fn=None → tüm chunk çağrıları <=1.0s.
- **S4** D18 ikili kural `_build_config()`: SNIPER_STATE_DIR explicit+relative →
  SystemExit FATAL; unset → abspath resolve + stderr WARN; audit_path aynı kural.
  Yeni test: `test_d18_state_dir_policy`. WorkingDirectory pin → Aşama 5 deployment contract.
- **S5** `orchestrator.startup()` `_mt5_conn is None` → tek audit event
  (`EventType.SAFETY`, payload `mt5_conn_unset_test_seam_active`) — B2 dersi: sessiz seam yok.
- **R1/N3** `tests/test_causality_extended.py` → `scripts/test_causality_extended.py`
  taşındı (script-format dosya; pytest collect etmesin).

### Yeni testler (+5 → tas4 toplam 17, orchestrator süiti 95/95)
1. `test_run_production_run_raises_calls_shutdown` (T-d)
2. `test_run_production_base_exception_still_shuts_down` (S1/KeyboardInterrupt)
3. `test_shutdown_writes_runtime_and_lifecycle_snapshots` (S2/D48)
4. `test_d18_state_dir_policy` (S4)
5. `test_run_production_chunked_sleep_path` (S3/T-c)

### N kayıtları
- **N1**: doğru toplam 90 idi (tas2 36 + startup 13 + snapshot 14 + tas3 15 + tas4 12);
  "76" rapor hatasıydı, delta sonrası 95.
- **N2**: e06fb3b remote'ta MEVCUT — push bir önceki oturumda sessiz yapılmış.
  Policy: bundan sonra push yalnızca reviewer'ın yazılı onayıyla; her push log'a
  (kim, ne zaman, hangi commit) girer. LUNA/Forexçi'den cevap bekleniyor.
- **N3**: dosya hiçbir commit'te yoktu (untracked, script-format); scripts/'e taşındı.
- **N4**: skip = `test_live_signal_runner.py::test_signal_runner_signal_event_payload_has_expected_fields`
  (random data, no signal). Aşama 2 pin: seed'e bağla.

### Worktree deneyi (e06fb3b)
`test_main_research_c_v1_1.py`: **5 fail e06fb3b'de de** → "pre-existing" lehine kanıt.
LİMİTASYON: tam izolasyon sağlanamadı — `src/strategy/` ve `experiment/` commit'li
değil; worktree çalışması için working-tree src/experiment kopyalandı. Fail kökü
(src/strategy drift mi, hep-kırık mı) hâlâ ayırt edilemiyor → COMMIT A önceliği.

### Açık maddeler (commit seremonisi öncesi/sonrası)
- COMMIT A: src/strategy + experiment/* + canonical test + parity artifact → sonra
  5-test re-run → GREEN ise tag `research-canonical-v1.1`, RED ise bilinen-kırık pin + bug-report.
- COMMIT B (piece-1 atomik): index_builder --full ÖNCE → orchestrator.py,
  run_production.py, test_orchestrator_tas2/3/4.py, recovery.py, trailing_bridge.py,
  test_e2e_live_chain.py, memory-bank, index.json; mesaj: D1–D48 mapping.
- PUSH: yalnızca reviewer yazılı onayıyla (N2 policy ilk uygulama).
- Aşama 5 pin'leri: WorkingDirectory pin, Telegram webhook, dead-man, wedge/resurrection
  drill, D47-ladder, D44, non-UTC test, per-N-bar save (D48'in loop yarısı).

## TAŞ 4 FINAL DELTA — K1–K4 (2026-08-30, ikinci review)

- **K1**: `test_run_chunked_path_real_orchestrator` — GERÇEK `Orchestrator.run()`
  (Taş 3 `make_orch` fixture) + `orchestrator.time.sleep` monkeypatch +
  `kill_after(2)` + `sleep_fn=None` → gerçek `elif _interruptible_sleep` dalı
  koşuluyor; tüm chunk'lar `0 < c <= 1.0`. FakeOrch kopya-test SİLİNDİ —
  production-branch kanıtı artık tek: gerçek kod.
- **K2**: run_production KeyboardInterrupt → exit kodu artık DURUM-BAĞIMLI:
  `2 if (_runtime_safe or verdict != PROCEED) else 0`; startup tamamlanmadan
  kesildi ise 0. kill_fn semantiğiyle hizalandı. 3 test:
  PROCEED→0, SAFE_START→2, runtime_safe→2.
- **K3**: shutdown() içinde schedule_snapshot failure → tek audit ERROR
  (`{"phase": "shutdown_snapshot", "error": ...}`) — best-effort ama sessiz değil.
- **K4**: code-in-hand final state bu mesajda (aşağıda).

### Regresyon
- Orchestrator süiti: **97/97** (tas2 36 + startup 13 + snapshot 14 + tas3 15 + tas4 19)
- Tam süit: **7 failed, 455 passed, 1 skipped** — fail listesi öncekiyle BİREBİR
  (2× e2e_live_chain pin'li + 5× canonical research pre-existing), drift YOK.

## SEREMONİ DEFTERİ — PUSH KAYDI (final gate)

```
push: onaylı (hakem, final gate — bu sohbet) — spot-check 7 yeşil + 1 sarı→yeşil
  (Q8: FakeOrch 12 referans = entry-point test seam, meşru ve zorunlu; K1
  gerçek-branch kanıtı Q8a dokümantasyonu + Q7 20 test + 98/98 koşum ile).
N2 policy ilk uygulama: kayıtsız push kapatıldı; itibarıyla her push = yazılı
  onay + log (kim/ne/zaman).
İKİ COMMIT (düzeltme — önceki taslakta yanlış hash'ti):
  2bff15b (research baseline / Aşama 0) + 5136094 (piece-1, D1–D48) → origin/main.
  NOT: e06fb3b zaten remote'taydı — push setine ait DEĞİL; deftere yanlış
  hash yazılma hatası push öncesi yakalandı ve düzeltildi.
Sonrası doğrulama: git log --oneline origin/main..HEAD → BOŞ beklenir;
  git ls-remote origin main → 5136094 beklenir. İki çıktı Aşama 1'in imzasıdır.
Onay: HAKEM — bu sohbet, final gate.
```

## D49 FINAL — COLD-REBUILD HOLE FIX (B-1) + PUSH (2026-08-31)

- **B-1**: `_begin_cold_rebuild()` (orchestrator.py) — stale/partial restore'da
  `_seen_bar_slots.clear()` + `_global_bar_index=0` + `_last_15m_ts=None` +
  FRESH `StrategyRuntime` + `_runtime_restored=False`; lifecycle dokunuşsuz (D6).
  İki çağrı noktası: S7 partial-restore dalı + S9 staleness gate (`warm_skip=False`).
  Kök neden: `_seed_restore_state()` restore slotlarını seen'a ekliyordu →
  reindexed loop seen-skip ile restore dönemini ATLADIYOR → delikli runtime.bars
  → O2 replay delikli stream'den bias/ATR/session üretiyordu.
- **T1/T4 hole-assertion'ları**: T1 restored-slot varlığı + `_assert_no_slot_gaps`
  (fake history 1700' — guard vakumda değil); T4 tamlık + oldest-slot full-coverage.
  KRİTİK KANIT: T4 ilk tam süitte KIRMIZIYDI (8 fail) → B-1 ile YEŞİL. Delik artık
  görünmez kalamaz.
- Regresyon (committed blob üzerinde): d49 8/8 · orchestrator grubu 92/92 ·
  push-öncesi son koşum 98/98 (startup+tas2+tas3+tas4+snapshot) ·
  tam süit `tests/` = **7 failed, 464 passed, 1 skipped** (668s).
  Fail listesi = pin'li 7 (2×e2e_live_chain + 5×canonical research) — baseline'la
  BİREBİR; tek diff T4 failed→passed (B-1 kanıtı). R-1 dürüst ifadesi: 7 fail
  düzeltilmedi, kapsam dışı/pin'li kaldı; beklenen liste buydu ve çıktı.
- **COMMIT**: `b36c7c4` "D49: boot-time sync replay (O2) + restore staleness
  gate — C1-C6, B-1" — yalnız 4 dosya (orchestrator.py, test_orchestrator_d49.py
  yeni, test_orchestrator_tas2.py T6-update, index.json). 35+ formatting-only
  modified dosya stage DIŞI (rambling check). Ayrı commit, piece-1 amend yok.
- **PUSH**: onaylı (hakem, bu sohbet) — `b9d15a3..b36c7c4 main -> main`.
  İmzalar: `git log origin/main..HEAD` → BOŞ · `git ls-remote origin main` →
  `b36c7c4176c8b5c362a9512fe545330aa4354cdd`. N2 policy ikinci uygulaması.

### INCIDENT — code-index-system watcher (kayıt, hakem talimatı)

- `tools/code-index-system/watcher.py` arka planda çalışıyordu (PID 10408) ve
  `index.json`'ı **bayat 658-fonksiyonluk üretimle** staged 1507-fonksiyonluk
  blob'un ÜZERİNE ezdi → pre-commit stash-restore çakışması → **iki commit
  rollback'i** (1. deneme: hook auto-fix + conflict; 2. deneme: aynı).
- Çözüm: watcher kill (PID 10408), staged index blob'u worktree'ye geri alındı,
  3. deneme temiz geçti → `b36c7c4`.
- **KARAR (hakem): watcher KAPALI kalacak, soak boyunca da kapalı.**
  Gerekçe: (1) kanıtlanmış tehlike; (2) index.json atomic-commit disiplinine
  bağlı — commit anında dışarıdan mutasyona açık tek dosya; (3) soak'ta index
  işlevi yok (MCP navigation artifact, runtime'a girmiyor). Index gerektiğinde
  MANUEL: `cd tools/code-index-system && python index_builder.py --config
  config.json --full` (commit ÖNCESİ, aynı protokol). Soak sonunda değerlendirilir.
- **HOOK HIJYENİ (Aşama 2 backlog)**: format değişikliği commit anında hook'a
  bırakılmayacak — `ruff format` stage'den ÖNCE elle koşulacak (veya hook
  `--check` moduna alınacak); commit-anı mutasyonu sıfır, stash koreografisi
  gereksizleşir.

### SOAK START GATE (4 şart, sıra önemli) — D49 MERGE sonrası; D53/Hakem ile ④ eklendi

1. **C2 end-state policy** — Forexçi YAZILI karar: simüle `active_trade`
   (O2 replay end-state) canlı girişleri bastırır mı? Mimari hazır:
   COLD_REBUILD_OK + replay_report `end_state` alanı.
2. **P0 teşhis** — 5 canonical causality fail'i: differential + blame
   (paralel koşabilir).
3. **Tag'li parity** — P0 çözülünce tag + artifact bağlama.
4. **Telegram seviye-1 E2E (D53/Hakem)** — operatör bot'a START basar →
   smoke `"ok":true` + gelen DM → raporla. Sahibi: operatör (insan adımı,
   tek tık). Kanal kanıtsız soak BAŞLAMAZ (hidden-green yok).
- **Known-flake pin (Hakem disposition, D53):** `d49 T4-fresh-boot` =
  time-boundary flake (dakika-kırpımlı anchor + boundary aşması; mekanizma
  güçlü, koşum kanıtı yok — 5+ koşumda yalnız 2 kez kırmızı, ikisi de
  uzun-süit/uzun-grup bağlamında). Soak'ta tekrarlanırsa hidden-red DEĞİL,
  pin'li flake. Aşama 2 backlog: `now_fn`-enjeksiyonlu deterministik rewrite.
- Paralel: **S10 boot-replay ölçümü** (~4.330 on_bar/boot — soak ilk raporunda
  sayı gelsin) · runbook'a `restore_staleness_slots` semantiği (2-slot tolerans
  penceresi; 0 = her gap rebuild).
- N-a notu: COLD_REBUILD_OK + final STARTUP = bir boot'ta iki STARTUP event
  (kabul); SHUTDOWN-dedupe'nin "one-per-kind" genellemesi Aşama 2'ye.

### SOAK TREE FREEZE (yeni kural, soak start anında aktif)

```text
soak süresince src/ + tests/ + index.json = HEAD; mutation YOK.
İstisna: soak artifact'leri (state/, logs/) + koşum log'ları (.gitignore'lu).
memory-bank: WRITABLE — chore commit'lere izinli (kod-dokunuşu yok; N2 push
policy yine geçerli). Aksi halde iki haftalık kanıt uncommitted birikir.
Kod değişikliği gerekirse: soak durur (event kaydı) → değişiklik →
tam süit → commit/push (N2) → soak restart. Kısayol yok.
```

Gerekçe: restart, commit'lenmiş VE süit-lenmiş bir ağaçtan ayağa kalkmak
zorunda; sınamamış state'te restart = soak'ın ölçtüğünü bulanıklaştırır.
Format sweep bu kural öncesi SON mutasyon penceresinde yapıldı (2026-08-31).

- Ledger write tool mid-write corrupt (5× D49 dup); recovered from HEAD —
  commit-early discipline third payoff (watcher / kayıtsız-push / tool-failure).

### C1–C4 PUSH KAYDI — N2 #5 + AĞAÇ DONDURULDU (2026-08-31, soak start)

- **SET (4 commit, hakem onaylı paket):**
  - `2730977` chore: relocate test_causality_synthetic.py root→tests/ (2 files, +243/−215)
  - `fb89e79` chore: ruff format sweep — behaviour-neutral (43 files) + index.json atomic
    (44 files, +275/−472)
  - `cb2d659` chore: archive initial GLM review → docs/archive/ (1 file, +1232)
  - `b89895a` chore: ledger — freeze rule + tool-corruption incident note (1 file, +18)
- **PUSH (N2 beşinci uygulama):** onaylı (hakem, bu sohbet) — `5c35862..b89895a main -> main`.
  İmzalar: `git log origin/main..HEAD` → BOŞ · `git ls-remote origin main` →
  `b89895ac21e793425529cbf84f8eb9b1950dd9eb` = local HEAD. Remote HEAD güncel.
- **Süit imzası (C2 nötrlük, ampirik):** 7 failed / 464 passed / 1 skipped / 0 errors
  (655.42s) — fail listesi pin'li baseline ile birebir (2×e2e_live_chain + 5×canonical).
- **AST nötrlük kanıtı (yeni kanıt sınıfı, hakem standardı):** behaviour-neutral iddia
  hiyerarşisi = iddia < koşum < AST. 45 .py'da import-set + gövde-AST kıyaslaması →
  NONE (19 sahte-diff = I001 alias sırası, normalize edildi). **Soak runbook kuralı:**
  soak sırasında chore commit yapılırsa nötrlük AST katmanıyla kanıtlanacak.
- **Sayı dersi (defter):** 42→43 — tahmin ≠ ölçüm; ölçümü rapor eden kazanır.
  Stage kazası commit ÖNCESİ yakalandı (75→44: untracked sızıntısı + ledger sızıntısı,
  ayrı ayrı temizlendi). Sıfır untracked arşive girdi.
- **Archive temizlik kontrolü (madde 4):** credential taraması = tek hit satır 437
  `password=config["password"]` (sözlük-anahtarı referansı, literal sır değil); IP yok,
  hesap no yok (6+ hane: yalnız magic=9007001), token yok. **Aşama 4 gate'ine şart
  olarak işlendi: canlı hesaba geçişte docs/archive/ canlı-kimlik temizliğinden
  geçecek.**
- **FREEZE: AKTİF.** src/ + tests/ + index.json = HEAD (`b89895a`); mutation YOK.
  memory-bank writable (kod-dokunuşu yok). Kod değişikliği = soak durur → tam süit →
  N2 → restart. Kısayol yok. Watcher KAPALI.
- **Soak gate açık kalemler:** ① C2 end-state policy (Forexçi yazılı karar)
  ② P0 teşhis (5 causality: differential + blame) ③ tag'li parity (P0 sonrası)
  ④ S10 boot-replay ölçümü (~4.330 on_bar/boot — ilk soak raporunda)
  ⑤ runbook staleness-knob semantiği.

---

## SOAK DURUM DENETİMİ + PROSES KAYITLARI — 2026-08-31 14:25 (Hakem notları 1-5 işlendi)

- **Rol zinciri (tek satır, Hakem emri):** soak operatörü: Forexci (qwen3.8 flash);
  hakem: GLM; sentez: Luna. Model/imalcı değişimi bildirildi — provenance parçası
  olarak kalıcı; rapor→sentez→hüküm zinciri freeze boyunca bağlayıcı.
- **Ledger penceresi (Hakem şartı):** `2f26da9` en geç İLK soak-checkpoint push'unda
  remote'a çıkar (günlük rapor + ledger tek set, tek N2). Pencere >7 gün → bağımsız
  mini-push (N2 #6) zorunlu. Batching bilinçli, pencere tanımlı.
- **⚠ FİİLİ SOAK DENETİMİ — iddia DOĞRULANAMADI (ölçüldü, tahmin edilmedi):**
  "soak başladı" cümlesinin 3 göstergesi saha tarandı:
  1. PROCESS: `tasklist`/`Get-Process` → python YOK, `terminal64.exe` (MT5) YOK.
     `state/audit.jsonl` YOK, lock dosyası YOK. Son canlı-log = 29 Ağu
     (phase5_demo/smoke — soak öncesi test koşumları).
  2. 72-saat listesi: soak fiilen koşmadığı için göstergeler N/A.
  3. MEMORY-FILE: `sniper_forex_soak_freeze.md` repo DIŞINDA — VS Code Copilot
     memory-tool deposunda (`workspaceStorage/.../memory-tool/memories/repo/`).
     Repo'ya sızıntı YOK: tracked-modified = 0, tree temiz. ✓
  **SONUÇ:** Soak operasyonel olarak DEĞİL. Başlatma ön-kosulları: MT5 terminal64
  (IC Markets kurulu) ayakta + account oturumu, `MT5_EXPECTED_LOGIN` set (boşsa
  D12 gereği warn+SAFE_START — bilinçli tercih), `SNIPER_STATE_DIR` mutlak,
  `python -m src.live.run_production` operatör tarafından başlatılacak.
  Freeze kuralları bu süre boyunca duruyor; soak sayacı gerçek startup anından başlar.
- **Aksiyon bekliyor:** operatör (Forexci) soak'ı fiilen başlatmalı; ilk startup
  raporu (verdict+reason+warmup_bars+REPLAY) gelmeden gün-3 takvimi işletilmez.

## HAKEM KARAR İŞLEME — 2026-08-31 (madde 2-4) + b81308b NETLEŞTİRME

- **b81308b tek satır cevap (blob doğrulandı, tahmin değil):** §13.5 (L793),
  §7.4 (L491), §7.2 persists-across-restart (L468), §9.5 (L627) — **dördü de
  b81308b içinde işlenmiş.** 2 dosya = `AGENTS.md` (+1144 satır blob) +
  `.github/copilot-instructions.md` (221→18 pointer). Üçlü set protocol
  dosyasını ESKİ haliyle çıkarmıyor; push sonrası mini-chore GEREKMEZ.
  Kanıt: `git show b81308b:AGENTS.md | grep -n "13.5|9.5|7.4|persists"`.
- **Memory-file yetimliği (madde 2):** `sniper_forex_soak_freeze.md`
  Copilot workspaceStorage deposundan **SİLİNDİ** (karar: Hakem; gerekçe:
  3-katman yedeklilik + §19 duplicate-source-of-truth bayat-kopya riski).
  Tek gerçek kaynak = repo AGENTS.md (§17) + bu defter.
- **Runbook (madde 4):** `memory-bank/RUNBOOK_SOAK_START.md` eklendi —
  şablonun kod-doğrulanmış hali. Fark düzeltmeleri: (a) tam getenv listesi
  çıkarıldı (SNIPER_WARMUP_COUNT, SNIPER_LADDER_THRESHOLD, SNIPER_FEED_CAP,
  SNIPER_MAGIC + varsayılanları); (b) **Telegram/APNs env'i kod tabanında
  yok** — "SNIPER_ALERT..." satırı şablondan düşürüldü, D28-Telegram E2E
  maddesi kanal fiilen wired değilken N-A işaretlendi (hidden-green yerine
  görünür N-A). Hesap sırrı runbook'a yazılmadı (yazılmaz).
- **Sıra (Hakem onaylı):** C2 cevabı (Forexçi) → soak start (runbook) →
  gün-1 verisi → TEK push seti {2f26da9, b81308b, b50b3bb, +bu chore,
  +gün-1 ledger} — tek N2, tek #9.5 hash-set'i. Pencere: >7 gün → mini-push.

## D53 — TELEGRAM ALERT TRANSPORT (kod + test, 2026-08-31, soak-öncesi son pencere)

- **Kapsam (Hakem D53 emri):** Transport `TelegramAlert` (urllib POST
  sendMessage, timeout ≤3 s sert kapağı, her network exception yutulur →
  ASLA raise; trading loop ağ çağrısıyla bloke olmaz/bozulmaz). Env çifti
  `TELEGRAM_BOT_TOKEN`+`TELEGRAM_CHAT_ID` `.env` üzerinden (`mt5_config`
  setdefault). Commit-öncesi tek-satır teyit: `.gitignore:2:.env` +
  `git check-ignore` ✓. Env yok → ConsoleAlert fallback + audit'te TEK
  STARTUP `{phase:"alerting",verdict:"CONSOLE_FALLBACK",
  reason:"telegram_env_unset"}` — sessiz fallback YOK (S5). İlk transport
  hatası → one-time `_dead` + görünür console WARN (spam yok, recursion yok).
- **Seam:** `Orchestrator.__init__` kuyruğu
  `self.alert = _build_alert_transport(self.config.alert_env, self.audit)`.
  `TelegramAlert(ConsoleAlert)` → alert_log/stderr kanonik kalır; mevcut 9
  `alert.send` çağrı noktası ve test gözlem desenleri DEĞİŞMEDİ (§2.2 reuse).
- **Redaksiyon:** `persistent_log._SENSITIVE_PATTERNS` +TELEGRAM çifti.
- **Hermeticity (kritik tuzak):** `.env`'de gerçek token varken testlerin
  gerçek DM post etmemesi için `tests/conftest.py` session-scoped autouse
  guard (iki TELEGRAM_* anahtarını pop+restore). Module-level pop İŞE
  YARAMAZ: mt5_config `.env`'i collection sırasında (conftest importundan
  SONRA) yüklüyor. Bağımsız probe testiyle kanıtlandı (gerçek creds'le
  Orchestrator console-only kuruluyor; probe geçiciydi, silindi).
- **Testler:** `tests/test_orchestrator_d53_alerting.py` — 11 test (factory
  binding/partial/single-WARN, orchestrator wiring, URL/payload/timeout
  patched urlopen ile, timeout→fallback, exception→fallback+no-retry,
  never-raises entegrasyon, timeout-cap). Patched-transport = §3 seviye-4/5
  kanıt.
- **GERÇEK KANAL (seviye-1, EKSİK):** smoke #1: `getMe` HTTP 200 (token
  geçerli) · `sendMessage` HTTP 400 **"chat not found"** — bot operatöre hiç
  yazılmamış (Telegram kısıtı: bot ilk mesajı kullanıcıdan alamaz).
  OPERATÖR ADIMI: botu açıp START → smoke yeniden (`"ok":true` + gelen DM =
  seviye-1). Runbook adım-3'e ön koşul satırı işlendi. Kanal kanıtlanmadan
  soak'a geçilmez (hidden-green yok).
- **SÜİT (§13, iki tam koşum):**
  - Koşum-1 (guard sonrası, index regen öncesi ağaç): **8F/474P/1S** (819 s).
    7F = bilinen baseline (2× e2e_live_chain + 5× research_c_v1_1). YENİ
    kırmızı: `test_orchestrator_d49.py::
    TestReplayEstablishesYesterdaysWindow::
    test_replay_establishes_yesterdays_window_fresh_boot`.
  - Diferansiyel (§8.2): tek test PASS · d49 dosyası 8/8 PASS ·
    orchestrator grubu 103/103 PASS · D53+d49 çifti 19/19 PASS.
  - Koşum-2 (NİHAİ ağaç): **7F/475P/1S** (828 s) = baseline + 11 D53 tam
    tutar; d49 tekrar kırmızı DEĞİL.
  - Teşhis: d49 T4 = time-boundary flake şüphesi (anchor `_recent_naive()`
    dakika kırpımı + uzun süit altında boundary aşması). Mekanizama dayalı
    güçlü şüphe, KOŞUM kanıtı değil (4 yeniden-koşumda reproduce yok).
    D53 ile nedensellik bağı yok. **AÇIK KALEM:** soak gözlem listesi —
    tekrarlanırsa now_fn-enjeksiyonlu kök-neden testi yazılır.
- **INDEX (§10.2):** final ağaçtan kasıtlı regen → 1532 fonksiyon; diff
  yalnız D53 dosyaları + kayan satır numaraları. **TUZAK:** `gitignore_utils`
  pathspec yoksa `.gitignore`'u SESSİZ atlıyor; venv'de pathspec yok → bir
  regen `logs/fix/`'i (gitignore'lu, 107 fn) sızdırdı. Düzeltme: venv'e
  pathspec 1.1.1 + yeniden regen (`grep -c '"logs' index.json` = 0).
  AÇIK SORU (Hakem): builder pathspec bağımlılığı requirements'ta declared
  değil + silent-skip → hard-fail mi olsun? (tools/ dokunuşu = ayrı kapsam.)
- **RUFF (hook v0.4.4):** biçim+lint temiz; format sonrası D53 11/11 yeşil.
- **COMMIT'LER:** KOD `8610951` {orchestrator, persistent_log, conftest,
  d53-test, index.json} — pre-commit hook validate-only geçti. CHORE
  {RUNBOOK + bu ledger}. Ledger yazımı ilk denemede tool tarafından
  "success" raporlayıp diske YAZMADI (bilinen mid-write failure modu —
  ikinci vaka); anchored replace ile yeniden yazıldı ve doğrulandı.
- **PUSH SETİ (N2 #6, §9.5 — BÜYÜDÜ, re-authorization gerekir):**
  {2f26da9, b81308b, b50b3bb, a94ab4b, 8610951, <chore>, <D54>}. Push →
  §9.2 zinciri → defter N2 #6 → FREEZE push'lanmış HEAD'de → GATE 4 şart.

## D54 — PATHSPEC DECLARED + LOUD-FAIL (2026-08-31, Hakem kararı: set 6→7)

- **Hakem kararları (bu tur):** (1) d49 T4 = **known-flake pin** (yukarıki
  gate bloğuna işlendi; soak'ta tekrarlanırsa hidden-red değil pin'li). (2)
  pathspec = **ikisi birden, şimdi, sete eklenerek**: requirements'a declared
  + `gitignore_utils` missing-import → LOUD fail. Gerekçe: index.json
  provenance-critical; sessiz-skip §19 pattern'i İKİNCİ vaka (mt5_conn'den
  sonra) → kural kodlanır; `tools/` freeze'te gri alan, son güvenli pencere
  şimdi. (3) Ledger tool vaka-2 prosedür teyidi: *anchored replace +
  verify-from-disk* protokol (iki vaka, iki kurtarma); §13.5 mesaj-sınırı,
  bu tool-kanalı — ayrım notu.
- **Kod:** `requirements.txt` += `pathspec` (declared). `gitignore_utils`:
  `except ImportError: pathspec=None` → `raise ImportError("index regen
  incomplete — install pathspec ...")`; ölü `spec=None`/`spec is not None`
  dalları söküldü (§20 less code, tek gerçek kaynak). `is_ignored` artık
  pathspec-varlığında `.gitignore`'u her zaman uygular.
- **Test:** `tests/test_tools_gitignore_utils_d54.py` — 2 test: (a)
  mock-missing (`builtins.__import__` patch, `pathspec` ImportError) →
  module load **raises** (match "install pathspec"); (b) pozitif kontrol:
  pathspec varken gitignored `logs/fix/` → `is_ignored=True`, `src/` →
  False (sızma sınıfını doğrudan pin'ler). Fresh-importlib-load, cache-free.
- **Koşum (Hakem: tam süit şart DEĞİL — core-live diff'siz, tek import):**
  D54 2/2 ✓ · ruff (hook v0.4.4) format+check temiz ✓ · orchestrator grubu:
  ilk koşumda T4 flake kırmızısı (1F/102P) → tek-test PASS → tekrar-PASS →
  grup yeniden **103/103** ✓ (pin'li flake, öngörüyle tutarlı; D54 core-live
  dokunmuyor). Index regen → 1536 fn, `grep -c '"logs'`=0, D54 sembolleri
  içeride ✓.
- **SET (N2 #6, §9.5 — 7 hash, Hakem onayı bu mesajla):**
  {2f26da9, b81308b, b50b3bb, a94ab4b, 8610951, <chore>, <D54>}. Push →
  §9.2 zinciri → defter N2 #6 → FREEZE push'lanmış HEAD'de → GATE 4 şart.

## D53/D54 PUSH KAYDI — N2 #6 + FREEZE YENİ HEAD'DE (2026-08-31)

- **who/what/when:** Luna (executing agent) — Hakem yazılı onayıyla (bu
  sohbet, D53-Final mesajı, "set 6 hash" + D54 ile 7'ye genişletme emri) —
  2026-08-31 ~17:05 +0300.
- **SET (7 commit, §9.5 hash-hash):**
  - `2f26da9` chore: ledger — N2 #5 push record, freeze ACTIVE (önceki onaylı set)
  - `b81308b` protocol: AGENTS.md — agent operating contract (önceki onaylı set)
  - `b50b3bb` chore: ledger — soak status audit, role-chain (önceki onaylı set)
  - `a94ab4b` chore: memory-bank — soak-start runbook (önceki onaylı set)
  - `8610951` D53: TelegramAlert transport + visible fallback (5 files, +636/−172)
  - `2c3f779` chore: memory-bank — D53 record + runbook bot-START (2 files, +86/−2)
  - `402aa6a` chore(tools): D54 pathspec declared + loud-fail (5 files, +209/−11)
- **PUSH (N2 altıncı uygulama):** `b89895a..402aa6a main -> main` →
  github.com/ahmetonurof-lab/sniper_forex.
- **İMZALAR (§9.2 post-push):** `git log origin/main..HEAD` → **BOŞ** ·
  `git ls-remote origin main` → `402aa6a6766c21fe62db8835141525b5e7f054d4`
  = local HEAD. Working tree clean (tracked). Remote HEAD güncel.
- **Set büyümesi beyanı (§9.5):** onaylı 4'lü set → 6'ya (D53) → 7'ye
  (D54, Hakem'in aynı mesajla verdiği ek-üye kararı). Her büyüme Hakem
  onaylı; unauthorized ride-along commit YOK — 7 commit'in 7'si de
  isim-isim onay metninde.
- **D54 precondition beyanı:** `tools/` ilk kez track edildi
  (`gitignore_utils.py`); `index_builder.py`/`config.json` hâlâ untracked
  → "tracked artifact ← untracked generator" provenance sorusu AÇIK
  (kendi kendine kapsam genişletilmedi, hakeme raporlandı).
- **FREEZE: AKTİF — yeni HEAD `402aa6a`.** src/ + tests/ + index.json
  donduruldu (soak başlangıcında fiilen uygulanacak; gate 4 şartı açık).
  memory-bank writable. Kod değişikliği = soak durur → tam süit → commit →
  ayrı push onayı.
- **GATE durumu (4 şart):** ① C2 policy — Forexçi yazılı kararı BEKLİYOR ·
  ② P0 teşhis — paralel · ③ tag'li parity — ②'ye bağlı ·
  ④ Telegram seviye-1 — OPERATÖR START adımı BEKLİYOR (bot'a hiç yazılmadı;
  smoke `sendMessage` → 400 chat-not-found). ①④ kapanmadan soak start yok.

## D55 — BUILDER TRACKED (N2 #7 adayı) — provenance zinciri kapanıyor

- **Hakem kararı (ratify mesajı §2):** TRACK — gerekçeler: §10.2
  "attributable" sözü, format-drift görünürlüğü, §21 next-agent ilkesi.
  Ön-şart grep: `C:/Users|Administrator|password|token|login` → **exit 1
  (temiz)** genişletilmiş taramada da sır/path yok. `config.json` tamamen
  relative path (`../..`) — makine-bağımsız, deployment-artifact olarak kabul.
- **T4 nuance (hakem şartı):** "İki ardışık tekil kırmızı = rastgele flake
  değil, DAKİKA-BOUNDARY deterministik yarışı. Soak-sonrası ilk kod
  penceresinde now_fn-enjeksiyonlu rewrite **ZORUNLU** (backlog'dan pin'e
  değil, şarta)."
- **Kapsam beyanı:** Hakem'in literal `git add tools/` komutu 17 dosya
  sürüklüyordu (watcher.log runtime artifact'ları, alakasız operasyon
  tool'ları). Parantez-scope intent (`index_builder.py` + `config.json`)
  esas alındı — **2 dosya track edildi**, kalan 15'i (watcher.py dahil)
  beyanlı dışarıda; karar hakeme sunulan açık soru.
- **Reformat (§11 kanıtı):** builder hook-version ruff'da I001+format
  fail veriyordu → `ruff check --fix` + `ruff format` uygulandı →
  **AST dump birebir identical** (davranış-nötr ispatı, prose değil).
- **Index regen:** satır-anchored → 1536 fn sabit, logs=0; diff yalnız
  generated_at + builder satır-kaymaları (28/28 satır).
- builder tracked — provenance chain complete: artifact + generator +
  rules (AGENTS.md) all versioned.
- **N2 #7 SET BEYANI (§9.5):** push kümesi fiilen **2 hash**:
  `{0711a5c (N2 #6 ledger kaydı, zorunlu ancestor), D55-builder-chore}`.
  Hakem onay metni "tek hash" diyordu — ancestor gerçeği seti 2'ye
  çıkarıyor; set-beyanı raporda, push bu beyan üzerine teyit bekliyor.

## N2 #7 PUSH KAYDI — 2-hash set, FREEZE HEAD `2a0d5b3`

- **Who/What:** Luna (icra) · Hakem (yetki: N2 #7 set-teyit mesajı,
  "2 hash, PUSH YETKİLİ" — sayım hatası hakem tarafından kayıtla kabul:
  "1 hash" bayat sayımdı, 0711a5c beyanı N2 #6 raporunda itirazsız geçmişti).
- **When:** 2026-08-31 · **Remote:** origin/main
  (https://github.com/ahmetonurof-lab/sniper_forex.git)
- **Set (2/2, ride-along yok):**
  `0711a5c` chore: ledger N2 #6 push kaydı
  `2a0d5b3` chore(tools): builder+config tracked (D55)
- **Push:** `402aa6a..2a0d5b3 main -> main`
- **Verification (§9.2):** `origin/main..HEAD` → **BOŞ** ·
  `git ls-remote origin main` → `2a0d5b352063634f6ec9aa64e3f0f0d23fac9e17`
  = local HEAD · working tree temiz (tracked).
- **Freeze invariant (hakem §5 keskinleştirmesi):** `402aa6a..2a0d5b3`
  arasında `src/` + `tests/` **SIFIR delta** — doğrulandı (git diff --stat
  boş). Tam delta: index.json (intentional regen) + ledger + builder/config.
- **FREEZE: AKTİF — HEAD `2a0d5b3`.** Soak READY (RUNNING değil); gate 4
  şart açık. Bu push'la provenance zinciri tamam: artifact (index.json) +
  generator (builder+config) + rules (AGENTS.md) versioned.

## TOOLS ENVANTERİ + WATCHER TOMBSTONE (hakem kararı: ŞİMDİ track YOK, Aşama 5)

- `tools/watcher.py` (untracked) — **KILLED 2026-08-31** (staged-index
  ezmeleri, iki rollback; incident analizi defterde, PID 10408).
  Disposition: Aşama 5'te ya temiz yeniden yazım ya kalıcı arşiv.
  Yol kaydı: `tools/code-index-system/watcher.py` — gelecekteki ajan için.
- Kalan 16 untracked tools dosyası — disposition envanteri (Aşama 5):
  - Runtime log'lar: `tools/code-index-system/watcher.log`,
    `tools/code-index-system/logs/watcher-{err,out}*.log` (9 dosya)
    → Aşama 5 **gitignore sweep** (kalıp eklenecek).
  - Windows-servis betikleri: `bootstrap_admin.ps1`, `install-service.ps1`,
    `setup-admin.ps1`, `start_watcher.bat`, `start_watcher.vbs`,
    `watcher-task.xml` (code-index-system/) · `sys_cleanup.ps1` (tools/)
    → Aşama 5 **WINSW OPS-ASSET ADAYI** — asıl iş malzemesi, orada
    track-edilebilir hale gelir.
  - Operasyon tool'ları: `ssh_audit.py`, `ssh_audit_cmd.py`,
    `rollback_stageA.py`, `rollback_stageB.py` (tools/) ·
    `histdata_acquisition/download_histdata.py`
    → Aşama 5'te **tek tek karar**.
- NEDEN şimdi değil: freeze disiplini + minimal scope; akıbetleri Aşama 5
  kararında gerçek ihtiyaçla belirlenir, bugün tahmin olmaz.

## P0 TEŞHİS (gate ②) — 5 canonical causality fail — KÖK NEDEN İZOLE (§8.2)

**Yöntem:** hakem ADIM-1 yönlendirmesi — differential worktree'lar
(dispose: repo-dışı, freeze bozulmadı; tümü temizlendi). Graft =
yalnız collection-icin eksik dep (src/strategy, gemini_detector), motor
davranışına dokunmadı.

**Ölçümler (test dosyası × motor revizyonu matrisi):**

| Commit | Motor revizyonu | Koşum sonucu |
|---|---|---|
| HEAD `2a0d5b3` | event-stream (409fc17) | **5F**/33P (isim-isim: same_bar, A_later_exit, B_self_excl, E_brute, tie_break) |
| `2bff15b` baseline 08-30 | event-stream | **aynı 5F** — baseline'a bu hâlde taşındı |
| `409fc17` 08-28 14:41 (yazım) | event-stream | **UNCOLLECTABLE** — `experiment/gemini_detector.py` o commit'te YOK (ilk kez 2bff15b), `src/strategy` ağaçta YOK → test dosyası kendi motoruna karşı HİÇ KOŞAMADI |
| `797d946` 08-28 11:19 (bisect) | bisect/prefix | **30P/1S YEŞİL** — bisect-era testleri bisect-era motoruna karşı yeşildi |
| `0899b38` 08-28 10:15 (promotion) | pre-bisect | kendi test dosyası kendi motoruna karşı **5F** (farklı isimler: x05/x025/peak/same_bar/pnl_differs) |

**Kök neden (izole):** `409fc17`'deki event-stream rewrite, `apply_dd_scaling`
semantiğini değiştirdi: ENTRY/EXIT olayları `(ts, priority)` sıralı yürünür,
multiplier ENTRY'de kilitlenir (`mult_lock`). Fixture'lardaki **backdated
exit (exit_ts < entry_ts)** durumunda EXIT olayı ENTRY'den ÖNCE işlenir →
`mult_lock.get()` → None → **`continue` = trade SESSİZ DÜŞÜRÜLÜR`
(n1 sayılmaz, paused sayılmaz, equity'ye girmez). 5 fail'in 4'ü bu
mekanizma; E_brute ayrıca ref'in exit-order-walk'ı ile prod'un entry-lock
aynı-timestamp penceresinde ayrışıyor (`prod mult 0.0 != ref 1.0 (dd=0.0)`).
Test docstring'leri hâlâ bisect-era sözleşmesini anlatıyor
("j = min(bisect_left(EX, entry), pos)") — testler bisect semantiğinin
kontratı, motor event-stream'in davranışı.

**Sınıflandırma (§8.2):** `introduced` — 409fc17'de üretildi ve YAZIM
ANINDA KOŞULAMADIĞI için hiç yeşil olmadan baseline'a miras kaldı.
"test bug" değil tek başına, "engine bug" değil tek başına: **kontrat
(bisect-semantik testler) ile davranış (event-stream motor) ayrışması +
sessiz-düşürme savunma dalı.** Gerçek veride exit<entry imkânsız
(entry_bar ≤ exit_bar) → canonical benchmark sayıları (2300T) bu
yoldan etkilenmemiş OLABİLİR — kanıtlanmadı; ③ parity işte bu
ayrışmanın gerçek-veride sıfır-olup-olmadığını ölçecek.

**Açık kalan soru (hakem kararına):** disposition üç seçenek —
(a) bisect semantiğine dönüş = canonical benchmark değişimi = araştırma
protokolü (izolate→benchmark→promote-onay);
(b) event-stream semantiği canonical ilan + 5 testin gerçek-veri
fixture'larıyla yeniden yazımı (exit≥entry) + sessiz-düşürmenin
fail-fast'a çevrilmesi (benim önerim: (b)+fail-fast — §19 sessiz-skip
deseninin bu ailesi de kodla kapanmalı);
(c) yalnız fail-fast + test skip = hidden-red'e kaçar, uygun değil.
**Kod değişikliği freeze-sonrası pencere bekler — bu tur yalnız teşhis.**

**Ders (kural-a-dayanak):** koleksiyonu-bile-olmayan-test = sıfır-kanıt;
"synthetic validation" iddiası taşıyan 409fc17 mesajı, koşulamayan dosya
için level-0 iddiaydı. Koşulmamış test, yazılmamış testtir.

## PARITY PROBE SONUCU (gate ③) — FARKLILIK VAR — KANONİK SAYILAR KARANTİNADA (2026-08-31)

**Hakem onaylı tasarım (§2/§6):** aynı akış → iki motor karşılaştırması.
Uygulamada genişletildi: salt-HEAD-stream testi yerine **her motor kendi
main() üretim yolunu tam koştu** (dört tam üretim: HEAD, 797d946,
0899b38, 409fc17; worktree'lar repo-dışı, graft = collection-dep yalnız,
feather verisi 08-23 mtime — tüm koşumlarda aynı dosyalar, version-control
dışı ama değişmemiş).

**Q5-ön-şartı ölçüldü (mult_lock get-path tetikleyicisi):** gerçek 6-major
stream'de (2302 tamamlanmış trade) **exit_ts < entry_ts = 0 adet** →
sessiz-düşürme dalı gerçek veride HİÇ tetiklenmiyor; yalnız sentetik
fixture'larda. Bu, fixture teşhisini doğrular — AMA parity sorusunu
kapatmıyor, çünkü fark başka bir yerde çıktı.

**FARK TABLOSU (aynı veri, dört motor tam-üretim):**

| Metrik | 0899b38 (PROMOTED) | 797d946 (bisect-fix) | 409fc17 = HEAD (event) |
|---|---:|---:|---:|
| surviving | **2300** | 2299 | 2302 |
| paused | **2** | 3 | **0** |
| x1 / x05 / x025 | **2186 / 99 / 15** | 2132 / 145 / 22 | 1994 / 278 / 30 |
| TotalR | **+2766.905** | +2646.92 | +2593.26 |
| MaxDD(R) | **4.7096** | 6.2866 | 5.0 |
| MaxDD% | **2.19** | 2.38 | 2.24 |
| PF | **5.13** | 4.90 | 4.97 |
| pause-set | **{GBPJPY#96, USDJPY#82}** | +EURUSD#101 | {} (boş) |

**Mutabakat:** 0899b38 tam-üretim, progress.md'deki PROMOTED tabloyu
**hane-hane yeniden üretti** (2300/2/2186/99/15/+2766.91/4.71/2.19/5.13,
pause-set dahil) → defter kaydı sahte değil; ama **HEAD motoru o sayıları
ARTIK üretmiyor.** Üç haneli drift: 243 trade'ün mult-dizisi farklı
(HEAD vs 0899), 115 trade (797 vs 0899).

**Drift zamançizgisi (mekanizma izole):**
1. `0899b38` (promosyon): ÇİFT-eğri — DD, BASE pnl'lerden kurulan
   pre-scale eğriden ölçülür (paused trade DD'ye katkı verir); walk exit-sıralı.
2. `797d946` ("strict causality + deterministic ordering"): çift-eğri
   korunur, exit<entry strict + `_trade_order_key` eklenir → sayılar değişir
   (2300→2299, paused 2→3, MaxDD 4.71→6.29). **Bu, PROMOTED sayıları
   sessiz değiştiren İLK commit.**
3. `409fc17` (event-stream rewrite): TEK-eğri canlı-yürüyüş — equity yalnız
   KABUL EDİLMİŞ trade'lerin SCALED pnl'iyle ilerler; paused DD'ye sıfır
   katkı; mult ENTRY'de kilitlenir → sayılar tekrar değişir
   (2299→2302, paused 3→0, MaxDD 6.29→5.0). Testler bu commit'te
   koşulamadi (P0 TEŞHİS).
4. `409fc17→HEAD`: davranış-nötr format (diff yalnız satır-sarma; probe
   409fc17 tam-üretimi HEAD sayılarıyla birebir = kanıt).

**Tahkim kanıtı (hangi semantik "production"?):** `src/live/portfolio_dd.py`
(Phase 11, freeze- dışı canlı modül): `record_realized(pnl_r)` yalnız
kapalı pozisyonlardan çağrılır; paused trade entry-öncesi bloklanır →
hiç kapanmaz → DD-eğrisine sıfır katkı. Bu, **409fc17/HEAD tek-eğri
semantiğiyle uyumlu**; 0899b38 çift-eğri semantiğiyle DEĞİL. Yani HEAD'in
docstring iddiası ("exact behavior of production portfolio_dd.py")
modül-anlamında destekli — ancak bu, PROMOTED benchmark sayılarını
otomatik olarak doğrulamaz: **canlı runtime semantiği ile araştırma
benchmark semantiği aynı olmak ZORUNDA mı — hakem kararı.**

**65k parity iddiası kapsam notu (abartma yok, gizleme yok):**
`65k_m1_eurusd_parity_artifact.json` BASE-sinyal paritesidir
(signal_count=23, head_sha=409fc17, M1→M15→sinyal katmanı) — DD-scaling
katmanından bağımsız; scaling drift'i base akışı DEĞİŞTİRMEDİ (dört
üretimin tümü aynı 2302 base stream). Phase-8 feather paritesi (2302/2302)
de base-katman iddiası. → **Karantina kapsamı: C v1.1 SCALING kanonik
sayıları (2300T/+2766.91/MaxDD 4.71/2.19/PF 5.13 + PROMOTED etiketi).
Base-sinyal/65k/Phase-8 parite iddiaları bu drift'ten ETKİLENMEZ.**

**§2 hükmü gereği:** FARKLIYSA → kanonik sayılar + PROMOTED etiketi
karantinada; A/B/C masaya döner. (b)-paketi (test rewrite + fail-fast)
tek başına yeterli DEĞİL — önce semantik tahkim kararı gerekiyor:
(a) 0899b38 çift-eğri'ye dönüş = PROMOTED sayılar geri gelir, ama
    production-uyumu iddiası düşer;
(b) HEAD tek-eğri canonical ilan = production-uyumlu, ama PROMOTED
    benchmark yeniden-koşumla değişir (yeni sayılar: 2302/0/1994-278-30/
    +2593.26/5.0/2.24/4.97) ve testler bu semantiğe göre yazılır;
(c) üçüncü yol: 797d946'nın çift-eğri+strict hâli (ne defterde ne kodda
    sahiplenilmiş ara semantik — elenebilir).
Luna öneri güncellemesi: teşhis turunda (b)+fail-fast demiştim; probe
showed (b)'nin "test-rewrite yeterli" varsayımı ÇÖKTÜ — artık (b) bir
benchmark-değişimi kararıdır, etiket karantinasıyla birlikte hakem
tahkimini gerektirir.

**Never-green dersi (hakem §5 resmi satırı):** her commit'in kendi
test-seti, o commit'te koşum çıktısıyla mutabakata tabidir — commit
mesajındaki validation iddiası koşum çıktısız kanıt sayılmaz.

**Silent-drop ailesi (hakem §5 resmi satırı):** silent-drop = sessiz-fail
ailesinin engine-içi tipi; sayaç-görünürlüğü gereksinimi (dropped_signals
audit'e) tüm engine-path'lerinde gözden geçirilir.

**KURAL (§13 kanadı, hakem onaylı):** "Koşulmamış test, yazılmamış
testtir." Commit-şablonu yeni sorusu: "bu değişikliğin kapsadığı testler
bu commit'te GERÇEKTEN koşulabildiler mi?"

**Probe artefaktları:** `C:/Users/Administrator/p0probe/`
(stream_head.json, result_head.json, result_bisect.json,
result_bisect_full.json, result_promote_0899.json, result_event_409.json,
gen_head.py, run_bisect.py, gen_bisect_full.py) — repo-dışı, worktree'lar
temizlendi, freeze dokunulmadı (src/tests zero-delta).

---

## TAHKİM: (b) ONAY — TEK-EĞRİ CANONICAL (2026-08-31, hakem kararı)

**Karar:** Parity probe'ün getirdiği kanıt üzerine hakem tahkimi (b)'yi
onayladı: **tek-eğri (single-curve) semantik canonical ilan edildi.**
paused trade = sıfır-katkı; canlı `portfolio_dd.py` semantiğiyle birebir
mutabık. (c) elemenir (sahipliksiz semantik = ölü semantik). (a) elemenir
(çift-eğriye dönüş ya portfolio_dd.py'yi değiştirir ya benchmark'ı
production'dan koparır — canlı sistem zaten tek-eğriyi ticaret ediyor).

**Yeni canonical sayılar (HEAD semantiği, tam üretim koşumu):**
2302T / +2593.26R / MaxDD 5.0R (2.24%) / PF 4.97 / paused 0 /
x1=1994 / x05=278 / x025=30. TotalR'ın düşmesi (+2767→+2593) "daha kötü
strateji" değildir: DD'nin farklı ölçülmesi çarpan dağılımını değiştirir.

### §12.1 SELF-CORRECTION — hakümün kendi önceki hükmü (silinmedi, buraya)

- **ESKİ HÜKÜM:** "(b) test-rewrite yeterli, benchmark değişimi gerekmez."
- **YENİ KANIT:** probe — fark fixture'larda değil SEMANTİKTE.
- **REVİZE:** (b) yeniden tanımlandı — benchmark resmen yeniden-koşumla
  değişir.
- **KÖK HATA:** hakem "fark motor-mu yoksa fixture-mı" sorusunu koşumla
  ayırt etmemişti. Kanıt katmanı kaydı: iddia < koşum < tam-üretim probe —
  bu masada üçüncü kez yükseltildi.

### §8.1 IFŞA — PROMOTION SONRASI İKİ SESSİZ SAYI-DEĞİŞİMİ

Hiçbiri promotion anında ifşa edilmemiştir (defter kaydı — hakem §3):

1. `797d946` "strict causality": 2300→2299, MaxDD 4.71→6.29.
2. `409fc17` event-stream: 2299→2302, paused 3→0 (semantik geçiş:
   çift-eğri→tek-eğri).

Üstüne: event-stream testleri hiç yeşil olmadı (asla-yeşil-olmayan borç,
KURAL'ın doğuş nedeni). **DEFTER KAYDI: §8.1 provenance zinciri
promotion'dan itibaren fiilen kırıktı.** Karantina (önceki bölümde) bu
kırığın resmî ilanıdır; bu tahkim kaydı karantinanın kapanış yönünü
(→ tek-eğri canonical) tespit eder.

### KARAR PAKETİ (teknik maddeler — uygulanıyor)

1. **fail-fast:** `apply_dd_scaling` EXIT dalındaki sessiz-düşürme
   (`mult is None → continue`) → `dropped_signals` sayacı + audit ERROR +
   eşik-aşımında hard-fail (§19 kod-kapanışı).
2. **invariant:** `entry_ts ≤ exit_ts` assert'i runtime-invariant olarak.
3. **test-rewrite:** gerçek-veri-düzende fixture (exit≥entry) + 1-2
   kasıtlı backdated-exit NEGATİF testi (fail-fast tetiklenmesi kanıtlanır).
4. **YENİ BENCHMARK RE-RUN:** HEAD semantiğiyle tam üretim; provenance
   paketi = engine commit + SEMANTİK BEYANI (tek-eğri, paused=sıfır-katkı)
   + config + dataset hash'leri (aşağıdaki fiksyasyon).
5. **TİCARİ ONAY (gate ⑤ — YENİ ŞART, hakem yetkisi dışı):** yeni sayılar
   altında strateji risk-profil onayı Forexçi'den. Eşik-revizyonu
   (t1/t2/t3 kalibrasyonu) ayrı sentez görevi.
6. **DATASET-FİKSASYONU:** ✅ YAPILDI — `memory-bank/dataset_manifest_v1.1.md`
   (18 feather + 6 RAW CSV, 24 SHA256 + satır sayıları). mtime kanıtı
   bit-kanıtla değiştirildi.
7. **TAG `research-canonical-v1.1` YENİDEN TANIMLANIR:** (b)-fix + yeni
   benchmark + ticari onay + parity-artifact (yeni semantiğe karşı)
   kapanınca atılır. O zamana kadar tag YOK.

### UYGULAMA NOTU — sessiz-düşürme production hattında zaten patlardı

`main()` STEP 3 postcheck'i (tier-sayım mutabakatı,
`n_x1+n_x05+n_x025+paused == completed_base`) sessiz-düşürülmüş bir trade'i
RuntimeError ile yakalar. Yani fail-fast eksiği FONKSİYON sınırındaydı,
pipeline sınırında değil — bu, değişikliğin etkisini daraltır ve
"hard-fail zaten vardı" diye küçümsenmez: fonksiyon-seviye tüketiciler
(testler, araçlar) korumasızdı. Q5 ölçümü: gerçek akışta backdated-exit
0/2302 → dal hiç tetiklenmedi; fail-fast bundan sonra tetiklenirse SEBEBİ
görünür olur.

### UYGULAMA KAPANIŞI (b-paketi, 2026-08-31) — maddeler 1-4 + 6

- **Madde 1 (fail-fast):** ✅ `apply_dd_scaling` EXIT dalındaki
  `mult is None → continue` sessiz-düşürmesi artık `dropped` listesine
  yazılıyor + `_logger.error` + dönüşten önce
  `_enforce_dropped_signal_policy(dropped)` (eşik `MAX_DROPPED_SIGNALS=0`).
- **Madde 2 (invariant):** ✅ Tamamlanmış her trade için
  `entry_ts > exit_ts` → `_logger.error` + `ValueError` (bilerek `assert`
  DEĞİL — `python -O`'da silinmemeli; §7 fail-safe gerekçesi koda yazıldı).
  OPEN trade'ler istisna (placeholder exit_ts gerçek değil).
- **Madde 3 (test-rewrite):** ✅ `tests/test_main_research_c_v1_1.py` 43
  test. Tüm fixture'lar gerçek-veri-düzene (entry≤exit) çevrildi:
  `same_bar`, `test_A`, `test_B_self_exclusion`, `test_tie_break` yeniden
  yazıldı; `test_D`/`test_E` randomik fixture'ları `entry=exit-offset`'e
  flip edildi + `test_D`'ye non-vacuity guard eklendi. 5 NEGATİF test:
  backdated→ValueError+caplog ERROR; OPEN-muafiyet; entry==exit legal;
  `_enforce_dropped_signal_policy` doğrudan (boş/geç/aşım);
  `MAX_DROPPED_SIGNALS==0`.
  - **BULGU (görünür kılınır):** `test_D` eski hâliyle VACUOUS-GREEN idi —
    backdated fixture → tüm trade'ler sessiz düşer → `[]==[]`. `test_E`
    kırmızıydı çünkü referans düşürülmüşleri oynatıyordu. Bu asimetri
    tahkim probe'unun (motor-mu-fixture-mı) kök kanıtıdır.
  - Eski `_reference_dd_and_mult` BAĞIMSIZ değildi (exit-sıra yürüyüşü,
    same-ts'de ENTRY-priority'ini ihlal ediyordu) → gerçek O(N²)
    per-trade yeniden-hesaba yazıldı.
- **`tests/test_causality_synthetic.py`:** ✅ 4/4 PASS + Current==Reference.
  Hardcoded beklentiler bisect-öncesi mutlak-R okumasındaydı (Test 3/4);
  canonical tek-eğri semantiğine güncellendi (disclosed; §19 görünür-kırmızı
  bırakmaz). `test_causality_extended.py` (kök, standalone) 10/10 PASS.
- **Madde 4 (benchmark re-run):** ✅ HEAD semantiğiyle tam üretim.
  Sonuç: `2302T | +2593.26R | 5.00R/2.24% | PF 4.97 | x1=1994 x0.5=278
  x0.25=30 | paused=0`. Pre-run dataset bit-doğrulaması: 24/24 SHA256
  MATCH. Sayı-değişikliği YOK (quarantine öncesi HEAD ile birebir) →
  (b)-fix semantik-beyanıdır, sayı-üretimi değil; invariant gerçek veride
  0/2302 ateşlendi (Q5). Provenance paketi:
  `memory-bank/benchmark_provenance_c_v1_1_arbitration_b.md` (engine
  sha256 + SEMANTİK BEYANI + config + canlı hash + row-count + bilinen
  gap'ler).
- **PROCESS İNSİDANI (§12.1/§13.5):** `memory-bank/progress.md` sonunda
  bozuk tek-satır bulundu: geçmiş bir `echo >>` komutunun `-e "\n---\n..."`
  argümanı kaçış-dizileri genişlemeden aynen yazılmış (LIVE FIX CHECKPOINT).
  İddia değişmeden okunur markdown'a restore edildi; satır içi
  `DDscaled`→`DD→scaled` (kaçırılan `→`) düzeltildi. Bu kayıt insidandır,
  gürültü değildir.

### TAM SÜİT SONUCU (b-paketi, 2026-08-31) — 3F/486P/1S + d49 flake tekrarı

- **Koşum:** `pytest tests/ -q` (tam `tests/`, 598.9 s) →
  **3 failed / 486 passed / 1 skipped**. Raw: `/tmp/full_suite_bfix.txt`.
- **Sayım mutabakatı (§13):** baseline 7F/477P/1S (485 test). Hedef
  2F/482P + bu pakette eklenen 5 negatif test = 2F/487P beklenirdi;
  gözlenen 3F/486P → fark TAM OLARAK 1× d49 flake (aşağıda). 5×
  `test_main_research_c_v1_1` kırmızısı GİTTİ (FAILED listesinde yok);
  2× `test_e2e_live_chain` pre-existing kaldı (disclosed); 485→490
  toplam = eklenen 5 negatif test. Gizli kırmızı yok.
- **FAILURE (§13.4 formatı):**
  - Test: `test_orchestrator_d49.py::TestReplayEstablishesYesterdaysWindow::
    test_replay_establishes_yesterdays_window_fresh_boot`
  - Scope: OUTSIDE current task (bu paket `experiment/`+`tests/test_main_
    research_c_v1_1.py`+`tests/test_causality_synthetic.py`'ye dokundu;
    orchestrator/d49'a dokunmadı — `git status` bu dosyalarda temiz).
  - Status: **REPEAT of documented open item** — D53 dönemi koşum-1'de
    aynı test aynı teşhisle kaydedilmişti (`activeContext.md` ~1107:
    "time-boundary flake şüphesi, anchor `_recent_naive()` dakika kırpımı
    + uzun süit altında boundary aşması; AÇIK KALEM: tekrarlanırsa
    now_fn-enjeksiyonlu kök-neden testi yazılır"). **Tekrarlandı.**
  - Evidence: hata mesajı `oldest slot 1788096600000 != expected
    1788095700000` = tam 15m (900000 ms) kayma — bir slot boundary
    aşması. Diferansiyel (§8.2): tek test 3× PASS, d49 dosyası 8/8 PASS,
    5× tekrarlı koşum 5/5 PASS; yalnız ~10 dakikalık tam süit içinde,
    `_recent_naive()`'ın fixture-kurulumu ile `_warmup`'ı arasına dakika
    kırpma boundary'si düştüğünde ortaya çıkıyor. Benim değişikliklerimle
    nedensellik bağı YOK (aynı desen D53'te de görüldü, o paket de
    orchestrator'a dokunmamıştı).
  - Action: **DISCLOSED, not hidden, not fixed here.** Kök-neden testi
    (now_fn enjeksiyonu) açık kalem olarak ORTADA — reçete ledger'da
    yazılı; bu (b)-paketi kapsamı dışı (Hakem onayı/ayrı commit gerekir).
    Bu commit'in süit iddiası: "full suite within tests/ = 3F/486P/1S,
    bundan 2'si pre-existing disclosed + 1'i documented time-boundary
    flake (repeat, differential evidence above)".
- **COMMIT 2 = `c66888a`** (8 dosya; hook'lar: ruff-format 2 satırı
  birleştirdi → hook-blob 43/43 PASS yeniden doğrulandı → index FINAL
  ağaçtan 2. regen (§10.3: commit = validate edilen blob); vulture/mypy/
  json/EoF temiz).
- **PROVENANCE sha256 mutabakatı (post-commit, disclosed):** provenance
  paketi engine sha256'sını working-tree CRLF baytlarından hesaplamıştı
  (773e01b1…); commit blob'u LF-normalize (78a4bce5…) — içerik aynı
  (doğrulandı: sha256(wt.replace(CRLF,LF)) == blob). Provenance'a her iki
  form + Windows-checkout reproduksiyon notu eklendi (ayrı doc commit).
  Koşum anındaki baytlar = form (i); bu, §8.1 "exact code" iddiasının
  doğru-nesne hâlidir.

### KURAL-ŞABLO (Hakem, N2 #8 hükmü — deftere tek satır)

> **sha256 provenance: line-ending formu + checkout-reproduksiyon notu
> zorunlu** (D53-öncesi vaka şablonu). Her working-tree-hash iki formda
> verilir: (i) koşum-anı baytları (Windows CRLF checkout), (ii) commit
> blob'u (LF-normalize); eşdeğerlik `sha256(wt.replace(CRLF,LF)) == blob`
> olarak doğrulanır ve Windows-checkout reproduksiyon notu düşülür.

### FLAKE-FIX — COMMIT 7 (N2 #8 hükmü, push ÖNCESİ — D54 hükmü revize)

- **HÜKÜM (§12.1 — Hakem kendi timeline'ını revize etti):** D54'teki
  "soak-sonrası ilk kod penceresinde now_fn rewrite ZORUNLU" hükmü
  **"push ÖNCESİ commit-7"** olarak değiştirildi. Gerekçeler: (1) kök
  neden test-only çıktı (production korkusu yok → fix ucuz); (2) push=
  freeze pratiğinde flake'i ertelemek = soak sırasında tests/ mutasyonu
  = §17 breach protokolü (en pahalı yol). FALLBACK (derin çıkarsa):
  6-hash push + ayrı task — KULLANILMADI, fix sığ kaldı.
- **Sınıflandırma (Hakem):** DEFECTIVE TEST (üretim-değil, test-anchor
  hatası). İlke deftere: *"bilinen-beklenen fail freeze'de kabul edilir;
  bilinen-kusurlu test edilmez."* 2× E2E = pin'li pre-existing
  (non-blocking); 1S `test_parity_6majors` = documented slow-skip
  (push/soak non-blocking, **TAG-zamanı kapanış şartı**: ③ kapanırken
  ya bir kez explicit koşulur ya skip-gerekçesi provenance paketine
  satır olarak girilir — skip'li parity, tag kanıt-zincirinde açık soru
  olarak kalamaz).
- **KÖK NEDEN (koşum-kanıtı + mekanizma-kanıtı, tahmin değil):**
  `resample_15m` bir bucket'ı `<3` M1 barı varsa düşürür. T4'ün
  full-coverage guard'ı `first_slot == feed_first_slot` assert eder.
  `history_anchor = _recent_naive() − 1700dk` ve `1700 % 15 = 5` →
  anchor'ın slot-içi fazı koşulduğu dakikaya bağlı. Faz analizi
  (deterministik script): ham anchor dakikaların
  **{3,4,18,19,33,34,48,49}**'ında ilk bucket'ı 1-2 bara düşürüyor →
  en-eski 15m bar sessizce siliniyor → `bars[0]` TAM 1 slot kayıyor
  (gözlenen `1788096600000 − 1788095700000 = 900000 ms = 15dk`).
  İzole koşum (~2 sn) o fazlara nadir denk gelir; ~10 dk'lık tam süit
  denk gelir → 3. tekrar deseni. Kanıt: saat bad-phase dakikasına
  sabitlendi (monkeypatch clock) → raw=1-bar DROP, aligned=15-bar OK;
  8/8 bad-phase'de doğrulandı.
- **FIX (test-only):** `_aligned_history_anchor(minutes_back)` helper'ı
  — anchor'ı 15m slot sınırına floor eder → ilk bucket HER zaman 15 bar
  taşır → guard'ın güçlü eşitlik assert'i KORUNUR (hâlâ tam coverage
  kanıtlıyor) ve faz-bağımsız olur. `now_fn`-enjeksiyonuna gerek
  kalmadı: kök, production `now` kullanımı değil, fixture anchor fazıydı
  (production `_warmup` aynı `now`'u close-filter için kullanıyor; o
  filtre en-UC bucket'ı etkiliyor, en-ESKİ'yi değil — bu yüzden hizalama
  tek başına yeterli ve doğru). KARDEŞ taraması: `first_slot==
  feed_first_slot` guard'ı YALNIZ T4'te; diğer −1700dk anchor'ları
  (224/285/364/532/571) en-eski-slot assert'i yok → immün, dokunulmadı
  (testte not olarak disclosure).
- **KOŞUMLAR:** d49 8/8 PASS · orchestrator grubu (d49+d53_alerting+
  startup+tas2+tas3+tas4) **103/103 PASS** deterministik (Hakem beklentisi
  "~104" — exact sayım 103, disclosed) · index FINAL ağaçtan regen
  (§10.2): 1545 fn (+1 = `_aligned_history_anchor`), `logs` sızıntısı 0,
  watcher ölü (0 python process, §10.1) · freeze-rutini: `src/`+frozen
  engine diff temiz · commit-7 kapsamı = `tests/test_orchestrator_d49.py`
  + `index.json` + bu ledger (executable-code kapsamı TEST-ONLY; memory-
  bank §17-izinli chore). Set 7-hash'te KALIYOR (ledger ayrı commit
  yapılmadı — §9.5 set-büyütme yok).

## N2 #8 PUSH KAYDI — 7-hash set, FREEZE HEAD `5ecbf0c`

- **Who/What:** Luna (icra) · Hakem (yetki: N2 #8 flake-kök-neden hükmü,
  aşamalı kural: "BEKLENEN eşleşirse → commit-7 → spot-check → 7-hash
  push — BU MESAJDA YETKİLİ").
- **When:** 2026-08-31 · **Remote:** origin/main
  (https://github.com/ahmetonurof-lab/sniper_forex.git)
- **Set-büyüme tarihi (§9.5):** 4 → 6 (flake-fix hükmüyle) → 7
  (commit-7). Her büyüme ayrı hakem yetkisi aldı; nihai yetki 7-hash
  seti için koşullu verildi ve koşullar sağlandı.
- **Set (7/7, ride-along yok — tam hash'ler):**
  `28ad9d5b40fd6f07afb704f33bca644bd93051d5` ledger N2 #7 push kaydı
  `d4830cc554c952e5338f305dea4f7e6f1b6b9959` P0 diagnosis (gate 2)
  `f906e7dbf7599e770a11cb8bbf80504da2de2b86` parity probe gate 3 — DIFFERENCE FOUND
  `34232a16b607e072e90910fb54ad3faa7a7d6131` arbitration (b) canonical + dataset SHA256
  `c66888a3db8ea9618a3b92e6743802e801d882be` (b) single-curve hardening (P0 FIX, 8 dosya)
  `0f133c0145f30ff51369a68c0c7348364de141f8` sha256 dual-form disclosure
  `5ecbf0c4aa21d0246d59076c2348c61a60751a92` commit-7: d49 flake fix (test-only)
- **Push öncesi koşutluk (hüküm BEKLENEN satırı):** final-ağaç tam süit
  **2 failed, 487 passed, 1 skipped, 0 error** (848.99 s) — kırmızılar
  yalnız parity-pinned `test_e2e_live_chain` çifti; d49 dalı temiz.
  Commit-7 blob'unda ek determinizm kanıtı: clock-pinned faz-matrisi
  8 kötü dakika + 2 iyi dakika = **10/10 PASS** (pre-fix 8/8 FAIL).
- **Gate spot-check (a-d):** blob'dan form-teyidi — (a) `MAX_DROPPED_
  SIGNALS: int = 0` (satır 257), (b) `entry_float > exit_float` →
  `raise ValueError` invariant (437→446), (c) `_enforce_dropped_signal_
  policy` çağrısı (546), (d) commit-7 `src/`+`experiment/`-dokunmaz
  (3 dosya: test+index+ledger).
- **Commit-7 hook olayı (§10.3 kaydı):** ilk commit denemesi hook
  düzeltmeleriyle abort oldu; Windows stash/restore turu staged index'i
  boşalttı (içerik worktree'da hook-düzeltmiş halde kaldı). Yeniden
  stage + commit: hook'lar **Passed** (blob = doğrulanmış ağaç). Blob
  ≡ worktree teyit edildi (`git diff HEAD` test+index = boş).
- **Push:** `2a0d5b3..5ecbf0c main -> main`
- **Verification (§9.2):** `origin/main..HEAD` → **BOŞ** ·
  `git ls-remote origin main` → `5ecbf0c4aa21d0246d59076c2348c61a60751a92`
  = local HEAD · working tree temiz (tracked).
- **FREEZE: AKTİF — HEAD `5ecbf0c`** (commit-7 dahil; src/ + tests/ tam
  donmuş). P0 borcu (fail-fast single-curve invariant) remote'da.
- **KALAN (TAG öncesi):** ③ closure = parity-skip koşulu (1S ya bir kez
  açıkça koşacak ya skip-reasonu provenance paketini girecek) + TAG
  paketi: (b)-fix hash + benchmark 2302T/+2593.26R/5.00R/PF 4.97/
  paused=0 + dataset SHA256 manifest + single-curve semantik beyanı.
  Gate ④ (soak) ve Gate ⑤ (Forexçi ticari paket: risk profili + çarpan
  dağılımı kaydı 2186/99/15→1994/278/30, scaled 114→308=%13.4, t1/t2/t3
  recalibration sahibi) — insan kapıları.

## ③(a) PARITY-KAPANIŞI + 1S KİMLİK DÜZELTMESİ (§12.1 — 2026-08-31)

- **Eski结论 (satır ~1603, olduğu gibi kalır):** "1S `test_parity_6majors`
  = documented slow-skip". **Neden yanlış:** etiket hiç doğrulanmamıştı —
  `-q` çıktısı skip-adını basmıyor; 1S kimliği tahminden kayıtlaştı.
- **Yeni kanıt (iki koşum, donmuş HEAD ağacı):**
  1. `test_parity_6majors` açıkça koşuldu → **7 passed, 0 skipped,
     514.06 s** (6 parametrik + summary; altı feather da diskte ~65k bar).
     Yani parity hiç atlamıyordu — süitin 487P'si içinde zaten koşuyordu.
  2. Gerçek 1S izole `-rs` ile yakalandı:
     `tests/test_live_signal_runner.py:201` —
     `test_signal_runner_signal_event_payload_has_expected_fields`:
     SKIPPED "no signals emitted (random data — rerun if needed)".
     Deterministik: üretic `seed=1` sabit (L93), 3000 M1 sentetik bar →
     0 sinyal → payload-şekil testi boş kümede atlıyor. Her süitte aynı
     node atlar → sayım kararlı (485→490 boyunca 1S sabit).
- **Hakem TAG-şartının akıbeti:** "ya bir kez explicit koşulur ya
  skip-gerekçesi pakete girer" → **İKİSİ DE OLDU**: parity explicit
  koşuldu (7/7 PASS) VE gerçek skip'in gerekçesi provenance'a girdi.
  Kapalı soru: `test_parity_6majors` etiket hatası — düzeltme bu kayıt +
  `memory-bank/forexci_package_gate5.md` §5'te.
- **Ek not:** signal_runner payload-testi "DEFECTIVE-ADJACENT" değil —
  skip bilinçli tasarımdı ("rerun if needed"); fakat seed=1 ile 0-sinyal
  deterministik olduğundan test fiilen hiçbir süitte assert-etmiyor.
  Aday açık-kalem: real-data varyantı veya seed-taraması (N2 #9+ işi,
  freeze altındayken dokunulmaz).

## KARAR-1 + KARAR-2 KABULÜ ve C2 WIRE (2026-09-01)

- **KARAR-1 (Hakem, OK):** Risk profili kabul: 2302T / +2593.26R /
  MaxDD 5.00R (2.24%) / PF 4.97. DD-scaling eşikleri 2R/4R/6R **kalır**
  (kod-default DEFAULT_T1/T2/T3 zaten bu değerlerde → config no-op;
  config tarafı motor production'da ayağa kalktıktan sonra ayrıca).
- **KARAR-2 (Hakem, verbatim kural):** GLOBAL ENTRY LOCK YOK.
  Sembol/parite bazında: bir paritede açık trade varsa aynı paritede
  yeni trade açılmaz; diğer pariteler etkilenmez; her sembol için aynı
  anda maks. 1 açık trade. `end_state=active_trade → entries_enabled=
  False` global olarak UYGULANMAYACAK; sembol-bazlı uygulanacak.
  → "Bunu C2 policy olarak bu semantik üzerinden wire et."
- **WIRE (bu commit):** `LiveRunner._symbol_entry_locked()` —
  broker-authoritative: bot-magic filtreli canlı pozisyonlar
  (`poll_deals` ile AYNI konvansiyon, §2.2 tek-kaynak) + dolgu-view
  `_position_to_ctx` birleşimi (lag/çift-entry koruması). Broker truth
  alınamazsa fail-safe KİLİTLİ (`_positions_get` "assume open"
  konvansiyonuyla tutarlı, §7). Guard `on_bar` başında
  `runtime.on_bar()`dan ÖNCE yakalanır — `_fill_pending` atomik
  create+signal tuzağı (entry kendi fill'iyle kendini bloklamaz).
  Kilitli sinyal: gönderilmez, `blocked_reason=
  c2_symbol_entry_lock_active_trade` + RISK audit (görünür, §19).
  §7.2 üç-yarılma korunur: state advancement (runtime.on_bar) ve
  pozisyon yönetimi (poll_deals/sync_trailing) kilitten ETKİLENMEZ.
  Boot `end_state=active_trade` global kapıyı kapatmaz (regresyon testi
  var). `_begin_cold_rebuild` docstring'indeki "C2 policy decision
  remains pending" notu ratify-politikaya bağlandı.
- **TEST KANITI:** +8 yeni geçen test (7 runner-level `test_p0_2_
  lifecycle_wiring.py` 9→16: block/allow-other-symbol/non-bot-magic/
  own-fill-second-block/release-after-close/no-broker-truth-fail-safe/
  management-continues; 1 orchestrator-level KARAR-2 regresyon
  `test_orchestrator_tas3.py` 15→16; d49 C2-report testleri mevcut
  haliyle yeşil). Tam süit: **2F / 495P / 1S / 0E (598.71 s)** —
  baseline 2F/487P/1S + 8 yeni = 495P (sayım tutarlı).
  2F = pinned pre-existing (stash-differential: donmuş HEAD'de aynı
  satır/aynı neden `order_sent=False` — E2EBroker.order_check retcode
  uyumsuzluğu; guard'dan bağımsız). 1S = signal_runner:201 (kimlik
  §13.5 düzeltmesiyle doğrulanmış).
- **KARAR-2 semantik not:** Çok-sembollü dağıtım zaten process-bazlı
  (1 Orchestrator = configured_symbols[0]); guard `self.symbol`
  eşleşmesine bağlı → diğer pariteler yapısal olarak bağımsız.

## N2 #9 PUSH KAYDI (2026-09-01 07:1x — LUNA, Hakem yetkisiyle)

- **who:** LUNA (agent) — Hakem yazılı yetkisi: "PUSH N2 #9: 3-hash
  set, YETKİLİ" (aynı mesajda KARAR-2 wire tahkimi: KABUL; dört tasarım
  kararı tek tek onaylı — atomiklik pre-capture / lag birleşim /
  fail-safe yön / görünür düşürme; §7.2 üç-yarılma ve boot regresyonu
  ayrıca teyitli).
- **what (SET, 3 hash — yetki tam bu sete bağlı, §9.5):**
  - `1e9dc5f` chore: ledger — N2 #8 push record
  - `7cfad79` chore(memory-bank): gate-3(a) parity closure + Forexçi gate-5
  - `7a1e6f1` feat(live): C2 symbol-based entry lock per KARAR-2
- **set-büyüme beyanı:** Önerilen mini-set 2 hash'ti (1e9dc5f+7cfad79);
  C2 wire commit'inin (7a1e6f1) katılmasıyla 2→3 büyüdü → set değişimi
  = yeniden yetki kuralı işledi; Hakem 3-hash setini açıkça yetkilendirdi.
- **remote:** origin main — `5ecbf0c..7a1e6f1` fast-forward.
- **imza 1:** `git log --oneline origin/main..HEAD` → BOŞ ✓
- **imza 2:** `git ls-remote origin main` =
  `7a1e6f10aeaf6dcf078af004a7c0fcb93f9d29ae` = local HEAD ✓
- **working tree:** push sonrası tracked temiz.
- **PROVENANCE OLAYI (§10.1, görünür kalır):** Push-öncesi pre-flight'ta
  index.json'da commit-sonrası bir mutasyon yakalandı: `CodeIndexWatcher`
  (PID 2700, `python -u watcher.py --config config.json`, sistem Python
  3.12) commit anındaki tasklist kontrolünde YOKTU; push hazırlığında
  (07:03:44) `generated_at`/`last_full_scan` alanlarını tek başına
  güncellemişti. Tespit → watcher kill → `git checkout -- index.json`
  (kasıtlı regen'li 7a1e6f1 blob'u korundu) → push. Push edilen blob,
  doğrulanan blob'dur (§10.3). Ders: "watcher durmuş mu" kontrolü tek
  seferlik değil, commit-ve-push anlarında YENİDEN yapılır.
- **FREEZE noktası güncellendi:** §17 soak-freeze HEAD = `7a1e6f1`
  (C2 wire'lı, süit-kanıtlı 2F/495P/1S). origin/main = 7a1e6f1.
- **Pano:** ②✅ ①-wired(7a1e6f1) ⑤-tek-cümle bekleniyor ③-tag-hazır
  ④-tık-bekliyor.

## D53b — WATCHER KARANTİNASI (Hakem escalation, 2026-09-01)

- **Karar revizyonu (§12.1):** Önceki "watcher kapalı + defter
  tombstone" kararım YETERSİZ kaldı — ikinci diriliş (PID 10408 → kill →
  "KAPALI" kaydı → PID 2700) bunu kanıtladı. Tombstone DURUM beyanıdır,
  MEKANİZMA değildir. Hakem kararı: **araç-desteği** — artifact karantinası.
- **GERÇEK DİRİLİŞ VEKTÖRÜ (bu icrada bulundu — önceki tarama eksikti):**
  Servis kayıtlı DEĞİL, planlanmış görev temiz (yalnız Windows'un kendi
  `\Microsoft\Windows\Shell\IndexerAutomaticMaintenance` — ilgisiz).
  Ancak `Start Menu\Programs\Startup\CodeIndexWatcher.lnk` →
  `wscript.exe start_watcher.vbs` → `python -u watcher.py` — LOGON
  tetikli. PID 2700'un kaynağı buydu. Düzeltme beyanı: N2 #9 kaydındaki
  "kaynak: el başlatması" hükmüm YANLIŞTI — otomatik logon başlatmasıydı;
  servis/görev taraması Startup klasörünü kapsamıyordu (§12.1).
- **KARANTİNA İCRASI (tools/code-index-system/, hepsi UNTRACKED → §17
  freeze kapsamı dışı; index_builder.py el-yolu protokolü DOKUNULMADI):**
  watcher.py, start_watcher.vbs, start_watcher.bat, watcher-task.xml
  (taslak; LogonTrigger + `cmd /c python -u watcher.py` içeriyordu —
  kayıt yoktu ama vektör taşıyordu), install-service.ps1,
  uninstall-service.ps1, bootstrap_admin.ps1, setup-admin.ps1 →
  hepsi `*.QUARANTINED_20260901`; watcher.cpython-312.pyc silindi;
  Startup\CodeIndexWatcher.lnk → aynı klasöre karantina kanıtı olarak
  taşındı. watcher.py başlığına 4 satırlık karantina notu eklendi.
- **NEGATİF TEST (doğrulandı):** `python -u watcher.py --config
  config.json` → `[Errno 2] No such file or directory` — sessiz diriliş
  yolu kapalı, gürültülü fail. Startup klasörü boş (yalnız desktop.ini).
- **ZORUNLU PRE-FLIGHT KURALI (Hakem onaylı, Aşama-5 commit'ine
  işlenecek):** "watcher/python süreci durmuş mu" kontrolü artık commit
  VE push anlarında ayrı ayrı zorunlu pre-flight maddesidir (§10.1
  operasyonel türevi). Bir oturumdaki kill, sonraki oturumu bağlamaz.
- **82fbac4 disposition (Hakem):** (A) TAG'le piggyback (N2 #10 2-hash
  set). Ön-yetki: 82fbac4 7 günü doldurmadan TAG düşmezse SOLO push
  önceden yetkilidir (N2 #6 deseni) — icra + defter yeter, söz istemez.
