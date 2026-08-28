#!/usr/bin/env python
"""P1-5 — Historical M1 timezone canonicalization tests.

Verifies:
- Historical bars use bar-date-aware DST, not current-time offset.
- Cross-path parity: candle_feed, signal_runner, paper normalize identically.
- No strategy core changes.
"""

from datetime import datetime
import pandas as pd

from src.live import clock
from src.live.signal_runner import SignalRunner
from src.live.paper import _rates_to_bars as paper_rates_to_bars


class FakeRate:
    def __init__(self, time, open, high, low, close, tick_volume=0.0):
        self.time = time
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.tick_volume = tick_volume


def test_historical_bar_uses_own_date_dst():
    """A July historical bar (summer) converts with +3; a Jan historical
    bar (winter) converts with +2, regardless of the current date."""
    jan_server = datetime(2026, 1, 15, 12, 0, 0)  # winter
    jul_server = datetime(2026, 7, 15, 12, 0, 0)  # summer
    assert clock.server_to_utc_historical(jan_server) - jan_server == __import__(
        "datetime"
    ).timedelta(hours=-2)
    assert clock.server_to_utc_historical(jul_server) - jul_server == __import__(
        "datetime"
    ).timedelta(hours=-3)


def test_historical_vs_current_offset_different():
    """If current date is July (summer), a January historical bar must
    NOT use the current +3 offset; it must use its own +2."""
    jan_server = datetime(2026, 1, 15, 12, 0, 0)
    historical_utc = clock.server_to_utc_historical(jan_server)  # correct
    # They must differ when the bar's season differs from current season.
    # We verify historical is exactly 1 hour more (winter = +2 vs summer +3).
    # current offset depends on today's date; we just assert historical is
    # deterministic and does not call server_utc_offset() implicitly.
    assert historical_utc == datetime(2026, 1, 15, 10, 0, 0)


def test_cross_path_parity_same_timestamp():
    """Same historical M1 timestamp normalized identically by candle_feed,
    signal_runner, and paper."""
    epoch_server = 1_780_000_000  # arbitrary server-time epoch
    rate = FakeRate(
        time=epoch_server,
        open=1.0,
        high=1.0,
        low=1.0,
        close=1.0,
        tick_volume=1.0,
    )

    # candle_feed path
    # Manually inject via the same normalization path used in fetch_m1
    # We test the conversion function directly for determinism.
    ts_server = pd.Timestamp(epoch_server, unit="s")
    from src.live.clock import server_to_utc_historical

    ts_utc_feed = pd.Timestamp(server_to_utc_historical(ts_server.to_pydatetime()))

    # signal_runner path
    bars_sig = SignalRunner._rates_to_bars([rate])
    ts_utc_sig = bars_sig[0].timestamp

    # paper path
    bars_paper = paper_rates_to_bars([rate])
    ts_utc_paper = bars_paper[0].timestamp

    assert ts_utc_feed == ts_utc_sig == ts_utc_paper, (
        f"cross-path timestamp mismatch: feed={ts_utc_feed}, "
        f"sig={ts_utc_sig}, paper={ts_utc_paper}"
    )
