#!/usr/bin/env python
"""P1 — DD REBUILD (journal replay) + UNKNOWN EXIT QUARANTINE tests.

Counterexamples from the forensic audit:
- start=100R, realized=-5R  ->  expected equity=95R, peak=100R, DD=5R
- -5R, +8R, -4R             ->  expected equity=99R, peak=103R, DD=4R
- unknown position exit     ->  DD MUST NOT change (quarantine)
"""

from __future__ import annotations

import json

from src.live.portfolio_dd import PortfolioDD
from src.live.trade_lifecycle import (
    OpenTradeContext,
    RealizedDealRecord,
    TradeLifecycle,
    build_open_context_from_fill,
)


def _ctx(position_id=1, realized=0.0):
    return OpenTradeContext(
        position_id=position_id, symbol="EURUSD", realized_r_accumulated=realized
    )


# ── DD rebuild: chronological journal replay ─────────────────────────


def test_dd_rebuild_counterexample_start_minus5():
    lc = TradeLifecycle()
    lc.rebuild_from_persisted(
        [_ctx(1)],
        realized_journal=[RealizedDealRecord(deal_id=101, position_id=1, pnl_r=-5.0)],
        starting_balance_r=100.0,
    )
    assert lc.portfolio_dd.realized_pnl_r == -5.0
    assert lc.portfolio_dd.peak_r == 100.0, "historical peak must be preserved"
    assert lc.portfolio_dd.current_dd_r() == 5.0
    assert lc.dd_is_reliable()


def test_dd_replay_multi_trade_scenario():
    journal = [
        RealizedDealRecord(deal_id=1, position_id=1, pnl_r=-5.0, timestamp=1.0),
        RealizedDealRecord(deal_id=2, position_id=2, pnl_r=8.0, timestamp=2.0),
        RealizedDealRecord(deal_id=3, position_id=3, pnl_r=-4.0, timestamp=3.0),
    ]
    lc = TradeLifecycle()
    lc.rebuild_from_persisted(
        [_ctx(1), _ctx(2), _ctx(3)],
        realized_journal=journal,
        starting_balance_r=100.0,
    )
    dd = lc.portfolio_dd
    assert dd.realized_pnl_r == -1.0  # -5 +8 -4
    assert dd.current_equity_r() == 99.0
    assert dd.peak_r == 103.0  # 100 -> 95 -> 103 -> 99
    assert dd.current_dd_r() == 4.0


def test_rebuild_replay_is_idempotent_no_duplicate_dd():
    journal = [
        RealizedDealRecord(deal_id=1, position_id=1, pnl_r=-5.0, timestamp=1.0),
        RealizedDealRecord(deal_id=2, position_id=1, pnl_r=8.0, timestamp=2.0),
    ]
    lc1 = TradeLifecycle()
    lc1.rebuild_from_persisted([_ctx(1)], journal, starting_balance_r=100.0)
    dd1 = lc1.portfolio_dd.current_dd_r()
    # Replay the SAME journal again (simulating a second restart).
    lc2 = TradeLifecycle()
    lc2.rebuild_from_persisted([_ctx(1)], journal, starting_balance_r=100.0)
    lc2.rebuild_from_persisted([_ctx(1)], journal, starting_balance_r=100.0)
    assert lc2.portfolio_dd.current_dd_r() == dd1
    assert lc2.portfolio_dd.realized_pnl_r == 3.0, "no duplicate DD on replay"


def test_rebuild_without_journal_marks_dd_unreliable():
    lc = TradeLifecycle()
    lc.rebuild_from_persisted([_ctx(1, realized=-5.0)], starting_balance_r=100.0)
    assert not lc.dd_is_reliable(), "total-PnL-only peak is not trustworthy"
    assert lc.portfolio_dd.current_dd_r() == 5.0  # conservative fallback


# ── Unknown exit quarantine ──────────────────────────────────────────


def test_known_exit_updates_dd():
    lc = TradeLifecycle()
    lc.register_open_context(_ctx(1))
    status = lc.record_exit_deal(101, 1, net_realized_cash=10.0, pnl_r=0.5)
    assert status == "recorded"
    assert lc.portfolio_dd.realized_pnl_r == 0.5
    assert len(lc.realized_journal) == 1


def test_duplicate_deal_recorded_exactly_once():
    lc = TradeLifecycle()
    lc.register_open_context(_ctx(1))
    assert lc.record_exit_deal(101, 1, 10.0, 0.5) == "recorded"
    assert lc.record_exit_deal(101, 1, 10.0, 0.5) == "duplicate"
    assert lc.portfolio_dd.realized_pnl_r == 0.5, "no double-count"
    assert len(lc.realized_journal) == 1


def test_unknown_exit_quarantined_dd_unchanged():
    lc = TradeLifecycle()
    lc.register_open_context(_ctx(1))
    before = lc.portfolio_dd.realized_pnl_r
    status = lc.record_exit_deal(999, 424242, net_realized_cash=-50.0, pnl_r=-5.0)
    assert status == "quarantined"
    assert lc.portfolio_dd.realized_pnl_r == before, "unknown exit must NOT hit DD"
    assert 999 in lc.quarantined_exits
    assert lc.quarantined_exits[999].reason == "unknown_position"


def test_unknown_exit_process_exit_deal_returns_false():
    lc = TradeLifecycle()
    assert lc.process_exit_deal(999, 424242, -50.0, -5.0) is False
    assert lc.portfolio_dd.realized_pnl_r == 0.0


def test_recover_quarantined_idempotent():
    lc = TradeLifecycle()
    lc.register_open_context(_ctx(1))
    # Exit arrives with an UNKNOWN position id -> quarantined (DD untouched).
    assert lc.record_exit_deal(999, 777, -10.0, -1.0) == "quarantined"
    assert lc.portfolio_dd.realized_pnl_r == 0.0
    # Reconciliation maps deal 999 to context position 1 -> recorded once.
    assert lc.recover_quarantined(999, 1) == "recorded"
    assert lc.portfolio_dd.realized_pnl_r == -1.0
    # Idempotent: re-recovery and re-poll both no-ops.
    assert lc.recover_quarantined(999, 1) in ("not_found", "duplicate")
    assert lc.record_exit_deal(999, 1, -10.0, -1.0) == "duplicate"
    assert lc.portfolio_dd.realized_pnl_r == -1.0
    assert len(lc.realized_journal) == 1


# ── Broker-confirmed context factory ─────────────────────────────────


def test_build_open_context_from_fill_rejects_unconfirmed_ids():
    import pytest

    with pytest.raises(ValueError):
        build_open_context_from_fill(
            position_id=0,
            order_id=1,
            entry_deal_id=2,
            symbol="EURUSD",
            side="long",
            entry_price=1.1,
            initial_sl=1.099,
            base_lot=0.01,
            filled_volume=0.01,
            lot_multiplier=1.0,
            initial_risk_cash_total=10.0,
            initial_risk_cash_per_unit=1000.0,
        )
    ctx = build_open_context_from_fill(
        position_id=999,
        order_id=111,
        entry_deal_id=222,
        symbol="EURUSD",
        side="long",
        entry_price=1.1,
        initial_sl=1.099,
        base_lot=0.01,
        filled_volume=0.01,
        lot_multiplier=1.0,
        initial_risk_cash_total=10.0,
        initial_risk_cash_per_unit=1000.0,
    )
    assert ctx.position_id == 999 and ctx.remaining_volume == 0.01


# ── Persistence round-trip ───────────────────────────────────────────


def test_to_persisted_restore_roundtrip_json_safe():
    lc = TradeLifecycle(portfolio_dd=PortfolioDD(starting_balance_r=100.0))
    lc.register_open_context(_ctx(1))
    assert lc.record_exit_deal(101, 1, 10.0, 0.5, timestamp=1.0) == "recorded"
    lc.record_exit_deal(999, 424242, -10.0, -1.0)  # quarantined
    data = lc.to_persisted()
    # Must be JSON-serializable (no arbitrary Python objects).
    json.dumps(data)

    lc2 = TradeLifecycle()
    lc2.restore_persisted(data)
    assert lc2.portfolio_dd.realized_pnl_r == 0.5
    assert lc2.portfolio_dd.current_dd_r() == lc.portfolio_dd.current_dd_r()
    assert 999 in lc2.quarantined_exits
    assert lc2.dd_is_reliable()
    # Journal replay did not double-count.
    assert len(lc2.realized_journal) == 1
