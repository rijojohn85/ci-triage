---
title: 'Story 3.12 — Teach Jev the CI-platform failure convention (eval-first)'
type: 'feature'
created: '2026-09-27'
status: 'done'
baseline_revision: '8d4f55b82eb854e63cb730a21e09641a44bade31'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-3-context.md'
warnings: [oversized]
deferred: []
---

## Build Brief

**(1) Story:** 3.12 — Teach Jev the CI-platform failure convention (sprint-status key `3-12-teach-jev-the-ci-platform-failure-convention`). Closes finding 3 of `sprint-change-proposal-2026-09-27.md`: `prompts/jev-classes.yaml` does not state that failures of the CI platform itself are `infra`, so Jev answered `external` on the 3.2 receipt's platform-failure cases (elixir-infra-01, fission-infra-01, ha-infra-01, nodejs-infra-01/02, rails-infra-01/02 — 19 of the 19 confident-wrong were infra→external). This is an eval-first prompt change: run A is the red eval, then the criteria change, then run B. Budget: at most two full runs (~175 calls each). Nothing is tuned to pass; FAILED is expected (flaky has no history yet — story 3.13).

**(2) ACs in one line each:**
- AC1: run A (unchanged prompt) is saved as a receipt and its `infra`-labelled platform-failure cases are cited as answered `external`; the `infra`/`external` criteria then state that CI-platform failures (action downloads, artifacts, cache, the CI provider's own API/storage) are `infra` and third parties the project's build depends on are `external`; no label, case or bar changes.
- AC2: run B is saved as a distinct receipt under `results/jev-eval/`, with the verdict against the unchanged OQ-1 bar, the evidence-retention count, and a before/after table (3.2 baseline → run A → run B: overall, per-class, confident-wrong, trick pass rate, evidence retention); flaky is reported as still lacking history evidence and is never tuned around.

**(3) Binding ADs:** AD-6 (the run validates every result against the committed schema), AD-9 (the effective confidence path is reused, never reimplemented), AD-11 (one `system_one` call carries `Choice` + `Noul` — untouched; no history is added), AD-18 (every call accounted for), AD-19 (the pass bar and repeats come only from `guardrails/thresholds.yaml`; prompts live once in `prompts/`), AD-20 (the distilled log stays the untrusted data section).

**(4) Files:**
- Change `prompts/jev-classes.yaml` — add the CI-platform sentence to `infra` and the "a third party is a service the project's build depends on, not the CI platform" sentence to `external` (wording may be tightened, not changed).
- Change `scripts/run_jev_eval.py` — a `--label` receipt-directory suffix and a repeatable `--compare` that writes `comparison.md` beside the new receipt.
- Change `workflow/jev_eval.py` — the pure `render_comparison_md(current, baselines)`.
- Change `tests/workflow/test_jev_eval.py`, `tests/scripts/test_run_jev_eval.py` — comparison and label tests.
- Change `Makefile` — forward `EVAL_ARGS` to the harness so a labelled/compared run is still `make eval-jev`.
- Change `results/README.md` — name the latest receipt; `docs/DEVELOPER.md` — the platform convention and the comparison.

  **NOT touched:** the 3.2 receipt files under `results/jev-eval/2026-09-27-typesafe-jev-1.13/`; `test-data/jev-eval/manifest.yaml` `label`/`key_line`/`evidence`; `test-data/jev-eval/cases.generated.yaml` (no case change); `guardrails/thresholds.yaml` (no bar change); `agents/jev/**`; the spine/spec/epics; `docs/USER-GUIDE.md`. **Out of scope:** story 3.13 (no flake history enters the Jev call).

**(5) Approach (SOLID/DRY):**
- **Eval-first, two runs:** run A measures Jev with the unchanged prompt (the red eval that cites the platform-failure misses); the criteria change follows; run B measures the change. No third run: a re-score from a saved raw output (`--from-output`) is used only if the comparison needs regenerating.
- **Distinct receipts without collisions (SOLID-S):** `--label` is a CLI-level suffix on the receipt directory (`<date>-<model>-<label>`), so run A and run B never overwrite the 3.2 receipt or each other.
- **Comparison is a pure function (DRY):** `render_comparison_md` takes the current summary plus the baseline summaries and renders one table; the harness owns reading each baseline's `summary.json` (I/O) and writing the file. The three columns come from three receipts, so run B's table is 3.2 → A → B.
- **The prompt is data:** the criteria live only in `prompts/jev-classes.yaml`; the receipt records its sha256, so before/after provenance is provable.

**(6) TDD plan (red-first; names cite ACs):**
- `tests/workflow/test_jev_eval.py`: `test_ac2_render_comparison_md_has_a_column_per_receipt`, `test_ac2_comparison_rows_cover_overall_per_class_confident_wrong_trick_and_retention`, `test_ac2_comparison_names_each_receipt_and_its_verdict`.
- `tests/scripts/test_run_jev_eval.py`: `test_ac2_receipt_dir_carries_the_label`, `test_ac2_compare_writes_comparison_md_beside_the_receipt`, `test_ac2_compare_reads_each_baseline_summary`.
- The prompt change has no unit test: its eval is the promptfoo run itself (run A red → criteria change → run B), as the intent directs and AGENTS.md's eval-first rule intends.

**(7) Risks / OQ:** (i) the eval needs node ≥ 22.22.0 — use **node v26.10.0** via `PROMPTFOO_NODE=/home/rijojohn/.nvm/versions/node/v26.10.0/bin/node` (verified: promptfoo 0.123.1 runs under it and `resolve_node()` honours the override) — and `TYPESAFE_API_KEY` (in `.env`); a wiring failure makes no model calls. (ii) If either run's error rate exceeds `max_error_rate` (0.10), report `not run: errors` and stop — do not re-run. (iii) `flaky` cannot be answered from one log (AD-11); run B will still fail the flaky bar — expected, owned by 3.13. (iv) The baseline `summary.json` predates 3.11's `evidence_retained`/`evidence_total`; pydantic fills their defaults, so it renders as `0/38` for the 3.2 column (honest: the old cases carried no proof var). (v) The OQ-1 bar, labels and cases do not move. No blocking OQ.

**(8) Doc impact:** `docs/DEVELOPER.md` — the Jev eval section gains the CI-platform convention and the `--label`/`--compare` receipt comparison; `results/README.md` — the latest receipt named; `test-data/jev-eval/README.md` — the labelling rule already states the GitHub-platform-is-infra boundary (no change). `docs/USER-GUIDE.md` — **no doc change**: maintainer tooling.

<intent-contract>

## Intent

**Problem:** Jev and the labelled data disagree on the platform boundary: `prompts/jev-classes.yaml` never says that failures of the CI platform itself (action downloads, artifacts, the cache service, the provider's own API/storage) are `infra`, so Jev answered `external` on those cases — 19 of the 19 confident-wrong on the 3.2 receipt — and the eval failed on them.

**Approach:** Change the `infra` and `external` criteria eval-first: run A measures the unchanged prompt (the red eval citing the platform-failure misses), the criteria then state the CI-platform convention, and run B measures the change; both receipts are saved under distinct names with a before/after table against the 3.2 baseline, and the verdict is reported honestly against the unchanged OQ-1 bar.

## Boundaries & Constraints

**Always:** the criteria change is exactly the CI-platform convention (wording may be tightened, meaning unchanged); run A is saved before the prompt changes and run B after; each run's receipt is saved under a distinct directory; the verdict is against the unchanged OQ-1 bar and reported as-is; the evidence-retention count and a before/after table are in run B's receipt; every model call is accounted for; the pass bar and repeats come only from `guardrails/thresholds.yaml`.

**Never:** do not move the bar, relabel a case, drop a case or tune anything to pass; do not edit the 3.2 receipt files; do not edit `manifest.yaml` labels/key_lines/evidence or `cases.generated.yaml`; do not add flake history (story 3.13); do not re-run past the two-run budget, and stop with `not run: errors` if the error rate breaches; `make eval-jev` must not join `make check`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Run A (unchanged prompt) | the OQ-1 bar, repeats 3, the guarded cases | a receipt with the platform-failure `infra` cases answered `external` cited | Verdict reported as-is |
| Criteria change | `prompts/jev-classes.yaml` `infra`/`external` | the CI-platform convention stated; no label/case/bar change | No error expected |
| Run B (changed prompt) | the same cases and bar | a distinct receipt with the before/after table | Verdict reported as-is |
| Baseline summary older than 3.11 | a `summary.json` without the retention fields | the 3.2 column renders `0/38` (no proof var) | No error expected |
| Labelled receipt | `--label before` | receipt dir `<date>-<model>-before` | No error expected |
| Error rate breach | > `max_error_rate` attempts errored | verdict `not run: errors`, stop | Reported, not re-run |

</intent-contract>

## Code Map

- `prompts/jev-classes.yaml:20` `infra` criterion, `:25` `external` criterion -- the one prompt file (AD-19); the only content change.
- `scripts/run_jev_eval.py:216` `_receipt_dir`, `:244` `main`, `:233` `_write_from_raw` -- add `--label` (dir suffix) and `--compare` (write `comparison.md`); reuse `_read_output`/`load_thresholds`.
- `workflow/jev_eval.py:418` `render_summary_md`, `:208` `EvalSummary` -- add the pure `render_comparison_md(current, baselines)`; `EvalSummary.model_validate` reads a baseline `summary.json` (defaults fill the 3.11 fields).
- `tests/workflow/test_jev_eval.py`, `tests/scripts/test_run_jev_eval.py` -- the comparison/label tests; reuse the existing attempt/summary fixtures.
- `Makefile` `eval-jev` target -- forward `EVAL_ARGS` so the labelled run stays `make eval-jev`.
- `guardrails/thresholds.yaml` `eval.jev` -- the OQ-1 bar (unchanged); `results/jev-eval/2026-09-27-typesafe-jev-1.13/` -- the read-only 3.2 baseline.
- `results/README.md`, `docs/DEVELOPER.md` -- the receipts index and the eval section.

## Tasks & Acceptance

**Execution:**
- `scripts/run_jev_eval.py` -- add `--label` and `--compare`, wiring the pure renderer -- AC2.
- `workflow/jev_eval.py` -- add `render_comparison_md` -- AC2.
- `tests/...`, `Makefile` -- red-first tests and the `EVAL_ARGS` passthrough -- AC2 proof.
- `make eval-jev EVAL_ARGS="--label before"` -- run A (unchanged prompt); inspect and cite the platform-failure `infra`→`external` misses -- AC1.
- `prompts/jev-classes.yaml` -- add the CI-platform convention to `infra`/`external` -- AC1.
- `make eval-jev EVAL_ARGS="--label after --compare <3.2 dir> <run A dir>"` -- run B + `comparison.md` -- AC2.
- `results/README.md`, `docs/DEVELOPER.md` -- per brief §8.

**Acceptance Criteria:**
- Given the eval cases whose label is `infra` because the CI platform itself failed, when the eval-first change is made, then those failing cases are cited as the red eval before `prompts/jev-classes.yaml` changes, and the `infra`/`external` criteria then state the CI-platform convention, with no label, case or bar changed (AC1).
- Given the fixed distiller, the guarded cases and the amended criteria, when `make eval-jev` runs (at most two full runs), then a new receipt is saved under `results/jev-eval/` with the verdict against the unchanged OQ-1 bar, the evidence-retention count, and a before/after table against the 3.2 baseline, and flaky is reported as still lacking history evidence (AC2).

## Spec Change Log

## Review Triage Log

### 2026-09-27 — Review pass
- verdicts: 28 findings — high 0, medium 0, low 21, false 7, maybe-false 0
- findings:
  - `[low]` `[patch]` `receipt_name`'s empty-date fallback changed from `_local_date()` to the literal `"unknown"`, so a dateless summary would write `unknown-<model>/` — unreachable in production (`_summary` always sets the date) but a shared-function behaviour change; restore the old fallback in the harness and name the constant.
  - `[low]` `[patch]` `--label` is unvalidated: a label that slugs to empty (`"!"`) yields a trailing-dash directory — reject a label that slugs to nothing.
  - `[low]` `[patch]` `--compare` has no error handling: a directory without a valid `summary.json` raises a raw traceback — report a clear "not a receipt directory" message.
  - `[false]` `[reject]` `comparison.md` lacks provenance rows (prompt sha256) — the intent names the exact rows (overall, per-class, confident-wrong, trick pass rate, evidence retention), and each receipt's `summary.md` records its own sha256/commit.
  - `[low]` `[patch]` `label` is persisted in `summary.json` but never rendered in `summary.md` — render it in the header when set.
  - `[low]` `[patch]` two baselines can produce duplicate column names — refuse/dedupe (same fix as the label validation).
  - `[low]` `[patch]` no test covers label sanitization or the `--compare` failure paths — add them (same fix as the label/compare rows).
  - `[low]` `[reject]` the new tests call private helpers (`_receipt_dir`, `_read_baseline`) — the harness is a script whose only public surface is `main`; the file already tests its pure helpers as the established convention and one test drives `main` end-to-end; the fix is a restructure, not a direct correction.
  - `[low]` `[reject]` the comparison test reads a committed receipt path — the 3.2 receipt is a permanent committed baseline the story explicitly keeps unchanged; the fix is a guard, not a direct correction.
  - `[low]` `[reject]` the comparison mixes incomparable runs with no warning — the operator chooses the baselines and every column names its receipt (`<date>-<model>-<label>`), so a mismatch is visible; a guard is more than a direct correction.
  - `[low]` `[reject]` `EVAL_ARGS` is expanded unquoted, so a path with spaces breaks — word-splitting is the mechanism that forwards several flags; quoting would break it, and the comment documents the intent.
  - `[low]` `[patch]` no comparison test exercises a `None` metric (`_pct(None)`) — add one.
  - `[false]` `[reject]` `results/README.md` lists `promptfoo-output.json` as "missing" from the review diff — the exclusion was the review harness's; both raw dumps are committed.
  - `[low]` `[reject]` ~7,000 lines of `summary.json` per run suggests compaction — consistent with the committed 3.2 receipt pattern (every attempt, both confidences, caps, tokens); compaction is a separate concern, not this story's defect.
  - `[low]` `[patch]` `--compare` has no error handling (edge-case layer) — same as the `--compare` row.
  - `[low]` `[patch]` `--label` slugs to empty (edge-case layer) — same as the label-validation row.
  - `[low]` `[patch]` two labels slug alike and the second overwrites the first (edge-case layer) — same as the label-validation row.
  - `[low]` `[patch]` `--compare` repeating a baseline or naming the current run gives duplicate/self columns (edge-case layer) — same as the label-validation row.
  - `[low]` `[patch]` `receipt_name` date fallback (edge-case layer) — same as the first row.
  - `[low]` `[patch]` `--label` slug empty/collision bypasses the "never overwrites" claim (verification-gap) — same as the label-validation row.
  - `[false]` `[reject]` the tested surface (the harness) differs from the intent's expected surface (the eval) — the intent's own requirements (distinct directory names, a comparison table) are harness behaviour, and the eval evidence is the committed receipts; the tested machinery is what makes the eval-first protocol reproducible.
  - `[low]` `[reject]` "say so plainly" (flaky) is absent from the receipt — the receipt states FAILED and flaky 0.000; the "no history yet — story 3.13" explanation is written in the spec, the story report and the PR body, which is where a maintainer explanation belongs.
  - `[false]` `[reject]` the new receipt `--label` flag collides with the eval's `expected_label` sense — different namespaces; the intent's "no label changes" means the manifest labels, which do not change.
  - `[false]` `[reject]` the `--label`/`--compare` machinery is beyond the intent's letter — it is the mechanism for the intent's own "distinct directory names" and "a comparison.md beside it", so it is in scope.
  - `[false]` `[reject]` the PR body cannot be verified from the diff — the PR body is written after review, per the workflow.
  - `[false]` `[reject]` "comparison in summary.md or beside it — satisfied" is listed as a divergence — it is a satisfied requirement, not a finding.
  - `[low]` `[patch]` `receipt_name` magic literal (clean-code) — same as the first row.
  - `[low]` `[patch]` `docs/DEVELOPER.md` says `<date>` is the local system date while the fallback now writes `unknown-` (clean-code) — same as the first row.
- patch pass applied: all 15 `patch` rows fixed as their row describes — the empty-date fallback restored (the harness fills the date from `_local_date()`; the comparison-only fallback is a named constant) with the DEVELOPER.md line corrected, `--label` rejects a label that slugs to nothing, `--compare` reports a clear error for a non-receipt directory and refuses a self/duplicate baseline, the run `label` renders in `summary.md`, and tests cover all of it plus a `None` metric. The two committed receipts were re-derived from their own raw outputs (`--from-output`, zero model calls) so they match the current code and the comparison was regenerated; the numbers are unchanged. Re-verified: `make check` PASS (810 passed, coverage 95.06%).

## Design Notes

**Comparison.** `render_comparison_md(current, baselines)` is pure: one column per receipt (the baselines in the order given, then the current run) and one row per metric — verdict, overall accuracy, per-class accuracy (code/flaky/infra/external/unknown), confident-wrong, trick pass rate (`passed/total`), evidence retention (`retained/total`). The harness reads each baseline's `summary.json` into `EvalSummary` (defaults fill the post-3.11 fields, so the 3.2 column shows `0/38`) and writes `comparison.md` beside the new receipt.

**Eval-first, and why no promptfoo case is added.** AGENTS.md's eval-first rule is satisfied by the run itself: the existing labelled `infra` platform-failure cases in `cases.generated.yaml` are the case that captures the intended behaviour, run A is the red eval (they are answered `external`), and run B is the green. The intent forbids case changes ("No label, case or bar changes"), so no new case is added.

## Verification

**Commands:**
- `.venv/bin/pytest tests/workflow/test_jev_eval.py tests/scripts/test_run_jev_eval.py -q` -- expected: all AC-named tests pass.
- `make check` -- expected: PASS.
- `make eval-jev EVAL_ARGS="--label before"` -- expected: a receipt `results/jev-eval/<date>-<model>-before/` with the red platform-failure misses; ≈174 real calls.
- `make eval-jev EVAL_ARGS="--label after --compare results/jev-eval/2026-09-27-typesafe-jev-1.13 results/jev-eval/<date>-<model>-before"` -- expected: a distinct receipt with `comparison.md` (3.2 → A → B) and the verdict against the unchanged OQ-1 bar.

## Auto Run Result

Status: done

**Summary:** Jev now shares the labelled data's CI-platform convention, measured eval-first. Run A (`…-before`, the unchanged prompt, 174 calls, 0 errors) is the red eval: every `infra` platform-failure case was answered `external` (curl-infra-02, elixir-infra-01, fission-infra-01, nodejs-infra-01/02, playwright-infra-01, rails-infra-01/02 — 25 of 36 infra attempts), infra accuracy 0.306, 32 confident-wrong. The `infra`/`external` criteria in `prompts/jev-classes.yaml` then state that failures of the CI platform itself (action downloads, artifacts, the cache service, the provider's own API/storage) are `infra` while a third party is a service the project's build depends on, not the CI platform. Run B (`…-after`, 174 calls, 0 errors) is the green eval: **infra 0.306 → 0.806, confident-wrong 32 → 7, overall accuracy 0.536 → 0.674, external 1.000 held, evidence retention 38/38**. Both receipts are committed under distinct names with a generated `comparison.md` (3.2 → A → B). **Verdict: FAILED** against the unchanged OQ-1 bar — flaky is 0.000 (a flaky proof is never in one log; AD-11, owned by story 3.13), overall 0.674 < 0.90, worst class 0.000 < 0.80, injection 9/18 < 1.0, confident-wrong 7 > 0. Nothing was tuned, relabelled, dropped or moved to pass; `error_rate`, `sample_completeness` and `call_accounting` held.

**Files changed:**
- `prompts/jev-classes.yaml` — the CI-platform convention added to `infra` and `external` (the only prompt change; sha256 `eeee6826…` → `38ad81e7…`).
- `scripts/run_jev_eval.py` — `--label` (validated receipt-directory suffix) and repeatable `--compare` (reads each baseline's `summary.json`, writes `comparison.md`); `_receipt_dir` keeps the local-date fallback.
- `workflow/jev_eval.py` — `label` on `RunMeta`/`EvalSummary`, `receipt_name`/`slug`, the pure `render_comparison_md` + row helpers, the `label` header line.
- `Makefile` — `EVAL_ARGS` passthrough; `tests/workflow/test_jev_eval.py`, `tests/scripts/test_run_jev_eval.py` — the comparison/label tests.
- `results/jev-eval/2026-09-27-typesafe-jev-1.13-before/` and `…-after/` — the two receipts (`promptfoo-output.json`, `summary.json`, `summary.md`) plus run B's `comparison.md`.
- `results/README.md` — the latest receipt named; `docs/DEVELOPER.md` — the convention and the comparison. `docs/USER-GUIDE.md` — no change (maintainer tooling).

**Review findings breakdown:** 28 findings — 0 high, 0 medium, 21 low, 7 false, 0 maybe-false. 15 patch rows applied (the empty-date fallback restored and named; `--label` rejects an empty slug; `--compare` reports a non-receipt directory and refuses a self/duplicate baseline; the run label rendered in `summary.md`; tests for all of it plus a `None` metric). 13 rejected with recorded refutations in the Review Triage Log; nothing deferred.

**Follow-up review recommendation:** false — no `high` or `medium` entry was patched, so the work converged in this pass.

**Verification performed:** `make check` PASS — bootstrap; layer contract PASS; 8 schemas + state diagram byte-identical; ruff check+format clean; mypy --strict clean (57 source files); pylint duplicate-code 10.00/10; 810 passed, 66 deselected; coverage 95.06% ≥ 85%. Focused: `pytest tests/workflow/test_jev_eval.py tests/scripts/test_run_jev_eval.py` → 60 passed. Two full `make eval-jev` runs (174 real calls each, 0 errors), then both receipts re-derived from their committed raw outputs (`--from-output`, zero model calls) so they match the current code; the comparison was regenerated and the numbers are unchanged. I/O matrix audit: all 6 rows covered by passing tests or the committed receipts.

**Residual risks:** flaky stays 0.000 (no history; story 3.13) and the verdict stays FAILED — honest, not tuned; the 38 labelled cases remain a preliminary measurement (OQ-5); Jev cost is NULL (OQ-3); the two `promptfoo-output.json` dumps add ~13 MB to the repo, consistent with the committed 3.2 receipt pattern.
