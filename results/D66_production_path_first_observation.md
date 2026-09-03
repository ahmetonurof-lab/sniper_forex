# D66 — PRODUCTION-PATH FIRST OBSERVATION (SINIF-2)

> **SINIF-2 (GÖZLEM)** — gerçek canlı motorun fiilî davranışı. SINIF-1 (SEÇİM) değil.
> **Durum:** **AÇIK / W1-SÜRÜYOR** (boot 14:07:49 → 19:00 server). Bu dosya henüz **kısmî**dir; W2 (22:00→04:00 server) ve graceful-stop sonrası tamamlanır.
> **Üretici:** Cline (D66 executor) · **SINIR:** trade kararı/edge iddiası YOK · kod-artefaktı değişmedi · `.env` dokunulmadı · push YOK.
> **Gözlem kuralı (§D/AM-3):** kanonik-state'e canlı-handle YOK — her okuma `cp` ile kopya-üzerinden.

---

## 1. Boot-kimliliği (Aşama-3, T0#7-amendmanlı)

| alan | değer |
|---|---|
| PID | **3416** (canlı, `Get-Process` count=1) |
| başlangıç | 2026-09-03 **14:07:49** local/server (server = UTC+3, ölçüldü) |
| komut | `python -u -m src.live.run_production` (`-u`: kalıcı-log'un satır-satır-düşmesi için) |
| env | `SNIPER_STATE_DIR=C:/Users/…/sniper_forex/state` (mutlak, D18) · `SNIPER_SYMBOLS=EURUSD` (Aşama-2: swap-gerekmedi) · **`MT5_EXPECTED_LOGIN` SET EDİLMEDİ** (kredibilgi-hattı Reis) |
| kalıcı-log | `state/d66_boot_stdout.log` — **D.2 şartı İLK-DEFA YERİNE GELDİ** (T0#5/T0#6 hiç log bırakmamıştı) |
| hesap | 53012914 · ICMarketsSC-Demo · balance 9990.42 · build 6140 · positions 0 · pending 0 · reconciliation OK |

### 1.1 §A donmuş-3944-lock takeover — ÖNCE/SONRA çifti (AM-4 taze-baseline ile)
```
ÖNCE  {"pid": 3944, "created_at": 1788381955.5328035, "phase": "startup"}   mtime-age 51,691 s · pid 3944 DEAD (count=0)
SONRA {"pid": 3416, "created_at": 1788433696.6637511, "phase": "startup"}   (in-place write, acquire :758)
```
Kod-sözleşmesiyle-uyumlu: dead-PID → anında stale (`_is_stale` :985–986); 900s-yaş-penceresi ikinci-mod. **Artifact elle-silinmedi** — takeover kendisi kanıt oldu (AM-T7-6 ✓).

### 1.2 §B dual-instance canlı-atestasyonu (AM-2 aynı-env) — **GEÇTİ**
```
stderr : [run_production] Already running (lock owner PID 3416) - EXIT
exit   : 0        (beklenen: run_production.py:107–111 — "not an error")
lock   : ikinci-instance DOKUNMADI (pid 3416 korundu) · audit'e olay YAZMADI
```

## 2. Startup-merdiveni (audit, copy-then-read — 6 satır)
| ts | olay | kritik-alan |
|---|---|---|
| 1788433671.62 | MT5_CONNECT | build 6140, login 53012914 |
| 1788433671.64 | STARTUP | `safe_mode: false` *(S11-öncesi-anlık — aşağıdaki-not)* |
| 1788433675.46 | STARTUP S9 REPLAY | `bias:"neutral"`, `end_state:"flat"`, `next_idx:4338`, `replay_bars:4237`, `session_key:"2026-09-03"`, **`signals_discarded:23`** |
| 1788433676.38 | STARTUP S9 | **`COLD_REBUILD_OK`** |
| 1788433676.39 | STARTUP S11 | `verdict:"SAFE_START"`, `restored:true`, `safe_reasons:["safe_mode_persisted: expected_login_unset","expected_login_unset"]`, `warmup_bars:4338` |
| 1788433676.65 | SAFETY | `gate:"closed"`, `reason:"startup_SAFE_START"` |

**§7.2 mührü fiilen-doğrulandı:** persisted-safe-mode, **tüm fresh-checkler geçse bile** boot'u degraded-kıldı ve nedeni **çift-yazıldı** (`safe_mode_persisted:` + taze) → temiz-startup, kalıcı-durumu **aklamadı**.

## 3. SINIF-1 → SINIF-2 PARİTİ (ilk-defa, canlı-zincir üzerinde)

| öngörü (D66_sweep_detection §1.8) | canlı-gözlem | sonuç |
|---|---|---|
| #1 S9 **COLD_REBUILD**, restore DEĞİL (`EURUSD.json` ≈38h bayat) | `COLD_REBUILD_OK`; `EURUSD.json` mtime hâlâ Sep 1 23:59 | **EŞLEŞTİ** |
| #2 `S11 SAFE_START` + gate CLOSED | birebir | **EŞLEŞTİ** |
| #3 day-key `2026-09-03` EURUSD bias **NEUTRAL/unlocked** | `session_key:"2026-09-03"`, `bias:"neutral"`, `end_state:"flat"` | **EŞLEŞTİ** |
| #4 pencere server 22:00→04:00'da body-formasyonu | W2 henüz gelmedi | **BEKLİYOR** |
| — body_high/body_low/tol sayısal-paritesi | canlı `session_atr` yalnız close-save'te | **BEKLİYOR** (§1.6 gereği bu-olmadan "parity" denmez) |

`replay_bars=4237 / warmup_bars=4338` Sep 2-bootuyla **birebir aynı** → replay-ölçeği deterministik (65k M1 → sabit kutu sayısı). `signals_discarded` 12→23 değişti (pencere kayması), **bu-bir-sapma-değil, girdi-farkı**.

## 4. BULGULAR (gizlenmez — §4.4)

### BULGU-1 · **KRİTİK — audit zinciri boot-başına YOK EDİLİYOR** (kod-kanıtlı)
`orchestrator.py:1040` `AuditChain(auto_flush_path=…)` mevcut-dosyayı **yüklemeden** kurulur · `audit.py:147` `self._events=[]` · `save()` (`:247–255`) tüm olay-listesini tmp'ye yazar ve `tmp.replace(path)` ile **üzerine-yazar** · `AuditChain.load()` üretimde **sıfır çağıran** (tek `.load(` :1449 recovery'ye ait). Sınıf-docstring'i "In-memory **append-only**" der — append-only **bellek-içi**; kalıcılık katmanı **whole-file overwrite**.

**Sonuç:** her yeni boot'un ilk flush'ı önceki boot'ların `audit.jsonl`'ını siler. **§18 "audit continuity" ve §6.1 restart-doğruluğu ihlali.** Ölçülen: Sep 2 23:08-bootunun 7 satırı → bugün 6 satır, **yalnız-bugünkü-olaylar**.
**Eylem:** kod-dokunulmadı (production-critical; ayrı-yetki gerekir). Sep 2 kayıtları aşağıda **kurtarıldı**. Önerilen-düzeltme (yetki-beekli): startup'ta `load()` + append-only flush, **veya** boot-başına rotasyon (`audit.<ts>.jsonl`).

**Kurtarılan-Sep 2-kanıtı (bu-sohbet'te-ölçülmüştü; artık dosyada YOK):**
```
STARTUP 1788379702.63  account 53012914 / ICMarketsSC-Demo / safe_mode false / symbols ["EURUSD"]
STARTUP 1788379709.12  S9 REPLAY  bias neutral, end_state flat, next_idx 4338, replay_bars 4237,
                                 session_key 2026-09-03, signals_discarded 12
STARTUP 1788379710.08  S9 COLD_REBUILD_OK replay_bars 4237
STARTUP 1788379710.10  S11 SAFE_START restored true safe_reasons ["expected_login_unset"] warmup_bars 4338
SAFETY  1788379710.35  gate closed reason startup_SAFE_START
WRITE_BLOCK 1788380651.38  PermissionError WinError 5: audit.jsonl.3944.tmp -> audit.jsonl  retries 8
```
**WRITE_BLOCK yorumu (düzeltmeli-okunsun):** `orchestrator.py:77–100` N2 #15-b gereği **öngörülen** davranıştır (PID-eşsiz tmp + 8-deneme/~6.4s + `on_block` adli-kaydı); kök-neden **harici geçici handle (AV/Defender on-access)**. Mekanizma **çökmedi** — boot devam etti. Flush-tamponu (`flush_if_due`; 30s-aralık / 50-eşik) olay-ts'si ile dosya-mtime'ını ayrıştırabilir; **üç-aday ayrıştırılamaz hâle geldi — Bulgu-1 yüzünden.**

### BULGU-2 · Runtime-state döngü-boyunca persist edilmiyor
Boot 14:07'den beri çalışıyor; `state/EURUSD.json` mtime hâlâ **Sep 1 23:59** → cold-rebuild edilen state **yalnız close-save'te** (D48) yazılıyor. Sonuç: **her sert-ölüm tam-replay'i zorunlu kılar** (Sep 2-bootu da hiç persist etmemişti — tutarlı). Canlı `session_atr` bu-yüzden **şimdi okunamaz** → §1.6 parite-kapısı W2/close-save'a kadar açık.

### BULGU-3 · Lock `phase` "startup"'ta kalıyor; `created_at` heartbeat'le ilerliyor
Gözlem: 14:07:56 `created_at 1788433696.66` → 14:08:56 `1788433756.73` (+20s = poll interval), `phase` hâlâ `"startup"`, age 9s. §A'nın başarısızlık-imzası `phase=…` alanına dayanıyor → **wedged-vs-startup ayrımı bu alandan yapılamaz**; yaş-tabanlı stale-yolu fiilen PID-liveness'a indirgenmiş olur (§A satır-32 "heartbeat absent" dalı ayrı bir saat varsayar). **Yorum-kod gerilimi; kusur olarak henüz sınıflandırılmadı — Aşama-5'te kapanır.**

### BULGU-4 · `clock.in_session` ölü-kod + docstring kendiyle çelişkili
`clock.py:13` pencereyi "19:00→01:00 **server time**" der; aynı modülün `server_to_utc_historical`'ı üretimi **UTC'ye çevirir** ve `SessionManager` UTC üzerinden çalışır → fiilî pencere **server 22:00→04:00**. `in_session(dt_server)` üretimde **çağıran-yok** (yalnız `tests/test_live_candle_feed.py:296–300`). **D66'nın kendi tabanını düzeltti** (§0.3); hükmün "04:00→19:00" pininin 19:00-uca 3s sapmaydı — ve W2-pini (22:00→04:00) bu düzeltmeyi bağımsız-doğruladı.

### BULGU-5 · Capture-hijyeni: MT5 iki-tuzagi (SINIF-1 araç-doğruluğu)
(a) `copy_rates_range` naive-datetime'ı **yerel-saat** sanıyor → istenen 12:00 yerine 09:00 döndü (−3h kayma); (b) **abonelik-gecikmesi**: `symbol_select` hemen-önce çağrılmasa GBPJPY **bayat (Aug 20–21)** veri döndürdü, 2sn-sonra doğru. → capture `copy_rates_from_pos` + epoch-filtre + tazelik-koruyucusu ile yapıldı. `DataLoader.list_symbols()` multi-TF kusuruyla aynı-aile: **backlog**.

## 5. Açık-kalanlar / devir
- **W1 sürüyor** (→19:00 server). **W2 (22:00→04:00 server) = CBDR penceresi** — bias-event'lerinin ilk canlı verisi; §1.8-#4 ancak orada kapanır. **W2, W1'den bilgi-yüklüdür** (Reis-kararı).
- **Graceful-stop Cline'da DEĞİL:** §C "yalnız foreground Ctrl-C"; arkaplan-kanalı Sep 2'de `err_att=187` ile kırıldı (bu-boot'ta da aynı kısıt). **Kill-zamanlaması Reis'te.** Beklenen-exit **2** (AM-1 mode-bağlı: SAFE_START → `2 if (runtime_safe or not entries_enabled)`).
- Close-save sonrası: `state/EURUSD.json`'daki `session_atr` ile offline-tarama **65000-çekimde yeniden koşulur** → §1.6 kapanır, §3'un "BEKLİYOR" satırları dolar.
- **Bulgu-1 için ayrı-hüküm gerekli** (kod-değişikliği yetkisi). Bulgu-1 kapanmadan hiçbir soak "audit-continuity" iddia edemez.
- **Reis-bildirimi (AM-T7-4/§5) üç-kanala: Hakem · Sentezleyici (Luna) · Owner (Forexçi).** Tek-kanal eksik-bildirime düşer.

## 6. Pinler (yazım-anı)
Bu-dosya + `results/D66_sweep_detection.md` (128L/11,718B) + `docs/T0_7_PREBOOT_CHECKLIST.md` v1.2 (105L/12,009B) + `state/d66_capture/` (6 feather + manifest). Hepsi **untracked**; `state/` repoda tamamen-untracked, `results/` ve `docs/` tracked-dizinler — **stage-edilmedi**. Boundary: `git status --porcelain --untracked-files=no` = yalnız `M AGENTS.md`, `M memory-bank/progress.md`. D62 `ad3fa87b…` ve D64 `8b18f70a…` bu-oturumda **dokunulmadı-doğrulandı**.

---

# BÖLÜM II — HAKEM RATİFİYESİ + W1 CANLI-BULGULARI (14:47–15:05 server)

## 7. Ratifiye (Hakem hükmü, 2026-09-03)
- **Aşama 0→3 KABUL; RED YOK.** 3/3 SINIF-1→2 parite-çeşidi (COLD_REBUILD / SAFE_START+gate / NEUTRAL-day-key) → **D65-ayrımının ilk SINIF-2 tarifi sabitlendi**.
- **Düzeltme-#1 KABUL** (pencere server 22:00→04:00); **W1–W2 sınırı server dilinde 19:00→22:00** (Hakem'in 3s sapması düzeltildi).
- **Detail-2 HAKEM TARAFINDAN DÜZELTİLDİ** (kendi hatası): doğru-eşleşme **EURUSD 1→0 (bias YOK)** · **USDCAD NEUTRAL→BULLISH (bias VAR)**. V-LIVE'nin **mekanizmal-seçim** olması ratifiye.
- **Düzeltme-#3 yön-tarafı kanandı** → ③-masası **altı-parça**: *güçlü-trend günleri bias kilitlemez*.
- **Bulgu-2 → backlog** (D68 gölgesinde; replay D49'da dokümanlı). **Bulgu-3 → §A-imza maddesine not** (checkpoint §A'nın ikinci modülüyle uyumlu; backlog).
- **Kararlar:** (i) **W2 = EVET, KOMİT**; (ii) kill = **Reis-eli-sinyali + W2-sonrası default 04:10 server**, beklenen-exit **2** (AM-1 mode-bağlı; SAFE_START'ta sapma DEĞİL), K5-dump YOK, lock-unlink, D48-snapshot-mtime; (iii) **65k tarama ŞARTLI — W2 bitiminde**, Bulgu-1 hükmünden bağımsız.
- **D68 protokol-dikişi yürürlükte:** her boot-öncesi `cp state/audit.jsonl state/audit_prev_<date>.jsonl` (mask-bağımsız). **İlk-icrası bu-oturumda ölçüldü → §8.1.**

## 8. D68-dikişinin ilk-icrası + W1 canlı-bulguları

### 8.1 Dikiş uygulandı (kod-dokunuşu yok)
`state/audit_prev_2026-09-03.jsonl` = **9 satır / 2765 B** (14:58). Dikiş, uygulandığı-ilk-anda-değerini-kanıtladı: aşağıdaki **Bulgu-6 tam bu-esnada yakalandı**.

### 8.2 BULGU-6 · WRITE_BLOCK boot-içi DE yineliyor ~~(Bulgu-1 genişledi)~~ → **DERECESİ AŞAĞI-ÇEKİLDİ (Bak: §12.2 + §13)**
> **⚠ Ratifiye-düzeltme:** Bu-başlığın-parantez-içindeki **"(Bulgu-1 genişledi)"** atfı **geri-alınmıştır.** WRITE_BLOCK, BULGU-1'in (boot-sınırı-kaybı) **kanıtı değildir** — §12.2'deki H1/H2/H3 şemsiyesi altında, **BULGU-1 satır-77'nin zaten-öngördüğü** (N2 #15-b: PID-eşsiz tmp + 8-deneme + `on_block`) **çalışan-bir-adli-koruyucunun-kayıdıdır.** D68-P0 yükü **tamamen BULGU-1'in kod-kanıtındadır.** Madde, **N2 #21-madde-4 izleme-kaydı** olarak-düşük-dereceyle-kalır.
Boot-olayları 14:07:51–**14:07:56**; sonra **45 dk sessizlik**; **14:52:40 WRITE_BLOCK → 14:52:46 `ERROR phase=audit_flush` → 14:52:46 WRITE_BLOCK**. Başarısızlık **yalnız boot-sınırında değil, ilk runtime-flush'ta da** occurrence. İyi-haber: N2 #15-b retry-döngüsü **~6 s içinde kurtardı** (9 satır dosyaya düştü) ve hata **kendini kaydetti** (sessiz değil). Kötü-haber: `ERROR phase=audit_flush` **üretime karıştı** — W1 "0 SIGNAL/SWEEP/ERROR" iddiam artık **0 SIGNAL/SWEEP + 1 ERROR** olarak düzeltildi (§13: sayı-düzeltmesi, gizleme yok). **İş-kuralı:** W1 temiz-eşleşmesi `SIGNAL|SWEEP` üzerinden verilecek; `ERROR` **ayrı-sayılacak**.

### 8.3 BULGU-7 · T0-CRASH'IN KAYIP AUDIT-ZİNCİRİ KURTARILDI (yetim tmp)
`state/audit.jsonl.tmp` (**Sep 1 23:59:02 / 1483 B / PID-suffix'siz = pre-N2#15 kod**) **6 tam-ayrışabilir olay** içeriyor; dosya newline ile bitiyor, **kesik 7. satır YOK** → tmp tamamıyla yazılmış, **ölüm `tmp.replace()` anında**:

| # | Olay | ts (server) | Kritik alan |
|---|---|---|---|
| 1 | MT5_CONNECT | 09-01 19:32:06 | — |
| 2 | STARTUP | 09-01 19:32:06 | — |
| 3 | STARTUP | 09-01 19:32:12 | `phase=S9 verdict=REPLAY` |
| 4 | STARTUP | 09-01 19:32:12 | **`phase=S11 verdict=PROCEED`, `restored:false`, `warmup_bars:4339`** |
| 5 | SAFETY | 09-01 19:32:13 | — |
| 6 | **SHUTDOWN** | **09-01 23:59:02** | **`exit:1, reason:"run_exception:PermissionError"`** |

**Crash-mekanizması ±18 ms yeniden-inşa:** `orchestrator.lock.tmp` `created_at=1788296341.9933178` (pid **16984**) → **+17.8 ms** → SHUTDOWN `1788296342.0110803`. Sıra: **kilit-yazımının rename'i patladı → exception `run()`'a çıktı → SHUTDOWN audit-tamponuna KAYDEDİLDİ → audit-save tmp'yi yazdı → audit-rename'de öldü.** İki-yetimin aynı-18ms-penceresinde kalması bu-sıranın fiziki-kanıtıdır.
**En-ağır-içerik — olay-4 `verdict=PROCEED`:** **Sep 1'de entry gate AÇIKTI** (bugünkü SAFE_START'ın zıddı), `restored:false`. T0'nin **trade-edebilir durumda çalıştığı audit-kaydıyla** doğrulandı — bugüne dek bu yalnız *yorum*dı.
**Paradoks (D68'e girdi):** kayıp-üreten-mekanizma kanıtı aynı-anda **korudu** — rename başarsaydı bir-sonraki-boot'un overwrite'ı bu 6 olayı da silecekti. **Bugün bu-6 olayın tek-kopyası: bu-dosya + defter.**
**Yeni küçük yorum-kod çelişkisi:** `orchestrator.py:91` "crash trace `orchestrator.lock.<pid>.tmp` gösteriyordu" der; **gerçek-yetimin-adı `orchestrator.lock.tmp` (PID'siz)** → T0, **PID-unique-fix'in henüz-yetişmediği bir yolda** ölmüştü; yorum olaydan-daha-güçlü-düzeltme varsayıyor. **Backlog (doküman-doğruluğu); kod-talebi yok.**

### 8.4 BULGU-8 · close-save YALNIZ graceful-stop'ta → parite-kapısı kill'e HAPSEDİLMİŞ
Üç-adımlı kod-kanıtı: (a) `schedule_snapshot` üretimde **tek-çağıran** = `orchestrator.py:1661`, `shutdown()` gövdesi-içi (`audit.shutdown()` :1641 + MT5-release :1650 ile aynı-teardown-bloğu); (b) `recovery.py:187–191` yalnız `rec.save` + `rec.save_lifecycle`; (c) **yorum kendisi itiraf ediyor:** *"Aşama 2 şartı: per-N-bar periodic save — graceful path alone cannot shrink the kill -9 crash window."* → **per-N-bar save YOK.**
Sonuç-zinciri: `session_atr` → **yalnız graceful-stop** → graceful-stop → **SIGINT** → SIGINT → **konsol** → pid 3416'nın parent'ı **`nohup.exe`** (kanıt: `crash_log.txt` satır-2 `parent: "19088: …nohup.exe"`) → **konsol YOK**. Ayrıca `orchestrator.py:2364–2365` **yalnız SIGINT+SIGTERM** kuruyor, **SIGBREAK YOK**; Windows'ta `os.kill(pid, SIGTERM)` → `TerminateProcess` (handler **çalmaz**).
**⇒ Karar (iii) olduğu-gibi-yerine-getirilemez:** "W2-bitiminde 65k tarama", W2'nin **kendiliğinden** bir `session_atr` üreteceğini varsayıyor; **öyle bir üretim yolu YOK.** §1.6 parite-kapısı W2'nin bitmesiyle **değil**, ancak **konsollu-yeniden-boot + gerçek Ctrl-C** ile kapanır. **Bu bir plan-hatası değil, kodun yapısal kısıtıdır ve ilk-defa ölçüldü.**

### 8.5 BULGU-9 · D68-P0 rotasına REPO-İÇİ EMSAL
`state/crash_log.txt` **append-mode** ve **boot-ları atlatıyor**: satır-1 pid **3944** `ts 1788379690.446` (Sep 2 23:08:10), satır-2 pid **3416** `ts 1788433671.607` (bugün 14:07:51). Yani **aynı kod-tabanında fiilen-çalışan bir append-persistence yolu zaten var**; `AuditChain` onu kullanmıyor. **AGENTS.md §2.2 ("mevcut-mekanizmayı-yeniden-kullan") gereği D68-P0'ın en-düşük-riskli emsali budur** — Hakem'in load+append-only ön-önerisini bağımsız-güçlendirir. Yan-ürün: satır-1, **devraldığım eski kilidin (pid 3944) Sep 2 23:08 boot'una ait olduğunu** bağımsız-doğruluyor → §A takeover-kanıtı **çift-kaynakla** teyitli.

## 9. Güncel-kapı-durumu ve seçenek-seti
| Kapı | Durum | Engel |
|---|---|---|
| W1 (→19:00) | **SÜRÜYOR** — 0 SIGNAL/SWEEP, 1 ERROR (§8.2) | — |
| W2 (22:00→04:00) | **KOMİT (Hakem-i)** | süreç taşınacak; **§8.4 kısıtı geçerli** |
| §1.6 parite | **ERİŞİLEMEZ** | close-save ⇒ graceful-stop ⇒ konsol; pid 3416'da yok |
| 65k tarama | ŞARTLI-yetki (Hakem-iii) | girdisi `session_atr` **üretiliyor-değil** |
| D68-P0 | Owner-batch / N2 #21 | kod-yetkisi yok; **emsal §8.5** |

**Seçenekler (karar Reis+Hakem'in; ben-tercih-vermiyorum):**
- **K1 · Konsollu-yeniden-boot — pariteyi açan TEK yol.** pid 3416 `taskkill /F` (non-graceful; close-save YOK, §C-kanıtları bu-boot için **"üretilemez"** olarak mühürlenir) → Reis kendi terminalinde aynı-komutla boot eder (**D68-dikişi ÖNCE**) → W2 + **gerçek Ctrl-C** → exit-2 + close-save + `session_atr` → 65k tarama + §1.6 kapanır. **Maliyet:** bugünkü W1 sürekliliği kırılır. **Kazanım:** T0#7'nin §C-kanıt-hedefi ilk-defa karşılanabilir.
- **K2 · Mevcut-boot'u-izlet, §C'yi "nohup-altında-imkânsız" olarak mühürle.** Parite kapısı **açık kalır**, 65k yetkisi **ertelenir**, Bulgu-8 kalıcı-tespit olarak deftere geçer.
- **K3 · Hibrit (en-yüksek-bilgi).** pid 3416 W2'yi gözler — **canlı bias-event verisi KAYBEDİLMEZ**, çünkü §8.4 yalnız *persist*'i engeller, *hesabı* değil. Sonra K1-second-boot **yalnız §C+close-save+parite** için ayrıca koşulur. İki-boot = iki-ayrı-kanıt-sınıfı; **soak-dondurması (§17) açısından her-boot ayrı-kayıt.**

## 10. HAKEM HÜKMÜ (2026-09-03 15:30) — **ROTA = K3** · kod-yetkisi/K1/K2 = RED

### 10.1 Hüküm
> **K3 işletilir.** PID-3416 **W2-boyunca canlı kalır** (zero-downtime; canlı-bias-event-verisi = D64-hedef-②'nin SINIF-2-besinini kaybetme bedelini ödeme). **W2-bitiminde Reis kendi interaktif terminalinde İKİNCİ boot'u başlatır** — **D68-dikişi İLK adım** → kısa-observasyon (~10 dk: S9/S11/NEUTRAL-day-key/§B ikinci-atır) → **gerçek foreground Ctrl-C** → **beklenen-zincir: exit-2 · D48 close-save (`schedule_snapshot:1661` koşar) · lock-unlink-769 · K5-YOK · crash_log-bayt-sabit** → **§C-zinciri bu ikinci boot'ta tam kanıtlanır (D58-kapanışı)** ve canlı `session_atr` ile karar-(iii) girdisi **üretilebilir** hâle gelir.

Adım-adım-runbook: `docs/T0_7_PREBOOT_CHECKLIST.md` **§H.2 (v1.4)**.

### 10.2 Neden-diğerleri-RED (hükmün-gerekçeleri, kayda)
- **K1 RED:** (i) W2-SINIF-2-verisi kaybettirir (kamp-çıkışı); (ii) non-graceful ölüm **yeni audit-yetim-kaydı üretir** → BULGU-7-yetim-imzasının **sistematikleşmesi**; (iii) §C kanıtı zaten üretilemez olurdu → **çifte kayıp**.
- **K2 RED:** *"imkânsız-mühürlenir"* parçası **KABUL** (kalıcı-tespit, → D70); ancak §C'nin tamamen reddi ve 65k'nın ertelenmesi **gereksiz kayıp** — hibrit-çözüm §C'yi veriyor.
- **KOD-YETKİSİ RED:** üretim-critical dosyada **canlı süreç üstünde diff** = D63-topolojisinin tam-reçetesi + §17-dondurması ihlali + doğurma-testi zorluğu (canlı-instance-abort'u amaçlanan bug üretmez). **Per-N-bar periodic save ve SIGBREAK handler → N2 #21 kapsamına**; *kod-sırası yanlış değil, **zamanlaması** yanlış.*

### 10.3 Yeni-ölçülmüş-kural (K1-RED gerekçesi ii → defter-kuralı)
**"taskkill = audit-orphan üretir."** Gerekçe: `save()` tmp-yazar → `replace()` patlarsa tmp-yetim-kalır (BULGU-7'de ölçülen tam-mekanizma). Dolayısıyla hard-kill, D68-kayıp-sınıfını **gizlemek-bir-yana, yetim-artefakt-la çoğaltır.** Bu-kural N2 #21 madde-4'un (WRITE_BLOCK-runtime-izlemesi) gerekçesidir.

### 10.4 Derece-hükümleri
| Bulgu | Derece | Yere |
|---|---|---|
| **BULGU-6** | ~~D68-P0 vaka-güçlendi~~ → **AŞAĞI-ÇEKİLDİ (ratifiye, §13):** "vaka-güçlendici" atfı **silinir.** Gerekçe: O1-disiplini **H1'i (AV/Defender) eleyemez**; tek-olay-üstünden-endonek-hükmü-verilemez. Tekil-retry 6 s'de kurtardı (mekanizma **çalışıyor**) | N2 #21 **madde-4 izleme-maddesi** + **telemetri-şablonu**: (i) `ERROR-ts ≈ WRITE_BLOCK-ts` eşleşmesinden **ayrı-olay-sayımı** — *aynı-saniye-iki-sayı-değildir*; (ii) H3 "saatlik-endonek" için **n=2 yetersiz**; (iii) RM-probe-payload'ları "kim-tutuyor" ilk-cevabını verirse **H1/H2 ayrışır** |
| **BULGU-7** | **D71 defter** (yapı-ışınsı-kazı standardı: *tam-gün-nokta, arşiv-geri-aitir*) — "Sep-1 gate AÇIK kanıt oldu"; **bir artefakt üç yorum dönüştürdü** | orchestrator-yorum çelişkisi → **backlog** (N2 #21 comment-hijyen toplu) |
| **BULGU-8** | **K3 ile kapandı-yönlendirildi** (kod-değişikliği YOLDA, N2 #21 madde-2/3) | **D70**: *"§C graceful-stop, nohup-tarzı launch altında **fiziki imkânsız**"* — D58'i *"arkaplan-kanalı-ölü"*den *"sinyal-iletimi-fiziki-olarak-olası-değil"*e **tamamlayıcı-düzeyde** değiştirir; foreground-yalnız-kuralı bu-şekille kalıcı |
| **BULGU-9** | **Kanıt-artışı** — N2 #21 P0-rotasının **repo-içi öncesi** | load+append-only artık "önce-bilinen-uygulamaya paralel" → **ratifiye** |

### 10.5 Sınıf-düzeltmesi + Hakem-öz-düzeltmesi-4
- **Sınıf-düzeltmesi (BULGU-6 başlığına):** WRITE_BLOCK/WinError-5 ailesi **D35-ownership-fatal DEĞİL** (N2 #15-b hükmü). W1'deki `ERROR phase=audit_flush` **"ERROR-beyanı-nüksü" değil, "sayım-beyanı-düzeltmesi"**dir. §8.2'deki düzeltme bu-başlıkla okunur.
- **@Hakem-öz-düzeltmesi-4 (kayda, §12.1):** Hakem'in §3-(ii)'deki **"04:10-default"** cümlesi **nohup bilgisiyle geçersizdi**; düzeltilmiş-karar **K3'deki zamanlamadır**. (Masa-üzerinde-iki-karar-düzeltmesi: Detail-2 ve 04:10 — ikisi-de hüküm-metninde görünür.)

### 10.6 BULGU-3 genişleyen-kanıt (hüküm-sonrası-yeni-ölçüm, 15:29)
`created_at` heartbeat ile tazeleiyor, `phase` **boot'tan 1s21dk sonra hâlâ `"startup"`**: 14:58 `1788436708.0007718` → 15:29 `1788438550.3587976` (**+1842 s**), iki-örnekte-de `phase="startup"`. → **wedged-startup vs normal-startup ayırt edilemiyor** (ölçüm 81 dk'ya çıktı) → N2 #21 madde-5.

### 10.7 Güncel-kapı (K3-sonrası)
| Kapı | Durum |
|---|---|
| W1 (→19:00) | SÜRÜYOR — 0 SIGNAL/SWEEP; 1 ERROR = **sayım-düzeltmesi-sınıfı** (§10.5) |
| W2 (22:00→04:00) | **KOMİT · PID-3416 CANLI** (K3) |
| §C + close-save + `session_atr` | **İKİNCİ-BOOT'TA üretilecek** (§H.2 runbook) |
| 65k tarama (Hakem-iii) | **otomatik-açılır** — ikinci-boot adım-5 girdisinden sonra |
| §1.6 parity | ikinci-boot + 65k-tarama sonrası **Aşama-5 COMPARISON** (SINIF-2) |
| Kod | **DOKUNULMADI** (`src/ tests/ index.json` diff boş) — N2 #21 altı-madde, PID-3416 canlı-iken-yok |




## 11. BULGU-10 · PENCERE-KOD-TÜRETİMİ + ÖLÜ-KOD-TUZAĞI (2026-09-03 15:45 · K3-uygulama-öncesi-çapraz-kontrol)

> ⚠ **ÖNCELİK-DÜZELTMESİ (§12.1 — bu-bölüm YENİ-BULGU DEĞİLDİR, kısmen-tekrardır).**
> §11.1 (fiilî-pencere = server 22:00→04:00) ve §11.3'ün-ölü-kod-tespiti **BULGU-4'de (satır-85-86) zaten kayıtlıydı**: "`clock.py:13` pencereyi server-time der … fiilî pencere **server 22:00→04:00** … `in_session(dt_server)` üretimde **çağıran-yok** (yalnız `tests/test_live_candle_feed.py:296–300`)".
> **Hata-sınıflandırması:** §1-ihlali (düzenlediğim dosyanın §4 bölümünü okumadan §11 yazıldı) + §2.2 (mevcut-kayıt yerine yeniden-keşif). **Nasıl-olduğu:** BULGU-1..5 §4 içinde, BULGU-6..9 §8 içinde; §10/§11 yazarken §8'den-devam ettim, §4'ü-yeniden-okumadım.
> **BULGU-10'un GERÇEKTEN-YENİ olan kısmı** (Bulgu-4'ün içermediği): (a) offset'in-kod-sabitleri `clock.py:20-21,53-57` (yaz+3/ağustos-kış+2, DST-kuralı) — Bulgu-4 bunu-saymıyordu; (b) **yerel-makine ≡ server-saati** ⇒ runbook'ta çeviri-gereksiz; (c) **pencere 04:00'da kapanır ⇒ 04:10 Ctrl-C body-sonrası** (zamanlama-doğrulaması); (d) W2-bitimi ile day-key-devrinin-çakışması; (e) `CBDR_TIME_SEMANTIC_ALIGNMENT_RAPORU.md:180` aritmetik-hatası; (f) `in_window`'un **4 çağıranla** sayısallaştırılması.
> **Hüküm-düzeltmesi:** §11.1'in "HÜKÜM" satırı **BULGU-4'ü teyit eder** (yeni-keşif değil, bağımsız-ikinci-doğrulama); §10.4-derece-tablosuna-göre BULGU-10'un derecesi **"BULGU-4 teyidi + 6-yeni-yan-ürün"**dir.

K3-runbook'u saatlere bağlanınca pencere-iddiası koddan-yeniden-doğrulandı. **Sonuç: Hakem'in-pencere-düzeltmesi yorum-olmaktan çıkıp türetim-oldu; bir de sahte-çelişki çözüldü.**

### 16.1 Pencere — halka-halka-türetim
| # | Halka | Kanıt |
|---|---|---|
| 1 | CBDR penceresi **UTC** saatleriyle tanımlı | `session.py:19-20` *"CBDR window: 19:00→01:00 UTC"*, `in_window = (h >= 19 or h < 1)`; varsayılanlar `session.py:28-29` (`start_hour=19, end_hour=1`) |
| 2 | Bar-gövdeleri **server→UTC** çevrilmiş girer | `candle_feed:104,113-118` (`server_to_utc_historical`), `clock.py:75` `dt_server − timedelta(hours=offset)` |
| 3 | Eylül = **yaz**, offset **+3** | `clock.py:20-21` (`SUMMER=3`, `WINTER=2`), `clock.py:53-57` (last-Sun-Mar → last-Sun-Oct) |
| 4 | ⇒ **UTC 19:00 = server 22:00** · **UTC 01:00 = server 04:00** | Aritmetik: server = UTC + 3 |
| 5 | **Bağımsız emsal** aynı eşlemeyi veriyor | `docs/CBDR_TIME_SEMANTIC_ALIGNMENT_RAPORU.md:179` — *"Server-time 22:00 = UTC 19:00 → IN_WINDOW başlangıcı"* |

> **HÜKÜM:** CBDR body-formation penceresi = **server 22:00 → 04:00**. Ratifiye-pencere **kod-türetimi + bağımsız-rapor-teyidi** ile kapandı (kanıt-hiyerarşisinde §3 seviye-2/4'e yükseldi).

### 16.2 Zamanlama-sonuçları (K3-runbook için operatif)
- **Pencere server 04:00'da KAPANIYOR** ⇒ **04:10 Ctrl-C body-tamamlanma-sonrasına denk geliyor** — Hakem'in-default'u **doğru**; ayrıca **W2 (19:00→22:00) tam yeni-CBDR-penceresi-açılışında bitiyor**, yani W2-bitimi ile day-key-devri çakışıyor (temiz-hizalanma, karışma-yok).
- **Yerel-makine-saati ≡ server-saati** (ölçüm: `date -u` 12:46 vs yerel 15:46 = UTC+3; yaz-offset de +3) ⇒ **runbook saatlerinde çeviri GEREKMEZ**, Reis kendi duvar-saatini okur.

### 16.3 Çözülen sahte-çelişki + ölü-kod tuzağı
`clock.py:23` *"Session window (**MT5 server time**): 19:00 -> 01:00"* der; `session.py:19` aynı **19→1** sayılarını **UTC** der. İlk-okumada "aynı-sabitler-iki-zaman-dilimi" = §2.2 duplicate-source-of-truth şüphesi doğurdu. **Çağıran-analizi şüpheyi giderdi:**
- `clock.in_session` → **üretimde SIFIR çağıran**; grep-yolu yalnız `tests/test_live_candle_feed.py:298-300` (graph `in_degree=1`, o-da test).
- `SessionManager.in_window` → **4 çağıran**, canlı-yol: `breakout_variant.py:262`, `liquidity_forensics.py:382`, `session.py:198`.

**Kalan-iki-kusur (defect değil, hijyen/tuzak):**
1. **Yanlış-etiket:** üretimde-olmayan bir fonksiyona "MT5 server time" penceresi atanmış — okuyucuyu §2.2-ihlali-varmış-yanına çekebilir (beni çekti). → **N2 #21 madde-6 (comment-hijyen)**, `orchestrator.py:91` ile aynı-çuvallara.
2. **Yeşil-test-ölü-koda** (§4.1): `test_in_session_spans_midnight` geçiyor ama hiçbir üretim-davranışını kanıtlamıyor — "test-pass ≠ architectural correctness" örneği. Silmek-değil, **ya canlı-yola bağlanmalı ya da test-kapsamı UTC-`in_window` üzerine yeniden-yazılmalı** (pre-reg kararı N2 #21'e).

### 16.4 Önceki-raporada-bulunan-aritmetik-hata (§12.1 — sessiz-düzeltme YOK, kayda)
`CBDR_TIME_SEMANTIC_ALIGNMENT_RAPORU.md:180`: *"Server-time 01:00 = UTC 22:00 → OUT_WINDOW dönüşü"*. **Yanlış:** UTC 22:00 için `h >= 19` sağlanır ⇒ hâlâ **IN_WINDOW**. Pencerenin gerçek kapanışı **UTC 01:00 = server 04:00**. Raporun ana-hükmü (§3, RUN_B güvenilir / MATCH: YES) bu-hatadan **etkilenmez** — satır, kenar-bölge-tanımındaki yazım-hatasıdır. **Dokümana dokunulmadı**; owner-batch düzeltme-adayı olarak kayıtlı.

### 16.5 Bu-bulgunun-kapıya-etkisi
**YOK — beklenti-değişikliği gerekmiyor.** §H.2 runbook saatleri olduğu-gibi doğru; §10.7 kapı-tablosu değişmedi. Kazanım: pencere-iddiası artık **kod-türetimi**, ve K3-ikinci-boot'un **04:10**'da durdurulması **body-kapanışından-sonra** olduğu bağımsız-doğrulandı.

## 12. BULGU-11 · GÖZLEMCİ-KİRLENMESİ-BAYRAĞI + W1-SAYIMININ-İKİNCİ-DÜZELTİLMESİ (2026-09-03 16:01)

### 12.1 Sayım-düzeltmesi (§13 — iki-düzeltme-de görünür, gizleme-yok)
Share-safe-döküm (`results/D66_observer_touchlog.txt` + satır-satır ayrıştırma) W1 olay-laderni yeniden-saydı:

| Aşama | Beyan | Durum |
|---|---|---|
| İlk | "0 SIGNAL/SWEEP/ERROR" | **eksik** — WRITE_BLOCK sayılmamıştı |
| Birinci-düzeltme | "0 SIGNAL/SWEEP + **1 ERROR**" | **eksik** — 14:52 epizodu 2 WRITE_BLOCK içeriyor, +3'inci henüz olmamıştı |
| **Nihai (16:01)** | **0 SIGNAL/SWEEP · 1 ERROR · 3 WRITE_BLOCK** | satır-7 `14:52:40 r=8` · satır-8 `14:52:46 ERROR` · satır-9 `14:52:46 r=8` · satır-10 `15:51:32 r=8` |

BULGU-6'nın "14:52:40 WRITE_BLOCK → 14:52:46 ERROR → ~6 s'de kurtuldu" anlatımı **yarı-yanlıştı:** epizod **3-olaylı** (2× WRITE_BLOCK + 1× ERROR). 15:51:32'deki üçüncü WRITE_BLOCK **ERROR üretmeden** atlatıldı.

### 12.2 Kontaminasyon-şüphesi (neden-ciddiye-alınıyor)
İki `node.exe` süreci **14:52:48** ve **14:52:53**'te oluşmuş — yani ilk epizodun **tam içinde** (ölçüm: `Win3_Process.CreationDate`). Bunlar bu-oturumun agent-barındırıcıları. O-sırada `state/audit.jsonl`'a **Git-Bash `cp` ile** dokundum.

**Mekanistik-açılım (varsayım, test-edilebilir):** Windows'ta `os.replace(tmp, audit.jsonl)`, hedef-dosya **delete-share-kapalı** bir-tutamayla açıksa `ERROR_ACCESS_DENIED (5)` döner. Python `open()` CRT `_SH_DENYNO` kullanır (delete-share **açık**) → engellemez. Git-Bash `cp`/`cat` için aynı-garanti **yok**. ⇒ **Kullandığım izleme-yöntemi, ölçtüğüm hatanın sebebi olabilir.**

**⚠ ELENEN-RAKİPLERİN-EKSİK-SAYIMI (kayıt-düzeltmesi):** Yukarıdaki "rakip-hipotez ÖLDÜ" ifadesi **yalnız watcher'ı** elemeğe yeter; **asıl-birinci-hipotezi atladım.** Oysa **BULGU-1 satır-77 zaten kaydetmiş:** WRITE_BLOCK `orchestrator.py:77–100`'de N2 #15-b gereği **ÖNGÖRÜLEN davranıştır** (PID-eşsiz tmp + 8-deneme/~6.4 s + `on_block` adli-kaydı); kök-neden olarak **"harici geçici handle (AV/Defender on-access)"** atanmış; **mekanizma çökmemiş**, boot devam etmiş. Yani WRITE_BLOCK bir **kusur-keşfi değil, çalışan-bir-adli-koruyucunun ürettiği-kayıttır.**
Dolayısıyla üç-aday-laderni doğru-çerçevesi: **(H1) AV/Defender on-access taraması** (önceden-kayıtlı, en-olası) · **(H2) gözlemci `cp` tutaması** (bugünkü-yeni-şüphe) · **(H3) endonek saatlik-döngü** (n=2, zayıf). **Watcher (H4) gerçekten elendi** (`QUARANTINED_20260901`).
**O4'ün-karar-gücü bu-düzeltmeyle-daraldı:** O1-disiplini WRITE_BLOCK'u keserse bu **yalnız H2'yi** elemeler; **H1'i eleyemez** (Defender kendi-zamanında-taramaya-devam eder). ⇒ **BULGU-6'nın "D68-P0 vaka-güçlendi" atfü ZAYIFLADI:** tekrarlayan-WRITE_BLOCK, D68'in (boot-sınırı-kaybı) kanıtı değil; **bağımsız, öngörülmüş ve çalışan** bir olaydır. D68-P0 hâlâ **BULGU-1'in-kod-kanıtıyla** ayaktadır (o-yük artık WRITE_BLOCK'ta değil).

**Zayıf-kalan-yan:** 15:51:32 olayından önceki son `cp` 15:41:40'ta (**~10 dk**); sıkı-korelasyon orada **yok**. Yani "hepsi-gözlemci" de kesinlenemez. **~59 dk'lık iki-epizod-aralığı** saatlik-bir-döngüye işaret edebilir ama n=2.

### 12.3 Disiplin-değişikliği (anında-yürürlükte)
- **O1:** `state/audit.jsonl` artık **yalnız share-safe Python** ile okunur (`_SH_DENYNO`).
- **O2:** `cp` / `cat` / `sha256sum` / `stat` ile audit.jsonl'a **dokunulmaz**.
- **O3:** Her okuma, okumadan **önce** `results/D66_observer_touchlog.txt`'a satır yazar (korelasyon-kanıtı kendiliğinden-üretilir, elle-ihlal-edilemez).
- **O4 (karar-kuralı, önceden-bağlandı):** O1-disiplini altında da WRITE_BLOCK yinelenirse → **ENDONEK**, D68-P0 sağlam. Bir-daha hiç olmazsa → **BULGU-6 gözlemci-kaynaklıdır ve geri çekilir.**

**Bu-kural §4.1'in-uygulanmasıdır:** "test-pass ≠ correctness"nin saha-kardeşi — **"gözlem ≠ endonek davranış"**. Kanıt-zincirine kendi-araçlığımın-karışma-ihtimali, bulguyu-olduğu-gibi-bırakmaktansa ölçülebilir-kılınarak-giderilir.

### 12.4 D68'e-ek-canlı-teyit (bu-düzeltilmiş-okumadan)
`audit.jsonl` mtime 15:58:52 → 16:00:53 ilerledi, **boyut 3190'da sabit**. Yani `save()` yeni-olay-olmasa-da **tüm-dosyayı-yeniden-yazıyor** — D68'in whole-file-overwrite teşhisinin (**Bulgu-1**) **canlı-zamanda bağımsız-doğrulaması.** Kod-okumasından-gözleme-terfi etti.

### 12.5 Sınırlar (dürüst-çekince)
- `retries: 8` üç-olayda-da aynı → sabit-üst-sınır; ladder'ın-kaç-saniyeye-yayıldığı ölçülmedi (retry-geri-çekilme-eykeli okunmadı) → **ilk-atama-zamanı belirsiz**, korelasyon-penceresi bu-yüzden-geniş.
- node.exe doğuş-zamanları **nedensellik-değil, eş-zamanlılık** kanıtıdır (§3 hiyerarşisinde seviye-6).
- W1 **0 SIGNAL/SWEEP** iddiası **değişmedi** — bu-beyan kontaminasyondan etkilenmez (olay-yokluğu, olay-varlığından-farklı-sınıftır; yine-de O4 sonrası yeniden-teyit edilecek).


## 13. HAKEM RATİFİKASYONU · 11-BULGU-MÜHÜRLÜ ENVANTER (2026-09-03 16:53)

> **Statü:** ENVANTER KABUL · BULGU-6 aşağı-çekme **ratifiye** · BULGU-10/11 öz-düzeltme = **Kural-6 onikinci-üçüncü-tur** · W1-nihai-sayım **MÜHÜRLÜ** · overwrite-semantiği **canlı-gözleme terfi ratifiye** · **RED-YOK.**

### 13.1 Ratifiye-dereceler ve rota-bağları
| # | Derece | Rota |
|---|---|---|
| 1 | **KRİTİK** — D68-P0, **BULGU-1'in kod-kanıtıyla ayakta** (BULGU-11'den-bağımsız) | N2 #21 madde-1 (owner-batch) |
| 2 | YÜKSEK | N2 #21 madde-2 |
| 3 | ORTA | N2 #21 madde-5 + **§H.4-sınırı** (§A imzası artık "wedged-vs-startup **ayırt-edilemez**" bilinciyle okunur) |
| 4 | ORTA | N2 #21 madde-6 + comment-hijyen |
| 5 | ORTA | Backlog (SINIF-1 araç-hijyeni; capture-protokolüne **iki-teyit-adımı**) |
| 6 | **AŞAĞI-ÇEKİLDİ** | N2 #21 madde-4 (izleme; "vaka-güçlendici" atfı **silindi**) |
| 7 | YÜKSEK → **D71** | tamamlandı |
| 8 | YÜKSEK → **K3-yönlendirme** | K3-ikinci-boot + N2 #21 madde-3 |
| 9 | ORTA (emsal-değeri) | N2 #21 madde-1 güçlendirici |
| 10 | **TEYİT → kısmi-tekrar**, 6-yan-ürün ayrıştırıldı | 2'si yeni-defter-maddesine terfi (aşağıda) |
| 11 | **KISMEN-GERİ** | H1/H2/H3 şemsiyesi |

### 13.2 İki-yan-ürün-defter-maddesine-terfi (BULGU-10)
- **"yerel ≡ server"** → **AM-T7-9**: *"runbook'lar zaman-dili belirtir (local / server / UTC); belirtmeyen satır runbook-hatasıdır."* Hakem-vurgusu: bu-bir **not değil, risk-ifadesidir.** Uygulaması §H.6-zaman-dili-çizelgesi.
- **"04:10 Ctrl-C = body-sonrası"** → **K3-zamanlama-precision'ı**: Ctrl-C pencere-bitişinde **değil**, day-key-`2026-09-03` penceresinin body-kapanışı-sonrasında; §H.4 sınırlarıyla (N2 #17 imza-kodu ile aynı).

### 13.3 Overwrite-semantiği — CANLI-GÖZLEM (bugünün en-güzel-kanıtı)
`audit.jsonl` **boyutu 3190 SABİT**, mtime ilerliyor: **15:58:52 → 16:00:53 → 16:06:53 → 16:52:58** (4-örnek). BULGU-1'in whole-file-overwrite'i artık **ölçülmüş-davranış**: dosya her flush'ta silip-yazıyor.
> **Hakem-çerçevesi:** *"Bu satır N2 #21 madde-1'in sahada-taşınabilir tek-deneysel imzasıdır — kod-yaşarken davranışı ölçtük, kod-ölmeden düzeltmeye gireceğiz."*
**Düzeltme-sonrası-acceptance-kriteri (öneri, #21'e-girer):** fix-uygulandıktan-sonra **yeni-olay-yokken mtime İLERLEMEMELİ**; ilerliyorsa append-only **kurulmamıştır**. Yani aynı-imza, düzeltmenin-kırmızı-yeşil-lambasıdır.

### 13.4 W1-NİHAİ-SAYIM — MÜHÜR + ayrıntı-hükmü
`0 SIGNAL/SWEEP · 1 ERROR · 3 WRITE_BLOCK` (satır-7 `14:52:40 r8` → satır-8 `14:52:46 ERROR` → satır-9 `14:52:46 r8` → satır-10 `15:51:32 r8`). İki-aşamalı-düzeltme-zinciri §13-uyumlu.
**Ayrıntı-hükmü:** ERROR ile WRITE_BLOCK'un **aynı-saniyede** olması, MT5 block-unlock-timing'ini kayıt-birliğine sokar ⇒ telemetri-şablonuna: **`ERROR-ts ≈ WRITE_BLOCK-ts` eşleşmesinden ayrı-olay-sayımı — "aynı-saniye, iki-sayı-değildir."**
**H3-ekranı:** 14:52→15:51 ≈ 59 dk, saatlik-endonek için **n=2 yetersiz**; H1/H2 aynen-aday. RM-probe payload'ları sonraki olaylarda **"kim tutuyor"** ilk-cevabını verirse H1/H2 ayrışır.

### 13.5 D64 durumu (Hakem-hatırlatmasıyla)
**D64-NİHAİ-MÜHÜR (Option-A seçilmişti; amendment-§5 uygulaması beklemiş).** Bu-envanterdeki "D64 Option A/B" satırı Cline tarafında **AÇIK-ŞART olarak aynen duruyor**; deftere **Aşama-5 wire-note**: `8b18f70a` + §5-bloğu + taze-pin. **D64 dosyasına dokunulmadı.**

### 13.6 Kapı-zinciri (pid 3416 canlı-bekler)
**A — D66-KAMP-1:** W1-KAPALI (sayım mühürlü) → **W2 22:00 (PID 3416 canlı kalır)** → **K3 ikinci-foreground-boot 04:10 `server`** (D68-dikişi ÖNCE; **AM-T7-7/8/9**) → §C-kanıt-zinciri (exit-2 beklenen · close-save · `session_atr`) → 65k-parite → **Aşama-5 COMPARISON tam (SINIF-2-etiketli)** → **B1′ iki-bülten-tek-yayın** → B2 → A6-mühür → N2#19-set-mührü → **N2 #21 (6 madde; owner)** → FAZ-B/N2 #20-pre-reg → Faz-3-owner-paketi. ∥ ③-altı-parça · D69-owner-hattında · **D64-amendment-§5 yazım-döngüsü bekler** · tetik-nöbeti (≈7 h 40 dk; aşım + sinyal-yok → yetki-talebi).

**Tek-cümle:** Envanterle masa dört-katmanlı kayıp-disiplinini canlı-pide ekledi — **11 bulgu mühürlü (BULGU-6 aşağı-çekildi, D68-P0 kod-kanıtıyla bağımsız), iki kayıt-hatası derecesiyle öz-düzeltildi, overwrite-semantiği canlı-davranışa terfi etti** — akış tek-adreste: **Reis → W2 (22:00) ve K3 foreground-boot (04:10).**

## 14. W2-İZLEME + DIŞ-AUDIT ARŞİVİ + BULGU-3 ARİTMETİK-DÜZELTMESİ (17:15 → 17:53)

### 14.1 D72-arb · hash-doğrulama sonucu (bkz. `results/D72_external_rootcause_audit.md`)
Luna 5.6'nın **beş ankoru da gerçek-commit** (5/5 **doğrulanmış**, 0 düzeltme): `a289a48d` audit-chain+JSONL-flush · `d87d1e1` audit-auto-flush · `68878d6` startup_snapshot+lock-contract · `afe6668` PID-liveness+heartbeat · `b36c7c4` boot-time-replay+restore-staleness-gate. ⇒ Ankorlar **BULGU-1/3/8 hatlarının-üstünde**; R1'in-sınıflandırma-değeri **bağımsız-yükseldi.**
**`afe6668` ≠ `afe695b`** (ortak-önek `afe6`, 6. haneden ayrılır; 2-gün-farkı; `fix:` vs `chore:`) ⇒ **Hakem-bayrağı doğrulandı: D53b-zinciri yalnız `afe695b`.** `afe695b` ayrıca **watcher-dirilme-vektörünün** (`Startup lnk → start_watcher.vbs`) bulunup-karantinaya-alındığını ve **N2 #9 "manual start" yanlış-kanısının-düzeltildiğini** taşır — **BULGU-11 watcher-öldürmesinin resmî-kaynak-kanıtı.**
**D25 TEYİTLİ:** `feed.update` / `feed.warmup` / `M1CandleFeed(` → **0 eşleşme**; yalnız `fetch_m1` (`candle_feed.py:103/179/197`) + `_fetch_m1_tri_state` (`orchestrator.py:1849/1905/2169`).

### 14.2 ADER-9 (yürürlükte)
*"Geçmişi ve kod-izini olmayan okuma sınıflandırmayı teyit eder; mekanizma-iddiası üretemez — **mekanizma çapa ister (satır / hash / artifact)**."* R1: 5/5 çapa → mekanizma **aday**. R2 (Gemini 3.8 Flash): **0 çapa** → watchdog-mekanizması **üretemez**, düştü; yerini **ölçülmüş BULGU-3** aldı. İç-envanterin **6/11'i her-iki-dış-okumadan-tam-bağımsız.**

### 14.3 BULGU-3 ARİTMETİK-DÜZELTMESİ (§12.1 — bu-gözlem-sürecinde-oldu)
`phase="startup"` için-önceki-kanıt **`created_at` − boot = 10804 s** idi. **Düşürüldü:** `created_at` **heartbeat-stamp'idir** (`orchestrator.py:621-622` belgelediği **tasarım**; tüketici `:987` `LOCK_STALE_SEC`, `:336-341` stale = pencere **+ ölü-PID**). O-çıpa **process-ayakta-kalma-süresini** ölçüyordu, **sah-takılma-süresini-değil.**
**Geçerli-türetme:** `phase="startup"` gözlem-dizisi **14:58 · 15:29 · 17:08 · 17:48** (4/4) ve çıpa **PID `StartTime` 14:07:49** → son-gözlem `17:48:43` = **3 sa 40 dk 54 sn**.
⇒ **BULGU-3'ün-ÖZÜ DURUYOR ve güçleniyor** (3h00m → **3h41m**; sonuç-değişmedi, kanıt-yolu-düzeltildi). **Yan-bulgu:** `created_at` **adı-yanlış-alan** (`heartbeat_at` olmalı / `boot_at` ayrı olmalı) — tuzak **kanıtlı, çünkü-saha-ajanı-ona-düştü** ve hata **üç ratified-kayda sızdı**. N2 #21-madde-5'in **artık-iki-gerekçesi-var.** Ayrıntı: `progress.md` **D73** + arşiv **§8**.

### 14.4 Overwrite-imzası · 6. örnek ve en-temiz-biçimi
`17:53:44` O1-okuması: **`lines=10` · `size=3190` · `mtime=17:53:44`.** Önceki-5-örnek yalnız-boyut-sabitliği gösteriyordu; bu **üç-değişkenli**: *satır-sayısı sabit + boyut sabit + mtime ilerler* ⇒ **yazar aynı-içeriği-yeniden-yazıyor.** ⇒ **D72(c) lambası bugün KIRMIZI** — *yeni-olay-yokken mtime ilerliyor* ⇒ **append-only henüz kurulmadı**; N2 #21-madde-1 kabul-kriteri **canlı olarak ihlal altında ve kriter işliyor.**

### 14.5 W2 sayımı (O1/O2/O3 altında, 17:53:44)
**`0 SIGNAL/SWEEP · 1 ERROR · 3 WRITE_BLOCK` — W1 mührüyle birebir aynı, değişim YOK.** Share-safe-okuma-altında **yeni WRITE_BLOCK yok** (5 okuma) ⇒ **O4-H3 falsifikasyonu sürüyor**; **H1 (AV/Defender on-access) ve H2 (gözlemci `cp`) hâlâ ayrışmadı**; BULGU-6'nın-aşağı-çekilme-yönü **doğru.**

### 14.6 Bu-turun-sınırı
Kod **DOKUNULMADI** · commit **YOK** · push **YOK** · pid **3416 CANLI/DOKUNULMADI** · D64 ve sweep_detection **DEĞİŞMEDİ** ✓ · **E4/E5/E6 hata-kataloğu maddeleri ile Luna/Gemini düz-yazısı ALMA-BOŞLUĞU olarak açık bırakıldı — uydurulmadı** (§13.5).

---

## 15. D74 · HÜKÜM-UYGULAMASI + CANLI-OLAY (izleme-öznese-değişti)

### 15.1 §14.6-DÜZELTMESİ (§12.1 — üstü-çizilir, silinmez)
~~Kod DOKUNULMADI · commit YOK · push YOK · **pid 3416 CANLI/DOKUNULMADI**~~ ⇒ **pid 3416 ÖLDÜ** (`Get-Process -Id 3416` count **0**, ölçüm 19:19:35). Kod-dokunulmadı / commit-yok / push-yok **duruyor**. **3416'nın çıkış-yolu artık kanıtlanamaz** — SHUTDOWN olayı (varsa) yeni-boot-overwrite'ında-silindi.

### 15.2 W2/K3 kapı-zincirinin-fiilen-kayması
Plan *"W2 22:00 → K3 foreground-boot 04:10"* idi. **19:17:10'da yeni-boot-geldi** (`.venv/Scripts/python.exe -u -m src.live.run_production`, parent `16660` venv-launcher; **`nohup.exe` değil**) ve **W2 daha-açılmadan izleme-öznese-değişti.** ⇒ **K3'ün-ikinci-boot'u kısmen-erken-gelmiş-olabilir**; ancak **§C/graceful-stop/close-save hâlâ-üretilemedi** (boot hâlâ koşuyor, `11476` canlı). **Yeni-özne PID 11476 ile W2 22:00→04:00 izlenir.**

### 15.3 BULGU-3'te-KÖK-DEĞİŞİKLİĞİ (kod-çapalı, bu-turun-en-önemli-teknik-sonucu)
`phase="startup"` **takılı-değildir; alanhİçbir-zaman-durum-taşımamıştır.** `orchestrator.py:920` `_write()` içinde `LockData(..., phase="startup")` **sabitini** kurar; `_write()` yalnız `acquire():758` + `heartbeat():840`'tan gelir; `git grep '\.phase\s*='` src/'de **0**. Gerçek makine `StartupPhase:371-382` (S0→S11) **mevcut** ama **`StartupResult` kwargs'ı** olarak bellekte-kalır, faz **audit'e** yazılır (`:1505-1560`). **Canlı-çürütme:** `19:17:25` `S11/SAFE_START` tamam + `19:17:26` `SAFETY gate=closed`; kilit `19:19:26`'da hâlâ `"startup"`. ⇒ **Süre-iddiaları (10804 s, 3h41m, 4h43m) HEPSİ düşer**; BULGU-3'ün özü (**`phase` ayırt-edemez**) **daha-güçlü** biçimde durur. **N2 #21 madde-5 → "icat et" değil "mevcut `StartupPhase`'i kilide taşı"** (§2.2).

### 15.4 AUDIT-TRUNCATION OLAYI (madde-1 kabul-kriterini-yükseltti)
`18:51:08` → `lines=10 · 3190 B · 0/1/3`; `19:18:41` → **`lines=6 · 1622 B · 0/0/0`** (yepyeni boot dizisi). **mtime-churn değil, satır-imhası.** Kurtarma: `state/audit_prev_2026-09-03.jsonl` (9 satır) + 10.satır touchlog-dökümü ⇒ **metin 10/10, artifact 0/10.** Bayt-özdeş anlık-kopya: `results/D74_audit_snapshot_2026-09-03_1919.jsonl` (1622 B, sha256 `184a95c4…`, **kaynakla özdeş**). **O2 ihlal edilmedi** (`cp`/`cat`/`sha256sum`/`stat` kullanılmadı; `io.open('rb')`). **Öz-eleştiri:** ilk kopya metin-kipiyle alınmıştı → **1616 B, CRLF→LF 6 bayt kayıp**; `'rb'/'wb'` ile düzeltildi.

### 15.5 (D)-BULGUMUN-GERİ-ALINMASI
*"gözlem-aracı kendi satırını yazmıyor"* iddiam **yanlıştı** — `audit_read.py:14-23` `log_touch()` okumadan-önce **makine-damgalı** satır yazıyor. Aracı **açmadan** iddia ettim (**ADER-9 ihlali, kendi-aracıma**). Kalan-doğru: **elle-satırlar tahmin, makine-satırları yetkili** (el `18:02:40` ↔ makine `18:51:08` = 49 dk sapma). ⇒ **N2 #21 madde-6b bu araç için zaten-karşılanıyor.**

### 15.6 Olumlu-teyitler (bozulmayanlar)
**§7.2 persisted-safe-mode → degraded boot ÇALIŞIYOR** (`S11 SAFE_START`, `safe_reasons[0]="safe_mode_persisted"`, `gate=closed`) — **sessiz-resume YOK.** **S9 `COLD_REBUILD_OK`, `replay_bars=4237`, `next_idx=4338`, `bias=neutral`, `end_state=flat`** — D64/D68-dikişinin-beklediği-yapı. **Tek-instance-disiplini korundu** (kilit-sahibi tek: `11476`).

### 15.7 SINIF-2 etiketi ve sınır
Bu-gözlemler **SINIF-2 (gözlem/teşhis)** kalır; hiçbir-işlem-kapısı-açılmadı. **Kod DOKUNULMADI · commit YOK · push YOK · yeni-boot-a DOKUNULMADI (Ctrl-C/kill Reis-yetkisi) · `state/` YAZILMADI · D64 dokunulmadı.**


---

## §17 — D75→D79 PROPAGASYONU (2026-09-03 gece; orijinal-§1–§15 olduğu-gibi-durur, §12.1)

**Bu-bölüm bu-dosyanın üstüne YAZMAZ — eski-satırlar geçersiz-kılındığı-yerde çizgili-kalır.** Aşağıdaki-dört-düzeltme bu-dosyanın kendi iddialarını da vurur.

### 17.1 D75 geri-alma (bu-dosyanın-öncülü olan iddia)

"AM-T7-8 koşulmadı / `audit_prev` yok / pid 3416 kendi-öldü" üçlüsü **yanlıştı.** Ölçüm: `state/audit_prev_2026-09-03b.jsonl` **13 satır / 4376 B @ 19:11:23** (Reis koştu) · pid 3416 → **`taskkill /F /PID 3416`** (Reis-eli, non-graceful). **O4-baseline 3/1 değil 5 WRITE_BLOCK / 2 ERROR.**

### 17.2 D77/D78 — §C-kanıt-zinciri KISMEN-KAPANDI, exit-SAPTI

| §C hedefi (Hakem-iii) | Sonuç | Kanıt |
|---|---|---|
| close-save (D48) | ✅ **ilk-gerçek-egzersiz** | `EURUSD.json` + `_lifecycle.json` mtime **19:50:55** |
| canlı `session_atr` | ✅ | **`0.0004935714285714741`** (`atr_val` 0.0006803779882671913) |
| lock-unlink | ✅ | `orchestrator.lock` yok |
| SHUTDOWN-olayı | ✅ | satır-11 `{"exit":1,"reason":"run_exception:PermissionError"}` @19:50:48.726 |
| **exit-2** | ❌ **SAPMA** | **exit-1** — audit-flush-çökmesi graceful-kodu ezdi (**D78**) |
| Ctrl-C-katkısı | ⚠️ **AÇIK (SINIF-2)** | (a) QuickEdit-copy vs (b) SIGINT→`kill_fn`+flush-çökmesi; stdout'ta `:155`-satırı YOK |

**Kök-neden CANLİ-yakalandı:** `[WinError 5] Access is denied: state\audit.jsonl.11476.tmp -> state\audit.jsonl` — `audit.py`'nin-kendi-etiketi. **Lock-yolu N2 #17 ile in-place'a çevrilmişti; audit-yolu KARDEŞ-DEFECT olarak tmp+`os.replace`'te kaldı.** Asimetri = lock-yaşadı, audit-öldü.

### 17.3 §9 "BEKLİYOR" satırlarının-kaderi

| satır | durum |
|---|---|
| `:54` W2 22:00→04:00 body-formasyonu | **ALINAMADI** — W2 skip (Reis-scheduling); FAZ-B'ye ertelendi |
| `:55` body_high/body_low/tol sayısal-paritesi | **ÖLÇÜLDÜ ✅** → `results/D79_65k_parity_evidence.md` |

### 17.4 §1.6-parite-kapısı KAPANDI — ve bu-dosyanın-tüm-sayıları yeniden-temele geçti

**"65k" script-değil, parametredir:** `SNIPER_WARMUP_COUNT` default **65000** (`run_production.py:80`); D66-çekimi **60000** idi (`d66_detect.py:17`). 65k-koşum: **canlı 15m-bar-sayısı 4338 BİREBİR karşılandı** (`next_idx=4338`), donmuş-tol **0.000244 vs canlı 0.00024678 = %1.1** (60k: **%34.5 sapma**).

**🔴 Bu-dosyanın §1.3/§1.8-5 tablosuna-dair-iki KARAR-DEĞİŞİMİ:**
- **AUDUSD bias `BEARISH` → `BULLISH`** (body aynı `[0.71712, 0.71635]`, tol 0.000275→0.000139). §1.8-5'in **SINIF-1 etiketi geri çekilir → SINIF-2**; +0.75-pip-marfjı −1.36-pip-tol-delta altında işaret-değiştirmesi matematiksel-zorunluluktu.
- **GBPUSD sweep `1 → 0`** — olay-kaybı, sayaç-farkı-değil.
- **EURUSD satırı ROBUST** (body/bias/day_key/start_idx birebir; sweep-event aynı) ⇒ §1.6'nın "EURUSD duyarlıdır" uyarısı **yanlış**; **duyarlılık sembol-bazlıdır.**

**Etiket:** Aşama-5 COMPARISON = **SINIF-2** (offline-harness, pencere-kayması ~6×15m bar, interpreter venv→base). **Bit-parity iddia edilmez; ölçek-paritesi iddia edilir.**

### 17.5 T0#8 — tek-süreç-dayanıklılık-deneyi (devam-ediyor, 21:01 itibarıyla)

> **⚠️ 21:06:48'de İPTAL — T0#8 aynı-hata ile ÖLDÜ (35m00s).** Bu-alt-başlık **olduğu-gibi-korunur** (§12.1); güncel-hüküm `progress.md` **D80-a** ve `D79_65k_parity_evidence.md` **§8.4**. **Çift-süreç-hipotezi burada-zayıfladı sandım → deney onu FALSİFİYE etti.**

Base-python boot **PID 11468 @ 20:31:44**, **tek-süreç** (venv-launcher yok). **29 dk 17 sn · WRITE_BLOCK = 0** — önceki-boot'un 22dk8s-patlama-eşiği **temiz-aşıldı**; `audit.jsonl` tmp+rename **başarıyla** tazelemede. **Çift-süreç-hipotezi zayıfladı; H1/H2 (dalga) güçlendi. Hüküm için ≥60 dk hedefleniyor.** Yan-bulgu: `safe_reasons` dize-yığını 3×/4× kendine-ekliyor — **deterministik payload-bozulması** (iki-boot, iki-interpreter, aynı-imza; race değil) → N2 #21 madde-7 adayı.

### 17.6 Bu-turun-boundary'si

Kod **DOKUNULMADI** · commit/push **YOK** · `state/`-e **yalnız `D77_preserve/`** (additive, 6-dosya + sha256-manifest) · T0#8 **CANLI/dokunulmuyor** · `git add -A` **kalıcı-yasak** (Hakem-§7; `state/` gitignore-dışı + untracked-junk) · sıra-ihlali-özürü **defterde-görünür** (`progress.md` T0#8 §"SIRA-İHLALİ ÖZ-DÜZELTMESİ").
