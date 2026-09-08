#!/usr/bin/env python
"""D176-B — LiveRunner width-attach (gercek canli yol testi).

Zincir-kancasi kanitlanir: E2EBroker uzerinden gercek LiveRunner.on_bar
yolu; runtime stub'u SIG dondurur, session.cbdr body'si DOLU ayarlanir
(kasilma senaryosu) -> evaluate GATE devreye girer -> emir GITMEZ.

Bu test FakeRunner degil, GERCEK LiveRunner kullanir (§4.2 production-path).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

from src.live.live_runner import LiveRunner, default_contract
from src.live.portfolio_dd import PortfolioDD
from src.live.risk import Account
from src.live.strategy_runtime import Signal
from src.live.trade_lifecycle import TradeLifecycle

sys.path.insert(0, str(Path(__file__).parent))
from test_e2e_live_chain import E2EBroker  # reuse §2.2


def _sig1() -> Signal:
    """Fresh Signal per call — module-level instance leaked cbdr_width_pct
    across tests (B2 attach -> B3 saw 0.12). Mutable-stub lesson (D176)."""
    return Signal(
        symbol="EURUSD",
        direction="bullish",
        side="long",
        entry_price=1.1000,
        sl=1.0990,
        tp=1.1018,
        entry_bar_index=1,
        sweep_bar_index=0,
        zone_index=0,
        zone_top=1.1005,
        zone_bottom=1.0995,
        zone_size=0.001,
        timestamp=pd.Timestamp("2026-09-08 01:00"),
    )


ACCOUNT = Account(balance=10000.0, equity=10000.0)


def _build_runner_with_body(bh: float, bl: float):
    fake = E2EBroker()
    runner = LiveRunner(
        symbol="EURUSD",
        mt5=fake,
        signal_only=False,
        contract=default_contract("EURUSD"),
        lifecycle=TradeLifecycle(portfolio_dd=PortfolioDD(starting_balance_r=100.0)),
    )
    runner.runtime.on_bar = lambda bar: _sig1()  # deterministic strategy stub
    # Simulate an ACCUMULATED CBDR session body (locked-day squeeze).
    runner.runtime.session.cbdr.body_high = bh
    runner.runtime.session.cbdr.body_low = bl
    return runner, fake


def test_b1_squeeze_body_blocks_live_path():
    # EURUSD p25=0.0866 -> squeeze body: bh=1.00025, bl=1.0 -> 0.025%.
    runner, fake = _build_runner_with_body(bh=1.00025, bl=1.0)
    res = runner.on_bar(None, ACCOUNT)
    sig_width = res.signal.cbdr_width_pct
    assert sig_width == pytest.approx(0.025)
    assert not res.approved
    assert res.blocked_reason == "cbdr_sikisma: width 0.0250% < p25 (NO TRADE, fail-closed)"
    # Production-path proof: NO order reached the broker.
    assert len(fake.requests) == 0


def test_b2_typical_body_allows_live_path():
    # width 0.12% (tipik) -> approved, order sent.
    runner, fake = _build_runner_with_body(bh=1.0012, bl=1.0)
    res = runner.on_bar(None, ACCOUNT)
    assert res.signal.cbdr_width_pct == pytest.approx(0.12)
    assert res.approved
    assert res.final_lot is not None


def test_b3_empty_body_gate_neutral():
    runner, fake = _build_runner_with_body(bh=0.0, bl=float("inf"))
    res = runner.on_bar(None, ACCOUNT)
    assert res.signal.cbdr_width_pct == pytest.approx(0.0)
    assert res.approved  # neutral: no info -> legacy behavior
