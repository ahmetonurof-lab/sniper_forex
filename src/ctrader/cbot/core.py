"""Pure compute engine for the CBDR calibration cBot.

Faithful, self-contained reproduction of the production CBDR / FVG / sweep
logic extracted from ``src/strategy/session.py``, ``src/strategy/fvg.py`` and
``src/strategy/sweep.py``. Decoupled from the cTrader ``api`` object so the
same code path can be exercised deterministically in unit tests (see
``tests/test_cbdr_calibration_core.py``).

Why a separate copy?
---------------------
D132 directs a *basitlesmis arastirma kopyasi* living under
``src/ctrader/cbot/`` — visually calibrating CBDR buckets on a cTrader chart.
It intentionally mirrors (but does not import) the canonical engines so the
two evolve independently and neither poisons the other's freeze boundary
(AGENTS.md §2.1 / §2.3). Formula fidelity is kept verbatim so calibration
values produced here translate directly to production ``get_cbdr_multiplier``.

Constraints honoured
---------------------
- Standard-library only (``math``). The cTrader Python runtime ships no
  numpy/pandas, so all numerics are scalar/list based.
- Times handled as integer epoch-minutes assumed UTC (repository convention).
"""

from __future__ import annotations

from collections import deque
from enum import IntEnum
from typing import Iterator, NamedTuple, Optional, Sequence

# --- fundamental time constants --------------------------------
MINUTES_PER_DAY = 1440  # minutes in a civil day


class Direction(IntEnum):
    NEUTRAL = 0
    BULLISH = 1
    BEARISH = -1


class MiniBar(NamedTuple):
    """Lightweight OHLC bar fed from ``api.Bars`` series."""

    ts_minutes: int  # epoch minutes (UTC), monotonically increasing
    open_: float
    high: float
    low: float
    close: float

    @property
    def body_high(self) -> float:
        return max(self.open_, self.close)

    @property
    def body_low(self) -> float:
        return min(self.open_, self.close)


# ---------------------------------------------------------------------------
# Clock helpers (integers-as-epoch-minutes, interpreted as UTC)
# ---------------------------------------------------------------------------


def day_num(minute: int) -> int:
    """Civil day ordinal for an epoch-minute (floors toward -infinity)."""
    q, r = divmod(minute, MINUTES_PER_DAY)
    return q


def clock_hhmm(minute: int) -> int:
    """Return HHMM (int) representing the time-of-day of ``minute`` (UTC)."""
    _, tod = divmod(minute, MINUTES_PER_DAY)
    h, m = divmod(tod, 60)
    return h * 100 + m


def fmt_date(num: int) -> str:
    """ISO YYYY-MM-DD for the civil day containing epoch-minute ``num`` (UTC)."""
    from datetime import datetime, timezone

    posix_sec = num * 60
    return datetime.fromtimestamp(posix_sec, tz=timezone.utc).date().isoformat()


def fmt_datetime(minute: int) -> str:
    """RFC-ish UTC stamp for an epoch-minute (labelling aid)."""
    from datetime import datetime, timezone

    return datetime.fromtimestamp(minute * 60, tz=timezone.utc).isoformat(timespec="minutes")


def cbdr_day_num(minute: int, span_start_hhmm: int, span_end_hhmm: int) -> int:
    """CBDR cycle ordinal — the civil day the window ENDS on.

    Mirrors canonical ``session.py::cbdr_day_key``: for a midnight-spanning
    window (end <= start), evening bars (>= start) roll FORWARD to the next
    civil day, so 19:00 day-D and 00:30 day-(D+1) share ONE CBDR cycle.
    Keying by raw civil day instead splits every midnight-spanning window
    into a 19:00-23:59 fragment and a 00:00-00:59 fragment — poisoning the
    body, the width% and every sweep evaluated against the half-body.
    """
    dn = day_num(minute)
    if span_end_hhmm <= span_start_hhmm and clock_hhmm(minute) >= span_start_hhmm:
        return dn + 1
    return dn


# ---------------------------------------------------------------------------
# Rolling ATR (simple Wilder-less mean true range over a bounded window)
# ---------------------------------------------------------------------------


class RollMean:
    """Fixed-size sliding-window arithmetic mean (stdlib only)."""

    __slots__ = ("capacity", "_buf", "_sum")

    def __init__(self, capacity: int) -> None:
        self.capacity = max(1, capacity)
        self._buf: deque = deque(maxlen=self.capacity)
        self._sum = 0.0

    def push(self, value: float) -> None:
        if len(self._buf) == self.capacity:
            self._sum -= self._buf[0]
        self._buf.append(value)
        self._sum += value

    @property
    def filled(self) -> bool:
        return len(self._buf) == self.capacity

    @property
    def mean(self) -> float:
        if not self._buf:
            return 0.0
        return self._sum / len(self._buf)


def true_range(a: MiniBar, prev_close: float) -> float:
    hl = a.high - a.low
    hpc = abs(a.high - prev_close)
    lpc = abs(a.low - prev_close)
    return max(hl, hpc, lpc)


# ---------------------------------------------------------------------------
# CBDR tracker — faithful clone of src/strategy/session.py::SessionManager
# ---------------------------------------------------------------------------


class CBDRConfig(NamedTuple):
    """Knobs surfaced as cBot parameters (defined on the C# Engine side)."""

    eps_minutes: int = 15  # intra-body clustering slack
    atr_period: int = 96  # rolling ATR look-back (bars)
    sweep_atr_tolerance_mult: float = 0.02
    sweep_default_tolerance: float = 0.0  # quote-unit fallback
    span_start_hhmm: int = 1900  # window opens (local-clock UTC)
    span_end_hhmm: int = 100  # window closes (may roll past 2359)


class CBDRDay:
    """Mutable accumulators for a single CBDR day."""

    __slots__ = ("num", "bh", "bl", "count", "sw_u", "sw_d", "done")

    def __init__(self, num: int) -> None:
        self.num = num
        self.bh = 0.0
        self.bl = float("inf")
        self.count = 0
        self.sw_u = False
        self.sw_d = False
        self.done = False

    def absorb(self, bh: float, bl: float) -> None:
        self.bh = max(self.bh, bh)
        self.bl = min(self.bl, bl)
        self.count += 1

    @property
    def viable(self) -> bool:
        return self.count > 0 and self.bh > 0.0 and self.bl < float("inf")


class CBDRTrackingRow(NamedTuple):
    """Immutable emission summarising one accumulated CBDR day."""

    day_key: str
    body_high: float
    body_low: float
    width_pct: float
    swept_up: bool
    swept_down: bool
    closed_within: bool


class CBDRTracker:
    """Drives per-day CBDR accumulation + sweep marking.

    Ported semantics (verbatim predicates from session.py):
      * inside window  -> track body (absorb max/open-high, min/open-low);
      * leaving window  -> lock body ONCE (viable only);
      * outside window  -> evaluate sweep; FIRST sweep marks the day.
    """

    def __init__(self, cfg: CBDRConfig) -> None:
        self.cfg = cfg
        self.prev_close: Optional[float] = None
        self.atr = RollMean(cfg.atr_period)
        self.active: Optional[CBDRDay] = None
        self.closed: list[tuple[int, CBDRDay]] = []  # insertion-order archive

    # ----- window predicate ---------------------------------------
    def _span_spans_midnight(self) -> bool:
        return self.cfg.span_end_hhmm <= self.cfg.span_start_hhmm

    def in_window(self, minute: int) -> bool:
        cur = clock_hhmm(minute)
        s, e = self.cfg.span_start_hhmm, self.cfg.span_end_hhmm
        if self._span_spans_midnight():
            return cur >= s or cur < e
        return s <= cur < e

    # ----- tolerance ----------------------------------------------
    def _tolerance(self) -> float:
        if self.atr.mean > 0.0:
            return self.atr.mean * self.cfg.sweep_atr_tolerance_mult
        return self.cfg.sweep_default_tolerance

    # ----- intake --------------------------------------------------
    def ingest(self, bar: MiniBar) -> None:
        """Feed one bar; advances day bookkeeping and sweep evaluation."""
        # CBDR CYCLE key (canonical session.py::cbdr_day_key parity): a
        # midnight-spanning window is ONE cycle — evening bars roll forward
        # to the day the window ends on. Raw civil-day keying would split
        # 19:00->01:00 into two half-windows.
        dn = cbdr_day_num(bar.ts_minutes, self.cfg.span_start_hhmm, self.cfg.span_end_hhmm)
        if self.active is None or self.active.num != dn:
            if self.active is not None and self.active.viable:
                self.active.done = True
                self.closed.append((dn, self.active))
            self.active = CBDRDay(dn)

        # ATR maintenance happens on every ingested bar.
        if self.prev_close is not None:
            self.atr.push(true_range(bar, self.prev_close))
        self.prev_close = bar.close

        act = self.active
        if self.in_window(bar.ts_minutes):
            act.absorb(bar.body_high, bar.body_low)
            return

        # Leaving window: lock body once.
        if not act.done and act.viable:
            act.done = True
            self.closed.append((dn, act))

        # Sweep eval (post-lock) — first sweep sticks.
        if act.viable and not (act.sw_u or act.sw_d):
            tol = self._tolerance()
            if bar.high > act.bh + tol and bar.close < act.bh:
                act.sw_u = True
            elif bar.low < act.bl - tol and bar.close > act.bl:
                act.sw_d = True

    # ----- exports -------------------------------------------------
    def flush_row(self, day: CBDRDay) -> Optional["CBDRTrackingRow"]:
        if not day.viable:
            return None
        width_pct = ((day.bh - day.bl) / day.bl) * 100.0 if day.bl else 0.0
        # day.num is a CBDR CYCLE ordinal (see cbdr_day_num): for a
        # midnight-spanning window it is the civil day the window ENDS on.
        # fmt_date expects an epoch-MINUTE — convert, or every day_key
        # collides into Jan 1970.
        return CBDRTrackingRow(
            day_key=fmt_date(day.num * MINUTES_PER_DAY),
            body_high=round(day.bh, 5),
            body_low=round(day.bl, 5),
            width_pct=round(width_pct, 4),
            swept_up=day.sw_u,
            swept_down=day.sw_d,
            closed_within=day.done,
        )

    def iter_rows(self) -> Iterator[NamedTuple]:
        seen: set[int] = set()
        for _, day in reversed(self.closed):
            if day.num in seen:
                continue
            seen.add(day.num)
            row = self.flush_row(day)
            if row is not None:
                yield row
        if self.active is not None and self.active.num not in seen:
            row = self.flush_row(self.active)
            if row is not None:
                yield row


# ---------------------------------------------------------------------------
# FVG detector — faithful clone of src/strategy/fvg.py::detect_fvg
# ---------------------------------------------------------------------------


class FVGHit(NamedTuple):
    index: int
    direction: Direction
    fvg_high: float
    fvg_low: float
    fvg_size: float


def detect_fvg_on(last3: Sequence[MiniBar], bias: Direction) -> Optional[FVGHit]:
    """Three-candle fair-value gap on the LAST THREE bars supplied.

    Predicates mirrored from fvg.py:
      * Bullish: bar3.low > bar1.high  (requires bias BULLISH or NEUTRAL)
      * Bearish: bar1.low > bar3.high  (requires bias BEARISH or NEUTRAL)
    """
    if len(last3) < 3:
        return None
    b1, b2, b3 = last3[-3], last3[-2], last3[-1]
    idx = b3.ts_minutes

    if b3.low > b1.high:
        if bias in (Direction.BULLISH, Direction.NEUTRAL):
            return FVGHit(idx, Direction.BULLISH, b3.low, b1.high, b3.low - b1.high)
        return None
    if b1.low > b3.high:
        if bias in (Direction.BEARISH, Direction.NEUTRAL):
            return FVGHit(idx, Direction.BEARISH, b1.low, b3.high, b1.low - b3.high)
        return None
    return None
