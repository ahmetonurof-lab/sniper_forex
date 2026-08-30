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
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from src.config.mt5_config import get_mt5_config
from src.live.audit import AuditChain, EventType
from src.live.clock import _utcnow_naive, server_to_utc_historical
from src.live.candle_feed import M1CandleFeed, _15M_MS, resample_15m
from src.live.recovery import RuntimeRecovery
from src.live.risk import RiskManager
from src.live.sizing import ContractSpec, PositionSizer
from src.live.strategy_runtime import StrategyRuntime
from src.live.trade_lifecycle import TradeLifecycle
from src.strategy.models import Bar


# ── Slot helpers (D19/D20 — 15m grid alignment) ─────────────────────


def _slot_floor_ms(label_ms: int) -> int:
    """Floor a millisecond label to its 15-minute grid slot (D19/D20)."""
    return (label_ms // _15M_MS) * _15M_MS


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
            return (
                bool(k32.GetExitCodeProcess(h, ctypes.byref(ec)))
                and ec.value == STILL_ACTIVE
            )
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


# ── Lock ──────────────────────────────────────────────────────────

LOCK_STALE_SEC = 60 * 15  # 15 minutes


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
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        data = LockData(pid=os.getpid(), created_at=time.time(), phase="startup")
        tmp = self.lock_path.with_suffix(".lock.tmp")
        tmp.write_text(json.dumps(data.to_dict()), encoding="utf-8")
        tmp.replace(self.lock_path)

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
    ):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.magic = magic
        self.config = config_obj or OrchestratorConfig(
            symbols=configured_symbols or [],
            state_dir=state_dir,
        )
        self.configured_symbols = configured_symbols or []
        self.audit = audit or AuditChain()
        self.lock = Lock(self.state_dir / "orchestrator.lock")
        self._mt5: Any = mt5
        # MT5Connection (production fetch path) — injectable for tests.
        self._mt5_conn: Any = mt5_conn
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
            return self._run_phases()
        except Exception as e:
            self.lock.release()
            return StartupResult(
                verdict=StartupVerdict.FATAL,
                phase=StartupPhase.S0_CONFIG,
                reason=f"unexpected: {type(e).__name__}: {e}",
            )

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
        # When unset, _fetch_m1_tri_state falls back to self._mt5.
        if self._mt5_conn is None:
            self._mt5_conn = None  # explicit

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
            runner = LiveRunner(
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
            snapshot = runner.startup_snapshot(
                configured_symbols=self.configured_symbols
            )
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
            self._runtime_restored = bool(
                self._recovery.load(self._runtime, self._symbol)
            )
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
            # Lifecycle state survived but the runtime did not warm ->
            # degraded continuation; explicit safe_reason (redelivery 2).
            safe_reasons.append("restore_partial_cold_runtime")
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
            safe_reasons.append(
                f"warmup_failed: {smoke_result.get('reason', 'unknown')}"
            )

        # Heartbeat (Taş 2): healthy S9 completion touches the lock so a
        # long healthy process is not misclassified as stale.
        self.lock.heartbeat()

        # D24: prepend persisted safe-mode reason if present.
        if self._persisted_safe_reason is not None:
            safe_reasons.insert(
                0, f"safe_mode_persisted: {self._persisted_safe_reason}"
            )

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

    # ── Safe-mode persistence (D24) ──────────────────────────────

    def _safe_path(self) -> Path:
        return self.state_dir / self.config.safe_mode_file

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
        path = self._safe_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        import json

        data = {"safe_mode": True, "reason": reason, "ts": time.time()}
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

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
            # D30: trade_mode 0=FULL, 1=LONG-only, 2=SHORT-only, 3=CLOSE-only.
            # Only FULL permits new entries. Flag, do not return None.
            self._trade_mode_ok = trade_mode == 0
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
        warm_skip = bool(
            self._runtime is not None and getattr(self._runtime, "_warmed", False)
        )

        if self._mt5 is None:
            if warm_skip:
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
        for b in m1_bars_all:
            ts_ms = int(b.timestamp.timestamp() * 1000)
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
        now_ms = int(now.timestamp() * 1000)
        reindexed: List[Bar] = []
        for b in m15_full:
            ts_ms = int(b.timestamp.timestamp() * 1000)
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

        return True, len(reindexed), smoke_result

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
        now_ms = int(now.timestamp() * 1000)
        for b in bars:
            if not hasattr(b, "timestamp"):
                continue
            ts_ms = int(b.timestamp.timestamp() * 1000)
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

        now_ms = int(now.timestamp() * 1000)
        new_bars: List[Bar] = []
        for c in m15:
            ts_ms = int(c.timestamp.timestamp() * 1000)
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

        return new_bars

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
