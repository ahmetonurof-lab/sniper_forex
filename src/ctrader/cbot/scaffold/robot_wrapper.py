"""robot_wrapper.py — convenience helpers for cTrader Automate Python cBots.

Source: spotware/ctrader-python-algo-samples (MIT-licensed).
This file provides order-entry convenience functions. The CBDR calibration
bot does not trade, but the file is included because some bridge codepaths
expect it as a registered in-memory module.
"""

from cAlgo.API import *


def execute_market_order(volume, symbol, trade_type, stop_loss=None, take_profit=None):
    """Execute a market order with optional SL/TP."""
    request = CreateMarketOrderRequest(trade_type, symbol.Name, volume)
    request.StopLoss = stop_loss
    request.TakeProfit = take_profit
    return api.SendOrder(request)


def close_position(position):
    """Close an open position at market."""
    request = ClosePositionRequest(position.Id)
    return api.ClosePosition(request)


def modify_position(position, stop_loss=None, take_profit=None):
    """Modify SL/TP on an open position."""
    request = ModifyPositionRequest(position.Id)
    request.StopLoss = stop_loss
    request.TakeProfit = take_profit
    return api.ModifyPosition(request)


def place_stop_order(volume, symbol, trade_type, entry_price, stop_loss=None, take_profit=None):
    """Place a stop order."""
    request = CreateStopOrderRequest(trade_type, symbol.Name, volume, entry_price)
    request.StopLoss = stop_loss
    request.TakeProfit = take_profit
    return api.SendOrder(request)


def place_limit_order(volume, symbol, trade_type, entry_price, stop_loss=None, take_profit=None):
    """Place a limit order."""
    request = CreateLimitOrderRequest(trade_type, symbol.Name, volume, entry_price)
    request.StopLoss = stop_loss
    request.TakeProfit = take_profit
    return api.SendOrder(request)


def cancel_order(pending_order):
    """Cancel a pending order."""
    request = CancelPendingOrderRequest(pending_order.Id)
    return api.CancelPendingOrder(request)


def modify_pending_order(
    pending_order, volume=None, entry_price=None, stop_loss=None, take_profit=None
):
    """Modify a pending order."""
    request = ModifyPendingOrderRequest(pending_order.Id)
    if volume is not None:
        request.Volume = volume
    if entry_price is not None:
        request.TargetPrice = entry_price
    request.StopLoss = stop_loss
    request.TakeProfit = take_profit
    return api.ModifyPendingOrder(request)
