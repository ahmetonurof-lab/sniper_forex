# SNIPER_FOREX — RUNTIME HARDENING + REPOSITORY CLEANUP RAPORU

## 1. Repository Cleanup Inventory

### Klasifikasyon Özeti

| Kategori | Dosya Sayısı | Toplam |
|----------|--------------|--------|
| PRODUCTION | 0 | Runtime'da kullanılmıyor ama gelecekte kullanılabilir |
| RESEARCH ARTIFACT | 0 | Araştırma kanıtı |
| DOCUMENTATION | 8 | Dokümantasyon |
| ACTIVE TEST | 0 | Test dosyaları |
| HISTORICAL FORENSIC | 22 | Geçmiş analiz artifact'leri |
| TEMPORARY DIAGNOSTIC | 16 | Geçici tanı dosyaları |
| OBSOLETE / SAFE TO REMOVE | 12 | Güvenle silinebilir |
| UNKNOWN | 0 | Bilinmeyen |

### Detaylı Klasifikasyon

#### OBSOLETE / SAFE TO REMOVE (Güvenle Silinebilir)

| Dosya | Üretici | Kod Referansı | Git'te | Runtime'da | Tarihsel Değer | Güvenle Silinebilir |
|-------|---------|---------------|--------|------------|----------------|---------------------|
| `logs/p1_fix_infra.txt` | P1 debug | Yok | Hayır | Hayır | Düşük | EVET |
| `logs/p1_fix_infra2.txt` | P1 debug | Yok | Hayır | Hayır | Düşük | EVET |
| `logs/p1_fix_src.txt` | P1 debug | Yok | Hayır | Hayır | Düşük | EVET |
| `logs/p1_flow.txt` | P1 debug | Yok | Hayır | Hayır | Düşük | EVET |
| `logs/p1_flow2.txt` | P1 debug | Yok | Hayır | Hayır | Düşük | EVET |
| `logs/p1_inventory.txt` | P1 debug | Yok | Hayır | Hayır | Düşük | EVET |
| `logs/p1_risk.txt` | P1 debug | Yok | Hayır | Hayır | Düşük | EVET |
| `logs/rollback_stageA.txt` | Rollback | Yok | Hayır | Hayır | Orta | EVET (işlem tamamlanmış) |
| `logs/rollback_stageB.txt` | Rollback | Yok | Hayır | Hayır | Orta | EVET (işlem tamamlanmış) |
| `nul` | Bozuk dosya | Yok | Hayır | Hayır | Yok | EVET |
| `phase5_demo.py` | Phase 5 test | Yok | Hayır | Hayır | Düşük | EVET (güncelliğini yitirmiş) |
| `docs/MaxDD_dusurme _teorileri.md` | Araştırma notu | Yok | Hayır | Hayır | Düşük | EVET |

#### HISTORICAL FORENSIC (Saklanmalı)

| Dosya | Neden Saklanmalı |
|-------|------------------|
| `logs/audit_counts.txt` | Geçmiş audit istatistikleri |
| `logs/audit_daily.txt` | Günlük audit özeti |
| `logs/audit_errors.txt` | Geçmiş hata logları |
| `logs/audit_events_3d.txt` | 3 günlük event geçmişi |
| `logs/audit_integrity.txt` | Bütünlük kontrol geçmişi |
| `logs/audit_paper_3d.txt` | Paper trade geçmişi |
| `logs/audit_paper_patterns.txt` | Pattern analizi |
| `logs/audit_proc.txt` | Process debug çıktısı |
| `logs/audit_proc_clean.txt` | Temiz process debug |
| `logs/audit_resources.txt` | Resource monitoring |
| `logs/audit_retry.txt` | Retry logları |
| `logs/audit_security.txt` | Güvenlik audit |
| `logs/audit_state.txt` | State debug |
| `logs/audit_stdout_clock.txt` | Clock drift analizi |
| `logs/audit_stdout_clock_clean.txt` | Temiz clock analizi |
| `logs/audit_ts.txt` | Timestamp analizi |

#### TEMPORARY DIAGNOSTIC (İnceleme Gerektirir)

| Dosya | Durum |
|-------|-------|
| `logs/bot_binance_local.py` | Crypto referans kopyası - silinebilir |
| `logs/bot_infra_local.py` | Crypto referans kopyası - silinebilir |
| `logs/config_local.py` | Crypto referans kopyası - silinebilir |
| `logs/risk_manager_local.py` | Crypto referans kopyası - silinebilir |
| `logs/test_risk_manager_local.py` | Crypto referans kopyası - silinebilir |
| `logs/fix/` | Fix script'leri - araştırma için sakla |

#### DOCUMENTATION (Saklanmalı)

| Dosya | Açıklama |
|-------|----------|
| `docs/FOREX_DEPLOYMENT_CONTRACT_v1.md` | Deployment sözleşmesi |
| `docs/FOREX_OBSERVABILITY_ACTION_PLAN.md` | Observability planı |
| `docs/WINDOWS_DEPLOYMENT_PLAN.md` | Windows deployment planı |
| `docs/POC_INSTRUCTIONS.md` | POC talimatları |
| `docs/POC_VALIDATION_CHECKLIST.md` | POC kontrol listesi |
| `docs/PING_RECEIVER_NATIVE.mq5` | MQL5 POC kodu |
| `docs/ping_server_native.py` | Python POC kodu |
| `docs/setup_poc.bat` | POC kurulum script'i |

#### RESEARCH ARTIFACT (Saklanmalı - Silinemez)

| Klasör | İçerik |
|--------|--------|
| `experiment/` | Aktif deney dosyaları |
| `results/` | Benchmark ve araştırma sonuçları |
| `memory-bank/` | Proje hafıza bankası |
| `tests/` | Test dosyaları |

---

## 2. Files Actually Removed

**Henüz dosya silinmedi.** Önce kullanıcı onayı bekleniyor.

Önerilen silme listesi:
```
logs/p1_fix_infra.txt
logs/p1_fix_infra2.txt
logs/p1_fix_src.txt
logs/p1_flow.txt
logs/p1_flow2.txt
logs/p1_inventory.txt
logs/p1_risk.txt
logs/rollback_stageA.txt
logs/rollback_stageB.txt
nul
phase5_demo.py
docs/MaxDD_dusurme _teorileri.md
```

---

## 3. Files Deliberately Preserved

| Dosya | Neden Saklanıyor |
|-------|------------------|
| `logs/audit_*.txt` | Geçmiş audit kanıtı |
| `logs/bot_*_local.py` | Crypto referans implementasyonu |
| `logs/config_local.py` | Crypto config referansı |
| `logs/fix/` | Fix script'leri - gelecekte kullanılabilir |
| `docs/PING_RECEIVER_NATIVE.mq5` | MQL5 POC referans kodu |
| `docs/ping_server_native.py` | Python POC referans kodu |
| `experiment/*.py` | Aktif araştırma deneyleri |
| `results/**/*.json` | Benchmark ve araştırma sonuçları |
| `memory-bank/*.md` | Proje durum hafızası |
| `tests/*.py` | Test dosyaları |

---

## 4. Production Dependencies Protected

| Bağımlılık | Koruma Nedeni |
|------------|---------------|
| `src/live/*.py` | Runtime modülleri |
| `src/strategy/*.py` | Strateji motoru |
| `src/data/*.py` | Veri katmanı |
| `experiment/config.py` | Deney konfigürasyonu |
| `experiment/trailing_adapter.py` | Trailing implementasyonu |
| `tools/code-index-system/` | Kod indeks sistemi |
| `scripts/*.py` | Veri işleme script'leri |
| `tests/*.py` | Test dosyaları |

---

## 5. Startup Broker-State Capability

### Mevcut Durum

| Kontrol | Mevcut? | Dosya | Açıklama |
|---------|---------|-------|----------|
| MT5 bağlantısı | ✅ | `live_runner.py` | `mt5.initialize()` |
| Açık pozisyonlar | ✅ | `position_manager.py` | `update()` ile MT5'ten oku |
| Pending orders | ❌ | - | Henüz implemente edilmedi |
| Mevcut SL | ✅ | `position_manager.py` | Position nesnesinde |
| Mevcut TP | ✅ | `position_manager.py` | Position nesnesinde |
| Local state | ✅ | `state.py` | `StateStore` ile |
| Broker/local reconciliation | ✅ | `reconciliation.py` | `Reconciler.reconcile()` |
| Restart recovery | ✅ | `recovery.py` | `RuntimeRecovery.load()` |

### Eksiklikler

| Eksiklik | Etki | Öncelik |
|----------|------|---------|
| Pending order kontrolü | Yeni emir öncesi mevcut emirler kontrol edilmiyor | MEDIUM |
| Startup'ta otomatik reconciliation | Restart sonrası otomatik reconcile yok | HIGH |
| Mevcut pozisyon varsa yeni engelleme | Bot pozisyon varsa yeni emir açabilir | HIGH |

---

## 6. Missing-Protection Detection/Repair Capability

### Mevcut Durum

| Kontrol | Mevcut? | Açıklama |
|---------|---------|----------|
| Pozisyon var + SL var | ✅ | `position_manager.py` SL alanı |
| Pozisyon var + TP var | ✅ | `position_manager.py` TP alanı |
| Pozisyon var + SL yok | ❌ | Henüz kontrol yok |
| Pozisyon var + TP yok | ❌ | Henüz kontrol yok |
| Duplicate protection | ✅ | `execution.py` fingerprint-based |
| Invalid protection | ❌ | Henüz kontrol yok |

### Eksiklikler

| Eksiklik | Etki | Öncelik |
|----------|------|---------|
| SL/TP eksikliği tespiti | Koruma olmayan pozisyon tespit edilemiyor | HIGH |
| Otomatik repair | Eksik SL/TP otomatik eklenmiyor | MEDIUM |
| SAFE MODE | Mismatch durumunda otomatik güvenli mod yok | HIGH |

---

## 7. Periodic Position-Health Capability

### Mevcut Durum

| Kontrol | Mevcut? | Açıklama |
|---------|---------|----------|
| Periyodik kontrol | ❌ | Henüz implemente edilmedi |
| ~60s snapshot | ❌ | Yok |
| Local state comparison | ✅ | `reconciliation.py` mevcut |
| Protection verification | ❌ | Yok |
| Mismatch/recovery event | ✅ | `AuditChain` ile loglanabilir |

### Eksiklik

| Eksiklik | Etli | Öncelik |
|----------|------|---------|
| Periyodik health check döngüsü | Pozisyon sağlığı düzenli kontrol edilmiyor | HIGH |
| Watchkit mekanizması | Takılı kalmış pozisyon tespiti yok | MEDIUM |

---

## 8. Existing TradeLifecycle Completeness

### Mevcut Bilgi

| Alan | Mevcut? | Kaynak |
|------|---------|--------|
| symbol | ✅ | `OpenTradeContext.symbol` |
| direction | ✅ | `OpenTradeContext.side` |
| entry | ✅ | `OpenTradeContext.entry_price` |
| SL | ✅ | `OpenTradeContext.initial_sl` |
| TP | ✅ | Signal'dan türetiliyor |
| lot | ✅ | `OpenTradeContext.filled_volume` |
| risk | ✅ | `OpenTradeContext.initial_risk_cash_total` |
| lot_multiplier | ✅ | `OpenTradeContext.lot_multiplier` |
| entry_deal_id | ✅ | `OpenTradeContext.entry_deal_id` |
| position_id | ✅ | `OpenTradeContext.position_id` |
| order_id | ✅ | `OpenTradeContext.order_id` |

### Eksik Bilgi

| Alan | Eksik? | Eklenmesi Gereken |
|------|--------|------------------|
| CBDR cycle | ❌ | `StrategyRuntime.session.cbdr_day_key` |
| CBDR body | ❌ | `StrategyRuntime.session.cbdr.body_high/low` |
| bias | ❌ | `StrategyRuntime.session.cbdr.daily_bias` |
| sweep | ❌ | `StrategyRuntime.last_sweep` |
| sweep level | ❌ | `StrategyRuntime.last_sweep.sweep_price` |
| FVG | ❌ | `StrategyRuntime.active_trade.trigger_fvg` |
| EQ | ❌ | Hesaplanan EQ değeri |
| trailing events | ✅ | `TrailingBridge.sync()` sonuçları |
| exit reason | ✅ | `TradeLifecycle.record_exit_deal()` status |
| PnL | ✅ | `RealizedDealRecord.pnl_r` |
| realized R | ✅ | `RealizedDealRecord.pnl_r` |
| timestamps | ✅ | `RealizedDealRecord.timestamp` |

---

## 9. Existing Observability Capabilities

| Mekanizma | Dosya | Durum |
|-----------|-------|-------|
| Persistent logging | `persistent_log.py` | ✅ Çalışıyor |
| AuditChain | `audit.py` | ✅ Çalışıyor |
| StateStore | `state.py` | ✅ Çalışıyor |
| PortfolioDD journal | `portfolio_dd.py` | ✅ Çalışıyor |
| TradeLifecycle | `trade_lifecycle.py` | ✅ Çalışıyor |
| PositionManager | `position_manager.py` | ✅ Çalışıyor |
| Reconciliation | `reconciliation.py` | ✅ Çalışıyor |
| Recovery | `recovery.py` | ✅ Çalışıyor |
| SafetyMonitor | `safety.py` | ✅ Çalışıyor |

---

## 10. Genuine Gaps

### Kritik (MUST HAVE)

| # | Boşluk | Etki |
|---|--------|------|
| 1 | Startup snapshot log | Başlangıçta ne olduğu görünmüyor |
| 2 | Per-symbol bootstrap log | Veri kalitesi doğrulanamıyor |
| 3 | CBDR state visibility | Strateji durumu görünmüyor |
| 4 | "Why no signal" log | Sinyal yokluğu açıklanamıyor |
| 5 | Mevcut pozisyonla yeni engelleme | Duplicate risk |
| 6 | SL/TP eksikliği tespiti | Koruma riski |

### Önemli (SHOULD HAVE)

| # | Boşluk | Etli |
|---|--------|------|
| 7 | Periyodik health check | Pozisyon sağlığı izlenemiyor |
| 8 | Watchdog | Takılı durum tespiti yok |
| 9 | Connection health log | Bağlantı sorunları görünmüyor |
| 10 | Recovery log | Kurtarma olayları loglanmıyor |

---

## 11. Implementation Order

### Adım 1: Repository Cleanup
- Kullanıcı onayı ile 12 dosya sil
- Git commit

### Adım 2: Startup Snapshot Logging
- `live_runner.py` başlangıç log ekle
- MT5 build, account, symbols, warmup bilgisi

### Adım 3: Per-Symbol Bootstrap Logging
- `candle_feed.py` warmup log ekle
- M1 count, M15 count, duplicates, missing

### Adım 4: CBDR State Visibility
- `strategy_runtime.py` CBDR state change log
- `live_runner.py` CBDR blocking reason

### Adım 5: "Why No Signal" Logging
- `live_runner.py` on_bar() blocking reason
- State machine: WAITING_CBDR, WAITING_SWEEP, vb.

### Adım 6: Position/Protection State
- `trade_lifecycle.py` position state log
- `position_manager.py` SL/TP verification

### Adım 7: Periodic Health Check
- Yeni modul: `health_check.py`
- ~60s aralıklarla broker snapshot + reconciliation

### Adım 8: Watchdog
- Status kilidi tespiti
- 90s üzeri stuck status → ACTIVE'e geri çek

---

## 12. Tests Available/Passed

### Mevcut Testler

| Test | Dosya | Durum |
|------|-------|-------|
| 65K regression | `tests/test_65k_regression_harness.py` | ✅ |
| Live audit safety | `tests/test_live_audit_safety.py` | ✅ |
| Live candle feed | `tests/test_live_candle_feed.py` | ✅ |
| Live execution | `tests/test_live_execution.py` | ✅ |
| Live paper | `tests/test_live_paper.py` | ✅ |
| Live parity gate | `tests/test_live_parity_gate.py` | ✅ |
| Live portfolio DD | `tests/test_live_portfolio_dd.py` | ✅ |
| Live position reconciliation | `tests/test_live_position_reconciliation.py` | ✅ |
| Live risk sizing | `tests/test_live_risk_sizing.py` | ✅ |
| Live signal runner | `tests/test_live_signal_runner.py` | ✅ |
| Live strategy runtime | `tests/test_live_strategy_runtime.py` | ✅ |
| Persistent logging | `tests/test_persistent_logging.py` | ✅ |
| P0-1 MT5 trailing | `tests/test_p0_1_mt5_trailing.py` | ✅ |
| P0-1 risk sizing | `tests/test_p0_1_risk_sizing.py` | ✅ |
| P0-2 lifecycle wiring | `tests/test_p0_2_lifecycle_wiring.py` | ✅ |
| P0-2 trade lifecycle | `tests/test_p0_2_trade_lifecycle.py` | ✅ |
| P1-5 timezone | `tests/test_p1_5_timezone.py` | ✅ |
| P2-6 paper continuity | `tests/test_p2_6_paper_continuity.py` | ✅ |
| E2E live chain | `tests/test_e2e_live_chain.py` | ✅ |

---

## 13. Visual Trade-Forensics Readiness

### Mevcut Durum

| Bileşen | Hazır? | Eksik |
|---------|--------|-------|
| OHLC/M15 bars | ✅ | - |
| CBDR | ❌ | Trade record'da yok |
| Sweep | ❌ | Trade record'da yok |
| FVG | ❌ | Trade record'da yok |
| EQ | ❌ | Trade record'da yok |
| Entry/SL/TP | ✅ | - |
| Trailing | ✅ | - |
| Exit | ✅ | - |

### Değerlendirme

Visual trade forensics için **hazır değil**. Önce TradeLifecycle'a strateji bağlamı (CBDR, sweep, FVG, EQ) eklenmeli. Bu, Phase 5'te tasarım aşamasında bırakılmıştır.

---

## 14. Recommended Next Single Implementation Step

### Önerilen Adım: Startup Snapshot Logging

**Neden:**
1. En düşük risk (sadece log ekleme)
2. En yükşek değer (başlangıçta ne olduğunu görme)
3. Diğer adımların temeli (bootstrap bilgisi)

**Uygulama:**
- Dosya: `src/live/live_runner.py`
- Değişiklik: `__init__()` sonrası startup log bloğu
- Test: `phase4_smoke.py` ile doğrula

**Beklenen Çıktı:**
```
[STARTUP] MT5 build=6140 account=53012914 server=ICMarketsSC-Demo
[STARTUP] Symbols: BTCUSD (M1=3030, M15=205, dup=0, miss=0)
[STARTUP] Warmup: bars=101 ATR=189.43 start_idx=101
[STARTUP] CBDR: key=2026-08-29 body=[0.0-Inf] locked=False bias=neutral
[STRATEGY] Ready — waiting for first signal
```

**Doğrulama:**
```bash
python phase4_smoke.py
grep -E "^\[STARTUP\]" logs/smoke_test.log
```

---

## Appendix A: Crypto vs Forex Karşılaştırma

| Özellik | Crypto | Forex | Transfer Gerekiyor? |
|---------|--------|-------|-------------------|
| Startup inventory | ✅ `_warmup_cbdr()` | ❌ | EVET |
| Daily event log | ✅ `event_log.py` | ✅ `audit.py` | HAYIR (zaten var) |
| Live state snapshot | ✅ `state_writer.py` | ✅ `state.py` | HAYIR (zaten var) |
| Console display | ✅ `console_reporter.py` | ❌ | EVET |
| ATR comparison log | ✅ `_warmup_cbdr()` | ❌ | EVET |
| Bias latch persistence | ✅ `state_manager.py` | ✅ `SessionState` | HAYIR (zaten var) |
| Watchdog | ✅ 90s stuck detection | ❌ | EVET |
| Per-symbol bootstrap | ✅ `_warmup_cbdr()` | ❌ | EVET |
| Trade lifecycle JSONL | ✅ `paper_trade_logger.py` | ✅ `audit.py` | HAYIR (zaten var) |
| Recovery logging | ✅ `recovery_manager.py` | ✅ `recovery.py` | HAYIR (zaten var) |

## Appendix B: Güvenlik Kontrol Listesi

- [ ] Strateji mantığı değişmedi
- [ ] Execution mantığı değişmedi
- [ ] Risk hesaplaması değişmedi
- [ ] State machine değişmedi
- [ ] Sadece `log.info()`, `log.warning()`, `log.error()` eklendi
- [ ] Yeni bağımlılık eklenmedi
- [ ] Tüm değişiklikler mevcut `log` nesneleri aracılığıyla
- [ ] Performans etkisi yok (logging async-friendly)
