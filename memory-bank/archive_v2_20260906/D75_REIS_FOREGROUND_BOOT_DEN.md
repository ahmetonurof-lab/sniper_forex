## D75 · REIS-FOREGROUND-BOOT DENETİMİ + KÖK-NEDENİN YENİDEN-KEŞFİ (öz-eleştiri)

**Reis'in eylemi:** `$env:SNIPER_STATE_DIR=<mutlak>` + `$env:SNIPER_SYMBOLS=EURUSD` + `python -u -m src.live.run_production 2>&1 | Tee-Object state\k3_boot_stdout.log` (foreground PowerShell). **= `19:17:10` bootu, PID 11476.**

**HÜKÜM: çekirdek-DOĞRU.** Foreground-boot K3'ün-ta-kendisi; **§C/graceful-stop/close-save ilk-kez üretilebilir** (nohup zinciri kırıldı). `SNIPER_STATE_DIR` mutlak-set edildi ⇒ CWD-bağımlılığı bu-alan-için kapandı. `-u` doğru. **Fail-safe ÇALIŞTI:** `safe_mode_persisted` → `S11 SAFE_START` → `entry gate CLOSED` — **sessiz-resume YOK, bu BAŞARI.**

**ATLANAN TEK ZORUNLU ADIM: AM-T7-8 (adım-0.5, `checklist:115`/`:135`).** Boot-öncesi `cp state/audit.jsonl state/audit_prev_<date>.jsonl` yapılmadı ⇒ **3416-devri 10 satır gitti; 3416'nın nasıl-öldüğü artık kanıtlanamaz.**

**ÖZ-ELEŞTİRİ (§12.1 + §1 ihlali, bana-yazık):** D74'te *"yeni kök-bulgu"* diye sunduğum truncation-mekanizmasını **D68'de KENDİM bulmuş ve checklist'e AM-T7-8 satırına harfiyen YAZMIŞTIM** (*"orchestrator.py:1040 AuditChain'i load etmeden kurar → her boot önceki zinciri yok eder"*). Aynı-şeyi yeniden-keşfettim, **kendi-kontrol-listeme-bakmadan**, ve **boot-öncesi-kopya-komutunu Reis'e-vermedim.** Kayıp-bedeni **benim süreç-ihmalimin-bedelidir, Reis'in-değil.**

**YAPISAL-DURUM (statik-kanıtla teyit, "olay" değil "davranış"):** `audit.py:241-255` `save()` = `"".join(... for evt in self._events)` → `_atomic_write_text` → **tmp.replace TAM-OVERWRITE**; `orchestrator.py:1040` **boş `_events`** ile kurar; `AuditChain.load()` `audit.py:259` **MEVCUT** ama `grep 'audit[.]load' src/` → **0 çağrı**. ⇒ **Her boot önceki zinciri SIFIRLAR** (Sep-2'nin 7 satırı da böyle-gitti). **Çözüm yeni-tasarım-değil:** ya `:1040` sonrası `prod_audit.load(...)` (**tek-satır, mevcut-metot**) ya audit'i crash_log-desenine-çevirme. **§2.2 altın-uygulaması.**

**crash_log NEDEN SAĞ-ÇIKTI — kodun-kendi-itirafı:** `orchestrator.py:239-256` docstring: *"os.open(O_APPEND|O_CREAT) + single os.write: **append-mode needs no tmp/rename (the mechanism under suspicion)**"*. ⇒ **tmp+rename "şüpheli-mekanizma" olarak ADLANDIRILMIŞ.** crash_log üç-bootu-taşıyor (3944←`bash.exe`, 3416←`nohup.exe`, 11476←`.venv`), audit sıfırlandı.

**YENİ-BULGU · İKİ-SÜREÇ-BİR-BOOT (Ctrl-C güvenliğini-etkiler):** `16660` = `.venv\Scripts\python.exe -u -m src.live.run_production` (**terminaline bağlı**) → child `11476` = `AppData\...\Python312\python.exe` aynı-argv, **KİLİT-SAHİBİ 11476**. `src/live/`'de `Popen|subprocess|multiprocessing|execv` → **0** ⇒ **spawner proje-kodu-değil; mekanizma ÇÖZÜLMEDİ (açık-kalem).** `.venv`=pandas **3.0.5**/numpy **2.5.2**, base=pandas **2.3.3**/numpy **2.2.6**; crash_log `self` 11476'yı **venv** gösterir, WMI image-path **base** ⇒ **ÇELİŞKİ, hangi-interpreter'ın-gerçekte-import-edildiği DOĞRULANMADI** ⇒ **§8.1 provenance kırığı** (3416 sistem-pythonu idi). **RİSK:** parent önce-ölürse child **yetim-kalır-kilidi-tutar** ⇒ **"durdurduk" sanırız.** **Ctrl-C SONRASI ZORUNLU:** `Get-Process -Id 16660,11476` **ikisi-de-gitti-mi** + lock unlink mi.

**WRITE_BLOCK GERİ-GELDİ ⇒ nohup-hipotezisi ÖLDÜ:** `19:28:27 retries=8` — **venv-bootunda, nohup OLMADAN.** Kalan-aday **kodun-kendi-etiketi** `audit.py:106` → *"AV/sync handle"* (Defender/OneDrive hedefi rename-anında-açık-tutuyor); yetim `.tmp`'ler bunun kalıntısı. Yeni-boot **ERROR=0** (eski ERROR 3416-devrine-ait, artık artifact-değil).

**ARAÇ-MASRAFI (Tee):** `2>&1 | Tee-Object` stderr'i **error-record**'a çevirdi → log'a `NativeCommandError` girdi (programa-zarar-yok, **artefakt-temizliği-bozuldu**). `state/k3_boot_stdout.log` **19:17:25'te donmuş (1944 B / 26+ dk)** — sessizlik-mi-tampon-mu **ayrıştırılamadı**; tamponsa **Ctrl-C anında çıkış-kuyruğu kaybolur = K3'ün-istediği-kanıt.** `state/` git-takipli-değil (`git ls-files state/`=0) ⇒ **repo kirlenmedi** ve `crash_log.txt` zaten-orada ⇒ **mevcut-konvansiyona-uygun.** **AMA `.gitignore`'da `state` YOK** ⇒ **`git add -A` tüm state/'i yutar — commit'te KULLANILMAZ.**

**YENİ-MADDE-ADAYI (§19 CWD-dependent persistence):** `_CRASH_LOG = Path("state")/"crash_log.txt"` `orchestrator.py:236` — **sabit-göreceli-yol, `SNIPER_STATE_DIR`'i HİÇ okumuyor.** CWD repo-kökü olduğu-için-çalıştı. **crash_log, state-dir-soyutlamasının-dışında-tek-kaçak-yol.**

**Boundary:** kod DOKUNULMADI · commit YOK · push YOK · **11476/16660 DOKUNULMADI** · `state/`-e YAZILMADI (log'u Reis yazdı, ben-okudum) · D64 `8b18f70a` DEĞİŞMEDİ ✓
