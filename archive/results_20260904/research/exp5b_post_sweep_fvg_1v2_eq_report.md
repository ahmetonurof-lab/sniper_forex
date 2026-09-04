# EXP5B — Final Rapor

**READ → VALIDATE → RUN → ATTRIBUTE → DOCUMENT** tamamlandı. Production koduna dokunulmadı; OB/Breaker = N/A; production EQ değişmedi.

---

## Kanıt Standardı

| Öğe | Değer |
|------|-------|
| Test command | `python -m pytest tests/ -v` |
| Backtest command | `python run_exp5b.py` |
| Workers | 6 (`multiprocessing.Pool`, sembol başına 1) |
| Date range | **2026-02-22 → 2026-08-21** (6 parite) |
| Config | 15m, TP_RR=1.8, SL_ATR=1.5, FVG_MIN=0.06·ATR, WICK≤0.75, ATR14, CBDR 19→01, tol=0.5·ATR |

---

## Population

| Metric | Değer |
|--------|-------|
| Total CBDR sweeps | 630 |
| FVG #1 | 630 |
| FVG #2 | 621 |
| Historical trades | 529 |

---

## Research EQ — FVG #1 vs #2

| Metric | FVG #1 | FVG #2 |
|--------|--------|--------|
| Correct at formation | 244 (**38.7%**) | 157 (**25.3%**) |
| Crosses EQ | 81 | 69 |
| Wrong at formation | 305 (48.4%) | 395 (63.6%) |
| NO_SWING_YET | 0 | 0 |
| Later becomes correct | 381 (60.5%) | 460 (74.1%) |
| Never becomes correct | 5 (0.8%) | 4 (0.6%) |
| Correct after 1 swing | 88 | 100 |
| Correct after 2 swings | 145 | 172 |
| Correct after 3+ swings | 148 | 188 |
| Fresh when first correct (later cohort) | 116 (**30.4%**) | 155 (**33.7%**) |
| Fresh when first correct (all) | 360 / 625 (57.6%) | 312 / 617 (50.6%) |

---

## Outcome Attribution (observation-only, no rule selection)

| FVG | N | WR% | Avg R | Total R | MaxDD | TP | PT | LOSS |
|------|---|------|-------|---------|-------|----|----|------|
| FVG #1 | 434 | 58.3 | 0.774 | 335.92 | 6.20 | 66 | 187 | 181 |
| FVG #2 | 33 | 51.5 | 0.071 | 2.33 | 7.00 | 3 | 14 | 16 |
| Later/Unknown | 62 | 74.2 | 2.806 | 173.97 | 5.00 | 9 | 37 | 16 |

---

## Interpretation

**Soru 1 — "Yanlış EQ'da doğan FVG sonradan doğru tarafa oturuyor mu?"**

Evet — neredeyse her zaman: never-correct ≈ %1'in altında. Ama kritik ayrıntı: **first-correct medyanı her iki slotta 165 dk** ve sonradan-correct olanların **yalnızca ~%30-34'ü o anda hâlâ fresh**. Yani EQ tarafı neredeyse hiç kalıcı olarak yanlış değil; asıl kısıt, düzelme geldiğinde bölgenin tazeliğini kaybetmiş olması (~⅔ durumda).

**Soru 2 — "#1 ile #2 sistematik farklı mı?"**

Evet, ama **formation'da**: #1 %38.7 vs #2 %25.3 correct doğuyor (13.4 puan). Eventual correction davranışında fark yok (hiç-correct farkı 0.1 puan, later-correct farkı 0.4 puan). #2 yapısal olarak daha geç, daha geride oluşuyor; #1 sweep sonrası structure-fresh bölgede yakalanıyor.

---

## Dosyalar

| Dosya | Açıklama |
|-------|----------|
| `exp5b_post_sweep_fvg_1v2_eq.py` | Ana modül |
| `test_exp5b_research_eq.py` | 20 unit test |
| `exp5b_post_sweep_fvg_1v2_eq_telemetry.json` | Ham veri |
| `exp5b_mini_validation.txt` | EURUSD 14g validation |
| `exp5b_pytest_v_raw.txt` | Ham pytest çıktısı |

**Kural**: Entry kuralı önerilmiyor (mandatory/fallback, sliding nearest, EQ gate vb. kararları bu veri ayrıca tartışmayı gerektiriyor).
