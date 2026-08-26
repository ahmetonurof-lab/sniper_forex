"""
Trailing Adapter — analyzer_v5.py inline trailing logic with EXACT parity.

CRITICAL: This is a DIRECT PORT of analyzer_v5.py trailing behavior.
- FVG detection: detect_fvgs(tc, lookback=50, timeframe="15m", min_fvg_size=...)
- FVG confirm: fvg_close_confirmed(fvg, chunk)
- SL calculation: fvg.bottom - ATR*0.10 (long) / fvg.top + ATR*0.10 (short)
- Min move filter: risk * TRAIL_MIN_MOVE_MULT
- TP parallel shift: ctp += sl_delta (long) / ctp -= sl_delta (short)

NO CHANGES to trailing algorithm. NO optimization.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

# ── Import NEXUS fvg module (for detect_fvgs + fvg_close_confirmed) ──
_NEXUS_SNIPER_SRC = str(Path("C:/Users/Administrator/Desktop/nexus-mcp/sniper/src"))
if _NEXUS_SNIPER_SRC not in sys.path:
    sys.path.insert(0, _NEXUS_SNIPER_SRC)

from fvg import detect_fvgs as _nexus_detect_fvgs  # noqa: E402
from models import Bar as NexusBar, FVG as NexusFVG  # noqa: E402

# ── Import sniper_forex Bar ──
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.strategy.models import Bar as ForexBar  # noqa: E402

# ── Config ──
from experiment.config import (  # noqa: E402
    ATR_TRAIL_MULT,
    TRAIL_MIN_MOVE_MULT,
    FVG_MIN_SIZE_ATR_MULT,
    FVG_WICK_RATIO_MAX,
)


def _norm_side(side: str) -> str:
    """
    Direction-dispatch compatibility fix (2026-08-22 forensic root cause).

    Trade dicts were created with side/direction = "bullish"/"bearish" while
    every execution branch below tests "long"/"short". As a result ALL long
    trades were routed through the short exit/trailing branch (instant
    bar.high >= sl kill, unreachable TP, fake PROFIT_TRAIL wins).

    This normalizes the label ONCE at the execution boundary. It changes ONLY
    dispatch — not trailing parameters, not strategy rules.
    """
    if side in ("long", "bullish"):
        return "long"
    if side in ("short", "bearish"):
        return "short"
    return side


def _to_nexus_bar(bar: ForexBar) -> NexusBar:
    """Convert sniper_forex Bar to NEXUS Bar format."""
    return NexusBar(
        index=bar.index,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        is_closed=True,
        timestamp=int(bar.timestamp.timestamp() * 1000)
        if hasattr(bar.timestamp, "timestamp")
        else 0,
    )


def _fvg_close_confirmed(fvg: NexusFVG, bars: list[NexusBar]) -> bool:
    """
    Exact copy of trailing_manager._fvg_close_confirmed().
    Retrace-only: gap ici kapanis onaylar; far-side invalidation.
    """
    scan_from = fvg.real_index + 2
    for b in bars:
        if b.index < scan_from:
            continue
        if fvg.direction == "bullish":
            if b.close < fvg.bottom:
                return False
            if fvg.bottom <= b.close <= fvg.top:
                return True
        else:
            if b.close > fvg.top:
                return False
            if fvg.bottom <= b.close <= fvg.top:
                return True
    return False


def apply_trailing(
    bars_15m: List[ForexBar],
    trades: list[dict],
    atr_val: float,
    symbol: str = "",
) -> dict:
    """
    Apply NEXUS inline trailing to a list of open trades.

    This is the EXACT logic from analyzer_v5.py lines 1208-1394.

    Args:
        bars_15m: 15m bar list (full history for FVG detection)
        trades: list of open trade dicts (modified in-place)
        atr_val: current ATR value
        symbol: symbol name (for FVG_SIZE_MAP lookup)

    Returns:
        dict with trailing stats
    """
    if not bars_15m or len(bars_15m) <= 1:
        return {"trailed": 0, "total_hops": 0}

    # ── Prepare chunk (last 50 bars for FVG detection) ──
    chunk = bars_15m[:-1]  # exclude current bar (no look-ahead)
    if not chunk:
        return {"trailed": 0, "total_hops": 0}

    # ── Detect FVGs for trailing (independent of entry FVG) ──
    min_mult = FVG_MIN_SIZE_ATR_MULT
    min_fvg_size = max(atr_val * min_mult, 1e-8)

    # Convert chunk to NEXUS bars
    nexus_chunk = [_to_nexus_bar(b) for b in chunk]

    cfvgs = _nexus_detect_fvgs(
        nexus_chunk,
        lookback=min(50, len(nexus_chunk)),
        timeframe="15m",
        min_fvg_size=min_fvg_size,
        max_wick_ratio=FVG_WICK_RATIO_MAX,
    )

    # ── Apply trailing to each open trade ──
    trailed_count = 0
    total_hops = 0

    for t in trades:
        if t.get("closed"):
            continue

        s2 = _norm_side(t["side"])
        csl = t["sl"]
        ctp = t["tp"]
        rpt2 = abs(t["initial_sl"] - t["entry_price"])
        ltc = 0

        if rpt2 <= 0:
            continue

        # ── FVG Trailing (main path) ──
        for fvg in cfvgs:
            if s2 == "long" and fvg.direction != "bullish":
                continue
            if s2 == "short" and fvg.direction != "bearish":
                continue

            # Retrace-only: gap ici kapanis onay
            if not _fvg_close_confirmed(fvg, nexus_chunk):
                continue

            # SL calculation
            ab2 = atr_val * ATR_TRAIL_MULT

            if s2 == "long":
                ns = fvg.bottom - ab2
                if ns > csl and (ns - csl) > rpt2 * TRAIL_MIN_MOVE_MULT:
                    sd2 = ns - csl
                    csl = ns
                    ctp += sd2
                    ltc += 1
            else:
                ns = fvg.top + ab2
                if ns < csl and (csl - ns) > rpt2 * TRAIL_MIN_MOVE_MULT:
                    sd2 = csl - ns
                    csl = ns
                    ctp -= sd2
                    ltc += 1

        # ── Update trade state ──
        if ltc > 0:
            t["sl"] = csl
            t["tp"] = ctp
            t["trailing_count"] = t.get("trailing_count", 0) + ltc
            trailed_count += 1
            total_hops += ltc

    return {"trailed": trailed_count, "total_hops": total_hops}


def check_exit(
    bar: ForexBar,
    trade: dict,
) -> Optional[dict]:
    """
    Check if trade should be exited (SL or TP hit).
    Exact logic from analyzer_v5.py exit section.

    Args:
        bar: current 15m bar
        trade: trade dict

    Returns:
        dict with exit info or None if no exit
    """
    s2 = _norm_side(trade["side"])
    sl = trade["sl"]
    tp = trade["tp"]

    if s2 == "long":
        if bar.low <= sl:
            result = (
                "PROFIT_TRAIL"
                if (trade.get("trailing_count", 0) > 0 and sl > trade["entry_price"])
                else "LOSS"
            )
            return {"exit_price": sl, "result": result}
        if bar.high >= tp:
            return {"exit_price": tp, "result": "TP"}
    else:
        if bar.high >= sl:
            result = (
                "PROFIT_TRAIL"
                if (trade.get("trailing_count", 0) > 0 and sl < trade["entry_price"])
                else "LOSS"
            )
            return {"exit_price": sl, "result": result}
        if bar.low <= tp:
            return {"exit_price": tp, "result": "TP"}

    return None
