# N2 #22 — FAZ-A HANDOFF PAKETİ (yeni-ajan-ön-briefing · TÜM-BAĞLAM-TEK-DOSYA)

> **Durum:** HANDOFF-KONTEKST-PİN (bu-dosya yazıldığı an bağlamı dondurur; **FAZ-A pre-reg bu-dosyadan-ÜSTÜNE-YENİ-dosyada açılır** — bu-dosyaya yazılmaz)
> **Yetki:** Hakem-hükmü — *"PUSH-{3-commit}-ratifiye · ÖNCELİK-KARARI: N2 #22-FAZ-A = YENİ-ÖNCELİK-1 (yeni-ajana; N2 #21-kalan-maddeler-ertele)"* · Reis-elinden-iletilir
> **Yazan:** Cline (D85/D86-masası) · **Tarih:** 2026-09-04 · **Sınıf-etiketi:** bu-dosya SINIF-1-statik (tümü-dosya-kanıtlı; v0.0-davranış-yok)
> **Tek-dosya-taahhüdü:** session/context-gelmeyecek → **tüm-bağlam burada** (§4). *Private-history talebi = protokol-ihlali* (SESSION_CHECKPOINT.md §8).

## 1. KAPSAM — frozen 2.7Y/6-major V0..V5 matrisi + downstream-sütunlar

**Veri-zemini (ölçülü-kanıtlı, 2026-09-04 bugün-doğrulandı):**
- 6-major × **15m feather** = motor-tükettiği-yaprak (`experiment/main_research_c_v1_1.py` no-args = FULL koşum; `SIX_MAJORS` `:780` = EURUSD, GBPUSD, GBPJPY, USDJPY, AUDUSD, USDCAD).
- Ölçülen-span (6-sembol-birebir): **2024-01-01 22:01:00 → 2026-08-21 20:45:00** (~2.63-yıl bar-zamanı; benchmark-dilinde "2.7Y") · satır-148-python-ölçümü `pd.read_feather`, kolonlar `timestamp,open,high,low,close,volume`.
- **Pin:** `memory-bank/dataset_manifest_v1.1.md` (84-satır, fiksasyon 2026-08-31) — **24/24 SHA256 bugün-birebir-doğrulandı** (18-feather + 6-RAW-CSV; protocol: manifest-§Verification). Ayrıntı-paket: `results/n2_22_fazA_dataset_pin.md` (B-paketi, bu-handoff'la-ikili).

**V0..V5-variant-matrisi — ⚠ PIN-PENDING-İFYASI (§13.5-dürüstlük):**
- Hakem-hükmü kapsamı **"frozen 2.7Y/6-major-V0..V5 (matris-n2_22-öncesi-v1.1-hüküm)"** diye sabitler; **ama "V0..V5" etiketlerinin-bağlı-tanımı bu-repo-defterinde-bulunamadı** (grep: `V0..V5|V0-V5|N2#22|N2_22` → `memory-bank/`+`results/` = **0-isabet**; `results/benchmark/` artifact-adlarında V-etiketi yok).
- Yorum **(bağlayıcı-değil, pre-reg'de-pinlineşir):** "matris-öncesi-v1.1-hüküm" Hakem–Reis-kanalındaki-yazılı-hükümdür; V0..V5 = o-hükmün-çözümlediği 6-variant-şeridi. **Yeni-ajan V0..V5 semantiğini TAHMİN ETMEZ** — Reis-hüküm-metniyle-iletilen tanımları pre-reg'de-artifact'a-pinner; belirsiz-kalırsa **koşum-ÖNCESİ Hakem-arbitrajı** (SRI-protokolü).
- Donuk-aday-çapaları (matris-bilinmese-de-sabit): C v1.1 (`0899b38`-promosyon; 2299T/+2646.92R/DD-6.29R/PF-4.90) · D v1.0 baseline (`results/benchmark/PURE_D_FVG_ORIGIN_EQ_benchmark.json`; 2847T/+2949.05R/DD-7.36R) · SRI-001 chain-6 (aşağıda-§2) · SRI-001 chain-4 = **kalıcı-RED** (2141T/−85.8R; port-edilmez, bulunursa-ihlal).

**Downstream-sütunlar (Reis-amendmanı):** offline-matris-çıktısına Reis'in-istediği-ek-kolonlar (canlı-gözlem-join'i: Boot-C-SINIF-2-telemetrisiyle-birleşebilir — bias/sinyal/pencere-çaprazlığı). **Kolon-listesi Reis-amendmanı-metnindedir** (iletimle-gelir); pre-reg bu-slotları-rezerve-eder, tanım-sonradan-değiştirilmez (pre-reg-disiplini).

## 2. KOD-ÇAPALARI (frozen-bağlar)

| Çapa | Konum | Donuk-kimlik |
|---|---|---|
| Dataset-pin | `memory-bank/dataset_manifest_v1.1.md` + `results/n2_22_fazA_dataset_pin.md` | 24×SHA256 (bugün-doğrulandı) |
| BREAKOUT-aday-tanımı | `results/N2_19_breakout_port_spec.md` (286L, PRE-REGISTERED) + doğum-üçlüsü: `experiment/exp_sri001_breakout_variant.py` (blob `bb66889`) · `results/exp_sri001_breakout_variant.json` · `results/SRI001_RAPOR.md` | doğum-commit **`7a6d564`** (2026-09-02); pin-HEAD `0081c64` |
| Port-modülü | `src/live/breakout_variant.py` (N2#19-Faz-1-fork) | parite 6/6 (`python tools/n2_19_parity_check.py` → 512T/+412.00R/4066-iz) |
| Düzeltilmiş-exit-anchor | D62-bülteni (`results/D62_breakout_timing_bulletin_draft.md`, v1.1-amendmanlı) | `--corrected` → **513T/+16.20R/hold_bars<0=0/513**; *benchmark-under-corrected-exit-anchor* etiketi-zorunlu |
| C-motor | `experiment/main_research_c_v1_1.py` | apply_dd_scaling `:411-452` (entry_ts-paralel-liste-şartı; backdated-exit ValueError-fail-fast) |
| Bias-gün-sayımı (bias-junction-bağlamı) | `results/D64_bias_census_evidence.md` (137L, sha-ön-eki `8b18f70a`) | kapsama **%82.87-census / %83.28-iz** · 4,104-gözlemlenebilir-gün · 6-madde-bias-gün-tanımı (progress.md:1009) — FAZ-B-pre-reg-girdisi |

**AM-N22-1..4 (Hakem-etiketleri; bağlayıcı-metinler-pre-reg'de-pinlineşir):**
1. **motor-sabiti** — matris-variant'ları donuk-sabitlerle koşar; parametre-oynatma-= yeni-deney-≠-bu-matris.
2. **bias-junction** — bias-gün-katmanı (D64-sayım-dili) ile variant-çıkışının-kesişimi; NEUTRAL-gün-davranışı pre-reg'de-tanımlanmalı.
3. **çift-sayım-yasağı** — aynı-bar/trade iki-variant-hesabına-giremez (D62-§4.1'deki-paralel-liste/exit-anchor-dersi = bu-yasağın-mühürlü-örneği).
4. **v0-çapraz-çapa** — her-variant-satırı V0-baz-çizgisine-çapraz-denetlenir; V0-tanımı pre-reg'in-ilk-pini.
*Bu-dört-madde Hakem-hükmünde-etiket-olarak-verildi; **işletme-tanımı koşum-öncesi pre-reg'de yazılır ve Hakem-arbitrajından-geçer** (tahminle-koşum-yasak).*

## 3. SINIRLAR (ihlalde-FAZ-derhal-durur — N2#19-§2-deseni-buraya-genelletildi)

- **S-a — canonical-motor-dokunuş-yok:** `experiment/` ve SRI-001-üçlüsü **salt-okunur** (blob-hash'leri-koşum-öncesi/sonrası-yeniden-ölçülür, doğum-piniyle-birebir). Ortak-çekirdek-çıkarma-yok (fork-deseni).
- **S-b — strategy_runtime-edit-yok + canlı-temas-yok:** `src/live/strategy_runtime.py` editlenmez; **boot/state/soak yasak — Boot-C (PID-18460, AUDUSD, audit-23, bias=BEARISH) ŞU-AN-CANLI ve SINIF-2-izlemede; koşumların-canlıyla-DOKUNMAZ** (ayrı-proses, offline-feather, MT5-call-yok).
- **S-c — Reis-sinyali-anında-dondurur:** çıktılar-untracked → freeze-bedeli-sıfır; sinyal-gelince-Faz-olduğu-gibi-bırakılır.
- **S-d — set-ayrılığı:** N2#22-çıktıları başka-set'e-girmez (A6/N2#19-deseni).
- **S-e — OOS-iddiası-yok:** çıktı = geçmiş-benchmark'ın-yeniden-üretilmesi/karşılaştırması; **canlı-kenar-beklenti-iddiası-taşımaz** (D62-§5-etiket-kuralları-devir: "benchmark-under-corrected-exit-anchor" ↔ doğum-etiketi-değiştokuşulamaz).
- **Sınıf-etiketi-SINIF-1:** statik-analiz + donuk-artifact-koşumu; davranış-katmanı-canlıya-değmez → FAZ-A-telemetrisi SINIF-1-etiketle-raporlanır.
- **Faz-3-wire-in YASAK** (D61-hükmü aynen-yürürlükte; N2#19-Faz-3-gate KAPALI/HOLD).
- **AGENTS.md-bağlayıcı:** codebase-memory-MCP-first (yoksa-STOP-bildir) · kanıt-hiyerarşisi · commit-öncesi-diff-muayenesi · **push-başlangıçta-YOK** (her-push-yazılı-hash-bound-yetki; koşum-çıktıları-untracked-kalır) · koşum-scriptleri `%TEMP%`-alışkanlığı (repo-disi-araç, sonuç-artifact'ı-repo'ya-YAZILIR-dosya-olarak).

## 4. AKTARIM — bootstrap-protokolü (sırayla-oku) + checkpoint-mini-delta

**Okuma-sırası (SESSION_CHECKPOINT.md §8-devir):**
1. `AGENTS.md` (sözleşme) → 2. bu-dosya (`results/N2_22_fazA_handoff.md`) → 3. `results/n2_22_fazA_dataset_pin.md` (B-paketi) → 4. `memory-bank/dataset_manifest_v1.1.md` (pin-kaynağı) → 5. `results/N2_19_breakout_port_spec.md` §1-3 + `results/D62_breakout_timing_bulletin_draft.md` §4-7 → 6. `results/D64_bias_census_evidence.md` §son (AGG-satırları) → 7. `memory-bank/progress.md` son-100-satır (D80-D87-bölgesi).

**Durum-dogrulama (okuma-bittiğinde-koştur):** `git log --oneline -3` (HEAD beklenen: 057da7a-üstünde-local-`173be24`+`100160d`) · `git log --oneline origin/main..HEAD` (BOŞ-değil: 2-local-commit-push-bekler — dokunma) · `tasklist /FI "PID eq 18460"` (Boot-C) · `wc -l state/audit.jsonl` (≥23; sadece-BÜYÜR, küçülürse-olay) · `sha256sum data/icmarket_feather/*_15m.feather` (pin-uyumu).

**Checkpoint-mini-delta (bu-handoff'un-SESSION_CHECKPOINT'e-işlenecek-farkı):**
- **Push:** {`7a9e7a4`,`460640d`,`057da7a`} → `d36856f..057da7a main` (hash-bound-yetkili; post-push-doğrulandı) · **local-push-bekleyen:** {`173be24` push-kaydı-6, `100160d` D86-defter} (SET-2-sıra-modeli).
- **D85:** canlı-sembol-swap-icra (κ-stop→BOOT-C-AUDUSD) · **SINIF-1↔2-mühür:** S9-replay-bias=BEARISH ↔ scan=BEARISH · rapor `results/D85_live_symbol_swap.md`.
- **D86 (yazılı-usul):** sembol-swap = coruma→κ-stop→`SNIPER_SYMBOLS`-env→Reis-bildirim→**SINIF-1↔2-karşılaştırma-ZORUNLU**→sınıf-etiketli-rapor.
- **D87 (bu-girdi):** N2#21-ERTELEME (dört-kalem) + N2#22-FAZ-A=öncelik-1 + bu-handoff-paketi.
- **Boot-C:** PID-18460 canlı (audit-23-stabil, WB=0-sürüyor, heartbeat-döngüsü) — pencere-sayacı FAZ-B-önem-ölçümü.
- **Açık-lifecycle-kalemi:** SHUTDOWN-audit-satırı-hâlâ-canlıda-görülmedi → sonraki-stop **foreground-PowerShell-lansmanından** (AM-T7-15-satır-9).

## 5. N2#21-ERTELENEN-DÖRT-KALEM (Hakem-hükmü-§2 — Boot-C-akıbetiyle-birlikte-açılır)

| # | Ertelenen | Not |
|---|---|---|
| 1 | Kalan-maddeler **4/2/5/6** (4=telemetri+RM-probe-en-yüksek-gain) | tekrar-açılış-tetiki: Boot-C-akıbet-kararı |
| 2 | Kalan-6-dosya-full-suite koşumu | uzun-suit-penceresi-sonra |
| 3 | D82-izleme-borcu | aynen-yaşar (yeni-ajan-bilgisi-≡-§4-mini-delta) |
| 4 | 12/13-D72-tamamlama-onayı | Reis-onayı-bekler |

## 6. B-PAKETİ — dataset-pin dosyası

`results/n2_22_fazA_dataset_pin.md`: 24-artifact-tam-hash-tablosu + ölçülen-span + doğrulama-komutları + **WinError-zorluğu-yok beyanı** (offline-`pd.read_feather`-okuma-yolu; WinError-5-sınıfı=canlı-yazım-yolu-sorunu — D80/D81-kanıt-zinciri-canlı-yazımda; FAZ-A-okuma-patika-tarafında-geçerliliği-yok). Motor-tüketimi: yalnız-15m-yaprak (5m/1m/RAW=upstream-donuk-zincir).

---
*Seal-borcu: bu-dosya-ve-paketi-dosya-düzeyinde-yazım-anı-mühürüyle-donar (wc+sha256 → progress.md D87-girdisi); pre-reg-yazan-ajan koşum-öncesi bu-hash'leri-tekrar-ölçer (uyuşmazlık = handoff-bozuldu = STOP).*
