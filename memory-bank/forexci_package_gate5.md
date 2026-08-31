# FOREXÇİ TİCARİ PAKETİ — Gate ⑤ + Gate ① (C2) — N2 #9 girdisi

> **Durum:** HAKEM RATİFİKASYONU sonrası hazır (N2 #8, 2026-08-31).
> **Kaynak disiplin:** Tüm sayılar commit'lenmiş artifact'tan doğrulandı
> (`results/research/c_v1_1_summary.json`, hane-hane) — hafızadan değil.
> **Bağlı HEAD (FREEZE):** `5ecbf0c4aa21d0246d59076c2348c61a60751a92`
> (origin/main'de; src/+tests/ donmuş).

---

## 1. RİSK PROFİLİ (C v1.1 kanonik — tek-eğri semantik)

| Metrik | Değer | Not |
|---|---|---|
| İşlem sayısı | **2302** | 6-major evreni, 15m |
| Net PnL | **+2593.26R** | başlangıç 100R → ~2693R |
| MaxDD | **5.00R (2.24%)** | absolute-unit dd semantiği |
| Profit Factor | **4.97** | |
| Win rate | **69.37%** | 1597W / 705L / 0 açık |
| Avg R | **1.1265R** | |
| paused | **0** | DD-ladder hiç devreye girmedi (Q5: invariant 0/2302 ateş) |
| Koşum süresi | 79.7 s | deterministik reprodüksiyon mevcut |

Semantik beyanı: equity yalnız kabul-edilen işlemlerin ÖLÇEKLENMİŞ
pnl'iyle EXIT'te ilerler; paused = sıfır-katkı; çarpan ENTRY'de kilitli.
(b)-fix (c66888a) bu semantiği fail-fast invariant ile mühürledi:
EXIT-çarpanı-YOKSA → sessiz düşüş yerine dropped-sayacı + audit-ERROR +
`MAX_DROPPED_SIGNALS=0` → RuntimeError.

## 2. ÇARPAN DAĞILIMI KAYDI (yapısal değişim — sahibin bilgisi)

| Dağılım (x1 / x0.5 / x0.25) | Ölçeklenen işlem | Oran |
|---|---|---|
| ESKİ (double-curve-era kayıt) | **2186 / 99 / 15** | 114 | %4.9 |
| YENİ (single-curve kanonik) | **1994 / 278 / 30** | 308 | **%13.4** |

DD-ladder artık 2.7× daha sık risk ölçekliyor. Bu bir iyileşme/bozulma
değil, **semantik doğrusunun sonucudur**: eski eğri paused-durumunu
eğriye katmıyordu; yeni eğri gerçek sermaye-eğrisiyle ölçekler.
→ **t1/t2/t3 eşikleri (2R/4R/6R) eski eğrinin dd-davranışına göre
seçilmişti; yeni eğriyle kalibrasyonu artık SAHİBİN KARARI (KARAR-1).**

## 3. KARAR-1 (Gate ⑤) — ticari onay

1. Risk profili onayı: yukarıdaki tablo ticari öneri tabanına esas mı?
2. **t1/t2/t3 kalibrasyonu:** 2R/4R/6R sabit kalsın mı, yeni %13.4
   ölçekleme profiline göre yeniden mi ayarlansın?
   (Karar → config-değişikliği → tam süit → N2 #9 prosedürü işler.)

## 4. KARAR-2 (Gate ① / C2) — replay-sonu aktif işlem semantiği

Soru: warmup-replay sonunda simüle edilmiş `active_trade` varsa, canlı
girişler bastırılsın mı?

Masadaki öneri: `end_state = active_trade` → `entries_enabled ∧= False`
(simüle pozisyon gerçek broker'da yok; yeni giriş açmak çift-yönelimli
maruziyet üretebilir). Retoneliği: soğuk-boot sonrası ilk saatlerde
sinyal-körlüğü yaratabilir — ikisi de savunulabilir; **yazılı
kabul/reddin N2 kaydına girecek.**

## 5. PROVENANS REFERANSI (TAG `research-canonical-v1.1` — hazır-koşullu)

Paket içeriği (TAG atılmadan önce kapanan ③ listesi):

- (b)-fix hash: `c66888a3db8ea9618a3b92e6743802e801d882be`
- flake-fix hash: `5ecbf0c4aa21d0246d59076c2348c61a60751a92`
- benchmark: 2302T / +2593.26R / 5.00R / PF 4.97 / paused=0
  (`results/research/c_v1_1_summary.json`, tracked)
- dataset SHA256 manifest: **24/24 MATCH / 0 MISMATCH**
  (`memory-bank/benchmark_provenance_c_v1_1_arbitration_b.md` §, 18 feather + 6 raw CSV)
- single-curve semantik beyanı (bu dosya §1)
- faz-matrisi determinizm kanıtı: 10/10 PASS, commit-blob üzerinde
- **parity-skip kapanışı — İKİ YOLDAN TAMAM (2026-08-31):**
  (i) `test_parity_6majors` açıkça koşuldu: **7/7 PASS, 0 skip, 514.06 s**
      (frozen HEAD ağacı — src/tests/index = `5ecbf0c` ile bitişik);
  (ii) gerçek skip-reasonu provenance'a girdi — bkz. aşağıdaki düzeltme.
- **1S KİMLİK DÜZELTMESİ (§12.1):** süitteki 1S hiç `test_parity_6majors`
  değildi (etiket hatası, ledger'da düzeltildi). Gerçek 1S =
  `test_live_signal_runner.py::test_signal_runner_signal_event_payload_has_expected_fields`
  (L201): deterministik seed=1 sentetik veri → 0 sinyal → payload-şekil
  testi boşta atlıyor. Parity 7 node'u süitin 487P'si içinde zaten
  yeşil-koşuyor. Kapanış şartı her iki yorumda da sağlanmış durumda.

---

*Bu dosya §17-izinli memory-bank kaydıdır; executable code içermez.
İki insan-cümlesi (KARAR-1, KARAR-2) geldiğinde N2 #9 açılır.*
