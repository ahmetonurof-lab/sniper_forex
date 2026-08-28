#!/usr/bin/env python
"""PHASE 9 — MT5 SIGNAL-ONLY ORCHESTRATOR.

Pulls real MT5 data, feeds the live strategy runtime, evaluates risk
for each emitted signal, and logs the full chain to AuditChain. NEVER
sends real orders (PHASE 11 controlled demo is the only path that
turns off `signal_only`).

Chain per symbol:
    MT5 M1 -> M1CandleFeed -> 15m (canonical boundary)
            -> StrategyRuntime.warmup + on_bar
            -> Signal -> RiskManager.evaluate
            -> AuditChain.append (CANDLE / SIGNAL / RISK)
            -> no Execution.send (signal_only=True default)

Pure / injectable: MT5 module passed as `mt5` arg (default = real
MetaTrader5). The runner can be driven from synthetic data in tests
by passing a fake `mt5` whose `copy_rates_from_pos` returns a pre-built
bar list.

Acceptance
----------
- Signals produced match backtest (Phase 8 parity: 2302 trades across
  6 majors on real feather data).
- No orders sent (signal_only default).
- Every CANDLE batch, every SIGNAL, every RISK decision is recorded
  in AuditChain for post-mortem review.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from src.live.audit import AuditChain, EventType
from src.live.candle_feed import M1CandleFeed, resample_15m
from src.live.clock import _utcnow_naive, server_to_utc_historical
from src.live.risk import Account, RiskManager
from src.live.sizing import ContractSpec
from src.live.strategy_runtime import Signal, StrategyRuntime
from src.strategy.models import Bar


# Default M1 count to pull per symbol (matches the canonical universe
# in data/icmarket_feather, ~65k M1 bars per symbol -> ~3 months).
DEFAULT_M1_COUNT = 65000


@dataclass
class RunnerConfig:
    """Configuration for a single `SignalRunner.run_session` call."""

    symbols: Sequence[str]
    m1_count: int = DEFAULT_M1_COUNT
    # Account snapshot passed to RiskManager (default: $10k, mirrors
    # experiment/config.py INITIAL_BALANCE).
    account_balance: float = 10000.0
    account_equity: float = 10000.0
    # Conservative contract spec (USD-account, 100k lot size, 5-digit
    # symbol). Production should pull real ContractSpec from MT5.
    default_contract: Optional[ContractSpec] = None


@dataclass
class RunnerResult:
    """Outcome of one runner session."""

    signals: List[Signal] = field(default_factory=list)
    approved_signals: List[Signal] = field(default_factory=list)
    blocked_signals: List[Signal] = field(default_factory=list)
    per_symbol: Dict[str, int] = field(default_factory=dict)
    errors: Dict[str, str] = field(default_factory=dict)


class SignalRunner:
    """Signal-only orchestrator: MT5 -> 15m -> Strategy -> Risk -> Audit.

    Args:
        mt5: optional MT5 module (testability). Defaults to real
            `MetaTrader5` package.
        risk_manager: optional RiskManager (default thresholds).
        default_spread: spread in price units passed to RiskManager
            when no live tick is available.
    """

    def __init__(
        self,
        mt5: Any = None,
        risk_manager: Optional[RiskManager] = None,
        default_spread: float = 0.0001,
    ):
        if mt5 is None:
            import MetaTrader5 as mt5_mod  # type: ignore

            mt5 = mt5_mod
        self.mt5 = mt5
        self.risk_manager = risk_manager or RiskManager()
        self.default_spread = default_spread

    # ── Public API ──────────────────────────────────────────────
    def run_session(
        self,
        config: RunnerConfig,
        audit: AuditChain,
    ) -> RunnerResult:
        """Run one signal-only session across all configured symbols.

        For each symbol:
            1) Pull M1 rates from MT5.
            2) Resample to 15m (canonical boundary).
            3) Warmup + replay StrategyRuntime.
            4) For every emitted Signal, evaluate RiskManager.
            5) Append CANDLE / SIGNAL / RISK events to AuditChain.
        NO orders are sent (signal_only invariant).
        """
        result = RunnerResult()
        for symbol in config.symbols:
            try:
                signals = self._run_symbol(symbol, config, audit)
            except Exception as e:
                result.errors[symbol] = f"{type(e).__name__}: {e}"
                audit.append(
                    timestamp=time.time(),
                    event_type=EventType.ERROR,
                    symbol=symbol,
                    payload={"phase": "symbol_run", "error": str(e)},
                )
                continue
            result.per_symbol[symbol] = len(signals)
            result.signals.extend(signals)

        # Risk evaluation pass (after the per-symbol loop so we have a
        # stable per-symbol contract spec).
        for sig in result.signals:
            contract = self._contract_for(sig.symbol, config)
            account = Account(
                balance=config.account_balance,
                equity=config.account_equity,
            )
            decision = self.risk_manager.evaluate(
                sig,
                account=account,
                contract=contract,
                spread=self.default_spread,
                lot=0.0,  # sizing not requested in signal-only pass
            )
            audit.append(
                timestamp=time.time(),
                event_type=EventType.RISK,
                symbol=sig.symbol,
                payload={
                    "approved": decision.approved,
                    "blocked": decision.blocked,
                    "reason": decision.reason,
                    "stop_distance": decision.stop_distance,
                    "checks": list(decision.checks),
                },
            )
            if decision.approved and not decision.blocked:
                result.approved_signals.append(sig)
            else:
                result.blocked_signals.append(sig)
        return result

    # ── Per-symbol internal ─────────────────────────────────────
    def _run_symbol(
        self,
        symbol: str,
        config: RunnerConfig,
        audit: AuditChain,
    ) -> List[Signal]:
        # 1) Pull M1 rates
        m1_rates = self.mt5.copy_rates_from_pos(symbol, "M1", 0, config.m1_count)
        if m1_rates is None or len(m1_rates) == 0:
            return []
        # 2) Convert M1 -> Bar list. MT5 `time` is server time (UTC+2/3);
        #    convert to UTC for canonical parity. Then drop the forming
        #    M1 (whose 1-min window has not elapsed) so the last bucket's
        #    high/low are final, matching M1CandleFeed.fetch_m1 + warmup.
        m1_bars_all = self._rates_to_bars(m1_rates)
        m1_bars = M1CandleFeed.is_closed_m1(m1_bars_all, now=_utcnow_naive())
        if not m1_bars:
            return []
        # 3) Resample 15m (canonical boundary, byte-equivalent to engine)
        bars_15m = resample_15m(m1_bars)
        audit.append(
            timestamp=time.time(),
            event_type=EventType.CANDLE,
            symbol=symbol,
            payload={"m1_count": len(m1_bars), "15m_count": len(bars_15m)},
        )
        # 3) Strategy runtime
        rt = StrategyRuntime(symbol)
        rt.warmup(bars_15m)
        if not rt._warmed:
            return []
        signals: List[Signal] = []
        for i in range(rt._next_idx, len(bars_15m)):
            sig = rt.on_bar(bars_15m[i])
            if sig is not None:
                signals.append(sig)
                audit.append(
                    timestamp=time.time(),
                    event_type=EventType.SIGNAL,
                    symbol=symbol,
                    payload={
                        "direction": sig.direction,
                        "side": sig.side,
                        "entry_price": sig.entry_price,
                        "sl": sig.sl,
                        "tp": sig.tp,
                        "entry_bar_index": sig.entry_bar_index,
                        "sweep_bar_index": sig.sweep_bar_index,
                        "zone_index": sig.zone_index,
                    },
                )
        return signals

    @staticmethod
    def _rates_to_bars(rates: Any) -> List[Bar]:
        """Convert MT5 rates (numpy structured array or list of dicts) to Bar.

        MT5 `time` is reported in **server time** (UTC+2 winter / UTC+3
        summer for ICMarketsSC-Demo). We convert to UTC via
        `clock.server_to_utc()` to match the canonical backtest timezone
        and the existing `M1CandleFeed.fetch_m1` path. This is the
        single source of truth for live M1 ingest.
        """
        bars: List[Bar] = []
        for i, r in enumerate(rates):
            # numpy structured arrays support both tuple and field access
            try:
                ts = int(r["time"])
                o = float(r["open"])
                h = float(r["high"])
                lo = float(r["low"])
                c = float(r["close"])
                v = float(r["tick_volume"])
            except Exception:
                # Some mt5 builds return tuple-like; try attribute access
                ts = int(r.time)
                o = float(r.open)
                h = float(r.high)
                lo = float(r.low)
                c = float(r.close)
                v = float(r.tick_volume)
            import pandas as pd

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

    def _contract_for(self, symbol: str, config: RunnerConfig) -> ContractSpec:
        """Return contract spec for `symbol`. Uses config default if set,
        else a conservative USD-account default.
        Production should pull real spec from MT5 symbol_info."""
        if config.default_contract is not None:
            return config.default_contract
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
