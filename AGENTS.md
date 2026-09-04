# AGENTS.md — SNIPER_FOREX Agent Operating Contract

> **Status:** Binding project protocol
> **Scope:** All AI agents, coding agents, reviewers, automation agents, and external assistants working on this repository
> **Authority:** This document defines the minimum operating discipline for changes to SNIPER_FOREX.
> **Prime directive:** **Never trade evidence for convenience.**

---

## 0. Mission
SNIPER_FOREX is a research and production trading system.

The repository is not merely source code. Its effective system of record is the combination of:

- canonical source code,
- tests,
- benchmark provenance,
- runtime/audit artifacts,
- memory-bank records,
- Git history,
- architectural decisions,
- review decisions,
- deployment constraints.

An agent that produces working code while silently violating this evidence chain has **not** completed its task.

The default engineering sequence is:

```
READ
→ CONTEXT
→ HYPOTHESIS
→ ISOLATE
→ TEST
→ IMPLEMENT
→ REGRESSION
→ AUDIT
→ COMMIT
→ PUSH
```

Do not skip directly from request → implementation.

---

# 1. CODEBASE-MEMORY MCP — MANDATORY

## 1.1 MUST use codebase-memory before meaningful work
For any non-trivial task involving architecture, runtime behaviour, state flow, research engines, recovery, deployment, testing strategy, or cross-file changes:

> **The agent MUST use the available codebase-memory MCP tools before implementation or architectural judgment.**

The agent must use codebase-memory to identify, where available:

- relevant files,
- callers and callees,
- state ownership,
- data flow,
- runtime path,
- test coverage,
- related implementations,
- canonical/frozen boundaries,
- historical/contextual relationships.

A shallow `grep` or file read is **not a substitute** for codebase-memory when the MCP is available.

## 1.2 Required reasoning pattern
For architecture-sensitive work, establish at minimum:

```
caller
→ callee
→ state
→ persistence
→ replay/recovery
→ tests
→ production entry point
```

Do not infer architecture from a single file.

## 1.3 MCP unavailable
If codebase-memory MCP is unavailable, inaccessible, broken, or returns an authorization/error state:

### Default rule: STOP architectural implementation.
The agent MUST report:

```
CODEBASE-MEMORY STATUS: UNAVAILABLE
Reason: <actual tool/error>
Impact: architectural context could not be fully verified
```

The agent MAY use direct repository inspection as a fallback **only when explicitly authorized by the user/reviewer to continue without MCP**.

When fallback inspection is authorized:

- clearly distinguish direct file evidence from MCP-derived context,
- do not claim "full codebase understanding",
- do not silently lower the confidence level,
- do not use absence of search results as proof of absence unless the search scope is demonstrably complete.

## 1.4 Project-local vs environment-level tools
The existence of a repository does not imply the existence of codebase-memory.

Agents must distinguish:

```
Repository contents
≠
Editor configuration
≠
Agent environment
≠
MCP server availability
```

Do not claim an MCP tool is "missing from the repo" merely because it is unavailable in the current agent environment.

---

# 2. CANONICAL SOURCE DISCIPLINE

## 2.1 Frozen/promoted engines
The following classes are protected:

- frozen benchmark engines,
- promoted canonical engines,
- production-critical protected runtime components,
- validated reference implementations.

An agent MUST NOT modify such code without explicit authorization.

For the research line, canonical engine changes must follow the established research protocol:

```
READ
→ isolate variable
→ benchmark
→ attribute
→ decide
→ document
→ promote only with explicit approval
```

## 2.2 Prefer existing mechanisms
When an existing mechanism already performs a required operation:

> **Reuse it before inventing a parallel implementation.**

Do not create duplicate sources of truth for:

- session state,
- bias,
- replay,
- recovery,
- risk calculations,
- broker state,
- lifecycle state,
- canonical strategy logic.

Example principle:

```
existing engine replay
      > new parallel CBDR calculator
```

A new mechanism requires explicit justification.

## 2.3 Research vs production
Research overlays and experiments must remain distinguishable from production code.

Do not silently promote experiment behaviour into canonical engines.

New behaviour should remain isolated in an appropriate experiment/overlay location until explicitly promoted.

---

# 3. EVIDENCE HIERARCHY
Claims must be proportional to evidence.

Preferred hierarchy:

```
1. Executed canonical production code path
2. Exact commit/blob inspection
3. Real production-path integration test
4. Controlled integration test
5. Unit test
6. Static/log/prose evidence
7. Hypothesis
```

Lower-level evidence MUST NOT be presented as if it were higher-level evidence.

Examples:

```
"StrategyRuntime can replay CBDR correctly"
```

does NOT prove:

```
"Orchestrator startup actually performs the replay."
```

Likewise:

```
"FakeOrch reproduces the branch"
```

does NOT prove:

```
"Orchestrator.run() executes that branch."
```

Whenever possible, tests must execute the **real code path being claimed**.

---

# 4. TEST DISCIPLINE

## 4.1 Test pass ≠ architectural correctness
Green tests are evidence, not absolution.

Before accepting a test as proof, ask:

- Does it execute the real implementation?
- Does it execute the production branch?
- Is it using a fake that duplicates the implementation?
- Does the assertion prove correctness or merely activity?
- Could a broken implementation still produce the asserted state?

## 4.2 Production-path coverage
If a production branch matters, at least one test should exercise that actual branch.

Do not replace:

```
real_object.run(...)
```

with:

```
FakeObject.run(...)
```

and call the production behaviour tested.

A fake may be retained for a contract/wiring test, but it must not be mistaken for production-path evidence.

## 4.3 Safety invariant vs test convenience
Never weaken a safety invariant solely to make a fixture pass.

Correct pattern:

```
production invariant preserved
+
fixture updated to construct valid production state
```

Incorrect pattern:

```
production safety relaxed
+
test passes
```

This rule applies especially to:

- ownership,
- lock files,
- stale detection,
- heartbeat,
- recovery,
- shutdown,
- signal handling,
- entry gating,
- reconciliation,
- risk limits.

## 4.4 Failure reporting
Failures MUST remain visible.

Never:

- delete a failing test merely to improve totals,
- weaken assertions without rationale,
- mark a failure "pre-existing" without evidence when provenance can be established,
- omit a suite from the report while describing results as "full suite,"
- replace a real branch with a fake branch and preserve the same claim.

When a failure is outside scope, report:

```
FAILURE
Scope: <inside/outside current task>
Status: <pre-existing / introduced / unknown>
Evidence: <how this conclusion was reached>
Action: <fix / pin / investigate>
```

---

# 5. REVIEWER / REFEREE AUTHORITY

## 5.1 RED = VETO

> **Reviewer RED is a veto.**

If an independent reviewer rejects a proposed implementation:

- do not silently bypass it,
- do not modify the implementation to make the objection disappear,
- do not reinterpret the veto as informational.

Instead:

```
RED
→ understand objection
→ propose new design/clarification
→ obtain explicit acceptance
→ implement
```

If the agent believes the reviewer is wrong, it may explain the disagreement, but must not self-authorize the rejected implementation.

## 5.2 Independent review must remain independent
When requesting a second opinion:

- provide the real context,
- state the actual problem,
- do not spoon-feed the desired architecture,
- do not phrase the prompt so narrowly that the reviewer can only validate the proposed solution.

The purpose of an independent review is to expose blind spots.

---

# 6. STATE, RECOVERY, REPLAY, AND TIME
Stateful runtime changes require explicit reasoning about:

- startup,
- restart,
- shutdown,
- downtime,
- partial state,
- stale state,
- replay,
- recovery,
- broker truth,
- timestamps,
- session boundaries.

## 6.1 Restart correctness
A restart path must answer:

```
What was persisted?
What was not persisted?
What happened while the process was down?
What is reconstructed from market history?
What comes from journal/lifecycle state?
```

Do not assume that "state exists" means "state is current."

## 6.2 Single source of truth
Prefer deterministic reconstruction from canonical market history when that is the established architecture.

Persisted state must not create a second conflicting source of truth unless explicitly designed and reviewed.

## 6.3 Timezone discipline
Timestamp conversions must use a single canonical convention.

For naive timestamps, the project convention must be explicit.

Do not mix:

```
stdlib naive datetime.timestamp()
```

with:

```
pandas naive Timestamp.timestamp()
```

without explicitly controlling timezone interpretation.

Timezone/epoch changes require regression tests.

## 6.4 Session boundaries
For session-driven systems such as CBDR:

```
data availability
≠
state reconstruction
≠
bias establishment
```

An agent must verify the complete chain.

Example:

```
M1 history
→ 15m bars
→ warmup
→ replay
→ SessionManager.update()
→ CBDR/session state
→ bias
```

It is not sufficient to prove that M1 data was fetched.

---

# 7. RUNTIME SAFETY
Production/runtime modifications MUST preserve fail-safe semantics.

Particular attention is required for:

- lock ownership,
- heartbeat,
- stale-owner detection,
- SIGINT/SIGTERM,
- shutdown,
- safe mode,
- reconciliation,
- broker data freshness,
- entry gates,
- SL/TP state,
- runtime exceptions.

## 7.1 Kill vs ownership
Human-requested termination and ownership-loss are distinct conditions.

Do not change their exit semantics merely to satisfy a test.

## 7.2 Safe mode
Safe mode must distinguish:

```
entry permission
vs
state advancement
vs
position management
```

Disabling entries must not automatically imply that all deterministic runtime state construction should stop.

Any intentional divergence requires explicit architectural decision and test coverage.

Safe mode **persists across restart**. A persisted safe-mode file forces a
degraded boot even when all fresh checks pass:

```
never silent resume
clearing safe mode = explicit operator action
```

A clean startup must not launder a persisted safe-mode state.

## 7.3 Recovery
Recovery must be deterministic.

If a stale/partial restore is invalidated:

```
stale runtime
→ fresh runtime
→ complete reconstruction
```

Do not leave stale runtime state mixed with rebuilt state.

## 7.4 Interruptible waits
Long waits (sleep, retry backoff, poll loops) MUST be interruptible by
shutdown signals (SIGINT/SIGTERM; PEP 475 semantics).

The maximum single wait chunk MUST be smaller than the stale-ownership
window:

```
max_wait_chunk < LOCK_STALE_SEC
```

Established arithmetic invariant for this repository:

```
backoff_max (300s) < lock stale window (900s)
```

An uninterruptible long sleep converts a clean shutdown request into a
watchdog-visible hang and risks orphaning lock ownership.

---

# 8. RESEARCH INTEGRITY

## 8.1 Canonical benchmark provenance
Every benchmark result must be traceable to:

- engine/version,
- dataset,
- configuration,
- date range,
- symbol universe,
- execution semantics,
- relevant overlay,
- exact commit/tag where applicable.

Do not attach "canonical" or "known-good" labels without a reproducible provenance chain.

## 8.2 Red canonical tests
A red canonical test is not something to hide under "pre-existing."

Determine whether it is:

```
engine bug
test bug
environment problem
historical drift
unknown
```

Use differential evidence where possible.

For promoted research engines, causality/parity failures are especially important.

## 8.3 Differential diagnosis
When a failure may originate from an overlay:

```
v1.0 baseline
vs
v1.1/promoted variant
```

must be compared whenever practical.

Use Git history/blame when the expected behaviour's provenance matters.

## 8.4 Tagging
Do not tag a canonical research state as validated while mandatory canonical tests are unresolved.

A broken canonical baseline must remain visibly broken.

---

# 9. GIT / PROVENANCE POLICY

## 9.1 Commit before push
Every commit must have a defined scope.

Before commit:

```
git status
git diff
git diff --cached
```

must be inspected.

## 9.2 Push requires written authorization

> **Every push requires explicit written authorization.**

No silent pushes.

No implicit "you probably meant push."

Before push, report:

- commit SHA(s),
- exact commit set,
- scope,
- intended remote branch,
- validation result.

After push:

```
git log --oneline origin/main..HEAD
git ls-remote origin main
git rev-parse HEAD
git status
```

must be used to verify synchronization.

## 9.3 Push provenance
Each push must be recorded in the project ledger/memory-bank with:

```
who
what
when
which commit(s)
which remote
verification result
```

If historical provenance is unclear, say so.

## 9.4 No amend across reviewed boundaries
Do not silently amend a reviewed commit.

A newly reviewed design correction should normally become a new explicit commit unless the reviewer explicitly authorizes another strategy.

## 9.5 Authorization is bound to a hash set
Push authorization covers the **exact commit set**, identified by commit
hash — never by description alone.

- The approved set is recorded in the ledger with commit hashes.
- Set growth, removal, or amendment of any member voids the
  authorization: **set change = re-authorization.**
- A commit that is not in the approved set MUST NOT ride along in the
  push. If it is an unavoidable ancestor of an approved commit, the full
  resulting push set must be re-confirmed before pushing.

---

# 10. INDEX / AUTOMATION HYGIENE
Repository index-generation tooling is part of the build/provenance environment.

## 10.1 Watchers
Background watchers MUST NOT silently mutate canonical files during a commit/review operation.

If an automated watcher modifies `index.json` or another provenance-critical file:

```
stop watcher
→ restore intended state
→ inspect diff
→ regenerate intentionally
→ re-run validation
```

Do not accept silent background mutations.

## 10.2 Index generation
When source line changes affect line-anchored index data:

```
format/change
→ test
→ index_builder --full
→ inspect index
→ stage
→ commit
```

Index generation must be intentional and attributable.

## 10.3 Commit-time mutation
Prefer:

```
manual format/check
→ stage
→ commit hook = validation
```

over hooks that unpredictably rewrite staged content during commit.

A commit must contain the blob that was actually validated.

---

# 11. BEHAVIOUR-NEUTRAL CHANGES
For formatting-only or other claimed behaviour-neutral work:

Required evidence:

```
claim
→ regression suite
→ semantic/AST verification when practical
```

A behaviour-neutral claim is stronger when backed by:

- syntax/format checks,
- test results,
- AST/body comparison,
- normalized import comparison.

Recommended hierarchy:

```
prose claim < test run < AST/semantic comparison
```

Do not call a large formatting sweep "behaviour-neutral" solely because tests passed when a stronger deterministic comparison is practical.

---

# 12. MEMORY-BANK / DECISION LEDGER
Important work MUST be recorded in the memory-bank.

At minimum capture:

```
What was tested?
Which engine/code?
Which dataset/config?
What variable was isolated?
What happened?
What was the decision?
What remains open?
What is the next test?
```

Record:

- major discoveries,
- blockers,
- reviewer decisions,
- rejected approaches,
- provenance incidents,
- deployment changes,
- important test failures,
- accepted technical debt.

## 12.1 Never rewrite history silently
If a previous conclusion changes:

```
old conclusion
→ why it was wrong
→ new evidence
→ revised conclusion
```

must remain visible.

Self-correction is a project asset, not an embarrassment.

---

# 13. TEST COUNT AND REPORTING DISCIPLINE
Numbers are evidence.

Whenever a suite count is reported, it must be reproducible.

Use per-file counts where practical:

```
pytest --collect-only -q
```

Avoid contradictory statements such as:

```
14 tests
```

when 13 are actually present.

If a suite excludes files, state the exact scope.

If "full suite" really means:

```
tests/
```

say:

```
full suite within tests/
```

Do not silently omit known failures or collection errors.

## 13.5 Delivery reconciliation (conversation-boundary transfers)
Large content (files, diffs, test suites) crossing an agent boundary MUST be:

- split with explicit headers: `# FILE` / `# PART` / `# LINES` / `# EOF-PARTn`
- receiver-confirmed: line count + last symbol (`def` / `class`) echoed back
- re-requested on mismatch — **never summarized from memory on partial receipt**

Mismatches are process incidents, not noise. Log them.

This is the communication-layer counterpart of §21's rule against relying
on private conversation history: a transfer that cannot be verified
arrived is a transfer that did not arrive.

---

# 14. AGENT PREFLIGHT CHECKLIST
Before implementing a meaningful task, the agent MUST answer internally or in the work log:

### Context

- Have I used codebase-memory MCP?
- Do I know the canonical files?
- Do I know the production caller → callee path?
- Do I know which tests exercise that path?

### Isolation

- What is the single variable being changed?
- What must remain untouched?
- Is there an existing mechanism I should reuse?

### Safety

- Could this affect locking, recovery, timestamps, reconciliation, sizing, or entry gating?
- Am I weakening an invariant to make a test pass?

### Evidence

- Am I testing the real code path?
- Does my assertion prove correctness or merely activity?
- Can a broken implementation still pass my test?

### Provenance

- What files will change?
- Are any generated files involved?
- Could a watcher/tool mutate them?
- What commit scope will result?

---

# 15. COMMIT CHECKLIST
Before creating a commit:

```
[ ] codebase-memory context obtained where required
[ ] intended files identified
[ ] frozen/canonical boundaries respected
[ ] tests written/updated
[ ] relevant regression suite passed
[ ] failures explicitly documented
[ ] generated/index files intentionally regenerated
[ ] background watcher interference ruled out
[ ] ruff/formatting performed before staging where required
[ ] git diff reviewed
[ ] git diff --cached reviewed
[ ] commit scope matches task
```

No commit if these questions cannot be answered.

---

# 16. PUSH CHECKLIST
Push is a separate authorization boundary.

Before push:

```
[ ] explicit written authorization exists
[ ] commit SHA(s) listed
[ ] commit scope reviewed
[ ] remote target confirmed
[ ] required regression completed
[ ] provenance entry prepared
```

After push:

```
[ ] origin/main..HEAD is empty
[ ] ls-remote matches expected HEAD
[ ] local HEAD recorded
[ ] working tree status recorded
[ ] memory-bank/ledger updated
```

---

# 17. SOAK TREE FREEZE
Once operational soak begins:

```
src/
tests/
index.json
```

are considered frozen at the tested HEAD.

No mutation during soak.

Allowed operational changes:

- `state/`
- runtime logs
- audit artifacts
- explicitly ignored soak artifacts
- memory-bank/chore records that do not alter executable code

If code changes are required during soak:

```
STOP SOAK
→ record event
→ change code
→ run full relevant suite
→ commit
→ explicit push authorization
→ push
→ verify remote
→ restart soak
```

No shortcuts.

The purpose is to ensure that a soak result always corresponds to a known, tested code version.

---

# 18. RUNTIME / SOAK OBSERVABILITY
Operational soak reports must prioritize:

```
startup/shutdown symmetry
bar continuity
15m grid integrity
gate transition distribution
error ladder activations
recovery timing
reconciliation anomalies
audit continuity
restart continuity
state reconstruction correctness
```

For startup/replay-heavy systems also measure:

```
replay bars
startup duration
rebuild duration
state end-state
CBDR/session establishment time
```

A soak is not successful merely because the process remains alive.

### Aşama-5: Crash / Fix-Bildirim Üçlü Kanal Zorunluluğu

Her SOAK-CRASH / fatal-error / fix-commit, **ÜÇ kanala AYNI ANDA** bildirilir:

| # | Kanal       | Rol                                          |
|---|-------------|----------------------------------------------|
| 1 | Hakem       | Arbitraj — karar yetkisi                      |
| 2 | Sentezleyici | Luna — sentez-girdisi olarak                |
| 3 | Owner       | Forexçi — operasyonel-bilgi olarak            |

**Tek-kanal bildirim = eksik-bildirim sayılır.**

> **FORMÜL:** "CRASH BİLDİRİMİ TEK KANALA YÖNLENDİRMEYİN."
>
> "Crash yemeyen production sistemi diye bir şey yok;
> CRASH'İ GİZLİ KIRILAN production sistemi vardır."

---

# 19. COMMON FAILURE MODES TO AVOID
The following patterns are explicitly prohibited:

### Fake-production-test
Reimplementing the production branch inside a fake and treating it as production evidence.

### Test-convenience safety downgrade
Relaxing a lock/ownership/safety invariant to satisfy an incomplete fixture.

### Silent fallback
Using a test seam or alternate path in production without making it visible.

### Hidden red
Dropping, skipping, renaming, filtering, or omitting a failure so that reported totals look green.

### Unproven "pre-existing"
Calling a failure pre-existing without differential/history evidence when such evidence is available.

### Duplicate source of truth
Adding a second implementation of state that should be reconstructed by the canonical engine.

### Background mutation
Allowing automation to modify tracked/provenance-critical files during review or commit.

### Silent push
Pushing without explicit authorization.

### CWD-dependent persistence
Assuming relative state paths are safe without deployment/runtime contract validation.

### Stale restore
Restoring state simply because a file exists, without checking whether the state actually covers the relevant market/session timeline.

---

# 20. DECISION RULE
When uncertain, prefer:

```
LESS CODE
+
MORE EVIDENCE
+
ONE SOURCE OF TRUTH
+
EXPLICIT PROVENANCE
```

over:

```
MORE CODE
+
ASSUMPTIONS
+
HIDDEN FALLBACKS
+
GREEN-LOOKING TESTS
```

---

# 21. FINAL AGENT CONTRACT
By working on this repository, an agent is expected to follow these principles:

> **Understand before editing.**

> **Use codebase-memory MCP when available; do not pretend a partial tool environment is full repository knowledge.**

> **Prove the production path, not a copy of it.**

> **Do not weaken safety invariants for test convenience.**

> **A reviewer RED is a veto until explicitly resolved.**

> **Failures remain visible.**

> **Canonical research remains reproducible.**

> **Every important decision leaves a memory-bank trail.**

> **Every commit has a declared scope.**

> **Every push requires explicit authorization and post-push verification.**

> **During soak, tested code is frozen.**

> **The repository must remain understandable to the next agent without relying on private conversation history.**

The goal is not merely to produce code that works.

The goal is to preserve a trading system whose:

```
CODE
+ TESTS
+ RESEARCH PROVENANCE
+ RUNTIME STATE
+ REVIEW HISTORY
+ GIT HISTORY
+ OPERATIONAL EVIDENCE
```

remain mutually trustworthy.

**When evidence and intuition disagree, stop and investigate.**
