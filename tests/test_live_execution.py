#!/usr/bin/env python
"""PHASE 5 — EXECUTION — synthetic unit tests.

Covers:
- Default signal_only=True -> NO real order sent (dry-run).
- market order with SL/TP/magic/comment payload.
- order_check validation failure -> NO order_send.
- Rejection (retriable) -> retry up to max_retries -> final failure recorded.
- Rejection (non-retriable) -> no retry.
- Duplicate protection (same sl/tp within window).
- Lot <= 0 -> no send.
- Magic + comment auto-injection.
- Acceptance: order sent with SL/TP, dup prevented, reject logged + retried.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from src.live.execution import (
    DEFAULT_COMMENT_PREFIX,
    DEFAULT_MAGIC,
    Execution,
    ExecutionResult,
    OrderRequest,
)
from src.live.sizing import ContractSpec
from src.live.strategy_runtime import Signal


# ── Fake MT5 ──────────────────────────────────────────────────────


class FakeResult:
    def __init__(self, retcode, order=0, deal=0, price=0.0, comment=""):
        self.retcode = retcode
        self.order = order
        self.deal = deal
        self.price = price
        self.comment = comment


class FakeMT5:
    """Minimal fake of the MetaTrader5 module for unit tests.

    Configurable behavior:
        - check_retcode: retcode returned by order_check.
        - send_retcodes: list of retcodes returned by successive order_send
          calls (one per attempt). If empty, uses fill_retcode.
        - fill_retcode: default retcode returned by order_send.
        - send_exceptions: list of exceptions to raise on order_send calls.
    """

    # Order of the constants must match real MT5 numbers used by Execution.
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_REJECT = 10006  # treat as non-retriable
    TRADE_RETCODE_REQUOTE = 10004
    TRADE_RETCODE_PRICE_CHANGED = 10005
    TRADE_RETCODE_PRICE_OFF = 10006
    TRADE_RETCODE_CONNECTION = 10031
    TRADE_RETCODE_TIMEOUT = 10036
    TRADE_RETCODE_RETRY = 10032
    CHECK_RETCODE_OK = 0  # order_check returns 0 on success (not TRADE_RETCODE_DONE)

    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    TRADE_ACTION_DEAL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_IOC = 1

    def __init__(self):
        self.check_retcode = self.CHECK_RETCODE_OK
        self.send_retcodes: List[int] = []
        self.fill_retcode: int = 10009
        self.send_exceptions: List[Optional[Exception]] = []
        self.check_payload: Optional[Dict[str, Any]] = None
        self.send_payloads: List[Dict[str, Any]] = []
        self.check_calls: int = 0
        self.send_calls: int = 0
        self._send_idx: int = 0

    def order_check(self, request: Dict[str, Any]):
        self.check_calls += 1
        self.check_payload = dict(request)
        return FakeResult(retcode=self.check_retcode)

    def order_send(self, request: Dict[str, Any]):
        self.send_calls += 1
        self.send_payloads.append(dict(request))
        # Raise exception if one is queued for this attempt.
        idx = self._send_idx
        self._send_idx += 1
        if idx < len(self.send_exceptions) and self.send_exceptions[idx] is not None:
            raise self.send_exceptions[idx]
        # Decide retcode.
        if idx < len(self.send_retcodes):
            rc = self.send_retcodes[idx]
        else:
            rc = self.fill_retcode
        return FakeResult(
            retcode=rc,
            order=12345 + idx,
            deal=67890 + idx,
            price=request.get("price", 0.0)
            + (0.00010 if rc == self.TRADE_RETCODE_DONE else 0.0),
            comment=f"fake {rc}",
        )


# ── Test helpers ─────────────────────────────────────────────────


def _signal(**overrides) -> Signal:
    base = dict(
        symbol="EURUSD",
        direction="bullish",
        side="long",
        entry_price=1.10000,
        sl=1.09500,
        tp=1.10900,
        entry_bar_index=100,
        sweep_bar_index=90,
        zone_index=95,
        zone_top=1.10100,
        zone_bottom=1.09900,
        zone_size=0.00200,
        timestamp=pd.Timestamp("2026-08-27 19:00:00"),
    )
    base.update(overrides)
    return Signal(**base)


def _contract() -> ContractSpec:
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


def _request(**overrides) -> OrderRequest:
    base = dict(
        signal=_signal(),
        lot=0.06,
        contract=_contract(),
        deviation=20,
    )
    base.update(overrides)
    return OrderRequest(**base)


# ── Tests ────────────────────────────────────────────────────────


def test_signal_only_does_not_send_real_order():
    """Default safety mode: NO real order is sent, payload is recorded."""
    mt5 = FakeMT5()
    ex = Execution(mt5=mt5, signal_only=True)
    res: ExecutionResult = ex.send(_request())
    assert res.sent is False
    assert res.filled is False
    assert res.dry_run is True
    assert res.reason == "signal_only"
    assert mt5.send_calls == 0  # NEVER reached order_send
    assert res.request is not None
    # Payload sanity.
    p = res.request
    assert p["action"] == mt5.TRADE_ACTION_DEAL
    assert p["symbol"] == "EURUSD"
    assert p["volume"] == 0.06
    assert p["sl"] == 1.09500
    assert p["tp"] == 1.10900
    assert p["magic"] == DEFAULT_MAGIC
    assert p["comment"].startswith(DEFAULT_COMMENT_PREFIX)


def test_live_send_filled_returns_fill_price_and_ids():
    """Live mode + clean fill: filled=True with order/deal/price captured."""
    mt5 = FakeMT5()
    ex = Execution(mt5=mt5, signal_only=False, max_retries=2)
    res = ex.send(_request())
    assert res.sent is True
    assert res.filled is True
    assert res.dry_run is False
    assert res.retcode == mt5.TRADE_RETCODE_DONE
    assert res.order_id == 12345
    assert res.deal_id == 67890
    assert res.fill_price is not None
    assert res.fill_price > 0
    assert res.attempts == 1
    assert res.reason == ""
    assert mt5.send_calls == 1


def test_order_check_failure_does_not_call_order_send():
    """If order_check returns a non-DONE retcode, order_send is NEVER called."""
    mt5 = FakeMT5()
    mt5.check_retcode = mt5.TRADE_RETCODE_REJECT
    ex = Execution(mt5=mt5, signal_only=False)
    res = ex.send(_request())
    assert res.sent is False
    assert res.filled is False
    assert res.reason == "order_check_failed"
    assert mt5.send_calls == 0
    assert res.retcode == mt5.TRADE_RETCODE_REJECT


def test_rejection_retriable_retries_then_succeeds():
    """First attempt: requote (retriable). Second: fill."""
    mt5 = FakeMT5()
    mt5.send_retcodes = [mt5.TRADE_RETCODE_REQUOTE, mt5.TRADE_RETCODE_DONE]
    ex = Execution(mt5=mt5, signal_only=False, max_retries=3, retry_sleep_sec=0.0)
    res = ex.send(_request())
    assert res.filled is True
    assert res.attempts == 2
    assert mt5.send_calls == 2


def test_rejection_retriable_exhausts_retries_then_fails():
    """All retriable rejections -> max_retries+1 attempts -> final failure."""
    mt5 = FakeMT5()
    mt5.send_retcodes = [mt5.TRADE_RETCODE_REQUOTE] * 5
    ex = Execution(mt5=mt5, signal_only=False, max_retries=2, retry_sleep_sec=0.0)
    res = ex.send(_request())
    assert res.filled is False
    assert res.sent is True
    assert res.attempts == 3  # initial + 2 retries
    assert res.reason == "TRADE_RETCODE_REQUOTE"
    assert mt5.send_calls == 3


def test_rejection_non_retriable_no_retry():
    """Non-retriable reject (REJECT) -> single attempt -> final failure."""
    mt5 = FakeMT5()
    # Send retcode 10006 is "PRICE_OFF" (retriable in our list).
    # Use a retcode that is NOT in the retriable set by patching the fake.
    NON_RETRIABLE = 10018  # TRADE_RETCODE_INVALID (arbitrary, not retriable)
    mt5.send_retcodes = [NON_RETRIABLE]
    ex = Execution(mt5=mt5, signal_only=False, max_retries=3, retry_sleep_sec=0.0)
    res = ex.send(_request())
    assert res.filled is False
    assert res.attempts == 1
    assert mt5.send_calls == 1
    assert res.reason.startswith("RETCODE_")


def test_send_exception_treated_as_retriable():
    """An exception on order_send -> retried; second attempt fills."""
    mt5 = FakeMT5()
    mt5.send_exceptions = [RuntimeError("transient broker timeout")]
    mt5.send_retcodes = [FakeMT5.TRADE_RETCODE_DONE]
    ex = Execution(mt5=mt5, signal_only=False, max_retries=2, retry_sleep_sec=0.0)
    res = ex.send(_request())
    assert res.filled is True
    assert res.attempts == 2
    assert mt5.send_calls == 2


def test_duplicate_protection_blocks_repeat_within_window():
    """Same (symbol, direction, sl, tp) within window -> blocked."""
    mt5 = FakeMT5()
    ex = Execution(
        mt5=mt5,
        signal_only=False,
        max_retries=0,
        duplicate_window_sec=60.0,
    )
    res1 = ex.send(_request())
    assert res1.filled is True
    assert mt5.send_calls == 1

    # Second call: same (symbol, sl, tp, direction) -> blocked, NO order sent.
    res2 = ex.send(_request())
    assert res2.filled is False
    assert res2.duplicate is True
    assert res2.reason == "duplicate_blocked"
    assert mt5.send_calls == 1  # not incremented


def test_duplicate_protection_different_sl_tp_not_blocked():
    """Same symbol/direction but different SL/TP -> NOT duplicate."""
    mt5 = FakeMT5()
    ex = Execution(
        mt5=mt5,
        signal_only=False,
        max_retries=0,
        duplicate_window_sec=60.0,
    )
    res1 = ex.send(_request())
    res2 = ex.send(_request(signal=_signal(sl=1.09400, tp=1.10800)))
    assert res1.filled is True
    assert res2.filled is True
    assert mt5.send_calls == 2


def test_lot_zero_does_not_send():
    mt5 = FakeMT5()
    ex = Execution(mt5=mt5, signal_only=False)
    res = ex.send(_request(lot=0.0))
    assert res.sent is False
    assert res.filled is False
    assert res.reason == "lot<=0"
    assert mt5.send_calls == 0
    assert mt5.check_calls == 0


def test_short_signal_uses_sell_order_type():
    mt5 = FakeMT5()
    ex = Execution(mt5=mt5, signal_only=True)
    res = ex.send(
        _request(signal=_signal(direction="bearish", side="short", entry_price=1.10000))
    )
    assert res.dry_run is True
    assert res.request["type"] == mt5.ORDER_TYPE_SELL


def test_magic_and_comment_override_in_payload():
    mt5 = FakeMT5()
    ex = Execution(mt5=mt5, signal_only=True, magic=42, comment_prefix="BOT")
    res = ex.send(_request(magic=999, comment="custom"))
    assert res.request["magic"] == 999
    assert res.request["comment"] == "custom"
