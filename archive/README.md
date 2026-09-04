# ARŞİV — FAZ-2 KARANTİNA TAŞIMASI (2026-09-04; Hakem BLOK-B)

Bu ağaç, D89-FAZ-1 envanteri sonrası FAZ-2 karantinayla taşınan **temizlik-eşyası**dır
(kanıt DEĞİL; istisna — kanıt `logs/adli/`'de ayrı tutulur, bakınız D92).
Menşei + bütünlük mührü: `archive/SHA256SUMS` → `sha256sum -c archive/SHA256SUMS`

| Bölme | İçerik | Menşei |
|---|---|---|
| `logs_20260904/pytest/` | `pytest_*.log` ×6 (ignored; `.gitignore:20`) | repo-kökü |
| `logs_20260904/fix_stub_package/` | kripto-P1-fix-sandbox **stub-paketi** (9-py; docstring-mühür: "Local test stub / SECRETSIZ kopya") | `logs/fix/` |
| `results_20260904/benchmark/repro_icmarket/` | `abfix_eq_trades.json` (96KB; untracked) | `results/benchmark/repro_icmarket/` |
| `results_20260904/research/` | exp5{b,c×3,e,f}-raporları ×6 + expA{summary,trades,dryrun} ×3 (untracked) | `results/research/` |

**Kural (D92):** arşive yeni giriş = `SHA256SUMS` satırı eklenerek (mühür-zinciri kopmaz).
Kanıt-bölmesi: `logs/adli/` (C-v1.1-rerun-stdout, sha256 `de4c621fd4528692` — Bulgu-6a hükmü).
