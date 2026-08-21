# Project Brief

**Project Name:** SNIPER_FOREX
**Purpose:** Port the existing SNIPER strategy to Forex/MT5
**Reference Repository:** https://github.com/ahmetonurof-lab/sniper
**Active Repository:** https://github.com/ahmetonurof-lab/sniper_forex

**Core Strategy (Baseline):**
CBDR sweep -> FVG -> first-touch entry -> 1.8R TP

**Baseline Performance (Phase 3):**
- 98 symbols, 1,845 trades
- 59.35% Win Rate, PF 2.628, +1,221R total
- 1 sweep -> 1 trade (bias_locked)

**Current Status:**
- Phases 0-4: COMPLETE
- Data: 98 symbols, 3,085,613 M1 bars (2026-07-21 to 2026-08-20)
- Strategy baseline: Working but unvalidated long-term
- Open investigation: CBDR sweep vs FVG origin hypothesis

**Key Findings:**
- SWING_HL shows higher WR/PF than CBDR in 1-month data (Phase 3.2)
- Bias_locked enforces 1 sweep -> 1 trade (Phase 4)
- CBDR necessity is NOT proven (open investigation)
- 1-month data insufficient for final validation

**Explicit Statement:**
The old SNIPER repository (ahmetonurof-lab/sniper) is reference-only. New development must be committed to sniper_forex.

**Key Constraints:**
- Do not invent a new strategy
- Do not import unrelated NEXUS logic
- The SNIPER strategy exists conceptually and must not be redesigned
- Strategy specification is documented in docs/SNIPER_FOREX_STRATEGY_SPEC.md
- All unresolved decisions are explicitly marked as UNRESOLVED
- No-lookahead invariant is a HARD CONSTRAINT
- Offline backtest only through data/feather/

**Next Steps:**
1. Test FVG quality without CBDR gate
2. Multi-source sweep integration
3. Download 3-6 month data for majors
4. Validate 59.35% WR over longer period