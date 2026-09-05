#!/usr/bin/env python
"""SESSION_CHECKPOINT_v3_DRAFT üretici (FROZEN aday; Hakem checkpoint-v3)."""

import re
from pathlib import Path

PROG = Path("memory-bank/progress.md")
D99 = Path("memory-bank/archive_v2_20260906/D99_N2_24_DEVİR_İCRASI_TAM_S.md")
DRAFT = Path("memory-bank/SESSION_CHECKPOINT_v3_DRAFT.md")


def build_map() -> str:
    with open(PROG, encoding="utf-8", newline="") as f:
        lines = f.read().split("\n")
    out = []
    for i, l in enumerate(lines):
        if "ARŞİV" in l and l.startswith("## "):
            ref = ""
            for j in range(i + 1, min(i + 4, len(lines))):
                if "Ayrıntı" in lines[j]:
                    ref = (
                        lines[j]
                        .split("Ayrıntı:")[-1]
                        .strip()
                        .replace("memory-bank/archive_v2_20260906/", "")
                    )
                    break
            num = re.match(r"^##\s*D(\d+)", l)
            dnum = num.group(1) if num else "?"
            title = re.sub(r"^##\s*", "", l)
            title = re.sub(r"\s*\*\(ARŞİV[^)]*\)\*\s*$", "", title)[:45]
            out.append(f"- D{dnum.ljust(3)} | {title.ljust(46)} | {ref}")
    return "\n".join(out)


MAIN = """# SESSION_CHECKPOINT_v3_DRAFT (FROZEN aday)

**Durum:** DRAFT · 2026-09-06 · Checkpoint-v3 hazırlık-turu (Hakem-direktifi) · commit/push = Reis-hash-bound-onayı-bekliyor

## §0 CANLI-DURUM

- **BTC-FULL-canlı:** PID-1924 (boot-6), `SNIPER_SYMBOLS=BTCUSD`, `SNIPER_SIGNAL_ONLY=0`, spread-filtre-pratik-kapalı (backtest-birebir), `startup PROCEED`, gate-open, V6-hibrit-canlı (CBDR-kilit + bias + rollback kanıtlı)
- **Forex-10944:** `/F /T` killed + coruma `state/D104_preserve/` (18+ dosya + SHA) — D86-bloğu donuk
- **Remote:** origin/main = `6323e63` (pushed) · HEAD = `6323e63` · unpushed-commit = {} (0)
- **Worktree-deferred:** 281 durum (11-M / 269-?? / 1-R git-mv) — SET-2b-beyanı ayrı-dosyada
- **Tarih-basılı-log aracı:** `tools/make_readable_log.py` (CBDR/BIAS/FVG/ENTRY özet; Reis-"json-okuyamam" ratifiye)

## §1 D60–D102 KOMPAKT-MAP (tam-metin: memory-bank/archive_v2_20260906/)

__MAP__

## §2 AKTİF-İŞLER

- **N2#21-madde-2 (D72-v2):** Reis-yazımı bekliyor (madde-2 kilidi devam)
- **N2#24 icra-turu:** tam-süit 638P/1S/0F (yeni-ajan devir-notu; test-raporu §4.2/§8.1 dolu)
- **FULL-BTC-SIGNAL-watch:** canlı PID-1924 — ilk-canlı-order-zinciri (SIGNAL→RISK→ORDER→FILL→POSITION) beklemede; FVG-touch anı
- **V6-canlı-davranış-census:** bias-kaynağı/sweep/HTF-fallback/rollback kanıt-destesi (archive D99 + D104-105)

## §3 KUYRUK (öncelik sırası)

1. **V6-İZOLE-yasak** (D96) — korunur (tek-bias-kaynağı değil; V6-hibrit-içinde test)
2. **FAZ-C öncelik:** 4 → 2 → 5 → 6
3. **B1′ bültenler** (ADER-5 çapraz-teyit; üçlü-kanal)
4. **D82 izleme:** cumulative-process-lifetime / node-429-segmenti (pill-test; kod-RED-değil kaydı)
5. **N2#25-backlog:** insan-okunur-log ISO-alanı kod-ameliyatı (audit-yazıcı) — ayrı-N2
6. **V6-anomali-paketi (D106-5-bulgu A/B/C):** CHECKPOINT-SONRASI; öncelik-altı; canlı-boot-dokunulmaz şartıyla

## §4 ANAYASA-v2 (D99-tam-metni + öğeler)

**D99 tam-metni (arşiv-birebir):**
__D99__

**Anayasa-v2 öğeleri:**
- **Kanal-mimarisi:** Hakem (arbitraj/karar) ↔ Sentezleyici (entegrasyon) ↔ Owner/Reis (operasyon) — üçlü-kanal; tek-kanal-bildirim = eksik (§18)
- **Ajan-mülkiyeti:** Cline-performans-icrası; GLM/devir-notu; devir = `READ→CONTEXT→İZOLE→TEST→İMPLEMENT→REGRESSION→AUDIT` zinciri (deftere-birebir)
- **Üç-bölümlü-hüküm-formu:** (1) kanıt-durumu (2) karar (3) açık-kalem — her-hüküm bu-formda
- **ADER-23/24:** yeni-sayfada resmî-girişi; ADER-20-paralel-iş-tek-hat üzerine inşa (asama-5 kod-turunda)

## §5 ADER-1..22 KOMPAKT

- ADER-1 Satır-ankoru: satır-okunmadan ankor değildir (Hakem)
- ADER-2 Tarih-beyanı saat-ölçümüyle üretilir, hafızadan değil
- ADER-3 Boş-yeşil kanıt değildir (fikstür-dejenerasyonu)
- ADER-4 (etiket-archive-D9x; §6-map)
- ADER-5 Pin-iddiası = dosya-yolu+form+yöntem üçlüsü
- ADER-6 Kampanya-kayıt-volatilite-kuralı (T0#9-sonrası)
- ADER-7 (etiket-archive-D9x)
- ADER-8 (etiket-archive-D9x)
- ADER-9 Hash-doğrulama + dış-audit-arşivi
- ADER-10 (etiket-archive-D9x)
- ADER-11 §6 arşiv-ratifiye + ADER-9-v1.1 çapa-özgü
- ADER-12 Aday: kayıp/başarısızlık ilanı öncesi doğrulama
- ADER-13 Yeniden-boot-yok (N2#21'e dek); kayıt-discipline
- ADER-14 (etiket-archive-D9x)
- ADER-15 Kopya-ıraklaması iddiası AST-seviyesinde kurulur
- ADER-16/16b κ-kurumsallaşma + N2#21-pre-reg
- ADER-17 Aday: toplu-dosya-yazımında-tek-sorumlu
- ADER-18 (etiket-archive-D9x)
- ADER-19 taskkill /F /T κ-protokol (graceful-yoksa)
- ADER-20 Paralel-iş-tek-hat (kesişmeyen-yüzey)
- ADER-21 (etiket-archive-D9x)
- ADER-22 deselect-node-ID-collect-phase-doğrulaması

## §6 DOKUNULMAZLAR

- `state/` koruma-zinciri (10-nesil) — D104_preserve dahil
- Canlı-BTC-BOOT (PID-1924) — templat/güvenlik doku-NOKTA
- Frozen-üçlü N2#19 (V6/session.py/köprü mb) + session.py gövdesi
- D62/D93/D95 kanıt-setleri (mühürlü)
- V6-İZOLE-YASAK (D96)
- `archive_v2_20260906/` (MANIFEST-sha256 mühürlü)
- Kripto-botu-reposu (nexus-mcp) — kesin-dokunulmaz (kullanıcı-itirazı)


"""


def main() -> int:
    with open(D99, encoding="utf-8", newline="") as f:
        d99 = f.read()
    DRAFT.write_text(
        MAIN.replace("__MAP__", build_map()).replace("__D99__", d99.strip()),
        encoding="utf-8",
        newline="",
    )
    print("v3-DRAFT yazildi:", DRAFT)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
