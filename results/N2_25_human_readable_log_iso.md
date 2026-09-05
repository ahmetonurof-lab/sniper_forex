# N2#25 — İnsan-okunur-log ISO-alanı kod-ameliyatı

> **Pre-reg (Hakem-ratifikasyonu: ONAYLANDI · UTC-0 tercih edildi · 2026-09-06)**
> **Kuyruk:** 5 (D106 öncesi) · **İcra:** Cline · **Push:** YASAK (local-only; hash-bound onayı bekler)

## 1. Bağlam ve misyon

`tools/make_readable_log.py`, `audit.jsonl` ham verisini Reis için okunabilir `.log` dosyasına
çevirir. Mevcut durumda `strftime("%Y-%m-%d %H:%M:%S")` ile **naive (saat dilimsiz)** zaman
damgası basılıyordu — AGENTS.md §6.3 (Timezone discipline) ihlali.

**Hedef:** Zaman damgasını **ISO 8601 + UTC** formatına (`YYYY-MM-DDTHH:MM:SS+00:00`) yükseltmek.

## 2. İzolasyon sınırları (dokunulmazlar)

- `src/live/*` — **KESİNLİKLE DOKUNMA**
- Canlı bot **PID-1924** — dokunma
- `index.json` ve `state/` — dokunma
- Değişiklik **yalnızca** `tools/make_readable_log.py` + `tests/test_make_readable_log.py`

## 3. Değişken (tek)

| Alan | Önce | Sonra |
|---|---|---|
| Zaman damgası | `datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")` (naive) | `datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")` (ISO-8601 UTC) |

## 4. Beklenen (pre-reg — gözlem öncesi)

- **Format:** her çıktı satırı `YYYY-MM-DDTHH:MM:SS+00:00` ile başlar.
- **Test:** `tests/test_make_readable_log.py` — 3 test (STATE→CBDR-KILIT, SIGNAL, tüm-satır-ISO).
- **Kanıt:** `pytest tests/test_make_readable_log.py -v` → 3 PASS · `git diff tools/make_readable_log.py` · örnek çıktı ilk-5-satır.

### §12.1 Sapma-notu (direktif örneği)

Direktifin örnek değeri `1757158245` == `2026-09-06T14:30:45+00:00` iddia etti; **doğrulanan
dönüşüm `2025-09-06T11:30:45+00:00`** (direktifte aritmetik hata; 1 yıl + 3 saat kayık).
Test **kanıt-bazlı değeri** sabitler; format gereksinimi değişmez.

## 5. Risk

- Production dokunulmadı (`src/` hariç) — **düşük risk**.
- `tools/`-dokunuşu D107 ile serbest (`tools/-dokunuşu-serbest, src/-değil`).

## 6. Kanıt (icra sonrası — DOLDURULDU 2026-09-06)

- [x] **Diff özeti:** `tools/make_readable_log.py` — tek değişiklik: `strftime("%Y-%m-%d %H:%M:%S")` (naive) → `fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")` (ISO-8601 UTC).
- [x] **Test sonucu:** `pytest tests/test_make_readable_log.py -v` → **3 passed** (STATE→CBDR-KILIT, SIGNAL, tüm-satır-ISO).
- [x] **Örnek çıktı** (küçük audit.jsonl parçası, ilk-4-satır):
  ```
  2025-09-06T11:30:45+00:00 [BOOT] BTCUSD: verdict=PROCEED warmup=4342
  2025-09-06T11:30:46+00:00 [CBDR-KILIT] BTCUSD: range=79940.88..79994.74 session=2026-09-05
  2025-09-06T11:30:47+00:00 [BIAS] BTCUSD: bullish kilit=sweep (V6-durumu=v6)
  2025-09-06T11:30:48+00:00 [SIGNAL] BTCUSD: side=long entry=80000.0 reason=cbdr_sweep_fvg_fill
  ```
- **Doğrulama:** her satır `YYYY-MM-DDTHH:MM:SS+00:00` ile başlıyor (ISO-8601 UTC) ✓

## 7. Commit / push protokolü

- **Commit kapsamı:** `tools/make_readable_log.py` + `tests/test_make_readable_log.py` + bu dosya.
- **Commit mesajı:** `feat(n2_25): make_readable_log ISO-8601 UTC timestamp`
- **PUSH: YASAK** — commit yerel kalır; push için Hakem'den yeni hash-bound onayı beklenir.
