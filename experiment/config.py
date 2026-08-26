"""
Benchmark Config — NEXUS production parameters mirror.
NO optimization. NO parameter changes. ONLY FVG selection varies.
"""

# ── Risk ──────────────────────────────────────────────────────
INITIAL_BALANCE = 10000.0
RISK_PER_TRADE = 0.003
TP_RR = 1.8

# ── ATR ───────────────────────────────────────────────────────
ATR_PERIOD = 14

# ── Entry ─────────────────────────────────────────────────────
SL_ATR_MULT = 1.5
FVG_BUFFER_MULT = 0.50
FVG_BUFFER_MIN_FACTOR = 0.10
MIN_RISK_DIST_ATR_MULT = 0.1

# ── FVG ───────────────────────────────────────────────────────
FVG_MIN_SIZE_ATR_MULT = 0.06
FVG_WICK_RATIO_MAX = 0.75

# ── Trailing (inline from analyzer_v5.py — DO NOT CHANGE) ─────
ATR_TRAIL_MULT = 0.10
TRAIL_MIN_MOVE_MULT = 0.2
COMMISSION_RATE = 0.0005  # %0.05 taker fee each leg

# ── Session ───────────────────────────────────────────────────
SESSION_START_HOUR = 19  # CBDR window start (MT5 server time)
SESSION_END_HOUR = 1  # CBDR window end

# ── Symbols ───────────────────────────────────────────────────
# All 98 symbols from data/feather/
