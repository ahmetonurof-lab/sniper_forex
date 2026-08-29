# SNIPER_FOREX — RUNTIME HARDENING TASKS

## STATUS

| Item | State |
|------|-------|
| Current phase | Repository cleanup COMPLETE |
| Native MT5 connection | PASS |
| Native DEMO execution | PASS |
| Runtime smoke | PASS |
| Live polling | PASS |
| Strategy changes | NONE |
| Repository tests | PASS (post-cleanup) |

---

## PRIORITY 0 — STARTUP SAFETY

### Task 0.1 — Startup Broker State Snapshot
**Status**: PENDING

At startup record:
- MT5 build/version
- account
- server
- balance/equity
- configured symbols
- open positions
- pending orders
- existing SL/TP
- local state
- reconciliation result

**Acceptance**: startup immediately exposes broker + local state.
**Files**: `src/live/live_runner.py`
**Test**: `phase4_smoke.py` + log inspection

---

### Task 0.2 — Startup Position Reconciliation
**Status**: PENDING

Verify and harden:
```
broker positions ↔ local state
```

**Acceptance**: restart cannot silently create duplicate strategy state.
**Files**: `src/live/recovery.py`, `src/live/reconciliation.py`
**Test**: Unit test with mock positions

---

### Task 0.3 — Existing Position Entry Guard
**Status**: PENDING

Determine and enforce correct behavior when a bot-owned position already exists.

Do not assume the correct rule; derive it from the current strategy/runtime semantics.

**Acceptance**: no unintended duplicate entry after restart.
**Files**: `src/live/live_runner.py`, `src/live/safety.py`
**Test**: Unit test with pre-existing position

---

## PRIORITY 1 — PROTECTION SAFETY

### Task 1.1 — Missing SL Detection
**Status**: PENDING

Detect: `position exists + SL missing`

**Acceptance**: condition is detected and persisted/logged.
**Files**: `src/live/position_manager.py`, `src/live/safety.py`
**Test**: Unit test with mock position missing SL

---

### Task 1.2 — Missing TP Detection
**Status**: PENDING

Detect: `position exists + TP missing`

**Acceptance**: condition is detected and persisted/logged.
**Files**: `src/live/position_manager.py`, `src/live/safety.py`
**Test**: Unit test with mock position missing TP

---

### Task 1.3 — Invalid / Duplicate Protection
**Status**: PENDING

Detect:
- invalid SL
- invalid TP
- duplicate protection
- unexpected protection state

**Acceptance**: runtime enters a safe state and blocks new entries until resolved.
**Files**: `src/live/safety.py`, `src/live/execution.py`
**Test**: Unit test with invalid protection scenarios

---

### Task 1.4 — Protection Repair
**Status**: PENDING (DESIGN FIRST)

Design and validate repair separately.

First implementation stage must prefer:
```
DETECT → LOG → SAFE MODE
```

Automatic repair requires a separate explicit validation gate.

**Acceptance**: repair is safe and validated.
**Files**: `src/live/safety.py`
**Test**: Unit test for each repair path

---

## PRIORITY 2 — PERIODIC POSITION HEALTH

### Task 2.1 — Periodic Broker Position Check
**Status**: PENDING

Implement a periodic broker-state health check.

Target: approximately every 60 seconds (confirm interval against existing architecture).

Check:
- position existence
- direction
- volume
- entry
- SL
- TP
- protection integrity
- broker/local reconciliation

Do not emit repetitive log spam; emit state changes and mismatches.

**Acceptance**: periodic health check runs and reports changes.
**Files**: New `src/live/health_monitor.py`
**Test**: Unit test with mock broker

---

### Task 2.2 — Connection Health
**Status**: PENDING

Record:
- connect
- disconnect
- reconnect
- failed initialization
- recovery attempt

**Acceptance**: connection loss is visible and recoverable.
**Files**: `src/live/audit.py`
**Test**: Unit test for connection events

---

### Task 2.3 — Recovery Visibility
**Status**: PENDING

Record:
- state restore
- position restore
- protection restore
- reconciliation result

**Acceptance**: restart/recovery leaves an auditable trail.
**Files**: `src/live/recovery.py`
**Test**: Unit test for recovery events

---

## PRIORITY 3 — STARTUP / DATA OBSERVABILITY

### Task 3.1 — Per-Symbol Data Snapshot
**Status**: PENDING

For every configured symbol record:
- M1 requested
- M1 received
- oldest timestamp
- newest timestamp
- M15 generated
- duplicate count
- missing/incomplete buckets

**Acceptance**: startup proves data quality for every symbol.
**Files**: `src/live/candle_feed.py`
**Test**: `phase4_smoke.py` + log inspection

---

### Task 3.2 — Warmup Snapshot
**Status**: PENDING

Record:
- warmup bars
- ATR
- start index
- warmup complete

**Acceptance**: runtime readiness is explicit.
**Files**: `src/live/strategy_runtime.py`
**Test**: `phase4_smoke.py` + log inspection

---

### Task 3.3 — Session / CBDR Snapshot
**Status**: PENDING

Record the ACTUAL active/completed cycle used by the runtime:
- CBDR cycle
- body_high
- body_low
- window state
- locked
- sweep
- sweep direction
- daily_bias
- bias_locked

Do not change CBDR semantics.

**Acceptance**: a daytime restart reports the actual strategy state being used.
**Files**: `src/live/strategy_runtime.py`
**Test**: Unit test for CBDR state logging

---

## PRIORITY 4 — STRATEGY STATE VISIBILITY

### Task 4.1 — State Transition Visibility
**Status**: PENDING

Make major state transitions visible:
- WAITING_CBDR
- WAITING_SWEEP
- SWEEP_CONFIRMED
- WAITING_FVG
- FVG_FOUND
- FVG_REJECTED
- READY_FOR_ENTRY
- POSITION_ACTIVE
- EXIT

Use existing state semantics. Do not invent a parallel strategy state machine.

**Acceptance**: state transitions are logged on change.
**Files**: `src/live/strategy_runtime.py`, `src/live/live_runner.py`
**Test**: Unit test for state transitions

---

### Task 4.2 — Why-No-Signal
**Status**: PENDING

Expose the actual blocking reason:
- CBDR not ready
- no sweep
- FVG unavailable
- EQ rejected
- risk rejected
- position already active

Deduplicate repetitive reasons. Do not log the same reason on every polling cycle.

**Acceptance**: blocking reason is clear and deduplicated.
**Files**: `src/live/live_runner.py`
**Test**: Unit test for blocking reasons

---

## PRIORITY 5 — TRADE FORENSICS

### Task 5.1 — Complete Trade Record
**Status**: PENDING

Extend the existing Forex lifecycle/audit architecture so that one completed trade can reconstruct the complete strategic story.

Target record:
- symbol
- side
- CBDR cycle
- CBDR body
- bias
- sweep
- sweep level
- MSS/CHOCH if represented
- FVG
- EQ
- entry
- initial SL
- initial TP
- RR
- risk
- lot
- DD/risk multiplier
- trailing steps
- exit
- exit reason
- PnL
- realized R
- order/deal/position IDs
- timestamps

Preferred design: **ONE TRADE = ONE FORENSIC RECORD**

Do not create a parallel state architecture if existing `TradeLifecycle` / `AuditChain` can be extended.

**Acceptance**: complete trade story reconstructable.
**Files**: `src/live/trade_lifecycle.py`, `src/live/audit.py`
**Test**: Unit test for trade record completeness

---

### Task 5.2 — Trade History Compatibility
**Status**: PENDING (EVALUATE)

Evaluate whether a `trades_history.jsonl`-style artifact adds real value to Forex.

If implemented:
- one completed trade per JSONL record
- machine-readable
- restart-safe
- no duplicated trailing entries caused by repeated identical fingerprints

**Acceptance**: trade history is useful and correct.
**Files**: `src/live/trade_lifecycle.py`
**Test**: Unit test for history format

---

## PRIORITY 6 — LIVE STATE / SNAPSHOT

### Task 6.1 — Runtime Snapshot
**Status**: PENDING (EVALUATE)

Evaluate whether existing `StateStore` is sufficient.

Only add a `live_state` artifact if there is a genuine missing capability.

Target visibility:
- account
- symbols
- last processed bar
- CBDR
- bias
- sweep
- FVG
- position
- SL
- TP
- trailing
- risk
- connection
- runtime state

Do not create a second state system unnecessarily.

**Acceptance**: runtime state is visible.
**Files**: `src/live/state.py`
**Test**: Unit test for snapshot

---

### Task 6.2 — Visual Trade Forensics
**Status**: DESIGN ONLY

Eventually support:
```
one completed trade
→ historical OHLC
→ CBDR
→ sweep
→ MSS/CHOCH
→ FVG
→ EQ
→ entry
→ SL/TP
→ trailing
→ exit
```

The visual layer must be downstream of the authoritative trade record and must never alter trading logic.

**Acceptance**: design document complete.
**Files**: `docs/FOREX_VISUAL_FORENSICS_DESIGN.md`
**Test**: N/A (design only)

---

## PRIORITY 7 — WATCHDOG

### Task 7.1 — Stuck-State Detection
**Status**: PENDING (DESIGN FIRST)

Watchdog may:
- DETECT
- LOG
- ALERT
- SAFE MODE

It must NOT silently mutate the strategy state machine or force:
```
STUCK → ACTIVE
```
without a dedicated evidence-backed design.

**Acceptance**: watchdog detects stuck states safely.
**Files**: New `src/live/watchdog.py`
**Test**: Unit test for stuck detection

---

## PRIORITY 8 — RESEARCH / PRODUCTION PARITY

### Task 8.1 — Protect Research Semantics
**Status**: ONGOING

Do not modify:
- C v1.0
- C v1.1
- StrategyRuntime
- FVG
- EQ
- Sweep
- CBDR
- Trailing
- Risk

unless a targeted regression proves an actual defect.

**Acceptance**: research engines unchanged.
**Files**: N/A (protection rule)
**Test**: Existing regression tests

---

### Task 8.2 — Live/Research Parity
**Status**: ONGOING

Any runtime change affecting market-data or strategy semantics must preserve established live/backtest parity.

Existing parity and chronology work remains authoritative.

**Acceptance**: parity preserved.
**Files**: N/A (protection rule)
**Test**: Existing parity tests

---

## IMPLEMENTATION RULE

Execute tasks **ONE AT A TIME**.

For every task:
```
inspect
→ implement minimal change
→ focused test
→ regression suite
→ runtime validation
→ evidence
→ update task status
```

Never bundle unrelated tasks into one patch.

No optimization work during runtime hardening.

No order testing unless explicitly authorized.

---

## CURRENT VALIDATED STATE

| Capability | Status | Evidence |
|------------|--------|----------|
| Native Windows x64 | PASS | Python 3.12.2, venv |
| IC Markets MT5 build 6140 | PASS | `terminal64.exe` |
| MetaTrader5 5.0.6147 | PASS | PyPI package |
| `mt5.initialize()` | PASS | Phase 2 test |
| `account_info()` | PASS | Phase 2 test |
| live tick | PASS | Phase 2 test |
| `order_check()` | PASS | Phase 3 test |
| `order_send()` | PASS | Phase 3 test |
| SL/TP | PASS | Phase 3 test |
| close | PASS | Phase 3 test |
| Runtime smoke | PASS | Phase 4 |
| Live polling | PASS | Phase 5 |
| Strategy changes | NONE | Protected |

---

## NEXT TASK

**Task 0.1 — Startup Broker State Snapshot**

First implementation step after this document is approved.
