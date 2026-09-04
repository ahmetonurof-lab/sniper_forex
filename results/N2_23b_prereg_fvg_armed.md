# N2#23-b PRE-REG — fvg_armed + AM-N23-2/3 (log-genişlemesi; Reis-onayı-ÖNCE — bu-belge-onaylanana-dek KOD-YOK)

**Menşei:** D92-charter (2026-09-05): AM-N23-2 (ts-şartı) + AM-N23-3 (insan-okunur-payload) + fvg_armed-emit + trailing-perspektifi-pini. Canlı-kanıtlar: t10d-boot (D91) sweep→SIGNAL-sessizlik-gözlemi + ts-integrity-probe (`state/t10d_preserve/ts_integrity_probe.py`).
**İlke (D92-kalıcı-kural):** kripto-log-standardı-masa-referansı — her-olay-üçlüsü (ne-zaman/ne-olmuş/ne-kadar) tek-bakışta; eksik-halinde-census-önce-yazılır, sonra-kod-dokunuşu.

## AM-N23-2 — satır-başı-event-time-ts-şartı (HALİHAZIR-UYUM: kod-dokunuşu-YOK)
- Canlı-dogrulama (probe, 2026-09-05): 224/224-satır-taşıyor · epoch-float · 0-monoton-ihlal · payload-iso-bozuk-0.
- Replay-semantiği-notu: S9-replay-kümesinde-satır-ts=replay-anı, bar_ts=içerik-tarihi — ikili-ayrık-alanlar-doğru-tasarım. **AM-N23-2-canlıda-KARARLI.**
- Şema-testi-taahhüdü: fvg_armed-şema-testine-ts-kanat-durumu-eklenir (yeni-satır-tipi-de-aynı-ts-disipliniyle-doğar).

## AM-N23-3 — insan-okunur-payload (kod-dokunuşu: signal_audit_payload + fvg_armed-payload)
- SIGNAL-payload'ına-fvg-öz-ölçüleri-eklenir: `fvg_top / fvg_bottom / fvg_size_pip / direction` (fvg_id-trace-bağı-KALIR — id-yanında-ölçüler).
- fvg_armed-payload-aynı-dili-kullanır (armed-fvg-ölçüleri+direction+bar_ts).
- Schema-testleri-alan-setini-sabitler (kapalı-set; mevcut-sinyal-testi-ile-uyumlu).

## Scope-fvg_armed — STATE(moment=fvg_armed) — sessizlik-kapatma
- **Bugün:** sweep-onay-STATE-sonrası-motor-FVG-arm-fazında-ilk-dokunuşu-bekler — bu-arada-SESSİZ (canlı-gözlem: t10d-boot-sonrası-0-STATE; arm-fazı-görünmez-bilinen-delik).
- **Plan:** FVG-arm-anında-(strategy_runtime-observation-katmanı; session.py-gövdesi-dokunulmadı)-tek-STATE-emit, moment=fvg_armed. R-1-deseninin-ikinci-momenti; emit-failures-logged-never-raised.
- **Doğrulama-ölçütü:** (1) şema-testi-payload-setini-sabitler (2) sentetik-koşumda-arm-emiti-görülür (3) canlı-boot'ta-doğal-satır (enjeksiyon-yok; boot-kararı-Reis'te-D86).

## Trailing-perspektifi-PİNİ (kod-yok; N2#21-notu)
- Trailing-gelecek-log-R-2/R-5-adımlarında-census'la-çizilir; şimdilik-SIGNAL-çapa-payload'ı-yeterli.

## Sınırlar + test-taahhüdü
- **Kod-yüzeyi:** ≤4-dosya (strategy_runtime + test-dosyaları); session.py-gövdesi-dokunulmaz; **mevcut-süit-tam-yeşil-kalmalı** (D90-üçlü-süit-okuma-kuralı-uygulanır: kod-hatası/çevre/native-ayrı-okunur).
- **Yeni-testler:** (1) fvg_armed-lifecycle-testi (sweep→armed→signal-sırası) (2) AM-N23-3-payload-şema-testi (3) AM-N23-2-ts-kanat-testi.
- **Boot-dokunulmaz:** bu-pre-reg-icrası-canlı-boot'u-etkilemez; yeni-kod-sonraki-restart'ta-alınır (Reis-D86-kararı).
- **Sıra:** N2#23-b → FULL-geçiş-zinciri (D92: N2#23-b-yeşil + süit-yeşil + Reis-onayı → D30-trade_mode=4 → ilk-e2e-canlı-order-zinciri-kanıtı).

**Ratifikasyon-durumu:** v1 — Reis-onayı-bekleniyor; onay-öncesi-KOD-YOK. Icra-sırası-onay-sonrası: (1) sentetik-şema-testleri → (2) implementasyon (≤4-dosya) → (3) süit-yeşil → (4) commit → hash-bound-push-talebi (SET-2'ye-biner) → sonraki-restart-penceresinde-canlı-doğrulama.
