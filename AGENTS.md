# SNIPER_FOREX — Agent Instructions

## 1. CODEBASE-MEMORY FIRST — MANDATORY
Before inspecting, modifying, or creating anything in the repository, use the available **codebase-memory tools** to understand the relevant codebase context.

### Knowledge Graph Tools (codebase-memory-mcp)
**Always prefer MCP graph tools over grep/glob/file-search for code discovery.**

1. `search_graph` — find functions, classes, routes, variables by pattern
2. `trace_path` — trace who calls a function or what it calls
3. `get_code_snippet` — read specific function/class source code
4. `query_graph` — run Cypher queries for complex patterns
5. `get_architecture` — high-level project summary

**Fallback to grep/glob only when:**
- Searching for string literals, error messages, config values
- Searching non-code files (Dockerfiles, shell scripts, configs)
- When MCP tools return insufficient results

### Examples
- Find a handler: `search_graph(name_pattern=".*OrderHandler.*")`
- Who calls it: `trace_path(function_name="OrderHandler", direction="inbound")`
- Read source: `get_code_snippet(qualified_name="pkg/orders.OrderHandler")`

Keep exploration **targeted and minimal**. Do not load large amounts of unrelated code into context.

---

## 2. READ THE PROJECT BEFORE ACTING
Never assume the current implementation from the task description alone.

Before making changes:

1. Inspect the relevant codebase structure.
2. Read the relevant `memory-bank` checkpoint.
3. Inspect the current implementation of the files/functions involved.
4. Check the latest relevant experiment, benchmark, or decision.
5. Determine whether the requested task is already implemented, partially implemented, or obsolete.
Do not begin modifying files until the current state is understood.

---

## 3. PRESERVE THE RESEARCH SYSTEM
This repository is an active research environment.

Treat existing **KNOWN-GOOD / frozen benchmarks** as regression references. Do not modify them unless explicitly instructed.

Research changes must follow:

**READ → HYPOTHESIS → ISOLATE → BENCHMARK → ATTRIBUTE → DECIDE → DOCUMENT**

Prefer existing scripts and infrastructure over creating new scripts.

Do not create duplicate experiments, redundant utilities, or unnecessary files.

---

## 4. ONE VARIABLE AT A TIME
When running a strategy experiment, isolate the intended variable.

Do not silently change:

- entry logic
- exit logic
- FVG logic
- sweep logic
- EQ logic
- filters
- risk logic
- data source
- timeframe
- execution assumptions
unless that change is explicitly part of the experiment.

If another problem is discovered, report it separately rather than silently fixing it inside the experiment.

---

## 5. DISTINGUISH STRATEGY CHANGES FROM MAINTENANCE
Formatting, linting, typing, performance, logging, and repository maintenance are not automatically strategy changes.

However, do not use "lint/cleanup" as a reason to alter trading behavior.

For any non-trivial code modification, verify that strategy behavior remains unchanged unless the task explicitly calls for a strategy change.

---

## 6. DATA AND BENCHMARK INTEGRITY
Always verify that the experiment uses the intended:

- symbols
- date window
- timeframe
- dataset
- benchmark implementation
Do not infer these from filenames alone.

Before comparing results, confirm that both variants use the same population and experimental conditions except for the isolated variable.

A different data window, loader, timeframe, or execution path can invalidate a comparison.

---

## 7. RESULTS MUST BE ATTRIBUTABLE
Do not judge an experiment only from aggregate PnL.

When relevant, compare:

- trade count
- win rate
- AvgR
- TotalR
- PF
- MaxDD
- MaxDD%
- common trades
- added trades
- removed trades
Prefer trade-level attribution when two variants produce different trade populations.

---

## 8. MAXDD / CAPITAL SURVIVABILITY
The primary research objective is **robustness and drawdown reduction**, not raw PnL maximization.

Do not optimize for higher PnL at the expense of materially worse drawdown without explicitly documenting the trade-off.

Treat MaxDD and capital survivability as first-class metrics.

---

## 9. MEMORY-BANK IS PART OF THE PROJECT STATE
The `memory-bank` is the persistent research context.

After a meaningful experiment, implementation milestone, or decision:

- update the relevant memory-bank checkpoint,
- record what changed,
- record the experiment/result,
- record the decision,
- record the next research state.
Do not claim that memory-bank is updated until the files are actually modified and verified.

When committing work, ensure required memory-bank changes are included in the commit.

---

## 10. GIT DISCIPLINE
Before modifying files:

```
git status
```
Before committing:

```
git diff
git diff --cached
git status
```
Verify that only intended files are staged.

**Index sync rule (mandatory before EVERY commit):**

`index.json` is the repository's function/class index used by external MCP
servers (e.g. codebase-memory) to navigate the codebase. If a commit adds
or modifies code, the index must reflect the new state BEFORE the commit.
Therefore, before every `git add` / `git commit`:

```
python tools/code-index-system/index_builder.py --full
```

This regenerates `index.json` at the repo root. If the diff shows a change
to `index.json`, stage and include it in the same commit. The index MUST
be committed atomically with the code change — never in a separate
"chore: update code index" follow-up, never left as a working-tree-only
artifact.

After committing:

- verify the commit contents,
- verify the commit hash,
- **push only at explicit checkpoints** (see "Push discipline" below),
  never automatically after every commit,
- verify the final repository state.
Never assume a file was committed merely because it was modified.

Never claim a push succeeded without verifying it.

**Push discipline (when to push):**

- DO NOT push automatically after every commit. Local commits accumulate.
- Push only at explicit **checkpoints**, which are:
  - end of a numbered phase (PHASE 1..11) when the user confirms PASS,
  - any time the user explicitly says "push",
  - any time MCP-side consumption of `index.json` is required (the index
    must be on the remote for external agents to see it).
- Before every push, the working tree must include a fresh `index.json`.
  If any code has changed since the last index regeneration, run
  `index_builder.py --full` first and commit the regenerated index before
  pushing. The pushed remote HEAD MUST contain a `index.json` that
  reflects the code at that commit — never a stale index.
- Before running `git push`, ALWAYS confirm with the user. Default
  behavior is "commit locally, do not push".
- After `git push`, verify the remote hash matches the local hash:
  ```
  git log --oneline origin/main..HEAD   # must be empty
  git ls-remote origin main             # must show the new HEAD
  ```

---

## 11. DO NOT OVER-ENGINEER
Prefer the smallest correct change.

Do not:

- rewrite working code unnecessarily,
- introduce new abstractions without need,
- duplicate existing functionality,
- create files merely to solve a local problem,
- refactor unrelated code during an experiment.
Minimal, reversible changes are preferred.

---

## 12. STOP CONDITIONS
Stop and report before proceeding if:

- the requested experiment cannot be isolated,
- the benchmark population is ambiguous,
- the dataset differs unexpectedly,
- an existing result cannot be reproduced,
- a change appears to affect strategy behavior outside the requested variable,
- the repository state conflicts with the task description.
Do not guess when the research state is ambiguous.

---

## 13. FINAL REPORT
At the end of a task, report only what matters:

- what was changed,
- what was tested,
- key result,
- whether the intended variable was isolated,
- relevant commit/push status,
- any unresolved issue.
Keep reports concise. Do not dump large code blocks or unrelated command output unless specifically requested.
