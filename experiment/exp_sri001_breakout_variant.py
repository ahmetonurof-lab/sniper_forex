"""SRI-001 — BREAKOUT-CONTINUATION VARIANT RESEARCH (Hakem icra-paketi).

MOD: Salt-okunur araştırma + yeni-experiment dosyası (freeze-dışı).
YASAK: src/, tests/, index.json, experiment/ içindeki mevcut dosyalar —
bu script YALNIZCA okur/import eder; hiçbir mevcut dosyayı değiştirmez.

AMAÇ (SRI-001, Hakem direktifi 2026-09-02):
  Mevcut motor fakeout+reclaim arar; breakout+continuation günlerini bilinçli
  reddeder (kanıt: 2026-09-02 EURUSD ~350 pip). Bu araştırma mevcut motoru
  DEĞİŞTİRMEZ — breakout-continuation'ı AYRI bir setup olarak ölçer.

BREAKOUT TANIMI (objektif, direktif §2):
  (a) pierce:   high > body_high + 0.5×tol  veya  low < body_low − 0.5×tol
                (tol = mevcut engine tolerance = 0.5 × session.atr — AYNI eşik)
  (b) close-acceptance: delme-barın CLOSE'u bandın DIŞINDA
  (c) displacement: N=4 bar içinde bandın içine GERİ KAPANMA YOK

ENTRY ZİNCİRLERİ (direktif §3):
  ZİNCİR-4: break + acceptance + displacement → entry = 4. displacement
            barının kapanışı.
  ZİNCİR-6: break + acceptance + displacement + MSS (CBDR-range ≥%50
            geçildi) + FVG (displacement-yönlü ilk FVG) + retest →
            entry = retest bar kapanışı.
  SL: CBDR bandı kıyısı (body_high/body_low — "bandına dönen fiyat" =
      breakout'un iptal koşulu).  TP: TP_RR = 1.8 (config aynen).

KOŞUM (direktif §4):
  DENEY-1: variant-only (chain-4 ve chain-6 ayrı kitler)
  DENEY-2: fakeout (kanonik, as-is) + breakout birleşik kit + overlap sayacı
  DENEY-3: kanonik kontrol grubu (run_test_a import — fingerprint doğrulama)

KANIT-STANDART (direktif §6):
  - Tüm sayılar exact run-çıktısı; her setup-kararı için bar-referansı
    (break/entry/exit bar index + timestamp + kural-bayrakları) JSON'da.
  - Kontrol-çapası: DENEY-3 fingerprint 2302T / +2875.00R / WR 69.37%
    (C v1.0 frozen baseline) ile birebir eşleşmek ZORUNDA.

Engine: experiment.main_research_c_v1_0.run_test_a (FROZEN canonical,
değiştirilmedi). FVG dedektörü: nexus detect_fvgs (motorla AYNI).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Setup paths ──
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd  # noqa: E402

from experiment.config import (  # noqa: E402
    ATR_PERIOD,
    FVG_MIN_SIZE_ATR_MULT,
    FVG_WICK_RATIO_MAX,
    MIN_RISK_DIST_ATR_MULT,
    SESSION_END_HOUR,
    SESSION_START_HOUR,
    TP_RR,
)
from experiment.main_research_c_v1_0 import (  # noqa: E402
    STARTING_BALANCE_R,
    BenchmarkTrade,
    _nexus_detect_fvgs,
    _to_nexus_bar,
    compute_atr,
    compute_stats,
    run_test_a,
)
from src.strategy.models import Bar  # noqa: E402
from src.strategy.session import SessionManager  # noqa: E402

SIX_MAJORS = ["EURUSD", "AUDUSD", "GBPUSD", "GBPJPY", "USDCAD", "USDJPY"]

# Kanonik kontrol-çapası (KNOW-GOOD v1.0 frozen baseline, 2026-08-28)
EXPECTED_FINGERPRINT = {"trades": 2302, "total_pnl": 2875.00, "win_rate": 69.37}

# Kanonik RUN_A per-symbol tablosu (docs/CBDR_TIME_SEMANTIC_ALIGNMENT_RAPORU.md §2.2)
EXPECTED_PER_SYMBOL = {
    "EURUSD": {"trades": 407, "total_pnl": 520.61, "win_rate": 73.0},
    "AUDUSD": {"trades": 388, "total_pnl": 443.48, "win_rate": 69.8},
    "GBPUSD": {"trades": 378, "total_pnl": 431.84, "win_rate": 70.6},
    "GBPJPY": {"trades": 394, "total_pnl": 391.21, "win_rate": 65.2},
    "USDCAD": {"trades": 366, "total_pnl": 605.77, "win_rate": 68.3},
    "USDJPY": {"trades": 369, "total_pnl": 482.10, "win_rate": 69.1},
}

DISPLACEMENT_BARS = 4  # N=4 (direktif §2c)
MSS_RANGE_FRACTION = 0.5  # MSS: CBDR-range ≥%50 (direktif §3)
FVG_SEARCH_EXTRA_BARS = 4  # FVG tamamlanma üst-bound: break+4 (disclosed assumption)
RETEST_WINDOW_BARS = 12  # retest bekleme üst-bound (disclosed assumption)


def load_15m(symbol: str) -> List[Bar]:
    """Load 15m feather — _run_symbol loader kopyası (values-array, aynı sıra).

    to_utc=YOK: feather timestamp'leri UTC'dir (§9.4 tahkim) ve kanonik
    fingerprint (2302T) ham-okuma semantiğiyle üretilmiştir — RUN_A paritesi.
    """
    feather_path = _PROJECT_ROOT / "data" / "icmarket_feather" / f"{symbol}_15m.feather"
    if not feather_path.exists():
        raise FileNotFoundError(f"Feather not found: {feather_path}")
    df = pd.read_feather(feather_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    timestamps = df["timestamp"].values
    opens = df["open"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    closes = df["close"].values.astype(float)
    volumes = df["volume"].values.astype(float)
    return [
        Bar(
            index=i,
            timestamp=pd.Timestamp(ts),
            open=o,
            high=h,
            low=l,
            close=c,
            volume=v,
        )
        for i, ts, o, h, l, c, v in zip(  # noqa: E741
            range(len(timestamps)), timestamps, opens, highs, lows, closes, volumes
        )
    ]


def run_breakout_chain(
    symbol: str,
    bars_15m: List[Bar],
    chain: int,
) -> Tuple[List[BenchmarkTrade], List[Dict[str, Any]], Dict[str, int]]:
    """SRI-001 breakout-variant koşumu (tek zincir, tek-pozisyon kit).

    Semantik-parite notlari:
      - ATR: compute_atr(warmup) + bar-başı Wilder güncelleme — run_test_a
        L193-194 + L224-231 birebir kopya.
      - SessionManager: run_test_a L198-205 ile AYNI kurulum (tolerance =
        0.5 × session.atr; engine session.atr'yi döngüde güncellemez →
        "mevcut tolerance ile AYNI eşik" = engine'in efektif eşiği).
      - Exit: 15m bar-üstü, SL-önce (worst-case) — check_exit L217-236
        sıralama-paritesi; trailing YOK (direktif: sabit TP 1.8R).
      - Kit: tek-pozisyon/sembol (engine kit-semantiği paritesi).
      - Döngü-başına 1 deneme: ilk break+acceptance barı denemi tüketir;
        zincir herhangi bir aşamada ölürse o döngüde trade yok.
    """
    counters: Dict[str, int] = {
        "bars": len(bars_15m),
        "break_bars_seen": 0,
        "reclaim_cancel_displacement": 0,
        "no_mss": 0,
        "no_fvg": 0,
        "reclaim_cancel_wait": 0,
        "no_retest": 0,
        "min_risk_skip": 0,
        "pathological_both_sides": 0,
        "data_end_short": 0,
        "entries": 0,
    }
    if len(bars_15m) < 100:
        return [], [], counters

    warmup = min(100, len(bars_15m) - 10)
    atr_val = compute_atr(bars_15m[:warmup], period=ATR_PERIOD)
    if atr_val <= 0:
        return [], [], counters

    session = SessionManager(
        symbol=symbol,
        start_hour=SESSION_START_HOUR,
        end_hour=SESSION_END_HOUR,
        atr=atr_val,
        sweep_atr_tolerance_mult=0.5,
        sweep_default_tolerance=10.0,
    )
    daykey = SessionManager(
        symbol=symbol,
        start_hour=SESSION_START_HOUR,
        end_hour=SESSION_END_HOUR,
    )

    trades: List[BenchmarkTrade] = []
    traces: List[Dict[str, Any]] = []
    trade_counter = 0
    position: Optional[Dict[str, Any]] = None
    attempt_cycle: Optional[str] = None

    start_idx = warmup + 1
    for i in range(start_idx, len(bars_15m)):
        bar = bars_15m[i]

        if i > start_idx:
            prev_close = bars_15m[i - 1].close
            tr = max(
                bar.high - bar.low,
                abs(bar.high - prev_close),
                abs(bar.low - prev_close),
            )
            atr_val = (atr_val * (ATR_PERIOD - 1) + tr) / ATR_PERIOD

        # Band takibi — sweep-return'u bilerek yok sayıyoruz: kanonik sweep
        # akışı DENEY-3'te run_test_a tarafından bağımsız üretilir; band
        # izleme sweep'den etkilenmez (session.py: track_body/lock/reset).
        session.update(bar)

        # ── Açık pozisyon yönetimi (SL-önce, check_exit paritesi) ──
        if position is not None:
            exit_price: Optional[float] = None
            result = ""
            if position["side"] == "long":
                if bar.low <= position["sl"]:
                    exit_price = position["sl"]
                    result = "LOSS"
                elif bar.high >= position["tp"]:
                    exit_price = position["tp"]
                    result = "TP"
            else:
                if bar.high >= position["sl"]:
                    exit_price = position["sl"]
                    result = "LOSS"
                elif bar.low <= position["tp"]:
                    exit_price = position["tp"]
                    result = "TP"
            if exit_price is not None:
                if result == "LOSS":
                    pnl_r = -1.0
                else:
                    risk = abs(position["entry_price"] - position["sl"])
                    if position["side"] == "long":
                        pnl_r = (exit_price - position["entry_price"]) / risk
                    else:
                        pnl_r = (position["entry_price"] - exit_price) / risk
                trade_counter += 1
                trades.append(
                    BenchmarkTrade(
                        trade_id=trade_counter,
                        symbol=symbol,
                        test_type=f"SRI001_CHAIN{chain}",
                        direction=position["side"],
                        entry_price=position["entry_price"],
                        sl=position["sl"],
                        tp=position["tp"],
                        entry_bar_index=position["entry_bar"],
                        sweep_bar_index=position["break_bar"],
                        zone_index=0,
                        zone_creation_bar=0,
                        zone_top=position["zone_top"],
                        zone_bottom=position["zone_bottom"],
                        zone_size=position["zone_size"],
                        zone_size_atr=position["zone_size_atr"],
                        sweep_size_atr=position["sweep_size_atr"],
                        bars_sweep_to_zone=position["bars_sweep_to_zone"],
                        bars_zone_to_entry=position["bars_zone_to_entry"],
                        exit_price=exit_price,
                        exit_bar_index=i,
                        exit_timestamp=bar.timestamp,
                        result=result,
                        pnl_r=pnl_r,
                        hold_bars=i - position["entry_bar"],
                    )
                )
                traces.append(
                    {
                        **position["trace"],
                        "exit_bar_index": i,
                        "exit_timestamp": str(bar.timestamp),
                        "exit_price": exit_price,
                        "result": result,
                        "pnl_r": round(pnl_r, 6),
                    }
                )
                position = None
            continue

        # ── Breakout setup değerlendirmesi (yalnızca pencere-dışı + flat) ──
        dt = bar.timestamp.to_pydatetime()
        if session.in_window(dt):
            continue

        cb = session.cbdr
        if not cb.locked or cb.body_high <= 0.0 or cb.body_low == float("inf"):
            continue

        day = daykey.cbdr_day_key(dt)
        if attempt_cycle == day:
            continue  # döngü-başına 1 deneme kuralı

        tol = session.atr * 0.5
        bh, bl = cb.body_high, cb.body_low
        rng = bh - bl
        if rng <= 0:
            continue

        long_break = bar.high > bh + tol and bar.close > bh
        short_break = bar.low < bl - tol and bar.close < bl
        if not (long_break or short_break):
            continue

        counters["break_bars_seen"] += 1
        attempt_cycle = day
        if long_break and short_break:
            counters["pathological_both_sides"] += 1
            traces.append(
                {
                    "cycle_day": day,
                    "break_bar_index": i,
                    "break_timestamp": str(bar.timestamp),
                    "dead_at": "PATHOLOGICAL_BOTH_SIDES",
                }
            )
            continue

        side = "long" if long_break else "short"
        b = i

        # Displacement barları b+1..b+4 mevcut mu?
        if b + DISPLACEMENT_BARS >= len(bars_15m):
            counters["data_end_short"] += 1
            continue
        disp = bars_15m[b + 1 : b + 1 + DISPLACEMENT_BARS]

        trace: Dict[str, Any] = {
            "chain": chain,
            "cycle_day": day,
            "break_bar_index": b,
            "break_timestamp": str(bar.timestamp),
            "side": side,
            "body_high": bh,
            "body_low": bl,
            "band_range": rng,
            "tolerance": tol,
            "tolerance_source": "0.5 * session.atr (engine-parity: run_test_a kurulum-ATR)",
            "atr_at_break": atr_val,
            "displacement_bars": DISPLACEMENT_BARS,
        }

        # (c) displacement: 4 bar içinde bandın içine geri kapanma YOK
        if side == "long":
            reclaimed = any(bb.close < bh for bb in disp)
        else:
            reclaimed = any(bb.close > bl for bb in disp)
        if reclaimed:
            counters["reclaim_cancel_displacement"] += 1
            traces.append({**trace, "dead_at": "RECLAIM_DISPLACEMENT"})
            continue

        if chain == 4:
            # ZİNCİR-4: entry = displacement 4. barının kapanışı
            e_idx = b + DISPLACEMENT_BARS
            entry_price: float = bars_15m[e_idx].close
            trace["mss_penetration"] = None
            trace["mss_ratio"] = None
            trace["fvg"] = None
            trace["retest_bar_index"] = None
        else:
            # ZİNCİR-6 aşama 1 — MSS: displacement bacağında (barlar b..b+4)
            # band-ötesi maksimum penetrasyon ≥ 0.5 × band-range (direktif §3
            # "CBDR-range ≥%50 geçildi").
            if side == "long":
                pen = max(x.high for x in [bar] + disp) - bh
            else:
                pen = bl - min(x.low for x in [bar] + disp)
            trace["mss_penetration"] = pen
            trace["mss_ratio"] = pen / rng if rng > 0 else 0.0
            if pen < MSS_RANGE_FRACTION * rng:
                counters["no_mss"] += 1
                traces.append({**trace, "dead_at": "NO_MSS"})
                continue

            # ZİNCİR-6 aşama 2 — FVG: displacement-yönlü İLK FVG (nexus
            # detect_fvgs — motorla AYNI dedektör). Tamamlanma barı
            # (real_index+2) aralığı: b+1 .. b+4+FVG_SEARCH_EXTRA_BARS.
            side_str = "bullish" if side == "long" else "bearish"
            fvg = None
            fvg_comp = -1
            dead_at: Optional[str] = None
            j_max = min(b + DISPLACEMENT_BARS + FVG_SEARCH_EXTRA_BARS, len(bars_15m) - 1)
            for j in range(b + DISPLACEMENT_BARS, j_max + 1):
                # FVG bekleme sırasında reclaim-ölü kontrolü (b+5..j)
                dead = False
                for m in range(b + DISPLACEMENT_BARS + 1, j + 1):
                    if side == "long" and bars_15m[m].close < bh:
                        dead = True
                        break
                    if side == "short" and bars_15m[m].close > bl:
                        dead = True
                        break
                if dead:
                    dead_at = f"reclaim_wait@{j}"
                    break
                chunk = bars_15m[max(0, j - 60) : j + 1]
                fvgs = _nexus_detect_fvgs(
                    [_to_nexus_bar(x) for x in chunk],
                    lookback=min(50, len(chunk)),
                    timeframe="15m",
                    min_fvg_size=max(atr_val * FVG_MIN_SIZE_ATR_MULT, 1e-8),
                    max_wick_ratio=FVG_WICK_RATIO_MAX,
                )
                cands = [
                    f
                    for f in fvgs
                    if f.direction == side_str and (b + 1) <= (f.real_index + 2) <= j
                ]
                if cands:
                    fvg = min(cands, key=lambda f: f.real_index)
                    fvg_comp = fvg.real_index + 2
                    break
            if fvg is None:
                if dead_at:
                    counters["reclaim_cancel_wait"] += 1
                else:
                    counters["no_fvg"] += 1
                traces.append({**trace, "dead_at": dead_at or "NO_FVG"})
                continue

            trace["fvg"] = {
                "real_index": fvg.real_index,
                "complete_bar": fvg_comp,
                "top": fvg.top,
                "bottom": fvg.bottom,
                "size": fvg.size,
                "direction": fvg.direction,
            }

            # ZİNCİR-6 aşama 3 — Retest: displacement tamamlanıp (b+4) FVG
            # zone'a dokunuş; entry = retest bar kapanışı. Band-içi kapanış
            # (reclaim) = breakout iptali.
            k_start = max(fvg_comp + 1, b + DISPLACEMENT_BARS + 1)
            k_end = min(fvg_comp + RETEST_WINDOW_BARS, len(bars_15m) - 1)
            e_idx = None
            entry_price = None
            retest_dead: Optional[str] = None
            for k in range(k_start, k_end + 1):
                kb = bars_15m[k]
                if side == "long":
                    if kb.close < bh:
                        retest_dead = f"reclaim_retest@{k}"
                        break
                    if kb.low <= fvg.top and kb.close > bh:
                        e_idx = k
                        entry_price = kb.close
                        break
                else:
                    if kb.close > bl:
                        retest_dead = f"reclaim_retest@{k}"
                        break
                    if kb.high >= fvg.bottom and kb.close < bl:
                        e_idx = k
                        entry_price = kb.close
                        break
            if entry_price is None:
                if retest_dead:
                    counters["reclaim_cancel_wait"] += 1
                else:
                    counters["no_retest"] += 1
                traces.append({**trace, "dead_at": retest_dead or "NO_RETEST"})
                continue
            trace["retest_bar_index"] = e_idx

        # ── Ortak giriş-inşası: SL = band kıyısı, TP = TP_RR (config aynen) ──
        sl = bh if side == "long" else bl
        risk = (entry_price - sl) if side == "long" else (sl - entry_price)
        if risk < atr_val * MIN_RISK_DIST_ATR_MULT:
            counters["min_risk_skip"] += 1
            traces.append({**trace, "dead_at": "MIN_RISK", "risk": risk})
            continue
        tp = entry_price + risk * TP_RR if side == "long" else entry_price - risk * TP_RR

        if chain == 6:
            sweep_size_atr = (trace["mss_penetration"] or 0.0) / atr_val if atr_val > 0 else 0.0
            bars_sweep_to_zone = (fvg_comp - b) if fvg_comp > 0 else 0
        else:
            sweep_size_atr = risk / atr_val if atr_val > 0 else 0.0
            bars_sweep_to_zone = 0

        trace.update(
            {
                "entry_bar_index": e_idx,
                "entry_timestamp": str(bars_15m[e_idx].timestamp),
                "entry_price": entry_price,
                "sl": sl,
                "tp": tp,
                "risk": risk,
                "tp_rr": TP_RR,
            }
        )
        counters["entries"] += 1
        position = {
            "side": side,
            "entry_price": entry_price,
            "sl": sl,
            "tp": tp,
            "entry_bar": e_idx,
            "break_bar": b,
            "zone_top": bh,
            "zone_bottom": bl,
            "zone_size": rng,
            "zone_size_atr": rng / atr_val if atr_val > 0 else 0.0,
            "sweep_size_atr": sweep_size_atr,
            "bars_sweep_to_zone": bars_sweep_to_zone,
            "bars_zone_to_entry": e_idx - b,
            "trace": trace,
        }

    # Data sonu — açık pozisyonu engine-OPEN konvansiyonuyla kapat (MTM)
    if position is not None:
        last_bar = bars_15m[-1]
        exit_price = last_bar.close
        risk = abs(position["entry_price"] - position["sl"])
        if position["side"] == "long":
            pnl_r = (exit_price - position["entry_price"]) / risk
        else:
            pnl_r = (position["entry_price"] - exit_price) / risk
        trade_counter += 1
        trades.append(
            BenchmarkTrade(
                trade_id=trade_counter,
                symbol=symbol,
                test_type=f"SRI001_CHAIN{chain}",
                direction=position["side"],
                entry_price=position["entry_price"],
                sl=position["sl"],
                tp=position["tp"],
                entry_bar_index=position["entry_bar"],
                sweep_bar_index=position["break_bar"],
                zone_index=0,
                zone_creation_bar=0,
                zone_top=position["zone_top"],
                zone_bottom=position["zone_bottom"],
                zone_size=position["zone_size"],
                zone_size_atr=position["zone_size_atr"],
                sweep_size_atr=position["sweep_size_atr"],
                bars_sweep_to_zone=position["bars_sweep_to_zone"],
                bars_zone_to_entry=position["bars_zone_to_entry"],
                exit_price=exit_price,
                exit_bar_index=len(bars_15m) - 1,
                exit_timestamp=last_bar.timestamp,
                result="OPEN",
                pnl_r=pnl_r,
                hold_bars=len(bars_15m) - 1 - position["entry_bar"],
            )
        )
        traces.append(
            {
                **position["trace"],
                "exit_bar_index": len(bars_15m) - 1,
                "exit_timestamp": str(last_bar.timestamp),
                "exit_price": exit_price,
                "result": "OPEN",
                "pnl_r": round(pnl_r, 6),
            }
        )

    return trades, traces, counters


def run_symbol_all(symbol: str, dry_run: bool) -> Dict[str, Any]:
    """Bir sembol: DENEY-3 (kanonik) + DENEY-1 (chain4/chain6) + DENEY-2/overlap."""
    t0 = time.time()
    bars_15m = load_15m(symbol)
    if dry_run:
        bars_15m = bars_15m[:2000]
    print(f"  [{symbol}] loaded {len(bars_15m)} 15m bars", flush=True)

    canon_trades = run_test_a(symbol, bars_15m)
    print(f"  [{symbol}] DENEY-3 canonical: {len(canon_trades)} trades", flush=True)

    c4_trades, c4_traces, c4_counters = run_breakout_chain(symbol, bars_15m, chain=4)
    print(f"  [{symbol}] DENEY-1 chain4: {len(c4_trades)} trades", flush=True)

    c6_trades, c6_traces, c6_counters = run_breakout_chain(symbol, bars_15m, chain=6)
    print(f"  [{symbol}] DENEY-1 chain6: {len(c6_trades)} trades", flush=True)

    combined4 = list(canon_trades) + list(c4_trades)
    combined6 = list(canon_trades) + list(c6_trades)

    daykey = SessionManager(symbol, SESSION_START_HOUR, SESSION_END_HOUR)

    def day_dir_map(trades: List[BenchmarkTrade]) -> Dict[Tuple[str, str], Dict[str, Any]]:
        out: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for t in trades:
            ref_idx = (
                t.sweep_bar_index if 0 <= t.sweep_bar_index < len(bars_15m) else t.entry_bar_index
            )
            ts = bars_15m[ref_idx].timestamp.to_pydatetime()
            day = daykey.cbdr_day_key(ts)
            d = "long" if t.direction in ("bullish", "long") else "short"
            rec = out.setdefault((day, d), {"n": 0, "r": 0.0, "completed": 0})
            rec["n"] += 1
            if t.result in ("TP", "PROFIT_TRAIL", "LOSS"):
                rec["completed"] += 1
                rec["r"] += t.pnl_r
        return out

    canon_map = day_dir_map(canon_trades)
    c4_map = day_dir_map(c4_trades)
    c6_map = day_dir_map(c6_trades)

    def overlap_analysis(var_map: Dict[Tuple[str, str], Dict[str, Any]]) -> Dict[str, Any]:
        keys = sorted(set(canon_map) & set(var_map))
        recs = []
        for k in keys:
            recs.append(
                {
                    "cycle_day": k[0],
                    "direction": k[1],
                    "canon_n": canon_map[k]["n"],
                    "canon_r": round(canon_map[k]["r"], 4),
                    "variant_n": var_map[k]["n"],
                    "variant_r": round(var_map[k]["r"], 4),
                    "combined_r": round(canon_map[k]["r"] + var_map[k]["r"], 4),
                }
            )
        return {
            "overlap_count": len(recs),
            "canon_r_sum": round(sum(r["canon_r"] for r in recs), 4),
            "variant_r_sum": round(sum(r["variant_r"] for r in recs), 4),
            "combined_r_sum": round(sum(r["combined_r"] for r in recs), 4),
            "delta_vs_fakeout_only": round(sum(r["variant_r"] for r in recs), 4),
            "records": recs,
        }

    all_days = sorted({k[0] for k in canon_map} | {k[0] for k in c4_map} | {k[0] for k in c6_map})
    day_classes: List[Dict[str, Any]] = []
    for d in all_days:
        c_n = sum(v["n"] for (dd, _), v in canon_map.items() if dd == d)
        c_r = sum(v["r"] for (dd, _), v in canon_map.items() if dd == d)
        v4_n = sum(v["n"] for (dd, _), v in c4_map.items() if dd == d)
        v4_r = sum(v["r"] for (dd, _), v in c4_map.items() if dd == d)
        v6_n = sum(v["n"] for (dd, _), v in c6_map.items() if dd == d)
        v6_r = sum(v["r"] for (dd, _), v in c6_map.items() if dd == d)
        cls = (
            "both"
            if (c_n and (v4_n or v6_n))
            else "fakeout_only"
            if c_n
            else "breakout_only"
            if (v4_n or v6_n)
            else "neither"
        )
        day_classes.append(
            {
                "cycle_day": d,
                "class": cls,
                "canon_n": c_n,
                "canon_r": round(c_r, 4),
                "chain4_n": v4_n,
                "chain4_r": round(v4_r, 4),
                "chain6_n": v6_n,
                "chain6_r": round(v6_r, 4),
            }
        )

    trend_days_c4 = [r for r in day_classes if r["chain4_n"]]
    fakeout_days_c4 = [r for r in day_classes if r["canon_n"]]

    return {
        "symbol": symbol,
        "bars": len(bars_15m),
        "elapsed_s": round(time.time() - t0, 1),
        "deney3_canonical": {
            "stats": compute_stats(canon_trades),
            "trades": [asdict(t) for t in canon_trades],
        },
        "deney1_chain4": {
            "stats": compute_stats(c4_trades),
            "trades": [asdict(t) for t in c4_trades],
            "traces": c4_traces,
            "counters": c4_counters,
        },
        "deney1_chain6": {
            "stats": compute_stats(c6_trades),
            "trades": [asdict(t) for t in c6_trades],
            "traces": c6_traces,
            "counters": c6_counters,
        },
        "deney2_combined_chain4": {"stats": compute_stats(combined4)},
        "deney2_combined_chain6": {"stats": compute_stats(combined6)},
        "overlap_chain4": overlap_analysis(c4_map),
        "overlap_chain6": overlap_analysis(c6_map),
        "day_classes": day_classes,
        "trend_days_chain4": {
            "count": len(trend_days_c4),
            "variant_r": round(sum(r["chain4_r"] for r in trend_days_c4), 4),
            "canon_r_on_same_days": round(sum(r["canon_r"] for r in trend_days_c4), 4),
        },
        "fakeout_days_chain4": {
            "count": len(fakeout_days_c4),
            "canon_r": round(sum(r["canon_r"] for r in fakeout_days_c4), 4),
            "variant_r_on_same_days": round(sum(r["chain4_r"] for r in fakeout_days_c4), 4),
        },
    }


def _fmt(s: Dict[str, Any]) -> str:
    return (
        f"{s['trades']:>5d}T {s['wins']:>4d}W/{s['losses']:>4d}L "
        f"WR {s['win_rate']:>5.1f}% {s['total_pnl']:>+9.2f}R "
        f"AvgR {s['avg_r']:>+6.3f} PF {s['profit_factor']:>5.2f} "
        f"DD {s['max_dd']:>6.2f}R ({s['max_dd_pct']:>5.2f}%)"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="SRI-001 breakout-variant research")
    parser.add_argument("symbols", nargs="*", help="Symbols (default: 6 majors)")
    parser.add_argument("--dry-run", action="store_true", help="Smoke test (first 2000 bars)")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    symbols = [s.upper() for s in args.symbols] if args.symbols else SIX_MAJORS
    print("=== SRI-001 BREAKOUT-CONTINUATION VARIANT RESEARCH ===")
    print(f"Symbols: {symbols} | dry_run={args.dry_run} | workers={args.workers}")
    print("Engine (DENEY-3): experiment.main_research_c_v1_0.run_test_a (FROZEN, as-is)")
    print(f"Expected control fingerprint: {EXPECTED_FINGERPRINT}")
    print()

    results: Dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(run_symbol_all, sym, args.dry_run): sym for sym in symbols}
        for fut in as_completed(futs):
            sym = futs[fut]
            results[sym] = fut.result()

    # ── Validation block (DENEY-3 control anchor) ──
    order = [s for s in SIX_MAJORS if s in results]
    tot_w = sum(results[s]["deney3_canonical"]["stats"]["wins"] for s in order)
    tot_c = sum(
        results[s]["deney3_canonical"]["stats"]["wins"]
        + results[s]["deney3_canonical"]["stats"]["losses"]
        for s in order
    )
    agg_canon = {
        "trades": sum(results[s]["deney3_canonical"]["stats"]["trades"] for s in order),
        "total_pnl": round(
            sum(results[s]["deney3_canonical"]["stats"]["total_pnl"] for s in order), 4
        ),
        "win_rate": round(tot_w / tot_c * 100, 2) if tot_c else 0.0,
    }
    fp_ok = (
        agg_canon["trades"] == EXPECTED_FINGERPRINT["trades"]
        and abs(agg_canon["total_pnl"] - EXPECTED_FINGERPRINT["total_pnl"]) < 0.01
        and abs(agg_canon["win_rate"] - EXPECTED_FINGERPRINT["win_rate"]) < 0.01
    )

    print("=== VALIDATION — DENEY-3 CONTROL ANCHOR ===")
    print(
        f"expected: {EXPECTED_FINGERPRINT['trades']}T "
        f"{EXPECTED_FINGERPRINT['total_pnl']:+.2f}R WR {EXPECTED_FINGERPRINT['win_rate']}%"
    )
    print(
        f"actual:   {agg_canon['trades']}T {agg_canon['total_pnl']:+.2f}R "
        f"WR {agg_canon['win_rate']}%"
    )
    print(f"MATCH: {'YES' if fp_ok else 'NO — INVESTIGATE (results NOT decision-grade)'}")
    print()

    # ── Kit tabloları: DENEY-1 / DENEY-2 / DENEY-3 ──
    def book_table(label: str, key: str) -> None:
        print(f"=== {label} ===")
        print(
            f"{'Symbol':<8} {'N':>5} {'WR%':>6} {'PnL(R)':>10} {'AvgR':>8} {'PF':>6} {'DD(R)':>7} {'DD%':>6}"
        )
        for s in order:
            st = results[s][key]["stats"]
            print(
                f"{s:<8} {st['trades']:>5d} {st['win_rate']:>5.1f} {st['total_pnl']:>+9.2f} "
                f"{st['avg_r']:>+7.3f} {st['profit_factor']:>5.2f} {st['max_dd']:>6.2f} {st['max_dd_pct']:>5.2f}"
            )
        tot_t = sum(results[s][key]["stats"]["trades"] for s in order)
        tot_p = sum(results[s][key]["stats"]["total_pnl"] for s in order)
        tw = sum(results[s][key]["stats"]["wins"] for s in order)
        tc = sum(
            results[s][key]["stats"]["wins"] + results[s][key]["stats"]["losses"] for s in order
        )
        wr = (tw / tc * 100) if tc else 0.0
        print(f"{'TOTAL':<8} {tot_t:>5d} {wr:>5.1f} {tot_p:>+9.2f}")
        print()

    book_table("DENEY-1a — BREAKOUT VARIANT ONLY (CHAIN-4)", "deney1_chain4")
    book_table("DENEY-1b — BREAKOUT VARIANT ONLY (CHAIN-6)", "deney1_chain6")
    book_table("DENEY-3 — CANONICAL CONTROL (FAKEOUT ONLY)", "deney3_canonical")
    book_table("DENEY-2a — COMBINED (CANONICAL + CHAIN-4)", "deney2_combined_chain4")
    book_table("DENEY-2b — COMBINED (CANONICAL + CHAIN-6)", "deney2_combined_chain6")

    for s in order:
        for ch, key in (("4", "overlap_chain4"), ("6", "overlap_chain6")):
            ov = results[s][key]
            print(
                f"OVERLAP chain{ch} {s}: days={ov['overlap_count']} "
                f"canon_R={ov['canon_r_sum']:+.2f} variant_R={ov['variant_r_sum']:+.2f} "
                f"combined_R={ov['combined_r_sum']:+.2f}"
            )
    print()
    for s in order:
        td = results[s]["trend_days_chain4"]
        fd = results[s]["fakeout_days_chain4"]
        print(
            f"DAYS {s}: trend-days(chain4 fired)={td['count']} var_R={td['variant_r']:+.2f} "
            f"canon_R_same_days={td['canon_r_on_same_days']:+.2f} | "
            f"fakeout-days={fd['count']} canon_R={fd['canon_r']:+.2f} "
            f"var_R_same_days={fd['variant_r_on_same_days']:+.2f}"
        )
    print()

    # ── Save JSON ──
    out_path = (
        Path(args.out)
        if args.out
        else _PROJECT_ROOT / "results" / "exp_sri001_breakout_variant.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        head_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(_PROJECT_ROOT), text=True
        ).strip()
    except Exception:
        head_sha = "unavailable"

    save = {
        "spec": "SRI-001 breakout-continuation variant research (Hakem icra-paketi 2026-09-02)",
        "provenance": {
            "head_sha": head_sha,
            "engine_deney3": "experiment.main_research_c_v1_0.run_test_a (FROZEN, imported as-is)",
            "fvg_detector": "nexus detect_fvgs (same as engine)",
            "dataset": "data/icmarket_feather/*_15m.feather (6 major, 2.7Y, UTC naive — §9.4 tahkim)",
            "time_semantics": "to_utc=False (RUN_A paritesi: CBDR 19->01 feather-native UTC)",
            "config_echo": {
                "TP_RR": TP_RR,
                "MIN_RISK_DIST_ATR_MULT": MIN_RISK_DIST_ATR_MULT,
                "FVG_MIN_SIZE_ATR_MULT": FVG_MIN_SIZE_ATR_MULT,
                "FVG_WICK_RATIO_MAX": FVG_WICK_RATIO_MAX,
                "ATR_PERIOD": ATR_PERIOD,
                "SESSION_START_HOUR": SESSION_START_HOUR,
                "SESSION_END_HOUR": SESSION_END_HOUR,
                "STARTING_BALANCE_R": STARTING_BALANCE_R,
                "DISPLACEMENT_BARS": DISPLACEMENT_BARS,
                "MSS_RANGE_FRACTION": MSS_RANGE_FRACTION,
                "FVG_SEARCH_EXTRA_BARS": FVG_SEARCH_EXTRA_BARS,
                "RETEST_WINDOW_BARS": RETEST_WINDOW_BARS,
            },
            "disclosed_assumptions": [
                "tolerance = 0.5 * session.atr (engine-parity: run_test_a SessionManager kurulum-ATR, dongude guncellenmez)",
                "SL = band kivisi (body_high/body_low) — direktif 'CBDR bandina donen fiyat' yorumu",
                "chain-6 zaman bound'lari: FVG tamamlanma <= break+8; retest break+5 sonrasi <= 12 bar (direktif sessiz; acik varsayim)",
                "tek-pozisyon/sembol kit semantigi (engine parite); pozisyon acikken setup degerlendirilmez",
                "dongu-basina 1 deneme (ilk break+acceptance bari denemi tuketir)",
                "MSS = max penetrasyon (barlar break..break+4) >= 0.5 * band_range",
                "exit 15m bar-ustu, SL-once (check_exit parite); trailing YOK (sabit TP 1.8R)",
                "entry bar kapanisinda giris; exit kontrolleri sonraki bardan",
                "DENEY-2 birlesik kitlerde ayni gun kanonik+variant eszamanli pozisyon mumkun",
            ],
        },
        "validation": {
            "expected_fingerprint": EXPECTED_FINGERPRINT,
            "actual_fingerprint": agg_canon,
            "fingerprint_match": fp_ok,
            "expected_per_symbol": EXPECTED_PER_SYMBOL,
        },
        "results": {s: results[s] for s in order},
        "case_study_2026_09_02": None,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(save, f, indent=2, default=str)
    print(f"Results saved to {out_path}")
    return 0 if fp_ok else 1


if __name__ == "__main__":
    sys.exit(main())
