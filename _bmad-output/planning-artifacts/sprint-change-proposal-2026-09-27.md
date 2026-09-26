# Sprint Change Proposal — 2026-09-27

**Trigger:** Story 3.2 (Jev eval, PR #14) — verdict FAILED, overall accuracy 0.297.
**Mode:** Batch. **Scope classification:** Moderate (4 new stories + two small spine amendments; no MVP change).
**Author:** Claude (correct-course), for Rijojohn.

## 1. Issue summary

The first real Jev eval ran 52 generated cases × 3 repeats against `typesafe/jev-1.13`. It FAILED
every quality bar. Case-by-case analysis of the receipt (`results/jev-eval/2026-09-27-typesafe-jev-1.13/`)
shows most of the failure is in the pipeline around Jev, not in Jev:

| # | Finding | Evidence |
|---|---|---|
| 1 | **The distiller drops the proof line.** GitHub Actions prefixes every log line with an ISO timestamp, so every `^`-anchored `ERROR_MARKERS` pattern never matches; the marker set is also Python-centric (no Go `--- FAIL:`, TAP `not ok`, Rust/Dart `error[…]`/`error •`, `npm ERR!`, apt `E: `, Playwright `1) [`, Mix `** (`). | The manifest `key_line` survives distillation in **15/38** cases. Re-running the distiller offline: timestamps stripped → 19/38; plus stack markers → ~30/38. |
| 2 | **The eval accepts unanswerable cases.** The case generator never checks that the proof survived. | 16 labelled cases distil to the identical single line `##[error]Process completed with exit code N.` with four different labels (code/infra/external/flaky); 3 trick cases are built on such bases. 7 of 8 `unknown` cases share the same runner-provisioner block. |
| 3 | **Labelling convention not in Jev's instructions.** Human-approved convention: GitHub platform failures (action download, artifacts, cache, api.github.com) = `infra`. `prompts/jev-classes.yaml` does not say so. | Where the proof survived, Jev scored 7/15; **6 of the 8 misses** are platform failures answered `external` (mostly confidence ≥ 0.85 → the bulk of the 19 confident-wrong). |
| 4 | **`flaky` is unanswerable from one log.** Flaky proof (a rerun passing / intermittent history) is never in the failing log itself; the Jev call only sees the distilled log (AD-11). | Flaky accuracy 0/21 attempts. |

The injection screen itself works: `noul` ≥ 0.84 on 5/6 trick cases; trick failures come from wrong base answers (findings 1–3).

## 2. Impact analysis

- **Epic 2:** story 2.5's distiller is correct against its synthetic fixtures but wrong on real GitHub logs → new story **2.13**. Downstream (2.7 evidence pack, 2.9 integration, every agent) benefits; no completed story is reverted.
- **Epic 3:** 3.2's harness is sound (make check green, honest verdict); its data validity needs a guard → **3.11**; Jev's class criteria need the platform convention → **3.12**; flaky needs history evidence → **3.13**. 3.3+ unchanged but now run after 3.13.
- **Spine:** AD-11 (Jev call shape) must allow a second delimited, structured evidence section in the same single call; AD-20 gains one clarifying clause (CI runner line prefixes). No other AD changes. AD-5 (agents hold no token) and AD-15 (repo-scoped, structured-only history) are preserved: the orchestrator collects, Jev only reads.
- **Contracts:** `HistoryRow` gains structured `terminal_state` / `human_verdict` (already stored by 2.6's `history` table — no migration); `EvidencePack` gains a structured job-outcome summary. Schemas regenerate.
- **Spec:** `verification.md` line on the Jev eval gains "plus structured flake evidence".
- **PRD/UX:** none.

## 3. Recommended approach

**Direct adjustment:** add four stories that run immediately after 3.2, in this order: 2.13 → 3.11 → 3.12 → 3.13, then resume 3.3. No rollback: PR #14 merges as the working eval harness with its FAILED receipt as the honest baseline.

- **Why this order:** fix the input (2.13) before guarding the exam against bad input (3.11, which would otherwise fail on today's distiller), then change Jev's instructions eval-first (3.12, which re-runs the eval and measures 1–3), then add the new evidence for flaky (3.13, which needs the spine amendment and re-runs again).
- **Effort:** 2.13 small–medium; 3.11 small; 3.12 small (+ ~170 model calls); 3.13 medium–large (contract, GitHub collection, eval data, + ~170 calls).
- **Risk:** 3.13 must not leak the answer — flake evidence may only come from runs created *before* the failing run. The small flaky sample (n=7) stays a stated caveat (OQ-5).
- **Not chosen:** adding more labelled logs now (the same distiller would drop their evidence too); dropping distillation (AD-20 is a safety boundary and Jev's input is bounded).

## 4. Detailed change proposals

### 4.1 Stories (epics.md — new)

#### Story 2.13: Distil real GitHub Actions logs across stacks

As a triage maintainer,
I want the distiller to keep the failing line of real GitHub Actions logs from any common stack,
So that agents receive the evidence that explains the failure instead of only the exit code.

**Scope:** MUST — CAP-2.

**Binding ADs:** AD-19, AD-20, AD-24.

**Dependencies:** 2.5, 3.2.

**External inputs / open questions:** None.

**Acceptance Criteria:**

**AC1**

**Given** real GitHub Actions log lines that begin with the runner's ISO-8601 timestamp prefix,
**When** the distiller matches error markers,
**Then** markers are matched against the line without that prefix, and the emitted line drops the prefix (it is runner metadata, not evidence),
**And** logs without a prefix behave exactly as before (every existing 2.5 test stays green, unchanged).

**AC2**

**Given** fixtures cut from the committed real logs in `test-data/jev-eval/logs/` for Go, TAP/Node, Rust, Dart/Flutter, npm, apt, Playwright, Elixir/Mix, Ruby, PHP and Java/Gradle failures,
**When** the distiller runs,
**Then** each stack's failure line is kept, each new pattern is one new `ERROR_MARKERS` registry entry (open/closed), and every pattern stays linear-time on adversarial input,
**And** a test runs the distiller over every labelled manifest log and asserts the manifest `key_line` survives in every case, except entries in a committed, human-approved exceptions list with a reason per entry (target: no exceptions; a non-empty list is reported in the story result).

#### Story 3.11: Guard the Jev eval against unanswerable cases

As a triage maintainer,
I want the eval to refuse cases whose evidence did not reach Jev,
So that an eval score measures Jev, not the pipeline in front of it.

**Scope:** MUST — CAP-3, CAP-6.

**Binding ADs:** AD-6, AD-19, AD-20.

**Dependencies:** 3.2, 2.13.

**External inputs / open questions:** OQ-5 (population) stays open.

**Acceptance Criteria:**

**AC1**

**Given** the labelled manifest and the real distiller,
**When** the case generator builds the eval cases,
**Then** it fails, naming each case, if a labelled case's `key_line` does not survive distillation or if two cases with different labels produce identical distilled input,
**And** the receipt records the evidence-retention count (labelled cases whose proof reached Jev / all labelled cases).

**AC2**

**Given** the `unknown` and trick case builders,
**When** cases are generated,
**Then** no two `unknown` cases share the same non-final content once timestamps, run ids and version numbers are normalised, and every trick case is built only on a base case whose proof survives,
**And** the 3.2 receipt is kept unchanged as the historical baseline, and the summary names it as superseded by the next run.

#### Story 3.12: Teach Jev the CI-platform failure convention

As a triage maintainer,
I want Jev's class descriptions to state that CI-platform failures are infra,
So that Jev and the labelled data use the same definition.

**Scope:** MUST — CAP-3, CAP-6.

**Binding ADs:** AD-6, AD-9, AD-11, AD-18, AD-19, AD-20.

**Dependencies:** 3.11.

**External inputs / open questions:** OQ-1 bar as supplied 2026-09-27; OQ-3 (Jev price) and OQ-5 stay open.

**Acceptance Criteria:**

**AC1**

**Given** the eval cases whose label is `infra` because the CI platform itself failed,
**When** the eval-first change is made,
**Then** those failing cases are cited as the red eval before `prompts/jev-classes.yaml` changes, and the `infra`/`external` criteria then state that failures of the CI platform (action downloads, artifacts, cache, the CI provider's API) are `infra` while third parties the project's build depends on are `external`,
**And** no label, case or bar changes in this story.

**AC2**

**Given** the fixed distiller, the guarded cases and the amended criteria,
**When** `make eval-jev` runs (at most 2 full runs),
**Then** a new receipt is saved under `results/jev-eval/` with the verdict against the unchanged OQ-1 bar, the evidence-retention count, and a before/after table against the 3.2 baseline,
**And** flaky is reported as still lacking history evidence (owned by 3.13) — never tuned around.

#### Story 3.13: Give Jev structured flake evidence

As a triage maintainer,
I want Jev to see a failing test's structured recent history in the same classification call,
So that flaky failures can be recognised from evidence rather than guessed from one log.

**Scope:** MUST — CAP-2, CAP-3, CAP-6.

**Binding ADs:** AD-5, AD-6, AD-9, AD-11 (as amended 2026-09-27), AD-15, AD-18, AD-19, AD-20, AD-24.

**Dependencies:** 3.12, 2.6, 2.7.

**External inputs / open questions:** OQ-1 bar as supplied; OQ-5 stays open (flaky n is small).

**Acceptance Criteria:**

**AC1**

**Given** a failed run being triaged,
**When** the orchestrator builds the evidence pack,
**Then** the pack carries structured, repo-scoped flake evidence: prior `history` rows for the failing fingerprint with their `terminal_state` and `human_verdict`, and the failing job's recent outcomes on the same branch (runs, failures, failures whose rerun on the same tested commit passed), over a window whose size lives in `guardrails/thresholds.yaml`,
**And** only runs created before the failing run are used (no future information), no free text enters the evidence (AD-15), the orchestrator collects it via the GitHub App, and Jev holds no token (AD-5).

**AC2**

**Given** an evidence pack with flake evidence,
**When** Jev classifies,
**Then** it is still exactly one `system_one` call carrying `Choice` and `Noul`, with the flake evidence in its own nonce-delimited untrusted data section next to the distilled log (AD-11, AD-20), and the `flaky` criterion in `prompts/jev-classes.yaml` refers to that evidence (eval-first),
**And** unit tests pin the call shape with a fake provider; contracts and generated schemas are updated.

**AC3**

**Given** every labelled eval case,
**When** the eval data is built,
**Then** each case (all classes, not only flaky) carries real flake evidence fetched from GitHub for runs before that case's failing run, stored beside the manifest with its source URLs, and cases without retrievable history are reported, not guessed,
**And** `make eval-jev` produces a new receipt with a before/after table against the 3.12 receipt, verdict against the unchanged OQ-1 bar.

### 4.2 Global build order (epics.md)

```
OLD
| 21 | 3 — … | 3.2  | Evaluate Jev classification before connection |
| 22 | 3 — … | 3.3  | Serve the evidence-grounded Analyzer |

NEW
| 21 | 3 — … | 3.2  | Evaluate Jev classification before connection |
| 22 | 3 — … | 2.13 | Distil real GitHub Actions logs across stacks |
| 23 | 3 — … | 3.11 | Guard the Jev eval against unanswerable cases |
| 24 | 3 — … | 3.12 | Teach Jev the CI-platform failure convention |
| 25 | 3 — … | 3.13 | Give Jev structured flake evidence |
| 26 | 3 — … | 3.3  | Serve the evidence-grounded Analyzer |
  (every later row renumbers +4)
```

Rationale: they close the Jev eval gap before the next agent; all dependencies point to earlier rows. The draft-validation record gains a dated change note (53 stories, 53 rows) instead of being rewritten.

### 4.3 Spine (ARCHITECTURE-SPINE.md)

```
AD-11 — Rule
OLD: One `system_one` call on the distilled log carries both the 5-class `Choice` and the injection pre-screen `Noul`.
NEW: One `system_one` call on the distilled log — plus the evidence pack's structured flake evidence (AD-24)
     in its own delimited section — carries both the 5-class `Choice` and the injection pre-screen `Noul`.
     (Amended 2026-09-27, sprint-change-proposal-2026-09-27: flaky cannot be decided from one log.)
```

```
AD-20 — Distiller
OLD: … drops narrative lines outside them, strips ANSI/control characters, numbers the lines, …
NEW: … drops narrative lines outside them, strips ANSI/control characters and CI-runner line prefixes
     (timestamps), numbers the lines, …  (Clarified 2026-09-27.)
```

AD-20 already lists history rows as untrusted delimited data; AD-15 already allows structured history in the pack; AD-24 already includes history rows and runner metrics. No other AD changes.

### 4.4 Spec (`verification.md`)

```
OLD: Jev classification eval uses labelled distilled logs;
NEW: Jev classification eval uses labelled distilled logs plus structured flake evidence;
```

### 4.5 Sprint status

Add `2-13-…`, `3-11-…`, `3-12-…`, `3-13-…` as `backlog`; set `3-2` to `done` once PR #14 merges (its ACs hold: measured, honest FAILED verdict against OQ-1; the agent is not declared passed).

## 5. Implementation handoff

- **Scope:** Moderate — backlog additions + two spine amendments, done in this correct-course (planning, not a build).
- **Builder:** Devin via `bmad-build-auto`, one story at a time or as a batch 2.13 → 3.11 → 3.12 (no external input needed); 3.13 separately (GitHub data collection + larger design).
- **Success criteria:** 2.13 — every manifest `key_line` survives (or a human-approved exception list); 3.11 — generator refuses unanswerable cases; 3.12 — new receipt with before/after; 3.13 — flaky evidence in the one call, new receipt. Passing the OQ-1 bar is the goal but not an AC: an honest FAILED receipt is an acceptable outcome, and nothing is tuned to pass.
