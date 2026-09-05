## D92 — FAZ-3-İLK-ADIM: ARŞİV-MÜHÜR-DEFTERİ (Hakem-BLOK-C; 2026-09-04 15:1x +03)

- **Yapı:** `archive/{logs,results}_20260904/` (tracked; `SHA256SUMS`-mühürlü) + `logs/adli/` (kanıt-bölmesi) + `logs/runtime/` (soak-yapı-iskeleti). Kanıt-tevkili: `logs/benchmark/bench_bfix_rerun_34232a1.out`→`logs/adli/` (sha256 `de4c621fd4528692` — **taşındı-içerik-değişmedi**).
- **Mühür:** `archive/SHA256SUMS` = tüm-arşiv-dosyaları-manifesti (`sha256sum -c archive/SHA256SUMS`-doğrulanabilir); örnekler: pytest_full.log `fb0b947fc94ac01c` · abfix_eq_trades.json `e85311c9c5975088` · expA_concurrent_cap_trades.json `b0c462125896b9ee`.
- **Kural:** arşive-yeni-giriş = SHA256SUMS-satırı-eklenmesiyle (mühür-zinciri-kopmaz); README `archive/README.md`.
- **Git-realiite-notu (kabul-beyanı):** `logs/adli/`-kanıtı `logs/`-ignore-gölgesinde → remote-yedek-DIŞI; Bulgu-6a-hükmü "KANIT-aynen-durur" yer-karı-budur.
- **FAZ-3-kalanı:** N2#23 (R-3+R-1 temiz-log-inşası) + log-bütçeleri — ayrı-charter. **LOCAL** (set-yukarıda).
