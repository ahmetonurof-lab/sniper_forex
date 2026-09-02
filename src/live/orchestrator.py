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

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from src.config.mt5_config import get_mt5_config
from src.live.audit import AuditChain, EventType
from src.live.candle_feed import _15M_MS, M1CandleFeed, resample_15m
from src.live.clock import _utcnow_naive, server_to_utc_historical
from src.live.reconciliation import ReconcileStatus, ReconciliationDecision
from src.live.recovery import RuntimeRecovery, schedule_snapshot
from src.live.risk import Account, RiskManager
from src.live.safety import SafetyMonitor
from src.live.sizing import ContractSpec, PositionSizer
from src.live.strategy_runtime import StrategyRuntime
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
#      window — 3 attempts, ~0.4s max << LOCK_STALE_SEC=900).
_TMP_WRITE_RETRIES = 3
_TMP_RETRY_BASE_SLEEP = 0.05


def _atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Atomically write ``text`` to ``path`` via a PID-unique tmp + rename.

    Crash-safe (never a truncated target) and contention-hardened: the tmp
    sibling is unique per process/attempt, so two live processes cannot
    collide on the same tmp path, and a transient handle lock on the rename
    is retried with backoff before giving up.
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
            if attempt + 1 < _TMP_WRITE_RETRIES:
                time.sleep(_TMP_RETRY_BASE_SLEEP * (2**attempt))
    # Best-effort cleanup of our own tmp before surfacing the failure.
    try:
        tmp.unlink()
    except OSError:
        pass
    raise last_err  # type: ignore[misc]


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
    audit_path: str = "state/audit.jsonl"
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
      - ``heartbeat()`` refreshes ``created_at`` so a long-running but
        quiet process is not misclassified as stale.

    acquire()  → raises LockError on conflict (existing live lock)
    release()  → no-op if we don't own the lock (pid mismatch)
    heartbeat() → refresh mtime (call from long-running healthy loops)
    """

    def __init__(self, lock_path: Path):
        self.lock_path = Path(lock_path)
        self._owned = False

    def acquire(self) -> None:
        if self._owned:
            return
        if self.lock_path.exists():
            data = self._read()
            if data is not None and not self._is_stale(data):
                raise LockError(
                    f"Lock held by PID {data.pid} (phase={data.phase}, "
                    f"age={time.time() - data.created_at:.0f}s)"
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

    def heartbeat(self) -> None:
        """Refresh lock mtime to prevent false-stale on long healthy runs.

        No-op if we do not own the lock. Safe to call from any tick.
        """
        if not self._owned:
            return
        self._write()

    def _read(self) -> Optional[LockData]:
        try:
            raw = json.loads(self.lock_path.read_text(encoding="utf-8"))
            return LockData.from_dict(raw)
        except (OSError, json.JSONDecodeError, KeyError):
            return None

    def _write(self) -> None:
        # N2 #15: PID-unique tmp + retry via _atomic_write_text. The old
        # fixed ".lock.tmp" sibling was the primary WinError 5 crash site
        # (two-process contention on the same tmp path, orchestrator.py:430
        # during heartbeat). Heartbeat cadence (~20s poll) is far above the
        # bounded retry cost (~0.4s), so lock liveness is unaffected.
        data = LockData(pid=os.getpid(), created_at=time.time(), phase="startup")
        _atomic_write_text(self.lock_path, json.dumps(data.to_dict()), encoding="utf-8")

    @staticmethod
    def _is_stale(data: LockData) -> bool:
        # Two failure modes: process crashed (dead PID) or process
        # wedged quietly past the staleness window (no heartbeat).
        if not _pid_alive(data.pid):
            return True
        return (time.time() - data.created_at) > LOCK_STALE_SEC

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
        prod_audit: AuditChain
        if getattr(self.config, "audit_path", None):
            prod_audit = AuditChain(auto_flush_path=self.config.audit_path)
        else:
            prod_audit = AuditChain()
        self.audit = audit if audit is not None and len(audit) > 0 else prod_audit
        self.lock = Lock(self.state_dir / "orchestrator.lock")
        self._mt5: Any = mt5
        # MT5Connection (production fetch path) — injectable for tests.
        self._mt5_conn: Any = mt5_conn
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
        self._safety: Optional[Any] = None
        # D53: Telegram transport when TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID are
        # configured; visible console fallback otherwise (single audit WARN).
        self.alert = _build_alert_transport(self.config.alert_env, self.audit)

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
        if self._mt5_conn is None:
            self.audit.append(
                time.time(),
                EventType.SAFETY,
                None,
                {"phase": "S1_connect", "warning": "mt5_conn_unset_test_seam_active"},
            )

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

        # ── S2: Account + Identity ──────────────────────────────
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

        # ── S2 identity check (D12, Taş 2 hardened) ────────────
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
        self._recovery = RuntimeRecovery(str(self.state_dir))
        self._runtime = StrategyRuntime(self._symbol)
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
        # _safe() heuristic: margin_level_low maps to S4 (not S2).
        margin_level = float(account_dict.get("margin_level", 0.0))
        if margin_level > 0 and margin_level < self.config.margin_level_min_pct:
            safe_reasons.append(
                f"margin_level_low: {margin_level:.1f}% < {self.config.margin_level_min_pct:.0f}%"
            )

        # ── S5: Broker snapshot (Taş 2 — INJECTION) ────────────
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
            self._runner = LiveRunner(
                symbol=self._symbol,
                mt5=self._mt5,
                audit=self.audit,
                magic=self.magic,
                signal_only=True,
                contract=self._contract,
                lifecycle=self._lifecycle,
                runtime=self._runtime,
                sizer=self._sizer,
                risk_manager=self._risk_manager,
            )
            snapshot = self._runner.startup_snapshot(configured_symbols=self.configured_symbols)
        except Exception as e:
            safe_reasons.append(f"snapshot_failed: {type(e).__name__}")

        # ── S6: SL/TP audit from snapshot ──────────────────────
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
        recon = snapshot.get("reconciliation", {})
        recon_status = recon.get("status", "NOT_RUN")
        if recon_status != "OK":
            if recon.get("block_trading", False):
                safe_reasons.append(f"recon_blocked: {recon_status}")

        # ── S9: Warmup + real-terminal smoke (D28/D33) ─────────
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
        if safe_reasons:
            self._write_safe_mode("; ".join(safe_reasons))
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
                },
            )
            return StartupResult(
                verdict=StartupVerdict.SAFE_START,
                phase=StartupPhase.S9_WARMUP,
                reason="; ".join(safe_reasons),
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

        # Final flush of the audit chain (persist all events).
        try:
            self.audit.shutdown()
        except Exception:
            pass

        # Release the broker handle (only if we hold it).
        try:
            if self._mt5 is not None and hasattr(self._mt5, "shutdown"):
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
                        {"phase": "shutdown_snapshot", "error": str(e)},
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
        _atomic_write_text(path, json.dumps(data, indent=2), encoding="utf-8")

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
                {"phase": "S3", "error": str(e)},
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

        if self._mt5 is None:
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
            self._runtime = StrategyRuntime(self._symbol)

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
        self._runtime = StrategyRuntime(self._symbol)
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
        """D35: ownership-verified heartbeat. False = another process took
        over (D36 STALE-ALIVE resurrection) → caller must exit immediately.

        No lock file on disk → ownership NOT provable (external tamper or
        D36 takeover race window) → False. A lock file owned by a DIFFERENT
        pid → ownership lost → False. Same pid → refresh heartbeat → True.
        """
        data = self.lock._read()
        if data is None:
            # No lock file on disk — ownership cannot be proven (external
            # tamper or D36 takeover race). Do NOT self-reclaim; report
            # ownership loss so the caller exits (fatal, code 1).
            return False
        if int(data.pid) != os.getpid():
            return False
        self.lock.heartbeat()
        return True

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

    def _get_account(self) -> Optional[Account]:
        """D4/D14: FRESH account per bar cycle; never cache across ticks."""
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
                    {"phase": "on_bar", "error": str(e)},
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
                    {"phase": "poll_deals_seed", "error": str(e)},
                )

        # D41: backlog replay — bars restored/warmed but not yet fed through
        # on_bar (state continuity; parity with SignalRunner replay).
        # Guarded by entries_enabled: SAFE-START (entries closed) must NOT
        # accumulate a pending backlog — gate stays closed, feed never runs,
        # so an unguarded replay would pile up until feed_cap.
        self._pending_feed = []
        if not monitor_only and entries_enabled and self._runtime is not None:
            nxt = int(getattr(self._runtime, "_next_idx", 0) or 0)
            if 0 <= nxt < len(rt_bars):
                self._pending_feed = list(rt_bars[nxt:])

        consecutive_errors = 0
        backoff = float(self.config.poll_interval_sec)

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
                    {"phase": "audit_flush", "error": str(e)},
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
                    {"phase": "bar_pipeline", "error": str(e)},
                )
            if new_bars:
                self._last_bar_ts = new_bars[-1].timestamp
                if not monitor_only and entries_enabled:
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
                except Exception as e:
                    poll_error = True
                    self.audit.append(
                        time.time(),
                        EventType.ERROR,
                        self._symbol,
                        {"phase": "poll_deals", "error": str(e)},
                    )
                try:
                    self._runner.sync_trailing()
                except Exception as e:
                    self.audit.append(
                        time.time(),
                        EventType.ERROR,
                        self._symbol,
                        {"phase": "sync_trailing", "error": str(e)},
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

            # 9) feed (entry path — the ONLY caller of runner.on_bar)
            if gate_allowed and account is not None and self._pending_feed:
                code = self._feed_bars(self._pending_feed, account)
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
