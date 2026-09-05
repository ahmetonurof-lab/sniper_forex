## D73 · BULGU-3 ARİTMETİK-DÜZELTMESİ + `created_at` AD-TUZAKI + OVERWRITE 6. ÖRNEK (2026-09-03 17:53)

**Tetikleme:** D72-arb arşivi-koşarken-çekilen-kilit-inspeksyonu, **ratified bir-kaydın-türetme-yolunu-düşürdü.** §12.1: eski-sonuç → neden-yanlış → yeni-kanıt → revize-sonuç.

### Düşürülen-şey (yalnız-kanıt-yolu, sonuç-değil)
**ESKİ:** "`phase=\"startup\"` **3 sa 00 dk**; kanıt `created_at 1788444500.47` − boot `1788433696.66` = **10804 s**."
**NEDEN-YANLIŞ:** `created_at` **doğum-anı-değil.** `orchestrator.py:621-622` *(belgelediği-bir-tasarım)*: *"``heartbeat()`` refreshes ``created_at`` so a long-running but quiet process is not misclassified as stale."* Tüketici `:987` `(time.time() - data.created_at) > LOCK_STALE_SEC`; `:336-341` stale = **`created_at`-penceresi + ÖLÜ-PID**. ⇒ Bu-çıpadan-türetilen-süre **"process-ne-kadar-ayakta"**dır, **"sah-ne-kadar-takılı"** değil.
**İÇ-ÇELİŞKİ (ağırlaştırıcı):** düzeltmenin-yaptığı **aynı-cümle** (§H.4) zaten *"`created_at` heartbeat ile tazelemeye devam ederken"* diyordu — yani **önerme-doğru-yazılmış, sonra-ihlal-edilmişti.**

### Yeni-kanıt (canlı, 17:48:43)
| Gözlem | Değer |
|---|---|
| PID 3416 `StartTime` (doğru-çıpa) | `14:07:49` |
| `phase` | hâlâ `"startup"` |
| Geçen | **3 sa 40 dk 54 sn** |
| `created_at` / lock `mtime` | `1788446923.92` ≈ `17:48:12` / `17:48:43` |
| ⇒ kalp-atışı-periyodu | **~30 sn** (yeniden-yazım-kanıtı) |
| `phase="startup"` gözlem-dizisi | **14:58 · 15:29 · 17:08 · 17:48** (4/4) |

**REVİZE-SONUÇ:** **BULGU-3 ÖZÜ DURUYOR ve güçleniyor** — süre **3h00m → 3h41m**, çıpa **`created_at` → `StartTime` + gözlem-dizisi**. Derece/saha-terfisi **olduğu-gibi**. **Hakem-D72 §2 hükmü-geçersizleşmedi:** hüküm **sonucu** (progress-token) taşıyordu, sayıyı-değil; sayı-düzeltmesi **hükmü-güçlendirir** (yanlış-çıpa **tesadüfen-doğru** sonuç-vermiş; doğru-çıpa **daha-güçlü**).

### YAN-BULGU · `created_at` AD-TUZAKI (N2 #21 madde-5'e-girer)
`created_at` **heartbeat taşır, creation adlandırılır.** Tuzak **kanıtlıdır çünkü-ben-ona-düştüm:** saha-ajanı kilit-dosyasını-okuyup **doğum-anı** sandı ve **yanlış-süre** türetti; hata **ratified-üç-kayda** (§H.4 / D66 §12 / progress D72) **sızdı.** Çözüm-adayı: **`heartbeat_at` yeniden-adlandırması** ya-da **ayrı `boot_at`/`progress_token`.** ⇒ **"ayrı-ilerleme-kimliği" gereksinimi-bağımsız-olarak-tekrar-doğdu** ve **artık-iki-gerekçesi-var:** (i) `phase` ayrıştıramıyor, (ii) `created_at` **adıyla-yalan-söylüyor.**

### OVERWRITE-İMZASI · 6. ÖRNEK = EN-TEMİZ-BİÇİM
`17:53:44` O1-okuması: **`lines=10` · `size=3190` · `mtime=17:53:44`** — sayaçlar W1-mührüyle **birebir-aynı**, mtime **yine** ilerlemiş. Önceki-5-örnek **yalnız-boyut-sabitliği** gösteriyordu; bu **üçünü-birlikte**:
```
satır-sayısı SABIT (10) + boyut SABIT (3190 B) + mtime ILERLER  ⇒ yazar aynı-içeriği-yeniden-yazıyor
```
⇒ **D72(c) kırmızı-yeşil-lambası BUGÜN KIRMIZI:** *yeni-olay-yokken mtime ilerliyor* ⇒ **append-only henüz-kurulmadı.** N2 #21-madde-1 kabul-kriteri **canlı-ihlal** altında ve **kriter iş-headıyor** (yanlışsa-gösterebiliyor — bu-kriterin-ilk-olumsuz-çalışması-değil, **ilk-üç-değişkenli-ölçümü**).

### W2-SAYIMI (17:53:44, O1/O2/O3 altında)
**`0 SIGNAL/SWEEP · 1 ERROR · 3 WRITE_BLOCK` — DEĞİŞİM YOK.** Share-safe-okuma-altında-**yeni-WRITE_BLOCK YOK** (5-okuma) ⇒ **O4-H3 falsifikasyonu sürüyor**; H1/H2 **hâlâ-ayrışmadı**; BULGU-6 aşağı-çekme-derecesi **doğru-yönde**.

### D72-arb ile-birlikte-kapan
Adım-1 **5/5 doğrulanmış-ankor · 0 düzeltme** · `afe6668`≠`afe695b` (bayrak-doğrulandı; D53b-yalnız-`afe695b`) · **D25 teyitli** (`feed.update`/`warmup`/`M1CandleFeed(` → **0**, yalnız `fetch_m1`) · Adım-2 arşiv **185→220 satır** · Adım-3 **ADER-9 yürürlükte** · **E4/E5/E6 ALMA-BOŞLUĞU olarak-açık (uydurulmadı)** · **D72-ID-çakışması Hakem-kararında.**

### D73-ek · ANKOR-KÖKENİ AYRIŞTIRMASI — R1'in-bağımsız-değeri **5 → 3 ankor**
Mühür-öncesi-tam-depo-taraması (kapsam: `git grep` tracked + `docs/ results/ memory-bank/ .clinerules/`; **`data/`+`.git/` hariç** — rekursif-grep 30 sn zaman-aşımına-uğradı, ⇒ **negatif-sonuç sınırlı-kapsamlıdır**, §1.3) şu-ayrışmayı-verdi:

| Hash | Diskte-zaten | Köken |
|---|---|---|
| `a289a48d`, `68878d6`, `afe6668` | **YOK** | **LUNA-ÖZGÜN** — gerçek-bilgi-artışı (3/5) |
| `d87d1e1` | **VAR** `FOREX_DEPLOYMENT_CONTRACT_v1.md:5,273` ("Repository State: d87d1e1") | **KENDİ-KAYIT-YANKISI** |
| `b36c7c4` | **VAR** `activeContext.md:914/918/920/929` (COMMIT + push-onaylı) | **KENDİ-KAYIT-YANKISI** |
| `afe695b` | **VAR** `activeContext.md:1848/1854/1856/1922` (§9.5 exact pushed-set) | R1-listesinde-**yoktu**; Hakem-karşılaştırması |

⇒ **5/5 gerçek-commit (duruyor), AMA 2/5'i kendi-defterimizin-tekrarı.** R1 onları-tekrar-etmekle **içeriden-bir-şeyi dışarıdan doğrulamamıştır.** **ADER-9'a-İKİNCİ-ŞART-girer:** *çapa-var olması-yeterli-değildir; **çapanın-kaynağı-da-sorgulanır — kendi-kaynağın-yankısı-teyit-sayılmaz.***

### D73-ek-2 · AD-SARIKARŞILIĞI TUZAKLARI (üç-tane, hepsi-ölçüldü)
1. **`AUDIT_1_claude_luna.md` / `AUDIT_gemini_3_7_flash.md` diskte-VAR ama R1/R2 DEĞİL:** konuları **FVG-freshness / stale-ATR / Nexus `real_index` / C-v1.0-v1.1 araştırma-motoru**; **beş-hash-in-teki-yok** (0 eşleşme), Gemini'de **"watchdog" yok** (0 eşleşme). Üçüncü-sahte-ankor: `docs/# LUNA DİRECTİFİ — kabul + paralel yürüt.md` (106 S, roll-assignment, hash-yok). ⇒ **Luna/Gemini-adlı-disk-artefaktları-kaynak-değildir; elenmiştir.** **Benim-ilk-aramasında-`head -20` yüzünden-kesilen-liste bu-üç-dosyayı-gizlemişti** — **arama-hijyeni-dersi: `head` ile-kesilen-negatif-sonuç, negatif-sonuç-değildir.**
2. **Sürüm-uyuşmazlığı:** direktif **"Gemini 3.8 Flash"**, disk-artefaktı **3.7**. Disktekiler-kaynak-olmadığı-için **çelişki-çözülmez-kalır** ⇒ R2'nin-gerçek-araç-sürümü **BİLİNMİYOR**.
3. **Deployment-contract eskiliği (kapsam-DIŞI, yalnız-not):** contract repo'yu **`d87d1e1` (Aug-29)**'e sabitlemiş; güncel-HEAD **`0081c64` (Sep-03)** ⇒ **6 gün eskimiş sözleşme.** Dokunulmadı.

### D73-ek-3 · ARKA-PLAN-MUTASYONU TESPİTİ (§10.1)
`git status` → **`M AGENTS.md`, +17 satır**, bölüm `Aşama-5: Crash / Fix-Bildirim Üçlü Kanal Zorunluluğu`. **Bu-turda-ben-yazmadım** (AGENTS.md açılmadı) ve **watcher-değil** (watcher `QUARANTINED_20260901`). ⇒ **Bu-turdan-önceye-ait, commit-edilmemiş-düzenleme.** **Risk:** ilerideki-commit'te **istem-dışı-yolcu** (§9.5 set-değişimi = yeniden-yetki). **Dokunulmadı; bildirildi.**

### D73-ek-4 · KAPANIŞ-YOKLAMASI (18:50) ve O3-ZAYIFLIĞI
**Sayım (6. share-safe-okuma):** `lines=10 · 0/1/3` — **W1 mührüyle birebir aynı**; share-safe-altında **hâlâ yeni WRITE_BLOCK yok** ⇒ O4-H3 falsifikasyonu sürüyor, H1/H2 ayrışmadı. **Overwrite 7. örnek:** `size=3190` sabit, `mtime 17:53:44 → 18:50:28` ilerler, yeni olay yok ⇒ **D72(c) lambası aralıksız KIRMIZI.** **Kilit 5. gözlem:** `phase="startup"`, `hb_age 20 s` ⇒ **~30 sn heartbeat bağımsız-teyitli**; BULGU-3 süresi **3h41m → 4h43m**, öz duruyor.
**O3-ZAYIFLIĞI (kendime-kayıt, ADER-9'un-en-rahatsız-edici-uygulaması):** dokunma-satırı-zaman-damgaları (`17:49:10`, `18:02:40`) **agent-tahminidir, saat-ölçümü-değildir** — agent'ın-kendi-saati-yok. Olay-mühürlerini-`audit_mtime`-ile-karşılaştırmak **bu-nedenle-yanıltıcıdır**; **O3'ün-kendi-kendine-kanıt-değeri düşük.** Çözüm-adayı: `audit_read.py` dokunma-satırını **kendisi-yazsın** (machine-timed) ⇒ O3 kendiliğinden-doğrulanabilir-olur. **Yapılmadı** (script-yetkisi-yok); **N2 #21-madde-6 adayı.** ⇒ **Çapa-eksikliği kendi-kurallarımızda-da-var.**

### D73-ek-5 · DEVİR-NOTU-BÜTÜNLÜĞÜ — üçüncü-yetim-artefakt **HİÇ VAR OLMAMIŞ** (§12.1/§13.5)
Gelen-devir-özeti **üç** yetim-artefakt sayıyordu: `audit.jsonl.tmp` · `orchestrator.lock.tmp` · **`orchestrator.lock.3944.tmp`**. Ölçüm:
| İddia | Gerçek |
|---|---|
| `state/audit.jsonl.tmp` | **VAR** — 1483 B, Sep-1 23:59; ilk satır `MT5_CONNECT`, son satır `SHUTDOWN {"exit":1,"reason":"run_exception:PermissionError"}` |
| `state/orchestrator.lock.tmp` | **VAR** — 68 B, Sep-1 23:59; içerik **`{"pid": 16984, ...}`** ⇒ **3944 ile-ilgisi YOK** |
| `state/orchestrator.lock.3944.tmp` | **YOK** — `find . -name '*3944*'` (`.git` hariç) → **0 sonuç**; `state/` tam-listesinde de yok |

**NEDEN-YOK (kayıp-değil, tasarım-gereği):** 3944-kilidi **`.tmp` adıyla-değil, `state/orchestrator.lock` CANLI-YOLUNDA** kayıtlıydı (§H.1 alıntısı: `{"pid":3944,"created_at":1788381955.53,"phase":"startup"}`, mtime-age 798 s, PID DEAD). PID 3416 boot'u (14:07) bu-kilidi **meşru takeover ile EZMİŞTİR** — yani §H.1'in **"takeover'ın-gerçek-kanıtı"** dediği-olay tam-da-budur: **kanıt, üzerine-yazılarak-tüketilen-bir-kanittır.**
**SONUÇ-1 (kanıt-seviyesi-düşüşü, §3):** 3944-delili artık **yalnız-düz-yazı-alıntısıdır** (kanıt-hiyerarşisinde **seviye-6**), **artifact (seviye-5) değildir.** §H.1'in **"ELLE SİLİNMEZ"** emri **fiilen-geçerli-değildir** — silinme-bizim-tarafımızdan-olmadı, **takeover'ın-kendi-doğal-sonucudur**; ama emir **yanlış-yere-yazılmıştır** (korunacak-bir-dosya-yoktu, korunacak-anlık-değer-vardı ve o-değer-alıntılanmıştı).
**SONUÇ-2 (devir-hijyeni, KURAL-ADAYI):** devir-özetindeki-dosya-adları **kanıtlanmadan-yazılmıştır** — üçüncü-ad **uydurma-etiket**tir (`orchestrator.lock` + `pid-3944` birleşimi). ⇒ **Aday-kural: "Devir-notundaki her dosya-adı ya `ls`-çıktısıyla ya-da `git status`-çıktısıyla eşlenmiş-olmalı; eşlenmemiş-ad 'iddia' olarak-etiketlenir."** Bu, §13.5'in-depolama-tarafıdır.
**Dokunulmadı:** iki-gerçek-yetim **olduğu-gibi-korundu**, yenisi-üretilmedi, 3944-için **sahte-artefakt-uydurulmadı.**

### Boundary (D73 turu)
Kod **DOKUNULMADI** (`src/ tests/ index.json` diff **boş**) · commit **YOK** (reflog teyit: HEAD hâlâ `0081c64` 00:18, **bana-ait-değil**) · push **YOK** · pid **3416 CANLI / DOKUNULMADI** · `.env` **DOKUNULMADI** · `index.json` **YENİDEN-ÜRETİLMEDİ** · lock **SİLİNMEDİ** · yetimler **KORUNDU** · D68-stitch **KORUNDU** · **D64 `8b18f70a` DEĞİŞMEDİ** ✓ · `sweep_detection 3cbc74fc` **DEĞİŞMEDİ** ✓ · 65k-parite **ikinci-boot-a-kadar-BLOKE**.
