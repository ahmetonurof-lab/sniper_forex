#!/usr/bin/env python
"""Live clock — MT5 server-time / timezone handling.

PHASE 2 — MARKET DATA / 15M CANDLE FEED.

MT5 terminal reports bar/tick timestamps in naive *server time*:
- Summer (DST): UTC+3
- Winter:       UTC+2  (unverified against live terminal — heuristic)

The canonical backtest dataset is naive UTC. For 15m aggregation parity,
live M1 timestamps must be converted server-time -> UTC before feeding
`resample_15m()`. This module owns that conversion plus the session window
clock (19:00 -> 01:00 server time, spans midnight).
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

# MT5 server UTC offsets (naive server time)
SERVER_UTC_OFFSET_SUMMER = 3
SERVER_UTC_OFFSET_WINTER = 2

# Session window (MT5 server time): 19:00 -> 01:00 (spans midnight)
SESSION_START_HOUR = 19
SESSION_END_HOUR = 1


def _utcnow_naive() -> datetime:
    """Current UTC time as a naive datetime (matches backtest convention)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _last_sunday(year: int, month: int) -> datetime:
    """Return the datetime of the last Sunday in the given month."""
    if month == 12:
        next_month = datetime(year + 1, 1, 1)
    else:
        next_month = datetime(year, month + 1, 1)
    last_day = next_month - timedelta(days=1)
    # weekday(): Mon=0 ... Sun=6. Back up to the last Sunday.
    days_since_sunday = last_day.weekday()
    return last_day - timedelta(days=(days_since_sunday + 1) % 7)


def server_utc_offset(now_utc: Optional[datetime] = None) -> int:
    """Return the MT5 server UTC offset for the given UTC time.

    Northern-hemisphere DST heuristic: last Sun Mar -> last Sun Oct.
    Returns 3 (summer) or 2 (winter).
    """
    now = now_utc or _utcnow_naive()
    year = now.year
    mar = _last_sunday(year, 3)
    oct_ = _last_sunday(year, 10)
    if mar <= now < oct_:
        return SERVER_UTC_OFFSET_SUMMER
    return SERVER_UTC_OFFSET_WINTER


def utc_to_server(dt_utc: datetime) -> datetime:
    """Convert a UTC datetime to naive MT5 server time.

    Uses the CURRENT server UTC offset (a live session has one offset at
    any moment, regardless of each bar's own timestamp).
    """
    return dt_utc + timedelta(hours=server_utc_offset())


def server_to_utc(dt_server: datetime) -> datetime:
    """Convert a naive MT5 server time to UTC.

    Uses the CURRENT server UTC offset (a live session has one offset at
    any moment, regardless of each bar's own timestamp).
    """
    return dt_server - timedelta(hours=server_utc_offset())


def now_server_time() -> datetime:
    """Current MT5 server time (naive)."""
    return utc_to_server(_utcnow_naive())


def in_session(
    dt_server: datetime,
    start_hour: int = SESSION_START_HOUR,
    end_hour: int = SESSION_END_HOUR,
) -> bool:
    """Check if a server-time datetime is inside the session window.

    Handles windows that span midnight (start_hour > end_hour).
    """
    h = dt_server.hour
    if start_hour > end_hour:  # spans midnight
        return h >= start_hour or h < end_hour
    return start_hour <= h < end_hour
