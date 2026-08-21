# Progress

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