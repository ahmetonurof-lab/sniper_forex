"""N2#26-REIS-DİREKTİFİ — make_readable_log: yerel saat + offset, logs/<SYM>/live.log, bar_ts.

N2#25 (Hakem-ratifikasyonlu) ISO-8601 UTC formatını REIS 2026-09-06'da
revize etti (askQuestions):
  - Format : yerel saat + offset  →  2026-09-05 22:13:00 +0300
  - Konum  : logs/<PARİTE>/live.log  (kanonik; logs/ gitignored)
  - STATE  : bar_ts göster (cold-rebuild replay burst'ünü ayırt etmek için)

Zaman-dilimi disiplini (§6.3): proje kuralı naive = UTC
(orchestrator.py:76). Event epoch → yerel+offset; bar_ts (naive-UTC) →
yerel+offset. Offset her satırda açık → naive-karışım yasağı korunur.
"""

from __future__ import annotations

import datetime
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

_TOOL_PATH = Path(__file__).resolve().parent.parent / "tools" / "make_readable_log.py"

_LOCAL_OFFSET_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [+-]\d{4} ")


def _load_tool() -> object:
    """Import make_readable_log as a NEW module (fresh exec, cache-free)."""
    spec = importlib.util.spec_from_file_location("_make_readable_log_n2_26", _TOOL_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules.pop("_make_readable_log_n2_26", None)
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        sys.modules.pop("_make_readable_log_n2_26", None)


def _run(src: Path, dst: Path, monkeypatch: pytest.MonkeyPatch) -> int:
    """Run the REAL main() path with monkeypatched argv and temp files."""
    monkeypatch.setattr(sys, "argv", ["make_readable_log.py", str(src), str(dst)])
    return _load_tool().main()


def _run_default(src: Path, monkeypatch: pytest.MonkeyPatch) -> int:
    """Run main() with ONLY the audit path → canonical logs/<SYM>/live.log."""
    monkeypatch.setattr(sys, "argv", ["make_readable_log.py", str(src)])
    return _load_tool().main()


def _expected_local(epoch: float) -> str:
    """Tool ile aynı yerel+offset formatında beklenen değer."""
    return datetime.datetime.fromtimestamp(epoch).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")


def test_state_output_local_offset_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """STATE (locked) -> [CBDR-KILIT]; timestamp yerel saat + offset."""
    line = json.dumps(
        {
            "event_type": "STATE",
            "payload": {
                "locked": True,
                "body_low": 79940.88,
                "body_high": 79994.74,
                "session_key": "2026-09-05",
            },
            "symbol": "BTCUSD",
            "timestamp": 1757158245,
        }
    )
    src = tmp_path / "audit.jsonl"
    src.write_text(line + "\n", encoding="utf-8")
    dst = tmp_path / "out.log"
    assert _run(src, dst, monkeypatch) == 0
    out = dst.read_text(encoding="utf-8")
    assert out.startswith(f"{_expected_local(1757158245)} [CBDR-KILIT] BTCUSD:")


def test_signal_output_local_offset_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ENTRY event (SIGNAL) -> [SIGNAL]; timestamp yerel saat + offset."""
    line = json.dumps(
        {
            "event_type": "SIGNAL",
            "payload": {"side": "long", "entry": 80000.0, "reason": "cbdr_sweep_fvg_fill"},
            "symbol": "BTCUSD",
            "timestamp": 1757158245,
        }
    )
    src = tmp_path / "audit.jsonl"
    src.write_text(line + "\n", encoding="utf-8")
    dst = tmp_path / "out.log"
    assert _run(src, dst, monkeypatch) == 0
    out = dst.read_text(encoding="utf-8")
    assert out.startswith(f"{_expected_local(1757158245)} [SIGNAL] BTCUSD:")


def test_all_output_lines_local_offset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Her satır yerel saat + offset öneki taşımalı."""
    lines = [
        json.dumps(
            {
                "event_type": "STARTUP",
                "payload": {"verdict": "PROCEED", "warmup_bars": 4342},
                "symbol": "BTCUSD",
                "timestamp": 1757158245,
            }
        ),
        json.dumps(
            {
                "event_type": "STATE",
                "payload": {"locked": True, "body_low": 1.0, "body_high": 2.0, "session_key": "k"},
                "symbol": "BTCUSD",
                "timestamp": 1757158246,
            }
        ),
        json.dumps(
            {
                "event_type": "SIGNAL",
                "payload": {"side": "short", "entry": 79000.0},
                "symbol": "BTCUSD",
                "timestamp": 1757158247,
            }
        ),
    ]
    src = tmp_path / "audit.jsonl"
    src.write_text("\n".join(lines) + "\n", encoding="utf-8")
    dst = tmp_path / "out.log"
    assert _run(src, dst, monkeypatch) == 0
    out = dst.read_text(encoding="utf-8")
    assert out  # non-empty
    for line in out.splitlines():
        assert _LOCAL_OFFSET_RE.match(line), f"non-local-offset line: {line!r}"


def test_default_output_logs_symbol_live_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit çıktı yoksa → logs/<SYMBOL>/live.log (kanonik konum)."""
    line = json.dumps(
        {
            "event_type": "STARTUP",
            "payload": {"verdict": "PROCEED", "warmup_bars": 4342},
            "symbol": "BTCUSD",
            "timestamp": 1757158245,
        }
    )
    src = tmp_path / "audit.jsonl"
    src.write_text(line + "\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)  # logs/ repo köküne değil tmp_path'e yazılsın
    assert _run_default(src, monkeypatch) == 0
    dst = tmp_path / "logs" / "BTCUSD" / "live.log"
    assert dst.exists()
    assert dst.read_text(encoding="utf-8").startswith(
        f"{_expected_local(1757158245)} [BOOT] BTCUSD:"
    )


def test_state_shows_bar_ts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """STATE event'lerinde bar_ts göster (replay burst'ü ayırt etmek için)."""
    line = json.dumps(
        {
            "event_type": "STATE",
            "payload": {
                "locked": True,
                "body_low": 79940.88,
                "body_high": 79994.74,
                "session_key": "2026-09-06",
                "bar_ts": "2026-09-06T01:00:00",
            },
            "symbol": "BTCUSD",
            "timestamp": 1757158245,  # event zamanı bar_ts'den farklı olmalı
        }
    )
    src = tmp_path / "audit.jsonl"
    src.write_text(line + "\n", encoding="utf-8")
    dst = tmp_path / "out.log"
    assert _run(src, dst, monkeypatch) == 0
    out = dst.read_text(encoding="utf-8")
    expected_bar = (
        datetime.datetime.fromisoformat("2026-09-06T01:00:00")
        .replace(tzinfo=datetime.timezone.utc)
        .astimezone()
        .strftime("%Y-%m-%d %H:%M:%S %z")
    )
    assert out.startswith(f"{expected_bar} [CBDR-KILIT] BTCUSD:")
    assert not out.startswith(f"{_expected_local(1757158245)} [CBDR-KILIT]")
