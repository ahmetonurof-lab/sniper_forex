#!/usr/bin/env python
"""D102-BTC-live port: per-symbol contract preset (BTCUSD) + default env symbol.

Production S3 builds the ContractSpec from live MT5 symbol_info (dynamic
for any symbol); this table only backs fallback / test / paper / signal-only
paths.
"""

from src.live.live_runner import default_contract
from src.live.run_production import _env_symbols
from src.live.sizing import contract_for_symbol


def test_contract_preset_btc_found():
    p = contract_for_symbol("BTCUSD")
    assert p["digits"] == 2
    assert p["tick_size"] == 0.01
    assert p["contract_size"] == 1.0
    assert p["volume_min"] == 0.01


def test_unknown_symbol_falls_back_to_generic_major():
    p = contract_for_symbol("GBPJPY")
    assert p["digits"] == 5
    assert p["contract_size"] == 100000.0


def test_default_contract_btc_spec():
    c = default_contract("BTCUSD")
    assert c.symbol == "BTCUSD"
    assert c.digits == 2
    assert c.tick_size == 0.01
    assert c.contract_size == 1.0


def test_default_contract_eurusd_unchanged():
    c = default_contract("EURUSD")
    assert c.digits == 5
    assert c.contract_size == 100000.0
    assert c.tick_size == 0.00001


def test_env_symbols_default_is_seven_majors(monkeypatch):
    """İŞ-4a S1 (D159, karar-8): default universe = 7 FX majors (BTCUSD
    crypto-era default retired; MT5-ölü, cTrader-first)."""
    monkeypatch.delenv("SNIPER_SYMBOLS", raising=False)
    assert _env_symbols() == [
        "EURUSD",
        "GBPUSD",
        "USDJPY",
        "AUDUSD",
        "USDCAD",
        "USDCHF",
        "NZDUSD",
    ]


def test_env_symbols_override_respected(monkeypatch):
    monkeypatch.setenv("SNIPER_SYMBOLS", "BTCUSD,EURUSD")
    assert _env_symbols() == ["BTCUSD", "EURUSD"]


def test_paper_default_contract_btc_uses_shared_preset():
    from src.live.paper import PaperSession

    sess = PaperSession(symbol="BTCUSD", mt5=object())
    c = sess._default_contract()
    assert c.digits == 2
    assert c.contract_size == 1.0
    assert c.tick_size == 0.01
