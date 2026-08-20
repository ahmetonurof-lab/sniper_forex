# System Patterns

## Architectural Rules

### Dependency Flow
```
config → data/trading → strategy → main
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
- Symbol A → StrategyState A
- Symbol B → StrategyState B
- Symbol C → StrategyState C
- No symbol may share:
  - daily_bias
  - bias_locked
  - CBDR state
  - FVG state
  - active trade state
  - trailing state

### Reference Implementation Behavior
- The old SNIPER repository (ahmetonurof-lab/sniper) is used for behavioral verification only
- Forex adaptation changes must be explicitly documented as UNRESOLVED
- Do not invent unresolved strategy rules
- Tests are behavioral contracts, not implementation guides

### Test Philosophy
- **Pure strategy tests**: Run with MT5 closed, IC Markets disconnected, internet unavailable
- **MT5 integration tests**: test_mt5_connection.py environment test
- Pure strategy tests must NOT depend on MT5
- Integration tests are separate from unit/behavioral contracts