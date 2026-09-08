# RUNBOOK — SOAK START (operatör için tek sayfa)

> Kaynak: Hakem şablonu (2026-08-31) + kod-doğrulanmış env listesi.
> **D159 karar-8 (cTrader-first): veri kaynağı cTrader — MT5 ölü (D120),
> yalnız `SNIPER_DATA_SOURCE=mt5` ile legacy restore edilir.** Env
> anahtarları `src/live/run_production.py` + `src/config/ctrader_config.py`
> içinden `getenv` taramasıyla doğrulandı (2026-09-09, D178-sonrası).
> Bu liste dışı env OKUNMAZ — uydurma anahtar setlemek sessiz-no-op'tur.

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
3. **Env set (Git Bash):**
   ```bash
   export SNIPER_STATE_DIR='C:\Users\Administrator\Desktop\sniper_forex\state'  # D18: MUTLAK yol
   export SNIPER_SYMBOLS=EURUSD
   export SNIPER_SIGNAL_ONLY=1             # paper soak (default zaten 1; açık yaz)
   export SNIPER_DATA_SOURCE=ctrader       # default; açık yazmak belgeleyici
   ```
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
4. **Kosum (venv + repo kökü):**
   ```bash
   source .venv/Scripts/activate
   python -m src.live.run_production
   ```
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

- SIGINT (Ctrl-C) → graceful: exit-code durum-bağımlı (K2: 0/2),
  SHUTDOWN audit + snapshot + lock release beklenir.
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
