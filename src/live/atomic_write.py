#!/usr/bin/env python
"""N2 #21 madde-8 — THE single write primitive for src/live/ (tek-modül).

One module, two write models, three consumers (orchestrator / audit /
state), ZERO copies (Hakem N1-e: ``append_line`` is a neighbor function
of the primitive, not a copy of it):

  atomic_write_text()   tmp+rename floor write — state/safe-mode JSON
                        documents (Hakem N4 row-2: rename KALIR — a torn
                        JSON document is the fatal class). The live LOCK
                        is NOT here: Lock._write stays IN-PLACE (N2 #17,
                        Hakem N4 row-1 — rename-YOK since N2 #17).
  append_line()         O_APPEND delta writer — audit.jsonl (Hakem N1:
                        delta-append; the audit tmp+rename concept dies,
                        absorbing madde-9-aday-A's audit leg).

K2 forensic floor standard on BOTH (BULGU-14 inverted criterion): an
exhausted budget routes a best-effort ``atomic_write_exhausted`` line
to state/crash_log.txt BEFORE re-raising — the exhausted log must be
written on ALL write paths; never a blind death (the 3/3 ölüm-izinde
evidence: K3 .11476 / T0#8 .11468 / T0#9 .14940 tmp signatures, with
``atomic_write_exhausted=0`` — the floorless copy died blind).

Shared constants + K1 retry ladder + K3 on_block contract moved here
from the three former local copies (N2 #15-b semantics preserved
verbatim): 8 retries × backoff(0.05·2^n) ≈ 6.35s worst case ≪
LOCK_STALE_SEC=900 (§7.4 invariant; pinned by test_orchestrator_n2_15b).

Single-writer assumption (Hakem N1-c, explicit): O1 topology — ONE
process per symbol/audit file. A multi-process interleave rule (O3
agenda) would be a separate ruling. fsync: NONE for now (Hakem N1-d —
LESS CODE; a layer is added only if a loss class justifies it).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

# ── Shared retry budget (K1, N2 #15-b) ─────────────────────────────
_TMP_WRITE_RETRIES = 8
_TMP_RETRY_BASE_SLEEP = 0.05

# ── N2 #17 — K2 crash-log + runtime mechanism flag ────────────────
# When ``_ATOMIC_WRITE_RUNTIME`` is False (FROZEN production posture),
# an exhausted write budget routes the failure to ``state/crash_log.txt``
# BEFORE re-raising (see module docstring). Set True ONLY for a
# diagnostic/rollback run; the boolean is pinned by tests (never
# silently flipped).
_ATOMIC_WRITE_RUNTIME = False
_CRASH_LOG = Path("state") / "crash_log.txt"


def _crash_log_append(path: Path, info: Dict[str, Any]) -> None:
    """K2 — best-effort forensic append to the crash log.

    os.open(O_APPEND|O_CREAT) + single os.write: append-mode needs no
    tmp/rename (the mechanism under suspicion), is atomic at these
    sizes, and swallows every exception — forensics must never mask
    the original failure nor break the caller.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"ts": time.time(), **info}, default=str) + "\n"
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except Exception:
        pass


def _fire_on_block(
    on_block: Optional[Callable[[Dict[str, Any]], None]], info: Dict[str, Any]
) -> None:
    """Invoke the K3 forensic sink, swallowing everything. The CALLER
    decides the single-signal timing (first failed attempt only)."""
    if on_block is None:
        return
    try:
        on_block(info)
    except Exception:
        pass  # forensics must never mask the original failure


def atomic_write_text(
    path: Path,
    text: str,
    encoding: str = "utf-8",
    on_block: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> None:
    """Atomically write ``text`` to ``path`` via a PID-unique tmp + rename.

    Crash-safe (never a truncated target) and contention-hardened: the tmp
    sibling is unique per process/attempt, so two live processes cannot
    collide on the same tmp path, and a transient handle lock on the rename
    is retried with backoff before giving up.

    Moved verbatim from orchestrator.py (N2 #21 madde-8): this remains
    canonical for the state/safe-mode files, where rename-atomicity
    (never a torn or truncated target) is a correctness requirement, and
    the exhausted budget lands in the K2 crash-log before re-raising.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding=encoding)
    last_err: Optional[OSError] = None
    for attempt in range(_TMP_WRITE_RETRIES):
        try:
            tmp.replace(path)
            return
        except OSError as e:  # WinError 5 (PermissionError) and friends
            last_err = e
            # Fire on_block once per file (first failed attempt only) —
            # the orchestrator and AuditChain sinks both depend on this
            # being a single forensic signal, not per-retry noise.
            if attempt == 0:
                _fire_on_block(
                    on_block,
                    {
                        "file": str(path),
                        "retries": _TMP_WRITE_RETRIES,
                        "error": f"{type(e).__name__}: {e}",
                    },
                )
            if attempt + 1 < _TMP_WRITE_RETRIES:
                time.sleep(_TMP_RETRY_BASE_SLEEP * (2**attempt))
    # Best-effort cleanup of our own tmp before surfacing the failure.
    try:
        tmp.unlink()
    except OSError:
        pass
    # K2 (N2 #17): forensics BEFORE the raise — in the T0#5/T0#6 windows
    # the WRITE_BLOCK audit flush itself was un-flushable, so this
    # append-only log is the flush-independent floor.
    if not _ATOMIC_WRITE_RUNTIME:
        _crash_log_append(
            _CRASH_LOG,
            {
                "kind": "atomic_write_exhausted",
                "file": str(path),
                "retries": _TMP_WRITE_RETRIES,
                "error": f"{type(last_err).__name__}: {last_err}",
            },
        )
    raise last_err  # type: ignore[misc]


def append_line(
    path: Path,
    text: str,
    encoding: str = "utf-8",
    on_block: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> None:
    """Append ``text`` to ``path`` (created if missing) — the audit
    delta-append primitive (Hakem N1 / N2 #21 madde-1).

    Design notes:
      - O_APPEND + write-all: no tmp, no rename — the WinError-5 rename
        class leaves the audit path entirely.
      - Newline repair: a crash mid-append can leave the last line
        without its trailing newline. Appending after it would MERGE
        the torn-but-complete line with the first new line (one corrupt
        line, two events lost). A missing trailing b"\\n" is therefore
        prepended before the first appended byte.
      - Retry ladder ONLY on open failures (nothing written yet). A
        write failure is NOT retried — a partial write may have landed
        and a retry could duplicate bytes; the torn tail is load-skipped
        instead (Hakem N1-b) and the K2 floor keeps the evidence channel
        alive. Either way the failure re-raises — D35: exhaustion stays
        fatal, never laundered into a silent success.
    """
    if not text:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode(encoding)
    if p.exists():
        try:
            if p.stat().st_size > 0:
                with open(p, "rb") as f:
                    f.seek(-1, os.SEEK_END)
                    if f.read(1) != b"\n":
                        data = b"\n" + data
        except OSError:
            pass  # repair is best-effort; the append below still runs
    last_err: Optional[OSError] = None
    fd = -1
    for attempt in range(_TMP_WRITE_RETRIES):
        try:
            fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_APPEND)
            break
        except OSError as e:
            last_err = e
            if attempt == 0:
                _fire_on_block(
                    on_block,
                    {
                        "file": str(p),
                        "retries": _TMP_WRITE_RETRIES,
                        "error": f"{type(e).__name__}: {e}",
                    },
                )
            if attempt + 1 < _TMP_WRITE_RETRIES:
                time.sleep(_TMP_RETRY_BASE_SLEEP * (2**attempt))
    if fd < 0:
        if not _ATOMIC_WRITE_RUNTIME:
            _crash_log_append(
                _CRASH_LOG,
                {
                    "kind": "atomic_write_exhausted",
                    "file": str(p),
                    "op": "append_open",
                    "retries": _TMP_WRITE_RETRIES,
                    "error": f"{type(last_err).__name__}: {last_err}",
                },
            )
        raise last_err  # type: ignore[misc]
    try:
        written = 0
        while written < len(data):
            written += os.write(fd, data[written:])
    except OSError as e:
        if not _ATOMIC_WRITE_RUNTIME:
            _crash_log_append(
                _CRASH_LOG,
                {
                    "kind": "atomic_write_exhausted",
                    "file": str(p),
                    "op": "append_write",
                    "retries": _TMP_WRITE_RETRIES,
                    "error": f"{type(e).__name__}: {e}",
                },
            )
        raise
    finally:
        os.close(fd)
