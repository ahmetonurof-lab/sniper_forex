"""Local test stub — bot_infra.py (server bot_infra.py'nin test icin yeterli kismi).

RetryConfig + CircuitBreaker + _RateLimiter. Gercek dosyadan birebir
kopyalanmistir (p1_fix_infra.txt / p1_fix_infra2.txt kaynak).
"""

import logging
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class RetryConfig:
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    backoff_multiplier: float = 2.0
    jitter: bool = True
    retry_on_http: tuple[int, ...] = (429, 500, 502, 503, 504)


class CircuitBreaker:
    """HTTP seviyesi devre kesici (network). Risk devre kesici DEGIL."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failures = 0
        self._open_until = 0.0

    def is_open(self) -> bool:
        if self._open_until <= time.monotonic():
            return False
        return True

    async def is_open_async(self) -> bool:
        return self.is_open()

    def record_success(self) -> None:
        self._failures = 0

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._open_until = time.monotonic() + self.recovery_timeout

    async def call(self, fn, *args, **kwargs):
        if self.is_open():
            remaining = self._open_until - time.monotonic()
            return Result.fail(f"Circuit breaker open — {remaining:.0f}s remaining")
        try:
            result = await fn(*args, **kwargs)
            self.record_success()
            return result
        except Exception:
            self.record_failure()
            raise


class _RateLimiter:
    """Basit token kova rate limiter (test icin yeterli)."""

    def __init__(self, max_per_minute: int = 1200):
        self.max_per_minute = max_per_minute
        self._tokens = max_per_minute
        self._last_refill = time.monotonic()

    async def acquire(self) -> None:
        # Test ortaminda gercek bekleme yok — token havuzu yeterince buyuk.
        return None


rate_limiter = _RateLimiter(max_per_minute=1200)


# models.Result stub — bot_binance_local.py icin
class Result:
    def __init__(self, ok: bool, value=None, error: str = ""):
        self._ok = ok
        self.value = value
        self.error = error

    @property
    def is_ok(self) -> bool:
        return self._ok

    @property
    def is_err(self) -> bool:
        return not self._ok

    @staticmethod
    def ok(value=None) -> "Result":
        return Result(True, value=value)

    @staticmethod
    def fail(error: str = "") -> "Result":
        return Result(False, error=error)
