#!/usr/bin/env python
"""CBDR sweep scan — 6-major universe, REPORT-ONLY, imports the LIVE engine.

AMAÇ
    Canlı üretim motorunun KENDİ CBDR mantığıyla (StrategyRuntime ->
    SessionManager.update — strategy_runtime.py:262-263 canlı yolu)
    6-major evren için güncel 19:00→01:00 UTC penceresinde (UTC+3
    22:00→04:00) onaylı sweep / bias-lock durumunu raporlar.

§2.2 REUSE — YENİ STRATEJİ FORMÜLÜ YAZILMADI; hepsi import:
    SIX_MAJORS evreni      src/live/parity_gate.py:33
    CBDR motoru            src/strategy/session.py SessionManager
                           (StrategyRuntime üzerinden — warmup ATR +
                            Wilder güncellemesi + session.update dahil,
                            birebir canlı per-bar yol)
    M1→15m                 src/live/candle_feed.resample_15m (frozen-mirror)
    M1 fetch               src/trading/mt5_connection.MT5Connection
                           + src/live/candle_feed.M1CandleFeed.fetch_m1
                           (server→UTC dönüşümü de import: :113-114)
    pencere saatleri       src/live/breakout_variant.py:69-70 (19, 1)

GÜVENLİK
    - Salt-okunur: MT5 copy_rates_from_pos (emir yok; state/ lock-audit
      dosyalarına dokunulmaz). Canlı Boot-B'ye (ayrı process) müdahale
      yok; MT5 API aynı terminale ikinci veri-bağlantısına izin verir.
    - Çıktı: stdout + state/cbdr_scan/<ts>.json (soak-izinli artefakt).

KULLANIM (repo kökünden)
    python scripts/cbdr_sweep_scan.py
    python scripts/cbdr_sweep_scan.py --count 6000 --json
    python scripts/cbdr_sweep_scan.py --symbols EURUSD,GBPUSD
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# T0#10 dersi: script-mode'da 'src' importu için repo kökü sys.path'e
# açıkça eklenir (module-mode çalıştırma tek başına yetmez).
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.live.candle_feed import M1CandleFeed, resample_15m  # noqa: E402
from src.live.parity_gate import SIX_MAJORS  # noqa: E402
from src.live.strategy_runtime import (  # noqa: E402
    SESSION_END_HOUR,
    SESSION_START_HOUR,
    StrategyRuntime,
)
from src.trading.mt5_connection import MT5Connection  # noqa: E402

DEFAULT_M1_COUNT = 4500  # ~75 saat M1 → on_bar kapsamı tam CBDR döngüsünü ezer


def _fmt_ts(ts) -> str:
    return ts.isoformat(sep=" ") if ts is not None else "-"


def scan_symbol(feed: M1CandleFeed, symbol: str, count: int) -> dict:
    """Tek sembolü canlı motor yoluyla tarar (warmup → on_bar akışı)."""
    bars_m1 = feed.fetch_m1(symbol, count=count)
    if not bars_m1 or len(bars_m1) < 300:
        return {
            "symbol": symbol,
            "status": "SKIP",
            "reason": f"M1 fetch yetersiz ({0 if not bars_m1 else len(bars_m1)} bar)",
        }

    bars_15m = resample_15m(bars_m1)

    rt = StrategyRuntime(symbol)
    rt.warmup(bars_15m)
    if not rt._warmed:  # noqa: SLF001 — canlıda da aynı alan kullanılır
        return {
            "symbol": symbol,
            "status": "SKIP",
            "reason": f"warmup başarısız (15m bar={len(bars_15m)}, min 100 gerekli)",
        }

    # Canlı per-bar yolu: on_bar -> session.update (strategy_runtime.py:262-263)
    fed = 0
    window_bars = 0  # güncel döngünün pencere-içi bar sayısı
    first_window_ts = last_window_ts = None
    cur_key = None
    for bar in bars_15m[rt._start_idx :]:
        rt.on_bar(bar)
        fed += 1
        key = rt.session.current_cbdr_key
        if key != cur_key:
            cur_key = key
            window_bars = 0
            first_window_ts = last_window_ts = None
        if rt.session.in_window(bar.timestamp.to_pydatetime()):
            window_bars += 1
            if first_window_ts is None:
                first_window_ts = bar.timestamp
            last_window_ts = bar.timestamp

    cb = rt.session.cbdr
    sweep_ts = None
    if cb.sweep_index is not None and 0 <= cb.sweep_index < len(rt.bars):
        sweep_ts = rt.bars[cb.sweep_index].timestamp

    return {
        "symbol": symbol,
        "status": "OK",
        "n_m1": len(bars_m1),
        "n_15m": len(bars_15m),
        "fed_bars": fed,
        "cbdr_key": cur_key,
        "window_bars": window_bars,
        "window_first": _fmt_ts(first_window_ts),
        "window_last": _fmt_ts(last_window_ts),
        "body_high": cb.body_high,
        "body_low": None if cb.body_low == float("inf") else cb.body_low,
        "locked": cb.locked,
        "bias_locked": cb.bias_locked,
        "sweep_confirmed": cb.sweep_confirmed,
        "sweep_direction": cb.sweep_direction.name if cb.sweep_direction else None,
        "sweep_level": cb.sweep_level,
        "sweep_ts": _fmt_ts(sweep_ts),
        "daily_bias": cb.daily_bias.name,
        "atr": rt.atr_val,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="CBDR sweep scan (6 majors, engine-import)")
    ap.add_argument("--count", type=int, default=DEFAULT_M1_COUNT, help="M1 bar sayısı")
    ap.add_argument(
        "--symbols",
        type=str,
        default=None,
        help="virgülle ayrılmış sembol listesi (varsayılan SIX_MAJORS)",
    )
    ap.add_argument("--json", action="store_true", help="state/cbdr_scan/ altına JSON yaz")
    args = ap.parse_args()

    symbols = (
        [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else list(SIX_MAJORS)
    )

    print("=" * 78)
    print("CBDR SWEEP SCAN — 6 MAJORS (engine-import, salt-okunur)")
    print("  motor        : StrategyRuntime.on_bar -> SessionManager.update (canlı yol)")
    print(
        f"  pencere      : UTC {SESSION_START_HOUR:02d}:00 -> {SESSION_END_HOUR:02d}:00 "
        f"(UTC+3 {SESSION_START_HOUR + 3:02d}:00 -> {SESSION_END_HOUR + 3:02d}:00)"
    )
    print(f"  evren        : {', '.join(symbols)}  (kaynak: src/live/parity_gate.py:33)")
    print(f"  M1 fetch     : {args.count} bar/sembol (copy_rates_from_pos, salt-okunur)")
    print("=" * 78)

    conn = MT5Connection()
    if not conn.connect():
        print("[FATAL] MT5 bağlantısı kurulamadı — tarama iptal.")
        return 1

    try:
        feed = M1CandleFeed()  # fetch_m1: get_rates + server→UTC (canlı dönüşüm)
        results = []
        for sym in symbols:
            print(f"\n[{sym}] taranıyor ...")
            row = scan_symbol(feed, sym, args.count)
            results.append(row)
            if row["status"] != "OK":
                print(f"  SKIP: {row.get('reason')}")
                continue
            print(
                f"  15m={row['n_15m']}  beslenen={row['fed_bars']}  "
                f"cbdr_key={row['cbdr_key']}  pencere_bar={row['window_bars']}"
            )
            print(
                f"  body: {row['body_low']} -> {row['body_high']}  locked={row['locked']}  "
                f"ATR={row['atr']:.6f}"
            )
            print(
                f"  sweep_confirmed={row['sweep_confirmed']}  "
                f"direction={row['sweep_direction']}  level={row['sweep_level']}  "
                f"ts={row['sweep_ts']}"
            )
            print(f"  bias_locked={row['bias_locked']}  daily_bias={row['daily_bias']}")

        print("\n" + "=" * 78)
        print("ÖZET (güncel CBDR döngüsü)")
        confirmed = [r for r in results if r.get("sweep_confirmed")]
        neutral = [r for r in results if r.get("status") == "OK" and not r.get("sweep_confirmed")]
        skipped = [r for r in results if r.get("status") == "SKIP"]
        if confirmed:
            for r in confirmed:
                print(
                    f"  SWEEP  {r['symbol']}: {r['sweep_direction']}  "
                    f"level={r['sweep_level']}  ts={r['sweep_ts']}  bias_locked=True"
                )
        else:
            print("  SWEEP  (yok) — onaylı sweep bulunamadı")
        for r in neutral:
            why = "pencere verisi yok" if not r.get("window_bars") else "tolerans aşan kapanış yok"
            print(f"  NEUTRAL {r['symbol']}: bias=neutral  ({why})")
        for r in skipped:
            print(f"  SKIP    {r['symbol']}: {r.get('reason')}")
        print("=" * 78)

        if args.json:
            out_dir = _REPO_ROOT / "state" / "cbdr_scan"
            out_dir.mkdir(parents=True, exist_ok=True)
            from datetime import datetime, timezone

            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            out = out_dir / f"cbdr_scan_{stamp}.json"
            out.write_text(
                json.dumps(
                    {
                        "engine": "StrategyRuntime.on_bar -> SessionManager.update",
                        "window_utc": f"{SESSION_START_HOUR:02d}:00->{SESSION_END_HOUR:02d}:00",
                        "universe_source": "src/live/parity_gate.py:33",
                        "m1_count": args.count,
                        "results": results,
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            print(f"JSON: {out}")
        return 0
    finally:
        conn.shutdown()


if __name__ == "__main__":
    sys.exit(main())
