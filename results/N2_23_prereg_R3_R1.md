# N2#23 PRE-REG — R-3 + R-1 (temiz-log-inşası; Reis-onayı-ÖNCE — bu-belge-onaylanana-dek KOD-YOK)

**Menşei:** D88-census §6 (R-3: satır-81 · R-1: satır-79) + öncelik-önerisi (satır-86: R-3+R-1) + Hakem-D89-kapanış-izinleri (2026-09-04).
**İlke-taahhüdü (census-satır-75-birebir):** mevcut-EventType'lara-bağlı **log-vurgu-katmanı** — strateji/bias/sweep/FVG-mantığına-DOKUNMAYAN, yalnız-görünürlük-ekleyen-yamalar. Kripto-standardı-hedef: her-15m-bar-karar-özet.

## Scope-R-3 — SIGNAL-emiti-canlı-yola (census-§3-satır-8a; §2-düzeltmesinin-kök-çaresi)
- **Bugün:** canlıda-SIGNAL-olayı-**hiç-üretilemiyor** — yalnız `paper.py:515,533,409` (paper-modu-akmıyor) + `audit.py:93` (docstring-örneği, kod-değil); LiveRunner/orchestrator-yolunda-emitter-yok.
- **Plan:** signal-üretim-sonucunun-canlı-yolda-görüldüğü-tek-noktaya-`EventType.SIGNAL`-audit-emiti. **Hakem-v1.1-kilidi (AM-R3):** `strategy_runtime`-signal-**dönüş-noktası** (census-§1.3-çürütme-zinciriyle-uyumlu; orchestrator-alım-noktası-cascade-test-zaten-kapsıyor) — Reis-işaretlerse-değişir. Payload-şeması: symbol/side/entry/sl/tp/reason/ts **+ FVG-id** (Hakem-v1.1; trace-bağlanabilirliği).
- **Doğrulama-ölçütü:** (1) yeni-unit-test-payload-şemasını-sabitler; (2) sentetik-koşumda-emiti-görür; (3) Boot-C-audit'te-ilk-SIGNAL-satırı — doğal-olay-beklenir (sentetik-olay-canlı-boot'a-enjekte-EDİLMEZ).

## Scope-R-1 — CBDR-özet-emiti (census-§3-satır-1..4 — dördü-de-OLAY-ÜRETİLMİYOR)
- **Bugün:** pencere-giriş/çıkış `session.py:198-206` · lock `:167-174` · sweep-taraması/kabulu `:104-156` · bias-lock `:158-165` — **tümü-SESSİZ**; tek-dolaylı-görünüm=sonraki-boot-S9-payload.
- **Plan:** dört-anın-runtime-tüketim-noktasında-(`strategy_runtime.py:263`-yakını) **tek-STATE-tipi-emit** (alternatif: CANDLE-payload-zenginleştirme — icra-onayında-kilit). Payload: pencere-in/out·locked·sweep{level,direction,tolerans}·bias. **Session.py-strateji-gövdesine-dokunuş-YOK** (katman-ayrımı-mutek: gözlem-katmanı-tüketir). **AM-N23-1 (Hakem-v1.1, ek-şart):** STATE-payload'a-d4-sinyal-alanları-eklenir — **sweep-olan/olmayan · bias-kilit-ts · sweep_ts** — S9-startup-payload-sayılarıyla-şema-uyumlu (N2#22-varyant-benchmark'ındaki-S9-replay-bias-SINIF-2-karar-olayıyla-canlı-bağ-kurulur; R-1-bu-uyumu-canlıda-ölçülebilir-eleyerek-SINIF-2-izleme-zincirini-tamamlar). Tek-satır-payload-zenginleştirmesi; yeterli-olmazsa-sıra-sıra-açıklanır.
- **Doğrulama-ölçütü:** FAZ-3-A-pencere-gözlemi-artık-CBDR-karar-hikâyesini-okur; ilk-RISK-emiti-beklentisi-SIGNAL/STATE-görünürlüğüyle-birleşir.

## Sınırlar + test-taahhüdü
- **Kod-yüzeyi:** yalnız-audit-emit-eklemeleri + importlar; src-yüzeyi-tahmini-≤4-dosya (strategy_runtime/orchestrator-bölgesi); **mevcut-süit-tam-yeşil-kalmalı** (waivor-dışı-sıfır-kırmızı).
- **Yeni-testler:** (1) SIGNAL-payload-şema-testi · (2) CBDR-özet-emiti-pencere-yaşam-döngüsü-testi (sweep/lock/bias-sırası).
- **FILL-yokluğu-PİNİ (P-1):** e2e-zincir-SIGNAL→RISK→ORDER→**FILL=görünmez-bilinen-delik**→POSITION — R-4-ayrı-charter; bu-pre-reg-zincir-deliklerini-yazılı-pinler.
- **Boot-C-dokunulmaz:** kod-değişimi-canlı-boot'u-etkilemez; restart/swap-kararı-Reis'te (D86-protokolü).
- **Sıra-taahhüdü:** R-3+R-1 → R-2+R-5 → R-4 → R-6 (census-satır-86).

**Ratifikasyon-durumu (v1.1):** Hakem-**RATİFİYE-WITH-NOTES** (2026-09-04; AM-N23-1 + R-3-kilit-önerisi + payload+FVG-id + sentetik-İLK-ADIM-sırası-dâhil) — **Reis-yazılı-✓-bekleniyor** (charter-bloğu-Hakem-hükmü-§3'te-hazır). Reis-✓-sonrası-icra-sırası: **(1) sentetik-şema-testi** → (2) R-3+R-1-implementasyon (≤4-dosya) → (3) süit-tam-yeşil → (4) Boot-C-ilk-SIGNAL/STATE-satırı-doğal-watch (enjeksiyon-yok) → (5) commit → (6) hash-bound-push-talebi {`06ff37b` + N2#23-commitleri} → push-kayıt-9 → R-2+R-5 → R-4 → R-6.
