# FIX-SPEC — T0#7 LOCK-RENAME WinError 5 (N2 #17 aday-seti)

> **[v1.2 RATIFIKASYON NOTU — Cline, 2026-09-03]** Reis/Hakem bu spec'i **v1.2 olarak RATİFİYE etti** (A1–A11 değişiklik-seti): (A1) Katman-3 **ZORUNLU**; (A2) okuma-triajı (B1 deliği); (A4) her `_write` çağrısında WRITE_BLOCK; (A6) Ek-A sağlamlaştırma (argtypes/restype + ERROR_MORE_DATA-döngüsü + non-NULL-reasons + doğru-struct); (A7) +3 fikstür; (A8) shutdown-flush → crash-log-dump; (A9) LOCK_CORRUPT + kayıt-PID-doğrulaması; (A10) rapor-notu. **İcra tamamlandı** — detay: `memory-bank/progress.md` N2 #17 kaydı. Bu dosyanın gövdesi v1.1 olarak korunur (Baş Mühendis dokümanı; değiştirilmedi). v1.2 verbatim metni §13.5 transfer-ihtilafı nedeniyle masada kaldı — yeniden-teslim-edilirse buraya eklenir.

**Yazan:** Baş Mühendis (GLM — bu masa) · **Tarih:** 2026-09-03 · **Sürüm:** v1.1 (repo-kanıtı eklendi)
**Statü:** TASLAK → Reis ratifikasyonu + Cline implementasyonu + operatör kanıt-raporu bekler
**Kanıt-tabanı:** SESSION_CHECKPOINT 2026-09-02 (§1, §5-A, §6-Atomics, §9) · N2 #15-b (`3eaf7e7`: K1 retry 8/~6.4s + PID-unique tmp + WRITE_BLOCK + exhaustion→safe-mode) · T0#5/T0#6 boot-imzaları · OS-kanıt: Defender-5007 event @ 2026-09-02 18:05:16 (`Exclusions\Paths\...state = 0x0`) · **[v1.1] repo-kaynak-kodu @ `5b23da5` (bu masada klonlandı, 2026-09-03 — §6 kod-kanıt ekleri)**
**Öncelik:** Channel-A — T0#7'nin açılış-kapısı. Sistem DOWN; canlı-CBDR penceresi kaçtı; T0#7 bu spec implementasyonu olmadan AÇILMAZ.

---

## 0. HÜKÜM ÖZETİ (bir paragraf)

T0#5 ve T0#6, özdeş imzayla (lock-rename WinError 5) çöktü — ikincisi Defender-exclusion **AKTİF** iken. Bu, rastgele-AV-yarışı değil, **deterministik bir açık-handle**'dır. Windows semantiği: `os.replace` = `MoveFileExW(REPLACE_EXISTING)`; hedef dosyada **FILE_SHARE_DELETE içermeyen açık bir handle** varsa → `ERROR_ACCESS_DENIED` (WinError 5). N2 #15-b kaynak-tarafını (tmp) PID-unique ile kapattı; başarısızlık **hedef-tarafında** (orchestrator.lock). Tutucu AV-dışı üç adaydan biri: (a) in-process handle-sızıntısı, (b) harici AV-dışı tutucu (sync-agent/backup-filter), (c) D53b resurrect-artığı. **Kanıtsız fix kör atıştır** → spec: teşhis-probu (Katman-1) + in-process handle-disiplini (Katman-2) + lock için rename→in-place strateji (Katman-3) + nonfatal heartbeat (Katman-4) + audit senkron-flush (Katman-5). T0#7 yalnız Katman 1+2+4+5 ile açılır.

---

## 1. KÖK-NEDEN ANALİZİ (kanıt-zinciri)

- **F1 — Hata hedef-tarafında:** N2 #15-b tmp'yi PID-unique yaptı (src-çakışma KAPANDI, `44d99a1` push-kanıtlı). T0#5/T0#6 başarısızlığı rename'in hedefi olan `state/orchestrator.lock` üzerinde. → Sorun: hedefte sürekli açık handle. (Python stdlib `open()` Windows'ta FILE_SHARE_DELETE paylaşımını garanti etmez; ampirik Windows kuralı: hedef açıkken `os.replace` PermissionError verir — **kendi sürecimizin okuma-yolu bile bloklar**.)
- **F2 — Deterministik:** T0#5 (17:50, retries=8/~6.4s tükenişi → exit=1) + T0#6 (18:1x, exclusion-AKTİF, PID 15784) aynı imza. ~6.4s'lik retry-penceresini İKİ KEZ yenmek, tutucunun pencere-boyunca hiç bırakmadığını gösterir. Yarış-hipotezi çürür.
- **F3 — Defender dışlandı:** Exclusion OS-kanıtlı aktif; iki-boot-özdeş-imza intibası zaten checkpoint'te kayıtlı. Kalan adaylar:
  - **(a) In-process handle-sızıntısı:** takeover/heartbeat **okuma-yolunda** kapatılmamış bir `open()` (monitor/liveness thread'i, preflight dalı). Sürekli-tutma = sızıntı (yarış değil).
  - **(b) Harici AV-dışı tutucu:** OneDrive/Dropbox/GDrive sync-agent, üçüncü-parti backup-filter, Search-Indexer varyantı.
  - **(c) D53b resurrect-artığı:** Startup-lnk zinciri watcher'ı diriltirse state/ dosyalarını açabilir (§8 N2 #15-b sonrası adım-2: karantina-taraması).
- **F4 — Kronoloji-ipucu (a)'yı güçlendirir:** T0#5 boot'ta **takeover-rename BAŞARDI** (~17:35, `{"pid":2456, "phase":"startup"}` yazıldı, canlı-python ✓) ama ~17:50'de heartbeat-rename PATLADI → tutucu boot'tan SONRA geldi veya okuma-yolu boot-sonrası devreye girdi. Ayrıca T0#5'te `shutdown_snapshot` da ERROR → tıkanma tek-dosya değil, **state/ yazma-yolu geneli** → handle-sızıntısı pattern'i hem lock'ta hem snapshot-hedeflerinde (okuma-yolları birden fazla dosyada sızdırıyor olabilir).
- **F5 — İkincil delik:** T0#6 terminal-audit-event'ler flushed-olmadan kayboldu (buffer-hipotezi DOĞRULANMADI). B1b timer-flush crash-anında yetmiyor → kanıt kaybı ayrı düzeltme-alanı (Katman-5).

> **Hüküm-disiplini:** F1–F5 olgu-kurgusudur; adaylar arasında isim KOYMAZ. İsim koyma yetkisi Katman-1 probunun audit-satırındadır. ("Sayım ≠ kanıt; -rs ile kimlik doğrulanır.")

---

## 2. PROGRESS.MD DÖRT-ADAYINA HÜKÜMLER

| # | Aday | Hüküm | Gerekçe |
|---|------|-------|---------|
| 1 | **Handle-holder teşhisi** | **BENİMSENDİ — Adım-1, ZORUNLU** | F3 üç-adaylı; kanıtsız fix kör atış. Kök-neden adı prob-kanıtıyla deftere girer |
| 2 | **Lock-write stratejisi** | **BENİMSENDİ — lock için rename→in-place** (Katman-3) | Rename hedefte DELETE-erişimi ister; in-place truncate-write yalnız WRITE ister. In-process-okuyucu senaryosunda belirleyici fark: R+W-paylaşımlı (DELETE'siz) handle rename'i bloklar, in-place yazmaya karışmaz |
| 3 | **Retry-vs-nonfatal** | **NONFATAL — heartbeat-yazma hatası; D11 ownership-loss FATAL kalır** (Katman-4) | Heartbeat liveness-reklamıdır, kitap-yazımı trade-bütünlüğü değildir. Süreç yaşasın, olay deftere düşsün; tutucunun adı kayda geçsin |
| 4 | **State-dir-relocation (D18 env-only)** | **ERTEDİLDİ — koşullu** | Prob harici sync-agent ADINI verirse ve exclusion uygulanamıyorsa taşınır. Kör taşınma kanıt-zincirini koparır + "aynı-koşulda-3.-boot" zehirlenmesini tekrarlar |

---

## 3. SPEC — BEŞ KATMAN

### Katman-1 — Handle-holder probu (ZORUNLU)
1. İlk hatalı rename/write denemesinden sonra (retry-tükenişini BEKLEMEDEN, ilk denemeden hemen sonra): **Restart-Manager API** ile hedef-dosyanın tutucuları listelenir — `RmStartSession → RmRegisterResources(hedef-yol) → RmGetList → {PID, uygulama-adı} listesi → RmEndSession`. **ctypes/stdlib-yalnız**; `handle.exe` dağıtımı ve admin gereksiz (kod-iskeleti Ek-A).
2. Sonuç audit-event'e gömülür:
   `{"event":"WRITE_BLOCK","target":"orchestrator.lock","holder_pids":[…],"holder_names":[…],"probe":"restart_manager","probe_rc":0}`
3. **Karar-ağacı:** Kendi PID'imiz listede → (a) in-process sızıntı KANITLANDI → Katman-2 kök-neden, uygulanır. Başka süreç adı → defter-satırı → Aday-4 (relocation/harici-exclusion) bu isimle değerlendirilir. Prob-hatası (RM bazı yollarda ERROR_ACCESS_DENIED dönebilir) da event'e düşer — **sessiz-geçiş YOK** (D54 ruhu).
4. Prob 1 kez/boot + her WRITE_BLOCK'da yeniden (üretime ağır yük değil: yalnız hata-anında koşar).

### Katman-2 — In-process handle-disiplini (ZORUNLU)
1. Lock'a (ve rename-hedefi TÜM state dosyalarına) erişim **tek context-manager'dan**: `open → read/parse → close` SENKRON; reader/writer bir `threading.Lock` ile serileştirilir.
2. **Kod-invariantı (yeni):** "Rename-hedefi bir dosyanın açık-handle ömrü, kendisini açan fonksiyonun kapanış-parantezini aşamaz." İhlalde LOUD-warn + audit-event.
3. **Review-hedefi #1:** T0#5'in takeover-yolu (PID-ölü takeover → yeni-lock yazımı) + heartbeat-monitor okuma-dalı — F4 kronolojisi gereği sızıntı en olası orada. İkincil hedef: schedule/bias okuma-yolları (shutdown_snapshot ERROR'unu açıklar).
4. Birim-test: sızıntı-avcısı — testte lock-hedefini açıp-kapatmayan bir yardımcı çağrısı yazılır, LOUD-warn'ın düştüğü assert edilir.

### Katman-3 — Lock-write stratejisi (ÖNERİLİR; T0#7 prob-sonrası karar-turası ile birlikte)
1. **LOCK dosyası için:** tmp+rename → **in-place truncate+write+flush+`os.fsync`**. Diğer state-dosyaları (schedule/bias/audit) **D18 atomic tmp+rename'da KALIR** — lock farklı varlık-sınıfıdır: ~30-byte kitap-tutma, yırtılabilirlik-toleranslı, parse-guard'lı. (D18 kapsamı bu spec'le lock için açıkça DARALTILIR — defter-satırı: D56.)
2. **Yırtık-lock kuralı:** Parse-edilemeyen lock → mtime-yaş ≥ `LOCK_STALE_SEC` (900) ise takeover izni; altındaysa bekle. mtime, yarım-yazmadan sağ-kalır (güvenilir fallback kimlik).
3. **Güçlü-alternatif (Ek-B, prob-sonrası karar):** Değişmez-lock — PID bir-kez yazılır, liveness = `os.utime` heartbeat; içerik asla yeniden yazılmaz → yırtık imkânsız. Bu masanın notu: utime da handle-paylaşımına duyarlı olabilir; Katman-1 prob verisi gelmeden araya girmez.

### Katman-4 — Nonfatal heartbeat (ZORUNLU — boot-kapısı bileşeni)
1. **Edinme-fatal / yenileme-degraded ayrımı (yeni sözleşme):**
   - **Boot-takeover yazması** başarısız → boot BAŞARISIZ (lock edinmeden koşmak yok — fail-fast). K1 8-attempt bütçesi burada kalır.
   - **Runtime-heartbeat yazması** başarısız → kısa-retry (3 deneme / ~2.4s) → `WRITE_BLOCK` (+Katman-1 prob verisi) → **`lock_write_degraded=true` — SÜREÇ YAŞAR** → bir-sonraki heartbeat tick'inde tekrar dener. SHUTDOWN YOK.
2. **Tek-örnek güvenlik-ispatı:** Bayat-lock'taki son-başarılı-PID **bizim canlı PID'mizdir**; yeni-boot PID-liveness kontrolünde CANLI PID görür → takeover-koşulu (ölü-PID) sağlanmaz → D35 korunur. Degraded mod tek-örnek ihlali **üretmez**.
3. **FATAL kalan tek yol:** D11 ownership-loss — okunan lock'ta canlı-**BAŞKA**-PID. K1-exhaustion→exit=1 yolu bu spec'le KALDIRILIR; §6-Atomics kuralı revize edilir: *"tmp+rename (diğer state-dosyaları) yalnız PID-unique tmp ile; lock in-place; exhaustion → WRITE_BLOCK(+prob) → degraded; WinError 5 fatal değil; fatal yalnız D11 ownership-loss."*
4. **D46 invaryantı korunur:** `backoff_max < LOCK_STALE_SEC (900)` — degraded-tekrar-denemeler tick-bazlıdır, ladder'i genişletmez.

### Katman-5 — Audit-kanal güvenilirliği (ZORUNLU)
1. `WRITE_BLOCK` / `ERROR` / shutdown-yollarında audit-buffer **SENKRON flush + fsync** — B1b timer-flush crash-anında yetmez (T0#6 kanıtı).
2. **Crash-class eventler** buffer'a değil doğrudan diske (acil-yol).
3. `shutdown_snapshot` hatası kendi audit-satırını düşürür — asla sessiz (T0#5: gelişim diske gitmedi).

---

## 4. T0#7 BOOT KAPISI (kanıt-değerini koruma — "aynı-koşulda-3.-boot" zehirlenmesin)

1. **ZORUNLU set: Katman 1+2+4+5** implementasyonu + birim-testler. Katman-3 önerilir; **4 olmadan boot YOK** — üçüncü kez aynı çöküş, soak-değil vakit-kaybı üretir.
2. **Birim-test fikstürleri (yeni):**
   - `test_lock_collision`: hedefe açık-handle tut → yazma-yolunun **degraded moda düştüğünü** + prob-event'inin düştüğünü + sürecin **ölmediğini** assert.
   - `test_torn_lock`: yarım-json + taze-mtime → bekle; yarım-json + 900s-mtime → takeover.
   - `test_ownership_loss_fatal`: canlı-başka-PID → fatal-1 yolunun korunduğunu assert.
   - ("Koşulmamış test yazılmamış testtir.")
3. **Operatör-raporu (boot-ÖNCESİ zorunlu girdiler):**
   - `git rev-parse HEAD` + `git log --oneline origin/main..HEAD` (BOŞ olmalı) + `git tag -l`
   - `tools/*.QUARANTINED_*` tarama-sonucu (F3-c)
   - **T0#6 TAM-log** (head/tail-penceresi değil — §13.5 dürüstlük-dersi)
   - progress.md fix-adaylar-bölümü (bu spec ile çapraz-kontrol — sapma varsa defter + bu masa)
   - **Repo-yolunun sync-agent kapsamı** (OneDrive/Dropbox/GDrive altında mı? — F3-b'nin en hızlı elenme/ışınlanma testi)
4. **Boot-sonrası ilk-2-saat kararı:** WRITE_BLOCK yok → Katman-3 kalıcı-turası + normal soak-izleme (§18 ölçütleri). WRITE_BLOCK var → prob verisindeki **adlı-tutucu** ile Aday-4/harici-fix kararı — bu sefer isimli-kanıtla.

---

## 5. PROVENANCE VE SINIRLAR

- Bu spec v1.0 **repo-dışı masada** yazıldı; **v1.1'de repo bu masaya klonlandı** (`https://github.com/ahmetonurof-lab/sniper_forex` → `/home/z/my-project/sniper_forex`, HEAD=`5b23da5` doğrulandı) — §6 kod-kanıt ekleri eklendi. Kalan repo-dışı kanıtlar: T0#5/T0#6 **tam stdout-logları** + Windows-yerel `state/` + pushlanmamış `3acb7cd` defter-yükü (checkpoint'in "adaylar progress.md'de" referansı Windows-YEREL progress.md'ye işaret eder — remote kopyada yok, son satır 870 = T0#5 BOOT kaydı). **Cline, implementasyon-öncesi** yerel progress.md aday-bölümü ve T0#5/T0#6 tam-loglarıyla çapraz-kontrol eder; sapma → defter + bu masa.
- **[v1.1] Kod-inceleme sınırı:** src/live taranması v1.1'de yapıldı (sızıntı-avı + subprocess taraması, §6.4); **runtime-kanıt (RM-prob çıktısı, T0#6 tam-log) hâlâ operatör-girdisi.**
- **Rol-zinciri değişikliği:** Bu masanın rolü Hakem'den **Baş Mühendis**'e yükseltildi (Reis, 2026-09-03). `rapor→sentez→hüküm` zinciri, Hakem-RED veto hakkı (§5.1) ve push-yetki-sınırı (§9.2, hash-bound §9.5) **DEĞİŞMEDİ**.
- **N2 numaralandırması:** Bu spec implementasyonla **N2 #17** olarak deftere girer; push Hakem hash-bound onayıyla.
- Açık-soru ③ (kış-DST probe) bu spec'in kapsamı dışında — N2 #15-b sonrası ayrı deney olarak ertelenmemiş, sırası korunmuş.

---

## EK-A — Restart-Manager prob iskeleti (Cline sağlamlaştırır; stdlib-yalnız)

```python
import ctypes
from ctypes import wintypes as wt

class RM_UNIQUE_PROCESS(ctypes.Structure):
    _fields_ = [("dwProcessId", wt.DWORD), ("ProcessStartTime", wt.FILETIME)]

class RM_PROCESS_INFO(ctypes.Structure):
    _fields_ = [("Process", RM_UNIQUE_PROCESS),
                ("strAppName", ctypes.c_wchar * 256),
                ("strServiceShortName", ctypes.c_wchar * 64),
                ("AppStatus", wt.DWORD),
                ("TSSessionId", wt.DWORD),
                ("bRestartable", wt.BOOL)]

CCH_RM_SESSION_KEY = 32

def find_file_holders(path: str) -> list:
    """Verilen dosyaya açık handle tutan süreçleri Restart-Manager ile listeler.
    Stdlib-yalnız; handle.exe/admin gerekmez. Hata durumunda probe_error sözlüğü döner —
    asla sessiz-geçiş yok (Katman-1/3 maddesi)."""
    try:
        rm = ctypes.WinDLL("rstrtmgr")
    except OSError as e:
        return [{"probe_error": f"load rstrtmgr: {e}"}]
    session = wt.DWORD(0)
    key = ctypes.create_unicode_buffer(CCH_RM_SESSION_KEY + 1)
    if rm.RmStartSession(ctypes.byref(session), 0, key) != 0:
        return [{"probe_error": "RmStartSession"}]
    try:
        # dikkat: rgsFileNames = LPCWSTR dizisi; tek dosya → dizi-başına işaretçi
        file_path = wt.LPCWSTR(path)
        arr1 = (wt.LPCWSTR * 1)(file_path)
        if rm.RmRegisterResources(session, 1, arr1, 0, None, 0, None) != 0:
            return [{"probe_error": "RmRegisterResources"}]
        needed, got, reasons = wt.DWORD(0), wt.DWORD(0), wt.DWORD(0)
        rc = rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(got), None, ctypes.byref(reasons))
        # ilk çağrı ERROR_MORE_DATA (239) dönmeli — needed'ı doldurur
        infos = (RM_PROCESS_INFO * needed.value)()
        got = wt.DWORD(needed.value)
        rc = rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(got), infos, ctypes.byref(reasons))
        if rc != 0:
            return [{"probe_error": f"RmGetList rc={rc}"}]
        return [{"pid": infos[i].Process.dwProcessId,
                 "name": infos[i].strAppName} for i in range(got.value)]
    finally:
        rm.RmEndSession(session)
```

**Cline-notları:** (1) İmza-riskleri yorumlandı — birim-testte gerçek açık-handle'lı dosya ile sabitle (testte kendi PID'in listede çıkmalı). (2) RM bazı sistem-yollarında `ERROR_ACCESS_DENIED` dönebilir → `probe_rc` event'e yazılır, hüküm katmaz. (3) Çağrı maliyeti: yalnız hata-anında; heartbeat-tick başına değil.

## EK-B — Değişmez-lock alternatifi (Katman-3 güçlü-alternatif, prob-sonrası karar)

PID bir-kez yazılır (takeover anında); liveness = `os.utime(lock, None)` her heartbeat'te. İçerik asla değişmez → yırtık-yazma imkânsız. Risk: `SetFileTime` yolunun kendi handle-paylaşım gereksinimi — Katman-1 prob verisi gelmeden uygulanmaz. Karar-turası: T0#7 boot-sonrası ilk-2-saat gözlemi (§4.4).

---

## 6. KOD-KANIT EKLERİ (v1.1 — repo @ `5b23da5`, bu masada doğrulandı, 2026-09-03)

> Bootstrap §8 tamam: `git rev-parse HEAD` = `5b23da5` ✓ · `origin/main..HEAD` BOŞ ✓ · tag-peel `7a1e6f1` ✓ · çalışma-ağacı temiz ✓. Aşağıdaki bulgular F1–F5 olgu-kurgusunu **kaynak-kodla** pekiştirir/düzenler.

### 6.1 F1 KODDA TEYİT — üç-kopyalı `_atomic_write_text`
`tmp.replace(path)` (= `os.replace` = `MoveFileExW(REPLACE_EXISTING)`) hedef-tarafı bloklama semantiği **üç ayrı kopyada** aynı: `orchestrator.py:~117` (lock+audit yolları) · `state.py:32` (StateStore — sembol-runtime json'ları) · `audit.py:44` (JSONL flush). Her kopyanın kendi yorumu: "circular-import önlemi için yerel kopya". **N2 #17 uyarısı:** Katman 1/3/4 düzeltmesi **üç kopyaya da** uygulanmak zorundadır; tek-yer-değişikliği üçüncü crash-vektörünü açık bırakır. (Kalıcı çözüm ortak yardımcı-modül — §2.2 "prefer existing mechanisms" gereği mimari-değişim sayılır, Cline saf-patch'i tercih edebilir; karar Cline raporunda.)

### 6.2 Retry-bütçesi ve exhaustion-yolu teyit
`state.py:28-29` + orchestrator kopyası: `_TMP_WRITE_RETRIES=8`, `0.05×2^attempt` üstel bekleme → toplam ~6.35s + 8 deneme ≈ **~6.4s iddia ile birebir**. Tükeniş: `tmp.unlink()` (temizlik) → `raise last_err` → **istisna yukarı sıçrar**. Lock yolunda: `heartbeat()` → `_write()` (orchestrator.py:491-520) → istisna `_heartbeat_validated()`'dan (1854-1870) run-loop'a → exception-handler → `shutdown(exit=1)`. **T0#5 imzasının (K1 8-attempt → exit=1) koddaki tam yolu budur.** Startup-heartbeat (orchestrator.py:1035) de benzer çöküş-noktasıdır — T0#6'nın boot-sonrası ölüm-yolu TAM-log'la ayrıştırılmalı (adaylar: run-loop heartbeat veya audit flush) — operatör-girdisi.

### 6.3 Katman-5 teyit — audit'in bellek-içi doğası
`audit.py:126-151`: AuditChain **bellek-içi append-only**, auto-flush koşulları `flush_threshold=50` olay / `flush_interval_sec=30`. Crash → son flush'tan sonraki olaylar **diske gitmez**. T0#6 "terminal-audit-event'ler flush-olmadan kaybolmuş" hipotezi **kodda yapısal-gerçek** (hipotez değil). Katman-5'in senkron-flush + crash-class doğrudan-disk gereksinimi kesinleşti.

### 6.4 F3-(a) ZAYIFLADI — sızıntı-avı temiz
src/live taraması: **`open()`-sız desen yok** (tüm okuma/yazma `read_text`/`write_text` — senkron-aç/kapa, 26 kullanım-noktası), **`subprocess`/`Popen`/`spawn` YOK** (repo-kendi çocuk-süreç üretmez — T0#5'teki "10988 ikinci-python" repo-kaynaklı olamaz; operatör-araç/nohup-kabuk sınıfı). → **Ağırlık (b) sync-agent / (c) resurrect-watcher'a kaydı.** (a) tam elenmez: süreç-içi sızıntı `read_text` yoluyla olamaz, ama Katman-2 disiplini yine de yazılır (savunma-katmanı + §6.6 hot-file gözlemi).

### 6.5 KATILIM-BULGUSU — lock = hot-file (tam-JSON rewrite her ~20s)
`_write()` (orchestrator.py:507-520) **her heartbeat'te tüm LockData JSON'unu yeniden yazar** (`pid`, `created_at=time.time()`, `phase="startup"` — faz etiketi runtime'da da hep "startup"; `created_at` fiilen son-heartbeat-zamanı, `_is_stale` buna göre karar veriyor). → `state/orchestrator.lock` **~20s'de bir full tmp+rename** — dakikada ~3 rename. Dizin-izleyici bir sync-agent için **tekrar-tekrar tetiklenen hedef**: (b) adayının deterministik-imza açıklama-gücü ARTTI (F2 ile uyumlu: tutucu her seferinde ~6.4s pencereyi deviriyor çünkü dosya sürekli değişiyor). **RUNBOOK-notu:** state-dir = `C:\Users\Administrator\Desktop\sniper_forex\state` — **Desktop-yolu** klasik folder-backup/sync hedefidir; §4.3 operatör-sorusu (OneDrive/Dropbox/GDrive kapsamı) kritikliğe yükseldi.

### 6.6 Katman-3'e yansıma
Lock için in-place truncate-write (Katman-3) veya immutable-lock (Ek-B) **hot-file churn'u da keser** — rename-sayısını ~0'a indirir; sync-agent kesişim-yüzeyini daraltır. Bu, Katman-3'ü "güzellik"ten **risk-azaltıcı** katmana yükseltir: T0#7'ye 3-katmanlı birlikte alınması (1+2+3+4+5 tam-set) önerilir — final karar Reis'te.

### 6.7 Ek-Kontrol listesi (Cline'a)
(1) Üç `_atomic_write_text` kopyasına aynı semantik; (2) `phase` etiketi runtime'da "running"a güncellenmeli mi — davranış-değişikliği sayılır, ayrı mini-karar olarak Cline rapor etsin (mevcut: hep "startup"); (3) `heartbeat()` çağrı yerleri: 1035 (startup) + 1870 (run-loop) — Katman-4'ün edinme/yenileme ayrımı ikisini de kapsamalı; (4) K4 test-çerçevesi mevcut 15 testin üstüne eklenmeli, mevcutlar KIRMAMALI (FREEZE disiplininde diff-minimal).
