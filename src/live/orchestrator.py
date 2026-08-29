#!/usr/bin/env python
"""TAŞ-1 — ORCHESTRATOR: startup, lock, identity, fail taxonomy.

S0  Config validation
S1  MT5 connection (initialize + login)
S2  Account info + broker identity + startup snapshot

Lock contract:
  PROCEED     → lock held   → released by shutdown (Taş 4)
  SAFE-START  → lock held   → process continues
  FATAL       → startup releases its own lock
  CRASH       → stale-lock takeover (backup only)
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
from src.live.candle_feed import M1CandleFeed, resample_15m
from src.live.recovery import RuntimeRecovery
from src.live.sizing import ContractSpec
from src.live.strategy_runtime import StrategyRuntime
from src.strategy.models import Bar


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
    """File-based single-instance lock.

    acquire()  → raises LockError on conflict (existing live lock)
    release()  → no-op if we don't own the lock (pid mismatch)
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
        self._symbol: str = ""
        self._contract: Optional[ContractSpec] = None
        self._runtime: Optional[StrategyRuntime] = None
        self._recovery: Optional[RuntimeRecovery] = None
        # Bar pipeline state (D19/D20)
        self._last_15m_ts: Optional[pd.Timestamp] = None
        self._global_bar_index: int = 0
        self._seen_bar_ids: set = set()

    def startup(self) -> StartupResult:
        """Run S0→S11 startup sequence with lock ownership contract.

        Returns StartupResult with verdict:
          PROCEED    → clean startup, lock held
          SAFE-START → degraded but survivable, lock held
          FATAL      → lock released by this method
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

        # ── Check persisted safe-mode from previous run ───────────
        safe = self._read_safe_mode()
        if safe is not None:
            # Safe mode persists from prior run — must be explicitly cleared.
            return StartupResult(
                verdict=StartupVerdict.SAFE_START,
                phase=StartupPhase.S0_CONFIG,
                reason=f"safe_mode_persisted: {safe['reason']}",
                account=None,
            )

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

        # ── S2 identity check (D12) ─────────────────────────────
        expected_login = self.config.expected_login or os.getenv("MT5_EXPECTED_LOGIN")
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
        # If expected_login is empty/unset → warn + SAFE-START.

        safe_reasons: List[str] = []

        # ── S3: ContractSpec ────────────────────────────────────
        if not self.configured_symbols:
            self.lock.release()
            return StartupResult(
                verdict=StartupVerdict.FATAL,
                phase=StartupPhase.S3_CONTRACT,
                reason="no_configured_symbols",
            )
        self._symbol = self.configured_symbols[0]

        contract = self._build_contract(self._symbol)
        if contract is None:
            safe_reasons.append("contract_build_failed")
        else:
            self._contract = contract
        contract_dict = contract.__dict__ if contract else None

        # ── S4: Margin level ────────────────────────────────────
        # _safe() heuristic: margin_level_low maps to S4 (not S2).
        margin_level = float(account_dict.get("margin_level", 0.0))
        if margin_level > 0 and margin_level < self.config.margin_level_min_pct:
            safe_reasons.append(
                f"margin_level_low: {margin_level:.1f}% < {self.config.margin_level_min_pct:.0f}%"
            )

        # ── S5: Broker snapshot ─────────────────────────────────
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

        # ── S7: Local state recovery ───────────────────────────
        self._recovery = RuntimeRecovery(str(self.state_dir))
        self._runtime = StrategyRuntime(self._symbol)
        try:
            self._recovery.load(self._runtime, self._symbol)
        except Exception as e:
            safe_reasons.append(f"recovery_failed: {type(e).__name__}")

        # ── S8: Recon gate ──────────────────────────────────────
        recon = snapshot.get("reconciliation", {})
        recon_status = recon.get("status", "NOT_RUN")
        if recon_status != "OK":
            if recon.get("block_trading", False):
                safe_reasons.append(f"recon_blocked: {recon_status}")

        # ── S9: Warmup + real-terminal smoke ───────────────────
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
        """Build a ContractSpec from live MT5 symbol_info (D3).

        D3: stops_level = trade_stops_level × point; tick_size/tick_value/
        volume_min-step-max from symbol_info; trade_mode != FULL → SAFE MODE.
        """
        if self._mt5 is None or not hasattr(self._mt5, "symbol_info"):
            return None
        try:
            self._mt5.symbol_select(symbol, True)
            si = self._mt5.symbol_info(symbol)
            if si is None:
                return None
            point = float(getattr(si, "point", 0.00001))
            stops_level = int(getattr(si, "trade_stops_level", 0))
            digits = getattr(si, "digits", 5)
            tick_value = float(getattr(si, "trade_tick_value", 1.0))
            volume_min = float(getattr(si, "volume_min", 0.01))
            volume_max = float(getattr(si, "volume_max", 100.0))
            volume_step = float(getattr(si, "volume_step", 0.01))
            trade_mode = getattr(si, "trade_mode", 0)
            # trade_mode: 0=FULL, 1=LONG, 2=SHORT, 3=CLOSE (only FULL is ok for new)
            if trade_mode != 0:
                # Not FULL — will be flagged as safe-mode reason by caller
                pass
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

    # ── S9: Warmup + real-terminal smoke (D15/D28) ─────────────

    def _warmup(self, m1_count: int) -> Tuple[bool, int, dict]:
        """S9: real-terminal smoke + StrategyRuntime warmup.

        D28 smoke (one-shot, before warmup):
            (a) 100 M1 çek → _rates_to_bars → timestamps grid-aligned + UTC
            (b) son kapalı M1 ≈ now − 1min (toleranslı)
            (c) 15m slot alignment D19 ile tutarlı.

        D15: uses _rates_to_bars + is_closed_m1 + resample_15m (import, not copy).
        Returns (ok, warmup_bars, smoke_result).
        """
        smoke_result: dict = {"errors": [], "reason": ""}

        # ── D28 smoke: fetch 100 M1 bars ────────────────────────
        if self._mt5 is None:
            smoke_result["reason"] = "no_mt5_connection"
            return False, 0, smoke_result

        try:
            rates = self._mt5.copy_rates_from_pos(
                self._symbol, getattr(self._mt5, "TIMEFRAME_M1", 1), 0, 100
            )
        except Exception as e:
            smoke_result["reason"] = f"copy_rates_exception: {e}"
            smoke_result["errors"].append(str(e))
            return False, 0, smoke_result

        if rates is None or len(rates) == 0:
            smoke_result["reason"] = "no_m1_rates"
            return False, 0, smoke_result

        m1_bars_all = self._rates_to_bars(rates)
        if not m1_bars_all:
            smoke_result["reason"] = "rates_to_bars_empty"
            return False, 0, smoke_result

        # (a) timestamps grid-aligned + UTC — they are Bar objects with
        # UTC timestamps by construction (server_to_utc conversion in
        # _rates_to_bars). Verify grid alignment.
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
            age = (
                (now - last_closed).total_seconds() if hasattr(now, "timestamp") else 0
            )
            if hasattr(last_closed, "timestamp"):
                last_ts_naive = (
                    last_closed.to_pydatetime()
                    if hasattr(last_closed, "to_pydatetime")
                    else last_closed
                )
                age = (now - last_ts_naive).total_seconds()
            # Tolerate up to 3 min (clock + network skew)
            if age < 0 or age > 3 * 60:
                smoke_result["reason"] = f"stale_last_closed_m1: age={age:.0f}s"
                smoke_result["errors"].append(f"last closed M1 age={age:.0f}s")
                # Not fatal — proceed to warmup but record

        # (c) 15m slot alignment D19 — resample and verify bucket alignment
        m15 = resample_15m(closed_m1)
        if not m15:
            smoke_result["reason"] = "no_15m_after_resample"
            return False, 0, smoke_result

        # ── Full warmup fetch ───────────────────────────────────
        try:
            full_rates = self._mt5.copy_rates_from_pos(
                self._symbol, getattr(self._mt5, "TIMEFRAME_M1", 1), 0, m1_count
            )
        except Exception:
            full_rates = rates  # fall back to smoke data

        if full_rates is None or len(full_rates) == 0:
            smoke_result["reason"] = "warmup_no_rates"
            return False, 0, smoke_result

        m1_bars_full = self._rates_to_bars(full_rates)
        closed_full = M1CandleFeed.is_closed_m1(m1_bars_full, now=now)
        m15_full = resample_15m(closed_full)

        # D20: index continuity — reindex from global counter
        if self._runtime is None:
            self._runtime = StrategyRuntime(self._symbol)

        # D20: assign global monotonic indices, continuing from where we left
        reindexed: List[Bar] = []
        for b in m15_full:
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

        # Track last 15m timestamp for premature-emit detection (D19)
        if reindexed:
            self._last_15m_ts = reindexed[-1].timestamp

        self._runtime.warmup(reindexed)

        if not self._runtime._warmed:
            smoke_result["reason"] = "runtime_warmup_failed"
            return False, 0, smoke_result

        # Clear any persisted safe_mode after successful warmup
        self.clear_safe_mode()

        return True, len(reindexed), smoke_result

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

        Implements premature-emit protection:
        - D19: Bar identity = (symbol, bar_open_time UTC). Same identity
          never emits twice (trailing edge: emit bucket B only when next
          bucket's M1 closes).
        - D20: Global monotonic index continuity across fetches.

        Returns newly completed 15m bars with proper indices (may be empty).
        """
        if self._mt5 is None:
            return []

        try:
            rates = self._mt5.copy_rates_from_pos(
                self._symbol, getattr(self._mt5, "TIMEFRAME_M1", 1), 0, 20
            )
        except Exception as e:
            self.audit.append(
                time.time(),
                EventType.ERROR,
                self._symbol,
                {"phase": "bar_pipeline", "error": str(e)},
            )
            return []

        if rates is None or len(rates) == 0:
            return []

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

        new_bars: List[Bar] = []
        for c in m15:
            # D19: identity = (symbol, open_time UTC)
            bar_id = (self._symbol, str(c.timestamp))
            if bar_id in self._seen_bar_ids:
                continue
            # D19 trailing edge: only emit if we've seen a later bucket
            # (i.e., this bucket's 15m window is fully closed). The
            # resample_15m + is_closed_m1 pipeline guarantees this:
            # is_closed_m1 drops the forming M1, so any 15m bucket containing
            # a forming bar's slot is withheld until that M1 closes and the
            # next bucket appears. We additionally guard with _last_15m_ts:
            # only emit bars strictly after the last emitted.
            if self._last_15m_ts is not None:
                c_ts = c.timestamp
                if hasattr(c_ts, "to_pydatetime"):
                    c_ts = c_ts.to_pydatetime()
                if c_ts <= self._last_15m_ts:
                    continue

            # D20: global monotonic index
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
            self._seen_bar_ids.add(bar_id)
            new_bars.append(bar)

        if new_bars:
            self._last_15m_ts = new_bars[-1].timestamp

        return new_bars

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
