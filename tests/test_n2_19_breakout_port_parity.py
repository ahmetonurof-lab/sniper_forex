#!/usr/bin/env python
"""N2 #19 — SRI-001 breakout-variant PORT PARİTE testleri.

Spec: `results/N2_19_breakout_port_spec.md` §5 — P-1 sabit-paritesi,
P-2 golden-run-paritesi, P-3 case-study-pin, P-4 negatif-kontrol,
P-5 (Faz-2d / §5.2) `exit_anchor` default-sadakati + canlı-uyumlu-dal invariantı.

Kanıt-seviyesi notu (§3 hiyerarşisi):
  - P-2, doğum-benchmark'ının KULLANDIĞI verinin kendisiyle (feather, 6 major,
    2.7Y) port'u trade-trade + trace-trace + sayaç-sayaç karşılaştırır. Float
    tolerans YOKTUR (`repr` düzeyinde eşitlik).
  - P-3, 2026-09-02 EURUSD case-study'sinin **repo'da kalıcılaştırılmış türetilmiş
    sayıları**yla (band/break/entry/tp/exit) çalışır. Ham 15m barları canlı MT5
    replay'den gelmişti ve feather 2026-08-21'de bittiği için gün yeniden-üretilmez
    (sentetik-gün-yeniden-yazımı §19 "fake-production-test" olurdu) — bkz. spec §5.1.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import List

import pandas as pd
import pytest

from src.live import breakout_variant as bv
from src.strategy.models import Bar

_ROOT = Path(__file__).resolve().parents[1]
_FEATHER = _ROOT / "data" / "icmarket_feather"
_REF_PATH = _ROOT / "results" / "exp_sri001_breakout_variant.json"

SIX_MAJORS = ("EURUSD", "AUDUSD", "GBPUSD", "GBPJPY", "USDCAD", "USDJPY")

# S-a: benchmark modülü YALNIZ salt-okunur import edilir (dosyasına dokunulmaz).
exp = pytest.importorskip(
    "experiment.exp_sri001_breakout_variant",
    reason="SRI-001 benchmark modulu bulunamadi",
)


def _ref() -> dict:
    return json.loads(_REF_PATH.read_text(encoding="utf-8"))


def _load_15m(symbol: str) -> List[Bar]:
    """Benchmark loader fork'u (:102-132) — to_utc YOK, aynı sıra/index."""
    path = _FEATHER / f"{symbol}_15m.feather"
    if not path.exists():
        pytest.skip(f"No 15m feather for {symbol}: {path}")
    df = pd.read_feather(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    ts = df["timestamp"].values
    op = df["open"].values.astype(float)
    hi = df["high"].values.astype(float)
    lo = df["low"].values.astype(float)
    cl = df["close"].values.astype(float)
    vo = df["volume"].values.astype(float)
    return [
        Bar(index=i, timestamp=pd.Timestamp(t), open=o, high=h, low=l, close=c, volume=v)
        for i, t, o, h, l, c, v in zip(range(len(ts)), ts, op, hi, lo, cl, vo)
    ]


def _norm(obj):
    """asdict çıktısını JSON-karşılaştırılabilir yapar (Timestamp -> str)."""
    if isinstance(obj, dict):
        return {k: _norm(x) for k, x in obj.items()}
    if isinstance(obj, list):
        return [_norm(x) for x in obj]
    if isinstance(obj, pd.Timestamp):
        return str(obj)
    return obj


# ────────────────────────────── P-1: sabit paritesi ──────────────────────────────
PORTED_CONSTANTS = (
    "DISPLACEMENT_BARS",
    "MSS_RANGE_FRACTION",
    "FVG_SEARCH_EXTRA_BARS",
    "RETEST_WINDOW_BARS",
    "TP_RR",
    "ATR_PERIOD",
    "MIN_RISK_DIST_ATR_MULT",
    "FVG_MIN_SIZE_ATR_MULT",
    "FVG_WICK_RATIO_MAX",
    "SESSION_START_HOUR",
    "SESSION_END_HOUR",
)


@pytest.mark.parametrize("name", PORTED_CONSTANTS)
def test_should_equal_benchmark_constant_when_ported(name):
    assert getattr(bv, name) == getattr(exp, name)


def test_should_equal_benchmark_atr_when_run_on_same_bars():
    bars = _load_15m("EURUSD")[:600]
    assert bv._compute_atr(bars, bv.ATR_PERIOD) == exp.compute_atr(bars, exp.ATR_PERIOD)


def test_should_keep_inline_tolerance_multiplier_at_half_atr():
    """Benchmark'da 0.5 satir-ici literaldir (:180/:295); port adlandirdi — deger pini."""
    assert bv.TOLERANCE_ATR_MULT == 0.5


def test_should_reject_chain4_when_only_chain6_is_ported():
    # ZİNCİR-4 doğumda RED aldı -> port modülünde kod-yolu yok (spec §2).
    with pytest.raises(ValueError):
        bv.run_breakout_chain("EURUSD", [], chain=4)
    with pytest.raises(ValueError):
        bv.evaluate_breakout_cycle(
            [], 0, session=None, atr_val=1.0, cycle_day="d", attempt_cycle=None, chain=4
        )


# ──────────────────────────── P-2: golden-run paritesi ───────────────────────────
@pytest.mark.parametrize("symbol", SIX_MAJORS)
def test_should_reproduce_benchmark_golden_run_when_ported(symbol):
    """Port, doğum-çıktısıyla trade-trade/trace-trace/sayaç-sayaç BİREBİR olmalı."""
    ref = _ref()["results"][symbol]["deney1_chain6"]
    trades, traces, counters = bv.run_breakout_chain(symbol, _load_15m(symbol))

    assert counters == ref["counters"]
    assert _norm([asdict(t) for t in trades]) == ref["trades"]
    assert _norm(traces) == ref["traces"]


def test_should_reproduce_total_benchmark_book_when_all_six_ported():
    """Çapalar: 512 trade / +412.00R (spec §3.3)."""
    ref = _ref()["results"]
    total_n = 0
    total_r = 0.0
    for symbol in SIX_MAJORS:
        ref6 = ref[symbol]["deney1_chain6"]
        trades, _, _ = bv.run_breakout_chain(symbol, _load_15m(symbol))
        total_n += len(trades)
        total_r += sum(t.pnl_r for t in trades)
        assert len(trades) == len(ref6["trades"])
    assert total_n == 512
    assert round(total_r, 2) == 412.00


# ─────────────────────────── P-3: case-study sabit-çivisi ────────────────────────
# 2026-09-02 EURUSD (RAPOR §3): short break 01:30 UTC -> retest entry 1.15799
# @03:45 -> SL 1.15833 -> TP 1.157378 -> TP vuruşu -> +1.8R.
def test_should_reproduce_case_study_entry_arithmetic_when_short():
    case = _ref()["case_study_2026_09_02"]
    entry = case["chain6"]["entry"]
    band = case["band"]
    sl, risk, tp = bv.build_entry("short", entry["price"], band["body_high"], band["body_low"])
    assert sl == entry["sl"]
    assert risk == entry["risk"]
    assert tp == entry["tp"]


def test_should_reproduce_case_study_pnl_r_when_tp_hit():
    """Case-study blogu R'yi 6-hane yuvarlanmis saklar (trace konvansiyonu :276).

    Ham bolme 1.7999999999999637 verir; dogum-iz-kaydi `round(pnl_r, 6)` ile
    1.8 yazar — port ayni konvansiyonu kullandigi icin baglama test edilir.
    (Ilk kosuda bu test ham-esitlik iddia etti ve KIRMIZI verdi; duzeltilen
    sey test-in iddiasidir, port degil — bkz. results/N2_19_parity_evidence.md §4.)
    """
    case = _ref()["case_study_2026_09_02"]["chain6"]
    entry = case["entry"]
    assert round((entry["price"] - case["exit"]) / entry["risk"], 6) == case["pnl_r"]


def test_should_reproduce_case_study_tolerance_and_pierce_threshold():
    """tol = 0.5 x session.atr (assumption 1) + short pierce = bl - tol."""
    case = _ref()["case_study_2026_09_02"]
    band, brk = case["band"], case["break"]
    tol = band["session_atr"] * 0.5
    assert tol == band["tolerance"]
    assert band["body_low"] - tol == brk["pierce_threshold"]
    assert brk["low"] < brk["pierce_threshold"] and brk["close"] < band["body_low"]


# ───────────────────────────── P-4: negatif kontroller ───────────────────────────
def test_should_change_trade_count_when_retest_window_collapsed(monkeypatch):
    """Parite 'her girdiye aynı çıktı' saflığında DEĞİL: pencere 1'e inerse bozulur."""
    bars = _load_15m("EURUSD")
    base = len(bv.run_breakout_chain("EURUSD", bars)[0])
    monkeypatch.setattr(bv, "RETEST_WINDOW_BARS", 1)
    assert len(bv.run_breakout_chain("EURUSD", bars)[0]) != base


def test_should_change_trade_count_when_displacement_shortened(monkeypatch):
    bars = _load_15m("EURUSD")
    base = len(bv.run_breakout_chain("EURUSD", bars)[0])
    monkeypatch.setattr(bv, "DISPLACEMENT_BARS", 2)
    assert len(bv.run_breakout_chain("EURUSD", bars)[0]) != base


def test_should_change_trade_count_when_tolerance_doubled(monkeypatch):
    """tol carpani 0.5 -> 1.0 olsaydi break kumesi degisirdi (assumption 1 canli testi)."""
    bars = _load_15m("EURUSD")
    base = len(bv.run_breakout_chain("EURUSD", bars)[0])
    monkeypatch.setattr(bv, "TOLERANCE_ATR_MULT", 1.0)
    assert len(bv.run_breakout_chain("EURUSD", bars)[0]) != base


# ─────────────── P-5: Faz-2d `exit_anchor` (spec §5.2 / D62) ───────────────────
@pytest.fixture(scope="module")
def eur_runs():
    """EURUSD tam-veride uc-kosum: parametresiz / acik-'break' / 'entry' (modul-cache)."""
    bars = _load_15m("EURUSD")
    return {
        "default": bv.run_breakout_chain("EURUSD", bars),
        "break": bv.run_breakout_chain("EURUSD", bars, exit_anchor=bv.EXIT_ANCHOR_BREAK),
        "entry": bv.run_breakout_chain("EURUSD", bars, exit_anchor=bv.EXIT_ANCHOR_ENTRY),
    }


def test_should_be_identical_when_exit_anchor_omitted_or_explicit_break(eur_runs):
    """F-2d(a) default-sadakati: acik-'break' cagrisi parametresiz-cagriyla BIREBIR.

    Bu, P-2 paritesinin API-degisikligi-sonrasi da ayakta oldugunun birim-duzey
    kanitidir (imza-eklemesi drift uretmedi).
    """
    d, b = eur_runs["default"], eur_runs["break"]
    assert _norm([asdict(t) for t in d[0]]) == _norm([asdict(t) for t in b[0]])
    assert _norm(d[1]) == _norm(b[1])
    assert d[2] == b[2]


def test_should_reject_unknown_exit_anchor():
    """Gecersiz-capa -> ValueError (sessiz-fallback YOK)."""
    bars = _load_15m("EURUSD")[:400]
    with pytest.raises(ValueError, match="exit_anchor"):
        bv.run_breakout_chain("EURUSD", bars, exit_anchor="tp")


def test_should_never_record_exit_before_entry_when_anchor_is_entry(eur_runs):
    """F-2d(c) invariant: 'entry' dalinda hold_bars<0 OLMAMALI; 'break' dalinda VAR.

    Ikinci-assert ayni zamanda D62'nin buyuklugunu olcer: sadik-dalda exit-before-entry
    gercek-veride gercekten gerceklesiyor (kod-yolu varsayim degil, gozlem).
    """
    entry_trades = eur_runs["entry"][0]
    break_trades = eur_runs["break"][0]
    assert entry_trades, "entry-dali hic trade uretmedi"
    assert [t.hold_bars for t in entry_trades if t.hold_bars < 0] == []
    assert all(t.exit_bar_index > t.entry_bar_index for t in entry_trades)
    neg = [t for t in break_trades if t.hold_bars < 0]
    assert neg, "break-dalda exit-before-entry yoksa D62 bulgusu kanitsiz kalir"


def test_should_change_book_when_anchor_is_entry(eur_runs):
    """Capa-secimi gercek-bir-lever: ticaret-sayisi ve/veya toplam-R degismeli.

    Degismeseydi Faz-2d olcumu bos-bir-islem olurdu (aktivite != dogruluk, spec §5).
    """
    nb, rb = len(eur_runs["break"][0]), round(sum(float(t.pnl_r) for t in eur_runs["break"][0]), 2)
    ne, re_ = len(eur_runs["entry"][0]), round(sum(float(t.pnl_r) for t in eur_runs["entry"][0]), 2)
    assert (nb, rb) != (ne, re_), f"capa-degisikligi kitabi hic degistirmedi: {nb}/{rb}"
