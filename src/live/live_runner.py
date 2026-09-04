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
from src.live.reconciliation import Reconciler
from src.live.risk import Account, RiskManager
from src.live.sizing import ContractSpec, PositionSizer
from src.live.strategy_runtime import Signal, StrategyRuntime, signal_audit_payload
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
        auto_snapshot: bool = False,
        configured_symbols: Optional[List[str]] = None,
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
        # N2 #23 R-1: the runtime owns the CBDR STATE observation layer;
        # wire THIS runner's audit sink into it (covers both the runtime
        # created here and an injected one without a sink — e.g. the
        # orchestrator handoff path). Idempotent; never overwrites a
        # sink that is already attached.
        if getattr(self.runtime, "audit", None) is None:
            self.runtime.audit = self.audit
        self._position_to_ctx: Dict[int, OpenTradeContext] = {}
        self._last_poll_ts: float = time.time()
        self._known_position_ids: set = set()
        open_positions_fn = self._positions_get
        self.bridge = TrailingBridge(
            execution=self.execution,
            is_open=lambda pid: open_positions_fn(pid),
        )
        if auto_snapshot:
            self.startup_snapshot(configured_symbols=configured_symbols)

    # ── Broker helpers (injectable in tests via self.mt5) ─────────
    def _positions_get(self, position_id: int) -> bool:
        if self.mt5 is None or not hasattr(self.mt5, "positions_get"):
            return True  # no broker snapshot available -> assume open
        try:
            positions = self.mt5.positions_get(ticket=int(position_id)) or []
        except Exception:
            return True  # transient failure -> do NOT treat as stale
        return len(positions) > 0

    # ── C2 entry lock (KARAR-2: symbol-based, never global) ──────
    def _symbol_entry_locked(self) -> bool:
        """True when THIS symbol already carries a bot-owned open trade.

        KARAR-2 policy: an open trade on a pair blocks new entries on the
        SAME pair only. Other pairs are unaffected (each symbol runs in its
        own process/runner — there is no portfolio-wide entry lock).

        Broker truth first: live positions filtered by bot magic, using the
        SAME convention as ``poll_deals`` (no parallel source of truth).
        The in-process fill view (``_position_to_ctx``) is unioned so a
        broker snapshot that lags a fresh fill — or a position whose exit
        the next poll has not recorded yet — cannot admit a second entry.
        Unknown broker state (no mt5 / no ``positions_get`` / exception) is
        treated as LOCKED: fail-safe, mirroring ``_positions_get``'s
        "assume open" convention. Positions without a ``symbol`` attribute
        (test seams) are attributed to this runner's symbol; positions
        without the bot magic are never bot-owned.
        """
        if self.mt5 is None or not hasattr(self.mt5, "positions_get"):
            return True  # no broker truth available -> conservative lock
        try:
            positions = self.mt5.positions_get() or []
        except Exception:
            return True  # transient failure -> do NOT admit a new entry
        for p in positions:
            if int(getattr(p, "magic", 0) or 0) != self.magic:
                continue
            sym = getattr(p, "symbol", None)
            if sym is not None and str(sym) != self.symbol:
                continue
            return True
        for ctx in self._position_to_ctx.values():
            if getattr(ctx, "symbol", self.symbol) != self.symbol:
                continue
            if float(getattr(ctx, "remaining_volume", 0.0) or 0.0) > 0:
                return True
        return False

    # ── Startup snapshot (S5 broker state + S8 recon gate) ────────────

    def startup_snapshot(
        self,
        configured_symbols: Optional[List[str]] = None,
    ) -> dict:
        """Capture broker + local state at startup (S5/S8).

        Returns a dict consumed by the orchestrator's S5/S8 phases:

            mt5_connected: bool
            mt5_build: str
            account: str  (login or "unknown")
            server: str
            balance: float
            equity: float
            symbols: list[str]
            positions: list[dict]  (bot-magic, with SL/TP audit info)
            pending_orders: list[dict]
            reconciliation: {
                status: str,         # "OK" | "ORPHAN" | "UNKNOWN_OPEN" | "MISMATCH" | "NOT_RUN"
                block_trading: bool,
                details: list[str],
            }
            local_state: {
                dd_reliable: bool,
                quarantined_exits_count: int,
                known_position_ids: list[int],
            }
            safe_mode: bool  (True if connected=False OR recon blocks OR DD unreliable)
        """
        from src.live.position_manager import _to_position

        snapshot: Dict[str, Any] = {
            "mt5_connected": False,
            "mt5_build": "unknown",
            "account": "unknown",
            "server": "unknown",
            "balance": 0.0,
            "equity": 0.0,
            "symbols": configured_symbols or [self.symbol],
            "positions": [],
            "pending_orders": [],
            "reconciliation": {
                "status": "NOT_RUN",
                "block_trading": True,
                "details": [],
            },
            "local_state": {
                "dd_reliable": self.lifecycle.dd_is_reliable(),
                "quarantined_exits_count": len(self.lifecycle.quarantined_exits),
                "known_position_ids": sorted(self._known_position_ids),
            },
            "safe_mode": False,
        }

        # ── Connected? ──────────────────────────────────────
        if self.mt5 is None:
            snapshot["safe_mode"] = True
            self._emit_startup_audit(snapshot)
            return snapshot

        # terminal info
        terminal_info = None
        try:
            terminal_info = self.mt5.terminal_info()
        except Exception:
            terminal_info = None

        if terminal_info is None:
            snapshot["safe_mode"] = True
            self._emit_startup_audit(snapshot)
            return snapshot

        snapshot["mt5_connected"] = True
        snapshot["mt5_build"] = str(getattr(terminal_info, "build", "unknown"))

        # account info
        account_info = None
        try:
            if hasattr(self.mt5, "account_info"):
                account_info = self.mt5.account_info()
        except Exception:
            account_info = None

        if account_info is None:
            # connected but no account — degraded
            snapshot["safe_mode"] = True
        else:
            snapshot["account"] = str(getattr(account_info, "login", "unknown"))
            snapshot["server"] = str(getattr(account_info, "server", "unknown"))
            snapshot["balance"] = float(getattr(account_info, "balance", 0.0))
            snapshot["equity"] = float(getattr(account_info, "equity", 0.0))

        # ── Positions + orders (bot-magic only) ─────────────
        remote_positions: Dict[int, Any] = {}
        try:
            raw_positions = self.mt5.positions_get() or []
            for raw in raw_positions:
                pos = _to_position(raw, self.magic)
                if pos is not None and pos.ticket > 0:
                    remote_positions[pos.ticket] = pos
                    snapshot["positions"].append(
                        {
                            "ticket": pos.ticket,
                            "symbol": pos.symbol,
                            "side": pos.side,
                            "volume": pos.volume,
                            "entry_price": pos.entry_price,
                            "sl": pos.sl,
                            "tp": pos.tp,
                            "magic": pos.magic,
                            "comment": pos.comment,
                            "open_time": pos.open_time,
                            "profit": pos.profit,
                            "swap": pos.swap,
                        }
                    )
        except Exception:
            pass

        try:
            raw_orders = self.mt5.orders_get() or []
            for raw in raw_orders:
                o_magic = getattr(raw, "magic", 0)
                try:
                    if int(o_magic) != int(self.magic):
                        continue
                except Exception:
                    continue
                snapshot["pending_orders"].append(
                    {
                        "ticket": getattr(raw, "ticket", 0),
                        "symbol": getattr(raw, "symbol", ""),
                        "type": getattr(raw, "type", 0),
                        "volume_initial": getattr(raw, "volume_initial", 0.0),
                        "price_open": getattr(raw, "price_open", 0.0),
                        "price": getattr(raw, "price_open", 0.0),
                        "sl": getattr(raw, "sl", 0.0),
                        "tp": getattr(raw, "tp", 0.0),
                        "magic": o_magic,
                        "comment": getattr(raw, "comment", ""),
                        "state": getattr(raw, "state", 0),
                    }
                )
        except Exception:
            pass

        # ── Reconciliation (S8) ─────────────────────────────
        # Build local positions from lifecycle open_trades so the Reconciler
        # can compare ticket sets. Use Position-like objects for comparison.
        local_for_recon: Dict[int, Any] = {}
        for pid, ctx in self.lifecycle.open_trades.items():
            local_for_recon[pid] = ctx

        # Convert remote MT5 positions to Position objects for Reconciler
        remote_for_recon: Dict[int, Any] = {}
        for ticket, pos in remote_positions.items():
            remote_for_recon[ticket] = pos

        if local_for_recon or remote_for_recon:
            reconciler = Reconciler()
            decision = reconciler.reconcile(local_for_recon, remote_for_recon)
            snapshot["reconciliation"] = {
                "status": decision.status.value,
                "block_trading": decision.block_trading,
                "details": decision.details,
            }
            if decision.block_trading:
                snapshot["safe_mode"] = True
        else:
            # No local or remote positions — clean state, OK.
            snapshot["reconciliation"] = {
                "status": "OK",
                "block_trading": False,
                "details": [],
            }

        # ── DD reliability (P1) ─────────────────────────────
        if not self.lifecycle.dd_is_reliable():
            snapshot["safe_mode"] = True

        self._emit_startup_audit(snapshot)
        return snapshot

    def _emit_startup_audit(self, snapshot: dict) -> None:
        """Emit a STARTUP audit event for the snapshot."""
        try:
            self.audit.append(
                time.time(),
                EventType.STARTUP,
                self.symbol,
                {
                    "mt5_connected": snapshot["mt5_connected"],
                    "mt5_build": snapshot["mt5_build"],
                    "account": snapshot["account"],
                    "server": snapshot["server"],
                    "balance": snapshot["balance"],
                    "equity": snapshot["equity"],
                    "symbols": snapshot["symbols"],
                    "positions_count": len(snapshot["positions"]),
                    "pending_orders_count": len(snapshot["pending_orders"]),
                    "safe_mode": snapshot["safe_mode"],
                    "reconciliation_status": snapshot["reconciliation"]["status"],
                },
            )
        except Exception:
            pass

    def _resolve_position_id(self, result) -> Optional[int]:
        if result.position_id:
            return int(result.position_id)
        # Fallback: resolve via deal history (broker-confirmed entry deal).
        if self.mt5 is not None and result.deal_id and hasattr(self.mt5, "history_deals_get"):
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
        """Process one closed 15m bar: strategy -> risk -> execution -> context.

        C2 entry lock (KARAR-2): while this symbol carries a bot-owned open
        trade, no NEW entry is sent on this symbol. The lock state is
        captured BEFORE ``runtime.on_bar`` because ``_fill_pending`` creates
        ``active_trade`` and emits the Signal in the same call — a post-hoc
        check would let an entry block itself. State advancement and
        position management are NOT gated (§7.2): the runtime still runs,
        ``poll_deals``/``sync_trailing`` keep managing the open position.
        A signal produced under lock is discarded visibly (RISK audit),
        never silently.
        """
        res = LiveRunnerStepResult()
        entry_locked = self._symbol_entry_locked()  # pre-capture (atomicity trap)
        sig = self.runtime.on_bar(bar)
        res.signal = sig
        if sig is None:
            return res
        # N2 #23 R-3: SIGNAL emit at the runtime-signal RETURN point — the
        # single live consumption point of strategy output (pre-reg v1.1
        # AM-R3; census §2 root-cause: the live path had NO SIGNAL emitter).
        # Emits BEFORE the entry-lock/risk gating so a blocked signal stays
        # visible as a SIGNAL -> RISK(approved=False) pair, never silent.
        self._audit(EventType.SIGNAL, signal_audit_payload(sig))
        if entry_locked:
            res.blocked_reason = "c2_symbol_entry_lock_active_trade"
            self._audit(
                EventType.RISK,
                {"approved": False, "reason": res.blocked_reason, "symbol": self.symbol},
            )
            return res

        contract = self.contract or default_contract(self.symbol)
        base_result = self.sizer.compute_lot(sig, balance=account.balance, contract=contract)
        res.base_lot = base_result.lot

        # Current DD — journal-authoritative; unreliable DD pauses scaling.
        if not self.lifecycle.dd_is_reliable():
            res.blocked_reason = "portfolio_dd_unreliable_pause"
            self._audit(EventType.RISK, {"approved": False, "reason": res.blocked_reason})
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
            self._audit(EventType.RISK, {"approved": False, "reason": res.blocked_reason})
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
            initial_risk_cash_per_unit=(risk_cash / filled_volume if filled_volume > 0 else 0.0),
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
                processed.append({"error": f"history_deals_get_failed: {e}", "position_id": pid})
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
