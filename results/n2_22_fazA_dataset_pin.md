# N2 #22 — FAZ-A DATASET-PİN DOSYASI (B-paketi)

> **Durum:** PİN-FİKSASYON (handoff-A-paketinin-B-üyesi; `results/N2_22_fazA_handoff.md` §6'ya-ayrıntı)
> **Kaynak-manifest:** `memory-bank/dataset_manifest_v1.1.md` (84-satır, fiksasyon 2026-08-31) — hash'ler-buradan-kopya
> **Bugünkü-doğrulama:** 2026-09-04 — `sha256sum` çıktısı × manifest-hash'leri **tam-64-hane-diff'i = BOŞ → 24/24-BİREBİR ✓** (18-feather + 6-RAW-CSV)

## 1. Motor-tükettiği-yaprak — 6×15m feather (`data/icmarket_feather/`)

| File | SHA256 | Rows | Ölçülen-span (2026-09-04) |
|---|---|---|---|
| AUDUSD_15m.feather | `ad332253a6aaa5afd4e09d77901c153246815413318ec7a42619a50c5bd23fdd` | 65732 | 2024-01-01 22:01:00 → 2026-08-21 20:45:00 |
| EURUSD_15m.feather | `42fcbb72bfc2f103f1801782067da26507c19978a81a8d3f65b5d4c655e58025` | 65740 | 〃 |
| GBPJPY_15m.feather | `99fb53137320110ed4968374a739b038d32424b1bef0b28d2b28e781af5206c3` | 65741 | 〃 |
| GBPUSD_15m.feather | `89d8efccedd2f351f54f529148a2d97f9d15f999887d0161386b9889099dab67` | 65730 | 〃 |
| USDCAD_15m.feather | `8adbb32109504765a48a602ccfeed7c9adf29563d61f96599afe4d0748222a45` | 65716 | 〃 |
| USDJPY_15m.feather | `3ee48eb627c3529045e6f28735d2c85558d8a675922768c068366a0ce9346845` | 65734 | 〃 |

Kolonlar (ölçüldü): `timestamp, open, high, low, close, volume`. Span-ölçümü: `pd.read_feather` ilk/son `timestamp` (6-sembol-birebir-aynı-sınır → matris-karşılaştırmasında-zaman-ekseni-tek).

## 2. Upstream-donuk-zincir — 6×5m + 6×1m feather

| File | SHA256 | Rows |
|---|---|---|
| AUDUSD_5m | `6bfe92571aa9afaede97e02d88dde5e7ae96e16f8a07f76cb629314f016911dc` | 196130 |
| EURUSD_5m | `e214cc8210749d958cfcda9e28ad14307d25df9e103d0cb57456b9711afd6fa4` | 196574 |
| GBPJPY_5m | `9572ffa3ca77a2e16bb32055567e6197a8be16343f5a4611b8b074ab35270f04` | 196877 |
| GBPUSD_5m | `a451e520001f5105056ccaf25e0e261626dc63d1b998e632782ca3a1907c5c40` | 196371 |
| USDCAD_5m | `3e41d705f4c730304061cfe340dc59f5c972267e84b7f47d36b52e3f6e05d3f6` | 195932 |
| USDJPY_5m | `2c941da24635bb3e5e460e0e8ca1b8afb9fdd495f9c07cf080d9a924b1c20481` | 196280 |
| AUDUSD_1m | `990567a1bc2b4b630e02439956be60c218c5e5398ce253287b12f36f513c13ad` | 977147 |
| EURUSD_1m | `628914e5a6df416e44062f24fd22dd269fd7ea53e18ac4fbcab9f405e9ea71ae` | 979793 |
| GBPJPY_1m | `253110e7a18f1d48387710caf2d4542d993a30138389c1e700632320a417a143` | 983232 |
| GBPUSD_1m | `e3e378325255f6f4e03091c760b56b297987c575a236749bbf8617e7c48916c6` | 979994 |
| USDCAD_1m | `09a092e7724ae8ea591e0818741a5c545d55e266cf72bee2ac9b41f08bd68d7b` | 977080 |
| USDJPY_1m | `6b99692578e7d9cb0b684a6b0037aeb43e4f1293a967a0bdf8f35cd940440bc9` | 979389 |

## 3. Upstream-RAW — 6×minute CSV (`data/icmarket_raw/`)

| File | SHA256 | Bytes |
|---|---|---|
| AUDUSD_Minute_2024_2026_RAW.csv | `8ddb08b1df4334f2bb2a32ab72d128402effff266e78e3e5d68bbe4ccdcd78e4` | 54,387,794 |
| EURUSD_Minute_2024_2026_RAW.csv | `f326d79ac0b5d3a36eed8506bfc6bcc457bb53ebed59ed95a14cae9a9e9d650a` | 54,593,302 |
| GBPJPY_Minute_2024_2026_RAW.csv | `f6f71545514940f449c135981321885db9c1a3cf8f5d6232e857b87c0b13f9f6` | 55,338,547 |
| GBPUSD_Minute_2024_2026_RAW.csv | `2f0f49154a58e6ad5119cbf2cd5fcd8c42a17b7b7dcca6a32dda20dcbc907f9e6` | 54,741,638 |
| USDCAD_Minute_2024_2026_RAW.csv | `c3a50e3b44f619ab6232799a47fde2d839854d4aed696f3805ffe131250a2fcf` | 54,452,275 |
| USDJPY_Minute_2024_2026_RAW.csv | `7b542f34687ac92a397c003d08dc32eeff293078371c24c2c847c3e2482fa467` | 54,817,370 |

## 4. Doğrulama-protokolü (koşum-ÖNCESİ-ZORUNLU)

```bash
sha256sum data/icmarket_feather/*.feather data/icmarket_raw/*.csv
  → 24-hash'i bu-dosyanın-§1-3-tablolarıyla (veya manifest'le) tam-64-hane-diff'le
  → HERHANGİ-bir-uyuşmazlık = dataset-drift = koşum-KARŞILAŞTIRILAMAZ = STOP
```
Satır-sayısı-yöntemi: `pyarrow.feather.read_table(path) → len()` (tablo-satır-üstü-değerler-bununla-ölçüldü).

## 5. FAZ-A-koşum-notları

- **Motor-yolu:** `experiment/main_research_c_v1_1.py` (no-args = FULL 2.7Y/6-major; `SIX_MAJORS :780`; feather-doğrudan-`DATA_DIR`/feather-üzerinden-okunur) — **`copy_rates`/MT5-çağrısı-YOK.**
- **WinError-zorluğu-yok (beyan):** WinError-5 / WRITE_BLOCK ailesi **canlı-yazım-patikası** sorundur (D80/D81: `_atomic_write_text`-üç-kopya, audit/state-yazımları). FAZ-A-patikası **salt-okunur-offline-feather-okumasıdır** → bu-sorun-sınıfı-buraya-geçerlilik-alanı-yoktur. Kalan-tekal-failure-mode: (a) hash-uyuşmazlığı → STOP, (b) pyarrow/pandas-eksikliği → env-kurulumu.
- **Çıktı-disiplini:** koşum-araçları `%TEMP%`; sonuç-artifact'ları-repo'ya-dosya-olarak-yazılır (untracked); **V0..V5-tanımları pinlenmeden-koşum-yapılmaz** (handoff-§1-pending-pin-işareti).
