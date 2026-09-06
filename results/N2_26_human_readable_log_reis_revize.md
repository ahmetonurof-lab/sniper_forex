# N2#26 — İnsan-Okunur-Log REIS Revizyonu (yerel saat + offset, logs/<SYM>/live.log, bar_ts)

> **Durum:** PRE-REG (Hakem ratifikasyonu bekliyor)
> **Tarih:** 2026-09-06
> **Kaynak:** REIS direktifi (askQuestions yanıtları) — N2#25'in (Hakem-ratifikasyonlu) revizyonu

---

## 1. REIS Kararları (2026-09-06)

| # | Karar | Detay |
|---|-------|-------|
| 1 | **Format** | Yerel saat + offset: `2026-09-05 22:13:00 +0300` (ISO-8601 UTC beğenilmedi) |
| 2 | **Konum** | `logs/<PARİTE>/live.log` — kanonik; `logs/` gitignored; pariteye göre alt klasör (state_btc_d104'te DEĞİL) |
| 3 | **Replay burst** | STATE event'lerinde `bar_ts` göster (cold-rebuild replay'de aynı-saniye burst'ü ayırt etmek için) |

REIS gerekçesi (free-text): "state_btc_d104'te olması doğru mu? Bizim log klasörümüz var... logs. Pariteye göre klasör açılmış. Yarın parite değiştiğinde BTC klasöründe EURUSD motoru çalıştıracağız? live.log iyidir."

## 2. Zaman-Dilimi Disiplini (§6.3)

- Proje kuralı (orchestrator.py:76): **naive = UTC** (`clock._utcnow_naive`).
- Event epoch → yerel+offset: `datetime.fromtimestamp(epoch).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")`.
- `bar_ts` (naive-UTC, `bar.timestamp.isoformat()`) → yerel+offset: `fromisoformat → replace(tzinfo=UTC) → astimezone()`.
- Offset her satırda açık (`+0300`) → §6.3 naive-karışım yasağı korunur.

## 3. Kapsam

- `tools/make_readable_log.py` — format + kanonik konum + bar_ts.
- `tests/test_make_readable_log.py` — N2#25 testlerinin revizyonu + yeni testler.

## 4. Risk

- **Düşük.** Araç-only (production `src/live/*` dokunulmaz). `logs/` gitignored → runtime artefaktı.
- N2#25'in ISO-UTC pin'i REIS kararıyla değişiyor — Hakem ratifikasyonu gerekir.

## 5. Kanıt Kontrol Listesi (doldurulacak)

- [x] `pytest tests/test_make_readable_log.py -v` → **5 PASSED** (state/signal/all-lines/default-output/bar_ts)
- [x] Canlı dönüşüm: `logs/BTCUSD/live.log` üretildi (661 satır), format `+0300`
- [x] bar_ts STATE satırlarında görünüyor (replay burst ayırt ediliyor: 04:00/05:30/08:30/18:30)
- [x] `git diff tools/make_readable_log.py` incelendi (aşağıda özet)

**Diff özeti (tools/make_readable_log.py):**
- `_fmt_local()`: epoch → `%Y-%m-%d %H:%M:%S %z` (yerel+offset)
- `_fmt_bar_ts()`: naive-UTC bar_ts → yerel+offset (proje kuralı naive=UTC)
- `_derive_symbol()`: ilk gerçek symbol
- `main()`: 1-arg → `logs/<SYM>/live.log`; 2-arg → explicit; STATE'te bar_ts

## 6. Commit Protokolü

- Mesaj: `feat(n2_26): make_readable_log REIS revizyonu — yerel+offset, logs/<SYM>/live.log, bar_ts`
- Kapsam: `tools/make_readable_log.py` + `tests/test_make_readable_log.py` + bu pre-reg
- **PUSH YASAK** — Hakem ratifikasyonu + hash-bound onay beklenir.
