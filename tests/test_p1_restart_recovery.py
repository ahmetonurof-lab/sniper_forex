#!/usr/bin/env python
"""P1 — RESTART / RECOVERY tests.

Running runtime -> save -> process restart -> load -> continue.

Asserts:
- pending entry filler resumes & FVG is restored as a REAL object
- active trade continuation (SL/TP/trailing state) restored
- next on_bar does not crash (bars buffer present)
- bars buffer present
- FVG object real object/state after restore
- entry risk lock preserved via lifecycle persistence
"""

from __future__ import annotations

import pandas as pd

from src.live.recovery import RuntimeRecovery
from src.live.strategy_runtime import StrategyRuntime
from src.strategy.models import Bar

STATE_DIR = "state_test_tmp"


class DummyFVG:
    real_index = 90
    direction = "bullish"
    top = 1.1005
    bottom = 1.0995
    size = 0.001
    invalidated = False


def _bars15(n=115, start="2026-08-01 00:00:00"):
    t = pd.Timestamp(start)
    out = []
    for i in range(n):
        out.append(
            Bar(
                index=i,
                timestamp=t,
                open=1.10,
                high=1.101,
                low=1.099,
                close=1.1005,
                volume=1000,
            )
        )
        t += pd.Timedelta(minutes=15)
    return out


def _runtime_with_pending_and_trade():
    rt = StrategyRuntime("EURUSD")
    rt.warmup(_bars15(120))
    for b in _bars15(8, "2026-08-02 06:00:00"):
        rt.on_bar(b)
    rt.pending_entry = {
        "fvg": DummyFVG(),
        "touch_bar_index": 101,
        "entry_bar_index": 102,
        "sweep_bar_index": 50,
        "sweep_price": 1.0950,
        "reference_level": 1.0960,
        "sl": 1.0980,
        "rp2": 0.0010,
        "fh": 0.0010,
        "direction": "bullish",
    }
    rt.active_trade = {
        "trade_id": 1,
        "side": "long",
        "entry_price": 1.1000,
        "sl": 1.0990,
        "tp": 1.1030,
        "initial_sl": 1.0990,
        "trailing_count": 2,
        "max_price": 1.1010,
        "min_price": 1.1000,
        "closed": False,
    }
    return rt


def _cleanup():
    import shutil
    from pathlib import Path

    root = Path(STATE_DIR)
    if root.exists():
        shutil.rmtree(root)


def test_recovery_roundtrip_full():
    _cleanup()
    try:
        rt = _runtime_with_pending_and_trade()
        rec = RuntimeRecovery(STATE_DIR)
        rec.save(rt, "EURUSD")

        rt2 = StrategyRuntime("EURUSD")
        assert rec.load(rt2, "EURUSD") is True

        # Bars buffer restored.
        assert len(rt2.bars) > 100, "15m buffer must be restored"
        assert rt2._warmed and rt2._next_idx > 100

        # FVG object restored as a real object.
        pe = rt2.pending_entry
        assert pe is not None
        assert pe["fvg"].real_index == 90, "FVG must be a real object (not str)"
        assert pe["fvg"].direction == "bullish" and pe["fvg"].top == 1.1005

        # Active trade continuation incl. trailing state.
        at = rt2.active_trade
        assert at is not None
        assert at["sl"] == 1.0990 and at["trailing_count"] == 2

        # 1) Pending entry filler resumes cleanly (no AttributeError).
        from src.strategy.models import Bar as B

        nxt = B(
            index=102,
            timestamp=pd.Timestamp("2026-08-02 08:00:00"),
            open=1.1002,
            high=1.1012,
            low=1.0992,
            close=1.1007,
            volume=1000,
        )
        assert rt2._fill_pending(nxt) is True
        assert rt2.active_trade["entry_price"] == 1.1002

        # 2) Next on_bar does not crash.
        sig = rt2.on_bar(nxt)
        assert sig is None or sig is not None  # no crash is the assertion
    finally:
        _cleanup()


def test_recovery_json_serializable_no_string_dump():
    _cleanup()
    try:
        rt = _runtime_with_pending_and_trade()
        rec = RuntimeRecovery(STATE_DIR)
        path = rec.save(rt, "EURUSD")
        raw = path.read_text(encoding="utf-8")
        import json

        data = json.loads(raw)
        # The FVG object serialized to a dict, NOT a repr string.
        assert isinstance(data["pending_entry"]["fvg"], dict)
        assert data["pending_entry"]["fvg"]["real_index"] == 90
        assert "DummyFVG object" not in raw
    finally:
        _cleanup()


def test_recovery_lifecycle_journal_restored():
    _cleanup()
    try:
        from src.live.portfolio_dd import PortfolioDD
        from src.live.trade_lifecycle import (
            OpenTradeContext,
            TradeLifecycle,
        )

        lc = TradeLifecycle(portfolio_dd=PortfolioDD(starting_balance_r=100.0))
        ctx = OpenTradeContext(
            position_id=999,
            symbol="EURUSD",
            entry_price=1.1000,
            initial_sl=1.0990,
            initial_risk_cash_total=30.0,
        )
        lc.register_open_context(ctx)
        lc.record_exit_deal(505, 999, -15.0, -0.5, timestamp=1.0)
        rec = RuntimeRecovery(STATE_DIR)
        rec.save_lifecycle(lc, "EURUSD")

        lc2 = TradeLifecycle()
        assert rec.load_lifecycle(lc2, "EURUSD") is True
        assert lc2.portfolio_dd.realized_pnl_r == -0.5
        assert lc2.portfolio_dd.current_dd_r() == 0.5  # peak=100, equity=99.5
        assert lc2.dd_is_reliable()
        assert 999 in lc2.open_trades
        # Entry risk lock preserved.
        assert abs(lc2.open_trades[999].initial_risk_cash_total - 30.0) < 1e-9
    finally:
        _cleanup()
