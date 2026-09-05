## D92 — LOG-VE-ENTRY-GENİŞLEMESİ CHARTER (Hakem-hükmü; 2026-09-05)

- **AM-N23-2 (ts-şartı):** her-emisyon-satırının-başlık-ts (event-time-epoch)-ZORUNLU; içerik-ts'ler-(bias_lock_ts-gibi)-ikincil-rapor-dili. **Canlı-dogrulama (probe, state/t10d_preserve/ts_integrity_probe.py):** 224/224-satır-ts-taşıyor · epoch-float · **0-monoton-ihlal** · payload-iso-bozuk-0 → **KARAR: mekanizma-KARARLI, deftere-düzeltme-komutu-GEREKMEZ.** Replay-semantiği-notu: S9-kümesinde-satır-ts=replay-anı (34-farklı-an, ~1s: 20:58:18-19), bar_ts=içerik-tarihi (temmuz-mezuniyet) — ikili-ayrık-alanlar-doğru-tasarım ("olay-ne-zaman"=satır-ts; "içerik-ne-zaman"=bar_ts).
- **AM-N23-3 (insan-okunur-payload):** emisyon-payload'ları-insan-okunur-ölçüler-taşır (fvg_top/fvg_bottom/fvg_size_pip/direction); id-yanına-öz-ölçüler-zorunlu.
- **N2#23-b (fvg_armed):** sweep-STATE→SIGNAL-arası-sessizliğin-kapatılması — `STATE(moment=fvg_armed)`-emit. **Canlı-motivasyon-kanıtı:** t10d-boot-sonrası-canlı-döngü-0-STATE (Cuma-gecesi-geçiş-yok) → arm-fazı-masa- için-görünmez. Pre-reg: `results/N2_23b_prereg_fvg_armed.md` — **Reis-onayı-ÖNCE-KOD-YOK**; census-sonrası-tek-ameliyat-deseni (D89).
- **Trailing-perspektifi-pini:** trailing-log-R-2/R-5-adımlarında-census'la-çizilir; şimdilik-SIGNAL-çapa-payload'ı-yeterli.
- **SAFE_START→FULL-geçiş-zinciri (3-şart):** N2#23-b-yeşil + süit-yeşil + Reis-onayı → FULL-boot (D30-trade_mode=4) → ilk-e2e-canlı-order-zinciri kanıtı (SIGNAL→RISK→ORDER→FILL→POSITION; FILL-pini-R-4-charter).
- **YENİ-KALICI-KURAL (deftere):** *"Kripto-log-standardı-masanın-referansıdır: her-olay-üçlüsü (ne-zaman/ne-olmuş/ne-kadar) tek-bakışta-görünür; eksik-halinde-census-önce-yazılır, sonra-kod-dokunuşu."*
- **LOCAL:** bu-defter-commiti-unpushed — SET-2-hash-bound-sete-biner.
