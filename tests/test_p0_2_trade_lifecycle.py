#!/usr/bin/env python
"""P0-2 — TradeLifecycle regression tests (minimal, no strategy change)."""

from src.live.portfolio_dd import PortfolioDD
from src.live.trade_lifecycle import OpenTradeContext, TradeLifecycle


def test_trade_lifecycle_register_and_process():
    lifecycle = TradeLifecycle()
    ctx = OpenTradeContext(
        position_id=1,
        symbol="EURUSD",
        side="long",
        entry_price=1.10,
        initial_sl=1.095,
        base_lot=0.06,
        final_lot=0.06,
        initial_risk_cash_total=60.0,
        initial_risk_cash_per_lot_or_unit=1000.0,
    )
    lifecycle.register_open_context(ctx)
    assert lifecycle.open_trades[1].position_id == 1


def test_process_exit_deal_idempotent():
    lifecycle = TradeLifecycle()
    lifecycle.register_open_context(OpenTradeContext(position_id=1, symbol="EURUSD"))
    # First process
    accepted = lifecycle.process_exit_deal(100, 1, 10.5, 0.01)
    assert accepted is True
    assert 100 in lifecycle.last_seen_deals
    # Duplicate -> ignored, PortfolioDD not updated again
    dd_before = lifecycle.portfolio_dd.current_dd_r()
    accepted2 = lifecycle.process_exit_deal(100, 1, 10.5, 0.01)
    assert accepted2 is False
    dd_after = lifecycle.portfolio_dd.current_dd_r()
    assert dd_after == dd_before  # no double-counting


def test_portfolio_dd_updated_once_per_realized():
    lifecycle = TradeLifecycle(portfolio_dd=PortfolioDD(starting_balance_r=100.0))
    lifecycle.register_open_context(
        OpenTradeContext(position_id=1, symbol="EURUSD", initial_risk_cash_total=10.0)
    )
    lifecycle.process_exit_deal(101, 1, 5.0, 0.5)
    assert lifecycle.portfolio_dd.current_equity_r() == 100.5
    assert lifecycle.portfolio_dd.current_dd_r() == 0.0  # at peak (no drawdown)


def test_partial_close_preserves_remaining_context():
    lifecycle = TradeLifecycle()
    ctx = OpenTradeContext(
        position_id=2,
        symbol="GBPUSD",
        base_lot=0.12,
        final_lot=0.12,
        filled_volume=0.12,
        remaining_volume=0.06,
    )
    lifecycle.register_open_context(ctx)
    # Partial close deal: only part of volume realized
    lifecycle.process_exit_deal(201, 2, 3.0, 0.25)
    # Context preserved for remaining volume (not deleted)
    assert 2 in lifecycle.open_trades
    # Processed deal tracked
    assert 201 in lifecycle.open_trades[2].processed_deal_ids


def test_restart_rebuild_preserves_accumulated_r():
    lifecycle = TradeLifecycle()
    lifecycle.register_open_context(
        OpenTradeContext(
            position_id=3,
            symbol="USDJPY",
            realized_r_accumulated=2.5,
        )
    )
    contexts = list(lifecycle.open_trades.values())
    new_lifecycle = TradeLifecycle()
    new_lifecycle.rebuild_from_persisted(contexts)
    assert 3 in new_lifecycle.open_trades
    # Accumulated realized R preserved (minimal rebuild from open context)
    assert new_lifecycle.open_trades[3].realized_r_accumulated == 2.5
