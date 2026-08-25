PHASE 2B.1 — REAL_CBDR REFERENCE EXTRACTION REPORT
1. Session Routing
Aspect	Finding
Profile selection	SessionState.__init__(start_hour=22, end_hour=2) is the DEFAULT. Symbol-specific hours come from cfg.SESSION_HOURS[profile["session"]] where profile can be DEFAULT (22/2), REAL_CBDR (19/1), or ASIA_RANGE (1/5).
Caller	sniper/src/bot.py:318-320: SessionState(start_hour=get_session_hours(sym)["start"], end_hour=get_session_hours(sym)["end"]) — passes config-derived hours
Override mechanism	sniper/src/session_router.py:31-33: get_session_hours(symbol) returns profile hours or {"start": 22, "end": 2} as fallback
REAL_CBDR profile	sniper/src/config.py:100: "REAL_CBDR": {"start": 19, "end": 1} — 19:00→01:00 UTC window
2. REAL_CBDR Profile Selection
Aspect	Finding
Profile dict	sniper/src/config.py:98-132: SESSION_HOURS: dict[str, dict[str, int]] = {"DEFAULT": {"start": 22, "end": 2}, "REAL_CBDR": {"start": 19, "end": 1}, "ASIA_RANGE": {"start": 1, "end": 5}}
Selection logic	sniper/src/session_router.py:31-33: get_session_hours(symbol) → cfg.CBDR_RISK_MATRIX.get(symbol) → cfg.SESSION_HOURS.get(profile["session"]) → fallback {"start": 22, "end": 2}
REAL_CBDR hours	19:00 UTC → 01:00 UTC (spanning midnight; sh=19 > eh=1 so spans_midnight=True, in_window = (h >= 19 or h < 1))
3. CBDR Body Accumulation
Aspect	Finding
track_body	sniper/src/session.py:74-82: Accumulates body_high = max(body_high, open/close) and body_low = min(body_low, open/close) across bars within the CBDR window
Window check	sniper/src/session.py:445: in_window = (h >= sh or h < eh) if spans_midnight else (sh <= h < eh) — only bars inside the 19:00-01:00 UTC window contribute
Outside window	Bars outside the window are ignored for body tracking (if in_window and not cbdr.locked: cbdr.track_body(open, close))
Lock trigger	sniper/src/session.py:451: out_of_window and not cbdr.locked and cbdr.body_high > 0 → calls cbdr.lock() when price exits the window and body has been accumulated
4. Start/End Boundary Behavior
Aspect	Finding
Window spans midnight	sh=19, eh=1 → spans_midnight = True
in_window formula	(h >= sh or h < eh) = (h >= 19 or h < 1) — hour 19, 20, 21, 22, 23, 0, 1 are inside; hours 2-18 are outside
out_of_window formula	(eh <= h < sh) if spans_midnight else (h >= eh or h < sh) = (1 <= h < 19) — hours 1-18 are outside; hour 19 is boundary (lock triggers on exit)
Daily reset	Next day at 19:00 UTC the cycle restarts (via cbdr_day_key() which returns the day the cycle ends — see Step 2 report)
5. Sweep Detection
Aspect	Finding
check_sweep	sniper/src/session.py:89-128: Compares current bar's high/low/close against accumulated body_high/body_low + tolerance
Tolerance	cfg.CBDR_SWEEP_ATR_TOLERANCE_MULT * atr (default 0.5 * atr) or CBDR_SWEEP_DEFAULT_TOLERANCE = 10.0 if atr <= 0
Bearish sweep	high > body_high + tolerance AND close < body_high → sets sweep_direction = "bearish", daily_bias = BEARISH, bias_locked = True
Bullish sweep	low < body_low - tolerance AND close > body_low → sets sweep_direction = "bullish", daily_bias = BULLISH, bias_locked = True
First sweep only	if self.bias_locked: return at entry — subsequent sweeps on the same day are skipped
6. Sweep Confirmation
Aspect	Finding
sweep_confirmed	Set to True inside check_sweep when conditions met; read via SessionState.sweep_confirmed property
Purpose	Distinguishes first confirmed sweep (sets bias + lock) from subsequent sweep attempts
7. Tolerance Calculation
Aspect	Finding
ATR-based	tolerance = atr * CBDR_SWEEP_ATR_TOLERANCE_MULT where CBDR_SWEEP_ATR_TOLERANCE_MULT = 0.5 (sniper/src/config.py:652)
Default fallback	CBDR_SWEEP_DEFAULT_TOLERANCE = 10.0 (sniper/src/config.py:654) used when atr <= 0
Applied in	sniper/src/session.py:105-107 inside check_sweep()
8. First Confirmed Sweep Behavior
Aspect	Finding
L-05 rule	"Günün ILK onaylanmış sweep'i daily_bias'i belirler ve bias_locked latch'ini açar" (First confirmed sweep determines daily_bias and opens bias_locked latch)
Lock persistence	Once bias_locked = True, it cannot be changed for the rest of the day (if self.bias_locked: return in check_sweep)
Day reset	Next CBDR cycle (next 19:00 UTC) resets all state via reset_for_new_cycle()
Idempotency	lock_bias_from_sweep() is idempotent: "aynı CBDR günü latch zaten kayitliysa True döner — bias gunde bir kez kilitlenir, ikinci sweep latch'i DEGISTIREMEZ"
8. daily_bias Assignment
Aspect	Finding
Assignment	sniper/src/session.py:117: self.daily_bias = DailyBias.BEARISH or DailyBias.BULLISH inside check_sweep()
Type	DailyBias enum: BULLISH, BEARISH, NEUTRAL
Persistence	Stored in CBDRState.daily_bias; read via SessionState.daily_bias property
After lock	Bias is fixed; if self.bias_locked: return prevents re-assignment
10. bias_locked Behavior
Aspect	Finding
Initial state	cbdr.locked = False in CBDRState.__init__()
Set to True	By check_sweep() when first sweep conditions met; also by lock() when price exits window with body > 0
Read-only	Property SessionState.bias_locked returns self._cbdr.locked
Cannot be unset	No code path resets bias_locked = False within a day; reset only happens at next cycle via reset_for_new_cycle()
11. Reset Behavior
Aspect	Finding
reset_for_new_cycle	sniper/src/session.py:129-137: Resets CBDRState.body_high=0.0, CBDRState.body_low=float("inf"), CBDRState.locked=False, CBDRState.sweep_confirmed=False, CBDRState.sweep_direction=None, CBDRState.sweep_level=None; also resets RangeTracker and TradeDayState
Trigger	SessionState.update() calls _reset_for_new_cbdr_cycle() when cbdr_key changes (new calendar day per the cbdr_day_key() logic)
Day key	state_manager.cbdr_day_key(dt, start_hour=22, end_hour=2) — but for REAL_CBDR the key uses start=19, end=1
12. Behavior After CBDR Window Closes
Aspect	Finding
Window close	When out_of_window and not cbdr.locked and cbdr.body_high > 0 → cbdr.lock() is called
After lock	check_sweep() is skipped (if self.bias_locked: return); only track_asia, track_london, track_ny continue
New day	At next 19:00 UTC, cbdr_day_key changes, _reset_for_new_cbdr_cycle() resets all state, and a new CBDR cycle begins
13. Symbol-Specific Overrides
Aspect	Finding
Profile lookup	get_session_hours(symbol) checks cfg.CBDR_RISK_MATRIX.get(symbol) first; if symbol has a profile, uses cfg.SESSION_HOURS[profile["session"]]
Default fallback	If symbol not in CBDR_RISK_MATRIX, returns {"start": 22, "end": 2} (DEFAULT profile)
REAL_CBDR symbols	Several USDT pairs have [REAL_CBDR] annotations in CBDR_RISK_MATRIX scores (e.g., APTUSDT, DOGEUSDT, etc.) but the hours profile is determined by the symbol's session profile, not the risk matrix
14. Relevant Tests
File	Behavior Tested
sniper/tests/test_integration.py:158,181,205,227,492	SessionState(start_hour=22, end_hour=2) — integration tests hardcode DEFAULT 22/2
sniper/tests/test_session.py:63-270	SessionState() with no args — uses constructor defaults (22/2)
sniper/tests/test_bot.py:77	isinstance(trader.states["BTCUSDT"], SessionState) — type check
sniper/tests/parity/test_parity_regression.py:174,258	SessionState(start_hour=sh, end_hour=eh) — parameterized tests
COMPARISON AGAINST SNIPER_FOREX SPEC
Component	Reference (REAL_CBDR 19:00-01:00 UTC)	SNIPER_FOREX Spec	Status
CBDR time window	19:00→01:00 UTC (4h spanning midnight, sh=19, eh=1)	UNRESOLVED — spec Section 2 defines sweep & bias lock but no time window	CONFLICT: spec does not define window; reference provides 19/1
Sweep definition	Body breaks range + closes back inside → liquidity sweep	Defined (spec Section 2): "A candle body breaks the CBDR body range and then closes back through/inside the relevant boundary"	SPEC DEFINED — matches reference
First sweep sets bias	Yes — first confirmed sweep sets daily_bias and bias_locked=True	Defined (spec Section 2): "First Confirmed Sweep of the Day determines daily_bias, opens bias_locked=True"	SPEC DEFINED — matches
Bias locked, no unlock	Yes — once locked, fixed for rest of day; subsequent sweeps skipped	Defined (spec Section 2): "Once Locked: daily_bias remains fixed for the rest of the trading day; Do NOT unlock/recalculate bias later in the same day"	SPEC DEFINED — matches
Tolerance calculation	0.5 × ATR or default 10.0	UNRESOLVED — spec Section 8 says "Apply existing epsilon/proximity rejection logic" but does not define epsilon/ATR formula	CONFLICT: spec references epsilon but does not define it; reference uses ATR-based tolerance
Daily reset	At next 19:00 UTC cycle	UNRESOLVED — spec Section 14 documents state machine states (DAILY_RESET, WAITING_FOR_SWEEP, BIAS_LOCKED, etc.) but does not define reset trigger	CONFLICT: spec documents states but not reset mechanism
Symbol-specific profiles	DEFAULT (22/2), REAL_CBDR (19/1), ASIA_RANGE (1/5) via config	UNRESOLVED — spec Section 16 proposes configuration table but not implemented	SPEC UNRESOLVED — configuration not yet built
UTC timezone assumption	Timestamps treated as UTC; no DST handling	UNRESOLVED — spec does not mention timezone; MT5 audit Step F concludes "timestamp semantics cannot be determined yet"	PENDING: needs human decision
CLASSIFICATION SUMMARY
Category	Determination
REFERENCE DEFINED	CBDR window (19:00-01:00 UTC), sweep detection, bias lock, reset behavior, tolerance formula, symbol profile selection
SPEC DEFINED	Sweep direction (bullish/bearish), first sweep determines bias, bias locked fixed for day, no unlock/recalc, entry = wick touch, SL = FVG boundary, TP = 1.8R
SPEC UNRESOLVED	CBDR time window, epsilon/ATR tolerance formula, daily reset trigger, timezone handling, symbol-specific configuration, trading-day boundary
CONFLICT	Spec references epsilon/proximity rejection (Sec 8) but does not define it; reference uses ATR-based tolerance; spec has no timezone assumptions; reference assumes UTC
STOP — Phase 2B.1 Extraction complete. No implementation code created, no specification modified, no commits or pushes. The extraction clearly distinguishes what the reference defines, what the spec defines, what is unresolved in the spec, and where conflicts exist that require human decisions.
