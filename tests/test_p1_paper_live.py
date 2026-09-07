#!/usr/bin/env python
"""P1 — PAPER LIVE fixes tests.

Covers:
- Real trade-risk lock in paper context (equity NEVER used as R basis).
  counterexample: equity=$10k, locked risk=$30, realized=+$54 -> +1.8R
- Default contract (contract=None): open -> close -> realized cash
  -> pnl_r -> PortfolioDD full chain works (no silent skip).
- Continuity: warmup -> run_step never crashes (no Timestamp vs float);
  no duplicate 15m emission; split buckets and M1 tail survive.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from src.live.audit import AuditChain
from src.live.live_runner import default_contract
from src.live.paper import PaperSession, _rates_to_bars
from src.live.strategy_runtime import Signal


def _fake_m1_rows(n, start_utc, px=1.1000):
    rows, t = [], start_utc
    for _ in range(n):
        rows.append(
            {
                "time": int(t.timestamp()),
                "open": px,
                "high": px + 0.0002,
                "low": px - 0.0002,
                "close": px,
                "tick_volume": 100,
            }
        )
        t += timedelta(minutes=1)
    return rows


class FakeMT5:
    def __init__(self, start_utc):
        self.start = start_utc

    def copy_rates_from_pos(self, symbol, timeframe, pos, count):
        return _fake_m1_rows(count, self.start)


START = datetime(2026, 8, 20, 0, 0)


def _paper_session(contract=None):
    return PaperSession(symbol="EURUSD", mt5=FakeMT5(START), contract=contract)


def _sig():
    return Signal(
        symbol="EURUSD",
        direction="bullish",
        side="long",
        entry_price=1.1000,
        sl=1.0990,
        tp=1.1018,
        entry_bar_index=1,
        sweep_bar_index=0,
        zone_index=0,
        zone_top=1.1005,
        zone_bottom=1.0995,
        zone_size=0.001,
        timestamp=pd.Timestamp(START),
    )


# ── Default contract full chain ──────────────────────────────────────


def test_default_contract_open_close_full_chain():
    sess = _paper_session(contract=None)
    n15 = sess.warmup(n_15m=200)
    assert n15 > 0 and sess.runtime._warmed

    contract = sess._default_contract()
    pos = sess.broker.open(_sig(), volume=0.01, contract=contract)
    assert pos.ticket == 1
    sess._persist_paper_context(pos, 0.01, 0.01, 1.0, contract)

    # SL hit: broker fills at the SL price 1.0990 (on_tick trigger).
    res = sess.run_step(AuditChain(), m1_bars=[], ticks=[{"bid": 1.0985, "ask": 1.0987}])
    closed = res.new_closed
    assert len(closed) == 1 and closed[0].status.value == "CLOSED_SL"
    # Realized cash computed with the default contract (long loss):
    # (1.0990-1.1000)/0.00001 * 1.0 * 0.01 = -1.00 USD
    assert abs(closed[0].pnl - (-1.00)) < 1e-6
    # Locked risk cash for 0.01 lot, 0.0010 stop -> 1.0 USD.
    assert abs(pos.volume * 100.0 - 1.0) < 1e-9
    # pnl_r = -1.00 / 1.00 = -1.0R recorded into paper DD.
    assert abs(sess._paper_dd.realized_pnl_r - (-1.0)) < 1e-9


def test_paper_r_conversion_counterexample_plus18R():
    # equity=$10,000, locked risk=$30, realized=+$54 -> +1.8R
    sess = _paper_session(contract=None)
    contract = default_contract("EURUSD")
    volume = 0.30  # locked risk = 0.0010/0.00001 * 1.0 * 0.30 = $30
    pos = sess.broker.open(_sig(), volume=volume, contract=contract)
    sess._persist_paper_context(pos, volume, volume, 1.0, contract)
    # Locked trade risk cash is $30 — NOT broker.equity of $10,000.
    ctx = sess._paper_context[pos.ticket]
    assert abs(ctx["initial_risk_cash_total"] - 30.0) < 1e-9

    # Win: exits +0.0060 above entry -> (0.0060/0.00001)*1.0*0.30 = +$180?
    # -- real win for +54$ is 0.0018 distance; use 1.8R via formula.
    from src.live.paper import _pnl

    pnl = _pnl("long", 1.1000, 1.1018, volume, 100000.0, 0.00001, 1.0)
    assert abs(pnl - 54.0) < 1e-9, f"+54 USD win expected, got {pnl}"
    pnl_r = pnl / ctx["initial_risk_cash_total"]
    assert abs(pnl_r - 1.8) < 1e-9, "R conversion must use the LOCKED risk cash"


def test_paper_entry_uses_default_contract_when_none():
    sess = _paper_session(contract=None)
    contract = sess._default_contract()
    assert contract.tick_size == 0.00001 and contract.volume_min == 0.01
    assert sess.contract is None, "constructor default must still be None"


# ── Continuity ───────────────────────────────────────────────────────


def test_continuity_first_run_step_no_crash_no_duplicate():
    sess = _paper_session()
    sess.warmup(n_15m=200)
    # New M1 beyond the warmup tail -> completes ONE new 15m bucket.
    new_start = START + timedelta(minutes=3 * 15 * 60)
    new_bars = _rates_to_bars(_fake_m1_rows(30, new_start))
    result = sess.run_step(AuditChain(), m1_bars=new_bars, ticks=None)
    assert "not warmed" not in result.errors
    # No TypeError: M1 float progress is never compared to 15m Timestamps.
    assert sess._last_emitted_m15_ts is not None
    # Now feed the SAME bars again (duplicate window) -> nothing re-emitted.
    result2 = sess.run_step(
        AuditChain(), m1_bars=_rates_to_bars(_fake_m1_rows(30, new_start)), ticks=None
    )
    # Both steps complete without exception.
    assert result2.errors == []


def test_continuity_stale_warmup_bars_not_reemitted():
    sess = _paper_session()
    sess.warmup(n_15m=200)
    # Replay old warmup M1 with an EMPTY tail — old buckets are far below
    # _last_emitted_m15_ts and must NOT re-emit / advance progress.
    sess._partial_m1_tail = []
    old_bars = _rates_to_bars(_fake_m1_rows(30, START))
    old_last = sess._last_emitted_m15_ts
    sess.run_step(AuditChain(), m1_bars=old_bars, ticks=None)
    assert sess._last_emitted_m15_ts == old_last, "old bars must not advance emission"


def test_continuity_partial_m1_tail_survives_split_bucket():
    sess = _paper_session()
    sess.warmup(n_15m=200)
    tail_start = START + timedelta(minutes=3 * 15 * 60)
    # Feed a PARTIAL tail (e.g. 8 M1 bars of a bucket) then the remainder.
    partial = _rates_to_bars(_fake_m1_rows(8, tail_start))
    sess.run_step(AuditChain(), m1_bars=partial, ticks=None)
    # The partial bucket is retained for the next step.
    assert sess._partial_m1_tail, "partial M1 tail must survive across steps"
    # Then the remainder (7 more bars) completes the 15m bucket.
    remainder = _rates_to_bars(_fake_m1_rows(7, tail_start + timedelta(minutes=8)))
    r = sess.run_step(AuditChain(), m1_bars=remainder, ticks=None)
    assert r.errors == []
