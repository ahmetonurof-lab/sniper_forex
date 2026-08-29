# FOREX OBSERVABILITY ACTION PLAN

## 1. Reference

### Crypto Sniper Implementation Files Examined

| File | Purpose | Key Capability |
|------|---------|----------------|
| `src/bot.py` | Main orchestrator | Startup warmup, ATR build, bias latch restore, watchdog |
| `src/event_log.py` | Structured event log | Daily JSONL files, 14-day retention, event taxonomy |
| `src/paper_trade_logger.py` | Trade lifecycle log | Structured JSONL, schema versioning, run IDs |
| `src/state_manager.py` | Persistent daily state | Trade quotas, sweep dedup, bias latch, FileLock |
| `src/state_writer.py` | Live state snapshot | Per-symbol state, CBDR, sweep, FVG, position, SL/TP, trailing |
| `src/trading/console_reporter.py` | Console display | State dedup, session status, sweep/FVG/position display |
| `src/trading/recovery_manager.py` | Startup recovery | Position reconciliation, ghost cleanup, orphan detection |
| `src/trading/user_data_handler.py` | WS user data | Order updates, position changes |
| `src/session.py` | Session/CBDR engine | Body tracking, sweep detection, bias lock |
| `src/retrace_state.py` | FVG/retrace state | State machine, trigger management |
| `src/indicators.py` | ATR calculation | Wilder's ATR, true range |
| `src/risk_manager.py` | Risk management | Dynamic multiplier, early London, CBDR matrix |

### Crypto Log Artefact Classification

| Artefact | Classification | Reason |
|----------|----------------|--------|
| `paper_trade.log` | PRODUCTION RUNTIME | Main log file with rotation |
| `events_YYYY-MM-DD.jsonl` | PRODUCTION RUNTIME | Daily event log, auto-cleanup |
| `live_state.json` | PRODUCTION RUNTIME | Real-time state snapshot, overwritten each bar |
| `trade_state.json` | PERSISTENT AUDIT | Daily trade state, survives restarts |
| `active_fvg.json` | PERSISTENT AUDIT | FVG state for recovery |
| `risk_state.json` | PERSISTENT AUDIT | Risk manager state |
| `trades_history.jsonl` | PERSISTENT AUDIT | Completed trades |
| `audit_proc.txt` | TEMPORARY DIAGNOSTIC | Process-level debug output |
| `audit_proc_clean.txt` | TEMPORARY DIAGNOSTIC | Cleaned process debug |
| `audit_resources.txt` | TEMPORARY DIAGNOSTIC | Resource monitoring |
| `audit_stdout_clock.txt` | TEMPORARY DIAGNOSTIC | Clock drift detection |
| `audit_ts.txt` | HISTORICAL FORENSIC | Timestamp analysis |
| `audit_errors.txt` | HISTORICAL FORENSIC | Error pattern analysis |
| `p1_*.txt`, `p1_flow*.txt` | HISTORICAL FORENSIC | Debug session artifacts |

---

## 2. Current Forex State

### Existing Mechanisms

| Mechanism | File | Status |
|-----------|------|--------|
| Persistent logging (rotating) | `src/live/persistent_log.py` | ✅ Working |
| AuditChain (in-memory + JSONL flush) | `src/live/audit.py` | ✅ Working |
| StateStore (per-symbol JSON) | `src/live/state.py` | ✅ Working |
| PortfolioDD (realized PnL journal) | `src/live/portfolio_dd.py` | ✅ Working |
| TradeLifecycle (exit deal processing) | `src/live/trade_lifecycle.py` | ✅ Working |
| PositionManager (MT5 position mirror) | `src/live/position_manager.py` | ✅ Working |
| RiskManager (signal gating) | `src/live/risk.py` | ✅ Working |
| SafetyMonitor (composite guards) | `src/live/safety.py` | ✅ Working |
| Reconciliation (broker vs local) | `src/live/reconciliation.py` | ✅ Working |
| Recovery (restart state restore) | `src/live/recovery.py` | ✅ Working |

### Current Gaps

| Gap | Impact | Severity |
|-----|--------|----------|
| No startup inventory log | Cannot see what happened at startup | HIGH |
| No per-symbol bootstrap snapshot | Cannot verify data quality per symbol | HIGH |
| No CBDR state visibility | Cannot see if CBDR is tracking/locked/biased | HIGH |
| No warmup completion proof | Cannot verify strategy readiness | HIGH |
| No ATR readiness logging | Cannot verify ATR calculation | MEDIUM |
| No strategy state display | Cannot see sweep/FVG/signal progress | HIGH |
| No position/SL/TP visibility | Cannot see open position state | MEDIUM |
| No persistent error log | Errors only in general log | MEDIUM |
| No state dedup/display | Console spam, no structured view | MEDIUM |
| No "why no signal" explanation | Cannot diagnose signal absence | HIGH |
| No connection health logging | Cannot see reconnection events | MEDIUM |
| No timestamp/clock visibility | Cannot detect clock drift | LOW |
| No reconciliation logging | Cannot see broker/local mismatches | MEDIUM |

---

## 3. Proven Reusable Crypto Patterns

### Pattern 1: Startup Inventory Log
**Crypto**: `_warmup_cbdr()` logs ATR, CBDR body, lock status, sweep status
**Forex equivalent**: Add to `M1CandleFeed.warmup()` or `StrategyRuntime.warmup()`
**Value**: Immediate visibility into data quality and readiness

### Pattern 2: Structured Event Log (Daily JSONL)
**Crypto**: `event_log.py` with `events_YYYY-MM-DD.jsonl`, 14-day retention
**Forex equivalent**: Extend `AuditChain` with daily file rotation and retention
**Value**: Persistent, queryable event history

### Pattern 3: Live State Snapshot
**Crypto**: `state_writer.py` writes `live_state.json` every bar
**Forex equivalent**: Extend `StateStore` to write full runtime snapshot
**Value**: Real-time state visibility without log parsing

### Pattern 4: Console State Display with Dedup
**Crypto**: `ConsoleReporter` with `display_session_status()`, `display_sweep_status()`, `display_fvg_status()`
**Forex equivalent**: Add display methods to a new `ConsoleReporter` class
**Value**: Immediate human-readable progress indication

### Pattern 5: ATR Comparison Logging
**Crypto**: `_warmup_cbdr()` logs fake vs real ATR with ratio
**Forex equivalent**: Add to warmup in `StrategyRuntime`
**Value**: Verifies ATR calculation correctness

### Pattern 6: Bias Latch Persistence
**Crypto**: `mark_bias_locked()` / `load_bias_lock()` in `state_manager.py`
**Forex equivalent**: Already in `SessionManager` but not persisted to disk
**Value**: Restart-proof bias state

### Pattern 7: Watchdog for Stuck States
**Crypto**: `_orphan_check_counter` with 90s stuck status detection
**Forex equivalent**: Add to main loop
**Value**: Prevents silent failures

### Pattern 8: Per-Symbol Bootstrap Snapshot
**Crypto**: `_warmup_cbdr()` logs per-symbol ATR, CBDR body, lock status
**Forex equivalent**: Add to warmup chain
**Value**: Per-symbol data quality verification

### Pattern 9: Trade Lifecycle Event Log
**Crypto**: `paper_trade_logger.py` with structured JSONL
**Forex equivalent**: Extend `AuditChain` with trade-specific events
**Value**: Complete trade lifecycle traceability

### Pattern 10: "Why No Signal" Logging
**Crypto**: `display_session_status()`, `display_sweep_status()`, `display_fvg_status()` show exact blocking reason
**Forex equivalent**: Add similar display/logging to strategy loop
**Value**: Diagnoses signal absence

---

## 4. Forex Gaps

### Critical Gaps (MUST HAVE)

| # | Gap | Current State | Required State |
|---|-----|---------------|----------------|
| 1 | Startup inventory | No startup log | Log: MT5 version, account, symbols, data fetched |
| 2 | Per-symbol bootstrap | No per-symbol data log | Log: M1 count, M15 count, duplicates, missing per symbol |
| 3 | CBDR state visibility | No CBDR logging | Log: CBDR key, body high/low, lock status, bias |
| 4 | Warmup completion | Silent warmup | Log: Warmup bars used, ATR value, start index |
| 5 | Strategy state display | No state display | Log: Session, sweep status, FVG scan status |
| 6 | "Why no signal" | No blocking reason | Log: Exact reason for each bar (CBDR unlocked, no sweep, no FVG, etc.) |
| 7 | Open position visibility | No position log | Log: Entry, SL/TP, trailing count, upnl |
| 8 | Persistent error log | Errors in general log | Separate error-only log with context |

### Important Gaps (SHOULD HAVE)

| # | Gap | Current State | Required State |
|---|-----|---------------|----------------|
| 9 | Daily event log rotation | AuditChain single file | Daily files with retention |
| 10 | Live state snapshot | StateStore per-symbol only | Full runtime snapshot including strategy state |
| 11 | Connection health | No connection events | Log: connect, disconnect, reconnect |
| 12 | Reconciliation logging | Silent reconciliation | Log: broker/local mismatches |
| 13 | Timestamp/clock visibility | No clock logging | Log: server time, UTC, drift detection |
| 14 | Recovery logging | No recovery events | Log: positions recovered, state restored |

### Nice to Have

| # | Gap | Current State | Required State |
|---|-----|---------------|----------------|
| 15 | Trade lifecycle JSONL | Audit only | Structured trade lifecycle events |
| 16 | Console state dedup | No console output | Deduplicated state display |
| 17 | Watchdog | No stuck detection | Detect stuck positions/orders |
| 18 | ATR comparison | No ATR verification | Log ATR calculation details |

### Not Applicable

| Feature | Reason |
|---------|--------|
| FileLock-based state | Forex runs single-process, no concurrent access |
| Ghost position cleanup | MT5 positions are authoritative, no ghost concept |
| Orphan order detection | MT5 orders are managed by broker, no orphan concept |
| User data WebSocket | Forex uses polling, not WebSocket |

---

## 5. MUST HAVE

### 5.1 Startup Inventory Log

**Problem**: When Forex starts, we cannot see what happened.
**Solution**: Add comprehensive startup logging.

**Files**: `src/live/live_runner.py`, `src/live/persistent_log.py`
**Expected output**:
```
[STARTUP] MT5 build=6140 account=53012914 server=ICMarketsSC-Demo balance=9990.42
[STARTUP] Symbols: BTCUSD (M1=3030, M15=205, dup=0, miss=0)
[STARTUP] Warmup: bars=101 ATR=189.43 start_idx=101
[STARTUP] CBDR: key=2026-08-29 body=[0.0-Inf] locked=False bias=neutral
[STRATEGY] Ready — waiting for first signal
```
**Validation**: Run bot, check log file for startup section

### 5.2 Per-Symbol Bootstrap Snapshot

**Problem**: Cannot verify data quality per symbol.
**Solution**: Log per-symbol data acquisition results.

**Files**: `src/live/candle_feed.py`
**Expected output**:
```
[DATA] BTCUSD M1: fetched=3030 oldest=2026-08-27T11:27 newest=2026-08-29T15:00
[DATA] BTCUSD M15: aggregated=205 duplicates=0 missing=0
```
**Validation**: Check log matches MT5 terminal data

### 5.3 CBDR State Visibility

**Problem**: Cannot see if CBDR is tracking, locked, or biased.
**Solution**: Log CBDR state on each bar when changed.

**Files**: `src/live/strategy_runtime.py`, `src/live/live_runner.py`
**Expected output**:
```
[CBDR] BTCUSD key=2026-08-29 body=[77500.00-78200.00] locked=False bias=neutral
[CBDR] BTCUSD LOCKED body=[77500.00-78200.00] bias=bullish (sweep@78250.00)
```
**Validation**: Verify CBDR state matches price action

### 5.4 Warmup Completion Proof

**Problem**: Cannot verify strategy readiness.
**Solution**: Log warmup completion with metrics.

**Files**: `src/live/strategy_runtime.py`
**Expected output**:
```
[WARMUP] BTCUSD complete: bars=101 ATR=189.43 start_idx=101 session_ready=True
```
**Validation**: Check log for warmup completion line

### 5.5 Strategy State Display

**Problem**: Cannot see sweep/FVG/signal progress.
**Solution**: Log strategy state changes.

**Files**: `src/live/strategy_runtime.py`
**Expected output**:
```
[SESSION] BTCUSD LONDON 15:15 UTC CBDR: BODY TRACKING...
[SWEEP] BTCUSD SWEEP: BEKLENIYOR | CBDR: [77500.00-78200.00]
[SWEEP] BTCUSD SWEEP: DETECTED | BULLISH | [78250.00]
[FVG] BTCUSD GAP_SCAN | MIN_SIZE: 189.43 | ARANIYOR...
[FVG] BTCUSD FVG:[78100.00-78200.00] | HAZIR | CLOSE: 78150.00
```
**Validation**: Verify state transitions match price action

### 5.6 "Why No Signal" Explanation

**Problem**: Cannot diagnose why no trades occur.
**Solution**: Log blocking reason for each bar.

**Files**: `src/live/live_runner.py`
**Expected output**:
```
[BAR] BTCUSD 15:15: CBDR unlocked — skip
[BAR] BTCUSD 15:30: CBDR locked, sweep pending — skip
[BAR] BTCUSD 15:45: Sweep confirmed, no FVG — skip
```
**Validation**: Check log for blocking reasons

### 5.7 Open Position Visibility

**Problem**: Cannot see open position state.
**Solution**: Log position state on each bar.

**Files**: `src/live/trade_lifecycle.py`
**Expected output**:
```
[POSITION] BTCUSD LONG @ 78150.00 SL=77950.00 TP=78550.00 TRAIL: 2x UPNL: +12.50
```
**Validation**: Verify position state matches MT5 terminal

### 5.8 Persistent Error Log

**Problem**: Errors mixed with general log.
**Solution**: Separate error-only log.

**Files**: `src/live/persistent_log.py`
**Expected output**: `logs/errors.log` with only ERROR level messages
**Validation**: Trigger an error, check errors.log

---

## 6. SHOULD HAVE

### 6.1 Daily Event Log Rotation
- Extend `AuditChain` with daily file rotation
- 14-day retention
- Files: `logs/audit_YYYY-MM-DD.jsonl`

### 6.2 Live State Snapshot
- Full runtime state in `state/live_state.json`
- Updated each bar
- Includes: balance, CBDR, sweep, FVG, position, SL/TP, trailing

### 6.3 Connection Health Logging
- Log MT5 connect/disconnect/reconnect events
- Files: `src/live/audit.py`

### 6.4 Reconciliation Logging
- Log broker/local state mismatches
- Files: `src/live/reconciliation.py`

### 6.5 Timestamp/Clock Visibility
- Log server time, UTC, drift detection
- Files: `src/live/clock.py`

### 6.6 Recovery Logging
- Log positions recovered at startup
- Files: `src/live/recovery.py`

---

## 7. Explicitly NOT Transferring

| Feature | Reason |
|---------|--------|
| FileLock-based state | Single-process, no concurrent access needed |
| Ghost position cleanup | MT5 positions are authoritative |
| Orphan order detection | MT5 manages orders, no orphan concept |
| User Data WebSocket handler | Polling-based, not WebSocket |
| Process resource logging | Not needed for production |
| ATR fake vs real comparison | Already using correct Wilder's ATR |
| Paper trade separate logger | Forex uses real MT5, no paper mode |
| Multiple output directories | Single output directory sufficient |
| Bias latch separate persistence | Already in SessionState, just needs logging |

---

## 8. Implementation Order

### Step 1: Add Startup Inventory Logging
**Files**: `src/live/live_runner.py`
**Changes**: Add startup log after MT5 initialize and warmup
**Expected output**: Startup section in log file
**Validation**: Run bot, verify startup log exists
**Risk**: Low — additive only
**Rollback**: Remove log lines

### Step 2: Add Per-Symbol Bootstrap Snapshot
**Files**: `src/live/candle_feed.py`
**Changes**: Add logging to `warmup()` and `fetch_m1()`
**Expected output**: Per-symbol data quality log
**Validation**: Run bot, verify data log matches MT5
**Risk**: Low — additive only
**Rollback**: Remove log lines

### Step 3: Add CBDR State Visibility
**Files**: `src/live/strategy_runtime.py`, `src/live/live_runner.py`
**Changes**: Add CBDR state logging on changes
**Expected output**: CBDR tracking/lock/bias log
**Validation**: Run bot, verify CBDR state transitions
**Risk**: Low — additive only
**Rollback**: Remove log lines

### Step 4: Add Warmup Completion Proof
**Files**: `src/live/strategy_runtime.py`
**Changes**: Add warmup completion log
**Expected output**: Warmup completion line with metrics
**Validation**: Run bot, verify warmup log
**Risk**: Low — additive only
**Rollback**: Remove log line

### Step 5: Add Strategy State Display
**Files**: `src/live/strategy_runtime.py`
**Changes**: Add session/sweep/FVG state logging
**Expected output**: Strategy progress log
**Validation**: Run bot, verify state transitions
**Risk**: Low — additive only
**Rollback**: Remove log lines

### Step 6: Add "Why No Signal" Logging
**Files**: `src/live/live_runner.py`
**Changes**: Add blocking reason to `on_bar()` result
**Expected output**: Blocking reason for each bar
**Validation**: Run bot, verify blocking reasons
**Risk**: Low — additive only
**Rollback**: Remove log lines

### Step 7: Add Open Position Visibility
**Files**: `src/live/trade_lifecycle.py`
**Changes**: Add position state logging
**Expected output**: Position state log
**Validation**: Run bot with open position, verify log
**Risk**: Low — additive only
**Rollback**: Remove log lines

### Step 8: Add Persistent Error Log
**Files**: `src/live/persistent_log.py`
**Changes**: Add separate error log handler
**Expected output**: `logs/errors.log`
**Validation**: Trigger error, check errors.log
**Risk**: Low — additive only
**Rollback**: Remove handler

### Step 9: Add Daily Event Log Rotation
**Files**: `src/live/audit.py`
**Changes**: Extend AuditChain with daily rotation and retention
**Expected output**: `logs/audit_YYYY-MM-DD.jsonl`
**Validation**: Run bot across midnight, verify rotation
**Risk**: Medium — changes AuditChain behavior
**Rollback**: Revert AuditChain changes

### Step 10: Add Live State Snapshot
**Files**: `src/live/state.py`
**Changes**: Add full runtime snapshot writer
**Expected output**: `state/live_state.json`
**Validation**: Run bot, verify live_state.json
**Risk**: Low — additive only
**Rollback**: Remove writer

### Step 11: Add Connection Health Logging
**Files**: `src/live/audit.py`
**Changes**: Add connection event logging
**Expected output**: Connect/disconnect/reconnect events
**Validation**: Disconnect/reconnect MT5, verify events
**Risk**: Low — additive only
**Rollback**: Remove event logging

### Step 12: Add Reconciliation Logging
**Files**: `src/live/reconciliation.py`
**Changes**: Add mismatch logging
**Expected output**: Reconciliation results
**Validation**: Create mismatch scenario, verify log
**Risk**: Low — additive only
**Rollback**: Remove log lines

---

## 9. Files/Functions Expected to Change

| File | Function | Change Type |
|------|----------|-------------|
| `src/live/persistent_log.py` | `setup_logging()` | Add error handler |
| `src/live/candle_feed.py` | `warmup()`, `fetch_m1()` | Add logging |
| `src/live/strategy_runtime.py` | `warmup()`, `on_bar()` | Add logging |
| `src/live/live_runner.py` | `__init__()`, `on_bar()` | Add startup + bar logging |
| `src/live/trade_lifecycle.py` | `register_open_context()`, `record_exit_deal()` | Add position logging |
| `src/live/audit.py` | `AuditChain` | Add daily rotation |
| `src/live/state.py` | `StateStore` | Add full snapshot |
| `src/live/reconciliation.py` | `reconcile()` | Add mismatch logging |
| `src/live/clock.py` | `server_to_utc_historical()` | Add drift logging (SHOULD HAVE) |

---

## 10. Validation for Each Step

### Step 1: Startup Inventory
```bash
python phase4_smoke.py
grep -E "^\[STARTUP\]" logs/smoke_test.log
# Expected: MT5 build, account, symbols, warmup info
```

### Step 2: Bootstrap Snapshot
```bash
grep -E "^\[DATA\]" logs/smoke_test.log
# Expected: Per-symbol M1/M15 counts, duplicates, missing
```

### Step 3: CBDR State
```bash
grep -E "^\[CBDR\]" logs/smoke_test.log
# Expected: CBDR tracking, lock, bias transitions
```

### Step 4: Warmup Completion
```bash
grep -E "^\[WARMUP\]" logs/smoke_test.log
# Expected: Warmup completion line with metrics
```

### Step 5: Strategy State
```bash
grep -E "^\[SESSION\]|\[SWEEP\]|\[FVG\]" logs/smoke_test.log
# Expected: Strategy progress lines
```

### Step 6: Blocking Reasons
```bash
grep -E "^\[BAR\]" logs/smoke_test.log
# Expected: Blocking reason for each bar
```

### Step 7: Position Visibility
```bash
grep -E "^\[POSITION\]" logs/smoke_test.log
# Expected: Position state lines
```

### Step 8: Error Log
```bash
# Trigger an error
cat logs/errors.log
# Expected: Error message with context
```

### Step 9: Daily Event Log
```bash
ls -la logs/audit_*.jsonl
# Expected: Daily audit files
```

### Step 10: Live State
```bash
cat state/live_state.json
# Expected: Full runtime state
```

---

## 11. Rollback / Safety

### General Principles
1. **Additive only**: All changes are additive — no existing behavior modified
2. **Log-only**: Changes only add logging — no strategy/execution changes
3. **Independent steps**: Each step can be rolled back independently
4. **No production risk**: Changes don't affect trading logic

### Rollback Procedure
```bash
# Revert specific file
git checkout HEAD -- src/live/live_runner.py

# Revert all changes
git checkout HEAD -- src/live/

# Verify clean state
git status
```

### Safety Checklist
- [ ] No strategy logic modified
- [ ] No execution logic modified
- [ ] No risk calculation modified
- [ ] No state machine modified
- [ ] Only `log.info()`, `log.warning()`, `log.error()` calls added
- [ ] No new dependencies added
- [ ] All changes are behind existing `log` objects
- [ ] No performance impact (logging is async-friendly)

---

## Appendix A: Crypto Event Taxonomy

| Event | Producer | Trigger | Payload | Destination |
|-------|----------|---------|---------|-------------|
| `entry` | bot.py `_try_entry()` | Entry order sent | side, entry_price, sl, tp, qty | events_YYYY-MM-DD.jsonl |
| `post_entry_check_failed` | bot.py `_try_entry()` | SL/TP sanity fail | sl_ok, tp_ok, side, entry_price, qty | events_YYYY-MM-DD.jsonl |
| `sl_placed` | protection_lifecycle.py | SL order placed | sl_id, symbol, price | paper_trade.log |
| `tp_placed` | protection_lifecycle.py | TP order placed | tp_id, symbol, price | paper_trade.log |
| `trail_candidate` | trailing_manager.py | New trail level | new_sl, reason, bar_index | paper_trade.log |
| `trade_closed` | exit_lifecycle.py | Position closed | result, exit_price, pnl | paper_trade.log |

## Appendix B: Forex Current Audit Events

| Event | Producer | Trigger | Payload | Destination |
|-------|----------|---------|---------|-------------|
| `CANDLE` | live_runner.py | Bar processed | bar timestamp, close | AuditChain |
| `SIGNAL` | live_runner.py | Signal generated | side, entry, sl, tp | AuditChain |
| `RISK` | live_runner.py | Risk evaluation | approved, reason, multiplier | AuditChain |
| `ORDER` | live_runner.py | Order sent | sent, filled, retcode, lot | AuditChain |
| `FILL` | live_runner.py | Fill confirmed | order_id, deal_id, price | AuditChain |
| `POSITION` | live_runner.py | Position opened | position_id, entry, volume, risk | AuditChain |
| `EXIT` | live_runner.py | Position closed | deal_id, position_id, status, cash, pnl_r | AuditChain |
| `STARTUP` | live_runner.py | Session start | phase, mode | AuditChain |
| `SHUTDOWN` | live_runner.py | Session end | reason | AuditChain |
| `MT5_CONNECT` | live_runner.py | MT5 connected | result | AuditChain |
| `ERROR` | live_runner.py | Exception | error message | AuditChain |

## Appendix C: Forex Missing Audit Events

| Event | Required Trigger | Required Payload |
|-------|------------------|------------------|
| `WARMUP_COMPLETE` | Warmup done | bars, atr, start_idx |
| `CBDR_UPDATE` | CBDR state change | key, body_high, body_low, locked, bias |
| `SWEEP_DETECTED` | Sweep found | direction, level, bar_index |
| `FVG_FOUND` | FVG detected | top, bottom, direction, bar_index |
| `BLOCKED_REASON` | Signal blocked | reason, bar_timestamp |
| `POSITION_UPDATE` | Position state change | sl, tp, trailing_count, upnl |
| `RECONNECT` | MT5 reconnected | timestamp |
| `RECONCILE` | Reconciliation result | broker_count, local_count, mismatches |
