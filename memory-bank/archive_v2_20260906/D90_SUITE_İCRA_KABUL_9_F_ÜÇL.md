## D90 — SUITE-İCRA-KABUL + 9-F-ÜÇLÜ-SINIFLANDIRMA + SUIT-OKUMA-KURALI (Hakem-hükmü; 2026-09-04 20:1x +03)

- **SUITE-İCRA-KABUL:** ilk-tam-koşum 594P/1S/9F/0-crash; born-red-e2e-fixi-tam-süitte-doğrulandı (run7/8/9-%11-sıfır-F). RED-YOK. **Waiver-listesi-güncellemesi: e2e-2-üye-KAPANIR** (D57-üçlüsünden-çıkış); kalan-9-F-pre-existing-olarak-ayrıştırıldı.
- **9-F-üçlü-sınıflandırma (her-biri-ayrı-rotada):**
  1. **tas4×8 = ÇEVRE-İHTİLAFI** — canlı-Boot-C-lock (`Already running (PID 18460)`-kanıtı). **Kod-debt-değil, test-env-telemetrisi.** Çözüm: süit-öncesi-canlı-stop (Reis-runbook) VEYA izole-SNIPER_STATE_DIR. **tas4-lock-path-hardening → N2#21-kuyruğu.** Runbook-satırı: test-süit-uyumlu-saat-penceresi (D70-launch-dersi-karşılığı).
  2. **d49-C3×1 = EXACTLY-ONCE-FLAKE** — 4×COLD_REBUILD_OK/beklenen-1; run2-PASS/run9-FAIL (flaky); stash-diferansiyeli-FAILED → pre-existing. **N2#21-kuyruğuna: emit-exactly-once-auditi.** Şimdilik: waiver-dışı-izleme-borcu — üreten-koşum-aralığı-notlanır, kalıcı-izleme.
  3. **native 0xc0000374 = non-det** — 2→4-görünüm (run1,6,7,8); run9-crashsiz; salt-import-5/5-temiz. Şüphe: canlı-MT5+full-suite-eşzamanlılığı. **D82-dosyası-güncellenir: izleme-sürer, pin-açma-yok, iki-bağımsız-oturum-izinde-değil.**
- **YENİ-SÜİT-OKUMA-KURALI (deftere):** *"Süit-çıkışı üç-katmanlı-okunur: (i) kod-hataları (fix), (ii) çevre-ihtilafı (runbook/izole-state), (iii) native-dış-çevre (D82) — hepsi-ayrı-rotada; tek-sayıda-birleştirme-yasak."*
- **N2#21-kuyruğuna-eklenen-borçlar:** tas4-lock-path-hardening · emit-exactly-once-audit · **LiveRunner-falsy-guard** (`audit or AuditChain()`) · D82-izleme-(kuyruk-dışı, gözlem).
- **T0#10-RESTART-GATE = REİS-KARARI:** iki-canlı-süreci (PID 5580-venv + 18460-base, ~11:12-boot, **eski-kod**) → R-3+R-1-canlı-emissyonlar-restart-olmadan-görünemez. Hakem-önerisi **(A) restart-şimdi** (D86-protokolü; (A)-alınırsa-yeni-boot-log-alanı-örn. t10d- + safe-reason-kayıtları-BULGU-13-devamı) / (B) ertele. Çift-süreç-ihtilafı-taarrüz-riski-notlu.
- **LOCAL:** bu-defter-commiti-unpushed — sonraki-hash-bound-sete-biner.
