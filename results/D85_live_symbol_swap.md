# D85 — CANLI PARİTE DEĞİŞİMİ: AUDUSD = SWEEP'LI-ÜÇLÜDEN İLK CANLI SEMBOL

**Statü:** EXECUTED · 2026-09-04 (Boot-C başlangıcı 08:13 UTC civarı)
**Yetki:** Hakem hükmü *D85-CANLI-PARİTE-DEĞİŞİMİ* (SCAN-RATİFİYE; RED-YOK)
**Tek-değişken disiplini:** `SNIPER_SYMBOLS=AUDUSD` env-override — `.env` DOKUNULMAZ, `SNIPER_STATE_DIR` bilinçli unset (Boot-B ile aynı), modül-kipi `python -u -m src.live.run_production` invariant.

## 1. SINIF-1 ↔ SINIF-2 SEMANTİK BİAS MATCH — İLK DEFA UYUM MÜHÜRLÜ ✅

| Kanal | Kaynak | Sonuç |
|---|---|---|
| **SINIF-1 (tahmin)** | `state/cbdr_scan/cbdr_scan_20260904_075501.json` — 6-major sweep scan (canlı-motor-import, sıfır-yeni-formül) | **AUDUSD: SWEEP BEARISH, bias_locked=True, onay 06:30 UTC** (ilk-onaylı-üçlüden; GBPUSD 07:45, USDCAD 07:15) |
| **SINIF-2 (canlı gözlem)** | `state/audit.jsonl` satır-21 — Boot-C S9 REPLAY payload | **`"bias": "bearish"`, end_state="flat", session_key="2026-09-04", replay_bars=4236, next_idx=4337, signals_discarded=27** |

**Pre-reg pin SONUCU:** Beklenen-yön **BEARISH** gerçekleşti; NEUTRAL-parite-bulgusu yolu **devreye-girmedi**. Scan (SINIF-1) → replay (SINIF-2) → canlı-bias zinciri **ilk defa semantik-uyumla kapandı** — R7/V-2 mirası canlıda.

**EURUSD-NEUTRAL-uyumu (önceden-girilmiş mühür):** Boot-B audit-15 `bias:"neutral"` ↔ scan EURUSD=NEUTRAL (ATR×0.5-aşan-kapanış-yok) — çelişki yok; **SINIF-2 ilk-yumuşak-uyum** T0#10'da-kayda-girmişti, D85 bunu 2. sembolle (AUDUSD) **çift-nokta** haline getirdi (D79-EURUSD → D85-AUDUSD sembol-duyarlılık ölçümü).

## 2. EXECUTE-ZİNCİRİ — ADIM-ADIM KANIT

| Adım | İşlem | Sonuç | Kanıt |
|---|---|---|---|
| 0 | **Coruma** (mutasyon-öncesi): 10-artefakt → `state/D85_preserve/` + `SHA256SUMS.txt` | tamam | audit-mührü: 18-satır/5253B, sha256 `5d56f03a835e8c9f…` |
| 1a | **Graceful-stop denemesi** (Hakem tercihi): AttachConsole+CTRL_C yardımcısı (`state/d85_graceful_stop_helper.py`) PID 16880 | **ATTACH_FAIL err=5** (konsol-erişilemez — detached-launch) | helper stdout; SHUTDOWN-yolu-bu-sekmeden-uzlaşılabilir-değildi |
| 1b | **taskkill /F /T /PID 16880** (Hakem-ruhsatlı κ-fallback, ADER-19) | **2×SUCCESS** (16880 + child-18716); launcher-1288 child-ölümü-üzerine kendiliğinden-çıktı (exit-zinciri); **audit 18/5253B bayt-özdeş DONDU, SHUTDOWN-YOK**; lock-stale-16880-dondu | kill-zinciri-çıktısı; D78-exit-degradasyon-üçüncü-örnek |
| 2 | **BOOT-C**: Start-Process env-override (venv-launcher 5580 → runtime **PID-18460**), Reis-bildirim-artefaktı `state/t10c_reis_notice.txt` | lansman tamam (tool-30s-cezası ×1 — lansman-aşağıda-kanıtla-hayatta) | `t10c_boot_stdout.log`, `t10c_boot_stderr.log` |
| 3 | **Gözlem** | aşağıda | audit 19-23; lock-heartbeat |

## 3. BOOT-C STARTUP GÖZLEMİ (audit.jsonl 18→23 append; dikiş-kanıtı)

| Audit-satırı | Olay | Değerlendirme |
|---|---|---|
| 19 | MT5_CONNECT | symbol=**AUDUSD** (env-override-etkisi-imzalı); server=ICMarketsSC-Demo; equity 9990.68 |
| 20 | STARTUP-account | `symbols: ["AUDUSD"]` — konfigürasyon-yayılımı ✓ |
| 21 | **S9 REPLAY** | **bias=bearish** (PIN ✓); replay_bars=4236; next_idx=4337; session_key=2026-09-04; signals_discarded=27 |
| 22 | S11 SAFE_START | **restored=false** → COLD imzası (AUDUSD-state-yok — beklenen); safe_reasons kirli-zincir **n=7** |
| 23 | SAFETY | gate=**closed** (startup_SAFE_START); failing_check=null |

**Append-dikişi (bayt-kanıtı):** post-Boot-C `head -c 5253` sha256 = **`5d56f03a…` bayt-özdeş** — 4-boot linyajı (T0#9+A+B+C) tek-dosyada, truncation-yok (d36856f-mekanizması-3.boot'ta-canlı).

## 4. BEKLENTİ-TABLOSU (Hakem §2-pin + §3-kanıt-planı)

1. **COLD_REBUILD beklenen** → ✓ (`restored:false` + S9-replay-4236-bar-tam-geçmiş; AM-T7-2-deseni). *Topoloji-notu (beyanlı):* Boot-B'nin-ayrı `COLD_REBUILD_OK` STARTUP-olayı ve stderr-"cold rebuild OK"-alerti Boot-C'de-yok; yetkili-soğuk-imzalar S11 `restored:false` + S9-REPLAY-payload — gizlenmez, §4.4-ruhuyla-kayda.
2. **Pre-reg pin: replay-sonu bias=BEARISH beklenir; NEUTRAL=parite-bulgusu** → **BEARISH** ✓ (parite-yolu-açılmadı).
3. **BULGU-13 çapraz-sembol n-büyümesi** → ✓ Boot-B n=6 → **Boot-C n=7** (+1/boot-topolojisi; madde-7-girdisi).
4. **gate-CLOSED-sabit (SAFE_START)** → ✓ audit-23 + stderr-SNIPER_ALERT.
5. **WB=0 (append-yolu)** → ✓ audit-23-stabil-gözlem-penceresi-boyunca.
6. **Lock-takeover-3** → ✓ stale-16880 → 18460 (14940→9072→16880→18460 dördüncü-kurousu).
7. **SINIF-2-semantic-bias-match** → ✓ **İLK-DEFA** (§1-tablosu).
8. **D64-FAZ-B ilk-canlı-ham-besin** → ✓ tek-sembol-tek-süreç-provası: EURUSD→AUDUSD 1×-yön-değişimi (6×-ölçek-öncesi).

## 5. Kanıt-planın-ölçtüğü-üç-şey (Hakem §3)

1. **Çok-sembol-topolojisi-provası:** ✓ tek-env-değişkeniyle-farklı-sembolde-tam-startup-zinciri.
2. **SINIF-1→2-yumuşak-uyum-zinciri:** ✓ scan→replay→canlı-bias İLK-sefer-uyum; EURUSD-NEUTRAL-öncül-uyumla-2.uyum-noktası.
3. **BULGU-13 çapraz-sembol:** ✓ n=6→7 izleri; üçlü-kanal-bildirim-disiplini AGENTS.md-Aşama-5 ile-deftere.

## 6. Sapma / açık-kalem kayıtları (beyanlı, §4.4)

- Graceful-stop **denendi-başarısız** (ATTACH_FAIL err=5) — κ-taskkill-fallback Hakem-önceden-ruhsatlı; SHUTDOWN-audit-olayı canlıda-hâlâ-görülmedi (T0#10-açık-kalemi-aynen-devam).
- Boot-C'de-ayrı-COLD_REBUILD_OK-olayı/stderr-alerti-yok (yetkili-imzalar S9/S11) — araştırma-kalemi.
- Lansman-tool-timeout-1 (30s-cezası) — proses-CimInstance-zinciriyle-kanıt-hayatta (18460/5580).
- **Boot-C (PID-18460) handoff-anında-canlı-bırakıldı** (Hakem-zinciri-akıbet-emri-içermez); Reis-bildirimi: `state/t10c_reis_notice.txt`.

## 7. Koruma-envanteri

`state/D85_preserve/`: audit.jsonl, orchestrator.lock, orchestrator_safe.json, EURUSD.json, EURUSD_lifecycle.json, t10_boot_stdout.log, t10b_boot_stdout.log, t10b_boot_stderr.log, crash_log.txt, cbdr_scan_run.txt, cbdr_scan/*.json + `SHA256SUMS.txt` (audit `5d56f03a…`, scan-json `75ab4479…`).
