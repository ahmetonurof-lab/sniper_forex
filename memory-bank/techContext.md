# Tech Context

## Language & Runtime
- **Python** - Version 3.x (targeting 3.10+ compatibility)
- Scripts run via `python -m src.<module>` from project root

## Dependencies
- **MetaTrader5** - IC Markets demo environment connection
- **python-dotenv** - Environment variable loading from .env file
- Native Windows environment (OS: Windows)

## Architecture Stack
- **Python** as the sole implementation language
- **MetaTrader5** Python API for MT5 terminal connection
- **python-dotenv** for .env file loading from project root
- **Git** for version control (GitHub: ahmetonurof-lab/sniper_forex)

## Key Technical Constraints
- Strategy must not directly import/call MT5 API
- .env credentials are never committed to git
- Strategy must be independently testable without MT5
- Per-symbol strategy state isolation required
- All unresolved decisions must be explicitly marked UNRESOLVED
- No strategy code in Phases 0-2A.1
- Reference implementation (sniper repo) is behavioral verification only

## Data Layer
- Encapsulates all MT5 API calls
- Provides symbol info, tick data, OHLC bars
- No signal generation, no trading logic
- Uses environment variables for credentials

## Trading Layer
- Handles MT5 initialize/login/shutdown
- NO order sending in Phases 0-2A.1
- Position management reserved for Phase 2B

## Strategy Layer
- Owns deterministic strategy logic
- Must not directly import/call MT5
- Operates on data layer output only
- All unresolved decisions marked UNRESOLVED
- Per-symbol strategy state isolation

## Main Orchestration
- Coordinates layer interactions
- Manages connection lifecycle
- Performs clean shutdown
- Does not implement strategy logic

## Git Workflow
- Initial commit: 42aacd3 ("initial: bootstrap sniper forex project")
- Branch: main
- Remote: origin (ahmetonurof-lab/sniper_forex)
- .env file must NOT be tracked
- Never push to old sniper repository
- Never force push