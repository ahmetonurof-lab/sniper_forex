# SNIPER FOREX — STRATEGY SPECIFICATION

## Phase 2A: Strategy Specification / No Implementation

**IMPORTANT:** The SNIPER strategy already exists conceptually and must NOT be redesigned. Do not invent a new strategy. Do not import unrelated NEXUS logic. This phase is ONLY to convert the existing SNIPER strategy into a precise Forex implementation specification.

---

## 1. DATA

### Original SNIPER Concept:
- 1m data
- 1m → 15m aggregation
- strategy evaluation on 15m bar close
- multi-symbol scanning

### Forex Implementation:
- Must use MT5 market data
- **NOT YET DECIDED:** Canonical 15m bars source

| Option | Description | Implications |
|--------|-------------|-------------|
| **A) MT5 native M15 bars** | Direct M15 timeframe from MT5 | Preserves native MT5 bar boundaries; may have different spread/quote behavior |
| **B) MT5 M1 bars aggregated into M15** | Aggregate 1-minute data into 15-minute bars | More control over bar construction; requires deterministic aggregation rule |

### Decision:
- **Document both possibilities**
- **Identify the implications**
- **Recommend one for Phase 2B**
- **DO NOT implement the decision yet**

### Critical:
- The final strategy must preserve **deterministic bar boundaries**

---

## 2. CBDR BODY + SWEEP

### CBDR is a DAILY structure:
- The system observes intraday candle bodies
- **Sweep definition:** A candle body breaks the CBDR body range and then closes back through/inside the relevant boundary. This constitutes a liquidity sweep.

### Sweep Direction:
- **bullish**
- **bearish**

### First Confirmed Sweep of the Day:
- Determines: **daily_bias**
- Opens: **bias_locked = True**

### Once Locked:
- **daily_bias remains fixed** for the rest of the trading day
- **Do NOT unlock/recalculate bias** later in the same day

---

## 3. HTF BIAS

### The 1D HTF bias filter is **OFF**:
- Do NOT add: EMA bias, daily trend filter, higher timeframe directional filter
- The daily bias comes from the **first confirmed CBDR sweep**

---

## 4. BIAS REJECTION

### If sweep direction conflicts with the CBDR directional relationship required by the strategy:

**Currently nothing about bias_reject is implementable — it remains fully UNRESOLVED until the directional relationship is defined by a human.**

- **Reject the setup**
- **Record the rejection reason as:** `bias_reject`
- **Do not silently discard** the setup

---

## 5. FVG DETECTION

### Detect Fair Value Gaps:
- **FVG direction must agree with daily_bias**
- **Opposite-direction FVGs are not valid entry FVGs**

### Supported FVG Types:
- **normal FVG**
- **IFVG candidate**

### IFVG Definition:
- When body price action breaks an FVG in the invalidating direction, record an inverted-FVG candidate
- **Do NOT invent additional IFVG rules**
- **Document exact conditions before implementation**

---

## 6. ENTRY

### Entry State: **TRIGGER_READY**

### For the FIRST valid FVG:
- **A WICK TOUCH of the FVG is sufficient for entry**
- **There is NO candle-close requirement** for initial FVG entry

### Important Distinction:

| Condition | Requirement |
|-----------|-------------|
| **INITIAL ENTRY** | wick touch = sufficient |
| **FVG INVALIDATION** | body break = invalidation |

### Therefore:
- **wick penetration alone does NOT invalidate**
- **body break invalidates**

---

## 7. INITIAL SL

### LONG:
- **SL = FVG.bottom**

### SHORT:
- **SL = FVG.top**

### Do NOT:
- Substitute ATR SL
- Substitute swing SL
- Add arbitrary buffers yet

---

## 8. INITIAL TP

### TP = **1.8R**

### Use the actual initial risk distance.

### Apply existing epsilon/proximity rejection logic:
- If SL is too close to the FVG according to the existing epsilon rule, **reject the setup**
- **Do NOT invent a new epsilon formula**
- **Document the required inputs for implementation**

---

## 9. TRAILING — FVG HOP CHAIN

### First FVG is the **entry FVG**

### Subsequent FVGs are **trailing candidates**

### Trailing Confirmation Rule: **fvg_close_confirmed**
- The candle must **CLOSE inside** the relevant FVG gap
- **A wick touch alone is NOT enough** for trailing confirmation

### When a Trailing FVG is Confirmed:
- **SL hops to the next FVG level**
- **Apply:** `TRAIL_MIN_MOVE_MULT × initial risk` as the minimum movement requirement
- **Do not move SL** for insignificant hops

---

## 10. PTrail

### TP moves in parallel with SL.

### When SL moves:
- **TP moves by the same absolute distance**
- This is **PTrail**

### Preserve the existing strategy relationship:
- **Do not independently recalculate TP** as a fresh RR target after every hop

---

## 11. NO-FVG BEHAVIOR

### If no new FVG is available:
- **RETRACE:**
  - **SL remains unchanged**
  - **TP remains unchanged**
- **No arbitrary trailing**

---

## 12. RETRACE FALLBACK

### If the configured number of bars passes without a new FVG:
- **Fallback may activate ONLY when:**
  - **required bar-silence condition is satisfied**
  - **UPNL >= 1.5R**

### Then:

| Direction | SL Formula |
|-----------|-----------|
| **LONG** | `SL = close - K × ATR` |
| **SHORT** | `SL = close + K × ATR` |

### This is **ATR-chase fallback**.

### Do NOT:
- Activate before the required profit threshold
- Invent K
- Invent the number of silent bars

### Those values must remain **explicit configuration parameters**.

---

## 13. EXIT

### Valid Exits:
- **TP**
- **initial SL**
- **trailing-hop SL**
- **ATR fallback SL**

### Protect against stale TP events:
- A stale TP event must not incorrectly close a position after TP has been moved

---

## 14. STATE MACHINE

### Eventually implement explicit states (document only):

| State | Description |
|-------|-------------|
| **DAILY_RESET** | New trading day begins |
| **WAITING_FOR_SWEEP** | Awaiting first CBDR sweep |
| **BIAS_LOCKED** | Daily bias is fixed |
| **FVG_READY** | Valid FVG detected |
| **TRIGGER_READY** | Entry trigger conditions met |
| **IN_POSITION** | Position is open |
| **TRAILING** | SL/TP trailing in effect |
| **CLOSED** | Position closed/exited |

### Do NOT implement these yet.

### **Document state transitions only.**

---

## 15. FOREX-SPECIFIC ITEMS TO IDENTIFY

### Before implementation, identify:

| Item | Reference |
|------|-----------|
| broker/server timezone | MT5 probe results |
| MT5 timestamp semantics | Phase 1 probe |
| trading day boundary | Not yet determined |
| weekend behavior | Not yet determined |
| symbol naming | Not yet determined |
| point/digits | Not yet determined |
| tick size | Not yet determined |
| spread | Not yet determined |
| pip normalization | Not yet determined |
| minimum stop distance | Not yet determined |
| symbol trading sessions | Not yet determined |
| missing bars | Not yet determined |
| DST implications | Not yet determined |
| XAUUSD differences from FX pairs | Not yet determined |

### Use the **Phase 1 MT5 probe results** where available.

### **Do not solve these by assumptions.**

---

## 16. CONFIGURATION

### Proposed Configuration Specification (do NOT implement yet):

| Parameter | Purpose | Unit | Default | Strategy-Fixed | Configurable |
|-----------|---------|------|---------|----------------|--------------|
| **CBDR parameters** | Daily body range structure | - | - | - | Yes |
| **FVG parameters** | Fair Value Gap detection | - | - | - | Yes |
| **RR** | Risk-Reward ratio | - | 1.8R | - | Yes |
| **epsilon** | Proximity rejection threshold | price units | - | - | Yes |
| **TRAIL_MIN_MOVE_MULT** | Minimum movement for trailing hop | × initial risk | - | - | Yes |
| **fallback silence bars** | Bars without new FVG before fallback | bar count | - | - | Yes |
| **fallback profit threshold** | UPNL threshold for fallback activation | R multiple | - | - | Yes |
| **ATR period** | ATR calculation period | bars | - | - | Yes |
| **ATR fallback multiplier K** | ATR multiplier for fallback SL | numeric | - | - | Yes |
| **session parameters** | Trading session filters | time | - | - | Yes |
| **symbol parameters** | Symbol-specific settings | - | - | - | Yes |

### Every parameter must have:
- **name**
- **purpose**
- **unit**
- **default status**
- **whether it is strategy-fixed or configurable**

---

## 17. OUTPUT

### Do NOT:
- Write strategy code
- Modify `src/strategy/` with implementation code

### Produce:
- **docs/SNIPER_FOREX_STRATEGY_SPEC.md** (this document)

### If `docs/` does not exist:
- Create it

### The document must contain:

1. Strategy overview
2. Data model
3. CBDR definition
4. Sweep definition
5. Daily bias lock
6. FVG rules
7. IFVG rules
8. Entry rules
9. SL rules
10. TP rules
11. FVG-hop trailing
12. PTrail
13. No-FVG retrace behavior
14. ATR fallback
15. Exit rules
16. State machine
17. Forex-specific considerations
18. Configuration table
19. **Explicit unresolved decisions**
20. **Implementation checklist for Phase 2B**

---

## CRITICAL RULE

### If a rule is not explicitly defined above:

**DO NOT INVENT IT.**

### Mark it: **UNRESOLVED**

### And explain what information is required before implementation.

### The purpose of this phase is to **eliminate ambiguity before coding**.

### No strategy implementation.
### No backtest.
### No order execution.
### No live trading.

---

## Implementation Checklist for Phase 2B

### When moving from Phase 2A to Phase 2B, implement:

- [ ] Convert specification to working code in `src/strategy/`
- [ ] Implement data aggregation decision (A or B for 15m bars)
- [ ] Implement CBDR detection and daily bias lock
- [ ] Implement sweep detection logic
- [ ] Implement FVG and IFVG detection
- [ ] Implement entry rules (wick touch, no close requirement)
- [ ] Implement initial SL (FVG.bottom/top)
- [ ] Implement initial TP (1.8R with epsilon rejection)
- [ ] Implement FVG-hop trailing chain
- [ ] Implement PTrail (TP moves with SL)
- [ ] Implement no-FVG retrace behavior
- [ ] Implement ATR fallback (with UPNL >= 1.5R threshold)
- [ ] Implement exit rules (TP, SL, trailing, fallback)
- [ ] Implement state machine (documented states)
- [ ] Resolve forex-specific items (timezone, DST, symbol naming, etc.)
- [ ] Create configuration system with all parameters
- [ ] Backtest with historical data
- [ ] Paper trading validation
- [ ] Live trading readiness assessment

---

**Phase 2A Complete:** Strategy specification documented with all ambiguity marked as UNRESOLVED where required. No code implemented. No strategy redesigned. Ready for Phase 2B implementation when directed.