#!/usr/bin/env python
"""SNIPER FOREX — MT5 REAL DATA PROBE - Phase 1

Run via: python -m src.test_mt5_data

Uses the existing architecture:
  config → data layer → test probe

Does NOT:
- implement strategy logic
- calculate trading signals
- send orders
- open positions

This phase: REAL MT5 DATA → UNDERSTAND THE DATA → VERIFY THE DATA
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config.mt5_config import get_mt5_config, mask_sensitive_info
from src.trading.mt5_connection import MT5Connection
from src.data.mt5_data import MT5DataLayer


def load_env_from_project_root():
    """Load .env file from project root reliably."""
    from pathlib import Path
    project_root = Path(__file__).parent.parent.parent
    env_file = project_root / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


def probe_symbol(data_layer, symbol_name):
    """Probe a single symbol for all data.
    
    Args:
        data_layer: MT5DataLayer instance
        symbol_name: Name of the symbol to probe
        
    Returns:
        dict: Probe results for the symbol
    """
    result = {
        "symbol": symbol_name,
        "available": False,
        "symbol_info": None,
        "tick": None,
        "ohlc": {},
        "quality": {}
    }
    
    # Probe symbol info
    result["symbol_info"] = data_layer.get_symbol_info(symbol_name)
    if result["symbol_info"]:
        result["available"] = True
    
    # Probe tick data
    result["tick"] = data_layer.get_tick(symbol_name)
    
    # Probe OHLC data for all timeframes
    timeframes = ["M1", "M5", "M15", "H1"]
    for tf in timeframes:
        rates = data_layer.get_rates(symbol_name, tf, 10)
        if rates and len(rates) > 0:
            # Quality checks
            chronological = all(rates[i]['time'] <= rates[i+1]['time'] for i in range(len(rates)-1))
            ohlc_valid = all(
                r['high'] >= max(r['open'], r['close']) and r['low'] <= min(r['open'], r['close'])
                for r in rates
            )
            
            result["ohlc"][tf] = {
                "count": len(rates),
                "first_timestamp": rates[0]['time'] if rates else None,
                "last_timestamp": rates[-1]['time'] if rates else None,
                "latest_open": rates[0]['open'],
                "latest_high": rates[0]['high'],
                "latest_low": rates[0]['low'],
                "latest_close": rates[0]['close'],
                "volume": rates[0].get('tick_volume', 0),
                "chronological": chronological,
                "ohlc_valid": ohlc_valid
            }
        else:
            result["ohlc"][tf] = {
                "count": 0,
                "quality": "unavailable"
            }
    
    # Data quality checks
    quality_results = []
    
    # Check chronological ordering for each timeframe
    for tf, ohlc_data in result["ohlc"].items():
        if ohlc_data.get("count", 0) > 0 and ohlc_data.get("chronological") is not None:
            quality_results.append(f"[OK] {tf} chronological")
        elif ohlc_data.get("count", 0) > 0:
            quality_results.append(f"[WARN] {tf} ordering issue")
    
    # Check OHLC validity
    for tf, ohlc_data in result["ohlc"].items():
        if ohlc_data.get("ohlc_valid") is not None:
            if ohlc_data["ohlc_valid"]:
                quality_results.append(f"[OK] {tf} OHLC valid")
            else:
                quality_results.append(f"[ERROR] {tf} OHLC invalid")
    
    # Check bid/ask
    if result["tick"]:
        bid_ask_ok = result["tick"]["ask"] >= result["tick"]["bid"]
        if bid_ask_ok:
            quality_results.append(f"[OK] bid/ask valid")
        else:
            quality_results.append(f"[WARN] bid/ask inverted")
    
    result["quality"] = quality_results
    return result


def main():
    """Run the complete MT5 real data probe."""
    print("=" * 60)
    print("SNIPER FOREX — MT5 REAL DATA PROBE")
    print("=" * 60)
    
    # Load environment
    load_env_from_project_root()
    
    # Initialize connection
    try:
        conn = MT5Connection()
        if not conn.connect():
            print("[ERROR] MT5 connection failed")
            print(f"   Details: {os.getenv('MT5_LOGIN', 'login')} / {os.getenv('MT5_SERVER', 'server')}")
            sys.exit(1)
        print("[OK] MT5 initialized")
        print("[OK] Account connected")
        print(f"[OK] Server: {conn.account_info.server}")
    except ValueError as e:
        print(f"[ERROR] Configuration error: {e}")
        print(f"   .env file may not be loading correctly")
        sys.exit(1)
    
    # Initialize data layer
    data_layer = MT5DataLayer()
    
    # Symbols to probe (in order of preference)
    symbols = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]
    
    # Available symbols
    all_symbols = data_layer.get_symbols_list()
    if all_symbols:
        # Filter to only available symbols, preserving preference order
        available = [s for s in symbols if s in all_symbols]
        if not available:
            # If none of the preferred are available, use first available
            available = [all_symbols[0]]
    else:
        available = symbols
    
    print("\n" + "-" * 60)
    print("SYMBOL PROBE")
    print("-" * 60)
    
    probes = []
    for symbol in available:
        result = probe_symbol(data_layer, symbol)
        probes.append(result)
        
        print(f"\n{symbol}")
        if result["available"]:
            si = result["symbol_info"]
            print(f"  [OK] Symbol available")
            print(f"      Bid       : {si['spread'] > 0 and si['point'] or 'N/A'}")
            print(f"      Ask       : available")
            print(f"      Spread    : {si['spread']} points")
            print(f"      Digits    : {si['digits']}")
            print(f"      Point     : {si['point']}")
            if si.get('trade_mode'):
                print(f"      Trade mode: {si['trade_mode']}")
        else:
            print(f"  [WARN] Symbol not available")
            # Try to find similar symbols
            if all_symbols:
                similar = [s for s in all_symbols if "EUR" in s or "USD" in s]
                if similar:
                    print(f"      Similar: {similar[0]}")
       
        # Tick data
        if result["tick"]:
            tick = result["tick"]
            print(f"\n  TICK")
            print(f"      Time    : {tick['time']}")
            print(f"      Bid       : {tick['bid']}")
            print(f"      Ask       : {tick['ask']}")
            spread_units = tick['ask'] - tick['bid']
            print(f"      Spread    : {spread_units:.5f} price units")
    else:
        print("\n  [WARN] No tick data available")
    
    # OHLC data
    print(f"\n  OHLC")
    for tf in ["M1", "M5", "M15", "H1"]:
        ohlc_data = probes[0]["ohlc"][tf] if probes and probes[0]["ohlc"] else {"count": 0}
        count = ohlc_data.get("count", 0)
        if count > 0:
            first = ohlc_data.get("first_timestamp")
            last = ohlc_data.get("last_timestamp")
            latest = ohlc_data.get("latest_close")
            print(f"      {tf:4s} : {count}/10 bars, first={first}, last={last}, latest_close={latest}")
        else:
            print(f"      {tf:4s} : unavailable")
    
    # Data quality
    print(f"\n  DATA QUALITY")
    if probes and probes[0].get("quality"):
        for q in probes[0]["quality"]:
            print(f"      {q}")
    
    # Summary
    print(f"\n  AVAILABLE SYMBOLS: {len(available)}/{len(symbols)}")
    for p in probes:
        status = "OK" if p["available"] else "NOT AVAILABLE"
        print(f"    {p['symbol']}: {status}")
    
    # Clean shutdown
    conn.shutdown()
    print("\n" + "=" * 60)
    print("PROBE COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()