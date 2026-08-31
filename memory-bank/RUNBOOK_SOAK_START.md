# RUNBOOK — SOAK START (operatör için tek sayfa)

> Kaynak: Hakem şablonu (2026-08-31) + kod-doğrulanmış env listesi.
> Env anahtarları `src/live/run_production.py` + `src/live/*.py` +
> `src/trading/mt5_connection.py` içinden `getenv` taramasıyla doğrulandı.
> Bu liste dışı env OKUNMAZ — uydurma anahtar setlemek sessiz-no-op'tur.

## Adımlar

1. **MT5 terminal64 başlat, IC Markets hesabına login** (kullanıcı yapar —
   hesap bilgisi operatör sırrıdır, hiçbir ajan/defter/runbook'a yazılmaz).
   Kurulu yol (doğrulanmış): `C:\Program Files\MetaTrader 5 IC Markets Global\terminal64.exe`
2. **Terminalde Algo Trading ON** — AutoTrading butonu yeşil; `trade_allowed=1`
   olmalı, yoksa S1 SAFE_START üretir (giriş kapalı, state inşası sürer).
3. **Env set (Git Bash):**
   ```bash
   export MT5_EXPECTED_LOGIN=<login>        # D12: boşsa warn + SAFE_START (bilinçli)
   export SNIPER_STATE_DIR='C:\Users\Administrator\Desktop\sniper_forex\state'  # D18: MUTLAK yol
   export SNIPER_SYMBOLS=EURUSD
   ```
   Opsiyonel (varsayılanlı): `SNIPER_AUDIT_PATH` (yoksa `$SNIPER_STATE_DIR/audit.jsonl`),
   `SNIPER_WARMUP_COUNT` (65000), `SNIPER_POLL_INTERVAL` (20), `SNIPER_MAX_SPREAD` (30),
   `SNIPER_LADDER_THRESHOLD` (3), `SNIPER_BACKOFF_MULT` (2), `SNIPER_BACKOFF_MAX` (300),
   `SNIPER_FEED_CAP` (1024), `SNIPER_MAGIC` (9007001).
   **Telegram/APNs env'i YOK** — alert kanalı bu kod tabanında henüz env-okumuyor;
   D28-Telegram E2E soak test maddesi ancak kanal fiilen wired'sa anlamlıdır (kontrol listesinde işaretlenecek).
4. **Kosum (venv + repo kökü):**
   ```bash
   source .venv/Scripts/activate
   python -m src.live.run_production
   ```
5. **İlk 60 sn:** startup bloğunu yakala → hakeme gönder:
   `startup PROCEED|SAFE_START|FATAL: <reason> (warmup_bars=N)` +
   REPLAY event'i (`replay_bars`, `end_state`, bias kuruluş saati).
   Konsol stdout + `state/audit.jsonl` aynı anda izlenir.
6. **İlk 3 bar (~45 dk):** emit saatleri 15m grid'e oturuyor mu —
   `audit.jsonl`'daki bar timestamp'leri `% 900 == 0` kontrolü.

## Soak sayacı

Gün-3 / gün-14 takvimi **bu adımdaki gerçek startup anından** işler;
masa saatinden değil. Soak = bu komutun döndürdüğü process; başka hiçbir
"başlattım" ifadesi soak başlangıcı sayılmaz (§3).

## Kill / restart drill (72-saat listesi maddesi)

- SIGINT (Ctrl-C) → graceful: exit-code durum-bağımlı (K2: 0/2),
  SHUTDOWN audit + snapshot + lock release beklenir.
- Restart → backoff ladder sıfırdan, heartbeat yeniden, REPLAY event'i
  tekrar üretilmeli; state tutarlılığı `state/` + audit karşılaştırmasıyla doğrulanır.
- Lock dosyası (`SNIPER_STATE_DIR` altında) kill sonrası kalmışsa: PID-ölü
  takeover yolu meşru, PID-canlı takeover FATAL olmalı.

## Freeze hatırlatması (§17)

Soak koşarken `src/` + `tests/` + `index.json` donmuş (b89895a).
Kod değişikliği gerekirse: STOP SOAK → kayıt → suite → commit → N2 → push →
soak restart. Bu runbook'un kendi güncellemesi memory-bank chore commit'idir,
freeze ihlali değildir.
