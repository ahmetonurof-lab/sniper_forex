# D89 — FAZ-1 ENVANTER + WORKTREE-PROTOKOLÜ İCRASI (Hakem D89-hükmü; salt-okuma + onaylı-remove)

**Tarih:** 2026-09-04 · **İcra:** Cline · **Charter:** Hakem-D89-FAZ-1 (envanter, her-dosya-etiketli) + worktree-kaldırma-protokolü (Reis-sahiplik-beyanıyla-onaylı). **Mutasyon-sınırı:** yalnız-bu-rapor + defter-girdisi + worktree-remove (protokol-Adım-3); başka-dokunuş-YOK (karantina-silme/taşıma/ignore = FAZ-2, Reis-✓-bekler).

## 1. WORKTREE-PROTOKOLÜ (üç-adım; tamam)

**Reis-sahiplik-beyanı (deftere-alıntı):** *"konsey-kurmuştum, kontrolsüz-çalışmaydı, sonrasında-hiç-kullanmadım, gereksiz."*

| Adım | Komut/kanıt | Sonuç |
|---|---|---|
| 1-teşhis | `git worktree list --porcelain` | five-jackfruit → branch `refs/heads/five-jackfruit`, HEAD `449806a` ("docs: record Phase 2B.1 decision closure", 2026-08-20 17:21) |
| 1-hüküm-i | `git log main..five-jackfruit` = **BOŞ**; merge-base == 449806a; `main` +131-commit-öne; `git branch --merged main` ✓; `git branch -d` kabul (çifte-merged-teyit); **unpushed-commit-YOK**; 449806a zaten `origin/main`-içinde | kayıp-iş-riski-SIFIR → devam |
| 1-hüküm-ii | `git -C ... status --short` = **boş** | temiz → Adım-2 |
| 2-A-dif | `comm -13` (ana-D-etiketleri-eksi-ikiz-D-etiketleri) = **BOŞ**; ikiz-progress.md = 39L (ana: 2011L); `git diff --stat 449806a main` = +2011/−40 (sadece-ana-büyümüş) | defter-ikizinde-ANA-da-olmayan-tek-satır-YOK |
| 2-B-untracked | status-boş | untracked-kanıt-YOK |
| 3-remove | `git worktree remove` rc=0 → `worktree prune` → `git branch -d five-jackfruit` (was 449806a) | TEYİT: worktree-list = yalnız-main; branch-list = yalnız-main; `.kilo/worktrees/` = **boş** |

**Remove-güvencesi:** status-boş-olduğundan-remove-ile-hiçbir-untracked-içerik-kaybedilmedi; 39L-defter-ikizi-+ src/{config,data,trading} nüshaları git-tarihinde (449806a, origin/main) kalıcı. **Modül-dublajı-riski sona erdi; tek-defter restore edildi.** `.kilo/` kalan-özü: agent-manager.json + node_modules + package.json (ajan-runtime; kendine-ait-.gitignore-var).

## 2. KARANTİNA-LİSTESİ — GIT-REALİTE-ETİKETLİ ENVANTER (Reis-✓-tablosu, FAZ-2-icra-bekler)

| # | Hedef | Git-durumu (ölçülmüş) | Boyut/tarih | Sınıf + öneri |
|---|---|---|---|---|
| 1 | `nul` | untracked (ls-files-boş) | 159-B · 09-01 23:33 | Win32-device-adı: PowerShell-`\\?\`-okuma-BAŞARISIZ ("FileStream…device" — kanıt-kendisi); MSYS-bash gerçek-dosyayı-görür → **FAZ-2-silme: `rm ./nul` (MSYS), fallback cmd `del \\?\C:\...\nul`**. İçerik-okunamadı (159-B; muhtemel-menşei: git-bash'te-cmd-usulü `> nul`-yönlendirmesi) |
| 2 | `%EXPERTS_DIR%/` | untracked | 1-dosya: PING_RECEIVER_NATIVE.mq5 4,378-B · 08-30 02:43 · **sha1 `a09b7ede3da5d3674e99bb43979d1339e3e26f6b`** | **İKİZ-MÜHRÜ: `docs/PING_RECEIVER_NATIVE.mq5` = AYNI-sha1** (ikisi-de-untracked → git-kaybı-sıfır; docs-nüshası-saklanır) → sil |
| 3 | `-p/` | untracked | **BOŞ-dizin** · 08-29 17:30 | kesik-komut-artığı teyit-içi-boş → `rmdir ./-p` (MSYS-başarır; PowerShell-istenirse `\\?\`-prefix) |
| 4 | `pytest_*.log ×6` | **ZATEN-git-ignored** (`.gitignore:20 pytest_*.log`; check-ignore-✓) | 192B/56,119B/21,091B/112B/101B/102B · 09-02 19:32–20:05 (D85-suit-dönemi) | ignore-ekleme-GEREKMEZ; **arşiv-taşıma** → `archive/logs_20260904/pytest/` (içerik-örneği: "65 passed", "37 passed" — temiz-koşu-çıktıları) |
| 5 | `.mypy_cache/` | untracked, ignore-YOK | 36-MB · 08-20 | cache → `.gitignore`-satırı-ekle: `.mypy_cache/` (+aynı-turda-`.pytest_cache/` — root'ta-untracked-cache-var); sil-GEREKMEZ |
| 6a | `logs/benchmark/` (1-dosya) | untracked | bench_bfix_rerun_34232a1.out · 4,149-B · 08-31 20:37 | **KANIT** — RESEARCH-C-v1.1-rerun-stdout'u (2.7Y-full, 6-sembol, commit-tagli-ad `34232a1`) → koru/arşive-taşı (`logs/adli/`-adayı, FAZ-3-yönü) |
| 6b | `logs/fix/` (11-madde) | untracked | 08-28–09-01 | **KANIT-DEĞİL — kod-stub-paketi!** `__init__.py`: *"Local test stub (logs/fix paketini isaretler)"*; config.py: *"server config'inin SECRETSIZ kopyası"*; bot_binance.py-57KB + risk_manager + 3-test + `.pytest_cache`/`__pycache__`-çöpü = kripto-P1-fix-sandbox-kalıntısı → arşive-taşı `archive/logs_20260904/fix_stub_package/` (Reis-dokunuş-kararı) |
| 7 | `test_causality_extended.py` (root) | **TRACKED** (⚠ manifest→sil-UYMAZ — git-bilinçli-karar-şart) | 9,570-B · son-commit `409fc17` (08-28) | **ESKİ-VARİANT:** scripts/ nüshası `2bff15b` (08-30)-de-yenilenmiş (diff: +87/−57; BenchmarkTrade-import+format). Öneri: FAZ-2'de `git rm` root-kopya (tarih-korur); Reis-kararı |
| 8 | `.kilo/worktrees/five-jackfruit` | git-bilinçli-remove | — | **TAMAMLANDI** (§1) |


## 3. Tarih-filtreli-kanıt-ayrımı-önerisi (FAZ-3-yön-öncesi-not)
- `logs/benchmark/bench_bfix_rerun_34232a1.out` = tek-kanıt-dosyası → `logs/adli/`-ya-da-archive-kanıt-bölmesi; `logs/fix/` = stub-kod → kanıt-değil (arşiv-taşıma-yeter).
- `results/` düzeni: tracked-artifactlar (`results/benchmark/PURE_D_FVG_ORIGIN_EQ_benchmark.json`, `results/research/`-içi-tracked-json/md) yerinde-kalır; untracked-eski-artefaktlar (`results/benchmark/repro_icmarket/abfix_eq_trades.json` 96KB · 08-30, `results/research/exp5*_*.json/md`-grubu, `expA_concurrent_cap_trades.json` 2.4MB) → `archive/results_20260904/` (FAZ-3, Reis-yön-✓).
- Root-ek-görüntü (tam-tarama-notu): `.vscode/` · `data/` · `docs/`-altı-çoklu-untracked — önceden-bilinen-136-kayıt-kitlesi; bu-charterin-dışında, dokunulmadı.

## 4. Yöntem
`git worktree list --porcelain` · `git log main..five-jackfruit` · `git merge-base` · `git branch --merged/-d` · `comm -13 <(grep -oE 'D[0-9]{2,3}' …)` (iki-progress.md-D-etiket-örme-diferansiyeli) · `git -C <wt> status --short` · `git ls-files` (tracked-ayrımı) · `git check-ignore -v` · `sha1sum` (ikiz-mührü) · `git diff --no-index` (causality-variant-karşılaştırması) · `du -sh` · PowerShell-device-adı-okuma-denesi (başarısızlık-kendisi-kanıttır). **Boot-C-dokunulmaz-teyidi:** PID-18460-alive; audit.jsonl = 23-satır (son: SAFETY/startup_SAFE_START/AUDUSD) — envanter-boyunca-hiçbir-runtime-dosyasına-dokunulmadı (state/-gitignore-hattı).

**Kapı-durumu:** worktree-protokolü-B2-KAPANDI; FAZ-2-karantina-yürütmesi + FAZ-3-yön-taslağı + Faz-0-push {`173be24`, `100160d`, `7874470`, `b59f2c2` + bu-commit} = Reis-yazılı-✓-bekler.
