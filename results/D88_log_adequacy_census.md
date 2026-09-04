# D88 — LOG-YETERLİLİK-CENSUS (FAZ-1 · read-only · Kripto-standardı-karşılaştırması)

> **Durum:** CENSUS-RAPORU (Hakem-D88-charter FAZ-1: *"ne-görünüyor-ne-görünmüyor sayıya-dönsün"*) · **Yazan:** Cline · 2026-09-04
> **Yöntem-disiplini:** salt-okuma (`git diff -- src/ tests/ index.json` = BOŞ korunur) · satır-ankorlu-statik-tarama (`grep -n`) + canlı-korpus-doğrulama (Boot-C `state/audit.jsonl` 23-olay + `t10c_boot_stdout.log` 12L) · koşum-araçları-shell-gömülü (repo-dışı) · push YOK · N2 #23-adayları BURADA KODLANMAZ (FAZ-2 = Reis-onayı-sonra).
> **Hakem-çerçevesi:** üç-hüküm-sütunu — **OLAY-ÜRETİLMİYOR / ÜRETİLİYOR-ama-log-yok / LOG-LANIYOR-detaylı**; kripto-standardı = *"kripto-log'un-gördüğün-her-satırın-forex-si-yani"*.

## 1. Üretim-zinciri-mimarisi (census'un-haritası)

```
15m-bar → orchestrator tick-loop → on_new_bar (:2263) → runtime.on_bar (:2267)
  → session.update (CBDR: track_body→lock→check_sweep→_confirm_sweep→bias_locked)   [SESSİZ — §3-satır-1..4]
  → FVG-scan (_nexus_detect_fvgs :277) → candidate-loop (:284-320) → pending        [SESSİZ — §3-satır-5..7]
  → LiveRunner.on_bar (:404) → risk-eval → execution(signal_only) → broker-observe  [koşullu-emit — §3-satır-8]
audit.jsonl emit: yalnız orchestrator (33-çağrı) + live_runner (RISK/ORDER/POSITION/EXIT) + paper (SIGNAL!)
```

## 2. Audit-emitter-envanteri (tam-tarama)

**Orchestrator — 33-audit-çağrısı (:975..2731), tip-dağılımı:** STARTUP-5 · SHUTDOWN-3 · ERROR-13 · SAFETY-5 · MT5_CONNECT-1 · WRITE_BLOCK-2 · LOCK_CORRUPT-1 · (flush-yardımcıları-3). **Orchestrator-hiç-üretmiyor:** CANDLE · SIGNAL · RISK · ORDER · FILL · POSITION · EXIT · RECONCILE · STATE_SAVE · MT5_DISCONNECT.

**Orchestrator-dışı emitterlar:**

| Modül:satır | Olay | Production-boot'ta-aklıyor-mu? |
|---|---|---|
| `live_runner.py:426,438,454,474` | RISK (approved/blocked) | **KOŞULLU** — yalnız-signal-risk-eval'a-ulaşınca; Boot-C'de-0-görülme |
| `live_runner.py:482` | ORDER (gönderildi/attempted) | KOŞULLU — signal-sonrası; signal_only'de-gönderim-yok-olay-bakırı-aynen |
| `live_runner.py:523` | POSITION | KOŞULLU — broker-gözlemi |
| `live_runner.py:630` | EXIT | KOŞULLU — pozisyon-kapanışı |
| `signal_runner.py:188` | CANDLE | **AKMIYOR** — SignalRunner-ayrı-modül; orchestrator-onu-kullanmıyor |
| `signal_runner.py:149` | RISK | AKMIYOR (aynı) |
| `paper.py:515,533,409` | SIGNAL/POSITION/EXIT | **AKMIYOR** — PaperSession-yalnız-paper-modu |
| `audit.py:93` | SIGNAL | **DEĞİL** — docstring-örneği (kod-yok) |


## 3. ANA-CENSUS-TABLOSU (Hakem-8-satırı; satır-ankorlu-kanıt)

| # | Olay (kripto-örnek) | Kod-yeri | Hüküm | Detay-b/nerede-c | Kanıt |
|---|---|---|---|---|---|
| 1 | CBDR-pencere-girişi/çıkışı | `session.py:198-206` (`update`: in_w-dalı) | **OLAY-ÜRETİLMİYOR** | pencere-içi/dışı-kararı-state-mutasyonu; canlıda-görünüm=YOK | session.py'de-0 print/log/audit (grep); runtime-tüketimi-sessiz (`strategy_runtime.py:263`) |
| 2 | Kilitlenme (body_locked) | `session.py:167-174` (`lock_cbdr`) + `:205-206` | **OLAY-ÜRETİLMİYOR** | `cbdr.locked=True`-tek-atama; olay/çıkış-yok; canlıda-yok | aynı-grep; runtime-flag-sessiz |
| 3 | Sweep-taraması/kabulu | `session.py:104-156` (`check_sweep`) | **OLAY-ÜRETİLMİYOR** | SweepEvent-in-memory-dönüyor (`:263-266` flag); tolerans/level/direction-log-YOK; canlıda-yok | runtime `:265-266` yalnız-flag; 0-audit |
| 4 | Bias-kilitlenmesi | `session.py:158-165` (`_confirm_sweep`) | **OLAY-ÜRETİLMİYOR** | `daily_bias/bias_locked`-mutasyon; **tek-dolaylı-görünüm = sonraki-boot S9-payload** (`bias:'bearish'` — Boot-C-audit-satır-21) | T0#5-çapası-teyit: transition-only-sınır; canlı-per-pencere-yok |
| 5 | FVG-aranyor | `strategy_runtime.py:277-286` | **OLAY-ÜRETİLMİYOR** | tarama-parametreleri (lookback/min-size/wick-ratio) hesaplanıyor-log-yok; canlıda-yok | 0-audit-0-stdout |
| 6 | FVG-bulundu (aralık-değerleri) | `strategy_runtime.py:284-320` candidate-loop | **OLAY-ÜRETİLMİYOR** | direction/zone/eq/mid hesapları-log-yok; **Hakem-öngörüsü-teyit**: audit-SIGNAL-olayı-sonradan-ve-canlı-yolda-o-da-yok (satır-8a) | 0-audit; kalıcı-iz-yalnız-ölü-pending-state'i |
| 7 | Entry-ara-adımları (MIN_RISK_DIST/pending-fill) | `strategy_runtime.py:235-237,323-332` | **OLAY-ÜRETİLMİYOR** | reddedilen-pending/bekleyen-fill-ara-adımları-sessiz; canlıda-audit-yok (state.json-ölü-yazım-harici) | 0-audit-0-stdout |
| 8a | SIGNAL | enum `audit.py:48` · emit `paper.py:515` | **ÜRETİLİYOR-ama-log-yok (production-yolda)** | LiveRunner-signal'ı-`StepResult`-taşır; **orchestrator/live_runner-SIGNAL-emiti-YOK** → canlı-boot'ta-signal-bile-olsa-SIGNAL-audit-olayı-DÜŞMEZ | emitter-taraması (§2); audit-23'te-0 |
| 8b | RISK | `live_runner.py:426,438,454,474` | **ÜRETİLİYOR-ama-canlıda-0-örnek (signal-koşullu)** | approved/blocked+reason-payload-dolu; ilk-sinyalde-düşmesi-beklenir | Boot-C-0; `signal_runner.py:149`-ayrı-yol |
| 8c | ORDER | `live_runner.py:482` | **ÜRETİLİYOR-ama-canlıda-0 (signal-koşullu; FAZ-3-B-yolu)** | enum-yorumu: "sent (or attempted)" | Boot-C-0 |
| 8d | FILL | enum `audit.py:51` | **OLAY-ÜRETİLMİYOR (ölü-enum-üyeli)** | **src-genelinde-0-emitter** → e2e-zincirinde-YAPISAL-DELİK (FAZ-3-B-pin-önkoşulu) | grep-EventType.FILL = 0-isabet |
| 8e | POSITION | `live_runner.py:523` | ÜRETİLİYOR-canlıda-0 (koşullu) | broker-gözlem-payload'ı | Boot-C-0 |
| 8f | EXIT | `live_runner.py:630` (+paper:409) | ÜRETİLİYOR-canlıda-0 (koşullu) | ClosedTrade-payload'ı | Boot-C-0 |

**Ek-bulgu-ölü-üyeler (enum-var-emitter-yok):** `RECONCILE` (`:55`) · `STATE_SAVE` (`:61`) · `MT5_DISCONNECT` (`:62`) — **0-emitter** → reconciler/state-save/reconnect-ladder olayları-audit'e-hiç-akmıyor (reconnect=yalnız-stdout `[RECONNECT]`-satırları).

## 4. ⚠ FAZ-3-A-BEKLENTİ-DÜZELTMESİ (Hakem-notunun-hipotezine-karşı-census-kanıtı)

Hakem-notu: *"fiyat-FVG-zone'a-gelirse-SIGNAL-olayı-audit'e-düşmeli (mevcut-mimari)"* → **CENSUS-BUNU-DESTEKLEMİYOR.**

- SIGNAL-emit-yeri-repo-genelinde-taraması: **yalnız `paper.py:515`** (PaperSession) + `audit.py:93` (docstring-örneği). Orchestrator-canlı-döngüsü-SIGNAL-emiti-YOK.
- Canlı-yolda-runtime-signal'ı `LiveRunnerStepResult`-içinde-taşınıyor; audit'e-akan-ilk-iz = **RISK** (`live_runner.py:426/438/454/474` — approved/blocked+reason) — ve-o-da-signal-üretimine-koşullu.
- **Düzeltilmiş-tahmin:** AUDUSD-FVG-zone-dokunuşunda-audit'e-düşecek-olan → `RISK` (risk-eval'a-ulaşabilirse) veya hiçbir-şey (signal-bile-üretilemezse/yok-olursa). **SIGNAL-satırı-aliyorum-beklentisi-yanlış-kanıt-üretir** (negatif-gözlem-yanılgısı: "RISK-görmedim=signal-üretilemedi" mi "signal-var-ama-sessiz" mi-ayrıştırılamaz).
- **Pencere-gözlemi-başarı-ölçütü-düzeltmesi:** ilk-doğal-test-olayı = **ilk-RISK-emiti** (blocked-bile-olsa-değerli: reason=BLOCKED-blok-sebebi-görünür). SIGNAL-canlıda-hiç-görülmeyecek — bu-bug-değil, emit-yokluğu (N2#23-kapsamı).

## 5. FAZ-3-B-ön-pin (env-değişikliği-ÖNCESİ-yapılacaklar; Reis-onayı-ayrı-basamak)

| # | Önkoşul | Census-kanıtı |
|---|---|---|
| P-1 | **FILL-emiti-yok** — e2e-audit-zinciri (SIGNAL→RISK→ORDER→FILL→POSITION) bugün-yapısal-olarak-tamamlanamaz; ya-FILL-emiteri-eklenir (N2#23-scope-kararı) ya-zincir-pin-i "FILL=görünmez-bilinen-delik" olarak-pre-reg'e-yazılır | `grep EventType.FILL` = 0-emitter |
| P-2 | **SIGNAL-emiti-yok** — zincir-başı-görünmez; pin: "zincir-öznesi=RISK'ten-itibaren" VEYA N2#23-SIGNAL-emiti | §4 |
| P-3 | signal_only-modunda-ORDER-emiti-"attempted"-yolunu-kapsıyor-mu-teyit-edilmeli (`:482`-payload-okunmalı) — pin-öncesi-1-okuma | enum-yorumu-"sent (or attempted)" |
| P-4 | trade_mode=4-açılışında-SAFETY-gate-'closed'→'open'-geçişi-audit-düşüşü-doğrulanmalı (SAFETY-emit-5-çeşit-var; gate-open-olayı-görünürlüğü-bilinmiyor) | audit-23: SAFETY-yalnız-`startup_SAFE_START` |

## 6. N2#23-ADAY-LİSTESİ (rezervasyon-önizlemesi — FAZ-2: Reis-onayı-HASH-BAĞLI-önce-KOD-YOK)

> İlke-taahhüdü: mevcut-EventType'lara-bağlı **log-vurgu-katmanı** — strateji/bias/sweep/FVG-mantığına-DOKUNMAYAN, yalnız-görünürlük-ekleyen-yamalar. Kripto-standardı-hedef-satır-başı: *"her-dakika-ne-yapıyorum"*-eşdeğeri-en-azından-her-15m-bar-karar-özet.

| Aday | İçerik | Hüküm-kaynağı |
|---|---|---|
| R-1 | CBDR-özet-emiti (bar-başı-değil): pencere-giriş/çıkış + lock + sweep(level/direction/tolerans) + bias-lock — **tek-STATE-olayı** veya-CANDLE-payload-zenginleştirme | §3-satır-1..4 (hepsi-ÜRETİLMİYOR) |
| R-2 | FVG-scan-özet-emiti: bar-başı-"aranyor"(parametreler) + bulunduğunda-zone/eq/mid/direction | §3-satır-5..6 |
| R-3 | SIGNAL-emiti-canlı-yola (LiveRunner/orchestrator) — §4-düzeltmesinin-kök-çaresi | §3-satır-8a |
| R-4 | FILL-emiteri (ölü-enum-üyeyi-canlandırma) — FAZ-3-B-zincirinin-bağımlılığı | §3-satır-8d |
| R-5 | ENTRY-ara-adım-emiti: MIN_RISK_DIST-reject/pending-kurul-du/pending-fill | §3-satır-7 |
| R-6 | Ölü-üyeler: RECONCILE/STATE_SAVE/MT5_DISCONNECT-emitter-bağlantısı | §3-ek-bulgu |

**Öncelik-önerisi (Hakem-onayına):** R-3+R-1 (bias/sweep-görünürlüğü FAZ-3-A-pencere-gözlemi-için-şart) → R-2+R-5 → R-4 (FAZ-3-B-öncesi) → R-6.

## 7. Yöntem-ve-provenans

- **Statik:** `grep -n` satır-ankorlu-tarama — audit.py(enum+dataclass) · orchestrator.py(33-çağrı-tarandı) · live_runner.py · signal_runner.py · paper.py · strategy/session.py(tam-215L) · strategy_runtime.py(270-332) · breakout_variant.py(kontrol).
- **Canlı:** `state/audit.jsonl`-Counter-parse (23-olay) · `state/t10c_boot_stdout.log`(12L).
- **Salt-okuma-kanıtı:** bu-rapor-yazımı-sırasında `git status --porcelain` yalnız-yeni-`results/D88_log_adequacy_census.md` + defter-satırı gösterir; `src/ tests/ index.json` diff-YOK.
- **Kapsam-sınırı:** breakout_variant.py-FVG-yolu-ayrı-(stop-order-kardeşi)-aynen-sessiz-kabul-edildi (aynı-runtime-deseni); MT5-stdout-detayları-census-kapsamı-dışı.


## 8. Canlı-doğrulama (Boot-C-korpusu)

- **audit-mix (23-olay, 4-boot-eriyik):** MT5_CONNECT-4 · STARTUP-15 · SAFETY-4 — **strateji/piyasa-olayı-sıfır.**
- **stdout (t10c_boot_stdout.log, 12-satır):** reconnect-hattı + SAFE_START-başlık — saatlerce-çalışmada-sıfır-ek-satır.
- **Karşılaştırma-sayısı:** kripto-örnek-dakika-başı-hikâye ↔ forex-üretim-yolu 15m'de-bir-SESSİZ + strateji-karar-anlarında-SESSİZ. **Gap = yapısal (kütüphane-eksik değil, emit-çağrısı-eksisiz).**
