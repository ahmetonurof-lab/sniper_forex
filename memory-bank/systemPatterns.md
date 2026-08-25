# System Patterns

## Architectural Rules

### Dependency Flow
```
config -> data/trading -> strategy -> main
```

### Layer Ownership
- **config layer** owns configuration
  - Reads .env from project root
  - Never hardcodes credentials
  - Provides config dict to data layer

- **data layer** owns market data access
  - Encapsulates all MT5 API calls
  - Provides symbol info, tick data, OHLC bars
  - No signal generation, no trading logic

- **trading layer** owns execution framework
  - Handles MT5 initialize/login/shutdown
  - NO order sending in Phases 0-2A.1
  - Position management reserved for Phase 2B

- **strategy layer** owns deterministic strategy logic
  - Must not directly import/call MT5
  - Operates on data layer output only
  - Per-symbol strategy state isolation
  - All unresolved decisions marked UNRESOLVED

- **main orchestrates**
  - Coordinates layer interactions
  - Manages connection lifecycle
  - Performs clean shutdown
  - Does not implement strategy logic

### Per-Symbol Strategy State Isolation
- Each symbol has an independent StrategyState instance
- Symbol A -> StrategyState A
- Symbol B -> StrategyState B
- Symbol C -> StrategyState C
- No symbol may share:
  - daily_bias
  - bias_locked
  - CBDR state
  - FVG state
  - active trade state
  - trailing state

## Sweep Lifecycle Pattern (Phase 4 Finding)

### Core Architecture
```
SWEEP (bar N)
    |
    v
bias_locked = TRUE
    |
    v
FVG detection (bar N+20 median)
    |
    v
First-touch entry (bar N+21 median)
    |
    v
Trade (TP/SL)
```

### Key Properties
- **1 sweep -> 1 trade (100%)** by construction
- CURRENT = ONE-SHOT = FRESH-SWEEP (all identical results)
- bias_locked prevents multiple sweeps per CBDR cycle
- All FVGs appear AFTER sweep bars (100%)

### Liquidity Source Hierarchy (Phase 3.2)

Three liquidity sources tested on SAME dataset:

| Source | Events | WR | PF | Avg R | Max DD | Notes |
|--------|--------|-----|-----|-------|--------|-------|
| CBDR | 1,826 | 76.2% | 5.77 | +1.13R | 4.0R | Current baseline, fewest signals |
| SESSION_HL | 7,558 | 75.4% | 5.52 | +1.11R | 25.8R | Newly defined for analysis |
| SWING_HL | 6,932 | 83.6% | 9.15 | +1.34R | 34.2R | Newly defined, highest WR/PF |

**NOT validated as proven edge.** 1-month data insufficient.

## CBDR vs FVG Origin (OPEN HYPOTHESIS)

The core question remains UNANSWERED:

- Does CBDR sweep CAUSE subsequent FVG? (displacement -> gap)
- Or does FVG form INDEPENDENTLY after sweeps? (continuation pattern)

### Evidence
- 100% FVGs appear after sweep bars
- Median ~20 bars between sweep and FVG
- Edge (59.35% WR) exists with CBDR gate

### Unknown
- FVG formation rate WITHOUT preceding sweep
- FVG reversal vs continuation classification
- Sweep-to-FVG distance as quality signal
- CBDR necessity vs convenience

**Status: HYPOTHESIS -- NOT VALIDATED**

## Dataset Discrepancy (Phase 3 vs 3.2)

| | Phase 3 Baseline | Phase 3.2 Forensics |
|--|------------------|--------------------|
| Trades | 1,845 | 16,257 |
| Source | CBDR-only (1 source) | 3 independent sources |
| Neden farkli | Single strategy run | Sum of 3 independent runs |
| Comparable? | NO | -- |

## Test Philosophy
- **Pure strategy tests**: Run with MT5 closed, internet unavailable
- **MT5 integration tests**: test_mt5_connection.py environment test
- Pure strategy tests must NOT depend on MT5
- Integration tests are separate from unit/behavioral contracts
- No-lookahead invariant is a HARD CONSTRAINT

## Reference Implementation Behavior
- The old SNIPER repository (ahmetonurof-lab/sniper) is used for behavioral verification only
- Forex adaptation changes explicitly documented
- Tests are behavioral contracts, not implementation guides
