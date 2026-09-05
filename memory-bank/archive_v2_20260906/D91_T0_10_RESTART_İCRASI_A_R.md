## D91 — T0#10-RESTART-İCRASI (A) + R-1-STATE-EMİTİ-CANLIDA-İLK-KEZ (2026-09-04 20:57-21:00 +03)

- **REİS-ONAYI:** "A" (T0#10-RESTART ONAY; D86-protokolü; Cline-icra).
- **(1) Coruma-N+1:** `state/t10d_preserve/` — orchestrator.lock.pre (`{pid:18460, phase:startup}` — kilit-sahibi-kanıtı) · audit_tail_pre.jsonl (13-satır) · ps_pre.txt.
- **(2) κ-STOP** (`stop_kappa.json`, 20:57:29): taskkill /F 5580 → SUCCESS · taskkill 18460 → **"not found"** — **parent-kill→child-gitmesi = "İKİ-SÜREÇ-BİR-BOOT"-TEYİDİ: çift-boot-şüphesi-ÇÖZÜLDÜ** (tek-boot; venv-launcher→base-child ağacı; 1392-satır-bulgusunun-canlı-dogrulaması). Post-stop: run_production-sayısı-**0** ✓. Kilit-dosyası-kalıntı (dead-PID → stale-takeover-beklenen-patika; elle-unlink-YAPILMADI — dead-owner-stale-path-normal-işleyişi).
- **(3) TEK-BOOT base-python** (D79-deseni, launcher-confound-yok): `C:\...\Python312\python.exe -u -m src.live.run_production`, CWD=repo-root, **tek-süreç PID-10944** (ne-parent-ne-child; ps-teyitli). stdout/stderr → `state/t10d_boot_stdout.log` / `t10d_boot_stderr.log`.
- **Boot-sonuçları:** MT5-Bağlı (ICMarketsSC-Demo, 53012914, 9990.68) · kilit-devralma ✓ (`{pid:10944}` — dead-18460-stale-takeover-canlıda-doğrulandı) · `cold rebuild OK (replay_bars=4236)` — S9-TEK-emisyon-bu-bootta · S11 restored=True · **`entry gate CLOSED: startup_SAFE_START`** — SAFE-START-persisted (§7.2: persisted-safe-mode-degraded-boot, asla-sessiz-resume).
- **safe-reasons-n (BULGU-13-devam):** `safe_mode_persisted`×8 + `expected_login_unset`×9 (yeni-kayıt-formu: iki-reason-tekrarlı; madde-7-girdisi).
- **(4) Audit-devralma ✓ + R-1-STATE-EMİTİ-CANLIDA-İLK-KEZ:** audit.jsonl'de-`STATE {bar_index:4299, bar_ts:2026-09-04T08:15:00, bias:bullish, bias_lock_ts:2026-09-04T08:15:00, ...}` — **d4-alanları-canlıda-üretildi** (AM-N23-1-şeması-görünür). R-3-SIGNAL-emiti: bekliyor (sinyal-fires-anı; watch-devam).
- **(5/6) SHUTDOWN-hedefi:** foreground-olmayan-boot (nohup) → sonraki-graceful-stop-döngüsünde-SHUTDOWN-audit-satırı-hedefi-duruyor; κ-kayıt-şartı-önceden-ödendi (stop_kappa.json).
- **Watch-gündemi (Reis-ile-aynı-zaman):** (i) ilk-canlı-R-3-SIGNAL-satırı (payload+AM-N23-1) (ii) R-1-STATE-d4-alan-devamlılığı (iii) WB=0-append-devamı (iv) D82-native-izleme-yeni-boot-penceresi (v) safe-reasons-n-büyümesi.
- **LOCAL:** bu-defter-commiti-unpushed — SET-2-hash-bound-sete-biner.
