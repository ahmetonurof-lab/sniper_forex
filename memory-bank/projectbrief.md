# Project Brief

**Project Name:** SNIPER_FOREX  
**Purpose:** Port the existing SNIPER strategy to Forex/MT5  
**Reference Repository:** https://github.com/ahmetonurof-lab/sniper  
**Active Repository:** https://github.com/ahmetonurof-lab/sniper_forex  

**Core Strategy:**
CBDR body sweep → daily bias lock → FVG → wick entry → FVG-hop trailing → PTrail → 1.8R TP

**Explicit Statement:**
The old SNIPER repository (ahmetonurof-lab/sniper) is reference-only. New development must be committed to sniper_forex.

**Key Constraints:**
- Do not invent a new strategy
- Do not import unrelated NEXUS logic
- Do not implement strategy code in Phases 0-2A.1
- The SNIPER strategy exists conceptually and must not be redesigned
- Strategy specification is documented in docs/SNIPER_FOREX_STRATEGY_SPEC.md
- All unresolved decisions are explicitly marked as UNRESOLVED