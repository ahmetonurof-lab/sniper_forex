#!/usr/bin/env python
"""P0-1 — LIVE MT5 TRAILING BRIDGE.

Carries `StrategyRuntime`'s trailing decisions to the real MT5 broker
WITHOUT modifying the runtime (the frozen strategy files are protected).

Chain implemented here:

    StrategyRuntime.on_bar()            (untouched; mutates active_trade dict)
        -> trailing decision visible as active_trade["sl"]/["tp"] change
        -> TrailingBridge.sync()
        -> Execution.modify_position_sl_tp()   (TRADE_ACTION_SLTP)
        -> broker confirmation (TRADE_RETCODE_DONE)
        -> bridge updates broker-confirmed SL/TP state
        -> subsequent broker-side SL/TP close (authoritative result)

Design rules:
- The runtime's trailing formula/thresholds are NOT touched. The bridge
  only OBSERVES the resulting `active_trade` dict.
- A modification is sent ONLY when the desired (sl, tp) differs from the
  last broker-confirmed state. Duplicate suppression is enforced in
  `Execution.modify_position_sl_tp`.
- Local "current_sl" is broker-confirmed state only. The runtime's
  simulation dict keeps its own values (used for exit simulation parity);
  the bridge never writes trailing values back into the runtime.
- Stale protection: if the position is no longer open (per the injected
  `is_open` check or a runtime-closed trade), NO modify is sent and the
  position is forgotten.
- Broker rejections are returned and recorded (never silently ignored).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from src.live.execution import Execution, ModifyResult
from src.live.strategy_runtime import StrategyRuntime


@dataclass
class TrailingEvent:
    """One bridge sync outcome (for audit / tests)."""

    position_id: int
    symbol: str
    action: str  # "sent" | "skipped" | "stale" | "no_change" | "no_trade"
    desired_sl: Optional[float] = None
    desired_tp: Optional[float] = None
    confirmed: bool = False
    reason: str = ""
    modify: Optional[ModifyResult] = None


@dataclass
class TrailingBridge:
    """Bridges runtime trailing decisions to real MT5 SL modifications."""

    execution: Execution
    # Optional broker-side liveness check: position_id -> bool.
    # LiveRunner injects PositionManager-backed lookup; tests may inject
    # a fake. When None, the bridge relies on runtime state only.
    is_open: Optional[Callable[[int], bool]] = None
    # Broker-confirmed SL/TP per position (authoritative local mirror).
    confirmed: Dict[int, tuple] = field(default_factory=dict)
    last_events: List[TrailingEvent] = field(default_factory=list)

    # -- Registration ------------------------------------------------
    def register_position(self, position_id: int, sl: float, tp: float) -> None:
        """Register a broker-confirmed entry fill's initial SL/TP."""
        self.confirmed[int(position_id)] = (float(sl), float(tp))

    def confirmed_sl(self, position_id: int) -> Optional[float]:
        entry = self.confirmed.get(int(position_id))
        return entry[0] if entry else None

    def forget(self, position_id: int) -> None:
        """Drop state for a closed position."""
        self.confirmed.pop(int(position_id), None)
        try:
            self.execution.forget_position(position_id)
        except Exception:
            pass

    def audit_trail(self) -> List[TrailingEvent]:
        """Read-only copy of all bridge events (for audit / tests)."""
        return list(self.last_events)

    # -- Sync ----------------------------------------------------------
    def sync(self, runtime: StrategyRuntime, position_id: int) -> TrailingEvent:
        """Push the runtime's current trailing decision to MT5 (if changed).

        Reads `runtime.active_trade["sl"]/["tp"]` (the trailing adapter
        mutates these in place). Sends a TRADE_ACTION_SLTP modify ONLY for
        a changed SL/TP, ONLY for an open position, and treats local
        state as updated only after broker confirmation.
        """
        trade = runtime.active_trade
        symbol = runtime.symbol

        if trade is None or trade.get("closed"):
            ev = TrailingEvent(
                position_id=int(position_id),
                symbol=symbol,
                action="no_trade",
                reason="no active trade",
            )
            self.last_events.append(ev)
            return ev

        desired_sl = float(trade.get("sl", 0.0))
        desired_tp = float(trade.get("tp", 0.0))

        # Stale protection: position closed at the broker -> never send.
        if self.is_open is not None and not self.is_open(int(position_id)):
            self.forget(position_id)
            ev = TrailingEvent(
                position_id=int(position_id),
                symbol=symbol,
                action="stale",
                reason="position not open at broker",
            )
            self.last_events.append(ev)
            return ev

        confirmed_entry = self.confirmed.get(int(position_id))
        if confirmed_entry is not None:
            conf_sl, conf_tp = confirmed_entry
            if desired_sl == conf_sl and desired_tp == conf_tp:
                ev = TrailingEvent(
                    position_id=int(position_id),
                    symbol=symbol,
                    action="no_change",
                    desired_sl=desired_sl,
                    desired_tp=desired_tp,
                    reason="broker-confirmed state already matches",
                )
                self.last_events.append(ev)
                return ev

        result = self.execution.modify_position_sl_tp(
            position_ticket=int(position_id),
            symbol=symbol,
            sl=desired_sl,
            tp=desired_tp,
        )
        if result.confirmed:
            # Broker-confirmed -> authoritative local mirror update.
            self.confirmed[int(position_id)] = (desired_sl, desired_tp)
            ev = TrailingEvent(
                position_id=int(position_id),
                symbol=symbol,
                action="sent",
                desired_sl=desired_sl,
                desired_tp=desired_tp,
                confirmed=True,
                modify=result,
            )
        else:
            # Rejected / dry-run / duplicate: NO local state change. The
            # rejection is surfaced (never silently ignored).
            ev = TrailingEvent(
                position_id=int(position_id),
                symbol=symbol,
                action="skipped",
                desired_sl=desired_sl,
                desired_tp=desired_tp,
                confirmed=False,
                reason=result.reason or result.retcode_name or "unconfirmed",
                modify=result,
            )
        self.last_events.append(ev)
        return ev
