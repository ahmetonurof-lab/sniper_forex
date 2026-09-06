#!/usr/bin/env python
"""D129 B.1 — CONSOLE REPORTER (multi-symbol human-readable status).

Pattern 4 — crypto'daki ``console_reporter.py``'nin forex karşılığı.

Amaç: İnsan operatörün o an ne olduğunu tek bakışta görmesi. Multi-symbol
destekli, sembol bazlı dedup'lu satırlar:

    [SESSION] EURUSD LONDON 15:15 UTC CBDR: BODY TRACKING...
    [SWEEP] EURUSD SWEEP: DETECTED | BULLISH | [1.08420]
    [FVG] EURUSD GAP_SCAN | MIN_SIZE: 0.00042 | ARANIYOR...
    [POSITION] EURUSD LONG @ 1.08450 SL=1.08410 TP=1.08650 TRAIL: 2x UPNL: +8.20

Sembol bazlı prefix ayrımı — karışma YOK. Her sembol kendi bloğunda.

Tasarım notları (AGENTS.md §2.2 — prefer existing mechanisms):
- Dedup/separator/timestamp çekirdeği crypto ``console_reporter.py``'den
  birebir taşındı (kanıtlanmış pattern, yeniden icat değil).
- ``report_*`` metodları duck-typed: gerçek forex nesnelerini
  (``CBDRState``, ``SweepEvent``, ``FVG``, ``Position``) ``getattr`` ile
  okur; eksik alanlarda zarifçe degrade olur. Böylece hem gerçek runtime
  hem test double'ları ile çalışır.
- Zaman damgası UTC (D129 örnekleri "15:15 UTC" — forex tarafı UTC
  konvansiyonu, AGENTS.md §6.3).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any, Optional, TextIO


class ConsoleReporter:
    """Konsol çıktı formatlaması + state-based dedup (multi-symbol).

    Crypto'daki ``ConsoleReporter``'ın forex karşılığı. Aynı (symbol, key)
    için tekrarlayan mesajları bastırır; sembol değiştiğinde separator
    basar; UTC zaman damgası ekler.
    """

    def __init__(self, out: Optional[TextIO] = None) -> None:
        self._out: TextIO = out if out is not None else sys.stdout
        self._log_state: dict[str, dict[str, str]] = {}
        self._prev_print_sym: Optional[str] = None

    # ── Çekirdek (crypto pattern) ──────────────────────────────
    def emit(self, sym: str, key: str, msg: str, force: bool = False) -> None:
        """Sembol bazlı dedup'lu satır bas.

        Args:
            sym: Sembol adı (örn: "EURUSD") veya "SYSTEM"
            key: Durum anahtarı (dedup için)
            msg: Yazdırılacak mesaj
            force: True ise dedup'u atla, her zaman yazdır
        """
        prev = self._log_state.get(sym, {}).get(key)
        if not force and prev == msg:
            return
        self._log_state.setdefault(sym, {})[key] = msg
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        separator = "" if self._prev_print_sym == sym else "\n"
        self._prev_print_sym = sym
        print(f"{separator}[{ts}] [{sym:<12}] {msg}", file=self._out, flush=True)

    def clear_state(self, sym: str, key: str) -> None:
        """Belirli bir state anahtarını temizle (zorla yeniden yazdırmak için)."""
        self._log_state.get(sym, {}).pop(key, None)

    # ── D129 B.1 report_* API ──────────────────────────────────
    def report_state(self, symbol: str, state: Any) -> None:
        """CBDR/session durumunu raporla (duck-typed ``CBDRState``).

        Beklenen alanlar (getattr, eksikse zarif degrade):
          session (str), hour/minute (int), cbdr_locked/locked (bool),
          daily_bias (Direction|str), body_high/body_low (float).
        """
        session = getattr(state, "session", "") or ""
        hour = getattr(state, "hour", None)
        minute = getattr(state, "minute", None)
        ts = f"{int(hour):02d}:{int(minute):02d}" if hour is not None and minute is not None else ""
        locked = bool(getattr(state, "cbdr_locked", getattr(state, "locked", False)))
        cbdr_s = "LOCKED" if locked else "BODY TRACKING..."
        bias = getattr(state, "daily_bias", None)
        bias_str = ""
        if bias is not None:
            b = bias.value if hasattr(bias, "value") else str(bias)
            if b.lower() not in ("neutral", "none", ""):
                bias_str = f" | BIAS: {b.upper()}"
        msg = f"SESSION: {session} {ts} UTC CBDR: {cbdr_s}{bias_str}".strip()
        self.emit(symbol, "st_ses", msg, force=True)

    def report_sweep(self, symbol: str, sweep: Any) -> None:
        """Sweep tespitini raporla (duck-typed ``SweepEvent``).

        Beklenen alanlar: direction (Direction|str), sweep_price (float).
        """
        direction = getattr(sweep, "direction", None)
        d = direction.value if hasattr(direction, "value") else str(direction or "")
        price = getattr(sweep, "sweep_price", None)
        price_s = f" [{price:.5f}]" if price is not None else ""
        msg = f"SWEEP: DETECTED | {d.upper()}{price_s}"
        self.emit(symbol, "st_sweep", msg, force=True)

    def report_fvg(self, symbol: str, fvg: Any) -> None:
        """FVG tarama/tespit durumunu raporla (duck-typed ``FVG``).

        Beklenen alanlar: fvg_high/fvg_low (float), fvg_size (float),
        direction (Direction|str).
        """
        direction = getattr(fvg, "direction", None)
        d = direction.value if hasattr(direction, "value") else str(direction or "")
        high = getattr(fvg, "fvg_high", None)
        low = getattr(fvg, "fvg_low", None)
        size = getattr(fvg, "fvg_size", None)
        if high is not None and low is not None:
            bounds = f" {d.upper()} {high:.5f}-{low:.5f}"
        else:
            bounds = ""
        size_s = f" | SIZE: {size:.6f}" if size is not None else ""
        msg = f"GAP_SCAN | MIN_SIZE: {size_s} | FVG{bounds}".replace(" | MIN_SIZE:  |", " |")
        self.emit(symbol, "st_fvg", msg, force=True)

    def report_position(self, symbol: str, pos: Any) -> None:
        """Açık pozisyon durumunu raporla (duck-typed ``Position``).

        Beklenen alanlar: side ("long"/"short"), entry_price, sl, tp,
        trailing_count (int), profit (float).
        """
        side = getattr(pos, "side", "")
        side_s = side.upper() if isinstance(side, str) else str(side)
        entry = getattr(pos, "entry_price", None)
        sl = getattr(pos, "sl", None)
        tp = getattr(pos, "tp", None)
        trail = getattr(pos, "trailing_count", 0)
        profit = getattr(pos, "profit", None)
        entry_s = f" @ {entry:.5f}" if entry is not None else ""
        sl_s = f" SL={sl:.5f}" if sl is not None else ""
        tp_s = f" TP={tp:.5f}" if tp is not None else ""
        trail_s = f" TRAIL: {int(trail)}x" if trail else ""
        upnl_s = f" UPNL: {profit:+.2f}" if profit is not None else ""
        msg = f"{side_s}{entry_s}{sl_s}{tp_s}{trail_s}{upnl_s}"
        self.emit(symbol, "st_pos", msg, force=True)
