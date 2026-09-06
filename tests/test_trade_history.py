#!/usr/bin/env python
"""D129 B.4 — trade_history.json tests.

Controlled-unit evidence (AGENTS.md §3): tempfile dir. No network/broker.
Verifies:
- new_trade_id uniqueness
- make_trade_record schema completeness
- TradeHistoryWriter append + count + read
- JSON Lines format (one JSON per line)
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, r"C:\Users\Administrator\Desktop\sniper_forex")

from src.live.trade_history import (
    TradeHistoryWriter,
    make_trade_record,
    new_trade_id,
)


def test_trade_id_unique():
    """trade_id UUID4 ve benzersiz."""
    ids = {new_trade_id() for _ in range(50)}
    assert len(ids) == 50, "UUID_collision"


def test_record_schema_keys():
    """Tüm D129 B.4 alanları mevcut."""
    rec = make_trade_record(
        symbol="EURUSD",
        direction="LONG",
        cbdr_context={
            "body_low": 1.0800,
            "body_high": 1.0820,
            "width_pct": 0.185,
            "bias": "BULLISH",
        },
        entry_time="2026-09-06T10:00:00+00:00",
        entry_price=1.0815,
        fvg={"top": 1.0812, "bottom": 1.0805},
        trigger="sweep",
        initial_sl=1.0800,
        initial_tp=1.0840,
        trailing_hops=[],
        exit_time="2026-09-06T14:00:00+00:00",
        exit_price=1.0830,
        exit_reason="tp",
        r_realized=0.8,
        risk_multiplier_used=1.0,
        duration_bars=20,
    )
    top_keys = {
        "trade_id",
        "symbol",
        "direction",
        "cbdr_context",
        "entry",
        "initial_sl",
        "initial_tp",
        "trailing_hops",
        "exit",
        "r_realized",
        "risk_multiplier_used",
        "duration_bars",
    }
    assert top_keys <= set(rec.keys()), f"missing: {top_keys - set(rec.keys())}"
    assert rec["direction"] == "LONG"
    assert isinstance(rec["cbdr_context"], dict)
    assert isinstance(rec["entry"], dict)
    assert isinstance(rec["exit"], dict)


def test_writer_append_count():
    """TradeHistoryWriter append + count."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "trade_history.json")
        writer = TradeHistoryWriter(path)
        assert writer.count() == 0

        rec1 = make_trade_record(
            symbol="EURUSD",
            direction="LONG",
            cbdr_context={},
            entry_time="t1",
            entry_price=1.0,
            fvg=None,
            trigger="sweep",
            initial_sl=0.9,
            initial_tp=1.1,
            trailing_hops=[],
            exit_time="t2",
            exit_price=1.05,
            exit_reason="tp",
            r_realized=0.5,
            risk_multiplier_used=1.0,
            duration_bars=5,
        )
        writer.write(rec1)
        assert writer.count() == 1

        rec2 = make_trade_record(
            symbol="USDJPY",
            direction="SHORT",
            cbdr_context={},
            entry_time="t3",
            entry_price=150.0,
            fvg=None,
            trigger="fvg",
            initial_sl=151.0,
            initial_tp=149.0,
            trailing_hops=[],
            exit_time="t4",
            exit_price=149.2,
            exit_reason="sl",
            r_realized=-0.8,
            risk_multiplier_used=1.0,
            duration_bars=10,
        )
        writer.write(rec2)
        assert writer.count() == 2


def test_json_lines_format():
    """Dosya JSON Lines formatında: her satır bağımsız JSON."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "trade_history.json")
        writer = TradeHistoryWriter(path)
        for i in range(3):
            writer.write({"i": i, "trade_id": new_trade_id()})
        with open(path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 3
        for line in lines:
            obj = json.loads(line)
            assert "trade_id" in obj


def test_read_all_roundtrip():
    """write → read_all roundtrip."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "trade_history.json")
        writer = TradeHistoryWriter(path)
        rec = make_trade_record(
            symbol="GBPUSD",
            direction="SHORT",
            cbdr_context={"width_pct": 0.12},
            entry_time="t1",
            entry_price=1.2700,
            fvg={"top": 1.2710, "bottom": 1.2705},
            trigger="cbdr",
            initial_sl=1.2720,
            initial_tp=1.2680,
            trailing_hops=[{"bar_index": 5, "new_sl": 1.2710}],
            exit_time="t2",
            exit_price=1.2682,
            exit_reason="tp",
            r_realized=1.5,
            risk_multiplier_used=1.0,
            duration_bars=8,
        )
        writer.write(rec)
        all_recs = writer.read_all()
        assert len(all_recs) == 1
        assert all_recs[0]["symbol"] == "GBPUSD"
        assert all_recs[0]["entry"]["fvg"]["top"] == 1.2710


def test_read_all_empty():
    """Dosya yoksa read_all boş liste döner."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "trade_history.json")
        writer = TradeHistoryWriter(path)
        assert writer.read_all() == []
        assert writer.count() == 0


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
