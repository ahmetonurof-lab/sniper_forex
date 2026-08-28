#!/usr/bin/env python
"""Live M1 candle feed -> canonical 15m closed candle production.

PHASE 2 — MARKET DATA / 15M CANDLE FEED.

Responsibilities:
- Pull-based M1 feed from MT5 (via `MT5DataLayer`).
- Forming vs closed candle distinction.
- Duplicate candle detection.
- Missing candle detection.
- Historical warmup.
- Server-time -> UTC conversion (parity with backtest).
- Canonical 15m aggregation matching the backtest boundary.

Canonical boundary (frozen engine `resample_15m()`):
- Bucket by grid-aligned 15m slot (epoch_ms // 15min).
- Label each bucket with its FIRST bar's timestamp (NOT grid-aligned).
- open=first, high=max, low=min, close=last, volume=sum.
- Drop buckets with <3 bars.

This module re-implements that exact boundary (copy-adapt) so the live
runtime does NOT import from the frozen research engine.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd

from src.data.mt5_data import MT5DataLayer
from src.live.clock import server_to_utc_historical
from src.strategy.models import Bar

# Canonical 15m bucket size in ms
_15M_MS = 15 * 60 * 1000


def _utcnow_naive() -> datetime:
    """Current UTC time as a naive datetime (matches backtest convention)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def resample_15m(bars_1m: List[Bar]) -> List[Bar]:
    """Aggregate M1 bars into canonical 15m bars.

    Mirrors the frozen research engine's `resample_15m()` EXACTLY so live
    aggregation is byte-for-byte parity with the backtest boundary.
    """
    buckets: Dict[int, List[Bar]] = {}
    for b in bars_1m:
        ts_ms = int(b.timestamp.timestamp() * 1000)
        slot = (ts_ms // _15M_MS) * _15M_MS
        buckets.setdefault(slot, []).append(b)

    m15: List[Bar] = []
    for slot in sorted(buckets):
        c = buckets[slot]
        if len(c) < 3:
            continue
        m15.append(
            Bar(
                index=len(m15),
                timestamp=c[0].timestamp,
                open=c[0].open,
                high=max(b.high for b in c),
                low=min(b.low for b in c),
                close=c[-1].close,
                volume=sum(b.volume for b in c),
            )
        )
    return m15


class M1CandleFeed:
    """Pull-based M1 feed from MT5 with dup/missing detection and 15m aggregation."""

    def __init__(self, data_layer: Optional[MT5DataLayer] = None):
        self.data = data_layer or MT5DataLayer()
        self._last_15m_ts: Optional[pd.Timestamp] = None
        # Last detection results (surfaced for audit/safety)
        self.last_duplicates: List[pd.Timestamp] = []
        self.last_missing: List[pd.Timestamp] = []

    # -- M1 fetch ---------------------------------------------------------
    def fetch_m1(self, symbol: str, count: int = 100) -> List[Bar]:
        """Fetch M1 bars from MT5, convert server-time -> UTC, oldest first.

        Returns [] on failure (error captured by data layer).
        """
        rates = self.data.get_rates(symbol, timeframe="M1", count=count)
        if rates is None:
            return []
        bars: List[Bar] = []
        for i, r in enumerate(rates):
            ts_server = pd.Timestamp(r["time"], unit="s")
            ts_utc = pd.Timestamp(server_to_utc_historical(ts_server.to_pydatetime()))
            bars.append(
                Bar(
                    index=i,
                    timestamp=ts_utc,
                    open=float(r["open"]),
                    high=float(r["high"]),
                    low=float(r["low"]),
                    close=float(r["close"]),
                    volume=float(r["tick_volume"]),
                )
            )
        return bars

    # -- Detection --------------------------------------------------------
    @staticmethod
    def find_duplicates(bars: List[Bar]) -> List[pd.Timestamp]:
        """Return timestamps that appear more than once (duplicate candles)."""
        seen: Dict[pd.Timestamp, int] = {}
        for b in bars:
            seen[b.timestamp] = seen.get(b.timestamp, 0) + 1
        return [ts for ts, n in seen.items() if n > 1]

    @staticmethod
    def find_missing(bars: List[Bar]) -> List[pd.Timestamp]:
        """Return expected M1 timestamps that are absent (gaps).

        Assumes bars sorted by timestamp. Missing = expected 1-min grid
        slots between first and last that have no bar.
        """
        if len(bars) < 2:
            return []
        missing: List[pd.Timestamp] = []
        prev = bars[0].timestamp
        for b in bars[1:]:
            cur = b.timestamp
            step = prev + pd.Timedelta(minutes=1)
            while step < cur:
                missing.append(step)
                step += pd.Timedelta(minutes=1)
            prev = cur
        return missing

    # -- Forming vs closed ------------------------------------------------
    @staticmethod
    def is_closed_m1(bars: List[Bar], now: datetime) -> List[Bar]:
        """Return only M1 bars whose 1-min window has fully elapsed.

        A bar at timestamp T is closed when now >= T + 1min.
        """
        closed = []
        for b in bars:
            if now >= b.timestamp + pd.Timedelta(minutes=1):
                closed.append(b)
        return closed

    # -- Warmup -----------------------------------------------------------
    def warmup(self, symbol: str, n_15m: int = 200) -> List[Bar]:
        """Fetch enough M1 history to build n_15m closed 15m candles.

        Returns aggregated 15m candles (oldest first). May be fewer than
        n_15m if buckets drop (<3 bars) or history is short.
        """
        # ~15 M1 bars per 15m candle, plus buffer for <3-bar drops
        m1_count = n_15m * 15 + 30
        m1 = self.fetch_m1(symbol, count=m1_count)
        if not m1:
            return []
        now = _utcnow_naive()
        closed = self.is_closed_m1(m1, now)
        m15 = resample_15m(closed)
        if m15:
            self._last_15m_ts = m15[-1].timestamp
        return m15

    # -- Incremental 15m production ---------------------------------------
    def update(self, symbol: str, now: Optional[datetime] = None) -> List[Bar]:
        """Pull latest M1, detect dup/missing, produce new closed 15m candles.

        Returns newly completed 15m candles (may be empty). Detection results
        are stored on `last_duplicates` / `last_missing`.
        """
        now = now or _utcnow_naive()
        m1 = self.fetch_m1(symbol, count=100)
        if not m1:
            return []
        closed = self.is_closed_m1(m1, now)
        self.last_duplicates = self.find_duplicates(closed)
        self.last_missing = self.find_missing(closed)
        m15 = resample_15m(closed)
        new: List[Bar] = []
        for c in m15:
            if self._last_15m_ts is None or c.timestamp > self._last_15m_ts:
                new.append(c)
        if new:
            self._last_15m_ts = new[-1].timestamp
        return new
