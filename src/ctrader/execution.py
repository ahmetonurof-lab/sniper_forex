#!/usr/bin/env python
"""D170-§3-Adım-③-B — CTraderExecution: cTrader emir gönderimi.

Tasarım: ``docs/CTRADER_ORDER_EXECUTION_DESIGN_D168.md`` (D169-entegre).

Sözleşme (§2.2 pin): MT5 ``Execution`` ile aynı ``send(OrderRequest) ->
ExecutionResult`` arayüzü; ``OrderRequest``/``ExecutionResult``
``src.live.execution``'dan import edilir (duplicate source YASAK).
MT5 ``Execution`` DOKUNULMAZ.

Kritik şema gerçekleri (cTrader Open API resmi fetch, 2026-09-08):

- ``ProtoOANewOrderReq.volume``: 0.01-unit çarpanlı ->
  ``protocol_volume = lot x contract_size x 100``.
- Absolute ``stopLoss``/``takeProfit`` MARKET emirlerde DESTEKLENMEZ ->
  ``relativeStopLoss``/``relativeTakeProfit`` kullanılır. Resmi doküman
  sabit 1/100000 birim yazar; D169-§4 dinamik savunma katmanı olarak
  ``scale = 10 ** pipPosition`` uygular (ProtoOASymbol.pipPosition
  runtime lookup: EURUSD=5 -> x100000, JPY=3 -> x1000). Lookup eksikse
  fail-loud: emir GÖNDERİLMEZ + SAFETY audit.
- Partial-fill (ORDER_PARTIAL_FILL / PARTIALLY_FILLED / filledVolume <
  volume) -> TERMINAL: retry YOK, istisna YOK; ORDER(partial_fill=True)
  + SAFETY("partial_fill_rejected").
- ``ProtoOAErrorRes.retryAfter`` (rate-limit) -> bekle + retry.

Mock-only: broker erişimi yalnızca ``connection.send_order(payload)``
üzerinden; testler FakeExecConnection kullanır. Gerçek emir (adım-④
kontrollü demo) AYRI onaya tabidir (D170-§4).
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Tuple

from src.live.audit import EventType
from src.live.execution import ExecutionResult, OrderRequest

__all__ = ["CTraderExecution", "CTraderSafetyError"]

# ProtoOAExecutionType (resmi şema): dolu/partial ayrımı için kullanılanlar
_EXEC_FILLED = "ORDER_FILLED"
_EXEC_PARTIAL = "ORDER_PARTIAL_FILL"
# ProtoOADealStatus: PARTIALLY_FILLED=3
_DEAL_PARTIAL = "PARTIALLY_FILLED"
# ProtoOAErrorCode: rate-limit
_ERR_RATE_LIMIT = "REQUEST_FREQUENCY_EXCEEDED"


class CTraderSafetyError(RuntimeError):
    """Limited-risk / sembol-GSL uyumsuzluğu (kapı-7; boot-FATAL)."""


class CTraderExecution:
    """cTrader emir gönderimi — MT5 ``Execution`` ile aynı sözleşme.

    ``send(OrderRequest) -> ExecutionResult``; duck-typing ile
    ``LiveRunner`` tarafında MT5-Execution ile swap edilebilir (Karar-A).
    """

    def __init__(
        self,
        connection: Any,
        audit: Any,
        symbol_meta: Dict[str, Dict[str, Any]],
        signal_only: bool = True,
        max_retries: int = 2,
        retry_sleep_sec: float = 0.5,
    ) -> None:
        self._connection = connection
        self._audit = audit
        self._symbol_meta = symbol_meta
        self._signal_only = signal_only
        self._max_retries = max_retries
        self._retry_sleep_sec = retry_sleep_sec

    # ── public API ───────────────────────────────────────────────────────

    def send(self, request: OrderRequest) -> ExecutionResult:
        """Emri gönder (signal_only=True -> dry-run, broker'a GİTMEZ)."""
        sig = request.signal
        symbol = sig.symbol

        # Kapı-6: lot<=0 (MT5-Execution ile aynı sözleşme)
        if request.lot <= 0:
            return ExecutionResult(sent=False, filled=False, reason="lot<=0", request=request)

        meta = self._symbol_meta.get(symbol) or {}

        # D169-§4: pipPosition dinamik lookup — eksikse fail-loud (emir YOK)
        pip_position = meta.get("pip_position")
        if pip_position is None:
            self._audit.append(
                time.time(),
                EventType.SAFETY,
                symbol,
                {"reason": "pip_position_missing", "symbol": symbol},
            )
            return ExecutionResult(
                sent=False,
                filled=False,
                reason="pip_position_missing",
                request=request,
            )

        volume = self._protocol_volume(request)
        rel_sl, rel_tp = self._relative_sl_tp(sig, int(pip_position))
        client_order_id = self._client_order_id(symbol)

        payload: Dict[str, Any] = {
            "symbol": symbol,
            "symbol_id": meta.get("symbol_id"),
            "order_type": "MARKET",
            "trade_side": "BUY" if sig.side == "long" else "SELL",
            "volume": volume,
            "relativeStopLoss": rel_sl,
            "relativeTakeProfit": rel_tp,
            "clientOrderId": client_order_id,
            "label": "SNIPER_FOREX",
        }

        if self._signal_only:
            # D169-Nokta-7: dry-run'da da ORDER audit (dry_run:true)
            self._audit.append(
                time.time(),
                EventType.ORDER,
                symbol,
                {
                    "dry_run": True,
                    "clientOrderId": client_order_id,
                    "volume": volume,
                    "relativeStopLoss": rel_sl,
                    "relativeTakeProfit": rel_tp,
                },
            )
            return ExecutionResult(
                sent=False,
                filled=False,
                dry_run=True,
                reason="signal_only",
                request=request,
            )

        return self._send_with_retry(request, payload)

    def validate_limited_risk(self, trader_is_limited_risk: bool, symbol: str) -> None:
        """Kapı-7: limited-risk hesap <-> sembol GSL uyum çift-kontrolü.

        Limited-risk hesapta GSL desteklemeyen sembol -> CTraderSafetyError
        (boot-FATAL). Uyumlu ise sessizce döner.
        """
        if not trader_is_limited_risk:
            return
        meta = self._symbol_meta.get(symbol)
        if meta is None:
            raise CTraderSafetyError(f"limited_risk_symbol_meta_missing: {symbol}")
        if not meta.get("guaranteed_stop_loss", False):
            raise CTraderSafetyError(
                f"symbol_not_limited_risk: {symbol} "
                "(limited-risk account requires guaranteedStopLoss-capable symbol)"
            )

    # ── helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _protocol_volume(request: OrderRequest) -> int:
        """lot x contract_size x 100 (0.01-unit protocol volume)."""
        return int(round(request.lot * request.contract.contract_size * 100))

    @staticmethod
    def _relative_sl_tp(sig: Any, pip_position: int) -> Tuple[int, int]:
        """scale = 10 ** pipPosition (D169-§4 dinamik savunma katmanı)."""
        scale = 10 ** int(pip_position)
        if sig.side == "long":
            rel_sl = (sig.entry_price - sig.sl) * scale
            rel_tp = (sig.tp - sig.entry_price) * scale
        else:
            rel_sl = (sig.sl - sig.entry_price) * scale
            rel_tp = (sig.entry_price - sig.tp) * scale
        return int(round(rel_sl)), int(round(rel_tp))

    @staticmethod
    def _client_order_id(symbol: str) -> str:
        """Kapı-5: SNIPER_{symbol}_{timestamp_ms}_{uuid8} (<=50 char)."""
        ts_ms = int(time.time() * 1000)
        uid8 = uuid.uuid4().hex[:8]
        return f"SNIPER_{symbol}_{ts_ms}_{uid8}"[:50]

    @staticmethod
    def _classify(etype: str, ev: Any) -> str:
        """Event sınıflandırma: Fake ("EXECUTION_EVENT"/"ERROR_RES") ve
        gerçek bağlantı ("MESSAGE" + tip-adı dispatch) yollarını kapsar."""
        if etype == "EXECUTION_EVENT":
            return "execution"
        if etype == "ERROR_RES":
            return "error_res"
        if etype == "MESSAGE":
            name = type(ev).__name__
            if name == "ProtoOAExecutionEvent":
                return "execution"
            if name == "ProtoOAErrorRes":
                return "error_res"
        return "other"

    def _send_with_retry(self, request: OrderRequest, payload: Dict[str, Any]) -> ExecutionResult:
        """Retry döngüsü (MT5-Execution deseni: max_retries+1 deneme)."""
        symbol = request.signal.symbol
        attempts = 0
        last_reason = "no_response"
        for attempt in range(1, self._max_retries + 2):
            attempts = attempt
            self._connection.send_order(payload)
            for etype, ev in self._connection.drain_events():
                kind = self._classify(etype, ev)
                if kind == "execution":
                    return self._handle_execution_event(request, payload, ev)
                if kind == "error_res":
                    retry_after = getattr(ev, "retryAfter", None)
                    error_code = getattr(ev, "errorCode", "") or ""
                    if error_code == _ERR_RATE_LIMIT and retry_after:
                        # rate-limit: retryAfter kadar bekle + retry
                        time.sleep(float(retry_after))
                        last_reason = f"rate_limit_retry:{error_code}"
                        break
                    last_reason = f"error_res:{error_code}"
                    self._audit.append(
                        time.time(),
                        EventType.SAFETY,
                        symbol,
                        {"reason": last_reason, "clientOrderId": payload["clientOrderId"]},
                    )
                    return ExecutionResult(
                        sent=True,
                        filled=False,
                        reason=last_reason,
                        attempts=attempts,
                        request=request,
                    )
            else:
                # event yok: sonraki deneme
                time.sleep(self._retry_sleep_sec)
                continue
            # break ile geldiysek retry devam
        return ExecutionResult(
            sent=True,
            filled=False,
            reason=last_reason,
            attempts=attempts,
            request=request,
        )

    def _handle_execution_event(
        self, request: OrderRequest, payload: Dict[str, Any], ev: Any
    ) -> ExecutionResult:
        """ProtoOAExecutionEvent işleme (fill / partial-fill terminal)."""
        symbol = request.signal.symbol
        exec_type = getattr(ev, "executionType", None)
        deal = getattr(ev, "deal", None)
        filled_volume = getattr(deal, "filledVolume", None) if deal else None
        deal_status = getattr(deal, "dealStatus", None) if deal else None
        order = getattr(ev, "order", None)
        position = getattr(ev, "position", None)
        error_code = getattr(ev, "errorCode", None)

        if exec_type == _EXEC_FILLED:
            # D169-Nokta-8: partial tetikleyicileri (üçü de) -> TERMINAL
            is_partial = (
                exec_type == _EXEC_PARTIAL
                or deal_status == _DEAL_PARTIAL
                or (filled_volume is not None and filled_volume < int(payload["volume"]))
            )
            if is_partial:
                self._audit.append(
                    time.time(),
                    EventType.ORDER,
                    symbol,
                    {
                        "partial_fill": True,
                        "clientOrderId": payload["clientOrderId"],
                        "volume": payload["volume"],
                        "filledVolume": filled_volume,
                    },
                )
                self._audit.append(
                    time.time(),
                    EventType.SAFETY,
                    symbol,
                    {"reason": "partial_fill_rejected"},
                )
                return ExecutionResult(
                    sent=True,
                    filled=False,
                    reason="partial_fill_rejected",
                    request=request,
                    volume=payload["volume"],
                    position_id=getattr(position, "id", None),
                )
            return ExecutionResult(
                sent=True,
                filled=True,
                reason="filled",
                request=request,
                order_id=getattr(order, "orderId", None),
                volume=payload["volume"],
                position_id=getattr(position, "id", None),
            )

        if exec_type == _EXEC_PARTIAL:
            # doğrudan ORDER_PARTIAL_FILL event'i (deal'siz) -> TERMINAL
            self._audit.append(
                time.time(),
                EventType.ORDER,
                symbol,
                {"partial_fill": True, "clientOrderId": payload["clientOrderId"]},
            )
            self._audit.append(
                time.time(),
                EventType.SAFETY,
                symbol,
                {"reason": "partial_fill_rejected"},
            )
            return ExecutionResult(
                sent=True,
                filled=False,
                reason="partial_fill_rejected",
                request=request,
                volume=payload["volume"],
            )

        # ORDER_REJECTED vb. -> terminal
        reason = f"execution_{exec_type}"
        if error_code:
            reason = f"{reason}:{error_code}"
        return ExecutionResult(
            sent=True,
            filled=False,
            reason=reason,
            request=request,
            order_id=getattr(order, "orderId", None),
        )
