# Active Context — Research Control Panel

> Single source of truth for the MaxDD research line.
> Last updated: 2026-08-27.
> Canonical engines (`main_research_c_v1_0.py`, `main_research_d_v1_0.py`) are NEVER
> edited for experiments. New behaviour lives in `experiment/exp_maxdd_*.py`
> overlays until it is promoted to a new engine version.

---

## CURRENT STATE

### Main Research Engines (frozen baselines)

| Engine | File | Version | Status |
|---|---|---|---|
| C | `experiment/main_research_c_v1_0.py` | **v1.0** — C2 EQ | FROZEN baseline |
| D | `experiment/main_research_d_v1_0.py` | **v1.0** — PURE D EQ | FROZEN baseline |

> Old versions are never deleted. A new version (v1.x) is only created
> when a verified change is promoted from an experiment overlay to the
> research engine.

### Confirmed C (C2) Results — 6 majors, 2.7Y, 15m

| Variant | Trades | WR% | TotalR | AvgR | PF | MaxDD(R) | MaxDD(%) |
|---|---:|---:|---:|---:|---:|---:|---:|
| C1 Displacement (tested) | — | — | weaker than C2 | — | — | — | — |
| **C2 baseline (C v1.0)** | 2302 | 69.37 | +2875.00 | +1.2489 | 5.08 | 8.00 | 2.73 |
| C2 + DD Risk Scaling (overlay) | 2302 | 69.37 | +2827.55 | +1.2283 | 5.13 | 8.00 | **1.85** |

- DD Risk Scaling is a **post-hoc overlay** (`experiment/exp_maxdd_C_dd_risk_scaling.py`).
  It has NOT been promoted to **C v1.1** — promotion requires a separate
  decision after standalone validation.
- C2 baseline numbers are the authoritative reference for every C-family
  comparison. `main_research_c_v1_0.py` git diff is empty across all experiments.

### Confirmed D (PURE D) Results — 6 majors, 2.7Y, 15m

| Variant | Trades | WR% | TotalR | AvgR | PF | MaxDD(R) | MaxDD(%) |
|---|---:|---:|---:|---:|---:|---:|---:|
| **D v1.0 baseline** | 2847 | 66.1 | +2949.05 | +1.0358 | 4.05 | 7.36 | 2.76 |

- Artifact: `results/benchmark/PURE_D_FVG_ORIGIN_EQ_benchmark.json`
- KNOWN-GOOD FROZEN BENCHMARK. Promotion rule: a new variant must beat
  this in a head-to-head comparison to supersede it.

### Rejected Experiments (C v1.0 line)

| ID | Experiment | Decision | Reason |
|---|---|---|---|
| A | Concurrent Exposure Cap = 3 | **REJECT** | non-binding (cap never reached); 0 blocked; no PnL/MaxDD change |
| B | 3-Loss / 12-bar Circuit Breaker | **REJECT** | non-binding (mechanism verified; 105 triggers but 0 blocked — pause window never overlaps a real entry); 0 PnL/MaxDD change |

Both: mechanically verified, file = `experiment/exp_maxdd_*.py`. See
`memory-bank/progress.md` for full per-experiment log.

---

## ROADMAP / TODO

### Phase 1 — C v1.0 MaxDD Research (single-variable overlays)

- [x] **A** — Concurrent Exposure Cap (REJECT / non-binding)
- [x] **B** — 3-Loss / 12-bar Circuit Breaker (REJECT / non-binding)
- [x] **C** — DD-Based Risk Scaling (MaxDD% 2.73 → 1.85; awaiting promotion decision)
- [ ] **D** — Open Exposure / Total-Risk Cap ← **NEXT**
- [ ] **E** — Time-of-Day Quality Filter
- [ ] **Combination tests** — only after all single-variable experiments resolve

### Phase 2 — D v1.0 MaxDD Research (mirror of Phase 1)

- [ ] A — Concurrent Exposure Cap
- [ ] B — 3-Loss / 12-bar Circuit Breaker
- [ ] C — DD-Based Risk Scaling
- [ ] D — Open Exposure / Total-Risk Cap
- [ ] E — Time-of-Day Quality Filter

### Phase 3 — Champion Selection

- [ ] Score C and D variants on a single objective score (MaxDD-first, then
      PF / AvgR / WR / TotalR preservation)
- [ ] Decide champion
- [ ] OOS validation if needed
- [ ] Promote winning engine to new version (C v1.x or D v1.x) — old
      version preserved, new version created

---

## NEXT ACTION

**NEXT = Phase 1 / D — C v1.0 üzerinde Open Exposure / Total-Risk Cap deneyi.**

- Engine: C v1.0 (`experiment/main_research_c_v1_0.py`, UNTOUCHED).
- Isolated variable: cap on total open R exposure across the portfolio
  (or per-symbol). TBD in experiment design.
- Method: post-hoc overlay on the C2 baseline trade stream, per-symbol or
  portfolio, NO lookahead. Accept/reject entries based on current open
  exposure.
- Output: `results/research/expD_*_summary.json`, `expD_*_trades.json`.
- File: `experiment/exp_maxdd_D_open_exposure.py` (new).
- Compare: C2 baseline vs C2 + cap. Report trades, WR, TotalR, PF, MaxDD(R),
  MaxDD(%), blocked count, per-symbol breakdown.
- Decision criteria: REJECT if non-binding (cap never reached);
  KEEP/PROMOTE if it reduces MaxDD(R) or MaxDD(%) without unacceptable PnL cost.

When the experiment is done, in THIS file:
- mark `[ ] D` → `[x] D` and add the result row to the experiment log
  below;
- update NEXT ACTION to the next pending item;
- update FILE MAP if a new file was created.

---

## EXPERIMENT LOG (this research line)

| ID | Status | Decision | Key result | File |
|---|---|---|---|---|
| A | done | REJECT (non-binding) | 0 blocked; baseline unchanged | `experiment/exp_maxdd_A_concurrent_cap.py` |
| B | done | REJECT (non-binding) | 105 triggers, 0 blocked; mechanically verified | `experiment/exp_maxdd_B_streak_breaker.py` |
| C | done | MaxDD% 1.85 (pending promotion) | MaxDD% 2.73→1.85, TotalR −1.65% | `experiment/exp_maxdd_C_dd_risk_scaling.py` |
| D | pending | — | — | (new file) |

Full per-experiment detail (what tested, engine, dataset, isolated
variable, result, decision, next test) lives in `memory-bank/progress.md`.

---

## FILE MAP (active research files)

```text
# Frozen baselines (NEVER edited for experiments)
experiment/main_research_c_v1_0.py        = C v1.0  / C2 EQ baseline
experiment/main_research_d_v1_0.py        = D v1.0  / PURE D EQ baseline

# C v1.0 MaxDD experiment overlays (Phase 1)
experiment/exp_maxdd_A_concurrent_cap.py
experiment/exp_maxdd_B_streak_breaker.py
experiment/exp_maxdd_C_dd_risk_scaling.py
# experiment/exp_maxdd_D_open_exposure.py        (NEXT — to be created)

# B replay audit
experiment/audit_expB_replay.py      = Experiment B mechanism audit
```

New experiment files are appended to the overlay list as they are created.
Baseline files are never modified by experiments.

---

## WORKING RULE (enforced every turn)

When an experiment is finished, in the SAME turn, update memory-bank:

1. `memory-bank/activeContext.md` — mark todo `[ ]` → `[x]`, append result
   row to the experiment log table, set NEXT ACTION to the next pending
   item, update FILE MAP if a new file was created.
2. `memory-bank/progress.md` — append a per-experiment entry with the
   required fields:
   - what was tested
   - which engine (C v1.0 / D v1.0)
   - which dataset (6 majors, 2.7Y, 15m, full)
   - isolated variable (one)
   - result (numbers)
   - decision (KEEP / REJECT / INCONCLUSIVE / pending)
   - next test

Canonical engines are NEVER edited for experiments. Verified promotions
create a new version (C v1.x, D v1.x); the old version is preserved.

---

## Replay causality note (carry-over)

The Exp B replay sorts EXIT-before-ENTRY at the same bar. For trades with
`entry_bar == exit_bar` (hold_bars=0, same-bar fill+exit), the EXIT is
processed before that trade's ENTRY, so `if t.trade_id in accepted` is
False and the EXIT is excluded from the loss streak. This is a **conscious
causality rule** (a trade's result cannot be used to make decisions on the
same bar it opened), not a bug. A pure-EXIT walk on the same data gives
42 triggers; the function's accepted-aware walk gives 105 (authoritative).
This note applies to any future replay that reuses the same event-stream
pattern.
