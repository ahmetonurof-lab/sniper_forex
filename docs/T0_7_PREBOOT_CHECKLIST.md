# T0#7 PRE-BOOT CHECKLIST + RUNBOOK APPENDICES (v1.6 — OPERATİF · D66-KAMP-1 · K3-RATİFİYE · 11-BULGU-MÜHÜRLÜ · AM-T7-11)

> Durum: UNTRACKED taslak — commit T0#7 kanıt-setiyle yapılır (Hakem direktifi 3a).
> Kod-bazlığı: `116117a` (N2 #17). Aşağıdaki TÜM beklentiler koddan-okundu (dosya:satır); tahmin-yok.
> **v1.1:** Hakem ratifikasyonu **AM-1..AM-4 işlendi** (§A taze-baseline · §B aynı-env-şartı · §C mode-bağlı-exit · §D tüm-gözlemciler).
> **v1.2 (2026-09-03, D66-KAMP-1):** **AM-T7-1..6 işlendi** → §F. Kaynak: Hakem hükmü "D66/SINIF-2-KAMP-1 açılışı, T0#7-amendmanlı yürütme".
> **v1.3 (2026-09-03 15:16, Cline):** **AM-T7-7/8 eklendi** → §G (D68-dikişi + §C boot-yolu şartı). *Not: v1.3'te ID-sıralaması Cline-tercihiydi; v1.4'te Hakem-numaralarına çevrildi (takas-aşağıda, §H).*
> **v1.4 (2026-09-03 15:30, Hakem hükmü "K3 RATİFİYE"):** **AM-T7-7 ↔ AM-T7-8 takas edildi** (hüküm-metni yetkili) + §H K3-boot-runbook + launch-modu-alanı zorunlu.
> **v1.6 (2026-09-03 19:25, Hakem hükmü "D72-KAPANIŞ" + D74 saha-olayı):** **AM-T7-10** (`git diff --stat AGENTS.md` beyanı) + **AM-T7-11** (`*.tmp` aramalarında-kesin-ad-beyanı) → **yeni §I**. §H.4'te **BULGU-3 mekanizması kökten-düzeltildi** (`phase` bir **sabit**, takılı-durum-değil). §A'ya **audit-truncation olayı** ve **madde-1 kabul-kriteri yükseltmesi** işlendi. **AM-T7-12** (K3-öncesi `AGENTS.md` owner-commit adımı) → §I.3.
> **v1.5 (2026-09-03 16:53, Hakem hükmü "BULGU-ENVANTERİ RATİFİYE"):** **AM-T7-9 eklendi** (runbook-satırları zaman-dili belirtir) → §G tablosu + **yeni §H.6 zaman-dili-çizelgesi**. Ayrıca **BULGU-6 derecesi aşağı-çekildi** (vaka-güçlendici atfı silindi; D68-P0 artık **BULGU-1 kod-kanıtından-bağımsız-taşınır**), ve **N2 #21 madde-4 telemetri-şablonu** üç-alt-maddeyle-genişledi (aynı-saniye-iki-sayı-değil / H3 n=2 yetersiz / RM-probe "kim-tutuyor"). *Sıra-düzeltmesi:* §G tablosu 8→7→**9** olarak okunur (Hakem-numara-otoritesi).



## A. Donmuş-3944-lock — pre-boot artefakt + beklenti-tablosu

**Artefakt (önsel kayıt: 2026-09-03 00:05 local):**
```
state/orchestrator.lock = {"pid": 3944, "created_at": 1788381955.5328035, "phase": "startup"}
mtime_age(kayıt-anı): 798 s · PID 3944: DEAD (tasklist doğrulandı)
```
**ELLE SİLİNMEZ** — takeover'ın gerçek kanıtı bu boot'un en değerli artifact'ıdır.

**AM-4 — BOOT-ÖNCESİ TAZE-BASELINE (zorunlu adım; 00:05-kaydı yeterli değil):**
Boot başlatılmadan HEMEN önce yeniden kaydet ve kanıt-setine yaz:
```
cat state/orchestrator.lock
python -c "import os; print(os.stat('state/orchestrator.lock').st_mtime)"
tasklist /FI "PID eq 3944"          # beklenen: boş liste (DEAD)
```
→ Takeover-kanıtı **önce/sonra çifti bu-baseline ile mühürlenir** (sonra = yeni-PID lock-json).
→ **Aynı-adımda AM-1 mod-kaydı:** boot-anında fiili-mod (S11 verdict: FULL / SAFE_START) kanıt-setine YAZILIR — §C exit-beklentisi bu moda bağlıdır.

**Beklenen dal** (`orchestrator.py` Lock.acquire 711–759, _is_stale 982–987, run_production 99–111):

| # | Adım | Kod | Beklenen |
|---|------|-----|----------|
| 1 | pre-guard | run_production.py:106 `pre_pid is not None and _pid_alive(pre_pid)` | 3944 DEAD → guard **GEÇER** (exit-0 olmaz) |
| 2 | _read | geçerli JSON | **parse-OK** → LOCK_CORRUPT **BEKLENMEZ** (A9 yalnız JSONDecodeError; EventType.LOCK_CORRUPT, orchestrator.py:1067–1079, instance-başına-tek) |
| 3 | _is_stale | `if not _pid_alive(data.pid): return True` (985–986) | **dead-PID → ANINDA stale** (900s-yaş-penceresi İKİNCİ moddur: live-but-wedged; `LOCK_STALE_SEC=900`, satır 444) |
| 4 | takeover | acquire satır 758 `self._write()` | in-place-write → lock JSON yeni-PID + phase=startup olur |
| 5 | boot-devam | S9 replay → S11 verdict | credential'lı-runbook → **PROCEED** |

**Yakalama-kanıtı:** lock-json önce/sonra · audit STARTUP(S9/S11) · stdout-log.
**Başarısızlık-imzaları:**
- `LockError: Lock held by PID …(phase=…, age=…s)` → PID canlı-okundu → DUR + tasklist kanıtı.
- `Lock target unreadable (torn/blocked) and not stale-eligible — boot refused (N2 #17)` → dosya bozuk → ham-byte-kaydı + bu-dalda LOCK_CORRUPT beklenir.
- JSON-geçerli-iken LOCK_CORRUPT → kod-hatası → kanıtı-donudur, Hakem'e.

## B. Pre-guard canlı testi (dual-instance — 116117a canlı-atestasyonu)

**AM-2 GÜVENLİK-ŞARTI (zorunlu):** ikinci-deneme **AYNI-ENV koşullarında** çalıştırılacak — **aynı `SNIPER_STATE_DIR` dahil** (aynı-workspace, aynı-runbook-ortamı). Gerekçe: ikinci-instance farklı-state-dir ile kalkarsa pre-guard canlı-lock'u GÖREMEZ → `exit-0` yerine **ikinci-gerçek-instance** = dual-instance-riski (testin sahte-negatifi production'a taşınır).
**Zaman-penceresi:** PROCEED-görüldükten SONRA, graceful-stop-ÖNCESİ. Test-sonrası `tasklist` ile ikinci-instance-süreç-yokluğu teyit edilir.

İkinci-boot denemesi (aynı-şartta):
```
python -m src.live.run_production
```
**Beklenen (run_production.py:107–111):** stderr'de BİREBİR:
`[run_production] Already running (lock owner PID <canlı_pid>) - EXIT` ve **exit-code 0**.
İkinci-instance lock'a DOKUNMAZ, audit'e olay YAZMAZ. (Not: string **stderr**'e gider — runbook `2>&1` yönlendirmesiyle logda görünür.)
**Kanıt-şablonu:** ikinci-instance stderr + exit-code + deneme-sırasında canlı-instance audit-değişmezliği + sonras `tasklist` teyidi.

## C. Graceful-stop prosedürü (D58-kapanış-adayı)

**YALNIZ foreground-konsol Ctrl-C** (arkaplan-MSYS-kanalı ölü-ucuz — ledger D58).
**Beklenen-zincir** (orchestrator.py 2595–2612, 2796–2813, shutdown 1604–1685):

| # | Olay | Beklenen-kanıt |
|---|------|----------------|
| 1 | SIGINT→_on_signal→_kill_requested | ≤1s-uyku-parçasında döngü-çıkışı (D46) |
| 2 | SHUTDOWN audit | payload `{"reason": "kill_switch_during_sleep" (uyku-içi — OLASILIKLI) veya "kill_switch" (döngü-başı), "exit": code}`; **AM-1 — code MODE-BAĞLIDIR:** koşul-zinciri `2 if (runtime_safe or not entries_enabled) else 0` → **PROCEED+FULL → `0`** · **PROCEED+SAFE_START → `2` = BEKLENEN-DAVRANIŞ, sapma-DEĞİL** (fiili-mod §A AM-4 adımında S11-verdict'ten kanıt-setine yazılmıştır) |
| 3 | audit.shutdown() | senkron final flush |
| 4 | D48 close-save | `schedule_snapshot` (recovery.py:187–191) → `state/<SYM>.json` + `state/<SYM>_lifecycle.json` mtime = stop-anı (**AM-T7-1: sembol-parametrik** — boot `SNIPER_SYMBOLS` ile hangi sembolü kaldırırsa onun dosyaları; EURUSD-donanımı YOK) |
| 5 | lock.release() | `state/orchestrator.lock` **SİLİNİR** (unlink, 769) |
| 6 | stdout | `[run_production] exit code <0 VEYA 2 — §A mod-kaydıyla eşleş>` (AM-1: koşulsuz-`0` şablonu SAFE_START-boot'ta sahte-sapma üretir) |
| 7 | K5-dump | **YOK** — `crash_log.txt` bayt-bazında-değişmez (AUDIT_FALLBACK_DUMP yalnız flush-HATA dalı, kind=1596) |

**Kanıt-şablonu (copy-then-read!):** `cp state/audit.jsonl /tmp/a && tail -3 /tmp/a` · snapshot-mtime'ları · lock-yokluğu · stdout-tail · crash_log-değişmezliği · mod-eşleşme-teyidi (S11-verdict ↔ exit-code).
**Sapma:** shutdown_snapshot hatası → ERROR `{"phase":"shutdown_snapshot"}` (1672–1679) = K3 loud-fail çalışıyor; yakala, gizleme.
**T0#7 ZORUNLU-BEKLENTİSİ (Hakem hükmü D.2, 2026-09-03 — tek-satır-ek, mevcut-satırlar-dokunulmadı):** T0#7 **çökse bile kalıcı-log bırakmak ZORUNDA**dır; T0#5/T0#6 **hiç kalıcı-log bırakmadı** (tek ham crash-log = T0#4), dolayısıyla **"log-yokluğu şeklinin kırılması" testin parçasıdır**. Flush-hipotezi: **GÜÇLENDİ, DOĞRULANMADI** — etiket T0#7-K5'e kadar değişmez.

## D. WRITE_BLOCK gözlem-protokolü (kalıcı-kural-2)

**Kural:** gözlemci kanonik-state'e canlı-handle tutmaz — **copy-then-read** (audit.jsonl/crash_log için tek-atışlık `cp` sonra kopya-okuma; döngüsel tail/grep YOK).
**AM-3 — KAPSAM:** bu-kural **TÜM gözlemcileri bağlar — REIS-KONSOLU DAHİL** (canlı `tail`/`grep` kanonik-dosyada YOK; gözlem daima kopya-üzerinden). Not, bülten-yayınıyla üçlü-kanala (Hakem/Luna/owner) da girer.
Beklenen-sayım (T0#7 penceresi): **0** (lock-yolu-yapısal-bağışık — in-place).
Her-olay → payload `{error, file, retries}` + **K1 RM-probe** alanları (`holder_pids/holder_names/probe_errors`) deftere → ilk-gerçek "kim-tutuyor" cevabı.

## E. Dokunma-listesi (değişmez — Hakem §4)

Sep-1 `*.tmp` kalıntıları (owner-kararı) · donmuş-3944-lock (§A) · `PYTHON_YOK` · `audit.jsonl` tmp+rename-kalır (D18-sınıfı; d4-kod-değişikliği-DEĞİL, protokol-dersi).

## F. AM-T7 AMENDMANLARI (v1.1 → v1.2 · Hakem hükmü D66-KAMP-1 · boot-öncesi-işlendi)

| # | Amendman | Durum / kanıt |
|---|---|---|
| **AM-T7-1** | §C.4 dosya-adları sembol-parametrik `<SYM>.json` | **İŞLENDİ** (§C satır-4 yeniden-yazıldı) |
| **AM-T7-2** | Swap-boot beklentisi: X-snapshot-yok → **S9 COLD_REBUILD_OK**; EURUSD-restore **BEKLENMEZ**; bias-end-state = replay-sonu; replay-içi bias-transition'ın audit ateşleyip-ateşlemediği **fiili-kayıt** (presuppose yok) | **KOŞUL GERÇEKLEŞMEDİ:** Aşama-1 tespiti **X == EURUSD** verdi (tie-break en-erken-ts: `2026-09-02 16:15 bullish`) → **swap-yok**, `SNIPER_SYMBOLS` override **GEREKMEDİ**, `.env`-dokunulmadı. Amendman-yetkisi ayakta; bu-boot EURUSD-plain. Restore-beklentisi yine-de geçerli: `state/EURUSD.json` mtime **Sep 1 23:59** (≈38h bayat) → **COLD_REBUILD beklenir**, restore DEĞİL |
| **AM-T7-3** | Capture-before-boot (adım-0 prerequisite; çökse-bile barlar arşivde) | **YERİNE GETİRİLDİ:** `state/d66_capture/` 6/6 sembol · 1551–1552 M1 · server `2026-09-02 12:00 → 09-03 13:52` · sha256-pin'li · `_capture_manifest.json`. Boot-bağımsız-arşiv ✓ |
| **AM-T7-4** | `trade_mode=SAFE_START` **explicit** — monitor-only yapısal (Reis-sınırının mührü) | **YAPI-OLARAK-ZORUNLU:** `run_production.py:79` `expected_login=os.getenv("MT5_EXPECTED_LOGIN") or None` → unset → safe. Çift-güvence: `state/orchestrator_safe.json` persisted (`reason:"expected_login_unset"`) ve §7.2 gereği **SİLİNMEZ** (clean-startup laundering yasağı). **Kredibilgi-hattı Reis'e aittir — Cline `MT5_EXPECTED_LOGIN` set ETMEZ.** PROCEED/FULL + ilk-send **ayrı-hüküm** |
| **AM-T7-5** | D66-deliverable + D65 sınıf-etiketleri zorunlu | `results/D66_sweep_detection.md` (**SINIF-1/SEÇİM**) · `results/D66_production_path_first_observation.md` (**SINIF-2/GÖZLEM**, Aşama-5) — her-ikisinde sınıf-etiketi dosya-başlığında |
| **AM-T7-6** | §A **aynen** — donmuş-3944-lock takeover **sembol-bağımsızdır**; artifact-koru; pre-guard/§B aynen | **KORUNDI** (§A/§B metnine dokunulmadı). Kod-sözleşmesi-teyidi: `orchestrator.py:985–986` dead-PID → anında stale; `pid 3944` 2026-09-03 13:5x'te `Get-Process` ile **DEAD** doğrulandı; lock-yaşı ≈14s ≫ `LOCK_STALE_SEC=900` (:444). **ELLE SİLİNMEZ** (takeover-kanıtı) |

### F.1 Cline-teşhis-notu (boot-öncesi-ölçüldü — §4.4: görünen-başarısızlık/ayrışma)
1. **Pencere-bazı düzeltmesi (hükmün §2-pinine):** `candle_feed.py:113–118` M1'i **server→UTC** çevirir; `SessionManager.in_window` bu **UTC** saat üzerinde çalışır → CBDR penceresi **UTC 19:00→01:00 ≡ server 22:00→04:00**, sweep-bandı **server 04:00→22:00**. Hüküm-pin'i "04:00→19:00" idi: **04:00-ucu-doğru, 19:00-uca-3s-yanlış** (`clock.py:13` docstring'i "server time" diyerek kendi dönüşümüyle çelişiyor). `clock.in_session(dt_server)` üretimde **çağıran-yok** (yalnız `tests/test_live_candle_feed.py:296–300`) → ölü-kod/latent-tuzak. **Aşama-4 W2-pini (22:00→04:00) düzeltmeyi bağımsız-doğruluyor.**
2. **Tolerans-çapası:** `session.atr` canlıda da warmup'ta-donuyor (`strategy_runtime.py:176`; `on_bar` güncellemez). Canlı `state/EURUSD.json`: `session_atr=0.000595714` → **tol=0.000297857**, `bars[0]=2026-06-30T11:57`, `_start_idx=101`. Offline rekonstrüksiyonun toleransı 60k-çekim nedeniyle **0.000332** (canlı default `SNIPER_WARMUP_COUNT=65000`). → **Aşama-5'te offline-tarama canlıdan-okunan `session_atr` ile yeniden-koşulmadan parity iddia edilmez.**
3. **Warmup-konumu ayrışması (pre-reg §0.4 doğrulandı):** V-LIVE/V-PIN arasında **iki-sembolde karar tersine dönüyor** (EURUSD 1→0 sweep; USDCAD NEUTRAL→BULLISH-locked). Mekanizma: `warmup()` `session.update()` **çağırmaz** → body-accumulation `_start_idx`'te başlar → V-PIN scope-başında **yapısal-kör**. **V-LIVE enstrüman olarak seçildi (gerekçe-mekanizmal, tercih-değil).**
4. **Kalıcı-log kapasitesi:** boot `SNIPER_WARMUP_COUNT` default **65000 M1** çeker; MT5 bu-çekimi-veriyor (ölçüldü: 60k → server `2026-07-07 20:53`'a-kadar).
5. **Graceful-stop kısıtı (boot-öncesi-deklare):** §C "YALNIZ foreground-konsol Ctrl-C" der; arkaplan-kanalı Sep 2'de denendi ve **başarısız** (`t07_ctrlc_result.txt: attach=1 err_att=187`). Cline'ın-non-interactive-ortamı SIGINT-veremez → **kill-switch-zamanlaması Reis'te** (hükmün rol-taksimiyle-uyumlu). Cline §B dual-instance-testini ve copy-then-read gözlemi yürütür.

## G. D68 AMENDMANLARI (v1.2 → v1.3 · Hakem hükmü D68 + W1 canlı-kanıtı)

| # | Amendman | Gerekçe / kanıt | Durum |
|---|---|---|---|
| **AM-T7-8** | **Boot-öncesi TEK-ATIMLIK audit-copy (ZORUNLU adım-0.5):** `cp state/audit.jsonl state/audit_prev_<YYYY-MM-DD>.jsonl` — **mask-bağımsız**, her-boot-öncesi, kod-dokunuşu-yok | **Bulgu-1/D68:** `orchestrator.py:1040` `AuditChain`'i mevcut dosyayı **load etmeden** kurar; `audit.py:247–255` `save()` whole-file overwrite (`tmp.replace`); `AuditChain.load()` üretimde **sıfır çağıran** → her boot önceki zinciri yok eder. Ölçülen kayıp: Sep-2'nin 7 satırı. | **YÜRÜRLÜKTE** — ilk icra `state/audit_prev_2026-09-03.jsonl` (9 satır/2765 B, 14:58) |
| **AM-T7-7** | **§C graceful-stop için boot-YOLU şartı:** Ctrl-C ile stop edilecek instance **Reis'in interaktif terminalinden** başlatılmalı; **`nohup`/arkaplan-launch ile §C kanıt-hedefi KARŞILANAMAZ** (pre-flight'ta sorulacak) | **Bulgu-8:** `schedule_snapshot` (D48 close-save) üretimde **tek-çağıran** = `orchestrator.py:1661`, `shutdown()` gövdesi-içi; `recovery.py:187–191`; yorum: *"per-N-bar periodic save — graceful path alone cannot shrink the kill-9 window"* → **periodic save YOK**. `orchestrator.py:2364–2365` yalnız SIGINT+SIGTERM, **SIGBREAK YOK**; Windows `os.kill(SIGTERM)`→`TerminateProcess` (handler çalmaz). Kanıt: `crash_log.txt` satır-2 `parent: "19088: …nohup.exe"` → pid 3416'nın **konsolu yok** | **AÇIK — bu-boot (pid 3416) bu şartı KARŞILAMIYOR**; K1/K2/K3 kararı Reis+Hakem'de |
| **AM-T7-9** | **Runbook-satırları ZAMAN-DİLİ belirtir (`local` / `server` / `UTC`):** her-saat-alanı etiketli-yazılır; **etiket-yoksa satır runbook-hatasıdır** ve düzeltilmeden runbook koşmaz | **BULGU-10 yan-ürünü (b):** yerel-makine ≡ server (Eylül, offset +3) — bu-bir *not* değil **risk-ifadesidir**: etiketsiz-saat, iki-zaman-diliminin çakıştığı her gün (DST-sınırı, kış-offset +2, farklı-makine) **sessizce yanlış-pencereye** düşer. §6.3 timezone-disiplininin runbook-katmanı | **YÜRÜRLÜKTE** — §H.2/§H.5 etiketlendi |

### G.1 §C.4-sonrası yeni doğrulama maddesi (close-save-kanıtı)
Graceful-stop sonrası **üçlü-eş-zaman** kontrolü zorunlu: `state/EURUSD.json` mtime **≈ stop-anı** + `session_atr` **bayat-değil** + `EURUSD_lifecycle.json` mtime. Üçü-birlikte-yoksa **stop graceful DEĞİLDİR** (sessiz-close-save-başarısızlığı = §7.2 laundering-ailesi). Not: `state/EURUSD.json` mtime **Sep 1 23:59:03** ve **pre-N2#15 kodun** ürünü (yetim `audit.jsonl.tmp` ile aynı-saniye) → **bayat-artefakt parity-kanıtı olarak kullanılamaz** (Bulgu-7).

### G.2 W1 gözlem-kuralı (Bulgu-6 düzeltmesi)
"W1'de ERROR yok" iddiası **yalnız** `SIGNAL|SWEEP` için geçerlidir; `ERROR phase=audit_flush` **ayrı-sayılır** ve raporlanır (§13 — hidden-red yasağı).

## H. K3 RATİFİYESİ (v1.4 · Hakem hükmü 2026-09-03 15:30)

### H.1 Yetkili amendman-metinleri (Hakem-sözcükleriyle)
- **AM-T7-7 (launch-modu):** *"Launch-modu kanıt-zincirini belirler: **nohup/arkaplan = graceful-imkânsız (§C-YOK)**; **foreground-konsol = §C-üretilebilir**. Boot-runbook'una **launch-modu-alanı** eklenir."*
- **AM-T7-8 (D68-dikişi):** *"Boot-öncesi-audit-copy (D68-dikişi) **zorunlu-adım**; hedef-dosya `state/audit_prev_<date>.jsonl`."*
- **Sınıf-düzeltmesi (Hakem, BULGU-6 başlığına):** WRITE_BLOCK/WinError-5 ailesi **D35-ownership-fatal DEĞİLDİR** (N2 #15-b hükmü). Dolayısıyla W1'deki `ERROR phase=audit_flush` bir **"ERROR-beyanı-nüksü" değil, "sayım-beyanı-düzeltmesi"**dir — rapor-başlığı bu-adla açılır.

### H.2 K3 · İKİNCİ-BOOT RUNBOOK (Reis'in interaktif terminali — tek-adres)
| Adım | Eylem | Beklenen-kanıt |
|---|---|---|
| 0 | **D68-dikişi (AM-T7-8):** `cp state/audit.jsonl state/audit_prev_2026-09-03.jsonl` | copy satır-sayısı = kaynak; **yeniden-kayıp-riski sıfır** |
| 1 | **Foreground-konsolda** boot (nohup YOK): `python src/live/run_production.py` | `crash_log.txt`'e **yeni `writer_diagnostic` satırı** `parent:` alanında **`bash.exe`/`cmd.exe`** yazar (**`nohup.exe` DEĞİL**) — launch-modu-kanıtı budur (AM-T7-7) |
| 2 | Kısa-observasyon (~10 dk) | `S9 COLD_REBUILD_OK` · `S11 SAFE_START` · `session_key` gün-anahtarı · gate CLOSED |
| 3 | **§B ikinci-atır:** aynı-env'da ikinci-instance | `Already running (lock owner PID <yeni>) - EXIT` |
| 4 | **Gerçek foreground Ctrl-C** | **exit-code 2** (AM-1 mode-bağlı; SAFE_START'ta beklenen, **sapma DEĞİL**) |
| 5 | **§C.4 üçlü-eş-zaman (G.1)** | `state/EURUSD.json` mtime ≈ stop-anı **+** `session_atr` **bayat-değil** **+** `EURUSD_lifecycle.json` mtime → **D48 close-save gerçekten koştu** (`schedule_snapshot:1661`) |
| 6 | K5/negatif-kontrol | **K5-dump YOK**; `crash_log.txt` **bayt-sabit** (append-only, 2 satır); lock **unlink** (769) |
| 7 | **65k-tarama yetkisi (Hakem-iii) otomatik-açılır** | Adım-5'ten okunan canlı `session_atr` → `tol=0.5·session_atr` → offline-tarama **canlı-çapayla** → **§1.6 parity** |

**Zorunlu-uyarı:** Adım-5 üçlüsü eksiksiz değilse **stop graceful SAYILMAZ** ve parity iddia edilemez (§7.2 laundering-ailesi).

### H.3 Boot-runbook'una yeni ZORUNLU alan (AM-T7-7 gereği)
Her-boot-kaydında şu-iki-alan boş-bırakılamaz: **`launch_mode ∈ {foreground-console, nohup, other}`** ve **`§C_producible ∈ {yes, no}`**. `launch_mode ≠ foreground-console` ise **§C/exit-2/close-save beklenmez** — beklenti-kaydı önceden yazılır (sonradan-keşif-değil).

### H.4 BULGU-3 genişleyen-kanıt (N2 #21 madde-5 risk-satırı)
Kilidin `created_at` alanı heartbeat ile tazelemeye devam ederken `phase` **boot'tan 1s21dk sonra bile `"startup"`**: 14:58 → `created_at 1788436708.0007718`; 15:29 → `created_at 1788438550.3587976` (+1842 s); her-ikisinde `phase="startup"`. → **wedged-startup ile normal-startup ayırt edilemiyor**. ~~**Ölçüm 81 dk → 3 sa 00 dk'ya çıktı** (17:08: `created_at 1788444500.47` − boot `1788433696.66` = **10804 s**, `phase` hâlâ `"startup"`).~~ **D73-DÜZELTMESİ (bu-satırda-iç-çelişki-vardı):** `created_at` heartbeat ile-tazelendiği için **sah-ne-kadar-takılı** değil **process-ne-kadar-ayakta** verir; bu-çıpayla-türetilen-süre **geçersizdir.** **Geçerli-türetme = gözlem-dizisi:** `phase="startup"` **14:58 · 15:29 · 17:08 · 17:48** — dördünde-de `startup`; boot `14:07:49` (PID `StartTime`) → son-gözlem `17:48:43` = **3 sa 40 dk 54 sn**. ⇒ **Ölçüm 81 dk → 3 sa 41 dk**; **sonuç aynı, kanıt-yolu düzeltildi.** **Yan-bulgu (madde-5'e-girer):** `created_at` **adı-yanlış-alan** — `heartbeat_at` olmalı ya-da `boot_at` ayrı-tutulmalı; tuzak **kanıtlı**, çünkü-saha-ajanı-ona-düştü (bkz. `results/D72_external_rootcause_audit.md` §8). **N2 #21 madde-5 risk-ifadesi:** ~~sapma-büyüklüğü artık boot-süresiyle-sınırlı-değildir — wedge, gözlem-penceresinin tamamını kapladı; ayrım-yolu `phase` değil, ayrı-bir-progress-kimliği-gerektirir.~~

**D74-KÖK-DÜZELTMESİ (bu-bölümün-tüm-süre-türetmeleri-GEÇERSİZ — mekanizma-başka-çıktı):**
`(A)`-hükmünün-yeni-çapası (`StartTime`→`14:58`→`≥4h43m`) koddan-doğrulanmaya-çalışıldığında **`phase` alanının bir SABİT olduğu bulundu**:
- **`orchestrator.py:920`** — `_write()` her çağrıldığında `LockData(pid=os.getpid(), created_at=time.time(), phase="startup")` **kuruyor** ⇒ `phase` **hardcoded-literal**, hiçbir-kaynaktan-okunmuyor.
- `_write()` **yalnız iki-yerden:** `acquire()` `:758`, `heartbeat()` `:840`. `git grep '\.phase\s*='` (src/, tests-hariç) → **0 sonuç** ⇒ kilit-fazı **hiçbir-yerde mutate edilmiyor.**
- Gerçek durum-makinesi **VAR**: `StartupPhase` `:371-382` (S0→S11, 11-durum). 14-kullanım-noktası (`:1165-1565`) **`StartupResult(...)` kwargs'ı** = bellek-içi-dönüş-değeri; gerçek faz **audit'e** yazılıyor (`:1505-1560`, `EventType.STARTUP {"phase":"S9"/"S11","verdict":…}`).
- **CANLI-ÇÜRÜTME (19:17 bootu):** audit `19:17:25` `S11 / SAFE_START` **tamamlandı** + `19:17:26` `SAFETY gate=closed reason=startup_SAFE_START`; kilit `19:19:26`'da **hâlâ `phase="startup"`.** ⇒ **Tamamlanmış-startup ile wedged-startup lock'ta AYNI baytı üretir.**

**YENİ-DOĞRU-ĐFADE:** ~~`phase="startup"` 3h41m / 4h43m boyunca ilerlemedi (wedged-startup ayırt edilemiyor).~~ ⇒ **`phase` hiç-ilerlemez — çünkü-hiçbir-zaman-durum-olmadı. "3h41m/4h43m" ölçümleri bir-literal'in n=4/n=5 tekrarüdür, süre-ölçümü-değildir.** BULGU-3'ün **özü kalır** (`phase` startup↔wedged ayırt-edemez) ama **nedeni "yapışkanlık" değil "bağlantı-eksikliği"dir.**
**N2 #21 madde-5 YENİDEN-KAPSAM (§2.2 "mevcut-mekanizmayı-yeniden-keşfetme"):** madde *"ayrı progress-kimliği icat et"* diyordu. **Kimlik mevcut ve audit'e yayınlanıyor.** Doğru-kapsam: **`StartupPhase`'i `LockData`'ya taşımak** (`_write()`'a gerçek-faz-parametresi + faz-değişiminde-yazım), **yeni-soyutlama-değil.**
**Tuzak-notu (kendi-kaynağa-karşı):** bu-bölümdeki **her-iki-süre-türetmesi de** (`10804 s`, `3h41m`) **aynı-kök-nedenden** doğdu: *sabit-bir-alanın-değişmemesini "takılma" saymak.* **Kural-adayı: "bir-alanın-stuck-olduğunu-iddia-etmeden-önce, o-alanı-yazan-kod-kolu-bulunmalı; yoksa-iddia-alan-hakkındadır, olay-hakkında-değil."**

### H.5 Saat-türetimi (BULGU-10 · runbook kendi-kendine-yeterli olsun diye)
- **Yerel-makine ≡ server-saati** (Eylül: `clock.py:20-21` yaz-offset **+3**; makine de UTC+3 — ölçüm `date -u` 12:46 / yerel 15:46). ⇒ **Bu runbook'taki TÜM saatler doğrudan duvar-saatinden okunur, çeviri YOK.**
- **CBDR body-penceresi = server 22:00 → 04:00** (kod-türetimi: `session.py:19-20` UTC `h>=19 or h<1` + `candle_feed:113-118` server→UTC + offset +3; emsal `CBDR_TIME_SEMANTIC_ALIGNMENT_RAPORU.md:179`).
- ⇒ **Adım-4 (Ctrl-C) 04:10'da pencere KAPANDIKTAN sonradır** — body-tamamlanmasını bölmez. W2-bitimi (22:00) ile yeni-pencere/day-key açılışı çakışır; **aynı-anda iki-olay, karışıklık yok.**
- **Uyarı (tuzak):** `clock.py:23` pencereyi "MT5 server time" diye etiketler — **o fonksiyon üretimde hiç çağrılmaz** (yalnız `tests/test_live_candle_feed.py:298-300`). Canlı-yol `SessionManager.in_window` (**UTC**). Saati buradan türetmeye kalkışma; §H.5'i esas al. (N2 #21 madde-6.)

### H.6 ZAMAN-DİLİ ETİKETLERİ (AM-T7-9 · §H.2 satırlarının okuma-anahtarı)
AM-T7-9 gereği §H.2'deki her-zaman-ifadesinin dili **şu-çizelgede sabittir** — runbook'u koşan kişi saatleri duvar-saatinden-okur, **çeviri yapmaz**, ama **etiketi bilir**:

| §H.2 adım | Zaman-ifadesi | **DİL** | Dayanak |
|---|---|---|---|
| 0–1 | boot-anı (04:10 civarı) | **`local` ≡ `server`** | `clock.py:20-21` yaz-offset +3; makine UTC+3 (ölçüm `date -u` 12:46 / yerel 15:46) |
| 2 | `session_key` gün-anahtarı | **`server`** (MT5 bar-etikeyti) | `candle_feed` server-bar'larını olduğu-gibi etiketler; UTC'ye **yalnız** `in_window` kararı için çevirir (`:113-118`) |
| 4 | Ctrl-C **04:10** | **`server`** (= `local`) | Body-penceresi **UTC 19:00→01:00** ≡ **server 22:00→04:00** ⇒ 04:10 = **body-kapanışı-sonrası** |
| 5 | "mtime ≈ stop-anı" | **`local` dosya-mtime'ı** | FS zamanı yerel-saattedir; stop-anı-da-yerel ⇒ **aynı-dil, karşılaştırma-meşru** |
| 7 | `session_atr` tazelik-ölçütü | **`local`** | Adım-5 ile aynı-dil |

**Kural-uygulaması:** Bu-tablodan-çıkan-hiçbir-satır "saat" demez, **"saat (`dil`)"** der. **Kış-döneminde (offset +2) `local ≡ server` eşitliği BOZULMAZ** (ikisi-de aynı-makinede), ancak **pencere-saatleri kayar** (body 23:00→05:00 olur) ⇒ **§H.5 yeniden-türetilmeden kış-runbook'u koşulamaz.** Bu, AM-T7-9'un asıl-gerekçesidir: eşitlik-bugünkü-ölçümdür, **ezel-kadî-değil.**

---

## I. D74-AMENDMANLARI (Hakem hükmü "D72-KAPANIŞ" + saha-olayı)

### I.1 AM-T7-10 — commit-öncesi `AGENTS.md` beyanı (ZORUNLU)
Her commit-öncesi: **`git diff --stat AGENTS.md`** çalıştırılır ve çıktısı commit-beyanına-yazılır. **Diff, paralel-hat (owner) beyanıyla uymuyorsa DUR.** Gerekçe: `AGENTS.md` şu-an **+17 satır commit-edilmemiş** içerikle (bölüm *Aşama-5: Crash/Fix-Bildirim Üçlü Kanal Zorunluluğu*) **masa-dışında-yazılmıştır**; §9.5 anlamında **set-değişimi** riskidir — istem-dışı-yolcu olursa push-yetkisi-kendi-kendine-genişlemiş-olur.

### I.2 AM-T7-11 — `*.tmp` aramalarında kesin-ad-beyanı (ZORUNLU)
Yetim-artefakt ararken **küresel-desenle-iddia-üretilmez.** Zorunlu-biçim:
```
find state/ -maxdepth 1 -name '*.lock.*tmp' -printf '%s %TY-%Tm-%Td %TH:%TM %p\n'
```
çıktısı **olduğu-gibi** kanıt-setine-girer; **çıktıdaki-ad neyse odur.** Gerekçe (D73-ek-5): devir-notu `state/orchestrator.lock.3944.tmp` adını **artefakt-diye-sundu**; `find . -name '*3944*'` → **0 sonuç**. Gerçek: 3944-kilidi **`.tmp` adıyla-hiç-var-olmadı**, `state/orchestrator.lock` **canlı-yolunda** oturuyordu ve **takeover tarafından üzerine-yazıldı.** `state/orchestrator.lock.tmp` ise **`{"pid": 16984, …}`** içerir — **3944 ile-ilgisi yok.**
⇒ **§A'daki "ELLE SİLİNMEZ" emri fiilen-geçersizdir** (korunacak-dosya-yoktu; korunacak-anlık-değer **alıntılanmıştı**). **3416/3944 takeover-kanıdı artık seviye-6 düz-yazıdır, seviye-5 artifact-değildir** (§3 hiyerarşisi; §12.1 gereği-cümle "artifact-mış-gibi" kurulamaz).

### I.3 AM-T7-12 — K3-öncesi `AGENTS.md` owner-commit adımı (ZORUNLU)
K3 ikinci-boot checklist'ine **boot-öncesi** adım olarak girer: *"paralel-hat yazarı (owner) kendi `AGENTS.md` commit'ini **K3 öncesi** kendi-başına-yapar; masa-hattı K3 kanıt-setinde `AGENTS.md`'yi **A6-sınırı gibi set-dışı** tutar."* ⇒ istem-dışı-yolcu riski **boot anında sıfırlanır**, iki-el-tehlikesi text-kaynağında-da-kapanır.

### I.4 OLAY-KAYDI — ikinci-boot audit-log'u **imha etti** (2026-09-03 19:17:10)
| Ölçüm | Değer |
|---|---|
| Önce | `18:51:08` (makine-damgası): `lines=10 · 3190 B · 0 SIGNAL/1 ERROR/3 WRITE_BLOCK` |
| Sonra | `19:18:41`: **`lines=6 · 1622 B · 0/0/0`**, içerik **yepyeni boot dizisi** |
| Eski-özne | ~~PID 3416 ÖLDÜ — nasıl-öldüğü kanıtlanamaz~~ **D76: Reis `taskkill /F /PID 3416` ile öldürdü (~19:13:23).** `/F` ⇒ SHUTDOWN olayı **beklenmez (doğru semantik, bug değil)** |
| Yeni-özne | **PID 11476**, `StartTime 19:17:10`, parent `16660` (.venv launcher) ⇒ **tek-boot, çift-instance DEĞİL** |
| Launch | `.venv/Scripts/python.exe -u -m src.live.run_production` — **`nohup.exe` DEĞİL** ⇒ **§C / exit-2 / close-save artık üretilebilir-olabilir** |
| Boot-log | `d66_boot_stdout.log` `14:07:56`'da donmuş ⇒ **bu bootu masa-hattı başlatmadı** |
| Safe-mode | `S11 SAFE_START` + `safe_reasons[0]="safe_mode_persisted"` ⇒ **§7.2 persisted-safe-mode → degraded boot ÇALIŞIYOR** ✓ |
| Kurtarma | ~~metin 10/10, artifact 0/10~~ **D76: KAYIP YOK.** AM-T7-8 icra edilmişti → `state/audit_prev_2026-09-03b.jsonl` **13 satır / 4376 B** @`19:11:23` = `MT5_CONNECT 1 · STARTUP 4 · SAFETY 1 · WRITE_BLOCK 5 · ERROR 2` ⇒ **3416-devri TAM korunmuş.** (Eski `audit_prev_2026-09-03.jsonl` 9 satır = **14:58'deki önceki** dikiş.) |
| Anlık-kopya | `results/D74_audit_snapshot_2026-09-03_1919.jsonl` — **1622 B, sha256 `184a95c450713eca20c6519e…`, kaynakla BAYT-ÖZDEŞ** |

**N2 #21 madde-1 KABUL-KRİTERİ YÜKSELTİLDİ:** ~~"yeni olay yokken `mtime` ilerlememeli"~~ ⇒ **"yeni boot sonrası ÖNCEKİ SATIRLAR SAYISI VE İÇERİĞİ KORUNMALI; `wc -l` düşerse kriter KIRMIZI."** mtime-churn yalnız *yazım-var* der; **satır-kaybı *tarih-imhası*dır.** Boot-öncesi-`AuditChain.load()` + append-only bu-kriteri-karşılamalıdır.
**Kanıt-kopyası kuralı (D74-öz-eleştiri):** kopya **`'rb'`/`'wb'` ile** alınır. Metin-kipi **CRLF→LF** çevirir (ölçüm: 1622 B → 1616 B, 6 bayt kayıp) ve **hash-karşılaştırmasını sessizce kırar.** Canlı `audit.jsonl`'a `cp`/`cat`/`sha256sum`/`stat` **vurulmaz** (O2); hash **Python-içi** hesaplanır.
**W2 izleme-öznesi değişti:** bundan-böyle **PID 11476**; **O4 sayım-tabanı sıfırdan** alınır, eski `0/1/3` mührü **yalnız-kurtarılan-9-satır-üzerinden** okunur.




---

## I.5 D76 · KÖK-NEDEN CANLI-YAKALANDI + ADLİ-ZEMİN-KAPISAMA-DELIĞI

**§I.4-başlığı-düzeltme:** ~~"ikinci-boot audit-log'u **imha etti**"~~ ⇒ **"ikinci-boot audit-log'unu GEÇİCİ-OVERWRITE etti; önceki-devir AM-T7-8 dikişiyle TAM korundu."** Başlık-yanlışı benim süreç-hatamın-ürünüdür (dikiş-dosyasını-aramadan-imha-ilan-ettim).

### I.5.1 KÖK-NEDEN · seviye-1 doğrudan-kanıt (kampanyanın-en-değerli-artefaktı)
`19:50` civarı boot **kendiliğinden-öldü** ve stdout'a-bu-yazdı:
```
[run_production] run() raised: [WinError 5] Access is denied:
  '...\state\audit.jsonl.11476.tmp' -> '...\state\audit.jsonl'
```
⇒ **`os.replace(tmp → target)` HEDEF-ÜZERİNDE-BAŞKA-BİR-HANDLE-NEDENİYLE engelleniyor.** Bu, `audit.py:106`'nün-kendi-etiketiyle-birebir-aynı: *"tmp→target rename blocked (**AV/sync handle*)"*. **D72(c) hipotezleri ÇÖZÜLDÜ: nohup-değil, venv-değil, çift-instance-değil — rename-handle.**
**~~DENEY: Defender-exclusion~~ ⇒ GERİ ALINDI, ZATEN ÇÜRÜTÜLMÜŞ.** `orchestrator._write()` docstring'i (**`~:890`**) bunu-bizim-önermeden-önce-kaydetmiş: *"N2 #15/#15-b history: PID-unique tmp + 8×~6.4s retry — **T0#6 still crashed with the same rename WinError 5 WITH the Defender exclusion active.**"* ⇒ **Defender-exclusion DENENDİ ve İŞE YARAMADI.** Reis'e bu-adımı-önermek **zaman- kaybıydı**; düzelttim.
**Gerçek-öncül-hipotez (Hakem, N2 #17) BU-GECE-bağımsız-keşfetimle-ÇAKIŞTI:** *"Leading hypothesis: a **dual-process writer (venv launcher + worker) contending on the lock** — rename-overwrite collides with the live target handle."* ⇒ Benim `16660`(venv)+`11476`(worker) bulgum **hakemin-hipotezini-bağımsız-doğruluyor.**
**KRİTİK ASİMETRİ:** **LOCK zaten ÇÖZÜLMÜŞ** — `_write()` *"N2 #17: IN-PLACE write, not tmp+rename … the rename-overwrite mechanism is removed from the hot path entirely."* **AUDIT ÇÖZÜLMEMİŞ** — `audit.py:241-255` hâlâ tmp+`os.replace`. ⇒ **Yakaladığımız krış, TANILANMIŞ-bir-kusurun-DÜZELTİLMEMİŞ-KARDEŞİDİR.** Aynı-defect-class bir-yazıcıda-giderilmiş, diğerinde-bırakılmış.
**FARKSIAL-TANI (§8.3) · `crash_log` `self`/`parent` ALANLARINDAN ÖLÇÜLDÜ:**
| Boot | `self` interpreter | `parent` | süreç | Sonuç |
|---|---|---|---|---|
| `3944` | **base** `Python312\python.exe` | `bash.exe` | **TEK** | WRITE_BLOCK, **HAYATTA** |
| `3416` | **base** `Python312\python.exe` | `nohup.exe` | **TEK** | 5 WRITE_BLOCK / 2 ERROR, **HAYATTA** (`taskkill /F`'e-kadar) |
| `11476` | **`.venv\Scripts\python.exe`** | **`.venv\Scripts\python.exe`** | **ÇİFT** | 4 WRITE_BLOCK (13 sn'de 3'ü) → **ÖLÜMCÜL WinError 5** |
⇒ **Çift-süreç-DURUMU BU-GECE-YENİ ve İLK-ÖLÜMCÜL-krışla-TAM-KORELE.** **Değişen-tek-değişken = `Activate.ps1` / venv-interpreter-seçimi.** Reis'in "foreground boot" çekirdek-hareketi **doğruydu** ama **farkında-olmadan-bu-değişkeni-soktu.**
**SIRADAKİ-DENEY (operatör-yalnız, KOD-DOKUNUŞU-YOK):** venv'i **aktive ETMEDEN** base-python ile foreground boot → `Get-CimInstance … -Filter "ParentProcessId=X"` ile **tek-PID-olduğu-doğrulanır** → WRITE_BLOCK patlaması kaybolursa **kök-neden seviye-1 MÜHÜRLER.** *(Not: base-python `pandas 2.3.3`/`numpy 2.2.6` taşır; venv `3.0.5`/`2.5.2`. Deney **provenance-değişimini de** beraberiinde-getirir — mühürlemeden-önce-kaydedilmeli.)*
**Handle-adayları (ölçüldü):** `MsMpEng` PID 10004 + `SearchIndexer` PID 5112 çalışıyor; **OneDrive ELENDİ** (`User Shell Folders\Desktop = C:\Users\Administrator\Desktop`). **Ancak Defender-exclusion zaten-denendiği-için birincil-şüpheli ARTIK çift-süreç-handle-çakışmasıdır.**

### I.5.2 P1-BULGU · gözlem-başarısızlığı erişilebilirlik-başarısızlığına-terfi-ediyor
`orchestrator.py:235` `_ATOMIC_WRITE_RUNTIME = False` (**FROZEN production posture, testlerle-pinned**) → rename-budget-tükenince **crash_log'a-yaz + RE-RAISE**. `run_production.py:174-177`: `except BaseException` → `print("run() raised")` → `orch.shutdown(exit_code=1, reason="run_exception:...")`.
⇒ **Audit-journal'ının rename'ının anlık-engellenmesi TÜM TRADING OTURUMUNU ÖLDÜRÜYOR.** Teşhis-kanalının-çökmesi, işlem-kanalının-çökmesine-bağlanmış. **§7 fail-safe semantiği-ihlali (kendi-kendine-uygulanan).** **exit-code = 1**, `:12`'deki "2 — safe-mode shutdown" **DEĞİL** ⇒ **§C'nin-beklediği-çıkış-kodu-üretilmedi.**
**N2 #21 madde-1'e-yeni-boyut:** sorun-yalnız-veri-kaybı-değil, **availability**. Kabul-kriteri: *"audit-rename-başarısızlığı oturumu-öldürmemeli."*

### I.5.3 P1-BULGU · adli-zemin (K2 floor) ÖLÜM-ANINDA-KAPALI
`state/crash_log.txt` **hâlâ yalnız 3 `writer_diagnostic` boot-kaydı** içeriyor — **19:50'lik ölümcül-crash KAYITLI DEĞİL.** `_crash_log_append` çağrıları `orchestrator.py:313/700/784/1593` — **hepsi orchestrator-içi.** `run_production.py:174` üst-seviye `BaseException` yakalayıcısı **crash_log'a YAZMIYOR, sadece stderr'e basıyor.**
⇒ **Kampanyanın-tek-ölümcül-crash'i crash_log'da SIFIR iz bıraktı.** Tek-nedenle-kurtardık: **Reis'in KAZARA-eklediği `Tee-Object`.** O-olsaydı-yoktu → **audit-yazan-mekanizma-bizzat-bozuk-olduğu-için hata-metni HİÇBİR-YERDE kalmayacaktı.**
⇒ **Bu, "iki-bağımsız-başarısızlığın-bileşimi = tam-kanıt-kara-deliliği"** vakasıdır ve **K2 tasarımının-kendi-docstring'indeki-iddiayı ("flush-independent forensic floor") karşılamadığını-gösterir.** **N2 #21 madde-adayı:** `run_production.py:174` dalına `_crash_log_append({"kind":"run_exception", …})` bağlanır (**mevcut-fonksiyon, yeni-soyutlama-yok**).

### I.5.4 OLUMLU · §7 runtime-safety İKİ-seviye-1-kanıt
1. **Anormal-çıkışta-lock-unlink ÇALIŞIYOR:** crash-sonrası `state/orchestrator.lock` **YOK**. `shutdown(exit_code=1)` gerçekten-koştu ⇒ **kilit-sahipliği-temiz-bırakılıyor, stale-lock-terk-etmiyor.** ✓
2. **Stale-lock TAKEOVER PID-yaşamına-dayanıyor, zaman-aşımına-değil:** 3416 `19:13:23`'te `taskkill /F` ile öldü, **lock stale-kaldı** (Reis `{"pid":3416,...}` okudu); 11476 `19:17:10`'da **devraldı.** Sapma = **227 s ≪ `LOCK_STALE_SEC` 900 s** ⇒ **tetikleyen-mekanizma ZAMAN-AŞIMI DEĞİL, PID-liveness.** **§7.1 "kill vs ownership ayrımı" CANLI-doğrulandı + KOD-TEYİDİ ALINDI:** `_is_stale` (`orchestrator.py:982-987`) → `if not _pid_alive(data.pid): return True` → **`_pid_alive` ÖNCE-kontrol ve kısa-devre**; `LOCK_STALE_SEC = 60*15 = 900 s` (`:444`); `_pid_alive` Windows'ta **`OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`** (`:329`/`:351`). ⇒ **227 s'lik devralma ZAMAN-AŞIMI ile AÇIKLANAMAZ; tek-açıklama PID-liveness.** **seviye-1 (canlı-gözlem) + seviye-2 (kod) = MÜHÜRLÜ.** Docstring kendi-iddiası: *"Two failure modes: process crashed (dead PID) or process wedged quietly past the staleness window."*
3. **Failed-rename tmp'si TOPLANMIŞ:** `state/*.tmp` yalnız Sep-1 yetimleri (`audit.jsonl.tmp` 1483 B, `orchestrator.lock.tmp` 68 B). `audit.jsonl.11476.tmp` **yok** ⇒ `finally`-temizliği çalışıyor; **ama kurtarılabilir-başka-event-de-yok.**

### I.5.5 ARAÇ-BULGUSU · `Tee-Object -FilePath` **UTF-16 LE** yazar
`state/k3_boot_stdout.log` **2388 B / mtime 19:50** ⇒ **Tee TAMPONLAMIYOR** (19:17:25→19:50 arası program gerçekten sessiz; gate kapalı). **AMA dosya UTF-16LE**: her-karakter-ardında `\u0000`. PS 5.1 `Tee-Object -FilePath` varsayılanı **Unicode**. ⇒ **Kanıt-setindeki-diğer-tüm-dosyalarla-uyumsuz-encoding**; 1944 B ölçümüm **UTF-16 baytıydı** (~972 karakter). **CRLF-bulgusunun-kardeşi: encoding-drift.**
**Kural-adayı:** *stdout-kanıtı ya `cmd /c "... > log 2>&1"` (bayt- sadık, UTF-8/ASCII) ya da `Tee-Object` + `Out-File -Encoding utf8`. Kanıt-dosyası-kopyalanırken **encoding ve BAYT-SAYISI-birlikte-kaydedilir**.*

### I.5.6 D77-DÜZELTMESİ · Reis'in Ctrl-C'si **planda-yazılı-olan-adımdı** ve **K3-kapısını AÇTI**

**~~Elde-edilen: graceful-stop DEĞİL, exception-death · §C/close-save/65k-parite BLOKE~~ ⇒ YANLIŞ.** Ben aynı-cevapta "graceful-stop olmadı" yazmışım; **olmuş.** Ölçülen:

| K3-§C hedefi | Durum | Kanıt |
|---|---|---|
| **close-save (D48)** | ✅ **GERÇEKLEŞTİ** | `state/EURUSD.json` mtime **`19:50:55`** (895374 B) + `EURUSD_lifecycle.json` mtime **`19:50:55`** (137 B) |
| **canlı `session_atr`** | ✅ **MEVCUT** | `session_atr = 0.0004935714285714741` · `atr_val = 0.0006803779882671913` |
| **SHUTDOWN audit olayı** | ✅ **YAZILDI** | satır-11 `{"exit": 1, "reason": "run_exception:PermissionError"}` @`19:50:48.726` |
| **lock unlink** | ✅ **GERÇEKLEŞTİ** | `state/orchestrator.lock` **YOK** |
| **lifecycle temiz** | ✅ **TUTARLI** | `open_trades [] · realized_journal [] · quarantined_exits [] · dd_reliable false` ⇒ SAFE_START/gate-CLOSED ile uyumlu, **sıfır-işlem** |
| **exit-code 2** | ❌ **ÜRETİLEMEDİ** | `exit 1` · `:12`'deki "2 — safe-mode shutdown" yerine `run_exception` dalı |

⇒ **`progress.md:1025`'in-K3-kapısını-tutan-tek-şartı—"canlı `session_atr` yalnız close-save'te"—ARTIK KARŞILANDI.** ⇒ **65k-parite-çekimi BLOKE-DEĞİL.** `:1136` masa-akışı **tek-adresi** veriyordu: *"Reis → W2-sonrası foreground-boot **+ Ctrl-C**."* ⇒ **Reis'in "kazara" dediği şey, planın-emrettiği-adımdır.**

**Ctrl-C'nin-ölüme-katkısı: AÇIK, mühürlenemedi.** Ayırt-edici-kanıt **olumsuz**: stdout'ta `":155` dalının-baskısı *"KeyboardInterrupt - graceful stop"* **YOK** (ölçüldü: `False`), `exit code` satırı-da-yok (`:179 return 1`, `:182`'yi-atlar). İki-okuma-da-ayakta:
- **(a) Ctrl-C hiç-ulaşmadı** — Windows konsol **QuickEdit** modunda seçim-varken Ctrl-C **panoya-kopyalar ve SIGINT göndermez**; süreç kendi-headine `19:50:48`'de öldü.
- **(b) Ctrl-C `run()` içindeki SIGINT→`kill_fn` yönlendiricisine-ulaştı** (`:153-154` yorumu bunu-söylüyor: *":155 yalnız bu-pencereler-DIŞINDAKİ KI için"*) ⇒ graceful-teardown başladı → close-save ✓ → **son-audit-flush'ta WinError 5** → `run()`'dan-kaçtı → `:174`.
⇒ **Ayrımı-yapacak-kanıt: `kill_fn` yolunun-kendi-SHUTDOWN-olayını-yazıp-yazmadığı.** Satır-12 WRITE_BLOCK, SHUTDOWN'dan **18 ms sonra** ⇒ **kill_fn-path-shutdown'ın-audit-yazımı-başarısız-olmuş-olabilir**; bu-(b)'yi-güçlendirir ama **kanıtlamaz.** **SINIF-1 olarak mühürlenmez.**

**EN-ACIMASIZ-ÇIKARIM (P1-1'in-keskin-hali):** Audit-defect'i, **K3'ün-tam-olarak-ölçmek-için-var-olduğu-tek-çıktıyı-bozdu: exit-code.** Close-save/SHUTDOWN/lock-hepsi-doğru-çalıştı; **audit-flush'ın-çökmesi exit-2'yi-exit-1'e-düşürdü.** Yani **kusur-kenar-notu-değil, hedefin-kendisine-değdi.**
**Ve `ERROR` olayının-kendi-etiketi:** `payload.phase = "audit_flush"` ⇒ **kod-başarısızlığı-kendi-elle-tamlıyor; yorum-yok.**
