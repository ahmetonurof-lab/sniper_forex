# DESIGN NOTE — Provider Timestamp Semantics + Canonical UTC Normalization + DST-Straddle Parity Hardening

> **Status:** Tasarlık — HAKEM/REİS onayı bekliyor. Kod değişikliği YAPILMADI.
> **Date:** 2026-09-09 · **Provenance:** MAIN `83950ec` kaynak-okuması + git history
> **Kapsam etiketi (Reis-emri):** Bu iş "CBDR değişikliği" veya "UTC migration"
> DEĞİLDİR. Adı: **provider timestamp semantics + canonical UTC normalization +
> DST-straddle parity hardening.** Engine davranışı (CBDR penceresi, bias, sweep)
> değişmez — değişen, bar-timestamp'larının kaynağına göre DOĞRU etiketlenmesidir.

---

## 1. Üç zaman-semantiği katmanı (mevcut gerçeğin dökümü)

| Kat | Semantik | Kanıt (kaynak) |
|---|---|---|
| cTrader OpenAPI | **UTC** — `ProtoOATrendbar.utcTimestampInMinutes` = UTC epoch minutes; `ProtoOASpotEvent.timestamp` = UTC ms (D178) | `src/ctrader/data_adapter.py:14-23, 608-628`; `docs/ctrader_openapi_official_research.md` |
| MT5 (legacy) | **naive server time** (ICMarketsSC-Demo: kış UTC+2 / yaz UTC+3; kış ofseti hâlâ "unverified heuristic") | `src/live/clock.py:6-9`; `signal_runner.py:223-226` docstring |
| Canonical engine | **naive UTC** — backtest feather dataset'i de naive UTC; engine'e giren her `Bar.timestamp` UTC olmak ZORUNDA | `clock.py:10-13`; `progress.md` parity kaydı ("iki pipeline da aynı UTC penceresine oturur") |

## 2. Mevcut mekanizma ve neden kaldırılmalı (sentetik round-trip)

Bugünkü cTrader akışı (`data_adapter.py:113`, `:150` → `signal_runner.py:250`):

```
cTrader UTC dakika
  → adapter:  ts_server = utc*60 + server_utc_offset()*3600   (SENTETİK server-time üretir)
  → runner:   server_to_utc_historical(ts_server)             (bar-own-date ile geri çıkar)
  → net:      UTC   (yılın çoğunda identity)
```

Tasarım-niyeti §2.2 (paralel-converter yok) idi ve `78fa8a4` (İş-4a, D159) ile
girdi — kanıt: `git log -S "re-expresses UTC minutes"`. Niyet doğru,
mekanizma **yanlış-layer'da**: UTC kaynağını suni olarak server-time'a
çevirip geri çevirmek, iki ayrı offset-kararı arasındaki tutarlılığa
güveniyor. Kaldırma gerekçeleri:

1. **L1 (aşağıda): round-trip identity DEĞİLDİR** — iki taraf farklı offset
   kullanınca net kayma ±1 saate çıkar.
2. Sentetik veri-üretimi: adapter, broker'ın asla döndürmediği bir "server
   epoch" uydurur → §19 "no synthetic data" ilkesinin gri alanı.
3. Okunabilirlik: her okuyucu "acaba bu `time` alanı şimdi ne?" sorusunu
   sormak zorunda (docstring uyarı bloğu bunun itirafı).
4. Test-ağırılığı: fixture'lar dönüşümü iki modülden ayrı ayrı
   identity-patch'lemek zorunda (`test_orchestrator_state_split.py:33-34`).

## 3. L1 — DST-straddle kusurunun somut örneği (yılda 2 kez, sessiz)

`data_adapter.py:148-151`: offset **adapter-kurulumunda bir kez**,
`server_utc_offset()` = **ŞİMDİKİ** ofset.
`clock.py:69-75`: runner **bar-ın-kendi-tarihi** ile ofset seçer.
Heuristic pencere: son-Pazar-Mart ≤ now < son-Pazar-Ekim → 3, değilse 2.

**Örnek-1 (sonbahar straddle):** Boot 2026-10-26 (DST-sonrası, kış → adapter
her bara **+2** ekler). Replay penceresi ~32 gün geriye gidiyor → 2026-10-24
barı içerir (hâlâ yaz-side, runner **−3** çıkarır):

```
cTrader gerçeği:   2026-10-24 19:00 UTC   (seans-açılış barı)
adapter üretir:    19:00 + 2h = "21:00"
runner bozar:      21:00 − 3h = 18:00 UTC  ← 1 SAAT ERKEN
```

*(Not: ilk taslakta 2026-11-02/10-30 örneği vardı — 10-30 zaten kış-side
olduğu için identity çıkıyordu; `/tmp/l1_repro.py` koşumu iki yönü de
üretti: ORNEK-1 −1h, ORNEK-2 +1h, KONTROL (straddle-dışı) barayı.)*

→ Bar 19:00 eşiğinin dışına düşer: `SessionManager.in_window`
(`src/strategy/session.py:58-62`) onu window-dışı sayar, `htf_bias`
day-key (`hour >= 19 → ertesi gün`, `htf_bias.py:52-56`) yanlış gün-verir;
15m-resample bucket'ı da kayar. O günün CBDR range'i eksik/yanlış barlarla
kurulur.

**Örnek-2 (ilkbahar straddle):** Boot 2026-03-30 (yaz-side → **+3**); pencere
2026-02-28 barlarını içerir (kış-side, runner **−2**): net **+1h** kayma.

Etki-yarıçapı: restart, DST-hafta-sonuna ≤ ~35 gün mesafedeyse tetiklenir;
yılda 2 pencere; hiçbir yerde hata-logu yok. **Parity için sessiz-katil.**

## 4. Neden CBDR davranışı DEĞİŞMEYEZ (davranış-değişmezlik argümanı)

- Engine pencere-kararlarını `Bar.timestamp` üzerinden verir; o timestamp
  bugün de UTC hedefleniyor, revizyonda da UTC — **hedef aynı, yol kısalıyor.**
- Yılın straddle-dışı ~358 gününde round-trip zaten identity → revizyon bu
  günlerde bit-bit aynı bar-ts üretir (regresyon-testi ile kanıtlanacak).
- Straddle günlerinde revizyon **yanlışı düzeltir**, davranışı değiştirmez:
  backtest (feather=UTC) ile canlı arasındaki 1-saatlik kaçak kapanır.
- `current_cbdr_key`/bias/sweep mantığına dokunan tek satır yok —
  `strategy/session.py`, `strategy_runtime.py` bu işin kapsamı DIŞINDA.
- Canlı kanıt (2026-09-09 soak): `[BAR] 15:30/15:45 UTC` slot-dakikaları
  doğru, `cbdr_key=2026-09-09` — mekanizma bugün çalışıyor; L1 bir
  ZAMANLAMA-bombası, mevcut-yanlışlık değil. (§8.2: mevcut hâl bozuk diye
  sunulmuyor.)

## 5. Hedef mimari — "provider declares, normalizer routes"

Tek-kaynak-kuralı (§2.2) korunur; converter ÇOKTAN-tek kalır, sentez-katmanı
ölür:

1. **Adapter sözleşmesi:** `data_adapter.trendbar_to_dict` artık
   `"time": int(tb.utcTimestampInMinutes) * 60` (raw UTC epoch seconds) ve
   `"ts_semantics": "utc"` yazar. `server_utc_offset` importu ve
   `__init__`'daki tek-seferlik-offset (`:148-151`) kaldırılır.
2. **Normalizer (tek karar-noktası):** `_rates_to_bars` (runner +
   orchestrator) dict-girdisinde `ts_semantics` alanına bakar:
   - `"utc"` → `pd.Timestamp(ts, unit="s")` (kimse dokunmaz),
   - `"server"` → `server_to_utc_historical(...)` (mevcut yol),
   - **alan yoksa → `"server"` varsayılanı** — MT5 numpy structured-array
     yolu alan-taşıyamaz; varsayılan MT5-davranışını bayt-bayt korur.
3. **MT5 legacy yolu (SNIPER_DATA_SOURCE=mt5) AYNEN kalır:**
   `candle_feed.fetch_m1:123-124`, `paper.py:606`, `orchestrator.py:2547-2548`
   server-time girdisi görmeye devam eder ve historical-converter'ı
   kullanır. Silinen tek şey cTrader'ın suni server-time üretimi.
   Kış-ofseti sezgisi (L2) MT5-yolunda kalır + boot'ta bir kez
   `SNIPER_ALERT`-level bilgi-notu düşer ("offset heuristic, unverified")
   — sessiz-varsayım görünür olur, davranış değişmez.
4. **clock.py sadeleşir (ölü-kod temizliği, grep-kanıtlı):**
   `server_to_utc()`, `utc_to_server()`, `now_server_time()`, `in_session()`
   → src/ altında **sıfır production-callers** (yalnız testler
   `test_live_candle_feed.py:294`, `test_m1_ingestion_parity.py` kullanıyor).
   Öneri: `server_to_utc_historical` + `server_utc_offset` + `_utcnow_naive`
   kalır; geri kalanı ya silinir ya test-seam olarak işaretlenir.
   `in_session` yerine `strategy/session.py`'in kendi pencere-mantığı
   zaten tek-kaynak.
   Docstring-düzeltmesi (L3): "session window 19:00→01:00 **server time**"
   → **UTC** (fiili-davranışın doğru-tanımı; D44 "raw SERVER epoch" notu da
   provider-bağımlı hale getirilir).
5. **Tick yolu:** zaten UTC (`data_adapter.py:608-628`, D178) — değişiklik
   yok; `_get_spread_state` (orchestrator:2865+) age-hesabı cTrader'da
   doğru kalır, MT5'te D44- kabzası aynen devam.

## 6. Dosya bazında değişiklik yüzeyi (min-diff tahmini)

| Dosya | Değişiklik | ≈diff |
|---|---|---|
| `src/ctrader/data_adapter.py` | time=raw UTC + `ts_semantics` alanı; offset import/init/delete; docstring güncel | +12/−18 |
| `src/live/signal_runner.py` | `_rates_to_bars` semantics-routing (dict-yolunda `.get("ts_semantics","server")`) | +8/−2 |
| `src/live/orchestrator.py` | `_rates_to_bars` aynı routing (2530-2555 bloğu) | +8/−2 |
| `src/live/paper.py` | aynı routing (606 civarı) — paper MT5-shape üretiyor, default "server" yeterli; yine-de sembolik-doktrin | +4/−1 |
| `src/live/clock.py` | docstring UTC-düzeltme; ölü-fonksiyon temizliği (ayrı commit, behaviour-neutral, §11 AST-kanıtlı) | +10/−40 |
| `tests/test_ctrader_data_adapter.py` | offset-testleri → UTC-passthrough testleri + **yeni DST-straddle** | +60 |
| `tests/test_m1_ingestion_parity.py` | cTrader-şekilli fixture'a `ts_semantics` eklenir; F1 (MT5) testleri DEĞİŞMEZ | +15/−10 |
| `tests/test_live_candle_feed.py` | `server_to_utc` silinirse ilgili test taşınır/silinir | −8 |
| `tests/test_orchestrator_state_split.py` vb. | identity_tz fixture'ları sadeleşebilir (opsiyonel, ayrı commit) | ~0 |

Kapsam DIŞI: `strategy/session.py`, `strategy_runtime.py`, `htf_bias.py`,
AuditChain, gate/recon — tek satır dokunulmaz.

## 7. Test/Regresyon seti — ÖNCE TESTLER TANIMLANIR (red → yeşil)

**Yeni (L1'i öldüren):**
- **T1 `test_dst_straddle_roundtrip_is_identity`** — parametrize boot ∈
  {2026-03-30, 2026-11-02} × bar ∈ {straddle-öncesi, sonrası} UTC-timestamp
  seti; `trendbar_to_dict` → `_rates_to_bars` zinciri **her bar için girdi
  UTC'nin aynısını** döndürmeli. Mevcut koda karşı KOŞULARAK KIRMIZI
  vermeli (bug-kanıtı), revizyonla yeşil.
- **T2 `test_adapter_emits_raw_utc`** — `utcTimestampInMinutes*60 ==
  d["time"]` ve `d["ts_semantics"]=="utc"` (offset'e bağımlılık yok).
- **T3 `test_rates_to_bars_semantics_routing`** — `ts_semantics` "utc"/
  "server"/absent üç yolu; absent → server-davranışı (MT5-geri-uyum).
- **T4 `test_session_boundary_bar_survives_straddle`** — 19:00-UTC
  seans-açılış barı straddle-bootopta `in_window` == True kalmalı
  (örnek-1'in uçtan-uca CBDR-teyzidir).

**Mevcut regresyon (yeşil kalmak zorunda):**
- `test_m1_ingestion_parity.py` F1 testleri (MT5 server→UTC iddiası) —
  MT5-yolu değişmediği için dokunulmadan geçmeli.
- `test_p1_5_timezone.py` (historical-converter DST-davranışı).
- `test_orchestrator_state_split.py` 5/5, `test_ctrader_data_adapter.py`
  geneli, parity-suite, tam `tests/` suiti (bilinen 14f/9e pre-existing
  hariç — §13 disiplini: sayı + kapsam beyanı ile).
- **T5 soak-öncesi offline-differential:** aynı M1 penceresiyle
  mevcut-kod vs revizyon-kod `resample_15m` çıktıları byte-karşılaştırması
  (straddle-dışı tarihte identity beklenir — §11 kanıt-hiyerarşisi).

**Test-hijyeni bağımlılığı:** T1 boot-tarihini enjekte edebilmeli →
`server_utc_offset(now_utc)` parametresi zaten var; adapter'a
`now_fn`-seam'i gerekir (görünür test-seam, §19 silent-fallback değil).

## 8. Uygulama sırası (Soak-bitşi / STOP SOAK prosedürü sonrası, EMİR BEKLENİYOR)

```
1. Bu design-note + yüzey-listesi → HAKEM onayı (§5.1 RED=veto)
2. STOP SOAK (gerekiyorsa) → event kaydı
3. T1–T4 yaz → koş → T1/T4 KIRMIZI olmalı (bug provası, kanıt olarak saklanır)
4. data_adapter + runner/orch/paper routing → T1–T4 yeşil
5. clock.py ölü-kod + docstring (ayrı commit; §11 AST-body-karşılaştırma kanıtı)
6. T5 differential + tam regresyon + ruff → commit'ler (küçük, tek-değişken)
7. Soak restart → §18 gözlem: bar-ts'ler, cbdr_key, straddle-penceresi yoksa
   bit-bit aynı çıktı beklentisi
8. memory-bank: design-note kararı + push KAYDI-23 ile birlikte
```

## 9. Açık kalanlar / riskler

- **L2 (kış ofseti doğrulanmamış):** MT5-yolunu etkiler; bu revizyon
  kapsamı DIŞINDA (kapsam-kaydırma yok) — ayrı iş-kalemi: ICMarkets
  server-time doğrulaması (D119-API-testi deseni) ile sabitlenir ya da
  MT5-yolu kullanımdan düşürülür.
- `server_to_utc` (non-historical) silinmesi 2 test-dosyasını dokunmaya
  zorlar; silmek yerine deprecated-bırakmak da seçilebilir (Hakem tercih).
- cTrader `count`-tabanlı fetch'te `from/to` chunk sınırları UTC — pagination
  (`:555` dedupe `int(d["time"])`) semantics-değişmez, dedupe-anahtarı
  zaten tutarlı.
- Bu note'un kendisi commit-değildir; commit ancak uygulama turunda ve
  onaylı-kapsamda (§9.1) yapılır.

## 10. KARAR EKİ — Hakem onayı ve uygulanan kapsam (2026-09-09)

Hakem hükmü (verbatim): *"RATIFIED — PROCEED. Ama minimum diff. Amaç sadece
cTrader UTC timestamp'ini doğru canonical UTC olarak geçirmek ve mevcut MT5
yolunu bozmamak. CBDR, bias, sweep, strategy mantığına dokunma. Yeni
soyutlama, gereksiz refactor, ekstra framework üretme. Önce mevcut testlerle
bug'ı göster, sonra en küçük değişikliği yap."*

Bu karar uyarınca §5.4/§6'dan **şunlar bu turdan ELENDİ** (kapsam-dışı):

- `clock.py` ölü-kod temizliği + docstring commit'i (§6 satırı geçersiz),
- `paper.py` routing değişikliği (§6 satırı geçersiz — paper MT5-shape
  ürettiğinden default-"server" yolu zaten davranış-nötr korundu),
- test-fixture sadeleştirmeleri.

**Uygulanan (commit `108a4b1`):** §5.1–§5.3 birebir — `data_adapter.py`
raw-UTC + `ts_semantics="utc"`, ctor/import/offset kaldırıldı;
`signal_runner.py`/`orchestrator.py` `_rates_to_bars` routing
(default `"server"` → MT5 yolu byte-for-byte değişmedi).

**Kırmızı kanıt (bug provası, §8-adım 3):**
`test_roundtrip_dst_straddle_recovers_utc` eski kodda FAIL:
bar 2026-10-24 19:00 UTC → 18:00 (−1h, winter-boot 2026-10-26).
Düzeltilince 3-sınır-tarihli identity guard olarak PASS.

**Regresyon:** adapter+boot 51/51; tam `tests/` = 14 failed / 9 errors /
647 passed — failure profilinin tamamı `experiment.main_research_c_v1_0`
arşiv-module hatası ailesi; stash-diferansiyeli ile bu değişiklikten
bağımsızlığı kanıtlandı (§13 raporlama disiplini).
