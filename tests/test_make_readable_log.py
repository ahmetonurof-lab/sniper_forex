"""N2#25 — make_readable_log must emit ISO-8601 UTC timestamps.

AGENTS.md §6.3 (timezone discipline): the previous naive
``strftime("%Y-%m-%d %H:%M:%S")`` mixed stdlib-naive semantics with the
audit epoch. The Hakem-approved N2#25 directive upgrades the timestamp to
ISO 8601 + UTC (``YYYY-MM-DDTHH:MM:SS+00:00``).

Provenance note (§12.1): the directive's example claimed epoch
``1757158245`` == ``2026-09-06T14:30:45+00:00``; the verified conversion is
``2025-09-06T11:30:45+00:00`` (arithmetic error in the directive). This test
pins the EVIDENCE-BASED value; the format requirement is unchanged.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

_TOOL_PATH = Path(__file__).resolve().parent.parent / "tools" / "make_readable_log.py"

_ISO_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00 ")


def _load_tool() -> object:
    """Import make_readable_log as a NEW module (fresh exec, cache-free)."""
    spec = importlib.util.spec_from_file_location("_make_readable_log_n2_25", _TOOL_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules.pop("_make_readable_log_n2_25", None)
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        sys.modules.pop("_make_readable_log_n2_25", None)


def _run(src: Path, dst: Path, monkeypatch: pytest.MonkeyPatch) -> int:
    """Run the REAL main() path with monkeypatched argv and temp files."""
    monkeypatch.setattr(sys, "argv", ["make_readable_log.py", str(src), str(dst)])
    return _load_tool().main()


def test_state_output_iso_utc_timestamp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """STATE (locked) -> [CBDR-KILIT]; timestamp must be ISO-8601 UTC.

    Directive input epoch 1757158245; verified conversion is
    2025-09-06T11:30:45+00:00 (directive's stated datetime was off by
    one year + 3h — see module docstring).
    """
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
    assert out.startswith("2025-09-06T11:30:45+00:00 [CBDR-KILIT] BTCUSD:")


def test_signal_output_iso_utc_timestamp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ENTRY event (SIGNAL) -> [SIGNAL]; timestamp must be ISO-8601 UTC."""
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
    assert out.startswith("2025-09-06T11:30:45+00:00 [SIGNAL] BTCUSD:")


def test_all_output_lines_iso_utc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every emitted line must carry an ISO-8601 UTC timestamp prefix."""
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
        assert _ISO_UTC_RE.match(line), f"non-ISO line: {line!r}"
