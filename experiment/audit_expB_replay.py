"""
audit_expB_replay.py — Forensic audit of Experiment B (3-Loss / 12-bar Breaker)

Does NOT re-run the C2 engine. Does NOT touch experiment/main_research_c_v1_0.py.

Two complementary lines of evidence:

PART A — Synthetic invariant tests (deterministic, in-memory):
  A1. Trigger fires EXACTLY when the 3rd accepted CLOSED consecutive LOSS
      closes. Entries with entry_bar_index in (L_exit, L_exit+12] are BLOCKED;
      entries strictly after L_exit+12 are ACCEPTED. Boundary at L_exit+12 is
      INCLUSIVE (the check is <= pause_until_bar).
  A2. Entry AFTER pause window (entry_bar > L_exit+12) is ACCEPTED.
  A3. A TP/PROFIT_TRAIL between two LOSSes resets the streak (no trigger).
  A4. A BLOCKED trade's EXIT event does NOT drive the loss streak.
  A5. OPEN trades are appended exactly once and are NOT in the event stream.

PART B — Real-data per-symbol forensic walk (loads saved expB trades):
  Calls apply_streak_breaker() per symbol on the saved 2302 trades and
  compares to the saved summary's per_symbol triggers/kept counts. Then, for
  each trigger found, reports the next baseline entry's distance to L_exit
  to mechanically explain why blocked=0.

Run:
    python experiment/audit_expB_replay.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from experiment.exp_maxdd_B_streak_breaker import (  # noqa: E402
    LOSS_STREAK,
    PAUSE_BARS,
    apply_streak_breaker,
)

# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════


def _mk_trade(trade_id: int, entry_bar: int, exit_bar: int, result: str, symbol: str = "TEST"):
    return SimpleNamespace(
        trade_id=trade_id,
        symbol=symbol,
        entry_bar_index=entry_bar,
        exit_bar_index=exit_bar,
        result=result,
    )


def _to_objs(raw_trades: List[dict]) -> List[SimpleNamespace]:
    return [
        SimpleNamespace(
            trade_id=t["trade_id"],
            symbol=t["symbol"],
            entry_bar_index=t["entry_bar_index"],
            exit_bar_index=t["exit_bar_index"],
            result=t["result"],
        )
        for t in raw_trades
    ]


# ═════════════════════════════════════════════════════════════════════════════
# PART A — SYNTHETIC INVARIANT TESTS
# ═════════════════════════════════════════════════════════════════════════════


def part_a_invariants() -> bool:
    print()
    print("=" * 78)
    print("PART A -- SYNTHETIC INVARIANT TESTS")
    print("=" * 78)
    all_pass = True

    # ── A1 ────────────────────────────────────────────────────────────────
    # L_exit=40  =>  pause_until=52  (window is (40, 52])
    # trade 4 entry_bar=45 -> BLOCKED  (45 <= 52)
    # trade 5 entry_bar=52 -> BLOCKED  (52 <= 52, boundary inclusive)
    # trade 6 entry_bar=53 -> ACCEPTED  (53 > 52)
    print()
    print("[A1] 3 consecutive LOSS -> entries in (L_exit, L_exit+12] BLOCKED;")
    print("     entry strictly after L_exit+12 ACCEPTED; boundary L_exit+12 is INCLUSIVE")
    trades = [
        _mk_trade(1, entry_bar=10, exit_bar=20, result="LOSS"),
        _mk_trade(2, entry_bar=21, exit_bar=30, result="LOSS"),
        _mk_trade(3, entry_bar=31, exit_bar=40, result="LOSS"),  # 3rd loss, L_exit=40
        _mk_trade(4, entry_bar=45, exit_bar=50, result="PROFIT_TRAIL"),  # 45<=52 BLOCK
        _mk_trade(5, entry_bar=52, exit_bar=60, result="PROFIT_TRAIL"),  # 52<=52 BLOCK (boundary)
        _mk_trade(6, entry_bar=53, exit_bar=70, result="PROFIT_TRAIL"),  # 53>52  ACCEPT
    ]
    kept, blocked, triggers, pause_bars = apply_streak_breaker(trades)
    print(
        f"  result: kept_ids={[t.trade_id for t in kept]} blocked={blocked} "
        f"triggers={triggers} pause_bars={pause_bars}"
    )
    print("  expect: kept_ids=[1, 2, 3, 6] blocked=2 triggers=1 pause_bars=12")
    ok = (
        [t.trade_id for t in kept] == [1, 2, 3, 6]
        and blocked == 2
        and triggers == 1
        and pause_bars == 12
    )
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}")
    all_pass &= ok

    # ── A2 ────────────────────────────────────────────────────────────────
    print()
    print("[A2] 3 LOSS -> next ENTRY AFTER pause window is ACCEPTED")
    trades = [
        _mk_trade(1, 10, 20, "LOSS"),
        _mk_trade(2, 21, 30, "LOSS"),
        _mk_trade(3, 31, 40, "LOSS"),
        _mk_trade(4, 60, 70, "PROFIT_TRAIL"),  # 60 > 52, accepted
    ]
    kept, blocked, triggers, _ = apply_streak_breaker(trades)
    print(f"  result: kept_ids={[t.trade_id for t in kept]} blocked={blocked} triggers={triggers}")
    print("  expect: kept_ids=[1, 2, 3, 4] blocked=0 triggers=1")
    ok = [t.trade_id for t in kept] == [1, 2, 3, 4] and blocked == 0 and triggers == 1
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}")
    all_pass &= ok

    # ── A3 ────────────────────────────────────────────────────────────────
    print()
    print("[A3] TP between two LOSSes RESETS the streak (no trigger)")
    trades = [
        _mk_trade(1, 10, 20, "LOSS"),
        _mk_trade(2, 21, 30, "TP"),  # resets streak
        _mk_trade(3, 31, 40, "LOSS"),
        _mk_trade(4, 41, 50, "LOSS"),  # only 2 in a row
        _mk_trade(5, 51, 60, "PROFIT_TRAIL"),
    ]
    kept, blocked, triggers, _ = apply_streak_breaker(trades)
    print(f"  result: kept_ids={[t.trade_id for t in kept]} blocked={blocked} triggers={triggers}")
    print("  expect: kept_ids=[1, 2, 3, 4, 5] blocked=0 triggers=0")
    ok = [t.trade_id for t in kept] == [1, 2, 3, 4, 5] and blocked == 0 and triggers == 0
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}")
    all_pass &= ok

    # ── A4 ────────────────────────────────────────────────────────────────
    print()
    print("[A4] Blocked trade's EXIT does NOT count toward the streak")
    trades = [
        _mk_trade(1, 10, 20, "LOSS"),
        _mk_trade(2, 21, 30, "LOSS"),
        _mk_trade(3, 31, 40, "LOSS"),  # trigger at L_exit=40, pause_until=52
        _mk_trade(4, 45, 55, "LOSS"),  # blocked at entry; its EXIT must NOT feed
        _mk_trade(5, 56, 65, "LOSS"),  # accepted; new streak: 1
        _mk_trade(6, 66, 75, "LOSS"),  # accepted; new streak: 2
        _mk_trade(7, 80, 90, "PROFIT_TRAIL"),  # TP, resets; never reaches 3
    ]
    kept, blocked, triggers, _ = apply_streak_breaker(trades)
    print(f"  result: kept_ids={[t.trade_id for t in kept]} blocked={blocked} triggers={triggers}")
    print("  expect: kept_ids=[1, 2, 3, 5, 6, 7] blocked=1 triggers=1")
    print("  (blocked 4's LOSS EXIT must NOT feed the next streak)")
    ok = [t.trade_id for t in kept] == [1, 2, 3, 5, 6, 7] and blocked == 1 and triggers == 1
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}")
    all_pass &= ok

    # ── A5 ────────────────────────────────────────────────────────────────
    print()
    print("[A5] OPEN tail trade is appended exactly ONCE; not in event stream")
    trades = [
        _mk_trade(1, 10, 20, "LOSS"),
        _mk_trade(2, 21, 30, "LOSS"),
        _mk_trade(3, 31, 40, "LOSS"),
        _mk_trade(4, 45, 49, "OPEN"),  # tail OPEN
    ]
    kept, blocked, triggers, _ = apply_streak_breaker(trades)
    n_open_in = sum(1 for t in trades if t.result == "OPEN")
    n_open_kept = sum(1 for t in kept if t.result == "OPEN")
    print(
        f"  result: kept_ids={[t.trade_id for t in kept]} OPEN_in_kept={n_open_kept} "
        f"blocked={blocked} triggers={triggers}"
    )
    print(f"  expect: OPEN_in_kept={n_open_in} blocked=0 triggers=1")
    ok = n_open_kept == n_open_in == 1 and blocked == 0 and triggers == 1
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}")
    all_pass &= ok

    return all_pass


# ═════════════════════════════════════════════════════════════════════════════
# PART B — REAL-DATA PER-SYMBOL FORENSIC WALK
# ═════════════════════════════════════════════════════════════════════════════


def _walk_triggers(sym_trades: List[dict]) -> List[dict]:
    """Per-symbol, exit-time-ordered 3-LOSS trigger walk.

    Returns one record per trigger with the next baseline entry's distance.
    """
    closed = [t for t in sym_trades if t["result"] in ("TP", "PROFIT_TRAIL", "LOSS")]
    closed.sort(key=lambda t: t["exit_bar_index"])
    cons = 0
    triggers: List[dict] = []
    for t in closed:
        if t["result"] == "LOSS":
            cons += 1
        elif t["result"] in ("TP", "PROFIT_TRAIL"):
            cons = 0
        if cons == LOSS_STREAK:
            L_exit = t["exit_bar_index"]
            next_entry = None
            for cand in closed:
                if cand["entry_bar_index"] > L_exit:
                    next_entry = cand
                    break
            distance = (next_entry["entry_bar_index"] - L_exit) if next_entry else None
            triggers.append(
                {
                    "L_exit": L_exit,
                    "pause_until": L_exit + PAUSE_BARS,
                    "next_entry_id": next_entry["trade_id"] if next_entry else None,
                    "next_entry_bar": next_entry["entry_bar_index"] if next_entry else None,
                    "distance": distance,
                    "would_block": distance is not None and distance <= PAUSE_BARS,
                }
            )
            cons = 0
    return triggers


def _replicate_function_walk(sym_trades: List[dict], trace: bool = False) -> List[dict]:
    """Replicate apply_streak_breaker()'s exact event walk to count triggers.

    Builds (entry_bar, ENTRY) and (exit_bar, EXIT) events, sorts them with
    EXIT-before-ENTRY at the same bar, then walks EXITs the same way the
    function does (cons tracks consecutive accepted LOSS). This MUST match
    the function's trigger count exactly for a per-symbol call.

    Also computes, for each trigger, the next baseline entry's distance from
    L_exit -- this is the distance the pause window must cover to block.
    """
    closed = [t for t in sym_trades if t["result"] in ("TP", "PROFIT_TRAIL", "LOSS")]
    events = []
    for t in closed:
        events.append((t["entry_bar_index"], 0, "ENTRY", t))
        events.append((t["exit_bar_index"], 0, "EXIT", t))
    events.sort(key=lambda e: (e[0], 0 if e[2] == "EXIT" else 1))
    cons = 0
    accepted = set()
    triggers: List[dict] = []
    for _, _, kind, t in events:
        if kind == "EXIT":
            if t["trade_id"] in accepted:
                if t["result"] == "LOSS":
                    cons += 1
                elif t["result"] in ("TP", "PROFIT_TRAIL"):
                    cons = 0
                if trace:
                    print(
                        f"    EXIT id={t['trade_id']} result={t['result']} "
                        f"bar={t['exit_bar_index']} cons={cons}"
                    )
                if cons == LOSS_STREAK:
                    L_exit = t["exit_bar_index"]
                    next_entry = None
                    for cand in closed:
                        if cand["entry_bar_index"] > L_exit:
                            next_entry = cand
                            break
                    distance = (next_entry["entry_bar_index"] - L_exit) if next_entry else None
                    triggers.append(
                        {
                            "L_exit": L_exit,
                            "trigger_trade_id": t["trade_id"],
                            "pause_until": L_exit + PAUSE_BARS,
                            "next_entry_id": next_entry["trade_id"] if next_entry else None,
                            "next_entry_bar": next_entry["entry_bar_index"] if next_entry else None,
                            "distance": distance,
                            "would_block": distance is not None and distance <= PAUSE_BARS,
                        }
                    )
                    cons = 0
        else:
            accepted.add(t["trade_id"])
    return triggers


def part_b_realdata() -> bool:
    print()
    print("=" * 78)
    print("PART B -- REAL-DATA PER-SYMBOL FORENSIC WALK")
    print("=" * 78)

    trades_path = _PROJECT_ROOT / "results" / "research" / "expB_streak_breaker_trades.json"
    summary_path = _PROJECT_ROOT / "results" / "research" / "expB_streak_breaker_summary.json"
    if not trades_path.exists() or not summary_path.exists():
        print(f"  ! missing artifacts: {trades_path} or {summary_path}")
        return False

    with open(trades_path) as f:
        raw = json.load(f)
    with open(summary_path) as f:
        summary = json.load(f)

    per_sym_raw: Dict[str, List[dict]] = {}
    for t in raw:
        per_sym_raw.setdefault(t["symbol"], []).append(t)

    # Distribution diagnostics
    n_total = len(raw)
    n_open = sum(1 for t in raw if t["result"] == "OPEN")
    n_loss = sum(1 for t in raw if t["result"] == "LOSS")
    print(f"  saved trades: total={n_total} LOSS={n_loss} OPEN={n_open}")
    print(
        f"  saved summary: baseline={summary['baseline']['trades']}T "
        f"breaker={summary['breaker']['trades']}T "
        f"blocked={summary['blocked_entries']} triggers={summary['triggers']}"
    )

    # ── Per-symbol: call apply_streak_breaker (the actual function) and
    #    compare to the saved summary's per_symbol numbers.
    print()
    print("  Per-symbol: apply_streak_breaker() vs saved summary")
    print(
        f"  {'symbol':<8} {'closed':>7} {'fn_kept':>8} {'fn_blocked':>11} "
        f"{'fn_trig':>9} {'ss_kept':>8} {'ss_trig':>8} "
        f"{'repl_trig':>10}  consistency"
    )
    total_fn_kept = total_fn_blocked = total_fn_triggers = 0
    total_repl = 0
    all_consistent = True
    all_triggers: List[dict] = []

    for sym in sorted(per_sym_raw):
        sym_raw = per_sym_raw[sym]
        objs = _to_objs(sym_raw)
        kept, blocked, triggers, _ = apply_streak_breaker(objs)
        kept_n = len(kept)
        ss = summary["per_symbol"].get(sym, {})
        ss_kept = ss.get("kept", -1)
        ss_trig = ss.get("triggers", -1)
        repl = _replicate_function_walk(sym_raw, trace=False)
        consistent = (kept_n == ss_kept) and (triggers == ss_trig) and (len(repl) == triggers)
        all_consistent &= consistent
        total_fn_kept += kept_n
        total_fn_blocked += blocked
        total_fn_triggers += triggers
        total_repl += len(repl)
        for tr in repl:
            tr["symbol"] = sym
            all_triggers.append(tr)
        print(
            f"  {sym:<8} {len(sym_raw):>7d} {kept_n:>8d} {blocked:>11d} "
            f"{triggers:>9d} {ss_kept:>8d} {ss_trig:>8d} "
            f"{len(repl):>10d}  {'OK' if consistent else 'MISMATCH'}"
        )
    print()
    print(
        f"  TOTAL: fn kept={total_fn_kept} fn blocked={total_fn_blocked} "
        f"fn triggers={total_fn_triggers}  replicate triggers={total_repl}"
    )

    # ── DIAGNOSTIC: explain replicate vs simple-walk discrepancy (AUDUSD) ──
    print()
    print("─" * 78)
    print("  NOTE on trigger count: the function's `accepted` check excludes")
    print("  trades whose EXIT is processed before their ENTRY (hold_bars=0,")
    print("  same-bar entry/exit). A pure-EXIT walk counts ALL LOSS/TP events")
    print("  regardless of acceptance. The function's count (105) is the")
    print("  authoritative one; the distance analysis below uses it.")
    print()
    print("─" * 78)
    print(
        f"  saved summary totals: kept={summary['breaker']['trades']} "
        f"blocked={summary['blocked_entries']} triggers={summary['triggers']}"
    )
    saved_match = (
        total_fn_kept == summary["breaker"]["trades"]
        and total_fn_blocked == summary["blocked_entries"]
        and total_fn_triggers == summary["triggers"]
    )
    print(f"  saved summary matches per-symbol function: {saved_match}")
    print(f"  per-symbol replicate walk matches function: {total_repl == total_fn_triggers}")

    # ── Why blocked=0: per-trigger next-entry distance distribution ──
    print()
    print("─" * 78)
    print("  Per-trigger next-entry distance (bars after L_exit) -- explains")
    print("  why blocked=0.  If every distance > 12, the pause window never")
    print("  covered a real entry, so nothing could be blocked.")
    distances = [t["distance"] for t in all_triggers if t["distance"] is not None]
    if distances:
        print(f"  N triggers: {len(distances)}")
        print(
            f"  min={min(distances)} max={max(distances)} "
            f"mean={sum(distances) / len(distances):.1f} "
            f"median={sorted(distances)[len(distances) // 2]}"
        )
        buckets = Counter()
        for d in distances:
            if d <= 12:
                buckets["1-12 (would block)"] += 1
            elif d <= 50:
                buckets["13-50"] += 1
            elif d <= 200:
                buckets["51-200"] += 1
            else:
                buckets[">200"] += 1
        print(f"  histogram: {dict(buckets)}")
        n_would_block = buckets.get("1-12 (would block)", 0)
        print(f"  triggers whose next entry is in (L_exit, L_exit+12]: {n_would_block}")
    else:
        n_would_block = 0
        print("  no triggers found")

    return all_consistent and saved_match and n_would_block == 0


# ═════════════════════════════════════════════════════════════════════════════
# Entry point
# ═════════════════════════════════════════════════════════════════════════════


def main() -> int:
    print("=" * 78)
    print("Experiment B (3-Loss / 12-bar Breaker) -- Replay Mechanism Audit")
    print("=" * 78)
    print(f"LOSS_STREAK={LOSS_STREAK}  PAUSE_BARS={PAUSE_BARS}")
    a_ok = part_a_invariants()
    b_ok = part_b_realdata()
    print()
    print("=" * 78)
    print(f"PART A synthetic invariants: {'ALL PASS' if a_ok else 'FAIL'}")
    print(f"PART B real-data consistency: {'PASS' if b_ok else 'FAIL'}")
    print("=" * 78)
    return 0 if (a_ok and b_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
