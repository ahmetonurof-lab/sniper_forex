"""D170-§3-Adım-③-A — CTraderExecution RED testleri (11 test).

Test-first (D170-§3): ``src/ctrader/execution.py`` HENÜZ YOK. Bu dosyadaki
tüm testler RED bekler; GREEN, Adım-③-B'de (implementasyon) gelir.

Kapsam (D170-§3 birebir):
    1.  test_volume_conversion_eurusd      lot x contract_size x 100
    2.  test_volume_conversion_usdjpy      JPY contract_size duyarlılığı
    3.  test_relative_sl_tp_eurusd         pipPosition=5 -> x100000
    4.  test_relative_sl_tp_usdjpy         pipPosition=3 -> x1000
    5.  test_pip_position_lookup_missing   fail-loud (emir yok + SAFETY)
    6.  test_client_order_id_format        SNIPER_{sym}_{ms}_{uuid8} <=50
    7.  test_partial_fill_terminal         TERMINAL + ORDER/SAFETY audit
    8.  test_is_limited_risk_boot_check    çift-kontrol (Trader+Symbol)
    9.  test_dry_run_no_order_sent         signal_only=True default
    10. test_error_res_retry_after         rate-limit retryAfter
    11. test_contract_pin                  §2.2 API koruması

Kabul (D170): TÜM testler RED (implementasyon yok). RED kanıtı:
``pytest tests/test_ctrader_execution.py`` çıktısı (§13 sayı disiplini).

Mock-only: gerçek broker'a emir GİTMEZ (FakeExecConnection). MT5
``Execution`` DOKUNULMAZ (test_contract_pin pin'ler). Şema kaynakları:
ProtoOANewOrderReq (relative*, volume 0.01-unit), ProtoOAExecutionEvent
(ORDER_PARTIAL_FILL=11), ProtoOADeal (filledVolume, dealStatus),
ProtoOAErrorRes (retryAfter), ProtoOATrader.isLimitedRisk,
ProtoOASymbol.guaranteedStopLoss / pipPosition.
"""

from __future__ import annotations

import dataclasses
import inspect
import re
import time
from types import SimpleNamespace

import pandas as pd
import pytest

from src.live.audit import EventType
from src.live.execution import DEFAULT_MAGIC, ExecutionResult, OrderRequest
from src.live.sizing import ContractSpec
from src.live.strategy_runtime import Signal

# ── RED-phase import guard ───────────────────────────────────────────────
# src/ctrader/execution.py Adım-③-B'de yazılacak. Modül-level ImportError
# tüm dosyayı düşürmesin diye guard'lanır; her test _require_impl ile AÇIK
# RED-FAIL verir -> 11/11 görünür kanıt (§13: sayılar kanıttır).
try:
    from src.ctrader.execution import CTraderExecution, CTraderSafetyError

    _IMPL_READY = True
except ImportError:
    CTraderExecution = None  # type: ignore[assignment]
    CTraderSafetyError = None  # type: ignore[assignment]
    _IMPL_READY = False


def _require_impl() -> None:
    """RED-phase guard: implementasyon yoksa AÇIK fail (gizli-skip YASAK)."""
    if not _IMPL_READY:
        pytest.fail("RED: src/ctrader/execution.py henüz yok (D170-§3-Adım-③-A)")


# ── Fakes (desen: tests/test_orchestrator_ctrader_boot.py) ───────────────


class FakeExecConnection:
    """send_order çağrılarını kaydeder; script'li event döndürür.

    Gerçek CTraderConnection ile aynı drain_events() sözleşmesi:
    [(tip, veri), ...] listesi. send_order payload'u dict olarak kaydedilir
    (implementasyonun ProtoOANewOrderReq'e çevirmeden ÖNCE hazırladığı
    alan-seti -> dönüşüm mantığı doğrudan kanıtlanır).
    """

    def __init__(self, scripted_events=None):
        self.calls: list[dict] = []
        self._scripted: list = list(scripted_events or [])
        self._queued: list = []

    def send_order(self, payload: dict) -> None:
        self.calls.append(dict(payload))
        if self._scripted:
            self._queued.append(self._scripted.pop(0))

    def drain_events(self):
        out, self._queued = self._queued, []
        return out


class AuditCollector:
    """Duck-typed audit hedefi (AuditChain.append sözleşmesi)."""

    def __init__(self):
        self.events: list = []

    def append(self, timestamp, event_type, symbol=None, payload=None):
        self.events.append((event_type, symbol, dict(payload or {})))

    def of_type(self, event_type):
        return [e for e in self.events if e[0] == event_type]


# ── Fixtures / helpers ───────────────────────────────────────────────────

SYMBOL_META = {
    # pipPosition: ProtoOASymbol.pipPosition (runtime lookup; EURUSD=5, JPY=3)
    "EURUSD": {"symbol_id": 3, "pip_position": 5, "guaranteed_stop_loss": False},
    "USDJPY": {"symbol_id": 7, "pip_position": 3, "guaranteed_stop_loss": False},
    "XAUUSD": {"symbol_id": 9, "pip_position": 2, "guaranteed_stop_loss": True},
}


def _spec_eurusd() -> ContractSpec:
    return ContractSpec(
        symbol="EURUSD",
        tick_size=0.00001,
        tick_value=1.0,
        contract_size=100000.0,
        digits=5,
    )


def _spec_usdjpy(contract_size: float = 100000.0) -> ContractSpec:
    return ContractSpec(
        symbol="USDJPY",
        tick_size=0.001,
        tick_value=1.0,
        contract_size=contract_size,
        digits=3,
    )


def _signal(symbol="EURUSD", side="long", entry=1.10000, sl=1.09900, tp=1.10200):
    return Signal(
        symbol=symbol,
        direction="bullish" if side == "long" else "bearish",
        side=side,
        entry_price=entry,
        sl=sl,
        tp=tp,
        entry_bar_index=100,
        sweep_bar_index=99,
        zone_index=5,
        zone_top=entry,
        zone_bottom=sl,
        zone_size=entry - sl,
        timestamp=pd.Timestamp("2026-09-08T08:00:00Z"),
    )


def _filled_event(filled_volume: int = 100000, position_id: int = 555001):
    """ProtoOAExecutionEvent-shaped fake (ORDER_FILLED)."""
    return SimpleNamespace(
        executionType="ORDER_FILLED",
        errorCode=None,
        order=SimpleNamespace(orderId=777001),
        position=SimpleNamespace(id=position_id),
        deal=SimpleNamespace(filledVolume=filled_volume, dealStatus="FILLED"),
    )


def _make_exec(conn, audit, signal_only=False, **kw):
    _require_impl()
    return CTraderExecution(
        connection=conn,
        audit=audit,
        symbol_meta=SYMBOL_META,
        signal_only=signal_only,
        **kw,
    )


# ── 1-2: Volume dönüşümü (protocol_volume = lot x contract_size x 100) ───


def test_volume_conversion_eurusd():
    """0.01 lot EURUSD (contract_size=100000) -> protocol volume 100000."""
    conn = FakeExecConnection(scripted_events=[("EXECUTION_EVENT", _filled_event(100000))])
    audit = AuditCollector()
    ex = _make_exec(conn, audit)

    res = ex.send(OrderRequest(signal=_signal(), lot=0.01, contract=_spec_eurusd()))

    assert len(conn.calls) == 1
    payload = conn.calls[0]
    assert payload["volume"] == 100000  # 0.01 x 100000 x 100
    assert res.filled is True  # round-trip: fill event'i doğru okundu


def test_volume_conversion_usdjpy():
    """JPY contract_size farkı: formül contract_size'a duyarlı (hardcode YASAK)."""
    # Standart USDJPY: contract_size=100000 -> 0.01 lot -> 100000
    conn = FakeExecConnection(scripted_events=[("EXECUTION_EVENT", _filled_event(100000))])
    ex = _make_exec(conn, AuditCollector())
    sig = _signal("USDJPY", "long", entry=155.000, sl=154.900, tp=155.200)
    ex.send(OrderRequest(signal=sig, lot=0.01, contract=_spec_usdjpy()))
    assert conn.calls[0]["volume"] == 0.01 * 100000.0 * 100

    # Farklı contract_size (mini-contract örneği) -> oransal dönüşüm değişmeli
    conn2 = FakeExecConnection(scripted_events=[("EXECUTION_EVENT", _filled_event(10000))])
    ex2 = _make_exec(conn2, AuditCollector())
    ex2.send(
        OrderRequest(
            signal=sig,
            lot=0.01,
            contract=_spec_usdjpy(contract_size=10000.0),
        )
    )
    assert conn2.calls[0]["volume"] == 0.01 * 10000.0 * 100


# ── 3-4: relative SL/TP (scale = 10^pipPosition, dinamik lookup) ─────────


def test_relative_sl_tp_eurusd():
    """EURUSD pipPosition=5 -> scale=100000; absolute SL/TP gönderilmez."""
    conn = FakeExecConnection(scripted_events=[("EXECUTION_EVENT", _filled_event())])
    ex = _make_exec(conn, AuditCollector())

    ex.send(OrderRequest(signal=_signal(), lot=0.01, contract=_spec_eurusd()))

    payload = conn.calls[0]
    # entry=1.10000, sl=1.09900 -> dist=0.00100 x 100000 = 100
    assert payload["relativeStopLoss"] == 100
    # tp=1.10200 -> dist=0.00200 x 100000 = 200
    assert payload["relativeTakeProfit"] == 200
    # KRİTİK (D169-Nokta-2): absolute SL/TP MARKET emirde desteklenmez
    assert "stopLoss" not in payload
    assert "takeProfit" not in payload


def test_relative_sl_tp_usdjpy():
    """USDJPY pipPosition=3 -> scale=1000 (JPY ölçek farkı)."""
    conn = FakeExecConnection(scripted_events=[("EXECUTION_EVENT", _filled_event())])
    ex = _make_exec(conn, AuditCollector())
    sig = _signal("USDJPY", "long", entry=155.000, sl=154.900, tp=155.200)

    ex.send(OrderRequest(signal=sig, lot=0.01, contract=_spec_usdjpy()))

    payload = conn.calls[0]
    # dist=0.100 x 1000 = 100 (JPY'de aynı relative değeri ÜRETEN farklı ölçek)
    assert payload["relativeStopLoss"] == 100
    assert payload["relativeTakeProfit"] == 200


# ── 5: pipPosition lookup eksik -> fail-loud ─────────────────────────────


def test_pip_position_lookup_missing():
    """pipPosition yok -> emir GÖNDERİLMEZ + SAFETY audit (fail-loud)."""
    meta = {"EURUSD": {"symbol_id": 3, "guaranteed_stop_loss": False}}  # pip_position YOK
    conn = FakeExecConnection()
    audit = AuditCollector()
    _require_impl()
    ex = CTraderExecution(connection=conn, audit=audit, symbol_meta=meta, signal_only=False)

    res = ex.send(OrderRequest(signal=_signal(), lot=0.01, contract=_spec_eurusd()))

    assert res.sent is False
    assert res.filled is False
    assert len(conn.calls) == 0  # EMİR YOK — fail-loud
    safety = audit.of_type(EventType.SAFETY)
    assert len(safety) == 1
    assert "pip_position" in str(safety[0][2]).lower()


# ── 6: clientOrderId formatı (D169-Nokta-4 kapı-5) ───────────────────────


def test_client_order_id_format():
    """SNIPER_{symbol}_{timestamp_ms}_{uuid_short}; <=50 char; unique."""
    # Her send'e fill event script'li (event yoksa retry beklenen davranış)
    conn = FakeExecConnection(scripted_events=[("EXECUTION_EVENT", _filled_event())] * 2)
    ex = _make_exec(conn, AuditCollector())

    ex.send(OrderRequest(signal=_signal(), lot=0.01, contract=_spec_eurusd()))
    ex.send(OrderRequest(signal=_signal(), lot=0.01, contract=_spec_eurusd()))

    coids = [c["clientOrderId"] for c in conn.calls]
    assert len(coids) == 2
    for coid in coids:
        assert re.fullmatch(r"SNIPER_[A-Z]+_\d{13}_[0-9a-f]{8}", coid), coid
        assert len(coid) <= 50
    assert coids[0] != coids[1]  # unique (duplicate-koruma anahtarı)


# ── 7: partial-fill TERMINAL (D169-Nokta-8; istisna YOK) ─────────────────


def test_partial_fill_terminal():
    """ORDER_PARTIAL_FILL -> TERMINAL: filled=False + ORDER(partial)+SAFETY."""
    ev = SimpleNamespace(
        executionType="ORDER_PARTIAL_FILL",
        errorCode=None,
        order=SimpleNamespace(orderId=777001),
        position=SimpleNamespace(id=555001),
        deal=SimpleNamespace(filledVolume=50000, dealStatus="PARTIALLY_FILLED"),
    )
    conn = FakeExecConnection(scripted_events=[("EXECUTION_EVENT", ev)])
    audit = AuditCollector()
    ex = _make_exec(conn, audit)

    res = ex.send(OrderRequest(signal=_signal(), lot=0.01, contract=_spec_eurusd()))

    assert res.sent is True  # emir gitti
    assert res.filled is False  # ama partial -> TERMINAL
    assert "partial_fill" in res.reason
    orders = audit.of_type(EventType.ORDER)
    assert any(e[2].get("partial_fill") is True for e in orders)
    safety = audit.of_type(EventType.SAFETY)
    assert any(e[2].get("reason") == "partial_fill_rejected" for e in safety)
    # retry YOK: tek send_order çağrısı
    assert len(conn.calls) == 1


# ── 8: isLimitedRisk çift-kontrol (D169-Nokta-4 kapı-7) ──────────────────


def test_is_limited_risk_boot_check():
    """Limited-risk hesap + GSL-desteklemeyen sembol -> fail-loud (FATAL)."""
    _require_impl()
    ex = CTraderExecution(
        connection=FakeExecConnection(),
        audit=AuditCollector(),
        symbol_meta=SYMBOL_META,
        signal_only=False,
    )
    # (True, EURUSD GSL=False) -> FATAL
    with pytest.raises(CTraderSafetyError):
        ex.validate_limited_risk(trader_is_limited_risk=True, symbol="EURUSD")
    # (True, XAUUSD GSL=True) -> uyumlu
    ex.validate_limited_risk(trader_is_limited_risk=True, symbol="XAUUSD")
    # (False, EURUSD) -> limited-risk değil, GSL şartı yok
    ex.validate_limited_risk(trader_is_limited_risk=False, symbol="EURUSD")


# ── 9: signal_only default True (dry-run) ────────────────────────────────


def test_dry_run_no_order_sent():
    """signal_only default True: broker'a GİTMEZ + dry_run ORDER audit."""
    conn = FakeExecConnection()
    audit = AuditCollector()
    _require_impl()
    ex = CTraderExecution(connection=conn, audit=audit, symbol_meta=SYMBOL_META)

    res = ex.send(OrderRequest(signal=_signal(), lot=0.01, contract=_spec_eurusd()))

    assert len(conn.calls) == 0  # broker'a GİTMEDİ
    assert res.dry_run is True
    assert res.filled is False
    orders = audit.of_type(EventType.ORDER)
    assert len(orders) == 1
    assert orders[0][2].get("dry_run") is True  # D169-Nokta-7


# ── 10: ERROR_RES retryAfter (rate-limit) ────────────────────────────────


def test_error_res_retry_after(monkeypatch):
    """REQUEST_FREQUENCY_EXCEEDED + retryAfter -> bekle + retry."""
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    err = SimpleNamespace(
        errorCode="REQUEST_FREQUENCY_EXCEEDED",
        description="rate limit",
        retryAfter=2,
    )
    conn = FakeExecConnection(
        scripted_events=[
            ("ERROR_RES", err),
            ("EXECUTION_EVENT", _filled_event()),
        ]
    )
    ex = _make_exec(conn, AuditCollector())

    res = ex.send(OrderRequest(signal=_signal(), lot=0.01, contract=_spec_eurusd()))

    assert len(conn.calls) == 2  # retry yapıldı
    assert sleeps and sleeps[0] >= 2  # retryAfter dikkate alındı
    assert res.filled is True


# ── 11: §2.2 contract pin (API koruması) ─────────────────────────────────


def test_contract_pin():
    """§2.2: MT5-Execution API DOKUNULMAZ + CTraderExecution sözleşme pin."""
    from src.live.execution import Execution as MT5Execution

    _require_impl()

    # MT5-Execution hâlâ import edilebilir (DOKUNULMAZ kanıtı)
    assert MT5Execution is not None
    assert DEFAULT_MAGIC == 9007001

    # OrderRequest sözleşmesi (MT5-Execution'dan import — duplicate YASAK)
    ofields = {f.name for f in dataclasses.fields(OrderRequest)}
    assert {"signal", "lot", "contract", "deviation", "magic", "comment"} <= ofields

    # ExecutionResult sözleşmesi
    rfields = {f.name for f in dataclasses.fields(ExecutionResult)}
    assert {"sent", "filled", "dry_run", "reason"} <= rfields

    # CTraderExecution aynı send(OrderRequest) -> ExecutionResult sözleşmesi
    assert hasattr(CTraderExecution, "send")
    params = list(inspect.signature(CTraderExecution.send).parameters)
    assert params[0] == "self" and params[1] == "request"
