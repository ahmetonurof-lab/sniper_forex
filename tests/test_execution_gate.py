#!/usr/bin/env python
"""Unit tests for Execution.send() order_check fix."""

from unittest.mock import MagicMock
import sys

sys.path.insert(0, r"C:\Users\Administrator\Desktop\sniper_forex")

from src.live.execution import Execution, OrderRequest
from src.live.sizing import ContractSpec
from src.live.strategy_runtime import Signal


def make_signal(sl=1.15350, tp=1.16850):
    return Signal(
        symbol="EURUSD",
        direction="long",
        side="long",
        entry_price=1.15850,
        sl=sl,
        tp=tp,
        entry_bar_index=0,
        sweep_bar_index=0,
        zone_index=0,
        zone_top=0.0,
        zone_bottom=0.0,
        zone_size=0.0,
        timestamp=None,
    )


def make_contract():
    return ContractSpec(
        symbol="EURUSD",
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        tick_size=0.00001,
        tick_value=1.0,
        contract_size=100000.0,
        stops_level=0.0,
        digits=5,
    )


def make_mock_mt5(
    check_retcode=0,
    send_retcode=10009,
    send_order=1001,
    send_deal=2001,
    send_price=1.15850,
    send_volume=0.06,
):
    mock = MagicMock()
    mock.TRADE_RETCODE_DONE = 10009
    mock.TRADE_ACTION_DEAL = 1
    mock.ORDER_TYPE_BUY = 0
    mock.ORDER_TYPE_SELL = 1
    mock.ORDER_TIME_GTC = 0
    mock.ORDER_FILLING_IOC = 1
    mock.TRADE_ACTION_SLTP = 2
    mock.TRADE_RETCODE_REQUOTE = 10004
    mock.TRADE_RETCODE_PRICE_CHANGED = 10005
    mock.TRADE_RETCODE_PRICE_OFF = 10006
    mock.TRADE_RETCODE_CONNECTION = 10031
    mock.TRADE_RETCODE_TIMEOUT = 10036
    mock.TRADE_RETCODE_RETRY = 10032
    mock.TRADE_RETCODE_REJECT = 10016
    mock.TRADE_RETCODE_DONE_PARTIAL = 10010

    # order_check returns retcode=0 on success (NOT TRADE_RETCODE_DONE)
    check_result = MagicMock()
    check_result.retcode = check_retcode
    check_result.comment = "Done" if check_retcode == 0 else "Error"
    mock.order_check.return_value = check_result

    # order_send
    send_result = MagicMock()
    send_result.retcode = send_retcode
    send_result.order = send_order
    send_result.deal = send_deal
    send_result.price = send_price
    send_result.volume = send_volume
    send_result.position = send_order  # position = order for simplicity
    send_result.comment = "Done"
    mock.order_send.return_value = send_result

    return mock


def test_order_check_success_allows_send():
    """order_check retcode=0 (success) should allow order_send to proceed."""
    mock_mt5 = make_mock_mt5(check_retcode=0, send_retcode=10009)
    exec_engine = Execution(mock_mt5, signal_only=False, magic=9007001)
    req = OrderRequest(signal=make_signal(), lot=0.06, contract=make_contract())
    result = exec_engine.send(req)
    assert result.filled is True, f"Expected filled=True, got {result.filled}"
    assert result.sent is True
    assert result.order_id == 1001
    assert result.deal_id == 2001
    assert result.fill_price == 1.15850
    print("PASS: test_order_check_success_allows_send")


def test_order_check_failure_blocks_send():
    """order_check retcode!=0 should block order_send."""
    mock_mt5 = make_mock_mt5(check_retcode=10013, send_retcode=10009)
    exec_engine = Execution(mock_mt5, signal_only=False, magic=9007001)
    req = OrderRequest(signal=make_signal(), lot=0.06, contract=make_contract())
    result = exec_engine.send(req)
    assert result.filled is False, f"Expected filled=False, got {result.filled}"
    assert result.sent is False
    assert "order_check_failed" in result.reason
    mock_mt5.order_send.assert_not_called()
    print("PASS: test_order_check_failure_blocks_send")


def test_order_check_exception_blocks_send():
    """order_check exception should block order_send."""
    mock_mt5 = make_mock_mt5()
    mock_mt5.order_check.side_effect = Exception("Connection lost")
    exec_engine = Execution(mock_mt5, signal_only=False, magic=9007001)
    req = OrderRequest(signal=make_signal(), lot=0.06, contract=make_contract())
    result = exec_engine.send(req)
    assert result.filled is False
    assert result.sent is False
    assert "order_check_exception" in result.reason
    mock_mt5.order_send.assert_not_called()
    print("PASS: test_order_check_exception_blocks_send")


def test_order_send_rejection():
    """order_send retcode!=TRADE_RETCODE_DONE should return filled=False."""
    mock_mt5 = make_mock_mt5(check_retcode=0, send_retcode=10016)
    exec_engine = Execution(mock_mt5, signal_only=False, magic=9007001)
    req = OrderRequest(signal=make_signal(), lot=0.06, contract=make_contract())
    result = exec_engine.send(req)
    assert result.filled is False
    assert result.sent is True
    assert result.retcode == 10016
    print("PASS: test_order_send_rejection")


def test_signal_only_mode():
    """signal_only=True should never send, even with valid check."""
    mock_mt5 = make_mock_mt5(check_retcode=0, send_retcode=10009)
    exec_engine = Execution(mock_mt5, signal_only=True, magic=9007001)
    req = OrderRequest(signal=make_signal(), lot=0.06, contract=make_contract())
    result = exec_engine.send(req)
    assert result.filled is False
    assert result.sent is False
    assert result.dry_run is True
    mock_mt5.order_send.assert_not_called()
    print("PASS: test_signal_only_mode")


def test_lot_zero_blocked():
    """lot<=0 should return immediately without calling order_check."""
    mock_mt5 = make_mock_mt5()
    exec_engine = Execution(mock_mt5, signal_only=False, magic=9007001)
    req = OrderRequest(signal=make_signal(), lot=0.0, contract=make_contract())
    result = exec_engine.send(req)
    assert result.filled is False
    assert result.sent is False
    assert "lot<=0" in result.reason
    mock_mt5.order_check.assert_not_called()
    print("PASS: test_lot_zero_blocked")


if __name__ == "__main__":
    test_order_check_success_allows_send()
    test_order_check_failure_blocks_send()
    test_order_check_exception_blocks_send()
    test_order_send_rejection()
    test_signal_only_mode()
    test_lot_zero_blocked()
    print("\nAll unit tests passed!")
