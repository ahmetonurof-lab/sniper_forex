## D71 · SEP-1-T0-CRASH-ADLİ-KAZISI (yapı-ışınsı-kazı-standardı · 2026-09-03 15:30)

**Standart:** *tam-gün-nokta, arşiv-geri-aitir* — bir-boot'un kanıtı, o-boot'un dosyalarından geriye-doğru tam-zincir olarak okunur; eksik-halka "yok" değil **"kayıp ve lokasyonu-belirsiz"** olarak yazılır.

**Kazı-sonucu (bir artefakt, üç yorum-dönüşümü):**
| Katman | Bulgu |
|---|---|
| **Yorum-duygusu** | Sep 1 23:59:02'de bir boot **PermissionError ile crash etmiş** — `SHUTDOWN reason:"run_exception:PermissionError"`, `exit:1` |
| **Kurgu → gerçek** | "Sep 1 SAFE_START idi" yorumu → `S11 verdict=PROCEED` + `restored:false` + `warmup_bars:4339` → **Sep 1'de entry gate AÇIKTI**. Artık **audit-kanıtlı olgu**; D64'ün "ilk-gerçek-uygulama" çerçevesi **güçleniyor** |
| **Paradoks** | Kayıplara yol-açan **bozuk-mekanizma** (tmp-replace), **bu olayın tek-kopyasını yanlışlıkla korumuş** — overwrite yerine append olsaydı 6 olay kaybolmazdı, yetim de oluşmazdı |

**Milisaniye-eş-zamanlılığı (crash sırası):** `orchestrator.lock.tmp` `created_at 1788296341.9933178` (pid 16984) → `SHUTDOWN` `1788296342.0110803` → **Δ = 17.8 ms**. Crash, lock-alımının **ilk-icra-anında** olmuş.

**Çelişki → backlog:** `orchestrator.py:91` yorumu `orchestrator.lock.<pid>.tmp` der; yetim **PID'siz** `orchestrator.lock.tmp`. Yorum mekanizmayı doğru tarif etmiyor → **N2 #21 madde-6 (comment-hijyen)**.

**Arşiv-geri-atıf:** 6 olay → `state/audit_prev_2026-09-03.jsonl` **değil**, `state/audit.jsonl.tmp` **üzerinden** geri-kazanıldı; ikisi **farklı kanıt-sınıfı** (biri koruma-dikişi, biri adli-kurtarma).

---
