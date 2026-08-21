# Active Context

## Current Phase: POST-PHASE 4 -- OPEN INVESTIGATION

## Completed Phases

### Phase 0: Bootstrap - COMPLETE
- 7/7 architecture validation passed
- Project structure verified
- Minimal dependencies (MetaTrader5, python-dotenv)
- Architecture: config -> data/trading -> strategy -> main
- .env loading fixed from project root
- No credentials hardcoded or committed

### Phase 1: MT5 Real Data Probe - COMPLETE
- Created src/test_mt5_data.py probe module
- Probes real market data from IC Markets MT5 terminal
- Symbol information, live tick data, OHLC bars (M1/M5/M15/H1)
- Data quality validation (chronological, OHLC validity, bid/ask)
- Clean shutdown lifecycle

### Phase 2A: Strategy Specification - COMPLETE
- Created docs/SNIPER_FOREX_STRATEGY_SPEC.md (377 lines)
- 17-section comprehensive strategy specification
- All SNIPER strategy concepts documented
- No strategy code implemented (preserved conceptually)
- All unresolved decisions explicitly marked as UNRESOLVED

### Phase 2A.1: Spec Hardening - COMPLETE
- Added clarification to Section 4 (Bias Rejection)
- CBDR time window explicitly unresolved
- Retrace terminology resolved (NO-FVG HOLD vs ATR FALLBACK)
- Rejection paths documented
- Per-symbol state isolation explicit
- Daily reset/open-position interaction explicit
- Timestamp timezone policy explicit

### Phase 2B.2: Forex Backtest Infrastructure - COMPLETE
- Created src/backtest/ module with 9 components
- 22 comprehensive tests all passing

### Data Acquisition - COMPLETE
- 98 symbols from MT5, 3,085,613 M1 bars
- Date range: 2026-07-21 to 2026-08-20
- Raw: 165 MB CSV, Feather: 73.5 MB
- Duplicates: 0, Invalid OHLC: 0
- MT5 fix: initialize() requires explicit login/password/server

### Phase 3: Real Data Strategy Baseline - COMPLETE
- Baseline: CBDR sweep + FVG + first-touch + 1.8R TP
- Full 98-symbol backtest: 1,845 trades, 59.3% WR, +1,221R
- DataLoader optimized 15x
- No-lookahead invariant enforced
- Key: bias_locked mechanism = 1 sweep -> 1 trade per CBDR cycle

### Phase 3.2: Liquidity Source Forensics - COMPLETE
- Compared CBDR vs SESSION_HL vs SWING_HL (same dataset)
- SESSION_HL and SWING_HL NEWLY DEFINED for this analysis

| Source | Events | Trades | WR | PF | Avg R | Max DD |
|--------|--------|--------|-----|-----|-------|--------|
| CBDR | 1,826 | 1,826 | 76.2% | 5.77 | +1.13R | 4.0R |
| SESSION_HL | 7,558 | 7,558 | 75.4% | 5.52 | +1.11R | 25.8R |
| SWING_HL | 6,932 | 6,873 | 83.6% | 9.15 | +1.34R | 34.2R |

Key finding: SWING_HL highest WR/PF. CBDR NOT proven uniquely superior.
1-month data insufficient for statistical significance.

### Phase 4: Sweep Lifecycle Forensics - COMPLETE

Core Finding: 1 sweep = 1 trade (100%). CURRENT = ONE-SHOT = FRESH-SWEEP (all identical).
Results: 1,845T, 59.35% WR, PF 2.628, +1,221R.
All FVGs after sweep (100%), no sweep produces 2+ trades.
Median ~20 bars sweep-to-FVG, entry 1 bar after FVG.
bias_locked prevents multiple sweeps per CBDR cycle.

## OPEN INVESTIGATION: CBDR Sweep vs FVG Origin

Status: **HYPOTHESIS -- NOT VALIDATED**

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
Real edge may not be "sweep triggers FVG" but rather:
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

## NEXT STEPS
1. Test FVG quality without CBDR gate (open investigation)
2. Multi-source sweep integration
3. Remove bias_locking constraint
4. Download 3-6 month data for majors
5. Validate 59.35% WR over longer period

## Current Git Baseline
- Repository: ahmetonurof-lab/sniper_forex
- Branch: main

## Strategy Layer Rules
- Strategy must not directly import/call MT5
- .env credentials are never committed
- Strategy must be independently testable without MT5
- Per-symbol strategy state isolation required
- Do not invent unresolved strategy rules
- Tests are behavioral contracts
- No-lookahead invariant: decision at time T uses only data <= T

## Tech Stack
- Python 3.12.2
- MetaTrader5 5.0.6090
- python-dotenv
- pandas, numpy
- MT5 IC Markets demo environment
- MT5 Server Time (timezone unverified)