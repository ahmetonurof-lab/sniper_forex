#!/usr/bin/env python
"""D176 — CBDR trade-gating wiring (Adim-C on-kosulu DEBT kapanisi).

Zincir (D150 Hakem-tasarimi, D152 sozu):
    session.cbdr body  ->  width_pct  ->  classify_width_regime
    ->  get_cbdr_multiplier  ->  RiskManager.evaluate gate

Kapanan borc: ``get_cbdr_multiplier`` (D152) production-cagiran-YOK idi
(grep-kaniti); bu test-dosyasi once RED ile eksik-baglantiyi davranis-
olarak kanitlar, impl sonrasi GREEN olur.

Kararlar (D176-beyan):
  * sikisma (mult 0.0) -> BLOCK, fail-closed (AGENTS.md 19).
  * diger rejimler -> DD-mult * CBDR-mult carpimi.
  * width <= 0 (bilgi-yok; eski cagri-yollari/signal-only runnerlar)
    -> notr 1.0, gate UYGULANMAZ. Gercek canli yolda Signal ancak
    CBDR locked+sweep sonrasi uretilir -> body dolu -> width > 0.
  * bilinmeyen sembol + width > 0 -> KeyError yayilir (fail-loud).
  * StrategyRuntime DOKUNULMAZ (frozen-parite riski zero); width
    LiveRunner tarafindan signal'e attach edilir.
"""

from __future__ import annotations

import pytest

from src.live.risk import Account, RiskManager
from src.live.strategy_runtime import Signal


def _signal(symbol: str = "EURUSD", width: float = 0.0) -> Signal:
    return Signal(
        symbol=symbol,
        direction="bullish",
        side="long",
        entry_price=1.10000,
        sl=1.09900,
        tp=1.10200,
        entry_bar_index=1,
        sweep_bar_index=0,
        zone_index=0,
        zone_top=1.10050,
        zone_bottom=1.09950,
        zone_size=0.00100,
        timestamp=None if False else __import__("pandas").Timestamp("2026-09-08 01:00"),
        cbdr_width_pct=width,
    )


ACCOUNT = Account(balance=10000.0, equity=10000.0)


def _contract():
    from src.live.live_runner import default_contract

    return default_contract("EURUSD")


# EURUSD bantlari: p25=0.0866 p75=0.166 p90=0.267
def test_t1_sikisma_blocks_fail_closed():
    rm = RiskManager()
    d = rm.evaluate(_signal(width=0.05), ACCOUNT, _contract(), spread=0.0)
    assert not d.approved
    assert d.blocked
    assert d.lot_multiplier == 0.0
    assert "cbdr" in (d.reason or "").lower()


def test_t2_tipik_multiplier_one():
    rm = RiskManager()
    d = rm.evaluate(_signal(width=0.12), ACCOUNT, _contract(), spread=0.0)
    assert d.approved
    assert d.lot_multiplier == pytest.approx(1.0)


def test_t3_yukselmis_multiplier_12():
    rm = RiskManager()
    d = rm.evaluate(_signal(width=0.20), ACCOUNT, _contract(), spread=0.0)
    assert d.approved
    assert d.lot_multiplier == pytest.approx(1.2)


def test_t4_makro_multiplier_15():
    rm = RiskManager()
    d = rm.evaluate(_signal(width=0.30), ACCOUNT, _contract(), spread=0.0)
    assert d.approved
    assert d.lot_multiplier == pytest.approx(1.5)


def test_t5_zero_width_is_neutral_backward_compat():
    rm = RiskManager()
    d = rm.evaluate(_signal(width=0.0), ACCOUNT, _contract(), spread=0.0)
    assert d.approved
    assert d.lot_multiplier == pytest.approx(1.0)


def test_t6_dd_and_cbdr_multipliers_multiply():
    rm = RiskManager()
    d = rm.evaluate(
        _signal(width=0.20),
        ACCOUNT,
        _contract(),
        spread=0.0,
        portfolio_dd_r=2.5,  # > t1=2 -> dd mult 0.5
    )
    assert d.approved
    assert d.lot_multiplier == pytest.approx(0.6)  # 0.5 * 1.2


def test_t7_unknown_symbol_fails_loud():
    rm = RiskManager()
    with pytest.raises(KeyError):
        rm.evaluate(_signal(symbol="XXYZUS", width=0.12), ACCOUNT, _contract(), spread=0.0)
