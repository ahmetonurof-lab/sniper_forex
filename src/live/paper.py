#!/usr/bin/env python
"""PHASE 10 — PAPER / DRY RUN.

Simulated execution against a virtual broker. The bot thinks it is
trading; in reality no order reaches the real broker. Acceptance:
- Paper signals consistent with backtest.
- PnL calculation is correct for 5-digit majors.

Components
----------
- `PaperPosition`: virtual open trade, mirrors `Position` from
  `position_manager.py` but with extra `status` + `pnl` fields.
- `PaperBroker`: in-memory order state (open/close + PnL math).
- `PaperSession`: one bar-step of the live loop. Pulls M1 rates from
  MT5, detects closed 15m bars, runs StrategyRuntime, opens paper
  positions on new signals, and updates open positions against the
  latest tick prices (SL/TP check).

Pure / injectable: MT5 module passed as `mt5`. Tests inject a fake.
No real broker is contacted.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from src.live.audit import AuditChain, EventType
from src.live.candle_feed import M1CandleFeed, resample_15m
from src.live.clock import _utcnow_naive, server_to_utc_historical
from src.live.position_manager import Position
from src.live.risk import Account, RiskManager
from src.live.portfolio_dd import PortfolioDD
from src.live.sizing import ContractSpec, PositionSizer
from src.live.strategy_runtime import Signal, StrategyRuntime
from src.strategy.models import Bar


class PositionStatus(str, Enum):
    """Lifecycle of a paper position."""

    OPEN = "OPEN"
    CLOSED_SL = "CLOSED_SL"
    CLOSED_TP = "CLOSED_TP"
    CLOSED_MANUAL = "CLOSED_MANUAL"


@dataclass
class PaperPosition:
    """Virtual open position with PnL tracking."""

    ticket: int
    symbol: str
    side: str  # "long" / "short"
    volume: float
    entry_price: float
    sl: float
    tp: float
    magic: int
    open_time: float
    status: PositionStatus = PositionStatus.OPEN
    exit_price: float = 0.0
    exit_time: float = 0.0
    pnl: float = 0.0  # in account currency (USD for 5-digit majors)

    def to_position(self) -> Position:
        """Convert to the live `Position` shape used elsewhere."""
        return Position(
            ticket=self.ticket,
            symbol=self.symbol,
            side=self.side,
            volume=self.volume,
            entry_price=self.entry_price,
            sl=self.sl,
            tp=self.tp,
            magic=self.magic,
            open_time=self.open_time,
        )


def _pnl(
    side: str,
    entry: float,
    exit_price: float,
    volume: float,
    contract_size: float,
    tick_size: float,
    tick_value: float,
) -> float:
    """Compute realized PnL in account currency.

    Formula for 5-digit majors (most pairs):
        pnl = sign * (exit - entry) / tick_size * tick_value * volume
    where sign = +1 for long, -1 for short.

    For 3-digit JPY pairs the same formula applies (tick_size=0.001,
    tick_value scaled accordingly) — this is the broker convention
    MetaTrader uses.
    """
    if tick_size <= 0 or tick_value <= 0 or contract_size <= 0:
        return 0.0
    sign = 1.0 if side == "long" else -1.0
    ticks = (exit_price - entry) / tick_size * sign
    # Volume is in lots; tick_value is per tick per lot.
    return ticks * tick_value * volume


# ── Broker ───────────────────────────────────────────────────────


class PaperBroker:
    """In-memory virtual broker. No I/O, no MT5 side effects."""

    def __init__(self, magic: int = 9007001, starting_equity: float = 10000.0):
        self.magic = magic
        self.equity = starting_equity
        self._open: Dict[int, PaperPosition] = {}
        self._closed: List[PaperPosition] = []
        self._next_ticket: int = 1

    # ── State access ────────────────────────────────────────────
    def get_open(self) -> List[PaperPosition]:
        return list(self._open.values())

    def get_closed(self) -> List[PaperPosition]:
        return list(self._closed)

    def total_pnl(self) -> float:
        return sum(p.pnl for p in self._closed)

    # ── Open / close ────────────────────────────────────────────
    def open(
        self,
        signal: Signal,
        volume: float,
        contract: ContractSpec,
        now: Optional[float] = None,
    ) -> PaperPosition:
        """Open a paper position at `signal.entry_price` (instant fill)."""
        if now is None:
            now = time.time()
        ticket = self._next_ticket
        self._next_ticket += 1
        pos = PaperPosition(
            ticket=ticket,
            symbol=signal.symbol,
            side=signal.side,
            volume=float(volume),
            entry_price=float(signal.entry_price),
            sl=float(signal.sl),
            tp=float(signal.tp),
            magic=self.magic,
            open_time=now,
        )
        self._open[ticket] = pos
        return pos

    def close(
        self,
        ticket: int,
        exit_price: float,
        now: Optional[float] = None,
        reason: PositionStatus = PositionStatus.CLOSED_MANUAL,
    ) -> Optional[PaperPosition]:
        """Close an open position at `exit_price` (manual exit)."""
        pos = self._open.pop(ticket, None)
        if pos is None:
            return None
        if now is None:
            now = time.time()
        # Caller-supplied contract info isn't tracked per-position here
        # for simplicity; PnL is set explicitly via `update_pnl` when a
        # contract is known. For now leave pnl=0 (caller patches it).
        pos.status = reason
        pos.exit_price = float(exit_price)
        pos.exit_time = now
        self._closed.append(pos)
        return pos

    def update_pnl(
        self,
        ticket: int,
        contract: ContractSpec,
        exit_price: float,
    ) -> float:
        """Patch the realized PnL for a closed position.

        Called by `PaperSession` once the contract is known (per symbol).
        """
        for p in self._closed:
            if p.ticket == ticket:
                p.pnl = _pnl(
                    side=p.side,
                    entry=p.entry_price,
                    exit_price=exit_price,
                    volume=p.volume,
                    contract_size=contract.contract_size,
                    tick_size=contract.tick_size,
                    tick_value=contract.tick_value,
                )
                return p.pnl
        return 0.0

    # ── Tick-based SL/TP check ──────────────────────────────────
    def on_tick(
        self,
        symbol: str,
        bid: float,
        ask: float,
        now: Optional[float] = None,
    ) -> List[PaperPosition]:
        """Check open positions for SL/TP hits at the current bid/ask.

        Returns the list of positions that were closed by this tick.
        SL is checked against bid (for long) / ask (for short).
        TP is checked against bid (for long) / ask (for short).
        Standard MT5 convention.
        """
        if now is None:
            now = time.time()
        closed: List[PaperPosition] = []
        for ticket in list(self._open.keys()):
            p = self._open[ticket]
            if p.symbol != symbol:
                continue
            trigger_price: Optional[float] = None
            reason: Optional[PositionStatus] = None
            if p.side == "long":
                # SL: bid <= sl. TP: bid >= tp.
                if bid <= p.sl:
                    trigger_price = p.sl
                    reason = PositionStatus.CLOSED_SL
                elif bid >= p.tp:
                    trigger_price = p.tp
                    reason = PositionStatus.CLOSED_TP
            else:  # short
                # SL: ask >= sl. TP: ask <= tp.
                if ask >= p.sl:
                    trigger_price = p.sl
                    reason = PositionStatus.CLOSED_SL
                elif ask <= p.tp:
                    trigger_price = p.tp
                    reason = PositionStatus.CLOSED_TP
            if trigger_price is not None and reason is not None:
                pos = self.close(ticket, trigger_price, now=now, reason=reason)
                if pos is not None:
                    closed.append(pos)
        return closed


# ── Session step ─────────────────────────────────────────────────


@dataclass
class PaperStepResult:
    """Outcome of a single `PaperSession.run_step` call."""

    new_closed: List[PaperPosition] = field(default_factory=list)
    new_opens: List[PaperPosition] = field(default_factory=list)
    ticks_processed: int = 0
    errors: List[str] = field(default_factory=list)


class PaperSession:
    """One bar-step of a paper-trading session.

    On each `run_step` call:
        1) Pull latest M1 from MT5.
        2) Detect any closed 15m candle.
        3) If a 15m closed -> run `StrategyRuntime.on_bar(closed_bar)`.
           New signal -> risk approve + PaperBroker.open.
        4) For every M1 in the step, run `on_tick` against open positions
           (SL/TP check).

    The session is stateful across calls (it remembers which bars have
    been processed and the next StrategyRuntime index).
    """

    def __init__(
        self,
        symbol: str,
        mt5: Any = None,
        broker: Optional[PaperBroker] = None,
        runtime: Optional[StrategyRuntime] = None,
        risk_manager: Optional[RiskManager] = None,
        contract: Optional[ContractSpec] = None,
    ):
        if mt5 is None:
            import MetaTrader5 as mt5_mod  # type: ignore

            mt5 = mt5_mod
        self.symbol = symbol
        self.mt5 = mt5
        self.broker = broker or PaperBroker()
        self.runtime = runtime or StrategyRuntime(symbol)
        self.risk_manager = risk_manager or RiskManager()
        self.contract = contract
        self._last_processed_m1_ts: Optional[float] = None
        self._warmed: bool = False
        self._paper_context: dict = {}
        self._paper_dd = PortfolioDD(starting_balance_r=100.0)
        # P2-6 — keep partial M1 tail across steps for 15m continuity
        self._partial_m1_tail: List[Bar] = []

    def warmup(self, n_15m: int = 200) -> int:
        """Pull historical M1, resample 15m, warm the runtime.

        Returns the number of 15m candles produced.
        """
        from src.live.candle_feed import resample_15m

        m1_count = n_15m * 15 + 30
        m1_rates = self.mt5.copy_rates_from_pos(self.symbol, "M1", 0, m1_count)
        if m1_rates is None or len(m1_rates) == 0:
            return 0
        m1_bars_all = _rates_to_bars(m1_rates)
        # Drop forming M1 (its 1-min window has not elapsed) for canonical
        # parity with M1CandleFeed.fetch_m1 + SignalRunner._run_symbol.
        m1_bars = M1CandleFeed.is_closed_m1(m1_bars_all, now=_utcnow_naive())
        if not m1_bars:
            return 0
        bars_15m = resample_15m(m1_bars)
        self.runtime.warmup(bars_15m)
        self._warmed = self.runtime._warmed
        self._last_processed_m1_ts = (
            float(m1_bars[-1].timestamp.timestamp()) if m1_bars else None
        )
        # Initialize partial tail with any unclosed M1 after the last full bucket
        # (for P2-6 incremental 15m continuity).
        if m1_bars:
            # Keep the tail that doesn't complete a 15m bucket at the end.
            # Minimal approach: keep up to 14 bars (one full 15m missing one) as partial.
            self._partial_m1_tail = (
                m1_bars[-14:] if len(m1_bars) >= 14 else list(m1_bars)
            )
        else:
            self._partial_m1_tail = []
        return len(bars_15m)

    def run_step(
        self,
        audit: AuditChain,
        m1_bars: Optional[List[Bar]] = None,
        ticks: Optional[List[Dict[str, float]]] = None,
    ) -> PaperStepResult:
        """Run one step. Caller may pass `m1_bars` and `ticks` (for tests
        with FakeMT5) or leave them None for real MT5 use.

        `ticks` is a list of `{"bid": float, "ask": float}` dicts, one
        per M1 in the step. We process them in order so SL/TP check is
        realistic (open-of-bar to close-of-bar walk).
        """
        result = PaperStepResult()
        if not self._warmed:
            result.errors.append("not warmed up yet")
            return result

        # If m1_bars not provided, fetch from MT5.
        if m1_bars is None:
            try:
                m1_rates = self.mt5.copy_rates_from_pos(self.symbol, "M1", 0, 100)
            except Exception as e:
                result.errors.append(f"copy_rates_from_pos failed: {e}")
                return result
            if m1_rates is None or len(m1_rates) == 0:
                return result
            m1_bars_all = _rates_to_bars(m1_rates)
            # Drop forming M1 for canonical parity (see warmup()).
            m1_bars = M1CandleFeed.is_closed_m1(m1_bars_all, now=_utcnow_naive())
            if not m1_bars:
                return result

        # 1) Tick-based SL/TP check across each M1 in the step.
        if ticks is not None:
            for tick in ticks:
                closed = self.broker.on_tick(
                    self.symbol, float(tick["bid"]), float(tick["ask"])
                )
                result.new_closed.extend(closed)
                # Patch PnL with our contract if known.
                if self.contract is not None and closed:
                    for c in closed:
                        self.broker.update_pnl(c.ticket, self.contract, c.exit_price)
                        # Update paper PortfolioDD with realized PnL (rehearsal, not MT5 authoritative)
                        if c.pnl != 0.0:
                            # Lock initial risk cash per unit from paper context for R conversion
                            context = self._paper_context.get(c.ticket, {})
                            initial_risk_total = context.get(
                                "initial_risk_cash_total", 10.0
                            )
                            # Minimal R conversion: use locked initial risk basis
                            # (simplified for paper rehearsal; full deal-level tracking uses TradeLifecycle)
                            pnl_r = c.pnl / (initial_risk_total or 10.0)
                            self._paper_dd.record_realized(pnl_r)
                        audit.append(
                            time.time(),
                            EventType.EXIT,
                            self.symbol,
                            {
                                "ticket": c.ticket,
                                "reason": c.status.value,
                                "exit_price": c.exit_price,
                                "pnl": c.pnl,
                            },
                        )
            result.ticks_processed = len(ticks)

        # P2-6 — Combine previous partial M1 tail + new M1 before aggregation
        combined_m1 = list(self._partial_m1_tail) + list(m1_bars)
        # Filter forming M1 already applied to new m1_bars above; partial tail
        # is retained from previous step and should be treated as historical.
        # For simplicity we treat all combined bars equally (they are all
        # past bars except possibly the very newest, which is handled by
        # is_closed_m1 in fetch/update paths); here we rely on the caller
        # providing closed M1 bars.
        new_15m = resample_15m(combined_m1) if combined_m1 else []
        # Emit only unseen completed 15m candles
        emitted_15m: List[Bar] = []
        for c in new_15m:
            if (
                self._last_processed_m1_ts is None
                or c.timestamp > self._last_processed_m1_ts
            ):
                emitted_15m.append(c)
        if emitted_15m:
            self._last_processed_m1_ts = emitted_15m[-1].timestamp

        # 2) Run strategy on emitted 15m candles (not on the raw M1 tail directly)
        # We pass emitted_15m to the strategy replay logic.
        if emitted_15m:
            self._run_on_15m(emitted_15m, audit, result, combined_m1)
        else:
            # If nothing emitted, just process ticks and retain partial tail
            pass

        # Update partial tail: keep the newest uncompleted M1 bars (up to 14)
        # from the combined stream for next step continuity.
        if combined_m1:
            # Retain last up-to-14 bars that didn't form a complete 15m bucket
            # (minimal approximation: keep the tail not fully covered by emitted 15m).
            last_emitted_slot = None
            if emitted_15m:
                last_emitted_slot = int(
                    emitted_15m[-1].timestamp.timestamp() * 1000 // (15 * 60 * 1000)
                ) * (15 * 60 * 1000)
            # Keep bars after the last fully emitted 15m bucket.
            new_tail: List[Bar] = []
            for b in combined_m1:
                ts_ms = int(b.timestamp.timestamp() * 1000)
                if last_emitted_slot is not None and ts_ms >= last_emitted_slot:
                    new_tail.append(b)
                elif last_emitted_slot is None:
                    new_tail.append(b)
            # Limit tail size to avoid unbounded growth (max 14 M1 bars = ~1 15m gap)
            self._partial_m1_tail = (
                new_tail[-14:] if len(new_tail) > 14 else list(new_tail)
            )
        else:
            self._partial_m1_tail = []
        return result

    def _run_on_15m(
        self,
        emitted_15m: List[Bar],
        audit: AuditChain,
        result: PaperStepResult,
        combined_m1: List[Bar],
    ) -> int:
        """Replay emitted 15m candles through StrategyRuntime; emit paper opens."""
        n_new = 0
        for c in emitted_15m:
            sig = self.runtime.on_bar(c)
            if sig is not None:
                # Risk gate with same live semantics (base lot + DD multiplier + quantization)
                contract = self.contract or self._default_contract()
                account = Account(balance=self.broker.equity, equity=self.broker.equity)
                base_sizer = PositionSizer()
                base_result = base_sizer.compute_lot(
                    sig, balance=account.balance, contract=contract
                )
                base_lot = base_result.lot
                current_dd_r = self._paper_dd.current_dd_r() if self._paper_dd else 0.0
                decision = self.risk_manager.evaluate(
                    sig,
                    account=account,
                    contract=contract,
                    spread=0.0,
                    lot=base_lot,
                    portfolio_dd_r=current_dd_r,
                )
                final_lot = (
                    PositionSizer.apply_scaling_and_quantize(
                        base_lot=base_lot,
                        lot_multiplier=decision.lot_multiplier,
                        volume_step=contract.volume_step,
                        volume_min=contract.volume_min,
                        volume_max=contract.volume_max,
                    )
                    if base_lot > 0
                    else 0.0
                )
                audit.append(
                    time.time(),
                    EventType.SIGNAL,
                    self.symbol,
                    {
                        "direction": sig.direction,
                        "approved": decision.approved,
                        "lot_multiplier": decision.lot_multiplier,
                        "base_lot": base_lot,
                        "final_lot": final_lot,
                    },
                )
                if decision.approved and not decision.blocked and final_lot > 0:
                    pos = self.broker.open(sig, volume=final_lot, contract=contract)
                    self._persist_paper_context(
                        pos, base_lot, final_lot, decision.lot_multiplier
                    )
                    result.new_opens.append(pos)
                    audit.append(
                        time.time(),
                        EventType.POSITION,
                        self.symbol,
                        {
                            "ticket": pos.ticket,
                            "side": pos.side,
                            "entry": pos.entry_price,
                            "sl": pos.sl,
                            "tp": pos.tp,
                            "volume": final_lot,
                        },
                    )
            n_new += 1
        return n_new

    def _persist_paper_context(
        self,
        pos,
        base_lot: float,
        final_lot: float,
        lot_multiplier: float,
    ) -> None:
        self._paper_context[pos.ticket] = {
            "base_lot": float(base_lot),
            "final_lot": float(final_lot),
            "lot_multiplier": float(lot_multiplier),
            "symbol": pos.symbol,
            "side": pos.side,
            "entry_price": pos.entry_price,
            "initial_sl": pos.sl,
            "initial_risk_cash_total": float(self.broker.equity or 10000.0),
        }

    def _default_contract(self) -> ContractSpec:
        return ContractSpec(
            symbol=self.symbol,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            tick_size=0.00001,
            tick_value=1.0,
            contract_size=100000.0,
            stops_level=0.0,
            digits=5,
        )


def _rates_to_bars(rates: Any) -> List[Bar]:
    """Convert MT5 rate rows to Bar list (parity with signal_runner).

    MT5 `time` is reported in **server time** (UTC+2 winter / UTC+3
    summer for ICMarketsSC-Demo). We convert to UTC via
    `clock.server_to_utc()` to match the canonical backtest timezone
    and the existing `M1CandleFeed.fetch_m1` path.
    """
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
