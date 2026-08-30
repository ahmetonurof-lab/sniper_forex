#!/usr/bin/env python
"""Tests 5-10: targeted causality validation for event-based apply_dd_scaling."""

import sys

sys.path.insert(0, ".")
from experiment.main_research_c_v1_0 import BenchmarkTrade
from experiment.main_research_c_v1_1 import apply_dd_scaling, compute_dd_multiplier


def mk(trade_id, entry, exit, pnl, result="TP", symbol="TEST"):
    return BenchmarkTrade(
        trade_id=trade_id,
        symbol=symbol,
        test_type="POST_SWEEP_FVG",
        direction="bullish",
        entry_price=1.0,
        sl=0.99,
        tp=1.02,
        entry_bar_index=0,
        sweep_bar_index=0,
        zone_index=0,
        zone_creation_bar=0,
        zone_top=1.001,
        zone_bottom=0.999,
        zone_size=0.002,
        zone_size_atr=1.0,
        sweep_size_atr=0.5,
        bars_sweep_to_zone=0,
        bars_zone_to_entry=0,
        exit_price=1.0 + pnl * 0.01,
        exit_bar_index=0,
        exit_timestamp=exit,
        result=result,
        pnl_r=pnl,
    )


def mult_map(surv, trades):
    return {t.trade_id: t.pnl_r / t.pnl_r for s in surv for t in trades if s.trade_id == t.trade_id}


def get_mult(surviving, base):
    for s in surviving:
        for b in base:
            if s.trade_id == b.trade_id and s.symbol == b.symbol:
                return s.pnl_r / b.pnl_r
    return 0.0


def get_pnl(surviving, trade_id, symbol="TEST"):
    for s in surviving:
        if s.trade_id == trade_id and s.symbol == symbol:
            return s.pnl_r
    return None


# =====================================================================
# TEST 5 — MULTIPLE OVERLAPPING TRADES
# =====================================================================
print("TEST 5 — MULTIPLE OVERLAPPING TRADES")
A = mk(1, 9.0, 12.0, -3.0, "LOSS")
B = mk(2, 10.0, 11.0, -3.0, "LOSS")
C = mk(3, 10.5, 13.0, -1.0, "LOSS")

surv, paused, n1, n05, n025 = apply_dd_scaling([A, B, C], [9.0, 10.0, 10.5], 100.0)
# A entry 9.0: dd=0 -> x1; exit 12.0 updates equity to 97
# B entry 10.0: A hasn't exited (12.0 > 10.0) -> dd=0 -> x1; exit 11.0 -> equity=94
# C entry 10.5: A (12.0) and B (11.0) neither have exited -> dd=0 -> x1

mult_A = get_mult(surv, [A])
mult_B = get_mult(surv, [B])
mult_C = get_mult(surv, [C])
print(f"  mult_A={mult_A} mult_B={mult_B} mult_C={mult_C}")
print(f"  PASS={mult_A == 1.0 and mult_B == 1.0 and mult_C == 1.0}")

# =====================================================================
# TEST 6 — EXIT / ENTRY PARTIAL STATE UPDATE
# =====================================================================
print()
print("TEST 6 — EXIT / ENTRY PARTIAL STATE UPDATE")
A = mk(1, 9.0, 9.5, -3.0, "LOSS")
B = mk(2, 10.0, 10.5, 2.0, "TP")
C = mk(3, 11.0, 11.5, -1.0, "LOSS")

surv, p, n1, n05, n025 = apply_dd_scaling([A, B, C], [9.0, 10.0, 11.0], 100.0)
mult_A = get_mult(surv, [A])  # 1.0
mult_B = get_mult(surv, [B])  # DD=3R after A exit -> x0.5
mult_C = get_mult(surv, [C])  # DD=2R after B scaled (+1) -> x1 (not >2)

print(f"  mult_A={mult_A} mult_B={mult_B} mult_C={mult_C}")
expected = mult_A == 1.0 and mult_B == 0.5 and mult_C == 1.0
print(f"  PASS={expected}")

# =====================================================================
# TEST 7 — THRESHOLD BOUNDARIES
# =====================================================================
print()
print("TEST 7 — THRESHOLD BOUNDARIES")
# Create trades with specific DD values by controlling prior state
# We'll verify compute_dd_multiplier directly (already covered) and
# verify event model respects strict > (not >=)


def test_mult(dd):
    return compute_dd_multiplier(dd)


results = [
    (2.0, 1.0),
    (2.000001, 0.5),
    (4.0, 0.5),
    (4.000001, 0.25),
    (6.0, 0.25),
    (6.000001, 0.0),
]
all_ok = True
for dd, exp in results:
    got = test_mult(dd)
    ok = abs(got - exp) < 1e-9
    all_ok = all_ok and ok
    print(f"  DD={dd:>8.6f} -> mult={got} (expected={exp}) {'PASS' if ok else 'FAIL'}")
print(f"  OVERALL PASS={all_ok}")

# =====================================================================
# TEST 8 — PAUSED EXIT LATER, ZERO REALIZED
# =====================================================================
print()
print("TEST 8 — PAUSED TRADE EXIT LATER, ZERO")
# Start with high DD (>6) so first trade pauses, then verify it contributes 0
# We build a synthetic case: start at balance=100, but we inject a prior loss
# by creating a first trade that creates DD > 6.

# Trade 1: -3R (x1) -> equity=97, peak=100, dd=3
# Trade 2: -4R (x0.25) -> scaled -1, equity=96, peak=100, dd=4
# Trade 3: -3R -> dd at entry=4 (>2) -> x0.5, scaled=-1.5, equity=94.5, peak=100, dd=5.5
# Trade 4: -3R -> dd at entry=5.5 (>4) -> x0.25, scaled=-0.75, equity=93.75, peak=100, dd=6.25 -> PAUSE

# So trade 4 is paused. Its exit should contribute 0.
t1 = mk(1, 9.0, 9.5, -3.0, "LOSS")
t2 = mk(2, 10.0, 10.5, -4.0, "LOSS")
t3 = mk(3, 11.0, 11.5, -3.0, "LOSS")
t4 = mk(4, 12.0, 12.5, 3.0, "TP")  # Will be paused if DD > 6

# Actually let's build it so t4 sees DD > 6 explicitly
# t1: x1 -> -3 -> equity=97
# t2: DD=3 -> x0.5 -> -2 -> equity=95
# t3: DD=5 -> x0.25 -> -0.75 -> equity=94.25
# t4: DD=5.75 -> still >6? No, 5.75 < 6. So not paused.
# Let's make t2 larger loss

t1 = mk(1, 9.0, 9.5, -5.0, "LOSS")  # x1 -> equity=95, dd=5
# After t1: dd=5 (>4) so next is x0.25 but t2 is next at entry 10.0
# t2: -5R at entry 10.0 -> DD=5 (>4) -> x0.25 -> -1.25 -> equity=93.75, dd=6.25
# t3: +1R at entry 11.0 -> DD=6.25 (>6) -> PAUSE

t1 = mk(1, 9.0, 9.5, -5.0, "LOSS")
t2 = mk(2, 10.0, 10.5, -5.0, "LOSS")
t3 = mk(3, 11.0, 11.5, 2.0, "TP")

surv, p, n1, n05, n025 = apply_dd_scaling([t1, t2, t3], [9.0, 10.0, 11.0], 100.0)
mult_t1 = get_mult(surv, [t1])
mult_t2 = get_mult(surv, [t2])
mult_t3 = get_mult(surv, [t3])  # Should be 0 (paused), not in surviving

# Verify t3 is paused and its PnL doesn't affect future
print(f"  mult_t1={mult_t1} mult_t2={mult_t2}")
print(f"  paused={p} (expected at least 1)")
# Check t3 is NOT in surviving
in_surv = any(s.trade_id == 3 for s in surv)
print(f"  t3 in surviving={in_surv} (expected False)")
# Check that if we add t4 after t3, t4 doesn't see t3's base PnL
t4 = mk(4, 12.0, 12.5, 1.0, "TP")
surv_f, p_f, _, _, _ = apply_dd_scaling([t1, t2, t3, t4], [9.0, 10.0, 11.0, 12.0], 100.0)
mult_t4 = get_mult(surv_f, [t4])
# After t1 (x1, -5): equity=95, peak=100, dd=5
# t2 entry at 10.0: dd=5 > 4 -> x0.25, scaled=-1.25, equity=93.75
# t3 entry at 11.0: dd=6.25 > 6 -> PAUSE
# t4 entry at 12.0: dd=6.25 > 6 -> PAUSE (t3 contributes 0)
print(f"  mult_t4={mult_t4} (expected 0 since DD>6 still holds without t3)")
print(f"  PASS={not in_surv and p >= 1 and mult_t4 == 0.0}")

# =====================================================================
# TEST 9 — LOCKED MULTIPLIER MUST NOT CHANGE
# =====================================================================
print()
print("TEST 9 — LOCKED MULTIPLIER")
# A: entry 9.0, exit 12.0, -3R -> x1 (entry DD=0)
# B: entry 10.0, exit 11.0, +5R -> DD=0 at entry (A hasn't exited), but let's make it so B's entry sees low DD
# Actually let's make A exit first (at 9.5) with -3R so B sees DD > 2
# A entry 9.0, exit 9.5, -3R -> x1
# B entry 9.75, exit 10.5, +2R -> sees DD=3 (>2) -> x0.5, locked
# C entry 10.0, exit 10.25, -1R -> C entry is at 10.0, B exit at 10.5. So at C entry (10.0), B hasn't exited. C sees only A's exit (9.5): DD=3 -> x0.5
# But wait, we want C to enter AFTER B exits. Let's change:
# A entry 9.0, exit 9.5, -3R
# B entry 9.75, exit 10.0, +2R -> DD at entry = 3 (>2) -> x0.5
# C entry 10.25, exit 11.0, -1R -> B has exited (10.0 < 10.25), so C sees A (-3) + B scaled (+1) = -2, peak=100, dd=2 -> x1 (not >2, exactly 2)
# Actually dd = 100 - 98 = 2 -> not > 2 -> x1

A = mk(1, 9.0, 9.5, -3.0, "LOSS")
B = mk(2, 9.75, 10.0, 2.0, "TP")
C = mk(3, 10.25, 11.0, -1.0, "LOSS")

surv, p, _, _, _ = apply_dd_scaling([A, B, C], [9.0, 9.75, 10.25], 100.0)
mult_B = get_mult(surv, [B])
mult_C = get_mult(surv, [C])
# B locked at 0.5 at ENTRY (9.75), must stay 0.5 at EXIT (10.0) even though C hasn't entered yet
print(f"  mult_B={mult_B} mult_C={mult_C}")
print(f"  B scaled pnl={get_pnl(surv, 2)} (expected +1.0 = +2*0.5)")
print(f"  PASS={mult_B == 0.5 and get_pnl(surv, 2) == 1.0}")

# =====================================================================
# TEST 10 — TRADE ORDER INDEPENDENCE
# =====================================================================
print()
print("TEST 10 — TRADE ORDER INDEPENDENCE")
A = mk(1, 9.0, 10.0, -2.0, "LOSS", "A")
B = mk(2, 10.5, 11.0, 1.5, "TP", "B")
C = mk(3, 11.5, 12.0, -1.0, "LOSS", "C")


def run_in_order(trades, entries):
    return apply_dd_scaling(trades, entries, 100.0)


# Different orderings
orders = [
    ([A, B, C], [9.0, 10.5, 11.5]),
    ([C, B, A], [11.5, 10.5, 9.0]),
    ([B, A, C], [10.5, 9.0, 11.5]),
    ([A, C, B], [9.0, 11.5, 10.5]),
]

results = []
for trades, entries in orders:
    s, p, n1, n05, n025 = run_in_order(trades, entries)
    pnls = sorted([t.pnl_r for t in s])
    mults = sorted(
        [
            (t.trade_id, round(t.pnl_r / t.pnl_r, 4))
            for t in trades
            for s_obj in s
            if s_obj.trade_id == t.trade_id
        ]
    )
    results.append((str(pnls), p, n1, n05, n025))

# For the correct semantics, all should be identical regardless of input order
# because events are sorted by (entry, exit) timestamps
all_same = all(r == results[0] for r in results)
for i, r in enumerate(results):
    print(f"  order {i + 1}: surviving_pnls={r[0]} paused={r[1]} x1={r[2]} x05={r[3]} x025={r[4]}")
print(f"  PASS={all_same}")
