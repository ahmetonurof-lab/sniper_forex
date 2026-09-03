# D79 — 65k PARİTE KANIT DOSYASI (Aşama-5 / §1.6 kapısı kapandı)

**Tarih:** 2026-09-03 20:53–20:56 local (sistem-saati ölçümü) · **İcra:** Cline · **HEAD:** `0081c64` (kod DOKUNULMADI) · push YOK
**Yetki:** Hakem K3-KAPANIŞ hükmü §5 — *"65k-PARİTE: YETKİ-AÇIK, SIRA-MÜHÜRLÜ"*; ön-şart **protokol-kimliği-teyidi → koşum**
**Ön-şart-zinciri:** D77-preserve (`20:31:18`, manifest'li) → harness-teyidi → koşum. **Üçü-de ölçülü.**

## 0. Protokol kimliği — "65k" script DEĞİL, PARAMETREDİR

Kaynak-hakem `results/D66_sweep_detection.md` §1.6 (`:113`): *"`SNIPER_WARMUP_COUNT` default **65000**, benim çekimim **60000** → offline-tarama, boot'tan-okunan `session_atr` ile 65000-çekimde YENİDEN-koşulmadan hiçbir band/bias/sweep satırına 'parity' denmez."*

| Öğe | Değer | Kanıt-seviyesi |
|---|---|---|
| Harness | `%TEMP%\d66_detect.py` (3758 B @ 13:57) | §1.9 beyanı + `ls` — **repo-dışı, kod-artefaktı-değil** |
| Tek-değişken | `:17 copy_rates_from_pos(…, 0, 60000)` → `65000` | **diff = yalnız 2 satır** (`:17` sayı · `:64` çıktı-yolu) |
| Parametre-kökeni | `src/live/run_production.py:80` `_env_int("SNIPER_WARMUP_COUNT", 65000)` | **kaynak-inspeksiyonu** (seviye-2) · `.env`'de YOK ⇒ canlı default 65000 |
| Baseline | `d66_detect_60000_baseline.json` (118827 B, mtime 13:58 korunmuş) | orijinal-çıktı **ezilmedi** |
| **REDDEDİLDİ** | `scripts/verify_phase11_parity_fix.py` | 38↔38 **trade-count** parity @15m; `65000`/`body_high`/`tol` **yok** → **başka-parite**. Kör-koşum-§8.1-ihlali **önlendi** |

**Aritmetik-teyit:** `0.5 × 0.0004935714285714741 = 0.00024678571428573705` ✓ (bağımsız-hesap, Hakem-§5 ile uyumlu).

## 1. BAŞSONUÇ — §1.6 PARİTE **KAPANDI** (canlı ölçek 65000'dir, ölçüldü)

| Metrik | 60000-çekim | **65000-çekim** | **CANLI (K3 close-save / T0#8)** | Δ 65k↔canlı |
|---|---|---|---|---|
| EURUSD 15m bar sayısı | 4005 | **4338** | **4338** (`next_idx`, audit satır-3) | **0 — BİREBİR** ✅ |
| EURUSD warmup-ATR | 0.000664 | 0.000489 | **0.0004935714285714741** | **+0.94 %** |
| EURUSD donmuş-tol | 0.000332 | 0.000244 | **0.00024678571428573705** | **+1.13 %** |
| Δ canlıya-göre | **+34.5 %** ← 60k | **+1.1 %** ← 65k | — | — |

**HÜKÜM:** Canlı motorun warmup-ölçeği **65000 M1'dir ve yalnız 65000-çekim bunu üretir** — bar-sayısı **birebir**, donmuş-tolerans **%1.1**. 60000-çekim **%34.5 sapar.** §1.6'nın yirmi-satırlık uyarısı artık **varsayım değil, ölçülmüş-olgudur.**

**%1.1'lik-kalan-fark İKİ bağımsız-nedenle AÇIKLANIR (gizlenmez):**
1. **Pencere-kayması:** 65k-çekim penceresi server `2026-09-03 20:45`'te biter (`last` alanı UTC 17:45 + 3 s); K3-boot penceresi `~19:17` server'da biter ⇒ **~1.5 s = ~6×15m bar** ileri-kayma. `copy_rates_from_pos(…,0,N)` **şimdi**-sonlu-pencere çeker; sabitlemek harness'i tek-değişken-olmaktan çıkarırdı.
2. **Interpreter-sürüklemesi:** canlı-ATR **`.venv`**-boot'undan (11476), offline-koşum **base-python**. Wilder-ATR düz float-aritmetiğidir; etki ihmal-edilebilir **AMA ölçülmeden iddia edilmez** — bu yüzden fark **sıfıra zorlanmadı.**

**SINIR (dürüstlük):** Birebir-eşitlik **bu-harness'la üretilemez** (pencere-kayması yapısal). Elde edilen **ölçek-paritesi**dir (bar-sayısı birebir + ATR %1.1), **bit-parity** değil. Bit-parity isteyen, `copy_rates_from` ile-sabit-bitış-epoğu veren **ayrı-pre-reg'li** harness ister.


## 2. ⚠️ KARAR-IŞI AYRIŞMA — §1.6'nın duyurusu **GERÇEK ÇIKTI**

60k → 65k geçişi **yalnız sayıları değil, motorun KARARLARINI değiştiriyor:**

| sembol | ATR 60k → 65k | tol 60k → 65k | sweep 60k → 65k | **bias 60k → 65k** |
|---|---|---|---|---|
| EURUSD | 0.000664 → 0.000489 | 0.000332 → 0.000244 | 1 → 1 | NEUTRAL → NEUTRAL |
| USDJPY | 0.061000 → 0.050000 | 0.030500 → 0.025000 | 0 → 0 | NEUTRAL → NEUTRAL |
| **GBPUSD** | 0.000883 → 0.000585 | 0.000441 → 0.000292 | **1 → 0** ⚠️ | NEUTRAL → NEUTRAL |
| **AUDUSD** | 0.000550 → 0.000279 | 0.000275 → 0.000139 | 1 → 1 | **BEARISH → BULLISH** 🔴 |
| USDCAD | 0.000681 → 0.000506 | 0.000340 → 0.000253 | 1 → 1 | NEUTRAL → NEUTRAL |
| GBPJPY | 0.106000 → 0.076571 | 0.053000 → 0.038286 | 0 → 0 | NEUTRAL → NEUTRAL |

### 2.1 AUDUSD — **YÖN TERSİNE DÖNDÜ** (§1.8-5 FALSİFİYE)

`D66_sweep_detection.md` §1.8-5 (SINIF-1 öngörü): *"AUDUSD tek kilitli-bias adayı (**BEARISH**, +0.75 pip marj)."*
**Ölçüm (65k, canlı-ölçek): bias = BULLISH, `locked=True`, body `[0.71712, 0.71635]` — body DEĞİŞMEDİ, yalnız tol yarıya düştü (0.000275 → 0.000139).**

⇒ **Aynı-body + daha-küçük-tol ⇒ sweep eşiği daha-zor-aşılır ⇒ biriken-wick-yorumu ters yöne kaydı.** §1.6 tam-bunu uyarmıştı (*"AUDUSD(+0.75) satırı bu-düzeltmeye-duyarlıdır"*). **Marj +0.75 pip iken tol-Δ = −0.000136 = −1.36 pip ⇒ işaret-değişimi matematiksel olarak ZORUNLUYDU; 60k-tabanlı öngörü yanlış-yere yazılmıştı.**
**Kapsam-notu:** AUDUSD boot-kapsamı-dışı (boot EURUSD) ⇒ **canlıda-doğrulanamaz**; bu bir **offline-ölçek-düzeltmesidir**, canlı-kanıt değil. **§1.8-5'in SINIF-1 etiketi geri çekilir → SINIF-2.**

### 2.2 GBPUSD — **SWEEP OLAYI KAYBOLDU** (1 → 0)

60k'ta üretilen GBPUSD sweep'i 65k'ta **yok.** **Neden-iki:** (i) tol 0.000441 → 0.000292 küçülünce fiyat-seviyesi eşiği (`high > bh + tol`) daha-ileri hareket ister; (ii) pencere 333-bar uzayınca body-birikimi farklı `body_high` üretir. **"Sweep var/yok" düzeyinde karar-farkı — sayaç-farkı değil.**

### 2.3 EURUSD — **ROBUST** (§1.8-3 DOĞRULANDI)

| Alan | 60k | 65k | Hüküm |
|---|---|---|---|
| `body_high` / `body_low` | 1.15895 / 1.15827 | **1.15895 / 1.15827** | **BİREBİR** ✅ |
| bias / locked | NEUTRAL / False | **NEUTRAL / False** | **BİREBİR** ✅ |
| `day_key` | 2026-09-03 | **2026-09-03** | BİREBİR ✅ |
| `start_idx` | 101 | 101 | BİREBİR ✅ |
| sweep olayı | `09-02 16:15 bullish sweep=1.1578 ref=1.15833` | **aynı-event, aynı-ref, aynı-sweep** | **ROBUST** ✅ |
| sweep `tol` alanı | 0.00033214285714286814 | 0.0002442857142857207 | **tol-farkı kayıt-alanına TAŞINIR** |

**§1.8-3 öngörüsü** (*"Day-key 2026-09-03 EURUSD bias'ı NEUTRAL/unlocked, body [1.15827, 1.15895] — tol-düzeltmesiyle-yeniden-doğrulanacak"*) → **yeniden-doğrulandı ✅.** Buna karşılık §1.6'nın *"EURUSD(+1.98) duyarlıdır"* uyarısı **yanlış-çıktı: EURUSD satırı ölçek-değişimine dayanıklı.** ⇒ **Duyarlılık sembol-bazlıdır, evrensel-değil.**

### 2.4 Near-miss enstrümanı (§1.7) — kapsam-genişlemesi, karar-değil

| sembol | near L 60k → 65k | near P 60k → 65k |
|---|---|---|
| EURUSD | 52 → **81** | 36 → **64** |
| AUDUSD | 8 → **9** | 7 → 7 |
| USDCAD | 57 → **86** | 4 → 4 |

**Neden-iki:** (i) pencere 4005 → 4338 bar (**+333 = +%8.3 kapsam**); (ii) tol küçülünce daha-çok-bar "fiyat-seviyesi-tutar-ama-kapanış-tutmaz" kümesine girer. **§1.7 kafondans-uyarısı ayakta:** sayaç `bias_locked` iken susar → AUDUSD'ün-düşük-sayısı (9) kilitten-gelir, sakinlikten-değil. **Bu alan teşhis-amaçlıdır, motor-kararı-değildir.**

## 3. YAN-BULGU · D79-b — `safe_reasons` payload-bozulması (deterministik, P2)

T0#8 audit satır-5: `safe_reasons: ["safe_mode_persisted: safe_mode_persisted: safe_mode_persisted: expected_login_unset; expected_login_unset; expected_login_unset", "expected_login_unset"]`
K3 stdout (19:17 boot): `startup SAFE_START: safe_mode_persisted: safe_mode_persisted: safe_mode_persisted: expected_login_unset; expected_login_unset; expected_login_unset; expected_login_unset`

**İki-farklı-boot · iki-farklı-interpreter · aynı-bozulma ⇒ RACE DEĞİL, deterministik-kod-hatası.** Neden-listesi her-tekrar-değerlendirmede kendini üstüne-ekleyerek büyüyor (3× / 4×). **Etki:** teşhis-okunabilirliği (neden-kaç-tane?), otomatik-sınıflandırma, Channel-C-parsing. **Trading-güvenliği ETKİSİ YOK** (gate doğru kapalı). **→ N2 #21-kapsam-adayı (madde-7):** *neden-listesi küme-kimliği ile tutulmalı, dize-yığını ile değil.*

## 4. YAN-BULGU · D79-c — T0#8 tek-süreç-dayanıklılığı (kök-neden deneyi, ÖN-SONUÇ)

Hakem-§5 "Seçenek-(2)" deneyi **istem-dışı önce-koştu** (bkz. `progress.md` T0#8 öz-düzeltmesi):

| | K3-boot (11476) | **T0#8-boot (11468)** |
|---|---|---|
| Interpreter | `.venv` launcher → base child | **base python, TEK süreç** |
| Süreç-topolojisi | **ÇİFT** | **TEK** (`Get-CimInstance` = 1) |
| Boot → ilk WRITE_BLOCK | `19:28:27` = **+11 dk 14 sn** | **YOK** |
| Uptime @ ölçüm 21:01 | 33 dk (ölü) | **29 dk 17 sn (CANLİ)** |
| WRITE_BLOCK sayımı | 5 + fatal WinError 5 | **0** |
| `audit.jsonl` mtime | dondu | **her-flush'ta tazele (20:51→20:58)** — tmp+`os.replace` **BAŞARILI** |

**Ön-okuma:** Önceki-boot **22 dk 8 sn**'de patladı; T0#8 **29 dk'yı WB=0 ile geçti** ve **aynı-audit-yolunu (tmp+rename) başarıyla koşmaya devam ediyor.** ⇒ **Çift-süreç-kalıcı-iç-çekişmesi hipotezi daha-da zayıfladı; H1/H2 (dalga / belirli-handle-çakışması) güçlendi.** **HÜKÜM İÇİN ERKEN:** hedef-pencere ≥60 dk; **patlama hiç-gelmeyebilir de** — ki bu "venv-launcher-launch-bağımlı" okumasını tek-başına destekler. **Erken-zafer-ilan-edilmiyor; izleme sürüyor.**

## 5. Aşama-5 COMPARISON — etiket-hükmü

**SINIF-2 olarak mühürlü** (offline-harness + pencere-kayması + interpreter-farkı; canlı-üretim-yolu DEĞİL). **Ama §1.6 kapısını KAPATIR:** bundan böyle hiçbir D66 band/bias/sweep satırına "60k-değeriyle parity" denemez; **geçerli-temel = 65k-çekim.**

## 6. ETKİLENEN DOSYALAR — D66-§3 "BEKLİYOR" satırları DOLDU

| D66 satırı | Eski-durum | Yeni-durum |
|---|---|---|
| `:54` #4-pencere server 22:00→04:00 body-formasyonu (W2) | **BEKLİYOR** | **ALINAMADI** — W2 skip edildi (Reis-scheduling); FAZ-B'ye ertelendi. **SINIF-2 verisi bugün üretilemedi** |
| `:55` body_high/body_low/tol sayısal-paritesi | **BEKLİYOR** | **ÖLÇÜLDÜ ✅** → bu-dosya §1/§2.3 |

## 7. Pinler (bu turda üretilen)

| Dosya | Rol |
|---|---|
| `results/D79_65k_parity_evidence.md` | bu-dosya |
| `%TEMP%\d66_detect_65000.py` (3764 B @ 20:53) | tek-değişken-harness |
| `%TEMP%\d66_detect_65000.json` (168196 B @ 20:56) | ham-tarama-çıktısı |
| `%TEMP%\d66_detect_65000.out` | koşum-stdout (6 satır + DONE) |
| `%TEMP%\d66_detect_60000_baseline.json` (118827 B, mtime 13:58 korunmuş) | **korunan-baseline** |
| `%TEMP%\d66_detect_60000.py` (3758 B @ 13:57) | orijinal-harness kopyası |
| `%TEMP%\d78_parity_cmp.py` / `d78_live_atr.py` | karşılaştırma-araçları (repo-dışı) |
| `state/D77_preserve/` (6 dosya + manifest) | zincir-hafızası |

**Boundary:** `src/` `tests/` `index.json` **DOKUNULMADI** · commit/push **YOK** · `.env` **DOKUNULMADI** · `index.json` **ÜRETİLMEDİ** · `state/`-e **yalnız D77-preserve yazıldı** (additive; boot-kendi-yazıları ayrı) · T0#8 **CANLI, dokunulmuyor** · D64 `8b18f70a` **DEĞİŞMEDİ** ✓ · D74 `184a95c4` **DEĞİŞMEDİ** ✓

---

## 8. EK · HAKEM-RATİFİYESİ + AMENDMANLAR (21:28 sonrası)

### 8.1 AM-N19-11 · ETİKET-ZORUNLUĞU (bu-dosyanın-kendi-satırı)

> **"Bit-parity iddia DEĞİL — ölçek-paritesi iddia edilir."**

§1/§2'deki **%1.1-uyuşması** bu-etiketle-okunur. SINIF-1-araç artık canlı-endeksle bölüm-birleştirilebilir durumda; **ama tek-bit-iddiası hiçbir-yerde kurulmaz.**

### 8.2 BULGU-12 · duyarlılık-plakası (öne-çıkan-satır)

> **`SENSITIVITY: symbol-pinned, not-universal`**

§1.6'nın "EURUSD-duyarlıdır" uyarısı **yanlış** çıktı: EURUSD-birebir, AUDUSD-bias-flip, GBPUSD-sweep-kaybı. **FAZ-B pre-reg'ine girdi-satırı:** per-symbol-tolerans-bağımlılığı-tablosu. **§1.8-5 SINIF-1 → SINIF-2** (canlı-endekse-bağlı).

### 8.3 BULGU-13 → N2 #21 madde-7

§3'teki `safe_reasons` payload-bozulması **BULGU-13** olarak mühürlendi: deterministik-birikim, race-değil; gate-sağlığına-etki YOK, teşhis-okunabilirliği + Channel-C-parsing-etkisi VAR. Madde-7 = list-join-yeri-tespit + idempotent-normalizasyon.

### 8.4 §4 (D79-c) **İPTAL EDİLDİ — yerini D80 aldı** (§12.1: sessiz-düzeltme YOK)

§4'ün *"hüküm için erken · izleme sürüyor · WRITE_BLOCK = 0"* satırı **artık-geçersizdir**: T0#8 **21:06:48'de aynı-hata ile ÖLDÜ.** §4'ün **çift-süreç-hipotezini-zayıflattı** okuması **doğru çıktı** ve **kanıtlandı**; "erken-zafer-ilan-etmiyorum" disiplin-ise yerindeydi — **zafer ilan edilmeden önce ölüm geldi.** Güncel-hüküm: `memory-bank/progress.md` **D80-a** (üç-dallı-matris: dal-(i) FALSİFİYE · dal-(ii) KAZANDI · dal-(iii) TETİKLENMEDİ).

### 8.5 D80-c · bu-çekimin-yol-açtığı-yeni-katman

65k-çekimi `audit.py`'yi-okumayı-gerektirdi; o-okuma **`_atomic_write_text`'in ÜÇ-kopyasını** ve **K2-forensic-floor'unun yalnız-tek-kopyada-olduğunu** ortaya çıkardı (`grep -c atomic_write_exhausted` → üç-crash_log-da **0**). **P1-adli-körlük artık hipotez-değil.** Tam-kayıt: `progress.md` D80-c · **N2 #21 madde-8 adayı** (üç-kopya → circular-import'suz tek-modül; *iki-kopyaya-daha-floor-eklemek §2.2-ihlalini-korur, YANLIŞ-çözüm*).

**Boundary (bu-ek-için):** kod **DOKUNULMADI** (salt-okuma) · commit/push YOK · T0#8 **ÖLÜ**, yeniden-boot yetkisi YOK · `state/D77_preserve/` **9-dosyaya-çıktı** (ölüm-öncesi-koruma, 3-nesil-zincir).
