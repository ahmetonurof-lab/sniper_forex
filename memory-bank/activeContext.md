# Active Context

## Phase 0: Bootstrap - COMPLETE
- 7/7 architecture validation passed
- Project structure verified
- Minimal dependencies (MetaTrader5, python-dotenv)
- Architecture: config → data/trading → strategy → main
- .env loading fixed from project root
- No credentials hardcoded or committed

## Phase 1: MT5 Real Data Probe - COMPLETE
- Created src/test_mt5_data.py probe module
- Probes real market data from IC Markets MT5 terminal
- Symbol information, live tick data, OHLC bars (M1/M5/M15/H1)
- Data quality validation (chronological, OHLC validity, bid/ask)
- Proper output format as specified
- Clean shutdown lifecycle
- Uses existing architecture (config → data layer → test probe)

## Phase 2A: Strategy Specification - COMPLETE
- Created docs/SNIPER_FOREX_STRATEGY_SPEC.md (377 lines)
- 17-section comprehensive strategy specification
- All SNIPER strategy concepts documented
- No strategy code implemented (preserved conceptually)
- All unresolved decisions explicitly marked as UNRESOLVED

## Phase 2A.1: Spec Hardening - COMPLETE
- Added clarification to Section 4 (Bias Rejection)
- CBDR time window explicitly unresolved
- Retrace terminology resolved (NO-FVG HOLD vs ATR FALLBACK)
- Rejection paths documented
- Per-symbol state isolation explicit
- Daily reset/open-position interaction explicit
- Timestamp timezone policy explicit
- Pure tests separated from MT5 integration tests
- Phase 2B scope boundaries explicit
- No strategy code created

## Current Git Baseline
- Commit: 42aacd3
- Repository: ahmetonurof-lab/sniper_forex
- Branch: main
- Status: clean

## Current Strategy Status
- Phase 0: Bootstrap - COMPLETE
- Phase 1: MT5 Real Data Probe - COMPLETE
- Phase 2A: Strategy Specification - COMPLETE
- Phase 2A.1: Spec Hardening - COMPLETE
- Phase 2B.1: Core Implementation - PENDING

## Strategy Layer Rules
- Strategy must not directly import/call MT5
- .env credentials are never committed
- Strategy must be independently testable without MT5
- Per-symbol strategy state isolation required
- Do not invent unresolved strategy rules
- Tests are behavioral contracts

## Tech Stack
- Python
- MetaTrader5
- python-dotenv
- MT5 IC Markets demo environment