"""Smoke test: execute the REAL scaffold bot end-to-end against a stubbed api.

D132 Adim 4g regression. The deployed bot previously lost a method
(``_track_window``) during an edit accident; ``py_compile`` cannot catch a
missing attribute, only runtime execution can. This test loads
``src/ctrader/cbot/scaffold/cbdr_calibration_bot.py`` verbatim, injects a
stubbed ``api`` (cAlgo/System namespaces faked), and drives the full
lifecycle: on_start warm-up -> on_bar feed -> on_timer -> on_stop output.

Guards covered:
  * every lifecycle/private method referenced by the class actually exists;
  * OnBar semantic: the just-CLOSED bar (Count-2) is ingested, never the
    still-forming last bar (Count-1);
  * warm-up excludes the forming bar;
  * duplicate ts feed is deduped (_last_ts guard);
  * CBDR rows are emitted on on_stop.
"""

from __future__ import annotations

import builtins
import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

SCAFFOLD = Path(__file__).resolve().parents[1] / "src" / "ctrader" / "cbot" / "scaffold"
BOT_FILE = SCAFFOLD / "cbdr_calibration_bot.py"


# ---------------------------------------------------------------------------
# Stub .NET / cAlgo surface (pythonnet-free)
# ---------------------------------------------------------------------------
def _install_stub_modules() -> None:
    """Register minimal clr/cAlgo/System stubs in sys.modules (idempotent)."""

    if "clr" in sys.modules and getattr(sys.modules["clr"], "_is_stub", False):
        return

    clr = ModuleType("clr")
    clr.AddReference = lambda *a, **k: None  # type: ignore[attr-defined]
    clr._is_stub = True  # type: ignore[attr-defined]

    calgo = ModuleType("cAlgo")
    calgo_api = ModuleType("cAlgo.API")

    class Color:  # cAlgo.API.Color stand-in (what the Draw* APIs expect)
        White = "White"

        @staticmethod
        def FromArgb(*args: int) -> tuple:
            # 4-arg (A,R,G,B) and 2/3-arg overloads.
            if len(args) == 3:
                return (255, args[0], args[1], args[2])
            if len(args) == 2:
                return (args[0], args[1])
            return tuple(args)

    class ChartIconType:
        UpArrow = "UpArrow"
        DownArrow = "DownArrow"

    class VerticalAlignment:
        Top = "Top"

    class HorizontalAlignment:
        Left = "Left"

    calgo_api.Color = Color  # type: ignore[attr-defined]
    calgo_api.ChartIconType = ChartIconType  # type: ignore[attr-defined]
    calgo_api.VerticalAlignment = VerticalAlignment  # type: ignore[attr-defined]
    calgo_api.HorizontalAlignment = HorizontalAlignment  # type: ignore[attr-defined]

    system = ModuleType("System")

    class SystemDateTime:
        """DateTime stand-in: holds a real datetime, exposes .Subtract()."""

        def __init__(self, *args: object) -> None:
            # Kind arg (7th) is dropped; bot never uses microseconds.
            y, mo, d = int(args[0]), int(args[1]), int(args[2])  # type: ignore[index]
            h = int(args[3]) if len(args) > 3 else 0  # type: ignore[index]
            mi = int(args[4]) if len(args) > 4 else 0  # type: ignore[index]
            s = int(args[5]) if len(args) > 5 else 0  # type: ignore[index]
            self._dt = datetime(y, mo, d, h, mi, s)

        def Subtract(self, other: "SystemDateTime") -> "FakeTimeSpan":
            return FakeTimeSpan(self._dt - other._dt)

    class FakeTimeSpan:
        def __init__(self, td: timedelta) -> None:
            self._td = td

        @property
        def TotalMinutes(self) -> float:
            return self._td.total_seconds() / 60.0

        @classmethod
        def FromSeconds(cls, secs: float) -> "FakeTimeSpan":
            return cls(timedelta(seconds=secs))

    class DateTimeKind:
        Utc = 0

    system.DateTime = SystemDateTime  # type: ignore[attr-defined]
    system.TimeSpan = FakeTimeSpan  # type: ignore[attr-defined]
    system.DateTimeKind = DateTimeKind  # type: ignore[attr-defined]

    # NOTE: no System.Drawing stub — the bot must NOT import System.Drawing
    # (its Color shadows cAlgo.API.Color and crashes the Draw* bridge).
    # If the bot ever re-adds that import, this test fails on import — which
    # is exactly the regression signal we want.
    sys.modules.pop("System.Drawing", None)

    sys.modules.setdefault("cAlgo", calgo)
    sys.modules["cAlgo.API"] = calgo_api
    sys.modules["clr"] = clr
    sys.modules.setdefault("System", system)


# ---------------------------------------------------------------------------
# Stub api object
# ---------------------------------------------------------------------------
def _epoch_minutes(dt: object) -> int:
    real = getattr(dt, "_dt", dt)  # unwrap SystemDateTime stub if present
    return int((real - datetime(1970, 1, 1)).total_seconds() // 60)


class _StubBar:
    def __init__(self, open_time: datetime, open_: float) -> None:
        # OpenTime mimics the .NET surface the bot relies on (.Subtract).
        system = sys.modules["System"]
        self.OpenTime = system.DateTime(
            open_time.year,
            open_time.month,
            open_time.day,
            open_time.hour,
            open_time.minute,
            open_time.second,
        )
        self.Open = open_
        self.High = open_ + 0.0012
        self.Low = open_ - 0.0012
        self.Close = open_ + 0.0004


class _StubBars:
    def __init__(self, bars: list[_StubBar]) -> None:
        self._bars = bars

    @property
    def Count(self) -> int:
        return len(self._bars)

    def __getitem__(self, i: int) -> _StubBar:
        return self._bars[i]

    def append(self, bar: _StubBar) -> None:
        self._bars.append(bar)


class _StubChart:
    def __init__(self) -> None:
        self.rects: list[str] = []
        self.coords: dict[str, tuple[float, float, float, float]] = {}

    def DrawRectangle(
        self, name: str, t1: float, y1: float, t2: float, y2: float, *_c: object
    ) -> SimpleNamespace:
        self.rects.append(name)
        self.coords[name] = (t1, y1, t2, y2)
        return SimpleNamespace(IsFilled=False)

    def DrawIcon(self, name: str, *_a: object) -> None:
        self.rects.append(name)

    def DrawText(self, name: str, *_a: object) -> None:
        self.rects.append(name)

    def DrawStaticText(self, name: str, *_a: object) -> None:
        self.rects.append(name)


def _make_history() -> list[_StubBar]:
    """15m closed bars 01-03 Jan 2026; window 1900-0100; last bar FORMING."""
    bars: list[_StubBar] = []
    t = datetime(2026, 1, 1, 0, 0)
    end = datetime(2026, 1, 3, 12, 0)
    price = 1.1000
    while t <= end:
        wiggle = 0.0008 * ((t.hour * 60 + t.minute) % 7 - 3)
        bars.append(_StubBar(t, price + wiggle))
        t += timedelta(minutes=15)
    return bars


def _make_api(bars: list[_StubBar], printed: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        EpsMinutes=15,
        AtrPeriod=96,
        SweepAtrToleranceMult=0.02,
        SweepDefaultTolerance=0.0,
        SpanStartHhmm=1900,
        SpanEndHhmm=100,
        SymbolName="EURUSD",
        TimeFrame=SimpleNamespace(Name="m15"),
        Bars=_StubBars(bars),
        Chart=_StubChart(),
        Timer=SimpleNamespace(Start=lambda _ts: None),
        Print=printed.append,
    )


@pytest.fixture()
def bot_class():
    """Load the REAL bot module with stubs installed; restore builtins after."""
    _install_stub_modules()
    saved_api = getattr(builtins, "api", None)
    saved_path = list(sys.path)
    sys.path.insert(0, str(SCAFFOLD))  # bot does: from core import ...
    spec = importlib.util.spec_from_file_location("cbdr_calibration_bot_under_test", BOT_FILE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    yield mod.CalibrationBot
    if saved_api is None:
        if hasattr(builtins, "api"):
            del builtins.api  # type: ignore[attr-defined]
    else:
        builtins.api = saved_api  # type: ignore[attr-defined]
    sys.path[:] = saved_path


def test_all_referenced_methods_exist(bot_class) -> None:
    """Regression for the lost _track_window (py_compile cannot catch it)."""
    for name in (
        "on_start",
        "on_bar",
        "on_timer",
        "on_stop",
        "_feed_bar",
        "_epoch_minutes",
        "_track_window",
        "_draw_cbdr",
        "_draw_fvg",
        "_draw_panel",
    ):
        assert callable(getattr(bot_class, name, None)), f"missing method: {name}"


def test_full_lifecycle_smoke(bot_class) -> None:
    bars = _make_history()
    printed: list[str] = []
    api = _make_api(bars, printed)
    builtins.api = api  # type: ignore[attr-defined]

    bot = bot_class()
    bot.on_start()  # warm-up must not raise (was: AttributeError _track_window)

    # Warm-up must ingest the last CLOSED bar, never the forming last bar.
    assert bot._last_ts == _epoch_minutes(bars[-2].OpenTime)
    assert bot._last_ts != _epoch_minutes(bars[-1].OpenTime)

    # OnBar: new forming bar appended -> just-closed bar (old last) is fed.
    last_real = bars[-1].OpenTime._dt  # unwrap stub wrapper
    new_forming = _StubBar(last_real + timedelta(minutes=15), 1.1010)
    bars.append(new_forming)
    bot.on_bar()
    assert bot._last_ts == _epoch_minutes(bars[-2].OpenTime)

    bot.on_timer()

    bot.on_stop()
    cbdr_lines = [ln for ln in printed if ln.startswith("CBDR ")]
    assert len(cbdr_lines) >= 2  # days 01.01 and 02.01 windows closed
    assert any("2026-01-01" in ln for ln in cbdr_lines)
    assert any("2026-01-02" in ln for ln in cbdr_lines)

    # Visuals: at least one CBDR rectangle drawn.
    assert any(name.startswith("cbdr_") for name in api.Chart.rects)


def test_cbdr_rect_right_edge_covers_final_window_slot(bot_class) -> None:
    """Cosmetic-bug regression (Reis screenshot 2026-09-07).

    The box previously ended at the last in-window bar's OPEN index, leaving
    its final slot (e.g. 00:45->01:00) unpainted. The right edge must now be
    last_in_window_index + 1 for every drawn day.
    """
    bars = _make_history()
    api = _make_api(bars, [])
    builtins.api = api  # type: ignore[attr-defined]

    bot = bot_class()
    bot.on_start()
    bot.on_stop()

    drawn = {
        n
        for n in api.Chart.rects
        if n.startswith("cbdr_")
        and not n.endswith("_w")
        and not n.endswith("_swU")
        and not n.endswith("_swD")
    }
    assert drawn, "no CBDR body rectangles drawn"
    for dk in drawn:
        bare = dk[len("cbdr_") :]  # _win_end keys are bare day_key dates
        assert bare in bot._win_end, f"rect {dk} lacks window tracking"
        _t1, _y1, t2, _y2 = api.Chart.coords[dk]
        assert (
            t2 == bot._win_end[bare] + 1
        ), f"{dk}: right edge {t2} != last in-window bar {bot._win_end[bare]} + 1"


def test_duplicate_bar_feed_is_deduped(bot_class) -> None:
    bars = _make_history()
    api = _make_api(bars, [])
    builtins.api = api  # type: ignore[attr-defined]

    bot = bot_class()
    bot.on_start()
    seen = bot._last_ts
    before = len(bot._recent)

    bot._feed_bar(len(bars) - 2)  # same bar again -> dedup guard must skip
    assert bot._last_ts == seen
    assert len(bot._recent) == before
