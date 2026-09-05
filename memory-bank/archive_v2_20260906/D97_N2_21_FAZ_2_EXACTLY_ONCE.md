## D97 — N2#21-FAZ-2: EXACTLY-ONCE-FIX-COMMIT + SÜİT-PENCERE-VERDİKTİ (2026-09-05 08:3x +03; Cline)

**Commit:** `6323e63` `fix(n2_21): audit_path CWD-relative default -> state_dir-derived (exactly-once root cause)` — 3-dosya (+100/−11): orchestrator.py (config-default `None`→state_dir-türevi-boot'ta, load-dahil; run_production-ABS-dokunulmaz; emit/AuditChain-semantiği-dokunulmaz) + n2_13-pin-yeniden-yazımı (`test_orchestrator_no_audit_path_uses_state_dir`) + prereg `results/N2_21_phase2_prereg_exactly_once_and_4_2_5_6.md`. **PUSH: Reis-hash-bound-onayı-bekliyor (§9.2) — tek-commit-set.**

**Kök-neden (aritmetik-kanıt):** CWD-relative-audit_path-default'u-test-orchestrator'ların-boot-load'unu-repo-kök-canlı-journal'e-bağlıyordu; 4-canlı-COLD_REBUILD_OK + testin-kendisi = "got 5". Prod-emisyon-her-zaman-exactly-once'ydu (D91-uyumlu); asıl-bug=§19-CWD-persistence + test-yalıtım-deliiği.

**Süit-pencere-verdikti (4-koşum + 2-izole; 608-node-segment-birliği):** 0-360-yeşil (run2) ∪ 360-576 (run1; tas4-8F-env-hariç) ∪ 577-608-tail-32P → **yeni-gerçek-F=0**. tas4×8-izole-teyit: tamamı `test_run_production_*`, hata=`Already running (lock owner PID 10944)` → çevre-ihtilafı-sınıfı (canlı-lock-sahibi-bu-pencerede-PID-10944-gözlemdi; N2#24-prereg'deki-Boot-C-PID-18460-referansı-o-kaydın-metnidir-bu-pencere-gözlemi-değil). Native-crash (0xc0000374, D82-sınıfı): belirti-noktası-kayar (run1-parité `main_research_c_v1_0.py:339`; run3-`test_proceed_holds_lock`-içi) — F-değil-kesinti-olarak-kayıtlı. **Operasyonel-ders (§19-sessiz-fallback-telemetrisi):** yanlış-deselect-node-ID-SESSİZCE-0-eşleşir; doğrusu `TestStartupProceed::test_proceed_holds_lock`.

**Madde-4-census (icra=gözlem; kod-donuk):** I2-dogrulandi — 3-koşum-boyunca-canlı-`state/audit.jsonl`-e-WRITE_BLOCK-sızması-0 (fix-izolasyon-deliiğini-kapattı); I1-beklenen-semantik: canlı-süreç-lock-sahibi-olduğundan-kendisi-WRITE_BLOCK-üretmez. Kapanış-raporu-icra-öncesi-değil; D86-penceresi-telemetri-eklenecek.

**Madde-5-ön-çalışma (kod-donuk; prereg-§3-e-işlendi):** `LockData.phase`-alanı-zaten-mevcut + geri-uyumlu-`from_dict`; asıl-iş-`_write()`-L838-hard-coded-`phase="startup"` → Lock'a-`set_phase()`-API + Orchestrator-faz-geçişleri + RUNTIME + heartbeat-mevcut-fazı-korur (BULGU-3-stickiness-canlı-teyit: 3-saatlik-lock-hâlâ-phase:startup).

**Engeller/açık:** madde-2 (Reis-in-D72-tam-metni-bekliyor; veya-4→5→6-yeniden-sıralama-tek-kelime-onayı) · D86-restart (N2#24-pre-reg-onay-akışı-ile-hizalanacak; ✓③-bekletmede) · index.json-regen-worktree-de-hazır-AMA-commit-i-N2#24-strategy_runtime-işiyle-tutarlı-sette (prereg-§6) · progress/defter-bu-sete-binmez (Luna-arbitraj; bu-giriş-dahil-commit-deferred).

**Kanıt-bütünlüğü-notu:** süit-penceresi-çalışma-ağacı-haliyle-koştu (fix + N2#24-V6-yarısı +192L-birlikte); fix-in-izole-davranışı-C3-izole-1P + n2_13-10/10 + d49+n2_21+tas3-33/33-pinli. strategy_runtime-yabancı-işine-dokunulmadı.
