# Tech Context

## Language & Runtime
- **Python 3.12.2** on Windows
- Scripts run via `python -m src.<module>` from project root

## Dependencies
- **MetaTrader5 5.0.6090** - MT5 terminal connection
- **python-dotenv** - .env file loading
- **pandas** - Data manipulation
- **numpy** - Numerical computation

## Architecture Stack
- Python as sole implementation language
- MetaTrader5 Python API for MT5 terminal
- git for version control (GitHub: ahmetonurof-lab/sniper_forex)

## Data Architecture

### Source of Truth
```
data/raw/          98 CSV files (165 MB)
data/feather/      98 Feather files (73.5 MB)
data/manifest.json All metadata
```

### Dataset
- Symbols: 98 (Major FX, Cross FX, Metals, Energy, Crypto, Exotics)
- Bars: 3,085,613 M1 bars
- Date range: 2026-07-21 to 2026-08-20
- Duplicates: 0
- Invalid OHLC: 0
- Volume: tick_volume
- Timezone: MT5 Server Time (UNVERIFIED)

### Key Insight
- mt5.initialize() requires explicit login/password/server params
- path alone is insufficient

### Data Pipeline
```
MT5 Terminal -> mt5_downloader -> raw/ CSV
                                  |
                            feather_converter -> feather/
                                  |
                            data_validator -> validation_report
                                  |
                            manifest_generator -> manifest.json
                                  |
                            ForexDataStore.load(symbol)
                                  |
                            DataLoader -> Strategy
```

### Strategy Backtest Modules
```
src/strategy/
  models.py         Bar, SweepEvent, FVGEvent, TradeSetup, etc.
  data_loader.py    Feather-only loader, optimized zip()
  session.py        Session detection, CBDR body accumulation
  sweep.py          ATR-based sweep detector, bias_locked
  fvg.py            3-candle FVG detector
  entry.py          First-touch entry detection
  trade_simulator.py Entry/SL/TP/exit/PnL calculation
  strategy.py       Main strategy engine (Sweep->FVG->Entry->Trade)
  phase4_lifecycle.py  Sweep lifecycle forensics
  liquidity_forensics.py  Multi-source liquidity analysis
```

## Key Technical Constraints
- Strategy must not directly import/call MT5 API
- .env credentials are never committed to git
- Strategy must be independently testable without MT5
- Per-symbol strategy state isolation required
- All unresolved decisions explicitly marked UNRESOLVED
- No-lookahead invariant: decision at time T uses only data <= T
- Offline backtest only through data/feather/

## Git Workflow
- Branch: main
- Remote: origin (ahmetonurof-lab/sniper_forex)
- .env file must NOT be tracked
- Never push to old sniper repository
- Never force push
- memory-bank/ updates committed separately from code