# N2 #21 OWNER-BATCH — PRE-REG v2 (post-ruling + icra-suite-katmanı · 2026-09-04 0x:xx)

**Statü:** v2 — Hakem-dört-nokta-ruling (N1–N4) mühürlü · Reis-③-tetikli ("Göster bakalım") · **kanıt-planı-v1.1-suite-katmanı-İCRA-EDİLDİ** · 12/13-hâlâ-açık (owner-D72-embed; uydurulmadı). v1.1 (`a4f9b6ca`) bileşimi-değişmez; bu-dosya-v1.1-üstüne-ruling+icra-katmanıdır.

## 1. Ruling→icra-karşılık-tablosu (kanıt-planı-v1.1)

| Hakem-hüküm | İcra | Kanıt (suite-katmanı) |
|---|---|---|
| **N1-a** delta-append (`_flushed_count`-sonrası; load-sonrası-sayaç) | `audit.save()`→`append_line`-delta; watermark `save()`-sahipliğinde (mid-save-buffer-yutma-yasak); `Orchestrator.__init__` boot-load (try/except-boot-asla-blok-olmaz) | `test_cascade_crash_continuity_real_boot_shutdown_boot` · `test_boot_load_initializes_delta_counter` |
| **N1-b** torn-line (yeni-tasarım-değil; testle-mühürle) | `load()`-malformed-skip (mevcut) + `append_line`-newline-tamiri (torn-merge-sınıfı) | `test_torn_last_line_prior_lines_recovered_then_append_continues` · `test_append_line_repairs_missing_trailing_newline` |
| **N1-c** tek-writer-açık-yazar | Modül-docstring + load-docstring (O1; O3-interleave=ayrı-hüküm-notu) | pre-reg-sınır-notu (kod-yok) |
| **N1-d** fsync-şimdi-YOK | Katman-eklenmedi (LESS CODE) | — |
| **N1-e** `atomic_write.py` + audit-append=komşu-fonksiyon | `src/live/atomic_write.py`: `atomic_write_text` + `append_line`; 3-kopya-SİLİNDİ (audit/state/orchestrator) | `TestRetryBudget::test_all_three_helpers_share_budget` (identity>equality) |
| **N2** tek-dokunuş=8+1+9A-audit-bacağı; telemetri-AYRI-commit | RM-probe-telemetri-HİÇ-dokunulmadı (ayrı-commit-ayrı-fikstür-bekliyor) | scope-beyanı |
| **N3** koruma=KOD'A-GİRMEZ; D77-protokolü-aynen | boot-guard-kodu-YOK | — |
| **N4** üç-yol: lock-in-place (rename-YOK) / state+safe-mode tmp+rename-KALIR / audit=delta-append | Lock-dokunulmadı; state/safe-mode=paylaşımlı-rename; audit=append | `test_floor_fires_*` (audit-open/state-rename/safe-mode-rename) + n2_17-lock-pinleri-yeşil |
| **Kanıt-1** cascade-crash (monkeypatch-fault-injection, gerçek-branch) | gerçek-`Orchestrator`+gerçek-`shutdown` | yukarıda |
| **Kanıt-3** floor-üç-yolda-DA-YAZAR | `atomic_write_exhausted` üç-yolda-pinlendi | BULGU-14-tersten-kriteri ✓ |

## 2. Sıra-sapması-beyanı (dürüstlük)

SIRA'da pre-reg-v2 → icra sırası vardı; icra-önce-yapıldı. Gerekçe: kanıt-planı-v1.1-ruling'de-zaten-pre-registered idi ve test-dosyası-o-planı-birebir-icra-ediyor. Sapma-bilinçli; mühür-bu-dosya-ile-tamamlanır — commit-sinyali-Reis'in.

## 3. Commit-scope-teklifi (12-dosya; push-AYRI-yazılı-yetki §9.2)

NEW `src/live/atomic_write.py`, `tests/test_n2_21_atomic_write.py` (8-test) · MOD `src/live/{audit,state,orchestrator}.py`, `index.json` (§10.2-yeniden-üretim-1732-fn), `tests/{conftest,test_orchestrator_n2_15b,test_orchestrator_n2_17,test_orchestrator_n2_17_lock_fixspec,test_orchestrator_d49}.py` · (defter-girdisi-ayrı-veya-aynı-commit-Reis-takdiri). AGENTS.md/progress.md-'M'-leri-önceden-vardi-scope-DIŞI-değerlendirilir.

## 4. Açık-kalem

Canlı-katman (iki-boot-continuity, T0#10, Reis-bildirimli) → madde-1-acceptance-gerçek-T0#10'da-mühürlenir · RM-probe-telemetri-ayrı-commit · 12/13-owner-D72-embed · tas3-flaky-native-crash-izleme-borcu.
