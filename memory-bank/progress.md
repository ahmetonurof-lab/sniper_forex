# Progress — Per-Experiment Log

> Companion to `memory-bank/activeContext.md` (the control panel).
> This file is the chronological per-experiment log for the MaxDD research
> line. Every experiment entry MUST contain: what was tested, which engine,
> which dataset, isolated variable, result, decision, next test.
> Last updated: 2026-08-29 (NATIVE WINDOWS MT5 PROVEN — Phase 2/3/4/5 PASS, repository cleanup complete, runtime hardening task list created).

### NATIVE WINDOWS MT5 CHECKPOINT (2026-08-29)

- **What was done**: Proven native Windows → MT5 → IC Markets DEMO execution path
- **Environment**: Python 3.12.2, MetaTrader5 5.0.6147, MT5 build 6140
- **Phases verified**:
  - Phase 2: `mt5.initialize()`, `account_info()`, `symbol_info_tick()` — PASS
  - Phase 3: BTCUSD DEMO `order_check()` → `order_send()` → SL/TP → close — PASS
  - Phase 4: Runtime smoke (signal_only=True, 50 bars processed) — PASS
  - Phase 5: Live polling harness (new M1CandleFeed, no duplicate bars) — PASS
- **Repository cleanup**: 12 obsolete files deleted (p1 debug, rollback logs, nul, old test harness)
- **New documents**:
  - `docs/FOREX_RUNTIME_HARDENING_TASKS.md` — 24 ordered tasks across 8 priorities
  - `docs/FOREX_OBSERVABILITY_ACTION_PLAN.md` — Crypto reference audit + gap analysis
  - `docs/FOREX_HARDENING_REPORT.md` — Comprehensive hardening report
- **Current HEAD**: d87d1e1 (persistent logging)
- **Next step**: Task 0.1 — Startup Broker State Snapshot (awaiting user direction)

---

### MT5 REAL CHECKPOINT (2026-08-28)
- LIVE PRODUCTION PATH TRACE: src/main.py → test_mt5_connection.py → MetaTrader5.initialize() → SignalRunner(mt5=) → M1CandleFeed.fetch_m1 → resample_15m → StrategyRuntime
- execution.py: direct MetaTrader5.order_send (injectable mt5=) — no abstraction/factory wrapper needed
- Missing live operations: (1) history/deals read in signal path, (2) native TRADE_ACTION_SLTP MT5 modification request
- Verification: Mock PASS (126), Static PASS (caller→callee + git diff CLEAN), Real MT5 NOT YET — connection-only gate pending MT5 credentials
- Architecture decision: minimal addition only (no new abstraction)
- Status: BLOCKED — awaiting MT5 connection credentials for manual gate 1

---

---

### CBDR_TIME_SEMANTIC_ALIGNMENT (2026-09-01) — Hakem Direktifi

- **Hipotez**: Research (server-time) vs production (UTC) zaman-dönüşümü CBDR sinyal-zamanlamasını ve trade sonuçlarını değiştirir.
- **Değişken**: Tek değişken — timestamp dönüşümü (`server_to_utc_historical`). Engine AYNI (`run_test_a`, frozen v1.0).
- **Dataset**: 6 major × 15m feather (~65k bar/sembol, 2.7 yıl).
- **Koşumlar**: 6 sembol × 2 run = 12 koşum.

> ⚠️ **HAKEM TAHKİMİ (2026-09-01) — DENEY YORUMU REVİZE EDİLDİ:**
> Forensic tespit: `data/icmarket_feather/` = **UTC** (server-time DEĞİL). Kanıt: +0h=%100 OHLC
> match, Cuma 21:56 kapanış + Cumartesi 0 bar + Pazar 22:01 açılış (yalnızca UTC imzası).
> `server_to_utc_historical` girdinin UTC olduğunu bilmez; tek naif datetime alır, -2/-3h kaydırır.
> → RUN_A fiilen **UTC penceresi** çalıştırdı; RUN_B **UTC'yi ikinci kez kaydırdı** (double-conversion).
> → A/B farkı time-semantik mismatch değil, **sahte dönüşüm artefaktıdır**.
> **Sonuçlar MASADA TUTULUR, karar-kaynağı sayılmaz.** Detay: `docs/CBDR_TIME_SEMANTIC_ALIGNMENT_RAPORU.md` §9.4.
> TAG v1.1 KORUNUR, benchmark valid, production pipeline valid (§9.4 parity açıklaması).

#### SONUÇLAR

**RUN_A (server-time, canonical):** 2302T / WR 69.4% / +2875.00R / PF 5.08 / DD 8.00R (2.73%)
- **Fingerprint: BİREBİR EŞLEŞME ✓** (2302T / +2875.00R / WR 69.37%)

**RUN_B (UTC, production):** 2259T / WR 68.0% / +2946.42R / PF 5.07 / DD 9.87R (5.38%)

**Sembol-bazlı A/B farkı:**
| Sembol | RUN_A | RUN_B | ΔTrade | ΔPnL |
|--------|-------|-------|--------|------|
| EURUSD | 407T/+520.61R | 397T/+533.90R | -10 | +13.29R |
| AUDUSD | 388T/+443.48R | 382T/+503.20R | -6 | +59.72R |
| GBPUSD | 378T/+431.84R | 378T/+492.91R | 0 | +61.07R |
| GBPJPY | 394T/+391.21R | 380T/+348.82R | -14 | -42.39R |
| USDCAD | 366T/+605.77R | 366T/+668.72R | 0 | +62.95R |
| USDJPY | 369T/+482.10R | 356T/+398.86R | -13 | -83.24R |

**CRITICAL — Signal Timing Δ (IN_WINDOW entry):**
- Her 6 sembolde de RUN_B'de IN_WINDOW entry sayısı düştü (USDCAD: -34, GBPJPY: -19)
- Toplam IN_WINDOW: RUN_A 430 → RUN_B 340 (-90 entry, -20.9%)
- 3 saatlik yaz saati kayması (server→UTC) CBDR penceresini 16:00→22:00 UTC'ye çeker, bu da bazı geçiş bölgesi sinyallerini OUT_WINDOW'a iter

**Verdict (revised per hakem arbitration 2026-09-01):**
- Deneyin A/B farkı **time-semantik karşılaştırması GEÇERSİZ** — iki run da UTC veriyle çalıştı, RUN_B double-conversion artefaktı üretti
- Signal timing shift mutlak değerleri anlamsız; kıyas ancak gerçek server-time veriyle (MT5 canlı stream) veya bilinçli dönüştürülmüş bir UTC→server dataset ile yapılabilir
- **production pipeline valid**: MT5 canlı stream = gerçek server-time, `server_to_utc_historical` doğru çalışır
- **research pipeline valid**: feather'ı UTC olarak okur, dönüşüm uygulamaz
- **Parity restored**: iki pipeline da aynı UTC penceresine oturur (research: UTC feather → UTC CBDR 19→01; production: server-time MT5 → server_to_utc_historical → UTC CBDR 19→01)

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

### PHASE 4 — RISK + POSITION SIZING (COMPLETE 2026-08-27)

- **What was done:** Built the risk engine + lot sizing for the live runtime.
- **Files changed:**
  - `src/live/risk.py` — NEW, `RiskManager` + `Account` + `RiskDecision`.
    Pure/injectable gatekeeper (no MT5 dependency).
  - `src/live/sizing.py` — NEW, `PositionSizer` + `ContractSpec` + `SizingResult`.
  - `tests/test_live_risk_sizing.py` — NEW, 12 synthetic unit tests.
- **Key design decisions:**
  - Risk checks (any fail → `approved=False`, `blocked=True`, reason + checks
    logged): stop_distance<=0, stop below broker stops_level, excessive spread
    (ratio vs stop distance), risk-per-trade ceiling, exposure cap (notional as
    a multiple of equity, leverage-style).
  - Lot = balance*risk_per_trade / (ticks*tick_value); rounded down to
    volume_step; clamped to [volume_min, volume_max].
  - Stop distance rounded to symbol digits to avoid float drift (e.g.
    0.0050000...115 → 0.005).
  - `RISK_PER_TRADE=0.003` from `experiment/config.py` is the default.
- **Tests run:**
  - `python -m pytest tests/test_live_risk_sizing.py` → 12/12 PASS.
  - `python -m pytest tests/` → 132/132 PASS.
- **Result:** Lot math correct (standard MT5 formula); volume min/max/step
  respected; risk fail → NO trade (blocked + logged) per acceptance criteria.
- **Frozen engines:** `main_research_c_v1_0.py` + `main_research_d_v1_0.py` git
  diff CLEAN (verified). No strategy behavior changed.
- **Decision:** PHASE 4 COMPLETE. Proceed to PHASE 5.
- **Next task:** PHASE 5 — EXECUTION (order execution engine: order_check,
  order_send, market order, SL/TP, magic number, comment, duplicate protection,
  rejection handling, retry; `src/live/execution.py`). Execution DISABLED by
  default — SIGNAL_ONLY / DRY_RUN must NOT send real orders.

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

### Exp C — DD-Based Risk Scaling (C v1.0) — PROMOTED (2026-08-28, corrected)

- **What tested:** scale per-trade risk by current realized portfolio DD
  (post-hoc overlay). Thresholds: DD>2R x0.50, DD>4R x0.25, DD>6R pause.
- **Engine:** C v1.0 (`experiment/main_research_c_v1_0.py`, UNTOUCHED).
- **Dataset:** 6 majors, 2.7Y, 15m bars, full.
- **Isolated variable:** post-hoc per-trade pnl_r multiplier based on
  realized portfolio drawdown at trade entry. NO lookahead (DD from
  realized exits only). Single lever.
- **Result (corrected 2026-08-28, after cross-symbol `entry_ts` bug
  fix):** **2 paused** (GBPJPY id=96, USDJPY id=82). 2300T /
  **+2766.91R** / AvgR **+1.2026** / **PF 5.13** / MaxDD(R) **4.71** /
  **MaxDD% 2.19**. Scaling event distribution: x1.0 = 2186, x0.5 = 99,
  x0.25 = 15, paused = 2. MaxDD(R) reduced (4.71 < 8.00) because
  per-symbol risk reduction shrinks both the equity peak-to-trough
  step and its pre-existing single-trade step.
- **INVALIDATED old result (pre-fix):** the previous
  `2302T / 0 paused / +2823-ish TotalR / MaxDD(R) 8.00 / MaxDD% 1.85`
  numbers were an artifact of a **cross-symbol `entry_ts_map` bug**
  in this file (the map was keyed only on `trade_id`; 1895/2302 trades
  received cross-symbol-contaminated entry_ts because `run_test_a`
  resets per-symbol `trade_counter` to 0 on every call). See
  `## C v1.1 PROMOTION (2026-08-28)` below for the fix details.
- **Decision:** **PROMOTED → C v1.1** (2026-08-28). The MaxDD% lever
  is now the canonical behaviour of `experiment/main_research_c_v1_1.py`.
  The corrected `exp_maxdd_C_dd_risk_scaling.py` is kept for historical
  / provenance role only; C v1.1 does NOT import it.
- **Next test:** combination tests on C v1.1 / D v1.0, or Phase 3
  Champion Selection.
- **Files:** `experiment/exp_maxdd_C_dd_risk_scaling.py` (corrected);
  `experiment/main_research_c_v1_1.py` (NEW canonical engine);
  `tests/test_main_research_c_v1_1.py` (24 unit tests, all PASS).
- **Outputs:** `results/research/expC_dd_risk_scaling_summary.json`,
  `results/research/expC_dd_risk_scaling_trades.json`,
  `results/research/c_v1_1_summary.json`.

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

---

### REAL-MT5 PARITY REGRESSION FIX (2026-08-28) — COMPLETE

- **What was done:** Closed the Phase 11 demo parity regression by
  fixing two M1-ingest bugs in `src/live/` and adding a regression
  test. Audit-first: no code changes were made until the root cause
  was traced stage-by-stage (report in `memory-bank/activeContext.md`
  "REAL-MT5 PARITY REGRESSION FIX" section).
- **Root cause:**
  1. `SignalRunner._rates_to_bars` and `PaperSession._rates_to_bars`
     treated MT5 `time` as UTC (`pd.Timestamp.utcfromtimestamp(ts)`).
     MT5 reports `time` in server time (UTC+2/3 DST). The +2/3h shift
     re-bucketed the 15m aggregation, dropped <3-bar buckets, and
     pushed some CBDR-window bars out of the 19:00→01:00 window.
  2. `SignalRunner._run_symbol` and `PaperSession.warmup/run_step`
     did not filter the forming M1 via `M1CandleFeed.is_closed_m1`.
     The unfinalized current-minute bar polluted the last 15m bucket.
- **Files changed (this fix):**
  - `src/live/signal_runner.py` — F1 (`server_to_utc` conversion)
    + F2 (`is_closed_m1` filter with `now=_utcnow_naive()`).
  - `src/live/paper.py` — F1 + F2 (same).
  - `tests/test_m1_ingestion_parity.py` — NEW, 8 F1/F2/F3 tests.
  - `scripts/verify_phase11_parity_fix.py` — NEW, 38↔38 head-to-head
    script (canonical `run_test_a` vs live `StrategyRuntime` on the
    EURUSD 2026-06-25 → 2026-08-28 window).
  - `docs/MT5_IMPLEMENTATION_ROADMAP.md` — added "REAL-MT5 PARITY
    REGRESSION FIX" checkpoint.
  - `memory-bank/activeContext.md` + `memory-bank/progress.md` —
    documented.
  - `index.json` — regenerated via `tools/code-index-system/index_builder.py --full`.
- **Isolated variable:** M1 ingestion (timezone + forming-bar filter).
  Strategy logic, ATR, session, FVG, EQ, SL/TP, trailing, exit — all
  unchanged.
- **Tests run:**
  - `pytest tests/test_m1_ingestion_parity.py` → 8/8 PASS.
  - `pytest tests/test_live_signal_runner.py` → 9 PASS, 0 FAIL
    (was 3 FAIL pre-fix, all due to `is_closed_m1` missing `now` arg).
  - `pytest tests/test_live_paper.py` → 23/23 PASS.
  - `pytest tests/` (full suite, slow parity deselected) → 246 PASS,
    1 SKIP, 0 FAIL.
  - `python scripts/verify_phase11_parity_fix.py` → canonical=23,
    live=23, 0 diffs (PARITY PASS).
- **Result:** Parity regression resolved. The first divergence stage
  (M1 timestamp interpretation) is removed. F1+F2+F3 PASS. Frozen C/D
  engines untouched (git diff CLEAN, verified). No research files
  committed. No new abstraction. DD Risk Scaling untouched.
- **Decision:** **PARITY FIX COMPLETE.** Ready for controlled demo
  with real orders pending explicit user approval (parity is no longer
  the blocker).
- **Next task:** Awaiting user direction — research promotion (C v1.1
  with DD scaling), Phase 12 (DD scaling integration), or other.

---

### C v1.1 PROMOTION (2026-08-28) — COMPLETE
>
> **⚠ QUARANTINED 2026-08-31 (arbitration (b), see
> `activeContext.md` TAHKİM section):** The numbers below
> (2300T / +2766.91R / MaxDD 4.71R / 2.19% / PF 5.13 / paused=2) were
> produced by the pre-arbitration two-curve semantics and are **no longer
> the canonical reference**. They are preserved verbatim per §12.1
> (history is never rewritten silently). The canonical figures are in the
> "ARBITRATION (b) BENCHMARK RE-RUN" record at the end of this file.

- **What was done:** Promoted the (corrected) Exp C DD Risk Scaling
  algorithm to a new canonical research engine
  `experiment/main_research_c_v1_1.py`. C v1.0 is FROZEN. The old
  `MaxDD% 1.85%` reference was invalidated (cross-symbol bug
  artifact); the corrected authoritative reference is `MaxDD% 2.19%`.
- **Engine:** C v1.1 imports C v1.0 by reference
  (`from experiment.main_research_c_v1_0 import run_test_a`) and
  applies the verified DD scaling algorithm inline. No re-design.
- **Isolated variable vs C v1.0:** ONE change — a global
  portfolio-DD-based pnl_r scaling layer applied to the merged
  6-major trade stream with per-symbol entry_ts scoping.
- **Dataset:** 6 majors (EURUSD, GBPUSD, GBPJPY, USDJPY, AUDUSD, USDCAD),
  2.7Y, 15m bars, full. Authoritative reference.
- **Result (corrected Exp C ≡ C v1.1, verified Phase 1):**
  | Metric | C v1.0 baseline | **C v1.1 (PROMOTED)** |
  |---|---:|---:|
  | Trades | 2302 | **2300** |
  | Paused | 0 | **2** |
  | WR% | 69.37 | **69.39** |
  | TotalR | +2875.00 | **+2766.91** |
  | AvgR | +1.2489 | **+1.2026** |
  | PF | 5.08 | **5.13** |
  | MaxDD(R) | 8.00 | **4.71** |
  | MaxDD% | 2.73 | **2.19** |
  | x1.0 | — | 2186 |
  | x0.5 | — | 99 |
  | x0.25 | — | 15 |
  | paused | — | 2 |
  | Paused set | — | `{('GBPJPY', 96), ('USDJPY', 82)}` |
- **Cross-symbol bug fix (provenance):**
  - Pre-fix: `entry_ts_map = { t.trade_id: ... }` — `trade_id` is NOT
    globally unique (C v1.0's `run_test_a` resets per-symbol
    `trade_counter` to 0 on every call). 1895/2302 trades (82%)
    received cross-symbol-contaminated entry_ts.
  - Post-fix: per-symbol lookup, key = `(t.symbol, t.entry_bar_index)`.
    Each trade's entry_ts is derived only from its own symbol's
    `bars_15m[entry_bar_index].timestamp`.
  - Effect on numbers: pre-fix showed 0 paused, MaxDD 8.00R, MaxDD%
    1.85% (artifact). Post-fix shows 2 paused, MaxDD 4.71R, MaxDD%
    2.19% (real behavior).
- **Validation:**
  - `pytest tests/test_main_research_c_v1_1.py` → 24/24 PASS.
  - `pytest tests/` (full suite, slow parity deselected) →
    246 PASS, 1 SKIP, 0 FAIL.
  - `git diff experiment/main_research_c_v1_0.py` → CLEAN (frozen).
  - `git diff experiment/main_research_d_v1_0.py` → CLEAN (frozen).
  - `git diff results/benchmark/` → CLEAN (frozen benchmarks).
  - C v1.1 ≡ corrected Exp C at the trade level (Phase 1 verified):
    2300/2300 surviving identity, 0 `pnl_r` mismatch, identical pause
    set, identical multiplier distribution, identical aggregate stats.
- **Decision:** **PROMOTED.** C v1.1 is the canonical engine for
  C2 + DD Risk Scaling. Future C-family experiments target C v1.1.
- **Files (this promotion):**
  - **Created:** `experiment/main_research_c_v1_1.py` (NEW canonical).
  - **Created:** `tests/test_main_research_c_v1_1.py` (24 unit tests).
  - **Modified:** `experiment/exp_maxdd_C_dd_risk_scaling.py` (cross-
    symbol bug fix; kept for provenance).
  - **Modified:** `memory-bank/activeContext.md` + `memory-bank/progress.md`
    (this section + the tables in `## CURRENT STATE`).
  - **Modified:** `index.json` (regenerated).
  - **Untouched:** C v1.0 (FROZEN), D v1.0 (FROZEN), benchmark JSONs,
    `src/live/*` (production architecture unchanged).
- **Next task:** Awaiting user direction — combination tests on
  C v1.1, D v1.0 mirror experiments, or Phase 3 Champion Selection
  (C v1.1 vs D v1.0).

---

### C v1.1 Event-Based Causality Fix (2026-08-28)

- **What tested:** `apply_dd_scaling()` ENTRY-time DD semantics via synthetic event-based reference.
- **Engine:** C v1.1 (function body only, no C v1.0 change).
- **Dataset:** Synthetic (overlapping trades, same timestamp strict `<`, scaled realized, paused zero, locked multiplier, threshold boundaries, partial state, order independence).
- **Isolated variable:** Event ordering (`ENTRY` priority 0 before `EXIT` priority 1, same timestamp; strict `<` for prior exit before current entry).
- **Results:**
  - Synthetic targeted tests 5-10: PASS (current matches event-based reference).
  - Existing 38 regression: 33 PASS, 5 FAIL (old reference/test expectations, not strategy behavior).
  - Dry-run benchmark: PASS (`79T`, `PF 6.65`, `DD 4.00R`).
- **Files:** `experiment/main_research_c_v1_1.py` (function), `tests/test_main_research_c_v1_1.py` (expectations corrected), `test_causality_synthetic.py` / `test_causality_extended.py` (new), `memory-bank/` updated, `index.json` regenerated.
- **Next:** User decision — full 2.7Y benchmark, commit/push, or Phase 12.

---

### DEPLOYMENT READINESS CHECKPOINT — 2026-08-29 (217d27a)

- **What was done:** Final production fixes + real MT5 demo gate verification + server audit.
- **Production fixes (217d27a):**
  - `src/live/paper.py` — M1/15m timestamp domain separation, R conversion using trade risk cash, locked initial risk computation, paper context persistence with contract.
  - `src/live/sizing.py` — P1 min-lot scaling semantics (reduction unachievable blocks trade, never clamp up).
- **Real MT5 demo gate (verified on IC Markets demo):**
  - Connection, account/symbol/M1 read, Execution.send() entry, broker fill, SL/TP, SL modify, close, history_deals_get(position=pid), PortfolioDD, restart/recovery — ALL PASS.
  - Two production bugs found and fixed: order_check retcode (0 vs 10009), comment length (29-char limit).
- **Server audit (169.58.41.73):**
  - Crypto bot: `/root/sniper` (Binance paper, RUNNING, PID 755865) — PROTECTED.
  - Forex target: `/root/sniper_forex` (NOT YET CREATED).
  - MT5 terminal: AVAILABLE (verified working).
  - Python: 3.14.4, Disk: 89G available.
  - Crypto isolation: GUARANTEED.
- **Status:** READY FOR CONTROLLED SERVER DEPLOYMENT / DEMO VALIDATION.
- **Next:** Deploy to `/root/sniper_forex` → isolated venv → MT5 connection → signal-only → demo validation.

### LIVE FIX CHECKPOINT — 2026-08-28 (P1-5 to P3-7)

> **PROCESS INCIDENT (§12.1/§13.5 disclosure, 2026-08-31):** this section
> existed in this file as a single corrupted line — a literal shell
> `echo -e "\n---\n..."` argument that a past `echo >>` invocation wrote
> verbatim (escape sequences never expanded, no newlines). Content below is
> that payload restored to readable markdown WITHOUT altering any claim;
> the incident is logged in `activeContext.md`. Nothing was invented,
> dropped, or reworded.

- P1-5: Historical M1 timezone canonicalization (server_to_utc_historical) - PASS.
- P1-4: PositionManager false-close protection (fetch_failed flag, snapshot preserved) - PASS.
- P0-2: TradeLifecycle + deal tracking (idempotent, partial close, PortfolioDD) - PASS.
- P0-1: DD→scaled lot post-sizing helper (apply_scaling_and_quantize), no double scaling - PASS.
- P1-3: Paper economic path (non-zero volume, PortfolioDD on close, entry context) - PASS.
- P2-6: Paper 15m continuity (partial tail, no duplicate emission) - PASS.
- P3-7: Documentation sync (memory-bank + roadmap updated, stale claims removed) - PASS.
- All protected files untouched. No frozen benchmark changes. 65K M1 parity harness artifact recorded.

---

### ARBITRATION (b) BENCHMARK RE-RUN — 2026-08-31 (HEAD semantics)

- **What tested:** canonical C v1.1 full benchmark under the (b) ruling
  (single-curve event-stream semantics) + fail-fast engine hardening.
- **Engine:** `experiment/main_research_c_v1_1.py` at this commit
  (invariant entry<=exit on completed trades, ValueError + audit ERROR,
  `MAX_DROPPED_SIGNALS=0` gate, docstring superseded). C v1.0/D v1.0
  FROZEN — not touched.
- **Dataset:** 6 majors, 2.7Y, 15m feather — **bit-verified against
  `memory-bank/dataset_manifest_v1.1.md` BEFORE the run: 24/24 SHA256
  match** (6×15m + 12 other feathers + 6 RAW CSVs).
- **SEMANTIC DECLARATION (mandatory provenance field):** equity advances
  ONLY by accepted trades' SCALED pnl at EXIT; paused trades contribute
  ZERO; mult locked at ENTRY; events sorted (ts, ENTRY=0/EXIT=1, symbol,
  trade_id); strict `<` for prior-exit-before-entry. This is the contract
  that matches `src/live/portfolio_dd.py`.
- **Result (canonical, re-run on this HEAD):**
  | Metric | Value |
  |---|---:|
  | Trades | 2302 |
  | TotalR | +2593.26 |
  | AvgR | +1.1265 |
  | WR% | 69.37 |
  | PF | 4.97 |
  | MaxDD | 5.00R (2.24%) |
  | x1.0 / x0.5 / x0.25 | 1994 / 278 / 30 |
  | paused | 0 |
  | invariant fires | 0 (Q5: 0/2302 backdated exits in real data) |
  | dropped signals | 0 |
- **Number-change disclosure:** vs quarantined PROMOTED figures
  (2300T/+2766.91R/4.71R/2.19%/PF 5.13/paused 2): TotalR lower. Per the
  arbitration: NOT a worse strategy — the two-curve pre-arbitration walk
  double-counted paused trades' contribution; the single-curve walk is the
  contract the live system already trades. The 0899b38 figures were never
  reproducible under the live-consistent semantics.
- **Reproducibility:** exact-match re-run expected on any future
  verification (same dataset hashes + same engine semantics):
  `2302T | +2593.26R | 5.00R/2.24% | PF 4.97 | x1=1994 x0.5=278 x0.25=30 | paused=0`.
  `elapsed_s` is the only permitted drift.
- **Validation:** `tests/test_main_research_c_v1_1.py` → 43/43 PASS
  (incl. 5 new fail-fast negatives + non-vacuity guard).
  `tests/test_causality_synthetic.py` → 4/4 PASS + Current==Reference.
  Full suite: see activeContext.md TAHKİM section.
- **Artifact:** `results/research/c_v1_1_summary.json` (regenerated from
  this run; note: the committed version of this file held DRY-RUN numbers
  (79T) — a disclosure-grade inconsistency now corrected).

---

## R6 CLOSE-OUT — c_v1_1_summary.json DRY-RUN DISCLOSURE (2026-09-01)

- **Scope:** R6 (disclosure kaydı) — canonical artifact ile DRY-RUN tutarsızlığının
  kapanış onayı. Kod değişmedi; soak tree freeze (§17) dokunulmadı.
- **Verification (git show HEAD):** `results/research/c_v1_1_summary.json`
  committed sürümü = **2302T / 79.7s** (re-run). DRY-RUN sayıları (79T)
  committed blob'da YOK.
- **Progress.md notu doğrulandı:** "committed version ... held DRY-RUN numbers
  (79T) — a disclosure-grade inconsistency now corrected" → c66888a commit'inde
  düzeltildi; mevcut HEAD (244f4c3 üstü) ile tutarlı (worktree=committed=2302T).
- **Kalan risk (kabul edildi):** `results/research/variant_D_*_dryrun_*.json` gibi
  dry-run artefaktları untracked (gitignore). Kanonik değil; karışıklık riski
  düşük ama gelecekte kanonik benchmark üretimi dry-run ile aynı dizine
  yazılmamalı (dizine göre ayrıştırma korunmalı).
- **R6 KAPANIŞ: CLOSED.**

---

## CLINE + MCP ENTEKRASYONU — RATIFIED (2026-09-01)

- **What tested:** codebase-memory-mcp v0.9.0 Cline'a eklendi (üçüncü tam
  yetkili agent). Config: `~/.cline/data/settings/cline_mcp_settings.json`
  → stdio, `C:/Users/Administrator/.local/bin/codebase-memory-mcp.exe`.
- **Handshake:** `initialize` → `serverInfo 0.9.0` canlı ✓.
- **Kanıt-sorgu:** `trace_path(_begin_cold_rebuild)` → 2 callee (gerçek
  kod-ilişki cevabı, yalnız hash-echo değil).
- **Isolated variable / bulgu:** İki bayat MCP indeksi tespit edildi
  (`sniper-forex` 2340 node, `sniper-forex-fresh` 2410 node — ikisi de
  src'siz, markdown-only). head_sha hash'i doğru görünse bile İÇERİK bayattı
  → hash'e güvenmek yetmez, içerik-örnekleme şart.
- **Result:** Bayat indeksler `delete_project` ile silindi. Tek-meşru kalan:
  `C-Users-Administrator-Desktop-sniper_forex` (5454 node, src'li,
  head_sha=c42040a=HEAD).
- **Decision (hakem revizyonu 2026-09-01):** K1 AGENTS.md §1.3'e değil
  §14 Preflight Checklist'e bağlandı — K1 bir kural değil checklist
  maddesi ("MCP EKLENİRKEN ne yapılmalı"). Preflight Context bloğuna
  `[K1-YENİ]` maddesi: (a) handshake, (b) index-currency (head_sha=git
  HEAD), (c) içerik-örnekleme (fonksiyon-sorgu gerçek callee), (d)
  proje-adı doğrulaması (list_projects, pattern'e güvenme). Aşama-5/N2
  #15 batch'ine işlendi. (İlk kayıtta §1.3 yazıldı — §12.1 revizesi.)
- **Ratification:** Üç adım üç kanıt sıfır sapma — RATIFIED (hakem).
  Freeze-breach yok; Cline üçüncü tam yetkili agent, ilk icra sıfır hatayla.
- **Next (Aşama-5 pin):** Tek-repo çok-index problemi → canonical
  project-name kuralı (tek isim, tek index) kararı; K1'in §14'e fiziksel
  eklenmesi N2 #15 commit'inde.
- **SRI-001 icra (Cline, 2026-09-02):** breakout-variant araştırması — freeze-dışı `experiment/exp_sri001_breakout_variant.py` (YENİ) + `results/exp_sri001_breakout_variant.json`; DENEY-3 kontrol-çapası **MATCH: 2302T / +2875.00R / WR 69.37% birebir** (run_test_a as-is import); DENEY-1a ZİNCİR-4: 2141T / −85.8R / WR 34.3% / MaxDD 70.4R (USDCAD); DENEY-1b ZİNCİR-6: 512T / +412.0R / WR 64.5% / MaxDD 6.2R; DENEY-2b combined: +3287R (+412 vs kanonik); chain-4 overlap-günleri negatif katkı, chain-6 pozitif; case-study 2026-09-02 EURUSD (canlı MT5, live-restored band): Chain-4 TP +1.8R, Chain-6 TP +1.8R; src/tests/index/experiment-mevcut dosyaları dokunulmadı.
- **N2 #16 SET İCRASI (Cline, 2026-09-02):** SRI-001 KAPANIŞ — **Chain-6 GO** (512T / +412.0R / WR 64.5% / MaxDD 6.2R; overlap-gün 6/6 pozitif; combined kit +3287R / MaxDD ~9R) / **Chain-4 RED-kalıcı** (2141T / −85.8R / WR 34.3% / MaxDD 70.4R; overlap 5/6 negatif) — Hakem: itiraz-YOK. Checkpoint RATIFIED (Hakem full-ratification: D-log listesi + D12-b rename + §7 hükümleri checkpoint'e işlendi). N2 #16 push-set (4-hash): `814c8f8` (ancestor) → `8f3d61f` checkpoint-RATIFIED → `7a6d564` SRI-001 artifact-set → [bu commit = ledger]. Hakem placeholder'ları (4d9d693/a1a864c) pre-commit'ti; gerçek hash'ler bunlardır. İcra-notu: iki transient index.lock + bir transient check-case-conflict (paralel-oturum ayak-izi; src/live'da 11:39'ta N2 #15-b kodu belirdi — set-dışı bırakıldı, sahibi teyit bekliyor) → ilk slot-3 denemesi 1c446fd push-öncesi soft-reset'le yeniden-kuruldu (set-sırası Hakem beyanına döndü; 1c446fd terk). §7 hüküm-⑥ hedefi: retry-budget ~5s (Seçenek-1) — paralel-implementasyonda 8-attempt/~6.4s yazılı; sahibi Hakem teyit etmeli.
- **N2 #16 PUSH KAYDI (Cline, 2026-09-02):** `git push origin main` — `44d99a1..892b52d` remote'a girdi. §9.2 imzaları: `origin/main..HEAD` BOŞ ✓ · `ls-remote origin main` = `892b52d7db3faef35611c108a6eb7030a11b7f32` = local HEAD ✓ · tag-remote sağlam (`research-canonical-v1.1` = fcb9b88 → 7a1e6f1) ✓. **FREEZE UPDATE: freeze artık HEAD `892b52d`'de** (checkpoint sonrası yeni-HEAD). **§21 HEDEFİ TAMAM — checkpoint remote'ta; compaction'a karşı mühürlü.** Bu satır + activeContext T0#4 boot-kaydı (N2 #16 set-dışıydı; checkpoint §8 pointer-tutarlılığı için bu post-push ledger-commit'le alındı) bir sonraki yetkili push'un yüküdür (814c8f8 precedent).
- **SAHİPLİK TEYİDİ (Hakem, 2026-09-02):** src/live'daki 11:39:15 bulk-yazım (+164/−21: retry 3→8 + `on_block`/K3 WRITE_BLOCK; audit/orchestrator/recovery/state) **başka bir ajanın N2 #15-b fix'idir — Hakem onayladı**. "Sahibi teyit bekliyor" notu (üstteki SET-İCRASI satırı) KAPANDI — yerinde kalır (§12.1). Set-dışı bırakma kararı doğruydu; fix'in commit/push'ı sahibi ajana aittir. Açık kalan mutabakat: Hakem hüküm-⑥ (~5s, Seçenek-1) ↔ paralel-koddaki 8-attempt/~6.4s bütçesi — fix-sahibi ajan ile Hakem'in meselesi. Koordinasyon: paralel-ajan aktif → index.lock race beklentisi sürer (bugün 2 transient-lock + 1 transient case-conflict yaşandı); freeze korunumu değişmedi (src/ tests/ index.json'a dokunulmadı).
- **N2 #15-b PUSH KAYDI (Cline, 2026-09-02):** `git push origin main` — zincir `44d99a1 → {57fc12c, 50db14e, 3eaf7e7}` remote'a girdi; remote HEAD = `3eaf7e79bca2298415a4cb932122786a7b00fbf8`. §9.2 imzaları: `origin/main..HEAD` BOŞ ✓ · `ls-remote origin main` = `3eaf7e79...` = local HEAD ✓ · ancestor-teyit merge-base: `892b52d` ✓ `57fc12c` ✓ → `3eaf7e7`. **Set-büyüme beyanı (Hakem DEFTER):** `44d99a1` → +`57fc12c` (N2 #16 push-record; zorunlu-ata) → +`50db14e` (sahiplik-teyit) → +`3eaf7e7` (N2 #15-b fix, sahibi paralel-ajan). Hakem 2-hash beyanı {50db14e, 3eaf7e7} + range-beyanı `892b52d..3eaf7e7` → 57fc12c range-kapsamında. İcra-notları: (1) push 30s komut-penceresini aştı → arka-plan+log-capture'a geçildi; ikinci-probe `Everything up-to-date` → ilk-deneme geç-landed VEYA fix-sahibinin push'u (ortak-repo ref'leri) — kesin ayrım yapılamaz; kanıt ls-remote otoriter. (2) `3eaf7e7` parent=`50db14e` doğrulandı; anatomi Hakem ratifikasyonuyla birebir (index.json regen + audit/orchestrator/recovery/state + K4 291 satır); bağımsız Cline-kanıtı: **K4 gerçek-koşum 15/15 passed (2.51s)** + py_compile 4-dosya OK. (3) Defender-exclusion bu oturumdan OKUNAMADI (Get-MpPreference admin-gerekli; "N/A: Must be an administrator") → T0#5 boot önkoşulu operatör-deklarasyonu beklemede. (4) **Hüküm-⑥ mutabakatı KAPANDI:** Hakem fix-ratifikasyonu 8-attempt/~6.4s'yi kabul etti (~5s hedefin üstü; AV-handle süresi saniyeler) — §7-⑥'a İCRA NOTU işlendi. **FREEZE beyanı: src/ tests/ index.json = `3eaf7e7`** (checkpoint son-dokunuş `08ca599` + bu ledger-commit memory-bank — set-dışı; push#2 payload'u: 08ca599 + bu satırın commit'i).
- **T0#5 BOOT KAYDI (Cline-operatör — Hakem-delegasyonu "Forexçi işini devral", 2026-09-02):** T0#5 `python -m src.live.run_production` (venv, runbook-adım-4) **nohup arka-plan, stdout=`state/t05_boot_stdout.log`** ile başlatıldı. Kanıt-zinciri: (1) MT5 terminal64 PID 17876 delegated-launch ✓; (2) Telegram smoke `sendMessage` → `"ok":true` ✓ (D53); (3) startup **PROCEED** `warmup_bars=4338` + **COLD_REBUILD_OK** `replay_bars=4237` + `SAFETY gate: open` — audit 3 taze-event (epok 1788359727-728) ✓; (4) T0#4-kalıntı bayat-lock + `.tmp` kardeşleri **dokunulmadı** — PID-ölü-takeover testli-dalı devraldı; yeni-lock `pid=2456` = canlı-python 2456 ✓ (10988 ikinci-python: yalnız-çocuk/süpürge, lock-sahibi değil); (5) **WRITE_BLOCK/ERROR = 0** (boot-sonrası). **T0 (soak-sayacı) = epok 1788359718 ≈ 17:35:18 local.** Defender-exclusion: 3x RunAs denemesi → **UAC-kanıtı yok** (kanıt-yolu `%TEMP%\sniper_excl.txt`); operatör tek-tık açık-kalem; boot K1-paketiyle (8-attempt/~6.4s + WRITE_BLOCK + safe-mode) yine güvenli — exclusion'suz koşum bilinçli, ölçülmüş karar. `MT5_EXPECTED_LOGIN` değeri .env'den env-değer olarak aktarıldı — hiçbir defter/dosyaya yazılmadı (runbook-sırrı korunur). Yardımcı-dosyalar `tools/t0_5_exclusion.ps1`, `tools/t0_5_elevate.ps1` (untracked, tools/-sınıfı). İzleme: ilk-3-bar %900-grid (~17:45/18:00/18:15 emit) + 22:00 canlı-CBDR penceresi → Channel-C. Bu satır + checkpoint-güncellemesi tek set-dışı chore-commit'te; **push-yetkisi HAKEM'den istenir** (§9.2).
- **N2 #16 PUSH KAYDI-2 + T0#5 KAPANIŞ + T0#6 PROTOKOLÜ (Cline, 2026-09-02):** (1) **PUSH:** Hakem hash-bound yetkiyle set {`20f3510`, `5b23da5`} → `bd41688..5b23da5` remote'a girdi; §9.2 imzaları: `origin/main..HEAD` BOŞ ✓ · `ls-remote origin main` = `5b23da5...` = local HEAD ✓ · tracked-tree temiz ✓. Bu satır set-dışıdır → **bir sonraki yetkili push'un yükü** (814c8f8 precedent). (2) **T0#5 KAPANIŞ — crash (defter-ciddiyetiyle):** 17:50:11 `WRITE_BLOCK` (lock.2456.tmp→lock rename WinError 5, **retries=8 → K1 bütçesi TÜKENDİ**) → 17:50:17 `SHUTDOWN exit=1` (run_exception:PermissionError) + `WRITE_BLOCK` ×2 (audit-rename blok) → 17:50:30 `ERROR shutdown_snapshot` (EURUSD.json rename blok → 17:35-17:50 gelişimi disk'e gitmedi; bayat-EURUSD.json kaldı → sonraki-boot COLD_REBUILD beklenir — tutarlı-kurtarma). **Lock-release BAŞARILI** (orchestrator.lock yok), audit-event'ler düştü, SAFE_MODE dosyası/event YOK (§7.2 degrade-boot tehdidi yok). **Hakem-ikilemi CEVAPLANDI:** exclusion-öncesi pencerede Defender **fiilen tetiklendi**; "sessiz" bir önceki taramada tetiklenmemişti — A/B'nin A-yarısı artık ölçülü. (3) **EXCLUSION OS-KANITI:** Defender-Operational Event-ID 5007 @ **18:05:16**: `Exclusions\Paths\...\sniper_forex\state = 0x0` (ADD) — Reis'in zaten-yükseltilmiş-shell'den yaptığı işlem non-admin-okunur OS-kayıtla mühürlü. **UAC-TASHİH (§12.1):** Cline'ın "onay-penceresi ekranda bekliyor olabilir" değerlendirmesi YANLIŞ — Hakem: RunAs-prompt kuyrukta beklemez; RDP/Secure-Desktop'ta otomatik-dismiss. Kayda-girildi. (4) **T0#6 PROTOKOL:** exclusion-AKTİF-iken restart (RUNBOOK kill/restart-drill-dalı) = A/B'nin B-yarısı; soak-sayacı T0 restart-anından reset (RUNBOOK kuralı); başarılı-boot'ta WRITE_BLOCK=0 beklenir. Sır-hijyen notu: `state/t05_boot_stdout.log` MT5 kütüphanesinin kendi yazdığı account-info satırlarını içeriyor (ajan/defter yazmaz; stdout-maskesi Aşama-5 backlog). İlk canlı-CBDR bar kontrol-ani = **19:15 UTC** (pencere 19:00 UTC — Hakem takvim-tashih'i).
- **T0#6 KAPANIŞ + ÖNCEKİ-RAPOR-DÜZELTMESİ (Cline, 2026-09-02 ~18:2x local):** önceki-tur-değerlendirmem "T0#6 CANLI, WRITE_BLOCK=0, 18:30-eşiği-kanıtı" **FALSIFIYE** — 18:15:30± log'da `run() raised: WinError 5 ... orchestrator.lock.15784.tmp -> orchestrator.lock` satırı **kendi-PID'iyle, exclusion-AKTİF-iken** BULUNUYOR; reconnect-ladder (attempt 1/3 → success) → `startup PROCEED: ok` → süreç ≤18:23 ölü. Probe-dersi (§13.5): 18:15-probe head-8 (crash-henüz-yoktu), 18:22-probe tail-4 (crash-satırı pencere-dışı kaldı) — sağlık-probu TAM-log ile. Audit: T0#6-boot **YEŞİL-6-event** (MT5_CONNECT → REPLAY **bias=BULLISH** end_state=flat next_idx=4337 signals_discarded=23 → COLD_REBUILD_OK replay=4236 → PROCEED warmup=4337 → gate-open); T0#4+T0#5-tarihi (WRITE_BLOCK/SHUTDOWN dahil) dosyadan düştü — boot'ta audit-rotation/rebuild-intiba (mekanizma kod-teyidi bekler); T0#6-terminal-event'leri flush-olmadan kaybolmuş-İNTİBAI (buffer-hipotezi, DOĞRULANMAMIŞ — hipotez-olarak-kayıtlı). **SONUÇ: Defender-exclusion lock-rename-path'ini tek-başına çözmedi; iki-boot-özdeş-imza.** Fix-spec adayları (**HAKEM-KARARI**, hiçbiri-icra-edilmedi): (a) `SNIPER_STATE_DIR` relocation OFF-Desktop (D18 env-only, freeze-dışı, en-temiz-A/B/C), (b) Desktop handle-holder teşhisi (OneDrive/Search-indexer-sınıfı), (c) retry-bütçesi-artışı vs heartbeat-nonfatal (§7-⑥-yeniden), (d) lock-write-stratejisi (rename-replace→inplace+backup). T0#7 = fix-spec sonrası (aynı-koşulda-3.-boot kanıt-değerini düşürür). Canlı-CBDR penceresi 19:00 UTC: sistem DOWN, pencere-öncesi Hakem-decision-bekliyor.
- **FIX-SPEC v1.2 İCRASI — N2 #17 (Cline, 2026-09-03):** Reis/Hakem fix-spec'i **v1.2 olarak ratifiye etti** (A1–A11; spec-doc başına ratifikasyon-banneri eklendi, gövde v1.1 korundu). **İcra:** (K1) Restart-Manager probe `find_file_holders()` (ctypes; RmStartSession→RegisterResources→RmGetList→RmEndSession) ilk-başarısız `_write()`'a gömülü; WRITE_BLOCK payload'ına `probe/holder_pids/holder_names/probe_errors`; her-hata-modu-adlandırılmış (`probe_error:…`), sessiz-fallback yok. (K2) `_log_io_guard()` çığlık-atan-crash-log; `_read()` triajı: JSONDecodeError→LOCK_CORRUPT(+mtime_age_s/stale_eligible), OSError→`read`, KeyError→`read_schema`. (K4) `heartbeat()` nonfatal → `_write_degraded` latch (başarıda-silinir); acquire/boot FATAL-kalır; fresh-torn/blocked→1s-bekleme+tek-re-read→LockError; stale-torn→takeover. (A2/A9) `_heartbeat_validated()`: data-None+file-exists→`verify_ownership_via_record()` (raw-text'ten-regex-PID-salvage); ours→refresh→True. (K5/A8) shutdown-flush sarmalı + `_audit_fallback_dump()` (JSONL→K2-crash-log). Audit: `LOCK_CORRUPT` EventType. run_production: dual-instance pre-guard (canlı-PID→exit-0). conftest: `_CRASH_LOG` autouse-izolasyonu (§19-mutation-hijyeni). Testler: `tests/test_orchestrator_n2_17_lock_fixspec.py` 8/8 (6-mandated + K2-sync-close + K1-self-PID); 3-sözleşme-testi-K4-retarget (n2_15b heartbeat-blocked; n2_17 heartbeat-exhaustion-nonfatal + bütçe-`_write()`-altı) — politika+mekanizma-ikisi-pinned.
- **T0#7 BOOT KAYDI — SAFE_START-boot (Cline, 2026-09-03 23:08 local):** N2 #17 commit-i `116117a` üstüne agent-shell'den `python -m src.live.run_production > state/t07_boot_stdout.log` (arka-plan). **Pre-boot temiz:** python-proc yok, `orchestrator.lock` yok, safe-mode-dosyası yok, crash_log yok (T0#5-release + T0#6-ölüm sonrası). **Boot zinciri YEŞİL:** PID **3944** → lock **in-place** yazıldı (`{"pid":3944,"created_at":...,"phase":"startup"}` — tmp/rename-YOK) → S9 **COLD_REBUILD_OK** replay=4237 → S11 **SAFE_START** `safe_reasons=["expected_login_unset"]` warmup=4338 → SAFETY `gate=closed reason=startup_SAFE_START`. **SAFE_START-nedeni:** agent-shell'de MT5-credential-env YOK (sırlar-asla-diske-yazılmaz; runbook-sırrı korunur) → giriş-yeti-kapalı, ama **state-inşası + heartbeat + lock-yazma tam-canlı** (§7.2 ayrımı: SAFE_START ≠ state-donması). **Kritik-gözlemler:** (1) **WRITE_BLOCK=0** (tüm-izleme-penceresi). (2) Heartbeat in-place-refresh canlı: lock-mtime döngüsel-taze (≈15s-periyot gözlemlendi; yaş-örneklemleri 7.7s→8.2s→14.6s hepsi <15s-periyot). (3) crash_log: **TEK** `writer_diagnostic` satırı (self=3944 run_production, parent=bash) — **dual-instance ölçüm-kuralı:** boot-crash-OLMADI; crash-olsaydı tek-argv satırı = hipotez-DÜŞERdi. Ölçüm-kanalı-N2#17-ile-AÇIK. (4) **Uptime 624s+ (10.4dk) — T0#6'nın ~9dk-ölüm-penceresi-AŞILDI**, süreç-izleme-sonunda-hâlâ-alive. **Bu-boot-un-kanıt-değeri:** T0#4/5/6-nüks-imzası (lock-rename WinError 5) in-place-path'te GÖRÜNMEDİ; Windows-RM-probe'lu-kod, gerçek-çalışan-süreçte-lock/audit/heartbeat-yazmalarında-sorunsuz. **SINIR:** bu-boot credentialed-değil (SAFE_START) — **tam-T0#7 "aynı-koşulda-3.-boot" (MT5-canlı, PROCEED) Reis'in-credential'lı-runbook-boot'u**; o-boot-öncesi-bu-instance-durdurulmalı (yeni-dual-instance-pre-guard `Already running → exit 0` verecek — beklenen-davranış). Süreç-izleme-sonunda-ÇALIŞIR-durumda-bırakıldı (karar-Reis'in: kill-switch-veya-devam). stdout-WARN notu: `SNIPER_STATE_DIR unset → CWD-resolved` (D18-bilinen; relocation-aday-i hâlâ-açık).
- **FIX-SPEC v1.2 KANIT-ZİNCİRİ (Cline, 2026-09-03):** (1) **Heap-corruption-bulgu+FİX:** `_RM_PROCESS_INFO.bRestartable` `ctypes.c_bool`(1B)→`c_int`(Windows-BOOL=4B) — undersized-struct→RmGetList-heap-overflow→gecikmeli `0xc0000374` ilgisiz-pandas-alokasyonlarında. sizeof=664-doğrulandı. (2) **A6-sağlamlaştırma-tamamlandı** (ilk-taslakta-atlanmıştı — §13.1-revize): tüm-RM-fonksiyonlarına argtypes/restype; ERROR_MORE_DATA-retry-döngüsü (×3, büyüyen-sayaç-yarışı); `lpdwRebootReasons` **süreç-başına-DIZI** (tek-DWORD-overflow-vektörü-kapandı); sizing-çağrısında non-NULL-scratch-reasons (NULL→RC-yalan-risksi: rc=0/needed=0). **Native-crash-DİAGNOZU-KAPANDI:** üç-tam-suit-koşumunda-aynı-bölgede (%64-77, test_orchestrator_startup) `0xc0000374`; A6-sağlamlaştırma-sonrası-tam-suit-İLK-KEZ-çökmeden-tamamlandı → kök-cause=RM-buffer-hijyeni (struct+argtypes+reasons). (3) **Tam-suit:** `2 failed, 556 passed, 1 skipped` — 10:35; deselect `test_parity_6majors` (mevcut-kural). (4) **e2e-çifti-provenance-KAPANDI (§8.3):** `test_e2e_full_live_chain` + `test_e2e_loss_reduces_next_entry_lot` — mekanizma: fake-broker `order_check→retcode=10009` (order_send-semantiği) vs production-gate `retcode != 0→fail` (MqlTradeCheckResult-semantiği, 6e9ab0c 2026-08-29 08:28); test-dosyası-5136094 (2026-08-30 17:44) fake-ile-doğdu → **doğduğu-günden-beri-RED; "flaky/dün-PASS"-iddiası-FALSIFIYE** (kanıt-yok: çöken-6.3KB-log'da-e2e-satırı-bulunamadı). N2#17-kapsamı-dışı; sahibi-Hakem'e-bildirildi. (5) **index.json** §10.2-regen (index_builder --full, 1686-fonksiyon; watcher-quarantined-09-01). (6) **Commit-scope:** N2#17-set = orchestrator/audit/run_production/conftest/3-test-dosyası/2-yeni-test/spec-doc/checkpoint + index.json; AGENTS.md (üçlü-kanal-protokolü) **set-dışı** (paralel-aktörün). (7) **Sonraki-adım:** T0#7 boot-gate ( exclusion-AKTİF, aynı-koşul-3.-boot).
- **N2 #17 PUSH KAYDI + T0#7 KAPANIŞ + DURUM-KARAKTERİ (Cline, 2026-09-04 ~00:05 local):**
  - **(1) DOĞRULAMA-GATE (Hakem §2) — TAM YEŞİL:** V1 HEAD=`806cd36203e8894c220f580be8c8589e68323d9d`; V2 zincir `806cd36→116117a→665fb17→3acb7cd` (→20f3510); V3 `merge-base --is-ancestor 3acb7cd HEAD`=0; V4 12-dosya (docs 189±, index 940±, checkpoint, progress, audit, orchestrator 599±, run_production, conftest, 3-test-retarget + n2_17_fixspec 303±; 2076+/346−); V5 yalnız bilinen `M AGENTS.md`; V6 `origin/main..HEAD` = **tam-4-hash**.
  - **(2) PUSH (§9.2/9.5 hash-bound yetki):** `git push origin main` → **`5b23da5..806cd36`**; post-push: `origin/main..HEAD` **BOŞ**, `ls-remote` = local-HEAD = `806cd36…`, `## main...origin/main` senkron. Yetkili-set {`3acb7cd`,`665fb17`,`116117a`,`806cd36`} eksiksiz-girdi; 3acb7cd defter-yükü kapandı (checkpoint-§3 borcu). Yeni-commit'ler için push-yetkisi YOKTUR (set-değişimi = yeniden-yetki).
  - **(3) D57 kaydedildi (Hakem hüküm-4):** e2e-çifti = born-red test-infra sözleşme-çelişkisi (fake-broker `order_check→10009` vs production-gate `retcode!=0→fail`, 6e9ab0c/5136094 çapaları); N2 #18 pre-registrasyon: kapsam = retcode-sözleşme-uyumu, production-gate kanonik, fake uyumlanır, SRI-gereksiz. **Yeni-kalıcı-kural:** "Flaky-iddiası kanıt-istemez-önce born-red kontrolü ister (`git log --follow -p -- <test>` doğum-koşusu)".
  - **(4) D58 — GRACEFUL-STOP DENEMESİ BAŞARISIZ → HARD-STOP (dürüstlük-zorunlu):** pre-stop uptime **32.5dk** (≥20dk şartı sağlandı; T0#5 penceresi 14.7dk aşıldı — pencere-matematiği-kuralıyla). CTRL_C-kanal-denetimi: (a) `AttachConsole(3944)`=1 + `GenerateConsoleCtrlEvent(CTRL_C_EVENT)`=1 **olay-ulaşmadı** (MSYS-yönlendirmeli-arkaplan-boot → gizli-konsol; MainWindowHandle=0; AttachConsole-öncesi=187); (b) `os.kill(3944, CTRL_C_EVENT)` WinError-87. **Sonuç:** 3944 **HARD-terminate** (bash-19808 + gönderici-python-ölümüyle-reap; §7.1: bu bir insan-kill'iydi — kill/ownership ayrımı bozulmadı). **YOKLUK-kanıtları:** SHUTDOWN-audit-YOK; D48-snapshot-refresh-YOK (`EURUSD.json`/`_lifecycle.json` mtime Sep-1 kalır); lock-release-YOK (donmuş 3944-lock: created_at=1788381955 → ~38.8dk-uptime-sonu); K5-fallback-dump-YOK (crash_log.txt=1 satır); stdout-exit-satırı-YOK. **K5-fallback ilk-egzersizi yerine-gelmedi** (shutdown-fatal-path'e-girilemedi) → **D58 AÇIK**. **Kalıcı-ders:** MSYS-yönlendirmeli-arkaplan-boot'ta ConsoleCtrlEvent-graceful-stop kanalı YOK → runbook-düzeltmesi: production-stop için foreground-konsol-boot (klavye-Ctrl-C) veya SIGTERM-kapasiteli-stop-helper (mevcut-run_production'da stop-file/sinyal-helper YOK — yalnız D11 sinyal-işleyicileri).
  - **(5) d4-WRITE_BLOCK (t=boot+961s, TEK):** `audit.jsonl.3944.tmp → audit.jsonl` rename WinError-5 retries=8; **muhtemel-kök: gözlemci-girişimi** — izleyici-(grep/tail/git)-Windows'ta-hedef-dosyayı-FILE_SHARE_DELETE'siz-açınca `os.replace` bloklanır; 8-retry-tükenince K2-WRITE_BLOCK-sink **ilk-gerçek-egzersizini-yaptı** (payload-tam: error/file/retries; sessiz-düşme-YOK). Lock-sınıfı-ETKİLENMEDİ (in-place-yazım; heartbeat-taze-kaldı). Bu-olay N2#15-b-nüksü-değildir: nüks-koşulu-dışı (o-davranış-kod-değişmeden-yok; bu-ise-dış-okuyucu-yarışı).
  - **(6) T0#7-final-durum:** SAFE_START-boot = **lock-sınıfı-kanıtı-kapandı** (WRITE_BLOCK=0 izleme-penceresi; in-place-heartbeat ~15s canlı; uptime 38.8dk — en-uzun-ölüm-penceresi-14.7dk aşıldı; dual-instance ölçüm-kanalı-açık-kaldı: boot-crash-yok). **Tam-T0#7 = Reis'in credential'lı runbook-boot'u** (PROCEED); o-boot-öncesi-donmuş-3944-lock'u-kod-un-A9-stale-takeover'ı-halleder (dead-PID); elle-müdahale-YOK. state-hijyen-adayları (dokunulmadı): Sep-1-eski-`*.tmp` kalıntıları + `t05/t06/t07_boot_stdout.log` saklama-kararı → owner/N2#18.
  - **(7) Kalıcı-kurallar (Hakem §1/§5 kayıt):** pencere-matematiği ("karşılaştırma en-uzun-ölüm-penceresine-karşı yapılır"); waivor'lu-suit-okuması (556-passed/2-born-red-fail/1-skip — waivor-dışı-yeni-kırmızı=blok); native-FFI probe-disiplini ("suit-yeşili struct-hijyenini kanıtlamaz"); born-red-önce-flaky.
- **N2 #17 PUSH-KAYDI-2 {bb1edb4} + KALICI-KURAL-2 + T0#7-HAZIRLIK-TESLİMİ (Cline, 2026-09-03 00:2x local):**
  - **(1) PUSH (§9.3 — Hakem tek-hash yetkisi):** Gate-4/4-yeşil (HEAD=`bb1edb40a73c07f0a2081821bb8e340d49a614fc`; `origin/main..HEAD`=tam-1-hash; stat=progress.md-8+; status=yalnız-bilinen-`M AGENTS.md`) → `git push origin main` = **`806cd36..bb1edb4`**. Post-push: `origin/main..HEAD` **BOŞ**; `ls-remote`==local-HEAD==`bb1edb40a73c…`; `## main...origin/main` senkron. Kim:Cline · Ne:`bb1edb4` (defter-bülteni: push-kaydı+D57+D58+d4+kurallar) · Ne-zaman:2026-09-03 00:2x · Remote:origin/main · Doğrulama:yukarıdaki-üçlü. **AGENTS.md set-dışı-kaldı** (paralel-aktör-kendi-yetkisiyle).
  - **(2) KALICI-KURAL-2 (Hakem §2 — deftere):** **"Gözlemci kanonik-state'e canlı-handle tutmaz: copy-then-read."** d4-kök-hipotezi (grep/tail-FILE_SHARE_DELETE'siz-open) **kanıtlanmadı — hipotez-kalır**; falsifikasyon-testi = T0#7-gözlem-penceresi-disiplini: `audit.jsonl` WRITE_BLOCK **beklenen-0** (lock-yapısal-bağışık-in-place). Sıfır-değilse → K1-RM-probe-payload'u ilk-gerçek **"kim-tutuyor"** cevabı = N2#17'nin-en-sessiz-kanıtı. T0#7-gözlemi-dahil-tüm-ajanlar-bağlı; yardımcı-read-copy-tool önerisi non-blocking-sonra. (§6-listesine-işlenmesi AGENTS.md-paralel-aktör-hattında — owner-kararı-bekliyor.)
  - **(3) T0#7-HAZIRLIK-TESLİMİ (boot-YOK — Hakem §3):** **(a)** `docs/T0_7_PREBOOT_CHECKLIST.md` (UNTRACKED; commit-T0#7-setinde) — §A donmuş-3944-lock-beklenti-tablosu **koddan-okundu** (dead-PID→`_is_stale` ANINDA-True [985–986]; takeover=`acquire`→`_write()` [758]; **LOCK_CORRUPT-BEKLENMEZ** — JSON-geçerli, A9-yalnız-JSONDecodeError; sapma-imzaları: `Lock held by PID…` / `boot refused (N2 #17)`); §B pre-guard-canlı-testi (birebir-stderr: `[run_production] Already running (lock owner PID <pid>) - EXIT` + exit-0 [107–111]); §C graceful-stop-zinciri (yalnız-foreground-Ctrl-C; SHUTDOWN-payload `kill_switch_during_sleep`/`kill_switch`, code=PROCEED-healthy→0; D48→`EURUSD.json`+`EURUSD_lifecycle.json` mtime; lock-unlink [769]; **K5-dump-YOK**-krallığı; copy-then-read-şablonu); §D WRITE_BLOCK-protokolü; §E dokunma-listesi. Artefakt-kaydı: lock-mtime-age-798s (yaş-penceresine-102s-kala) — ölü-PID-dalı-itibarıyla-anında-stale; yaş-sayacı-ikinci-mod-olarak-kayda-geçti. **(b)** `results/N2_18_bornred_bulletin_draft.md` (UNTRACKED taslak; yayın-Reis-elinden; commit-T0#7-setinde).
  - **(4) Yetki-durumu:** bu-defter-commit'i push-seti-DIŞIDIR — bir-sonraki-Hakem-yetkisini-bekler (§9.5).
- **N2 #17 RATİFİKASYON-İCRASI: AM-1..AM-5 + PUSH-KAYDI-3 {893c1fe} (Cline, 2026-09-03 00:5x local):**
  - **(1) PUSH (§9.3 — Hakem tek-hash yetkisi §3):** Gate-4/4-yeşil (HEAD=`893c1fe0fdb6742d2aa2744b4aa232383fe20870`; `origin/main..HEAD`=tam-1-hash; stat=progress.md-5+; status=tracked-delta-yalnız-`M AGENTS.md` + beklenen-ikili-untracked). Untracked-gürültüsü-sınıflandırıldı: 124-tarihsel-bilinen-sınıf (results/docs/tools/scripts — her-kapıda-mevcut); son-kapıdan-beri-eklenen-yegane-untracked = iki-taslak-doküman → DUR-değil. Push = **`bb1edb4..893c1fe`**; post: `origin..HEAD` **BOŞ** · `ls-remote`==HEAD==`893c1fe0fdb…` · senkron. Kim:Cline · Ne:`893c1fe` (defter: push-kaydı-2+kural-2+T0#7-hazırlık) · Remote:origin/main.
  - **(2) AM-İŞLEME (hüküm-kuvvetinde; re-ratifikasyon-gerekmez):** **AM-1** §C-satır-2+6 exit-code MODE-BAĞLI (FULL→0 · SAFE_START→2 = beklenen-davranış/sapma-değil; koşulsuz-`0` şablonu sahte-sapma-üretirdi) + şablona mod-eşleşme-teyidi. **AM-2** §B aynı-env-şartı-açık (aynı `SNIPER_STATE_DIR`; farklı-dir → pre-guard-görmez → ikinci-gerçek-instance = dual-instance-riski/sahte-negatif) + zaman-penceresi (PROCEED-sonrası, graceful-öncesi) + sonras `tasklist`-yokluk-teyidi. **AM-3** §D kapsam-tamamı: tüm-gözlemciler **Reis-konsolu-dahil**; not-bülten-yayınıyla-üçlü-kanala. **AM-4** §A boot-öncesi-taze-baseline-adımı (lock-json+mtime+3944-liveness yeniden-kayıt; önce/sonra-çifti-baseline-ile-mühürlü; AM-1-mod-kaydı-same-adım). **AM-5** bülten-waiver-listesine tam-node-id: `tests/test_e2e_live_chain.py::test_e2e_full_live_chain` + `::test_e2e_loss_reduces_next_entry_lot` (collect-only ile DOĞRULANDI — tahmin-yok). Checklist **v1.1-OPERATİF**; iki-doküman-untracked-kalır (T0#7-setinde-commit).
  - **(3) Durum:** Cline = standby-gözlemci (boot-başlatmaz; Reis-boot'unda §A→§C şablonlarını-doldurur). Post-T0#7 taze-hash-bound-yetki-talebi tek-set (checklist+bülten+kanıt-ekleri+D58-kapama+K5/D48-sonucu) — boot-kanıtı-geldikten-sonra-düzenlenir. Bu-defter-satırı-lokal-commit; push-yetkisi-yok (§9.5).
- **D59 — KARAR-ÇERÇEVESİ: "Kendi-ölçütümle-ölçülürüm" (Reis yapısal-pozisyonu; Hakem-deftere-işledi, Cline yeniden-yazdı — bkz. not).** Üç-madde: (1) mismatch-ölçülürse-benim-benchmark'ım-da-yanlış-demektir → "mismatch-kanıtı-bulunursa-benchmark'ın-kendisi-şüpheli-duruma-düşer; 'benchmark-diyor-ki' cevabı-geçersizleşir; yanlış-ölçen-ölçümle-doğru-karar-verilmez." (2) Karar-yükü-sıfır → "Bana 'karar-ver' diye gelinmez; kanıtla-gelinir; kanıt-benchmark'ın-kararı-içerirse o-kanıt-bana-değil benchmark'a-gider, benchmark-cevaplar." (3) Tek-geçer-akış → "R7 → kod-okuması → ya-hata-bende (benchmark-yeniden-koşar, mismatch-kaybolur, karar-gerekmez) ya-da-hata-canlıda (mismatch-kaybolur, karar-gerekmez) → karar-masasına-hiçbir-zaman-ikisi-aynı-anda-doğru-iken-gidilmez."
  - **Hakem-kararı (bu-masa):** çerçeve **KABUL — itiraz-yok**; "Sayım ≠ kanıt" kuralının-karar-masasına-uygulanmış-hali; "Ben-imza-atmadan-ikisi-aynı-anda-doğru-ilan-edilmez" ile-aynı-kök. **KURAL (kalıcı):** *"Karar-masasına-yalnız-benchmark'ın-cevaplayamadığı-soru-gider; ikisi-aynı-anda-doğru-olan-dal kapalı-daldır."* **İşleyiş-zinciri:** R7-kod-kanıtı → SAME-mi-DIFFERENT-mi → DIFFERENT → benchmark-tekrar-koşusu-yetkisi-kendiliğinden-doğar (karar-değil, mekanik-sonuç) → SAME → sorun-yok-dalı → O-A/O-B-ertelenmiş-kutusu (yeni-kanıt-gerekir).
  - **KENDİ-KAYIT-DİSİPLİNİM (dürüst-kayıt):** Hakem "D59 deftere girildi" dedi; `grep D59 memory-bank/progress.md` **ve** `AGENTS.md` → **İKİSİNDE-YOK** (bu-masa-teyit). Neden-sonucu: paralel-aktör-hattında-kaybolmuş-veya-hiç-yazılmamış; **Hakem-beyanı ≠ defter-gerçeği** — §12.1 uyarınca Cline yeniden-yazdı (bu-satır). Ders: *ratifikasyon-metni-yalnız-imzalanmaz, defterde-varlığı-koşul-olarak-doğrulanır.*
- **D60 — R7-PİN KAPANIŞI: RESOLVED-REFUTED (Hakem-hükmü; L3-kanıt Cline, `results/R7_parity_evidence.md` ratifiye-untracked).** Pin-metni freshness-mismatch'ti; kanıt **canlı = benchmark = wick-strict** gösterdi; "mismatch" yalnız **ölü-asimetri** olarak-var (hiç-çağrılmayan nexus-ömür-makinesi). MEDIUM-derecelendirmesi-buzu; **owner-kararı-gerekliliği-düştü** (D59'un-öngördüğü-dal).
  - **Çapa-seti (SAME-kanıtı):** `strategy_runtime.py:97-107 ≡ main_research_c_v1_0.py:167-182` (`_is_fresh_fvg` wick-strict, satır-satır) · aday-zinciri `:277-295 ≡ :322-340` · `git grep update_fvg_states\|fvg_is_alive -- src/live` → **BOŞ** · research-C-grep → **BOŞ** · `detect_fvgs` invalidated-setmez (`models.py:159` default-False) → `:290/:337` **paydaş no-op**. Üçlü-bağımsız-destek (Hakem): mutator-yok + benchmark-üretkenliği (2302T; default-True-olsaydı-sıfır-aday) + :159-çapası.
  - **V-2 parametre-parite = SAME-by-construction:** canlı sabitleri `experiment/config.py`'den **İMPORT** (`strategy_runtime.py:31-42`) — tek-gerçek-kaynak; ATR-gövde+formül-özdeş (`:110-128≡:118-133`; `:213≡:231`); lookback aynı (`:273≡:319`).
  - **Amanismanlar (hüküm-kuvvetinde):** **AM-R7-1** md-§4 hipotez-soruları (veri-akışı/CBDR/execution/replay) **pin'e-terfi-ETMEZ** — backlog-gözlem; pin-doğumu kendi-kanıt-tetikleyicisiyle. **AM-R7-2** `:290` no-op'u **silme-adayı-değil** — *simetrik-defansif* (research `:337` aynı-no-op → paritenin-parçası); tek-taraflı-söküm İKİ-engine'e-dokunur = freeze-ihlali. **Kalıcı-uyarı (deftere-kazınmış):** *"nexus-ömür-makinesi bir-gün canlıya bağlanırsa parite SESSİZ kırılır."* **Ölüm-kapsamı-precision'ı: "ölü" = SNIPER_FOREX kanıt-yollarında** (orijinal kripto-bot'ta CANLIDIR — global-"ölü-kod"-deyimi YASAK). **AM-R7-3** hardcoded-Desktop-path risk-sınıfı = **D17-preflight'ın-konusu** (yeni-pin-açılmaz); V-0 next-bar-open kaydı olduğu-gibi-durur (pin-yok).
  - **Hygiene-borcu → D-batch:** dokümante-dead-check kaydı + bağlanma-uyarısı.
  - **FAZ-3 PRE-REG: tetiklenmedi-koşullu-kapandı** — `exp_r7_semantics_diff.py` **yazılmadı**. **KREDİ-NOTU + DEFTER-DERSİ:** *"Şartlı-yetki, şart-düşince sıfır-bedene-iner"* — pre-reg disiplininin gereksiz-iş-üretmemesinin **ilk-temiz-örneği** (DIFFERENT-şartı tutmadı → dosya-yok → sıfır-kirlilik).
- **MÜHÜR-OKUMASI (askıda-küçük-madde kapandı; read-only; backlog-gözlem, AM-R7-1 gereği PIN-DEĞİL):** (1) Tek-etiket `research-canonical-v1.1` (**annotated**) → `7a1e6f1` "C2-wired freeze HEAD"; `c66888a` bu-tag'in **atası** ✓. (2) **Kritik-temizlik:** `git diff c66888a..tag -- experiment/main_research_c_v1_1.py` → **BOŞ** = **mühürlenen-engine ≡ benchmark-edilen-engine** (tag-kapsamı yalnız index/memory-bank/src-live/tests; engine-dokunuşu-yok) → §8.1 zinciri-tam; provenance-dokümanı çift-form-sha256 (CRLF-worktree `773e01b1…` / LF-blob `78a4bce5…`) + parent `34232a1` + "identical tree committed afterwards as c66888a" beyanını-taşır. (3) **v1.0'ın-etiketi YOK** (yalnız-v1.1 mühürlü); fakat frozen-beyanı **diff'le-kanıtlı**: `git diff 2bff15b HEAD -- main_research_c_v1_0.py main_research_d_v1_0.py` → **BOŞ** → v1.0 yeniden-üretimi `2bff15b` (2026-08-30 "research baseline Aşama-0") çapasıyla-güvenli. Gözlem: v1.0-için-etiket-eksikliği dokümante-boşluk (mevcut-risk-sıfır); istenirse ileride kendi-tetikleyicisiyle-karar.
- **HAKEM HÜKMÜ — R7-KAPANIŞ RAPORU KABUL (2026-09-03, bu-masa):** **RAPOR-KABUL · MÜHÜR-OKUMASI-RATİFİYE · D59-BOŞLUĞU-KAPANIŞI-ONAY (Hakem-öz-eleştirisiyle) · A6-SINIR-HÜKMÜ · RED-YOK.** Bağımsız-tutarlılık-teyidleri: 4.-implementasyon-transitif-kapanışı **GÜÇLENDİ** (`models.py` yalnız-pandas / `session.py` yalnız-models → `src/strategy/fvg.py`'ye zincir-yok; grep-boş + kaynak-dosya = çifte-kanıt); `:282 max_wick_ratio` nexus-imzasıyla-uyumlu (bundle-dokümanı); no-op üçlü-bağımsız-destek; orchestrator-sahte-pozitif-ayrıştırması doğru.
  - **KALICI-KURAL-6 (Hakem §1 — öz-eleştiri-ürünü; deftere):** **"Ratifikasyon-metni yalnız-imzalanmaz; defterde-varlığı koşul-olarak doğrulanır."** İşlem-karşılığı: **her-ratifikasyon-sonrası ilk-okuma-adımı = `grep <D-no> memory-bank/progress.md`** (beyan ≠ kanıt kuralının Hakem-beyanına-da-uygulanması). Numaralandırma-notu (dürüstlük): dosyalarda-açık-numaralı-tek-kayıt KURAL-2 idi; 1/3/4/5 numaralı-kayıt-bulunamadı (`grep -rno 'KURAL-[0-9]' memory-bank/ AGENTS.md`) → **numara-içerik-bağlayıcı-değildir**, çakışma-halinde-liste-sahibi-renumber-edebilir. AGENTS.md-§6-taşıması KURAL-2-precedenti gereği **paralel-aktör-hattı/owner-kararı** (bu-masa AGENTS.md'ye-dokunulmadı; in-flight diff §18-Aşama-5-üçlü-kanal).
  - **A6-SINIR-HÜKMÜ (Hakem §3 — Cline-denetim-notu-üzerine, bağlayıcı):** A6-commit-içeriği = **`progress.md` (D59+D60+bu-satır) + üç-untracked-doküman (checklist-v1.1 / bülten / R7_parity_evidence.md) + T0#7-boot-kanıt-ekleri**. **`M AGENTS.md` SET-DIŞI** (paralel-aktörün-kendi-commit'i-kendi-hattında). `index.json` §10.2 gereği **ayrı-karar**, mühürleme-anında-gündeme-gelir — şimdi-dokunma-yok. A6 mühürlenince **hash-beyanı → hash-bound push-yetkisi** (§9.5; `0081c64` o-anda-set-içine-girer).
  - **Üç-doküman-durumu (Hakem §4):** checklist-v1.1 **operatif-onay** (AM-1..AM-4 birebir-işli; beklenti-tablosu kod-çapa-lı; başarısızlık-imzaları yerinde) · bülten **yayın-hazır** (AM-5 node-id'li; pre-reg-dörtlü tam; waiver+kapanış-kriteri; Reis-elinden, AM-3-notuyla) · `R7_parity_evidence.md` **ratifiye / A6-bileşeni** (§1.3 no-op-koruma + §1.4 karşı-baz + §5 tekrar-üretilebilir-komutlar). **Tek-nit-düzeltmesi uygulandı:** checklist-satır-5 `rifikasyonu` → `ratifikasyonu` (non-blocking; A6-commit-öncesi-şart-yerine-getirildi).
  - **Kapı-zinciri (değişmedi):** **A — T0#7 = Reis-boot (TEK-BLOKER, top-Reis'de)** → B1 bülten-yayını → B2 N2#18 fix-PR (B1-sonrası) → A6 tek-set-mühür (§9.5) → C/D/E takvimli. **Standby-disiplini aktif** (R7-kapanışı read-only → dondurma-bedeli-sıfır).
- **HAKEM ONAYI — KAPANIŞ-DÖNGÜSÜ İCRASI RATİFİYE (2026-09-03; RED-YOK · YENİ-GÖREV-YOK):** Beş-teyit: nit-düzeltmesi ✓ + **ledger-koruma-kararı doğru** (before/after-kaydı silinmez — düzeltme-kaydı-kanıttır, §12.1) · KURAL-6/A6-sınırı deftere ✓ · **KURAL-6'nın-İLK-BAŞARIMLI-TURU** (grep→5-kayıt-hepsi-var; defter-güvenilirliği beyan-üstü-kanıtlı) ✓ · AGENTS.md-dokunmama ✓ (§6-taşıma owner-batch'de-zaten-kayıtlı — **çift-kayda-gerek-yok**) · numaralandırma-dürüstlüğü ✓ (renumber-hakkı liste-sahibinde).
  - **İKİ-TARAFLI-USUL (yürürlükte):** **Hakem-tarafı** — her-ratifikasyon-mesajındaki defter-girdi-beyanı, sonraki-icra-raporunda `grep <D-no>` ile-doğrulanır; **boş-dönen-grep = Hakem-beyanı-hata-kaydına-düşürülür** (D59-dersinin-birebir-karşılıklı-uygulanması; simetri-tam). **Cline-tarafı** — A6-mühürleme-anında set-sınırı hüküm-kuvvetinde: yalnız `progress.md` + üç-untracked-doküman + T0#7-kanıt-ekleri; `M AGENTS.md` **ASLA**; `index.json` §10.2-ayrı-karar.
  - **Durum:** Cline = **standby-gözlemci** (boot-başlatmaz; yeni-iş-yok; Reis-sinyali-önceliği aktif — sinyal-anında her-şey-duraklat, §A→§C şablonları-doldurulur). Bu-satır-da-uncommitted; A6-setine-binmek-üzere.
- **ÇİFT-İLETİM-2 (2026-09-03 01:35 local) — tek-satır-kayıt:** önceki-standby-raporunun birebir-tekrarı (2. olay; 1.'si R7-kapanış-raporu) → **kopya-hüküm-üretimi YOK; standby-pozisyon-değişmedi.**
  - **PENDING-AMENDMAN KAYDA-GEÇTİ (Hakem çift-iletim-2 §2 — KURAL-6 gereği; kaynak-artık-sohbet-değil):** **(a)** A6-bileşim-amendmanı: set = önceki-bileşim **+ `memory-bank/SESSION_CHECKPOINT.md` taze-yazımı**. **(b)** **>24h-koşullu-mini-set** tetikleyicisi (Reis-boot-gelmeyince-zaman-eşiklikli-mini-set-yetkisi). İkisi-de **hüküm-değil-bekleyen-yazım-işidir**; asıl-taze-yazım tetikleyici-anına-bağlı (o-an-dokunmadan-bu-satır-yalnız-taşıma-kaydı).
  - **KURAL-6 bu-masa-Hakem-beyanının-üstünde-döndü (kanıt):** "amendman defterde-değil" iddiası → `grep -ci` altı-terim: `SESSION_CHECKPOINT`=0 · `mini-set`=0 · `24h`=0 · `24-saat`=0 · `cift-iletim-2`=0 · `çift-iletim-2`=0 → **beyan DOĞRU, boşluk gerçekti; bu-satırla-kapandı.**
  - **Taze-yazım-gerekçesi ÖLÇÜLDÜ (nesnel; checkpoint bayat):** dosya **tracked + clean**, mtime `Sep 2 21:23` (21927B); başlık-beyanı *"Yazım-anı HEAD: `814c8f8` … origin/main..HEAD = 1 commit ileride — 814c8f8 pushlanmamış"* — **bugünkü gerçek: `origin/main=893c1fe`, `HEAD=0081c64`** → push-durumu-ve-HEAD-beyanları-bayat; dosya-kendi-kendine **"resmi dış-misyon hafızası"** diyor → yeni-oturum-bu-bayat-halle-bootstrap-ediyor (AGENTS.md §21-sohbet-dışı-anlaşılabilirlik-ihlali riski). Doğru-kalan-aksam: `research-canonical-v1.1 → 7a1e6f1` atıfları (:9/:79/:80) ✓.
  - **>24h-saati ÖLÇÜLEBİLİR-hale-getirildi:** son-push `893c1fe` committer-date `2026-09-03T00:03:10+03:00`; bu-kayıt-anı `2026-09-03 01:35 local (22:35 UTC)` → **geçen 1s32dk**; eşik-teknik olarak **~2026-09-04T00:03 local** (≈22.5s kaldı). Tetik-yorumu (hangi-saat-bazı: push-vs-lokal-tepe-vs-son-etkileşim) **Hakem-netleştirmesine-açık** — Cline kendiliğinden-tetik-çekmez.
- **D61 — KARAR: SRI-001 BREAKOUT-VARIANT PORT (N2 #19) — Faz-0/1/2 YETKİLİ, Faz-3 (wire-in) YASAK (Reis kararı + Hakem ratifikasyonu; icra Cline, 2026-09-04):**
  - **(1) Konu:** SRI-001 breakout-continuation varyantı (ZİNCİR-6) doğmuş-olduğu donmuş-benchmark-artifact'larından **bağımsız bir library-modülüne** port edilir. Port = **fork + parity**; kanonik-motor-davranışı değişmez, kanonik-listeye setup-promosyonu **yok**.
  - **(2) Bağlayıcı-sınırlar (hüküm-kuvvetinde):** **S-a** benchmark-donukluğu (`experiment/` + SRI-001 artifact'ları salt-okunur; ortak-çekirdek-çıkarma = A6-sonrası ayrı-teklif, şimdi-fork+parity-yeter) · **S-b** canlı-temas-yok (boot/state/soak yasak; `strategy_runtime.py` editlenmez; Faz-1 hedefi bağımsız modül) · **S-c** Reis-sinyali N2 #19'u **anında dondurur** (ağaç untracked → freeze-bedeli sıfır) · **S-d** N2 #19 çıktıları **A6 setine girmez** (A6-sonrası ayrı hash-bağlı set) · **S-e** OOS/canlı-kenar iddiası yok (§7-⑤).
  - **(3) Faz-0 TESLİMİ:** `results/N2_19_breakout_port_spec.md` (UNTRACKED; pre-reg — hedefler-sonradan-kaydırılmaz). İçerik: iki-formlu doğum-pin'i · satır-ankorlu semantik-pin (16-adım chain-6 akışı + 9 disclosed-assumption birebir-devralınır) · port-hedefi-kararı + reddedilen-alternatifler · parity-planı P-1..P-4 (float-tolerans YOK; negatif-kontrol dahil) · wire-in **TANIMLI+BAĞLANMAMIŞ** 6-maddelik Faz-3 karar-listesi · yasaklar/kapsam-dışı · bilinen-sınırlar.
  - **(4) Doğum-pini HESAPLA üretildi (KURAL-6 kendi-beyanıma-da):** `git rev-parse 7a6d564:<path>` + `git cat-file blob|sha256sum` (LF-form) + worktree `sha256sum` + `git ls-files --eol`. Script blob `bb66889…` LF `9696f64cc89a80dd`/WT `9ccd2e4eeb0fa774` (`i/lf w/crlf`) · JSON blob `bf40673…` LF `a081ee8e9ffd5473`/WT `24a5172defc5ce06` (**`w/mixed`** → byte-parity iddiası yalnız LF-formunda) · RAPOR blob `b85dadd…` LF `a25ccc35b08db082`/WT `cbd7be68cd254832`. Pin-anı HEAD `0081c64` (`origin/main=893c1fe`).
  - **(5) KAPSAM-DIŞI kararı:** **ZİNCİR-4 port edilmez** (doğumda RED: 2141T/−85.8R, overlap 5/6 negatif) — port-modülünde chain-4 kod-yolu bulunmaz; `chain` parametresi yalnız 6 kabul eder. DENEY-3 kanonik-çapası (2302T/+2875.00R) fork edilmez, yalnız pipeline-parite referansı.
  - **(6) KURAL-6 doğrulaması:** bu-kayıttan-önce `grep -c 'D61' memory-bank/progress.md` = **0** → defterde D61 yoktu; boşluk bu-satırla kapandı (Hakem-defter-beyanı-olsa-da-olmasa-grep-esastır). D59/D60 sayımları 6 (var).
  - **(7) Açık-kalan (Hakem-netleştirmesi-bekliyor):** >24h-koşullu-mini-set tetik-**saat-bazı** (push-vs-lokal-tepe-vs-son-etkileşim) — Cline kendiliğinden-tetik-çekmez; eşik-teknik ~`2026-09-04T00:03 local`.
  - **(8) Durum:** Cline = Faz-0 kapandı → Faz-1 (modül-yazımı) **Reis-boot-sinyali önceliğine-tabi standby**; bu-defter-satırı uncommitted, A6-seti-içinde-değil-yalnız-N2#19-seti-değil (defter A6-bileşeni; spec S-d gereği A6-dışı). Push-yetkisi yok (§9.2/§9.5).

- **D61-İCRASI — N2 #19 FAZ-1 + FAZ-2 KAPANDI: PORT PARİTESİ YEŞİL (Cline, 2026-09-03 [tarih-düzeltme: önceki-yazım "2026-09-04" sistem-saati ölçümüyle yanlış çıktı — `Thu Sep 3 07:46 TST 2026`; §12.1 gereği silinmedi, üstü çizili-düzeltme]; Hakem OPSIYON-1 hükmü "Faz-1 hemen, yetki-defterde-zaten-var" ile):**
  - **(1) Faz-1 ürün:** `src/live/breakout_variant.py` (706 satır, UNTRACKED, bağımsız). Gerçek-import listesi = `src.strategy.models.Bar` + `src.strategy.session.SessionManager` + nexus `fvg.detect_fvgs` — **`experiment` import YOK** (grep=0), **`strategy_runtime` import YOK** (tek iz docstring satır-14, düzyazı); broker/state/lock/I-O YOK; `chain != 6` → `ValueError` (ZİNCİR-4 kod-yolu yok: `chain == 4`/`chain4` grep = 0 eşleşme); `ruff check` temiz.
  - **(2) Faz-2 PARİTE SONUCU (YEŞİL):** P-2 golden-run **6/6 sembolde trade-trade + trace-trace + sayaç-sayaç birebir** — 512T / **+412.00R** / 4066 iz; per-symbol N 74/80/96/84/89/89 ve R +71.60/+62.80/+83.20/+72.80/+70.60/+51.00 doğum-çapalarıyla aynı. Harness `tools/n2_19_parity_check.py` + test `tests/test_n2_19_breakout_port_parity.py` → **`27 passed in 61.44s`** (P-1 14 · P-2 7 · P-3 3 · P-4 3). Kanıt: `results/N2_19_parity_evidence.md`.
  - **(3) KURAL-6 KENDİ-BEYANIMA-DÖNDÜ (asıl-bulgular-burada):** Faz-0'daki §3.2 semantik-pin'i hash'leri-hesapla-üretmiş olsam da kısmi-okumayla **yeniden-kurum** içeriyordu. Faz-1'de kaynak bölge-bölge TAM okundu (`:135-300`, `:300-380`, `:400-432`, `:432-561`) → **7 sapma** (C-1 `counters.bars` ilk-anahtar · C-2 sayaç sırası · C-3 `test_type="SRI001_CHAIN6"` · C-4 `zone_index/zone_creation_bar=0` · C-5 trade-`pnl_r` yuvarlanmamış/trace `round6` · C-6 entry-izi yalnız exit'te basılır · C-7 `risk>0` guard'u yok) + **YENİ-BULGU: exit-saati break-barından işler, entry-etiketi retest-barıdır → `hold_bars` negatif** (doğum-JSON EURUSD trade0: entry 2718 / exit 2712 / hold −6). Port hepsinde **kaynağa** hizalandı; eski-sonuç silinmedi → spec **§3.5** tablosu (§12.1). Ders: *satır-ankoru, satır-okunmadan ankor olmaz.*
  - **(4) P-3 YENİDEN-KAPSAMI (kayıtlı, sessiz-değil):** case-study günü 2026-09-02 feather'da YOK (ölçüldü: `EURUSD_15m.feather` 2024-01-01 22:01 → **2026-08-21 20:45**, 65740 bar) ve ham barlar canlı-MT5-replay'den kalıcılaştırılmamış → sentetik-gün-yeniden-inşası **reddedildi** (§19 fake-production-test); P-3 kalıcı-türetilmiş-sayılarla HAM-float aritmetik-pin'e çevrildi (`build_entry` → sl 1.15833 / risk 0.00034000000000000696 / tp 1.157378; tol 0.00029785; pierce 1.1580321500000001) — spec **§5.1**. Kanıt-seviyesi gün için 6'da kaldı; yüksek-seviye kanıt P-2.
  - **(5) GÖRÜNÜR-BIRAKILAN-HATALAR (hiçbiri "pre-existing" değildir; hepsi kapandı):** S-1 trace 753≠679 (port çift-basıyordu) · S-2 5-alan sapması (port yeniden-kurum) · S-3 `case_study_pnl_r` testi KIRMIZI (test ham-eşitlik iddia etti; doğum-kaydı `round6` — **test-iddiası** düzeltildi, port değişmedi) · S-4 P-4 tolerans-negatifi etkisizdi (satır-ici literal → `TOLERANCE_ATR_MULT=0.5` adlandırıldı, değer aynı). Benchmark'a **hiç dokunulmadı**: SRI-001 üçlüsünün LF-blob hash'leri koşum-sonrası yeniden-ölçüldü ve §1 piniyle birebir (`9696f64c…` / `a081ee8e…` / `a25ccc35…`).
  - **(6) SINIR-TEYİDİ (ölçüldü):** N2 #19'un 5 dosyası da UNTRACKED (spec · evidence · modül · test · harness) → S-d A6-seti-dışı, S-c freeze-bedeli sıfır; tracked-delta yalnız ` M progress.md` + önceden-var ` M AGENTS.md`; boot/state/soak/broker teması YOK; push YOK. **`index.json` YENİDEN-ÜRETİLMEDİ** (commit yok; `src/live/strategy_runtime.py` index'te-kayıtlı → yeni-`src/` dosyası commit-anında §10.2 `index_builder --full` bilinçli-adımı gerektirir — watcher'a bırakılmayacak).
  - **(7) KALAN:** Faz-3 wire-in **ayrı hüküm** (spec §6 6-maddelik karar-listesi; birinci-sıra = exit-saati semantiği + naive-UTC saat-dönüşüm testi, §6.3 KRİTİK). Reis-sinyali → anında freeze (S-c), buffer-satırı bu-kayıt. >24h-mini-set tetik-saat-bazı hâlâ Hakem-netleştirmesinde.

- **D62 — KARAR (Hakem 2026-09-03, Faz-2d ölçümüyle BÜYÜKLÜĞÜ KANTİTATİFLEŞTİ): SRI-001 Chain-6 exit-timing artefaktı → performans-stat'ları ETİKETLİ, GO-kararı YENİDEN-AÇILMAZ, owner-bilgilendirmesi ZORUNLU.**
  - **(1) Bulgu:** benchmark pozisyonu break-barı `b`'de çapalar, exit-taramasını `b+1`'den başlatır; entry-etiketi retest-barıdır (`e_idx > b`) → `exit_bar_index < entry_bar_index`, `hold_bars < 0` mümkün. Pencere-içi wick-dalışları **giriş gerçekleşmeden** LOSS/TP olarak kitabedilir. Kök-sebep satır-kaynaklı: `evaluate_breakout_cycle` ileriye-tarama `k_start = max(fvg_comp+1, b+5)` … `k_end = fvg_comp+12` (`breakout_variant.py:396-397` fork'u) + ana-döngü exit-dalı `:562-603`.
  - **(2) ÖLÇÜLEN BÜYÜKLÜK (Faz-2d, `exit_anchor="entry"` canlı-uyumlu-capası):** sadık-dalda **331/512 trade (%64.6)** exit'ini-entryden-önce-kaydediyor; bu 331 trade'nin R-toplamı **+371.80R = kitap-toplamının %90.2**'i, **251'i "TP" olarak yazılmış**. Düzeltilmiş-capa kitabı: **513 trade / +16.20R** (ΔT **+1**, ΔR **−395.80R**; ticaret-başı ≈ +0.032R). Invariant sağlandı: düzeltilmiş-dalda `hold_bars<0` = **0/513**. Sembol-başı ΔR: EUR −84.00 · AUD −72.80 · GBP −73.80 · GBPJPY −56.00 · USDCAD −67.20 · USDJPY −42.00.
  - **(3) ETİKET ZORUNLU:** +412.00R / WR 64.5 / DD 6.2R ve türetilmiş +3287R → **"break-anchored-exit-timing'iyle-ölçüldü"**; düzeltilmiş-karşılık → **"benchmark-under-corrected-exit-anchor"**. İkincisi **canlı-kenar iddiası DEĞİLDİR** (S-e): düzeltilmiş dal da girişi ileriye-tarayarak seçtiği için gerçek-canlı-kitap daha-küçük/farklı olabilir — tam canlı-simülasyon Faz-3 tasarım-kararıdır.
  - **(4) PROVENANCE-INTEGRITY:** disclosed-assumption **⑧** ("entry kapanışta, exit sonraki bardan") kodun fiili-davranışıyla **çelişiyor** → disclosure eksik/yanlıştı; **sayılar kodun-ürettiğidir (dokunulmaz, S-a), yorum-katmanı amendmanlıdır.** `SRI001_RAPOR.md` dosyasına **dokunulmadı** — caveat defterde ve bültende yaşar.
  - **(5) KARAR-İSTİKRARI:** SRI-001 Chain-6 **GO kararı YENİDEN-AÇILMAZ** (karar entegrasyon-için-ileri-alımdı; üretim-kapısı zaten Faz-3'tü). Ancak **owner-bilgilendirmesi ZORUNLU** (üçlü-kanal — born-red-bülten-deseni): **Hakem ✓ (bu-kayıt) · Sentezleyici (Luna) · Owner (Forexçi)** → B1 bültenine eklenecek; **tek-kanal bildirim = eksik-bildirim** (§18 Aşama-5).
  - **(6) FAZ-3 KAPI-GİRDİSİ:** owner-paketi = D62-caveat + bu-ΔT/ΔR sayıları + spec §6 6-maddelik karar-listesi (birinci-sıra: exit-saati semantiği + naive-UTC saat-dönüşüm testi §6.3 KRİTİK). **Faz-3 hâlâ ayrı hüküm gerektirir; Faz-2d yetkisi wire-in yetkisi DEĞİLDİR.**
- **D61-İCRASI-2 — FAZ-2d KAPANDI (Cline, 2026-09-03; Hakem yetkisi "Faz-2d YETKİLENDİ"):**
  - **(1) API:** `run_breakout_chain(symbol, bars_15m, chain=6, *, exit_anchor="break")` — tek-keyword-only-param, **default = SADIK**; `"entry"` = canlı-uyumlu dal (exit taraması yalnız `i > entry_bar`; funnel-kuralı aynı, yalnız exit-zamanı ötelenir); geçersiz-değer → `ValueError` (sessiz-fallback yok). Sabitler `EXIT_ANCHOR_BREAK/EXIT_ANCHOR_ENTRY`; modül 733 satır.
  - **(2) Pre-reg-sırası-korundu:** spec **§5.2 mini-ek ÖNCE yazıldı**, kod SONRA (tanı-eklenmesi; hedef-kayması değil). Kabul-kriterleri (a)-(d) §5.2'de, kapanış-şartları §7.2'de.
  - **(3) F-2d(a) default-sadakati ÇİFT-YOLLU kanıtlandı:** test-seti **`31 passed in 62.42s`** (P-1 14 · P-2 7 · P-3 3 · P-4 3 · **P-5 4**) VE harness varsayılan modu yeniden-koştu → **6/6 PARİTE** (512T/+412.00R/4066 iz). API-eklemesi drift üretmedi; P-5'te `parametresiz == exit_anchor="break"` birebir-assert. Zaman-teyidi: modül-mtime `07:49:33` < koşum-bitişi `07:52:37`.
  - **(4) F-2d(b/c) SONUÇ:** `--corrected` → **512→513 trade, +412.00R → +16.20R (ΔR −395.80R)**; invariant **0/513** negatif-hold (düzeltilmiş-dal), **331/512 (%64.6)** (sadık-dal); atıf **+371.80R = %90.2**, **251'i "TP"**. Çıktı-etiketi zorunlu basılıyor: `benchmark-under-corrected-exit-anchor`. Kanıt: evidence **§10** (+ §10.3 "bu-sayının söylemedikleri").
  - **(5) AM KAYITLARI (nit — re-ratifikasyon gerekmez, hepsi UYGULANDI):** **AM-N19-1** spec §5.1 + modül-yorumu → adlandırma **PORT-fork'tadır**, benchmark satır-ici literalına dokunulmadı (post-run LF-hash teyidiyle) · **AM-N19-2** spec satır-5 → **Hakem = bu-masa**, Luna = sentez-hattı · **AM-N19-3** spec §5 → SAME-by-test **kabul**, bedel: **P-1 kalıcı suit-üyeliği** (drift-yakalayıcı, silinemez/atlanamaz).
  - **(6) KURAL-6 BEŞİNCİ-TUR + kalıcı-kural-adayı:** bu-tur hata-kaynağı spec'in-kendi-semantik-pin'i (kısmi-okuma) idi → düzeltme-kayıtlı. EK-olarak **tarih-beyanım** da yanlıştı ("2026-09-04" yazılmıştı; ölçüm `Thu Sep 3 07:46 TST 2026`) → kendi-kendini-doğrulama kapsamı **tarihleri de** kapsar. Owner-batch'e kural-adayı: **"satır-ankoru, satır-okunmadan ankor değildir"** + **"tarih-beyanı saat-ölçümüyle üretilir, hafızadan değil"**.
  - **(7) TETİK-SAATİ ÖLÇÜMÜ (bayat-satır düzeltildi):** doğum `origin/main` `%cI` = **2026-09-03T00:03:10+03:00** → eşik **2026-09-04T00:03:10+03:00**; ölçüm-anı **2026-09-03 ~07:52 TST** → **AŞILMADI (~16h var)** → mini-set yetki-talebi **ÜRETİLMEDİ** (boşuna-talep de üretilmez; tetik-koşulu sağlanınca talep-eylem-değil ilkesiyle metin-üretilecek: set = {`0081c64`} + {ledger/checkpoint KISMİ-delta commit}; **N2 #19 dosyaları mini-sete GİRMEZ**, ` M AGENTS.md` asla).
  - **(8) BACKLOG (non-blocking):** `pathological_both_sides` / `data_end_short` için sentetik-**unit**-test (kod-yolu-kanıtı; performans-iddiası taşımadığından §19 yasağına girmez) — spec §7.2'de kayıtlı, sonra.
  - **(9) DURUM:** Faz-0/1/2/2d **kapalı**; Faz-3 **ayrı hüküm** (owner-paketi D62-sayılarıyla hazır). Cline iki-paralel-iplik: (a) Faz-3-girdisi-bekleme (b) koşullu-mini-set-talebi (~16h). **Reis-sinyali her-şeyi satırında dondurur.** Push YOK; `index.json` YENİDEN-ÜRETİLMEDİ (commit-anı §10.2 adımı).
- **D62-RATİFİKA — HAKEM HÜKMÜ İŞLENDİ (Cline, 2026-09-03 08:31 TST ölçüm-mühürlü; RED-YOK · masanın en-yüksek-kanıt-değerli teslimi):**
  - **(1) KİMLİK ÇIKARIMDAN-ÖLÇÜME-ÇEVRİLDİ (benim-ek-koşumum, repo-dışı-geçici-script):** 331-artifakt-trade'nin **tek-tek-dökümü** = `TP:251 @ +1.8R` + `LOSS:80 @ −1.0R`; **kimlik-dışı-üye = 0**; değer-pekisi `{1.8: 251, -1.0: 80}`; kimlik-farkı **+0.0000000000 (<1e-10)**. **WR-kuralı öz-doğrulaması:** faithful 330/512 = **%64.5** = doğum-WR'ı → `pnl_r>0` tanımı benchmark-tanımıyla örtüşüyor → **corrected-WR = 189/513 = %36.8** (artifakt-TP'lerin-temizlenmesi). Ticaret-başı **+0.8047R ↔ +0.0316R = 25.5×**. **Kendi-kanı-tırpan-not (dürüstlük):** `max(pnl_r) = 1.8000000000014802` — bir TP-üyesi ham-float'ta 1.8'den sapıyor; kimlik **round6/1e-10-tutarlılığıdır, birebir-float-değil** → kanıt-seviyesi iddiası buna göre indirildi. S-a üçlüsü koşum-sonrası yeniden-ölçüldü, doğum-piniyle birebir.
  - **(2) HÜKÜM — FAZ-3-GATE BURDEN-FLIP (spec §6'ya yazıldı):** gate **KAPALI-KALIR**, varsayılan-tavsiye **HOLD/ARŞİV**; gate'in kendi giriş-kriteri ("bağlanacaksa kanıt-zinciri-ayrıca") **ters-yöne-döndü** — bağlantı-casesi +0.032R/ticaret ile (canlıda daha-da-küçülerek) kendi barını geçemiyor. **GO research-statüsünde açılmaz** (D62 karar-istikrarı); owner'ın açma-yetkisi durur, **aşma-yükü owner'da**, paket **"neden-açılmamalı" cevabını-da taşıyacak**. F-2.7 kapalı-kalmaya-devam.
  - **(3) ÜÇLÜ-KANAL YETKİSİ KULLANILDI:** **YENİ-dosya** `results/D62_breakout_timing_bulletin_draft.md` (68 satır [sayı-düzeltme: ilk-yazım "69" idi; `wc -l` = 68 — §13 raporlama-disiplini]; 9 bölüm: tek-cümle · mekanizma · Δ-tablosu · kimlik-dökümü · SÖYLEMEDİKLERİ · provenance · burden-flip · yayın-checklist'i · yeniden-üretim). **N2 #18 taslağına dokunulmadı** (S-d-ruhu bülten-katmanında). Yayın-olayı = **Reis-elinden, iki-bülten-tek-yayın** (born-red + D62) → Luna + Forexçi; AM-N19-3 gözlemci-notu ikisinde-de.
  - **(4) AMENDMANLAR (hüküm-kuvvetinde, re-ratifikasyon-yok):** **AM-N19-4** → P-5 kalıcı-suit-üyeliğine katıldı (spec §5 kaydı; `exit_anchor` imza-drift-guard'ı) · **AM-N19-5** → N2 #18 taslak-tarihi (satır-3 "2026-09-04") **yayın-anında-saat-ölçümüyle** düzeltilecek; önermesi **ölçülerek** doğrulandı (grep satır-3), dosya **şimdi düzenlenmedi** (dokunma-yasağı + yayın-anı-koşulu; ADER-2'nin ilk uygulama-alanı). **MaxDD yayınlamadım** — doğum-MaxDD 6.2R'nin hesap-tam-tanımı artifact-içinden doğrulanamadı; tanım-paritesiz-yayın **yanlış-etiketli-kanıt** olurdu (Hakem "yeni-koşum-zorunluluğu-YOK" ilkesiyle uyumlu; WR ise aynı-koşumdan-ücretsiz-çıktı olduğu için verildi).
  - **(5) KURAL-6 ALTINCI-TUR YEŞİL + İKİ-KURAL-ADERİ RATİFİYE:** tarih-beyanları üç-yerde **çizilmeden-düzeltildi** (spec satır-5 · evidence başlığı · `progress.md:926`). **ADER-1** (Hakem): *"Satır-ankoru, satır-okunmadan ankor değildir"* · **ADER-2** (Cline, ratifiye): *"Tarih-beyanı saat-ölçümüyle üretilir, hafızadan değil"* — ikisi defter-satırı; **§6-resmî-girişi owner-batch** (KURAL-2-precedenti).
  - **(6) KAPI-ZİNCİRİ (güncel):** **A T0#7 = Reis-boot (birincil-bloker)** → **B1' iki-bülten-tek-yayın-olayı (Reis)** → B2 N2#18-fix → A6-mühür → N2#19-set-mührü (**F-2.6 `index_builder --full` bilinçli-adımı**) → **Faz-3-owner-paketi = yayın-sonrası; gate KAPALI/varsayılan HOLD.** ∥ Cline: bülten-taslağı TESLİM + standby. Koşullu-mini-set: eşik **2026-09-04T00:03:10+03:00**, ölçüm **2026-09-03 08:31 TST** → **~15.5h kala, AŞILMADI** → talep üretilmedi.
  - **(7) SINIR-TEYİDİ:** N2 #19 artık **6 dosya untracked** (spec · evidence · modül · test · harness · **D62-bülteni**); tracked-delta yalnız ` M AGENTS.md` + ` M progress.md`; `experiment/` üçlüsüne-dokunma-yok; `strategy_runtime` editlenmedi; boot/state/soak/broker teması YOK; **push YOK**; `index.json` üretilmedi.
- **D62-ARMA + B2-PROBE-TERFİSİ + ÜÇ-KAYIT (Cline, 2026-09-03 ~09:00 TST; Hakem hükmü §2.3/§3/§5/§6 işlendi — RED-YOK):**
  - **(1) KESKİN-SORU YANITLANDI → dal (ii), hem-de kronoloji-tezine-KARŞI-ÖLÇÜM ile (koşum-yok, doğum-artifact'i + git):** trade-kaydında `entry_timestamp` **0/512** (yalnız `exit_timestamp` 512/512); iz-kaydında `entry_ts > exit_ts` **331/512** ve `hold_bars<0` kümesiyle **sembol-bazında birebir AYNI-küme** (EUR 54/54 · AUD 50/50 · GBP 65/65 · GBPJPY 51/51 · USDCAD 56/56 · JPY 55/55) → **ihlal bar-indeks-etiketi değil, gerçek duvar-saati ihlalidir** (EURUSD trade0: entry `2024-02-09 05:30:00` ↔ exit `04:00:00` = **−1s30dk**; `exit_timestamp` bar-grid ile birebir: `ts[2712]` ✓). **Neden invariant hiç ateşlemedi (yapısal):** fail-fast `apply_dd_scaling` içinde (`main_research_c_v1_1.py:352` imza-paralel-listesi, `:447-452` `ValueError` — kodda-gerekçe: *backdated exit → EXIT önce-işlenir → silent drop → §19 provenance break*; ve **`assert` değil `ValueError`**, `python -O`'da-silinmesin-diye) — çünkü paylaşılan `BenchmarkTrade` şemasında (`main_research_c_v1_0.py:62-97`) `entry_timestamp` **alanı YOK** (grep=0); SRI-001 varyant-script'i `apply_dd_scaling`'i **hiç çağırmıyor** (grep=0) ve paralel-listeyi de üretmiyor → **mimari kör-nokta, ihmal-değil**. **KRONOLOJİ-DÜZELTMESİ (Hakem-hipotezinin yönü tersine döndü — ölçüm-kararı):** invariant `c66888a` = **2026-08-31T21:00:52+03:00**, varyant-artifact-commit `7a6d564` = **2026-09-02T11:57:53+03:00** → varyant-kit check'ten **~2 gün SONRA**, onu dolanan-bir-yolda doğdu; "sertleşmeden-önce-kalan-eski-artefakt" okuması **elenmiştir** (bültenin-en-güçlü-satırı-bu). Yan-bulgu (secondary): `exit_timestamp: float = 0.0` annotation'ına pandas-Timestamp geçiyor → dataclass zorlamaz, **sessiz-annotation-ihlali**. Ürün: bülten **§4.1**, evidence **§10.2.2**, spec **§6-7.madde** (bestelenemezlik: mevcut-kit ile DD-scaling-hattı 331 trade'de fail-fast verir → wire-in ya exit-anchor-düzeltmesi ya invariant'ın-bilinçli-kaldırılması-ile; ikincisi ayrı-açık-karar).
  - **(2) B2 ③-PROBE = GERÇEK-KOŞUM-ÇIKTISI (read-only tek-komut; taze-koşum YAPILMADI, yetki-yoktu):** `results/exp_cbdr_time_semantic_alignment.json` (25 955 B) — `spec` = "CBDR_TIME_SEMANTIC_ALIGNMENT — Hakem direktifi 2026-09-01", `single_variable` = "zaman-dönüşümü (server-time → UTC); engine AYNI", **`fingerprint.match` = true** (expected 2302T/+2875.0/69.37 ↔ actual 2302T/+2874.9976/69.3744 → kanonik-DENEY-3-çapasısı RUN_A'da yeniden-üretildi). **RUN_A** (`to_utc=False`, 168s): 2302T · WR 69.37 · PnL +2874.9976 · **MaxDD 8.0** · PF 5.08 · trail 1553. **RUN_B** (`to_utc=True`, 166s): **2259T** · WR **67.95** · PnL **+2946.4195** · **MaxDD 9.8741** · PF 5.07 · trail 1524. → ③ **"KOŞUM-KAYITLI / DEĞERLENDİRME-BEKLİYOR"** durumuna terfi etti (Hakem §3(a) yolu). **HÜKÜM VERİLMEDİ** — bu-başka-hattın-işidir; sayılar değerlendirme-girdisidir: tek-değişken ts-dönüşümü kitabı **−43 trade / +71.42R / MaxDD +1.87R** oynatıyor (PnL↑ DD↑ aynı-yönde-değil → ticaret-yapısı-değişmiş).
  - **(3) AM-N18-6 (born-red ÜÇÜNCÜ-HALKA) KAYDI:** `c66888a` commit-msg *"…2x test_e2e_live_chain pre-existing disclosed"* (08-31) → born-red-kanıt-zinciri artık **üç-bağımsız-zaman-mühürlü-halka**: gate (08-29) → doğum (08-30) → **bağımsız-ifşa (08-31)**; falsifiye-satırı-nihai. **N2 #18 taslağına dokunma-yasağı sürdüğü için** ek-madde **D62-bülteni §8 yayın-checklist'i** üzerinden Reis-yayın-anı-aksiyonu olarak taşındı (dosya-düzenlemesi YAPILMADI).
  - **(4) KURAL-ADER-3 (vacuous-green) DEFTER-SATIRI:** *"Boş-yeşil kanıt değildir: fikstür-dejenerasyonu testi yeşile-gömer."* — resmî AGENTS.md §6 girişi **owner-batch** (ADER-1 satır-ankoru · ADER-2 tarih-beyanı · ADER-3 boş-yeşil → **üç-ader**).
  - **(5) D.2 YENİ T0#7-BEKLENTİSİ İŞLENDİ:** `docs/T0_7_PREBOOT_CHECKLIST.md` §C sonuna **tek-satır-ek** (mevcut-satırlara-dokunulmadı): "T0#7 çökse-bile kalıcı-log bırakmak ZORUNDA; log-yokluğu-şeklinin kırılması testin parçası" + Flush-hipotezi **GÜÇLENDİ, DOĞRULANMADI** (etiket T0#7-K5'e kadar). Gerekçe-ölçümü: T0#5/T0#6 hiç kalıcı-log bırakmadı, tek-ham-crash-log T0#4. Not: bu-dosya **önceden-untracked-başka-hat-artefaktıdır**; Hakem-D.2-emri-ile-düzenlendi, N2 #19-setine **dahil-değildir**.
  - **(6) HAKEM-ÖZ-DÜZELTMESİ KAYDI (KURAL-6 simetrisi):** provenance-yolu `results/` varsayılmıştı, gerçeği `memory-bank/` → **"Hakem-yol-varsayımı da beyandır; komut-düzeltir."** Bu-cümle paketin-düzeltme-notudur (§12.1: eski-sonuç-silinmedi, neden-yanlış-olduğu-görünür-kaldı).
  - **(7) YAYINLAMA-SIRASI + NÖBET:** Cline-taslak **TESLİM** (§4.1 arması ile ~85 satır) → **Hakem-metin-onayı** → **Reis: iki-bülten-tek-yayın-olayı** (N2#18 + AM-N19-5-düzeltmesi · D62) → Luna + Owner (Aşama-5). Tetik-saat: eşik **2026-09-04T00:03:10+03:00**, ölçüm **2026-09-03 ~09:00 TST** → **AŞILMADI (~15h)**, mini-set talebi üretilmedi. Sınır: **kod-artefaktları değişmedi** (modül/test/harness hash'leri aynı → 31-passed iddiası yeniden-koşum-gerektirmez), S-a üçlüsü temiz, lint temiz, **push YOK**, `index.json` üretilmedi.
  - **(8) ARMA-GÜÇLENDİRMESİ + PIN-SÜPERESYONU (aynı-oturum, ~09:10 TST):** iddia-yanlış-değil-eksikti, tamamlandı — `apply_dd_scaling` `entry_ts=None`'da **da** `ValueError` atıyor ve hata-metni şema-kusurunu **kendi-kelimeleriyle** söylüyor: *"the canonical BenchmarkTrade has no entry_timestamp field — the caller must pass it explicitly"* (`main_research_c_v1_1.py:411-416`, okundu). → **iki-dal-da-sert-hata**: (a) liste-yok → anında, (b) iz-seviyesi-liste → **331/512** ValueError; **sessiz-geçme-dalı motor-tarafında-mevcut-değil**. Üç-dokümana-işlendi (bülten §4.1 · evidence §10.2.2 · spec §6-7). Yan-kontrol: dokümanlarda-phantom-path yok (`src/strategy/breakout.py` atıfı **reddedilen-alternatif** beyanıdır, dosya-varlık iddiası değil — incelenip-temizlendi). **Bu-kayıt-anındaki-dış-pinler** (progress.md kendi-kendini-pinleyemez, §0): spec `9afa31ea3245d0a2`/286L → (7-madde-sonrası-yenilendi) · evidence `8e141c27385f967e`/194L → (yenilendi) · bülten `fc72045069e8dff2`/86L → (yenilendi) — nihai-pinler-mesaj-taşıyıcılığında; kod-üçlüsü-değişmez: `54a20b843bdd0c36` · `e09c88cad92377a0` · `c6de43d942aeedb6`.

- **D62-RATİFİKASYON-İCRASI + BÜLTEN-TAM-METİN-TESLİMİ (Cline, 2026-09-03 09:17 TST ölçüldü; Hakem hükmü FAZ-2d-İCRA işlendi — RED-YOK):**
  - **(1) İKİ-BÜLTEN-TEK-YAYIN öncesi tek-kalan-kapı AÇILDI:** bülten-tam-metini Hakem'e yapıştırıldı (mesaj-taşıyıcılığında; §13.5 receiver-confirmed). Yayın-öncesi-son-kapı = Hakem-metin-onayı → ardından Reis-yayın-olayı.
  - **(2) §2.1 BAĞLAYICI-DİL UYGULANDI:** bülten §4 başlığı → `Aritmetik-kimlik *(round6-tutarlılığı)*` + gövdeye ham-pekis-notu (`max(pnl_r)=1.8000000000014802`, birebir-float-değil). Float-kimliği-indirimi artık bülten-diline-bağlayıcı. MaxDD-yayınmama ilkesi bülten §5.5'te zaten mevcut — dokunulmadı ✓.
  - **(3) AM-N19-6 YERİNE GETİRİLDİ:** 12-koşum-dökümünün tekrar-üretilebilirlik-standardı bülten §9'a işlendi — komut-satırı `python "%TEMP%\d62_decomp.py"` + script-kimlik-mührü (2661 B · mtime 08:27:18+03:00 · sha256-ön-ek `ccf484d7c38ace42`) + beklenen-çıktı-satırları. Kanıt-zinciri: script yalnız repo-modüllerini çağırır → döküm "tekrarlanamaz-kanıt" sınıfından çıktı. Eş-zamanlı: aynı-mühür evidence §10.2.1'e de yansıyacak-mi kararı Hakem'e bırakıldı; bülten-§9 yeterli-belgelendirme olarak okundu.
  - **(4) SAYIM-DİSİPLİNİ (§13, ölçüldü):** bülten 86→**88 satır** (`wc -l -c` bu-turda; CRLF-sayımı-dahil). Önceki "68-satır" beyanı §4.1-arması-öncesi-revizyona aittir — silinmedi, üstü-buradan-görünür (§12.1).
  - **(5) ADER-3 GREP-TEYİDİ (Hakem-§5-açığı kapatıldı):** defter-satırı **VAR** → `progress.md:964` "(4) KURAL-ADER-3 (vacuous-green) DEFTER-SATIRI" ✓. Resmî AGENTS.md-girişi **YOK** (`grep ADER AGENTS.md` = boş) — bu-owner-batch'idir, beklenen-eksik; Hakem-beyanı-hata-kaydı-gerekmezdi. Simetrik-teyit: Hakem'in-"defter-satırı-şimdi"-beyanı-boş-çıkmadı.
  - **(6) KAPILAR DEĞİŞMEDİ:** T0#7 = Reis-boot (birincil-bloker) ∥ eşik 2026-09-04T00:03:10+03:00, ölçüm 09:17 → **~14h46m, AŞILMADI** → yetki-talebi-yok. Push YOK · `index.json` üretilmedi · kod-üçlüsüne-dokunma-yok (`54a20b843bdd0c36`/`e09c88cad92377a0`/`c6de43d942aeedb6` değişmez) · N2#18-taslağına-dokunma-yasağı sürüyor · S-a temiz.

- **D62-BÜLTENİ v1.1 — HAKEM ONAY-AMENDMANLI İCRASI (Cline, 2026-09-03 09:51 TST ölçüldü; Hakem hükmü: ÇEKİRDEK-ONAY · ÜÇ-AMENDMAN yayın-öncesi-uygulandı · RE-OKUMA-YOK · RED-YOK):**
  - **(1) HÜKÜM-KABULÜ:** Hakem bağımsız-aritmetik-mührü (sembol-ΔR toplamı = −395.80 = ΔR-toplamı birebir; 6/6 çift; WR-farkı 27.7; §4-kimlik 371.80) not edildi — sayı-dokusu doğrulanmış-ürün. Üç-amendman Hakem-elinden-birebir-satırlarla `results/D62_breakout_timing_bulletin_draft.md` içine işlendi.
  - **(2) AM-N19-7 (borç-kapanışı):** §4.1 tablosuna `grid-kimliği` satırı eklendi — `hold_bars −6 × 15 dk = −90 dk ↔ (05:30 − 04:00) birebir`; örnek-satırının −1s30dk beyanıyla bar-grid kimliği artık açıkça bağlantılı (ihlal gerçek-duvar-saati ters-sıralaması, bar-etiketi-yanılsaması değil).
  - **(3) AM-N19-8 (§9-repro-tamamlama):** iki-git-komutu eklendi ve **bağımsız yeniden-ölçüldü** (`git log -1 --format=%cI` → `c66888a`=2026-08-31T21:00:52+03:00 · `7a6d564`=2026-09-02T11:57:53+03:00 — Hakem-satırlarıyla birebir); `--corrected` satırına beklenen-çıktı iliştirildi (`513T / +16.20R / hold_bars<0 = 0/513`).
  - **(4) AM-N19-9 (yanlış-atıf İCRASI):** §4.1 kronoloji-parantezi *"(Hakem-hipotezi 'bir-gün-sonra'…)"* SİLİNDİ; yerine Hakem-elinden tek-satır: *(kronoloji hipotez-değil, iki-commit-timestamp'ının-ölçümüdür; bypass-okuması-hipotezden-bağımsızdır.)*. Kalan-cümle kendi-ayakta. Ders-kaydı: **beyan-≠-kanıt Hakem'e-de uygulanır** — §3 katman-hiyerarşisinin tarafsızlığı doğrulanmıştır.
  - **(5) ÜÇ-TEYİT-GREP'İ (Hakem-§3, yayın-öncesi-teyit-seviyesi, ölçüldü):** `grid-kimliği` → §4.1 satır-45 ✓ · `%cI c66888a`/`%cI 7a6d564`/`beklenen: 513T` → §9 satır-86-88 ✓ · `iki-commit-timestamp` → satır-49 ✓; yanlış-atıf-literal'i için grep **= 0** ✓ (checklist-satırı kelimeyi-içermesin diye yeniden-yazıldı — self-defeating-grep düzeltmesi, §13.5 ruhu).
  - **(6) TAZE-PİN (belge-kendi-kendini-pin'leyemez — Hakem-emri, ölçüldü):** bülten v1.1 = **93 satır / 12214 B** · sha256-ön-ek `ad3fa87b5660f6b0` (09:51 TST; 88-satır önceki-pin-in-üstü-buradan-görünür, §12.1). Yayın-anında-bir-daha-yenilenir ve yayın-mesajı-taşır (§8-yeni-checklist-maddeleri: v1.1-teyit-grep-i + taze-pin-ölçümü, AM-N19-5'le-aynı-adım).
  - **(7) KAPILAR DEĞİŞMEDİ:** Zincir aynen — **A T0#7 (Reis-boot, birincil-bloker)** → **B1' iki-bülten-tek-yayın (v1.1-hazır)** → B2 → A6-mühür → N2#19-set-mührü (6-dosya + `index_builder --full` bilinçli-adımı) → Faz-3-owner-paketi (gate KAPALI/HOLD). ∥ ③-değerlendirme-masası açılmadı · ADER-3-grep-teyidi bir-sonraki-yazım-döngüsünde. Tetik-saat nöbeti sürüyor (eşik 2026-09-04T00:03:10+03:00, ölçüm 09:51 → ~14h12m, AŞILMADI → yetki-talebi-yok). Push YOK · `index.json` üretilmedi · kod-üçlüsüne-dokunma-yok · N2#18-taslağına-dokunma-yasağı sürüyor · S-a temiz.
- **D62-v1.1 BAĞIMSIZ-ÇAPRA-TEYİDİ + ÖZ-DÜZELTME + EŞZAMANLI-YAZAR-İNSİDANI (Cline-#2 oturumu, 2026-09-03 10:25 TST ölçüldü; Hakem ONAY-AMENDMANLI hükmünün ikinci-el-doğrulaması):**
  - **(1) ÜÇ-AMENDMAN BİREBİR-DOĞRULANDI (kaçışsız-yöntem — `tr -d '\r'` + `grep -F -o -n -f`, shell-escape-artifactı-devre-dışı):** AM-N19-7 `grid-kimliği` → **satır 45** ✓ · AM-N19-9 yeni-parantez `*(kronoloji hipotez-değil, iki-commit-timestamp'ının-ölçümüdür; bypass-okuması-hipotezden-bağımsızdır.)*` → **satır 49** ✓ (italik-sarmal dahil, apostrof **0x27** ASCII) · AM-N19-8 iki-git-komutu → **satır 87/88** ✓ · `beklenen: 513T / +16.20R / hold_bars<0 = 0/513` → **satır 86** ✓ · yasak-literal `Hakem-hipotezi` → **0 eşleşme (silinmiş)** ✓. **Tek-biçimsel-sapma (vetoya-saklı, öneri-kalsın):** AM-N19-8.3 Hakem'in-ayrı-komut-satırı olarak değil mevcut `--corrected` satırının **yorumuna-birleştirilmiş** — içerik-tam, **komut-çiftlenmesi-yok** (repro-blokta-iki-aynı-komut-daha-kötü-olurdu). **Eşitlik-notu (Hakem-§2-tablosuna):** "AM-N19-7 ✗ EKSİK" değerlendirmesi **86-satırlık-eski-anlık-görüntüye** aittir — onay-için-yapıştırılan-93-satırlık-v1.1'de üç-amendman-satırı **zaten-var** idi (satır 45/49/87/88, yukarıda-birebir-doğrulandı). Yani "borç", hüküm-gelmeden-önce-ödenmişti; **sonuç-değişmez**, kayıt-düzeltmesidir (§12.1; *beyan-≠-kanıt ilkesi okuma-anlarına-da uygulanır*).
  - **(2) HAKEM-ARİTMETİĞİ İKİNCİ-ELDEN-YENİDEN-ÜRETİLDİ:** sembol-ΔR-toplamı 84.00+72.80+73.80+56.00+67.20+42.00 = **395.80 = ΔR-toplamı** ✓ · 6/6 çift-farkı birebir ✓ · WR-farkı **27.7** ✓ · §4-kimlik 451.8−80 = **371.80** ✓ · per-trade 0.8047→0.0316, oran **25.48** (§1 "~25×" / §3 "25.5×" tutarlı) ✓. **PİN-ÇAPRAŞMASI-YOK:** bu-oturumun-bağımsız-ölçümü = **93 satır / 12214 B / sha256 `ad3fa87b5660f6b0`** — paralel-oturumun-:984-kaydıyla **birebir aynı üç-değer** (iki-oturum, tek-mühür).
  - **(3) ÖZ-DÜZELTME (§12.1 — görünür-kalsın, beyan-≠-kanıt bana-da):** önceki-turda "mesaj-taşıyıcılı-kod-üçlü-pinleri hiçbir-yöntemle-yeniden-üretilmiyor" **bulgusunu yaydım — bu bir ETİKET-KAYDIRMASIYDI.** `54a20b843bdd0c36` / `e09c88cad92377a0` / `c6de43d942aeedb6` **experiment-üçlüsünün değil N2 #19 PORT-ÜÇLÜSÜNÜN** pinleridir ve **üçü-de birebir-doğrulandı**: `src/live/breakout_variant.py` = `54a20b843bdd0c36` ✓ · `tests/test_n2_19_breakout_port_parity.py` = `e09c88cad92377a0` ✓ · `tools/n2_19_parity_check.py` = `c6de43d942aeedb6` ✓. Experiment-üçlüsünün gerçek-mühürleri **zaten :920'de** yöntem-üstelikli-kayıtlıydı (blob-LF `9696f64cc89a80dd`/`a081ee8e9ffd5473` + worktree `9ccd2e4eeb0fa774`/`24a5172defc5ce06`, `i/lf w/crlf`, JSON `w/mixed`). **Sonuç: sınır-iddiası yanılmamış — şimdi olumlu-doğrulanmış.** Yanlış-negatifi-üreten-ikinci-şey: kendi-geçici-script'imin needle-yazım-hatası (AM-N19-9'u "YOK" gösterdi); yöntem-tercihi-bundan-böyle-**`grep -F -f` dosyadan**.
  - **(4) EŞZAMANLI-YAZAR-İNSİDANI (§10.1/§13.5 — süreç-olayı, gürültü-değil):** aynı-bülten-üstünde **ikinci bir Cline oturumu** 09:17–09:52 aralığında yazdı (bülten 09:51:10 · defter 09:52:54; `progress.md` 969→976→**985 satır**, `5abfd29c`→`0f378e05`→`276a1a92`). Bu-oturum (Cline-#2) AM-N19-7'yi **bilmeden mükerrer** ekledi → **tespit-edip geri-aldı (net-sıfır, diff'te-iz-yok)**; sonrasında **tek-harf-eklemedi** ve Hakem-emri-olduğu-için-yalnız **EOF'a-ekleme** ile yazdı (hiçbir-mevcut-satırı-değiştirmedi). Watcher-değildi: `tasklist` python-yok. **KARAR-GEREKTİRİR (owner/Reis):** yayın-anına-kadar bülten ve defter **tek-elde-donmalıdır**; iki-yazarlı-belge = pin-i-geçersiz-kılan-kosu.
  - **(5) HAKEM-EMRİ OWNER-BATCH-SATIRI (dokunuş-yok, yalnız-defter):** tip-hijyen-ailesi — `BenchmarkTrade.exit_timestamp: float` annotation'ına **pandas-Timestamp** geçiriliyor (dataclass-zorlamaz, sessiz-tip-sapması). Kaynak: `main_research_c_v1_0.py:62-97` şeması.
  - **(6) COMMIT-ANI-NİT (şimdi-dokunuş-yok):** `docs/T0_7_PREBOOT_CHECKLIST.md` başlığı **v1.1**'de-duruyor (ölçüldü) → D.2-eki ile birlikte **v1.2'ye-bump** commit-anında. ADER-3-defter-satırı ayakta (`grep 'Boş-yeşil kanıt değildir'` = 1 ✓).
  - **(7) KAPILAR + SAAT (ölçüldü, değişmedi):** **A T0#7 (Reis-boot, birincil-bloker)** → **B1′ iki-bülten-tek-yayın (v1.1-hazır, üç-AM-uygulanmış)** → B2 → A6-mühür → N2#19-set-mührü (6-dosya + `index_builder --full` bilinçli-adımı) → Faz-3-owner-paketi (gate **KAPALI/HOLD**, "neden-açılmamalı" cevabıyla). ∥ ③-değerlendirme-masası **açılmadı** (girdi-hazır; ④-çıkışı *DD 8→9.87*). Eşik `2026-09-04T00:03:10+03:00`, ölçüm **10:25:02+03:00 → ~13h38m, AŞILMADI** → yetki-talebi YOK. Push YOK · `index.json` üretilmedi · N2#18-taslağına-dokunma-yasağı sürüyor · `experiment/`-üçlüsü-doğum-gününde-ve-HEAD-temiz · S-a/S-d temiz.

- **D63-AMENDMAN — FREEZE-PİN DÜZELTMESİ (Hakem-öz-düzeltmesi-2) + PORT-ÜÇLÜSÜ-İADESİ + ADER-5 (Cline, 2026-09-03 10:48:40 TST ölçüldü; Hakem hükmü: ÇAPRAZ-TEYİT RATİFİYE · RED-YOK · B1′ HAKEM-TARAFINDA-AÇIK):**
  - **(1) FREEZE-PİN DÜZELTİLDİ — dört-ayaklı-mühür:** `results/D62_breakout_timing_bulletin_draft.md` = **93 satır / 12214 B / sha256 `ad3fa87b5660f6b0`** [yöntem: `sha256sum <worktree-yol>` — CRLF-byte, LF-normalize-değil]. Ayaklar: ① amendments-oturumu 09:51:10 · ② ledger `:984` · ③ bu-oturum-yeniden-ölçümü · ④ **09:51:10 → 10:48:40 = 57 dk zero-writer-durağanlığı** (`stat` mtime-hareketsiz). **Süpersedde-kaydı:** `6312e51c`/12109 B = *"kaynaksız-geçici-ölçüm"* sınıfı — **defterde 0-kez-geçiyor** (`grep -c 6312e51c` = 0, yalnız-chat-taşıyıcılı, disk-karşı-doğrulanamaz), ne-doğrulanır-ne-yanlanır (§12.1-uyumsuz). **Hakem-öz-düzeltmesi-2:** donma-hükmü, aynı-mesajda-defterli-ters-pin-dururken **tek-kaynaklı-sayıya** verilmiş — *beyan-≠-kanıt-Hakem'e-ikinci-uygulama* (birincisi-D59). **Donma-kendisi-değişmedi:** bülten **0-yazar**, yayına-dek.
  - **(2) AM-N19-10 UYGULAMA-DÜZELTMESİ (port-üçlüsü İADE):** `54a20b843bdd0c36` = `src/live/breakout_variant.py` · `e09c88cad92377a0` = `tests/test_n2_19_breakout_port_parity.py` · `c6de43d942aeedb6` = `tools/n2_19_parity_check.py` — üçü-de **birebir-reproduce** [yöntem: `sha256sum <worktree-yol>`]. Önceki **"bilinmeyen-yöntem" etiketi KALDIRILIR**; **AM-N19-10 kural-olarak-ayakta** (method-tagging), yalnız-uygulaması-düzeltildi. Experiment-üçlüsünün-mühürleri zaten `:920`'de yöntem-üstelikli (blob-LF `9696f64cc89a80dd`/`a081ee8e9ffd5473` · worktree `9ccd2e4eeb0fa774`/`24a5172defc5ce06` · JSON `w/mixed`).
  - **(3) ADER-5 (yeni-defter-kuralı):** *"Pin-iddiası = dosya-yolu + form + yöntem üçlüsüdür; yarım-beyanlı-pin-iddiası sınır-ihlali-alarmı-üretmez, düzeltme-ister."* Yanlış-dosya-hash'i **sahte-ihlal-alarmı** üretti (iki-yanlış-negatifin-kardeşi: yanlış-dosya + needle-escape). **Boundary-ihlal-ihtilafında-ilk-soru: hangi-DOSYA?**
  - **(4) DUFF-STANDARDI (byte-teyit-tanımı):** kaçışsız-duff = `tr -d '\r'` + `grep -F -o -n -f <pattern-dosyası>`; **`python -c` içinde-escape-yasak.** Bu-tur-üç-kritik-satır-böyle-mühürlendi (satır 45/49/87/88) + yasak-literal `Hakem-hipotezi` = **0 eşleşme**.
  - **(5) AM-N19-8 KABUL-VARYANI:** `beklenen: 513T / +16.20R / hold_bars<0 = 0/513` → satır-86'da `--corrected` yorumu-içinde-taşınır; **birleşik-biçim KABUL, split-istemi YOK** (ayrı-satır = repro-blokta-birebir-duplicate-komut; §8-grep-maddesi "ayrı-satır" şartı içermiyor).
  - **(6) KURAL-6-SİMETRİSİ BU-TUR YEŞİL:** ADER-3-defter-satırı `grep -c 'Boş-yeşil kanıt değildir'` = **1** ✓ → Hakem'in-"deftere-gir"-beyanı-doğrulandı, **hata-kaydı YOK**. Eşitlik-notu-kabul: "AM-N19-7 ✗ EKSİK" değerlendirmesi **88L-snapshot-scoped** idi; kalıcı-borç yok — *"borç-yoktu, ödeme-önce-yapılmıştı."*
  - **(7) CHECKLIST-NİT TEYİDİ:** `docs/T0_7_PREBOOT_CHECKLIST.md` başlığı **v1.1**'de-duruyor (ölçüldü) → **v1.2-bump commit-anında**, bump **taze-pinle-girer** (belge-kendi-kendini-pin'leyemez). Proposal-kabul.
  - **(8) KAPILAR + SAAT:** **A T0#7 (Reis-boot, birincil-bloker)** → **B1′ — HAKEM-TARAFI AÇIK** (Reis-checklist: AM-N19-5-tarih-düzeltmesi + üçlü-gönderim/Aşama-5 + v1.1-grep'leri + taze-pin-taşıma) → B2 → A6-mühür → N2#19-set-mührü (6-dosya-donuk + `index_builder --full` bilinçli-adımı; port-üçlüsü-orada-git-mühürü-alır) → Faz-3-owner-paketi (gate **KAPALI/HOLD**). ∥ ③-değerlendirme-masası açılmadı (girdi-hazır; ④-çıkışı *DD 8→9.87*). Eşik `2026-09-04T00:03:10+03:00`, ölçüm **10:48:40+03:00 → 13h14m, AŞILMADI** → yetki-talebi YOK. Push YOK · `index.json` üretilmedi · tracked-delta yalnız `M AGENTS.md` + `M progress.md`. **Reis'e-kalan-tek-karar (Hakem-önerisi):** implementer-**oturum-topolojisi** — konsolidasyon veya açık-partisyon-deklarasyonu (bülten-donuk → dosya-çatışma-riski sıfır).
  - **(9) LEDGER-PİNLERİNE METHOD-TAG (AM-N19-10 tam-kapsam — non-blocking-satır):** tüm-defter-pinleri bundan-böyle **[yöntem: …]** etiketiyle-yazılır. Bu-bloğun-öncesi: `progress.md` = 994 satır / sha256 `f305bfdb802a9f2f` [yöntem: `sha256sum <worktree-yol>`, CRLF-byte, LF-normalize-değil; mtime 10:36:21] → önceki-zincir 969L/`5abfd29c` → 985L/`276a1a92` [aynı-yöntem, paralel-oturum-kaydı]. Bu-append-sonrası-taze-pin aşağıda-ölçüldüğü-gibi-kaydedilir (belge-kendi-kendini-pin'leyemez → pin, bir-sonraki-girdinin-kaynağıdır).


- **D64 · FAZ-A — CBDR BIAS-GÜN CENSUS'U (Cline, 2026-09-03 11:23 TST ölçüldü; Hakem-çağrısı "FAZ-A =ifa-sonrası-sıradaki-iş"; çıktının-mührü-aşağıda):**
  - **(0) DEVİR-MÜHRÜ-DEVRALINDI (ratifiye-protokolün-ilk-icrası):** bu-girdiden-önceki-defter-durumu = `memory-bank/progress.md` **1006 satır / sha256 `0bd5a5d53bbd2299`** [yöntem: `sha256sum <worktree-yol>`, CRLF-byte, LF-normalize-değil] · zincir: `5abfd29c → 276a1a92 → f305bfdb → 0bd5a5d5` → terminal-kuralı-ayakta (her-push'ta-git-hash'ine-sıfırlanır).
  - **(1) MANDAT-İZİ-KAPATILDI:** §0.1'de-beyan-edildiği-üzere FAZ-A/D64 mandatı defterde **0-satır** idi (yalnız-chat-taşıyıcılı) → `results/D64_bias_census_evidence.md` **§0-pre-reg ile açıldı ve sayım ÖNCESİ tanıt-pin'lendi** (*tanımsız-sayım-yasak / "Sayım≠kanıt"*). Bias-gün-tanımı 6-madde: `cbdr_day_key` = pencerenin-BİTTİĞİ-tarih · gözlemlenebilirlik = pencere-dışı-bar-şartı · `bias_locked` + `daily_bias` · NEUTRAL = gözlemlenebilir-ve-kurulmamış · ilk-sweep-kazanır · tolerans = `0.5 × ATR14(warmup)` **donmuş**.
  - **(2) CENSUS (6-sembol, 2024-01-03→2026-08-22, 15m, kanonik-sürücü):** gözlemlenebilir **4,104 gün**, kurulmuş **3,401** → **bias-oranı %82.87** (sembol-bazında **%79.53 USDCAD → %88.74 EURUSD**) · BULL 1,575 / BEAR 1,826 (**%53.7 bear, 6/6 sembolda**) · lag-medyan 7–28 bar. **İç-tutarlılık:** `826 − 684 = 142` = §0.3'te-bağımsız-ölçülen-hafta-sonu-kapanış-günleri (92+50) → payda-düşüşü keyfi-değil; `BULL+BEAR = 3,401 = kurulmuş` ✓.
  - **(3) ARTIMSAL-KAZANÇ (EURUSD, n=607, tol-birimi, TRADE-EDİLEMEZ):** bias-yönlü mean **+0.8593** / hit **%52.22** · always-long −0.3022 · always-short +0.3022 → **sabit-baz-çizgiye-göre +0.5571 tol/gün bilgi-farkı**; ANCAK aralık-gürültüsü mean|·| ≈ **20.9 tol** = sinyalin ~24 katı, hit-rate yazı-turaya-yakın, median>mean (negatif-kuyruk). **Canlı-edge-iddiası YOK** (giriş/SL/TP/fee yok). Bar-bazlı-normalizasyon **FAZ-B pre-reg'ına-bırakıldı** (tanım-şimdi-değiştirilmez).
  - **(4) FUNNEL-ÖNGÖRÜSÜ DOĞRULANDI:** artefakt `traces[].cycle_day` join'i → iz-günleri **4,066**, bias-kurulmuş **3,386** = **%83.28** vs census **%82.87** → **6/6 sembolda ≤0.62 pp**.
  - **(5) PARİTE-TEYİTLERİ (en-ağır-madde — census-makinesi = üretim-makinesi):** **CBDR gövde-paritesi 2,400/2,400** (6×400 örnek, `traces[].body_high` ↔ yeniden-yürütülen `cbdr.body_high`, bağıl ≤1e-9) · **tolerans-paritesi 6/6** (`traces[].tolerance` ↔ `0.5×ATR14(warmup)`, ≤1.6e-5) · **donmuş-tolerans-iddiamın-üstü-artefakt-kendi-alanıyla-açıldı:** `tolerance_source = "0.5 * session.atr (engine-parity: run_test_a kurulum-ATR)"` → benim-`grep 'session\.atr' = 0` statik-çıkarımım (svy-6) **artefakt-provenance'ı (svy-2/3) ile teyitli** (ADER-3-ruhu: kod-olgusu → üretim-kaydı).
  - **(6) YENİ-KAYIT-BULGULARI (owner-paketi-girdisi):** `master_bias` kanonik-kolda **407/407 boş-string** → bias hesaplanıyor ama **trade-defterine-yazılmıyor** (Faz-3 "neden-açılmamalı" listesine) · `DataLoader.list_symbols()` çok-TF dizinde sahte-sembol üretiyor → `FileNotFoundError` (ölçüldü, **dokunuş-yok**, backlog) · zaman-tabanı doküman-çelişkisi: loader *"UTC (as-is from MT5)"* vs `config.py:30` *"MT5 server time"* vs `exp4b_oos.py:25` *"UTC"*; ampirik: günlük-açılış-modu 0 / kapanış-modu 23 (12/12 ay), hafta-sonu kapanışı 92 gün h20 + 50 gün h21 → census **tabanı yeniden-yazmadı**, kanonik-gibi-ham-kullandı; taban-sorusu ③'de.
  - **(7) SINIR + KAPILAR + SAAT:** çıktının-mührü `results/D64_bias_census_evidence.md` = **137 satır / 12,640 B / sha256 `8b18f70acc74ae1a`** [yöntem: `sha256sum <worktree-yol>`, CRLF-byte] · **untracked** · hiçbir-kod-artefaktı-değişmedi (`git status --untracked-files=no` → yalnız `M AGENTS.md` + `M progress.md`) · koşum-scriptleri `%TEMP%` · push YOK · `index.json` üretilmedi · D62 bülteni **0-yazar** (`ad3fa87b`/12,214 B/93L, mtime 09:51:10 — **81 dk**) · FAZ-A çıktısı-da-Reis-sinyalinde-donar. Kapı: **A T0#7 (Reis-boot)** → B1′ → B2 → A6-mühür (terminal-1) → N2#19-set (terminal-2) → **FAZ-B pre-reg (girdisi: %82.87/%83.28 + master_bias-boşluğu)** → Faz-3-owner-paketi (KAPALI/HOLD) ∥ ③-masası açılmadı (④: DD 8→9.87; **BEAR-ağırlığı %53.7 ③'nin-ortak-şüphelisi**). Saat **11:23:33+03:00**, eşik `2026-09-04T00:03:10` → **12h40m, AŞILMADI** → yetki-talebi YOK.
  - **(8) ZİNCİR-TEYİDİ (protokolün-ilk-icrasında-yükselme — ADER-5-ruhu):** devir-pini **taşınmadı, yeniden-üretildi**: bu-girdinin-bloğu-geri-sararak (`head -1006` + `tail -n +1017`) yazım-öncesi-durumu yeniden-inşa → **1006 satır / sha256 `0bd5a5d53bbd2299` = emanet-alınan pinle BİREBİR eşleşti**. Yani zincirin-son-halkası artık *iddia* değil *doğrulanabilir-olgu*; yöntem-yeniden-üretilebilir (`[yöntem: blok-geri-sarma + sha256sum]`). Hakem'in "tek-teorik-risk" olarak işaretlediği **sonsuz-geçerlilik-iddiası** bu-yöntemle bir-kat-daha-zayıfladı: her-girdi-kendinden-önceki-pini **kanıtlayarak** açılabilir. Yeni-mevcut-mühür: kapanış-pini protokol-gereği **bir-sonraki-girdinin-açılış-satırına-emanet** (bu-girdi-sonrası-ölçülen-satır-sayısı aşağıdaki-düzeltmede). *(Düzeltme: bu-madde-yazılırken "1017 satır" denmişti; ölçülen **1018 satır** — kendi-kendine-pin-iddiası-geri-çekildi, çünkü her-düzenleme-pini-değiştirir; tek-doğru-usul devir-emaneti.)*


- **D66 · SINIF-2-KAMP-1 AÇILIŞI — T0#7-AMENDMANLI İCRA, İLK CANLI-ZİNCİR (Cline-executor, 2026-09-03 14:07–14:40 TST ölçüldü; Hakem hükmü "D66/SINIF-2-KAMP-1 açılışı"; devir-mührü: `memory-bank/progress.md` = **1018 satır / sha256 `161abf2527236ac2`** / mtime 11:28:31 [yöntem: `sha256sum <worktree-yol>`, CRLF-byte, LF-normalize yok] — zincir `5abfd29c→276a1a92→f305bfdb→0bd5a5d5→161abf25` taşınmadı, ölçüldü).**
  - **(0) MCP-ZORUNLULUĞU (AGENTS.md §1):** codebase-memory bu-oturumda **indekslenmemişti** → `index_repository(fast)` koşuldu: `5934 node / 16847 edge`, proje `C-Users-Administrator-Desktop-sniper_forex` (`tools/` kapsam-dışı). §1.3 "UNAVAILABLE" beyanı gereksiz-kaldı; indeksleme-repoya-yazmadı (`persistence=false`).
  - **(1) AŞAMA-0 CAPTURE (AM-T7-3, boot-öncesi):** `state/d66_capture/` 6/6 majör · 1551–1552 M1 · server `2026-09-02 12:00 → 09-03 13:52` · sha256'lar D66_sweep_detection §0.6'da · `_capture_manifest.json` (build 6140, captured_at 13:51:59+03:00). **İki-MT5-tuzagi ölçüldü (Bulgu-5):** `copy_rates_range` naive-datetime'ı YEREL sanıp pencereyi −3h kaydırıyor; `symbol_select` öncül-olmazsa GBPJPY **bayat (Aug 20–21)** veri veriyor (2sn-sonra doğru) → `copy_rates_from_pos`+epoch-filtre+tazelik-koruyucusu.
  - **(2) AŞAMA-1 DETECTION — SAYIMDAN-ÖNCE-TANIM (§0):** `results/D66_sweep_detection.md` = **128 satır / 11,718 B / sha256 `3cbc74fc064a05f2`** (untracked). Enstrüman **yeniden-yazım-değil**: canlı `StrategyRuntime`+`candle_feed.resample_15m`+`clock.server_to_utc_historical` offline sürüldü (§2.2/§3). **Sweep-tablosu (V-LIVE, kapsam-içi):** EURUSD `09-02 16:15 bullish` (marj **+1.98 pip**) · GBPUSD `09-02 16:30 bullish` (+9.79) · USDCAD `09-02 16:30 bearish` (+2.60) · AUDUSD `09-03 10:15 bearish` (**+0.75**, tek kilitli-bias) · USDJPY/GBPJPY **açıkça "none-today"**. **Tie-break en-erken-ts → X=EURUSD → Aşama-2 swap-YOK, `.env`-dokunulmadı** (override-yetkisi ayakta, kullanılmadı).
  - **(3) HÜKÜM-PİNLERİNE KOD-KANITLI ÜÇ-DÜZELTME:** **(a) pencere-bazı:** `candle_feed.py:113–118` M1'i UTC'ye çeviriyor, `SessionManager.in_window` UTC-üzerinde → fiilî pencere **server 22:00→04:00**, sweep-bandı **server 04:00→22:00**; hükmün "04:00→19:00" pininin 04:00-uca doğru, 19:00-uca **3s hatalı** (`clock.py:13` docstring kendi dönüşümüyle çelişiyor; `in_session` üretimde **çağıran-yok** = ölü-kod). **Hâkim'in W2-pini (22:00→04:00) düzeltmeyi bağımsız-doğruladı.** **(b) warmup-konumu belirsizliği SESSİZ ÇÖZÜLMEDİ:** V-LIVE (tarih-başı-ilk-100, motorun-fiili-şekli) vs V-PIN ("pencere-öncesi-son-100", hâkim-pin) → **iki-sembolde karar tersine dönüyor** (EURUSD 1→0 sweep; USDCAD NEUTRAL→BULLISH-locked). Mekanizma: `warmup()` `session.update()` **çağırmaz** → body-accumulation `_start_idx`'te başlar → **V-PIN scope-başında yapısal-kör** (`session.py:117–118`) → V-LIVE tercih-değil **mekanizmal-seçim**. **(c) zaman-tabanına-dördüncü-ölçüm:** `symbol.time` epoch'u UTC-okununca yerel-duvarla birebir → **MT5 server = UTC+3** (D64 §0.3 üçlü-çelişkisine ölçülen-cevap; loader'ın "UTC as-is" ifadesi etiket-yanılgısı, kod-ham-kullanıyor).
  - **(4) AŞAMA-3 BOOT (T0#7-amendmanlı, S-2):** **pid 3416 / 14:07:49**, `python -u -m src.live.run_production`, env `SNIPER_STATE_DIR=<mutlak>`+`SNIPER_SYMBOLS=EURUSD`, **`MT5_EXPECTED_LOGIN` SET EDİLMEDİ** (kredibilgi-hattı Reis; `mt5_config.py:25` `os.environ.setdefault` → process-env üstündür, `.env`-ezmez — hâkim-Aşama-2-iddiası kodla-teyitli). **§A takeover-kanıtı ÖNCE/SONRA:** `pid 3944` (yaş **51,691s** ≫ `LOCK_STALE_SEC=900`, `Get-Process` count=0 = DEAD) → `pid 3416` in-place; **artifact elle-silinmedi** (AM-T7-6). **§B dual-instance CANLI-ATESTASYONU GEÇTİ:** stderr `[run_production] Already running (lock owner PID 3416) - EXIT`, **exit 0**, lock'a dokunmadı. **Merdiven:** S9 `COLD_REBUILD_OK replay_bars=4237` → S11 `SAFE_START restored:true safe_reasons:["safe_mode_persisted: expected_login_unset","expected_login_unset"] warmup_bars=4338` → SAFETY `gate:closed`. **§7.2 mührü fiilen-doğrulandı: temiz-startup kalıcı-safe-mode'u AKLAMADI.** **D.2 İLK-DEFA YERİNE GELDİ:** `state/d66_boot_stdout.log` (14 satır) — T0#5/T0#6 hiç kalıcı-log bırakmamıştı.
  - **(5) SINIF-1→SINIF-2 PARİTİ (masa ilk-defa canlı-zincirde):** §1.8-öngörüleri **#1 COLD_REBUILD ✓ / #2 SAFE_START+gate ✓ / #3 day-key `2026-09-03` bias NEUTRAL ✓** (canlı S9 payload `bias:"neutral", session_key:"2026-09-03", end_state:"flat", next_idx:4338`) — **üçü-üç eşleşti**; W1'de **0 SIGNAL/SWEEP/ERROR**. Sayısal body/tol paritesi **BEKLİYOR** (canlı `session_atr` yalnız close-save'te) → **§1.6 kuralı: canlı-toleransla 65000-çekim yeniden-koşulmadan hiçbir satıra "parity" denmez.** `signals_discarded` 12→23 = girdi-farkı (pencere kayması), sapma-değil.
  - **(6) BULGU-1 · KRİTİK — AUDIT ZİNCİRİ BOOT-BAŞINA YOK EDİLİYOR (kod-kanıtlı):** `orchestrator.py:1040` `AuditChain(auto_flush_path=…)` mevcut-dosyayı **yüklemeden** kurulur · `audit.py:147` `self._events=[]` · `save()` `:247–255` tüm-listeyi yazıp `tmp.replace(path)` → **whole-file overwrite** · `AuditChain.load()` üretimde **sıfır-çağıran**. Docstring "In-memory **append-only**" der — append-only bellek-içi, kalıcılık overwrite. **Ölçülen:** Sep 2 23:08-bootunun 7 satırı → bugün 6 satır, yalnız-bugünkü-olaylar. **§18 "audit continuity" + §6.1 ihlali.** **KOD-DOKUNULMADI** (production-critical, ayrı-hüküm). **Sep 2 kayıtları bu-deftere ve D66-gözlem-dosyasına KURTARILARAK gömüldü** (WRITE_BLOCK dâhil) — dosyada artık-yoklar ve bir-sonraki-boot bugünkü 6 satırı da silecek: **bu-girdi o-zincirin tek-kalıcı-kopyasıdır.** WRITE_BLOCK'un-kendisi **kusur-değil**: `orchestrator.py:77–100` N2 #15-b öngörüsü (PID-eşsiz tmp + 8-deneme/~6.4s + `on_block`), kök-neden harici-AV-handle; mekanizma çökmedi.
  - **(7) BULGU-2/3:** runtime-state döngü-boyunca-persist-edilmiyor (`EURUSD.json` mtime hâlâ Sep 1 23:59; Sep 2-bootu da etmemişti → **her sert-ölüm tam-replay**) · lock `phase` "startup"'ta kalıyor, `created_at` heartbeat'le ilerliyor (+20s=poll) → §A'nın `phase=…` başarısızlık-imzası **wedged-vs-startup ayrımı veremez**.
  - **(8) CHECKLIST v1.1→v1.2:** `docs/T0_7_PREBOOT_CHECKLIST.md` = **105 satır / 12,009 B / sha256 `9a39f4bf6a28c073`** (untracked) — **AM-T7-1..6 işlendi** (§F) + §F.1 Cline-teşhis-notu (5 madde, görünen-ayrışma). AM-T7-1 §C.4 `<SYM>.json` parametrik; AM-T7-2 koşulu gerçekleşmedi (X==EURUSD) ama yetkisi ayakta; AM-T7-6 §A/§B metnine dokunulmadı. Gözlem-dosyası: `results/D66_production_path_first_observation.md` = **100 satır / 10,075 B / sha256 `c5e2ce39b2097d66`** (SINIF-2 etiketli, **AÇIK/KISMÎ**).
  - **(9) SINIR + KAPILAR + SAAT:** kod-artefaktı-değişmedi (`git status --untracked-files=no` → yalnız `M AGENTS.md` + `M progress.md`) · push YOK · `index.json` üretilmedi · `experiment/` trio ve `strategy_runtime` dokunulmadı · `.env` içeriği okunmadı (yalnız anahtar-ADLARI) · D62 **`ad3fa87b`/12,214 B/93L değişmedi** (0-yazar ≈4s49dk) · D64 **`8b18f70a`/12,640 B/137L değişmedi** (hâkim seal/amendment sırası hâlâ bekliyorum; A/B seçenekleri duruyor). Kapı: **A İCRA-DA (bu-girdi)** → B1′ iki-bülten-tek-yayın → B2 → A6-mühür → N2#19-set → FAZ-B/N2#20-pre-reg → Faz-3-owner-paketi (KAPALI/HOLD) ∥ ③-masası (D66-③-girdisi: **güçlü-trend günleri bias KİLİTLEMEZ, yalnız wick-reclaim kilitler** — sayım-değil mekanizma; USDJPY-yarı-nötrlüğüyle uyumlu) ∥ ADER-3-sonraki-grep. Saat **14:40+03:00**, tetik-eşiği `2026-09-04T00:03:10` → **9h23m, AŞILMADI**.
  - **(10) REİS-BİLDİRİMİ (üç-kanala; tek-kanal eksik-bildirim — §18):** **T0#7 bugün KOŞTU ve CANLI: pid 3416, SAFE_START, gate CLOSED, kalıcı-log var.** İki-karar-beekliyor: **(i) W2** — CBDR penceresi server **22:00→04:00**; W1 (19:00'da biter) yalnız sweep-bandını görür, **W2 bilgi-yüklü** (bias-event'lerinin ilk canlı verisi) → süreç 22:00-sonrasına taşınacak mı? **(ii) kill-zamanlaması** — §C yalnız **foreground Ctrl-C** istiyor; arkaplan-kanalı Sep 2'de `err_att=187` ile kırıldı, Cline-ortamı da SIGINT veremiyor → **duruşu Reis verir** (beklenen-exit **2**, AM-1 mode-bağlı). **Yeni-açık-hüküm gerekli: BULGU-1** (audit boot-başına-telafi) — kod-değişikliği yetkisi istemiyorum, yalnız-karar: `load()`+append-only mi / boot-başına-rotasyon mu / bilerek-mi-terk?


---

## D68 — AUDIT-CONTINUITY KRİZİ + W1 CANLI-BULGULARI (2026-09-03 15:20 server)

**Handoff-pin (taze-ölçüldü, yazım-öncesi):** `memory-bank/progress.md` **1032 satır / sha256 `f3a175d6ee1ae609` / mtime 14:46:38** — hüküm-pin'iyle **birebir tuttu** (arka-plan-mutasyonu YOK; §10.1 temiz).
`[method: sha256sum <worktree path>, CRLF-byte, LF-normalize not]`

### D68 hüküm-metni (Hakem, masaya)
> **D68 (2026-09-03, Cline-bulgu + Hakem-hükmü):** `AuditChain` **boot-başına-yok-ediliyor** — `orchestrator.py:1040` mevcut-dosyayı load-ETMEDEN kuruyor; `save()` whole-file-overwrite (`tmp.replace`); `load()` üretimde **sıfır-çağıran**. **Ölçülen kayıp:** Sep-2'nin 7 satırı (WRITE_BLOCK-dahil) bugünkü-boot'ta üzerine yazıldı; **tek kalıcı kopya = bugünkü defter-girdisi** (kurtarılmış-embed). **Sınıflandırma: §18 audit-continuity ihlali; D6/D48 zincirine mahkemelik.** D6-"lifecycle-dokunuşsuzluk" durumunu değiştirmez — crash-reaksiyonu değil, **sürekli-bileşen-kaybı**.

- **Kod-dokunuş-yasağı sürüyor** (production-critical, PID-3416 alive). Kurtarma deftere gömülü ✓, gözlem-dosyasına embed ✓.
- **Protokol-dikişi (AM-T7-7) YÜRÜRLÜKTE:** her boot-öncesi `cp state/audit.jsonl state/audit_prev_<date>.jsonl` (mask-bağımsız). **İlk icra ölçüldü:** `state/audit_prev_2026-09-03.jsonl` 9 satır / 2765 B @14:58.
- **Yol-kararı:** Hakem ön-önerisi **load+append-only = P0-rotası** (D18-atomics ailesi); final **Owner-batch**'ine (kod-yetkisi owner-domain). **N2 #21 adayı** — 4 fikstür (load+append / boot-rotasyon / overwrite-yasak / continuity-fikstürü) + mevcut 15+6+27 suite kırılmadan.

### W1 canlı-bulguları (Bulgu-6/7/8/9 — SINIF-2 GÖZLEM)
- **BULGU-6 · WRITE_BLOCK boot-içi de yineliyor.** Boot-olayları 14:07:51–56 → **45 dk sessizlik** → 14:52:40 WRITE_BLOCK → 14:52:46 `ERROR phase=audit_flush` → WRITE_BLOCK. N2 #15-b retry **~6 s'de kurtardı**; hata kendini kaydetti (sessiz değil). **Sayı-düzeltmesi (§13, gizleme yok):** W1 = **0 SIGNAL/SWEEP + 1 ERROR**.
- **BULGU-7 · T0-crash'ın kayıp audit-zinciri KURTARILDI.** `state/audit.jsonl.tmp` (Sep 1 23:59:02 / 1483 B / **PID-suffix'siz = pre-N2#15 kod**) **6 tam olay**, kesik-7.satır YOK → tmp tamam, **ölüm `tmp.replace()`te**. İçerik: MT5_CONNECT, STARTUP, S9-REPLAY, **S11 `verdict=PROCEED` `restored:false` `warmup_bars:4339`**, SAFETY, **SHUTDOWN `exit:1 reason:"run_exception:PermissionError"`**. **±18 ms yeniden-inşa:** `lock.tmp created_at=1788296341.9933` (pid **16984**) → +17.8 ms → SHUTDOWN `1788296342.0111`. Sıra: kilit-rename patladı → exception `run()`a → SHUTDOWN tampona yazıldı → audit-save tmp yazdı → **audit-rename'de öldü**. **En-ağır:** **Sep 1'de entry gate AÇIKTI** (bugünkü SAFE_START'ın zıddı) — bugüne dek yalnız *yorum* olan şey **audit-kaydıyla** doğrulandı. **Paradoks:** kayıp-üreten mekanizma kanıtı korudu (rename başarılı olsaydı sonraki-boot overwrite'ı bunları da silecekti). **Küçük yorum-kod çelişkisi:** `orchestrator.py:91` "`orchestrator.lock.<pid>.tmp` gösteriyordu" der, gerçek-yetimin **PID'siz** → fix henüz-yetişmemiş; **backlog (doküman-doğruluğu), kod-talebi yok.**
- **BULGU-8 · close-save YALNIZ graceful-stop'ta → parite-kapısı kill'e hapsedilmiş.** `schedule_snapshot` üretimde **tek-çağıran** `orchestrator.py:1661` = `shutdown()` gövdesi-içi (`audit.shutdown()` :1641 + MT5-release :1650 ile aynı blok); `recovery.py:187–191`; yorum itirafı: *"per-N-bar periodic save — graceful path alone cannot shrink the kill-9 window"* → **periodic save YOK**. Zincir: `session_atr` ⇒ graceful-stop ⇒ SIGINT ⇒ **konsol** ⇒ pid 3416 parent'ı **`nohup.exe`** (`crash_log.txt` satır-2) ⇒ **konsol YOK**. `orchestrator.py:2364–2365` yalnız SIGINT+SIGTERM, **SIGBREAK YOK**; Windows `os.kill(SIGTERM)`→`TerminateProcess` (handler çalmaz). **⇒ Hakem-kararı (iii) olduğu-gibi uygulanamaz:** W2 kendi-kendine `session_atr` üretmez. §1.6 parite ancak **konsollu-yeniden-boot + gerçek Ctrl-C** ile kapanır. **Plan-hatası değil, kodun yapısal kısıtı; ilk-defa ölçüldü.**
- **BULGU-9 · D68-P0'ya REPO-İÇİ EMSAL.** `state/crash_log.txt` **append-mode ve boot-atlatıyor**: satır-1 pid **3944** `ts 1788379690.446` (Sep 2 23:08:10), satır-2 pid **3416** `ts 1788433671.607` (bugün 14:07:51). Aynı kod-tabanında **fiilen-çalışan append-persistence var**; `AuditChain` kullanmıyor → **§2.2 gereği D68-P0'ın en-düşük-riskli emsali**, Hakem'in load+append-only önerisini bağımsız güçlendirir. Yan-ürün: devralınan kilidin **Sep 2 23:08 boot'una (pid 3944)** ait olduğu çift-kaynakla teyitli → §A takeover kanıtı pekişti.

### Ratifiye + düzeltmeler (Hakem §2)
3/3 SINIF-1→2 parite-çeşidi **kabul** (D65-ayrımının ilk SINIF-2 tarifi). **Düzeltme-#1** pencere server 22:00→04:00 **kabul**; **W1–W2 sınırı server dilinde 19:00→22:00**. **Detail-2 Hakemce düzeltildi** (kendi hatası): EURUSD 1→0 **bias YOK** · USDCAD **NEUTRAL→BULLISH bias VAR**; V-LIVE mekanizmal-seçim **ratifiye**. **Düzeltme-#3 yön-tarafı kanandı** → ③-masası **altı-parça**: *güçlü-trend günleri bias kilitlemez*. Bulgu-2 → **backlog**; Bulgu-3 → **§A-imza notu/backlog**.

### Açık-kalan (Reis+Hakem kararı bekleniyor)
**AM-T7-8 / §C kilidi:** pid 3416 nohup-altında → graceful-stop imkânsız. Üç-seçenek (gözlem-dosyası §9): **K1** konsollu-yeniden-boot (pariteyi açan tek yol; W1 sürekliliği kırılır) · **K2** izlet, §C'yi "nohup-altında imkânsız" mühürle (parite açık kalır, 65k ertelenir) · **K3** hibrit (3416 W2'yi gözler — §8.4 yalnız *persist*'i engeller, *hesabı* değil; sonra ikinci-boot yalnız §C+close-save+parite için). **Cline tercih-vermedi.**

**Boundary (yazım-sonrası-doğrulandı):** `git status --porcelain --untracked-files=no` = yalnız `M AGENTS.md`, `M memory-bank/progress.md`; `git diff --stat -- src/ tests/ index.json` = **BOŞ**. Push YOK. `.env` dokunulmadı. `orchestrator_safe.json` ve `orchestrator.lock` **korundu** (yetim `.tmp`ler de dahil — Bulgu-7 kanıtı). D62 `ad3fa87b…` / D64 `8b18f70a…` **değişmedi**.


## D70 · LAUNCH-MODU-KANIT-ZİNCİRİNİ-BELİRLER (sistematik-ders · 2026-09-03 15:30 · Hakem K3-hükmü)

**Ders-cümlesi (kalıcı):** **"§C graceful-stop, nohup-tarzı launch altında FİZİKİ olarak imkânsız."**
Bu-ders D58'i tamamlar: D58 *"nohup altındayken Ctrl-C'nin gerçek-olmadığı"* → D70 *"nohup altındayken sinyal-iletimi fiziki olarak mümkün-değil; dolayısıyla o-instance'ta hiçbir graceful-kanıt aranmaz."* **Foreground-yalnız-kuralı** bu-biçimiyle kalıcılaşıyor.

**Neden-sistematik (tek-boot-olayı-değil):** close-save'ın üretimde **tek-girişi** `shutdown()` (`orchestrator.py:1661`); periodic-save YOK (kaynak-kodu kendi-yorumuyla itiraf ediyor). Yani **eksik-olan-bir-özellik-değil, eksik-olan-tek-yolun-kendisi.** Launch-modu yanlış seçildiğinde §C / §1.6 / D58-kapanışı **hepsi-birden** erişilemez olur — **üç-kapı-tek-anahtar.**

**Ölçülen-kanıt:** `crash_log.txt` satır-2 `parent: "19088: C:\Program Files\Git\usr\bin\nohup.exe"` (pid 3416) — append-only kanıt-mekanizması launch-modunu **kendi-kendine kaydediyor**; yani teşhis-mekanizması zaten mevcut, sadece okunmamıştı.

**Yeni-ölçülmüş-kural (K1-RED gerekçesi ii):** **"taskkill = audit-orphan üretir."** `save()` tmp-yazar → `replace()` patlarsa tmp-yetim-kalır (BULGU-7'nin tam-mekanizması). Hard-kill, D68-kayıp-sınıfını gizlemek-bir-yana **yetim-artefakt-la çoğaltır.**

**Uygulama-kararı:** **AM-T7-7** (checklist v1.4 §H.1) + boot-runbook'una **ZORUNLU iki alan**: `launch_mode ∈ {foreground-console, nohup, other}` ve `§C_producible ∈ {yes, no}` — beklenti-kaydı **önceden** yazılır, sonradan-keşif-değil (§H.3).

**Numaralandırma-düzeltmesi (§12.1, görünür):** Cline'ın v1.3'ünde AM-T7-7=audit-copy / AM-T7-8=konsol idi; **Hakem-hükmü tersi** → v1.4'te **takas edildi**, takasın-kendisi §H.1'de kayıtlı (tarihçe sessiz yeniden-yazılmadı).

---

## D71 · SEP-1-T0-CRASH-ADLİ-KAZISI (yapı-ışınsı-kazı-standardı · 2026-09-03 15:30)

**Standart:** *tam-gün-nokta, arşiv-geri-aitir* — bir-boot'un kanıtı, o-boot'un dosyalarından geriye-doğru tam-zincir olarak okunur; eksik-halka "yok" değil **"kayıp ve lokasyonu-belirsiz"** olarak yazılır.

**Kazı-sonucu (bir artefakt, üç yorum-dönüşümü):**
| Katman | Bulgu |
|---|---|
| **Yorum-duygusu** | Sep 1 23:59:02'de bir boot **PermissionError ile crash etmiş** — `SHUTDOWN reason:"run_exception:PermissionError"`, `exit:1` |
| **Kurgu → gerçek** | "Sep 1 SAFE_START idi" yorumu → `S11 verdict=PROCEED` + `restored:false` + `warmup_bars:4339` → **Sep 1'de entry gate AÇIKTI**. Artık **audit-kanıtlı olgu**; D64'ün "ilk-gerçek-uygulama" çerçevesi **güçleniyor** |
| **Paradoks** | Kayıplara yol-açan **bozuk-mekanizma** (tmp-replace), **bu olayın tek-kopyasını yanlışlıkla korumuş** — overwrite yerine append olsaydı 6 olay kaybolmazdı, yetim de oluşmazdı |

**Milisaniye-eş-zamanlılığı (crash sırası):** `orchestrator.lock.tmp` `created_at 1788296341.9933178` (pid 16984) → `SHUTDOWN` `1788296342.0110803` → **Δ = 17.8 ms**. Crash, lock-alımının **ilk-icra-anında** olmuş.

**Çelişki → backlog:** `orchestrator.py:91` yorumu `orchestrator.lock.<pid>.tmp` der; yetim **PID'siz** `orchestrator.lock.tmp`. Yorum mekanizmayı doğru tarif etmiyor → **N2 #21 madde-6 (comment-hijyen)**.

**Arşiv-geri-atıf:** 6 olay → `state/audit_prev_2026-09-03.jsonl` **değil**, `state/audit.jsonl.tmp` **üzerinden** geri-kazanıldı; ikisi **farklı kanıt-sınıfı** (biri koruma-dikişi, biri adli-kurtarma).

---

## N2 #21 · KAPSAM-GENİŞLETMESİ (pre-reg çerçevesi · **owner-batch rotası KALKIYOR**)

**Kapsam (D68-P0 + kayaçlar) — altı madde:**
1. **load + append-only `AuditChain`** — BULGU-9'daki `crash_log.txt` append-mode **repo-içi emsali**; D68-dikişinin kod-karşılığı. **Sahada-taşınabilir tek-deneysel imzası (ratifiye):** *yeni-olay-yokken `audit.jsonl` mtime'ı ilerler, boyutu sabit kalır* — bugün **4-örnekle ölçüldü** (3190 B sabit; mtime 15:58:52 / 16:00:53 / 16:06:53 / 16:52:58). **Acceptance-kriteri imzanın-tersten-okunmasıdır:** fix-sonrası **yeni-olay-yokken mtime İLERLEMEMELİ**; ilerlerse append-only kurulmamıştır.
2. **per-N-bar state/audit persist** — BULGU-8/2; **N önceden-bilinçli pre-reg** (keyfi-sonradan-seçim değil).
3. **SIGBREAK / graceful-kanal açılması** — K3-ikinci-boot'un derinlemesine-temeli; window-sinyal-helper ops-yolu **bir seçenek-katalog girdisi**.
4. **BULGU-6 WRITE_BLOCK runtime-izlemesi** — K1-kanıtlarıyla. **Telemetri-şablonu (Hakem, 3 alt-madde):** (i) **`ERROR-ts ≈ WRITE_BLOCK-ts` eşleşmesinden ayrı-olay-sayımı — "aynı-saniye, iki-sayı-değildir"** (14:52:46 çifti); (ii) H3 "saatlik-endonek" için **n=2 yetersiz**, hüküm verilemez; (iii) **RM-probe payload'ları** sonraki olaylarda **"kim tutuyor"** ilk-cevabını verirse **H1 (AV/Defender) / H2 (gözlemci-cp) ayrışır.**
5. **BULGU-3 phase-stickiness** — §A imza-maddesi; **ölçüm artık 81 dk** (`created_at` +1842 s tazelendi, `phase` hâlâ `"startup"`).
6. **comment-hijyen** — `orchestrator.py:91` vs BULGU-7.

**Risk-ifadesi DÜZELTİLDİ (BULGU-6 aşağı-çekme ratifiye):** ~~"WRITE_BLOCK runtime-aktif; K2-retry çalışıyor ama ERROR-payload'ı üretime sızıyor" → D68-P0 vaka-güçlendi~~ ⇒ **"WRITE_BLOCK, N2 #15-b'nin ÖNGÖRDÜĞÜ davranıştır ve adli-kayıt üretir; kök-neden H1/H2/H3 arasında AYRIŞMAMIŞTIR (O1-disiplini H1'i eleyemez). D68-P0 bu-maddeye-dayanamaz — yükü tamamen BULGU-1'in kod-kanıtındadır."**
**Ek-kural (madde-4'ün-kapsamı):** izleme, **H1/H2 ayrıştırmaya-yönelik-ölçüm-tasarımı** olarak-tanım­lanır (RM-probe + dokunma-günlüğü korelasyonu); "kusur-izleme" olarak-değil.
**Sınır:** suit **15+6+27 kırılmaz** · D66-KAMP-1 deliverable'ları **set-dışı (ayrı hash-set)** · **kod-dokunuş PID-3416 canlı iken YOK** (N2 #21 execution, boot-sonrası pencerede).
**Kod-yetkisi-RED gerekçesi (kayda):** üretim-critical dosyada canlı-süreç-üstünde diff = **D63-topolojisinin tam reçetesi** + §17 ihlali + doğurma-testi zorluğu. *Kod-sırası yanlış değil, zamanlaması yanlış.*

---

## K3-HÜKMÜ + DURUM-PİNLERİ (2026-09-03 15:30–15:40)

**Rota:** **K3 hibrit** · K1 RED · K2 RED (tek-parça-muhafazayla) · KOD-YETKİSİ RED → N2 #21.
**Üç-düzeltme-pin ratifiye:** pencere-server-22:00→04:00 (`candle_feed:113–118` UTC-çevirimi; benim 19:00-UTC pinkal-düzeltmem mühürlendi) · V-LIVE-mekanizmal-seçim (warmup-körü) · 0-ERROR-düzeltmesi (§13 yönü doğru).
**Sınıf-düzeltmesi:** WRITE_BLOCK/WinError-5 ailesi **D35-ownership-fatal DEĞİL** (N2 #15-b) → W1'deki `ERROR phase=audit_flush` **"ERROR-beyanı-nüksü" değil, "sayım-beyanı-düzeltmesi"**.
**@Hakem-öz-düzeltmesi-4 (kayda):** §3-(ii)'deki **"04:10-default"** cümlesi nohup-bilgisiyle geçersizdi; düzeltilmiş-karar **K3-zamanlaması**. (Masada-iki-karar-düzeltmesi: Detail-2 ve 04:10 — ikisi-de görünür.)

**Kapı-zinciri A:** W1 → **W2-komit (pid 3416 canlı)** → W2-bitimi → **K3 ikinci-boot (Reis foreground, D68-dikiş önce)** → §C-zinciri (exit-2 beklenen) → **65k otomatik-açılır** → **Aşama-5 COMPARISON (SINIF-2)** → **B1′ iki-bülten-tek-yayın** → B2 → A6-mühür → N2#19 set-mührü → **N2 #21 (genişletilmiş kapsam)** → FAZ-B / N2 #20 pre-reg → Faz-3 owner-paketi. ∥ ③-altı-parça · D69 owner-hattında · tetik-nöbeti (~9 s; aşım + sinyal-yok → yetki-talebi).

**Süreç (15:29):** pid **3416 CANLI** · lock pid 3416 `phase:"startup"` · audit **9 satır** · stdout **14 satır** · **0 SIGNAL/SWEEP** · 1 ERROR (sayım-düzeltmesi-sınıfı).

| Artefakt | Değer |
|---|---|
| `docs/T0_7_PREBOOT_CHECKLIST.md` | **v1.4** · §H (AM takas + K3-runbook 7-adım + launch-modu-alanı + BULGU-3-81dk) |
| `results/D66_production_path_first_observation.md` | §10 eklendi (K3-hükmü + RED-gerekçeleri + dereceler + sınıf-düzeltmesi) |
| `results/D66_sweep_detection.md` | **DEĞİŞMEDİ** 128L / `3cbc74fc064a05f2` |
| `results/D64_bias_census_evidence.md` | **DEĞİŞMEDİ** `8b18f70acc74ae1a` (D62 `ad3fa87b5660f6b0`) |
| Kod | `git diff --name-only -- src/ tests/ index.json` → **BOŞ** |
| Push | **YOK** · `.env` **DOKUNULMADI** · `index.json` **üretilmedi** |
| Yetimler | `audit.jsonl.tmp` + `orchestrator.lock.tmp` + `orchestrator.lock.3944.tmp` **KORUNDU** (BULGU-7 kanıtı) |

**Tek-cümle:** *Bulgu-8 kill-zamanlamasını değiştirdi ama kanıt-zincirini kırmadı* — **K3: pid 3416 W2'yi tamamlar; Reis'in interaktif ikinci-boot'u §C + close-save + 65k-girdisini TEK-adımda üretir; kod-yetkisi N2 #21'e ertelendi (kapsam altı-maddeye büyüdü), launch-modu-dersi AM-T7-7 ile kalıcılaştı.** Masa-akışı tek-adreste: **Reis → W2-sonrası foreground-boot + Ctrl-C.**

---

## BULGU-10 · PENCERE-KOD-TÜRETİMİ + ÖLÜ-KOD-TUZAĞI (2026-09-03 15:45 · K3-uygulama-öncesi-çapraz-kontrol)

**Tetik:** K3-runbook saatlere bağlanınca ratifiye-pencere koddan yeniden-doğrulandı.

**Türetim-zinciri:** `session.py:19-20,28-29` pencereyi **UTC 19:00→01:00** tanımlar (`h>=19 or h<1`) · `candle_feed:104,113-118` + `clock.py:75` barları **server→UTC** çevirir · `clock.py:20-21,53-57` Eylül = **yaz, +3** ⇒ **UTC 19:00 = server 22:00**, **UTC 01:00 = server 04:00** · bağımsız-emsal `CBDR_TIME_SEMANTIC_ALIGNMENT_RAPORU.md:179` aynısını yazar.
> **HÜKÜM:** CBDR body-penceresi = **server 22:00→04:00** — Hakem-düzeltmesi artık **kod-türetimi + rapor-teyidi** (yorum-değil).

**İki-operatif-sonuç:** (a) Pencere **server 04:00'da kapanır** ⇒ **04:10 Ctrl-C body-sonrasına** denk — Hakem-default'u doğru; W2-bitimi ile day-key-devri çakışıyor (temiz-hizalanma). (b) **Yerel-makine ≡ server** (`date -u` 12:46 / yerel 15:46 = +3) ⇒ runbook'ta **çeviri gerekmez.**

**Sahte-çelişki çözüldü:** `clock.py:23` aynı 19→1'i **"MT5 server time"** etiketliyor → §2.2 duplicate-source şüphesi. Çağıran-analizi giderdi: `clock.in_session` **üretimde sıfır-çağıran** (grep: yalnız `tests/test_live_candle_feed.py:298-300`; graph `in_degree=1` = test), canlı-yol `SessionManager.in_window` (**4 çağıran**: `breakout_variant:262`, `liquidity_forensics:382`, `session:198`). **İhlal YOK.**

**Kalan-iki-kusur → N2 #21 madde-6'ya genişletme:**
1. **Yanlış-etiket:** üretim-dışı fonksiyona "MT5 server time" penceresi atanmış; okuyucuyu sahte-§2.2-ihlaline çeker (beni çekti). `orchestrator.py:91` ile **aynı çuval.**
2. **Yeşil-test-ölü-koda:** `test_in_session_spans_midnight` geçer ama hiçbir üretim-davranışını kanıtlamaz (§4.1). **Silme-yok:** ya canlı-yola bağlanır ya kapsam UTC-`in_window` üzerine yeniden-yazılır — **pre-reg kararı N2 #21.**

**Rapor-hatası (§12.1, sessiz-düzeltme YOK):** `CBDR_TIME_SEMANTIC_ALIGNMENT_RAPORU.md:180` *"Server-time 01:00 = UTC 22:00 → OUT_WINDOW dönüşü"* **yanlış** — `h=22 ≥ 19` ⇒ hâlâ IN_WINDOW; gerçek kapanış UTC 01:00 = server 04:00. Ana-hüküm (RUN_B güvenilir / MATCH: YES) **etkilenmez.** **Dokümana dokunulmadı** — owner-batch düzeltme-adayı.

**Kapıya-etkisi: YOK.** §H.2 saatleri olduğu-gibi doğru; §10.7 değişmedi. Kazanım: pencere-iddiası kod-türetimi, 04:10 duruşu body-sonrası bağımsız-doğrulandı.

**Boundary (Bulgu-10 sonrası):** kod **DOKUNULMADI** · push **YOK** · pid 3416 **CANLI** · audit 9 · 0 SIGNAL/SWEEP · 1 ERROR (sayım-düzeltmesi-sınıfı).

---

## BULGU-11 · GÖZLEMCİ-KİRLENMESİ-BAYRAĞI + W1-SAYIMININ-İKİNCİ-DÜZELTİLMESİ (2026-09-03 16:01)

**Nihai-W1-sayımı:** `0 SIGNAL/SWEEP · 1 ERROR · 3 WRITE_BLOCK` — satır-7 `14:52:40 r=8`, satır-8 `14:52:46 ERROR`, satır-9 `14:52:46 r=8`, satır-10 `15:51:32 r=8`.
**İki-aşamalı-düzeltme zinciri (§13, görünür):** "0 SIGNAL/SWEEP/ERROR" → "0 + 1 ERROR" → **"0 + 1 ERROR + 3 WRITE_BLOCK"**. BULGU-6'nın "tek WRITE_BLOCK, 6 s'de kurtuldu" anlatımı yarı-yanlıştı: epizod **3-olaylı**; 15:51:32 ise **ERROR-üretmeden** atlatıldı.

**Kontaminasyon-şüphesi:** iki `node.exe` **14:52:48 / 14:52:53**'te oluşmuş — ilk epizodun tam içinde; o-sırada `state/audit.jsonl`'a Git-Bash `cp` ile dokundum. Mekanizma (test-edilebilir varsayım): Windows `os.replace(tmp, audit)` hedef **delete-share-kapalı** tutamayla açıksa `WinError 5` döner; Python `open()` `_SH_DENYNO` (delete-share **açık**) kullanır, Git-Bash `cp`/`cat` için garanti yok ⇒ **kullandığım izleme-yöntemi ölçtüğüm hatanın sebebi olabilir.**
**Rakip-hipotez ÖLDÜ:** `tools/code-index-system/watcher.py.QUARANTINED_20260901` — Sep-1'de karantina, koşmuyor; §10.1 arka-plan-mutasyonu açıklama-değil.
**Zayıf-yan (dürüst):** 15:51:32'den önceki son `cp` 15:41:40 (~10 dk) → orada sıkı-korelasyon **yok**; "hepsi-gözlemci" de kesinlenemez. ~59 dk aralık saatlik-döngü şüphesi veriyor ama **n=2**.

**Disiplin-değişikliği (anında-yürürlükte):** **O1** audit yalnız share-safe-Python · **O2** `cp`/`cat`/`sha256sum`/`stat` ile audit'e dokunma-yok · **O3** her okuma okuma-**öncesinde** `results/D66_observer_touchlog.txt`'a satır yazar (kendiliğinden-korelasyon, elle-ihlal-edilemez) · **O4 karar-kuralı önceden-bağlandı:** O1 altında da WRITE_BLOCK yinelenirse → **ENDONEK, D68-P0 sağlam**; hiç olmazsa → **BULGU-6 gözlemci-kaynaklı, geri çekilir.**
**Kuralın-kökeni (§4.1 saha-kardeşi):** "test-pass ≠ correctness" → **"gözlem ≠ endonek davranış."**

**D68'e ek-canlı-teyit:** `audit.jsonl` mtime 15:58:52→16:00:53 ilerlerken **boyut 3190 sabit** ⇒ `save()` yeni-olay-olmasa-da tüm-dosyayı-yeniden-yazıyor. Bulgu-1 (whole-file-overwrite) **kod-okumasından canlı-gözleme terfi etti.**

**Çekince:** `retries: 8` üç-olayda-da aynı (sabit üst-sınır); geri-çekilme-eykeli okunmadığı için **ilk-atama-zamanı belirsiz**, korelasyon-penceresi geniş. node.exe doğuşları **eş-zamanlılık**, nedensellik-değil (§3 seviye-6).

**N2 #21'e-giden:** madde-4 (WRITE_BLOCK-runtime-izlemesi) artık **O1–O4 gözlemci-disipliniyle** koşullu; risk-ifadesine ek: *"runtime WRITE_BLOCK'un endonek/gözlemci-atribüsyonu O4 ile çözülmeden #21 kapsamı daraltılamaz."*

**Boundary:** kod **DOKUNULMADI** (`src/ tests/ index.json` diff boş) · push **YOK** · pid **3416 CANLI** · yetimler (`audit.jsonl.tmp`, `orchestrator.lock.tmp`) **KORUNDU** · `audit_prev_2026-09-03.jsonl` 2765 B **YERİNDE**.

---

## D72 · BULGU-ENVANTERİ RATİFİKASYONU — 11-BULGU-MÜHÜRLÜ + İKİ-KAYIT-HATASI-DERECESİ (2026-09-03 16:53)

**Hüküm-statüsü:** ENVANTER KABUL · BULGU-6 aşağı-çekme **ratifiye** · BULGU-10/11 öz-düzeltme = **Kural-6 onikinci/üçüncü-tur** · W1-nihai-sayım **MÜHÜRLÜ** · overwrite-semantiği **canlı-gözleme terfi ratifiye** · **RED-YOK.**
**Bu-turun-asıl-değeri (Hakem tanımı):** canlı-bekleyen-süreç-üstünde **dört-katmanlı-kayıp-disiplini** — envanter → öncelik-düzeltmesi → hipotez-şemsiyesi → canlı-teyit.

### Ratifiye-dereceler (tamamı §13.1 tablosunda; rota-özü)
**1 KRİTİK**(N2#21-1) · **2 YÜKSEK**(2) · **3 ORTA**(5 + §H.4-sınırı) · **4 ORTA**(6) · **5 ORTA**(backlog; capture'a **iki-teyit-adımı**) · **6 AŞAĞI-ÇEKİLDİ**(4, izleme) · **7 YÜKSEK→D71**(kapandı) · **8 YÜKSEK→K3**(+madde-3) · **9 ORTA**(madde-1 güçlendirici) · **10 TEYİT→kısmi-tekrar**(2 yan-ürün terfi) · **11 KISMEN-GERİ**(H1/H2/H3).

### İki-yan-ürün → defter-maddesi-terfisi
- **AM-T7-9 (YENİ, yürürlükte):** *"Runbook'lar zaman-dili belirtir (local / server / UTC); belirtmeyen satır runbook-hatasıdır ve düzeltilmeden runbook koşmaz."* **BULGU-10 yan-ürünü (b)'nin terfisi** — Hakem-vurgusu: *not değil, **risk-ifadesi***. Uygulama: checklist **§H.6 zaman-dili-çizelgesi** (§H.2'nin-beş-satırı etiketlendi) + **kış-uyarısı**: `local ≡ server` eşitliği offset-değişse-de bozulmaz (aynı-makine), **ama pencere-saatleri kayar** ⇒ §H.5 yeniden-türetilmeden kış-runbook'u koşulamaz.
- **K3-zamanlama-precision'ı:** Ctrl-C pencere-bitişinde **değil**, day-key-`2026-09-03` body-kapanışı-sonrasında (04:10 `server`) — §H.4 sınırlarıyla, N2 #17 imza-kodu ile aynı.

### Overwrite-semantiği → CANLI-GÖZLEM (bugünün en-güzel-kanıtı)
`audit.jsonl` **3190 B sabit / mtime ilerler**: 15:58:52 · 16:00:53 · 16:06:53 · **16:52:58** (4-örnek). BULGU-1 whole-file-overwrite artık **ölçülmüş-davranış**.
**Kabul-kriterine-terfi (imzanın-tersten-okunması):** fix-sonrası **yeni-olay-yokken mtime İLERLEMEMELİ**; ilerlerse append-only **kurulmamıştır**. ⇒ Aynı-gözlem hem **kusur-kanıtı** hem **düzeltmenin kırmızı-yeşil lambası.**
**Hakem-çerçevesi:** *"kod-yaşarken davranışı ölçtük, kod-ölmeden düzeltmeye gireceğiz."*

### W1-MÜHÜR + ayrıntı-hükmü
`0 SIGNAL/SWEEP · 1 ERROR · 3 WRITE_BLOCK` — iki-aşamalı-düzeltme-zinciri görünür. **Ayrıntı-hükmü:** ERROR ile WRITE_BLOCK aynı-saniyede (14:52:46) ⇒ telemetriye **"aynı-saniye, iki-sayı-değildir"** kuralı. **H3-ekranı:** 59-dk aralığı **n=2** → saatlik-endonek hükmü **verilemez**; H1/H2 aday; ayrışma-yolu **RM-probe "kim-tutuyor"**.

### D64 WIRE-NOTE (Aşama-5'e-devir)
**D64-NİHAİ-MÜHÜR: Option-A seçilmişti; amendment-§5 uygulaması BEKLEMİŞ.** Envanterdeki "Option A/B" satırı Cline tarafında **AÇIK-ŞART** olarak duruyor. Devir-kaydı: `results/D64_bias_census_evidence.md` **`8b18f70a`** + **§5-bloğu** + yayın-anında **taze-pin**. **Dosyaya dokunulmadı** (yedinci-halka zincir-değişmezliği sürüyor).

### Boundary (ratifikasyon-turu)
Kod **DOKUNULMADI** (`src/ tests/ index.json` diff **boş**) · push **YOK** · pid **3416 CANLI** · `sweep_detection 3cbc74fc` ve **D64 `8b18f70a` DEĞİŞMEDİ** ✓ · yetimler korundu · D68-dikişi yerinde · **O1–O3 gözlemci-disiplini yürürlükte** (audit artık yalnız share-safe-Python; her-okuma dokunma-günlüğüne otomatik-satır).

---

## D72-arb · HASH-DOĞRULAMA + DIŞ-AUDIT ARŞİVİ + ADER-9 (2026-09-03 17:15) — Reis-Komutu, üç-madde-tek-yazım

### Madde-1 · HASH-DOĞRULAMA — SONUÇ: **5/5 DOĞRULANMIŞ-ANKOR · 0 DÜZELTME**
| Luna-hash | Tam-hash | Commit-zamanı `+03:00` | Konu-özü | Sınıf |
|---|---|---|---|---|
| `a289a48d` | `a289a48d686b2b3a313cd858f0ee2d26da67339c` | 08-27 23:01:31 | phase7: **audit chain** + safety monitor (5 fail-safe, JSONL flush) | **DOĞRULANMIŞ** |
| `d87d1e1` | `d87d1e11fa3e2cb2a9b161f6e4a8f3bdc287b3cd` | 08-29 12:18:12 | persistent runtime logging + **audit auto-flush** | **DOĞRULANMIŞ** |
| `68878d6` | `68878d61be134f6b2d04e43517e91c1a308065dd` | 08-30 02:45:13 | TAŞ 2 — orchestrator S3-S9, **startup_snapshot**, bar pipeline, **lock contract** | **DOĞRULANMIŞ** |
| `afe6668` | `afe666849d91a6ba87e528071acbcf9319b87db2` | 08-30 10:42:35 | TAŞ 2 blockers(1-8) — slot-floor emit, S5 injection, **PID liveness+heartbeat**, MT5 tri-state | **DOĞRULANMIŞ** |
| `b36c7c4` | `b36c7c4176c8b5c362a9512fe545330aa4354cdd` | 08-31 11:39:51 | D49: **boot-time sync replay (O2)** + **restore staleness gate** — C1-C6, B-1 | **DOĞRULANMIŞ** |

**Konusal-teyit (beklenmedik-pozitif):** beş-commit-in-hepsi **BULGU-1 / BULGU-3 / BULGU-8 mekanizma-linelerinin-üstündedir** — Luna'nın-ankor-seçimi **rastgele-değil, hedefli.** ⇒ R1'in-sınıflandırma-değeri **bağımsız-yükseldi** (§3 eğilimine-aykırı; dürüst-kayıt).

**Benzerlik-bayrağı ÇÖZÜLDÜ — `afe6668` ≠ `afe695b`:** ortak-önek `afe6`, **6. haneden ayrılır** (`666`/`695`); tarih-farkı **~2 gün** (08-30 10:42 vs 09-01 07:33); tür-farkı `fix:` vs `chore: ledger`. ⇒ **Hakem-bayrağı DOĞRULANDI: D53b-zinciri YALNIZ `afe695b`.** **Yan-teyit:** `afe695b` konusu *"real resurrection vector FOUND: Startup lnk → start_watcher.vbs logon autostart, correcting N2 #9 'manual start' misjudgment"* + *"mandatory pre-flight rule: watcher-process check at BOTH commit and push"* der ⇒ **BULGU-11 watcher-öldürmesinin resmî-kaynak-kanıtı budur** ve **§10.1-ısrarı-lafzen-değil-commit'le-bağlıdır.**

**GREP · D25 TEYİTLİ:** `feed.update` → **0** · `feed.warmup` → **0** · `M1CandleFeed(` → **0** · yalnız `fetch_m1` (`candle_feed.py:103/179/197`) ve `_fetch_m1_tri_state` (`orchestrator.py:1849/1905/2169`, def `:2274`, yorum `:1219`). Beklenen-çıktı-şablonu **birebir-karşılandı.**

### Madde-2 · ARŞİV — `results/D72_external_rootcause_audit.md` (YENİ · untracked · 185 satır)
Etiketli-bölümler: §0-alma-boşluğu · §1-R1-Luna-5.6 · §2-R2-Gemini-3.8-Flash · §3-hata-kataloğu · §4-arbitraj-tablosu(11) · §5-D72-a/b/c · §6-ADER-9 · EK-1-ham-hash-çıktısı · EK-2-ham-grep-çıktısı · §7-kapanış.
**AÇIK-KALEM (gizlenmedi):** **E4/E5/E6 doldurulmadı** — 6-maddelik-hata-kataloğunun-3'ü iletildi, 3'ü **bağlamımda-yoktu**; uydurmadım (§13.5 *kısmi-alımda-hafızadan-özetleme-yok*). Aynı-sebep-le **Luna/Gemini düz-yazısı arşivde-değil**, yalnız **kanıtlanabilir-çekirdek** (hash + Hakem-nitelendirmesi) var. **İletim-talebi §1.4'te** (split-header + alıcı-onayı).
**ID-ÇAKIŞMASI (Hakem-kararı-bekliyor):** Hakem "D72" = dış-audit-arbitrajı; defterde "D72" = envanter-ratifikasyonu. **İki-olay-aynı-ID.** Aday: **D72-env / D72-arb.** Sessizce-çözmedim.

### Madde-3 · ADER-9 (yürürlükte)
> **"Geçmişi ve kod-izini olmayan okuma sınıflandırmayı teyit eder; mekanizma-iddiası üretemez — mekanizma çapa ister (satır / hash / artifact)."**

**Kendi-kendine-uygulanması:** bu-turun-kendisi-ADER-9'un-labıdır — Luna'nın-**hash'leri doğrulandı**, Luna'nın-**ne-dediği elimde değil** ⇒ o-kısım sınıflandırmaya-yarar, mekanizmaya-yaramaz.

### Boundary (D72-arb turu)
Kod **DOKUNULMADI** (`src/ tests/ index.json` diff **boş**) · commit **YOK** · push **YOK** · pid **3416 CANLI / DOKUNULMADI** · `.env` **DOKUNULMADI** · `index.json` **YENİDEN-ÜRETİLMEDİ** · lock **SİLİNMEDİ** · yetimler (`audit.jsonl.tmp`, `orchestrator.lock.tmp`, `orchestrator.lock.3944.tmp`) **KORUNDU** · D68-stitch `audit_prev_2026-09-03.jsonl` **KORUNDU** · **D64 `8b18f70a` DEĞİŞMEDİ** ✓ · `sweep_detection 3cbc74fc` **DEĞİŞMEDİ** ✓ · W2-izleme **O1/O2/O3 altında sürüyor** · 65k-parite-scanı **ikinci-boot-a-kadar-BLOKE**.


---

## D73 · BULGU-3 ARİTMETİK-DÜZELTMESİ + `created_at` AD-TUZAKI + OVERWRITE 6. ÖRNEK (2026-09-03 17:53)

**Tetikleme:** D72-arb arşivi-koşarken-çekilen-kilit-inspeksyonu, **ratified bir-kaydın-türetme-yolunu-düşürdü.** §12.1: eski-sonuç → neden-yanlış → yeni-kanıt → revize-sonuç.

### Düşürülen-şey (yalnız-kanıt-yolu, sonuç-değil)
**ESKİ:** "`phase=\"startup\"` **3 sa 00 dk**; kanıt `created_at 1788444500.47` − boot `1788433696.66` = **10804 s**."
**NEDEN-YANLIŞ:** `created_at` **doğum-anı-değil.** `orchestrator.py:621-622` *(belgelediği-bir-tasarım)*: *"``heartbeat()`` refreshes ``created_at`` so a long-running but quiet process is not misclassified as stale."* Tüketici `:987` `(time.time() - data.created_at) > LOCK_STALE_SEC`; `:336-341` stale = **`created_at`-penceresi + ÖLÜ-PID**. ⇒ Bu-çıpadan-türetilen-süre **"process-ne-kadar-ayakta"**dır, **"sah-ne-kadar-takılı"** değil.
**İÇ-ÇELİŞKİ (ağırlaştırıcı):** düzeltmenin-yaptığı **aynı-cümle** (§H.4) zaten *"`created_at` heartbeat ile tazelemeye devam ederken"* diyordu — yani **önerme-doğru-yazılmış, sonra-ihlal-edilmişti.**

### Yeni-kanıt (canlı, 17:48:43)
| Gözlem | Değer |
|---|---|
| PID 3416 `StartTime` (doğru-çıpa) | `14:07:49` |
| `phase` | hâlâ `"startup"` |
| Geçen | **3 sa 40 dk 54 sn** |
| `created_at` / lock `mtime` | `1788446923.92` ≈ `17:48:12` / `17:48:43` |
| ⇒ kalp-atışı-periyodu | **~30 sn** (yeniden-yazım-kanıtı) |
| `phase="startup"` gözlem-dizisi | **14:58 · 15:29 · 17:08 · 17:48** (4/4) |

**REVİZE-SONUÇ:** **BULGU-3 ÖZÜ DURUYOR ve güçleniyor** — süre **3h00m → 3h41m**, çıpa **`created_at` → `StartTime` + gözlem-dizisi**. Derece/saha-terfisi **olduğu-gibi**. **Hakem-D72 §2 hükmü-geçersizleşmedi:** hüküm **sonucu** (progress-token) taşıyordu, sayıyı-değil; sayı-düzeltmesi **hükmü-güçlendirir** (yanlış-çıpa **tesadüfen-doğru** sonuç-vermiş; doğru-çıpa **daha-güçlü**).

### YAN-BULGU · `created_at` AD-TUZAKI (N2 #21 madde-5'e-girer)
`created_at` **heartbeat taşır, creation adlandırılır.** Tuzak **kanıtlıdır çünkü-ben-ona-düştüm:** saha-ajanı kilit-dosyasını-okuyup **doğum-anı** sandı ve **yanlış-süre** türetti; hata **ratified-üç-kayda** (§H.4 / D66 §12 / progress D72) **sızdı.** Çözüm-adayı: **`heartbeat_at` yeniden-adlandırması** ya-da **ayrı `boot_at`/`progress_token`.** ⇒ **"ayrı-ilerleme-kimliği" gereksinimi-bağımsız-olarak-tekrar-doğdu** ve **artık-iki-gerekçesi-var:** (i) `phase` ayrıştıramıyor, (ii) `created_at` **adıyla-yalan-söylüyor.**

### OVERWRITE-İMZASI · 6. ÖRNEK = EN-TEMİZ-BİÇİM
`17:53:44` O1-okuması: **`lines=10` · `size=3190` · `mtime=17:53:44`** — sayaçlar W1-mührüyle **birebir-aynı**, mtime **yine** ilerlemiş. Önceki-5-örnek **yalnız-boyut-sabitliği** gösteriyordu; bu **üçünü-birlikte**:
```
satır-sayısı SABIT (10) + boyut SABIT (3190 B) + mtime ILERLER  ⇒ yazar aynı-içeriği-yeniden-yazıyor
```
⇒ **D72(c) kırmızı-yeşil-lambası BUGÜN KIRMIZI:** *yeni-olay-yokken mtime ilerliyor* ⇒ **append-only henüz-kurulmadı.** N2 #21-madde-1 kabul-kriteri **canlı-ihlal** altında ve **kriter iş-headıyor** (yanlışsa-gösterebiliyor — bu-kriterin-ilk-olumsuz-çalışması-değil, **ilk-üç-değişkenli-ölçümü**).

### W2-SAYIMI (17:53:44, O1/O2/O3 altında)
**`0 SIGNAL/SWEEP · 1 ERROR · 3 WRITE_BLOCK` — DEĞİŞİM YOK.** Share-safe-okuma-altında-**yeni-WRITE_BLOCK YOK** (5-okuma) ⇒ **O4-H3 falsifikasyonu sürüyor**; H1/H2 **hâlâ-ayrışmadı**; BULGU-6 aşağı-çekme-derecesi **doğru-yönde**.

### D72-arb ile-birlikte-kapan
Adım-1 **5/5 doğrulanmış-ankor · 0 düzeltme** · `afe6668`≠`afe695b` (bayrak-doğrulandı; D53b-yalnız-`afe695b`) · **D25 teyitli** (`feed.update`/`warmup`/`M1CandleFeed(` → **0**, yalnız `fetch_m1`) · Adım-2 arşiv **185→220 satır** · Adım-3 **ADER-9 yürürlükte** · **E4/E5/E6 ALMA-BOŞLUĞU olarak-açık (uydurulmadı)** · **D72-ID-çakışması Hakem-kararında.**

### D73-ek · ANKOR-KÖKENİ AYRIŞTIRMASI — R1'in-bağımsız-değeri **5 → 3 ankor**
Mühür-öncesi-tam-depo-taraması (kapsam: `git grep` tracked + `docs/ results/ memory-bank/ .clinerules/`; **`data/`+`.git/` hariç** — rekursif-grep 30 sn zaman-aşımına-uğradı, ⇒ **negatif-sonuç sınırlı-kapsamlıdır**, §1.3) şu-ayrışmayı-verdi:

| Hash | Diskte-zaten | Köken |
|---|---|---|
| `a289a48d`, `68878d6`, `afe6668` | **YOK** | **LUNA-ÖZGÜN** — gerçek-bilgi-artışı (3/5) |
| `d87d1e1` | **VAR** `FOREX_DEPLOYMENT_CONTRACT_v1.md:5,273` ("Repository State: d87d1e1") | **KENDİ-KAYIT-YANKISI** |
| `b36c7c4` | **VAR** `activeContext.md:914/918/920/929` (COMMIT + push-onaylı) | **KENDİ-KAYIT-YANKISI** |
| `afe695b` | **VAR** `activeContext.md:1848/1854/1856/1922` (§9.5 exact pushed-set) | R1-listesinde-**yoktu**; Hakem-karşılaştırması |

⇒ **5/5 gerçek-commit (duruyor), AMA 2/5'i kendi-defterimizin-tekrarı.** R1 onları-tekrar-etmekle **içeriden-bir-şeyi dışarıdan doğrulamamıştır.** **ADER-9'a-İKİNCİ-ŞART-girer:** *çapa-var olması-yeterli-değildir; **çapanın-kaynağı-da-sorgulanır — kendi-kaynağın-yankısı-teyit-sayılmaz.***

### D73-ek-2 · AD-SARIKARŞILIĞI TUZAKLARI (üç-tane, hepsi-ölçüldü)
1. **`AUDIT_1_claude_luna.md` / `AUDIT_gemini_3_7_flash.md` diskte-VAR ama R1/R2 DEĞİL:** konuları **FVG-freshness / stale-ATR / Nexus `real_index` / C-v1.0-v1.1 araştırma-motoru**; **beş-hash-in-teki-yok** (0 eşleşme), Gemini'de **"watchdog" yok** (0 eşleşme). Üçüncü-sahte-ankor: `docs/# LUNA DİRECTİFİ — kabul + paralel yürüt.md` (106 S, roll-assignment, hash-yok). ⇒ **Luna/Gemini-adlı-disk-artefaktları-kaynak-değildir; elenmiştir.** **Benim-ilk-aramasında-`head -20` yüzünden-kesilen-liste bu-üç-dosyayı-gizlemişti** — **arama-hijyeni-dersi: `head` ile-kesilen-negatif-sonuç, negatif-sonuç-değildir.**
2. **Sürüm-uyuşmazlığı:** direktif **"Gemini 3.8 Flash"**, disk-artefaktı **3.7**. Disktekiler-kaynak-olmadığı-için **çelişki-çözülmez-kalır** ⇒ R2'nin-gerçek-araç-sürümü **BİLİNMİYOR**.
3. **Deployment-contract eskiliği (kapsam-DIŞI, yalnız-not):** contract repo'yu **`d87d1e1` (Aug-29)**'e sabitlemiş; güncel-HEAD **`0081c64` (Sep-03)** ⇒ **6 gün eskimiş sözleşme.** Dokunulmadı.

### D73-ek-3 · ARKA-PLAN-MUTASYONU TESPİTİ (§10.1)
`git status` → **`M AGENTS.md`, +17 satır**, bölüm `Aşama-5: Crash / Fix-Bildirim Üçlü Kanal Zorunluluğu`. **Bu-turda-ben-yazmadım** (AGENTS.md açılmadı) ve **watcher-değil** (watcher `QUARANTINED_20260901`). ⇒ **Bu-turdan-önceye-ait, commit-edilmemiş-düzenleme.** **Risk:** ilerideki-commit'te **istem-dışı-yolcu** (§9.5 set-değişimi = yeniden-yetki). **Dokunulmadı; bildirildi.**

### D73-ek-4 · KAPANIŞ-YOKLAMASI (18:50) ve O3-ZAYIFLIĞI
**Sayım (6. share-safe-okuma):** `lines=10 · 0/1/3` — **W1 mührüyle birebir aynı**; share-safe-altında **hâlâ yeni WRITE_BLOCK yok** ⇒ O4-H3 falsifikasyonu sürüyor, H1/H2 ayrışmadı. **Overwrite 7. örnek:** `size=3190` sabit, `mtime 17:53:44 → 18:50:28` ilerler, yeni olay yok ⇒ **D72(c) lambası aralıksız KIRMIZI.** **Kilit 5. gözlem:** `phase="startup"`, `hb_age 20 s` ⇒ **~30 sn heartbeat bağımsız-teyitli**; BULGU-3 süresi **3h41m → 4h43m**, öz duruyor.
**O3-ZAYIFLIĞI (kendime-kayıt, ADER-9'un-en-rahatsız-edici-uygulaması):** dokunma-satırı-zaman-damgaları (`17:49:10`, `18:02:40`) **agent-tahminidir, saat-ölçümü-değildir** — agent'ın-kendi-saati-yok. Olay-mühürlerini-`audit_mtime`-ile-karşılaştırmak **bu-nedenle-yanıltıcıdır**; **O3'ün-kendi-kendine-kanıt-değeri düşük.** Çözüm-adayı: `audit_read.py` dokunma-satırını **kendisi-yazsın** (machine-timed) ⇒ O3 kendiliğinden-doğrulanabilir-olur. **Yapılmadı** (script-yetkisi-yok); **N2 #21-madde-6 adayı.** ⇒ **Çapa-eksikliği kendi-kurallarımızda-da-var.**

### D73-ek-5 · DEVİR-NOTU-BÜTÜNLÜĞÜ — üçüncü-yetim-artefakt **HİÇ VAR OLMAMIŞ** (§12.1/§13.5)
Gelen-devir-özeti **üç** yetim-artefakt sayıyordu: `audit.jsonl.tmp` · `orchestrator.lock.tmp` · **`orchestrator.lock.3944.tmp`**. Ölçüm:
| İddia | Gerçek |
|---|---|
| `state/audit.jsonl.tmp` | **VAR** — 1483 B, Sep-1 23:59; ilk satır `MT5_CONNECT`, son satır `SHUTDOWN {"exit":1,"reason":"run_exception:PermissionError"}` |
| `state/orchestrator.lock.tmp` | **VAR** — 68 B, Sep-1 23:59; içerik **`{"pid": 16984, ...}`** ⇒ **3944 ile-ilgisi YOK** |
| `state/orchestrator.lock.3944.tmp` | **YOK** — `find . -name '*3944*'` (`.git` hariç) → **0 sonuç**; `state/` tam-listesinde de yok |

**NEDEN-YOK (kayıp-değil, tasarım-gereği):** 3944-kilidi **`.tmp` adıyla-değil, `state/orchestrator.lock` CANLI-YOLUNDA** kayıtlıydı (§H.1 alıntısı: `{"pid":3944,"created_at":1788381955.53,"phase":"startup"}`, mtime-age 798 s, PID DEAD). PID 3416 boot'u (14:07) bu-kilidi **meşru takeover ile EZMİŞTİR** — yani §H.1'in **"takeover'ın-gerçek-kanıtı"** dediği-olay tam-da-budur: **kanıt, üzerine-yazılarak-tüketilen-bir-kanittır.**
**SONUÇ-1 (kanıt-seviyesi-düşüşü, §3):** 3944-delili artık **yalnız-düz-yazı-alıntısıdır** (kanıt-hiyerarşisinde **seviye-6**), **artifact (seviye-5) değildir.** §H.1'in **"ELLE SİLİNMEZ"** emri **fiilen-geçerli-değildir** — silinme-bizim-tarafımızdan-olmadı, **takeover'ın-kendi-doğal-sonucudur**; ama emir **yanlış-yere-yazılmıştır** (korunacak-bir-dosya-yoktu, korunacak-anlık-değer-vardı ve o-değer-alıntılanmıştı).
**SONUÇ-2 (devir-hijyeni, KURAL-ADAYI):** devir-özetindeki-dosya-adları **kanıtlanmadan-yazılmıştır** — üçüncü-ad **uydurma-etiket**tir (`orchestrator.lock` + `pid-3944` birleşimi). ⇒ **Aday-kural: "Devir-notundaki her dosya-adı ya `ls`-çıktısıyla ya-da `git status`-çıktısıyla eşlenmiş-olmalı; eşlenmemiş-ad 'iddia' olarak-etiketlenir."** Bu, §13.5'in-depolama-tarafıdır.
**Dokunulmadı:** iki-gerçek-yetim **olduğu-gibi-korundu**, yenisi-üretilmedi, 3944-için **sahte-artefakt-uydurulmadı.**

### Boundary (D73 turu)
Kod **DOKUNULMADI** (`src/ tests/ index.json` diff **boş**) · commit **YOK** (reflog teyit: HEAD hâlâ `0081c64` 00:18, **bana-ait-değil**) · push **YOK** · pid **3416 CANLI / DOKUNULMADI** · `.env` **DOKUNULMADI** · `index.json` **YENİDEN-ÜRETİLMEDİ** · lock **SİLİNMEDİ** · yetimler **KORUNDU** · D68-stitch **KORUNDU** · **D64 `8b18f70a` DEĞİŞMEDİ** ✓ · `sweep_detection 3cbc74fc` **DEĞİŞMEDİ** ✓ · 65k-parite **ikinci-boot-a-kadar-BLOKE**.


## D74 · HAKEM-HÜKMÜ-UYGULAMASI + SAHA-OLAYI (19:17 ikinci-boot) + ÜÇ-ÖZ-DÜZELTME
*Tarih: 2026-09-03 · Hat: D72-arb kapanışı → hüküm → uygulama sırasında gelişen canlı olay.*

### 0. HÜKÜM-KABUL EDİLDİ (RED-yok)
`(A)` hakem-öz-düzeltmesi-6 (10804-s-üretimi-hakem-tarafından-üretilmişti) · `(B)` AGENTS.md bağlı-dönüşüm + AM-T7-10 · `(C)` seviye-6-tanımlı-mühür + AM-T7-11 · `(D)` N2 #21 madde-6b · `§5` **`D72-env`/`D72-arb` ayrımı KABUL** + ADER-11 · `§6` arşiv **271S/`9f057ca6` ratifiye** + **ADER-9-v1.1** (çapa-özgünlüğü) · `§7` R1/R2-düz-yazısı Reis-elinden-gelecek, ben append-only eklerim.

### 1. OLAY-1 · `phase` BİR **SABİTTİR**, TAKILI-BİR-DURUM-DEĞİL (kod-çapalı, canlı-teyitli)
Hükmün `(A)` maddesindeki yeni-çıpayı (`StartTime`→`14:58`→`≥4h43m`) koddan-doğrularken mekanizma-çöktü:

| Çapa | Gerçek |
|---|---|
| `orchestrator.py:920` | `data = LockData(pid=os.getpid(), created_at=time.time(), phase="startup")` — **`_write()` içinde, her-yazımda-sabit-literal** |
| `_write()` çağırıcıları | **yalnız ikisi:** `acquire()` `:758` ve `heartbeat()` `:840` |
| `git grep '\.phase\s*='` (src/, tests hariç) | **0 sonuç** — kilit-fazı **hiçbir-yerde mutate edilmiyor** |
| `StartupPhase` `:371-382` | `S0_CONFIG … S11_READY` — **11-durumlu gerçek durum-makinesi MEVCUT** |
| `phase=StartupPhase.X` (14-site, `:1165-1565`) | **`StartupResult(...)` kwargs'ıdır** — yani **bellek-içi-dönüş-değeri**, kilit-değil |
| `:1505-1560` | gerçek faz **audit'e** yazılıyor: `EventType.STARTUP {"phase":"S9"/"S11","verdict":…}` |

⇒ Kilit-dosyasındaki `phase` **inşası-gereği-bilgi-taşımayan-bir-alandır.** "Takılı" değil; **ilerleme-kapısı-hiç-yazılmamış.**
**CANLI-KARŞI-ÖRNEK (saat-çapraz-doğrulamalı):** audit `19:17:25`'te `S11 / SAFE_START` **tamamlandı**, `19:17:26`'da `SAFETY gate=closed reason=startup_SAFE_START`; kilit `19:19:26`'da **hâlâ `phase="startup"`**. ⇒ **Tamamlanmış-startup + lock-"startup" = alanın-durum-olmadığının-doğrudan-kanıtı.**
**BULGU-3 YENİDEN-ĐFADE (kök-değişikliği):** eskisi *"phase 4s43dk ilerlemedi ⇒ startup↔wedged ayırt edilemiyor"* — **ölçülen-şey bir-literal'in n=5 tekraruydu.** Doğrusu, **daha-ağır:** *operatörün-güvendiği-teşhis-alanı inşası-gereği sabittir; hiçbir-şeyi ayırt-edemez.* Süre-iddiası (**4h43m**) **tamamen düşer** — geriye-süre-değil, **alanın-anlamsızlığı** kalır.
**N2 #21 madde-5 YENİDEN-KAPSAM (§2.2):** madde *"ayrı-ilerleme-kimliği icat-et"* diye yazılmıştı; **kimlik ZATEN VAR (`StartupPhase`) ve audit'e yayınlanıyor.** Doğru-kapsam: **`StartupPhase`'i `LockData`'ya taşımak** (`_write()`'a gerçek-faz-parametresi) — yeni-soyutlama-değil.
**N2 #21 madde-1 KABUL-KRİTERİ YÜKSELDİ:** benim-övdüğüm-kriter *("yeni-olay-yokken mtime ilerlememeli")* **zayıfmış** — asıl-kriter **"önceki-satırlar yeni-boot-sonrasında-da durmalı"**. Aşağıdaki-olay bunu ihlal-etti.

### 2. OLAY-2 · 19:17:10 İKİNCİ-BOOT + **AUDIT-TRUNCATION (gerçek-veri-kaybı)**
`18:51:08` (makine-damgası) okuması: `lines=10 · size=3190 · 0/1/3`. `19:18:41` okuması: **`lines=6 · size=1622 · 0/0/0`** — içerik **yepyeni-boot-dizisi** (`MT5_CONNECT`, `STARTUP`×4, `SAFETY`).

| Ölçüm | Değer |
|---|---|
| Eski-sahip | **PID 3416 — `Get-Process` count **0**, ÖLDÜ** |
| Yeni-sahip | **PID 11476**, `StartTime 19:17:10`; kilit-sahibi |
| "Çift-instance" mı? | **HAYIR** — `crash_log` satır-3: `self=11476 (.venv python)`, **`parent=16660 (.venv python)`** ⇒ **tek-boot, venv-launcher→child.** Yanıltan: `Get-CimInstance` iki-python gösterdi. |
| Launch-yolu | `.venv/Scripts/python.exe … run_production.py` — **`nohup.exe` DEĞİL** (3416'nın parent'ı `nohup.exe` idi, crash_log satır-2) ⇒ **§C/graceful-stop/close-save artık üretilebilir-olabilir** |
| `d66_boot_stdout.log` | **14:07:56'da durdu, değişmedi** ⇒ **bu-bootu-ben-başlatmadım** (Reis-olası) |
| Safe-mode | `S11 SAFE_START` + `safe_reasons[0]="safe_mode_persisted"` ⇒ **§7.2 "persisted-safe-mode → degraded boot" ÇALIŞIYOR** ✓ (sessiz-resume YOK) |
| **KAYIP** | 3416-devrine-ait **10 satırın tamamı**: 3 WRITE_BLOCK + 1 ERROR + **3416'nın SHUTDOWN kaydı (varsa)** |
| **KURTARMA** | `state/audit_prev_2026-09-03.jsonl` = **9 satır** (MT5_CONNECT, STARTUP×4, SAFETY, WRITE_BLOCK, ERROR, WRITE_BLOCK) + 10.satır (`WRITE_BLOCK 15:51:32 retries=8`) **touchlog-dökümünde yazılı** ⇒ **10/10 metin olarak kurtarılabilir, artifact olarak değil** |
| **YENİ-KOPYA** | `results/D74_audit_snapshot_2026-09-03_1919.jsonl` — **1622 B, sha256 `184a95c450713eca20c6519e…`, kaynakla BAYT-ÖZDEŞ ✓** (`state/`-e dokunulmadı) |

⇒ **D72(c) lambası "kırmızı"dan "yanıyor"a geçti:** mtime-churn değil, **boot-üstüne-boot-yazımı ve tarih-imhası** gözlemlendi. **§18 audit-continuity kırıldı** ve **3416'nın nasıl-öldüğü artık kanıtlanamaz** — bu, turun-en-pahalı-maliyetidir.

### 3. ÖZ-DÜZELTME-1 · BULGU **(D) GERİ ALINIR** (6b talebi kısmen-gereksiz)
Ben *"dokunma-damgaları benim tahminim, araç kendi satırını yazmıyor"* dedim ve **aracı açmadan** mekanizma iddia ettim. **`audit_read.py:14-23` `log_touch()` OKUMADAN ÖNCE makine-damgalı satırı KENDİ yazıyor** (`datetime.now(utc)` + local). ⇒ **(D) yanlıştı; 6b'nin istediği davranış BU ARAÇTA ZATEN VAR.** Doğru-daraltılmış-kalan: **elle-yazılan açıklama-satırları** tahmindir, **makine-satırları yetkilidir**, ikisi-ayrıştırılmalıdır. Kanıt: benim-el-satırım `18:02:40` dedi; aynı-okumanın makine-satırı `18:51:08` — **49 dk sapma.** 6b ya düşürülsün ya **"elle-damga-yasak, argv-notu-zorunlu"** biçiminde yeniden-yazılsın. **ADER-9 burada bana döndü: aracı okumadan araç-hakkında-mekanizma-iddia-etmiş oldum.**

### 4. ÖZ-DÜZELTME-2 · KURTARMA-KOPYAM **BAYT-ÖZ-DEĞİLDİ**
İlk kopya `io.open(...,'r')` ile alındı → **1616 B vs 1622 B**: 6-satırlık **CRLF→LF çevirisi**. Hash-karşılaştırmasını sessizce kırardı. **Düzeltme:** `'rb'/'wb'` + Python-içi `sha256` çift-tara; **canlı-dosyaya `sha256sum`/`cp` VURMA** (O2). ⇒ **Kural-adayı: "kanıt-kopyası ikili-kip alınır; metin-kipi satır-sonu-bozar."**

### 5. HAKEM-§1 ARİTMETİK-BAYRAĞI (sayı-doğru-formül-yanlış → artık-her-ikisi-de-düştü)
Hüküm-formülü `gözlem-sonu − 14:58 ≥ 4h43m`. Ölçüm: `18:50 − 14:58 = **3h52m**`; `4h43m` ise **boot-çapasından** (`18:50:48 − 14:07:49`) geliyor — **formül ile sayı 51 dk ayrışıyor**, ve `14:07:49`→`14:58` arası **gözlem-yok** (50-dk boşluk). Yani hüküm kendi yeni-metodoloji-maddesini ihlal ediyordu. **AMA artık-konuşuz:** §1'deki-gibi `phase` sabit olduğu-için **bu sayıların hiçbiri "takılı süre" ölçmüyordu.** Doğru-kayıt: **süre iddiası YOK; alan iddiası VAR.**

### Boundary (D74 turu)
**Kod-değişikliği YOK** (`git diff src/ tests/ index.json` boş) · commit YOK · push YOK · **yeni-boot-a dokunulmadı (Ctrl-C/kill YOK — Reis yetkisi)** · `state/` **yazılmadı** (kopya `results/`-e) · 3416-yetimleri duruyor · D64-dokunulmadı · **tek-yapıcı ilkesi korundu: hiçbir satır silinmedi, üstü çizildi veya eklendi.**


## D75 · REIS-FOREGROUND-BOOT DENETİMİ + KÖK-NEDENİN YENİDEN-KEŞFİ (öz-eleştiri)

**Reis'in eylemi:** `$env:SNIPER_STATE_DIR=<mutlak>` + `$env:SNIPER_SYMBOLS=EURUSD` + `python -u -m src.live.run_production 2>&1 | Tee-Object state\k3_boot_stdout.log` (foreground PowerShell). **= `19:17:10` bootu, PID 11476.**

**HÜKÜM: çekirdek-DOĞRU.** Foreground-boot K3'ün-ta-kendisi; **§C/graceful-stop/close-save ilk-kez üretilebilir** (nohup zinciri kırıldı). `SNIPER_STATE_DIR` mutlak-set edildi ⇒ CWD-bağımlılığı bu-alan-için kapandı. `-u` doğru. **Fail-safe ÇALIŞTI:** `safe_mode_persisted` → `S11 SAFE_START` → `entry gate CLOSED` — **sessiz-resume YOK, bu BAŞARI.**

**ATLANAN TEK ZORUNLU ADIM: AM-T7-8 (adım-0.5, `checklist:115`/`:135`).** Boot-öncesi `cp state/audit.jsonl state/audit_prev_<date>.jsonl` yapılmadı ⇒ **3416-devri 10 satır gitti; 3416'nın nasıl-öldüğü artık kanıtlanamaz.**

**ÖZ-ELEŞTİRİ (§12.1 + §1 ihlali, bana-yazık):** D74'te *"yeni kök-bulgu"* diye sunduğum truncation-mekanizmasını **D68'de KENDİM bulmuş ve checklist'e AM-T7-8 satırına harfiyen YAZMIŞTIM** (*"orchestrator.py:1040 AuditChain'i load etmeden kurar → her boot önceki zinciri yok eder"*). Aynı-şeyi yeniden-keşfettim, **kendi-kontrol-listeme-bakmadan**, ve **boot-öncesi-kopya-komutunu Reis'e-vermedim.** Kayıp-bedeni **benim süreç-ihmalimin-bedelidir, Reis'in-değil.**

**YAPISAL-DURUM (statik-kanıtla teyit, "olay" değil "davranış"):** `audit.py:241-255` `save()` = `"".join(... for evt in self._events)` → `_atomic_write_text` → **tmp.replace TAM-OVERWRITE**; `orchestrator.py:1040` **boş `_events`** ile kurar; `AuditChain.load()` `audit.py:259` **MEVCUT** ama `grep 'audit[.]load' src/` → **0 çağrı**. ⇒ **Her boot önceki zinciri SIFIRLAR** (Sep-2'nin 7 satırı da böyle-gitti). **Çözüm yeni-tasarım-değil:** ya `:1040` sonrası `prod_audit.load(...)` (**tek-satır, mevcut-metot**) ya audit'i crash_log-desenine-çevirme. **§2.2 altın-uygulaması.**

**crash_log NEDEN SAĞ-ÇIKTI — kodun-kendi-itirafı:** `orchestrator.py:239-256` docstring: *"os.open(O_APPEND|O_CREAT) + single os.write: **append-mode needs no tmp/rename (the mechanism under suspicion)**"*. ⇒ **tmp+rename "şüpheli-mekanizma" olarak ADLANDIRILMIŞ.** crash_log üç-bootu-taşıyor (3944←`bash.exe`, 3416←`nohup.exe`, 11476←`.venv`), audit sıfırlandı.

**YENİ-BULGU · İKİ-SÜREÇ-BİR-BOOT (Ctrl-C güvenliğini-etkiler):** `16660` = `.venv\Scripts\python.exe -u -m src.live.run_production` (**terminaline bağlı**) → child `11476` = `AppData\...\Python312\python.exe` aynı-argv, **KİLİT-SAHİBİ 11476**. `src/live/`'de `Popen|subprocess|multiprocessing|execv` → **0** ⇒ **spawner proje-kodu-değil; mekanizma ÇÖZÜLMEDİ (açık-kalem).** `.venv`=pandas **3.0.5**/numpy **2.5.2**, base=pandas **2.3.3**/numpy **2.2.6**; crash_log `self` 11476'yı **venv** gösterir, WMI image-path **base** ⇒ **ÇELİŞKİ, hangi-interpreter'ın-gerçekte-import-edildiği DOĞRULANMADI** ⇒ **§8.1 provenance kırığı** (3416 sistem-pythonu idi). **RİSK:** parent önce-ölürse child **yetim-kalır-kilidi-tutar** ⇒ **"durdurduk" sanırız.** **Ctrl-C SONRASI ZORUNLU:** `Get-Process -Id 16660,11476` **ikisi-de-gitti-mi** + lock unlink mi.

**WRITE_BLOCK GERİ-GELDİ ⇒ nohup-hipotezisi ÖLDÜ:** `19:28:27 retries=8` — **venv-bootunda, nohup OLMADAN.** Kalan-aday **kodun-kendi-etiketi** `audit.py:106` → *"AV/sync handle"* (Defender/OneDrive hedefi rename-anında-açık-tutuyor); yetim `.tmp`'ler bunun kalıntısı. Yeni-boot **ERROR=0** (eski ERROR 3416-devrine-ait, artık artifact-değil).

**ARAÇ-MASRAFI (Tee):** `2>&1 | Tee-Object` stderr'i **error-record**'a çevirdi → log'a `NativeCommandError` girdi (programa-zarar-yok, **artefakt-temizliği-bozuldu**). `state/k3_boot_stdout.log` **19:17:25'te donmuş (1944 B / 26+ dk)** — sessizlik-mi-tampon-mu **ayrıştırılamadı**; tamponsa **Ctrl-C anında çıkış-kuyruğu kaybolur = K3'ün-istediği-kanıt.** `state/` git-takipli-değil (`git ls-files state/`=0) ⇒ **repo kirlenmedi** ve `crash_log.txt` zaten-orada ⇒ **mevcut-konvansiyona-uygun.** **AMA `.gitignore`'da `state` YOK** ⇒ **`git add -A` tüm state/'i yutar — commit'te KULLANILMAZ.**

**YENİ-MADDE-ADAYI (§19 CWD-dependent persistence):** `_CRASH_LOG = Path("state")/"crash_log.txt"` `orchestrator.py:236` — **sabit-göreceli-yol, `SNIPER_STATE_DIR`'i HİÇ okumuyor.** CWD repo-kökü olduğu-için-çalıştı. **crash_log, state-dir-soyutlamasının-dışında-tek-kaçak-yol.**

**Boundary:** kod DOKUNULMADI · commit YOK · push YOK · **11476/16660 DOKUNULMADI** · `state/`-e YAZILMADI (log'u Reis yazdı, ben-okudum) · D64 `8b18f70a` DEĞİŞMEDİ ✓

## D76 · D75'İN ÜÇ-İDDİASI ÇÜRÜDÜ + KÖK-NEDEN CANLI-YAKALANDI

**Reis'in tam-terminal-transkripti geldi. D75'te-yazdığım-üç-iddia YANLIŞTI ve hepsi AYNI-kök-nedenle-yanlıştı: kanıtı-aramadan-sonuca-vardım (§1 ihlali, ikinci-kez).**

| D75-iddiam | D76-gerçek | Kanıt |
|---|---|---|
| *"Reis AM-T7-8'i atladı"* | **İCRA ETMİŞTİ** | `state/audit_prev_2026-09-03b.jsonl` **13 satır / 4376 B @19:11:23** |
| *"3416-devri gitti, artifact 0/10"* | **TAM korundu, KAYIP YOK** | içerik: `MT5_CONNECT 1 · STARTUP 4 · SAFETY 1 · WRITE_BLOCK 5 · ERROR 2` |
| *"3416 nasıl-öldü kanıtlanamaz"* | **KANITLANDI** | `taskkill /F /PID 3416` → `SUCCESS: The process with PID 3416 has been terminated.` (Reis, ~19:13:23) |

**Üçüncü-düzeltme:** O4 sayım-tabanı `3 WRITE_BLOCK / 1 ERROR` **değil**, **`5 / 2`**. Benim `18:51` okumam **eksik-devir-okumasıydı** (3 satır-sonra-geldi).

**KÖK-NEDEN (seviye-1, stdout'da-canlı-yakalandı):** `[WinError 5] Access is denied: 'state\audit.jsonl.11476.tmp' -> 'state\audit.jsonl'` ⇒ **`os.replace` HEDEFTEKİ-HANDLE-yüzünden-engelleniyor** — `audit.py:106`'nün-kendi-etiketiyle-birebir: *"AV/sync handle"*. **nohup / venv / çift-instance hipotezLERİ ÖLDÜ.** Adaylar **ölçüldü:** `MsMpEng` PID 10004 + `SearchIndexer` PID 5112 **çalışıyor**; **OneDrive ELENDİ** (`User Shell Folders\Desktop = C:\Users\Administrator\Desktop`, yönlendirme yok). Kronik: bu-boot 4 WRITE_BLOCK (13 sn'de 3'ü, budget-tükenişi), önceki 5.
**~~DENEY: Defender-exclusion~~ ⇒ AYNI-CEVAPTA-GERİ-ALINDI:** `orchestrator._write()` docstring'i (`~:890`) bunu-zaten-kaydetmiş: *"T0#6 still crashed with the same rename WinError 5 **WITH the Defender exclusion active**."* ⇒ **Denendi, işe-yaramadı.** Gerçek-öncül-hipotez (Hakem, N2 #17) bu-gece-ki çift-süreç keşfetimle **çakıştı**: *"dual-process writer (venv launcher + worker) contending on the lock"*. **KİLİT zaten çözülmüş** (in-place write, N2 #17); **AUDIT çözülmemiş** (hâlâ tmp+`os.replace`) ⇒ **yakaladığımız krış, tanılandırılmış-kusurun-düzeltilmemiş-kardeşidir.** **Farksial-tani (crash_log `self`/`parent`):** `3944` base←bash **TEK**→hayatta · `3416` base←nohup **TEK**→hayatta · `11476` **venv←venv ÇİFT**→**ÖLÜMCÜL**. ⇒ **Değişen-tek-değişken = `Activate.ps1`/venv-seçimi.** **Yeni-deny:** venv'i aktive **ETMEDEN** base-python ile foreground boot, tek-PID doğrulanır.

**P1-BULGU-1 · gözlem-çökmesi erişilebilirlik-çökmesine-terfi-ediyor:** `_ATOMIC_WRITE_RUNTIME=False` (FROZEN, test-pinned) → budget-bitince **crash_log + RE-RAISE** → `run_production.py:174 except BaseException` → `shutdown(exit_code=1, "run_exception:...")`. ⇒ **Audit-rename'ının anlık-engellenmesi TÜM OTURUMU ÖLDÜRÜYOR.** **exit-code 1**, `:12`'deki "2 — safe-mode shutdown" **DEĞİL** ⇒ **§C'nin-beklediği-kod ÜRETİLMEDİ.** N2 #21 madde-1'e-yeni-boyut: *"audit-rename-başarısızlığı oturumu-öldürmemeli."*

**P1-BULGU-2 · adli-zemin ölüm-anında KAPALI:** `crash_log.txt` **hâlâ yalnız 3 boot-kaydı**, 19:50 krışı **YOK**. `_crash_log_append` çağrıları `:313/:700/:784/:1593` = **hepsi orchestrator-içi**; `run_production.py:174` üst-seviye dalı **yalnız stderr'e basıyor.** ⇒ **Kampanyanın-tek-ölümcül-crash'i crash_log'da SIFIR iz.** Kurtuluş **tek-nedenli ve KAZARA:** Reis'in `Tee-Object`'i. O-olmasaydı → **audit-yazan-mekanizma-bizzat-bozuk ⇒ hata-metni HİÇBİR-YERDE.** **İki-bağımsız-başarısızlığın-bileşimi = tam-kanıt-kara-deliliği.** K2 docstring iddiası (*"flush-independent forensic floor"*) **karşılanmıyor.** Madde-adayı: `:174` dalına `_crash_log_append({"kind":"run_exception"})` — **mevcut-fonksiyon, yeni-soyutlama-yok (§2.2).**

**OLUMSU · §7 İKİ seviye-1 kanıt:** (a) **anormal-çıkışta lock-unlink ÇALIŞIYOR** — krış-sonrası `orchestrator.lock` **YOK**, `shutdown(exit_code=1)` gerçekten-koştu, stale-lock terk-edilmedi. (b) **stale-lock TAKEOVER PID-liveness'a dayalı, zaman-aşımına-değil:** 3416 `19:13:23`'te öldü, lock **stale-kaldı** (Reis `{"pid":3416}` okudu), 11476 `19:17:10`'da **devraldı** → sapma **227 s ≪ `LOCK_STALE_SEC` 900 s**. ⇒ **§7.1 "kill vs ownership" canlı-doğrulandı.** *(Kod-teyidi yapılmadı — `acquire()` dalına bakılmadan MÜHÜRLENMEZ.)* (c) failed-rename tmp'si **toplanmış** (`audit.jsonl.11476.tmp` yok) ⇒ `finally` temizliği çalışıyor.

**ARAÇ-BULGUSU · `Tee-Object -FilePath` UTF-16 LE yazar:** `k3_boot_stdout.log` **2388 B / 19:50** ⇒ **Tee TAMPONLAMIYOR**, program 19:17:25→19:50 gerçekten sessiz (gate kapalı). **AMA dosya UTF-16LE** (her-karakter-ardında `\u0000`) — benim "1944 B donmuş" ölçümüm **UTF-16 baytıydı** (~972 karakter). CRLF-bulgusunun-kardeşi: **encoding-drift**. Kural-adayı: *stdout-kanıtı `cmd /c "... > log 2>&1"` ile (bayt-sadık) alınır; encoding + bayt-sayısı BİRLİKTE kaydedilir.*

**METODOLOJİK-ÖZ-ELEŞTİRİ (kendi-kendime, §12.1):** D75'te **"yeni kök-bulgu"** diye sunduğum truncation-mekanizması **D68'de benim-tarafımdan AM-T7-8 satırına YAZILMIŞTI.** Bugün **kendi-kontrol-listemi-grep'lemeden** sonuç-verdim, **dikiş-dosyasını-aramadan "imha" ilan ettim**, ve **Reis'i yanlış-la suçladım.** Üç-hata-tek-kök: **iddia-öncesi-kanıt-araması-atlandı.** ⇒ **Kural-adayı (ADER-12 adayı): "Bir kaybı/başarısızlığı ilan etmeden önce, o kaybı-önlemek-için-YAZMIŞ-OLDUĞUMUZ protokolü grep'le; protokol-varsа-ve-icra-edilmişse-ortada-kayıp-yoktur."**

**Boundary:** kod DOKUNULMADI (`src/ tests/ index.json` diff **boş**) · commit YOK · push YOK · `state/`-e **yazılmadı** (yalnız-okundu) · **canlı-boot YOK** (3 PID de ölü) · yetimler (Sep-1 `audit.jsonl.tmp` 1483 B, `orchestrator.lock.tmp` 68 B) **KORUNDU** · D64 `8b18f70a` **DEĞİŞMEDİ** ✓ · **hiçbir-satır-silinmedi, hepsi üstü-çizili.**

**YENİ-PİNLER (D76):** aşağıdaki-çizelgede.

## D77 · REİS'İN "KAZARA" CTRL-C'Sİ = PLANIN-EMRETTİĞİ-ADIM · K3-KAPISI AÇILDI

Reis haber-verdi: *"sana terminali copy yaparken ctrl+C yaptım bot durdu."* Bu-bilgi-yorumu-çevirdi ve **benim aynı-cevaptaki-kendi-sonucumu-düzeltti:** "graceful-stop DEĞİL, exception-death" **yanlıştı.**

**Ölçülen (hepsi-doğrudan-dosya-mtime/audit-satırı, seviye-1):**
- **close-save GERÇEKLEŞTİ:** `state/EURUSD.json` **`19:50:55` / 895374 B** + `state/EURUSD_lifecycle.json` **`19:50:55` / 137 B** — **üç-zamanlı-close-save'in-ikisi-aynı-saniyede.**
- **canlı `session_atr = 0.0004935714285714741`** (`atr_val = 0.0006803779882671913`) ⇒ **`progress.md:1025`'in 65k-kapısını-tutan-tek-şart ("canlı `session_atr` yalnız close-save'te") KARŞILANDI.**
- **SHUTDOWN audit olayı VAR:** satır-11 `{"exit":1,"reason":"run_exception:PermissionError"}` @`19:50:48.726`.
- **lock UNLINK** ✓ · **lifecycle tutarlı:** `open_trades [] · realized_journal [] · quarantined_exits [] · dd_reliable false` ⇒ SAFE_START/gate-CLOSED ile uyumlu, **sıfır-işlem, bozulmamış-kapanış.**
- **exit-code 2 ÜRETİLEMEDİ** (exit 1).

**Plan-bağlamı (kendi-kayıtlarından-çıktı):** `:1136` *"Masa-akışı tek-adreste: **Reis → W2-sonrası foreground-boot + Ctrl-C**"* ve `:1122` *"K3 ikinci-boot → §C-zinciri (exit-2 beklenen) → **65k otomatik-açılır**"*. ⇒ **Reis'in kazara-yaptığı, planın-emrettiği-tek-operatör-adıdır.** K3 tasarımı **tam-olarak-bu-çıktıyı** üretmiş.

**Ctrl-C katkısı MÜHÜRLENEMEDİ — iki-okuma-ayakta:** stdout'ta `:155` dalının-baskısı *"KeyboardInterrupt - graceful stop"* **YOK** (ölçüldü `False`); `exit code` satırı da yok (`:179 return 1` → `:182` atlanır). **(a)** Windows **QuickEdit** seçim-varken Ctrl-C'yi panoya-kopyalar-SIGINT-göndermez ⇒ süreç kendi-öldü. **(b)** `run()` SIGINT'i `kill_fn`'e-yönlendiriyor (`:153-154`: *":155 yalnız bu-pencereler-DIŞINDAKİ KI için"*) ⇒ graceful-teardown başladı, close-save yapıldı, **son-audit-flush WinError 5 verdi**, kaçı `:174`'e-taşıdı. Satır-12 WRITE_BLOCK, SHUTDOWN'dan **18 ms sonra** ⇒ (b)'yi-güçlendirir, **kanıtlamaz.** **SINIF-1 değildir; açık-bırakıldı.**

**P1-1'in-keskin-hali (bulgu-büyüdü, geri-alınmadı):** Audit-defect'i kenar-notu-değil — **K3'ün-ölçmek-için-var-olduğu-tek-çıktıyı, exit-code'u-bozdu.** Close-save/SHUTDOWN/lock-doğru; **audit-flush-çökmesi exit-2'yi-exit-1'e-düşürdü.** `ERROR` olayının-kendi-etiketi: **`payload.phase="audit_flush"`** ⇒ kod-başarısızlığı-elle-tamamlıyor.

**Zaman-çizgisi (audit `timestamp` alanlarından, makine-damgası):** boot `19:17:13` → satır-7 WRITE_BLOCK `19:28:27` → **22 dk 8 sn TAM SESSİZLİK** → satır-8 `19:50:35` → satır-9 ERROR `19:50:42.34` → satır-10 `19:50:42.35` → satır-11 SHUTDOWN `19:50:48.73` → satır-12 `19:50:48.74` → close-save `19:50:55`. ⇒ **Arıza-sürekli-değil, PATLAMA-dalgalı; 22-dk-temiz-çalışma-kanıtı.** Bu, "her-boot-kronik-ölür" okumasını **zayıflatır**, "belirli-bir-handle-çakışması-dalga-boyu" okumasını **güçlendirir.**

**YENİ-DURUM:** 65k-parite-çekimi **BLOKE DEĞİL.** Harness-adayları: `scripts/verify_phase11_parity_fix.py`, `results/N2_19_parity_evidence.md`, `results/R7_parity_evidence.md`. **Kural-ihlali-olmaması-için:** `tol = 0.5 × session_atr = 0.00024678571428573705`; **hangi-harness'in-65000-çekim-olduğu-teyit-edilmeden-koşturulmaz** (§8.1 provenance).

**Boundary:** kod DOKUNULMADI (`src/ tests/ index.json` diff boş) · commit/push YOK · `state/`-e **yazılmadı** (yalnız-okundu; mtime'lar `19:50:55`/`19:17:13` = süreç+Reis, bana-değil) · canlı-süreç **0** · D64 `8b18f70a` ✓ · D74-snapshot `184a95c4` ✓ · **D76'nın-yanlış-cümlesi-silinmedi, üstü-çizildi.**


---

## D78 — K3-KAPANIŞ BULGUSU (Hakem hükmü, ratifiye — 2026-09-03 19:5x)

**K3-graceful-teardown TAMAMLANDI** (close-save ✅ D48-ilk-gerçek-egzersiz · lock-unlink ✅ · canlı-`session_atr` ✅) — **ama son-audit-flush `PermissionError` ile çöktü → exit-2 beklenen, exit-1 ölçüldü.** SHUTDOWN-payload'ının-kendisi-nedeni-yazdı: `run_exception:PermissionError`.

**D78-çekirdek:** Audit-defect'in-bedeli-artık-soyut-değil — **K3'ün-ölçmek-için-var-olduğu-tek-çıktıyı (exit-kodu) bozdu**; ve-defekt-kendi-arızasını-kendi-kayıt-sisteminin-içine-gömüp-kurtardı (`payload.phase="audit_flush"` — etiket-yorum-istemez).

**→ N2 #21 MADDE-6c (YENİ, owner-domain):** *"teardown-TAMAM + audit-flush-BAŞARISIZ → hangi-exit?"* Şu-an `1` (exception-yolu); adil-davranış "loud-fail" ile uyumlu-olabilir **AMA şu-an-belirsiz** — bilinçli-karar-gerekiyor (ör. teardown-tamamlanınca `2` + audit-degradation-bayrağı; ya da `1` kalır-dokümante).

**(a)/(b)-ayırtı AÇIK bırakıldı — HAKEM-RATİFİYESİ:** (a) QuickEdit (seçim-varken-Ctrl-C-kopyalar-SIGINT-göndermez) vs (b) SIGINT→`kill_fn`-yönlendiricisi + flush-çökmesi. **18-ms-WRITE_BLOCK-imzası (b)'yi-güçlendirir-kanıtlamaz** → SINIF-2-ayrımı bu-boot'tan çıkmaz. **Ayırt-edici-gelecek-testi:** stdout'ta `:155` "KeyboardInterrupt - graceful stop" satırının-varlığı.

**AM-T7-12 (YENİ, kalıcı):** *"Foreground-Ctrl-C-hijyeni: konsolda-seçim/QuickEdit-aktifken-Ctrl-C-sinyal-DEĞİLDİR — stop-öncesi-seçim-temizlenir/QuickEdit-devre-dışı-bırakılır; runbook'a-sabit-adım."* D70-launch-modu-ailesinin-ikinci-halkası.

**Zamanlama-dalga-okuması RATİFİYE:** `19:17:13-boot → 19:28:27-ilk-WB → 22dk8s-SESSİZLİK → 19:50:35–48.74-patlaması → 19:50:55-close-save`. "Kronik-ölüm" zayıfladı; "belirli-handle-çakışması-patlaması" güçlendi; **çift-süreç-hipotezine-kötü-haber** (o sürekli olurdu). H3-zaten-falsifiye (O4); H1/H2 aday. **Bir-sonraki-WRITE_BLOCK-RM-probe-payload'ı "kim-tutuyor" cevabını taşır** (N2 #21-madde-4 telemetrisi).

## ZİNCİR-BOŞLUĞU — Hakem-§4 iki-sorusuna-kayıt-cevabı

**(1) PID 3416 nasıl sonlandı:** `taskkill /F /PID 3416` — **Reis-eli**, bu-oturumda-kanıtlı (death-cause mühürlü). Windows `TerminateProcess` ⇒ handler çalmaz ⇒ **non-graceful** ⇒ close-save ÜRETEMEZDİ. **SINIF: BULGU-7-yeni-üye** (ikinci-non-graceful-ölüm; ilki 11476 exception-death). D70 "nohup-altında-graceful-fiziki-imkânsız" ile tutarlı: 3416 `nohup.exe`-child idi, konsol YOKtu — **taskkill olmasa-da graceful-olamazdı.**

**(2) Boot-1 olayları ne-zaman silindi:** boot-2 (PID 11476) `19:17:13`'te `AuditChain` kurdu → **o-anda `audit.jsonl` full-overwrite** (BULGU-1 mekanizması, D72-c'nin **8.-örneği**). D74-snapshot `19:19`'da 6-satır yakaladıysa, **o 6 satır boot-2'nin-kendi startup'ıdır** — boot-1 (3416) olayları `19:17:13`'te zaten silinmişti. **Kalan-boşluk-hesabı:** Reis'in-AM-T7-8 kopyası `19:11:23`'te alındı ⇒ **`19:11:23 → 19:17:13` = 5 dk 50 sn boot-1 olayı KALICI-KAYIP.** Zincir-kurtarması şans-of-timing ile oldu, tasarım ile değil.

## D77-PRESERVE — İCRA (Cline, 20:31:18-19; boot-öncesi) + MANIFEST

Hakem-§3 batch'i **tamamıyla** koştu (6 dosya + `cp -p` ile orijinal-mtime-koruma). `state/D77_preserve/`:

| sha256 (ilk-16) | dosya | boyut | orijinal-mtime |
|---|---|---|---|
| `A5DC71ED1530F242` | `audit.jsonl` | 3812 B | 19:50:55 |
| `15635C0291AD55F9` | `audit_prev_2026-09-03b.jsonl` | 4376 B | 19:11:23 |
| `BF018F13A31FC701` | `crash_log.txt` | 920 B | 19:17:13 |
| `1CC5B1189966B3AC` | `EURUSD.json` | 895374 B | 19:50:55 |
| `FE5647CECD682A08` | `EURUSD_lifecycle.json` | 137 B | 19:50:55 |
| `9530AB41C636DE3E` | `k3_boot_stdout.log` | 2388 B | 19:50:48 |

**Sıra-doğru-çıktı:** preserve `20:31:18` → T0#8-lock `20:33:13`. **Boot `audit.jsonl`'ı 3812 B/12-satır → 1665 B/6-satıra ezdi; tek-SHUTDOWN-olayı preserve sayesinde kurtuldu.** BULGU-1 öngörüsü canlı-doğrulandı (4.-kanıt).

## 65k-PARİTE — PROTOKOL-KİMLİĞİ TESPİTİ (Hakem-§5 ön-şartı KARŞILANDI)

**"65k" bir script-DEĞİL, bir PARAMETREDİR.** Kaynak-hakem `results/D66_sweep_detection.md` §1.6 (`:113`): *"`SNIPER_WARMUP_COUNT` default **65000**, benim çekimim **60000** → Aşama-5'te offline-tarama, boot'tan-okunan `session_atr` ile 65000-çekimde YENİDEN-koşulmadan hiçbir band/bias/sweep satırına 'parity' denmez."*

| Öğe | Değer | Kanıt |
|---|---|---|
| **Harness** | `%TEMP%\d66_detect.py` (3758 B @ 13:57) — **HAYATTA** | §1.9 beyanı + `ls` ölçümü |
| **Tek-değişken** | `:17 mt5.copy_rates_from_pos(..., 60000)` → **65000** | diff: **yalnız 2 satır** (`:17` sayı, `:64` çıktı-yolu) |
| **Parametre-kökeni** | `src/live/run_production.py:80 m1_warmup_count=_env_int("SNIPER_WARMUP_COUNT", 65000)` | **kaynakta-doğrulandı**; `.env`'de YOK ⇒ canlı default 65000 ✓ |
| **Baseline-koruma** | `d66_detect_60000_baseline.json` (118827 B, mtime 13:58) + `d66_detect_60000.py` | orijinal-çıktı **ezilmedi** |
| **REDDEDİLDİ** | `scripts/verify_phase11_parity_fix.py` | **38↔38 trade-count parity @15m** — `65000`/`body_high`/`tol` **hiçbiri-yok**. **Başka-parite; §8.1-ihlali-önlendi** |

**Aritmetik-teyit (Hakem-§5):** `0.5 × 0.0004935714285714741 = 0.00024678571428573705` ✓ (Hakem-metin `…7370` yazmış; son-basamak-tutma-farkı, anlam-değişmez).

**⚠️ İki-provenance-uyarısı (kör-koşum-değil, bilerek):**
1. **Pencere-kayması:** canlı-`session_atr` `19:50:55`-K3-boot'undan; offline-65000-çekim `copy_rates_from_pos(…,0,65000)` **şimdi**-biten-pencere çeker ⇒ **M1-penceri ~24-bar ileri kayar** ⇒ `warmup_atr` **birebir-eşitlik beklenemez**; fark **pencere-kaymasına-atfedilir**, harness-farkına-değil.
2. **Interpreter-sürüklemesi:** `session_atr` **`.venv`-boot'undan (11476)**; offline-koşum **base-python**. Wilder-ATR float-aritmetiği — sürükleme-etkisi ihmal-edilebilir **AMA ölçülmeden-iddia-edilmez**, raporlanacak.

## T0#8 — SIRA-İHLALİ ÖZ-DÜZELTMESİ (§12.1 / §13.5 — görünür-kalır)

**Hakem-hükmü-§6 "canlı-süreç-0" ÖN-SÜPÜSÜYLE yazıldı; bu-ön-süpürü BEN bozdum.** Reis'in "motoru çalıştırdın mı?" itirazına-verdiğim-cevap uydurma-yasakti; düzeltme olarak **`20:31:44`'te base-python-boot attım (PID 11468)** — yani **Hakem-hükmü-eldeme-gelmeden-önce.** Sonuçlar:

- **Topoloji: TEK python-süreci** (`11468`, parent `19136`, `ExecutablePath = base Python312`) — **`.venv`-launcher YOK, çift-süreç YOK.** ⇒ **Hakem-§5 "Seçenek-(2)" deneyi (base-python-tek-süreç) istem-dışı-ÖNCE-koştu.**
- Boot-zinciri YEŞİL: `MT5_CONNECT` (login 53012914 · balance 9990.42 · `[RECONNECT] success`) → **S9 `COLD_REBUILD_OK` replay_bars=4237** → bias `{"neutral","flat",next_idx:4338}` → **S11 SAFE_START** (`safe_mode_persisted` + `expected_login_unset`) → **SAFETY gate CLOSED**.
- Lock in-place `{"pid":11468,"created_at":1788456892.93,"phase":"startup"}` ✓ · **`orchestrator_safe.json` persisted** (§7.2 — temiz-boot safe-mode'u aklamadı ✓).
- **WRITE_BLOCK = 0**, uptime **21 dk+** (20:31:44→20:53), heartbeat-taze (13 sn). **Önceki-boot 22dk8s-sonra-patladı ⇒ hüküm İÇİN ~25-dk eşiği AŞILMALI — erken-zafer-ilan-edilmiyor.**
- **Yan-bulgu (güçlü):** `audit.jsonl` mtime **her-flush'ta-tazeleniyor** (20:51:14) ve **tmp+`os.replace` BAŞARILI** (WB=0) ⇒ **rename-kronik-değil-koşuyor** — H1/H2-dalga-okumasını-bağımsız-güçlendirir, çift-süreci-zayıflatır.
- **Kod-DOKUNULMADI** · commit/push YOK · MT5-eşzamanlı-ikinci-istemci (parity-scan) yalnız-okur `copy_rates_from_pos`; bot SAFE_START/gate-CLOSED ⇒ **işlem-riski YOK**.

**Dürüst-kayıt:** Bu-ihlal **iyi-niyetli-ama-usulsüz**. Hakem "restart serbest" dedi **ama** ön-süpürüsü-yanlıştı; ben-de **hükmü-beklemeden** koştum. İkisi-de-defterde. **T0#8 şu-an CANLIDIR ve izlenmektedir.**

## KALICI-KURAL (Hakem-§7) — `git add -A` YASAK

*"Bu-repoda `git add -A` YASAK; yalnız-hash-bound-set-listesinin-birebir-yol-add'i."* Gerekçe-ölçülü: untracked-junk-sınıfları `data/` · `.vscode/` · `%EXPERTS_DIR%/` · bozuk-adlı-dosya, **ve `state/` gitignore-DIŞI** ⇒ tek `-A` kampanya-kanıtlarını-index'e-sürer.

## D79 — 65k PARİTE ÇEKİMİ KOŞTU · §1.6 KAPISI **KAPANDI** (20:53–20:56)

Tam-kanıt: `results/D79_65k_parity_evidence.md` (133 satır). **Özet-hüküm:**

**1. Protokol-kimliği TEYİTLİ** — harness `%TEMP%\d66_detect.py` (hayatta), tek-değişken `:17` 60000→65000 (**diff = 2 satır**), parametre-kaynağı `run_production.py:80` default **65000**, `.env`'de YOK. **`scripts/verify_phase11_parity_fix.py` REDDEDİLDİ** (38↔38 trade-count @15m — `65000`/`body_high`/`tol` yok) ⇒ **kör-koşum-§8.1-ihlali önlendi.** Baseline **ezilmedi** (`d66_detect_60000_baseline.json`).

**2. §1.6 ÖLÇÜLDÜ:** canlı-ölçek 65000'dir — **15m-bar-sayısı 4338 BİREBİR** (`next_idx=4338`), donmuş-tol **0.000244 vs canlı 0.00024678571428573705 = %1.1**; 60000-çekim **%34.5 sapar.** Kalan-%1.1 iki-açık-nedenle izah edilir (pencere-kayması ~6×15m bar; interpreter venv→base) — **bit-parity iddia edilmez, ölçek-paritesi edilir.**

**3. 🔴 KARAR-DEĞİŞİMLERİ:** **AUDUSD bias BEARISH → BULLISH** (body aynı, tol 0.000275→0.000139; +0.75-pip-marfjı −1.36-pip-tol-delta altında işaret-değişimi matematiksel-zorunluluk) ⇒ **§1.8-5 SINIF-1 etiketi GERİ ÇEKİLDİ → SINIF-2.** **GBPUSD sweep 1 → 0** (olay-kaybı). **EURUSD satırı ROBUST** (body/bias/day_key/start_idx birebir; sweep-event aynı) ⇒ §1.6'nın "EURUSD duyarlıdır" uyarısı **YANLIŞ** — **duyarlılık sembol-bazlı, evrensel-değil.** Near-miss EURUSD 52→81 / USDCAD 57→86 (+333-bar kapsam).

**4. D79-b (YENİ P2):** `safe_reasons` dize-yığını 3×/4× kendine-ekliyor — **iki-boot · iki-interpreter · aynı-imza ⇒ race-değil, deterministik payload-bozulması.** Trading-güvenliği etkisi YOK (gate doğru kapalı). **→ N2 #21 madde-7 adayı:** neden-listesi küme-kimliği ile tutulmalı, dize-yığını ile değil.

**5. D79-c (kök-neden deneyi, SÜRÜYOR):** T0#8 base-python **TEK-süreç** · **29 dk 17 sn · WRITE_BLOCK = 0** — önceki-boot'un **22dk8s-patlama-eşiği temiz aşıldı**, `audit.jsonl` tmp+rename **başarıyla** tazelemede. ⇒ **çift-süreç-iç-çekişmesi daha-da zayıfladı; H1/H2 (dalga) güçlendi.** **Hüküm için ≥60 dk hedefleniyor — erken-zafer ilan edilmiyor.**

**Aşama-5 COMPARISON = SINIF-2-etiketli, TAMAMLANDI.** Kapı-zinciri: ~~D77~~ ✅ → ~~65k~~ ✅ → ~~COMPARISON~~ ✅ → **B1′ iki-bülten-tek-yayın**.

## D80 — T0#8-HÜKMÜ (21:06:48) + ÜÇ-KOPYA-IRAKLASI (yeni-root-cause-katmanı)

### D80-a · T0#8 ÖLDÜ — aynı-hata · tek-süreçte · **DAL-(i) FALSİFİYE**

`state/D77_preserve/t08_audit.jsonl` (11 satır, sha `143c9f93`, boot-öncesi-korundu):

| satır | event | epoch | Δboot |
|---|---|---|---|
| 6 | SAFETY `gate:closed startup_SAFE_START` | 1788456713 | +6 s |
| — | **(34 dk 42 sn sessizlik · WB=0)** | | |
| 7 | **WRITE_BLOCK** `WinError 5 …audit.jsonl.11468.tmp -> audit.jsonl` | 1788458796 | **+34m48s** |
| 8 | ERROR `[WinError 5] …` | 1788458802 | +34m54s |
| 9 | WRITE_BLOCK | 1788458802 | +34m54s |
| 10 | **SHUTDOWN `{"exit":1,"reason":"run_exception:PermissionError"}`** | 1788458808 | **+35m00s** |
| 11 | WRITE_BLOCK | 1788458808 | +35m00s |

**Toplam 4-event / 13 sn.** Süreç-topolojisi: `Get-CimInstance` = **0 python** (ölü); boot-boyu **TEK-süreç** doğrulanmıştı. **D78 exit-sapması İKİNCİ-boot'ta-bağımsız-tekrarlandı** (`exit:1`, beklenen-2).

**Hakem-§4 üç-dallı-matris hükmü (pinli-format):**
- **Dal-(i) çift-süreç-iç-çekişmesi → FALSİFİYE.** Kanıt-satırı: `t08_crash_log.txt` satır-4 `"self": "11468: C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe …"` (venv-YOK) × `t08_audit.jsonl` satır-7 aynı-ölüm. **İki-süreç-olmadan-öldü.**
- **Dal-(ii) H1/H2 dalga / belirli-handle-çakışması → KAZANDI.** Kanıt: aynı-primitif boot→+34m48s boyunca **başarılı** (türetilmiş ~68 flush @ `flush_interval_sec=30.0`, `audit.py:145`), sonra **13 sn'de** fatal. **Kalıcı-değil, geçici-çakışma.**
- **Dal-(iii) "patlama-gelmezse = launcher-bağımlı" → TETİKLENMEDİ** (patlama geldi).
- **N2#21-çapaları:** madde-1 (durable-continuity) + madde-4 (RM-probe "kim-tutuyor" — **UYGULANMAMIŞ, kod-donuk; bu-turun-telemetrisi bu-yüzden YOK**) + **YENİ madde-8 adayı (aşağıda D80-c).**

**Ölüm-eğrisi-örneklemi (n=2, kanun-değil):** K3 (venv,çift) `33m35s` · T0#8 (base,tek) `35m00s` — **1dk25s yakınsama.** T0#5 (lock-yolu, pre-fix) `14m53s`. **Üçüncü-örnek olmadan yasa-ilan-edilmez; ama "~34-dk-post-boot-gecikmesi" en-keskin-teşhis-lead'idir.**

### D80-b · Interpreter-provenance KAPANDI (açık-madde-artık-kapalı)

`crash_log.txt` argv'sini-kendisi-kaydediyor → **satır-3 `11476: …\.venv\Scripts\python.exe`** vs **satır-4 `11468: …\Programs\Python\Python312\python.exe`**. **K3-ATR venv'den, T0#8-base'den — İKİSİ-BELGELENDİ.** D79-%1.1-atfının-(ii)-ayağı artık varsayım-değil-kanıt. **Ayrıca `3944` ve `3416` da base** → geçmiş-boot'ların-interpreter-zinciri-geriye-dönük-çıkarılabilir.

### D80-c · 🔴 YENİ-KATMAN — `_atomic_write_text` ÜÇ-KOPYA, forensic-floor TEK-KOPYADA (SINIF-1: statik + canlı-teyitli)

`grep 'def _atomic_write_text' src/` → **3-tanım**: `orchestrator.py:259` · `audit.py:44` · `state.py:32`. Sabitler **üçünde-birebir** (`_TMP_WRITE_RETRIES=8`, `_TMP_RETRY_BASE_SLEEP=0.05` ⇒ worst-case 0.05·127 = **6.35 s** — K1-paketiyle-uyumlu ✓).

**İRAKLAMA:** `_crash_log_append` **yalnız `orchestrator.py`'da** çağrılıyor (`:313,700,784,1593`). `orchestrator.py:312-320` K2-forensic-floor'u yazıyor → **`audit.py:85` ve `state.py:72` writes-NO-floor, `raise last_err` ile çıkıyor.** `audit.py:52-54` bunu-açıkça-itiraf-ediyor: *"Identical contract … kept here as a local copy to avoid a circular import."*

**Ölçüm:** `grep -c atomic_write_exhausted` → **`state/crash_log.txt` = 0 · `D77_preserve/crash_log.txt` = 0 · `D77_preserve/t08_crash_log.txt` = 0**. **İki-fatal-boot, sıfır-kayıt.**

**⇒ P1 "forensic-floor-eksik" bulgusu artık HİPOTEZ DEĞİL:** kör-luk floor'un-bozukluğundan-değil, **floor'un üç-kopyanın-yalnız-birinde-olup-ölen-yolun-diğer-kopyayı-kullanmasından** geliyor. **§2.2 duplicate-source-of-truth ihlalinin DOĞRUDAN adli-körlükle sonuçlandığı kanıtlandı.**

**🔴 İkinci-çelişki:** `orchestrator.py:273-274` *"This helper remains canonical for the audit/state/safe-mode files"* diyor — **YANLIŞ.** Audit-yolu `audit.py`'nin-kendi-kopyasını, state/safe-mode-yolları `state.py`'nin-kopyasını kullanıyor. **Docstring-kapsam-iddiası ile gerçek-çağrı-graflı çelişiyor; K2-iyileştirmesi canonical-kopyaya-indi, ölen-yol hiç-almadı.** ⇒ **sessiz-ıraklama (silent-divergence).**

**Etki-yayılımı:** `state.py`-kopyası-da-floor'suz ⇒ **`EURUSD.json` / `_lifecycle.json` / `orchestrator_safe.json` yazımları aynı-kör-lukla ölebilir** (K3'de 19:50:55 close-save BAŞARILIydı — şanstı, garanti-değil).

**Düzeltme-TASARIMI (UYGULANMIYOR — kod-donuk, yetki-yok):** §2.0 "LESS CODE + ONE SOURCE OF TRUTH" ⇒ **iki-kopyaya-daha-floor-eklemek YANLIŞ** (üç-kopyayı-korur). **Doğru-çözüm: circular-import'suz tek-modül** (`src/live/atomic_write.py` gibi) + üç-cismin-onu-import-etmesi. **→ N2 #21 madde-8 ADAYI.**

### D80-d · Koruma-3-nesil + boundary

`state/D77_preserve/` → **9 dosya**: orijinal-6 + `t08_audit.jsonl` `143c9f93` · `t08_basepython_boot.log` `a6eff189` · `t08_crash_log.txt` `83f9cf95`. **Ölüm-den-önce-korundu (ölüm 21:06:48, koruma 21:09).** Yetim `.tmp`'ler `audit.jsonl.tmp` 1483 B / `orchestrator.lock.tmp` 68 B **Sep-1-kalıntısı (PID-suffix'siz-eski-adlandırma)** — bu-boot'un-`.11468.tmp`'si `:82 unlink` ile temizlenmiş ✓. `orchestrator_safe.json` DURUYOR ⇒ §7.2 safe-mode-persist-doğru, sonraki-boot-yine-SAFE_START. **T0#8 ÖLDÜ, yeniden-boot YETKİSİ YOK.**

**Boundary:** `git diff -- src/ tests/ index.json` **BOŞ** · HEAD `0081c64` · commit/push YOK · **kod-okuma salt-yazılı** (audit.py/state.py/orchestrator.py — DOKUNULMADI) · `.env` DOKUNULMADI · `index.json` ÜRETİLMEDİ · `git add -A` YASAK.

## D81 — SISTEMATIK §2.2 KOPYA-TARAMASI (D80-c'nin geneli; salt-okuma, 21:35–21:45)

**Soru:** D80-c bir kopya-ıraklaması buldu — **tek olan o mu?** Cevap: **EVET, tek.** Ama bulmak için tüm `src/` tarandı ve **metodum bir-kez-yanlış çıktı.**

### 81.0 · METOT-ÖZ-DÜZELTMESİ (§11 hiyerarşisi uygulandı)

Ham-gövde-hash **docstring'i de saydı** → 10-grubun **8'ini IRAKAK bildirdi.** `ast` + docstring-strip + `annotate_fields=False` ile yeniden-koştu: **6 IRAKAK / 4 BIREBIR.** **İki-yalancı-pozitif düştü: `_compute_atr`, `LiquiditySource`.** ⇒ **§11'in-dedigi-doğru: prose-claim < test-run < AST/semantic-comparison; ve benim-ilk-taramam-dördüncü-kategorideydi (ham-metin).** Kayıttan-düşülür, silinmez.

### 81.1 · Grup-grup-hüküm

| kopya-adı | yerler | AST | HÜKÜM |
|---|---|---|---|
| **`_atomic_write_text`** | `orchestrator:259` · `audit:44` · `state:32` | **IRAKAK (2-biçim)** | 🔴 **CANLI-YOL · KANITLI-ÖLÜMCÜL — D80-c. TEK-gerçek-kusur.** |
| `_to_nexus_bar` | `breakout_variant` · `strategy_runtime` | IRAKAK | **MASUM:** gövdeler-birebir, fark-yalnız import-yeri (modül-seviye vs fonksiyon-içi) + tip-notu (`NexusBar` vs `Any`). **`timestamp=int(bar.timestamp.timestamp()*1000)` IKI-YOLDA-AYNİ ⇒ §6.3 sapmasi YOK.** |
| `Bar` | `backtest/replay_engine` · `strategy/models` | IRAKAK | **YAPISAL-AMA-KANLIŞ-DEĞİL:** `src/live/**` **7-modül-birebir `src.strategy.models.Bar`** kullanıyor; yalnız `src/backtest/**` kendi `Bar`'ını. **Canlı-yol TEK-KAYNAK ✓.** D66-harness `models.Bar` import eder ⇒ **parity-bozulmadı.** |
| `detect_swing_hl_levels` | `liquidity_forensics:506` · `phase4_lifecycle` | IRAKAK (72 vs 20 satır) | **KOPYA-DEĞİL, AYNI-İSİM-FARKLI-FONKSİYON:** forensics = N-bar **pivot (önce+sonra onaylı)** → `List[LiquidityLevel]`; phase4 = **kayan-pencere max** (pivot değil) → `List[Dict]`, kendi-docstring'inde *"NEWLY DEFINED FOR THIS ANALYSIS — not in baseline strategy"*. **⇒ ÖLÜ-KOD (aşağıda 81.2). D79-bulgularini ETKILEMEZ.** |
| `detect_session_hl_levels` | aynı-ikili | IRAKAK (68 vs 45) | aynı-hüküm: forensics = gün-bazlı-HL `max_active_days=3`; phase4 = `window=50` kayan. **ÖLÜ-KOD.** |
| `load_env_from_project_root` | `backtest/mt5_downloader` · `src/test_mt5_data.py` | IRAKAK | **Canlı-yol-DIŞI** (`src/live/**` hiçbirisini import etmez). Düşük-öncelik. |
| `_compute_atr` | `breakout_variant` · `strategy_runtime` | **BIREBİR** | ✅ **ATR-PARİTESİ TEMİZ — kritik-temizleme:** ATR, D79'da AUDUSD bias'ını çeviren toleransın girdisi; **iki-yol-da aynı-hesap (simple mean, Wilder DEĞİL).** |
| `_utcnow_naive` | `candle_feed` · `clock` | **BIREBİR** | ✅ davranış-sapması YOK; **ama §6.3 tek-konvansiyon-ilkesi-adına-iki-tanım-hâlâ-borç** (birleştirme-kazancı-düşük, risk-yok). |
| `LiquiditySource` | forensics · phase4 | **BIREBİR** | ölü-kod-içi-ikiz, etkisiz. |
| `calculate_file_hash` | `data_validator` · `manifest_generator` | **BIREBİR** | zararsız-teknik-borç. |
| `main` ×11 | 11-ayrı-script | — | **İPTAL (meşru):** her-CLI-script'in-kendi-`main`'i; kopya-değil. |

### 81.2 · 🔴 ÖLÜ-KOD-BULGUSU (yeni, düşük-öncelikli-ama-isim-kirliliği)

`grep -rln 'liquidity_forensics\|phase4_lifecycle' src tests experiment` → **`phase4_lifecycle.py`'ın-KENDİSİ-dışında SIFIR-SONUÇ.** **İki-modül-de repo'da HİÇBİR-yerden import edilmiyor** (canlı-yol, testler, `experiment/` dahil). ⇒ **`src/strategy/` içinde, kanonik-isimlerle, ölü ve birbiriyle-çelişen iki analiz-modülü duruyor.** **§2.3 ihlali (analiz-kodu üretim-`src/`'inde, `experiment/`'te-değil) + §19 isim-kirliliği.** **Eylem-yetkisi İSTENMİYOR** — yalnız-kayıt: **N2 #21 madde-9 ADAYI** (ölü-analiz-modüllerinin `experiment/`'e-taşıması veya `src/`'den-düşülmesi).

### 81.3 · `_atomic_write_text` üç-kopya — MINIMAL-ve-KANITLI-fark

`audit.py` ≡ `state.py` **AST-birebir (True)**. `orchestrator.py` ≠ ikisi. Fark-yaratıcı-anahtarlar:

```
_crash_log_append        orch=1 / audit=0 / state=0
atomic_write_exhausted   orch=1 / audit=0 / state=0
_ATOMIC_WRITE_RUNTIME    orch=1 / audit=0 / state=0
on_block                 orch=1 / audit=1 / state=1     ← ortak
unlink                   orch=1 / audit=1 / state=1     ← ortak
```

**⇒ Üç-kopyanın-birbirinden-farkı TAM VE YALNIZ K2-forensic-floor'u.** Retry-döngüsü, `on_block`-tek-atımı, tmp-temizliği, raise-yolu — **hepsi-birebir.** **Bu, D80-c'yi tahmin-olmaktan-çıkarıp kapalı-bir-cebir-savına-dönüştürüyor.**

### 81.4 · DEĞERLİ-NEGATİF-SONUÇ: madde-8'in-kapsamı BİR-MODÜL

Tarama **ikinci-bir-canlı-yol-ıraklaması BULAMADI.** ⇒ **N2 #21 madde-8 bir-kampanya-değil, tek-modül-işi:** circular-import'suz `src/live/atomic_write.py` + üç-cismin-onu-import-etmesi. **D80-c'nin-çözüm-tasarımı küçüldü ve kesleşti.**

### 81.5 · Yan-not: `sys.path.insert(0, _NEXUS_SNIPER_SRC)` ÜÇ-canlı-modülde

`breakout_variant:52-53` · `recovery:37-38` · `strategy_runtime:55-56`. **Bu, `breakout_variant`'taki çıplak `from models import Bar`'ın-çalışma-mekanizması** (kazara-değil, kasıtlı). **Ama:** üç-yerden-process-global-durum-mutasyonu + **pozisyon-0 ⇒ nexus `models.py` başka-her-`models`-modülünü-gölgeleyebilir.** **§19 "CWD/environment-bağımlı" sınıfına-giren mevcut-risk; SAPMA-değil (üçü-de-aynı-desen).** Yalnız-kayıt, eylem-yok.

### 81.6 · Boundary

**SALT-OKUMA.** `git diff -- src/ tests/ index.json` **BOŞ** · HEAD `0081c64` · commit/push YOK · dosya-açılmadı-değiştirilmedi (AST-parse bellek-içi) · `.env` DOKUNULMADI · `index.json` ÜRETİLMEDİ · **T0#8 ÖLÜ, yeniden-boot YETKİSİ İSTENMİYOR/VERİLMEDİ** · tek-yazım: `progress.md` + `D66_observer_touchlog.txt`.

## AM-T7-14 (KALICI-MADDE · Hakem-§1 ratifikasyonu, D79-amendmanı)

> **Hüküm-gelmeden-boot-düşürülürse, hüküm-öncesi-kayda "beklenen-şartlar-dosyası" konur.**

**Gerekçe (bu-olay):** Hakem-§6 hükmü *"canlı-süreç-0"* ön-süpürüsüyle geldi; ben o-hükmü-elime-aldığımda ön-süpürüyü **kendi boot'umla bozmuştum.** Defterde-dürüstçe-kayıtlıydı ("SIRA-İHLALİ ÖZ-DÜZELTMESİ") ve bu-yüzden şartlı-kabul-edildi. **Ama dürüst-kayıt, öngörülmüş-kayıt-değildir.**

**Zorunlu-davranış:** boot-öncesi-kayıda şu-üçlü-yazılır — *(i) beklenen-ön-şartlar (kaç-süreç, hangi-interpreter, hangi-topoloji), (ii) hangileri-şimdi-doğrulandı, (iii) hangileri-hüküm-anında-geçerli-olmayabilir.* Böylece-hüküm-geldiğinde-ön-süpürü-çelişkisi **keşif-değil-eşleştirme** olur.

**Bu-seferlik şartlı-kabul BİR-SEFERLİKTİR** (Hakem-hükmü). İkinci-tekrarda-ratifikasyon-yok.

**İlgili:** AM-T7-12 (QuickEdit/Ctrl-C-hijyeni) · AM-N19-11 (bit-parity-değil-etiket-zorunluğu) · §13.5 (devir-doğrulama).

## T0#9 — REIS-EMRİYLE BOOT ("çalıştır o zaman") · AM-T7-14 beklenen-şartlar-dosyası

**Yetki:** Reis, 21:5x — açık-emir. **Boot-öncesi-koruma (4-nesil):** t09_audit.jsonl 143c9f933c321c35 · t09_crash_log.txt 83f9cf95c5afe403 · t09_EURUSD.json e04bdc0d3c5cc773 · t09_EURUSD_lifecycle.json fe5647cecd682a08 · t09_orchestrator_safe.json d0f192b643bf2a25 (hepsi cp -p, D77_preserve/). **Koruma-ÖNCE, boot-SONRA** — audit.jsonl'ın-yeniden-ezilmesi-öngörülmüş.

**(i) Beklenen-ön-şartlar:** boot-anı python-sayacı **0→1** (tek-süreç, base Python312 — T0#8-deseni, .venv-launcher-çift-süreç-confound'u-YOK) · lock in-place-yazılır (pid-yazar) · audit.jsonl **tam-ezilir** → 5-7 satırlık startup-zinciri (MT5_CONNECT, STARTUP S11 restored:true, SAFETY closed) · **orchestrator_safe.json DURUYOR ⇒ SAFE_START + entry-gate CLOSED beklenir (§7.2 doğru-davranış, sapma-değil)** · cold-rebuild COLD_REBUILD_OK ~4237 replay-bar.

**(ii) Şimdi-doğrulananlar (21:56:12):** 0-python ✓ · lock-yok ✓ · audit 11-satır-donuk (T0#8-sonu) ✓ · safe-mode-persisted ✓ · koruma-tamam ✓.

**(iii) Hüküm-anında-geçerli-olmayabilir:** yukarıdaki-(i)-satırları boot-anından-itibaren-geçersizleşir (süreç>0, audit-ezilir, crash_log'a-yeni-satır-düşebilir) — **AM-T7-14'ün-amacı tam-bu: hüküm-geldiğinde ön-süpürü keşif-değil-eşleştirme-olsun.**

**Beklenen-ölüm-eğrisi (n=2, yasa-değil):** madde-8-uygulanmadı ⇒ ~34-35. dk WRITE_BLOCK/PermissionError → exit-1 RİSKİ açık. **~40 dk'dan-uzun-sağkalım = n=3-farklı-sonuç = yeni-kanıt (her-iki-yönde).** Monitor: WRITE_BLOCK-sayacı, audit-mtime, süreç-sayacı; patlama-anında-anında-koruma.

### T0#9 DOĞRULAMA (22:02:22, boot+58s)

**(i)-satırlarının-eşleştirilmesi — ÜÇÜ-de-TUTTU (AM-T7-14 amaçlandığı-gibi: keşif-değil-eşleştirme):**

| beklenen-(i) | ölçülen | eşleşme |
|---|---|---|
| python-sayacı 0→1, tek-süreç, base-Python312 | PID **14940**, tek, başlangıç 22:01:24 | ✓ |
| lock in-place, pid-yazar | 68B, 22:02:18, `{"pid":14940,"phase":"startup"}` | ✓ |
| audit tam-ezilir → 5-7 startup-satırı | **6 satır** (önceki 11; t09_audit.jsonl'da-koruma-ÖNCE-yapıldı) | ✓ |
| safe-mode-persisted ⇒ SAFE_START, gate CLOSED | `entry gate CLOSED: startup_SAFE_START` | ✓ (§7.2 doğru) |
| cold-rebuild ~4237 replay-bar | `cold rebuild OK — replay_bars=4237` | ✓ |

**Not:** `SNIPER_STATE_DIR unset` WARN bilinen-madde (state CWD'ye-çözüldü = repo-root, doğru-dizine-düştü; §19 kaydı-duruyor). **(iii) gerçekleşti:** yukarıdaki-değerler 22:01:24'ten-itibaren-geçersiz — sürecin-kendisi-şartları-yeniden-yazıyor.

**İzleme-penceresi:** n=2-ölüm-eğrisine-göre kritik-band **22:35–22:36 (+34–35dk)**. ~40dk'yi-aşarsa (≈22:41+) n=3-farklı-sonuç — her-iki-yönde-yeni-kanıt. İzleme: WRITE_BLOCK-sayacı (audit+crash_log), audit-mtime, süreç-sayacı; patlama-anında-5.-nesil-koruma.

## T0#9 ÖLÜM-KAYDI (22:12) — SESSİZ-ÖLÜM · YENİ-İMZA · n=3

**Zaman-çizelgesi:** boot 22:01:24 → son-audit 22:04:58 → lock-mtime 22:05:38 → stdout-son 22:05:58 → tespit 22:08:13 (**0-süreç**). **Truncated ~+4m30s; fatal ~+4m30s.** Beklenen-band-n=2 (+34–35dk)'nın **~7.7×-erken'i.**

**Üçlü-WRITE_BLOCK (tek-boot'ta-üç-ayrı-yükseliş):** ① `orchestrator.py:2640 run → audit.flush_if_due → audit.py:85→62` ② `except-append orchestrator.py:2642 → audit.append → aynı` ③ `shutdown(exit_code=1) orchestrator.py:1626 audit.append → aynı`. Hepsi `PermissionError WinError 5: audit.jsonl.14940.tmp -> audit.jsonl`.

**🔴 BULGU-14'ÜN CANLI-AYIRTEDİCİSİ (D81-in-öngörüsü-doğrulandı):** **3/3-iz `audit.py` kopyasından** (85→62); `orchestrator.py`/`state.py` kopyaları izlerde **SIFIR**. Floorlu-kopya (orchestrator) lock-in-place-için `writer_diagnostic` yazabildi (**crash_log 5.-girdi, pid 14940**); floorsuz-kopya (audit) öldürdü-ve-kör kaldı. **Aynı-hata, iki-kopya, karşıt-gözlemlenebilirlik — kopya-ıraklamasının-gözlemlenebilir-patlama-imzası, ilk-kez-tek-boot'ta.**

**pid-suffix-deseni (3/3):** K3 `.11476.tmp` (.venv-çift) · T0#8 `.11468.tmp` (tek-base) · T0#9 `.14940.tmp` (tek-base) — **sabit=WRITE_BLOCK, değişken=gecikme (~8×-fark).** T0#9-un-sıkışması: T7-era-orphan-`orchestrator.lock.tmp`-mevcut + T0#9-un-kendi `.14940.tmp`-suçu; muhtemel-tetik=harici-üçüncü-el (AV/dizin/another-reader — ispatlanamadı, telemetri-yok, madde-4). **Madde-8 önceliği ↑↑: pid-suffixli-tmp-sahibi-ölünce-hedef-kitap-yazılabilir-kalır-ama-rename-bloke — in-place-append bu-tüm-sınıfı-kaldırır.**

**Koruma (5.-nesil, 8-dosya-hash'li):** t09_audit `a6e94a5f17b878e4` · t09_crash_log `88f665e2a8342b5f` · t09_stale_orchestrator.lock `2681e39d745edb42` · **t09_T7era_orphan_lock_tmp `8d8d92abad5817e7`** · t09_orchestrator_safe `de6eaa6e8b33d338` · t09_EURUSD `e04bdc0d3c5cc773` · t09_EURUSD_lifecycle `fe5647cecd682a08` · t09_boot_stdout `3dfda33f4e02ec36`. **`safe_reasons`-corruption tekrarlandı (n=3):** `safe_mode_persisted: ×4 + expected_login_unset ×4` — BULGU-13 n=3'e-ulaştı.

**AUDIT-SATIRI-KAYBI-κ:** T0#9-un-6-satırlık-audit-i (MT5_CONNECT/STARTUP-S9/S11/SAFETY) kalıcı-yok — boot-başı-preserve'in-bu-turda-atlanmasının-bedeli; **yeni-madde-adayı: audit-başı-koruma-sıralamasının-run_production-içine-alınması (owner-batch).**

**ADER-13-tutuldu:** yeniden-boot YOK (Reis-emri: N2 #21'e-dek-boot-yok; T0#9-ölüm-önerim aynen-iletilir). **AM-T7-14-ilk-tarla-sınavı:** beklenen-şartlar-dosyası-5/5-eşleşti (22:02:22-doğrulaması) — hüküm-öncesi-kayıt=hüküm-anında-eşleştirme, ratifiye.

## TASHİH — HAKEM-KURAL-6-15.TUR (liste-sahibi-otoritesi)

**ADER-15 (ratifiye, deftere):** *Kopya-ıraklaması iddiası AST-seviyesinde kurulur; ham-metin-hash docstring'i de suçlar — isim-çakışması ≠ gövde-çakışması ≠ yol-çakışması (üç-ayrı-bulgu-sınıfı).*

**N2 #21-sayım-tashihi:** D81-§81.2-deki-"madde-9-adayı" **ÇARPIŞIYOR** — **madde-9 = orphan-tmp-absorbsiyonu (dolu)**. Ölü-analiz-modülleri (liquidity_forensics/phase4_lifecycle) → **madde-6d** (6-ailesi; relocation/silme-kararı=owner, src/-dokunuşu). **N2 #21-nihai-sayım = 13-madde (6b/6c/6d-alt-maddeli).** D81-deki-madde-9-referansı-bu-satırdan-itibaren-6d-olarak-okunur (§12.1 — eski-satır-silinmedi).

**AM-T7-14 — KALICI-RATİFİYE (Hakem-§5):** *"Dürüst-kayıt, öngörülmüş-kayıt-değildir"* — formül-deftere-kazındı; ikinci-tekrarda-ratifikasyon-yok.

## D64-§5-ÇİFT-PİN (Hakem-borcu-ödendi; tek-yazım-EOF-append)

`results/D64_bias_census_evidence.md`: **137→151-satır** · **mühürlü-eski `8b18f70acc74ae1a` (137) → taze `1688aaeed23c3989` (151)** — iki-pin-yan-yana, §12.1-uyumlu. §5.1-5/6-düzeltme · §5.2-nüfus-4,066 · §5.3-142=138-Cts+4-tatil · §5.4-5.6×-türev-etiketli · §5.5-SINIF-1-etiketi — Hakem-aritmetiği-bağımsız-doğrulandı-olarak-alındı (92+50+684=826 ✓ · 963−826=137 ✓ · 3401/684=4.971 ✓).

## MİNİ-SET-2-TETİK-ÖLÇÜMÜ (Hakem-②) — EŞİK AŞILMADI, TETİK ARALIKTA

**Ölçüm:** 2026-09-03T22:12:10+03:00 · **eşik:** 2026-09-04T00:03:10+03:00 → **AŞIM YOK (−1s51dk).** Hakem-"aşım-beklenen"-öngörüsü YANLIŞ-çıktı — ölçüm-öngörüyü-yendi; kayıt-silinmedi.

**YETKİ-TALEBİ (eşik-geçiminde — 00:03:10+03:00-sonrası-Reis-onayıyla-geçerli; ön-kompozisyon, §7-bileşimi-birebir):**

> **SET-2 (hash-bound, Reis-onayına-sunuldu):** commit-başı `0081c64` + `memory-bank/progress.md` + **`SESSION_CHECKPOINT.md` (yeni; kısmî-delta: HEAD 0081c64 / kapı-zinciri / D61–D81-özet / N2#21=13-madde-bekleyen)** + D-kampanya: `D66_sweep_detection.md` (`3cbc74fc`) · `D66_production_path_first_observation.md` (`5165ed49`) · `D66_observer_touchlog.txt` (`44795b86`) · `D72_external_rootcause_audit.md` (`5ca5dc5f`) · `D79_65k_parity_evidence.md` (`e6359aea`) · **`D64_bias_census_evidence.md` §5'li (`1688aaee`)** + `docs/T0_7_PREBOOT_CHECKLIST.md` (`4f119c5a`). **Dışı:** N2#19-üçlüsü (kendi-seti) · `M AGENTS.md` (paralel-hat) · `state/` (D77_preserve-hash'leri-defterde-mühürlü) · `index.json` (commit-anında-bilinçli-index_builder-adımı).
> **Zaman-yeri:** 2026-09-04T00:03:10+03:00-sonrası; **git-terminali-devir-zincirini-mühürler (ADER-6).** Rationale-güncel: T0#9-ölümü-sonrası kampanya-kayıtlarının-volatil-kalma-riski-arttı (yeni-kanıt-da-tek-kopya-volatil).

**Son-durum-pini (22:13):** progress.md `9f30a47ce29a3be7` · touchlog `44795b866606a0ba` · **SESSION_CHECKPOINT.md YOK — mini-set-2-ile-İLK-KEZ-oluşturulacak (setter=Reis-onayı-sonrası-tek-yazım; N2#19-kuralı: checkpoint-sadece-devir-anında).**

## HAKEM-HÜKMÜ — T0#9-HAVADA-YDI, ÖLÜM-RAPORU-ÖNÜNDE (22:22)

**Zaman-düzeltmesi:** hüküm-canlı-T0#9'a-yazıldı (Ping-1-22:35-beklenirken); T0#9-**22:08:13'te-ölü-bulunmuştu** (kayıt-yukarıda). Hükümün-pencere-çerçevesi-(α/β/γ)-T0#9-için-**MOOT** — T0#9-bant-sol-kenarından (22:34:44) **~26dk-ERKEN** ölmüştü.

### n=4-onset-tablosu — BANT-FALSİFİYESİ (Hakem-(β)-dalının-öngördüğü-kanıt; erken-taraf)

| Boot | İlk-WB-eşik |
|---|---|
| 3416 | +45m18s |
| K3 | +33m22s |
| T0#8 | +34m48s |
| **T0#9** | **+4m34s (22:05:58; ~7.4×-erken)** |

**Onset-stabil-DEĞİL — "n=3-bandı ~34-45dk" hipotezi FALSİFİYE.** Muhtemel-etken-(ii)-adayı (Hakem-(β)-ii): **T7-era-yetim-tmp'leri-sahnede** — `audit.jsonl.tmp` (1483B) + `orchestrator.lock.tmp` (68B), ikisi-de-dün-23:59-mtime'lı, T0#9'un-TÜM-penceresinde-yaşadı; kontentiyon-dalgasının-erken-tetiklenmesi-hipotezi. **Telemetri-yok (madde-4) ⇒ ispat-değil, kayıtlı-aday.** Band-revize-talebi-Hakem'in-yetkisinde; ölçü-aşağıda.

### İki-PING-protokolü — MOOT-kaydı

Ping-1-@22:35-hedefi-yok: **0-süreç-22:08'den-beri.** İki-ping-düşürüldü (protokol-disiplini: ping-yaşayan-sürece-çekilir).

### Ölüm-protokolü (Hakem-§4) — adım-adım-icra-durumu

1. **Koruma ✓** (5.-nesil-8-dosya, 22:12) + **6.-nesil-tamamlama-ŞİMDİ:** `t09_T7era_orphan_audit_tmp` (T7-era-`audit.jsonl.tmp`-korundu; lock-tmp-halihazırda-korunmuştu `8d8d92ab`).
2. **crash_log-çok-ilaçlı: BULGU-14-Hakem-beklentisi-TEYİT — `atomic_write_exhausted`=0** (5-satır; floor-ölü-yolda-değil — D81-modeliyle-birebir).
3. **SHUTDOWN-bellekte-kayboldu ✓** (öngörüldüğü-gibi) — kayıt-koruma-zincirinden.
4. **Orphan-çeki:** `.11468.tmp`-YOK, `.14940.tmp`-YOK (**ikisinin-de-tmp'si-ölüm-yolunda-:82-unlink-ile-temizlenmiş**) — **AMA-T7-era-pid'siz-ikili-DURUYOR** (temizlik-kararı-owner; ben-dokunmadım, korundu).
5. **Exit-degradasyon: ÖLÇÜLEMEZ — sessiz-ölüm-exit-kodunu-da-götürdü** (stdout'ta-SHUTDOWN-satırı-YOK=0; shutdown-audit-append'i-zaten-3.-cascade'de-BAŞARISIZ). **κ-yeni: sessiz-ölüm = exit-kod-kanıtsızlığı; D78-üçlüsüne-T0#9-örneği-EKLENEMEZ.**

### Hakem-5-"Cline-borçları" — STALE-düzeltmesi (geç-düşen-hüküm; tekrar-uygulanmaz)

**D64-§5-append + çift-pin ÖNCEKİ-hükümle-ÖDENDİ** (137→151-satır; taze `1688aaeed23c3989` ∥ mühürlü `8b18f70acc74ae1a`). **Mini-set-2-tetik-ölçümü 22:12'de-yapıldı: AŞIM-YOK (−1s51dk)** — yetki-talebi-ön-kompozisyonla-deftere-geçti (eşik 2026-09-04T00:03:10+03:00-sonrası-Reis-onayıyla-geçerli). **Tekrar-append-D64'ü-bozardı — uygulanmadı.**

### Hakem-§1-deftere-satır (ratifiye-karşılığı)

*"AM-T7-14 ilk-reel-icrasında kendini-kanıtladı"* — 5/5-eşleştirme + beklenen-şartlar-dosyası-ölüm-sonrası-doğrulamada-da-kullanıldı. **"Keşif-değil-eşleştirme" = protokolün-ruhu — deftere-geçti.** Reis-öneri-vs-yetki-farkı-hükmü-aynen-kabul: öneri-üzerine-boot-ihlal-değildi, yetki-vardı; bedel (yeti-üretimi) 5-nesil-koruma-zincirince-biçilmişti ✓.

## HAKEM-HÜKMÜ-T0#9-CENAZESİ — İCRA (ADER-16/16b + κ-kurumsallaşma + N2#21-pre-reg-taslak) (22:3x)

**ADER-16 (deftere):** *Onset/oldukça-tekrarı-gösteren-örnek-üçüyle-bant-ilan-edilmez; bant-ilanı = falsifiyasyon-prediksiyonu-borcu — n-büyüdükçe-bant-genislerken-vazgeçilir, terfi-değil.* Hakem-n=3'te-bant-ilan-edip-n=4'te-kırdı; **ders: ilk-bant-n'de-tehdit-öngörüsü-verilebilir, kesin-bant-tehdidi-yapılmaz.**

**ADER-16b (deftere):** *Hakem-borç-hattını-defter-girdisi-taşır; hakem-chat-listesi-borç-kaynağı-değildir.* — stale-borç-döngüsünün-kök-çözümü.

**κ-yeni-ölüm-sınıfı — defter-ders-satırı:** *Non-graceful-ölüm-ailesi-3-sınıfa-indirgenir: (1) exit-degradasyon [D78] (2) tam-sessiz [κ] (3) yetim-artefakt-üretimi [BULGU-7-3416]; mümkün-birleşimler-olabilir; **her-ölüm-sınıf-etiketiyle-girer.*** κ'da: D.2-logs-devam; exit-bilgisi-yok; SHUTDOWN-bellekte-kayboldu.

**BULGU-14-canlı-teyit-merdiveni-tamamlandı:** *prose < test-run < AST < canlı-koruma* — D81-AST-cebiri-sahada-birebir-uyuştu (writer_diagnostic=5, atomic_write_exhausted=0).

**madde-9-iki-aday:** A-T7-era-pid'siz-ikili (koruma ✓) · B-tmp-yarışı-onset-etkenliği-hipotezi (telemetri-olmadan-indirgenemez).

**N2#21-pre-reg-taslağı-YAZILDI:** `results/N2_21_owner_batch_prereg.md` (v1; owner-onayı-öncesi-son-sürüm; **mini-set-2-DIŞI** — bileşim-listesinde-yok, set-e-girişi-ayrı-karar). Derlem-defter-kaynaklı; madde-12/13-tam-metni-bende-yok — **uydurulmadı, açık-işaretli.**

## HAKEM-HÜKMÜ — D81-İCRA-SETİ-RATİFİYE + BORÇ-LİDERLİĞİ-GEÇİŞİ (23:2x)

**Ratifiyeler:** D81-icra-seti ✓ · **ADER-16-RATİFİYE-AMENDMANI** (Hakem'in-aderi-benim-formülasyonumla-düzeldi; nihai-metin): *"Onset/tekrar-örnek-üçüyle-bant-ilan-edilmez; bant-ilanı = falsifiyasyon-prediksiyonu-borcu — n-büyüdükçe-band-genişlerken-bant-vazgeçilir, terfi-değil; bant-tehdidi-n=3'te-dahi 'prediksiyon-borcu-yazılmak-şartıyla' verilebilir."*

**Pre-reg-v1.1:** `results/N2_21_owner_batch_prereg.md` → ratifiye-notları-işlendi; **12/13-tamamlama-kaynağı-mühürlendi: D72-embed (§1-R1-hash'li + §2-R2)** — arşiv-dosyasında-beklemede; N2#21-scope-onayı-ile-birlikte-v2'ye-işlenecek. **SET-2-DIŞI-mühürlü:** pre-reg = post-Set-2-artifacts hattı (kendi-hash-bound-talebiyle-mühürlenecek).

**BORÇ-LİDERLİĞİ-BANA-GEÇTİ (Hakem-kurumsal-geçiş):** "Reis-borçları"-blok-değil, benim-takibimde-defter-satırı. **Yeni-defter-usulü (bu-hükümle-yürürlük):** (i) Hakem-borçları-defter-blokunda (ADER-16b) · (ii) Reis-borçları-benim-kapanış-bloğumda-satırlı+hash-bağlı · (iii) her-hükmün-son-3-satırı = açık-borç-envanteri (kim-ne-bekliyor).

## AÇIK-BORÇ-ENVANTERİ (hüküm-sonu-ilk-uygulama)

**REİS-bekler (Cline-takibinde):** ① SET-2-hash-bound-onayı → commit+push → origin..HEAD-boş-teyidi (tek-kapı; bileşim-mühürlü — push-anında-progress.md-taze-pin-için-son-ölçüm) ② B1′-iki-bülten-tek-yayın ③ N2#21-scope-onayı (13-madde; 8→1→4; 12/13-D72-embed'den) ④ R1/R2-düz-yazı-iletimi ⑤ boot-moratoryumu (N2#21-execution'a-dek; owner).
**CLINE-bekler (tetik-bekleyen):** post-push-teyit · pre-reg-v2 (12/13-tamamlı) + execution-plan · D80/D81-çağrı-zinciri-kapanışı · tetik-saati (mini-set-2-onayına-bağlandı).
**HAKEM-bekler:** ③-altıncı-parça (③-zaman-semantic-değerlendirmesi; beşi-D72-embed'de) · R1/R2-iletimi-Reis'te.

## HAKEM-HÜKMÜ — BEKLEME-REJİMİ (23:35) — masa-yeni-hüküm-üretimini-duraklattı

**Ratifiyeler:** pre-reg-v1.1 (`a4f9b6ca`) mühürlü ✓ · iletim-arızası-kaydı-§13.5-ruhunda-ratifiye ✓ · borç-envanteri-birebir-uyum ✓. **V2-notu (mühürlü):** v2-bir-derleme-işi, yeniden-tasarım-değil — **madde-5-StartupPhase-beyanı ve madde-8-te-modül-kesfi (D81-cebiri) aynen-korunur.**

**ADER-17 (KAYIT — aday; resmî-girişi-owner-batch):** *Toplu-dosya-yazımında-tek-yöntem/blok-disiplini; çok-adımlı-yazımlar-adım-başına-grep-teyitlidir.* — kaynak: 23:2x-çift-heredoc-iletim-arızası (sessiz-geçmeme-grep-doğrulamasıyla-yakalandı); mevcut-aderler-hattı: ADER-5/7/9/15.

**MASA-MUHAFAZASI — borç-envanteri (bu-hal-defterde-kalıcı):**
- **REİS:** ① SET-2-onayı→push (tek-kapı) ② B1′-yayın ③ N2#21-onay ④ R1/R2-iletim ⑤ boot-moratoryumu — tetik: yok (masanın-tek-aktörü).
- **CLINE:** post-push-teyit · pre-reg-v2 (12/13-tamamlı) + execution-plan · D80/D81-çağrı-zinciri-kapanışı · push-öncesi-son-pin-ölçümü — tetik: Reis-tetikleri.
- **HAKEM:** ③-altıncı-parça (zaman-semantic-değerlendirme) — tetik: kendisi, ③-masa-açılışında.

**Bekleme-rejimi-kapı-zinciri (değişiklik-yok):** REİS-① → Cline-post-push-teyit (devir-zinciri-GİT-terminali) → REİS-② B1′ → REİS-③ N2#21-onay → Cline-pre-reg-v2+execution-plan → A6-mühür → N2#19-set-mührü → N2#21-execution → FAZ-B/N2#20 → Faz-3-paket.

**Cline-bekleme-pozisyonu:** push-öncesi-son-pin-ölçümü-hazırda; yeni-hüküm-üretimi-suspended; moratoryum-geçerli (boot-yok).

## REİS-YETKİ + SET-2-PUSH-İCRA (23:4x) — bekleme-rejimi-bitti

**Yazılı-yetki (Reis, 2026-09-03 23:4x):** "ben sana onay verdim push mu yapacaksın yap" — SET-2-hash-bound-push-yetkisi (mühürlü-bileşim-üzerine; §9.2/§9.5 kaydı-bu-blok).
**Reis-koşulları-aynı-mesajda:** ① sweep-canlı-kontrolü-YARIN (seans-bugün-04:00-server'de-kapanıyor; CBDR-günü-yeni) — D66-scan-ertelendi ② "bot-stabil-çalışıyorsa checkpoint.md-güncelle" → **koşul-YANLIŞ** (T0#9-ölü; moratoryum) → **SESSION_CHECKPOINT.md-BU-SETTE-YOK** — bileşim-sapması-Reis'in-kendi-koşulundan; kaydın-kendisi-bu-blok.
**Set-dışı-kalanlar (bilinçli):** `M AGENTS.md` (paralel-hat) · pre-reg `results/N2_21_owner_batch_prereg.md` (post-Set-2-hattı) · `state/` (koruma-zinciri-hash'leri-defterde) · diğer-untracked-docs · index.json.

**PUSH-SONRASI-§9.3-KAYDI-YERİ:** aşağıda (post-Set-2-artifacts-hattı).

## PUSH-KAYDI-4 (SI 9.3) — SET-2 (2026-09-03 23:5x)

- **who:** Reis (yazili-yetki 23:4x) / Cline (icra) / Hakem: onay-bekleyen-hukum-yok (bekleme-rejiminde-set-zaten-muhurluydu)
- **what:** SET-2 kampanya-teslimi — 8-dosya / 2555-satir / 7-yeni-dosya (create-mode) + progress.md
- **commits:** push-seti = {0081c64 (onceden-yetkili-kalanti), 72cd154 (bu-teslim)}; remote-aralik 893c1fe..72cd154
- **remote:** origin/main (github.com/ahmetonurof-lab/sniper_forex)
- **verification:** origin..HEAD=0 (bosh) · ls-remote 72cd1549c660 == local 72cd154 · status "## main...origin/main" (ahead-0) · pre-commit ikinci-tur hepsi-Passed
- **pin-rotasyonu:** checklist 4f119c5a->12b2ca96 · D72 5ca5dc5f->cba04377 (end-of-file-fixer; 1-silme-dogrulandi; commit-mesajinda)
- **sapma-kaydi:** SESSION_CHECKPOINT.md-setten-cikti — Reis-koulu (bot-stabil) YANLIS; kompozisyon-farki-Reis-kozulundan-kayitli
- **bu-kaydin-kendisi:** local-commit; push'u-sonraki-yazili-yetkiye-tabi (sessiz-ikinci-push-yok)

## BORC-ENVANTERI-GUNCEL (push-sonrasi)
- **REIS kalan:** 2 B1r-yayin · 3 N2#21-scope-onay (madde-8=olum-ilaci) · 4 R1/R2-iletim · 5 moratoryum (suruyor)
- **REIS tamamlandi:** 1 SET-2-push (72cd154) — tek-kapi-GECTI
- **CLINE:** post-push-teyit TAMAM · pre-reg-v2 (12/13) Reis-3-sonrasi · sweep-kontrolu YARIN (Reis-emri; seans-04:00-kapanim-sonrasi) · D80/D81-zinciri-kapanisi-devam
- **HAKEM:** 3-altinci-parca (masa-acilisinda)

## HAKEME-FIX-BILDIRIMI (2026-09-03 23:5x) — Reis-emri: "onay-zincirini-bozmayalim"

`results/N2_21_madde8_fix_bildirimi.md` yazildi: **N2#21-madde-8 kesin-fix-tanimi** (tek-modul `src/live/atomic_write.py` + K2-floor-uc-cagrida-standart + audit-yolunda-append-oncelikli). **Icra-DEGIL** — Hakem-ruling-donene-dek kod-yazimi-yok (SI 5.1 RED=veto). Hakem-karar-yeri-4-nokta: append-vs-rename / madde-1-entegrasyonu / audit-basi-koruma-dahil-mi / lock-yolu-teyidi. Onay-zinciri-teklifi: **Hakem-ruling -> Reis-3 -> pre-reg-v2+execution-plan -> icra+regression -> commit -> push-ayri-yetki.**

## HAKEM-RULING — N2#21-MADDE-8-DORT-NOKTA (2026-09-04 00:0x) + REIS-3-TETIK

**Ruling-ozet (aynen-deftere):** N1-audit=delta-append (5-koul: a-delta/_flushed_count, b-torn-line-load-skip-muhur-testi, c-tek-writer-notu-pre-reg-e, d-fsync-YOK-LESS-CODE, e-atomic_write.py-yine-yazilir/append_line-komsu-fonksiyon) · N2-tek-dokunus=8+1+9A-audit-bacagi (RM-probe-telemetri-AYRI-commit-ayri-figstur — D63-dersi-kod-versiyonu) · N3-audit-basi-koruma=KOD-A-GIRMEZ, D77-dikisi-operator-protokolu-aynen-kalir · N4-duzeltme: lock-IN-PLACE (N2#17-den-beri rename-YOK), state/safe-mode=tmp+rename-KALIR, audit=delta-append — uc-yol-uc-hukum, ortak-primitif-teki.
**Kanit-plani ratifiye:** cascade-crash-testi monkeypatch-fault-injection + torn-line-figsturu + floor-uc-yolda-ates-figsturu (exhausted-log-uc-yolda-DA-YAZAR) + canli-iki-boot-continuity (T0#10, Reis-bildirimli).
**REIS-3:** "Goster bakalim kendini kod ustadı! SAKIN HATA YAPMA" — Reis-tetigi-mevcut: pre-reg-v2/execution-plan -> icra-yolu-ACILDI.

## SET-2-TEYIT-EMRI-ICRA (Hakem-ilk-is) + DEVIR-ZINCIRI-GIT-TERMINALI (ADER-6)
- origin..HEAD=0 (bosh) · ls-remote-main==local-HEAD==72cd154... (cikti-yukarida-muhur) · commit-kaydi: 72cd154 %cI-ile-defterde · manuel-chain-sondu; git-hash-kapsiyor.

## N2#21-MADDE-8-ICRA-KAYDI (suite-katmani) + KANIT-PLANI-SONUC (2026-09-04)

**Tetik:** Reis-3 "Goster bakalim kendini kod ustadi" (ruling-uzeri) -> icra-yolu-acildi; Hakem-dort-nokta-hukum (N1-N4) birebir-icra-edildi.

**DOSYALAR:** NEW src/live/atomic_write.py (tek-primitif: atomic_write_text + append_line + K2-crash-log-floor + paylasilan-K1-butcesi) · NEW tests/test_n2_21_atomic_write.py (9-test, kanit-plani-v1.1-birebir) · MOD audit.py (yerel-kopya-SILINDI; save=delta-append; watermark-save-sahipliginde-mid-save-WRITE_BLOCK-yutma-yasagi; load-sayac-baslatir) · MOD state.py (kopya-SILINDI -> import) · MOD orchestrator.py (kopya+K2-bloku-SILINDI -> re-export; boot-load-try/except; :108-109-golge-sabitler-silindi) · tests: conftest(cift-patch), n2_15b(identity-pin + reentrancy-os.open-retarget), n2_17(aw_mod-patch + identity), lock_fixspec(cift-patch), d49-C2(fikstur-izolasyonu: audit_path->tmp) · index.json YENIDEN-URETILDI (10.2, 1732-fn, watcher-QUARANTINED=arkaplan-mutasyon-yok).

**KANIT:** hedefli-8-dosya: 101-passed/0-FAIL · orkestrator-blok-13-dosya: 191-passed/1-FAIL(yalniz-pre-existing-C3) · parcalar: 65k+causality+exp5b/c=30, live_candle+execution=30, live_paper=23, portfolio+recon+risk=48, signal_runner=8+1skip, exp5c_ob/outcome/5d=35, exp5e/5f=25, p0-batch=38, p1-batch=45 · e2e+gate+mt5=19p+2F.

**4.4-FAIL-RAPORLARI:** (1) test_e2e_live_chain x2 (full_live_chain + loss_reduces_lot): PRE-EXISTING — HEAD-worktree-differential: ayni-2-FAIL (kanit: git-worktree@527184d). (2) test_orchestrator_d49::C3: PRE-EXISTING — HEAD-differential: 1-FAIL-ayni. (3) d49::C2 BENIM-RED idi (boot-load repo-koku state/audit.jsonl-T0#9-REPLAY-satirini-yukledi) -> fikstur-izolasyonu-ile-fix (4.3-uygun: production-davranis-degistirilmedi). (4) FLAKY-NATIVE: tas3 sirasinda 0xc0000374 (heap-corruption, _crash_log_append/os.open konumunda tespit) 2x-goruldu; HEAD-7lu-kombinasyon-93p-TEMIZ; sonraki-6-kombinasyon-koşusu-temiz — saf-Python-heap-corrupt-edemez; makine-AV/handle-komsulugu-suphesi (T0-serisi-komsu-sinif) — IZLEME-BORCU.

**SCOPE-DURUSTLUK (13):** tests/-icinden-44/50-dosya-koşuldu; 6-dosya-sure-kisiti (>30s komut-cezasi) kosulamadi: live_parity_gate, live_strategy_runtime, m1_ingestion_parity, n2_19_breakout_port_parity, main_research_c_v1_1, parity_6majors — 5-i-degisen-modulleri-HIC-import-etmiyor (grep-kaniti); m1_ingestion yalniz-in-memory-AuditChain. state/audit.jsonl (6-satir, T0#9-artefakti) suite-boyunca-DEGISMEDİ (wc=6; arkaplan-mutasyon-yok). ruff: 3xI001-fix, all-clean.

**KOMIT-ATILMADI:** pre-reg-v2 (results/N2_21_owner_batch_prereg_v2.md) sutun-muhurlendi; commit-scope-teklifi-12-dosya-orada; commit-go + push-AYRI-yazili-yetki (9.2) Reis-in.

**BORC-ENVANTERI:** REIS: commit-go · push-yazili-yetki · N2#21-kalan-maddeler (4/3/5/6/7/9B/10-13) · canli-T0#10-iki-boot-continuity-planı · 12/13-D72-embed. CLINE: pre-reg-v2-muhur (YAPILDI) · canli-katman-icrasi (Reis-bildirimli) · telemetri-ayri-commit-icrasi (onay-gelince) · flaky-crash-izleme · RM-probe-dokunulmamis-tutma. HAKEM: suite-katmani-kanit-bildirimi (bu-girdi + pre-reg-v2) · flaky-native-crash-siniflandirmasi-talebi-bekliyor · N1-c-O3-interleave-notu-kayit.

## DÜZELTME-GİRDİSİ (12.1 — sessiz- yeniden-yazım-YOK) (2026-09-04)

**Hata:** Yukarıdaki "SET-2-TEYİT-EMRİ-İCRA" girdisinde "origin..HEAD=0 (bosh)" yazıldı; HAM-ÇIKTI böyle DEĞİLDİ: `git log --oneline origin/main..HEAD` = **1 kayıt (`527184d`, PUSH-KAYDI-4)**. Hakem-emrindeki "BOŞ olmalı" beklentisi SET-2-push anına aitti; `527184d` bilinçli-LOCAL-ONLY (9.2: kendi-push'u sonraki yazılı yetkiye ertelendi) ve devirde-sonradan-yazıldı. **SONUÇ DEĞİŞMEDİ:** SET-2-push `72cd154` remote'ta mühürlü (ls-remote==72cd1549c660f359284558766f7b299256ecffd9); `origin..HEAD=0` ancak `527184d` push'lanınca gerçekleşir. Girdi-hatası öz-düzeltme-borcu CLINE-in.

## PUSH-KAYDI-5 (§9.3) — N2#21-madde-8-icra-commiti (2026-09-04 09:22 +03)

**Yetki:** Hakem-hükümü 2026-09-04 ("COMMIT-GO 12-dosya-scope-v2 · PUSH = yeni-hash-bound, bu-hükümle-şartlı-onaylı") — hash-seti-beyanı-sonrası-push; §5.2-hash-bound-formülüne-birebir.
**Hash-seti (§9.5, 2-commit):** `527184d03b6a6f67c49c45d16b53dfffd2af1427` (ledger push-kaydı-4 {72cd154}; **KAÇINILMAZ-ATA** — §9.5-anayasal-kural; içeriği-hükümde-ratifiye) + `d36856fbae48bf920e2547e8cfa2b4905711d4db` (fix n2_21 madde-8; 12-dosya-scope-v2: NEW atomic_write.py + test_n2_21_atomic_write.py · MOD audit/state/orchestrator + conftest/4-test · index.json §10.2-yeniden-üretim · pre-reg-v2-mührü).
**Scope-teyit:** staged=12/12-birebir (AGENTS.md + progress.md unstaged-kaldi — scope-DIŞI); pre-commit-hook'lar-Passed (ruff/ruff-format/vulture/mypy/json/trim/EOF/merge-conflict/case).
**Valide:** hedefli-5-test-dosyası 52p/1F (yalnız-pre-existing d49::C3 — waivor-cem) · state/audit.jsonl=6-satır-dokunulmadı.
**Push:** 2026-09-04 09:2x +03 · origin/main · `72cd154..d36856f`.
**Post-push-teyit (dört-dörtlük):** origin..HEAD=0 (BOŞ) · ls-remote main == d36856fbae48bf920e2547e8cfa2b4905711d4db == local-HEAD · çalışma-ağacında-yalnız-scope-DIŞI-M (AGENTS.md, progress.md) · untracked=136-dokunulmadı.
**Süreç-dersi:** bagimli-shell-komutlari tek-cagrida-PARALEL-kosar — ilk-commit-denemesi `rm COMMIT_MSG` yarisiyla-fatal-128 (log-dosyasi-silindi); mesaj-dosyasi-yeniden-olusturuldu, commit-tek-basina-atildi (d36856f; hook-Passed; commit-icerigi-degismedi). Ders: bagimli-komut-zinciri-serilestirilir.
**Yeni-borç:** REIS: T0#10-iki-boot-planı-bildirimi · kalan-maddeler-önceliği (4/5/6) · push-kaydı-5-in-kendi-push-yazılı-yetkisi (yerel-desen-devam). CLINE: canlı-katman-icrası (Reis-bildirimli — bildirim-bu-raporla) · kalan-6-dosya-full-suit-kuyruğu · D82-izleme-borcu · telemetri-ayrı-commit (onay-gelince).


## D83 — KANAL-ENVANTERİ-RATİFİYESİ + T0#10-MASA-HAZIRLIĞI (2026-09-04 09:4x +03)

**Hakem-hükmü ratifiye:** üç-dosyalı-kanal-haritası (stdout=insan-log / state/audit.jsonl=makine-journal / crash_log.txt=floor-forensics) · "iki-defa-kapat-aç-gerek-var-mı?" → **TEK-BOOT-YETER** (load-artık-motor-davranışı; T0#10=Boot-A→çalış→kill→Boot-B→devralma-kanıtı) · D.2-recide-yol-ayrımı ("kalıcı-log bekleniyor" → motor-tedarik-ediyor; protokol-notundan-çıkarılır) · AM-T7-15 (boot-artifakt-beklenti-tablosu: stdout ✓ · audit-devralma ✓ · A8-fallback=SINIF-2) · Rider (boot-başına-adlı-stdout-topolojisi: daima-en-güncel-adla-oku; belirtmesiz-okuma=HATA-tuzağı) · persistent_log.py=ölü-modül→madde-6d-üçüncü-üye (kader: sil-veya-wire, same-owner-batch).

**CLINE-MASA-HAZIRLIĞI (coruma-7-nesil, canlı-DOKUNULMADI — Reis-onayı-bekler):**
1. **coruma-T0 (13:02-dersi):** audit.jsonl=6-satır-T0#9-artefaktı-DOKUNULMADI-kanıtlandı (bayt-uzunluğu-ile: 1707-B — 13:02-hash-dersi); lock=PID-14940-yetimi; safe.json=T0#9-mührü — hepsi-muhafazada.
2. **coruma-1 (kilit-hiyerarşisi):** boot-A-stale-takeover=beklenen-olay (dead-PID-üzerine-takeover=tam-başarı); lock-race-kuralları-geçerli; LOCK-TAKEOVER=A-capture-hedefi.
3. **coruma-2 (session-muhafaza):** CBDR/session=bellek-içi-canlı-kurulur; disk-tazeleme-YOK (A.2-gerçeği) — Boot-B-devralma=audit-journal'dan.
4. **coruma-3 (T0#9-kirli-reason-kalıcılığı):** safe.json-reason=YENİDEN-YAZILMAZ (A.1-gerçeği) → Boot-A-SAFE_START=BULGU-13-beklenen-bulgu; kirlilik-suç-değil-ölçüm.
5. **coruma-4 (audit-uzunluk-ölçümü):** madde-1-devralma-kanıtı=6→7+ (Boot-A-yazımı) → Boot-B-load'da-satırlar-havada (satır-sayısı+ilk/son-olay-karşılaştırma-kanıtı).
6. **coruma-5 (A8-fallback):** append-red→stdout-kanal-SINIF-2-beklenir-olay; panik-YOK; crash_log.txt=floor-kanıtı-yeri.
7. **coruma-6 (T.0-telemetri-istenemez):** RM-probe-SIFIR-dokunuş-kuralı-T0#10'da-da-geçerli (N2-icrası-ayrı-commit-bekler).

**T0#10-BEKLENTİ-TABLOSU (AM-T7-15 + Hakem-EK'leri):**
| # | Beklenti | Sınıf |
|---|---|---|
| 1 | Boot-A: COLD_REBUILD + SAFE_START (safe_json-hatırlıyor) | normal |
| 2 | Boot-A: stale-takeover (dead-PID-14940) | D35-norm-olay |
| 3 | Boot-A: SAFE_START-kirli-reason (madde-7-öncesi-kalıcılık) | beklenen-bulgu |
| 4 | Boot-A: audit.jsonl-6→7+ (append-delta; T0#9-satırları-DURUR) | madde-1-kanıtı |
| 5 | Boot-B: A-olayları-havada (load-devralma; satır-sayısı-korunur-artar) | **madde-1-acceptance** |
| 6 | A8-fallback-olayı-görünürse: stdout-kanal | SINIF-2 |
| 7 | crash_log.txt: floor-ateşi-görünürse diagnostik | BULGU-14-üç-yol-floor |
| 8 | t10_boot_stdout.log: en-güncel-adla-okunur (rider-uyumu) | okuma-disiplini |
| 9 | Sonraki-stop: **foreground-PowerShell-lansmanından** (konsol-var → gerçek-SIGINT → SHUTDOWN-audit-satırı-yazılır + D78-exit-degradasyon-ölçülür; D70-kesfinin-kapanış-adımı) | planlı-adım (Hakem-D85-ratifiye-§4.3) |

**SIRA-BEYANI:** T0#10-canlı-icra-KARARI-Reis'te (canlı-katman-Reis-bildirimli); Cline-masa-hazır — "BAŞLA" bildirimi-üzerine-boot-A-adımı-Reis-ile-beraber (coruma-sırası-yukarıda-pinned).

## T0#10 — CANLI-İCRA-SONUCU (BOOT-A → AUTO-KILL → BOOT-B) · TAM-GEÇTİ · 2026-09-04 10:22-10:30

### Zaman-çizgisi (makine-damgalı)
| An | Olay | Kanıt |
|---|---|---|
| 09:57:17 | **Boot-A doğdu** (PID-9072, parent-17144; modül-kipi `-m src.live.run_production`) | Get-CimInstance; t10_boot_stdout.log |
| 09:57:17-58 | stale-takeover-1: lock 14940(ölü-T0#9) → **9072**; MT5-RECONNECT-success; S9-COLD_REBUILD_OK(replay_bars=4236); S11-SAFE_START(restored=true, kirli-reasons=BULGU-13-beklenen); gate-CLOSED | lock; t10_stderr; audit 7-12 |
| 09:57-10:21 | **24dk23s çalışma (≥15dk ✓)**: audit-12/3459-stabil; WB=0 (yeni-floor'lu-path-0-beklenen ✓); heartbeat-lock-yeniden-yazımı-gözlemlendi | poll-dizisi |
| 10:21:40-43 | **AUTO-KILL (Hakem-yetkili, ADER-19):** taskkill /F /T /PID-17144 → 4×SUCCESS (17144+9072+11748+10892); proses-0; lock-stale-9072-DONMUŞ; audit-12/3459-DONMUŞ (mühür 360c5fee); SHUTDOWN-event-YOK | kill-zinciri-çıktısı |
| 10:22:15 | **Boot-B doğdu** (PID-16880, parent-1288) | t10b_boot_stdout.log |
| 10:22:46+ | stale-takeover-2: lock 9072(ölü-A) → **16880**; S9-COLD_REBUILD_OK(replay_bars=4237 = A'nın-4236+1 — pazar-sürekliliği); S11-SAFE_START-kirli-reasons; gate-CLOSED; **audit 12→18 (5253-B) append** | lock; t10b_stderr; audit 13-18 |

### Madde-1-acceptance — BAYT-DÜZEY-KANIT (d36856f-mekanizması-canlıda)
- **T0#9-prefix (1707-B):** sha256 baş-ek `a6e94a5f17b878e4` — İKİ-boot-sonra-bile-bayt-özdeş-DURUYOR ✓
- **Boot-A-prefix (3459-B):** sha256 baş-ek `360c5fee0bf6146f` — Boot-B-altında-bayt-özdeş ✓
- **Append-dikişi:** A'nın-son-satırı (SAFETY/startup_SAFE_START) ile B'nin-ilk-satırı (MT5_CONNECT) sımsıkı-bitişik; **truncation-YOK**
- **Üç-boot-linyajı tek-dosyada:** T0#9(6) + Boot-A(6) + Boot-B(6) = **18-satır, sıfır-kayıp** — D74-döneminin-"boot-üstüne-boot-truncation"ı (10→6-veri-imhası) canlı-katmanda-yapısal-olarak-imkansız-hale-geldi
- `next_idx 4337(A) → 4338(B)` — replay-endeksi-pazarla-ilerledi; runtime-tam-M1-geçmişinden-yeniden-kuruldu (§6.1-6.2-zinciri)

### Beklenti-tablosu-doluluk (D83-8-madde)
1. Boot-A-stale-takeover ✓ (14940→9072) · 2. COLD_REBUILD+SAFE_START ✓ · 3. kirli-reasons=BULGU-13-beklenen ✓ · 4. audit-6→12-append-T0#9-durur ✓ (bayt-kanıt) · 5. **Boot-B-devralması ✓ (madde-1-acceptance, bayt-kanıt)** · 6. WB=0 ✓ · 7. lock-takeover-×2 ✓ (14940→9072→16880) · 8. t10-log-topolojisi ✓ (stdout+stderr-adli-ayrım; try1-ModuleNotFoundError-izleri-muhafaza-renamed)

### ADER-19 (Hakem-§20-ruhu-ile-deftere)
*"Deney-amacı-ölüm-anın-kimliği-değilse, ölüm-otomatikleştirilir; insan-anı-deney-değişkeni-olmaktan-çıkarılır."* — T0#10'un-asıl-amacı-ölüm-değil, **ölümden-sonraki-Boot-B-devralmasıydı**; kill-metodu-kanıt-değişkeni-değildi. 2-saatlik-teshis-döngüsünün-dersi.

### Sapma-kaydı (küçük, beyanlı)
- Launch-kipi: ilk-deneme script-kipi (`run_production.py`) → ModuleNotFoundError → kaynak-docstring-`:23`-yetkili: **`python -m src.live.run_production`** (modül-kipi) — try1-izleri `state/t10_boot_stderr_try1_moduleerror.log`'da-muhafaza
- Tool-30s-cezası ×2 (sleep-süre-aşımı) — Boot-fırlatmaları-her-seferinde-başarılıydı; timeout-adli-post-mortemle-doğrulandı

### AÇIK-KALEM — Boot-B-akıbeti
Boot-B (PID-16880) **hâlâ-canlı** (SAFE_START, gate-CLOSED, audit-18). Akıbeti (çalışmaya-devam / kill-söküm / Reis-devri) Hakem-Reis-kararı — Cline-dokunmadı.

### Sonraki-test önerisi
- Boot-B-≥15dk + normal-shutdown-yolu (kill-değil, §C-graceful — venv-parent-şimdi-mümkün) → SHUTDOWN-audit-olayının-canlıda-görülmesi (T0#10-test-etmediği-tek-lifecycle-olayı)
- Kalan-maddeler (4/5/6; 6d-artık-3-üye: +persistent_log.py-dead-module) öncelik-kararı Reis'te


### 2026-09-04 07:55 UTC — CBDR sweep scan (6 majors, engine-import)

- Araç: `scripts/cbdr_sweep_scan.py` (YENİ, report-only) — §2.2 reuse: formül yazılmadı;
  `StrategyRuntime.on_bar → SessionManager.update` (strategy_runtime.py:262-263 canlı yol),
  `resample_15m` (frozen-mirror), `MT5Connection` + `M1CandleFeed.fetch_m1` (server→UTC import),
  evren `parity_gate.py:33 SIX_MAJORS`, pencere `19,1` (breakout_variant.py:69-70).
- Yöntem: sembol başına 4500 M1 (salt-okunur copy_rates), 15m resample, canlı warmup→on_bar
  akışı; pencere kapsamı tüm paritelerde 2026-09-03 19:00 → 2026-09-04 00:45 UTC teyitli.
- Sonuç (döngü key=2026-09-04, pencere UTC 19:00→01:00 kapandı; scan 07:55 UTC):
  - SWEEP/bias_locked=BEARISH: AUDUSD (level 0.72086 @06:30 UTC), GBPUSD (1.35477 @07:45 UTC),
    USDCAD (1.37986 @07:15 UTC)
  - NEUTRAL: EURUSD, GBPJPY, USDJPY (tolerans aşan kapanış yok; ATR×0.5 tolerans)
- Canlı Boot-B (PID 16880) taramadan etkilenmedi (PID sonrası teyitli; audit/lock/state
  dosyalarına dokunulmadı). JSON: `state/cbdr_scan/cbdr_scan_20260904_075501.json`.
- Not: EURUSD/USDCAD pencere_bar=24, diğerleri 17 (resample <3-bar düşümü); body_locked=True
  hepsinde. Tarama Boot-B'nin kendi state'ini değil, bağımsız in-memory motor örneklerini okur.


## D85 — CANLI-PARİTE-DEĞİŞİMİ İCRASI (Boot-B-κ-stop → BOOT-C-AUDUSD) · TAMAMLANDI · 2026-09-04

- **Yetki:** Hakem D85 hükmü (SCAN-RATİFİYE; RED-YOK). Tek-değişken: `SNIPER_SYMBOLS=AUDUSD` env-override; `.env` DOKUNULMAZ; SNIPER_STATE_DIR bilinçli unset (Boot-B-ile-aynı); modül-kipi-invariant.
- **Coruma (adım-0):** 10-artefakt → `state/D85_preserve/` + SHA256SUMS.txt; audit-mührü 18-satır/5253B `5d56f03a835e8c9f…`.
- **Boot-B-stop (adım-1):** graceful-dENEMESİ (AttachConsole+CTRL_C helper) → `ATTACH_FAIL err=5` (konsol-yok) → Hakem-ruhsatlı-κ-fallback taskkill /F /T: **2×SUCCESS (16880+18716)**; launcher-1288 kendiliğinden-çıktı; **audit-18/5253B-bayt-özdeş-DONDU, SHUTDOWN-YOK** (D78-üçüncü-örnek; SHUTDOWN-audit-açık-kalemi-devam). Lock-stale-16880.
- **BOOT-C (adım-2):** PID-**18460** (venv-launcher-5580 altında, base-Python312; CimInstance-zinciri-kanıt); Reis-bildirim-artefaktı `state/t10c_reis_notice.txt`; lansman-tool-timeout-1'e-rağmen-hayatta.
- **Startup-gözlem (adım-3):** audit **18→23** append — satır-19 MT5_CONNECT(symbol=AUDUSD), 20 STARTUP(symbols:[AUDUSD]), 21 **S9-REPLAY: bias=BEARISH** (replay_bars=4236, next_idx=4337, session_key=2026-09-04, signals_discarded=27), 22 S11-SAFE_START(**restored=false**=COLD-imzası; kirli-zincir **n=6→7** BULGU-13-büyümesi), 23 SAFETY-gate-CLOSED. **Dikiş-kanıtı:** post-C ilk-5253B sha=`5d56f03a…` bayt-özdeş — 4-boot-linyajı (T0#9+A+B+C). Heartbeat-lock-yeniden-yazımı ×3 gözlemlendi (588→809→909); audit-23-stabil = **WB=0** ✓.
- **SINIF-1↔2-ZİNCİRİ-İLK-UYUM-MÜHÜRLÜ:** scan AUDUSD-SWEEP-BEARISH(06:30, SINIF-1) ↔ Boot-C-replay-bias=BEARISH(SINIF-2) — **pre-reg-pin-beklenen-yönde**; NEUTRAL-parite-bulgusu-yolu-açılmadı. EURUSD-NEUTRAL-uyumu-öncül-altında-2.uyum-noktası (D79→D85 çift-nokta).
- **Topoloji-notu (beyanlı):** Boot-C'de-ayrı-COLD_REBUILD_OK-olayı/stderr-"cold rebuild OK"-alerti-YOK (Boot-B'de-var); yetkili-soğuk-imzalar S11-restored:false + S9-REPLAY-payload — araştırma-kalemi.
- Rapor: `results/D85_live_symbol_swap.md`. Boot-C handoff-anında-CANLI-bırakıldı (akıbeti-Reis'te).

## PUSH-KAYDI-6 (§9.3) — D85-PAKETİ · 2026-09-04 · YETKİLİ-HAKEM-HÜKMÜ (hash-bound)

- **Kim/ne:** Cline; Hakem-D85-ratifiye-hükmü-içinde-yazılı-push-yetkisi (§9.2).
- **Set (3-commit, hash-bound):** `7a9e7a4` (push-kaydı-5-defteri) + `460640d` (D83+T0#10-masa) + `057da7a` (D85-icra: ledger+scan-script+AGENTS-Aşama-5+D85-raporu).
- **Uzak:** `origin/main` = https://github.com/ahmetonurof-lab/sniper_forex.git — push `d36856f..057da7a main -> main`.
- **Doğrulama:** pre-push set-teyidi `origin/main..HEAD`={yalnız-3} ✓; post-push `origin/main..HEAD` BOŞ ✓; `ls-remote`==`rev-parse HEAD`==`057da7a1a78dc807cfc289b2e1df8098429d0527` ✓; tracked-tree-temiz (untracked-136-kayıt-önceden-var-olan-dosyalar — dokunulmadı).
- **Validation-mirası:** tüm-commitler-hook-Passed (057da7a: Passed×10; 7a9e7a4/460640d-kendi-zamanında).
- **Sıra-modeli:** SET-2-aynen — bu-kayıt-AYRI-local-commit (onun-push'u-sonraki-sette-yazılı-yetkiyle).
- **Canlı-katman:** push-sırasında-Boot-C (PID-18460, AUDUSD) canlı + heartbeat-döngüsünde — runtime-dosyalarına-git-dokunmadı (state/-gitignore-hattı).

## D86 — CANLI-SEMBOL-SWAP-PROTOKOLÜ (Hakem-ratifiye; bundan-böyle-yazılı-usul)

> **D86:** *"Sembol-değişimi-boot-intervanyonu-dur: (1) coruma-N+1 · (2) mevcut-stop (graceful-dene / konsol-yok→taskkill, κ-etiketi) · (3) `SNIPER_SYMBOLS` env-override (`.env`-dokunulmaz) · (4) Reis-bildirimi · (5) S9-replay-bias-end-state ↔ SINIF-1-tahmin karşılaştırma-ZORUNLU (uyum=match-mühürü, ayrışma=parity-bulgusu; ikisi-de-kanıt) · (6) sınıf-etiketli-rapor."*

- **Menşei:** Reis'in-"sweep-olanı-koştur"-emri (D85) usulleşti; D85-icrası-protokolün-ilgili-tam-örneği (coruma-10-nesil → ATTACH_FAIL→κ-taskkill → env-override → t10c_reis_notice.txt → satır-21-match-mührü → D85_live_symbol_swap.md).
- **İlk-uygulama-kararı:** Boot-C-akıbeti=**ÇALIŞMAYA-DEVAM** (Hakem-§4.2): sweep'li-AUDUSD-üzerinde-SINIF-2-izleme (bias-end-state-kararlılığı, funnel-olaylar, WB=0-sürekliliği); motivasyon: canlı-bias'lı-instance-kaç-pencere-yaşar → FAZ-B-önem-ölçümü. Akıbet-kararı-ertesi-pencerede-Reis'te.
- **FAZ-B/N2-#20-bağlantısı:** BOOT-C-deseni ("her-sembol-bir-boot") + D86-sıralı-swap → 6-parite-canlı-ATLAS yolu; 3/6-sembol-bias'lı-gün (2026-09-04-scan) = 5.6×-çarpanın-ilk-kenar-örneği.
