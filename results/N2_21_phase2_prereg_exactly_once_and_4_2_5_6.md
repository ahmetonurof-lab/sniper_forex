# N2 #21 FAZ-2 — PRE-REG (exactly-once ↑↑ + madde-4→2→5→6 · Reis-in-ratifiye-sırası · 2026-09-05)

**Statü:** Reis-hash-bound-onay-öncesi-pre-reg. Kaynak-defterler: D87 (N2#21-ertelenen-dört-kalem) · D90 (dört-borç) · N2_21_owner_batch_prereg.md (v1.1-ratifiye-madde-tanımları). Hiçbir-madde-içeriği-icat-edilmedi; bende-olmayan-içerik-açık-işaretli.

---

## 0. ✓ EXECUTED — EXACTLY-ONCE AUDIT (öncelik-↑↑; bugün-icra-edildi)

### 0.1 Kök-neden (ARİTMETİK-KANITLI; "flake"-yanlış-sınıflandırma-çözüldü)
`OrchestratorConfig.audit_path` dataclass-default'u **CWD-relative** idi (`"state/audit.jsonl"`). N2#21-madde-1-boot-load'u (d36856f) bu-CWD-relative-yolu-load-edince:

| Kanum-anı | Değer | Anlamı |
|---|---|---|
| `state/audit.jsonl` COLD_REBUILD_OK-sayısı (test-ÖNCESİ) | **4** | canlı-bootların-GERÇEK-emisyonları (replay_bars=4236/4237/4236 + t10d-boot-20:57) |
| test-SONRASI-sayı | **4** | test-canlı-dosyaya-**LEKE-YAZMADI** (tmp-flush) — sadece-load-etti |
| C3-assertion "got 5" | 4-canlı + 1-testin-kendi = **5** ✓ | birebir-aritmetik-uyum |
| D90-okuması "got 4" (23:00-dönemi) | o-gün-dosyada-3-canlı + 1 = 4 ✓ | birebir-aritmetik-uyum |
| Bugün-izole-yeniden-koşum (fix-öncesi-davranış) | FAIL "got 5" | reproduce ✓ |

**Sonuç:** D90-daki "exactly-once-flake 4/5" → **prod-emisyon-her-zaman-exactly-once'ydu** (D91-canlı-kanıtıyla-uyumlu: "S9-TEK-emisyon"). Asıl-bug: (a) test-yalıtım-deliiği (boot-load-canlı-journal'i-test-chain'ine-çekiyor), (b) CWD-bağımlı-persistence-default'u (**§19-yasağına-aykırı**). C2-testinin-d49:599-605-notu-bu-deliiği-zaten-bilip-kendini-korumuştu; C3-bağlanmamıştı.

### 0.2 Fix (3-dosya; prod-wiring-davranışı-değişmez)
1. `src/live/orchestrator.py` (config): `audit_path: str = "state/audit.jsonl"` → `audit_path: Optional[str] = None` (state_dir-türevi-boot'ta).
2. `src/live/orchestrator.py` (__init__): journal-yolu-türevi `state_dir/audit.jsonl`; load-türevi-yolu-kullanır; `run_production.py`-explicit-ABS-yolu-**değişmez**.
3. `tests/test_orchestrator_n2_13_audit.py`: pin-testi-güncellendi (state_dir-türevi-pin; disk-persistence-sessizce-kapatılamaz-pin'i-korunuyor).

### 0.3 Doğrulama (yürütüldü)
- ruff check+format: clean · C3-izole: **1-PASS (2.38s)** · n2_13-dosyası: **10/10** · d49+n2_21+tas3: **33/33**.
- Canlı-journal-lekesizlik: 4→4 ✓ · PID-10944-canlı-boot-dokunulmadı (eski-kod; fix-sonraki-restart'ta-alınır).
- Tam-süit: **BKZ-§5 (run penceresi).**

### 0.4 Bu-fix'in-dokunuş-alanı-sınırı
Sadece-journal-YOLU-türetimi. Emit-sitesi (S9/COLD_REBUILD_OK bloğu), emit-koşulu, AuditChain-append/load semantiği, verdict-akışı **dokunulmadı**. N2#23-b-emisyon-yüzeyi-etkilenmez.

---

## 1. SIRA-2 · madde-4 — RM-probe TELEMETRİSİ "kim-tutuyor" (kod-donuk; icra=GÖZLEM-PROTOKOLÜ)
- **Kod-durumu (canlı, d36856f):** probe→WRITE_BLOCK-payload'a-gömülü: `holder_pids`/`holder_names`/`probe_errors` (orchestrator.py-lock-write-failure-anı) — probe-sadece-write-failure-anında (heartbeat-tick'te-değil; maliyet-nötr).
- **İcra-beyanı:** kod-değişikliği-YOK. FAZ-A3-döneminde-istenen-telemetri-artık-erişilebilir; icra = canlı-audit'ten-WRITE_BLOCK+probe-alan-ölçümü (audit_read-bazlı-census) + D86-restart-penceresinde-yeni-boot-telemetrisi. **Bant-ilanı-YASAK (ADER-16); O1-O4-gözlemci-disiplini; ADER-13: probe-"kim-tutuyor"un-tam-cevabını-taşımaz — kayıt-kanıt-olarak-dursun.**
- **Kapanış-şekli:** results-census-raporu (değil-kod-commit'i).

## 2. SIRA-3 · madde-2 — TAM-METİN-DEFTER-DIŞI (BEKLEMEDE: Reis'ten-D72-derlem-metni)
- owner-batch-v1.1-in-açık-beyanı: *"tam-metin-D72-arb-derleminden-owner-onayında-birleştirilir (İçerik-bende-tam-yok — uydurulmadı)"* — §1191-risk-derlemi 2×YÜKSEK(2).
- **İsteğim:** Reis-in-D72-arb-derleminden-madde-2-tam-metni (yalnız-bu-madde). Metin-gelmeden-içerik-uydurma-YOK.
- Metin-icra-öncelikli-ise: sıra 4→[2-metin-gelince]→5→6 şeklinde-2-ile-5-yer-değiştirebilir — Reis-in-tek-kelime-onayı-yeterli.

## 3. SIRA-4 · madde-5 — StartupPhase→LockData YENİDEN-KAPSAM (kod-iş)
- §1345: kimlik-ZATEN-VAR (StartupPhase); doğru-kapsam = LockData'ya-taşıma (`_write()`'a-gerçek-faz-parametresi) — yeni-soyutlama-DEĞİL. §1267 created_at-AD-tuzağı-bu-maddeden-geçer.
- **Plan-iskeleti:** (a) `LockData`-şemasına-faz-alanı (+ geri-uyumlu-load: eski-lock-dosyası-default-faz), (b) `_write()`-çağrı-yerlerinde-faz-geçişi (startup-fazları-S1..S11; runtime-loop→"RUNTIME"), (c) stale-heuristiği-faz-bilinci-incelemesi (LOCK_STALE_SEC-aritmetiği-dokunulmaz), (d) testler: faz-sıçraması-pin'i + eski-schema-load + heartbeat-faz-akışı. **Tamamlandığında-tam-süit-penceresi-şart.**
- **Ön-kod-çalışması (2026-09-05; icra-değil):** `LockData.phase`-alanı-ZATEN-mevcut + `from_dict`-geri-uyumlu (`d.get("phase","")`) → (a)-yapısal-olarak-hazır. Asıl-dokunuş: `_write()`-L838-deki-hard-coded `phase="startup"` (Lock-sınıfı-fazı-bilmez; acquire'da-bir-kez-yazılır, heartbeat-L758-aynı-donuk-değeri-tekrar-yazar → canlı-lock-3-saat-sonra-hâlâ-phase:startup = BULGU-3-stickiness-canlı-teyidi). İcra-tasarımı: Lock'a-`set_phase()`-publik-API (yeni-soyutlama-değil; StartupPhase-kimliği-yeniden-kapsamlanıyor) + Orchestrator-faz-geçişlerinde-çağırır + RUNTIME'e-oturtur + heartbeat-mevcut-fazı-korur.

## 4. SIRA-5 · madde-6-ailesi (4-alt-madde; sıra-içinde-a→d)
- **6a** machine-timed-dokunma-satırı (audit_read.py-kendisi-yazsın; O3-kendiliğinden-doğrulanır) · **6b** manual-timestamps-YASAK · **6c** teardown-TAMAM+audit-flush-FAIL→doğru-exit-kodu (D78-n=3; κ-örneği-EKLENEMEZ) · **6d** ölü-analiz-modülleri-relocation (liquidity_forensics/phase4_lifecycle — **karar=owner; src/-dokunuşu** → 6d-owner-kararı-özel-onay-ister).
- Not: 6a/6b aynı-dokunuş-alanı (audit_read.py); 6c exit-kod-yüzeyi; 6d-owner-bekleyen.

---

## 5. TAM-SÜİT-PENCERESİ (2026-09-05 İCRA-SONUCU; 4-koşum; kanıt-segment-birliği)
- **Koşumlar:** run1 (D90-deselect) → çökme ~%94 `test_parity_6majors` içi (`experiment/main_research_c_v1_0.py:339 run_test_a`, 0xc0000374); run2 (aynı-deselect) → 0-360-tamamen-yeşil (0F/0E/1S), çökme-%59-pandas-içi (repo-frame-yok); run3 (+`--ignore=parity`) → çökme-%59 **`test_proceed_holds_lock` İÇİNDE — deselect-node-ID-uyuşmazlığı bulundu: gerçek-ID `TestStartupProceed::test_proceed_holds_lock` (yazılan `TestOrchestratorStartup::` sessizce-0-eşleşme = §19-sessiz-fallback-telemetrisi)**; tail-run (#577-608: parity+persistent_logging+startup_snapshot+tools_d54) → **32 passed (330.77s)**; tas4-izole → **12P+8F**.
- **8F-kimliği-kesin:** tamamı `test_run_production_*` (tas4-#499-506), hata= `Already running (lock owner PID 10944) - EXIT` → **çevre-ihtilafı-sınıfı** (canlı-lock; §5-öngörüsü-birebir-teyit).
- **Segment-birliği (608-node):** 0-360 (run2-yeşil) ∪ 360-576 (run1: tas4-8F-env-hariç-yeşil) ∪ 577-608 (tail-32P) → **yeni-gerçek-F = 0** (hedef-tuttu; d49-C3-F'liği-ortadan-kalktı).
- **Native-crash-durumu:** 3-pencere-4-çökme — repo-frame'li-belirti-noktaları-iki: `test_proceed_holds_lock` (startup→warmup→fetch) ve `main_research_c_v1_0.py:339 run_test_a`; ortak-zemin = MT5-komşusu-ağır-pandas/C-ext-yolları; belirti-noktası-koşumlar-arası-kayar (D82-sınıfı-telemetri: crash-yüzeyi-değişken, deselect-çözümü-geçici). Bu-testler-F-değil-kesintiolarak-kayda-geçti.

## 6. COMMIT/PUSH
- **Bu-set (hash-bound):** `src/live/orchestrator.py` (fix) + `tests/test_orchestrator_n2_13_audit.py` (pin) + `results/N2_21_phase2_prereg_exactly_once_and_4_2_5_6.md` (pre-reg). **push-yalnız-Reis-in-yazılı-hash-bound-onayıyla (§9.2).** progress.md-commit-deferred durumunu-korur (Luna-arbitraj-bekliyor) — defter-girişi-bu-sete-BİNMEZ, sonraki-sete.
- **index.json-KASITLI-ERTeleme (§10.1/10.2):** `index_builder --full` koşuldu (2026-09-05T08:32Z; artifact-worktree-de) AMA-worktree-de-commitlenmemiş-N2#24-strategy_runtime-işi-var (bkz-§7) — index-onları-bu-sete-sessizce-atfetmez; index-commit-i-N2#24-setiyle-tutarlı-ağaçta-yapılır. HEAD-index-bilinçli-stale-kalıyor (not-düşüldü).

## 7. RİSKLER / İZNİKLER
- Canlı-PID-10944 eski-kodda-donuk-izlemede (watch-untouchables) — fix-canlıda-yalnız-D86-restart-penceresinde-aktive-olur (✓③-bekletmede; N2#24-pre-reg-gelişine-kadar).
- Pin-testi-değişikliği "pin-görünürlüğünü-kaybettirmez" — pin-state_dir-ancak-yön-değişirse-yine-kırılır (persistence-silence-pin'i-korunuyor).
- Madde-5-kod-işi-D80-dışı-dokunuş (lock-katı) — icra-öncesi-tam-süit-penceresi-şartı-prereg'de-beyanlı.
- **Worktree-içi-yabancı-iş:** `src/live/strategy_runtime.py` +192-satır "N2#24-V6-hibrit" (mtime-bugün-08:30; benim-setim-dışı; D86-bekeleminin-karşı-tarafı-ile-uyumlu) — sete-SOKULMADI/dokunulmadı. **Kanıt-bütünlüğü-notu:** §5-süit-kanıtı bu-worktree-haliyle (fix + N2#24-yarısı-birlikte) koştu; fix'in-izole-davranışı-ayrıca-C3-izole-1P + n2_13-10/10 + d49/n2_21/tas3-33/33 ile-pinli.
- **Sessiz-deselect-telemetrisi (§19-sınıf):** yanlış-node-ID (`TestOrchestratorStartup::`) pytest'te-0-eşleşmeyle-SESSİZCE-geçer — düzeltilmiş-ID `TestStartupProceed::test_proceed_holds_lock` sonraki-pencere-deselect'lerinde-kullanılmalı (run3-çökmesi-bu-uyuşmazlığı-ortaya-çıkardı).
