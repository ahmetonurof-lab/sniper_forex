# D106 — V6-ANOMALİ-PAKETİ (N2#25 · CHECKPOINT-v3 İLK-İŞİ)

> **Statü:** ANALİZ/CENSUS-paketi · kod-DEĞİŞİKLİĞİ YOK (canlı-BTC-boot PID-1924 dokunulmadı, §17)
> **Kanıt-kaynağı:** `state_btc_d104/audit.jsonl` (1405 satır · 6-boot · STARTUP S9=6) + `state/D104_preserve/audit.jsonl` (forex-boot) + kod (`src/live/strategy_runtime.py`, `src/live/orchestrator.py`)
> **Kapsam:** Hakem-§5 bulguları A/B/C — kök-neden + karar-talebi

> ### ⚠️ PIN-BLOĞU (ADER-1/ADER-5 düzeltmesi — Hakem-D107-RED-sonrası; push-öncesi-şart)
>
> **Bu-raporun-kod-satır-ankorları WORKTREE-DEFERRED blob'una aittir — `origin/main` `51cee9b` DEĞİL.**
>
> ```text
> PIN: worktree-deferred (PID-1924'ün-koştuğu blob) — origin/main 51cee9b DEĞİL
> strategy_runtime.py  wc -l = 980
>   sha256sum        = f1b4c89fb3c12356d0340021987da815437cf94d86da07be066c15c1842b6b27   (yöntem: sha256sum)
>   git hash-object  = 5833c876c9d740b90cdd79059424d64b801032d7                            (yöntem: git hash-object, blob SHA-1)
> orchestrator.py    git hash-object = d9684d58636d7f85d6324473b2996e8f94cef1fa
> # origin/main 51cee9b KARŞITLIK (V6-hibrit YOK):
>   strategy_runtime.py  wc -l = 754 · sha256sum = 6dbfff207d2ff41db01c6b3a87a1c162a38866757e0ce53bfbe1df9a1e21ae7f · git blob = ffa129ceca82d305e69d2a73de649c424f2daaec
>   rollback_count / ignored_count / pathological_count = 0 isabet (sembol YOK)
>   _v6_rollback_count   = :235   (origin 51cee9b:754satır'da SEMBOL YOK)
>   _v6_rollback_count +=1 = :411
>   _v6_pathological_count = :454 · _v6_ignored_count = :470
>   _emit_state          = :246   (payload rollback_count = :292)
>   to_state             = :839   (persist rollback_count = :897)
>   from_state           = :903   (restore rollback_count = :971)
> # C-emit (append vs verdict AYRIMI — karıştırma):
>   origin 51cee9b: orchestrator.py:1444 = self.audit.append(   ·   :1450 = "verdict": "COLD_REBUILD_OK"
>   worktree:       orchestrator.py:1520 = self.audit.append(   ·   :1526 = "verdict": "COLD_REBUILD_OK"
>   (D106-v1 ":1526" = worktree-verdict; origin'da karşılığı append :1444 / verdict :1450)
> ```
>
> **Kök-neden (ader-hatası):** census, canlı-`audit.jsonl`'ı okudu → o-log **worktree-blob'unun** (V6-hibrit) çıktısı. Kod-ankorları da worktree'den-alındı ama **blob-bildirilmedi**. origin/main'de V6-hibrit-kodu **hiç yok** (754 satır, rollback/ignored/pathological = 0 isabet).
> **Etki:** A/B bulguları **çalışan-sistem-için GEÇERLİ**, fakat origin-mühürlü-koda BAĞLANAMAZ. A2/B-cerrahisi → **V6-hibrit origin'e commit'lenmeden hedef-yok** (Hakem-A-kararı: "cerrahi origin'de hedef yok").
> **C:** kapanış iddiası origin'de AYAKTA (yorum :338 + emit append :1444 / verdict :1450 + fix `6323e63`); D106-v1 ":1526" yalnız worktree-verdict-karışıklığıydı.


---

## BULGU-A — `rollback_count` kapsam-tanımı (GLOBAL lifetime vs GÜN/BOOT-reset)

**Gözlem (kanıt):**
- Zaman-serisi: `2026-07-23 rb=0 → 07-25 rb=1 → 07-27 rb=2 → 07-28 rb=3 → 07-30 rb=4 → 08-05 rb=5 → 08-13 rb=6 → 08-28 rb=7 → … rb=8`. **Gün-sınırında SIFIRLANMIYOR** — 6-haftalık monoton.
- Kod: `_v6_rollback_count` init `:235`, `+=1` `:411`, **persist** `to_state:897`, **restore** `from_state:971`. → lifetime-sayaç, restart-lar-arası-taşınır.

**Anomali (sayı-çelişkisi):**
| Ölçüm | Değer | Anlam |
|---|---|---|
| `rollback_count` (max) | **8** | persisted lifetime sayaç |
| `v6_rollback` moment-emit | **45** | audit'te basılan olay-satırı |
| tekil rollback `bar_ts` | **12** | tarihî-gerçek rollback sayısı |

→ **8 ≠ 45 ≠ 12.** Üç-sayı birbirini tutmuyor.

**Kök-neden (kanıtlı):** Her-boot replay aynı tarihî rollback'leri YENİDEN-emits eder. Boot-başına-trace: `8,8,7,7,7,8` (6-boot) ≈ 45. Sayaç persisted (tek-ilerler), olaylar boot-chopped (her-replay-tekrar). `_emit_state` anlık-sayaç-değerini taşır ama olay-başına-delta TAŞIMAZ → audit'ten tekil-rollback-üretimi yeniden-üretilemez.

**KARAR-TALEBİ (Reis/Hakem):** `rollback_count` semantiği RESMEN tanımlansın:
- **(A1)** lifetime-persisted provenance (mevcut) → o-zaman moment-emit'ler boot-chop NOTU taşısın (`boot_id`/`replay_seq`), yoksa 45/8 yanıltır.
- **(A2)** per-boot replay-derived → o-zaman PERSIST edilmesin (from_state:971 kaldırılsın), her-boot 0'dan-türetilsin (deterministik-rekonstrüksiyonla uyumlu).
- **Cline-önerisi:** A2 — tek-kaynak-doğruluğu (market-history'den deterministik yeniden-üretim), §6.2 "single source of truth" ile hizalı; persisted sayaç ikinci-çelişkili-kaynak üretiyor.

---

## BULGU-B — fallback-yol-teşhis-sayaçları audit'te YOK (observability-gap)

**Gözlem (kanıt):**
- Kodda-üç-V6-sayaç: `rollback_count` (`:411`), `ignored_count` (breakout≠HTF → `:470`), `pathological_count` (both-breakout → `:454`).
- `_emit_state` (`:246`) payload — `rollback_count` satırı (`:292`): **yalnız `rollback_count`** taşır — `ignored_count`/`pathological_count` **YOK**.
- Audit-grep: `ignored_count`=**0**, `pathological_count`=**0** (hiç-basılmamış); `rollback_count`=1283.
- `to_state` (`:897-899`) üçünü-de persist eder → **sadece-disk-state'te-görünür, canlı-log'da-GÖRÜNMEZ**.

**Anomali:** Fallback-kurulum-yolunun iki-red-dalı (ignored / pathological) canlı-izlemede kör. `v6_fallback_lock`=80-emit, `v6_rollback`=45-emit var; ama "kaç-breakout-HTF-yüzünden-işlenmedi" / "kaç-patolojik-both" audit'ten-okunamaz.

**Kök-neden:** `_emit_state` alan-listesi rollback-dışı-sayaçları içermiyor (N2#24 AM-N24-3'te yalnız rollback_count eklendi; ignored/pathological atlanmış).

**KARAR-TALEBİ:** `_emit_state`'e `ignored_count` + `pathological_count` alanları eklensin (payload-şeması genişler — SIGNAL 8→12 deseni gibi versiyon-notu gerekir). Bu bir KOD-CERRAHİSİ (N2#25-kapsamı), canlı-boot-dokunulmaz-kuralı nedeniyle **ayrı-izni-komitede** uygulanır.

---

## BULGU-C — çifte-COLD_REBUILD-tranche → ZATEN-KÖK-LEŞ + FIX'lenmiş

**Gözlem (kanıt):**
- Temiz-BTC-boot (`state_btc_d104/audit.jsonl`): `COLD_REBUILD_OK` = **0** ✓ (fresh-boot, stale-restore yok → rebuild-gerekmez; DOĞRU).
- Forex-preserved-boot (`state/D104_preserve/audit.jsonl`): `COLD_REBUILD_OK` = **4** → `replay_bars` = **4236×2 + 4237×2** (EURUSD). İki-değer × iki-kez = **duplike-tranche**.

**Kök-neden (ZATEN-ÇÖZÜLMÜŞ):** `orchestrator.py:338` yorumu + COLD_REBUILD_OK emit (worktree `:1526` / origin `51cee9b` `:1450`) → N2#21 exactly-once hatası: `audit_path` CWD-relative default, birden-fazla-runtime/startup-pass aynı-relative-yola yazdı → 4 satır. **FIX: commit `6323e63`** (`fix(n2_21): audit_path CWD-relative default -> state_dir-derived (exactly-once root cause)`).

**Sonuç:** Bulgu-C **RESOLVED** — kanıt: temiz-BTC-boot'ta 0 (beklenen), forex-boot 4× semptomu fix-öncesi-kalıntı (preserve-arşivi). Yeni-iş YOK; sadece deftere "kapandı" olarak işlenir.

---

## ÖZET-KARAR-TABLASI

| Bulgu | Durum | Aksiyon | Yetki |
|---|---|---|---|
| **A** rollback-scope | AÇIK-karar | A1 (boot-notu) veya A2 (persist-kaldır) seçimi | Reis/Hakem-kararı |
| **B** fallback-sayaç-gap | AÇIK-kod-cerrahisi | `_emit_state`'e ignored+pathological ekle | N2#25 commit (canlı-sonrası) |
| **C** COLD_REBUILD-tranche | **KAPALI** | `6323e63` fix-doğrulandı; defter-notu | — |

**Kanıt-hiyerleşimi-notu:** A/B statik-kod + audit-census kanıtıdır (seviye-6); üretim-branch'i canlı-boot'ta çalıştırıldı ama A-kararı/B-cerrahisi regression-ile-doğrulanmalı (seviye-3/4). C, executed-path + fix-commit ile seviye-2.
