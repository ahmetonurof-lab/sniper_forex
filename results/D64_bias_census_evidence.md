# D64 — CBDR BIAS-GÜN CENSUS'U (FAZ-A) — EVIDENCE FILE

> **Statü:** PRE-REGISTERED (§0 sayımdan ÖNCE yazıldı) · **read-only** · untracked · kod-artefaktı-değişmedi · Reis-sinyalinde-bu-dosya-da-donlar
> **Üretici:** Cline · **Ölçüm saati:** 2026-09-03 11:0x +03:00
> **SINIR:** Bu dosya **hiçbir canlı-edge iddiası taşımaz.** İçerideki hiçbir sayı trade-edilebilir bir kenar olarak okunamaz (§8.1 etiket zorunluluğu).

---

## §0. PRE-REGISTRATION (sayımdan önce, bağlayıcı)

### 0.1 Provenance-beyanı (dürüstlük payı)
FAZ-A/D64 mandatası `memory-bank/progress.md` içinde **hiçbir satırda geçmiyor** (`grep -c 'FAZ-A|D64|bias-gün|census' = 0`, ölçüldü) — yani mandat **yalnız-chat-taşıyıcılı**. Bu dosya o izi kapatmak için yazıldı ve **mandatın-bu-yorumla-ifa-edildiğini** açıkça beyan eder: Hakem yorumu farklıysa §0.4–§0.6 yeniden-yazılabilir, **§0.2–§0.3 (girdi-mühürleri ve tanım) değişmez.**

### 0.2 Donmuş girdiler (pin'lenmiş)
Dataset: `data/icmarket_feather/` · 6 sembol · 1m feather · sha256 önekleri (`[yöntem: sha256sum <worktree-yol>]`):

| dosya | sha256(16) |
|---|---|
| `AUDUSD_1m.feather` | `990567a1bc2b4b63` |
| `EURUSD_1m.feather` | `628914e5a6df416e` |
| `GBPJPY_1m.feather` | `253110e7a18f1d48` |
| `GBPUSD_1m.feather` | `e3e378325255f6f4` |
| `USDCAD_1m.feather` | `09a092e7724ae8ea` |
| `USDJPY_1m.feather` | `6b99692578e7d9cb` |

EURUSD-örnek-lem: 979,793 satır · `2024-01-01 22:01` → `2026-08-21 20:56` · `timestamp` dtype `datetime64[ns]` (**naive**).

### 0.3 Zaman-tabanı (SEÇİM değil, ölçülen-özellik)
`DataLoader` docstring'i: *"Timestamps normalized to UTC (as-is from MT5)"* — kendi-içinde-çelişkili; `experiment/config.py:30` pencereyi **"MT5 server time"** der; `exp4b_oos.py:25` veriyi **"UTC"** der. Ampirik-ölçüm (bu-dosya-içi, 3 sembol):

- Günlük açılış-saati modu = **0**, kapanış-saati modu = **23** — her-ayda-sabit (12/12 ay).
- Hafta-sonu kapanışı: **92 gün saat 20 · 50 gün saat 21 · 684 gün saat 23** (üç sembolde-birebir aynı sayılar).

**Kayıt-kararı:** census **tabanı yeniden-yazmaz**; kanonik-makinenin-yaptığını yapar — feather-etiketleri ham-hâliyle `in_window()`/`cbdr_day_key()`'e gider. Yani sonuçlar **hangi-saat-olursa-olsun o-saat-te-durur**; taban-sorusu ③-değerlendirmesine (CBDR time-semantic) havale, burada **doküman-çelişkisi-olarak-tepitlenmiştir**.

### 0.4 Kanonik-yeniden-kullanım (yeniden-yazma YOK — §2.2)
| bileşen | kaynak |
|---|---|
| `SessionManager` (pencere, `cbdr_day_key`, `track_body`, `check_sweep`, `_confirm_sweep`, `update`) | `src/strategy/session.py:16–215` |
| `Bar`, `CBDRState`, `Direction` | `src/strategy/models.py:15–92` |
| `resample_15m`, `compute_atr` | `experiment/main_research_c_v1_0.py:118–164` (**import edildi**, kopyalanmadı) |
| `DataLoader` | `src/strategy/data_loader.py:17` |
| `SESSION_START_HOUR=19`, `SESSION_END_HOUR=1`, `ATR_PERIOD=14` | `experiment/config.py:12,30,31` (runtime-doğrulandı) |
| Sürücü parametreleri `warmup=min(100,n−10)`, `start_idx=warmup+1`, `sweep_atr_tolerance_mult=0.5`, `sweep_default_tolerance=10.0` | `main_research_c_v1_0.py:193–205` |

**Kanónica-dair-ölçülmüş-olgu (tanımın-parçası):** `session.atr` kurucuda-bir-kez-set-edilir, sürücü-döngüsünde **hiç güncellenmez** (`grep -n 'session\.atr' main_research_c_v1_0.py` → **0 eşleşme**; döngü-yalnız-yerel-`atr_val`'i-Wilder-günceller, satır 231). Sonuç: **süpürme-toleransı tüm-2.6-yıl-boyunca-warmup-ATR'sinde-donmuştur.** Census bu donmuş-toleransı kullanır — çünkü kanonik-makine onu kullanır.

### 0.5 BIAS-GÜN TANIMI (pin'lenmiş — tanımsız-sayım-yasak)
Bir **(sembol, D)** çifti için:

1. **D** = `cbdr_day_key(ts)` — spans-midnight penceresinde akşam-parçası (h≥19) → **bir-sonraki-tarih**, sabah-parçası (h<1) → aynı-tarih. Yani **D, CBDR penceresinin BİTTİĞİ takvim günüdür.**
2. **Gözlemlenebilir-gün:** `cbdr_day_key == D` olan **en-az-bir** bar `index ≥ start_idx`'te işlenir **ve** o-bar pencere-dışındadır (sweep-kontrolü-yalnız-dışarıda-çalışır, `session.py:200–213`). Aksi → `pre_warmup` veya `window_only` olarak **ayı-ca-sayılır, payda-yazılmaz.**
3. **Bias-kurulmuş(D):** kanonik `SessionManager`, D-çevrimi `reset_for_new_cycle()` ile sıfırlanmadan **önce** `cbdr.bias_locked == True` raporluyorsa; yön = `cbdr.daily_bias ∈ {BULLISH, BEARISH}`.
4. **NEUTRAL(D):** gözlemlenebilir ve kurulmamış.
5. **İlk-sweep-kazanır:** `bias_locked` koruması nedeniyle **gün-başına-en-fazla-bir-bias** (`session.py:114–115`).
6. **Tolerans** = `0.5 × ATR14(warmup)` — sembol-bazında-sabit (§0.4), ölçülüp-yazılacak.

### 0.6 Önceden-kayıtlı-istatistikler (sayıldıktan-sonra-eklenmez)
- **(A) Census (6 sembol):** gözlemlenebilir-gün, kurulmuş, **bias-oranı**, BULL/BEAR dağılımı, `pre_warmup`/`window_only` redleri, lock→sweep bar-sayısı medyanı.
- **(B) Artımsal-kazanç (EURUSD-bazlı):** bias-kurulum-bar'ından çevrim-reset'ine-kadar **işaret-ölçekli-drift**, birim = donmuş-tolerans; karşılaştırma = **koşulsuz-aynı-saat-eşleşikli-baz-çizgi**. **Trade-edilemez-statistik** (giriş/SL/TP/fee/kayma YOK) → **canlı-edge-iddiası-değil.**
- **(C) Sembol-bazlı-funnel-öngörüsü:** (A)'nın bias-takvimi, kanonik funnel'in gün-payını **önceden-tahmin eder**; tahmin, D62/SRI-001 artefaktının gerçek-gün-sayılarıyla **karşılaştırılıp-yaş-ıslak-yazılır** — yeni-trade-koşusu-değil.

### 0.7 Gözlemlenen-defect (dokunuş-yok, backlog)
`DataLoader.list_symbols()` (`data_loader.py:44–46`) `*.feather` glob'layıp **yalnız `_1m` çıkarır**; çok-TF'li-bir-dizinde `AUDUSD_15m` gibi-sahte-semboller-üretir → `load()` `FileNotFoundError` (bu-oturumda-ölçüldü). Census **açık-sembol-listesi** kullanır; defect **gizlenmez, backlog'a-yazılır.**

### 0.8 Boundary
Read-only · `src/`, `experiment/`, `tests/`, `tools/`, `index.json` **değişmedi** · push YOK · geçici-koşum-script'i `%TEMP%` içinde (repoya-yazılmaz) · bülten `ad3fa87b` **0-yazar-donması-sürüyor**.

---


## §1. SONUÇ (A) — BIAS-GÜN CENSUS'U

Koşum-biçimi: kanonik `SessionManager` sürücüsü, `main_research_c_v1_0.run_test_a` parametreleriyle (§0.4), 15m, `start_idx = warmup+1`. Gün-anahtarı = `cbdr_day_key`.

| sembol | 15m-bar | `days_total` | **gözlemlenebilir** | **kurulmuş** | NEUTRAL | BULL | BEAR | **bias-oranı** | tol (donmuş) | lag-medyan | lag-p90 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| AUDUSD | 65,732 | 826 | 684 | 567 | 117 | 265 | 302 | **82.89 %** | 0.00020714 | 8 | 48 |
| EURUSD | 65,740 | 826 | 684 | 607 | 77 | 259 | 348 | **88.74 %** | 0.00018893 | 15 | 40 |
| GBPJPY | 65,741 | 826 | 684 | 565 | 119 | 272 | 293 | **82.60 %** | 0.04903571 | 13 | 41 |
| GBPUSD | 65,730 | 826 | 684 | 573 | 111 | 259 | 314 | **83.77 %** | 0.00026571 | 21 | 45 |
| USDCAD | 65,716 | 826 | 684 | 544 | 140 | 245 | 299 | **79.53 %** | 0.00028893 | 28 | 53 |
| USDJPY | 65,734 | 826 | 684 | 545 | 139 | 275 | 270 | **79.68 %** | 0.03892857 | 7 | 46 |
| **AGG** | — | 4,956 | **4,104** | **3,401** | 703 | 1,575 | 1,826 | **82.87 %** | — | — | — |

Kapsam: gün-anahtarları `2024-01-03 → 2026-08-22` (altı sembolde aynı-takvim).

**İç-tutarlılık-teyitleri (önceden-kayıtlı-olmayan, sonradan-çıkan-iki-üst-üstelik):**
1. `days_total − observable = 826 − 684 = **142**` = §0.3'te-bağımsız-ölçülen-hafta-sonu-kapanış-günleri (**92 + 50 = 142**). Yani payda-düşüşü tanımı-veri-yapısıyla-birebir-kapanıyor — keyfi-eleme-değil.
2. BULL+BEAR = 1,575 + 1,826 = **3,401 = kurulmuş-toplam** ✓ (gün-başına-tek-bias, §0.5/5).
3. **BEAR-ağırlığı 6/6 sembolda** (1,826 / 3,401 = **%53.7**) — tanım-formu simetrik olduğu-için bu bir veri/semantik-sinyalidir, tanım-artefaktı-değil; **nedeni bu-census'un kapsamı dışında** (③-zaman-semantic-probesu ile ortak şüpheli).

## §2. SONUÇ (B) — ARTIMSAL KAZANÇ (EURUSD-bazlı, **trade-edilemez**)

Aralık = bias-kurulum-bar'ı → çevrim-reset-bar'ı; birim = donmuş-tolerans (0.00018893); n = 607 kurulmuş-gün.

| kural | mean | median | hit-rate |
|---|---|---|---|
| **bias-yönlü** (işaret = `daily_bias`) | **+0.8593** | +1.4820 | 52.22 % |
| always-long (aynı aralıklar, +1) | −0.3022 | −1.7996 | 46.29 % |
| always-short (aynı aralıklar, −1) | +0.3022 | +1.7996 | 53.71 % |
| NEUTRAL-gün referansı (n=77, `fout`→reset) | +2.6087 | — | mean\|x\| = **20.9280** |

**Okuma (abartısız):** bias-yönlü ortalama, en-iyi-sabit-yönlü-baz-çizgiyi **0.5571 tol/gün** geçiyor — yani bias, "hep-short" gibi sabit bir kurala-göre bilgi-taşıyor. ANCAK (i) hit-rate %52.2 ile yazı-turaya çok-yakın, (ii) aralık-gürültüsü (mean|·| ≈ **20.9 tol**) sinyalin **~24 katı**, (iii) median > mean → dağılım negatif-kuyruklu. **Sonuç: pozitif-fark, küçük-etki, yüksek-varyans.** **Canlı-edge-iddiası YOK** — giriş/SL/TP/fee/kayma yok; yalnızca bias-günlerinin yön-ölçekli drift'idir.

**Sınırlar (önceden-kayıtlı-forma bağlı kalma):** (a) aralık-uzunluğu günden-güne değişir, **bar-bazında normalize edilmedi**; (b) NEUTRAL-referansı uzun-aralıklı olduğu için tabloyla **doğrudan karşılaştırılamaz**, yalnız ölçek-hatırlatmasıdır; (c) reset-anı hafta-sonu-boşluğuna düşebilir → takvim-bazlı atlama.

## §3. SONUÇ (C) — SEMBOL-BAZLI FUNNEL ÖNGÖRÜSÜ + PARİTE-TEYİTLERİ

Öngörü: census-bias-oranı, kanonik funnel'in fiilen iz-üreten günlerinin bias-taşıma oranını tahmin eder mi? Join-anahtarı: artefakt `traces[].cycle_day` ↔ census gün-anahtarı.

| sembol | artefakt iz-günü | bias-kurulmuş | **artefakt-oranı** | **census-oranı (§1)** | Δ |
|---|---|---|---|---|---|
| AUDUSD | 678 | 565 | 83.33 % | 82.89 % | +0.44 pp |
| EURUSD | 679 | 605 | 89.10 % | 88.74 % | +0.36 pp |
| GBPJPY | 675 | 559 | 82.81 % | 82.60 % | +0.21 pp |
| GBPUSD | 681 | 573 | 84.14 % | 83.77 % | +0.37 pp |
| USDCAD | 675 | 541 | 80.15 % | 79.53 % | +0.62 pp |
| USDJPY | 678 | 543 | 80.09 % | 79.68 % | +0.41 pp |
| **AGG** | **4,066** | **3,386** | **83.28 %** | **82.87 %** | **+0.41 pp** |

**Öngörü-doğrulandı:** 6/6 sembolda **≤0.62 pp** ayrışma; küçük pozitif sapma-tutalı (iz-üreten günler, bias-kurulma olasılığı biraz daha yüksek günler).

### 3.1 Bağımsız-parite-teyitleri (census-makinesi ↔ üretim-artefaktı)
| teyit | sonuç | kanıt-seviyesi |
|---|---|---|
| **CBDR gövde-paritesi** — `traces[].body_high` ↔ yeniden-yürütülen `cbdr.body_high` | **2,400 / 2,400** (6 sembol × 400 örnek, bağıl-hata ≤1e-9) | üretim-artefaktı karşı-doğrulaması |
| **Tolerans-paritesi** — `traces[].tolerance` ↔ `0.5 × ATR14(warmup)` | **6/6 sembolde tek-değer, ≤1.6e-5 bağıl** | üretim-artefaktı kendi alanı |
| **Donmuş-tolerans-iddiası** (§0.4) | artefakt `tolerance_source` = *"0.5 \* session.atr (engine-parity: run\_test_a **kurulum-ATR**)"* — 2.6 yıl boyunca **tek-değer** | **statik-çıkarım (svy-6) → artefakt-provenance (svy-2/3) ile teyitli** |
| `master_bias` (kanonik kol, 407/407 EURUSD) | **boş-string** — bias hesaplanıyor ama **trade-defterine yazılmıyor** | kayıt-eksisikliği (owner-paketi-notu) |

## §4. KAPANIŞ · SINIR · KALAN

- **(1).hedef-sayı kapandı:** bias-gün kapsama-oranı = **%82.87 (census) / %83.28 (artefakt-iz-günleri)**, altı sembol, 2.6 yıl, 4,104 gözlemlenebilir gün. FAZ-B pre-reg'ı bu sayıyı **girdi** olarak alır.
- **Boundary-uyuldu:** hiçbir kod-artefaktı değişmedi (`src/`, `experiment/`, `tests/`, `tools/`, `index.json` temiz); koşum-scriptleri `%TEMP%` içinde; push YOK; D62 bülteni **0-yazar-donması sürüyor**.
- **Bu dosyanın kendi mührü ayrıca ölçülecek** (belge-kendi-kendini-pin'leyemez → devir-mührü-protokolü: bir sonraki girdiye emanet).
- **Kalanlar:** (i) BEAR-ağırlığının kaynağı ③-zaman-semantic-değerlendirmesiyle ortak soru; (ii) `master_bias` boş-string'i → owner-paketi "neden-açılmamalı" girdisi; (iii) `DataLoader.list_symbols()` çok-TF-defect'i (§0.7); (iv) bar-bazlı-normalize-drift ve per-bar baz-çizgi **FAZ-B pre-reg'ında tanımlanmalı** (şimdi yapılmadı — tanım sonradan değiştirilmez).

## §5. DÜZELTME-VE-YÜKSELTMELER (Hakem-elinden; Seçenek-A-sonrası; §12.1 — önceki-sayılar-yukarıda-silinmeden-duruyor)

**§5.1 BEAR-dominans düzeltmesi:** §1.8-3'teki "6/6" YANLIŞ → **5/6**. USDJPY 275 BULL / 270 BEAR = %49.54 BEAR-payı (hafif-BULL) — tablo-kendi-cümleyi-çürütüyordu. AGG %53.69 aynen. Diferansiyel-teşhis: skew-6/6-olsaydı sistem-artefaktı-hipotezi-kesinleşirdi; USDJPY-nötrlüğü saf-sistematik hipotezini ZAYIFLATIR, sembol-bazlı-veri/semantik bileşenini GÜÇLENDİRİR (③-girdisi; §7-②-IN_WINDOW-anomalisiyle-ortak-şüpheli).

**§5.2 Parite-nüfus yükseltmesi:** §3.1'deki 2,400/2,400 örneklem (trk[:400]) → **tam-nüfus 4,066/4,066, UYUŞMAZLIK=0 (≤1e-9)**; artefakt gün-başına-tek-trace üretir (tekrar=0) → iddia örneklem-seviyesinden-nüfus-seviyesine-yükseldi.

**§5.3 142-düşüşü tarih-düzeyi:** 826−684=142 = **138 Cumartesi + 4 tatil-anahtarı** (2024-12-25, 2025-01-01, 2025-12-25, 2026-01-01); saat-partisyonu=anahtar-partisyonu birebir (92@20+50@21+684@23=826); takvim 963−826=**137 Pazar**; warmup-maliyeti=tam-1-gün (ilk-anahtar 2024-01-02 hiç-doğmaz).

**§5.4 Gözlem-frekansı çarpanı (türev-etiketli):** kurulmuş-gün/takvim-günü = 3401/684 = **4.97** ↔ EURUSD-tek 0.887 → **5.6×**. Etiket (D65-mühürlü): **gözlem-bütçesi-türevi; fırsat/edge-çarpanı DEĞİL**; bias→trade-dönüşümü SINIF-2'de-açık.

**§5.5 Sınıf-etiketi:** bu-dosyanın-her-sayısı **SINIF-1**; canlı-pencere-ham-bar-arşivi (SINIF-2-fikstür-adayı) ayrı-artifact'tır, kendisi-eşdeğerlik-kanıtı-değildir.

*(§0.2–§0.3 pre-reg çekirdeği-değişmez — §0.1-bağlılık-korundu.)*
