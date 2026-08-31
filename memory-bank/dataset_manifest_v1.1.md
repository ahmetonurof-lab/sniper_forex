# DATASET MANIFEST — C v1.1 BENCHMARK PROVENANCE (fixation 2026-08-31)

> **Purpose (referee order, tahkim paketi madde 6 — "DATASET-FIKSASYONU ŞİMDİ"):**
> The benchmark dataset is UNVERSIONED in git (`?? data/`). Until now, the
> only provenance proof for "the benchmark ran on this exact data" was file
> mtime (Aug 22–23 < promotion Aug 28) — a weak, forgeable proof. This
> manifest replaces the mtime proof with a per-file SHA256 bit-proof.
> Any future benchmark re-run MUST be verified against this list BEFORE the
> run is considered comparable.
>
> **Binding scope:** the 6×15m feather files are read directly by
> `experiment/main_research_c_v1_1.py` (via `DATA_DIR`/feather). The 5m/1m
> feathers and the RAW CSVs are the upstream pipeline inputs; they are
> hashed too so the full chain is frozen, not just the leaf.

## Engine-consumed feather files (`data/icmarket_feather/`)

| File | SHA256 | Rows |
|---|---|---|
| AUDUSD_15m.feather | `ad332253a6aaa5afd4e09d77901c153246815413318ec7a42619a50c5bd23fdd` | 65732 |
| AUDUSD_1m.feather  | `990567a1bc2b4b630e02439956be60c218c5e5398ce253287b12f36f513c13ad` | 977147 |
| AUDUSD_5m.feather  | `6bfe92571aa9afaede97e02d88dde5e7ae96e16f8a07f76cb629314f016911dc` | 196130 |
| EURUSD_15m.feather | `42fcbb72bfc2f103f1801782067da26507c19978a81a8d3f65b5d4c655e58025` | 65740 |
| EURUSD_1m.feather  | `628914e5a6df416e44062f24fd22dd269fd7ea53e18ac4fbcab9f405e9ea71ae` | 979793 |
| EURUSD_5m.feather  | `e214cc8210749d958cfcda9e28ad14307d25df9e103d0cb57456b9711afd6fa4` | 196574 |
| GBPJPY_15m.feather | `99fb53137320110ed4968374a739b038d32424b1bef0b28d2b28e781af5206c3` | 65741 |
| GBPJPY_1m.feather  | `253110e7a18f1d48387710caf2d4542d993a30138389c1e700632320a417a143` | 983232 |
| GBPJPY_5m.feather  | `9572ffa3ca77a2e16bb32055567e6197a8be16343f5a4611b8b074ab35270f04` | 196877 |
| GBPUSD_15m.feather | `89d8efccedd2f351f54f529148a2d97f9d15f999887d0161386b9889099dab67` | 65730 |
| GBPUSD_1m.feather  | `e3e378325255f6f4e03091c760b56b297987c575a236749bbf8617e7c48916c6` | 979994 |
| GBPUSD_5m.feather  | `a451e520001f5105056ccaf25e0e261626dc63d1b998e632782ca3a1907c5c40` | 196371 |
| USDCAD_15m.feather | `8adbb32109504765a48a602ccfeed7c9adf29563d61f96599afe4d0748222a45` | 65716 |
| USDCAD_1m.feather  | `09a092e7724ae8ea591e0818741a5c545d55e266cf72bee2ac9b41f08bd68d7b` | 977080 |
| USDCAD_5m.feather  | `3e41d705f4c730304061cfe340dc59f5c972267e84b7f47d36b52e3f6e05d3f6` | 195932 |
| USDJPY_15m.feather | `3ee48eb627c3529045e6f28735d2c85558d8a675922768c068366a0ce9346845` | 65734 |
| USDJPY_1m.feather  | `6b99692578e7d9cb0b684a6b0037aeb43e4f1293a967a0bdf8f35cd940440bc9` | 979389 |
| USDJPY_5m.feather  | `2c941da24635bb3e5e460e0e8ca1b8afb9fdd495f9c07cf080d9a924b1c20481` | 196280 |

## Upstream RAW minute CSVs (`data/icmarket_raw/`)

| File | SHA256 | Bytes |
|---|---|---|
| AUDUSD_Minute_2024_2026_RAW.csv  | `8ddb08b1df4334f2bb2a32ab72d128402effff266e78e3e5d68bbe4ccdcd78e4` | 54387794 |
| EURUSD_Minute_2024_2026_RAW.csv  | `f326d79ac0b5d3a36eed8506bfc6bcc457bb53ebed59ed95a14cae9a9e9d650a` | 54593302 |
| GBPJPY_Minute_2024_2026_RAW.csv  | `f6f71545514940f449c135981321885db9c1a3cf8f5d6232e857b87c0b13f9f6` | 55338547 |
| GBPUSD_Minute_2024_2026_RAW.csv  | `2f0f49154a58e6ad5119cbf2cd5fcd8c42a17b7b7dcca6a32dda20dcbc907f9e` | 54741638 |
| USDCAD_Minute_2024_2026_RAW.csv  | `c3a50e3b44f619ab6232799a47fde2d839854d4aed696f3805ffe131250a2fcf` | 54452275 |
| USDJPY_Minute_2024_2026_RAW.csv  | `7b542f34687ac92a397c003d08dc32eeff293078371c24c2c847c3e2482fa467` | 54817370 |

## Verification protocol

```
before any canonical C v1.1 benchmark re-run:
    sha256sum data/icmarket_feather/*.feather data/icmarket_raw/*.csv
    → compare line-by-line against this manifest
    → ANY mismatch = dataset drift = benchmark NOT comparable = STOP
```

Hash extraction commands (reproducible):

```
sha256sum data/icmarket_feather/*.feather
sha256sum data/icmarket_raw/*_Minute_2024_2026_RAW.csv
pyarrow.feather.read_table(path) → len()  # row counts above
```

## Provenance notes

- Feather mtimes: 2026-08-22/23 — all predate the C v1.1 promotion
  (`0899b38`, 2026-08-28) and both silent semantic changes
  (`797d946`, `409fc17`). Consistent with, but weaker than, this hash proof.
- `data/` is git-untracked (`?? data/`): the hashes in this file are the
  ONLY bit-level record of the benchmark dataset. This is the §8.1 gap this
  fixation closes.
- `data/icmarket_raw/` also contains 3 pipeline scripts
  (`audit_icmarket_raw.py`, `convert_icmarket_utc_to_server.py`,
  `cross_check_tz.py`, mtime 2026-08-30). These are RAW→feather conversion
  tooling; the conversion scripts as-of promotion are themselves in git
  history, so the CSV→feather chain is recoverable from repo + this manifest.
  (Disclosed: script mtimes postdate the feathers — they were used for
  later audits, not silently for the benchmark data.)
- The parity probe (gate ③) that triggered the (b) arbitration consumed
  EXACTLY these feather bytes (worktrees were given copies; copies verified
  identical by hash at probe time).
