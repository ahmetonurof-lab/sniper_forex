#!/usr/bin/env python
"""D129 B.1 — ConsoleReporter tests.

Multi-symbol dedup + separator + UTC timestamp + report_* duck-typed
formatting. Controlled-unit evidence (AGENTS.md §3): no network, no
broker — pure string-formatting assertions against an in-memory sink.
"""

import io
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

sys.path.insert(0, r"C:\Users\Administrator\Desktop\sniper_forex")

from src.live.console_reporter import ConsoleReporter


def _make_reporter() -> tuple[ConsoleReporter, io.StringIO]:
    sink = io.StringIO()
    return ConsoleReporter(out=sink), sink


def test_emit_dedup_same_symbol_key():
    """Aynı (sym, key) + aynı msg → ikinci basım bastırılır."""
    rep, sink = _make_reporter()
    rep.emit("EURUSD", "st_ses", "SESSION: LONDON")
    rep.emit("EURUSD", "st_ses", "SESSION: LONDON")
    lines = sink.getvalue().strip().split("\n")
    assert len(lines) == 1, f"dedup başarısız: {lines}"


def test_emit_force_bypasses_dedup():
    """force=True → dedup atlanır, her zaman basılır."""
    rep, sink = _make_reporter()
    rep.emit("EURUSD", "st_ses", "SESSION: LONDON", force=True)
    rep.emit("EURUSD", "st_ses", "SESSION: LONDON", force=True)
    lines = sink.getvalue().strip().split("\n")
    assert len(lines) == 2


def test_emit_separator_on_symbol_change():
    """Sembol değiştiğinde boş satır separator basılır."""
    rep, sink = _make_reporter()
    rep.emit("EURUSD", "k1", "msg1")
    rep.emit("GBPUSD", "k1", "msg2")
    assert "\n\n" in sink.getvalue(), "sembol değişiminde separator yok"


def test_emit_utc_timestamp():
    """Zaman damgası UTC HH:MM:SS formatında."""
    rep, sink = _make_reporter()
    rep.emit("EURUSD", "k1", "msg")
    line = sink.getvalue().strip()
    now = datetime.now(timezone.utc).strftime("%H:%M:%S")
    assert f"[{now}]" in line, f"UTC damga yok: {line}"


def test_clear_state_forces_reprint():
    """clear_state → aynı msg yeniden basılır (dedup kalkar)."""
    rep, sink = _make_reporter()
    rep.emit("EURUSD", "st_ses", "SESSION: LONDON")
    rep.clear_state("EURUSD", "st_ses")
    rep.emit("EURUSD", "st_ses", "SESSION: LONDON")
    lines = sink.getvalue().strip().split("\n")
    assert len(lines) == 2


def test_report_state_locked_with_bias():
    """report_state: LOCKED + BIAS formatı."""
    rep, sink = _make_reporter()
    state = SimpleNamespace(
        session="LONDON",
        hour=15,
        minute=15,
        cbdr_locked=True,
        daily_bias=SimpleNamespace(value="bullish"),
    )
    rep.report_state("EURUSD", state)
    line = sink.getvalue().strip()
    assert "SESSION: LONDON 15:15 UTC CBDR: LOCKED" in line
    assert "BIAS: BULLISH" in line


def test_report_state_body_tracking_no_bias():
    """report_state: BODY TRACKING + neutral bias → BIAS satırı yok."""
    rep, sink = _make_reporter()
    state = SimpleNamespace(
        session="LONDON",
        hour=15,
        minute=15,
        cbdr_locked=False,
        daily_bias=SimpleNamespace(value="neutral"),
    )
    rep.report_state("EURUSD", state)
    line = sink.getvalue().strip()
    assert "CBDR: BODY TRACKING..." in line
    assert "BIAS:" not in line


def test_report_sweep_bullish():
    """report_sweep: BULLISH + fiyat formatı."""
    rep, sink = _make_reporter()
    sweep = SimpleNamespace(
        direction=SimpleNamespace(value="bullish"),
        sweep_price=1.08420,
    )
    rep.report_sweep("EURUSD", sweep)
    line = sink.getvalue().strip()
    assert "SWEEP: DETECTED | BULLISH [1.08420]" in line


def test_report_fvg_bounds():
    """report_fvg: yön + üst/alt sınır formatı."""
    rep, sink = _make_reporter()
    fvg = SimpleNamespace(
        direction=SimpleNamespace(value="bullish"),
        fvg_high=1.08455,
        fvg_low=1.08445,
        fvg_size=0.00042,
    )
    rep.report_fvg("EURUSD", fvg)
    line = sink.getvalue().strip()
    assert "FVG BULLISH 1.08455-1.08445" in line


def test_report_position_long():
    """report_position: LONG + SL/TP/TRAIL/UPNL formatı."""
    rep, sink = _make_reporter()
    pos = SimpleNamespace(
        side="long",
        entry_price=1.08450,
        sl=1.08410,
        tp=1.08650,
        trailing_count=2,
        profit=8.20,
    )
    rep.report_position("EURUSD", pos)
    line = sink.getvalue().strip()
    assert "LONG @ 1.08450 SL=1.08410 TP=1.08650 TRAIL: 2x UPNL: +8.20" in line


def test_report_position_minimal_fields():
    """report_position: eksik alanlarda zarif degrade (crash yok)."""
    rep, sink = _make_reporter()
    pos = SimpleNamespace(side="short")
    rep.report_position("EURUSD", pos)
    line = sink.getvalue().strip()
    assert "SHORT" in line


def test_multi_symbol_no_mixing():
    """Multi-symbol: her sembol kendi satırında, karışma yok."""
    rep, sink = _make_reporter()
    rep.report_state(
        "EURUSD",
        SimpleNamespace(
            session="LONDON",
            hour=15,
            minute=15,
            cbdr_locked=True,
            daily_bias=SimpleNamespace(value="bullish"),
        ),
    )
    rep.report_state(
        "GBPUSD",
        SimpleNamespace(
            session="LONDON",
            hour=15,
            minute=15,
            cbdr_locked=False,
            daily_bias=SimpleNamespace(value="bearish"),
        ),
    )
    text = sink.getvalue()
    assert "EURUSD" in text and "GBPUSD" in text
    # Her satır tek sembol içerir (prefix ayrımı)
    for line in text.strip().split("\n"):
        if not line.strip():
            continue
        assert ("EURUSD" in line) != ("GBPUSD" in line), f"karışma: {line}"


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"PASS: {t.__name__}")
        except Exception:
            print(f"FAIL: {t.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed")
