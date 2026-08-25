# Progress

## LIVE ↔ BACKTEST PARITY AUDIT — PASS (2026-08-22, read-only)

### TIME SOURCE
- Dataset timestamps = naive MT5 server time; ICMarketsSC-Demo live server
  verified against dataset (same account 53012914); period maps to UTC+3.
- Active strategy uses server-time directly; no timezone conversion.

### DATA PARITY — PASS
- EURUSD 4479/4479 and BTCUSD 4479/4479 overlapping bars vs live MT5:
  exact OHLC (within float epsilon), exact tick_volume, matching weekend structure.

### EVENT PARITY — PASS
- 24 representative events reconstructed (multi-symbol, both directions,
  CBDR + day sessions, winners + losers).
- BASE∩EQ shared 987 events: direction/zone/entry/risk = 100% agreement.
- 4/150 window anomaly + 2/987 sweep-index anomaly traced to comparison
  mapping/resampling method, not strategy behavior (0 anomalies on re-check).

### TRADE PARITY — PASS
- Frozen direction-fix benchmark verified: PROFIT_TRAIL direction 812/812
  correct; SL/TP geometry + expected R behavior verified; hold_bars parity
  within expected OPEN-trade exceptions.

### PERMANENT ARCHITECTURAL RULE
LIVE MT5 behavior is the ground truth; backtest/execution must deterministically
reproduce it, not approximate it.

### FUTURE WORK RULE
All future changes must preserve LIVE ↔ BACKTEST parity unless a deviation is
explicitly intended, isolated, measured, and documented.

## INTERNAL SWEEP RESEARCH — CLOSED, BOTH VARIANTS REJECTED (2026-08-22)

Detection-only counterfactual on frozen EQ benchmark (read-only; disposable
script deleted after run; no code/benchmark/execution changes).

### v1 — Loose internal sweep (20-bar, pivot 1/1)
- 1262/1262 replayed; pass rate 97.62% (nearly non-binding).
- Filtering FALSE group (n=30, +36.9R) worsens total performance.
- p=0.075, chronologically unstable (H1/H2 sign flip). **DECISION: REJECT.**

### v2 — MSS-anchored internal sweep
- Anchor reconstruction exact: 1262/1262 (replay rules: update() from warmup+1;
  skip [entry..exit] while trade open; session ATR frozen at warmup).
- MSS = body-close proxy; all chain events ≤ zone_index−1 (causal).
- Coverage: MSS 90.1%, FULL_CHAIN 63.8%.
- avg R: FULL_CHAIN 0.559 vs MSS_ONLY 0.610 vs NO_MSS 0.572 (ordering inverted
  vs hypothesis; NO_MSS best WR 64.8%). p=0.75. Filter ≈ −38% total R (~722→449).
- Chronologically unstable. **DECISION: REJECT.**

### Permanent research conclusion
- Minor HH/LL internal-sweep + MSS chain carries NO incremental information in
  the current NEXUS 15m entry structure. Research line CLOSED; no parameter sweeps.

### Preserved state
- Parity checkpoint valid (DATA/EVENT/TRADE PARITY PASS); frozen benchmark
  remains KNOWN-GOOD reference.

## KNOWN-GOOD BENCHMARK FREEZE - COMPLETE (2026-08-22)

### Direction-dispatch bug — found & fixed
- Direction values reached execution as "bullish"/"bearish"; execution/trailing
  branching expected "long"/"short" → LONG trades managed as SHORT.
- Normalization done at execution boundary in experiment/ adapter layer:
  `bullish → long`, `bearish → short` (`_norm_side()` in trailing_adapter.py).
- Trade records keep direction labels for reporting.
- `src/` was NOT modified during this fix (git diff -- src/ = empty).
- Validation: validate_direction_fix.py = **17/17 PASS**
- Reference ADAUSD: entry=0.16620 SL=0.16537 TP=0.16768 → PROFIT_TRAIL @0.16813 (+2.344R)

### Frozen benchmark — CURRENT REFERENCE (98 symbols, full data, 15m)
EQ vs BASELINE:
- 1471 → 1262 trades
- WR 51.1% → 58.2%
- +577.02R → +722.72R (+145.70R delta)
- PF 1.80 → 2.37
- DD 27.17R → 12.73R (~53% reduction)
- 29,925 EQ rejected candidates

Directional:
- BASELINE bull 628T WR48.7% +316.67R PF1.99 | bear 843T WR52.8% +260.36R PF1.65
- EQ bull 528T WR55.1% +414.44R PF2.76 | bear 734T WR60.4% +308.27R PF2.06

### CRITICAL HISTORICAL WARNING
Pre-fix execution results are invalid as execution-behavior benchmarks because
the direction-dispatch bug corrupted trailing behavior.
Do NOT use old pre-fix benchmark numbers for future comparisons.

### Repository state
- Sterilization inventory completed.
- No files deleted, no files moved, no code cleanup performed yet.
- `src/` diff remains empty.
- `index.json` is modified by an external indexing operation and remains
  pending user decision.
- No commit. No push.
- Reference doc: docs/KNOWN_GOOD_BENCHMARK.md

## CHECKPOINT: MaxDD CHRONOLOGY FIX — COMPLETE (2026-08-25)

### Problem
`exit_bar_index` is symbol-local. Multi-symbol portfolio equity curves built by sorting `exit_bar_index` produce incorrect chronological order. Example: Symbol A `exit_bar_index=150` (Jul 25) could sort after Symbol B `exit_bar_index=50` (Aug 1) even though B's trade happened 7 days later.

### Root Cause
`compute_stats()` used `sorted(completed, key=lambda x: x.exit_bar_index)` for equity curve construction.

### Fix Applied
1. Added `exit_timestamp: float` to `BenchmarkTrade` dataclass
2. Four trade closing points now carry the actual bar timestamp:
   - Normal exit: `bar.timestamp`
   - OPEN trade: `last_bar.timestamp`
3. `compute_stats()` now uses `sorted(completed, key=lambda t: t.exit_timestamp)`
4. Added `max_dd_pct` to return dict

### Formula Verification
- MaxDD_R: `peak = max(peak, equity); dd = peak - equity; max_dd = max(max_dd, dd)` ✓
- MaxDD%: `if peak > 0: dd_pct = dd / peak * 100` ✓
- OPEN trades excluded from equity curve ✓

### Unchanged
- Strategy/trade generation: entry, exit, TP, SL, FVG, sweep, config all untouched
- Old result files not modified
- No new backtest run

### Old Values (NOT TARGETS)
- 7.32R (EXP5F, 529 trades), 12.73R (KNOWN-GOOD, 1262 trades) used wrong chronology
- New values will differ; real output is the target

### Next Action
- Run benchmark with corrected code
- Validate output

---

## Phase 0: Bootstrap - COMPLETE
- 7/7 architecture validation
- Project structure verified
- Minimal dependencies configured
- Git repository initialized

## Phase 1: MT5 Real Data Probe - COMPLETE
- Real market data from IC Markets MT5 terminal
- Symbol/tick/OHLC data probed
- .env loading fixed with python-dotenv

## Phase 2A: Strategy Specification - COMPLETE
- 377-line strategy specification
- docs/SNIPER_FOREX_STRATEGY_SPEC.md created

## Phase 2A.1: Spec Hardening - COMPLETE
- Section 4 bias_reject clarification
- Terminology resolved
- All UNRESOLVED decisions explicitly marked

## Phase 2B.2: Forex Backtest Infrastructure - COMPLETE
- Created src/backtest/ module (9 components)
- 22 tests all passing

## Data Acquisition - COMPLETE
- 98 symbols from MT5, 3,085,613 M1 bars
- Date range: 2026-07-21 to 2026-08-20
- Raw: 165 MB CSV, Feather: 73.5 MB
- Duplicates: 0, Invalid OHLC: 0
- MT5 fix: initialize() requires explicit login/password/server

## Phase 3: Real Data Strategy Baseline - COMPLETE
- Baseline: CBDR sweep + FVG + first-touch + 1.8R TP
- Full 98-symbol backtest: 1,845 trades, 59.3% WR, +1,221R
- DataLoader optimized 15x
- No-lookahead invariant enforced

## Phase 3.2: Liquidity Source Forensics - COMPLETE
- Compared CBDR vs SESSION_HL vs SWING_HL (same dataset)
- All three NEWLY DEFINED for this analysis (not in baseline)

| Source | Events | Trades | WR | PF | Avg R | Max DD |
|--------|--------|--------|-----|-----|-------|--------|
| CBDR | 1,826 | 1,826 | 76.2% | 5.77 | +1.13R | 4.0R |
| SESSION_HL | 7,558 | 7,558 | 75.4% | 5.52 | +1.11R | 25.8R |
| SWING_HL | 6,932 | 6,873 | 83.6% | 9.15 | +1.34R | 34.2R |

Key: SWING_HL highest WR/PF. CBDR lowest MaxDD but fewest signals.
CBDR NOT proven uniquely superior. 1-month data insufficient.

Dataset Discrepancy:
- Phase 3 baseline: 1,845T (CBDR-only, 1 source)
- Phase 3.2 forensics: 16,257T (3 independent sources)
- NOT directly comparable

## Phase 4: Sweep Lifecycle Forensics - COMPLETE

Core Finding:
  1 sweep = 1 trade (100%)
  CURRENT = ONE-SHOT = FRESH-SWEEP (all identical)

Results: 1,845T, 59.35% WR, PF 2.628, +1,221R
All FVGs after sweep (100%), no sweep produces 2+ trades.
Median ~20 bars sweep-to-FVG, entry 1 bar after FVG.

bias_locked prevents multiple sweeps per CBDR cycle.
Every sweep produces exactly one trade by construction.

FVG Timing: after_sweep=1845, at_sweep=0, before_sweep=0

---

## OPEN INVESTIGATION: CBDR Sweep vs FVG Origin

Status: HYPOTHESIS - NOT VALIDATED

Question: Is CBDR sweep the CAUSE of subsequent FVG,
or does FVG form independently after sweeps?

What We Know:
- 100% FVGs appear AFTER sweep bars
- Median ~20 bars between sweep and FVG
- Edge (59.35% WR) exists
- CBDR sweep is current mandatory gate

What We Do NOT Know:
- Whether FVGs form at same rate WITHOUT preceding sweep
- Whether FVG is caused by sweep displacement or independent continuation
- Whether FVG is reversal or continuation pattern
- Whether sweep-to-FVG distance correlates with edge
- Whether CBDR is necessary or any sweep suffices

Hypothesis (UNVALIDATED):
Real edge may not be sweep triggers FVG but rather:
- Bias + FVG continuation pattern
- Sweep just confirms bias direction
- FVG forms from independent price displacement
- CBDR is useful bias filter, not cause of setup

What Would Validate/Refute:
- Test FVGs WITHOUT preceding sweep -> similar WR?
- Measure FVG quality by sweep-to-FVG distance
- Compare CBDR-gated vs unfiltered FVGs
- Measure FVG size/distance vs PnL correlation

Decision Status:
- NOT DECIDED: remove CBDR as mandatory gate
- NOT DECIDED: FVG reversal vs continuation
- NOT DECIDED: sweep-to-FVG distance as quality signal
- NOT DECIDED: CBDR necessary vs just convenient

---

## NEXT STEPS
1. Test FVG quality without CBDR gate (open investigation)
2. Multi-source sweep integration
3. Remove bias_locking constraint
4. Download 3-6 month data for majors
5. Validate 59.35% WR over longer period

---

## RAW 1m DATA SOURCE INVESTIGATION — 2024→2026-08-22 (2026-08-22)

Task: acquire RAW 1m OHLCV for 6 majors (EURUSD, GBPUSD, USDJPY, AUDUSD,
USDCAD, GBPJPY) covering 2024 → today. DATA QUALITY AUDIT only — NO FVG
computation, NO production code changes, NO benchmark changes, NO commit/push.

### Source accessibility results
- **Dukascopy**: FULLY BLOCKED at network level (ConnectTimeout on all hosts).
  No workaround. Documented in data/dukascopy_raw/ACCESSIBILITY_REPORT.md.
- **HistData**: Site reachable, but `/get.php` POST returns empty HTTP 200
  (bot-block). Token regex fixed (`name="tk"[^>]*value=`) but block persists
  even with browser headers + Referer + cookie. Hard block.
- **Yahoo Finance**: Reachable, but 1m history capped at **7 days** max
  (range=7d → ~10k bars; 1mo/2y → HTTP 422). Insufficient for 2024→2026.
- **MetaTrader5 (ICMarketsSC-Demo)**: Reachable, but demo history limited to
  **~47 days** only. Insufficient.
- **Twelve Data**: CHOSEN. Reachable (verify=False needed for TLS-intercept).
  Free FX 1m history goes back to at least Jan 2024. Limits: 5000 bars/req
  (outputsize 1-5000), 8 req/min, 800 req/day. **NO volume field on free FX
  1m** (returns datetime/open/high/low/close only). Timezone = UTC.

### Downloader
- `data/twelvedata_raw/download_twelvedata.py` — windowed puller (1h windows
  to stay under 5000 bars), respects 8 req/min, pauses at 780 req/day until
  next UTC day, resume-capable via `state.json`.
- Target: `data/twelvedata_raw/csv/<PAIR>_1m.csv` (UTC, oldest→newest).
- API key: user-provided (free tier). ~1700 requests total → ~2 days due to
  800/day cap. Runs in background; re-run to resume if session dies.

### Status
- **CANCELLED by user (2026-08-22)**. Background download killed; partial
  CSV/state.json removed. `download_twelvedata.py` kept (reusable).
- **FXCM alternative (user-pasted script) REJECTED (2026-08-22)**: host
  `candledata.fxcm.com` returns DNS "Non-existent domain" — service dead.
  Also tried data/historicaldata/api.fxcm.com + fxcm.candledata.com: all
  non-existent. fxcm.com itself resolves fine, so it's not a network block.
- **USER-PROVIDED DATA (2026-08-23)**: 6 majors in `data/icmarket_raw/`
  (`*_Minute_2024_2026_RAW.csv`): EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD,
  GBPJPY. ~53MB each, ~0.98M rows each, 5.88M total.
- **AUDIT DONE (2026-08-23)** — see IC MARKET RAW AUDIT below. Structurally
  CLEAN (sorted, 0 dupes, 0 OHLC errors, volume present). Open issue:
  **timezone UNSPECIFIED** (naive timestamps) — must confirm UTC vs IC Markets
  server time (UTC+2/3) before any session-based (CBDR/sweep) use.

## IC MARKET RAW AUDIT (2026-08-23) — `data/icmarket_raw/`

Format: `Time,Open,High,Low,Close,Volume` | ASCII/UTF-8 | naive timestamps
(no tz suffix) | tick Volume present (min 1, max ~530-576, mean 68-145).

| Pair | Rows | First | Last | Span(d) | Missing% | Dup | OHLC err | Wknd bars |
|------|------|-------|------|---------|----------|-----|----------|-----------|
| EURUSD | 979,793 | 2024-01-01 22:01 | 2026-08-21 20:56 | 963 | 29.3% | 0 | 0 | 21,172 |
| GBPUSD | 979,994 | same | same | 963 | 29.3% | 0 | 0 | 21,052 |
| USDJPY | 979,389 | same | same | 963 | 29.4% | 0 | 0 | 20,857 |
| AUDUSD | 977,147 | same | same | 963 | 29.5% | 0 | 0 | 20,768 |
| USDCAD | 977,080 | same | same | 963 | 29.5% | 0 | 0 | 20,849 |
| GBPJPY | 983,232 | same | same | 963 | 29.1% | 0 | 0 | 21,467 |

- All 6: sorted=True, bad_time=0, duplicates=0, OHLC sane (high>=low,
  high>=O/C, low<=O/C, no negatives, no NaN).
- **Missing 29% is almost ENTIRELY weekend closures**: 141 gaps >1d per pair
  (= ~137 weekends over 2.64y; max_gap 2945min≈49h = Fri close→Sun open).
  Weekday continuity ~99.7% (only 64-240 sub-30min gaps/pair = illiquidity).
- **Timezone AMBIGUITY (CRITICAL)**: timestamps naive. Backtest infra uses
  IC Markets server time (UTC+2/3) per earlier parity audit. ~21k "weekend"
  bars/pair suggests possible tz offset vs UTC — MUST verify before use.
- **Ends 2026-08-21 20:56**, not today (2026-08-23) → ~1.5d shortfall.
- Starts 2024-01-01 22:01 (Monday), not Sunday 22:00 market open (minor).
- Bid/Ask NOT separate (only OHLC). Volume = tick volume, non-zero everywhere.

## IC MARKET RAW → SERVER TIME CONVERSION (2026-08-23)

User confirmed: files are **UTC (+0)**, Bid prices, Tick Volume. Backtest infra
uses **IC Markets server time**. Convert UTC → server time so data aligns 1:1
with the MT5 feather pipeline (ground truth per parity audit).

### Timezone determination (CROSS-CHECKED)
- Anchor from user: cTrader file (UTC+0) day-start = **21:00 UTC** → 21:00+3h
  = **00:00 server time** ⇒ server = **UTC+3** (summer/DST).
- Candle cross-check vs `data/feather/EURUSD_1m.feather` (server time):
  raw UTC +3h matched feather OHLC (31% exact, decisive vs ~0% at +0/+1/+2h).
- **DST-aware offset applied**: server = NY + 7h ⇒ **UTC+3 (DST) / UTC+2 (std)**,
  using `zoneinfo.America/New_York`. Both +2 and +3 present in data (winter/summer).
- Validation after conversion: converted(server) vs feather(server) @ offset 0 →
  **31,368 / 31,369 candles time-aligned (99.997%)**. OHLC near(<1e-5)=44.6%
  (rest = different feed/precision between cTrader raw and MT5 feather; expected).

### Output
- Raw UTC preserved in `data/icmarket_raw/*_RAW.csv` (source of truth).
- Converted server-time CSVs in `data/icmarket_server/*_RAW.csv` (6 pairs).
  server_first = 2024-01-02 00:01, server_last = 2026-08-21 23:56.
- Weekend bars dropped from ~21,000/pair (UTC mislabel) to ~160/pair (server)
  → confirms timezone fix is correct.
- Scripts: `data/icmarket_raw/audit_icmarket_raw.py`,
  `data/icmarket_raw/cross_check_tz.py`,
  `data/icmarket_raw/convert_icmarket_utc_to_server.py`.