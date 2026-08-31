"""38→38 parity verification — head-to-head on EURUSD 15m.

Runs the FROZEN canonical `run_test_a` and the LIVE `StrategyRuntime`
on the same 15m EURUSD series (windowed to 2026-06-25 → 2026-08-28,
the Phase 11 demo window). Reports the trade counts and per-trade
diff. Pass iff the two match exactly (parity at the 15m level).

Note: This is the strongest 38↔38 verification we can run offline
(without a live MT5 terminal). The 38-trade figure in the Phase 11
demo is the count produced by `run_test_a` on the 15m series
derived from the 65K M1 EURUSD window. The M1→15m ingest layer
is exercised by the F3 unit tests (test_f3_* in
tests/test_m1_ingestion_parity.py); the 15m→strategy layer is
exercised by THIS script. Together they cover the full
M1 → 15m → strategy → trade chain end-to-end.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO))

from src.live.strategy_runtime import StrategyRuntime  # noqa: E402
from src.strategy.models import Bar  # noqa: E402


def _load_eurusd_15m(window_start: str, window_end: str):
    df = pd.read_feather(_REPO / "data" / "icmarket_feather" / "EURUSD_15m.feather")
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df[(df["timestamp"] >= window_start) & (df["timestamp"] <= window_end)].reset_index(
        drop=True
    )
    return [
        Bar(
            index=i,
            timestamp=pd.Timestamp(ts),
            open=float(o),
            high=float(h),
            low=float(lo),
            close=float(c),
            volume=float(v),
        )
        for i, ts, o, h, lo, c, v in zip(
            range(len(df)),
            df["timestamp"],
            df["open"],
            df["high"],
            df["low"],
            df["close"],
            df["volume"],
        )
    ]


def main():
    bars_15m = _load_eurusd_15m("2026-06-25", "2026-08-28")
    print(f"EURUSD 15m bars in window: {len(bars_15m)}")
    if len(bars_15m) < 100:
        print("FAIL: not enough bars to warm up")
        sys.exit(1)

    from experiment.main_research_c_v1_0 import run_test_a

    canonical = run_test_a("EURUSD", bars_15m)
    n_can = len(canonical)
    print(f"Canonical (run_test_a): {n_can} trades")

    rt = StrategyRuntime("EURUSD")
    rt.warmup(bars_15m)
    if not rt._warmed:
        print("FAIL: live runtime did not warm up")
        sys.exit(1)
    live_signals = []
    for i in range(rt._next_idx, len(bars_15m)):
        sig = rt.on_bar(bars_15m[i])
        if sig is not None:
            live_signals.append(sig)
    n_live = len(live_signals)
    print(f"Live (StrategyRuntime): {n_live} signals")

    if n_can != n_live:
        print(f"PARITY FAILED: {n_can} != {n_live}")
        sys.exit(1)

    diffs = 0
    for k, (t, s) in enumerate(zip(canonical, live_signals)):
        fields = [
            ("direction", t.direction, s.direction),
            ("entry_price", t.entry_price, s.entry_price),
            ("sl", t.sl, s.sl),
            ("tp", t.tp, s.tp),
            ("entry_bar_index", t.entry_bar_index, s.entry_bar_index),
            ("sweep_bar_index", t.sweep_bar_index, s.sweep_bar_index),
            ("zone_index", t.zone_index, s.zone_index),
        ]
        for name, a, b in fields:
            if a != b:
                print(f"  trade#{k} {name}: canonical={a} live={b}")
                diffs += 1
    if diffs:
        print(f"PARITY FAILED: {diffs} field diffs")
        sys.exit(1)
    print("PARITY PASS: canonical == live verified.")


if __name__ == "__main__":
    main()
