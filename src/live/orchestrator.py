#!/usr/bin/env python
"""TAŞ-1/2 — ORCHESTRATOR: startup, lock, identity, bar pipeline, fail taxonomy.

S0  Config validation
S1  MT5 connection (initialize + login)
S2  Account info + broker identity + startup snapshot
S3  ContractSpec (D3: stops_level×point; D30: trade_mode != FULL → safe_reason)
S4  Margin level check
S5  Broker snapshot (LiveRunner inject: contract=, lifecycle=, runtime=,
                     sizer=, risk_manager=)
S6  SL/TP audit
S7  Local state recovery (D33: load_lifecycle + load)
S8  Reconciliation gate
S9  Warmup + real-terminal smoke (D28). D33: if restored → skip warmup,
                                  seed index base + slot set.
S11 READY

Lock contract (Taş 1, hardened Taş 2 — Windows-safe PID liveness + heartbeat):
  PROCEED     → lock held   → released by shutdown (Taş 4)
  SAFE-START  → lock held   → process continues
  FATAL       → startup releases its own lock
  CRASH       → dead-PID OR stale-time takeover
  STALE-ALIVE → alive PID but quiet (heartbeat missing) → takeover
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from src.config.mt5_config import get_mt5_config
from src.ctrader.position_adapter import CTRADER_BOT_LABEL, _to_position_ctrader
from src.live.atomic_write import (  # noqa: F401 — re-export for tests/compat
    _ATOMIC_WRITE_RUNTIME,
    _CRASH_LOG,
    _TMP_RETRY_BASE_SLEEP,
    _TMP_WRITE_RETRIES,
    _crash_log_append,
)
from src.live.atomic_write import (
    atomic_write_text as _atomic_write_text,
)
from src.live.audit import AuditChain, EventType, error_payload
from src.live.candle_feed import _15M_MS, M1CandleFeed, resample_15m

# DEBT-W1 (D129 B.1-B.4): human-readable logging modules — wired lazily
# in run() via _wire_live_logging (§2.2: reuse the existing modules;
# no parallel log implementation).
from src.live.canli_trade_log import (
    DailyUtcFileHandler,
    canli_trade_logger,
    setup_canli_trade_log,
)
from src.live.clock import _utcnow_naive, server_to_utc_historical
from src.live.console_reporter import ConsoleReporter
from src.live.reconciliation import Reconciler, ReconcileStatus, ReconciliationDecision
from src.live.recovery import RuntimeRecovery, schedule_snapshot
from src.live.risk import Account, RiskManager
from src.live.safety import SafetyMonitor
from src.live.sizing import ContractSpec, PositionSizer
from src.live.strategy_runtime import StrategyRuntime
from src.live.trade_history import (
    TRADE_HISTORY_FILENAME,
    TradeHistoryWriter,
    make_trade_record,
)
from src.live.trade_lifecycle import TradeLifecycle
from src.strategy.models import Bar

# ── Slot helpers (D19/D20 — 15m grid alignment) ─────────────────────


def _slot_floor_ms(label_ms: int) -> int:
    """Floor a millisecond label to its 15-minute grid slot (D19/D20)."""
    return (label_ms // _15M_MS) * _15M_MS


def _naive_utc_epoch(ts: Any) -> float:
    """Epoch seconds for a naive-UTC timestamp (D45).

    Project convention: naive = UTC (clock._utcnow_naive). stdlib
    ``datetime.timestamp()`` misinterprets naive datetimes as LOCAL time,
    while pandas assumes UTC — mixing the two shifts ``now_ms`` by the
    machine's tz offset. On a non-UTC VPS the D19 close-filter would emit
    late (UTC+) or reintroduce premature emit (UTC−). This helper is the
    single canonical conversion.
    """
    ts = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
    return ts.replace(tzinfo=timezone.utc).timestamp()


def _dedupe_safe_reason(reason: str) -> str:
    """Collapse a safe-mode reason string to its root causes.

    Each boot used to wrap the previous persisted reason in a new
    ``safe_mode_persisted:`` layer and re-append the same recon_blocked
    entries, so the persisted string grew unboundedly (observed 14× chain
    in state/PRESERVE_20260910_S5_PRECLEAR/orchestrator_safe.json). This
    strips nested ``safe_mode_persisted:`` chains and dedupes repeated
    entries, keeping first-occurrence order and a single persist tag.
    Safe-file semantics (persist tag + read path) are unchanged — only the
    accumulated reason string is bounded.
    """
    if not reason:
        return reason
    had_tag = reason.startswith("safe_mode_persisted: ")
    seen: List[str] = []
    for part in reason.split(";"):
        part = part.strip()
        if not part:
            continue
        while part.startswith("safe_mode_persisted: "):
            part = part[len("safe_mode_persisted: ") :].strip()
        if part and part not in seen:
            seen.append(part)
    joined = "; ".join(seen)
    if had_tag and joined:
        return f"safe_mode_persisted: {joined}"
    return joined


# ── Atomic tmp+rename write (N2 #15 — WinError 5 hardening) ────────
# The T0 crash (2026-09-01) died at `tmp.replace(...)` with WinError 5
# (PermissionError) on BOTH the lock heartbeat and the audit shutdown
# flush. Two root-cause hypotheses point here:
#   (a) two Python processes (venv shim + worker) racing the same
#       non-unique `.tmp` sibling path;
#   (b) transient Windows handle lock (AV/Defender scan or an open
#       handle) making `os.replace` fail.
# N2 #15 hardens every persisted-file write in the live loop with:
#   1. PID-unique tmp sibling (never two processes writing the same tmp),
#   2. bounded retry with backoff on the rename step (clears transient
#      handle locks without blocking the trading loop past the heartbeat
#      window).
# N2 #15-b (T0#4): T0#4 proved the PID-unique tmp fixed the CONTENTION
# layer (crash trace showed ``orchestrator.lock.<pid>.tmp``), but the
# rename still died with WinError 5 on BOTH the lock and the audit
# target in one window — a transient EXTERNAL handle (AV/Defender
# on-access scan) locking the TARGET file. The original ~0.35s budget
# was too small for a seconds-long scan handle. Budget raised to 8
# attempts / ~6.4s worst-case total sleep (0.05·(2^0..2^6) = 6.35s),
# still 0.7% of LOCK_STALE_SEC=900 (§7.4 invariant preserved).
# ``on_block`` (K3): forensic callback invoked on EVERY failed rename
# with {file, attempt, retries, error} — the WRITE_BLOCK audit event.
# N2 #21 madde-8: the constants are the re-exported shared ones (see the
# atomic_write import above) — NO local shadow copies (tek-modül).


# ── N2 #17 — Katman-1: Restart-Manager handle-holder probe ─────────
# FIX-SPEC v1.2 Katman-1 (Hakem-ratifiye): ilk başarısız lock yazım
# denemesinden hemen sonra (retry-tükenişini beklemeden) hedef dosyaya
# açık handle tutan süreçler Restart-Manager API ile listelenir.
# Stdlib-yalnız (ctypes); handle.exe/admin gerekmez. Ek-A iskeletinin
# sağlamlaştırılmışı: needed==0 (tutucu yok) ve her adımda rc kaydı —
# asla sessiz-geçiş yok (prob-hatası da {'probe_error': ...} döner).
class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_ulong), ("dwHighDateTime", ctypes.c_ulong)]


class _RM_UNIQUE_PROCESS(ctypes.Structure):
    _fields_ = [("dwProcessId", ctypes.c_ulong), ("ProcessStartTime", _FILETIME)]


class _RM_PROCESS_INFO(ctypes.Structure):
    # Windows RM_PROCESS_INFO: bRestartable is a C BOOL = 4 bytes
    # (c_int) — NOT c_bool (1 byte). A undersized field shrinks the
    # struct and RmGetList then writes past the buffer → heap
    # corruption (observed as delayed 0xc0000374 in an unrelated
    # pandas allocation during the N2 #17 test session — fixed).
    _fields_ = [
        ("Process", _RM_UNIQUE_PROCESS),
        ("strAppName", ctypes.c_wchar * 256),
        ("strServiceShortName", ctypes.c_wchar * 64),
        ("AppStatus", ctypes.c_ulong),
        ("TSSessionId", ctypes.c_ulong),
        ("bRestartable", ctypes.c_int),
    ]


_CCH_RM_SESSION_KEY = 32
_RM_ERROR_MORE_DATA = 234  # WinError ERROR_MORE_DATA (RmGetList first call)


def find_file_holders(path: str) -> list:
    """List processes holding an open handle on ``path`` (Restart-Manager).

    N2 #17 Katman-1 probe: runs ONLY at write-failure time (never in the
    heartbeat tick), so the per-call cost is irrelevant in production.
    Non-Windows → []. Every failure mode returns a ``{'probe_error': …}``
    dict instead of raising or silently returning [] — the holder name
    enters the ledger only as named evidence (hüküm-disiplini).
    """
    if os.name != "nt":
        return []
    try:
        rm = ctypes.WinDLL("rstrtmgr")
    except OSError as e:
        return [{"probe_error": f"load rstrtmgr: {e}"}]
    # A6-ii (Ek-A Cline-notları): FULL argtypes/restype declarations.
    # Undeclared prototypes leave marshaling to ctypes defaults; the RM
    # APIs take pointer/count pairs and silently write caller buffers —
    # exact prototypes are the bounds check.
    rm.RmStartSession.argtypes = [ctypes.POINTER(ctypes.c_ulong), ctypes.c_ulong, ctypes.c_wchar_p]
    rm.RmStartSession.restype = ctypes.c_ulong
    rm.RmRegisterResources.argtypes = [
        ctypes.c_ulong,
        ctypes.c_uint,
        ctypes.POINTER(ctypes.c_wchar_p),
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_void_p,
    ]
    rm.RmRegisterResources.restype = ctypes.c_ulong
    rm.RmGetList.argtypes = [
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_uint),
        ctypes.POINTER(ctypes.c_uint),
        ctypes.POINTER(_RM_PROCESS_INFO),
        ctypes.POINTER(ctypes.c_uint),
    ]
    rm.RmGetList.restype = ctypes.c_ulong
    rm.RmEndSession.argtypes = [ctypes.c_ulong]
    rm.RmEndSession.restype = ctypes.c_ulong
    session = ctypes.c_ulong(0)
    key = ctypes.create_unicode_buffer(_CCH_RM_SESSION_KEY + 1)
    rc_start = rm.RmStartSession(ctypes.byref(session), 0, key)
    if rc_start != 0:
        return [{"probe_error": f"RmStartSession rc={rc_start}"}]
    try:
        arr = (ctypes.c_wchar_p * 1)(path)
        rc_reg = rm.RmRegisterResources(session, 1, arr, 0, None, 0, None)
        if rc_reg != 0:
            return [{"probe_error": f"RmRegisterResources rc={rc_reg}"}]
        # A6-i: the holder count can GROW between the sizing call and the
        # fill call — retry on ERROR_MORE_DATA with a fresh buffer instead
        # of writing past a stale-sized array (the delayed heap-corruption
        # signature observed during the N2 #17 test session).
        for _attempt in range(3):
            needed = ctypes.c_uint(0)
            got = ctypes.c_uint(0)
            # Sizing call: infos=NULL with *pnProcInfo=0; lpdwRebootReasons
            # must be NON-NULL or RM returns rc=0/needed=0 (no holders)
            # instead of ERROR_MORE_DATA with the true count.
            scratch = (ctypes.c_uint * 4)()
            rc = rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(got), None, scratch)
            if rc == 0 and needed.value == 0:
                return []  # no holders — a legitimate, named result (rc=0)
            if rc != 0 and rc != _RM_ERROR_MORE_DATA:
                return [{"probe_error": f"RmGetList rc={rc}"}]
            n = max(needed.value, 1)
            infos = (_RM_PROCESS_INFO * n)()
            got = ctypes.c_uint(needed.value)
            reasons = (ctypes.c_uint * n)()  # ONE reboot-reason PER PROCESS
            rc = rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(got), infos, reasons)
            if rc == _RM_ERROR_MORE_DATA:
                continue  # list grew — re-size and retry (bounded ×3)
            if rc != 0:
                return [{"probe_error": f"RmGetList rc={rc}"}]
            return [
                {"pid": int(infos[i].Process.dwProcessId), "name": str(infos[i].strAppName)}
                for i in range(got.value)
            ]
        return [{"probe_error": "RmGetList count kept growing (3 attempts)"}]
    finally:
        try:
            rm.RmEndSession(session)
        except Exception:
            pass


def _pid_alive(pid: int) -> bool:
    """Windows-safe PID liveness check (Taş 2 lock hardening).

    Primitive (primary) liveness layer — Taş 1 restore:
      - Windows (os.name == "nt"): uses ``OpenProcess`` with
        ``PROCESS_QUERY_LIMITED_INFORMATION`` + ``GetExitCodeProcess``,
        requiring an exit code of ``STILL_ACTIVE (259)`` for a live pid.
        A pid we cannot open (no handle) is treated as dead.
      - POSIX/macOS: ``os.kill(pid, 0)`` — ``ProcessLookupError`` => dead,
        ``PermissionError`` => alive but no permission.

    The age-based stale window (``LOCK_STALE_SEC``) is the SECOND,
    independent safety layer: a process that is ALIVE per this check is
    never marked stale on age alone; it can only become stale if the lock
    file's ``created_at`` exceeds ``LOCK_STALE_SEC`` AND the PID is dead,
    OR (for a live-but-quiet process) the heartbeat is absent past the
    staleness window. See ``Lock._is_stale``.
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        import ctypes

        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        try:
            ec = ctypes.c_ulong()
            return bool(k32.GetExitCodeProcess(h, ctypes.byref(ec))) and ec.value == STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


# ── Fail taxonomy ─────────────────────────────────────────────────


class StartupPhase(str, Enum):
    S0_CONFIG = "S0"
    S1_CONNECT = "S1"
    S2_IDENTITY = "S2"
    S3_CONTRACT = "S3"
    S4_MARGIN = "S4"
    S5_SNAPSHOT = "S5"
    S6_SLTP_AUDIT = "S6"
    S7_RECOVERY = "S7"
    S8_RECON_GATE = "S8"
    S9_WARMUP = "S9"
    S11_READY = "S11"


class StartupVerdict(str, Enum):
    PROCEED = "PROCEED"
    SAFE_START = "SAFE_START"
    FATAL = "FATAL"


@dataclass
class StartupResult:
    verdict: StartupVerdict
    phase: StartupPhase
    reason: str
    account: Optional[Dict[str, Any]] = None
    terminal: Optional[Dict[str, Any]] = None
    snapshot: Optional[Dict[str, Any]] = None
    contract: Optional[Dict[str, Any]] = None
    warmup_bars: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return self.verdict == StartupVerdict.PROCEED


# ── Config ──────────────────────────────────────────────────────


@dataclass
class OrchestratorConfig:
    """Configuration for the production orchestrator (Phase 1).

    Phase 1 constraint: exactly ONE symbol is enforced.
    """

    symbols: List[str] = field(default_factory=list)
    m1_warmup_count: int = 65000
    state_dir: str = "state"
    # N2 #21 (exactly-once audit): None -> derived from state_dir at boot
    # (state_dir/audit.jsonl). The old hard-coded CWD-relative default
    # ("state/audit.jsonl") anchored TEST orchestrators to the REPO-ROOT
    # live journal (§19 CWD-persistence hazard): the N2#21-madde-1 boot
    # load then pulled live events into test chains — the D90 C3
    # "got 4/5" exactly-once root cause (4 live COLD_REBUILD_OK lines).
    audit_path: Optional[str] = None
    margin_level_min_pct: float = 300.0
    tick_stale_sec: float = 30 * 60
    poll_interval_sec: float = 20.0
    alert_env: str = "SNIPER_ALERT"
    expected_login: Optional[str] = None
    safe_mode_file: str = "orchestrator_safe.json"
    # ── Taş 3 runtime loop ────────────────────────────────────────
    max_spread_points: float = 30.0
    error_ladder_threshold: int = 3
    backoff_multiplier: float = 2.0
    backoff_max_sec: float = 300.0  # < LOCK_STALE_SEC(900) — heartbeat aralığı güvenli
    feed_cap: int = 1024
    # ── D104: real-order gate (controlled-demo PHASE-11) ──────────
    # Default True (safety). Runbook controlled-demo sets SNIPER_SIGNAL_ONLY=0
    # explicitly to let the chain reach ORDER→FILL→POSITION on the DEMO rail.
    signal_only: bool = True
    # ── D49: restore staleness threshold (in 15m slots) ───────────
    # A restored runtime whose last processed bar is >= this many 15m
    # slots behind `now` is STALE → cold rebuild (full fetch + warmup +
    # O2 replay) instead of a warm resume. Weekend gap (Fri-close →
    # Sun-boot ~190 slots) or any downtime gap >= 2 slots triggers rebuild.
    restore_staleness_slots: int = 2


# ── Lock ──────────────────────────────────────────────────────────

LOCK_STALE_SEC = 60 * 15  # 15 minutes

# ── MT5 symbol trade-mode enum (Bug B fix, live boot 2026-09-01) ──
# Package-verified against the installed MetaTrader5 build on 2026-09-01:
#   SYMBOL_TRADE_MODE_DISABLED=0, LONGONLY=1, SHORTONLY=2,
#   CLOSEONLY=3, FULL=4
# The old code assumed 0=FULL — inverted. Live EURUSD (IC Markets) reports
# trade_mode=4, so the old check falsely SAFE-STARTED, and a DISABLED
# symbol (0) would have counted as FULL — a reverse-lock hazard for
# Aşama 4. Defined as a module constant (not read off self._mt5) because
# test fakes do not carry package enum attributes; pinned by
# tests/test_mt5_connection_hardening.py enum-pin test against the real
# package when importable.
_SYMBOL_TRADE_MODE_FULL = 4


@dataclass
class LockData:
    pid: int
    created_at: float
    phase: str

    def to_dict(self) -> dict:
        return {"pid": self.pid, "created_at": self.created_at, "phase": self.phase}

    @classmethod
    def from_dict(cls, d: dict) -> "LockData":
        return cls(
            pid=int(d["pid"]),
            created_at=float(d["created_at"]),
            phase=str(d.get("phase", "")),
        )


class LockError(Exception):
    pass


class ConsoleAlert:
    """Minimal alert sink (Taş 3 Aşama 1): stderr + in-memory log.

    Tests observe ``alert.alert_log`` entries (``.level`` / ``.msg``).
    D53 wires the real channel on top of this sink (``TelegramAlert``);
    the sink stays canonical so every transport keeps the same log.
    """

    def __init__(self, env: str = "SNIPER_ALERT") -> None:
        self.env = env
        self.alert_log: List[Any] = []

    def send(self, level: str, msg: str) -> None:
        import sys

        entry = SimpleNamespace(level=level, msg=msg, ts=time.time())
        self.alert_log.append(entry)
        print(f"[{self.env}][{level}] {msg}", file=sys.stderr)


class TelegramAlert(ConsoleAlert):
    """D53 — Telegram transport over the console sink (urllib POST sendMessage).

    Hard rules (referee spec, S5 lesson):

    - The trading loop must NEVER be blocked or broken by alerting: the POST
      runs with a ``timeout_sec`` cap (≤ 3 s) and every network exception is
      swallowed — ``send`` never raises.
    - Silent fallback is forbidden: on the first transport failure the alert
      is disabled once (``_dead``) and a visible console WARN is recorded
      (no per-message spam, no recursion).
    - ``alert_log`` / stderr behaviour is inherited unchanged, so existing
      call sites and tests keep observing the same entries.
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        env: str = "SNIPER_ALERT",
        timeout_sec: float = 3.0,
    ) -> None:
        super().__init__(env)
        self.bot_token = bot_token
        self.chat_id = chat_id
        # Spec cap: a network call must never stall the loop beyond 3 s.
        self.timeout_sec = min(float(timeout_sec), 3.0)
        self._dead = False

    def send(self, level: str, msg: str) -> None:
        super().send(level, msg)  # console sink stays canonical first
        if self._dead:
            return
        try:
            self._post(level, msg)
        except Exception as e:  # noqa: BLE001 - never propagate into trading
            self._dead = True  # one-time visible degradation, never raises
            super().send(
                "WARN",
                f"telegram transport disabled ({type(e).__name__}) — console-only fallback",
            )

    def _post(self, level: str, msg: str) -> None:
        import urllib.parse
        import urllib.request

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        body = urllib.parse.urlencode(
            {"chat_id": self.chat_id, "text": f"[{self.env}][{level}] {msg}"}
        ).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
            resp.read()


def _build_alert_transport(env: str, audit: Optional[AuditChain] = None) -> ConsoleAlert:
    """D53 factory: TelegramAlert when TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
    are both set (via .env / environment), otherwise ConsoleAlert.

    The fallback must be VISIBLE (S5: sessiz fallback YASAK): exactly one
    audit WARN event is appended when the Telegram env pair is absent.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if token and chat_id:
        return TelegramAlert(token, chat_id, env)
    if audit is not None:
        audit.append(
            time.time(),
            EventType.STARTUP,
            None,
            {
                "phase": "alerting",
                "verdict": "CONSOLE_FALLBACK",
                "reason": "telegram_env_unset",
            },
        )
    return ConsoleAlert(env)


class SafeModeStore:
    """Read/write accessor for the persisted safe-mode file (D24).

    Thin standalone view over the same JSON the orchestrator writes via
    ``_write_safe_mode`` — exists so tools/tests can inspect persisted
    safe-mode state without constructing a full Orchestrator.
    """

    def __init__(self, state_dir: str, filename: str = "orchestrator_safe.json"):
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / filename

    def load(self) -> Optional[dict]:
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def write(self, reason: str) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        data = {"safe_mode": True, "reason": reason, "ts": time.time()}
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def clear(self) -> None:
        if self.path.exists():
            try:
                self.path.unlink()
            except OSError:
                pass


class Lock:
    """File-based single-instance lock with PID liveness + heartbeat.

    Taş 2 hardening:
      - Windows-safe PID liveness (``_pid_alive``) so a CRASHED process
        is detected even when its lock file is still fresh on disk.
      - ``heartbeat()`` rewrites the lock body IN-PLACE renewing
        ``created_at`` (the freshness carrier for the "wedged quietly,
        no heartbeat" staleness criterion — contract UNCHANGED) while
        preserving the current lifecycle ``phase`` set via
        ``set_phase()`` (N2 #21 madde-5), so the advertised phase never
        silently reverts to "startup" on a healthy run.

    acquire()  → raises LockError on conflict (existing live lock)
    release()  → no-op if we don't own the lock (pid mismatch)
    heartbeat() → refresh mtime (call from long-running healthy loops)

    N2 #17: the write mechanism is IN-PLACE (open + truncate + write +
    fsync, K1 retry ladder preserved) — the N2 #15 tmp+rename strategy
    remains ONLY for audit/state/safe-mode files (``_atomic_write_text``),
    because T0#6 (exclusion ACTIVE) falsified the AV-race hypothesis and
    implicated the rename-overwrite step itself (dual-process writer).

    ``on_block`` (K3) is the forensic sink invoked once when the in-place
    lock write exhausts its retry budget — the WRITE_BLOCK audit event.
    The first successful write also appends a one-shot writer_diagnostic
    (self/parent process identity) to the K2 crash-log (``_CRASH_LOG``).
    """

    def __init__(
        self,
        lock_path: Path,
        on_block: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_corrupt: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.lock_path = Path(lock_path)
        self._owned = False
        self._on_block = on_block
        self._on_corrupt = on_corrupt
        self._path_attempt_logged = False
        self._lock_corrupt_logged = False
        # N2 #17 Katman-4: latched degraded state — a failed heartbeat
        # refresh keeps the process alive and retries next tick; the flag
        # is surfaced for tests/monitoring and cleared on next success.
        self._write_degraded = False
        # N2 #21 madde-5 (prereg §3): lifecycle phase advertised in the
        # lock body. Default preserves the historical "startup" schema
        # for non-orchestrator users; set_phase() transitions it and
        # every _write() persists the current value (the old code
        # re-stamped phase="startup" on each heartbeat, so a live lock
        # forever claimed "startup" — BULGU-3 stickiness).
        # created_at stays the heartbeat-freshness carrier (prereg §3c:
        # LOCK_STALE_SEC arithmetic untouched) — it is deliberately NOT
        # latched: _is_stale reads it to detect "wedged quietly, no
        # heartbeat", so renewing it per heartbeat IS the liveness
        # contract (a latch here would falsely mark every healthy
        # long run stale-eligible and enable live takeover).
        self._phase: str = "startup"

    def _diagnose_path_write(self) -> None:
        """N2 #17 boot-writer diagnostic (one-shot, non-fatal).

        Fires once per Lock instance (first successful _write window),
        appending a line to the K2 crash-log with the process command
        line, parent PID and parent command line — the exact evidence
        Hakem's dual-instance probe asks for (are BOTH launcher and
        worker running the orchestrator?). Never raises; failure to
        diagnose must never fail the lock write.
        """
        if self._path_attempt_logged:
            return
        self._path_attempt_logged = True
        try:
            import sys as _sys

            me = f"{os.getpid()}: {_sys.executable} {' '.join(_sys.argv)}"
            ppid = os.getppid() if hasattr(os, "getppid") else -1
            parent = f"{ppid}: <unavailable>"
            try:
                if os.name == "nt" and ppid > 0:
                    import ctypes

                    k32 = ctypes.windll.kernel32
                    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, ppid)
                    if h:
                        try:
                            buf = ctypes.create_unicode_buffer(4096)
                            # QueryFullProcessImageNameW via kernel32 is
                            # available on Win8+; fallback keeps '<unavailable>'.
                            size = ctypes.c_ulong(len(buf))
                            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                                parent = f"{ppid}: {buf.value}"
                        finally:
                            k32.CloseHandle(h)
                else:
                    with open(f"/proc/{ppid}/cmdline", "rb") as f:
                        parent = (
                            f"{ppid}: {f.read().replace(b'\\x00', b' ').decode('utf-8', 'replace')}"
                        )
            except Exception:
                pass
            _crash_log_append(
                _CRASH_LOG,
                {
                    "kind": "writer_diagnostic",
                    "self": me,
                    "parent": parent,
                },
            )
        except Exception:
            pass

    def acquire(self) -> None:
        """Boot-takeover: FATAL on unresolvable conflicts (Katman-4.1 —
        fail-fast, no lock-less running). N2 #17 additions:
        - Fresh TORN lock (A9 triage, mtime < LOCK_STALE_SEC): wait 1s
          and re-read once — a torn IN-PLACE write heals within seconds
          when the previous owner still lives (its heartbeat rewrites
          the full body). Stale-torn → takeover below.
        - Read-BLOCKED fresh lock (OSError triage): one 1s read-retry;
          still unreadable → LockError (boot fail-fast). A sharing
          violation must not be mistaken for "no lock" — writing over
          a live foreign lock would be the D35 hazard.
        Stale-torn/stale-readable → takeover _write() (mtime survives
        the torn write as the fallback identity — spec Katman-3.2).
        """
        if self._owned:
            return
        if self.lock_path.exists():
            data = self._read()
            if data is not None and not self._is_stale(data):
                raise LockError(
                    f"Lock held by PID {data.pid} (phase={data.phase}, "
                    f"age={time.time() - data.created_at:.0f}s)"
                )
            if data is None:
                # Torn (A9) or read-blocked (A2 OSError) — mtime decides.
                fresh = True
                try:
                    fresh = (time.time() - self.lock_path.stat().st_mtime) < LOCK_STALE_SEC
                except OSError:
                    pass  # unreadable mtime → treat as fresh (conservative)
                if fresh:
                    self._log_io_guard("acquire_unreadable_fresh", LockError("torn/blocked"))
                    time.sleep(1.0)
                    data = self._read()
                    if data is not None and not self._is_stale(data):
                        raise LockError(
                            f"Lock held by PID {data.pid} (phase={data.phase}, "
                            f"age={time.time() - data.created_at:.0f}s)"
                        )
                    if data is None:
                        # Still unreadable/torn after one heal window:
                        # boot fails fast (Katman-4.1) — we must not
                        # write over a possibly-live foreign lock.
                        raise LockError(
                            "Lock target unreadable (torn/blocked) and "
                            "not stale-eligible — boot refused (N2 #17)"
                        )
        self._write()
        self._owned = True

    def release(self) -> None:
        if not self._owned:
            return
        if self.lock_path.exists():
            data = self._read()
            if data is not None and data.pid != os.getpid():
                return  # not our lock
            try:
                self.lock_path.unlink()
            except OSError:
                pass
        self._owned = False
        # N2 #21 madde-5: a released lock advertises the historical
        # default again — the next acquire() starts a fresh lifecycle.
        self._phase = "startup"

    def _log_io_guard(self, op: str, e: Exception) -> None:
        """Katman-2: LOUD-warn for every lock-file IO anomaly.

        Code invariant (FIX-SPEC v1.2 Katman-2): an open-handle lifetime on
        a rename-target state file must not outlive the function that
        opened it — every read/write here is synchronous close-in-scope.
        Any anomaly (share-blocked read, blocked write) is warned and
        crash-logged; it never raises out of the lock helpers.
        """
        try:
            _crash_log_append(
                _CRASH_LOG,
                {
                    "kind": "LOCK_IO_GUARD",
                    "pid": os.getpid(),
                    "op": op,
                    "file": str(self.lock_path),
                    "error": f"{type(e).__name__}: {e}",
                },
            )
        except Exception:
            pass

    def _emit_lock_corrupt(self, payload: Dict[str, Any]) -> None:
        """A9: one LOCK_CORRUPT event per Lock instance (no tick spam)."""
        if self._lock_corrupt_logged:
            return
        self._lock_corrupt_logged = True
        if self._on_corrupt is not None:
            try:
                self._on_corrupt(payload)
            except Exception:
                pass  # forensics never mask the read-path decision

    def verify_ownership_via_record(self) -> Optional[int]:
        """N2 #17 A9: salvage the PID from a lock whose JSON body is torn.

        The PID is stored FIRST in the body (``{"pid": N, ...}``), so a
        regex over the raw text recovers ownership even when json.loads
        fails on a truncated write. Returns the PID, or None when even
        the salvage fails (ownership stays unprovable — hüküm katmaz).
        Diagnostic only; never raises.
        """
        try:
            raw = self.lock_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        m = re.search(r'"pid"\s*:\s*(\d+)', raw)
        return int(m.group(1)) if m else None

    def heartbeat(self) -> None:
        """Refresh lock mtime to prevent false-stale on long healthy runs.

        No-op if we do not own the lock. Safe to call from any tick.

        N2 #17 Katman-4 (FIX-SPEC v1.2): a FAILED refresh write is
        NONFATAL — the heartbeat is a liveness advertisement, not
        trade-book integrity. The process lives, the failure is LOUD
        (crash-log + WRITE_BLOCK audit via _write's on_block + latched
        ``_write_degraded``) and the next tick retries. Boot-takeover
        write failure (acquire) stays FATAL (fail-fast); the K1
        8-attempt/~6.4s budget is unchanged.
        """
        if not self._owned:
            return
        try:
            self._write()
            self._write_degraded = False
        except OSError as e:
            self._write_degraded = True
            self._log_io_guard("heartbeat_write", e)

    def _read(self) -> Optional[LockData]:
        """Read+parse lock data with A2/A9 triage (N2 #17 FIX-SPEC v1.2).

        Failure classes are now DISTINCT — the B1 read-path hole was that
        OSError and torn-JSON collapsed into the same silent None, which
        _heartbeat_validated then treated as ownership loss (fatal exit
        on a transient external read-handle):

        - OSError → read BLOCKED (external handle/permission). A2: this
          is NOT ownership evidence. LOUD crash-log, then None; the
          caller (_heartbeat_validated) verifies ownership via
          ``verify_ownership_via_record()`` before any fatal decision.
        - json.JSONDecodeError → torn in-place write. A9: one LOCK_CORRUPT
          audit event carrying the mtime age (fresh-torn vs stale-torn ≥
          LOCK_STALE_SEC) — the ledger names the anomaly; None returned.
        - KeyError → schema gap → None (unchanged).
        """
        try:
            raw = json.loads(self.lock_path.read_text(encoding="utf-8"))
            return LockData.from_dict(raw)
        except json.JSONDecodeError as e:
            age = -1.0
            try:
                age = time.time() - self.lock_path.stat().st_mtime
            except OSError:
                pass
            self._emit_lock_corrupt(
                {
                    "file": str(self.lock_path),
                    "mtime_age_s": round(age, 1),
                    "stale_eligible": bool(age >= LOCK_STALE_SEC),
                    "error": f"json: {e}",
                }
            )
            self._log_io_guard("read_torn", e)
            return None
        except OSError as e:
            self._log_io_guard("read", e)
            return None
        except KeyError as e:
            self._log_io_guard("read_schema", e)
            return None

    def _write(self) -> None:
        """Persist lock data. N2 #17: IN-PLACE write, not tmp+rename.

        N2 #15/#15-b history: PID-unique tmp + 8×~6.4s retry — T0#6 still
        crashed with the same rename WinError 5 WITH the Defender
        exclusion active. Leading hypothesis (Hakem, N2 #17): a
        dual-process writer (venv launcher + worker) contending on the
        lock — rename-overwrite collides with the live target handle.
        The heartbeat therefore writes IN-PLACE (single open handle,
        truncate+write+fdatasync) — the rename-overwrite mechanism is
        removed from the hot path entirely. Self-heartbeat is
        single-writer (this process owns the lock per D35 acquire +
        Lock.owned); Lock._read()'s JSON tolerance covers torn in-place
        reads for unrelated processes, and ``created_at`` monotonicity
        is asserted by tests.

        D35 ownership contract UNCHANGED: Lock._owned gates this method;
        the PID-in-lock verification stays the ownership proof — this
        change replaces the WRITE MECHANISM, not the ownership check.

        If an external handle still blocks even the in-place open()
        (evidence would be a WRITE_BLOCK event naming the lock target),
        the K2 crash-log diagnostic captures the exact failure for the
        handle-holder forensics.

        N2 #17 Katman-1 (FIX-SPEC v1.2): on the FIRST failed attempt
        (not after budget exhaustion) the Restart-Manager probe lists
        the processes holding an open handle on the lock target; the
        holder PIDs/names (or the probe error — never silent) are
        embedded in the WRITE_BLOCK audit event.
        """
        data = LockData(
            pid=os.getpid(),
            # created_at renewed per write: freshness carrier for
            # _is_stale's "no heartbeat" criterion (contract unchanged,
            # prereg §3c). phase is the LIVE label (set_phase), never
            # the old frozen "startup" literal (BULGU-3).
            created_at=time.time(),
            phase=self._phase,
        )
        payload = json.dumps(data.to_dict())
        # Parent-dir creation matches the N2 #15 helper contract (tests
        # and callers rely on acquire() working into a fresh state dir).
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._diagnose_path_write()
        # Single-writer by D35: only the lock owner runs this method
        # (heartbeat no-ops when not owned). The K1 retry ladder and the
        # K3 on_block contract are PRESERVED on the in-place path — an
        # external handle blocking the in-place open must still be
        # survived (seconds-long AV/indexer handles) and still recorded.
        last_err: Optional[OSError] = None
        for attempt in range(_TMP_WRITE_RETRIES):
            try:
                fd = os.open(str(self.lock_path), os.O_WRONLY | os.O_CREAT)
                try:
                    os.ftruncate(fd, 0)
                    os.write(fd, payload.encode("utf-8"))
                    try:
                        # fdatasync is POSIX-only; fsync is the Windows
                        # equivalent for this durability intent. A failing
                        # fsync never breaks the heartbeat (liveness is
                        # carried by the write + mtime, not durability).
                        os.fsync(fd)
                    except OSError:
                        pass
                finally:
                    os.close(fd)
                return
            except OSError as e:
                last_err = e
                if attempt == 0:
                    # Katman-1 probe: name the holder at the first failed
                    # attempt (retry-tükenişi beklemeden — spec §3-K1).
                    holders: list = []
                    try:
                        holders = find_file_holders(str(self.lock_path))
                    except Exception as probe_err:  # pragma: no cover
                        holders = [{"probe_error": f"exception: {probe_err}"}]
                    if self._on_block is not None:
                        try:
                            self._on_block(
                                {
                                    "file": str(self.lock_path),
                                    "retries": _TMP_WRITE_RETRIES,
                                    "error": f"{type(e).__name__}: {e}",
                                    "probe": "restart_manager",
                                    "holder_pids": [h["pid"] for h in holders if "pid" in h],
                                    "holder_names": [h["name"] for h in holders if "name" in h],
                                    "probe_errors": [
                                        h["probe_error"] for h in holders if "probe_error" in h
                                    ],
                                }
                            )
                        except Exception:
                            pass  # forensics never mask the original failure
                if attempt + 1 < _TMP_WRITE_RETRIES:
                    time.sleep(_TMP_RETRY_BASE_SLEEP * (2**attempt))
        assert last_err is not None
        raise last_err

    @staticmethod
    def _is_stale(data: LockData) -> bool:
        # Two failure modes: process crashed (dead PID) or process
        # wedged quietly past the staleness window (no heartbeat).
        if not _pid_alive(data.pid):
            return True
        return (time.time() - data.created_at) > LOCK_STALE_SEC

    def set_phase(self, phase: str) -> None:
        """N2 #21 madde-5 (BULGU-3): transition the advertised lifecycle
        phase on the lock body ("S0_config" ... "S9_warmup", "S11_ready",
        "running" once the Taş-3 loop starts).

        Contract:
        - OWNERSHIP REQUIRED: only the lock owner mutates the shared
          body. Calling before acquire() / after release() raises
          LockError — a phase transition is never silently dropped.
        - IMMEDIATE WRITE: the transition is flushed to the lock body
          right away so external observers (conflict error messages,
          operator triage) read the CURRENT phase, and boot-phase
          transitions actually reach disk (the next heartbeat may be a
          full warmup away). Fail-safe = heartbeat semantics (N2 #17
          Katman-4): a FAILED phase write is NONFATAL and LOUD (crash
          -log + latched ``_write_degraded``); the in-memory label is
          already advanced and the next heartbeat tick re-attempts the
          flush. Phase metadata never refreshes ``created_at``.
        """
        if not self._owned:
            raise LockError(
                f"set_phase('{phase}') requires lock ownership "
                "(call acquire() first) — refusing to mutate foreign state"
            )
        self._phase = str(phase)
        try:
            self._write()
            self._write_degraded = False
        except OSError as e:
            self._write_degraded = True
            self._log_io_guard("set_phase_write", e)

    @property
    def owned(self) -> bool:
        return self._owned


# ── Orchestrator ───────────────────────────────────────────────────


class Orchestrator:
    """TAŞ-1: startup orchestration with lock ownership contract.

    Usage:
        orch = Orchestrator(state_dir="state")
        result = orch.startup()
        if result.verdict == StartupVerdict.PROCEED:
            # lock held — run loop
            ...
        elif result.verdict == StartupVerdict.SAFE_START:
            # lock held — degraded but alive
            ...
        # FATAL → lock already released by startup()
    """

    def __init__(
        self,
        state_dir: str = "state",
        magic: int = 9007001,
        configured_symbols: Optional[List[str]] = None,
        audit: Optional[AuditChain] = None,
        config_obj: Optional[OrchestratorConfig] = None,
        mt5: Any = None,
        mt5_conn: Any = None,
        now_fn: Optional[Callable[[], datetime]] = None,
    ):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.magic = magic
        self.config = config_obj or OrchestratorConfig(
            symbols=configured_symbols or [],
            state_dir=state_dir,
        )
        self.configured_symbols = configured_symbols or []
        # N2 #13 — B1/B2 (audit journal wiring + falsy-empty guard).
        # Empty AuditChain is FALSY (AuditChain.__len__ == 0), so a naive
        # `audit or AuditChain()` silently DROPS an injected empty chain
        # (caught during N2 #12 soak evidence run). Build the production
        # chain first, then prefer the caller's chain when it is non-empty.
        # Also wire config.audit_path into auto_flush so the production
        # orchestrator persists the journal to disk (was the N2 #12 gap).
        # N2 #21 (exactly-once audit): the journal anchors to state_dir
        # unless explicitly configured — never to the CWD. run_production
        # passes an explicit absolute path (unchanged); test orchestrators
        # get tmp_state isolation by construction.
        config_audit_path = getattr(self.config, "audit_path", None) or str(
            self.state_dir / "audit.jsonl"
        )
        prod_audit: AuditChain
        if config_audit_path:
            prod_audit = AuditChain(auto_flush_path=config_audit_path)
            # N2 #21 madde-1 (Hakem N1-a): boot LOADS the existing journal
            # BEFORE any flush. Combined with delta-append save() this
            # restores prior boots' events into the chain AND keeps them
            # on disk — the whole-file overwrite that erased every prior
            # boot's chain (BULGU-1 / D77-ezilme / T0#9 κ) is gone.
            # Continuity must never block the boot: a failed load degrades
            # to counter=0 (delta-append still preserves prior lines).
            try:
                prod_audit.load(config_audit_path)
            except Exception:
                pass
        else:
            prod_audit = AuditChain()
        self.audit = audit if audit is not None and len(audit) > 0 else prod_audit

        # N2 #15-b (K3): WRITE_BLOCK forensic sink. A blocked tmp→target
        # rename (transient AV/sync handle on the TARGET file — the T0#4
        # second root-cause layer) leaves a durable audit trail. The
        # helper fires on_block once per file (first failed rename), so
        # no filtering is needed here — one event per blocked file.
        def _write_block_sink(info: Dict[str, Any]) -> None:
            try:
                self.audit.append(
                    time.time(),
                    EventType.WRITE_BLOCK,
                    self._symbol or None,
                    {
                        "file": info.get("file"),
                        "retries": info.get("retries"),
                        "error": info.get("error"),
                    },
                )
            except Exception:
                pass  # forensics must never mask the original write failure

        self._on_write_block = _write_block_sink

        # N2 #17 A9: LOCK_CORRUPT forensic sink — a torn in-place lock
        # write (unreadable JSON) is named once per Lock instance with
        # its mtime age (fresh-torn vs stale-torn ≥ LOCK_STALE_SEC).
        def _lock_corrupt_sink(info: Dict[str, Any]) -> None:
            try:
                self.audit.append(
                    time.time(),
                    EventType.LOCK_CORRUPT,
                    self._symbol or None,
                    {
                        "file": info.get("file"),
                        "mtime_age_s": info.get("mtime_age_s"),
                        "stale_eligible": info.get("stale_eligible"),
                        "error": info.get("error"),
                    },
                )
            except Exception:
                pass  # forensics must never mask the read-path decision

        self.lock = Lock(
            self.state_dir / "orchestrator.lock",
            on_block=_write_block_sink,
            on_corrupt=_lock_corrupt_sink,
        )
        self.audit.on_block = _write_block_sink
        self._mt5: Any = mt5
        # MT5Connection (production fetch path) — injectable for tests.
        self._mt5_conn: Any = mt5_conn
        # İŞ-4a S1 (D159): cTrader-first mode flag. Set in S1 when the
        # injected data connection is a cTrader adapter (duck-typed: no
        # `connect` attribute). Default False — MT5 path unchanged.
        self._ctrader_mode: bool = False
        # D38 (runner lifetime retention): the LiveRunner built in S5 is
        # retained on the orchestror for process lifetime. The Taş 3 loop
        # will call on_bar()/poll_deals()/sync_trailing() ONLY through
        # self._runner — no second LiveRunner is ever reconstructed.
        self._runner: Optional[Any] = None
        self._symbol: str = ""
        self._contract: Optional[ContractSpec] = None
        # S5 injection: orchestrator OWNS these, hands them to LiveRunner.
        self._runtime: Optional[StrategyRuntime] = None
        self._lifecycle: Optional[TradeLifecycle] = None
        self._sizer: Optional[PositionSizer] = None
        self._risk_manager: Optional[RiskManager] = None
        self._recovery: Optional[RuntimeRecovery] = None
        # D30: builder flags trade_mode != FULL for S3 to surface.
        self._trade_mode_ok: bool = True
        # D33: set True in S7 when any state restored from disk.
        # Per-state flags let S9 correctly distinguish "runtime is a warm
        # continuation" (runtime._warmed) from "lifecycle alone restored".
        self._restored: bool = False
        self._runtime_restored: bool = False
        self._lifecycle_restored: bool = False
        # D9 tri-state: consecutive fetch errors (None/[]) → ERROR counter.
        self._fetch_error_count: int = 0
        # Bar pipeline state (D19/D20).
        # _seen_bar_ids holds 15m SLOT millisecond ints (not identity tuples).
        self._last_15m_ts: Optional[pd.Timestamp] = None
        self._global_bar_index: int = 0
        self._seen_bar_slots: set = set()
        # Persisted safe-mode (read once at startup, consumed by S11).
        self._persisted_safe_reason: Optional[str] = None
        # D49 (O2): boot-time sync replay report (C2 single summary event).
        self._replay_report: Optional[dict] = None
        # D49 (C3): cold rebuild was required (stale/partial restore); used to
        # emit WARN+alert (visible) while still allowing PROCEED when the
        # rebuild succeeds.
        self._cold_rebuild_needed: bool = False
        # ── Taş 3 runtime loop state ─────────────────────────────
        self._now_fn: Callable[[], datetime] = now_fn or _utcnow_naive
        self._startup_result: Optional[StartupResult] = None
        self._kill_requested: bool = False
        self._runtime_safe: bool = False  # D10: transient, auto-clear
        self._runtime_safe_reason: str = ""
        self._gate_was_allowed: Optional[bool] = None
        self._last_bar_ts: Optional[Any] = None
        self._pending_feed: List[Any] = []
        self._feed_cap_alerted: bool = False
        self._ladder_alerted: bool = False
        # İŞ-6 (DİREKTİF-14): first-failure-only audit for the cTrader
        # account fetch fail-soft path (avoids per-bar audit spam).
        self._account_fail_soft_alerted: bool = False
        self._safety: Optional[Any] = None
        # D53: Telegram transport when TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID are
        # configured; visible console fallback otherwise (single audit WARN).
        self.alert = _build_alert_transport(self.config.alert_env, self.audit)
        # ── DEBT-W1: live logging wiring (lazy; initialized in run()) ──
        # None until _wire_live_logging() succeeds; every consumer guards
        # on _log_wired so a wiring failure can never touch the loop.
        self._log_dir: Optional[str] = None
        self._console: Optional[Any] = None
        self._canli_log: Optional[Any] = None
        self._trade_writer: Optional[Any] = None
        self._log_wired: bool = False
        self._exit_keys_logged: set = set()

    # ── DEBT-W1: live logging wiring (D129 B.1-B.4) ───────────────────

    def _wire_live_logging(self) -> None:
        """DEBT-W1: connect the D129 log modules to this orchestrator.

        Lazy + fail-safe: called once from run(). Log-dir convention is
        the sibling ``logs/`` of state_dir (production: repo-root/state
        → repo-root/logs; tests: tmp/state → tmp/logs). Any failure
        degrades to an ERROR audit event — the trading loop must never
        crash because a human-readable log could not be created.
        """
        if self._log_wired:
            return
        try:
            log_dir = str(Path(self.state_dir).parent / "logs")
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            self._log_dir = log_dir
            self._console = ConsoleReporter()
            lg = canli_trade_logger()
            has_target = any(
                isinstance(h, DailyUtcFileHandler)
                and str(getattr(h, "log_dir", "")) == str(Path(log_dir))
                for h in lg.handlers
            )
            if has_target:
                self._canli_log = lg
            else:
                # Stale/foreign handlers (a handler for ANOTHER log_dir from
                # an earlier session object, or test-harness capture handlers
                # attached mid-run) would silently redirect the daily file —
                # log lines succeed while the expected file never appears.
                # Reconfigure fresh so THIS orchestrator's file convention is
                # guaranteed. Production is unaffected (fresh process → empty
                # handler list → setup runs exactly once, singleton intact).
                for h in list(lg.handlers):
                    lg.removeHandler(h)
                self._canli_log = setup_canli_trade_log(log_dir=log_dir)
            self._trade_writer = TradeHistoryWriter(
                path=str(Path(log_dir) / TRADE_HISTORY_FILENAME)
            )
            self._log_wired = True
            verdict_name = "-"
            if self._startup_result is not None:
                verdict_name = str(
                    getattr(self._startup_result.verdict, "name", self._startup_result.verdict)
                )
            self._canli_info(f"STARTUP symbol={self._symbol or '-'} verdict={verdict_name}")
            self.audit.append(
                time.time(),
                EventType.STARTUP,
                self._symbol or None,
                {"phase": "live_logging_init", "log_dir": log_dir, "status": "wired"},
            )
        except Exception as e:
            self._log_wired = False
            try:
                self.audit.append(
                    time.time(),
                    EventType.ERROR,
                    self._symbol or None,
                    # A1 (OBS-P0): exception type + sinirli traceback kalici
                    error_payload(e, phase="live_logging_init", status="degraded"),
                )
            except Exception:
                pass  # forensics must never mask the original failure

    def _canli_info(self, msg: str) -> None:
        """Write one line to the canli_trade daily log (guarded no-op)."""
        if self._canli_log is not None:
            try:
                self._canli_log.info(msg)
            except Exception:
                pass

    def _emit_gate(self, gate_allowed: bool, reason: str) -> None:
        """DEBT-W1: gate transition → console + canli log.

        Called from the run() transition block AFTER the SAFETY audit
        append — the machine journal stays authoritative; this layer is
        the human-readable mirror (D129 B.1/B.2).
        """
        if not self._log_wired:
            return
        try:
            line = f"GATE {'OPEN' if gate_allowed else 'CLOSED'}: {reason}"
            if self._console is not None:
                self._console.emit(self._symbol, "gate", line)
            self._canli_info(line)
        except Exception:
            pass

    def _emit_bar_pulse(self, new_bars: List[Any], gate_allowed: bool, reason: str) -> None:
        """Adım-6 "Why No Signal" pulse (SOAK-D3/D4; Hakem-onaylı).

        BAR-BAZLI (poll-bazlı DEĞİL): called ONLY when produce_new_bars()
        returned >=1 new 15m bar — ~96 lines/day, not ~4300. Gate-
        durumundan bağımsız nabız: SAFE_START sessizliğini (SOAK-D2:
        3s18dk audit-sessizliği) her 15m'de kendini-kanıtlayan tek
        satırla kırar. Kanal-deseni: audit-STATE (moment=bar_pulse) +
        canli-log; console-emit ATLANIR (dedup-key gürültüsü; canli-log
        yeterli). Fail-safe: pulse hatası asla döngüyü düşürmez
        (sessiz-guard, _emit_gate deseni).

        B1 (OBS-P0 karar-kilidi 2026-09-09): guard artık İKİ-KATMANLIDIR —
        ``_log_wired`` YALNIZ insan-okunur canli-log satırını korur;
        makine-journal (audit STATE append) wiring-başarısızlığından
        BAĞIMSIZDIR. Gerekçe: ``_wire_live_logging`` hatası (ERROR
        "degraded", :1233-1241) ``_log_wired=False`` bırakır; eski tek-
        guard altında bu, SOAK-D2 makine-sessizliğini journal'a geri
        getiriyordu — tam da gözlem-kör-noktasını kapatan nabzın kendisi
        körleşiyordu. Audit-append'in tek bağı new_bars (bar-bazlılık)
        kalır; davranış-nötr (karar-değiştirmez), emit-only.
        """
        if not new_bars:
            return
        try:
            last = new_bars[-1]
            bar_ts = getattr(last, "timestamp", None)
            bar_ts_iso = bar_ts.isoformat() if bar_ts is not None else "-"
            if self._log_wired:
                line = (
                    f"[BAR] {self._symbol or '-'} {bar_ts_iso} "
                    f"gate={'OPEN' if gate_allowed else 'CLOSED'} "
                    f"reason={reason or 'ok'} skip"
                )
                self._canli_info(line)
            self.audit.append(
                time.time(),
                EventType.STATE,
                self._symbol,
                {
                    "moment": "bar_pulse",
                    "bar_ts": bar_ts_iso,
                    "bar_index": int(getattr(last, "index", -1)),
                    "gate": "open" if gate_allowed else "closed",
                    "reason": reason or "ok",
                },
            )
        except Exception:
            pass

    def _log_exit_deal(self, entry: Any) -> None:
        """DEBT-W1: poll_deals exit payload → console/canli line + record.

        Only status="recorded" produces a trade_history record: a
        quarantined exit has no open-trade context here, and re-deriving
        the mapping would duplicate TradeLifecycle as a second source of
        truth (§2.2). The audit EXIT event remains authoritative.
        """
        if not self._log_wired or not isinstance(entry, dict) or "error" in entry:
            return
        deal_id = entry.get("deal_id") or 0
        if not deal_id or deal_id in self._exit_keys_logged:
            return
        self._exit_keys_logged.add(deal_id)
        try:
            position_id = entry.get("position_id") or 0
            status = str(entry.get("status", "unknown"))
            cash = float(entry.get("cash", 0.0) or 0.0)
            pnl_r = float(entry.get("pnl_r", 0.0) or 0.0)
            line = (
                f"EXIT deal={deal_id} pos={position_id} status={status} "
                f"cash={cash:.2f} pnl_r={pnl_r:.2f}"
            )
            if self._console is not None:
                self._console.emit(self._symbol, f"exit:{deal_id}", line)
            self._canli_info(line)
            if status == "recorded":
                self._write_trade_record(entry, position_id)
        except Exception:
            pass

    def _write_trade_record(self, entry: Dict[str, Any], position_id: int) -> None:
        """Build the canonical D129-B.4 trade record for a recorded exit.

        Real fields come from OpenTradeContext (entry side/price/SL) and
        the poll payload (pnl_r, exit price/time when the broker deal
        carries them). Unknowns stay explicit defaults; the audit EXIT
        event remains the authoritative forensic record.
        """
        if self._trade_writer is None:
            return
        lc = self._lifecycle
        if lc is None and self._runner is not None:
            lc = getattr(self._runner, "lifecycle", None)
        ctx = None
        if lc is not None:
            open_trades = getattr(lc, "open_trades", {}) or {}
            try:
                ctx = open_trades.get(int(position_id))
            except (TypeError, ValueError):
                ctx = None
        if ctx is None:
            return  # unmapped — no fabricated context
        record = make_trade_record(
            symbol=str(getattr(ctx, "symbol", "") or self._symbol),
            direction=str(getattr(ctx, "side", "long")),
            cbdr_context={},
            entry_time=0.0,
            entry_price=float(getattr(ctx, "entry_price", 0.0) or 0.0),
            fvg=None,
            trigger="",
            initial_sl=float(getattr(ctx, "initial_sl", 0.0) or 0.0),
            initial_tp=0.0,
            trailing_hops=[],
            exit_time=float(entry.get("time", 0.0) or 0.0),
            exit_price=float(entry.get("price", 0.0) or 0.0),
            exit_reason="unknown",
            r_realized=float(entry.get("pnl_r", 0.0) or 0.0),
            risk_multiplier_used=float(getattr(ctx, "lot_multiplier", 1.0) or 1.0),
            duration_bars=0,
        )
        record["source"] = "DEBT-W1-wiring"
        self._trade_writer.write(record)

    def startup(self) -> StartupResult:
        """Run S0→S11 startup sequence with lock ownership contract.

        Returns StartupResult with verdict:
          PROCEED    → clean startup, lock held
          SAFE-START → degraded but survivable, lock held
          FATAL      → lock released by this method

        D24 (Taş 2): when a persisted safe-mode file exists from a prior
        run, phases STILL execute (operator sees current state via audit);
        verdict is forced to SAFE_START with the persisted reason included.
        """
        # ── Acquire lock ──────────────────────────────────────────
        try:
            self.lock.acquire()
        except LockError as e:
            return StartupResult(
                verdict=StartupVerdict.FATAL,
                phase=StartupPhase.S0_CONFIG,
                reason=f"lock_conflict: {e}",
            )

        # ── Read persisted safe-mode (D24: do NOT short-circuit) ──
        safe = self._read_safe_mode()
        if safe is not None:
            self._persisted_safe_reason = str(safe.get("reason", "unknown"))

        try:
            result = self._run_phases()
            self._startup_result = result  # Taş 3: run() consumes this
            return result
        except Exception as e:
            self.lock.release()
            fatal = StartupResult(
                verdict=StartupVerdict.FATAL,
                phase=StartupPhase.S0_CONFIG,
                reason=f"unexpected: {type(e).__name__}: {e}",
            )
            self._startup_result = fatal
            return fatal

    def _run_phases(self) -> StartupResult:
        # ── S0: Config ──────────────────────────────────────────
        # N2 #21 madde-5: advertise the startup lifecycle on the lock
        # body (immediate in-place write, Katman-4 nonfatal on failure).
        self.lock.set_phase("S0_config")
        try:
            config = get_mt5_config()
        except ValueError as e:
            self.lock.release()
            return StartupResult(
                verdict=StartupVerdict.FATAL,
                phase=StartupPhase.S0_CONFIG,
                reason=f"config_invalid: {e}",
            )

        # ── S1: Connect ─────────────────────────────────────────
        # İŞ-4a S1 (D159): cTrader-first boot. When the injected data
        # connection is a cTrader adapter (duck-typed: no `connect`
        # attribute — MT5Connection HAS connect(), the adapter does not),
        # the MetaTrader5 module import is SKIPPED entirely. MT5-ölü
        # ortamda `import MetaTrader5` FATAL ("mt5_import_failed")
        # üretiyordu — cTrader-üretim-yolu artık birincil. MT5 yolu
        # DEĞİŞMEDİ (aynı import → init → login zinciri çalışır);
        # sessiz-fallback YOK (§19): mode seçimi yalnızca enjekte-edinlen
        # bağlantı-niteliğiyle belirlenir, env-bayrağıyla DEĞİL — yanlış
        # wiring görünür bir hata üretir, sessizce MT5'e düşmez.
        self.lock.set_phase("S1_connect")
        ctrader_mode = self._mt5_conn is not None and not hasattr(self._mt5_conn, "connect")
        if ctrader_mode:
            # cTrader birincil: adapter'ın bağlantı-kurulumu burada yapılır
            # (reactor-thread + app-auth + account-auth zinciri). ensure_connected
            # kısa-poll; fail-loud FATAL — cannot-reach-data = cannot-run.
            try:
                connected = self._mt5_conn.ensure_connected(max_attempts=5)
            except Exception as e:
                self.lock.release()
                return StartupResult(
                    verdict=StartupVerdict.FATAL,
                    phase=StartupPhase.S1_CONNECT,
                    reason=f"ctrader_connect_exception: {type(e).__name__}: {e}",
                )
            if not connected:
                self.lock.release()
                return StartupResult(
                    verdict=StartupVerdict.FATAL,
                    phase=StartupPhase.S1_CONNECT,
                    reason="ctrader_connect_failed",
                )
            self._ctrader_mode = True
            self.audit.append(
                time.time(),
                EventType.MT5_CONNECT,
                self.configured_symbols[0] if self.configured_symbols else None,
                {"transport": "ctrader", "phase": "S1_connect"},
            )
        else:
            try:
                import MetaTrader5 as mt5_mod

                self._mt5 = mt5_mod
            except ImportError:
                self.lock.release()
                return StartupResult(
                    verdict=StartupVerdict.FATAL,
                    phase=StartupPhase.S1_CONNECT,
                    reason="mt5_import_failed",
                )

        # Construct MT5Connection (production fetch path) if injected.
        # Taş 2 test seam: MT5Connection is NOT auto-constructed here
        # because it binds MetaTrader5 at import time and cannot be
        # redirected via sys.modules patching in tests. Production
        # wires this in `run_production.py` (future Taş) by passing
        # `mt5_conn=MT5Connection()` to the Orchestrator constructor.
        # When unset, _fetch_m1_tri_state falls back to self._mt5 (test
        # seam). B2 lesson (Taş 4 delta, S5): a silent seam must never be
        # silent in production - surface it in the audit chain.
        if self._mt5_conn is None and not ctrader_mode:
            self.audit.append(
                time.time(),
                EventType.SAFETY,
                None,
                {"phase": "S1_connect", "warning": "mt5_conn_unset_test_seam_active"},
            )

        if ctrader_mode:
            # İŞ-4a S1: cTrader-mode skips the MT5 initialize/login chain
            # AND the S2 account_info/terminal_info reads (they are MT5
            # module calls). Identity is established by the cTrader
            # account-auth inside ensure_connected().
            # İŞ-6 (DİREKTİF-14): the account snapshot is now FETCHED via
            # ProtoOATrader (real balance/equity/leverage/currency) instead
            # of explicit zeros. Fail-soft: fetch failure → explicit zeros
            # (existing fail-safe semantics preserved) + audit/uyarı-beyanlı.
            account_state = self._fetch_ctrader_account_state()
            account_dict = {
                "login": str(self._mt5_conn.config.get("account_id", "")),
                "server": str(self._mt5_conn.config.get("host", "")),
                "balance": account_state["balance"],
                "equity": account_state["equity"],
                "currency": account_state["currency"],
                "leverage": account_state["leverage"],
                "margin_level": 0.0,
                "account_source": account_state["source"],
            }
            terminal_dict = None
            self.audit.append(
                time.time(),
                EventType.MT5_CONNECT,
                self.configured_symbols[0] if self.configured_symbols else None,
                {
                    "transport": "ctrader",
                    "phase": "S2_identity",
                    "account": account_dict,
                    "note": (
                        "account_state_fetched_ctrader_mode"
                        if account_state["source"] == "real"
                        else "account_state_fail_soft_ctrader_mode"
                    ),
                },
            )
            # D12 identity check: MT5_EXPECTED_LOGIN is an MT5-path flag.
            # In cTrader mode the identity is the ctidTraderAccountId from
            # config; a set MT5_EXPECTED_LOGIN cannot match it — surface a
            # WARN (not FATAL, not silent) and continue.
            expected_login = self.config.expected_login or os.getenv("MT5_EXPECTED_LOGIN")
            if expected_login:
                self.audit.append(
                    time.time(),
                    EventType.SAFETY,
                    self.configured_symbols[0] if self.configured_symbols else None,
                    {
                        "phase": "S2_identity",
                        "warning": "expected_login_is_mt5_flag_ignored_in_ctrader_mode",
                        "expected_login": str(expected_login),
                    },
                )
            safe_reasons: List[str] = []
        else:
            terminal_path = config.get("terminal_path", "")
            try:
                if terminal_path:
                    init_ok = self._mt5.initialize(path=terminal_path)
                else:
                    init_ok = self._mt5.initialize()
            except Exception as e:
                self.lock.release()
                return StartupResult(
                    verdict=StartupVerdict.FATAL,
                    phase=StartupPhase.S1_CONNECT,
                    reason=f"initialize_exception: {e}",
                )

            if not init_ok:
                self.lock.release()
                return StartupResult(
                    verdict=StartupVerdict.FATAL,
                    phase=StartupPhase.S1_CONNECT,
                    reason="initialize_failed",
                )

            try:
                login_ok = self._mt5.login(
                    login=int(config["login"]),
                    password=config["password"],
                    server=config["server"],
                )
            except Exception as e:
                self.lock.release()
                return StartupResult(
                    verdict=StartupVerdict.FATAL,
                    phase=StartupPhase.S1_CONNECT,
                    reason=f"login_exception: {e}",
                )

            if not login_ok:
                self._mt5.shutdown()
                self.lock.release()
                return StartupResult(
                    verdict=StartupVerdict.FATAL,
                    phase=StartupPhase.S1_CONNECT,
                    reason="login_failed",
                )

            # ── S2: Account + Identity ──────────────────────────
            self.lock.set_phase("S2_identity")
            try:
                account_info = self._mt5.account_info()
            except Exception as e:
                self.lock.release()
                return StartupResult(
                    verdict=StartupVerdict.FATAL,
                    phase=StartupPhase.S2_IDENTITY,
                    reason=f"account_info_exception: {e}",
                )

            if account_info is None:
                self._mt5.shutdown()
                self.lock.release()
                return StartupResult(
                    verdict=StartupVerdict.FATAL,
                    phase=StartupPhase.S2_IDENTITY,
                    reason="account_info_none",
                )

            try:
                terminal_info = self._mt5.terminal_info()
            except Exception:
                terminal_info = None

            account_dict = {
                "login": str(getattr(account_info, "login", "")),
                "server": str(getattr(account_info, "server", "")),
                "balance": float(getattr(account_info, "balance", 0.0)),
                "equity": float(getattr(account_info, "equity", 0.0)),
                "currency": str(getattr(account_info, "currency", "USD")),
                "leverage": int(getattr(account_info, "leverage", 0)),
                "margin_level": float(getattr(account_info, "margin_level", 0.0)),
            }
            terminal_dict = None
            if terminal_info is not None:
                terminal_dict = {
                    "build": int(getattr(terminal_info, "build", 0)),
                    "path": str(getattr(terminal_info, "path", "")),
                    "trade_allowed": bool(getattr(terminal_info, "trade_allowed", False)),
                }

            self.audit.append(
                time.time(),
                EventType.MT5_CONNECT,
                self.configured_symbols[0] if self.configured_symbols else None,
                {"account": account_dict, "terminal": terminal_dict},
            )

            # ── S2 identity check (D12, Taş 2 hardened) ─────────
            # Empty/unset expected_login → warn + SAFE-START (not FATAL).
            # Set + mismatch → FATAL. Set + match → clean.
            # NEW-1 (redelivery 4): terminal_info.trade_allowed == 0 →
            # SAFE_START (terminal present but trading disabled).
            expected_login = self.config.expected_login or os.getenv("MT5_EXPECTED_LOGIN")
            d12_safe_pending: List[str] = []
            if expected_login:
                actual_login = account_dict["login"]
                if actual_login != str(expected_login):
                    self._mt5.shutdown()
                    self.lock.release()
                    return StartupResult(
                        verdict=StartupVerdict.FATAL,
                        phase=StartupPhase.S2_IDENTITY,
                        reason=f"identity_mismatch: expected={expected_login} actual={actual_login}",
                    )
            else:
                d12_safe_pending.append("expected_login_unset")

            # NEW-1: trade_allowed == 0 -> SAFE_START.
            if terminal_dict is not None and not terminal_dict.get("trade_allowed", True):
                d12_safe_pending.append("trade_allowed_disabled")

            safe_reasons: List[str] = list(d12_safe_pending)

        # ── S3: ContractSpec ────────────────────────────────────
        self.lock.set_phase("S3_contract")
        if not self.configured_symbols:
            self.lock.release()
            return StartupResult(
                verdict=StartupVerdict.FATAL,
                phase=StartupPhase.S3_CONTRACT,
                reason="no_configured_symbols",
            )
        self._symbol = self.configured_symbols[0]

        # D33: construct lifecycle + recovery + runtime EARLY so S5 can
        # inject them into the LiveRunner. Restoration happens in S7
        # (mutates the same object the runner already holds by reference).
        self._recovery = RuntimeRecovery(str(self.state_dir), on_block=self._on_write_block)
        # N2 #23 R-1: the runtime carries the audit sink so the CBDR STATE
        # observation layer (strategy_runtime.on_bar consumption point) can
        # emit into the SAME chain the orchestrator owns.
        self._runtime = StrategyRuntime(self._symbol, audit=self.audit)
        self._lifecycle = TradeLifecycle()
        self._sizer = PositionSizer()
        self._risk_manager = RiskManager()

        contract = self._build_contract(self._symbol)
        if contract is None:
            safe_reasons.append("contract_build_failed")
        else:
            self._contract = contract
            # D30: surface trade_mode != FULL as a safe_reason (builder
            # must NOT return None here — it returns the spec + flag).
            if not self._trade_mode_ok:
                safe_reasons.append("trade_mode_not_full")
        contract_dict = contract.__dict__ if contract else None

        # ── S4: Margin level ────────────────────────────────────
        self.lock.set_phase("S4_margin")
        # _safe() heuristic: margin_level_low maps to S4 (not S2).
        margin_level = float(account_dict.get("margin_level", 0.0))
        if margin_level > 0 and margin_level < self.config.margin_level_min_pct:
            safe_reasons.append(
                f"margin_level_low: {margin_level:.1f}% < {self.config.margin_level_min_pct:.0f}%"
            )

        # ── S5: Broker snapshot (Taş 2 — INJECTION) ────────────
        self.lock.set_phase("S5_snapshot")
        # Orchestrator OWNS contract / lifecycle / runtime / sizer / risk_manager
        # and hands them to the LiveRunner by reference. The live_runner
        # constructor is NOT edited.
        from src.live.live_runner import LiveRunner

        snapshot: Dict[str, Any] = {
            "mt5_connected": False,
            "reconciliation": {
                "status": "NOT_RUN",
                "block_trading": True,
                "details": [],
            },
            "safe_mode": True,
            "positions": [],
            "pending_orders": [],
        }
        try:
            # D38: retain the REAL LiveRunner instance on the orchestrator
            # so the process-lifetime loop uses the SAME object identity.
            # No second LiveRunner is ever reconstructed.
            # İŞ-7 (SEÇENEK-C): cTrader mode → CTraderExecution inject edilir
            # (MT5-Execution ASLA kullanılmaz — sessiz-fallback yasağı §19).
            # Fail-closed: _build_ctrader_execution() başarısızsa execution=None
            # → LiveRunner.on_bar emir gönderemez (execution_unavailable_fail_closed).
            execution = self._build_ctrader_execution() if self._ctrader_mode else None
            self._runner = LiveRunner(
                symbol=self._symbol,
                mt5=self._mt5,
                execution=execution,
                audit=self.audit,
                magic=self.magic,
                signal_only=self.config.signal_only,
                contract=self._contract,
                lifecycle=self._lifecycle,
                runtime=self._runtime,
                sizer=self._sizer,
                risk_manager=self._risk_manager,
            )
            # İŞ-4a S5 (D159, karar-5): in cTrader mode the LiveRunner is
            # CONSTRUCTED but startup_snapshot() is NOT called — the MT5
            # module calls inside it would fail on mt5=None and flip
            # safe_mode=True, whose persistence (§7.2) would then force
            # every future boot into SAFE-START (safe-mode persist loop).
            # Instead we hand-build the snapshot shape. Reconciliation is
            # now REAL: adapter.get_positions() fetches broker positions via
            # ProtoOAReconcileReq and the Reconciler compares them against
            # the local lifecycle state (same pure function the MT5 path
            # uses — §2.2, no duplicate source of truth). The NOT_RUN
            # hardcoded string is replaced by the real ReconcileStatus.
            if self._ctrader_mode:
                snapshot = self._build_ctrader_snapshot()
            else:
                snapshot = self._runner.startup_snapshot(configured_symbols=self.configured_symbols)
        except Exception as e:
            safe_reasons.append(f"snapshot_failed: {type(e).__name__}")

        # ── S6: SL/TP audit from snapshot ──────────────────────
        self.lock.set_phase("S6_sltp_audit")
        positions = snapshot.get("positions", [])
        sltp_issues = []
        for p in positions:
            if p.get("sl", 0.0) <= 0:
                sltp_issues.append(f"position {p.get('ticket')} missing SL")
        if sltp_issues:
            safe_reasons.append("sltp_audit_unprotected_positions")
            self.audit.append(
                time.time(),
                EventType.SAFETY,
                self._symbol,
                {"phase": "S6", "issues": sltp_issues},
            )

        # ── S7: Local state recovery (D33, redelivery 2) ──────────
        self.lock.set_phase("S7_recovery")
        # load() restores the runtime (bars buffer + FVG state);
        # load_lifecycle() restores the journal + DD from disk.
        # Partial restore: lifecycle OK + runtime cold → NOT a warm
        # continuation → fall through to full warmup, but keep the
        # restore-seeded slot/index seeds, and surface a safe_reason.
        self._runtime_restored = False
        self._lifecycle_restored = False
        try:
            self._runtime_restored = bool(self._recovery.load(self._runtime, self._symbol))
        except Exception as e:
            safe_reasons.append(f"recovery_failed: {type(e).__name__}")
        if self._lifecycle is not None:
            try:
                if self._recovery.load_lifecycle(self._lifecycle, self._symbol):
                    self._lifecycle_restored = True
            except Exception as e:
                safe_reasons.append(f"lifecycle_recovery_failed: {type(e).__name__}")
        runtime_warmed_at_s7 = bool(getattr(self._runtime, "_warmed", False))
        if self._lifecycle_restored and not runtime_warmed_at_s7:
            # D49 (C3): lifecycle state survived but the runtime did not warm
            # -> a cold rebuild is REQUIRED. This is VISIBLE (WARN audit +
            # alert) but NOT a SAFE_START reason: if the rebuild succeeds in
            # S9, the verdict reverts to PROCEED. Forcing SAFE_START here
            # would doom every weekend / partial-restore restart to safe mode.
            self._cold_rebuild_needed = True
            # D49 B-1: partial restore — invalidate restored pipeline state
            # here so _seed_restore_state() later in _warmup seeds nothing.
            self._begin_cold_rebuild()
            self.audit.append(
                time.time(),
                EventType.ERROR,
                self._symbol,
                {"phase": "S7", "warning": "restore_partial_cold_runtime_rebuild_required"},
            )
        self._restored = bool(self._runtime_restored or self._lifecycle_restored)

        # ── S8: Recon gate ──────────────────────────────────────
        self.lock.set_phase("S8_recon_gate")
        recon = snapshot.get("reconciliation", {})
        recon_status = recon.get("status", "NOT_RUN")
        if recon_status != "OK":
            if recon.get("block_trading", False):
                safe_reasons.append(f"recon_blocked: {recon_status}")

        # ── S9: Warmup + real-terminal smoke (D28/D33) ─────────
        self.lock.set_phase("S9_warmup")
        warmup_count = getattr(self.config, "m1_warmup_count", 65000)
        warmup_ok = False
        warmup_bars = 0
        smoke_result: dict = {"errors": [], "reason": "not_run"}
        try:
            warmup_ok, warmup_bars, smoke_result = self._warmup(warmup_count)
        except Exception as e:
            safe_reasons.append(f"warmup_exception: {type(e).__name__}: {e}")
        if not warmup_ok:
            safe_reasons.append(f"warmup_failed: {smoke_result.get('reason', 'unknown')}")

        # C3: a cold rebuild (stale / partial restore) must be VISIBLE but not
        # silently demote the verdict. If the rebuild succeeded, emit WARN +
        # alert; PROCEED is unaffected (feed + sizing now use correct state).
        if self._cold_rebuild_needed and warmup_ok:
            replay = (self._replay_report or {}).get("replay_bars", 0)
            self.alert.send(
                "WARN",
                f"cold rebuild OK — runtime restored from full history (replay_bars={replay})",
            )
            self.audit.append(
                time.time(),
                EventType.STARTUP,
                self._symbol,
                {
                    "phase": "S9",
                    "verdict": "COLD_REBUILD_OK",
                    "replay_bars": replay,
                },
            )

        # Heartbeat (Taş 2): healthy S9 completion touches the lock so a
        # long healthy process is not misclassified as stale.
        self.lock.heartbeat()

        # D24: prepend persisted safe-mode reason if present.
        if self._persisted_safe_reason is not None:
            safe_reasons.insert(0, f"safe_mode_persisted: {self._persisted_safe_reason}")

        # ── S11: READY ──────────────────────────────────────────
        self.lock.set_phase("S11_ready")
        if safe_reasons:
            # KARAR-Commit-2 (dedupe): collapse nested safe_mode_persisted:
            # chains and repeated entries so the persisted reason string is
            # bounded (observed 14× chain in PRECLEAR). Safe-file semantics
            # unchanged — the tag is still written once, the read path is
            # untouched; only the accumulated reason string is deduped.
            reason = _dedupe_safe_reason("; ".join(safe_reasons))
            self._write_safe_mode(reason)
            self.audit.append(
                time.time(),
                EventType.STARTUP,
                self._symbol,
                {
                    "phase": "S11",
                    "verdict": "SAFE_START",
                    "safe_reasons": safe_reasons,
                    "warmup_bars": warmup_bars,
                    "restored": self._restored,
                    # İŞ-6 (DİREKTİF-14): boot-beyanı — account-state
                    # (real values or fail-soft 0.0, source-tagged).
                    "account_state": {
                        k: account_dict.get(k)
                        for k in ("balance", "equity", "leverage", "currency", "account_source")
                    },
                },
            )
            return StartupResult(
                verdict=StartupVerdict.SAFE_START,
                phase=StartupPhase.S9_WARMUP,
                reason=reason,
                account=account_dict,
                terminal=terminal_dict,
                snapshot=snapshot,
                contract=contract_dict,
                warmup_bars=warmup_bars,
                errors=smoke_result.get("errors", []),
            )

        self.audit.append(
            time.time(),
            EventType.STARTUP,
            self._symbol,
            {
                "phase": "S11",
                "verdict": "PROCEED",
                "warmup_bars": warmup_bars,
                "contract": contract_dict.get("symbol") if contract_dict else None,
                "restored": self._restored,
                # İŞ-6 (DİREKTİF-14): boot-beyanı — account-state
                # (real values or fail-soft 0.0, source-tagged).
                "account_state": {
                    k: account_dict.get(k)
                    for k in ("balance", "equity", "leverage", "currency", "account_source")
                },
            },
        )
        return StartupResult(
            verdict=StartupVerdict.PROCEED,
            phase=StartupPhase.S11_READY,
            reason="ok",
            account=account_dict,
            terminal=terminal_dict,
            snapshot=snapshot,
            contract=contract_dict,
            warmup_bars=warmup_bars,
        )

    def release_lock(self) -> None:
        """Explicit lock release for shutdown (Taş 4)."""
        self.lock.release()

    def _audit_fallback_dump(self, phase: str, err: Exception) -> None:
        """N2 #17 Katman-5/A8: dump buffered audit events to the K2
        crash-log when the audit flush target itself is blocked.

        The terminal events must survive the process by SOME channel —
        the crash-log is the flush-independent forensic floor (same
        mechanism as the exhausted-budget routing in _atomic_write_text).
        Never raises.
        """
        try:
            lines = [
                json.dumps(evt.to_dict(), default=str, sort_keys=True) for evt in self.audit.events
            ]
        except Exception:
            return
        _crash_log_append(
            _CRASH_LOG,
            {
                "kind": "AUDIT_FALLBACK_DUMP",
                "pid": os.getpid(),
                "phase": phase,
                "error": f"{type(err).__name__}: {err}",
                "events": lines,
            },
        )

    def shutdown(self, exit_code: int = 0, reason: str = "shutdown") -> None:
        """Taş 4 (B-a): idempotent graceful teardown, safe to call from ANY
        exit path (kill, ownership-lost, safe-mode, strategy exception).

        Guarantees:
          - SHUTDOWN audit event is recorded exactly once (B-a: the
            ownership-lost path previously wrote only ERROR, no SHUTDOWN).
          - audit chain is flushed to disk (final flush).
          - MT5 terminal is shut down (release the broker handle).
          - lock is released (only if we own it).
        Idempotent: a second call is a no-op.
        """
        if getattr(self, "_shutdown_done", False):
            return
        self._shutdown_done = True

        # DEBT-W1: final human-readable line. Guarded — shutdown() may run
        # before run() ever wired the logging layer (log_wired False → no-op).
        if self._log_wired:
            try:
                line = f"SHUTDOWN exit={exit_code} reason={reason}"
                self._canli_info(line)
                if self._console is not None:
                    self._console.emit(self._symbol, "shutdown", line)
            except Exception:
                pass  # teardown must never fail on a log line

        # B-a: record a SHUTDOWN event if none was already written for this
        # exit (run() writes one on the kill paths; ownership-lost did not).
        has_shutdown = any(
            getattr(e, "event_type", None) == EventType.SHUTDOWN for e in self.audit.events
        )
        if not has_shutdown:
            self.audit.append(
                time.time(),
                EventType.SHUTDOWN,
                self._symbol or None,
                {"reason": reason, "exit": exit_code},
            )

        # N2 #17 Katman-5 (FIX-SPEC v1.2): the final flush is a
        # FATAL-path guarantee — T0#5/T0#6 lost their terminal audit
        # events because this flush was either blocked or never reached.
        # audit.shutdown() is synchronous here; if the flush target is
        # ITSELF blocked, the buffered events are dumped to the K2
        # crash-log (A8 fallback) so the evidence survives by some
        # channel — never silently.
        try:
            self.audit.shutdown()
        except Exception as e:
            try:
                self._audit_fallback_dump("shutdown_flush", e)
            except Exception:
                pass

        # Release the broker handle (only if we hold it).
        # İŞ-4a S1 (D159): cTrader-mode → conn.stop() (reactor thread +
        # sockets). The adapter has no `shutdown`; MT5Connection HAS
        # `shutdown` (duck-typing check preserved — same branch handles
        # both: hasattr(shutdown) → MT5 path; ctrader_mode → adapter).
        try:
            if self._ctrader_mode:
                if self._mt5_conn is not None and hasattr(self._mt5_conn, "stop"):
                    self._mt5_conn.stop()
            elif self._mt5 is not None and hasattr(self._mt5, "shutdown"):
                self._mt5.shutdown()
        except Exception:
            pass

        # D48: close-save runtime + lifecycle BEFORE releasing the lock so
        # the next boot restores warm state instead of paying full warmup.
        # (Aşama 2 şartı: per-N-bar periodic save - graceful path alone
        # cannot shrink the kill -9 crash window.)
        if self._runtime is not None and self._lifecycle is not None:
            try:
                schedule_snapshot(
                    self._runtime,
                    self._lifecycle,
                    self._symbol,
                    state_dir=str(self.state_dir),
                )
            except Exception as e:
                # K3 (Taş 4 final): teardown must never raise, but a failed
                # close-save must not be silent either — the next boot pays
                # full warmup and the operator must know why.
                try:
                    self.audit.append(
                        time.time(),
                        EventType.ERROR,
                        self._symbol,
                        # A1 (OBS-P0): exception type + sinirli traceback kalici
                        error_payload(e, phase="shutdown_snapshot"),
                    )
                except Exception:
                    pass

        # Release the lock (no-op if not owned / not ours).
        try:
            self.lock.release()
        except Exception:
            pass

    # ── Safe-mode persistence (D24) ──────────────────────────────

    def _safe_path(self) -> Path:
        # D18: absolute path — the process may chdir (systemd WorkingDirectory,
        # cron, watchdog relaunch); a relative state_dir would silently write
        # safe-mode to the wrong cwd. Resolve once against the real cwd.
        return (self.state_dir / self.config.safe_mode_file).resolve()

    def _read_safe_mode(self) -> Optional[dict]:
        path = self._safe_path()
        if not path.exists():
            return None
        try:
            import json

            data = json.loads(path.read_text(encoding="utf-8"))
            return data
        except (OSError, json.JSONDecodeError):
            return None

    def _write_safe_mode(self, reason: str) -> None:
        # D18 + atomic: write to a PID-unique tmp sibling then rename (N2 #15
        # hardening), so a crash mid-write never leaves a truncated/corrupt
        # safe-mode file (which would force a spurious SAFE-START on the next
        # boot). Absolute path via _safe_path().
        path = self._safe_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        import json

        data = {"safe_mode": True, "reason": reason, "ts": time.time()}
        _atomic_write_text(
            path, json.dumps(data, indent=2), encoding="utf-8", on_block=self._on_write_block
        )

    def clear_safe_mode(self) -> None:
        """Clear persisted safe-mode file (manual or after clean reconcile)."""
        path = self._safe_path()
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass

    # ── S3: ContractSpec builder ────────────────────────────────

    def _build_contract(self, symbol: str) -> Optional[ContractSpec]:
        """Build a ContractSpec from live MT5 symbol_info (D3 / D30).

        D3: stops_level = trade_stops_level × point; tick_size/tick_value/
        volume_min-step-max from symbol_info.
        D30: trade_mode != FULL → safe_reason. The builder returns the
        ContractSpec (does NOT return None for this) and sets
        self._trade_mode_ok = False so the caller can append a
        safe_reason in S3.
        """
        if self._mt5 is None or not hasattr(self._mt5, "symbol_info"):
            # İŞ-4a S3 (D159): cTrader-mode has no MT5 symbol_info. We use
            # an EXPLICIT default contract preset for FX majors (beyanlı —
            # audited, not silent): digits=5, tick_size=0.00001,
            # contract_size=100000, volume 0.01..100 step 0.01,
            # stops_level=0.0 (cTrader symbol details would refine this in
            # a later İş item). trade_mode unknown → flagged ok
            # conservatively; sizing uses tick_value which we set
            # conservatively to 1.0 (per-point USD for a 0.00001 tick on a
            # 100k contract — standard FX major value).
            if self._ctrader_mode:
                self._trade_mode_ok = True
                return ContractSpec(
                    symbol=symbol,
                    volume_min=0.01,
                    volume_max=100.0,
                    volume_step=0.01,
                    tick_size=0.00001,
                    tick_value=1.0,
                    contract_size=100000.0,
                    stops_level=0.0,
                    digits=5,
                )
            self._trade_mode_ok = True  # unknown — don't falsely flag
            return None
        try:
            self._mt5.symbol_select(symbol, True)
            si = self._mt5.symbol_info(symbol)
            if si is None:
                self._trade_mode_ok = True
                return None
            point = float(getattr(si, "point", 0.00001))
            stops_level = int(getattr(si, "trade_stops_level", 0))
            digits = getattr(si, "digits", 5)
            tick_value = float(getattr(si, "trade_tick_value", 1.0))
            volume_min = float(getattr(si, "volume_min", 0.01))
            volume_max = float(getattr(si, "volume_max", 100.0))
            volume_step = float(getattr(si, "volume_step", 0.01))
            trade_mode = getattr(si, "trade_mode", 0)
            # D30 (Bug B fix 2026-09-01): MetaTrader5 enum is
            # DISABLED=0, LONGONLY=1, SHORTONLY=2, CLOSEONLY=3, FULL=4.
            # Only FULL (=4) permits new entries. Flag, do not return None.
            # The previous `== 0` check was inverted (assumed 0=FULL).
            self._trade_mode_ok = trade_mode == _SYMBOL_TRADE_MODE_FULL
            return ContractSpec(
                symbol=symbol,
                volume_min=volume_min,
                volume_max=volume_max,
                volume_step=volume_step,
                tick_size=point,
                tick_value=tick_value,
                contract_size=float(getattr(si, "trade_contract_size", 100000.0)),
                stops_level=stops_level * point,  # D3: points → price units
                digits=digits,
            )
        except Exception as e:
            self.audit.append(
                time.time(),
                EventType.ERROR,
                symbol,
                # A1 (OBS-P0): exception type + sinirli traceback kalici
                error_payload(e, phase="S3"),
            )
            return None

    # ── S9: Warmup + real-terminal smoke (D15/D28/D33) ─────────────

    def _warmup(self, m1_count: int) -> Tuple[bool, int, dict]:
        """S9: real-terminal smoke + StrategyRuntime warmup.

        D28 smoke (one-shot, ALWAYS runs — restored or fresh):
            (a) 100 M1 çek → _rates_to_bars → timestamps grid-aligned + UTC
            (b) son kapalı M1 ≈ now − 1min (toleranslı)
            (c) 15m slot alignment D19 ile tutarlı.

        D15: uses _rates_to_bars + is_closed_m1 + resample_15m (import, not copy).
        D19 (redelivery): warmup output is filtered to buckets whose slot+15m is
        closed at `now`; their slot-ms is seeded into _seen_bar_slots and
        _global_bar_index is bumped past them. Restore-seeded slots are NEVER
        re-emitted / re-indexed during a cold fall-through warmup.
        D33 (redelivery 2): `self._restored` (any state on disk) is distinct
        from `runtime._warmed` (a valid warm continuation). A lifecycle-only
        restore with a cold runtime is NOT a warm continuation — we fall
        through to full warmup while preserving the restore-seeded slot set
        and index base. The partial-restore safe_reason is emitted in S7.
        D33 (redelivery 3): the D28 100-M1 broker-edge smoke runs EVEN on a
        restored runtime; a smoke failure propagates as warmup failure →
        SAFE-START from `_run_phases` S11.
        D24: no automatic clear_safe_mode() — cleared only by runbook.

        Returns (ok, warmup_bars, smoke_result).
        """
        smoke_result: dict = {"errors": [], "reason": ""}

        # ── D33 (redelivery 2): seed restored slots + index always, so a
        # cold fall-through warmup never re-emits restored buckets.
        if self._runtime is not None:
            self._seed_restore_state()

        # Is the runtime a VALID warm continuation? (runtime restore +
        # previously warmed) vs. merely "some state on disk".
        warm_skip = bool(self._runtime is not None and getattr(self._runtime, "_warmed", False))
        # D49: a warm-restored runtime whose last bar is STALE (downtime /
        # weekend gap > restore_staleness_slots — "2 keep / 3 rebuild") is
        # NOT a valid warm continuation — force a cold rebuild (full fetch +
        # warmup + O2 replay) so CBDR/ATR/bias reflect the current window.
        if warm_skip and self._restore_stale_slots() > self.config.restore_staleness_slots:
            warm_skip = False
            self._cold_rebuild_needed = True
            # D49 B-1: clear restore-seeded slots / index + fresh runtime,
            # so the rebuild replays the FULL history (no gap).
            self._begin_cold_rebuild()

        if self._mt5 is None and not self._ctrader_mode:
            if warm_skip:
                # D49: warm-skip path records an empty replay report (no replay).
                self._replay_report = {
                    "replay_bars": 0,
                    "signals_discarded": 0,
                    "end_state": self._replay_end_state(),
                    "next_idx": int(getattr(self._runtime, "_next_idx", 0) or 0),
                    "session_key": self._cbdr_session_key(),
                    "bias": self._cbdr_bias(),
                }
                smoke_result["reason"] = "restored_warm_no_mt5"
                return True, self._warm_bar_count(), smoke_result
            smoke_result["reason"] = "no_mt5_connection"
            return False, 0, smoke_result

        # ── D28 smoke: fetch 100 M1 bars (redelivery 3 — always runs) ──
        status, payload = self._fetch_m1_tri_state(count=100)
        if status != "OK":
            smoke_result["reason"] = f"smoke_{status.lower()}: {payload}"
            return False, 0, smoke_result
        rates = payload

        m1_bars_all = self._rates_to_bars(rates)
        if not m1_bars_all:
            smoke_result["reason"] = "rates_to_bars_empty"
            return False, 0, smoke_result

        # (a) timestamps grid-aligned + UTC.
        # D45: canonical naive-UTC epoch — pandas .timestamp() assumes UTC,
        # stdlib assumes LOCAL; the modulo check must use one convention.
        for b in m1_bars_all:
            ts_ms = int(_naive_utc_epoch(b.timestamp) * 1000)
            if ts_ms % (60 * 1000) != 0:
                smoke_result["reason"] = "grid_misalign"
                smoke_result["errors"].append(
                    f"M1 timestamp not minute-grid-aligned: {b.timestamp}"
                )
                return False, 0, smoke_result

        # (b) last closed M1 ≈ now - 1min (tolerant ±3 min)
        now = _utcnow_naive()
        closed_m1 = M1CandleFeed.is_closed_m1(m1_bars_all, now=now)
        if closed_m1:
            last_closed = closed_m1[-1].timestamp
            if hasattr(last_closed, "to_pydatetime"):
                last_closed = last_closed.to_pydatetime()
            age = (now - last_closed).total_seconds()
            if age < 0 or age > 3 * 60:
                smoke_result["reason"] = f"stale_last_closed_m1: age={age:.0f}s"
                smoke_result["errors"].append(f"last closed M1 age={age:.0f}s")

        # (c) 15m slot alignment — verify at least one closed bucket exists
        m15_smoke = resample_15m(closed_m1)
        if not m15_smoke:
            smoke_result["reason"] = "no_15m_after_resample"
            return False, 0, smoke_result

        # If the runtime is a warm continuation, skip the heavy full fetch.
        if warm_skip:
            # D49: warm-skip path records an empty replay report (no replay).
            self._replay_report = {
                "replay_bars": 0,
                "signals_discarded": 0,
                "end_state": self._replay_end_state(),
                "next_idx": int(getattr(self._runtime, "_next_idx", 0) or 0),
                "session_key": self._cbdr_session_key(),
                "bias": self._cbdr_bias(),
            }
            smoke_result["reason"] = "restored_warm"
            return True, self._warm_bar_count(), smoke_result

        # ── Full warmup fetch (cold / partial-restore fall-through) ──
        status, payload = self._fetch_m1_tri_state(count=m1_count)
        if status != "OK":
            smoke_result["reason"] = f"warmup_{status.lower()}: {payload}"
            return False, 0, smoke_result
        full_rates = payload

        m1_bars_full = self._rates_to_bars(full_rates)
        closed_full = M1CandleFeed.is_closed_m1(m1_bars_full, now=now)
        m15_full = resample_15m(closed_full)

        # D19 (redelivery 2): skip restore-seeded slots, close-filter the rest.
        # D45: canonical naive-UTC epoch (tz-portable — never stdlib .timestamp()).
        now_ms = int(_naive_utc_epoch(now) * 1000)
        reindexed: List[Bar] = []
        for b in m15_full:
            ts_ms = int(_naive_utc_epoch(b.timestamp) * 1000)
            slot = _slot_floor_ms(ts_ms)
            if slot in self._seen_bar_slots:
                continue  # restored — never re-emit / re-index
            if now_ms < slot + _15M_MS:
                continue  # bucket not yet closed at `now` — drop
            self._seen_bar_slots.add(slot)
            reindexed.append(
                Bar(
                    index=self._global_bar_index,
                    timestamp=b.timestamp,
                    open=b.open,
                    high=b.high,
                    low=b.low,
                    close=b.close,
                    volume=b.volume,
                )
            )
            self._global_bar_index += 1

        if self._runtime is None:
            # N2 #23 R-1: audit sink wired (same chain) — see S3 construction.
            self._runtime = StrategyRuntime(self._symbol, audit=self.audit)

        if not reindexed:
            smoke_result["reason"] = "no_15m_after_close_filter"
            return False, 0, smoke_result

        if reindexed:
            self._last_15m_ts = reindexed[-1].timestamp

        self._runtime.warmup(reindexed)

        if not self._runtime._warmed:
            smoke_result["reason"] = "runtime_warmup_failed"
            return False, 0, smoke_result

        # D49 (O2): synchronous boot-time replay of the remaining history so
        # the runtime reaches the TRUE end-state (CBDR/ATR/bias/session) BEFORE
        # the live loop starts. This closes the "fresh-start CBDR not
        # implemented in orchestration" hole: warmup() stores a PREFIX of
        # reindexed; the rest must be replayed through on_bar (SignalRunner
        # pattern). engine untouched; on_bar appends + advances _next_idx
        # internally, so runtime.bars grows to the full set and the D41
        # loop-backlog is naturally empty afterwards (C1). Replay start is
        # rt._next_idx — hardcode forbidden (C4). Historical signals are
        # counted as discarded (not sent — determinism, C2).
        nxt = int(getattr(self._runtime, "_next_idx", 0) or 0)
        replay_bars = 0
        signals_discarded = 0
        if 0 <= nxt < len(reindexed):
            for bar in reindexed[nxt:]:
                sig = self._runtime.on_bar(bar)
                replay_bars += 1
                if sig is not None:
                    signals_discarded += 1
        self._replay_report = {
            "replay_bars": replay_bars,
            "signals_discarded": signals_discarded,
            "end_state": self._replay_end_state(),
            "next_idx": int(getattr(self._runtime, "_next_idx", 0) or 0),
            "session_key": self._cbdr_session_key(),
            "bias": self._cbdr_bias(),
        }
        # C2: a SINGLE boot summary event — per-signal audit is SignalRunner's
        # job and would spam at boot. Remote visible, not silent.
        self.audit.append(
            time.time(),
            EventType.STARTUP,
            self._symbol,
            {"phase": "S9", "verdict": "REPLAY", "payload": self._replay_report},
        )

        return True, len(reindexed), smoke_result

    # ── D49 helpers ─────────────────────────────────────────────────

    def _restore_stale_slots(self) -> int:
        """Number of 15m slots the restored runtime's last bar is behind now.

        Returns >= 0; a cold/fresh runtime with no bars returns a large
        value (>= threshold) so it is treated as needing full warmup.
        """
        if self._runtime is None:
            return 10**6
        try:
            bars = list(getattr(self._runtime, "bars", []) or [])
        except Exception:
            return 10**6
        if not bars or not hasattr(bars[-1], "timestamp"):
            return 10**6  # unknown state → force rebuild (> any threshold)
        last_ts = bars[-1].timestamp
        last_ms = int(_naive_utc_epoch(last_ts) * 1000)
        slot_last = _slot_floor_ms(last_ms)
        now = self._now_fn() if hasattr(self, "_now_fn") and self._now_fn else _utcnow_naive()
        now_ms = int(_naive_utc_epoch(now) * 1000)
        slot_now = _slot_floor_ms(now_ms)
        return max(0, (slot_now - slot_last) // _15M_MS)

    def _replay_end_state(self) -> str:
        """C2 end-state policy: flat (no open sim trade) vs active_trade."""
        if self._runtime is None:
            return "unknown"
        at = getattr(self._runtime, "active_trade", None)
        if at is not None and not at.get("closed"):
            return "active_trade"
        return "flat"

    def _cbdr_session_key(self) -> Optional[str]:
        if self._runtime is None:
            return None
        try:
            return self._runtime.session.current_cbdr_key
        except Exception:
            return None

    def _cbdr_bias(self) -> Optional[str]:
        if self._runtime is None:
            return None
        try:
            return self._runtime.session.cbdr.daily_bias.value
        except Exception:
            return None

    # ── D49 B-1: cold-rebuild state invalidation ────────────────────

    def _begin_cold_rebuild(self) -> None:
        """D49 B-1: a stale or partial restore invalidates ALL restored
        pipeline state. A rebuild must see the FULL history — never skip
        restored slots (the seen-skip guard exists for the cold
        fall-through path, not for a full rebuild). Fresh StrategyRuntime
        also drops any stale restored active_trade / pending_entry so the
        singlet-lock phantom cannot leak into the live session. C2 is now
        settled (KARAR-2, symbol-based): the entry lock is enforced
        broker-authoritatively in LiveRunner.on_bar/_symbol_entry_locked —
        a live bot position on this symbol blocks new entries on THIS
        symbol only, never globally; determinism is preserved regardless.
        Lifecycle is untouched (D6 — invalidation only on broker-side
        anomalies, never on orchestrator-side restart)."""
        self._seen_bar_slots.clear()
        self._global_bar_index = 0
        self._last_15m_ts = None
        # N2 #23 R-1: fresh rebuild keeps the audit sink (same chain) so the
        # CBDR STATE observation layer survives the identity swap.
        self._runtime = StrategyRuntime(self._symbol, audit=self.audit)
        self._runtime_restored = False

    # ── D33 restore seeding helpers (redelivery 2) ──────────────────

    def _seed_restore_state(self) -> None:
        """Seed `_global_bar_index` + `_seen_bar_slots` from restored
        runtime.bars so a cold fall-through warmup never re-emits /
        re-indexes buckets that were already restored."""
        if self._runtime is None:
            return
        try:
            bars = list(getattr(self._runtime, "bars", []) or [])
        except Exception:
            return
        now = _utcnow_naive()
        # D45: canonical naive-UTC epoch (tz-portable).
        now_ms = int(_naive_utc_epoch(now) * 1000)
        for b in bars:
            if not hasattr(b, "timestamp"):
                continue
            ts_ms = int(_naive_utc_epoch(b.timestamp) * 1000)
            slot = _slot_floor_ms(ts_ms)
            if now_ms >= slot + _15M_MS:
                self._seen_bar_slots.add(slot)
        max_idx = -1
        for b in bars:
            if hasattr(b, "index"):
                max_idx = max(max_idx, int(b.index))
        if max_idx >= 0:
            self._global_bar_index = max(self._global_bar_index, max_idx + 1)
        if bars and hasattr(bars[-1], "timestamp"):
            self._last_15m_ts = bars[-1].timestamp

    def _warm_bar_count(self) -> int:
        """Number of 15m bars currently buffered in the runtime."""
        if self._runtime is None:
            return 0
        try:
            return len(list(getattr(self._runtime, "bars", []) or []))
        except Exception:
            return 0

    # ── D15/D19/D20: Bar pipeline (runtime loop) ────────────────

    def _rates_to_bars(self, rates: Any) -> List[Bar]:
        """Convert MT5 rates (numpy structured array or list of dicts) to Bar list.

        Uses SignalRunner._rates_to_bars (import, not copy — D15).
        Falls back to inline conversion if SignalRunner is not importable.
        """
        try:
            from src.live.signal_runner import SignalRunner

            if hasattr(SignalRunner, "_rates_to_bars"):
                return SignalRunner._rates_to_bars(rates)
        except ImportError:
            pass
        # Fallback: inline conversion
        bars: List[Bar] = []
        for i, r in enumerate(rates):
            try:
                ts = int(r["time"])
                o = float(r["open"])
                h = float(r["high"])
                lo = float(r["low"])
                c = float(r["close"])
                v = float(r["tick_volume"])
            except Exception:
                ts = int(r.time)
                o = float(r.open)
                h = float(r.high)
                lo = float(r.low)
                c = float(r.close)
                v = float(r.tick_volume)
            ts_server = pd.Timestamp(ts, unit="s")
            # Mirror SignalRunner._rates_to_bars routing exactly (fallback
            # path must not diverge): ts_semantics="utc" rows are already
            # canonical UTC; legacy server-time rows keep the historical
            # server→UTC conversion unchanged.
            sem = r.get("ts_semantics", "server") if isinstance(r, dict) else "server"
            if sem == "utc":
                ts_utc = ts_server
            else:
                ts_utc = pd.Timestamp(server_to_utc_historical(ts_server.to_pydatetime()))
            bars.append(
                Bar(
                    index=i,
                    timestamp=ts_utc,
                    open=o,
                    high=h,
                    low=lo,
                    close=c,
                    volume=v,
                )
            )
        return bars

    def produce_new_bars(self) -> List[Bar]:
        """Fetch latest M1, produce new closed 15m candles (D15/D19/D20).

        Implements premature-emit protection (Taş 2 — D19 slot floor):
        - Bar identity is the 15m SLOT (epoch ms floored to 15m grid).
          Same slot never emits twice — tracked in `_seen_bar_slots`.
        - A slot emits only when the FULL 15m bucket has closed at
          `now`, i.e. `now >= slot + 15m`. This is the trailing-edge
          emit rule: a bucket that hasn't fully elapsed is dropped here
          even if it slipped past `is_closed_m1`.
        - D20: Global monotonic index continuity across fetches.

        Returns newly completed 15m bars with proper indices (may be empty).
        On fetch error, increments `_fetch_error_count` and returns [].
        """
        if self._mt5 is None and self._mt5_conn is None:
            return []

        status, payload = self._fetch_m1_tri_state(count=20)
        if status != "OK":
            self._fetch_error_count += 1
            self.audit.append(
                time.time(),
                EventType.ERROR,
                self._symbol,
                {
                    "phase": "bar_pipeline",
                    "error": f"fetch_{status.lower()}: {payload}",
                    "consecutive_errors": self._fetch_error_count,
                },
            )
            return []
        # Reset error counter on a healthy fetch.
        self._fetch_error_count = 0

        rates = payload
        m1_bars_all = self._rates_to_bars(rates)
        now = _utcnow_naive()
        closed_m1 = M1CandleFeed.is_closed_m1(m1_bars_all, now=now)

        # Dedup detection (informational)
        dupes = M1CandleFeed.find_duplicates(closed_m1)
        if dupes:
            self.audit.append(
                time.time(),
                EventType.SAFETY,
                self._symbol,
                {"phase": "bar_pipeline", "duplicates": len(dupes)},
            )

        m15 = resample_15m(closed_m1)

        # D45: canonical naive-UTC epoch (tz-portable).
        now_ms = int(_naive_utc_epoch(now) * 1000)
        new_bars: List[Bar] = []
        for c in m15:
            ts_ms = int(_naive_utc_epoch(c.timestamp) * 1000)
            slot = _slot_floor_ms(ts_ms)
            # D19 (Taş 2): slot-floor identity (NOT a tuple).
            if slot in self._seen_bar_slots:
                continue
            # D19 trailing edge: only emit when the full 15m bucket has
            # closed at `now`. This is the authoritative emit rule —
            # resample_15m + is_closed_m1 can leak a forming bucket
            # (e.g. when count < 16 forces a 1-bar bucket drop), and
            # this check is the final gate.
            if now_ms < slot + _15M_MS:
                continue

            bar = Bar(
                index=self._global_bar_index,
                timestamp=c.timestamp,
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
                volume=c.volume,
            )
            self._global_bar_index += 1
            self._seen_bar_slots.add(slot)
            new_bars.append(bar)

        if new_bars:
            self._last_15m_ts = new_bars[-1].timestamp

        # D42: gap check — a skipped 15m slot between consecutive NEW bars
        # signals a broker data gap (feed interruption / missing bucket).
        # Informational + audit: the strategy still runs on the bars it has,
        # but the gap is surfaced so an operator can reconcile the hole.
        self._check_bar_gaps(new_bars)

        return new_bars

    def _check_bar_gaps(self, new_bars: List[Any]) -> None:
        """D42: detect skipped 15m slots between consecutive new bars.

        Emits a SAFETY audit event + WARN alert when a hole is found.
        Pure/injectable so tests can drive it directly.
        """
        if len(new_bars) < 2:
            return
        gaps = []
        for a, b in zip(new_bars, new_bars[1:]):
            slot_a = _slot_floor_ms(int(_naive_utc_epoch(a.timestamp) * 1000))
            slot_b = _slot_floor_ms(int(_naive_utc_epoch(b.timestamp) * 1000))
            missing = (slot_b - slot_a) // _15M_MS - 1
            if missing > 0:
                gaps.append((slot_a, slot_b, int(missing)))
        if gaps:
            self.audit.append(
                time.time(),
                EventType.SAFETY,
                self._symbol,
                {"phase": "bar_pipeline", "gap_slots": gaps},
            )
            self.alert.send(
                "WARN",
                f"D42 data gap: {len(gaps)} hole(s) in 15m feed "
                f"(missing slots: {[g[2] for g in gaps]})",
            )

    # ── D9 tri-state fetch helper (Blocker 4) ──────────────────────

    def _fetch_m1_tri_state(self, count: int) -> Tuple[str, Any]:
        """Fetch M1 rates with tri-state semantics (D9 / Blocker 4).

        Production path (Taş 2): ``MT5Connection.get_rates(symbol, "M1", count)``
        is the canonical fetch. None or [] both map to ``"ERROR"`` and
        increment the consecutive-error counter; the payload is the
        underlying reason for the audit log.

        Test seam: if ``self._mt5_conn`` is not set (tests inject
        ``self._mt5`` directly), fall back to
        ``self._mt5.copy_rates_from_pos`` so the existing FakeMT5-based
        tests keep working without a global MT5Connection patch.

        Returns:
            ("OK", rates) on success.
            ("ERROR", reason_str) on None/empty/exception.
        """
        try:
            if self._mt5_conn is not None and hasattr(self._mt5_conn, "get_rates"):
                rates = self._mt5_conn.get_rates(self._symbol, "M1", count)
                if rates is None:
                    err = getattr(self._mt5_conn, "last_error", "rates_unavailable")
                    return "ERROR", f"mt5conn_get_rates_none: {err}"
                if len(rates) == 0:
                    return "ERROR", "mt5conn_get_rates_empty"
                return "OK", rates
        except Exception as e:
            return "ERROR", f"mt5conn_get_rates_exception: {e}"

        # Test seam: injected mt5 module with copy_rates_from_pos.
        if self._mt5 is None:
            return "ERROR", "no_mt5"
        try:
            rates = self._mt5.copy_rates_from_pos(
                self._symbol, getattr(self._mt5, "TIMEFRAME_M1", 1), 0, count
            )
        except Exception as e:
            return "ERROR", f"copy_rates_exception: {e}"
        if rates is None:
            return "ERROR", "copy_rates_none"
        if len(rates) == 0:
            return "ERROR", "copy_rates_empty"
        return "OK", rates

    # ── _safe() heuristic (D3/D12/D20 mapping) ────────────────────

    def _safe(self, condition: str) -> Tuple[bool, str]:
        """Map safety conditions to phase + verdict.

        Heuristic (per memory-bank):
            margin_level_low  → S4 (not S2)
            identity_mismatch → FATAL (S2)
            contract_fail     → SAFE_START (S3)
            warmup_fail       → SAFE_START (S9)
            recon_block       → SAFE_START (S8)
        """
        if condition == "margin_level_low":
            return True, "S4"
        if condition == "identity_mismatch":
            return False, "S2"  # FATAL
        if condition in ("contract_fail", "warmup_fail", "recon_block"):
            return True, condition.split("_")[0].upper()
        return True, "unknown"

    # ── Tick loop helper (S9 bar feed for runtime loop) ─────────

    def on_new_bar(self, bar: Bar) -> Any:
        """Feed a new 15m bar into the runtime. Called by the tick loop."""
        if self._runtime is None or not self._runtime._warmed:
            return None
        return self._runtime.on_bar(bar)

    def is_connected(self) -> bool:
        """Check if MT5 connection is alive."""
        # İŞ-4a S1 (D159): cTrader-mode delegates to the adapter.
        if self._ctrader_mode:
            try:
                return bool(self._mt5_conn.is_connected())
            except Exception:
                return False
        if self._mt5 is None:
            return False
        if hasattr(self._mt5, "is_connected"):
            return self._mt5.is_connected()
        try:
            return self._mt5.terminal_info() is not None
        except Exception:
            return False

    # ── TAŞ 3: runtime loop ────────────────────────────────────────

    def _install_signal_handlers(self) -> None:
        """D11: SIGINT/SIGTERM → kill flag. Non-main-thread/test-safe."""
        try:
            import signal

            signal.signal(signal.SIGINT, self._on_signal)
            signal.signal(signal.SIGTERM, self._on_signal)
        except (ValueError, ImportError, AttributeError, OSError):
            pass

    def _on_signal(self, _signum: Any, _frame: Any) -> None:
        self._kill_requested = True

    def _heartbeat_validated(self) -> bool:
        """D35: ownership-verified heartbeat with N2 #17 A2 read-triage.

        Returns False ONLY on unprovable/proven-lost ownership (fatal,
        code 1 — test_ownership_loss_fatal stays valid):

        - Record readable, same pid → refresh → True.
        - Record readable, DIFFERENT pid → D11 ownership loss → False
          (FATAL path UNCHANGED).
        - No lock file on disk → ownership NOT provable (external tamper
          or D36 takeover race window) → False. Never self-reclaim.
        - data None but file EXISTS (A2/A9 triage — the B1 hole): the
          body was read-blocked (OSError, now LOUD crash-logged) or torn
          (A9 LOCK_CORRUPT). Salvage the pid from the raw record:
          ours → refresh nonfatally (Katman-4; a failed refresh write
          stays alive and retries next tick) → True; anything else →
          ownership unprovable → False (hüküm katmaz).
        """
        data = self.lock._read()
        if data is not None:
            if int(data.pid) != os.getpid():
                return False
            self.lock.heartbeat()
            return True
        if not self.lock.lock_path.exists():
            # No lock file on disk — ownership cannot be proven (external
            # tamper or D36 takeover race). Do NOT self-reclaim; report
            # ownership loss so the caller exits (fatal, code 1).
            return False
        salvaged = self.lock.verify_ownership_via_record()
        if salvaged == os.getpid():
            # A2: the JSON body was unreadable (read-blocked or torn)
            # but the raw record still names US. A sharing violation is
            # not ownership evidence — refresh (nonfatal write) and live.
            self.lock.heartbeat()
            return True
        return False

    def _interruptible_sleep(self, seconds: float, kill_fn) -> bool:
        """D46: chunked interruptible sleep.

        PEP 475: a plain time.sleep(300) is NOT interrupted by SIGINT/SIGTERM
        → graceful shutdown would stall up to 300s (systemd SIGKILL → Taş 4
        graceful path skipped). Sleep in <=1s chunks and re-check the kill
        flag between chunks. Returns True if a kill was requested mid-sleep.
        """
        chunk = 1.0
        remaining = float(seconds)
        while remaining > 0:
            if kill_fn():
                return True
            time.sleep(min(chunk, remaining))
            remaining -= chunk
        return False

    def _recon_decision_for_gate(self) -> ReconciliationDecision:
        """D34: safety.check's reconciliation input — NEVER None.

        Startup point-in-time decision; periodic reconcile = Aşama 2 (Task 2.1).
        """
        snap = self._startup_result.snapshot if self._startup_result else None
        rc = (snap or {}).get("reconciliation") or {}
        try:
            status = ReconcileStatus(str(rc.get("status", "NOT_RUN")))
        except ValueError:
            return ReconciliationDecision(
                status=ReconcileStatus.MISMATCH,
                block_trading=True,
                details=[f"snapshot_recon_not_parseable:{rc.get('status')}"],
            )
        return ReconciliationDecision(
            status=status,
            block_trading=bool(rc.get("block_trading", True)),
            details=list(rc.get("details") or []),
        )

    def _build_ctrader_execution(self) -> Optional[Any]:
        """İŞ-7 (SEÇENEK-C): build CTraderExecution for cTrader mode.

        Fail-closed: returns None on any failure → LiveRunner.on_bar blocks
        (execution_unavailable_fail_closed). NEVER falls back to MT5
        Execution (§19 silent-fallback yasağı). symbol_meta carries
        symbol_id + pip_position for the configured symbols; a symbol whose
        symbol_id cannot be resolved is excluded (no order can be built).
        """
        try:
            from src.ctrader.execution import CTraderExecution

            symbol_meta = self._build_ctrader_symbol_meta()
            if not symbol_meta:
                return None
            return CTraderExecution(
                connection=self._mt5_conn,
                audit=self.audit,
                symbol_meta=symbol_meta,
                signal_only=self.config.signal_only,
            )
        except Exception:
            return None

    def _build_ctrader_symbol_meta(self) -> Dict[str, Dict[str, Any]]:
        """İŞ-7: symbol_meta for CTraderExecution.

        symbol_id resolved via the adapter (public resolve_symbol_id);
        pip_position derived from the FX-major contract preset digits
        (EURUSD 5, JPY 3 — D169-§4 dynamic scale). A symbol whose symbol_id
        cannot be resolved is EXCLUDED (fail-closed: no meta → no order).
        """
        meta: Dict[str, Dict[str, Any]] = {}
        symbols = self.configured_symbols or [self._symbol]
        for symbol in symbols:
            symbol_id = None
            try:
                symbol_id = self._mt5_conn.resolve_symbol_id(symbol)
            except Exception:
                symbol_id = None
            if symbol_id is None:
                continue
            digits = int(self._contract.digits) if self._contract else 5
            meta[symbol] = {
                "symbol_id": int(symbol_id),
                "pip_position": digits,
            }
        return meta

    def _build_ctrader_snapshot(self) -> dict:
        """S5 cTrader-mode snapshot with REAL reconciliation (İş-4a).

        Parallel to the MT5 `LiveRunner.startup_snapshot` path — the MT5
        branch is untouched. Fetches broker positions via
        `adapter.get_positions()` (ProtoOAReconcileReq), converts them to
        `Position` objects, and runs the same `Reconciler.reconcile()`
        against the local lifecycle state.

        Fail-loud semantics: a transient fetch failure (None) or an
        exception keeps the gate fail-closed (block_trading=True) with a
        visible reason — never a silent OK. A clean empty state (no local,
        no remote) yields OK (matches the MT5 path's empty-state branch).
        """
        mt5_connected = bool(
            self._mt5_conn.is_connected() if hasattr(self._mt5_conn, "is_connected") else False
        )
        positions_list: List[Dict[str, Any]] = []
        remote_positions: Dict[int, Any] = {}
        unknown_symbol_ids: List[int] = []
        recon_status = "NOT_RUN"
        recon_block = True
        recon_details: List[str] = []
        try:
            contract_size = float(self._contract.contract_size) if self._contract else 100000.0
            raw_positions = self._mt5_conn.get_positions(contract_size=contract_size)
            if raw_positions is None:
                recon_details.append("ctrader_get_positions_transient_failure")
            else:
                for d in raw_positions:
                    positions_list.append(d)
                    if d.get("unknown_symbol_id") is not None:
                        # İŞ-5 PARÇA-B (N2#28): symbol unresolvable → the
                        # ownership scope of this position cannot even be
                        # established (label filtering is meaningless on an
                        # unknown symbol). Feed it to the Reconciler as a
                        # remote position (no label filter) → UNKNOWN_OPEN →
                        # block_trading=True. Silent skip is FORBIDDEN.
                        unknown_symbol_ids.append(int(d["unknown_symbol_id"]))
                        pos = _to_position_ctrader(d, label_filter="")
                    else:
                        pos = _to_position_ctrader(d, CTRADER_BOT_LABEL)
                    if pos is not None:
                        remote_positions[int(pos.ticket)] = pos
                # Local lifecycle state (persisted via state.py — restored
                # in S7; at S5 it reflects the pre-restore object, matching
                # the MT5 path's own S5 timing).
                local_for_recon: Dict[int, Any] = {}
                if self._lifecycle is not None:
                    for pid, ctx in self._lifecycle.open_trades.items():
                        local_for_recon[pid] = ctx
                if local_for_recon or remote_positions:
                    reconciler = Reconciler()
                    decision = reconciler.reconcile(local_for_recon, remote_positions)
                    recon_status = decision.status.value
                    recon_block = decision.block_trading
                    recon_details = list(decision.details)
                else:
                    recon_status = "OK"
                    recon_block = False
                    recon_details = []
        except Exception as e:
            recon_status = "NOT_RUN"
            recon_block = True
            recon_details = [f"ctrader_reconcile_exception: {type(e).__name__}"]
        snapshot = {
            "mt5_connected": mt5_connected,
            "reconciliation": {
                "status": recon_status,
                "block_trading": recon_block,
                "details": recon_details,
            },
            "safe_mode": recon_block,
            "positions": positions_list,
            "pending_orders": [],
        }
        self.audit.append(
            time.time(),
            EventType.SAFETY,
            self._symbol,
            {
                "phase": "S5",
                "warning": "ctrader_snapshot_reconciled",
                "reconciliation": recon_status,
                "positions_count": len(positions_list),
                "block_trading": recon_block,
                "unknown_symbol_ids": unknown_symbol_ids,
            },
        )
        return snapshot

    def _get_spread_state(self, now_dt: datetime) -> Tuple[bool, float]:
        """(tick_fresh, spread_points). Tick missing/stale → (False, 0.0);
        caller maps that to connection_ok=False (CONNECTION gate).

        D44: tick.time is raw SERVER epoch — negative ages (future)
        tolerated; staleness is therefore approximate on offset servers;
        STALE_DATA (UTC-correct bars) is the authoritative freshness guard
        in Aşama 1.
        """
        try:
            if self._mt5_conn is not None and hasattr(self._mt5_conn, "get_tick_data"):
                d = self._mt5_conn.get_tick_data(self._symbol)
                if not d:
                    return False, 0.0
                bid, ask, t = float(d["bid"]), float(d["ask"]), float(d["time"])
            elif self._mt5 is not None:
                tk = self._mt5.symbol_info_tick(self._symbol)
                if tk is None:
                    return False, 0.0
                bid, ask, t = float(tk.bid), float(tk.ask), float(tk.time)
            else:
                return False, 0.0
        except Exception:
            return False, 0.0
        if t <= 0:
            return False, 0.0
        age = _naive_utc_epoch(now_dt) - t
        if age > self.config.tick_stale_sec:
            return False, 0.0  # age < 0 (server ahead) tolerated — D44
        point = self._contract.tick_size if self._contract else 0.0
        if point <= 0:
            return False, 0.0
        return True, max(0.0, (ask - bid) / point)

    def _fetch_ctrader_account_state(self) -> Dict[str, Any]:
        """İŞ-6 (DİREKTİF-14): real account state via ProtoOATrader fetch.

        Returns {balance, equity, leverage, currency, source} where source
        is "real" (successful fetch) or "fail_soft_0.0" (fetch failed —
        existing 0.0 fail-safe semantics preserved; kaynak-yükseltme,
        gevşetme yok). The fail-soft audit is emitted once per session
        (first failure) to avoid per-bar spam.
        """
        try:
            state = self._mt5_conn.get_account_state()
        except Exception as exc:
            if not self._account_fail_soft_alerted:
                self._account_fail_soft_alerted = True
                self.audit.append(
                    time.time(),
                    EventType.SAFETY,
                    self.configured_symbols[0] if self.configured_symbols else None,
                    {
                        "phase": "account_state",
                        "warning": "ctrader_account_fetch_failed_fail_soft",
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
            return {
                "balance": 0.0,
                "equity": 0.0,
                "leverage": 0,
                "currency": "USD",
                "source": "fail_soft_0.0",
            }
        if not state:
            return {
                "balance": 0.0,
                "equity": 0.0,
                "leverage": 0,
                "currency": "USD",
                "source": "fail_soft_0.0",
            }
        return {
            "balance": float(state.get("balance", 0.0)),
            "equity": float(state.get("equity", 0.0)),
            "leverage": int(state.get("leverage", 0)),
            "currency": str(state.get("currency", "USD")),
            "source": "real",
        }

    def _get_account(self) -> Optional[Account]:
        """D4/D14: FRESH account per bar cycle; never cache across ticks."""
        # İŞ-6 (DİREKTİF-14): cTrader-mode now fetches REAL account state
        # via ProtoOATrader (was explicit 0.0-beyan-pini — İŞ-4a-S1,
        # karar-7/D159). Fail-soft: fetch failure → 0.0-beyan (existing
        # lock semantics preserved — sizing sees balance=0 → rejects → no
        # order can ever be built; kaynak-yükseltme, gevşetme yok).
        if self._ctrader_mode:
            state = self._fetch_ctrader_account_state()
            return Account(
                balance=state["balance"],
                equity=state["equity"],
                currency=state["currency"],
            )
        try:
            acc = self._mt5.account_info() if self._mt5 is not None else None
        except Exception:
            return None
        if acc is None:
            return None
        return Account(
            balance=float(getattr(acc, "balance", 0.0)),
            equity=float(getattr(acc, "equity", 0.0)),
        )

    def _assert_signal_only(self, res: Any) -> Optional[str]:
        """Aşama 1 invariant: nothing real may leave the loop."""
        if getattr(res, "order_sent", False):
            return "order_sent_true_in_signal_only"
        if getattr(res, "fill", None) is not None:
            return "fill_in_signal_only"
        if getattr(res, "context_registered", None) is not None:
            return "context_registered_in_signal_only"
        return None

    def _feed_bars(self, bars: List[Any], account: Account) -> Optional[int]:
        """Feed bars through runner.on_bar. Returns exit code on emergency."""
        for bar in bars:
            try:
                res = self._runner.on_bar(bar, account)
            except Exception as e:
                # D6: strategy exception → persist + alert + STOP.
                # Restart is the clean path: recovery rebuilds deterministic
                # state from market data, not from a half-updated memory.
                self._write_safe_mode(f"strategy_exception:{type(e).__name__}")
                self.audit.append(
                    time.time(),
                    EventType.ERROR,
                    self._symbol,
                    # A1 (OBS-P0): exception type + sinirli traceback kalici
                    error_payload(e, phase="on_bar"),
                )
                self.alert.send(
                    "CRITICAL",
                    f"strategy exception: {e} — safe mode persisted, loop stops",
                )
                return 2
            violation = self._assert_signal_only(res)
            if violation:
                self._write_safe_mode(violation)
                self.audit.append(
                    time.time(),
                    EventType.ERROR,
                    self._symbol,
                    {"phase": "signal_only", "violation": violation},
                )
                self.alert.send("CRITICAL", f"SIGNAL_ONLY VIOLATION: {violation} — loop stops")
                return 2
        return None

    def _advance_state_only(self, bars: List[Any]) -> Optional[int]:
        """§7.2 (SOAK-EYE-1, Hakem-kararı 2026-09-09): gate-CLOSED state feed.

        Entry-permission ve state-advancement AYRI kavramlardır: gate
        kapalıyken motor ilerlemeye devam eder — CBDR window/lock/sweep/
        cycle_reset/V6/FVG emit'leri, boot-replay'in (S9) kullandığı aynı
        runtime.on_bar consumption-point'inden akar. §2.2: kanonik
        on_new_bar seam'i yeniden-kullanılır (bu görev için YAZILMIŞTI,
        hiç bağlanmamıştı) — yeni paralel mekanizma YOK.

        Korunan invariantlar:
          - LiveRunner YOK: risk/sizer/execution yapısal olarak yok;
            üretilen signal ATILIR ve görünür sayılır (STATE audit,
            moment=signals_discarded — E1(ii); SIGNAL şeması kirlenmez) —
            asla sessiz değil (R-3 census dersi).
          - Strategy exception → _feed_bars ile birebir D6 semantiği
            (safe-mode persist + CRITICAL alert + loop stop, exit 2).
        """
        discarded = 0
        for bar in bars:
            try:
                sig = self.on_new_bar(bar)
            except Exception as e:
                self._write_safe_mode(f"strategy_exception:{type(e).__name__}")
                self.audit.append(
                    time.time(),
                    EventType.ERROR,
                    self._symbol,
                    # A1 (OBS-P0): exception type + sinirli traceback kalici
                    error_payload(e, phase="state_advance"),
                )
                self.alert.send(
                    "CRITICAL",
                    f"strategy exception (state-only): {e} — safe mode persisted, loop stops",
                )
                return 2
            if sig is not None:
                discarded += 1
        if discarded:
            # E1(ii) (OBS-P0 karar-kilidi EK-2): bu bir SINYAL degil,
            # toplamsayimdir — SIGNAL tipinde yayinlaninca kapali SIGNAL
            # semasini ucuncu bir emit ile kirletiyordu. STATE (moment
            # discriminator'i, bar_pulse deseni) altina tasindi;
            # gorunurluk invarianti (R-3 census dersi) AYNEN korunur.
            self.audit.append(
                time.time(),
                EventType.STATE,
                self._symbol,
                {"moment": "signals_discarded", "signals_discarded": discarded},
            )
        return None

    def run(
        self,
        kill_switch_fn: Optional[Callable[[], bool]] = None,
        sleep_fn: Optional[Callable[[float], None]] = None,
    ) -> int:
        """TAŞ 3 runtime loop. Requires startup().

        Returns:
          0 — clean shutdown (kill switch, healthy state)
          2 — safe-mode shutdown (strategy exception / signal_only violation /
              killed while SAFE-START or runtime-safe)
          1 — fatal runtime anomaly (lock ownership lost)
        Entry point (Taş 4) maps to process exit + calls shutdown().
        """
        if self._startup_result is None:
            raise RuntimeError("run() called before startup()")
        # DEBT-W1: wire the D129 log modules (lazy, fail-safe, once).
        self._wire_live_logging()
        kill_fn = kill_switch_fn or (lambda: self._kill_requested)
        sleep = sleep_fn or time.sleep
        self._install_signal_handlers()

        monitor_only = self._runner is None  # D39
        entries_enabled = self._startup_result.verdict == StartupVerdict.PROCEED
        recon_decision = self._recon_decision_for_gate()  # D34
        self._safety = SafetyMonitor(max_spread_points=self.config.max_spread_points)

        rt_bars = list(getattr(self._runtime, "bars", []) or []) if self._runtime else []
        if rt_bars:
            self._last_bar_ts = rt_bars[-1].timestamp

        # D5: tracking seed — broker positions ↔ open_trades baseline
        if not monitor_only:
            try:
                self._runner.poll_deals()
            except Exception as e:
                self.audit.append(
                    time.time(),
                    EventType.ERROR,
                    self._symbol,
                    # A1 (OBS-P0): exception type + sinirli traceback kalici
                    error_payload(e, phase="poll_deals_seed"),
                )

        # D41: backlog replay — bars restored/warmed but not yet fed through
        # on_bar (state continuity; parity with SignalRunner replay).
        # §7.2 (SOAK-EYE-1): guard artık yalnız monitor_only — SAFE-START
        # backlog'u adım-9'un gate-closed state-advancement yolu tüketir,
        # feed_cap'e yığılma gerekçesi kalmadı. (Eski gerekçe — "feed never
        # runs" — bu change'in giderdiği §7.2 ihlalinin kendisiydi; §12.1
        # gereği görünür bırakılıyor.)
        self._pending_feed = []
        if not monitor_only and self._runtime is not None:
            nxt = int(getattr(self._runtime, "_next_idx", 0) or 0)
            if 0 <= nxt < len(rt_bars):
                self._pending_feed = list(rt_bars[nxt:])

        consecutive_errors = 0
        backoff = float(self.config.poll_interval_sec)

        # N2 #21 madde-5 (BULGU-3): the lock body must advertise the live
        # runtime loop instead of the frozen "startup" label. The phase
        # write is DEFERRED until after the first D35 ownership-validated
        # heartbeat: an immediate write here would rewrite the shared body
        # (with OUR pid) BEFORE ownership triage — a foreign/tampered body
        # planted between acquire() and the loop would be silently masked
        # and ownership loss would never fire (regression caught by
        # test_ownership_lost_exits_1 / test_ownership_loss_fatal: the
        # loop must not mutate the shared body before ownership is proven).
        phase_advertised = False

        while True:
            # 1) kill switch (D11) — FIRST. A human kill request wins over
            #    ownership state: its exit code (0/2) must not be overridden
            #    by a concurrent ownership check. Ownership loss is a system
            #    decision → fatal 1, checked only when no kill is pending.
            try:
                killed = bool(kill_fn())
            except Exception:
                killed = False
            if killed:
                code = 2 if (self._runtime_safe or not entries_enabled) else 0
                self.audit.append(
                    time.time(),
                    EventType.SHUTDOWN,
                    self._symbol,
                    {"reason": "kill_switch", "exit": code},
                )
                self.shutdown(exit_code=code, reason="kill_switch")
                return code

            # 2) D35 ownership-validated heartbeat — after kill check. A lost
            #    lock is fatal (code 1) regardless of strategy state.
            if not self._heartbeat_validated():
                self.alert.send(
                    "CRITICAL",
                    "lock ownership LOST — another process took over; exiting",
                )
                self.audit.append(
                    time.time(),
                    EventType.ERROR,
                    self._symbol,
                    {"phase": "lock", "error": "ownership_lost"},
                )
                # B-a: ownership-lost previously wrote only ERROR; shutdown()
                # records the SHUTDOWN event + flushes + releases lock.
                self.shutdown(exit_code=1, reason="ownership_lost")
                return 1

            # 2a-bis) N2 #21 madde-5: advertise "running" — ownership is
            #     proven for this tick, so the body mutation is now safe.
            #     One-shot: healthy runs write it once, then heartbeats
            #     keep re-stamping the same live label (never "startup").
            if not phase_advertised:
                self.lock.set_phase("running")
                phase_advertised = True

            # 2b) N2 #13 — B1 disk audit: persist buffered audit events on
            #     a timer independent of append volume. The journal is
            #     append-driven by design (flush only inside append()), so a
            #     quiet market with no errors/gate transitions would never
            #     reach disk. Calling flush_if_due() once per loop bounds
            #     the flush interval to poll_interval (<=30s) and guarantees
            #     "soak starts with the audit on disk".
            try:
                self.audit.flush_if_due()
            except Exception as e:
                self.audit.append(
                    time.time(),
                    EventType.ERROR,
                    self._symbol,
                    # A1 (OBS-P0): exception type + sinirli traceback kalici
                    error_payload(e, phase="audit_flush"),
                )

            # 3) bar pipeline (D19/D20; fetch fail → internal ERROR counter)
            try:
                new_bars = self.produce_new_bars()
            except Exception as e:
                new_bars = []
                self.audit.append(
                    time.time(),
                    EventType.ERROR,
                    self._symbol,
                    # A1 (OBS-P0): exception type + sinirli traceback kalici
                    error_payload(e, phase="bar_pipeline"),
                )
            if new_bars:
                self._last_bar_ts = new_bars[-1].timestamp
                # §7.2 (SOAK-EYE-1): backlog girişi entries_enabled'dan
                # BAĞIMSIZ — gate kapalıyken de barlar birikir ve adım-9
                # state-advancement ile tüketilir (motor soğumaz).
                if not monitor_only:
                    self._pending_feed.extend(new_bars)
                    if len(self._pending_feed) > self.config.feed_cap:  # D43
                        self._pending_feed = self._pending_feed[-self.config.feed_cap :]
                        if not self._feed_cap_alerted:
                            self._feed_cap_alerted = True
                            self.alert.send(
                                "WARN",
                                f"feed backlog capped at {self.config.feed_cap} — replay gap",
                            )
                            self.audit.append(
                                time.time(),
                                EventType.ERROR,
                                self._symbol,
                                {"phase": "feed", "error": "backlog_capped"},
                            )

            # 4) fresh account (D4/D14)
            account = self._get_account()

            # 5) tick/spread state (gate input; D13/D44)
            now_dt = self._now_fn()
            tick_fresh, spread_points = self._get_spread_state(now_dt)
            connection_ok = tick_fresh

            # 6) exits + trailing — ALWAYS run when runner exists
            #    (SAFE MODE keeps position management; entries are gated)
            poll_error = False
            if not monitor_only:
                try:
                    exits = self._runner.poll_deals()
                    if exits and any(isinstance(x, dict) and "error" in x for x in exits):
                        poll_error = True
                    # DEBT-W1: each processed exit → console/canli line +
                    # trade_history record (dedup by deal_id; error payloads
                    # surface via the ERROR audit + D10 ladder instead).
                    for _exit_evt in exits or []:
                        self._log_exit_deal(_exit_evt)
                except Exception as e:
                    poll_error = True
                    self.audit.append(
                        time.time(),
                        EventType.ERROR,
                        self._symbol,
                        # A1 (OBS-P0): exception type + sinirli traceback kalici
                        error_payload(e, phase="poll_deals"),
                    )
                try:
                    self._runner.sync_trailing()
                except Exception as e:
                    self.audit.append(
                        time.time(),
                        EventType.ERROR,
                        self._symbol,
                        # A1 (OBS-P0): exception type + sinirli traceback kalici
                        error_payload(e, phase="sync_trailing"),
                    )

            # 7) D10 fail ladder (data path: rates + account + positions)
            healthy = self._fetch_error_count == 0 and account is not None and not poll_error
            if healthy:
                if consecutive_errors > 0:
                    self.alert.send(
                        "INFO",
                        f"broker data recovered after {consecutive_errors} failed tick(s)",
                    )
                consecutive_errors = 0
                backoff = float(self.config.poll_interval_sec)
                self._ladder_alerted = False
                self._runtime_safe = False  # transient safe auto-clears
                self._runtime_safe_reason = ""
            else:
                consecutive_errors += 1
                backoff = min(
                    backoff * self.config.backoff_multiplier,
                    self.config.backoff_max_sec,
                )
                if (
                    consecutive_errors >= self.config.error_ladder_threshold
                    and not self._ladder_alerted
                ):
                    self._ladder_alerted = True
                    self._runtime_safe = True
                    self._runtime_safe_reason = f"broker_data_ladder:{consecutive_errors}"
                    self.alert.send(
                        "WARN",
                        f"{self._runtime_safe_reason} — entries blocked (transient)",
                    )

            # 8) safety gate — every tick (S2: recon decision never None)
            decision = self._safety.check(
                kill_switch=False,
                connection_ok=connection_ok,
                last_candle_time=(
                    _naive_utc_epoch(self._last_bar_ts) if self._last_bar_ts is not None else None
                ),
                now=_naive_utc_epoch(now_dt),
                spread_points=spread_points,
                reconciliation=recon_decision,
            )
            gate_allowed = bool(
                decision.allowed and entries_enabled and not self._runtime_safe and not monitor_only
            )
            if gate_allowed != self._gate_was_allowed:  # transition-only alerts
                self._gate_was_allowed = gate_allowed
                # N2 #13 — B3 (gate-OPEN reason label).
                # When decision.allowed is True the SafetyMonitor returns
                # reason=""; the else-branch's "monitor_only" was a string
                # constant, not a real diagnostic. Derive a meaningful
                # fallback: OPEN -> "ok", CLOSED -> keep decision.reason.
                if gate_allowed:
                    reason = decision.reason or "ok"
                elif not entries_enabled:
                    reason = decision.reason or "startup_SAFE_START"
                else:
                    reason = decision.reason or self._runtime_safe_reason or "unknown"
                self.alert.send(
                    "INFO" if gate_allowed else "WARN",
                    f"entry gate {'OPEN' if gate_allowed else 'CLOSED'}: {reason}",
                )
                self.audit.append(
                    time.time(),
                    EventType.SAFETY,
                    self._symbol,
                    {
                        "gate": "open" if gate_allowed else "closed",
                        "reason": reason,
                        "failing_check": (
                            decision.failing_check.value if decision.failing_check else None
                        ),
                    },
                )
                # DEBT-W1: same transition → human-readable mirror
                # (console dedup line + canli_trade daily log).
                self._emit_gate(gate_allowed, reason)

            # 8a) Adım-6 "Why No Signal" pulse — BAR-BAZLI (SOAK-D4):
            #     produce_new_bars yalnız yeni 15m slot kapanınca dolu
            #     döner (_seen_bar_slots dedup + trailing-edge), bu yüzden
            #     `new_bars` dolu değilse sessiz no-op. Gate-transition-
            #     blokundan BAĞIMSIZ: her barda nabız — SAFE_START
            #     sessizliğini kırar (SOAK-D2 dersi). reason-hesabı
            #     transition-bloğunun üç-dallı mantığını BİREBİR yansıtır
            #     (orada `reason` yalnız geçişte hesaplanır — burada her
            #     bar'da lazily yeniden-hesaplanır; ikincil-kaynak değil,
            #     aynı-formül).
            if gate_allowed:
                pulse_reason = decision.reason or "ok"
            elif not entries_enabled:
                pulse_reason = decision.reason or "startup_SAFE_START"
            else:
                pulse_reason = decision.reason or self._runtime_safe_reason or "unknown"
            self._emit_bar_pulse(new_bars, gate_allowed, pulse_reason)

            # 9) feed — §7.2 SPLIT (SOAK-EYE-1, Hakem-kararı): state
            #    advancement HER bar'da işler; entry-execution yalnız
            #    gate-OPEN + fresh-account. Exactly-once-advancement:
            #    if/elif — aynı bar iki yoldan da geçmez. Gate-OPEN ama
            #    account-yok → D43 accumulate (eski davranış korundu;
            #    sizing fresh-account ister, state değil).
            if self._pending_feed and gate_allowed and account is not None:
                # entry path — the ONLY caller of runner.on_bar
                code = self._feed_bars(self._pending_feed, account)
                if code is not None:
                    self.shutdown(exit_code=code, reason="feed_emergency")
                    return code
                self._pending_feed = []
            elif self._pending_feed and not gate_allowed:
                code = self._advance_state_only(self._pending_feed)
                if code is not None:
                    self.shutdown(exit_code=code, reason="feed_emergency")
                    return code
                self._pending_feed = []

            # 10) D46 interruptible sleep — chunked <=1s so SIGINT/SIGTERM
            #     (PEP 475) can break a long backoff; kill re-checked between
            #     chunks. When a sleep_fn is injected (tests), call it once
            #     with the full value so backoff cadence stays observable.
            target = backoff if not healthy else float(self.config.poll_interval_sec)
            if sleep_fn is not None:
                sleep(target)
            elif self._interruptible_sleep(target, kill_fn):
                # kill requested during sleep → exit cleanly (D11 semantics)
                code = 2 if (self._runtime_safe or not entries_enabled) else 0
                self.audit.append(
                    time.time(),
                    EventType.SHUTDOWN,
                    self._symbol,
                    {"reason": "kill_switch_during_sleep", "exit": code},
                )
                self.shutdown(exit_code=code, reason="kill_switch_during_sleep")
                return code
