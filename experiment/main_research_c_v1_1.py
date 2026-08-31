"""
main_research_c_v1_1.py — Research C engine v1.1: C2 EQ + DD-Based Risk Scaling

=============================================================================
ARBITRATION SUPERSESSION BANNER (2026-08-31 — read this FIRST)
=============================================================================
The DD-scaling SEMANTICS below have changed twice AFTER the 2026-08-28
promotion, silently, without disclosure (AGENTS.md §8.1 provenance break):

  - 0899b38 (promotion): DOUBLE-curve pre_scale/post_scale DD, bisect
    pointer walk -> 2300T / paused 2 / +2766.91R / MaxDD 4.71R / PF 5.13.
  - 797d946: strict causality + _trade_order_key -> 2299T / paused 3 /
    MaxDD 6.29R (a second silent number change, undisclosed).
  - 409fc17 == HEAD: SINGLE-curve live event-stream walk (equity advances
    ONLY by accepted trades' SCALED pnl at EXIT; paused contribute ZERO;
    multiplier locked at ENTRY) -> 2302T / paused 0.

A parity probe (gate ③) proved the difference is in the SEMANTICS, not the
test fixtures. The referee (Hakem) arbitration ruled option (b): the
SINGLE-CURVE semantics are CANONICAL because they match the live trading
module `src/live/portfolio_dd.py` (record_realized is called only after a
closed position; a paused trade never calls it). The old "PROMOTED" figures
(2300T/+2766.91R/4.71R/PF 5.13) are QUARANTINED and must NOT be cited as
canonical until the benchmark is re-run under HEAD semantics with the
provenance package (engine commit + semantic declaration + config + dataset
hashes in `memory-bank/dataset_manifest_v1.1.md`).

The algorithm actually implemented at HEAD is the SINGLE-CURVE event-stream
walk described in the CAUSALITY section below. The "pointer-free bisect
refactor" labels in the historical sections are the SUPERSEDED 0899b38/797d946
semantics, retained only so the correction chain stays visible (§12.1).

=============================================================================
PROMOTION HEADER (PROMOTED 2026-08-28 — figures QUARANTINED, see banner)
=============================================================================
- Engine:          C v1.1 (CANONICAL research engine, version 1.1)
- Parent:          C v1.0  (`experiment/main_research_c_v1_0.py`, FROZEN baseline)
- Variant:         DD-Based Risk Scaling overlay (global portfolio)
- Promotion source:`experiment/exp_maxdd_C_dd_risk_scaling.py`
                   (corrected 2026-08-28 — see provenance section)
- Status:          PROMOTED. The old "pending promotion" / "candidate"
                   status is REMOVED. C v1.1 is the canonical reference
                   for the C2 + DD Scaling research line.
- Authoritative
  benchmark (C v1.0
  baseline, 2.7Y / 6 majors
  / 15m / full):       Trades 2302, WR 69.37%, TotalR +2875.00,
                      AvgR +1.2489, PF 5.08, MaxDD 8.00R, MaxDD% 2.73%
- Authoritative
  benchmark (C v1.1
  with DD scaling,   6 majors / 2.7Y / 15m / full -- see the live run output
  pointer-free       below for exact Trades / WR / TotalR / PF / MaxDD. The
  bisect refactor:   canonical figures are produced by
                     `python experiment/main_research_c_v1_1.py` and saved to
                     results/research/c_v1_1_summary.json.
- Scaling event
  distribution
  (C v1.1):          reported by the benchmark run (x1.0 / x0.5 / x0.25 /
                     paused counts printed on the [C v1.1] summary line).
- Paused set / trade
  identity:          NOT a fixed set -- determined by the strictly-before-entry
                     DD query at each trade's entry (see CAUSALITY section).

This is NOT a re-implementation. The C v1.0 trade-generation core
(sweep → FVG → C2 EQ → first touch → next-bar-open entry → SL/TP →
trailing → exit) is preserved BY IMPORT. The verified DD Risk
Scaling overlay is embedded as an in-line, post-trade-risk attribution
layer.

=============================================================================
INVALIDATED OLD EXP C REFERENCE
=============================================================================
The earlier Exp C reference numbers
(Trades 2302, paused 0, MaxDD% 1.85, PF 5.13, TotalR ≈ +2823R)
were an ARTIFACT of a cross-symbol `entry_ts_map` bug in
`experiment/exp_maxdd_C_dd_risk_scaling.py` (Phase 1, 2026-08-28):

  - `run_test_a` resets its per-symbol `trade_counter` to 0 on every
    call, so `trade_id` is NOT globally unique across symbols.
  - The old `entry_ts_map = { t.trade_id: ... }` keyed by `trade_id`
    only, so 1895/2302 trades (82%) received a cross-symbol-contaminated
    `entry_ts` value.
  - The contamination happened to produce 0 paused, MaxDD 8.00R,
    MaxDD% 1.85% — those numbers are an artifact, NOT the real
    behavior.
  - Phase 1 fixed the bug (per-symbol lookup) and re-ran the full
    benchmark. The corrected Exp C result (Trades 2300, paused 2,
    MaxDD 4.71R, MaxDD% 2.19%) was itself later SUPERSEDED by the
    pointer-free bisect refactor (see CAUSALITY section): the deterministic
    ordering and strictly-before-entry causality now produce the canonical
    C v1.1 figures printed by `python experiment/main_research_c_v1_1.py`.

The 1.85% MaxDD% number is INVALIDATED. The 2.19%/4.71R "corrected Exp C"
figures are ALSO superseded by the pointer-free bisect refactor (exact
current figures come from the live benchmark run).

=============================================================================
WHAT CHANGED VS C v1.0
=============================================================================
ONE isolated change: a per-trade `pnl_r` scaling layer based on the
realized portfolio drawdown at the trade's entry time, applied
GLOBALLY across the 6-major merged trade stream.

- C v1.0 contributes each trade's `pnl_r` (= ±1R SL-relative) directly
  to the equity curve. That is a 1R-per-trade fixed risk model.
- C v1.1 multiplies each accepted trade's `pnl_r` by a multiplier
  derived from the portfolio DD observed BEFORE that trade's entry:
      DD > 6R  -> PAUSE   (trade excluded; 0 paused on the canonical
                           single-curve stream — the old "2 paused" figure
                           belonged to the quarantined 0899b38 semantics)
      DD > 4R  -> x0.25
      DD > 2R  -> x0.50
      else     -> x1.00

  The scaling is applied to the trade's CONTRIBUTION to the equity
  curve (pnl_r is what would have been added to realized equity). It
  does NOT modify:
    - the trade's existence,
    - the trade's entry / exit prices,
    - the trade's SL / TP,
    - the trade's result type (TP / LOSS / PROFIT_TRAIL / OPEN),
    - the trade's exit timestamp / exit_bar_index,
    - the underlying entry/SL/TP/trailing/exit logic.

=============================================================================
 NO-LOOKAHEAD / SAME-BAR CAUSALITY  (single-curve event-stream semantics)
=============================================================================
The scaling walks ONE global realized-equity curve via an event stream
(each completed trade emits an ENTRY event at its entry_ts and an EXIT
event at its exit_ts; events are ordered by
`(timestamp, ENTRY-before-EXIT, symbol, trade_id)` — see
`apply_dd_scaling`).

  - At a trade's ENTRY, the multiplier is computed from the CURRENT
    realized DD (`dd = peak - equity`) and LOCKED for that trade; only
    prior EXIT events have advanced equity/peak, so a trade is scaled
    exclusively by trades that CLOSED STRICTLY BEFORE its entry
    (`exit_timestamp < entry_timestamp` -- strict `<`; same-timestamp
    ENTRY-before-EXIT ordering enforces the strictness).
  - At a trade's EXIT, the LOCKED multiplier is applied: the SCALED pnl
    (`base_pnl_r x mult`) is added to equity/peak. A PAUSED trade
    (mult == 0) contributes ZERO to the realized state — exactly the
    production semantics of `src/live/portfolio_dd.py`, where
    `record_realized(pnl_r)` is called only after a closed position.
  - The current trade is excluded from its own DD by construction: its
    ENTRY event precedes its EXIT event at the same timestamp, and its
    EXIT is the only event that mutates equity.

RUNTIME INVARIANT (arbitration (b), 2026-08-31): `entry_ts <= exit_ts`
for every completed trade — enforced (ValueError, not assert) inside
`apply_dd_scaling`. A backdated exit would flip the ENTRY/EXIT order and
silently drop the trade; that silent-drop branch is now a counted,
audit-ERROR-logged, hard-fail path (`_enforce_dropped_signal_policy`,
`MAX_DROPPED_SIGNALS = 0`).

Deterministic tie-break for identical timestamps is
`(symbol, trade_id)`; this is stable across sessions/threads/platforms.

=============================================================================
GLOBAL PORTFOLIO DD (per-symbol entry_ts is preserved)
=============================================================================
The scaling is applied to the MERGED 6-major trade stream (not
per-symbol). Each trade keeps its OWN entry timestamp (derived from
its own symbol's `bars_15m[entry_bar_index].timestamp`) and the
global equity/peak are walked in chronological `exit_timestamp`
order. Per-symbol entry_ts is NEVER cross-contaminated: the lookup
key is `(t.symbol, t.entry_bar_index)`, not `t.trade_id`.

=============================================================================
BEHAVIORAL INVARIANTS (unchanged from C v1.0)
=============================================================================
- 15m construction: identical (M1 → resample_15m, no change here; live
                    ingestion is exercised at the live layer, not the
                    research engine).
- ATR: 14-period Wilder update, computed on bars_15m[:warmup] initially.
- CBDR session window: 19:00→01:00 (server time, spans midnight).
- Sweep detection: SessionManager.update() — IDENTICAL.
- Bias lock: post-sweep — IDENTICAL.
- FVG detection: nexus `detect_fvgs()` — IDENTICAL.
- FVG freshness: `_is_fresh_fvg()` — IDENTICAL.
- C2 EQ formula: eq = (sweep_price + leg_mid) / 2 — IDENTICAL.
- EQ gate: entire FVG on correct side of EQ — IDENTICAL.
- First-touch: bar.low ≤ fvg.top (bullish) / bar.high ≥ fvg.bottom (bearish)
              within ±0.1*ATR — IDENTICAL.
- Next-bar-open execution: entry_price = bars_15m[i+1].open — IDENTICAL.
- SL placement: rp2 = atr * SL_ATR_MULT (1.5); buffer = max(MIN, min(0.25*fh,
               BUFFER_MULT * rp2)) — IDENTICAL.
- TP placement: TP_RR (1.8) × risk distance — IDENTICAL.
- Trailing: `experiment.trailing_adapter.apply_trailing` (1.8R) — IDENTICAL.
- Exit chronology: exit_timestamp-ordered equity curve — IDENTICAL.
- Starting balance: 100R — IDENTICAL.

=============================================================================
USAGE
=============================================================================
The canonical C v1.1 (with DD Risk Scaling) is produced by `main()`,
which:
  1. runs C v1.0 base for all 6 majors (or symbols passed via argv),
  2. merges the base trade streams with per-symbol `entry_ts`,
  3. calls `apply_dd_scaling()` exactly once on the merged stream,
  4. computes stats on the same scaled stream.

Single-symbol helpers (base only, no scaling — for per-symbol
debugging or local inspection):

  from experiment.main_research_c_v1_1 import run_test_a_v11
  base_trades = run_test_a_v11("EURUSD", bars_15m)  # unscaled base

Or via the 6-major worker:

  python experiment/main_research_c_v1_1.py
  python experiment/main_research_c_v1_1.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_logger = logging.getLogger("experiment.main_research_c_v1_1")

# ── Setup paths ──
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# Import the FROZEN C v1.0 engine (UNTOUCHED). We re-use its trade
# generation core BY IMPORT. We do NOT modify it.
from experiment.main_research_c_v1_0 import (  # noqa: E402
    STARTING_BALANCE_R,
    BenchmarkTrade,
)
from experiment.main_research_c_v1_0 import (
    run_test_a as _run_test_a_v10,
)

# ── DD Risk Scaling thresholds (validated in Exp C) ──
# These mirror the production defaults in src/live/portfolio_dd.py
# and the experiment defaults in exp_maxdd_C_dd_risk_scaling.py.
DD_T1: float = 2.0  # >2R  -> x0.50 risk
DD_T2: float = 4.0  # >4R  -> x0.25 risk
DD_T3: float = 6.0  # >6R  -> PAUSE  (trade excluded)

# ── Fail-fast policy for the DD-scaling EXIT branch (arbitration (b)) ──
# Under the single-curve event-stream semantics, a completed trade whose
# EXIT event is processed BEFORE its ENTRY event (exit_ts < entry_ts, a
# "backdated exit") would silently drop from the scaled stream via the old
# `mult is None: continue` branch. A silent drop is a §19 provenance break,
# so it is now (a) hard-blocked by the entry<=exit runtime invariant inside
# apply_dd_scaling, and (b) counted + audit-ERROR-logged + raised-on-threshold
# as defence-in-depth. Threshold 0 => the FIRST residual drop is fatal.
MAX_DROPPED_SIGNALS: int = 0


# ─────────────────────────────────────────────────────────────────────
# DD scaling core
# ─────────────────────────────────────────────────────────────────────


def compute_dd_multiplier(dd_now: float) -> float:
    """Return the lot/pnl multiplier for a given realized DD (in R).

    Returns:
        0.00 if dd_now > DD_T3  (PAUSE)
        0.25 if dd_now > DD_T2
        0.50 if dd_now > DD_T1
        1.00 otherwise

    Mirrors `exp_maxdd_C_dd_risk_scaling.py::apply_dd_risk_scaling`
    and `src/live/portfolio_dd.py::compute_lot_multiplier`.
    """
    if dd_now > DD_T3:
        return 0.0
    if dd_now > DD_T2:
        return 0.25
    if dd_now > DD_T1:
        return 0.50
    return 1.0


def _to_float_ts(t) -> float:
    """Normalize Timestamp/float/number to float seconds since epoch."""
    import pandas as _pd

    if hasattr(t, "timestamp") and callable(t.timestamp):
        return float(t.timestamp())
    if hasattr(t, "timestamp") and not callable(t.timestamp):
        # numpy datetime64-like
        return float(_pd.Timestamp(t).timestamp())
    return float(t)


def _enforce_dropped_signal_policy(
    dropped: List[Tuple[str, int]],
    max_dropped: int = MAX_DROPPED_SIGNALS,
) -> None:
    """Fail-fast gate for the DD-scaling EXIT branch (arbitration (b), item 1).

    A completed trade whose EXIT was processed without a locked ENTRY
    multiplier is a DROPPED SIGNAL — under the old code it was silently
    `continue`d, i.e. a §19 silent-drop provenance break. Each drop is
    counted by the caller and audit-ERROR-logged as it happens; this gate
    turns any drop beyond `max_dropped` (default 0 = zero tolerance) into
    a hard failure so the scaled stream can never be trusted while a
    silent drop is in flight.

    NOTE: with the entry<=exit invariant in `apply_dd_scaling` this branch
    is unreachable by construction; it is retained as defence-in-depth
    against future ordering-bug classes, and is unit-tested directly.
    """
    if len(dropped) > max_dropped:
        raise RuntimeError(
            f"apply_dd_scaling fail-fast: {len(dropped)} completed trade(s) "
            f"dropped at the EXIT branch without a locked ENTRY multiplier "
            f"(symbols/ids: {dropped[:10]}{'...' if len(dropped) > 10 else ''}); "
            f"hard-fail threshold MAX_DROPPED_SIGNALS={max_dropped} exceeded. "
            f"A dropped signal is a silent provenance break (AGENTS.md §19) "
            f"— the scaled stream is NOT trustworthy."
        )


def _exit_order_key(t: BenchmarkTrade) -> Tuple[float, str, int]:
    """Deterministic global ordering key for the stats equity curve
    (`compute_stats_v11`) — the same chronological convention the
    DD-scaling event stream walks by.

    KEY CONTRACT: (exit_timestamp, symbol, trade_id)
      * exit_timestamp first  -> chronological by exit (the only causally
                                 valid ordering for a realized equity curve).
      * symbol then trade_id -> the deterministic tie-break. Two trades
                                 with an identical exit timestamp resolve
                                 by (symbol, trade_id); this is stable
                                 across Python sessions, threads, and
                                 platforms (no reliance on insertion order
                                 or set iteration).

    Strictly-before-entry causality inside the SCALING walk is enforced
    separately by the event-stream ordering in `apply_dd_scaling`
    (ENTRY priority 0 before EXIT priority 1 at equal timestamps) —
    NOT by adding entry_ts into this key.
    """
    return (_to_float_ts(t.exit_timestamp), str(t.symbol), int(t.trade_id))


def apply_dd_scaling(
    trades: List[BenchmarkTrade],
    entry_ts: Optional[List[float]] = None,
    starting_balance: float = STARTING_BALANCE_R,
) -> Tuple[List[BenchmarkTrade], int, int, int, int]:
    """Apply DD-based risk scaling to the merged base trade stream.

    PRODUCTION SEMANTICS (realized equity walk):
        - Single global state: (equity, peak, dd)
        - State is updated ONLY by ACCEPTED (non-paused) trades at their EXIT,
          using their SCALED pnl_r (= base_pnl_r × multiplier)
        - PAUSED trades: blocked before entry, no realized pnl ever recorded,
          contribute ZERO to the equity/peak/dd state
        - Current trade excluded from its own DD by the strict exit<entry guard

    This is the exact behavior of production `portfolio_dd.py`:
        `record_realized(pnl_r)` is called only after a closed position;
        a PAUSED trade (blocked before entry) never calls it → its pnl_r
        is never in the realized DD state.

    Algorithm (O(N log N) due to sort, N≈2300):
        1. Enforce the entry_ts <= exit_ts invariant on every completed
           trade (ValueError + audit ERROR on violation — a backdated
           exit is a data-integrity failure, never silently dropped).
        2. Emit 2 events per completed trade: ENTRY at entry_ts
           (priority 0), EXIT at exit_ts (priority 1); sort events by
           (timestamp, priority, symbol, trade_id).
        3. Single live walk of the event stream:
           - ENTRY: mult = compute_dd_multiplier(peak - equity);
                    lock mult for (symbol, trade_id).
           - EXIT:  paused (mult==0) -> contributes ZERO, count and skip;
                    accepted -> equity += base_pnl * mult;
                    peak = max(peak, equity); emit scaled trade.
        4. Fail-fast gate: any EXIT processed without a locked ENTRY is
           counted, audit-ERROR-logged, and hard-fails past
           MAX_DROPPED_SIGNALS (defence-in-depth; unreachable while the
           invariant holds).
        5. The state after processing trade T's EXIT contains the SCALED
           contributions of ALL prior ACCEPTED trades + ZERO from prior
           PAUSED trades (single-curve semantics).

    Determinism: same (exit_ts, symbol, trade_id) key as compute_stats_v11.

    Args:
        trades:           base (UNSCALED) BenchmarkTrade list. May
                          include OPEN trades (skipped, no equity contribution).
        entry_ts:         parallel list of entry timestamps, one per
                          trade, in the SAME order as `trades`. Must
                          be the same length as `trades`. Required.
        starting_balance: starting equity in R (default 100R).

    Returns:
        surviving_trades: list of scaled BenchmarkTrade (only `pnl_r`
                           mutated; SL/TP/entry/exit/result/symbol/
                           trade_id/zone/sweep are UNCHANGED).
        paused_count:     number of trades that were paused
                          (multiplier == 0.0; excluded from surviving,
                          contributed ZERO to the realized state).
        x1_count, x05_count, x025_count: tier counts.
    """
    if entry_ts is None:
        raise ValueError(
            "entry_ts is required for apply_dd_scaling (the canonical "
            "BenchmarkTrade has no entry_timestamp field — the caller "
            "must pass it explicitly)."
        )
    if len(entry_ts) != len(trades):
        raise ValueError(
            f"entry_ts length ({len(entry_ts)}) must equal trades "
            f"length ({len(trades)}). entry_ts is a parallel list."
        )

    # Pair each completed trade with its entry_ts (parallel lists).
    # RUNTIME INVARIANT (arbitration (b), 2026-08-31): a completed trade's
    # exit must never predate its entry (entry_ts <= exit_ts). A backdated
    # exit would reorder the event stream so the EXIT is processed before
    # the ENTRY, silently dropping the trade at `mult is None` below. That
    # silent drop is a §19 provenance break, so it is hard-blocked here.
    # NOTE: this is a ValueError (not a bare `assert`) on purpose — `assert`
    # is stripped under `python -O`, which is unacceptable for a trading
    # safety invariant (AGENTS.md §7 fail-safe semantics).
    completed_pairs: List[Tuple[BenchmarkTrade, float, float]] = []
    for t, e in zip(trades, entry_ts):
        if t.result not in ("TP", "PROFIT_TRAIL", "LOSS"):
            continue
        entry_float = _to_float_ts(e)
        exit_float = _to_float_ts(t.exit_timestamp)
        if entry_float > exit_float:
            _logger.error(
                "apply_dd_scaling INVARIANT VIOLATION: backdated exit "
                "(entry_ts=%r > exit_ts=%r) for trade symbol=%s trade_id=%s",
                entry_float,
                exit_float,
                t.symbol,
                t.trade_id,
            )
            raise ValueError(
                f"apply_dd_scaling invariant violated: trade "
                f"(symbol={t.symbol}, trade_id={t.trade_id}) has "
                f"entry_ts={entry_float} > exit_ts={exit_float} "
                f"(backdated exit). Completed trades must satisfy "
                f"entry_ts <= exit_ts."
            )
        completed_pairs.append((t, entry_float, exit_float))

    # Build event stream for each completed trade.
    # Each trade produces 2 events:
    #   ENTRY at entry_float  (priority 0)
    #   EXIT  at exit_float   (priority 1)
    # Same timestamp: ENTRY before EXIT (strict < for prior exit < current entry)
    # Trade identity: (symbol, trade_id) — unique per symbol+id combination.
    events = []  # list of (timestamp, priority, symbol, trade_id, event_type, base_pnl_r, trade_ref)
    # event_type: "ENTRY" or "EXIT"
    # priority: 0 for ENTRY, 1 for EXIT
    # sort key: (timestamp, priority, symbol, trade_id)

    for t, entry_float, exit_float in completed_pairs:
        symbol_id = (str(t.symbol), int(t.trade_id))
        events.append((entry_float, 0, str(t.symbol), int(t.trade_id), "ENTRY", t, symbol_id))
        events.append((exit_float, 1, str(t.symbol), int(t.trade_id), "EXIT", t, symbol_id))

    events.sort(key=lambda e: (e[0], e[1], e[2], e[3]))

    surviving: List[BenchmarkTrade] = []
    paused = 0
    n_x1 = 0
    n_x05 = 0
    n_x025 = 0

    equity = starting_balance
    peak = starting_balance
    # Lock multiplier per (symbol, trade_id) at ENTRY time.
    mult_lock = {}  # (symbol, trade_id) -> float multiplier
    # FAIL-FAST counter (arbitration (b)): completed trades whose EXIT event
    # was processed without a locked ENTRY multiplier. Under the
    # entry<=exit invariant above this is unreachable via backdated exits;
    # any hit means a NEW ordering bug class — it must never be silent.
    dropped: List[Tuple[str, int]] = []

    for ts, priority, sym_str, tid, event_type, t_ref, symbol_id in events:
        t_obj = t_ref  # BenchmarkTrade reference

        if event_type == "ENTRY":
            # ENTRY event: compute DD from current realized equity/peak.
            # Only prior EXIT events have updated equity/peak.
            # Prior ENTRY events (same timestamp, lower priority) have NO effect
            # on equity/peak — multiplier is computed but not yet applied.
            dd_now = peak - equity
            mult = compute_dd_multiplier(dd_now)
            mult_lock[symbol_id] = mult
        else:  # EXIT
            mult = mult_lock.get(symbol_id)
            if mult is None:
                # FAIL-FAST (was: silent `continue` drop — §19 code
                # closure, arbitration (b) decision item 1). Counted,
                # audit-ERROR-logged, and raised below against
                # MAX_DROPPED_SIGNALS.
                dropped.append((sym_str, tid))
                _logger.error(
                    "apply_dd_scaling DROPPED SIGNAL: EXIT event for trade "
                    "symbol=%s trade_id=%s at ts=%r had no locked ENTRY "
                    "multiplier (event-stream ordering violation). "
                    "dropped_count so far=%d (hard-fail threshold=%d).",
                    sym_str,
                    tid,
                    ts,
                    len(dropped),
                    MAX_DROPPED_SIGNALS,
                )
                continue
            if mult == 0.0:
                # PAUSED trade: no realized contribution.
                paused += 1
                # Note: mult_lock already has 0; nothing updates equity/peak.
                continue

            # ACCEPTED trade: apply scaled realized PnL at EXIT time.
            if mult == 1.0:
                n_x1 += 1
            elif mult == 0.5:
                n_x05 += 1
            elif mult == 0.25:
                n_x025 += 1

            scaled_pnl = t_obj.pnl_r * mult
            equity += scaled_pnl
            if equity > peak:
                peak = equity

            scaled = BenchmarkTrade(**t_obj.__dict__)
            scaled.pnl_r = scaled_pnl
            surviving.append(scaled)

    # Note: paused trades are NOT in surviving. Their base pnl_r contributes ZERO.
    # Their multiplier is 0. The event stream processed them at ENTRY (mult=0)
    # and at EXIT (mult==0 -> skip, no state update).
    _enforce_dropped_signal_policy(dropped)
    return surviving, paused, n_x1, n_x05, n_x025


def _derive_entry_ts(trades: List[BenchmarkTrade], bars_15m: List) -> List[float]:
    """Build a parallel `entry_ts` list from each trade's
    `entry_bar_index` and the OWN symbol's `bars_15m` timestamps.

    Per-symbol scoped by construction: the `bars_15m` list belongs
    to one symbol. Each trade's entry_ts is derived from
    `bars_15m[entry_bar_index].timestamp` — never from a global
    map keyed by `trade_id` (which collides across symbols
    because `run_test_a` resets per-symbol `trade_counter` to 0
    on every call).

    Fail-fast: if `entry_bar_index` is out of range for the
    given `bars_15m`, raise ValueError. Research benchmarks must
    not silently fall back to `epoch=0` (which would corrupt the
    chronological ordering in the global C v1.1 walk).

    Returns:
        List[float] parallel to `trades`, each element =
        `pd.Timestamp(bars_15m[entry_bar_index].timestamp).timestamp()`
        as float seconds since epoch.
    """
    import pandas as pd

    ts_array = [b.timestamp for b in bars_15m]
    n = len(ts_array)
    out: List[float] = []
    for t in trades:
        ei = getattr(t, "entry_bar_index", 0)
        if not (0 <= ei < n):
            raise ValueError(
                f"Invalid entry_bar_index for {t.symbol} "
                f"trade_id={t.trade_id}: {ei} (bars_15m len={n})"
            )
        out.append(float(pd.Timestamp(ts_array[ei]).timestamp()))
    return out


# ─────────────────────────────────────────────────────────────────────
# C v1.1 entry point
# ─────────────────────────────────────────────────────────────────────


def run_test_a_v11(
    symbol: str,
    bars_15m: List,
) -> List[BenchmarkTrade]:
    """C v1.1 base trades for ONE symbol (no DD scaling).

    Runs the FROZEN C v1.0 engine for `symbol` on `bars_15m` and
    returns the unscaled base trade list. The DD Risk Scaling
    overlay is GLOBAL across the 6-major merged stream; it is
    NOT applied here. The canonical C v1.1 (with scaling) is
    produced by `main()`, which merges 6 majors and calls
    `apply_dd_scaling()` exactly once.

    This function is a thin wrapper for symmetry / future
    per-symbol debugging; it must NOT do per-symbol scaling
    (that would contradict the global C v1.1 semantics).

    Trade identity (entry/exit/SL/TP/zone/sweep) is identical to
    C v1.0 — no mutation, no scaling.
    """
    return _run_test_a_v10(symbol, bars_15m)


# ─────────────────────────────────────────────────────────────────────
# Stats (mirrors C v1.0 compute_stats so v1.0 ↔ v1.1 are comparable)
# ─────────────────────────────────────────────────────────────────────


def compute_stats_v11(
    trades: List[BenchmarkTrade],
    starting_balance: float = STARTING_BALANCE_R,
) -> Dict[str, Any]:
    """Compute portfolio statistics on a (post-scaling) trade list.

    Mirrors `main_research_c_v1_0.compute_stats` so C v1.0 and C v1.1
    can be compared apples-to-apples. The trade list is expected to
    already be SCALED (output of `run_test_a_v11`).
    """
    if not trades:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "open": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "avg_r": 0.0,
            "max_dd": 0.0,
            "max_dd_pct": 0.0,
            "profit_factor": 0.0,
            "trailing_trades": 0,
            "total_hops": 0,
            "avg_hops": 0.0,
            "avg_mfe": 0.0,
            "avg_mae": 0.0,
            "median_mfe": 0.0,
            "median_mae": 0.0,
        }

    completed = [t for t in trades if t.result in ("TP", "PROFIT_TRAIL", "LOSS")]
    wins = [t for t in completed if t.result in ("TP", "PROFIT_TRAIL")]
    losses = [t for t in completed if t.result == "LOSS"]
    total_pnl = sum(t.pnl_r for t in completed)

    # Chronological equity curve using the SAME deterministic exit ordering
    # as apply_dd_scaling (exit_timestamp, symbol, trade_id) so the stats
    # curve and the scaling curves never disagree on trade order.
    sorted_trades = sorted(completed, key=_exit_order_key)
    equity = starting_balance
    peak = starting_balance
    max_dd = 0.0
    max_dd_pct = 0.0
    for t in sorted_trades:
        equity += t.pnl_r
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
        if peak > 0:
            pct = dd / peak * 100
            if pct > max_dd_pct:
                max_dd_pct = pct

    trailed = [t for t in trades if t.trailing_count > 0]
    total_hops = sum(t.trailing_count for t in trades)

    mfes = [t.max_favorable for t in completed]
    maes = [t.max_adverse for t in completed]
    avg_mfe = statistics.mean(mfes) if mfes else 0.0
    avg_mae = statistics.mean(maes) if maes else 0.0
    median_mfe = statistics.median(mfes) if mfes else 0.0
    median_mae = statistics.median(maes) if maes else 0.0

    gross_wins = sum(t.pnl_r for t in wins)
    gross_losses = abs(sum(t.pnl_r for t in losses))
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else float("inf")

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "open": len([t for t in trades if t.result == "OPEN"]),
        "win_rate": len(wins) / len(completed) * 100 if completed else 0.0,
        "total_pnl": round(total_pnl, 4),
        "avg_r": round(total_pnl / len(completed), 4) if completed else 0.0,
        "max_dd": round(max_dd, 4),
        "max_dd_pct": round(max_dd_pct, 2),
        "profit_factor": round(profit_factor, 2),
        "trailing_trades": len(trailed),
        "total_hops": total_hops,
        "avg_hops": round(total_hops / len(trailed), 2) if trailed else 0.0,
        "avg_mfe": round(avg_mfe, 4),
        "avg_mae": round(avg_mae, 4),
        "median_mfe": round(median_mfe, 4),
        "median_mae": round(median_mae, 4),
    }


# ─────────────────────────────────────────────────────────────────────
# Worker (mirrors C v1.0 _run_symbol) — BASE trades only (no scaling)
# ─────────────────────────────────────────────────────────────────────


def _run_symbol_base(sym: str, dry_run: bool) -> Tuple[List[BenchmarkTrade], List[float]]:
    """Run the FROZEN C v1.0 engine for one symbol and derive per-symbol
    `entry_ts` (one timestamp per base trade). No DD scaling here.

    Returns:
        base_trades: unscaled (base) BenchmarkTrade list for `sym`.
        entry_ts:    parallel list of pd.Timestamp (entry time) for
                     each base trade, derived from
                     `bars_15m[entry_bar_index].timestamp`. Trade
                     identity and chronological order match
                     `base_trades` exactly.
    """
    import pandas as pd

    print(f"  [WORKER] {sym}: starting C v1.1 (base) ...", flush=True)
    from src.strategy.models import Bar

    feather_path = _PROJECT_ROOT / "data" / "icmarket_feather" / f"{sym}_15m.feather"
    df = pd.read_feather(feather_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    bars_15m = [
        Bar(
            index=i,
            timestamp=pd.Timestamp(ts),
            open=float(o),
            high=float(h),
            low=float(lo),
            close=float(c),
            volume=float(v),
        )
        for i, ts, o, h, lo, c, v in zip(
            range(len(df)),
            df["timestamp"].values,
            df["open"].values.astype(float),
            df["high"].values.astype(float),
            df["low"].values.astype(float),
            df["close"].values.astype(float),
            df["volume"].values.astype(float),
        )
    ]
    if dry_run:
        bars_15m = bars_15m[:2000]
    base_trades = _run_test_a_v10(sym, bars_15m)
    entry_ts = _derive_entry_ts(base_trades, bars_15m)
    return base_trades, entry_ts


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Research C v1.1 — C2 EQ + DD Risk Scaling")
    parser.add_argument("symbols", nargs="*", help="Symbols (default: 6 majors)")
    parser.add_argument("--dry-run", action="store_true", help="Smoke test (2000 bars)")
    parser.add_argument(
        "--starting-balance",
        type=float,
        default=STARTING_BALANCE_R,
        help=f"Starting balance in R for DD% (default: {STARTING_BALANCE_R})",
    )
    args = parser.parse_args()

    SIX_MAJORS = ["EURUSD", "GBPUSD", "GBPJPY", "USDJPY", "AUDUSD", "USDCAD"]
    symbols = [s.upper() for s in args.symbols] if args.symbols else SIX_MAJORS

    print("=== RESEARCH C v1.1 — C2 EQ + DD-BASED RISK SCALING ===")
    print(f"Thresholds: DD>{DD_T1}R x0.50 | DD>{DD_T2}R x0.25 | DD>{DD_T3}R PAUSE")
    print(f"Symbols: {symbols} | {'DRY RUN' if args.dry_run else 'FULL 2.7Y'}")
    print()

    # ========================================================================
    # STEP 1 — BASE TRADES
    # For each symbol, run the FROZEN C v1.0 engine and derive
    # per-symbol `entry_ts` (one timestamp per base trade). No
    # DD scaling here. `all_base_trades[i]` and `all_entry_ts[i]`
    # always represent the SAME trade; the order is the symbol
    # iteration order (deterministic).
    # ========================================================================
    t0 = time.time()
    all_base_trades: List[BenchmarkTrade] = []
    all_entry_ts: List[float] = []
    for s in symbols:
        base_sym, et_sym = _run_symbol_base(s, args.dry_run)
        all_base_trades.extend(base_sym)
        all_entry_ts.extend(et_sym)
    elapsed = time.time() - t0
    # Defensive: every base trade must have a matching entry_ts.
    if len(all_base_trades) != len(all_entry_ts):
        raise RuntimeError(
            f"main STEP 1 contract violated: "
            f"len(all_base_trades)={len(all_base_trades)} "
            f"!= len(all_entry_ts)={len(all_entry_ts)}"
        )

    # ========================================================================
    # STEP 2 — SINGLE GLOBAL SCALING PASS
    # Apply DD scaling to the merged 6-major stream. EXACTLY ONE
    # call to `apply_dd_scaling()`. No per-symbol scaling, no
    # second pass, no recomputation. Single-curve event-stream walk:
    # multiplier locked at ENTRY from realized DD, scaled pnl applied
    # at EXIT; paused trades contribute ZERO (see apply_dd_scaling).
    # ========================================================================
    scaled_trades, paused, n_x1, n_x05, n_x025 = apply_dd_scaling(
        all_base_trades,
        entry_ts=all_entry_ts,
        starting_balance=args.starting_balance,
    )

    # ========================================================================
    # STEP 3 — STATS FROM THE SAME SCALED STREAM
    # Stats and scaling counts come from the SAME returned stream.
    # No second pass; no recomputation. `starting_balance` is
    # passed identically to `apply_dd_scaling` and
    # `compute_stats_v11` so the equity curve is internally
    # consistent.
    # ========================================================================
    stats = compute_stats_v11(scaled_trades, starting_balance=args.starting_balance)
    # POST-CONDITION: stats counts (wins + losses) + (open_n) must
    # equal the scaled stream length. Equivalently: tier counts
    # (x1 + x0.5 + x0.25 + paused) must equal the COMPLETED base
    # trade count (the same number used for total_pnl denominator).
    completed_base = sum(1 for t in all_base_trades if t.result in ("TP", "PROFIT_TRAIL", "LOSS"))
    completed_scaled = sum(1 for t in scaled_trades if t.result in ("TP", "PROFIT_TRAIL", "LOSS"))
    if n_x1 + n_x05 + n_x025 + paused != completed_base:
        raise RuntimeError(
            f"main STEP 3 consistency violated: tier counts "
            f"(x1={n_x1} + x0.5={n_x05} + x0.25={n_x025} + paused={paused} "
            f"= {n_x1 + n_x05 + n_x025 + paused}) != completed base "
            f"trades ({completed_base})"
        )
    if completed_scaled + paused != completed_base:
        raise RuntimeError(
            f"main STEP 3 consistency violated: surviving scaled "
            f"({completed_scaled}) + paused ({paused}) != completed "
            f"base ({completed_base})"
        )
    completed = [t for t in scaled_trades if t.result != "OPEN"]
    open_n = len(scaled_trades) - len(completed)

    print(
        f"  [C v1.1] {stats['trades']}T | {stats['wins']}W/{stats['losses']}L | "
        f"{stats['win_rate']:.2f}% WR | {stats['total_pnl']:+.2f}R | "
        f"PF {stats['profit_factor']:.2f} | DD {stats['max_dd']:.2f}R "
        f"({stats['max_dd_pct']:.2f}%) | OPEN {open_n} | "
        f"x1={n_x1} x0.5={n_x05} x0.25={n_x025} paused={paused} | {elapsed:.1f}s"
    )
    print()

    # Per-symbol breakdown
    print("=== PER-SYMBOL (C v1.1, from scaled stream) ===")
    syms: Dict[str, List[BenchmarkTrade]] = {}
    for t in scaled_trades:
        syms.setdefault(t.symbol, []).append(t)
    print(f"{'Symbol':<12} {'N':>5} {'WR%':>6} {'PnL':>10} {'AvgR':>8} {'PF':>6}")
    print("-" * 50)
    for sym in sorted(syms):
        s = compute_stats_v11(syms[sym], starting_balance=args.starting_balance)
        print(
            f"{sym:<12} {s['trades']:>5d} {s['win_rate']:>5.1f}% "
            f"{s['total_pnl']:>+9.2f}R {s['avg_r']:>+7.4f} {s['profit_factor']:>5.2f}"
        )
    print()

    # Persist
    out_dir = _PROJECT_ROOT / "results" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "stats": stats,
        "scaling": {
            "x1": n_x1,
            "x0_5": n_x05,
            "x0_25": n_x025,
            "paused": paused,
            "t1": DD_T1,
            "t2": DD_T2,
            "t3": DD_T3,
        },
        "engine": "C v1.1",
        "parent": "C v1.0",
        "promotion_source": "experiment/exp_maxdd_C_dd_risk_scaling.py",
        "starting_balance_r": args.starting_balance,
        "elapsed_s": round(elapsed, 1),
    }
    with open(out_dir / "c_v1_1_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"Results saved to {out_dir}/c_v1_1_summary.json")


def _load_bars(sym: str, dry_run: bool) -> List:
    import pandas as pd

    from src.strategy.models import Bar

    df = pd.read_feather(_PROJECT_ROOT / "data" / "icmarket_feather" / f"{sym}_15m.feather")
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    bars_15m = [
        Bar(
            index=i,
            timestamp=pd.Timestamp(ts),
            open=float(o),
            high=float(h),
            low=float(lo),
            close=float(c),
            volume=float(v),
        )
        for i, ts, o, h, lo, c, v in zip(
            range(len(df)),
            df["timestamp"].values,
            df["open"].values.astype(float),
            df["high"].values.astype(float),
            df["low"].values.astype(float),
            df["close"].values.astype(float),
            df["volume"].values.astype(float),
        )
    ]
    if dry_run:
        bars_15m = bars_15m[:2000]
    return bars_15m


if __name__ == "__main__":
    main()
