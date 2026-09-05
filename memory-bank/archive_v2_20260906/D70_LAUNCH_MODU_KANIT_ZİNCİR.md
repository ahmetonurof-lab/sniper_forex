## D70 · LAUNCH-MODU-KANIT-ZİNCİRİNİ-BELİRLER (sistematik-ders · 2026-09-03 15:30 · Hakem K3-hükmü)

**Ders-cümlesi (kalıcı):** **"§C graceful-stop, nohup-tarzı launch altında FİZİKİ olarak imkânsız."**
Bu-ders D58'i tamamlar: D58 *"nohup altındayken Ctrl-C'nin gerçek-olmadığı"* → D70 *"nohup altındayken sinyal-iletimi fiziki olarak mümkün-değil; dolayısıyla o-instance'ta hiçbir graceful-kanıt aranmaz."* **Foreground-yalnız-kuralı** bu-biçimiyle kalıcılaşıyor.

**Neden-sistematik (tek-boot-olayı-değil):** close-save'ın üretimde **tek-girişi** `shutdown()` (`orchestrator.py:1661`); periodic-save YOK (kaynak-kodu kendi-yorumuyla itiraf ediyor). Yani **eksik-olan-bir-özellik-değil, eksik-olan-tek-yolun-kendisi.** Launch-modu yanlış seçildiğinde §C / §1.6 / D58-kapanışı **hepsi-birden** erişilemez olur — **üç-kapı-tek-anahtar.**

**Ölçülen-kanıt:** `crash_log.txt` satır-2 `parent: "19088: C:\Program Files\Git\usr\bin\nohup.exe"` (pid 3416) — append-only kanıt-mekanizması launch-modunu **kendi-kendine kaydediyor**; yani teşhis-mekanizması zaten mevcut, sadece okunmamıştı.

**Yeni-ölçülmüş-kural (K1-RED gerekçesi ii):** **"taskkill = audit-orphan üretir."** `save()` tmp-yazar → `replace()` patlarsa tmp-yetim-kalır (BULGU-7'nin tam-mekanizması). Hard-kill, D68-kayıp-sınıfını gizlemek-bir-yana **yetim-artefakt-la çoğaltır.**

**Uygulama-kararı:** **AM-T7-7** (checklist v1.4 §H.1) + boot-runbook'una **ZORUNLU iki alan**: `launch_mode ∈ {foreground-console, nohup, other}` ve `§C_producible ∈ {yes, no}` — beklenti-kaydı **önceden** yazılır, sonradan-keşif-değil (§H.3).

**Numaralandırma-düzeltmesi (§12.1, görünür):** Cline'ın v1.3'ünde AM-T7-7=audit-copy / AM-T7-8=konsol idi; **Hakem-hükmü tersi** → v1.4'te **takas edildi**, takasın-kendisi §H.1'de kayıtlı (tarihçe sessiz yeniden-yazılmadı).

---
