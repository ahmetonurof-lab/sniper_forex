"""
P1-FIX testleri — bot_binance.py -1021 (stale timestamp) fix'i.

Kapsam:
  - get/post/delete/_emergency_post retry'larinda timestamp HER ATTEMPT'te
    yenilenir (eski kod: loop disinda bir kez uretilirdi -> retry ayni
    stale timestamp'i gonderirdi -> recvWindow asimi -1021)
  - signature da yeni timestamp ile yeniden hesaplanir
  - basarisiz attempt sonrasi basarili attempt dogru sonuc doner
"""

import asyncio
import json
import re
import time

import pytest
from bot_binance import BinanceRESTClient


class FakeResponse:
    def __init__(self, status, text):
        self.status = status
        self._text = text

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Attempt 1'de ClientError firlatir, sonra basarili doner.

    Her cagrida (url, data) kaydedilir — timestamp tazeligi buradan
    dogrulanir.
    """

    def __init__(self, fail_attempts=1, ok_status=200, ok_body=None):
        self.fail_attempts = fail_attempts
        self.ok_status = ok_status
        self.ok_body = ok_body if ok_body is not None else {"ok": True}
        self.calls = []  # (method, url, data)
        self.closed = False  # _ensure_session() kontrolu icin

    def get(self, url, headers=None):
        self.calls.append(("GET", url, None))
        if len(self.calls) <= self.fail_attempts:
            raise __import__("aiohttp").ClientConnectionError("conn reset")
        return FakeResponse(self.ok_status, json.dumps(self.ok_body))

    def post(self, url, data=None, headers=None):
        self.calls.append(("POST", url, data))
        if len(self.calls) <= self.fail_attempts:
            raise __import__("aiohttp").ClientConnectionError("conn reset")
        return FakeResponse(self.ok_status, json.dumps(self.ok_body))

    def delete(self, url, headers=None):
        self.calls.append(("DELETE", url, None))
        if len(self.calls) <= self.fail_attempts:
            raise __import__("aiohttp").ClientConnectionError("conn reset")
        return FakeResponse(self.ok_status, json.dumps(self.ok_body))


def _extract_ts(url_or_data: str) -> int:
    """url veya form-data'dan timestamp degerini cikar."""
    m = re.search(r"(?:[?&]|^)timestamp=(\d+)", url_or_data)
    if m:
        return int(m.group(1))
    m = re.search(r"timestamp=(\d+)", url_or_data)
    return int(m.group(1)) if m else -1


def _make_client(session: FakeSession) -> BinanceRESTClient:
    client = BinanceRESTClient.__new__(BinanceRESTClient)
    client._api_key = "test_key"
    client._api_secret = "test_secret"
    client._base_url = "https://demo-fapi.binance.com"
    client._retry_config = __import__("bot_infra").RetryConfig(
        max_retries=3, base_delay=0.01, max_delay=0.05, jitter=False
    )
    client._circuit_breaker = __import__("bot_infra").CircuitBreaker(
        failure_threshold=100, recovery_timeout=60.0
    )
    client._rate_limiter = __import__("bot_infra")._RateLimiter(max_per_minute=100000)
    client._semaphore = asyncio.Semaphore(10)
    client._session = session
    client._session_owner = False
    return client


class TestGetRetryFreshTimestamp:
    @pytest.mark.asyncio
    async def test_get_retry_uses_fresh_timestamp(self):
        session = FakeSession(fail_attempts=1)
        client = _make_client(session)
        r = await client.get("/fapi/v1/ticker/price", "symbol=BTCUSDT")
        assert r.is_ok
        assert len(session.calls) == 2
        ts1 = _extract_ts(session.calls[0][1])
        ts2 = _extract_ts(session.calls[1][1])
        assert ts1 != ts2, "retry ayni stale timestamp'i kullandi (-1021!)"
        assert abs(time.time() * 1000 - ts2) < 5000, "ikinci ts taze olmali"

    @pytest.mark.asyncio
    async def test_get_retry_signature_recomputed(self):
        session = FakeSession(fail_attempts=1)
        client = _make_client(session)
        r = await client.get("/fapi/v1/ticker/price", "symbol=BTCUSDT")
        assert r.is_ok
        sig1 = re.search(r"signature=([0-9a-f]+)", session.calls[0][1]).group(1)
        sig2 = re.search(r"signature=([0-9a-f]+)", session.calls[1][1]).group(1)
        assert sig1 != sig2, "signature yeni timestamp ile yeniden hesaplanmali"


class TestPostRetryFreshTimestamp:
    @pytest.mark.asyncio
    async def test_post_retry_uses_fresh_timestamp(self):
        session = FakeSession(fail_attempts=1)
        client = _make_client(session)
        r = await client.post("/fapi/v1/order", {"symbol": "BTCUSDT", "side": "BUY"})
        assert r.is_ok
        assert len(session.calls) == 2
        ts1 = _extract_ts(session.calls[0][2])
        ts2 = _extract_ts(session.calls[1][2])
        assert ts1 != ts2, "retry ayni stale timestamp'i kullandi (-1021!)"
        assert abs(time.time() * 1000 - ts2) < 5000

    @pytest.mark.asyncio
    async def test_post_retry_signature_recomputed(self):
        session = FakeSession(fail_attempts=1)
        client = _make_client(session)
        r = await client.post("/fapi/v1/order", {"symbol": "BTCUSDT", "side": "BUY"})
        assert r.is_ok
        sig1 = re.search(r"signature=([0-9a-f]+)", session.calls[0][2]).group(1)
        sig2 = re.search(r"signature=([0-9a-f]+)", session.calls[1][2]).group(1)
        assert sig1 != sig2


class TestDeleteRetryFreshTimestamp:
    @pytest.mark.asyncio
    async def test_delete_retry_uses_fresh_timestamp(self):
        session = FakeSession(fail_attempts=1)
        client = _make_client(session)
        r = await client.delete("/fapi/v1/order", "symbol=BTCUSDT&orderId=123")
        assert r.is_ok
        assert len(session.calls) == 2
        ts1 = _extract_ts(session.calls[0][1])
        ts2 = _extract_ts(session.calls[1][1])
        assert ts1 != ts2, "retry ayni stale timestamp'i kullandi (-1021!)"
        assert abs(time.time() * 1000 - ts2) < 5000


class TestEmergencyPostRetryFreshTimestamp:
    @pytest.mark.asyncio
    async def test_emergency_post_retry_uses_fresh_timestamp(self):
        session = FakeSession(fail_attempts=1)
        client = _make_client(session)
        r = await client._emergency_post("/fapi/v1/order", {"symbol": "BTCUSDT", "side": "SELL"})
        assert r.is_ok
        assert len(session.calls) == 2
        ts1 = _extract_ts(session.calls[0][2])
        ts2 = _extract_ts(session.calls[1][2])
        assert ts1 != ts2, "emergency retry ayni stale timestamp'i kullandi (-1021!)"
        assert abs(time.time() * 1000 - ts2) < 5000


class TestNoRetryOnNonRetryable:
    @pytest.mark.asyncio
    async def test_get_http_400_no_retry_single_call(self):
        """-1021 gibi HTTP 400 retry edilmemeli (retry_on_http disinda)."""
        session = FakeSession(fail_attempts=0, ok_status=400, ok_body={"code": -1021})
        client = _make_client(session)
        r = await client.get("/fapi/v1/ticker/price", "symbol=BTCUSDT")
        assert r.is_err
        assert len(session.calls) == 1, "HTTP 400 retry edilmemeli"
        assert "-1021" in r.error or "400" in r.error
