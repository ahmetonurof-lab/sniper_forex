# D66 — AŞAMA-1 SWEEP DETECTION (SINIF-1) — PRE-REGISTRATION

> **Statü:** §0 sayımdan ÖNCE yazıldı · read-only · untracked · kod-artefaktı-değişmedi
> **Üretici:** Cline (D66 executor) · **Yazım:** 2026-09-03 13:5x +03:00 (server = UTC+3, ölçüldü)
> **SINIF:** Bu dosya **SINIF-1 (SEÇİM)** ürünüdür — tespit/öngörü. SINIF-2 (gözlem) değil. Canlı-log ile karşılaştırma `results/D66_production_path_first_observation.md`'de (Aşama-5).
> **SINIR:** Trade kararı/edge iddiası taşımaz.

---

## §0. PRE-REGISTRATION (bağlayıcı — sonuçlar aşağıda DEĞİL)

### 0.1 Amaç
Kanonik-canlı semantiğe göre **2026-09-02 12:00 (server) → capture-anı** penceresinde gerçekleşmiş sweep(leri) tespit etmek ve Aşama-2 sembol-kararına + Aşama-4/5 canlı-karşılaştırmaya girdi vermek. Çıktı: tablo **veya açıkça "none-today"**.

### 0.2 Enstrüman: YENİDEN-YAZIM YOK — canlı üretim kodu offline sürülür
AGENTS.md §2.2 (mevcut-mekanizmayı-yeniden-kullan) + §3 (gerçek-kanıt-hiyerarşisi) gereği tespit, **canlı modüllerin kendisiyle** yapılır:

| bileşen | canlı kaynak |
|---|---|
| M1→UTC dönüşümü | `src/live/clock.py:69 server_to_utc_historical` (bar'ın-kendi-offset'i, DST-sezgisel) |
| 15m agregasyon | `src/live/candle_feed.py:44 resample_15m` (UTC-grid `ts_ms//900000`, etiket=ilk-M1-bar'ı, **<3-bar kutu düşer**, sırasız-giriş yeniden-sıralanmaz/R4) |
| Sürücü | `src/live/strategy_runtime.py:131 StrategyRuntime` → `warmup()` :163, `on_bar()` :184 → `session.update(bar)` :263 |
| Sweep semantiği | `src/strategy/session.py:104 check_sweep` / `:56 in_window` / `:64 cbdr_day_key` |
| Pencere | `src/live/clock.py:24–25` `SESSION_START_HOUR=19`, `SESSION_END_HOUR=1` → `StrategyRuntime:142–143` |
| Tolerans | `sweep_atr_tolerance_mult=0.5`, `sweep_default_tolerance=10.0` (`strategy_runtime.py:145–146`) |

### 0.3 PENCERE-DIŞI BANDI — HÜKÜM-PİNİNE KOD-KANITLI DÜZELTME
Hüküm §2-Aşama-1 pini: *"kontrol yalnız pencere-dışı (**04:00→19:00 server**)"*. Ölçülen canlı zincir:

1. `candle_feed.py:113–118` M1'i **server→UTC çevirir** (`server_to_utc_historical`), sonra `resample_15m`'e verir.
2. `SessionManager.in_window` bu **UTC-etiketli** barların saati üzerinde çalışır (`h>=19 or h<1`).
3. Yaz-offset'i = **+3 saat** (bugün, ölçüldü: `symbol.time` epoch'u UTC-okunduğunda yerel-duvar-saatiyle birebir).

→ CBDR penceresi **UTC 19:00→01:00 = server 22:00→04:00**; sweep-kontrol-bandı = **server 04:00→22:00**.
Yani hâkim-pin'in **"04:00" ucu DOĞRU** (pencere server 04:00'te kapanır), **"19:00" ucu DEĞİL** — 19:00 UTC başlangıcının server karşılığı **22:00**. `clock.py:13` docstring'i pencereyi "19:00→01:00 **server time**" diye tarif ederek bu 3-saat kaymasını kendisiyle çelişiyor; `clock.in_session(dt_server)` (:93) **üretimde hiç çağrılmıyor** (yalnız `tests/test_live_candle_feed.py:296–300`) → ölü-kod, latent tuzak, backlog.
**Bu taramada band = UTC h∈[1,19) ≡ server 04:00→22:00.** (Düzeltme kabul edilmezse tarama yeniden-koşulur; sonuçlar iki-bazda-da-raporlanabilir.)

### 0.4 TOLERANS = donmuş — ve WARMUP-KONUMU belirsizliği (SESSİZ SEÇİM YOK)
`session.atr` canlıda **yalnız `warmup()` içinde bir kez** set edilir (`strategy_runtime.py:176`); `on_bar` hiç güncellemez (:213 yalnız-yerel-`atr_val`'i Wildler günceller) → **canlı tolerans da warmup-ATR'sinde donar** (D64-bulgusu canlı-yolda doğrulandı). Persist/restore: `:485/:534/:543`.

Fakat warmup'un **nerede** olduğu iki-okumaya izin veriyor:
- **V-LIVE (birincil):** motorun-fiilen-yaptığı — sürülen listenin **ilk-100** 15m barı warmup. Canlı-boot `replay_bars=4237 / warmup_bars=4338` raporladı (audit, Sep 2 23:08) → warmup, tarih-başında (~45 gün önce).
- **V-PIN (hâkim-pin okuması):** "warmup = **pencere-öncesi-son-100**×15m-bar".

İkisi **farklı donmuş-tolerans** üretir → farklı sweep-kararı mümkündür. **Tara, ikisini-de koş, ayrışmayı raporla.** Sessiz-tercih yapılmaz.

### 0.5 Sayım-pinleri
1. **Kapsam (detection scope):** sweep-olay-zamanı ∈ [server 2026-09-02 12:00, capture-anı] ≡ UTC [2026-09-02 09:00, …].
2. **İlk-sweep-kazanır:** `bias_locked` sonrası `check_sweep` None döner (`session.py:114–115`) → gün-başına-en-fazla-bir-sweep.
3. **Tie-break:** en-erken `timestamp`.
4. **Kayıt-alanları:** `{symbol, ts_server, ts_utc, yön, sweep_price, ref_level, tol, bar_index, day_key}`.
5. **"none-today"** birincil-çıktı-seçeneğidir, başarısızlık değil (fallback-ağacı: default = EURUSD-plain-T0#7).

### 0.6 Girdi-mühürleri (capture, Aşama-0 — AM-T7-3: boot-öncesi-yakalama)
`state/d66_capture/` (untracked; `state/` repoda-tamamen-untracked, 0 takip-dosyası) · MT5 build 6140 · IC Markets Global · `copy_rates_from_pos`+epoch-filtre (⚠️ `copy_rates_range` naive-datetime'ı **yerel** sanıp pencereyi −3h kaydırıyor, ölçüldü) · ⚠️ **abonelik-gecikmesi:** `symbol_select` hemen-önce çağrılmasa GBPJPY **bayat (Aug 20–21)** veri döndürdü, 2sn-sonra doğru → tazelik-koruyucusu-koşuldu.

| sembol | n(M1) | kapsam (server) | sha256(16) |
|---|---|---|---|
| EURUSD | 1551 | 09-02 12:00 → 09-03 13:51 | `89fee22afa6a6ad4` |
| USDJPY | 1552 | 09-02 12:00 → 09-03 13:52 | `1513e8562d458537` |
| GBPUSD | 1552 | aynı | `68fb424dd8599699` |
| AUDUSD | 1552 | aynı | `d1919703d878a8da` |
| USDCAD | 1552 | aynı | `4fd4c660939f7735` |
| GBPJPY | 1552 | aynı | `c9c2fd3a7648cb32` |

Warmup-önek-için ek-çekim: 60,000 M1 = server `2026-07-07 20:53 → 2026-09-03 13:54` (canlı-boot'un ~45-günlük replay ölçeğini karşılar).

### 0.7 Boundary
Read-only · kod-değişikliği YOK · `.env`-e-dokunulmadı (yalnız anahtar-ADLARI okundu: MT5_LOGIN/PASSWORD/SERVER, TELEGRAM_*) · push YOK · `index.json` YOK · boot HENÜZ YOK (Aşama-3 ayrı-hüküm).

---

## §1. SONUÇLAR (tarama-koştu — §0 mühürlendikten SONRA)

**Enstrüman:** canlı `StrategyRuntime` offline · 6/6 sembol · 4005 15m-bar (60k M1, server `2026-07-07 20:53 → 09-03 13:54`) · iki warmup-varyantı.

### 1.1 Sweep-tablosu (kapsam içi, V-LIVE = birincil)

| sembol | ts (server) | ts (UTC) | yön | sweep_price | ref_level | tol | day_key | marj (pip) |
|---|---|---|---|---|---|---|---|---|
| **EURUSD** | **2026-09-02 16:15** | 13:15 | **bullish** | 1.15780 | 1.15833 | 0.000332 | 2026-09-02 | **+1.98** |
| GBPUSD | 2026-09-02 16:30 | 13:30 | bullish | 1.34928 | 1.35070 | 0.000441 | 2026-09-02 | +9.79 |
| USDCAD | 2026-09-02 16:30 | 13:30 | bearish | 1.39088 | 1.39028 | 0.000340 | 2026-09-02 | +2.60 |
| AUDUSD | 2026-09-03 10:15 | 07:15 | bearish | 0.71747 | 0.71712 | 0.000275 | 2026-09-03 | **+0.75** |
| USDJPY | — | — | — | — | — | — | — | *none-today* |
| GBPJPY | — | — | — | — | — | — | — | *none-today* |

**Tie-break (en-erken-ts) → X = EURUSD.** USDJPY ve GBPJPY için sonuç **açıkça "none-today"** (fallback-ağacı-devre-dışı: kapsamda ≥1 sweep var).

### 1.2 AŞAMA-2 KARARI
`X == EURUSD` → **swap-yok** · `SNIPER_SYMBOLS` override **gerekmiyor** · **`.env`-dokunulmadı** (secret-hattı) · kod-değişikliği-sıfır · D14-tek-sembol-uyumlu. Boot **EURUSD-plain** (AM-T7-2'nin-koşullu-dalı-kullanılmadı, yetkisi-ayakta).

### 1.3 CBDR end-state (day-key 2026-09-03, capture-anında)

| sembol | V-LIVE bias | locked | body_high | body_low | tol(V-LIVE) | tol(V-PIN) |
|---|---|---|---|---|---|---|
| EURUSD | NEUTRAL | ✗ | 1.15895 | 1.15827 | 0.000332 | 0.000220 |
| USDJPY | NEUTRAL | ✗ | 158.984 | 158.638 | 0.030500 | 0.072179 |
| GBPUSD | NEUTRAL | ✗ | 1.34898 | 1.34790 | 0.000441 | 0.000325 |
| **AUDUSD** | **BEARISH** | **✓** | 0.71712 | 0.71635 | 0.000275 | 0.000242 |
| USDCAD | NEUTRAL | ✗ | 1.38461 | 1.38370 | 0.000340 | 0.000226 |
| GBPJPY | NEUTRAL | ✗ | 214.379 | 213.848 | 0.053000 | 0.097786 |

### 1.4 §0.4 ayrışması — GERÇEK ÇIKTI (sessiz-tercih YOK)
İki-sembolde **karar tersine dönüyor**: EURUSD sweep 1→0 · USDCAD NEUTRAL→**BULLISH-locked**.
**Mekanizma (neden V-LIVE):** `warmup()` yalnız-ATR hesaplar, `session.update()` **çağırmaz** → body-accumulation `_start_idx`'te başlar. V-PIN'de warmup scope-un-hemen-öncesinde bittiği için scope-başında `body_high==0.0` → `check_sweep` erken-çıkarışa düşer (`session.py:117–118`) → **V-PIN yapısal-kör**. V-LIVE canlı-motorun-fiili-şekli (tarih-başı-warmup + kesintisiz replay). **Seçim-tercih-değil, mekanizmal.**

### 1.5 Hüküm-düzeltmesi-#1 — DOĞRULANDI (35 bar, birincil-enstrüman)
EURUSD, server `09-03 04:30 → 13:45`: her-15m barında `high > body_high + tol` ✓ (ext 1.15934→**1.16147**), fakat **kapanış da band-üstünde** → `close < body_high` ✗ → **bearish-sweep koşul-u-tutmaz**; bullish-koşulu (`low < body_low − tol`) de ✗. **Sonuç: bu-sabahki-hareket canonical SWEEP DEĞİL, yönsel KIRILIM.** body_high tüm gün **1.15895'te dondu** (pencere 04:00 server'da kapandı, out-of-window'da `track_body` işlemez).
**Yan-bulgu (③'e-mekanik-girdi):** güçlü-trend günleri **bias kilitlemez** — yalnız wick-reclaim günleri kilitler. Bu, D64'un %82.87 coverage'ı ve BEAR-eğilimi için sayım-değil-mekanizma-üretir.

### 1.6 Sağlamlık-uyarısı (parity iddiasından ÖNCE okunmalı)
Sweep marjları **+0.75 … +9.79 pip**. Canlı motorun **gerçek** donmuş toleransı `state/EURUSD.json`'da: `session_atr=0.000595714` → **tol=0.000297857** (benim 0.000332'm ≠ — çünkü canlı warmup `2026-06-30`'da başlıyor ve `SNIPER_WARMUP_COUNT` default **65000**, benim çekimim 60000). → **Aşama-5'te offline-tarama, boot'tan-okunan `session_atr` ile 65000-çekimde YENİDEN-koşulmadan hiçbir band/bias/sweep satırına "parity" denmez.** Sınır-davasındaki EURUSD(+1.98) ve AUDUSD(+0.75) satırları bu-düzeltmeye-duyarlıdır.

### 1.7 Near-miss enstrümanı — tanımı-ve-kafondansı
"near-miss" = motorun-sweep-vermediği barlarda, **fiyat-seviyesi** koşulunun (`high>bh+tol` veya `low<bl−tol`) tuttuğu ama **kapanış** koşulunun tutmadığı barlar (V-LIVE sayımları: EURUSD 52 / USDJPY 85 / GBPUSD 49 / AUDUSD 8 / USDCAD 57 / GBPJPY 44; 09-03 04:00-sonrası: 35/40/29/5/36/39). **Kafondans uyarısı:** sayaç `bias_locked` iken susar → AUDUSD'ün-düşük-sayısı kilitten-gelir, sakinlikten-değil. Bu-alan **teşhis-amaçlıdır, motor-kararı-değildir** (tolerans ve bh/bl benim snapshot'ımdan).

### 1.8 Aşama-4/5'e-devredilen-öngörüler (SINIF-1 — canlıda-test-edilecek)
1. Boot **S9 COLD_REBUILD** verecek (`EURUSD.json` ≈38h bayat), restore DEĞİL (AM-T7-2).
2. `S11 SAFE_START` + entry-gate CLOSED (AM-T7-4, çift-yapısal-güvence).
3. Day-key `2026-09-03` EURUSD bias'ı: **NEUTRAL/unlocked**, body `[1.15827, 1.15895]` (tol-düzeltmesiyle-yeniden-doğrulanacak).
4. **Pencere server 22:00→04:00** (= W2) body-formasyonunu ilk-defa canlıda üretecek; W1 (boot→19:00 server) yalnız sweep-bandını görür → **W2, W1'den daha-bilgi-yüklü** (Reis-kararı için not).
5. AUDUSD tek kilitli-bias adayı (BEARISH, +0.75 pip marj) — fakat kapsam-dışı-sembol: boot EURUSD kalktığı için gözlenmez.

### 1.9 Pinler
`results/D66_sweep_detection.md` §0-yazım-sonrası-§1-eki; capture-mühürleri §0.6'da. Tarama-çıktısı (ham-JSON): `%TEMP%\d66_detect.json` (repo-dışı). Script: `%TEMP%\d66_detect.py` (repo-dışı — kod-artefaktı-değil).

---
