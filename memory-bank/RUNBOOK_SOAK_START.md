# RUNBOOK — SOAK START (operatör için tek sayfa)

> Kaynak: Hakem şablonu (2026-08-31) + kod-doğrulanmış env listesi.
> **D159 karar-8 (cTrader-first): veri kaynağı cTrader — MT5 ölü (D120),
> yalnız `SNIPER_DATA_SOURCE=mt5` ile legacy restore edilir.** Env
> anahtarları `src/live/run_production.py` + `src/config/ctrader_config.py`
> içinden `getenv` taramasıyla doğrulandı (2026-09-09, D178-sonrası).
> Bu liste dışı env OKUNMAZ — uydurma anahtar setlemek sessiz-no-op'tur.

## Adım 0 — Terminal ön-koşulu (ZORUNLU — boot öncesi işaretlenir)

> D181/D181.1 kanıtı (2026-09-09): graceful-stop YALNIZ doğru ortamda
> çalışır. Engel koddan kalktı; ortamdan kalkmadı. Bu madde hatırlatma
> değil, boot'u ENGELLEYEN ön-koşuldur.

- [ ] **Soak ConPTY tabanlı terminalden BAŞLATILMAZ.** VS Code entegre
  terminali (ve ConPTY kullanan herhangi bir SSH/multiplexer kurulumu)
  yasaktır: ConPTY altında CTRL_C iletimi ÇALIŞMAZ —
  `GenerateConsoleCtrlEvent` r=1 döner (yanlış-pozitif) ama sinyal
  iletilmez (D181-T3). Soak `cmd.exe` veya `PowerShell` penceresinden
  DOĞRUDAN (native console) başlatılır.
- [ ] **Soak native Windows console'dan DOĞRUDAN başlatılır (cmd.exe /
  PowerShell) — Git-Bash/MSYS/WSL üzerinden HİÇBİR ara-katmanla
  (wrapper script, `timeout`, `make`, bash fonksiyonu, CI runner
  script'i, `bash -c` dahil) başlatılmaz.** Kök-neden tek komuta özgü
  DEĞİL: MSYS/Git-Bash ortamı native-Windows-child'a sinyal İLETEMEZ —
  aynı ortamdan koşan her wrapper aynı engeline çarpar. Somut kanıt
  (D181.1 denklik-replikası): Git-Bash GNU `timeout 5` handler'lı
  child'ı rc=124 force-kill etti — handler çağrılmadı, SHUTDOWN audit
  yazılmadı, lock kaldı (bu, D180 bulgusunun kök-nedenidir; D180'deki
  komut `timeout 150 python -m src.live.run_production` idi). Soak
  ön-süresiz çalışır; durdurma yalnız operatör Ctrl-C iledir.
  **Bu genişletme Hakem notuyla yapıldı (2026-09-09):** `timeout` yasağı
  değil, MSYS tabanlı her şeyin yasağı — gerçek kök-neden ortam
  sınıfıdır, tek binary değil.
- [ ] **Foreground teyidi:** soak process'i başlatan native console'da
  ön-planda çalışıyor ve operatör aynı pencerede Ctrl-C basabilecek
  durumda olmalıdır (arka-plan/servis-start drill'i geçersiz kılar).
- [ ] **QuickEdit-tuzağı hatırlatması (SOAK-STOP kanıtı, 2026-09-09
  13:48):** Ctrl-C "işlemiyor"sa ÖNCE pencerede kalmış bir metin-seçimi
  var mı bak → **ESC ile seçimi bırak → tekrar Ctrl-C.** QuickEdit
  seçim-modunda Ctrl+C kopyalama olarak yorumlanır, sinyal python'a
  ulaşmaz. Kanıt: ESC+Ctrl-C → graceful SHUTDOWN (exit=2,
  kill_switch_during_sleep, lock-release, snapshot) — birebir D181-T4.
  ESC+Ctrl-C de çalışmazsa STOP TALEP ET — asla pencere-kapatma/taskkill.
- [ ] **Console-oturum teyidi (RDP/uzak-oturum yasak):** soak, fiziksel
  veya KVM-bağlı console oturumunda başlatılır; RDP/VPS uzak oturumdan
  BAŞLATILMAZ — RDP disconnect, oturuma bağlı console pencerelerini bazı
  yapılandırmalarda öldürür (= pencere-kapatma force-kill sınıfı olay;
  operatör hatası değil, sıradan bağlantı kopması). **Bu makinede kanıt
  (2026-09-09):** `SESSIONNAME=Console`; `qwinsta` → yalnız
  `>console Administrator 1 Active` (RDP-oturumu-yok);
  `TermService=Stopped`; 3389-dinleyici-yok → **RDP kapalı ve
  kullanılmıyor; erişim fiziksel/console.** Boot-öncesi teyit:
  `echo $SESSIONNAME` = `Console` (PowerShell: `$env:SESSIONNAME`).
  RDP ileride açılırsa: SOAK-STOP → Adım-0 bu madde dahil tekrar.

## Adımlar

1. **cTrader ön-koşulları (terminal YOK — Open API):** repo kökü `.env`
   içinde `CTRADER_CLIENT_ID` / `CTRADER_CLIENT_SECRET` /
   `CTRADER_ACCOUNT_ID` / `CTRADER_HOST` mevcut olmalı
   (`ctrader_config.py` .env'i otomatik yükler; eksikse fail-loud FATAL —
   sessiz MT5 fallback YOK). Hesap bilgisi operatör sırrıdır, hiçbir
   ajan/defter/runbook'a yazılmaz. Paper soak: `CTRADER_HOST=demo.ctraderapi.com`.
2. **Token geçerliliği (Algo-Trading'in cTrader karşılığı):** repo kökü
   `token_cache.json` erişilebilir olmalı (D140 access token; OAuth2
   refresh akışı bağlantıda otomatik). S1 karşılığı = bağlantı-auth:
   `ACCOUNT_AUTH_RES` gelmezse D178 `account_authorized` gate'i
   SAFE_START/FATAL üretir (canlı ölçüm: TCP ~0.2-2s + auth ~+1.9-2.2s;
   `ensure_connected: True (3.3s)`).
3. **Env set (Adım-0'a uygun native console — PowerShell):**
   ```powershell
   $env:SNIPER_STATE_DIR = 'C:\Users\Administrator\Desktop\sniper_forex\state'  # D18: MUTLAK yol
   $env:SNIPER_SYMBOLS      = 'EURUSD'
   $env:SNIPER_SIGNAL_ONLY  = '1'   # paper soak (default zaten 1; açık yaz)
   $env:SNIPER_DATA_SOURCE  = 'ctrader'  # default; açık yazmak belgeleyici
   ```
   (D181.2 not: bu bölüm Git-Bash `export` sözdiziminden PowerShell'e
   çevrildi — Adım-0 ara-katman yasağıyla kendi kendine çelişiyordu.
   Git-Bash `export` karşılıkları yalnız posix-ortamda çalışacak
   birim-testler içindir, soak-boot için DEĞİL.)
   **`MT5_EXPECTED_LOGIN` SETLENMEZ** — ctrader-modunda yok-sayılır ve
   her boot audit-WARN üretir
   (`expected_login_is_mt5_flag_ignored_in_ctrader_mode`). Kimlik
   kontrolü ctrader'da `CTRADER_ACCOUNT_ID` üzerinden yapılır
   (validate_ctrader_config fail-loud).
   Opsiyonel (varsayılanlı): `SNIPER_AUDIT_PATH` (yoksa `$SNIPER_STATE_DIR/audit.jsonl`),
   `SNIPER_WARMUP_COUNT` (65000), `SNIPER_POLL_INTERVAL` (20), `SNIPER_MAX_SPREAD` (30),
   `SNIPER_LADDER_THRESHOLD` (3), `SNIPER_BACKOFF_MULT` (2), `SNIPER_BACKOFF_MAX` (300),
   `SNIPER_FEED_CAP` (1024), `SNIPER_MAGIC` (9007001).
   **Telegram (D53 wired):** `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` repo
   kökündeki `.env` içinden otomatik okunur (`mt5_config` setdefault — export
   gerekmez). `TELEGRAM_CHAT_ID=7711060411` `.env`'de mevcut; **BOT TOKEN
   operatör tarafından `.env`'e yazılmalı** (sir — hiçbir defter/koda yazılmaz).
   Token yoksa: ConsoleAlert fallback + audit'te TEK `alerting/CONSOLE_FALLBACK`
   WARN — sessiz fallback YOK (S5). soak-start kontrolü: `audit.jsonl`'da bu
   WARN yoksa ve ilk transition'da Telegram DM gelmiyorsa kanal ölüdür.
   **Ön koşul (operatör):** Bot kendisine hiç yazmamış kullanıcıya DM ATAMAZ
   (Telegram platform kısıtı — `sendMessage` → 400 "chat not found"). Soak
   başlamadan önce operatör Telegram'da botu açıp **START**'a basmalı;
   ardından smoke testi (`curl sendMessage` → `"ok":true`) ile kanal
   doğrulanmadan soak'a geçilmemeli.
4. **Kosum (venv + repo kökü — native console'da):**
   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
   .\.venv\Scripts\Activate.ps1
   python -m src.live.run_production
   ```
   (Aynı pencerede: Adım-3 env'leri + bu aktivasyon + kosum — console
   penceresi soak boyunca AÇIK kalır; kapatmak = force-kill sınıfı
   olaydır.)
5. **İlk 60 sn:** startup bloğunu yakala → hakeme gönder:
   `startup PROCEED|SAFE_START|FATAL: <reason> (warmup_bars=N)` +
   REPLAY event'i (`replay_bars`, `end_state`, bias kuruluş saati).
   Konsol stdout + `state/audit.jsonl` aynı anda izlenir.
   **Beklenen (Hakem-onaylı, 2026-09-09): SAFE_START** — reason yalnız
   `recon_blocked: NOT_RUN` (cTrader position-recon iş-kalemi
   tamamlanana dek; gate CLOSED = fail-closed doğru; signal_only'de
   emir zaten yok). Farklı reason görürsen (warmup_failed,
   symbols_response_timeout, auth) D178-öncesi bug ailesidir → soak
   başlamaz, rapor et.
6. **İlk 3 bar (~45 dk):** emit saatleri 15m grid'e oturuyor mu —
   `audit.jsonl`'daki bar timestamp'leri `% 900 == 0` kontrolü.
   **Dipnot (Hakem-onaylı, SOAK-D2, 2026-09-09):** SAFE_START-soak'ta
   gate CLOSED → feed yok → `on_bar` çağrılmaz → canlı STATE
   ÜRETİLEMEZ (canlı-gözlem beklenmez). Grid kanıtı bu modda REPLAY
   STATE'lerinden okunur (SOAK-D2 kanıtı: 1905/1905 bar_ts %900
   hizalı, 0 ihlal; audit sessizliği = fail-closed tasarım sonucu,
   heartbeat birincil canlılık kanıtıdır).

## Soak sayacı

Gün-3 / gün-14 takvimi **bu adımdaki gerçek startup anından** işler;
masa saatinden değil. Soak = bu komutun döndürdüğü process; başka hiçbir
"başlattım" ifadesi soak başlangıcı sayılmaz (§3).

## Canlılık taraması (günlük)

- günlük tarama: process canlı + audit büyüyor + (Telegram sessizse) neden yok.
- Telegram bir dead-man sinyali DEĞİLDİR: transition-only + ladder +
  cold-rebuild hacmi düşük tasarlandı — sessizlik normal olabilir, ama
  "neden yok" sorusu audit karşılaştırmasıyla cevaplanmalıdır. Gerçek
  external dead-man ping Aşama 5 kapsamındadır.

## Kill / restart drill (72-saat listesi maddesi)

- **Drill YALNIZ Adım-0'a uygun ortamda yapılır:** soak'ın çalıştığı
  native console'da, foreground process'e doğrudan Ctrl-C. `taskkill`,
  MSYS `timeout`, ConPTY-terminalden sinyal denemeleri GEÇERSİZ
  drill'dir — sinyal ulaşmaz; force-kill veya yanlış-pozitif üretir
  (D181.1). Bu yollarla alınan "graceful-yok" gözlemi kod-hatası
  SAYILMAZ, ortam-hatasıdır.
- SIGINT (Ctrl-C) → graceful: exit-code durum-bağımlı (K2: 0/2),
  SHUTDOWN audit + snapshot + lock release beklenir. Kanıt
  (D181-T4, gerçek-console CTRL_C): rc=2, 2.0 sn, SHUTDOWN-audit
  `kill_switch_during_sleep`, lock release — kusursuz.
- **MISMATCH-hatırlatması (Hakem-talebi, SOAK-D1.1):** Soak boyunca
  GATE CLOSED reason'ında `reconciliation status: MISMATCH` görürseniz,
  bu **bilinen bir etiket hatasıdır** (SOAK-D1.1) — gerçek pozisyon
  kontrolü gerektirmez. (Kök: manuel-snapshot `NOT_RUN` değeri
  enum-üyeliği-yok → fail-closed-MISMATCH-düşüşü; davranış-güvenli,
  etiket-yanlış. Ayrıntı: progress.md açık-kalem-7a/7b/7c.)
- Restart → backoff ladder sıfırdan, heartbeat yeniden, REPLAY event'i
  tekrar üretilmeli; state tutarlılığı `state/` + audit karşılaştırmasıyla doğrulanır.
- Lock dosyası (`SNIPER_STATE_DIR` altında) kill sonrası kalmışsa: PID-ölü
  takeover yolu meşru, PID-canlı takeover FATAL olmalı.

## Freeze hatırlatması (§17)

Soak koşarken `src/` + `tests/` + `index.json` donmuş (5d8e067 =
9f0fe80 + yalnız memory-bank PUSH-KAYDI-20; executable kod 9f0fe80
ile birebir — D178 fix'leri dahil).
Kod değişikliği gerekirse: STOP SOAK → kayıt → suite → commit → N2 → push →
soak restart. Bu runbook'un kendi güncellemesi memory-bank chore commit'idir,
freeze ihlali değildir.

**Heap-crash 0xc0000374 kapsamı (Hakem-doğrulaması, 2026-09-09):**
`_diagnose_path_write` production-erişilebilir — `Lock._write()` içinde
one-shot tanı, her boot çalışır (crash_log.txt writer_diagnostic
kayıtları = 7/7 production boot pozitif çalıştırma-kanıtı, hepsi temiz).
Crash yalnız pytest-context'inde görüldü. Paralel inceleme kalemi
YÜKSELTİLDİ (Hakem matrisi: production-erişilebilir → gündemde yukarı),
soak-blocker DEĞİL.

**Kapsam-dipnotu (Hakem-notu, 2026-09-09):** Bu checklist **local test
ortamı** bağlamında yazıldı (Reis-teyidi: "şu an test aşaması ve local
makinayız"; kanıt: SESSIONNAME=Console, RDP-kapalı). Sistem ileride bir
sunucuya (Ubuntu/Windows VPS) taşınırsa **Adım-0'ın RDP/console-erişim
maddesi YENİDEN değerlendirilecek** — "local makinayız, atlanabilir"
durumu o zaman geçerli olmayacak (PUSH-KAYDI-21 açık-kalem).
