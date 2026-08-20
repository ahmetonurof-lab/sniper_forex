# Product Context

## Intended System Behavior
The SNIPER_FOREX system is a Forex trading bot designed for the MetaTrader 5 platform on the IC Markets demo account. The system will implement the SNIPER strategy concept for Forex markets.

## Strategy Philosophy
The SNIPER strategy is a conceptual Forex trading strategy built around:
- CBDR (Core Balance Daily Range) body sweep detection
- Daily bias lock from the first confirmed sweep
- Fair Value Gap (FVG) detection and trading
- Wick touch entries
- FVG-hop trailing with PTrail
- 1.8R initial TP with trailing exit

## What SNIPER is Supposed to Accomplish
- Identify daily structure via CBDR body analysis
- Detect liquidity sweeps that determine daily bias
- Find and trade Fair Value Gaps
- Manage positions with trailing exits at 1.8R
- Preserve deterministic bar boundaries
- Isolate per-symbol strategy states

## What is Intentionally NOT Part of the System
- New strategy invention (strategy exists conceptually)
- NEXUS logic import
- Order execution in Phases 0-2A.1
- Backtest systems (Phase 1 is data probe only)
- Live trading (Phase 2B pending)
- Mock/synthetic MT5 connections

## No Strategy Redesign
The existing SNIPER strategy concept must be preserved. Only documentation and specification is allowed in Phases 0-2A.1. No code implementation until Phase 2B.

## Preserve Reference Implementation Behavior
The old SNIPER repository (ahmetonurof-lab/sniper) is used only for behavioral verification. Any Forex adaptation changes must be explicitly documented as UNRESOLVED decisions in the strategy specification.