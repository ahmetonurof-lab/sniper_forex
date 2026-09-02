#!/usr/bin/env python
"""TAŞ 4 — PRODUCTION ENTRY POINT.

The first place this system runs as a REAL process: born via startup(),
lives in the Taş 3 runtime loop, and dies cleanly via shutdown().

Exit-code contract (maps run() -> process exit):
  0 — clean shutdown (kill switch, healthy state) OR already-running
      exit: the N2 #17 dual-instance pre-guard found a live lock owner
      and this instance deliberately did nothing (not an error)
  1 — fatal runtime anomaly (lock ownership lost) / startup FATAL
  2 — safe-mode shutdown (strategy exception / signal_only violation /
      killed while SAFE-START or runtime-safe)

Taş 4 pins addressed here:
  - entry point (exit 0/1/2 mapping)          — this module
  - mt5_conn ZORUNLU wiring + S1 devri        — MT5Connection() injected
  - sleep_fn=None E2E koşumu                  — run() called with sleep_fn=None
                                                (production chunked path)
  - shutdown() her path'te (B-a)              — called on every exit

Usage:
    python -m src.live.run_production
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from src.live.orchestrator import Orchestrator, OrchestratorConfig, StartupVerdict, _pid_alive
from src.trading.mt5_connection import MT5Connection


def _env_symbols() -> list:
    """Symbols from SNIPER_SYMBOLS (comma-separated) or a sane default."""
    raw = os.getenv("SNIPER_SYMBOLS", "EURUSD")
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _build_config() -> OrchestratorConfig:
    symbols = _env_symbols()
    # D18 binary rule (Taş 4 delta, S4):
    #   SNIPER_STATE_DIR explicitly set AND relative  -> FATAL (silent CWD
    #     drift would move state/audit to the wrong place on chdir).
    #   unset (default "state")                       -> resolve against cwd + WARN.
    state_dir = os.getenv("SNIPER_STATE_DIR")
    if state_dir is None:
        state_dir = os.path.abspath("state")
        print(
            "[run_production] WARN: SNIPER_STATE_DIR unset - state dir "
            f"resolved against CWD: {state_dir}",
            file=sys.stderr,
        )
    elif not os.path.isabs(state_dir):
        raise SystemExit(
            f"[run_production] FATAL: SNIPER_STATE_DIR is relative: "
            f"{state_dir!r} - set an absolute path (D18: CWD drift would "
            f"move state/audit to the wrong location)"
        )
    audit_path = os.getenv("SNIPER_AUDIT_PATH")
    if audit_path is None:
        audit_path = os.path.join(state_dir, "audit.jsonl")
    elif not os.path.isabs(audit_path):
        audit_path = os.path.abspath(audit_path)
    return OrchestratorConfig(
        symbols=symbols,
        state_dir=state_dir,
        audit_path=audit_path,
        expected_login=os.getenv("MT5_EXPECTED_LOGIN") or None,
        m1_warmup_count=_env_int("SNIPER_WARMUP_COUNT", 65000),
        poll_interval_sec=float(os.getenv("SNIPER_POLL_INTERVAL", "20")),
        max_spread_points=float(os.getenv("SNIPER_MAX_SPREAD", "30")),
        error_ladder_threshold=_env_int("SNIPER_LADDER_THRESHOLD", 3),
        backoff_multiplier=float(os.getenv("SNIPER_BACKOFF_MULT", "2")),
        backoff_max_sec=float(os.getenv("SNIPER_BACKOFF_MAX", "300")),
        feed_cap=_env_int("SNIPER_FEED_CAP", 1024),
    )


def main() -> int:
    """Run the production orchestrator. Returns the process exit code."""
    config = _build_config()

    # ── N2 #17: dual-instance enforce (D53b pattern) ────────────
    # If a live process already owns the lock (file exists + owner PID
    # alive — Hakem spec verbatim), this instance exits BEFORE anything
    # heavy. Everything else (stale file, corrupt JSON, dead PID) stays
    # on the Lock/PID-dead-takeover path, unchanged.
    lock_path = Path(config.state_dir) / "orchestrator.lock"
    if lock_path.exists():
        pre_pid: int | None = None
        try:
            pre_pid = int(json.loads(lock_path.read_text(encoding="utf-8"))["pid"])
        except (OSError, ValueError, KeyError, TypeError):
            pre_pid = None
        if pre_pid is not None and _pid_alive(pre_pid):
            print(
                f"[run_production] Already running (lock owner PID {pre_pid}) - EXIT",
                file=sys.stderr,
            )
            return 0

    # ── mt5_conn ZORUNLU wiring (Taş 4) ─────────────────────────
    # Production ALWAYS injects a real MT5Connection so the canonical
    # fetch path (get_rates / get_tick_data) is used — never the test
    # seam fallback to self._mt5.copy_rates_from_pos.
    mt5_conn = MT5Connection()

    orch = Orchestrator(
        state_dir=config.state_dir,
        magic=_env_int("SNIPER_MAGIC", 9007001),
        configured_symbols=config.symbols,
        config_obj=config,
        mt5_conn=mt5_conn,
    )

    # ── Startup + Runtime loop under ONE teardown umbrella ──────
    # K5 (Taş 4 seremoni): startup() — including the S9 65k-bar warmup,
    # the LONGEST interrupt window — must be inside the try so a KI there
    # hits the graceful path (SHUTDOWN audit + snapshot + lock release).
    # Before this move, KI during startup = unhandled traceback, no audit,
    # lock left on disk (PID-dead takeover recovers, but B-a broke there).
    code: int = 1
    try:
        result = orch.startup()
        if result.verdict == StartupVerdict.FATAL:
            # startup() already released the lock; nothing to tear down.
            print(
                f"[run_production] FATAL startup: {result.reason}",
                file=sys.stderr,
            )
            return 1

        print(
            f"[run_production] startup {result.verdict.value}: {result.reason} "
            f"(warmup_bars={result.warmup_bars})"
        )

        # ── Runtime loop (sleep_fn=None → production chunked path) ──
        # run() calls shutdown() on its own mapped exit paths (B-a); the
        # finally here guarantees shutdown() on paths run() does NOT map —
        # including KeyboardInterrupt / async signal exceptions
        # (BaseException). shutdown() is idempotent -> safe to double-call.
        code = int(orch.run(kill_switch_fn=None, sleep_fn=None))
    except KeyboardInterrupt:
        # K2 (Taş 4 final): Ctrl-C is a HUMAN stop — same semantics as the
        # kill_fn path: state-dependent code (2 if SAFE-START/runtime-safe
        # or non-PROCEED startup, else 0). The window is narrow (run()
        # installs signal handlers that route SIGINT to kill_fn), so this
        # except is the single defense line for KI raised outside those
        # windows (e.g. during import/teardown edges).
        print("[run_production] KeyboardInterrupt - graceful stop", file=sys.stderr)
        verdict = getattr(orch._startup_result, "verdict", None)
        if verdict is not None:
            code = (
                2
                if (getattr(orch, "_runtime_safe", False) or verdict is not StartupVerdict.PROCEED)
                else 0
            )
        else:
            code = 0  # killed before startup completed - no live loop state
        orch.shutdown(exit_code=code, reason="keyboard_interrupt")
        return code
    except BaseException as e:  # noqa: BLE001 - teardown must not be skipped
        print(f"[run_production] run() raised: {e}", file=sys.stderr)
        code = 1
        orch.shutdown(exit_code=1, reason=f"run_exception:{type(e).__name__}")
        return 1
    finally:
        # B-a belt-and-braces: no-op when shutdown already ran.
        orch.shutdown(exit_code=code, reason="entry_point_finally")

    print(f"[run_production] exit code {code}")
    return code


if __name__ == "__main__":
    sys.exit(main())
