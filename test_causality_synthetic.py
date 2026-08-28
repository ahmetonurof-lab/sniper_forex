"""
Synthetic causality tests for apply_dd_scaling ENTRY-time DD semantics.
Verifies:
  1. Overlapping trades (B enters while A still open)
  2. Same timestamp strict causality (exit < entry, not <=)
  3. Scaled realized PnL in DD state
  4. Paused trade zero contribution
"""
import sys
sys.path.insert(0, 'C:/Users/Administrator/Desktop/sniper_forex')
from experiment.main_research_c_v1_1 import apply_dd_scaling, compute_dd_multiplier, _to_float_ts
from experiment.main_research_c_v1_0 import BenchmarkTrade


def mk_trade(trade_id, entry_ts, exit_ts, pnl_r, result='TP', symbol='TEST'):
    return BenchmarkTrade(
        trade_id=trade_id, symbol=symbol, test_type='POST_SWEEP_FVG',
        direction='bullish', entry_price=1.0, sl=0.99, tp=1.02,
        entry_bar_index=0, sweep_bar_index=0, zone_index=0,
        zone_creation_bar=0, zone_top=1.001, zone_bottom=0.999,
        zone_size=0.002, zone_size_atr=1.0, sweep_size_atr=0.5,
        bars_sweep_to_zone=0, bars_zone_to_entry=0,
        exit_price=1.0 + pnl_r * 0.01, exit_bar_index=0,
        exit_timestamp=exit_ts, result=result, pnl_r=pnl_r,
    )


def reference_apply_dd_scaling(trades, entry_ts, starting_balance=100.0):
    """Event-based reference: ENTRY before EXIT at same timestamp.
    ENTRY: read dd, compute mult, store in trade.
    EXIT: if mult>0: equity+=base*mult, peak=max; if paused: nothing.
    """
    completed = [(t, float(e)) for t, e in zip(trades, entry_ts)
                 if t.result in ('TP', 'PROFIT_TRAIL', 'LOSS')]

    # ENTRY events: (ts, 0=ENTRY, trade, entry_float)
    # EXIT events:  (ts, 1=EXIT,  trade, None)
    events = []
    for t, e in completed:
        events.append((float(e),  0, t, float(e)))  # ENTRY
        events.append((_to_float_ts(t.exit_timestamp), 1, t, None))  # EXIT
    events.sort(key=lambda x: (x[0], x[1]))  # timestamp asc, ENTRY(0) before EXIT(1) at same ts

    equity = starting_balance
    peak = starting_balance
    surviving = []
    paused = 0
    n_x1 = n_x05 = n_x025 = 0
    trade_mult = {}

    for ts, etype, t, _ in events:
        if etype == 0:  # ENTRY
            dd_now = peak - equity
            mult = compute_dd_multiplier(dd_now)
            trade_mult[(t.symbol, t.trade_id)] = mult
            if mult == 0.0:
                paused += 1
            elif mult == 1.0:
                n_x1 += 1
            elif mult == 0.5:
                n_x05 += 1
            else:
                n_x025 += 1
        else:  # EXIT
            mult = trade_mult.get((t.symbol, t.trade_id))
            if mult is None:
                continue
            if mult > 0:
                scaled_pnl = t.pnl_r * mult
                equity += scaled_pnl
                if equity > peak:
                    peak = equity
                sc = BenchmarkTrade(**t.__dict__)
                sc.pnl_r = scaled_pnl
                surviving.append(sc)
            # mult == 0 (paused): nothing recorded

    return surviving, paused, n_x1, n_x05, n_x025


def get_mult(surviving_trades, base_trade):
    for t in surviving_trades:
        if t.symbol == base_trade.symbol and t.trade_id == base_trade.trade_id:
            return t.pnl_r / base_trade.pnl_r
    return 0.0


print('=' * 70)
print('TEST 1 — OVERLAPPING TRADES')
print('=' * 70)
# A: ENTRY=9.0, EXIT=12.0, -5R (still open when B enters)
# B: ENTRY=10.0, EXIT=11.0, -1R (B enters while A is still open => DD=0 => x1)
tA = mk_trade(1, 9.0, 12.0, -5.0, 'LOSS', 'A')
tB = mk_trade(2, 10.0, 11.0, -1.0, 'LOSS', 'B')

cur_s, cur_p, _, _, _ = apply_dd_scaling([tA, tB], [9.0, 10.0], 100.0)
ref_s, ref_p, _, _, _ = reference_apply_dd_scaling([tA, tB], [9.0, 10.0], 100.0)

b_cur = get_mult(cur_s, tB)
b_ref = get_mult(ref_s, tB)
print(f'  B mult (current):  {b_cur}  (expected 1.0)')
print(f'  B mult (reference): {b_ref}  (expected 1.0)')
print(f'  TEST 1: {"PASS" if abs(b_cur - 1.0) < 1e-9 else "FAIL"}')


print()
print('=' * 70)
print('TEST 2 — SAME TIMESTAMP STRICT CAUSALITY')
print('=' * 70)
# A: ENTRY=9.0, EXIT=10.0, -5R
# B: ENTRY=10.0, EXIT=11.0, -1R
# A exits at 10.0 == B enters at 10.0 => strict < excludes A from B
tA2 = mk_trade(1, 9.0, 10.0, -5.0, 'LOSS', 'A')
tB2 = mk_trade(2, 10.0, 11.0, -1.0, 'LOSS', 'B')

cur_s2, _, _, _, _ = apply_dd_scaling([tA2, tB2], [9.0, 10.0], 100.0)
ref_s2, _, _, _, _ = reference_apply_dd_scaling([tA2, tB2], [9.0, 10.0], 100.0)

b2_cur = get_mult(cur_s2, tB2)
b2_ref = get_mult(ref_s2, tB2)
print(f'  B mult (current):  {b2_cur}  (expected 1.0)')
print(f'  B mult (reference): {b2_ref}  (expected 1.0)')
print(f'  TEST 2: {"PASS" if abs(b2_cur - 1.0) < 1e-9 else "FAIL"}')


print()
print('=' * 70)
print('TEST 3 — SCALED REALIZED PNL IN DD STATE')
print('=' * 70)
# A: entry=9, exit=10, -3R => x1, realized=-3R => equity=97, peak=100, dd=3R
# B: entry=11, exit=12, +2R => sees dd=3R => x0.5, realized=+1R => equity=98, peak=100
# C: entry=13, exit=14, +1R => sees dd=2R => x0.5, realized=+0.5R
tA3 = mk_trade(1, 9.0, 10.0, -3.0, 'LOSS', 'A')
tB3 = mk_trade(2, 11.0, 12.0, 2.0, 'TP', 'B')
tC3 = mk_trade(3, 13.0, 14.0, 1.0, 'TP', 'C')

cur_s3, _, _, _, _ = apply_dd_scaling([tA3, tB3, tC3], [9.0, 11.0, 13.0], 100.0)
ref_s3, _, _, _, _ = reference_apply_dd_scaling([tA3, tB3, tC3], [9.0, 11.0, 13.0], 100.0)

print(f'  Current surviving:  {[round(t.pnl_r,4) for t in cur_s3]}')
print(f'  Reference surviving: {[round(t.pnl_r,4) for t in ref_s3]}')
print(f'  Expected: A=-3R, B=+1R (scaled), C=+0.5R (scaled)')

# Check individual
cur_A = get_mult(cur_s3, tA3)
cur_B = get_mult(cur_s3, tB3)
cur_C = get_mult(cur_s3, tC3)
ref_A = get_mult(ref_s3, tA3)
ref_B = get_mult(ref_s3, tB3)
ref_C = get_mult(ref_s3, tC3)

print(f'  A mult: cur={cur_A} ref={ref_A}  (expected 1.0)')
print(f'  B mult: cur={cur_B} ref={ref_B}  (expected 0.5 — uses +1R NOT +2R in DD state)')
print(f'  C mult: cur={cur_C} ref={ref_C}  (expected 0.5)')
t3_ok = (abs(cur_A-1.0)<1e-9 and abs(cur_B-0.5)<1e-9 and abs(cur_C-0.5)<1e-9)
print(f'  TEST 3: {"PASS" if t3_ok else "FAIL"}')


print()
print('=' * 70)
print('TEST 4 — PAUSED TRADE ZERO REALIZED CONTRIBUTION')
print('=' * 70)
# t1: -3R x1 => equity=97, peak=100, dd=3R
# t2: -3R x1 => equity=94, peak=100, dd=6R
# t3: entry sees dd=6R => DD_T3=6 => PAUSE => mult=0 => equity stays 94
# t4: entry sees dd=6R (paused contributed 0) => x0.25 => realized +0.5R
t1 = mk_trade(1, 9.0, 10.0, -3.0, 'LOSS', 'A')
t2 = mk_trade(2, 11.0, 12.0, -3.0, 'LOSS', 'B')
t3 = mk_trade(3, 13.0, 14.0, 5.0, 'TP', 'C')   # PAUSE
t4 = mk_trade(4, 15.0, 16.0, 2.0, 'TP', 'D')   # x0.25

cur_s4, cur_p4, cur_n1, cur_n05, cur_n025 = apply_dd_scaling(
    [t1, t2, t3, t4], [9.0, 11.0, 13.0, 15.0], 100.0)
ref_s4, ref_p4, ref_n1, ref_n05, ref_n025 = reference_apply_dd_scaling(
    [t1, t2, t3, t4], [9.0, 11.0, 13.0, 15.0], 100.0)

t4_cur = get_mult(cur_s4, t4)
t4_ref = get_mult(ref_s4, t4)
print(f'  Paused count: cur={cur_p4} ref={ref_p4}  (expected 1)')
print(f'  t4 mult:      cur={t4_cur}  ref={t4_ref}  (expected 0.25)')
print(f'  Current surviving:  {[round(t.pnl_r,4) for t in cur_s4]}')
print(f'  Reference surviving: {[round(t.pnl_r,4) for t in ref_s4]}')
print(f'  Expected: t1=-3R, t2=-3R, t4=+0.5R  (t3 paused, contributes nothing)')
t4_ok = (cur_p4 == 1 and abs(t4_cur - 0.25) < 1e-9)
print(f'  TEST 4: {"PASS" if t4_ok else "FAIL"}')


print()
print('=' * 70)
print('OVERALL SUMMARY')
print('=' * 70)
t1_pass = abs(b_cur - 1.0) < 1e-9
t2_pass = abs(b2_cur - 1.0) < 1e-9
t3_pass = t3_ok
t4_pass = t4_ok

print(f'  Test 1 (Overlapping):      {"PASS" if t1_pass else "FAIL"}')
print(f'  Test 2 (Same timestamp):   {"PASS" if t2_pass else "FAIL"}')
print(f'  Test 3 (Scaled realized):  {"PASS" if t3_pass else "FAIL"}')
print(f'  Test 4 (Paused zero):       {"PASS" if t4_pass else "FAIL"}')
print()

all_match = (abs(b_cur - b_ref) < 1e-9 and
             abs(b2_cur - b2_ref) < 1e-9 and
             cur_p4 == ref_p4 and
             len(cur_s4) == len(ref_s4) and
             all(abs(cur_s4[i].pnl_r - ref_s4[i].pnl_r) < 1e-9 for i in range(len(cur_s4))))

print(f'  Current == Reference (all 4 tests): {all_match}')
if not all_match:
    print('  *** DIVERGENCE: current implementation differs from reference! ***')
    if t1_pass and t2_pass and t3_pass and t4_pass:
        print('  BUT: All tests pass — reference agrees with current on these cases.')
else:
    print('  Implementation matches event-based reference.')
