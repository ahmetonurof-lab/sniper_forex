#!/usr/bin/env python
"""Live strategy runtime — ports run_test_a entry/SL/TP core.

PHASE 3 — STRATEGY RUNTIME.

Chain per closed 15m bar:
    SessionManager -> CBDR -> Sweep -> Bias -> FVG -> EQ -> First FVG
    -> First Touch -> Signal.

Reuses `SessionManager` (src/strategy/session.py) and `apply_trailing` /
`check_exit` (experiment/trailing_adapter.py) directly. Ports the entry/SL/TP
core from `run_test_a` (copy-adapt; the frozen engine is NOT modified).

This is the C2 (POST_SWEEP_FVG) engine behavior. Per-symbol state is isolated
(one StrategyRuntime per symbol). Deterministic replay parity is the goal.
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

_LOG = logging.getLogger(__name__)

# ── Reuse config (same constants as frozen engine) ──
from experiment.config import (  # noqa: E402
    ATR_PERIOD,
    FVG_BUFFER_MIN_FACTOR,
    FVG_BUFFER_MULT,
    FVG_MIN_SIZE_ATR_MULT,
    FVG_WICK_RATIO_MAX,
    MIN_RISK_DIST_ATR_MULT,
    SESSION_END_HOUR,
    SESSION_START_HOUR,
    SL_ATR_MULT,
    TP_RR,
)

# ── Reuse trailing adapter (apply_trailing + check_exit) ──
from experiment.trailing_adapter import (  # noqa: E402
    _norm_side,
    apply_trailing,
    check_exit,
)
from src.live.audit import AuditChain, EventType  # N2 #23 R-1 (observation layer)
from src.strategy.models import Bar, Direction, SweepEvent
from src.strategy.session import SessionManager

# ── Nexus FVG (external dependency, same as frozen engine) ──
_NEXUS_SNIPER_SRC = str(Path("C:/Users/Administrator/Desktop/nexus-mcp/sniper/src"))
if _NEXUS_SNIPER_SRC not in sys.path:
    sys.path.insert(0, _NEXUS_SNIPER_SRC)

from fvg import detect_fvgs as _nexus_detect_fvgs  # noqa: E402
from models import Bar as NexusBar  # noqa: E402


@dataclass
class Signal:
    """Entry signal produced by the runtime (consumed by risk/execution)."""

    symbol: str
    direction: str  # "bullish" / "bearish"
    side: str  # "long" / "short"
    entry_price: float
    sl: float
    tp: float
    entry_bar_index: int
    sweep_bar_index: int
    zone_index: int
    zone_top: float
    zone_bottom: float
    zone_size: float
    timestamp: pd.Timestamp


def signal_audit_payload(sig: Signal) -> Dict[str, Any]:
    """N2 #23 R-3: SIGNAL audit payload builder (schema test ile sabit).

    Şema (pre-reg ``results/N2_23_prereg_R3_R1.md`` v1.1 + Hakem AM-v1.1
    FVG-id; N2 #23-b AM-N23-3 genişlemesi): ``symbol/side/entry/sl/tp/
    reason/ts + fvg_id + fvg_top/fvg_bottom/fvg_size_pip/direction`` —
    KAPALI set (12 alan; fvg_id trace-bağı korunur, ölçüler id-yanda).

    Pure: I/O yok, audit-bağımlılığı yok. Emit noktası (LiveRunner.on_bar,
    runtime-signal-dönüşünün canlı tüketim noktası) adım-2'de bu builder'ı
    çağırır; şema testi (test_n2_23_emit_schema) bu sözleşmeyi sabitler.
    """
    return {
        "symbol": sig.symbol,
        "side": sig.side,
        "entry": sig.entry_price,
        "sl": sig.sl,
        "tp": sig.tp,
        "reason": "cbdr_sweep_fvg_fill",
        "ts": sig.timestamp.isoformat(),
        "fvg_id": f"{sig.symbol}:zone{sig.zone_index}",
        # N2 #23-b AM-N23-3: insan-okunur fvg-ölçüleri (id-yanda; trace-bağı
        # korunur). fvg_size_pip: sembol-pip-boyutuna normalize ölçü.
        "fvg_top": sig.zone_top,
        "fvg_bottom": sig.zone_bottom,
        "fvg_size_pip": sig.zone_size / _pip_size(sig.symbol),
        "direction": sig.direction,
    }


def _pip_size(symbol: str) -> float:
    """Pip-boyutu (N2 #23-b AM-N23-3): JPY-quote çifti 0.01, aksi 0.0001.

    Pure yardımcı: majörler + sentetik-test sembolleri. JPY olmayan her
    sembol (``TEST`` dahil) standart 0.0001 pip alır.
    """
    return 0.01 if symbol.upper().endswith("JPY") else 0.0001


def _to_nexus_bar(bar: Bar) -> NexusBar:
    """Convert sniper_forex Bar to NEXUS Bar format (parity with engine)."""
    return NexusBar(
        index=bar.index,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        is_closed=True,
        timestamp=int(bar.timestamp.timestamp() * 1000)
        if hasattr(bar.timestamp, "timestamp")
        else 0,
    )


def _is_fresh_fvg(fvg, bars_15m: List[Bar], current_index: int) -> bool:
    """Strict freshness check for FVG (parity with engine)."""
    scan_from = fvg.real_index + 2
    for b in bars_15m[scan_from:current_index]:
        if fvg.direction == "bullish":
            if b.low <= fvg.top:
                return False
        else:
            if b.high >= fvg.bottom:
                return False
    return True


def _compute_atr(bars: List[Bar], period: int = 14) -> float:
    """ATR over the last `period` bars (parity with engine compute_atr)."""
    if len(bars) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(bars)):
        bar = bars[i]
        prev = bars[i - 1]
        tr = max(
            bar.high - bar.low,
            abs(bar.high - prev.close),
            abs(bar.low - prev.close),
        )
        trs.append(tr)
    if len(trs) < period:
        return 0.0
    import numpy as np

    return float(np.mean(trs[-period:]))


class StrategyRuntime:
    """Per-symbol live strategy runtime (C2 POST_SWEEP_FVG port).

    One instance per symbol (6 majors isolation). Feed closed 15m bars via
    `on_bar()`. State is recoverable via `to_state()` / `from_state()`.
    """

    def __init__(self, symbol: str, audit: Optional[AuditChain] = None):
        self.symbol = symbol
        self.session = SessionManager(
            symbol=symbol,
            start_hour=SESSION_START_HOUR,
            end_hour=SESSION_END_HOUR,
            atr=0.0,
            sweep_atr_tolerance_mult=0.5,
            sweep_default_tolerance=10.0,
        )
        self.atr_val = 0.0
        self.sweep_detected = False
        self.last_sweep: Optional[SweepEvent] = None
        self.active_trade: Optional[dict] = None
        self.pending_entry: Optional[dict] = None  # touch detected, awaiting fill
        self._last_signal: Optional[Signal] = None
        self.trade_counter = 0
        self.trades: List[dict] = []  # completed trade records
        self.bars: List[Bar] = []  # all 15m bars seen
        self.nexus_bars_full: List[NexusBar] = []
        self._next_idx = 0
        self._start_idx = 0
        self._warmed = False
        # N2 #23 R-1: CBDR STATE emit observation state. The audit sink is
        # injected (LiveRunner/orchestrator); None -> emits disabled (zero
        # behavior change for all existing callers/tests). Timestamps are
        # LIVE-OBSERVED transition stamps — NOT persisted via to_state (no
        # second source of truth): after a restart they read None until the
        # next sweep/cycle, an honest gap, never a silent fake.
        self.audit: Optional[AuditChain] = None
        self._last_in_window: Optional[bool] = None
        self._sweep_ts: Optional[str] = None
        self._bias_lock_ts: Optional[str] = None
        if audit is not None:
            self.audit = audit

    def _emit_state(
        self,
        moment: str,
        bar: Bar,
        *,
        in_window: bool,
        sweep_tol: Optional[float],
    ) -> None:
        """N2 #23 R-1: single STATE-type emit at CBDR transition moments.

        Pre-reg payload: pencere-in/out · locked · sweep{level,direction,
        tolerans} · bias + AM-N23-1 d4 alanları (sweep_yes, bias_lock_ts,
        sweep_ts), S9-startup-payload-şemasıyla sayı-uyumlu. Observation
        layer ONLY: session.py body untouched; strategy flow unaffected
        (emit failures are logged, never raised).
        """
        if self.audit is None:
            return
        c = self.session.cbdr
        try:
            self.audit.append(
                time.time(),
                EventType.STATE,
                self.symbol,
                {
                    "moment": moment,
                    "in_window": bool(in_window),
                    "locked": bool(c.locked),
                    "bias_locked": bool(c.bias_locked),
                    "sweep_yes": bool(c.sweep_confirmed),
                    "sweep_direction": (c.sweep_direction.value if c.sweep_direction else None),
                    "sweep_level": c.sweep_level,
                    "sweep_tol": sweep_tol,
                    "sweep_ts": self._sweep_ts,
                    "bias_lock_ts": self._bias_lock_ts,
                    "bias": c.daily_bias.value,
                    "body_high": c.body_high,
                    "body_low": c.body_low,
                    "session_key": self.session.current_cbdr_key,
                    "bar_ts": bar.timestamp.isoformat(),
                    "bar_index": int(bar.index),
                },
            )
        except Exception:
            _LOG.warning("N2 #23 R-1: CBDR STATE emit failed", exc_info=True)

    def _emit_fvg_armed(self, fvg, i: int) -> None:
        """N2 #23-b: STATE emit at the FVG arm moment (pending entry created).

        R-1 deseninin ikinci momenti: sweep-onay-STATE'i ile SIGNAL arasında
        motor arm-fazındayken SESSİZ kalıyordu (t10d-boot canlı-gözlemi:
        boot-sonrası 0 STATE). Arm anında tek STATE satırı yazılır.
        Observation layer ONLY: session.py body untouched; strategy flow
        unaffected (emit failures are logged, never raised). Payload
        AM-N23-3 dilini kullanır (fvg-ölçüleri + direction + bar_ts).
        Ts-disiplini AM-N23-2: satır-ts=emit-anı (audit epoch), bar_ts=
        içerik-momenti (touch bar) — ikili ayrık-by-design.
        """
        if self.audit is None or self.last_sweep is None:
            return
        try:
            self.audit.append(
                time.time(),
                EventType.STATE,
                self.symbol,
                {
                    "moment": "fvg_armed",
                    "fvg_top": float(fvg.top),
                    "fvg_bottom": float(fvg.bottom),
                    "fvg_size_pip": float(fvg.size) / _pip_size(self.symbol),
                    "direction": fvg.direction,
                    "sweep_bar_index": int(self.last_sweep.bar_index),
                    "sweep_price": float(self.last_sweep.sweep_price),
                    "touch_bar_index": int(i),
                    "entry_bar_index": int(i + 1),
                    "sl_pre": float(self.pending_entry["sl"]) if self.pending_entry else None,
                    "bar_ts": self.bars[i].timestamp.isoformat(),
                    "bar_index": int(i),
                },
            )
        except Exception:
            _LOG.warning("N2 #23-b: fvg_armed STATE emit failed", exc_info=True)

    # -- Warmup -----------------------------------------------------------
    def warmup(self, bars_15m: List[Bar]) -> None:
        """Initialize ATR + session from historical 15m bars.

        Mirrors run_test_a: warmup = min(100, len-10); start_idx = warmup+1.
        Stores bars 0..warmup so `on_bar` can append from start_idx onward
        without gaps (parity with the engine's full-bar-list access).
        """
        if len(bars_15m) < 100:
            return
        warmup = min(100, len(bars_15m) - 10)
        self.atr_val = _compute_atr(bars_15m[:warmup], period=ATR_PERIOD)
        if self.atr_val <= 0:
            return
        self.session.atr = self.atr_val
        self.bars = list(bars_15m[: warmup + 1])
        self.nexus_bars_full = [_to_nexus_bar(b) for b in bars_15m[: warmup + 1]]
        self._start_idx = warmup + 1
        self._next_idx = self._start_idx
        self._warmed = True

    # -- Per-bar processing ------------------------------------------------
    def on_bar(self, bar: Bar) -> Optional[Signal]:
        """Process one closed 15m bar. Returns a Signal when an entry fills.

        Faithfully replicates run_test_a's per-bar loop body for index `i`.
        """
        if not self._warmed:
            return None
        i = self._next_idx
        # Ensure bar.index matches its position (parity with engine loop).
        bar = Bar(
            index=i,
            timestamp=bar.timestamp,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )
        self.bars.append(bar)
        self.nexus_bars_full.append(_to_nexus_bar(bar))

        # Update ATR (only for i > start_idx, parity with engine)
        if i > self._start_idx:
            prev_close = self.bars[i - 1].close
            tr = max(
                bar.high - bar.low,
                abs(bar.high - prev_close),
                abs(bar.low - prev_close),
            )
            self.atr_val = (self.atr_val * (ATR_PERIOD - 1) + tr) / ATR_PERIOD

        # Fill any pending entry at this bar's open (parity: entry at i+1 open)
        if self.pending_entry is not None:
            filled = self._fill_pending(bar)
            if filled:
                # Canonical processes the ENTRY bar immediately: apply_trailing
                # then check_exit run on the bar the trade fills (i). Without
                # this, a trade that trails+exits on its own entry bar is missed
                # (parity divergence).
                if self.active_trade is not None:
                    apply_trailing(
                        self.bars[max(0, i - 500) : i + 1],
                        [self.active_trade],
                        self.atr_val,
                        self.symbol,
                    )
                    exit_info = check_exit(bar, self.active_trade)
                    if exit_info is not None:
                        self._close_trade(exit_info, i, bar)
                self._next_idx = i + 1
                return self._last_signal
            # MIN_RISK_DIST rejection: pending cleared, sweep preserved. Fall
            # through to sweep detection + FVG scan on this bar (canonical
            # continues scanning with the same sweep after a failed FVG).
            # self.pending_entry is now None; continue below.

        # -- Active trade management --
        if self.active_trade is not None:
            apply_trailing(
                self.bars[max(0, i - 500) : i + 1],
                [self.active_trade],
                self.atr_val,
                self.symbol,
            )
            exit_info = check_exit(bar, self.active_trade)
            if exit_info is not None:
                self._close_trade(exit_info, i, bar)
                self._next_idx = i + 1
                return None
            self.active_trade["max_price"] = max(
                self.active_trade.get("max_price", bar.high), bar.high
            )
            self.active_trade["min_price"] = min(
                self.active_trade.get("min_price", bar.low), bar.low
            )
            self._next_idx = i + 1
            return None

        # ── N2 #23 R-1: CBDR lifecycle observation (consume-point emits) ──
        # The four silent session.py moments (window in/out, lock, sweep
        # accept, bias lock) become visible HERE, at the runtime consumption
        # point — session.py body untouched (pre-reg katman-ayrımı).
        _dt = bar.timestamp.to_pydatetime()
        _in_w = self.session.in_window(_dt)
        _pre_locked = self.session.cbdr.locked
        _pre_sweep_confirmed = self.session.cbdr.sweep_confirmed
        _sweep_tol = (
            self.session.atr * self.session.sweep_atr_tolerance_mult
            if self.session.atr > 0
            else self.session.sweep_default_tolerance
        )

        # -- Sweep detection --
        sweep = self.session.update(bar)
        if sweep is not None:
            self.sweep_detected = True
            self.last_sweep = sweep
            # AM-N23-1: canlı-gözlem mühürleri — sweep kabul + bias kilit
            # aynı barda (session._confirm_sweep ikisini birden kurar).
            self._sweep_ts = bar.timestamp.isoformat()
            self._bias_lock_ts = bar.timestamp.isoformat()

        _post = self.session.cbdr
        if self._last_in_window is not None and _in_w != self._last_in_window:
            if _in_w:
                self._emit_state("window_in", bar, in_window=_in_w, sweep_tol=_sweep_tol)
            else:
                self._emit_state("window_out", bar, in_window=_in_w, sweep_tol=_sweep_tol)
        self._last_in_window = _in_w
        if _post.locked and not _pre_locked:
            self._emit_state("locked", bar, in_window=_in_w, sweep_tol=_sweep_tol)
        if sweep is not None:
            self._emit_state("sweep", bar, in_window=_in_w, sweep_tol=sweep.tolerance)
        elif _pre_sweep_confirmed and not _post.sweep_confirmed:
            # yeni-çevrim-reseti (session.update içi) — gözlem-tarihleri sıfırla
            self._sweep_ts = None
            self._bias_lock_ts = None
            self._emit_state("cycle_reset", bar, in_window=_in_w, sweep_tol=_sweep_tol)

        if not self.sweep_detected or self.last_sweep is None:
            self._next_idx = i + 1
            return None

        sweep_direction = "bullish" if self.last_sweep.direction == Direction.BULLISH else "bearish"
        lb = min(100, i + 1)
        nexus_bars = self.nexus_bars_full[i + 1 - lb : i + 1]

        min_fvg_size = max(self.atr_val * FVG_MIN_SIZE_ATR_MULT, 1e-8)
        fvgs = _nexus_detect_fvgs(
            nexus_bars,
            lookback=lb,
            timeframe="15m",
            min_fvg_size=min_fvg_size,
            max_wick_ratio=FVG_WICK_RATIO_MAX,
        )

        for fvg in fvgs:
            if fvg.real_index <= self.last_sweep.bar_index:
                continue
            if fvg.direction != sweep_direction:
                continue
            if fvg.invalidated:
                continue
            if not _is_fresh_fvg(fvg, self.bars, i):
                continue
            if i <= self.last_sweep.bar_index:
                continue

            window = self.bars[self.last_sweep.bar_index : i + 1]
            if not window:
                continue
            leg_high = max(b.high for b in window)
            leg_low = min(b.low for b in window)
            leg_mid = (leg_high + leg_low) / 2.0
            eq = (self.last_sweep.sweep_price + leg_mid) / 2.0

            # C2 EQ filter: entire FVG on correct side of EQ
            if self.last_sweep.direction == Direction.BULLISH:
                if fvg.top > eq:
                    continue
            else:
                if fvg.bottom < eq:
                    continue

            # First-touch entry check
            if fvg.direction == "bullish":
                if not (bar.low <= fvg.top and bar.low >= fvg.bottom - self.atr_val * 0.1):
                    continue
            else:
                if not (bar.high >= fvg.bottom and bar.high <= fvg.top + self.atr_val * 0.1):
                    continue

            # NEXUS parity: next-bar-open execution. In live, the next bar's
            # open is not known yet, so we store a pending entry and fill it
            # when the next bar arrives (signal emitted at fill).
            #
            # NOTE: the sweep is NOT reset here. Canonical only clears the
            # sweep once a trade is actually created (after MIN_RISK_DIST
            # passes). If the pending is later rejected at fill (MIN_RISK_DIST
            # failure), the sweep must survive so scanning continues with the
            # same sweep — matching canonical's continue-on-failure behavior.
            self._create_pending(fvg, i)
            self._next_idx = i + 1
            return None  # signal emitted at fill (next bar)

        self._next_idx = i + 1
        return None

    # -- Pending entry -----------------------------------------------------
    def _create_pending(self, fvg, i: int) -> None:
        """Compute SL/TP at touch bar `i`; store pending entry (no entry_price)."""
        fh = fvg.top - fvg.bottom
        rp2 = self.atr_val * SL_ATR_MULT
        if fvg.direction == "bullish":
            ab = (
                max(
                    fh * FVG_BUFFER_MIN_FACTOR,
                    max(rp2 * 0.1, min(fh * 0.25, rp2 * FVG_BUFFER_MULT)),
                )
                if fh > 0
                else rp2 * 2
            )
            sl = fvg.bottom - ab if fh > 0 else 0.0  # entry_price unknown yet
        else:
            ab = (
                max(
                    fh * FVG_BUFFER_MIN_FACTOR,
                    max(rp2 * 0.1, min(fh * 0.25, rp2 * FVG_BUFFER_MULT)),
                )
                if fh > 0
                else rp2 * 2
            )
            sl = fvg.top + ab if fh > 0 else 0.0

        self.pending_entry = {
            "fvg": fvg,
            "touch_bar_index": i,
            "entry_bar_index": i + 1,
            "sweep_bar_index": self.last_sweep.bar_index,
            "sweep_price": self.last_sweep.sweep_price,
            "reference_level": self.last_sweep.reference_level,
            "sl": sl,
            "rp2": rp2,
            "fh": fh,
            "direction": fvg.direction,
        }
        # N2 #23-b: FVG-arm anı emit — sweep-onay-STATE'i ile SIGNAL
        # arasındaki sessizlik-delik kapanır (pre-reg: observation-layer,
        # akış-değişmez; emit fail=logged never raised).
        self._emit_fvg_armed(fvg, i)

    def _fill_pending(self, bar: Bar) -> bool:
        """Fill pending entry at `bar.open`; create active_trade + Signal.

        Returns True if a trade was created, False if the pending was rejected
        (MIN_RISK_DIST failure) — in which case the sweep is preserved so the
        caller can re-scan FVGs with the same sweep.
        """
        p = self.pending_entry
        fvg = p["fvg"]
        entry_price = bar.open
        sl = p["sl"]
        rp2 = p["rp2"]
        fh = p["fh"]
        direction = p["direction"]

        if fh <= 0:
            sl = entry_price - rp2 * 2 if direction == "bullish" else entry_price + rp2 * 2

        rd = abs(entry_price - sl)
        if rd <= 0:
            sl = entry_price - rp2 * 2 if direction == "bullish" else entry_price + rp2 * 2
            rd = abs(entry_price - sl)
        tp = entry_price + rd * TP_RR if direction == "bullish" else entry_price - rd * TP_RR

        if rd < self.atr_val * MIN_RISK_DIST_ATR_MULT:
            # MIN_RISK_DIST failure: reject this pending but KEEP the sweep so
            # scanning continues with the same sweep (canonical parity). The
            # caller falls through to re-scan on the current bar.
            self.pending_entry = None
            self._last_signal = None
            return False

        # Trade created -> clear the sweep (canonical resets it here).
        self.sweep_detected = False
        self.last_sweep = None

        self.trade_counter += 1
        self.active_trade = {
            "trade_id": self.trade_counter,
            "side": _norm_side(direction),
            "direction": direction,
            "entry_price": entry_price,
            "sl": sl,
            "tp": tp,
            "initial_sl": sl,
            "initial_tp": tp,
            "entry_bar": p["entry_bar_index"],
            "sweep_bar_index": p["sweep_bar_index"],
            "zone_index": fvg.real_index,
            "zone_creation_bar": fvg.real_index,
            "zone_top": fvg.top,
            "zone_bottom": fvg.bottom,
            "zone_size": fvg.size,
            "zone_size_atr": fvg.size / self.atr_val if self.atr_val > 0 else 0,
            "sweep_size_atr": abs(p["sweep_price"] - p["reference_level"]) / self.atr_val
            if self.atr_val > 0
            else 0,
            "bars_sweep_to_zone": fvg.real_index - p["sweep_bar_index"],
            "bars_zone_to_entry": p["touch_bar_index"] - fvg.real_index,
            "trailing_count": 0,
            "max_price": entry_price,
            "min_price": entry_price,
            "closed": False,
        }
        self._last_signal = Signal(
            symbol=self.symbol,
            direction=direction,
            side=_norm_side(direction),
            entry_price=entry_price,
            sl=sl,
            tp=tp,
            entry_bar_index=p["entry_bar_index"],
            sweep_bar_index=p["sweep_bar_index"],
            zone_index=fvg.real_index,
            zone_top=fvg.top,
            zone_bottom=fvg.bottom,
            zone_size=fvg.size,
            timestamp=bar.timestamp,
        )
        self.pending_entry = None
        return True

    # -- Trade close ------------------------------------------------------
    def _close_trade(self, exit_info: dict, i: int, bar: Bar) -> None:
        """Close active trade, record result (parity with engine)."""
        exit_price = exit_info["exit_price"]
        result = exit_info["result"]
        t = self.active_trade
        if _norm_side(t["side"]) == "long":
            pnl_r = (exit_price - t["entry_price"]) / abs(t["entry_price"] - t["initial_sl"])
        else:
            pnl_r = (t["entry_price"] - exit_price) / abs(t["sl"] - t["entry_price"])
        if result == "LOSS":
            pnl_r = -1.0
        t["exit_price"] = exit_price
        t["exit_bar_index"] = i
        t["exit_timestamp"] = bar.timestamp
        t["result"] = result
        t["pnl_r"] = pnl_r
        t["closed"] = True
        self.trades.append(t)
        self.active_trade = None

    # -- State persistence (restart recovery) ------------------------------
    def to_state(self) -> dict:
        """Serialize recoverable runtime state (for state.py persistence)."""
        return {
            "symbol": self.symbol,
            "atr_val": self.atr_val,
            "session_atr": self.session.atr,
            "sweep_detected": self.sweep_detected,
            "last_sweep": (
                {
                    "symbol": self.last_sweep.symbol,
                    "timestamp": str(self.last_sweep.timestamp),
                    "direction": self.last_sweep.direction.value,
                    "sweep_price": self.last_sweep.sweep_price,
                    "reference_level": self.last_sweep.reference_level,
                    "sweep_index": self.last_sweep.sweep_index,
                    "bar_index": self.last_sweep.bar_index,
                    "tolerance": self.last_sweep.tolerance,
                }
                if self.last_sweep
                else None
            ),
            "active_trade": self.active_trade,
            "pending_entry": self.pending_entry,
            "trade_counter": self.trade_counter,
            "trades": self.trades,
            "_next_idx": self._next_idx,
            "_start_idx": self._start_idx,
            "_warmed": self._warmed,
            "session": {
                "body_high": self.session.cbdr.body_high,
                "body_low": self.session.cbdr.body_low,
                "locked": self.session.cbdr.locked,
                "bias_locked": self.session.cbdr.bias_locked,
                "sweep_confirmed": self.session.cbdr.sweep_confirmed,
                "sweep_direction": (
                    self.session.cbdr.sweep_direction.value
                    if self.session.cbdr.sweep_direction
                    else None
                ),
                "sweep_level": self.session.cbdr.sweep_level,
                "sweep_index": self.session.cbdr.sweep_index,
                "daily_bias": self.session.cbdr.daily_bias.value,
                "current_cbdr_key": self.session.current_cbdr_key,
            },
        }

    def from_state(self, state: dict) -> None:
        """Restore runtime state from a serialized dict."""
        self.symbol = state["symbol"]
        self.atr_val = state["atr_val"]
        # R1/R2: restore session.atr (sweep tolerance source). Fallback for
        # state files persisted before N2 #14 (no "session_atr" key) is
        # audited — never silent (§ contract: no silent fallback).
        if "session_atr" in state:
            self.session.atr = state["session_atr"]
        else:
            _LOG.warning(
                "R1/R2: 'session_atr' missing from persisted state "
                "(pre-N2#14 format); audited fallback session.atr = atr_val "
                "= %s for %s",
                self.atr_val,
                self.symbol,
            )
            self.session.atr = self.atr_val
        self.sweep_detected = state["sweep_detected"]
        ls = state.get("last_sweep")
        self.last_sweep = (
            SweepEvent(
                symbol=ls["symbol"],
                timestamp=pd.Timestamp(ls["timestamp"]),
                direction=Direction(ls["direction"]),
                sweep_price=ls["sweep_price"],
                reference_level=ls["reference_level"],
                sweep_index=ls["sweep_index"],
                bar_index=ls["bar_index"],
                tolerance=ls["tolerance"],
            )
            if ls
            else None
        )
        self.active_trade = state.get("active_trade")
        self.pending_entry = state.get("pending_entry")
        self.trade_counter = state["trade_counter"]
        self.trades = state.get("trades", [])
        self._next_idx = state["_next_idx"]
        self._start_idx = state["_start_idx"]
        self._warmed = state["_warmed"]
        s = state["session"]
        self.session.cbdr.body_high = s["body_high"]
        self.session.cbdr.body_low = s["body_low"]
        self.session.cbdr.locked = s["locked"]
        self.session.cbdr.bias_locked = s["bias_locked"]
        self.session.cbdr.sweep_confirmed = s["sweep_confirmed"]
        self.session.cbdr.sweep_direction = (
            Direction(s["sweep_direction"]) if s["sweep_direction"] else None
        )
        self.session.cbdr.sweep_level = s["sweep_level"]
        self.session.cbdr.sweep_index = s["sweep_index"]
        self.session.cbdr.daily_bias = Direction(s["daily_bias"])
        self.session.current_cbdr_key = s["current_cbdr_key"]
