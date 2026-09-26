---
title: 'Build and persist the deterministic evidence pack'
type: feature
created: '2026-09-26'
status: done
review_loop_iteration: 1
followup_review_recommended: false
context: ['/home/rijojohn/dev/stage4/AGENTS.md']
baseline_revision: 'f8e373119552ddb7d99db62a027db929e1bae0c5'
---

## Build Brief

1. Story 2.7; sprint key `2-7-build-and-persist-the-deterministic-evidence-pack`.
2. AC1 selects the correct baseline and persists complete evidence. AC2 filters and ranks intersecting commits deterministically. AC3 keeps collection task-scoped, secrets private, and untrusted text separate from instructions.
3. AD-7: evidence locators must be resolvable. AD-15: every read uses task repo_id and history is structured. AD-16: mint one installation token per collection step, held only by orchestrator. AD-20: distill before serving, delimit untrusted text. AD-24: one deterministic pack, actual full comparison range and file-intersection candidates. AD-27: reuse existing blame-free projection rather than invent attribution policy.
4. Add `workflow/evidence.py`, `workflow/github_evidence.py`, `workflow/evidence_collection.py`, relevant tests; correct empty-range constraint in `contracts/evidence.py` and regenerate schemas. Do not edit planning spine/spec/epics, prompts, live specialist integrations or later stories.
5. SOLID-S: pure ranking/assembly separate from GitHub transport and orchestration. SOLID-I/D: narrow injected lookup/read/token interfaces with faithful fakes. DRY: reuse `distill`, thresholds, history fingerprints, `StepRecorder` and its existing guarded transaction; do not copy fencing or attribution rules.
6. TDD: AC1 baseline selection/fallback, empty range, complete pack and atomic persistence tests first; AC2 deterministic intersection, two suspects, concurrent pushes/no-intersection tests first; AC3 scope mismatch, private token/raw-log boundaries and hostile text serialization tests first. Include marked real-boundary integration tests. Run each red slice before implementation, then green and refactor.
7. Prerequisites 0.4/2.3/2.5/2.6 exist on main. Risks: pagination, file paths/import discovery, moving branch heads, delimiter escaping and empty comparisons. Use failed run's immutable head, no invented metrics or dependency graph. No unresolved external input for this story. Context7 unavailable; consult official GitHub REST documentation for API usage.
8. Update docs/DEVELOPER.md with module locations, entrypoints, test commands and AD links. Update docs/USER-GUIDE.md with artifact contents and how to use the existing collection entrypoint; accurately state current integration status. Workflow README may link the developer guide.

<intent-contract>

## Intent

**Problem:** The workflow has no deterministic, durable pack bounding the evidence and suspects agents may use.

**Approach:** Collect read-only task-scoped GitHub evidence, distill logs, select baseline, rank file-intersecting commits, add structured history/real metrics and commit the pack through existing step persistence.

## Boundaries & Constraints

**Always:** use task repository and immutable failed HEAD; choose latest success of same workflow/branch, otherwise same repository default-branch head; retain full actual comparison SHAs; deterministic ranking; no raw logs/tokens in pack or agent context; delimiter-safe untrusted data; tenant-scoped history; existing lease-guarded persistence and attribution removal.

**Never:** fabricate a commit for empty ranges, fabricate metrics, invoke a dependency graph for ranking, connect specialist agents, write GitHub effects, modify prompts or authoritative planning documents.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Matching baseline | Successes across workflows/branches | Latest matching success chosen deterministically | None |
| No matching success | Default branch commit | Default head baseline | None |
| Empty comparison | Baseline equals failed HEAD | Empty commits/candidates; valid pack | None |
| Concurrent push | Branch moves after failed run | Compare to failed run immutable HEAD | None |
| Two intersecting commits | Changed files overlap frames/imports | Deterministic ranked suspects only | None |
| No intersection | Unrelated changed files | No suspects | None |
| Foreign repository | Response scope differs from task | No pack persisted/served | Typed non-retryable refusal |
| Hostile text | Commit/title contains delimiter or instructions | Remains escaped untrusted data | None |

</intent-contract>

## Code Map

- `/tmp/stage4-story27-preserve.diff`: saved first-pass implementation for positive preservation during re-derivation. Restore tests first, observe failures against baseline, then preserve reviewed behavior while fixing all constraints below. Do not restore this spec from the patch.
- `workflow/steps.py`, `workflow/step_store.py`: extend StepCommit with optional task-run identity (repo/run/attempt) checked against triage_run inside the existing guarded transaction, before step insertion/state change. Collector supplies identity; unrelated leased run must refuse. Keep existing callers compatible.

- `contracts/evidence.py`: existing EvidencePack/CommitRecord/CandidateSuspect/HistoryRow shapes; remove only erroneous commits min_length=1 for actual empty range.
- `workflow/distiller.py`: public `distill` numbers and bounds evidence; `workflow/thresholds.py` loads limits.
- `workflow/history_store.py`: `lookup(repo_id, fingerprint)`; project internal HistoryEntry into existing served HistoryRow, check scope.
- `workflow/steps.py`, `workflow/step_store.py`: `StepRecorder.record(claim, repo_id, StepCommit)` persists JSON and state atomically; reuse fencing unchanged.
- `gateway/events.py`: task repo_id/installation/run/attempt identity; repository authority originates here, never model output.
- `workflow/task_store.py`, `workflow/attribution.py`: reuse existing artifact and blame-free stripping behavior.
- `tests/contracts/test_evidence.py`: add empty range contract regression; schema drift enforced by `scripts/generate_schemas.py`.

## Tasks & Acceptance

**Execution:**
- Review repair: preserve baseline/fallback/empty-range, deterministic ranking, distilled/escaped context, structured history, complete comparison refusal, secret exclusion, tested atomic persistence and docs from first pass. Re-derive from saved patch test-first, then add red regressions for the following verified gaps.
- `workflow/github_evidence.py`: resolve absolute checkout stack/test paths against task repository checkout prefix before file matching/contents requests; reject traversal. Validate compare response endpoints/repository against requested baseline/head; validate tree/content URL and revision/path against task. Bind jobs to run_attempt as well as run/repository. Add public tests for each refusal and valid task response.
- `workflow/evidence.py`, `workflow/github_evidence.py`: one source for successful matching-run policy, reused by adapter to avoid duplicate selection conditions. Test multiple matches, input reversal and timestamp ties.
- `tests/workflow/test_github_evidence.py`, collection tests: public end-to-end collection tests for imports (normal/from/relative), changed imported module candidates and successful multi-page comparison/files/jobs/run selection. Tests must fail when imports are disabled or later-page data dropped.
- `tests/workflow/test_evidence_integration.py`: add marked real GitHub read test requiring explicit environment configuration, exercising actual requests, with clear skip if configuration unavailable. Never claim skipped GitHub integration passed.
- `tests/workflow/test_evidence_collection.py`: recorder fake accepts/stores StepCommit and honors step/attempt/status/output exactly.
- `workflow/evidence.py`: pure baseline selection, normalized file intersection/ranking and pack assembly.
- `workflow/github_evidence.py`: read-only GitHub adapter with injected request/token boundaries, complete pagination and strict task scope, full SHA validation and genuinely collected metrics; check official API docs.
- `workflow/evidence_collection.py`: collection, distillation, history projection, safe agent context and persistence via existing recorder.
- `tests/workflow/test_evidence.py`, `tests/workflow/test_github_evidence.py`, relevant marked integration/security tests: public behavior AC1–AC3 and all matrix rows, red before production code.
- `contracts/evidence.py`, generated schema: allow actual empty comparison.
- `docs/DEVELOPER.md`, `docs/USER-GUIDE.md`: documented current entrypoint and artifact behavior.

**Acceptance Criteria:**
- AC1: Given a failed workflow/branch, when DISTILLING builds EvidencePack, then last_green is the latest successful run of that workflow on that branch, else default-branch head, and pack persists as run_step with numbered distilled log, full last_green..HEAD SHAs, history rows and collected runner metrics.
- AC2: Given commits changing stack-trace files or test imports, when candidate ranking runs, then only intersecting candidates enter candidate_suspects and ordering is deterministic, and tests cover two suspects/concurrent pushes and no intersection; no dependency-graph tool or invented metric is used.
- AC3: Given GitHub evidence collection, when the tool layer fetches task-scoped context, then per-step installation token stays in orchestrator and repository identifiers come from the task, and untrusted commit messages/title/history remain data; agent context contains no raw CI logs or other repo evidence.

## Spec Change Log

2026-09-26 review repair 1: source review found incomplete task/revision/attempt binding, absolute checkout path handling and unexercised import/pagination/latest-success behavior. Tasks now explicitly require their refusal and public coverage; StepCommit task identity must be checked in the existing transaction. KEEP first-pass positive behavior listed above, real Postgres atomicity/fencing tests, schemas and both guide updates. Saved patch `/tmp/stage4-story27-preserve.diff`; original code reverted before re-derivation. Intent-contract unchanged.

## Review Triage Log

### 2026-09-26 — Review pass 1
- verdicts: 12 findings — high 0, medium 10, low 2, false 0, maybe-false 0
- findings:
  - `[medium]` `[bad_spec]` Import discovery untested — all adapter logs referenced src/a.py and returned before source/tree discovery; repair requires public import-only suspect test.
  - `[medium]` `[bad_spec]` Latest of several matches untested — one matching success cannot distinguish max from min; repair requires permutation/tie tests.
  - `[medium]` `[bad_spec]` Valid later pages untested — only foreign-page refusal existed; repair requires complete valid comparison/files aggregation tests.
  - `[medium]` `[bad_spec]` Absolute checkout paths do not match relative changed files — PurePosixPath retains root, so exact intersection fails; repair normalizes known task checkout prefix.
  - `[medium]` `[bad_spec]` Claim/task identity unbound — recorder guards claim owner/repo but not supplied workflow_run_id/run_attempt; repair adds optional transaction-checked identity.
  - `[medium]` `[bad_spec]` Comparison endpoints unbound — total count and individual repo-scoped commits do not prove requested baseline/head; repair validates response endpoints.
  - `[medium]` `[bad_spec]` Tree/content revision scope unchecked — import discovery accepts foreign/stale source without locator validation; repair validates supplied scope and revision.
  - `[medium]` `[bad_spec]` Jobs from wrong attempt accepted — code checks run_id and URL but not run_attempt; repair checks attempt.
  - `[medium]` `[bad_spec]` No marked real GitHub boundary check — all current integration tests inject Reader; repair adds configured live check with explicit unavailable-service skip.
  - `[medium]` `[bad_spec]` Import discovery coverage gap (clean-code layer) — same verified missing path as verification reviewer; same repair.
  - `[low]` `[bad_spec]` Duplicated matching-success conditions — adapter and pure policy differ on conclusion; repair reuses one policy.
  - `[low]` `[bad_spec]` Recorder fake violates interface — object lacks promised attributes and returned record ignores input fields; repair faithfully types and returns StepCommit fields.

Layers: edge-case, verification-gap and clean-code ran. Blind-hunter and intent-alignment skipped for platform agent capacity. Fresh verification reviewer could not spawn (thread limit); reused investigator. Clean-code reused implementer and is not an independent review. These limitations are reported rather than claiming five independent layers.

### 2026-09-26 — Review pass 2

- verdicts: 2 findings — high 0, medium 2, low 0, false 0, maybe-false 0
- findings:
  - `[medium]` `[patch]` Import variants shared one commit, so one working import masked broken variants — parameterized one import and one corresponding changed file, independently asserting each candidate through public collection.
  - `[medium]` `[patch]` Latest-success date order unverified — added later timestamp with lower run ID and asserted it wins in both input orders.
- Edge reviewer verified all five source repairs, no remaining defect. Verification reviewer confirmed pagination and fake fixes, then found these two test gaps; both corrected and parent inspected diff/reran focused suite (56 passed). Clean-code, blind-hunter and intent-alignment layers skipped this pass to limit usage at user's request. Patched counts: medium 2, high 0. No specific remaining risk attributable to those test fixes; follow-up review recommendation false. Live GitHub verification remains unavailable and explicitly skipped.

## Verification

- `.venv/bin/pytest tests/workflow/test_evidence.py tests/workflow/test_github_evidence.py tests/contracts/test_evidence.py -q`: all AC/matrix unit tests pass.
- Run marked evidence integration tests against real boundaries; record any unavailable service explicitly without claiming a pass.
- `make check`: all required gates green; no missing docs.

## Auto Run Result

Implemented on `story/2-7-build-and-persist-the-deterministic-evidence-pack`.

- AC1: baseline selection/fallback, empty actual range, complete pack/history/metrics,
  incomplete comparison refusal and atomic persistence covered by named `test_ac1_*`
  tests. Empty range first failed with the existing contract's `min_length` error;
  new pure/adapter/collector tests first failed on absent modules. Incomplete
  comparison first failed with `DID NOT RAISE`, then passed after total validation.
- AC2: `test_ac2_two_suspects_normalized_intersection_and_stable_order` covers
  two overlapping commits, permutation-stable ranking and no intersection;
  `test_ac1_ac2_compare_immutable_failed_head_and_real_metrics` verifies fixed
  failed HEAD rather than moving branch heads. Initial missing-module red;
  implementation green. No dependency graph or fabricated timing value used.
- AC3: named tests cover foreign repository, wrong run attempt, foreign commit
  pagination, foreign job, foreign history, one token mint, escaped hostile text,
  distilled-only context and author removal. Foreign second-page and job cases
  failed with `DID NOT RAISE` before strict scope checks were added, then passed.
- Existing task author stripping was promoted to the public
  `without_author_attribution` name and reused without changing policy.
- Required developer/user guides updated. No prompt or authoritative planning
  spine/spec-directory/epics change; no GitHub write or specialist integration.

Verification:

- `.venv/bin/pytest tests/workflow/test_evidence.py tests/workflow/test_github_evidence.py tests/contracts/test_evidence.py -q`: **16 passed**.
- `.venv/bin/pytest tests/workflow/test_evidence.py tests/workflow/test_github_evidence.py tests/workflow/test_evidence_collection.py tests/contracts/test_evidence.py -q`: **20 passed**.
- `.venv/bin/pytest -m integration tests/workflow/test_evidence_integration.py -q -rs`:
  sandbox attempt skipped all 3 because Docker socket access was denied; authorized
  escalated retry: **3 passed**, using real disposable Postgres 18 containers.
  Proves saved pack plus structured history/state, rollback on database-trigger
  fault and rejection of replaced worker owner.
- `make check`: sandbox attempt failed bootstrap network; authorized escalated
  retry **MAKE CHECK: PASS**, **335 passed / 45 integration deselected**,
  **92.03% total coverage**, all layer/schema/diagram/lint/format/type/duplication
  gates green. No new lint exceptions.
- Repository graph incrementally refreshed after code changes. New untracked
  modules may require staging/full rebuild for graph change review.

Current boundary: real GitHub collection was not exercised. The read adapter
accepts injected HTTP and installation-token boundaries; it has faithful fake
coverage. No live token issuer, worker scheduling or specialist-agent wiring
was added, as documented in both guides. Python imports are direct only;
truncated file trees are refused rather than guessed.

### Review repair 1 result

Preserved tests were restored before implementation: the empty-range contract
failed on `min_length`, and evidence modules were absent. Restoring preserved
production behavior made all 20 first-pass focused tests green.

- AC1: added multiple matching successes, input reversal and equal-timestamp
  tie coverage, plus valid later run/comparison/file/job pages. Matching-success
  selection now has one pure source. Four task-identity refusal cases failed
  with `DID NOT RAISE` before the optional transaction guard was added.
- AC2: public collection tests cover normal, from and relative imports and
  Linux/Windows checkout paths, with suspects changing only imported modules.
  Absolute path requests and commit-pinned tree expectations failed before
  repair; pure path/import resolution and immutable source fetching made them
  green. Later-page assertions would fail if later commits/files/jobs/runs
  were dropped. Existing correct pagination was preserved.
- AC3: compare endpoints/base, commit tree pointers, tree SHA/URL, content
  path/URL/revision/blob and job attempt are checked. Foreign/stale-response
  tests first failed to raise; traversal cases first reached improper contents
  requests, then were refused before those requests. Collector now supplies
  `TaskRunIdentity` in `StepCommit`. The real wrong-task Postgres test failed
  with `DID NOT RAISE StepTaskMismatchError` before collector wiring, then passed.
  Recorder fake now accepts/stores `StepCommit` and honors its fields; the
  fake-field regression failed before correction. Both guides updated.

Final commands:

- `.venv/bin/pytest tests/workflow/test_evidence.py tests/workflow/test_github_evidence.py tests/workflow/test_evidence_scope.py tests/workflow/test_evidence_collection.py tests/workflow/test_evidence_identity.py tests/contracts/test_evidence.py -q`: **43 passed**.
- `.venv/bin/pytest -m integration tests/workflow/test_evidence_integration.py -q -rs` (authorized Docker access): **4 passed, 1 skipped**. Real Postgres
  verifies complete pack/history/state, rollback, stale owner and unrelated task
  refusal. The real GitHub test explicitly skipped because its five
  `TRIAGE_EVIDENCE_*` environment values were unavailable; no live GitHub pass
  is claimed.
- `make check` (authorized network access for bootstrap): **MAKE CHECK: PASS**,
  **358 passed / 47 integration deselected**, **93.52% total coverage**. All
  bootstrap/layer/schema/diagram/lint/format/type/duplication gates passed.
- Graph incrementally refreshed after repairs; parent owns final review.

No later story, prompt, GitHub write, specialist connection or authoritative
planning-document change was introduced. Live HTTP/token worker wiring remains
injected, as documented. Collection refuses incomplete trees and resolves only
direct Python imports rather than inventing dependency relationships.

### Final parent verification and AC proof

Parent inspected the complete diff, source and tests after both review passes.
All eight matrix rows ran and passed: matching/fallback/empty baselines,
concurrent pushes, two/no suspects, foreign scopes and hostile text.

Reproduce the exact AC selections using this common file list:

```bash
evidence_tests=(tests/workflow/test_evidence.py tests/workflow/test_github_evidence.py tests/workflow/test_evidence_scope.py tests/workflow/test_evidence_collection.py tests/workflow/test_evidence_identity.py tests/contracts/test_evidence.py)
.venv/bin/pytest "${evidence_tests[@]}" -q -k ac1
.venv/bin/pytest "${evidence_tests[@]}" -q -k ac2
.venv/bin/pytest "${evidence_tests[@]}" -q -k ac3
```

- AC1: **14 passed**. Named tests include latest timestamp/tie/reversal selection,
  default fallback, empty range, complete pack/history/metrics and guarded storage.
- AC2: **19 passed**. Named tests include two/no suspects, immutable failed head,
  independent normal/from/relative import cases for each checkout-path format,
  and successful later-page aggregation.
- AC3: **25 passed**. Named tests include foreign repository/history/pages/jobs,
  wrong attempts, compare/tree/content revision binding, task identity refusal,
  safe delimiters, private tokens and blame-free context.
- Full focused command (same list without `-k`): **56 passed**.
- `.venv/bin/pytest -m integration tests/workflow/test_evidence_integration.py -q -rs`:
  **4 passed, 1 skipped**; real Postgres verified. GitHub skipped solely for missing
  explicit identity/token configuration, not reported as passing.
- `make check`: **MAKE CHECK: PASS**, **371 passed, 47 integration deselected**,
  **93.52% coverage** after final test-only fixes. Log: `/tmp/stage4-story27-final-check.log`.
- Both required guides changed and inspected. No lint exceptions added. Graph
  refreshed and change/flow queries consulted; direct source/test evidence wins
  over missing graph relationships.

Review outcome: first pass's 12 findings repaired through one spec repair loop;
second pass's two medium verification gaps patched. No findings deferred or
rejected. Follow-up recommendation false: strengthened tests verified both
patches, with no specific remaining risk attributable to them. Review layer and
agent-reuse limitations are recorded in the triage log. Residual limitation:
live GitHub read unavailable; HTTP/token providers are injected, automatic
worker/specialist integration remains future work. No source/spine conflict found.

Batch stop: user requested stop after 2.7. Stories 4.1, 6.1, 6.2 and 2.8 were
not started; 2.9 was not started. No push or merge performed.
