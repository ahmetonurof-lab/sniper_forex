#!/usr/bin/env python
"""N2#26-REIS-DİREKTİFİ (N2#25 revizyonu): audit.jsonl → okunabilir .log.

REIS kararları (2026-09-06, askQuestions):
  - Format : yerel saat + offset  →  2026-09-05 22:13:00 +0300
  - Konum  : logs/<PARİTE>/live.log  (kanonik; logs/ gitignored)
  - STATE  : bar_ts göster (cold-rebuild replay burst'ünü ayırt etmek için)

Zaman-dilimi disiplini (§6.3): proje kuralı naive = UTC
(orchestrator.py:76). Event epoch → yerel+offset; bar_ts (naive-UTC) →
yerel+offset. Offset her satırda açık → naive-karışım yasağı korunur.

Kullanım:
    python tools/make_readable_log.py <audit.jsonl>              → logs/<SYMBOL>/live.log
    python tools/make_readable_log.py <audit.jsonl> <çıktı.log>  → explicit (test)
"""

import datetime
import json
import os
import sys

ENTRY_EVENTS = ("SIGNAL", "RISK", "ORDER", "FILL", "POSITION", "EXIT")


def _fmt_local(epoch: float) -> str:
    """Epoch → yerel saat + offset (2026-09-05 22:13:00 +0300)."""
    return datetime.datetime.fromtimestamp(epoch).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")


def _fmt_bar_ts(bar_ts: str, fallback_epoch: float) -> str:
    """Naive-UTC bar_ts → yerel saat + offset (proje kuralı: naive = UTC)."""
    try:
        dt = datetime.datetime.fromisoformat(bar_ts)
    except ValueError:
        return _fmt_local(fallback_epoch)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S %z")


def _derive_symbol(records: list) -> str:
    """İlk gerçek symbol (audit tek-parite botudur)."""
    for r in records:
        sym = r.get("symbol")
        if sym and sym != "?":
            return sym
    return "UNKNOWN"


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print("kullanim: make_readable_log.py <audit.jsonl> [<cikti.log>]")
        return 2
    src = sys.argv[1]
    explicit_dst = sys.argv[2] if len(sys.argv) == 3 else None

    records = []
    with open(src, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if explicit_dst is None:
        dst = os.path.join("logs", _derive_symbol(records), "live.log")
    else:
        dst = explicit_dst
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)

    out = []
    prev_locked = False
    prev_bias_locked = False
    prev_bias = None
    seen_fvg = set()
    seen_rollback = set()
    for r in records:
        et = r["event_type"]
        sym = r.get("symbol", "?")
        p = r.get("payload", {})
        if isinstance(p, dict) and isinstance(p.get("payload"), dict):
            p = p["payload"]
        if not isinstance(p, dict):
            continue

        if et == "STARTUP" and "verdict" in p:
            ts = _fmt_local(r["timestamp"])
            out.append(f"{ts} [BOOT] {sym}: verdict={p['verdict']} warmup={p.get('warmup_bars')}")
            continue

        if et == "STATE":
            bar_ts = p.get("bar_ts")
            ts = _fmt_bar_ts(bar_ts, r["timestamp"]) if bar_ts else _fmt_local(r["timestamp"])
            if p.get("locked") and not prev_locked:
                out.append(
                    f"{ts} [CBDR-KILIT] {sym}: "
                    f"range={p.get('body_low')}..{p.get('body_high')} "
                    f"session={p.get('session_key')}"
                )
            bl = p.get("bias_locked")
            b = p.get("bias")
            if bl and (not prev_bias_locked or b != prev_bias):
                kilid = "sweep" if p.get("sweep_yes") else "?"
                v6dur = p.get("htf_source") or (
                    "v6-lock-sifirlandi" if p.get("moment") == "v6_rollback" else "yok"
                )
                out.append(f"{ts} [BIAS] {sym}: {b} kilit={kilid} (V6-durumu={v6dur})")
            if p.get("moment") == "v6_rollback":
                key = (p.get("bar_index"), "rb")
                if key not in seen_rollback:
                    out.append(
                        f"{ts} [V6-ROLLBACK] {sym}: sayi="
                        f"{p.get('rollback_count')} sweep={p.get('sweep_direction')}"
                        f" htf={p.get('htf_dir')}"
                    )
                    seen_rollback.add(key)
            if p.get("moment") == "fvg_armed":
                key = p.get("bar_index")
                if key not in seen_fvg:
                    out.append(
                        f"{ts} [FVG] {sym}: {p.get('direction')} "
                        f"top={p.get('fvg_top')} bottom={p.get('fvg_bottom')} "
                        f"sl_pre={p.get('sl_pre')}"
                    )
                    seen_fvg.add(key)
            prev_locked = bool(p.get("locked"))
            prev_bias_locked = bool(bl)
            if bl:
                prev_bias = b
            continue

        if et in ENTRY_EVENTS:
            ts = _fmt_local(r["timestamp"])
            kv = " ".join(f"{k}={v}" for k, v in p.items())
            out.append(f"{ts} [{et}] {sym}: {kv}")

    with open(dst, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"OK {len(out)} ozet-satiri -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
