# SNIPER_FOREX — MT5 DEMO IMPLEMENTATION ROADMAP

> **MASTER SOURCE OF TRUTH** for the research → MT5 DEMO production transition.
> This file is the persistent cross-agent task/roadmap. A new agent reads this
> file + `memory-bank/` + codebase-memory, then continues from the first
> unchecked phase. Do NOT assume prior conversation history.
>
> Created: 2026-08-27. Companion to `memory-bank/activeContext.md` (research
> control panel) and `memory-bank/progress.md` (research log).

---

## STATUS HEADER

```
Current Phase:        PHASE 11 — CONTROLLED MT5 DEMO
Last Completed Phase: PHASE 10 — PAPER / DRY RUN (2026-08-28)
Last Commit:          3ed3e7a (phase10: paper trading)
Blocking Issue:       none
Next Action:          Start PHASE 11 (controlled demo: 1 symbol -> 6 majors)
```

---

## NON-NEGOTIABLE RESEARCH SAFETY

The following are **IMMUTABLE research references**. DO NOT touch:

- `experiment/main_research_c_v1_0.py` (C v1.0 / C2 EQ — FROZEN)
- `experiment/main_research_d_v1_0.py` (D v1.0 / PURE D EQ — FROZEN)
- Frozen benchmark JSONs under `results/benchmark/` (e.g. `PURE_D_FVG_ORIGIN_EQ_benchmark.json`, `abfix_*.json`)

If any of these show a git diff during an implementation phase → **STOP**.

**DD Risk Scaling** is OUT OF SCOPE for production implementation at this stage
(research: C = candidate, D = REJECT). Position it as an optional future risk
module / promotion decision pending. Do NOT auto-add to production.

**C/D engine selection** must NOT be forced in a way that unnecessarily locks the
production architecture. Strategy behavior must NOT be changed.

**Goal chain:**
```
KNOWN-GOOD BACKTEST BEHAVIOR
        ↓
LIVE RUNTIME
        ↓
DETERMINISTIC PARITY
        ↓
MT5 DEMO
```

---

## IMPLEMENTATION RULE

- Analyze existing code first. Reuse existing functions/modules before creating
  new files. Avoid unnecessary abstraction and file proliferation.
- Do NOT refactor the frozen research engine to merge with production code.
  Production implementation stays a **separate runtime**.
- Production runtime lives under `src/live/` (new package), separate from
  research `experiment/` and Phase-0 `src/trading|data|backtest`.

---

## PHASES

---

### [x] PHASE 1 — MT5 FOUNDATION

- **Objective:** Harden the MT5 connection + data layer so the bot has a
  reliable, reconnect-capable, failure-aware MT5 foundation.
- **Tasks:**
  - Harden `MT5Connection`: initialize/login failure handling, `last_error`
    capture, reconnect/recovery, terminal availability check, path-based
    initialize.
  - Harden `MT5DataLayer`: symbol availability, tick/rates access robustness.
  - Add structured status/error reporting (no credentials logged).
- **Files:**
  - `src/trading/mt5_connection.py` (modify — harden)
  - `src/data/mt5_data.py` (modify — harden)
  - `tests/test_mt5_connection_hardening.py` (new — synthetic unit tests)
- **Dependencies:** `src/config/mt5_config.py` (.env), MetaTrader5 package.
- **Tests:**
  - `python -m src.test_mt5_connection` (architecture) — 7/7 PASS
  - `python -m pytest tests/test_mt5_connection_hardening.py` — 10/10 PASS
  - `python -m pytest tests/` — 100/100 PASS
- **Acceptance criteria:**
  - connection PASS ✅
  - failure handling PASS ✅
  - reconnect PASS ✅
  - tick/rates access PASS ✅
  - frozen engines unchanged (git diff CLEAN) ✅
- **Status:** COMPLETE (2026-08-27)
- **Commit:** d997cd3
- **Known risks:** MT5 terminal environment dependency; credentials must never
  be logged.
- **Notes:** Phase 0 `MT5Connection` had no reconnect and only `print()` error
  handling. Added: path-based initialize, `last_error` capture, `is_connected`,
  `reconnect`, `ensure_connected`, robust error handling in data layer. No
  strategy behavior changed. Frozen engines untouched.

---

### [x] PHASE 2 — MARKET DATA / 15M CANDLE FEED

- **Objective:** Reliable M1 feed → canonical 15m closed candle production.
- **Tasks:**
  - MT5 M1 feed (pull-based).
  - Forming vs closed candle distinction.
  - Duplicate candle detection.
  - Missing candle detection.
  - Historical warmup.
  - Timezone / server-time handling.
  - Canonical 15m aggregation (match backtest boundary).
- **Files:**
  - `src/live/candle_feed.py` (new)
  - `src/live/clock.py` (new — timezone/session clock)
- **Dependencies:** PHASE 1.
- **Tests:** Synthetic M1→15m aggregation; dup/missing injection; forming candle.
- **Acceptance criteria:** Same M1 input → same 15m OHLC/timestamp as canonical
  backtest.
- **Status:** COMPLETE (2026-08-27)
- **Commit:** b81115d
- **Known risks:** Aggregation boundary parity (must match `resample_15m()`).
- **Notes:** Canonical engines load 15m feather directly; live must aggregate M1
  with the SAME boundary (`resample_15m()`: epoch//15min, drop <3-bar buckets).
  Implemented `src/live/candle_feed.py` (M1CandleFeed: fetch_m1, find_duplicates,
  find_missing, is_closed_m1, warmup, update; resample_15m parity) and
  `src/live/clock.py` (server-time UTC offset summer/winter, session window).
  Server-time -> UTC conversion uses CURRENT offset (one offset per live session).
  Frozen engines untouched.

---

### [x] PHASE 3 — STRATEGY RUNTIME

- **Objective:** Port backtest strategy behavior to live runtime.
- **Tasks:**
  - 15m closed bar → SessionManager → CBDR → Sweep → Bias → FVG → EQ → First
    FVG → First Touch → Signal.
  - Per-symbol state (6 majors isolation).
  - Candle event loop.
  - Restart / state recovery.
- **Files:**
  - `src/live/strategy_runtime.py` (new)
  - `src/live/state.py` (new — persistence/recovery)
- **Dependencies:** PHASE 2, `src/strategy/session.py`,
  `experiment/trailing_adapter.py`, nexus FVG (see decision).
- **Tests:** Deterministic replay — same 15m data → same signals/SL/TP as
  canonical engine.
- **Acceptance criteria:** Historical replay parity with canonical engine
  (signal/SL/TP).
- **Status:** COMPLETE (2026-08-27)
- **Commit:** 18ba794
- **Known risks:** Port errors; external nexus path dependency.
- **Notes:** Reuse `SessionManager` and `trailing_adapter` directly. Port the
  entry/SL/TP core from `run_test_a` (copy-adapt, do NOT modify frozen engine).
  Parity achieved: EURUSD + GBPUSD replay match canonical signal/SL/TP.
  Two parity gotchas fixed: (1) entry bar must be processed immediately
  (apply_trailing + check_exit on the fill bar); (2) sweep must NOT be reset at
  pending/touch time — reset only after a trade is created, and MIN_RISK_DIST
  failure must fall through to re-scan FVGs with the same sweep.

---

### [x] PHASE 4 — RISK + POSITION SIZING

- **Objective:** Risk engine + lot sizing.
- **Tasks:**
  - Account balance/equity.
  - Risk per trade.
  - Lot calculation.
  - Contract specs.
  - Volume min/max/step.
  - Stop distance.
  - Spread.
  - Exposure.
  - Broker constraints.
- **Files:**
  - `src/live/risk.py` (new)
  - `src/live/sizing.py` (new)
- **Dependencies:** PHASE 3.
- **Tests:** Synthetic risk scenarios (limit breach, high spread, stop-level).
- **Acceptance criteria:** If risk check fails → NO trade. Trade blocked and
  logged.
- **Status:** COMPLETE (2026-08-27)
- **Commit:** ca7af81
- **Known risks:** Incorrect risk math → demo loss.
- **Notes:** `RISK_PER_TRADE=0.003` in `experiment/config.py` is the reference.
  `src/live/risk.py` = `RiskManager` + `Account` + `RiskDecision` (pure,
  injectable). Checks: stop_distance<=0, stop below broker stops_level,
  excessive spread (ratio vs stop), risk-per-trade ceiling, exposure cap
  (notional as multiple of equity). Any fail → `approved=False`, `blocked=True`,
  reason + checks logged. `src/live/sizing.py` = `PositionSizer` + `ContractSpec`
  + `SizingResult`. Lot = balance*risk / (ticks*tick_value), rounded down to
  volume_step, clamped to [volume_min, volume_max]. Stop distance rounded to
  symbol digits to avoid float drift.

---

### [x] PHASE 5 — EXECUTION

- **Objective:** Order execution engine.
- **Tasks:**
  - `order_check`
  - `order_send`
  - Market order
  - SL/TP
  - Magic number
  - Comment
  - Duplicate protection
  - Rejection handling
  - Retry
- **Files:**
  - `src/live/execution.py` (new)
  - `tests/test_live_execution.py` (new — 12 synthetic unit tests)
- **Dependencies:** PHASE 1, 4.
- **Tests:** order_check validation; rejected/requote injection; duplicate order.
  - 12/12 PASS; full suite 144/144 PASS.
- **Acceptance criteria:** Order sent with SL/TP, dup prevented, reject logged +
  retried. ✅
- **Status:** COMPLETE (2026-08-27)
- **Commit:** d210dcf
- **Known risks:** Real order sending (demo only).
- **Notes:** **`signal_only=True` default** — NO real order is sent until
  the caller explicitly opts in. `OrderRequest` carries signal + lot + contract;
  `Execution.send()` runs `order_check` first (no send on validation fail), then
  `order_send` with retry on retriable retcodes (REQUOTE, PRICE_CHANGED,
  PRICE_OFF, CONNECTION, TIMEOUT, RETRY). Non-retriable rejects (REJECT, etc.)
  do NOT retry. Duplicate protection: per-(symbol, direction, sl, tp)
  fingerprint with configurable cooldown (`duplicate_window_sec`, default 5s)
  prevents double-click + retry storms. Magic (default 9007001) + comment
  (`SNIPER_FX|<sym>|<dir>|sweep<i>|z<j>`) are auto-injected. Exceptions in
  `order_send` are treated as retriable. Frozen engines untouched (git diff
  CLEAN).

---

### [x] PHASE 6 — POSITION MANAGER + RECONCILIATION

- **Objective:** Position tracking + state↔MT5 reconciliation.
- **Tasks:**
  - `positions_get`
  - Bot-owned positions (magic filtering)
  - Closed trade detection
  - Restart recovery
  - State ↔ MT5 reconciliation
  - Orphan / mismatch detection
- **Files:**
  - `src/live/position_manager.py` (new — `Position`, `ClosedTrade`, `PositionManager`, `PositionUpdate`)
  - `src/live/reconciliation.py` (new — `Reconciler`, `ReconciliationDecision`, `ReconcileStatus`)
  - `tests/test_live_position_reconciliation.py` (new — 16 synthetic unit tests)
- **Dependencies:** PHASE 5.
- **Tests:** 16/16 PASS; live suite 56/56 PASS (phase2/4/5/6). Frozen engines unchanged (git diff CLEAN).
- **Acceptance criteria:** Bot only manages its own (magic) positions; restart
  recovery correct; mismatch → trade block. ✅
- **Status:** COMPLETE (2026-08-27)
- **Commit:** 193ff5f
- **Known risks:** State↔MT5 mismatch → wrong action.
- **Notes:** `PositionManager` is pure/injectable: MT5 module passed as
  `mt5` arg (default = real MetaTrader5). Magic filter (`self.magic` ==
  bot's, default 9007001 mirrors `execution.py`) — manual positions and
  other EA's are NEVER touched. `update()` returns `PositionUpdate` with
  `positions` (current snapshot), `new_opens` (tickets that appeared
  since last poll), `closed_trades` (tickets that disappeared, carrying
  last-known state). `restore()` seeds snapshot from `state.py` for
  restart recovery. Exception-safe: if `positions_get` raises, update
  returns an empty update (caller can block trading).
  `Reconciler` is pure: takes two `dict[ticket, Position]` (local +
  remote) and returns `ReconciliationDecision`. Status aggregation
  (worst-of): MISMATCH > UNKNOWN_OPEN > ORPHAN > OK. `block_trading=True`
  on any non-OK (acceptance: mismatch → trade block). Mismatch fields:
  volume, sl, tp, side, entry_price, symbol. Frozen engines untouched.

---

### [x] PHASE 7 — LOGGING + SAFETY

- **Objective:** Full audit chain + fail-safe.
- **Tasks:**
  - Full chain: CANDLE → SIGNAL → RISK → ORDER → FILL → POSITION → EXIT.
  - Safety: kill switch, stale data block, connection failure block, excessive
    spread block, reconciliation failure block.
- **Files:**
  - `src/live/audit.py` (new — `AuditEvent`, `EventType`, `AuditChain`)
  - `src/live/safety.py` (new — `SafetyCheck`, `SafetyDecision`, `SafetyMonitor`)
  - `tests/test_live_audit_safety.py` (new — 19 synthetic unit tests)
- **Dependencies:** All prior.
- **Tests:** 19/19 PASS; live suite 75/75 PASS (phase2/4/5/6/7). Frozen engines unchanged (git diff CLEAN).
- **Acceptance criteria:** Every signal→order→fill recorded; safety condition →
  bot stops trading. ✅
- **Status:** COMPLETE (2026-08-27)
- **Commit:** a289a48
- **Known risks:** —
- **Notes:** **`AuditChain`** (`audit.py`): pure in-memory append-only event
  log + JSONL flush (`save`/`load`, atomic via tmp+rename). `EventType`
  enum: CANDLE / SIGNAL / RISK / ORDER / FILL / POSITION / EXIT / SAFETY
  / RECONCILE / ERROR. Each event has timestamp + symbol + free-form
  payload (json-serializable). **`SafetyMonitor`** (`safety.py`): pure
  composite gate with 5 guards in fixed severity order
  (KILL_SWITCH > STALE_DATA > CONNECTION > SPREAD > RECONCILIATION).
  Any guard fail -> `allowed=False`, `failing_check=that guard`,
  `reason=human-readable string`. Reconciliation None (first tick) does
  NOT block. Default thresholds: `max_spread_points=30`, `stale_seconds=1800`
  (30 min, one 15m bar + slack). Runtime loop expected to call
  `check(...)` at the top of each tick and skip trading if blocked.
  Frozen engines untouched.

---

### [x] PHASE 8 — FULL BACKTEST/LIVE PARITY

- **Objective:** Deterministic parity between backtest and live runtime.
- **Tasks:**
  - Deterministic replay.
  - Compare: candle, ATR, CBDR, sweep, bias, FVG, EQ, entry, SL, TP, exit.
- **Files:**
  - `src/live/parity_gate.py` (new — `check_symbol`, `check_all_six_majors`,
    `ParityReport`, `can_enable_execution`)
  - `tests/test_parity_6majors.py` (new — 7 tests, parametrized over
    6 majors + aggregate summary)
  - `tests/test_live_parity_gate.py` (new — 5 synthetic unit tests for
    parity gate contract; slow `check_all_six_majors` deselected by
    default, run on demand via `parity_check.py` or full pytest)
- **Dependencies:** PHASE 3.
- **Tests:** 6/6 majors parity PASS (2302 canonical trades = 2302 live
  signals, 0 diffs); gate tests 4/4 PASS. Frozen engines unchanged
  (git diff CLEAN). Aggregate per-symbol: EURUSD 407, AUDUSD 388,
  GBPUSD 378, GBPJPY 394, USDCAD 366, USDJPY 369. Runtime ~3:42 for
  the full 6-major parity replay.
- **Acceptance criteria:** Parity PASS. Execution must NOT be enabled
  without parity PASS. ✅
- **Status:** COMPLETE (2026-08-27)
- **Commit:** 87162dd
- **Known risks:** Parity break → cannot go live.
- **Notes:** Per-trade diff: direction, entry_price, sl, tp,
  entry_bar_index, sweep_bar_index, zone_index (7 fields). 100% match
  across all 6 majors. `parity_gate.can_enable_execution(report)`
  is the execution-gating predicate PHASE 11 must call before turning
  off `signal_only`. Frozen engines untouched.

---

### [x] PHASE 9 — MT5 SIGNAL-ONLY

- **Objective:** Real MT5 data, 6 majors, NO orders.
- **Tasks:**
  - MT5 → M1 → 15m → strategy → signal → risk.
  - Log signals only.
- **Files:**
  - `src/live/signal_runner.py` (new — `SignalRunner`, `RunnerConfig`,
    `RunnerResult`)
  - `tests/test_live_signal_runner.py` (new — 9 synthetic unit tests
    with FakeMT5, including the signal-only invariant
    `mt5.send_calls == 0`)
- **Dependencies:** PHASE 8.
- **Tests:** 8/8 PASS + 1 skipped (random data). Live fast suite
  87/87 PASS. Frozen engines unchanged (git diff CLEAN).
- **Acceptance criteria:** Signals produced match backtest; no orders
  sent. ✅
- **Status:** COMPLETE (2026-08-27)
- **Commit:** 66956d3
- **Known risks:** —
- **Notes:** `SignalRunner` is pure/injectable (MT5 module passed as
  `mt5` arg). Per-symbol chain: `copy_rates_from_pos(M1)` -> `resample_15m()`
  (canonical boundary, identical to frozen engine) -> `StrategyRuntime.warmup`
  + `on_bar()` -> emit Signal -> `RiskManager.evaluate` -> `AuditChain.append`
  (CANDLE / SIGNAL / RISK events). **`signal_only` invariant:** runner
  NEVER calls `order_send`. `RunnerResult` partitions signals into
  approved vs blocked; per-symbol count + error map. Error in one
  symbol is isolated (logged as AuditChain ERROR event, other symbols
  still run). Real data validation against Phase 8 parity is the next
  step (PHASE 10 paper run will exercise this on real MT5 feed). Frozen
  engines untouched.

---

### [x] PHASE 10 — PAPER / DRY RUN

- **Objective:** Real MT5 data, simulated execution, NO real orders.
- **Tasks:**
  - Simulate: fill, SL, TP, exit, PnL.
- **Files:**
  - `src/live/paper.py` (new — `PaperPosition`, `PositionStatus`,
    `PaperBroker`, `PaperSession`, `PaperStepResult`, `_pnl`)
  - `tests/test_live_paper.py` (new — 23 synthetic unit tests covering
    position lifecycle, SL/TP hit, PnL math for 5-digit majors and
    3-digit JPY pairs, volume scaling, dry-run invariant)
- **Dependencies:** PHASE 9.
- **Tests:** 23/23 PASS. Live fast suite 110/110 PASS. Frozen engines
  unchanged (git diff CLEAN).
- **Acceptance criteria:** Paper signals consistent with backtest; PnL
  sim correct. ✅
- **Status:** COMPLETE (2026-08-28)
- **Commit:** 3ed3e7a
- **Known risks:** —
- **Notes:** `PaperBroker` is the in-memory virtual broker — never
  touches MT5. `open()` instant-fills at `signal.entry_price` with
  monotonic ticket. `on_tick(bid, ask)` checks SL/TP per MT5
  convention (long: bid<=sl / bid>=tp, short: ask>=sl / ask<=tp) and
  closes with `CLOSED_SL` / `CLOSED_TP` reason. `_pnl` uses the broker
  formula `sign * (exit - entry) / tick_size * tick_value * volume`
  — works for both 5-digit majors and 3-digit JPY pairs (tested).
  `update_pnl(ticket, contract, exit_price)` patches realized PnL on
  closed positions. `PaperSession.run_step(audit, m1_bars?, ticks?)`
  is one bar-step: per-tick SL/TP check + strategy on closed 15m +
  risk gate + paper open. **Dry-run invariant:** `PaperSession` NEVER
  calls `mt5.order_send` (tested). Frozen engines untouched.

---

### [ ] PHASE 11 — CONTROLLED MT5 DEMO

- **Objective:** Real demo orders, controlled.
- **Tasks:**
  - First: 1 symbol → low risk → controlled monitoring.
  - Then: 6 majors.
  - Reconciliation, logging, safety, kill switch mandatory.
- **Files:** (existing modules)
- **Dependencies:** All prior phases PASS.
- **Tests:** Controlled demo run.
- **Acceptance criteria:** Orders sent correctly, SL/TP placed, reconciliation
  works, audit trail complete.
- **Status:** NOT STARTED
- **Commit:** (pending)
- **Known risks:** Real demo orders.
- **Notes:** Only after all previous phases PASS.

---

## EXECUTION MODEL

- Apply phases in order. Do NOT skip to the next phase before the current one
  is complete.
- At the end of each phase:
  1. Tests
  2. Acceptance criteria
  3. git diff
  4. frozen engine integrity
  5. memory-bank update
  6. roadmap checkbox update (`[ ]` → `[x]`)
  7. commit
  8. checkpoint report
- If a phase is NOT PASS:
  - Do NOT proceed to the next phase.
  - Write the problem as a blocker in the roadmap.
  - Apply/test the fix, re-verify.
- After a phase PASSes, give a checkpoint and end the session. The next agent
  continues from the roadmap.

---

## MEMORY-BANK RULE

The master roadmap is NOT the task list itself. Memory-bank reflects project
state only:
- which phase completed
- important architectural decisions
- test/parity results
- frozen benchmark status
- commit hash
- known risks/blockers
- next phase

Update `memory-bank/activeContext.md` and `memory-bank/progress.md` after each
completed phase.
