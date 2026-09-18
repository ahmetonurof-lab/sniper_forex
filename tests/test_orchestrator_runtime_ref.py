"""RUNTIME-REF (cold-rebuild fork fix): reference-identity tests.

Production bug: Orchestrator._begin_cold_rebuild() installed a fresh
StrategyRuntime on self._runtime while the S5-built LiveRunner kept the
pre-rebuild object — S9 replay converged R1, the live loop fed stale R0.

These tests prove, at reference level (no replay machinery, §4.2-safe):
  1. pre-rebuild:  orch._runtime is orch._runner.runtime
  2. post-rebuild: orch._runtime is orch._runner.runtime (same NEW object)
  3. exactly one new StrategyRuntime is constructed (no duplicate runtime)
  4. the runner itself is never replaced (single-LiveRunner architecture)
  5. session state seen by runner.on_bar is the replay target's session
     (runner.runtime.session is orch._runtime.session)
"""

from __future__ import annotations

from src.live.audit import AuditChain
from src.live.live_runner import LiveRunner
from src.live.orchestrator import Orchestrator, OrchestratorConfig
from src.live.strategy_runtime import StrategyRuntime


def _bare_orch(tmp_path):
    cfg = OrchestratorConfig(
        symbols=["EURUSD"],
        state_dir=str(tmp_path / "state"),
        audit_path=str(tmp_path / "audit" / "a.jsonl"),
        expected_login="111",
        m1_warmup_count=1000,
    )
    orch = Orchestrator(
        state_dir=str(tmp_path / "state"),
        magic=9007001,
        configured_symbols=["EURUSD"],
        audit=AuditChain(),
        config_obj=cfg,
        mt5=None,
        mt5_conn=None,
    )
    orch._symbol = "EURUSD"
    return orch


def _wire(orch, runtime):
    orch._runtime = runtime
    orch._runner = LiveRunner(symbol="EURUSD", runtime=runtime)
    return orch._runner


def test_cold_rebuild_propagates_runtime_to_runner(tmp_path):
    orch = _bare_orch(tmp_path)
    r0 = StrategyRuntime("EURUSD", audit=orch.audit)
    runner = _wire(orch, r0)
    # 1. pre-rebuild identity
    assert orch._runtime is r0
    assert orch._runner.runtime is r0
    orch._begin_cold_rebuild()
    r1 = orch._runtime
    # 2. post-rebuild identity: same NEW object on both holders
    assert r1 is not r0
    assert orch._runner.runtime is r1
    # 4. runner itself untouched (no second LiveRunner)
    assert orch._runner is runner
    # 5. session seen by live feed is the replay target's session
    assert orch._runner.runtime.session is orch._runtime.session


def test_cold_rebuild_constructs_exactly_one_runtime(tmp_path, monkeypatch):
    orch = _bare_orch(tmp_path)
    r0 = StrategyRuntime("EURUSD", audit=orch.audit)
    runner = _wire(orch, r0)
    made = []
    import src.live.orchestrator as orch_mod

    real_cls = orch_mod.StrategyRuntime

    def counting_cls(*a, **k):
        obj = real_cls(*a, **k)
        made.append(obj)
        return obj

    monkeypatch.setattr(orch_mod, "StrategyRuntime", counting_cls)
    orch._begin_cold_rebuild()
    # 3. exactly one new runtime; runner points at it; runner not rebuilt
    assert len(made) == 1
    assert orch._runtime is made[0]
    assert orch._runner.runtime is made[0]
    assert orch._runner is runner


def test_cold_rebuild_without_runner_is_safe(tmp_path):
    """_begin_cold_rebuild must not fail when no runner exists yet (S-ordering)."""
    orch = _bare_orch(tmp_path)
    assert orch._runner is None
    orch._begin_cold_rebuild()
    assert orch._runtime is not None
    assert orch._runtime.session is not None
