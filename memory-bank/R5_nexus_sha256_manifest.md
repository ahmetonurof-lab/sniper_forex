# R5 — NEXUS DEPENDENCY SHA256 MANIFEST (R5 close-out)

> **Scope:** R5 (provenance kaydı) — nexus dependency fingerprint sabitleme.
> **Status:** CLOSED (2026-09-01, read-only kayıt — kod değişmedi).
> **Freeze:** `src/`, `tests/`, `index.json` tested HEAD `244f4c3`'te
> donduruldu (§17). Bu dosya memory-bank — izinli chore kaydı.

## 1. Nexus dependency lokasyonu

C2 POST_SWEEP_FVG portu (`src/live/strategy_runtime.py`) nexus motorunu
import etmez — kopya-uyarlama (copy-adapt) ile frozen research engine'den
bağımsız çalışır (`src/live/candle_feed.py` docstring: "live runtime does
NOT import from the frozen research engine"). Ancak:

- **Reference/parity anchor:** `C:/Users/Administrator/Desktop/nexus-mcp/sniper/src`
  (harici repo) — FVG/bar/pivot semantiğinin kanonik kaynağı.
- **MUST-SEE #1:** `real_index` semantiği bu repo'dan okundu (aşağıda).

## 2. SHA256 manifest (2026-09-01, N2 #13 seti anı)

```
nexus-mcp/sniper/src/fvg.py    → 950578d5caf19514570c42b91e3329ecd269f976ba77eb0a62cb491d91dae1b1
nexus-mcp/sniper/src/models.py → a95a4bb2ffb109783b3bcd6ebfb643cdc1811dc81d59c8684017c2fa73338faf
nexus-mcp/sniper/src/pivot.py  → 0d34822cbeec34ff05c5cb930068072428bb919d20cffaa69387889c49001578
```

- Hash yöntemi: `certutil -hashfile <file> SHA256` (Windows).
- Bu hash'ler "N2 #13 seti" anındaki bilinen-iyi nexus sürümünü sabitler.
- Eğer nexus repo gelecekte değişirse, önce bu manifest'e kayıt + parity
  testi — sessiz promotion YASAK (§8.1, §2.3).

## 3. MUST-SEE #1 — real_index semantiği (R3'ün kaderini belirleyen okuma)

`nexus-mcp/sniper/src/fvg.py` `detect_fvgs()`:

```python
fvg = FVG(
    direction="bullish",
    top=b_next.low,
    bottom=b_prev.high,
    real_index=b_curr.index,   # ← impulse/orta bar index'i
    timeframe=timeframe,
)
```

- **`real_index` = FVG'yi oluşturan impulse bar'ın (b_curr, i) index'i** —
  üç-bar pattern'in (b_prev, b_curr, b_next) ORTA barı. "Formation bar".
- `models.py` `FVG` dataclass: `real_index: int`, `_next_check_abs`
  default `real_index + 2` — tarama orta bar'dan 2 sonra başlar.
- **R3 doğrulaması:** `src/live/strategy_runtime.py:94` `_is_fresh_fvg()`:
  ```python
  scan_from = fvg.real_index + 2
  for b in bars_15m[scan_from:current_index]:
  ```
  Python slice `bars_15m[scan_from:current_index]` **end-exclusive** —
  current bar (current_index) TARANMAZ. Current bar far-side close ile
  FVG'yi invalide etse bile `_is_fresh_fvg` True döner.
  → **R3 finding CONFIRMED** (AUDIT_1/2/gemini ile tutarlı).
  → Düzeltme önerisi: current-bar invalidation semantics (normal touch
  izinli; far-side close reddedilir) — blind `current_index+1` DEĞİL.
  → Detaylı reproducer: `docs/R1-R6_A2_freshness_reproducer.md` (bkz. (c)).

## 4. Referanslar

- `src/live/strategy_runtime.py` `_is_fresh_fvg` (satır 94)
- `src/live/candle_feed.py` `resample_15m` (satır 43, frozen boundary)
- `nexus-mcp/sniper/src/fvg.py` `detect_fvgs` / `update_fvg_states`
- `nexus-mcp/sniper/src/models.py` `Bar` / `FVG` dataclass'ları
- `memory-bank/activeContext.md` R1-R6 REMEDIATION section (REVISED)
