# mypy: disable-error-code="name-defined"
"""CBDR calibration cBot — thin cTrader Automate presentation shim.

D132 Adim 2+3 deliverable. This file is the *presentation* layer only: it maps
the cTrader ``api`` bar stream into ``MiniBar`` records, feeds the pure
compute engine in ``core.py``, and draws the CBDR body / FVG / sweep markers
on the chart. All mathematics lives in ``core.py`` (unit-tested offline).

Runtime contract (verified against spotware/ctrader-python-algo-samples):
  * Plain Python class — does NOT inherit Robot.
  * ``api`` is injected globally by EngineHelper.SetApiGlobal().
  * Lifecycle proxied: on_start / on_bar / on_timer / on_stop.
  * Parameters are declared on the C# Engine side as [Parameter(...)] and
    read here as ``api.<PascalCaseName>``.
  * Stdlib only — the cTrader Python runtime ships no numpy/pandas.

Deployment model (Reis-confirmed, MT5-EA style): ONE cBot attached to ONE
chart per pair. The same code runs on each pair's chart; cTrader supplies the
per-pair symbol via ``api.SymbolName`` / ``api.Bars``. No multi-symbol
GetBars needed — the platform handles multi-pair by re-attaching the bot.

This is a RESEARCH/calibration copy (AGENTS.md §2.3). It intentionally does
not import production engines; it mirrors their predicates via core.py.
"""

# ruff: noqa: F405  (api injected via builtins by EngineHelper; ChartIconType/
#                    DateTimeKind arrive via the cAlgo.API star import)
# isort: skip_file  (clr.AddReference ordering is semantically required)
import clr  # noqa: F401  (required by the cTrader Python bridge)

clr.AddReference("cAlgo.API")
from collections import deque  # noqa: E402

# NOTE: Color here is cAlgo.API.Color (via the star import) — exactly what the
# official Spotware samples pass to every Chart.Draw* call. Do NOT import
# System.Drawing.Color: it shadows this name and the bridge then fails with
# "System.Drawing.Color value cannot be converted to cAlgo.API.Color".
from cAlgo.API import *  # noqa: F401,F403  (api, Bars, ChartIconType, Color, ...)
from System import DateTime, TimeSpan  # noqa: E402

from src.ctrader.cbot.core import (  # noqa: E402
    MINUTES_PER_DAY,
    CBDRConfig,
    CBDRTracker,
    Direction,
    MiniBar,
    cbdr_day_num,
    detect_fvg_on,
    fmt_date,
)

# --- colour palette (research doc §12.3) ---------------------------------
# cAlgo.API.Color.FromArgb overloads (official samples):
#   4-arg (a, r, g, b)  — ChartEllipse Sample: FromArgb(50, Color.Red.R, ...)
#   2-arg (alpha, Color) — ChartTriangle Sample: FromArgb(100, Color.Red)
CBDR_BODY_COLOR = Color.FromArgb(90, 30, 144, 255)  # translucent blue
FVG_BULL_COLOR = Color.FromArgb(120, 255, 165, 0)  # translucent orange
FVG_BEAR_COLOR = Color.FromArgb(120, 255, 20, 147)  # translucent deep pink
SWEEP_COLOR = Color.FromArgb(255, 255, 0, 255)  # magenta/purple (A,R,G,B)
TEXT_COLOR = Color.White

PANEL_REFRESH_SECONDS = 30


class CalibrationBot:
    """Draws CBDR bodies, FVG gaps and sweep markers on a 15m chart."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def on_start(self):
        self.cfg = CBDRConfig(
            eps_minutes=int(api.EpsMinutes),
            atr_period=int(api.AtrPeriod),
            sweep_atr_tolerance_mult=float(api.SweepAtrToleranceMult),
            sweep_default_tolerance=float(api.SweepDefaultTolerance),
            span_start_hhmm=int(api.SpanStartHhmm),
            span_end_hhmm=int(api.SpanEndHhmm),
        )
        self.tracker = CBDRTracker(self.cfg)
        self._recent = deque(maxlen=3)  # last 3 MiniBars for FVG detection
        self._win_start = {}  # day_key -> first in-window bar index
        self._win_end = {}  # day_key -> last in-window bar index
        self._drawn = set()  # names already drawn (avoid redraw spam)

        # Warm up from the already-loaded bar history so the first live bar
        # has ATR + body context (deterministic reconstruction, §6.2).
        for i in range(api.Bars.Count):
            self._feed_bar(i)

        api.Timer.Start(TimeSpan.FromSeconds(PANEL_REFRESH_SECONDS))
        self._draw_panel()

    def on_bar(self):
        # on_bar fires on each NEW bar open; feed the just-formed bar.
        self._feed_bar(api.Bars.Count - 1)
        self._draw_panel()

    def on_timer(self):
        # Periodic refresh of the static summary panel.
        self._draw_panel()

    def on_stop(self):
        for row in self.tracker.iter_rows():
            api.Print(
                "CBDR %s bh=%.5f bl=%.5f width=%.4f%% swU=%s swD=%s closed=%s"
                % (
                    row.day_key,
                    row.body_high,
                    row.body_low,
                    row.width_pct,
                    row.swept_up,
                    row.swept_down,
                    row.closed_within,
                )
            )

    # ------------------------------------------------------------------
    # Bar intake
    # ------------------------------------------------------------------
    def _feed_bar(self, idx: int):
        bar = api.Bars[idx]
        minute = self._epoch_minutes(bar.Time)
        mb = MiniBar(
            ts_minutes=minute,
            open_=float(bar.Open),
            high=float(bar.High),
            low=float(bar.Low),
            close=float(bar.Close),
        )
        self.tracker.ingest(mb)
        self._recent.append(mb)
        self._track_window(idx, minute)
        self._draw_cbdr(idx)
        self._draw_fvg(idx)

    @staticmethod
    def _epoch_minutes(dt) -> int:
        """System.DateTime -> integer epoch-minutes (UTC)."""
        epoch = DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)
        return int(dt.ToUniversalTime().Subtract(epoch).TotalMinutes)

    def _track_window(self, idx: int, minute: int):
        """Record the bar-index span of each day's CBDR window."""
        if self.tracker.in_window(minute):
            # Cycle key MUST match tracker.ingest (cbdr_day_num): evening
            # bars roll to the window-end day, else the drawn rectangle
            # covers only the 00:00->01:00 fragment of the window.
            dk = fmt_date(
                cbdr_day_num(minute, self.cfg.span_start_hhmm, self.cfg.span_end_hhmm)
                * MINUTES_PER_DAY
            )
            self._win_start.setdefault(dk, idx)
            self._win_end[dk] = idx

    # ------------------------------------------------------------------
    # Drawing (all api.Chart.* touches are isolated here)
    # ------------------------------------------------------------------
    def _draw_cbdr(self, idx: int):
        for row in self.tracker.iter_rows():
            key = "cbdr_%s" % row.day_key
            if row.closed_within:
                # Closed day: draw once.
                if key in self._drawn:
                    continue
                self._drawn.add(key)
            # Active (in-window) day: redraw each bar so the body grows.

            start_idx = self._win_start.get(row.day_key, idx)
            end_idx = self._win_end.get(row.day_key, idx)
            # Right edge = end_idx + 1: the last in-window bar only OPENS at
            # end_idx, so anchoring there leaves its final slot (e.g.
            # 00:45->01:00) unpainted and the box visually stops short of the
            # window end. One extra bar index paints the full window slot
            # (always valid: only CLOSED bars are fed, so end_idx+1 <= Count-1).
            end_r = end_idx + 1
            rect = api.Chart.DrawRectangle(
                key, start_idx, row.body_high, end_r, row.body_low, CBDR_BODY_COLOR
            )
            rect.IsFilled = True
            api.Chart.DrawText(
                key + "_w", "%.4f%%" % row.width_pct, end_r, row.body_high, TEXT_COLOR
            )

            # Sweep markers (purple arrows).
            if row.swept_up:
                api.Chart.DrawIcon(
                    key + "_swU", ChartIconType.UpArrow, end_idx, row.body_high, SWEEP_COLOR
                )
            if row.swept_down:
                api.Chart.DrawIcon(
                    key + "_swD",
                    ChartIconType.DownArrow,
                    end_idx,
                    row.body_low,
                    SWEEP_COLOR,
                )

    def _draw_fvg(self, idx: int):
        if len(self._recent) < 3:
            return
        hit = detect_fvg_on(list(self._recent), Direction.NEUTRAL)
        if hit is None:
            return
        key = "fvg_%s" % hit.index
        if key in self._drawn:
            return
        self._drawn.add(key)
        color = FVG_BULL_COLOR if hit.direction == Direction.BULLISH else FVG_BEAR_COLOR
        rect = api.Chart.DrawRectangle(key, idx - 2, hit.fvg_high, idx, hit.fvg_low, color)
        rect.IsFilled = True

    def _draw_panel(self):
        rows = list(self.tracker.iter_rows())
        latest = rows[0] if rows else None
        lines = [
            "CBDR Calibration | %s | %s" % (api.SymbolName, api.TimeFrame.Name),
            "Window %04d-%04d | ATR %d | tol %.3f"
            % (
                self.cfg.span_start_hhmm,
                self.cfg.span_end_hhmm,
                self.cfg.atr_period,
                self.cfg.sweep_atr_tolerance_mult,
            ),
        ]
        if latest:
            lines.append(
                "Latest %s: width %.4f%% | swU=%s swD=%s"
                % (latest.day_key, latest.width_pct, latest.swept_up, latest.swept_down)
            )
        lines.append("Legend: blue=CBDR body | orange=bull FVG | pink=bear FVG | magenta=sweep")
        api.Chart.DrawStaticText(
            "panel", "\n".join(lines), VerticalAlignment.Top, HorizontalAlignment.Left, TEXT_COLOR
        )
