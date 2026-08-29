#!/usr/bin/env python
"""P0-2 — LIVE RUNNER: authoritative production wiring.

Wires the real chain end-to-end:

    Signal (StrategyRuntime, untouched)
      -> base lot (PositionSizer.compute_lot)
      -> current DD (TradeLifecycle.portfolio_dd, journal-authoritative)
      -> RiskManager.evaluate (lot_multiplier)
      -> final quantized lot (PositionSizer.apply_scaling_and_quantize)
      -> Execution.send (TRADE_ACTION_DEAL)
      -> broker-confirmed fill (TRADE_RETCODE_DONE)
      -> TradeLifecycle.register_open_context (from FILL data, not request)
      -> TrailingBridge.sync (TRADE_ACTION_SLTP on changed SL)
      -> broker deal history poll
      -> TradeLifecycle.record_exit_deal (idempotent; unknown -> quarantine)
      -> PortfolioDD.record_realized (ONLY via the lifecycle)
      -> next entry

Safety:
- `signal_only=True` by default (no real orders; the whole chain can be
  rehearsed against the audit log without touching the broker).
- DD-unreliable state (restart without journal) PAUSES risk scaling.
- The lifecycle is the ONLY caller of PortfolioDD.record_realized.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.live.audit import AuditChain, EventType
from src.live.execution import Execution, OrderRequest
from src.live.portfolio_dd import PortfolioDD
from src.live.risk import Account, RiskManager
from src.live.sizing import ContractSpec, PositionSizer
from src.live.strategy_runtime import Signal, StrategyRuntime
from src.live.trade_lifecycle import (
    OpenTradeContext,
    TradeLifecycle,
    build_open_context_from_fill,
)
from src.live.trailing_bridge import TrailingBridge, TrailingEvent


@dataclass
class LiveRunnerStepResult:
    """Outcome of one `on_bar` + poll cycle (audit/test surface)."""

    signal: Optional[Signal] = None
    approved: bool = False
    blocked_reason: str = ""
    base_lot: float = 0.0
    final_lot: float = 0.0
    lot_multiplier: float = 1.0
    order_sent: bool = False
    fill: Optional[Any] = None
    context_registered: Optional[OpenTradeContext] = None
    trailing_events: List[TrailingEvent] = field(default_factory=list)
    exits: List[dict] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def default_contract(symbol: str) -> ContractSpec:
    """Conservative USD-account default (5-digit major)."""
    return ContractSpec(
        symbol=symbol,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        tick_size=0.00001,
        tick_value=1.0,
        contract_size=100000.0,
        stops_level=0.0,
        digits=5,
    )


class LiveRunner:
    """Authoritative live orchestration for ONE symbol."""

    DEAL_ENTRY_IN = 0  # mt5 DEAL_ENTRY_IN (open deal; ignored in polls)

    def __init__(
        self,
        symbol: str,
        mt5: Any = None,
        execution: Optional[Execution] = None,
        lifecycle: Optional[TradeLifecycle] = None,
        risk_manager: Optional[RiskManager] = None,
        sizer: Optional[PositionSizer] = None,
        contract: Optional[ContractSpec] = None,
        audit: Optional[AuditChain] = None,
        runtime: Optional[StrategyRuntime] = None,
        signal_only: bool = True,
        starting_balance_r: float = 100.0,
        magic: int = 9007001,
    ):
        if mt5 is None and execution is None:
            import MetaTrader5 as mt5_mod  # type: ignore

            mt5 = mt5_mod
        self.symbol = symbol
        self.mt5 = mt5
        self.magic = magic
        self.execution = execution or Execution(mt5=mt5, signal_only=signal_only)
        self.lifecycle = lifecycle or TradeLifecycle(
            portfolio_dd=PortfolioDD(starting_balance_r=starting_balance_r)
        )
        self.risk_manager = risk_manager or RiskManager()
        self.sizer = sizer or PositionSizer()
        self.contract = contract
        self.audit = audit or AuditChain()
        self.runtime = runtime or StrategyRuntime(symbol)
        open_positions_fn = self._positions_get
        self.bridge = TrailingBridge(
            execution=self.execution,
            is_open=lambda pid: open_positions_fn(pid),
        )
        self._position_to_ctx: Dict[int, OpenTradeContext] = {}
        self._last_poll_ts: float = time.time()
        self._known_position_ids: set = set()

    # ── Broker helpers (injectable in tests via self.mt5) ─────────
    def _positions_get(self, position_id: int) -> bool:
        if self.mt5 is None or not hasattr(self.mt5, "positions_get"):
            return True  # no broker snapshot available -> assume open
        try:
            positions = self.mt5.positions_get(ticket=int(position_id)) or []
        except Exception:
            return True  # transient failure -> do NOT treat as stale
        return len(positions) > 0

    def _resolve_position_id(self, result) -> Optional[int]:
        if result.position_id:
            return int(result.position_id)
        # Fallback: resolve via deal history (broker-confirmed entry deal).
        if (
            self.mt5 is not None
            and result.deal_id
            and hasattr(self.mt5, "history_deals_get")
        ):
            try:
                deals = self.mt5.history_deals_get(ticket=int(result.deal_id)) or []
                for d in deals:
                    pid = getattr(d, "position_id", None)
                    if pid:
                        return int(pid)
            except Exception:
                pass
        return None

    # ── Entry path ─────────────────────────────────────────────────
    def on_bar(self, bar, account: Account) -> LiveRunnerStepResult:
        """Process one closed 15m bar: strategy -> risk -> execution -> context."""
        res = LiveRunnerStepResult()
        sig = self.runtime.on_bar(bar)
        res.signal = sig
        if sig is None:
            return res

        contract = self.contract or default_contract(self.symbol)
        base_result = self.sizer.compute_lot(
            sig, balance=account.balance, contract=contract
        )
        res.base_lot = base_result.lot

        # Current DD — journal-authoritative; unreliable DD pauses scaling.
        if not self.lifecycle.dd_is_reliable():
            res.blocked_reason = "portfolio_dd_unreliable_pause"
            self._audit(
                EventType.RISK, {"approved": False, "reason": res.blocked_reason}
            )
            return res
        current_dd_r = self.lifecycle.portfolio_dd.current_dd_r()

        decision = self.risk_manager.evaluate(
            sig,
            account=account,
            contract=contract,
            spread=0.0,
            lot=base_result.lot,
            portfolio_dd_r=current_dd_r,
        )
        res.lot_multiplier = decision.lot_multiplier
        if not decision.approved or decision.blocked:
            res.blocked_reason = decision.reason or "risk_rejected"
            self._audit(
                EventType.RISK,
                {
                    "approved": False,
                    "reason": res.blocked_reason,
                    "lot_multiplier": decision.lot_multiplier,
                },
            )
            return res

        final_lot = PositionSizer.apply_scaling_and_quantize(
            base_lot=base_result.lot,
            lot_multiplier=decision.lot_multiplier,
            volume_step=contract.volume_step,
            volume_min=contract.volume_min,
            volume_max=contract.volume_max,
        )
        res.final_lot = final_lot
        if final_lot <= 0:
            # Includes the min-lot BLOCK semantics (reduction unachievable).
            res.blocked_reason = "scaled_lot_zero_minlot_block"
            self._audit(
                EventType.RISK, {"approved": False, "reason": res.blocked_reason}
            )
            return res

        res.approved = True
        order = OrderRequest(signal=sig, lot=final_lot, contract=contract)
        exec_result = self.execution.send(order)
        res.order_sent = exec_result.sent
        self._audit(
            EventType.ORDER,
            {
                "sent": exec_result.sent,
                "filled": exec_result.filled,
                "retcode": exec_result.retcode,
                "lot": final_lot,
            },
        )
        if not exec_result.filled:
            res.blocked_reason = exec_result.reason or "not_filled"
            return res

        res.fill = exec_result
        # Context from BROKER-CONFIRMED fill only (never the pre-send request).
        position_id = self._resolve_position_id(exec_result)
        if not position_id:
            res.errors.append("fill_without_position_id")
            return res
        fill_price = exec_result.fill_price or sig.entry_price
        filled_volume = exec_result.volume or final_lot
        risk_cash = self._risk_cash_total(fill_price, sig.sl, filled_volume, contract)
        ctx = build_open_context_from_fill(
            position_id=position_id,
            order_id=int(exec_result.order_id or 0),
            entry_deal_id=int(exec_result.deal_id or 0),
            symbol=sig.symbol,
            side=sig.side,
            entry_price=fill_price,
            initial_sl=sig.sl,
            base_lot=base_result.lot,
            filled_volume=filled_volume,
            lot_multiplier=decision.lot_multiplier,
            initial_risk_cash_total=risk_cash,
            initial_risk_cash_per_unit=(
                risk_cash / filled_volume if filled_volume > 0 else 0.0
            ),
        )
        self.lifecycle.register_open_context(ctx)
        self._position_to_ctx[position_id] = ctx
        self._known_position_ids.add(position_id)
        self.bridge.register_position(position_id, sig.sl, sig.tp)
        res.context_registered = ctx
        self._audit(
            EventType.POSITION,
            {
                "position_id": position_id,
                "entry": fill_price,
                "volume": filled_volume,
                "initial_risk_cash_total": risk_cash,
            },
        )
        return res

    @staticmethod
    def _risk_cash_total(entry_price, sl, volume, contract: ContractSpec) -> float:
        """Locked initial trade risk in account currency (from FILL data)."""
        stop_distance = abs(float(entry_price) - float(sl))
        if contract.tick_size <= 0 or contract.tick_value <= 0:
            return 0.0
        ticks = stop_distance / contract.tick_size
        return ticks * contract.tick_value * float(volume)

    # ── Open management: trailing ──────────────────────────────────
    def sync_trailing(self) -> List[TrailingEvent]:
        """Push runtime trailing decisions for open positions to MT5."""
        events: List[TrailingEvent] = []
        trade = self.runtime.active_trade
        if trade is None or trade.get("closed"):
            return events
        for position_id in list(self._position_to_ctx.keys()):
            events.append(self.bridge.sync(self.runtime, position_id))
        return events

    # ── Exit path: broker deal history ─────────────────────────────
    def poll_deals(self, now: Optional[float] = None) -> List[dict]:
        """Poll broker deal history; authoritative exits -> lifecycle.

        Uses position-based history queries (history_deals_get(position=pid))
        for broker compatibility. Time-range queries are NOT used because
        many brokers (including IC Markets demo) only support position-based
        deal history lookup.

        pnl_r = net realized cash / locked initial_risk_cash_total.
        Unknown/unmapped positions are quarantined by the lifecycle
        (PortfolioDD untouched).
        """
        now = now if now is not None else time.time()
        processed: List[dict] = []
        if self.mt5 is None or not hasattr(self.mt5, "history_deals_get"):
            return processed

        # 1. Get current open positions from broker
        try:
            current_positions = self.mt5.positions_get() or []
        except Exception as e:
            return [{"error": f"positions_get_failed: {e}"}]

        current_ids = set()
        for p in current_positions:
            magic = getattr(p, "magic", 0)
            if magic == self.magic:
                current_ids.add(p.ticket)

        # 2. Detect disappeared positions (were open, now closed)
        disappeared = self._known_position_ids - current_ids

        # 3. Query exit deal for each disappeared position
        for pid in disappeared:
            try:
                deals = self.mt5.history_deals_get(position=int(pid))
            except Exception as e:
                processed.append(
                    {"error": f"history_deals_get_failed: {e}", "position_id": pid}
                )
                continue

            if not deals:
                continue

            for d in deals:
                entry = getattr(d, "entry", None)
                if entry is None or int(entry) == self.DEAL_ENTRY_IN:
                    continue  # only exit deals realize PnL
                if int(getattr(d, "magic", 0) or 0) != self.magic:
                    continue  # not bot-owned
                cash = (
                    float(getattr(d, "profit", 0.0) or 0.0)
                    + float(getattr(d, "swap", 0.0) or 0.0)
                    + float(getattr(d, "commission", 0.0) or 0.0)
                )
                position_id = int(getattr(d, "position_id", 0) or 0)
                ctx = self.lifecycle.open_trades.get(position_id)
                risk_cash = ctx.initial_risk_cash_total if ctx else 0.0
                pnl_r = cash / risk_cash if risk_cash > 0 else 0.0
                deal_id = int(getattr(d, "ticket", 0) or 0)
                status = self.lifecycle.record_exit_deal(
                    deal_id=deal_id,
                    position_id=position_id,
                    net_realized_cash=cash,
                    pnl_r=pnl_r,
                    timestamp=float(getattr(d, "time", 0.0) or 0.0),
                )
                processed.append(
                    {
                        "deal_id": deal_id,
                        "position_id": position_id,
                        "status": status,
                        "cash": cash,
                        "pnl_r": pnl_r,
                    }
                )
                self._audit(
                    EventType.EXIT,
                    {
                        "deal_id": deal_id,
                        "position_id": position_id,
                        "status": status,
                        "cash": cash,
                        "pnl_r": pnl_r,
                    },
                )
                if status == "recorded" and position_id in self._position_to_ctx:
                    self.bridge.forget(position_id)
                    self._position_to_ctx.pop(position_id, None)

        # 4. Update known positions
        self._known_position_ids = current_ids | set(self.lifecycle.open_trades.keys())
        self._last_poll_ts = now
        return processed

    # ── helpers ─────────────────────────────────────────────────────
    def _audit(self, event_type: EventType, payload: dict) -> None:
        try:
            self.audit.append(time.time(), event_type, self.symbol, payload)
        except Exception:
            pass
