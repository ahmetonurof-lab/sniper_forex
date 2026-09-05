## D74 · HAKEM-HÜKMÜ-UYGULAMASI + SAHA-OLAYI (19:17 ikinci-boot) + ÜÇ-ÖZ-DÜZELTME
*Tarih: 2026-09-03 · Hat: D72-arb kapanışı → hüküm → uygulama sırasında gelişen canlı olay.*

### 0. HÜKÜM-KABUL EDİLDİ (RED-yok)
`(A)` hakem-öz-düzeltmesi-6 (10804-s-üretimi-hakem-tarafından-üretilmişti) · `(B)` AGENTS.md bağlı-dönüşüm + AM-T7-10 · `(C)` seviye-6-tanımlı-mühür + AM-T7-11 · `(D)` N2 #21 madde-6b · `§5` **`D72-env`/`D72-arb` ayrımı KABUL** + ADER-11 · `§6` arşiv **271S/`9f057ca6` ratifiye** + **ADER-9-v1.1** (çapa-özgünlüğü) · `§7` R1/R2-düz-yazısı Reis-elinden-gelecek, ben append-only eklerim.

### 1. OLAY-1 · `phase` BİR **SABİTTİR**, TAKILI-BİR-DURUM-DEĞİL (kod-çapalı, canlı-teyitli)
Hükmün `(A)` maddesindeki yeni-çıpayı (`StartTime`→`14:58`→`≥4h43m`) koddan-doğrularken mekanizma-çöktü:

| Çapa | Gerçek |
|---|---|
| `orchestrator.py:920` | `data = LockData(pid=os.getpid(), created_at=time.time(), phase="startup")` — **`_write()` içinde, her-yazımda-sabit-literal** |
| `_write()` çağırıcıları | **yalnız ikisi:** `acquire()` `:758` ve `heartbeat()` `:840` |
| `git grep '\.phase\s*='` (src/, tests hariç) | **0 sonuç** — kilit-fazı **hiçbir-yerde mutate edilmiyor** |
| `StartupPhase` `:371-382` | `S0_CONFIG … S11_READY` — **11-durumlu gerçek durum-makinesi MEVCUT** |
| `phase=StartupPhase.X` (14-site, `:1165-1565`) | **`StartupResult(...)` kwargs'ıdır** — yani **bellek-içi-dönüş-değeri**, kilit-değil |
| `:1505-1560` | gerçek faz **audit'e** yazılıyor: `EventType.STARTUP {"phase":"S9"/"S11","verdict":…}` |

⇒ Kilit-dosyasındaki `phase` **inşası-gereği-bilgi-taşımayan-bir-alandır.** "Takılı" değil; **ilerleme-kapısı-hiç-yazılmamış.**
**CANLI-KARŞI-ÖRNEK (saat-çapraz-doğrulamalı):** audit `19:17:25`'te `S11 / SAFE_START` **tamamlandı**, `19:17:26`'da `SAFETY gate=closed reason=startup_SAFE_START`; kilit `19:19:26`'da **hâlâ `phase="startup"`**. ⇒ **Tamamlanmış-startup + lock-"startup" = alanın-durum-olmadığının-doğrudan-kanıtı.**
**BULGU-3 YENİDEN-ĐFADE (kök-değişikliği):** eskisi *"phase 4s43dk ilerlemedi ⇒ startup↔wedged ayırt edilemiyor"* — **ölçülen-şey bir-literal'in n=5 tekraruydu.** Doğrusu, **daha-ağır:** *operatörün-güvendiği-teşhis-alanı inşası-gereği sabittir; hiçbir-şeyi ayırt-edemez.* Süre-iddiası (**4h43m**) **tamamen düşer** — geriye-süre-değil, **alanın-anlamsızlığı** kalır.
**N2 #21 madde-5 YENİDEN-KAPSAM (§2.2):** madde *"ayrı-ilerleme-kimliği icat-et"* diye yazılmıştı; **kimlik ZATEN VAR (`StartupPhase`) ve audit'e yayınlanıyor.** Doğru-kapsam: **`StartupPhase`'i `LockData`'ya taşımak** (`_write()`'a gerçek-faz-parametresi) — yeni-soyutlama-değil.
**N2 #21 madde-1 KABUL-KRİTERİ YÜKSELDİ:** benim-övdüğüm-kriter *("yeni-olay-yokken mtime ilerlememeli")* **zayıfmış** — asıl-kriter **"önceki-satırlar yeni-boot-sonrasında-da durmalı"**. Aşağıdaki-olay bunu ihlal-etti.

### 2. OLAY-2 · 19:17:10 İKİNCİ-BOOT + **AUDIT-TRUNCATION (gerçek-veri-kaybı)**
`18:51:08` (makine-damgası) okuması: `lines=10 · size=3190 · 0/1/3`. `19:18:41` okuması: **`lines=6 · size=1622 · 0/0/0`** — içerik **yepyeni-boot-dizisi** (`MT5_CONNECT`, `STARTUP`×4, `SAFETY`).

| Ölçüm | Değer |
|---|---|
| Eski-sahip | **PID 3416 — `Get-Process` count **0**, ÖLDÜ** |
| Yeni-sahip | **PID 11476**, `StartTime 19:17:10`; kilit-sahibi |
| "Çift-instance" mı? | **HAYIR** — `crash_log` satır-3: `self=11476 (.venv python)`, **`parent=16660 (.venv python)`** ⇒ **tek-boot, venv-launcher→child.** Yanıltan: `Get-CimInstance` iki-python gösterdi. |
| Launch-yolu | `.venv/Scripts/python.exe … run_production.py` — **`nohup.exe` DEĞİL** (3416'nın parent'ı `nohup.exe` idi, crash_log satır-2) ⇒ **§C/graceful-stop/close-save artık üretilebilir-olabilir** |
| `d66_boot_stdout.log` | **14:07:56'da durdu, değişmedi** ⇒ **bu-bootu-ben-başlatmadım** (Reis-olası) |
| Safe-mode | `S11 SAFE_START` + `safe_reasons[0]="safe_mode_persisted"` ⇒ **§7.2 "persisted-safe-mode → degraded boot" ÇALIŞIYOR** ✓ (sessiz-resume YOK) |
| **KAYIP** | 3416-devrine-ait **10 satırın tamamı**: 3 WRITE_BLOCK + 1 ERROR + **3416'nın SHUTDOWN kaydı (varsa)** |
| **KURTARMA** | `state/audit_prev_2026-09-03.jsonl` = **9 satır** (MT5_CONNECT, STARTUP×4, SAFETY, WRITE_BLOCK, ERROR, WRITE_BLOCK) + 10.satır (`WRITE_BLOCK 15:51:32 retries=8`) **touchlog-dökümünde yazılı** ⇒ **10/10 metin olarak kurtarılabilir, artifact olarak değil** |
| **YENİ-KOPYA** | `results/D74_audit_snapshot_2026-09-03_1919.jsonl` — **1622 B, sha256 `184a95c450713eca20c6519e…`, kaynakla BAYT-ÖZDEŞ ✓** (`state/`-e dokunulmadı) |

⇒ **D72(c) lambası "kırmızı"dan "yanıyor"a geçti:** mtime-churn değil, **boot-üstüne-boot-yazımı ve tarih-imhası** gözlemlendi. **§18 audit-continuity kırıldı** ve **3416'nın nasıl-öldüğü artık kanıtlanamaz** — bu, turun-en-pahalı-maliyetidir.

### 3. ÖZ-DÜZELTME-1 · BULGU **(D) GERİ ALINIR** (6b talebi kısmen-gereksiz)
Ben *"dokunma-damgaları benim tahminim, araç kendi satırını yazmıyor"* dedim ve **aracı açmadan** mekanizma iddia ettim. **`audit_read.py:14-23` `log_touch()` OKUMADAN ÖNCE makine-damgalı satırı KENDİ yazıyor** (`datetime.now(utc)` + local). ⇒ **(D) yanlıştı; 6b'nin istediği davranış BU ARAÇTA ZATEN VAR.** Doğru-daraltılmış-kalan: **elle-yazılan açıklama-satırları** tahmindir, **makine-satırları yetkilidir**, ikisi-ayrıştırılmalıdır. Kanıt: benim-el-satırım `18:02:40` dedi; aynı-okumanın makine-satırı `18:51:08` — **49 dk sapma.** 6b ya düşürülsün ya **"elle-damga-yasak, argv-notu-zorunlu"** biçiminde yeniden-yazılsın. **ADER-9 burada bana döndü: aracı okumadan araç-hakkında-mekanizma-iddia-etmiş oldum.**

### 4. ÖZ-DÜZELTME-2 · KURTARMA-KOPYAM **BAYT-ÖZ-DEĞİLDİ**
İlk kopya `io.open(...,'r')` ile alındı → **1616 B vs 1622 B**: 6-satırlık **CRLF→LF çevirisi**. Hash-karşılaştırmasını sessizce kırardı. **Düzeltme:** `'rb'/'wb'` + Python-içi `sha256` çift-tara; **canlı-dosyaya `sha256sum`/`cp` VURMA** (O2). ⇒ **Kural-adayı: "kanıt-kopyası ikili-kip alınır; metin-kipi satır-sonu-bozar."**

### 5. HAKEM-§1 ARİTMETİK-BAYRAĞI (sayı-doğru-formül-yanlış → artık-her-ikisi-de-düştü)
Hüküm-formülü `gözlem-sonu − 14:58 ≥ 4h43m`. Ölçüm: `18:50 − 14:58 = **3h52m**`; `4h43m` ise **boot-çapasından** (`18:50:48 − 14:07:49`) geliyor — **formül ile sayı 51 dk ayrışıyor**, ve `14:07:49`→`14:58` arası **gözlem-yok** (50-dk boşluk). Yani hüküm kendi yeni-metodoloji-maddesini ihlal ediyordu. **AMA artık-konuşuz:** §1'deki-gibi `phase` sabit olduğu-için **bu sayıların hiçbiri "takılı süre" ölçmüyordu.** Doğru-kayıt: **süre iddiası YOK; alan iddiası VAR.**

### Boundary (D74 turu)
**Kod-değişikliği YOK** (`git diff src/ tests/ index.json` boş) · commit YOK · push YOK · **yeni-boot-a dokunulmadı (Ctrl-C/kill YOK — Reis yetkisi)** · `state/` **yazılmadı** (kopya `results/`-e) · 3416-yetimleri duruyor · D64-dokunulmadı · **tek-yapıcı ilkesi korundu: hiçbir satır silinmedi, üstü çizildi veya eklendi.**
