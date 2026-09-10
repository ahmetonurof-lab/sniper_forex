#!/usr/bin/env python
"""cTrader position → internal Position conversion (İş-4a / reconciliation).

Pure, testable conversion functions. The MT5 path
(`position_manager._to_position`) is NOT touched — this is a parallel
cTrader adapter (§2.2: no duplicate source of truth; the Reconciler
consumes the same `Position` dataclass).

Proto schema (verified from ctrader_open_api OpenApiModelMessages_pb2):
  ProtoOAPosition:
    positionId (int64, 1)
    tradeData (ProtoOATradeData, 2)
    positionStatus (enum, 3)   # POSITION_STATUS_OPEN=1
    swap (int64, 4)
    price (double, 5)          # entry price, raw (not scaled)
    stopLoss (double, 6)
    takeProfit (double, 7)
    utcLastUpdateTimestamp (int64, 8)
    commission (int64, 9)
    ...
  ProtoOATradeData:
    symbolId (int64, 1)
    volume (int64, 2)          # protocol volume = lot x contract_size x 100
    tradeSide (enum, 3)        # BUY=1, SELL=2
    openTimestamp (int64, 4)   # epoch ms
    label (string, 5)
    comment (string, 7)

Volume decode: protocol_volume = lot x contract_size x 100
(`src/ctrader/execution.py::_protocol_volume`). To recover lots:
    lots = protocol_volume / (contract_size * 100)

Ownership: cTrader has no magic number; bot-owned positions are
identified by `label == CTRADER_BOT_LABEL` (mirrors the label written by
`src/ctrader/execution.py` and the `connection.py` default).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.live.position_manager import Position

# Bot-owned label (mirrors src/ctrader/execution.py + connection.py default).
CTRADER_BOT_LABEL = "SNIPER_FOREX"

# ProtoOAPositionStatus
POSITION_STATUS_OPEN = 1

# ProtoOATradeSide
TRADE_SIDE_BUY = 1
TRADE_SIDE_SELL = 2


def _normalize_side(trade_side: Any) -> str:
    """cTrader tradeSide (BUY=1, SELL=2) → 'long'/'short'."""
    try:
        return "long" if int(trade_side) == TRADE_SIDE_BUY else "short"
    except Exception:
        return str(trade_side)


def position_to_dict(
    raw: Any,
    contract_size: float,
    symbol_name: str,
) -> Optional[Dict[str, Any]]:
    """Convert a ProtoOAPosition to an MT5-shaped dict (snapshot/audit).

    Returns None for non-OPEN positions (positionStatus != OPEN) or
    malformed input. Volume is decoded from protocol units to lots.
    """
    if raw is None:
        return None
    try:
        status = int(getattr(raw, "positionStatus", 0))
        if status != POSITION_STATUS_OPEN:
            return None
        trade_data = getattr(raw, "tradeData", None)
        if trade_data is None:
            return None
        protocol_volume = int(getattr(trade_data, "volume", 0))
        cs = float(contract_size) if contract_size else 1.0
        volume_lots = protocol_volume / (cs * 100.0) if cs > 0 else 0.0
        return {
            "ticket": int(getattr(raw, "positionId", 0)),
            "symbol": str(symbol_name),
            "side": _normalize_side(getattr(trade_data, "tradeSide", 0)),
            "volume": volume_lots,
            "entry_price": float(getattr(raw, "price", 0.0)),
            "sl": float(getattr(raw, "stopLoss", 0.0)),
            "tp": float(getattr(raw, "takeProfit", 0.0)),
            "magic": 0,  # cTrader has no magic; label is the ownership key
            "comment": str(getattr(trade_data, "comment", "")),
            "open_time": float(getattr(trade_data, "openTimestamp", 0.0)) / 1000.0,
            "profit": 0.0,  # not directly available on ProtoOAPosition
            "swap": float(getattr(raw, "swap", 0.0)),
            "label": str(getattr(trade_data, "label", "")),
        }
    except Exception:
        return None


def _to_position_ctrader(
    raw_dict: Dict[str, Any],
    label_filter: str = CTRADER_BOT_LABEL,
) -> Optional[Position]:
    """Convert an MT5-shaped cTrader position dict to our `Position`.

    Filters by bot-owned label (cTrader has no magic number). Returns
    None for non-bot positions or malformed input.
    """
    if not raw_dict:
        return None
    label = str(raw_dict.get("label", ""))
    if label_filter and label != label_filter:
        return None
    try:
        return Position(
            ticket=int(raw_dict.get("ticket", 0)),
            symbol=str(raw_dict.get("symbol", "")),
            side=str(raw_dict.get("side", "long")),
            volume=float(raw_dict.get("volume", 0.0)),
            entry_price=float(raw_dict.get("entry_price", 0.0)),
            sl=float(raw_dict.get("sl", 0.0)),
            tp=float(raw_dict.get("tp", 0.0)),
            magic=int(raw_dict.get("magic", 0)),
            comment=str(raw_dict.get("comment", "")),
            open_time=raw_dict.get("open_time"),
            profit=float(raw_dict.get("profit", 0.0)),
            swap=float(raw_dict.get("swap", 0.0)),
        )
    except Exception:
        return None
