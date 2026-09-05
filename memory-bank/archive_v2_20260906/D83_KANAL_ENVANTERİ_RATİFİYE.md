## D83 — KANAL-ENVANTERİ-RATİFİYESİ + T0#10-MASA-HAZIRLIĞI (2026-09-04 09:4x +03)

**Hakem-hükmü ratifiye:** üç-dosyalı-kanal-haritası (stdout=insan-log / state/audit.jsonl=makine-journal / crash_log.txt=floor-forensics) · "iki-defa-kapat-aç-gerek-var-mı?" → **TEK-BOOT-YETER** (load-artık-motor-davranışı; T0#10=Boot-A→çalış→kill→Boot-B→devralma-kanıtı) · D.2-recide-yol-ayrımı ("kalıcı-log bekleniyor" → motor-tedarik-ediyor; protokol-notundan-çıkarılır) · AM-T7-15 (boot-artifakt-beklenti-tablosu: stdout ✓ · audit-devralma ✓ · A8-fallback=SINIF-2) · Rider (boot-başına-adlı-stdout-topolojisi: daima-en-güncel-adla-oku; belirtmesiz-okuma=HATA-tuzağı) · persistent_log.py=ölü-modül→madde-6d-üçüncü-üye (kader: sil-veya-wire, same-owner-batch).

**CLINE-MASA-HAZIRLIĞI (coruma-7-nesil, canlı-DOKUNULMADI — Reis-onayı-bekler):**
1. **coruma-T0 (13:02-dersi):** audit.jsonl=6-satır-T0#9-artefaktı-DOKUNULMADI-kanıtlandı (bayt-uzunluğu-ile: 1707-B — 13:02-hash-dersi); lock=PID-14940-yetimi; safe.json=T0#9-mührü — hepsi-muhafazada.
2. **coruma-1 (kilit-hiyerarşisi):** boot-A-stale-takeover=beklenen-olay (dead-PID-üzerine-takeover=tam-başarı); lock-race-kuralları-geçerli; LOCK-TAKEOVER=A-capture-hedefi.
3. **coruma-2 (session-muhafaza):** CBDR/session=bellek-içi-canlı-kurulur; disk-tazeleme-YOK (A.2-gerçeği) — Boot-B-devralma=audit-journal'dan.
4. **coruma-3 (T0#9-kirli-reason-kalıcılığı):** safe.json-reason=YENİDEN-YAZILMAZ (A.1-gerçeği) → Boot-A-SAFE_START=BULGU-13-beklenen-bulgu; kirlilik-suç-değil-ölçüm.
5. **coruma-4 (audit-uzunluk-ölçümü):** madde-1-devralma-kanıtı=6→7+ (Boot-A-yazımı) → Boot-B-load'da-satırlar-havada (satır-sayısı+ilk/son-olay-karşılaştırma-kanıtı).
6. **coruma-5 (A8-fallback):** append-red→stdout-kanal-SINIF-2-beklenir-olay; panik-YOK; crash_log.txt=floor-kanıtı-yeri.
7. **coruma-6 (T.0-telemetri-istenemez):** RM-probe-SIFIR-dokunuş-kuralı-T0#10'da-da-geçerli (N2-icrası-ayrı-commit-bekler).

**T0#10-BEKLENTİ-TABLOSU (AM-T7-15 + Hakem-EK'leri):**
| # | Beklenti | Sınıf |
|---|---|---|
| 1 | Boot-A: COLD_REBUILD + SAFE_START (safe_json-hatırlıyor) | normal |
| 2 | Boot-A: stale-takeover (dead-PID-14940) | D35-norm-olay |
| 3 | Boot-A: SAFE_START-kirli-reason (madde-7-öncesi-kalıcılık) | beklenen-bulgu |
| 4 | Boot-A: audit.jsonl-6→7+ (append-delta; T0#9-satırları-DURUR) | madde-1-kanıtı |
| 5 | Boot-B: A-olayları-havada (load-devralma; satır-sayısı-korunur-artar) | **madde-1-acceptance** |
| 6 | A8-fallback-olayı-görünürse: stdout-kanal | SINIF-2 |
| 7 | crash_log.txt: floor-ateşi-görünürse diagnostik | BULGU-14-üç-yol-floor |
| 8 | t10_boot_stdout.log: en-güncel-adla-okunur (rider-uyumu) | okuma-disiplini |
| 9 | Sonraki-stop: **foreground-PowerShell-lansmanından** (konsol-var → gerçek-SIGINT → SHUTDOWN-audit-satırı-yazılır + D78-exit-degradasyon-ölçülür; D70-kesfinin-kapanış-adımı) | planlı-adım (Hakem-D85-ratifiye-§4.3) |

**SIRA-BEYANI:** T0#10-canlı-icra-KARARI-Reis'te (canlı-katman-Reis-bildirimli); Cline-masa-hazır — "BAŞLA" bildirimi-üzerine-boot-A-adımı-Reis-ile-beraber (coruma-sırası-yukarıda-pinned).
