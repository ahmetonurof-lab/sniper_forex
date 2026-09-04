# D91 — FAZ-2 KARANTİNA MANİFESTİ (Hakem BLOK-B; 2026-09-04 15:0x +03)

**Yetki:** Hakem-hükümü BLOK-B satır-1..9 (Reis-eli-tek-blok) birebir; icra-Cline. **Boot-C-dokunulmaz:** PID-18460-canlı; state/-audit-dokunuşu-YOK.

| B | Hedef | İşlem | Sonuç |
|---|---|---|---|
| 1 | `nul` (159B; PS-device-adı-anomalisi) | MSYS `rm ./nul` | ✓ silindi |
| 2 | `%EXPERTS_DIR%/` (mq5-ikiz-sha1 `a09b7ede…`≡docs-nüshası) | `rm -rf` | ✓ silindi (untracked-ikiz → git-kaybı-0) |
| 3 | `-p/` (içi-boş) | `rmdir ./-p` | ✓ silindi |
| 4 | `pytest_*.log` ×6 | → `archive/logs_20260904/pytest/` | ✓ taşındı (ignore-ZATEN-`.gitignore:20`) |
| 5 | `.gitignore` | +`.mypy_cache/` +`.pytest_cache/` | ✓ (36-MB-cache-artık-ignored) |
| 6a | `logs/benchmark/bench_bfix_rerun_34232a1.out` | **DOKUNULMADI — KANIT** (C-v1.1-rerun-stdout; `logs/`-ignore-gölgesi-yerinde-sürer) | ✓ masanın-hükmü: KANIT-aynen-durur |
| 6b | `logs/fix/` 11-madde stub-paketi | → `archive/logs_20260904/fix_stub_package/` | ✓ taşındı (docstring-mühürleri-korundu) |
| 7 | root `test_causality_extended.py` (TRACKED; `409fc17`-eski-variant) | **`git rm`** — scripts-nüshası `2bff15b`-kanonik | ✓ silindi (içerik-git-geçmişinde-kalıcı) |
| 8 | `results/` eski-artefaktlar: abfix_eq_trades.json (96KB) + exp5{b,c,c,c,e,f}×6 + expA{summary,trades,dryrun}×3 | → `archive/results_20260904/{benchmark/repro_icmarket,research}/` | ✓ 10-dosya-taşındı; boş `repro_icmarket/`-rmdir |
| 9 | `.vscode/`+`data/`+`docs/`-untracked-kitlesi | **DOKUNULMADI** — charter-dışı | ✓ |

**Commit-kesimi (tracked):** `.gitignore`(M) + `results/D91_karantina_manifest.md`(N) + `test_causality_extended.py`(D-git-rm) + `archive/`-(N-tracked-kesim) — tek-commit, LOCAL; push-nihai-pakette-hash-bound-talebiyle.
**Not:** 6b-stub .py-dosyaları-arşivde-tracked-kesime-girer — pre-commit-kancaları-üzerinden-geçmeli; hook-preflight-sonucu-mesajda.
