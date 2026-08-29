# SNIPER_FOREX — CLEANUP → TASK PLAN → MEMORY CHECKPOINT

## MISSION

Prepare the Forex repository for the next implementation phase.

The current native Windows MT5 environment is proven functional:

- Native Windows x64
- IC Markets MT5 build 6140
- `MetaTrader5` Python package 5.0.6147
- `mt5.initialize()` PASS
- `account_info()` PASS
- live tick PASS
- DEMO `order_check()` PASS
- DEMO `order_send()` PASS
- SL/TP PASS
- close PASS
- runtime smoke PASS
- live polling harness PASS

Stop environment experimentation.

The next phase is **codebase cleanup, operational hardening, observability, state/recovery verification, and trade-forensic completeness**.

---

# PHASE 1 — REPOSITORY CLEANUP

## 1.1 Audit first

Inspect the repository before deleting anything.

Classify candidate files as:

```text
PRODUCTION
RESEARCH / BENCHMARK
DOCUMENTATION
ACTIVE TEST
HISTORICAL FORENSIC
TEMPORARY DIAGNOSTIC
OBSOLETE / SAFE TO REMOVE
UNKNOWN
```

Check:

```text
git status
git ls-files
code references/imports
test references
startup/recovery references
```

Do not delete files merely because they are old.

## 1.2 Cleanup targets

The following were previously identified as likely obsolete:

```text
logs/p1_fix_infra.txt
logs/p1_fix_infra2.txt
logs/p1_fix_src.txt
logs/p1_flow.txt
logs/p1_flow2.txt
logs/p1_inventory.txt
logs/p1_risk.txt
logs/rollback_stageA.txt
logs/rollback_stageB.txt
nul
phase5_demo.py
```

Also inspect:

```text
docs/MaxDD_dusurme _teorileri.md
```

but do NOT delete it unless its lack of research/provenance value is proven.

Inspect these carefully before deciding:

```text
logs/bot_binance_local.py
logs/bot_infra_local.py
logs/config_local.py
logs/risk_manager_local.py
logs/test_risk_manager_local.py
logs/fix/
```

Do not remove Crypto reference artifacts merely because they are outside the current Forex runtime.

## 1.3 Preserve

Do not touch:

```text
experiment/
results/
memory-bank/
tests/
src/
canonical research engines
benchmark evidence
active documentation
```

unless a separate dependency audit proves an individual file is obsolete.

## 1.4 Cleanup execution

Only delete files classified:

```text
OBSOLETE / SAFE TO REMOVE
```

After deletion:

1. run repository tests
2. verify git status
3. verify no production import/reference is broken
4. record deleted files

Do NOT commit yet unless explicitly instructed after the cleanup validation.

---

# PHASE 2 — CREATE THE AUTHORITATIVE FOREX TASK LIST

Create:

```text
docs/FOREX_RUNTIME_HARDENING_TASKS.md
```

This file is the authoritative ordered work queue for the next phase.

Use exactly this structure:

# SNIPER_FOREX — RUNTIME HARDENING TASKS

## STATUS

Current phase:
Repository cleanup complete / pending

Native MT5 connection:
PASS

Native DEMO execution:
PASS

Runtime smoke:
PASS

Live polling:
PASS

Strategy changes:
NONE

## PRIORITY 0 — STARTUP SAFETY

### Task 0.1 — Startup Broker State Snapshot
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

Acceptance:
startup immediately exposes broker + local state.

### Task 0.2 — Startup Position Reconciliation
Verify and harden:

```text
broker positions
↔
local state
```

Acceptance:
restart cannot silently create duplicate strategy state.

### Task 0.3 — Existing Position Entry Guard
Determine and enforce correct behavior when a bot-owned position already exists.

Do not assume the correct rule; derive it from the current strategy/runtime semantics.

Acceptance:
no unintended duplicate entry after restart.

---

## PRIORITY 1 — PROTECTION SAFETY

### Task 1.1 — Missing SL Detection

Detect:

```text
position exists + SL missing
```

Acceptance:
condition is detected and persisted/logged.

### Task 1.2 — Missing TP Detection

Detect:

```text
position exists + TP missing
```

Acceptance:
condition is detected and persisted/logged.

### Task 1.3 — Invalid / Duplicate Protection

Detect:

```text
invalid SL
invalid TP
duplicate protection
unexpected protection state
```

Acceptance:
runtime enters a safe state and blocks new entries until resolved.

### Task 1.4 — Protection Repair

Design and validate repair separately.

First implementation stage must prefer:

```text
DETECT
→ LOG
→ SAFE MODE
```

Automatic repair requires a separate explicit validation gate.

---

## PRIORITY 2 — PERIODIC POSITION HEALTH

### Task 2.1 — Periodic Broker Position Check

Implement a periodic broker-state health check.

Target:

```text
approximately every 60 seconds
```

but confirm interval against the existing runtime architecture before implementation.

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

### Task 2.2 — Connection Health

Record:

```text
connect
disconnect
reconnect
failed initialization
recovery attempt
```

Acceptance:
connection loss is visible and recoverable.

### Task 2.3 — Recovery Visibility

Record:

```text
state restore
position restore
protection restore
reconciliation result
```

Acceptance:
restart/recovery leaves an auditable trail.

---

## PRIORITY 3 — STARTUP / DATA OBSERVABILITY

### Task 3.1 — Per-Symbol Data Snapshot

For every configured symbol record:

```text
M1 requested
M1 received
oldest timestamp
newest timestamp
M15 generated
duplicate count
missing/incomplete buckets
```

Acceptance:
startup proves data quality for every symbol.

### Task 3.2 — Warmup Snapshot

Record:

```text
warmup bars
ATR
start index
warmup complete
```

Acceptance:
runtime readiness is explicit.

### Task 3.3 — Session / CBDR Snapshot

Record the ACTUAL active/completed cycle used by the runtime:

```text
CBDR cycle
body_high
body_low
window state
locked
sweep
sweep direction
daily_bias
bias_locked
```

Do not change CBDR semantics.

Acceptance:
a daytime restart does not merely report an empty future CBDR state; it reports the actual strategy state being used.

---

## PRIORITY 4 — STRATEGY STATE VISIBILITY

### Task 4.1 — State Transition Visibility

Make major state transitions visible:

```text
WAITING_CBDR
WAITING_SWEEP
SWEEP_CONFIRMED
WAITING_FVG
FVG_FOUND
FVG_REJECTED
READY_FOR_ENTRY
POSITION_ACTIVE
EXIT
```

Use existing state semantics.

Do not invent a parallel strategy state machine.

### Task 4.2 — Why-No-Signal

Expose the actual blocking reason.

Examples:

```text
CBDR not ready
no sweep
FVG unavailable
EQ rejected
risk rejected
position already active
```

Deduplicate repetitive reasons.

Do not log the same reason on every polling cycle.

---

## PRIORITY 5 — TRADE FORENSICS

### Task 5.1 — Complete Trade Record

Extend the existing Forex lifecycle/audit architecture so that one completed trade can reconstruct the complete strategic story.

Target record:

```text
symbol
side
CBDR cycle
CBDR body
bias
sweep
sweep level
MSS/CHOCH if represented
FVG
EQ
entry
initial SL
initial TP
RR
risk
lot
DD/risk multiplier
trailing steps
exit
exit reason
PnL
realized R
order/deal/position IDs
timestamps
```

Preferred design:

```text
ONE TRADE = ONE FORENSIC RECORD
```

Do not create a parallel state architecture if existing `TradeLifecycle` / `AuditChain` can be extended.

### Task 5.2 — Trade History Compatibility

Evaluate whether a `trades_history.jsonl`-style artifact adds real value to Forex.

If implemented:

- one completed trade per JSONL record
- machine-readable
- restart-safe
- no duplicated trailing entries caused by repeated identical fingerprints

---

## PRIORITY 6 — LIVE STATE / SNAPSHOT

### Task 6.1 — Runtime Snapshot

Evaluate whether existing `StateStore` is sufficient.

Only add a `live_state` artifact if there is a genuine missing capability.

Target visibility:

```text
account
symbols
last processed bar
CBDR
bias
sweep
FVG
position
SL
TP
trailing
risk
connection
runtime state
```

Do not create a second state system unnecessarily.

### Task 6.2 — Visual Trade Forensics

DESIGN ONLY for now.

Eventually support:

```text
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

---

## PRIORITY 7 — WATCHDOG

### Task 7.1 — Stuck-State Detection

Watchdog may:

```text
DETECT
LOG
ALERT
SAFE MODE
```

It must NOT silently mutate the strategy state machine or force:

```text
STUCK → ACTIVE
```

without a dedicated evidence-backed design.

---

## PRIORITY 8 — RESEARCH / PRODUCTION PARITY

### Task 8.1 — Protect Research Semantics

Do not modify:

```text
C v1.0
C v1.1
StrategyRuntime
FVG
EQ
Sweep
CBDR
Trailing
Risk
```

unless a targeted regression proves an actual defect.

### Task 8.2 — Live/Research Parity

Any runtime change affecting market-data or strategy semantics must preserve established live/backtest parity.

Existing parity and chronology work remains authoritative.

---

# IMPLEMENTATION RULE

Execute tasks ONE AT A TIME.

For every task:

```text
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

# PHASE 3 — MEMORY-BANK CHECKPOINT

After repository cleanup and after creating/updating the task list, update the central project memory.

Primary files:

```text
memory-bank/activeContext.md
memory-bank/progress.md
```

Record at minimum:

```text
current repository state
current HEAD
cleanup performed
native Windows MT5 status
DEMO execution proof
runtime smoke proof
live polling proof
current task-list location
next single task
known unresolved issues
```

Do NOT invent completion status.

The memory-bank must reflect actual validated state only.

---

# PHASE 4 — FINAL REPORT

Return:

```text
1. Cleanup completed
2. Deleted files
3. Preserved files
4. Repository test result
5. Task list path
6. Memory-bank files updated
7. Current validated Forex status
8. First next implementation task
9. Unresolved issues
```

Do not start Task 0.1 automatically.

After the report, STOP.