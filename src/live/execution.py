#!/usr/bin/env python
"""PHASE 5 — ORDER EXECUTION ENGINE.

Translates a `Signal` + sizing into a real MT5 market order:

    order_check  ->  order_send  ->  ExecutionResult

Design:

- Pure / injectable: MT5 module is passed in as `mt5` (default = real MetaTrader5
  package). Tests inject a fake `mt5` to avoid any real terminal dependency.
- The execution layer NEVER decides what to trade — risk (PHASE 4) is the only
  gatekeeper. This module only handles the mechanics of sending an order that
  has already been approved.
- `signal_only=True` (default) is the safety mode: NO order is sent, the call
  records what WOULD have been sent and returns ExecutionResult with
  `sent=False, dry_run=True`. Set `signal_only=False` only for controlled demo
  runs (PHASE 11). The default protects PHASE 9 (signal-only) and PHASE 10
  (paper) by design.
- Magic number + comment are mandatory and added by the engine (the caller
  cannot accidentally forget them).
- Duplicate protection: a per-symbol `recent_orders` cache (configurable TTL in
  seconds) prevents sending the same (symbol, direction, sl, tp) within the
  cooldown window. This blocks double-clicks and rapid-fire retry storms.
- Rejection handling:
    * `TRADE_RETCODE_REQUOTE` / `PRICE_CHANGED` / `PRICE_OFF` -> retriable.
    * `TRADE_RETCODE_REJECT` / `TRADE_RETCODE_DONE_PARTIAL` partial filled
      treated as terminal.
    * Connection-level errors (no order result) -> retriable up to `max_retries`.
- A failed fill NEVER crashes the runtime — it returns an ExecutionResult
  with `filled=False, reason=...` and the audit trail is preserved.

Acceptance: order sent with SL/TP, dup prevented, reject logged + retried.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.live.sizing import ContractSpec
from src.live.strategy_runtime import Signal

# ── Constants ────────────────────────────────────────────────────
# Default broker timezone is GMT+0..GMT+3; we use UTC for fill time
# independence. Magic + comment defaults are bot-wide identifiers.
DEFAULT_MAGIC = 9007001
DEFAULT_COMMENT_PREFIX = "SFX"

# Retriable MT5 return codes (broker asked to retry, transient).
# Ref: https://www.mql5.com/en/docs/constants/errorswarnings/enum_trade_return_codes
_RETRIABLE_RETCODE_NAMES = {
    "TRADE_RETCODE_REQUOTE",  # 10004
    "TRADE_RETCODE_PRICE_CHANGED",  # 10005
    "TRADE_RETCODE_PRICE_OFF",  # 10006
    "TRADE_RETCODE_CONNECTION",  # 10031
    "TRADE_RETCODE_TIMEOUT",  # 10036
    "TRADE_RETCODE_RETRY",  # 10032 (broker busy)
}


@dataclass
class OrderRequest:
    """A pre-risk, pre-sizing request to send to MT5.

    Carries everything the execution layer needs to build an order_send
    payload (no MT5 constants in the dataclass — the engine maps them).
    """

    signal: Signal
    lot: float
    contract: ContractSpec
    deviation: int = 20  # max slippage in points (slippage limit)
    magic: int = DEFAULT_MAGIC
    comment: str = ""


@dataclass
class ExecutionResult:
    """Outcome of an order_send attempt.

    `filled` is True ONLY if the broker returned TRADE_RETCODE_DONE
    (or an equivalent filled-confirmed code). Anything else is a failure
    (rejected, retried, or dry-run).
    """

    sent: bool
    filled: bool
    dry_run: bool = False
    retcode: Optional[int] = None
    retcode_name: str = ""
    order_id: Optional[int] = None
    deal_id: Optional[int] = None
    fill_price: Optional[float] = None
    request: Optional[Dict[str, Any]] = None
    response: Optional[Dict[str, Any]] = None
    reason: str = ""
    attempts: int = 1
    duplicate: bool = False
    retries: int = 0
    # P0-1: broker-confirmed fill metadata (additive; entry path unchanged).
    volume: Optional[float] = None
    position_id: Optional[int] = None


@dataclass
class ModifyResult:
    """Outcome of a TRADE_ACTION_SLTP position-modification attempt.

    `confirmed` is True ONLY if the broker returned TRADE_RETCODE_DONE for
    the SL/TP modification. Local state must be treated as authoritative
    ONLY after `confirmed=True` (P0-1 acceptance).
    """

    sent: bool
    confirmed: bool
    dry_run: bool = False
    retcode: Optional[int] = None
    retcode_name: str = ""
    reason: str = ""
    position_id: Optional[int] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    request: Optional[Dict[str, Any]] = None
    response: Optional[Dict[str, Any]] = None


class Execution:
    """Order execution engine (market orders, SL/TP, magic, comment).

    Defaults: `signal_only=True` (no real orders sent). Production demo runs
    (PHASE 11) construct this class with `signal_only=False` explicitly.

    Args:
        mt5: MetaTrader5 module (or a fake). Injected for testability.
        signal_only: When True, NO real orders are sent (default; safety).
        magic: Default magic number for orders (overridable per request).
        comment_prefix: Prefix for the auto-generated comment.
        duplicate_window_sec: Cooldown for duplicate protection (seconds).
        max_retries: Number of retry attempts for retriable rejections.
        retry_sleep_sec: Sleep between retry attempts (seconds).
    """

    def __init__(
        self,
        mt5: Any = None,
        signal_only: bool = True,
        magic: int = DEFAULT_MAGIC,
        comment_prefix: str = DEFAULT_COMMENT_PREFIX,
        duplicate_window_sec: float = 5.0,
        max_retries: int = 2,
        retry_sleep_sec: float = 0.5,
    ):
        if mt5 is None:
            import MetaTrader5 as mt5_mod  # type: ignore

            mt5 = mt5_mod
        self.mt5 = mt5
        self.signal_only = signal_only
        self.magic = magic
        self.comment_prefix = comment_prefix
        self.duplicate_window_sec = duplicate_window_sec
        self.max_retries = max_retries
        self.retry_sleep_sec = retry_sleep_sec
        # Per-symbol recent-orders cache: (sl, tp, direction) -> last_send_ts
        self._recent: Dict[str, float] = {}
        # P0-1 — SL/TP modification dedupe state (per position):
        #   _confirmed_modify[(pos, sl, tp)] -> confirmed by broker
        #   _last_modify_request[pos] -> last (sl, tp) request sent
        self._confirmed_modify: Dict[int, tuple] = {}
        self._last_modify_request: Dict[int, tuple] = {}

    # ── Public API ──────────────────────────────────────────────
    def send(self, request: OrderRequest) -> ExecutionResult:
        """Send a market order for the given request.

        Order of operations:
            1. Validate lot > 0.
            2. Build MT5 request payload.
            3. Duplicate protection (skip if same (symbol, sl, tp, dir)
               was sent within `duplicate_window_sec`).
            4. order_check (validate; if rejected, no send).
            5. order_send (with retry on retriable errors).
            6. Return ExecutionResult.
        """
        sig = request.signal
        lot = request.lot

        if lot <= 0:
            return ExecutionResult(
                sent=False,
                filled=False,
                reason="lot<=0",
                request=self._build_request(request),
            )

        payload = self._build_request(request)
        fingerprint = self._fingerprint(sig.symbol, sig.direction, sig.sl, sig.tp)

        # Duplicate protection.
        if self._is_duplicate(fingerprint):
            return ExecutionResult(
                sent=False,
                filled=False,
                reason="duplicate_blocked",
                duplicate=True,
                request=payload,
            )

        # order_check (validate without sending).
        try:
            check = self.mt5.order_check(payload)
        except Exception as e:
            check = None
            check_error = f"order_check_exception: {e}"
        else:
            check_error = None

        if check is None or getattr(check, "retcode", None) != 0:
            # Validation failed — DO NOT send. Mark as retriable so the caller
            # can decide whether to escalate, but do NOT auto-retry a
            # validation failure (it is usually a config error).
            return ExecutionResult(
                sent=False,
                filled=False,
                reason=check_error or "order_check_failed",
                retcode=getattr(check, "retcode", None) if check else None,
                retcode_name=self._retcode_name(getattr(check, "retcode", None) if check else None),
                request=payload,
                response=self._normalize_result(check),
            )

        # signal_only: record what WOULD have been sent, do not send.
        if self.signal_only:
            self._mark_sent(fingerprint)
            return ExecutionResult(
                sent=False,
                filled=False,
                dry_run=True,
                reason="signal_only",
                request=payload,
                response={"check": self._normalize_result(check)},
            )

        # Real send with retry.
        attempts = 0
        last_result: ExecutionResult = ExecutionResult(
            sent=False, filled=False, reason="no_attempt"
        )
        for attempt in range(1, self.max_retries + 2):  # initial + max_retries
            attempts = attempt
            try:
                result = self.mt5.order_send(payload)
            except Exception as e:
                last_result = ExecutionResult(
                    sent=False,
                    filled=False,
                    reason=f"order_send_exception: {e}",
                    request=payload,
                    attempts=attempts,
                )
                # Exception is treated as retriable (could be transient).
                if attempt <= self.max_retries:
                    time.sleep(self.retry_sleep_sec)
                    continue
                break

            normalized = self._normalize_result(result)
            retcode = normalized.get("retcode")
            retcode_name = self._retcode_name(retcode)
            if self._is_filled(retcode):
                self._mark_sent(fingerprint)
                return ExecutionResult(
                    sent=True,
                    filled=True,
                    retcode=retcode,
                    retcode_name=retcode_name,
                    order_id=normalized.get("order_id"),
                    deal_id=normalized.get("deal_id"),
                    fill_price=normalized.get("fill_price"),
                    request=payload,
                    response=normalized,
                    attempts=attempts,
                    volume=normalized.get("volume"),
                    position_id=normalized.get("position_id"),
                )

            # Not filled.
            last_result = ExecutionResult(
                sent=True,
                filled=False,
                retcode=retcode,
                retcode_name=retcode_name,
                order_id=normalized.get("order_id"),
                request=payload,
                response=normalized,
                reason=retcode_name or "rejected",
                attempts=attempts,
            )
            if self._is_retriable(retcode) and attempt <= self.max_retries:
                last_result.retries = attempt
                time.sleep(self.retry_sleep_sec)
                continue
            break

        # Failed: do NOT mark as sent (allow a future retry to actually send).
        last_result.attempts = attempts
        return last_result

    # ── P0-1: Position SL/TP modification (TRADE_ACTION_SLTP) ───
    def modify_position_sl_tp(
        self,
        position_ticket: int,
        symbol: str,
        sl: float,
        tp: float,
        deviation: int = 20,
        magic: Optional[int] = None,
    ) -> ModifyResult:
        """Modify the SL/TP of an open position via TRADE_ACTION_SLTP.

        Semantics (P0-1 acceptance):
        - Only sends when (sl, tp) differs from the last broker-confirmed
          state (duplicate suppression, per position).
        - `confirmed=True` ONLY on broker TRADE_RETCODE_DONE. The caller
          must NOT update authoritative local state before that.
        - Rejections are returned (never silently ignored); no local
          state change happens on rejection.
        - signal_only=True (safety default) -> dry-run, nothing sent.
        """
        pos = int(position_ticket)
        desired = (float(sl), float(tp))

        # Duplicate suppression: identical to last broker-confirmed state.
        if self._confirmed_modify.get(pos) == desired:
            return ModifyResult(
                sent=False,
                confirmed=False,
                reason="already_confirmed",
                position_id=pos,
                sl=desired[0],
                tp=desired[1],
            )
        # Duplicate suppression: identical request already in flight.
        if self._last_modify_request.get(pos) == desired:
            return ModifyResult(
                sent=False,
                confirmed=False,
                reason="modify_in_flight",
                position_id=pos,
                sl=desired[0],
                tp=desired[1],
            )

        payload = {
            "action": self.mt5.TRADE_ACTION_SLTP,
            "symbol": symbol,
            "position": pos,
            "sl": desired[0],
            "tp": desired[1],
            "deviation": deviation,
            "magic": magic if magic is not None else self.magic,
        }

        # signal_only safety mode: record what WOULD be sent.
        if self.signal_only:
            self._last_modify_request[pos] = desired
            return ModifyResult(
                sent=False,
                confirmed=False,
                dry_run=True,
                reason="signal_only",
                position_id=pos,
                sl=desired[0],
                tp=desired[1],
                request=payload,
            )

        self._last_modify_request[pos] = desired
        try:
            result = self.mt5.order_send(payload)
        except Exception as e:
            # Exception -> nothing confirmed; caller may retry later.
            self._last_modify_request.pop(pos, None)
            return ModifyResult(
                sent=False,
                confirmed=False,
                reason=f"modify_exception: {e}",
                position_id=pos,
                sl=desired[0],
                tp=desired[1],
                request=payload,
            )

        normalized = self._normalize_result(result)
        retcode = normalized.get("retcode")
        retcode_name = self._retcode_name(retcode)
        if self._is_filled(retcode):
            self._confirmed_modify[pos] = desired
            self._last_modify_request[pos] = desired
            return ModifyResult(
                sent=True,
                confirmed=True,
                retcode=retcode,
                retcode_name=retcode_name,
                position_id=pos,
                sl=desired[0],
                tp=desired[1],
                request=payload,
                response=normalized,
            )

        # Rejected: clear in-flight marker so a retry is possible, do NOT
        # update confirmed state, and surface the rejection to the caller.
        self._last_modify_request.pop(pos, None)
        return ModifyResult(
            sent=True,
            confirmed=False,
            retcode=retcode,
            retcode_name=retcode_name,
            reason=retcode_name or "modify_rejected",
            position_id=pos,
            sl=desired[0],
            tp=desired[1],
            request=payload,
            response=normalized,
        )

    def confirmed_sl_tp(self, position_ticket: int) -> Optional[tuple]:
        """Broker-confirmed (sl, tp) for a position, or None if never modified."""
        return self._confirmed_modify.get(int(position_ticket))

    def forget_position(self, position_ticket: int) -> None:
        """Drop dedupe state for a closed position (stale-protect cleanup)."""
        pos = int(position_ticket)
        self._confirmed_modify.pop(pos, None)
        self._last_modify_request.pop(pos, None)

    # ── Build payload ───────────────────────────────────────────
    def _build_request(self, request: OrderRequest) -> Dict[str, Any]:
        """Build the MT5 order_send payload from a Signal + lot."""
        sig = request.signal
        # MT5 comment limit is 31 chars (broker-enforced). Use compact format.
        # Format: SFX-{symbol}-{S|L}-{zone}-{sweep}  (max ~20 chars)
        side_char = "L" if sig.side == "long" else "S"
        comment = request.comment or (
            f"SFX-{sig.symbol}-{side_char}{sig.zone_index}-{sig.sweep_bar_index}"
        )
        order_type = self.mt5.ORDER_TYPE_BUY if sig.side == "long" else self.mt5.ORDER_TYPE_SELL
        return {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": sig.symbol,
            "volume": request.lot,
            "type": order_type,
            "price": sig.entry_price,
            "sl": sig.sl,
            "tp": sig.tp,
            "deviation": request.deviation,
            "magic": request.magic if request.magic is not None else self.magic,
            "comment": comment,
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self.mt5.ORDER_FILLING_IOC,
        }

    # ── Helpers ─────────────────────────────────────────────────
    @staticmethod
    def _fingerprint(symbol: str, direction: str, sl: float, tp: float) -> str:
        # Round to 5 dp to avoid float-drift duplicates.
        return f"{symbol}|{direction}|{sl:.5f}|{tp:.5f}"

    def _is_duplicate(self, fingerprint: str) -> bool:
        ts = self._recent.get(fingerprint)
        if ts is None:
            return False
        if (time.time() - ts) > self.duplicate_window_sec:
            self._recent.pop(fingerprint, None)
            return False
        return True

    def _mark_sent(self, fingerprint: str) -> None:
        self._recent[fingerprint] = time.time()

    def _is_filled(self, retcode: Optional[int]) -> bool:
        if retcode is None:
            return False
        return retcode == getattr(self.mt5, "TRADE_RETCODE_DONE", 10009)

    def _is_retriable(self, retcode: Optional[int]) -> bool:
        if retcode is None:
            return True  # unknown -> assume transient
        for name in _RETRIABLE_RETCODE_NAMES:
            if getattr(self.mt5, name, -1) == retcode:
                return True
        return False

    def _retcode_name(self, retcode: Optional[int]) -> str:
        if retcode is None:
            return ""
        # Walk known TRADE_RETCODE_* names on the mt5 module.
        for name in dir(self.mt5):
            if name.startswith("TRADE_RETCODE_") and getattr(self.mt5, name) == retcode:
                return name
        return f"RETCODE_{retcode}"

    def _normalize_result(self, result: Any) -> Dict[str, Any]:
        """Convert an mt5 OrderCheckResult/OrderSendResult to a plain dict."""
        if result is None:
            return {}
        if isinstance(result, dict):
            return dict(result)
        try:
            return {
                "retcode": getattr(result, "retcode", None),
                "order_id": getattr(result, "order", None) or getattr(result, "order_id", None),
                "deal_id": getattr(result, "deal", None) or getattr(result, "deal_id", None),
                "fill_price": getattr(result, "price", None) or getattr(result, "fill_price", None),
                "volume": getattr(result, "volume", None),
                "position_id": getattr(result, "position", None)
                or getattr(result, "position_id", None),
                "comment": getattr(result, "comment", None),
            }
        except Exception:
            return {}
