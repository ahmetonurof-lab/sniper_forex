## D77-PRESERVE — İCRA (Cline, 20:31:18-19; boot-öncesi) + MANIFEST

Hakem-§3 batch'i **tamamıyla** koştu (6 dosya + `cp -p` ile orijinal-mtime-koruma). `state/D77_preserve/`:

| sha256 (ilk-16) | dosya | boyut | orijinal-mtime |
|---|---|---|---|
| `A5DC71ED1530F242` | `audit.jsonl` | 3812 B | 19:50:55 |
| `15635C0291AD55F9` | `audit_prev_2026-09-03b.jsonl` | 4376 B | 19:11:23 |
| `BF018F13A31FC701` | `crash_log.txt` | 920 B | 19:17:13 |
| `1CC5B1189966B3AC` | `EURUSD.json` | 895374 B | 19:50:55 |
| `FE5647CECD682A08` | `EURUSD_lifecycle.json` | 137 B | 19:50:55 |
| `9530AB41C636DE3E` | `k3_boot_stdout.log` | 2388 B | 19:50:48 |

**Sıra-doğru-çıktı:** preserve `20:31:18` → T0#8-lock `20:33:13`. **Boot `audit.jsonl`'ı 3812 B/12-satır → 1665 B/6-satıra ezdi; tek-SHUTDOWN-olayı preserve sayesinde kurtuldu.** BULGU-1 öngörüsü canlı-doğrulandı (4.-kanıt).
