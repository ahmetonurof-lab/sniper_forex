#!/usr/bin/env python
"""D105-RATİFİYE-ARAÇ (özet-mod): audit.jsonl → 4-an-özet .log.

Reis-formatı — SADECE: CBDR-KILIT > BIAS > FVG > ENTRY (SIGNAL/RISK/ORDER/
FILL/POSITION). Diğer ayrıntı ham-jsonl'de kalır (aynı-dizinde).

Kullanım:
    python tools/make_readable_log.py <audit.jsonl> <çıktı.log>
"""

import datetime
import json
import sys

ENTRY_EVENTS = ("SIGNAL", "RISK", "ORDER", "FILL", "POSITION", "EXIT")


def main() -> int:
    if len(sys.argv) != 3:
        print("kullanim: make_readable_log.py <audit.jsonl> <cikti.log>")
        return 2
    src, dst = sys.argv[1], sys.argv[2]
    out = []
    prev_locked = False
    prev_bias_locked = False
    prev_bias = None
    prev_gate = None
    seen_fvg = set()
    seen_rollback = set()
    with open(src, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            et = r["event_type"]
            ts = datetime.datetime.fromtimestamp(
                r["timestamp"], tz=datetime.timezone.utc
            ).isoformat(timespec="seconds")
            sym = r.get("symbol", "?")
            p = r.get("payload", {})
            if isinstance(p, dict) and isinstance(p.get("payload"), dict):
                p = p["payload"]
            if not isinstance(p, dict):
                continue

            if et == "STARTUP" and "verdict" in p:
                out.append(
                    f"{ts} [BOOT] {sym}: verdict={p['verdict']} " f"warmup={p.get('warmup_bars')}"
                )
                continue

            if et == "STATE":
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
                    out.append(f"{ts} [BIAS] {sym}: {b} kilit={kilid} " f"(V6-durumu={v6dur})")
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
                kv = " ".join(f"{k}={v}" for k, v in p.items())
                out.append(f"{ts} [{et}] {sym}: {kv}")

    with open(dst, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"OK {len(out)} ozet-satiri -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
