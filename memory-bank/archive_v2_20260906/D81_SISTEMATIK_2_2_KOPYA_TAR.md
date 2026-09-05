## D81 — SISTEMATIK §2.2 KOPYA-TARAMASI (D80-c'nin geneli; salt-okuma, 21:35–21:45)

**Soru:** D80-c bir kopya-ıraklaması buldu — **tek olan o mu?** Cevap: **EVET, tek.** Ama bulmak için tüm `src/` tarandı ve **metodum bir-kez-yanlış çıktı.**

### 81.0 · METOT-ÖZ-DÜZELTMESİ (§11 hiyerarşisi uygulandı)

Ham-gövde-hash **docstring'i de saydı** → 10-grubun **8'ini IRAKAK bildirdi.** `ast` + docstring-strip + `annotate_fields=False` ile yeniden-koştu: **6 IRAKAK / 4 BIREBIR.** **İki-yalancı-pozitif düştü: `_compute_atr`, `LiquiditySource`.** ⇒ **§11'in-dedigi-doğru: prose-claim < test-run < AST/semantic-comparison; ve benim-ilk-taramam-dördüncü-kategorideydi (ham-metin).** Kayıttan-düşülür, silinmez.

### 81.1 · Grup-grup-hüküm

| kopya-adı | yerler | AST | HÜKÜM |
|---|---|---|---|
| **`_atomic_write_text`** | `orchestrator:259` · `audit:44` · `state:32` | **IRAKAK (2-biçim)** | 🔴 **CANLI-YOL · KANITLI-ÖLÜMCÜL — D80-c. TEK-gerçek-kusur.** |
| `_to_nexus_bar` | `breakout_variant` · `strategy_runtime` | IRAKAK | **MASUM:** gövdeler-birebir, fark-yalnız import-yeri (modül-seviye vs fonksiyon-içi) + tip-notu (`NexusBar` vs `Any`). **`timestamp=int(bar.timestamp.timestamp()*1000)` IKI-YOLDA-AYNİ ⇒ §6.3 sapmasi YOK.** |
| `Bar` | `backtest/replay_engine` · `strategy/models` | IRAKAK | **YAPISAL-AMA-KANLIŞ-DEĞİL:** `src/live/**` **7-modül-birebir `src.strategy.models.Bar`** kullanıyor; yalnız `src/backtest/**` kendi `Bar`'ını. **Canlı-yol TEK-KAYNAK ✓.** D66-harness `models.Bar` import eder ⇒ **parity-bozulmadı.** |
| `detect_swing_hl_levels` | `liquidity_forensics:506` · `phase4_lifecycle` | IRAKAK (72 vs 20 satır) | **KOPYA-DEĞİL, AYNI-İSİM-FARKLI-FONKSİYON:** forensics = N-bar **pivot (önce+sonra onaylı)** → `List[LiquidityLevel]`; phase4 = **kayan-pencere max** (pivot değil) → `List[Dict]`, kendi-docstring'inde *"NEWLY DEFINED FOR THIS ANALYSIS — not in baseline strategy"*. **⇒ ÖLÜ-KOD (aşağıda 81.2). D79-bulgularini ETKILEMEZ.** |
| `detect_session_hl_levels` | aynı-ikili | IRAKAK (68 vs 45) | aynı-hüküm: forensics = gün-bazlı-HL `max_active_days=3`; phase4 = `window=50` kayan. **ÖLÜ-KOD.** |
| `load_env_from_project_root` | `backtest/mt5_downloader` · `src/test_mt5_data.py` | IRAKAK | **Canlı-yol-DIŞI** (`src/live/**` hiçbirisini import etmez). Düşük-öncelik. |
| `_compute_atr` | `breakout_variant` · `strategy_runtime` | **BIREBİR** | ✅ **ATR-PARİTESİ TEMİZ — kritik-temizleme:** ATR, D79'da AUDUSD bias'ını çeviren toleransın girdisi; **iki-yol-da aynı-hesap (simple mean, Wilder DEĞİL).** |
| `_utcnow_naive` | `candle_feed` · `clock` | **BIREBİR** | ✅ davranış-sapması YOK; **ama §6.3 tek-konvansiyon-ilkesi-adına-iki-tanım-hâlâ-borç** (birleştirme-kazancı-düşük, risk-yok). |
| `LiquiditySource` | forensics · phase4 | **BIREBİR** | ölü-kod-içi-ikiz, etkisiz. |
| `calculate_file_hash` | `data_validator` · `manifest_generator` | **BIREBİR** | zararsız-teknik-borç. |
| `main` ×11 | 11-ayrı-script | — | **İPTAL (meşru):** her-CLI-script'in-kendi-`main`'i; kopya-değil. |

### 81.2 · 🔴 ÖLÜ-KOD-BULGUSU (yeni, düşük-öncelikli-ama-isim-kirliliği)

`grep -rln 'liquidity_forensics\|phase4_lifecycle' src tests experiment` → **`phase4_lifecycle.py`'ın-KENDİSİ-dışında SIFIR-SONUÇ.** **İki-modül-de repo'da HİÇBİR-yerden import edilmiyor** (canlı-yol, testler, `experiment/` dahil). ⇒ **`src/strategy/` içinde, kanonik-isimlerle, ölü ve birbiriyle-çelişen iki analiz-modülü duruyor.** **§2.3 ihlali (analiz-kodu üretim-`src/`'inde, `experiment/`'te-değil) + §19 isim-kirliliği.** **Eylem-yetkisi İSTENMİYOR** — yalnız-kayıt: **N2 #21 madde-9 ADAYI** (ölü-analiz-modüllerinin `experiment/`'e-taşıması veya `src/`'den-düşülmesi).

### 81.3 · `_atomic_write_text` üç-kopya — MINIMAL-ve-KANITLI-fark

`audit.py` ≡ `state.py` **AST-birebir (True)**. `orchestrator.py` ≠ ikisi. Fark-yaratıcı-anahtarlar:

```
_crash_log_append        orch=1 / audit=0 / state=0
atomic_write_exhausted   orch=1 / audit=0 / state=0
_ATOMIC_WRITE_RUNTIME    orch=1 / audit=0 / state=0
on_block                 orch=1 / audit=1 / state=1     ← ortak
unlink                   orch=1 / audit=1 / state=1     ← ortak
```

**⇒ Üç-kopyanın-birbirinden-farkı TAM VE YALNIZ K2-forensic-floor'u.** Retry-döngüsü, `on_block`-tek-atımı, tmp-temizliği, raise-yolu — **hepsi-birebir.** **Bu, D80-c'yi tahmin-olmaktan-çıkarıp kapalı-bir-cebir-savına-dönüştürüyor.**

### 81.4 · DEĞERLİ-NEGATİF-SONUÇ: madde-8'in-kapsamı BİR-MODÜL

Tarama **ikinci-bir-canlı-yol-ıraklaması BULAMADI.** ⇒ **N2 #21 madde-8 bir-kampanya-değil, tek-modül-işi:** circular-import'suz `src/live/atomic_write.py` + üç-cismin-onu-import-etmesi. **D80-c'nin-çözüm-tasarımı küçüldü ve kesleşti.**

### 81.5 · Yan-not: `sys.path.insert(0, _NEXUS_SNIPER_SRC)` ÜÇ-canlı-modülde

`breakout_variant:52-53` · `recovery:37-38` · `strategy_runtime:55-56`. **Bu, `breakout_variant`'taki çıplak `from models import Bar`'ın-çalışma-mekanizması** (kazara-değil, kasıtlı). **Ama:** üç-yerden-process-global-durum-mutasyonu + **pozisyon-0 ⇒ nexus `models.py` başka-her-`models`-modülünü-gölgeleyebilir.** **§19 "CWD/environment-bağımlı" sınıfına-giren mevcut-risk; SAPMA-değil (üçü-de-aynı-desen).** Yalnız-kayıt, eylem-yok.

### 81.6 · Boundary

**SALT-OKUMA.** `git diff -- src/ tests/ index.json` **BOŞ** · HEAD `0081c64` · commit/push YOK · dosya-açılmadı-değiştirilmedi (AST-parse bellek-içi) · `.env` DOKUNULMADI · `index.json` ÜRETİLMEDİ · **T0#8 ÖLÜ, yeniden-boot YETKİSİ İSTENMİYOR/VERİLMEDİ** · tek-yazım: `progress.md` + `D66_observer_touchlog.txt`.
