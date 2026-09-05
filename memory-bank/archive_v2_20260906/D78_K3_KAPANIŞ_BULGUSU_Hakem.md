## D78 — K3-KAPANIŞ BULGUSU (Hakem hükmü, ratifiye — 2026-09-03 19:5x)

**K3-graceful-teardown TAMAMLANDI** (close-save ✅ D48-ilk-gerçek-egzersiz · lock-unlink ✅ · canlı-`session_atr` ✅) — **ama son-audit-flush `PermissionError` ile çöktü → exit-2 beklenen, exit-1 ölçüldü.** SHUTDOWN-payload'ının-kendisi-nedeni-yazdı: `run_exception:PermissionError`.

**D78-çekirdek:** Audit-defect'in-bedeli-artık-soyut-değil — **K3'ün-ölçmek-için-var-olduğu-tek-çıktıyı (exit-kodu) bozdu**; ve-defekt-kendi-arızasını-kendi-kayıt-sisteminin-içine-gömüp-kurtardı (`payload.phase="audit_flush"` — etiket-yorum-istemez).

**→ N2 #21 MADDE-6c (YENİ, owner-domain):** *"teardown-TAMAM + audit-flush-BAŞARISIZ → hangi-exit?"* Şu-an `1` (exception-yolu); adil-davranış "loud-fail" ile uyumlu-olabilir **AMA şu-an-belirsiz** — bilinçli-karar-gerekiyor (ör. teardown-tamamlanınca `2` + audit-degradation-bayrağı; ya da `1` kalır-dokümante).

**(a)/(b)-ayırtı AÇIK bırakıldı — HAKEM-RATİFİYESİ:** (a) QuickEdit (seçim-varken-Ctrl-C-kopyalar-SIGINT-göndermez) vs (b) SIGINT→`kill_fn`-yönlendiricisi + flush-çökmesi. **18-ms-WRITE_BLOCK-imzası (b)'yi-güçlendirir-kanıtlamaz** → SINIF-2-ayrımı bu-boot'tan çıkmaz. **Ayırt-edici-gelecek-testi:** stdout'ta `:155` "KeyboardInterrupt - graceful stop" satırının-varlığı.

**AM-T7-12 (YENİ, kalıcı):** *"Foreground-Ctrl-C-hijyeni: konsolda-seçim/QuickEdit-aktifken-Ctrl-C-sinyal-DEĞİLDİR — stop-öncesi-seçim-temizlenir/QuickEdit-devre-dışı-bırakılır; runbook'a-sabit-adım."* D70-launch-modu-ailesinin-ikinci-halkası.

**Zamanlama-dalga-okuması RATİFİYE:** `19:17:13-boot → 19:28:27-ilk-WB → 22dk8s-SESSİZLİK → 19:50:35–48.74-patlaması → 19:50:55-close-save`. "Kronik-ölüm" zayıfladı; "belirli-handle-çakışması-patlaması" güçlendi; **çift-süreç-hipotezine-kötü-haber** (o sürekli olurdu). H3-zaten-falsifiye (O4); H1/H2 aday. **Bir-sonraki-WRITE_BLOCK-RM-probe-payload'ı "kim-tutuyor" cevabını taşır** (N2 #21-madde-4 telemetrisi).
