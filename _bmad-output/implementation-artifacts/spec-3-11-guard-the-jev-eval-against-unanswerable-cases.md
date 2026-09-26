---
title: 'Story 3.11 — Guard the Jev eval against unanswerable cases'
type: 'feature'
created: '2026-09-27'
status: 'done'
baseline_revision: 'a359169f2c932d240d3c0787930754abf9d2ba12'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-3-context.md'
warnings: [oversized]
deferred: []
---

## Build Brief

**(1) Story:** 3.11 — Guard the Jev eval against unanswerable cases (sprint-status key `3-11-guard-the-jev-eval-against-unanswerable-cases`). Closes finding 2 of `sprint-change-proposal-2026-09-27.md`: the case generator never checks that a case's proof survived, so the eval scored Jev on cases it could not answer (16 labelled cases distilled to one bare exit-code line under four labels; 7 of 8 `unknown` cases shared the same runner-provisioner block). Story 2.13 fixed the distiller; this story makes the eval refuse bad input and record how much proof reached Jev. No model calls.

**(2) ACs in one line each:**
- AC1: the generator FAILS (non-zero, naming each case) when a labelled case's `key_line` does not survive distillation — except ids in `distiller-exceptions.yaml`, which are excluded from the generated cases and reported — or when two cases with different expected labels have identical distilled input; and the receipt (`workflow/jev_eval.py` summary) records the evidence-retention count (labelled cases whose proof reached Jev / all labelled cases).
- AC2: no two `unknown` cases share the same non-final content after normalising timestamps, run/worker ids, GUIDs, hex hashes and version numbers (draw cause-free lines from different parts of the log, deterministically); trick cases are built only on bases whose proof survives; the 3.2 receipt is kept unchanged and marked superseded in `results/README.md`.

**(3) Binding ADs:** AD-6 (payloads/`vars` are the contracts surface; the run still validates against the committed schema), AD-19 (no threshold literal — the generator and scorer read the one thresholds file), AD-20 (the distilled log is the only log form Jev sees; an `unknown` case carries no cause by the distiller's own definition), AD-7 (numbered lines are stable anchors). The eval's honest-verdict rules (AD-9/AD-18) are unchanged — no label, case or bar moves.

**(4) Files:**
- Change `scripts/build_jev_eval_cases.py` — the survival guard, the duplicate-input guard, exception handling, the unknown-window selection and the `key_line` var.
- Change `tests/scripts/test_build_jev_eval_cases.py` — AC1/AC2 guard tests.
- Change `workflow/jev_eval.py` — `Attempt.proof_present`, `EvalSummary.evidence_retained`/`evidence_total`, the retention computation, the summary line.
- Change `tests/workflow/test_jev_eval.py` — AC1 retention tests.
- Regenerate `test-data/jev-eval/cases.generated.yaml` (`make jev-eval-cases`).
- Change `test-data/jev-eval/README.md` — the unknown-case rule (different parts + uniqueness), the guard, the `key_line` var.
- Change `results/README.md` — mark the 3.2 receipt superseded.
- Change `docs/DEVELOPER.md` — "The Jev eval (story 3.2)" section (the guard, the retention count).

  **NOT touched:** the 3.2 receipt files under `results/jev-eval/2026-09-27-typesafe-jev-1.13/`; `test-data/jev-eval/manifest.yaml` `label`/`key_line`/`evidence`; `prompts/jev-classes.yaml`; `guardrails/thresholds.yaml` (no bar change); `workflow/distiller.py` (2.13 owns it); `agents/jev/eval_provider.py` (it reads only `repo` + `lines`; the new `key_line` var is never sent to the model); `scripts/run_jev_eval.py` (it passes the results through unchanged); the spine/spec/epics; `docs/USER-GUIDE.md`.

**(5) Approach (SOLID/DRY):**
- **One guard, one place (SOLID-S):** a pure `find_unanswerable(...)` in the generator returns the offending cases; `build_cases` raises a typed `UnanswerableCasesError` carrying them; `main` prints each and returns non-zero without writing. The `--check` path fails the same way (it calls `build_cases`).
- **The proof is carried on the case (DRY):** `_labelled_case` adds a `key_line` var (the manifest `key_line`, prefix-stripped) so the scorer can check — without reading the manifest — that the proof is in the lines Jev received. `Attempt.proof_present` is a bool computed in `build_attempt`; the lines are not duplicated into the receipt.
- **Exceptions are data, not code:** the generator reads `distiller-exceptions.yaml` (the 2.13 file), excludes those ids from `labelled`, skips them in the survival guard and reports them (stdout); no id is special-cased in code.
- **Unknown cases are spread, deterministically:** a rank-ordered scan (`start = rank * count`, then advance by `count`) picks the first window of `count` cause-free lines whose normalised signature is unused, so the cases draw from different parts of their logs and never collide.
- **Open/closed:** the guard is a named check (survival, duplicate input), not a growing `if/elif`; a future check is a new entry.

**(6) TDD plan (red-first; names cite ACs):**
- `tests/scripts/test_build_jev_eval_cases.py`:
  - `test_ac1_unanswerable_labelled_case_is_named_and_fails`
  - `test_ac1_generator_excludes_exception_ids_and_reports_them`
  - `test_ac1_two_labels_with_identical_distilled_input_fail`
  - `test_ac1_labelled_cases_carry_the_proof_key_line`
  - `test_ac1_trick_cases_are_built_only_on_surviving_bases`
  - `test_ac2_unknown_cases_are_unique_after_normalisation`
  - `test_ac2_unknown_cases_draw_from_different_parts_of_the_log`
  - `test_ac2_generated_file_stays_reproducible` (the existing reproducibility test, kept green)
- `tests/workflow/test_jev_eval.py`:
  - `test_ac1_summary_records_evidence_retention`
  - `test_ac1_evidence_retention_counts_only_labelled_cases`
  - `test_ac1_evidence_retention_drops_when_the_proof_is_missing`
  - `test_ac1_summary_md_records_evidence_retention`

**(7) Risks / OQ:** (i) the retention denominator is the labelled cases the run scores — the generated ones; exceptions are excluded by the generator and reported, so the count is 38/38 today (recorded reading, in the spec's Design Notes). (ii) The unknown window's cause-freeness is the distiller's marker definition (unchanged from 3.2); a warning line that names a failure but matches no marker can still land in a window — the existing no-cause test still guards it. (iii) `key_line` in the case vars is recorded in the promptfoo output and the receipt, but it is already public in the committed manifest and is never sent to the model. (iv) The guard must not fire on today's data (verified: 0 unanswerable labelled cases, 0 duplicate inputs after 2.13). No blocking OQ.

**(8) Doc impact:** `docs/DEVELOPER.md` — the Jev eval section gains the generator guard and the evidence-retention line; `test-data/jev-eval/README.md` — the unknown-case rule (different parts, uniqueness) and the guard; `results/README.md` — the 3.2 receipt is superseded by the next run. `docs/USER-GUIDE.md` — **no doc change**: maintainer tooling, no user-visible behaviour.

<intent-contract>

## Intent

**Problem:** The eval accepts cases whose proof never reached Jev: the generator never checks that a labelled case's `key_line` survives distillation, so Jev was scored on cases it could not answer (16 labelled cases distilled to one bare exit-code line under four labels), and 7 of 8 `unknown` cases shared the same runner-provisioner block. The score therefore measured the pipeline in front of Jev, not Jev.

**Approach:** Make the generator refuse unanswerable input — failing, non-zero and naming each case, when a labelled `key_line` does not survive distillation (except committed exceptions) or when two differently-labelled cases share identical distilled input — and build `unknown` cases from different parts of the log with unique normalised content; record the evidence-retention count in the receipt.

## Boundaries & Constraints

**Always:** the generator fails non-zero and names each unanswerable case (labelled `key_line` not in the distilled output, or two differently-labelled cases with identical distilled input); ids in `distiller-exceptions.yaml` are excluded from the generated cases and reported; trick cases use only bases whose proof survives; no two `unknown` cases share non-final content after normalising timestamps, run/worker ids, GUIDs, hex hashes and version numbers; the receipt records the evidence-retention count; the generated file stays byte-reproducible (`--check`); the thresholds come only from `guardrails/thresholds.yaml`.

**Never:** do not edit any `label`, `key_line` or `evidence` in `manifest.yaml`; do not edit `prompts/jev-classes.yaml`; do not edit the 3.2 receipt files; do not move a bar, relabel, drop a case or tune anything to pass; do not special-case case ids in code; no model calls in this story; `make eval-jev` must not join `make check`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Labelled proof survives | manifest log whose distilled output contains the `key_line` | case generated, carries its `key_line` var | No error expected |
| Labelled proof dropped | a labelled `key_line` not in the distilled output | generator exits non-zero, naming the case, nothing written | Fails loudly |
| Exception id | id listed in `distiller-exceptions.yaml` | case excluded from the generated file and reported | No error expected |
| Two labels, one input | two labelled cases with identical distilled lines and different labels | generator exits non-zero, naming both | Fails loudly |
| Unknown spread | 8 unknown sources | every case's non-final content unique after normalisation | No error expected |
| Trick base | trick source drawn from surviving labelled cases | base proof present in the trick's lines | No error expected |
| Receipt retention | labelled attempts with/without their proof in `lines` | `evidence_retained`/`evidence_total` recorded and rendered | No error expected |

</intent-contract>

## Code Map

- `scripts/build_jev_eval_cases.py:89` `build_cases`, `:138` `_labelled_case`, `:154` `_unknown_case`, `:174` `_trick_case`, `:196` `_cause_free_lines`, `:222` `_select_trick_sources`, `:266` `_one_per_repo`, `:293` `main` -- the generator: add the guard, the exception handling, the unknown-window selection, the `key_line` var.
- `test-data/jev-eval/distiller-exceptions.yaml` -- the committed exceptions list (2.13); read by the generator; `id` + `reason` + `status`.
- `test-data/jev-eval/manifest.yaml` -- the 38 labelled entries (`id`, `label`, `log_file`, `key_line`); read-only.
- `workflow/distiller.py:190` `distill` -- the real distiller the generator runs; reuse, do not edit.
- `workflow/jev_eval.py:92` `Attempt`, `:293` `build_attempt`, `:359` `score_attempts`, `:418` `render_summary_md`, `:438` `_header_lines` -- add `proof_present`, the retention fields and the summary line.
- `tests/scripts/test_build_jev_eval_cases.py` -- the generator tests (`_cases`, `_of_kind`, `_manifest` helpers; the reproducibility and no-cause tests must stay green).
- `tests/workflow/test_jev_eval.py` -- the scorer tests; the attempt-building helper/fixtures are reused for the retention tests.
- `results/README.md` -- the receipts index; add the superseded note.
- `test-data/jev-eval/README.md:15` -- "The generated eval cases (story 3.2)"; update the unknown-case rule and add the guard.
- `docs/DEVELOPER.md` -- "The Jev eval (story 3.2)" section.

## Tasks & Acceptance

**Execution:**
- `scripts/build_jev_eval_cases.py` -- add `find_unanswerable` + `UnanswerableCasesError`, read the exceptions file (exclude + report), add the `key_line` var to labelled cases, spread the unknown windows with normalised uniqueness, draw trick sources from surviving labelled cases -- AC1/AC2.
- `tests/scripts/test_build_jev_eval_cases.py` -- the AC1/AC2 generator tests from brief §6, red-first -- AC1/AC2 proof.
- `workflow/jev_eval.py` -- `Attempt.proof_present`, `EvalSummary.evidence_retained`/`evidence_total`, `_evidence_retention`, the summary line -- AC1.
- `tests/workflow/test_jev_eval.py` -- the retention tests -- AC1 proof.
- `test-data/jev-eval/cases.generated.yaml` -- regenerate with `make jev-eval-cases` -- keeps the drift gate green.
- `results/README.md`, `test-data/jev-eval/README.md`, `docs/DEVELOPER.md` -- per brief §8.

**Acceptance Criteria:**
- Given the labelled manifest and the real distiller, when the generator builds the eval cases, then it fails non-zero naming each case whose `key_line` does not survive distillation (except reported exceptions) or whose distilled input duplicates a differently-labelled case, and the receipt records the evidence-retention count (AC1).
- Given the `unknown` and trick builders, when cases are generated, then no two `unknown` cases share non-final content after normalising timestamps, run/worker ids, GUIDs, hex hashes and version numbers, every trick case is built only on a base whose proof survives, and the 3.2 receipt is kept unchanged and marked superseded in `results/README.md` (AC2).

## Spec Change Log

## Review Triage Log

### 2026-09-27 — Review pass
- verdicts: 40 findings — high 0, medium 3, low 27, false 10, maybe-false 0
- findings:
  - `[medium]` `[patch]` `package.json` unpins promptfoo (`0.123.1` → `^0.123.1`) and `package-lock.json` loses 244 lines — an unintended, out-of-scope toolchain change (AGENTS.md "pinned versions win"); revert both files to the baseline.
  - `[medium]` `[patch]` `_unknown_window`'s terminal `return free[:count]` bypasses the `used` signature check, so a collision can ship two `unknown` cases with identical non-final content — the exact AC2 violation the story forbids; refuse (typed error) instead, and test the collision path.
  - `[low]` `[patch]` a short log yields a window shorter than `UNKNOWN_SETUP_LINES` (possibly empty) — same fix: refuse when no unique full window exists.
  - `[low]` `[patch]` the docstring claims "run/worker ids" while the code strips digit runs (which covers them) — name the mapping.
  - `[low]` `[patch]` proof matching is a substring check and an empty `key_line` matches everything — add an empty-proof guard; keep substring (the 2.13 acceptance metric) and document it.
  - `[low]` `[patch]` the offset fallback can take an earlier window than a previous rank, so the docs' "different parts" is not exact — reword the docs; uniqueness is the hard rule.
  - `[low]` `[patch]` `excluded_exception_ids` validates only the top-level type and silently ignores a stale id — validate entries, raise a typed error, and assert ids exist in the manifest.
  - `[low]` `[patch]` the duplicate-input signature is the joined text, not the exact line set — use a tuple-of-lines signature.
  - `[low]` `[reject]` the `--check` refusal path is untested — the guard is directly tested through `build_cases`, `--check` calls `build_cases` first, and `main`'s handler is a 4-line print/return bound to the module `ROOT`, so a regression is caught by the guard tests.
  - `[low]` `[patch]` the new tests call private helpers (`_normalise_unknown`, `_one_per_repo`, `_cause_free_lines`, `_read_log`) and replay `_unknown_window`'s stride — assert through `build_cases` with an independent normaliser in the test.
  - `[low]` `[patch]` `main` re-reads the exceptions file and never prints the exclusions on the refusal path — expose the excluded ids from `build_cases` and report them before the refusal check.
  - `[false]` `[reject]` the spec's `oversized` warning is unaddressed — it is machine-readable orchestration metadata; the Design Notes carry the relevant design.
  - `[false]` `[reject]` `proof_present` is per-attempt while retention is per-case — promptfoo repeats a case with identical vars, so the flag is uniform and `any` vs `all` cannot differ.
  - `[false]` `[reject]` "`key_line` never sent to the model" is unenforced — `agents/jev/eval_provider.py` builds the pack from `repo` + `lines` only (verified), so the var cannot reach the model, and that provider's own tests pin the shape.
  - `[low]` `[patch]` `_unknown_window`'s fallback can duplicate or degenerate (edge-case layer) — same root cause and fix as the medium fallback row.
  - `[low]` `[patch]` exception entries are unvalidated (edge-case layer) — same as the exceptions-validation row.
  - `[low]` `[patch]` an empty proof substring-matches (edge-case layer) — same as the proof-matching row.
  - `[low]` `[patch]` substring matching inflates retention (edge-case layer) — same as the proof-matching row.
  - `[low]` `[patch]` exceptions are unreported on the refusal path (edge-case layer) — same as the `main` row.
  - `[low]` `[patch]` `package.json` caret range (edge-case layer) — same as the toolchain row.
  - `[low]` `[patch]` `package-lock.json` churn (edge-case layer) — same as the toolchain row.
  - `[low]` `[patch]` the fallback violates the uniqueness claim (edge-case layer) — same as the medium fallback row.
  - `[medium]` `[patch]` the collision and fallback paths of `_unknown_window` have no coverage and the terminal fallback can ship a duplicate (verification-gap, pre-verified) — same fix as the medium fallback row, plus a crafted-collision test and a short-log test.
  - `[low]` `[patch]` `package.json`/`package-lock.json` unpin (verification-gap) — same as the toolchain row.
  - `[false]` `[reject]` a pre-3.11 receipt re-scored would render `0/0` — a real re-score of an old raw output has 38 labelled cases with no `key_line` var, so it honestly renders `0/38`; `0/0` needs zero labelled attempts, which no run produces.
  - `[false]` `[reject]` retention is measured at the case-data surface, not the model boundary (intent-alignment) — the provider receives the case vars verbatim and builds the pack from `lines`, so the case-data check is the boundary check; a provider-boundary check would duplicate `test_eval_provider`.
  - `[low]` `[patch]` substring vs line membership (intent-alignment) — same as the proof-matching row.
  - `[low]` `[patch]` uniqueness as an enforced invariant (intent-alignment) — same as the medium fallback row.
  - `[false]` `[reject]` "different parts" is weakly served (a laravel window lands on marker-free docker-retry warnings) — cause-freeness is the distiller's marker definition, the 3.2 recorded reading the AC's parenthetical endorses, and the no-cause test still guards it.
  - `[false]` `[reject]` the receipt does not name the superseded baseline (intent-alignment) — the intent's parenthetical describes the *next* run's summary, which story 3.12 produces; 3.11's obligation is the `results/README.md` note, done.
  - `[false]` `[reject]` the retention denominator is the run's labelled cases, not the manifest's (intent-alignment) — the spec records this reading; with exceptions empty the two coincide (38/38) and DEVELOPER.md states the denominator explicitly.
  - `[low]` `[patch]` the `package.json` change has no reading under the intent (intent-alignment) — same as the toolchain row.
  - `[false]` `[reject]` the negative-path tests use crafted roots, not the real manifest (intent-alignment) — a guard can only be exercised on data that trips it; the real manifest is covered by the positive-path and reproducibility tests.
  - `[low]` `[patch]` `package.json`/`package-lock.json` unpin (clean-code) — same as the toolchain row.
  - `[low]` `[patch]` tests drive private helpers (clean-code) — same as the test-surface row.
  - `[low]` `[patch]` the fallback swallows the error the guard exists to surface (clean-code) — same as the medium fallback row.
  - `[low]` `[patch]` `excluded_exception_ids` raises a bare `ValueError` (clean-code) — same as the exceptions-validation row (typed error).
  - `[low]` `[patch]` `main` reads the exceptions file twice (clean-code) — same as the `main` row.
  - `[low]` `[patch]` substring proof matching (clean-code) — same as the proof-matching row.
  - `[low]` `[patch]` `find_unanswerable` hardcodes two sequential loops instead of the open/closed check entries the brief promised — iterate a tuple of named check functions.
- patch pass applied: all 30 `patch` rows fixed as their row describes — the toolchain change reverted (`package.json` + `package-lock.json` back to the baseline pin), `_unknown_window` now refuses (`NoUniqueUnknownWindowError` → `UnanswerableCasesError`) instead of returning a non-unique/short window (with collision and short-log tests), the proof check guards an empty `key_line` and the duplicate check uses an exact tuple-of-lines signature, `excluded_exception_ids` validates entries and rejects a stale id (typed `MalformedExceptionsError`), `build_cases` exposes the excluded ids so `main` reads the file once and reports them on the refusal path too, the new tests assert through `build_cases` with a test-local normaliser, `find_unanswerable` iterates named checks, and the normaliser docs/README state the run/worker-id → digit-run mapping and uniqueness as the hard rule. Re-verified: `make check` PASS (798 passed, coverage 95.00%) and the drift gate byte-identical.

## Design Notes

**Evidence retention.** A labelled case's proof reaches Jev when the manifest `key_line` is in the numbered lines the case sends. `_labelled_case` writes the prefix-stripped `key_line` into the case vars; `build_attempt` sets `Attempt.proof_present`; `score_attempts` records `evidence_retained` (distinct labelled cases with the proof present) over `evidence_total` (distinct labelled cases in the run). The denominator is the labelled cases the run scores — the generated ones — because the generator excludes committed exceptions from the generated file and reports them; today the count is 38/38.

**Unknown spread.** `_normalise_unknown(text)` strips ISO timestamps, GUIDs, hex runs (>= 7 chars), version numbers and digit runs, then collapses whitespace. For the rank-th unknown source, the window starts at `rank * count` and advances by `count` until its normalised signature is unused, so the eight cases draw from different parts of their logs deterministically.

```
start = rank * count
while start + count <= len(free):
    window = free[start:start + count]
    if normalise("\n".join(window)) not in used: return window
    start += count
```

## Verification

**Commands:**
- `.venv/bin/pytest tests/scripts/test_build_jev_eval_cases.py tests/workflow/test_jev_eval.py -q` -- expected: all AC-named tests pass.
- `make jev-eval-cases && .venv/bin/python scripts/build_jev_eval_cases.py --check` -- expected: writes the file, then PASS (byte-identical).
- `make check` -- expected: PASS (bootstrap, layer contract, schema + state-diagram drift, ruff, mypy --strict, pylint duplicate-code, pytest ≥85%).

## Auto Run Result

Status: done

**Summary:** The eval now refuses input Jev cannot answer. `scripts/build_jev_eval_cases.py` fails non-zero, naming each case, when a labelled case's `key_line` does not survive distillation or when two differently-labelled cases distil to the same lines; committed `distiller-exceptions.yaml` ids are excluded from the generated cases and reported (no id is special-cased in code). Labelled cases carry a prefix-stripped `key_line` var so the scorer can check the proof reached the classifier; `workflow/jev_eval.py` records `evidence_retained`/`evidence_total` (38/38 today) and renders an `evidence retention:` line. The eight `unknown` cases now draw cause-free windows from different parts of their logs with pairwise-unique normalised content, and the generator refuses rather than emit a duplicate or short window. Trick cases are built only on bases whose proof survives. The 3.2 receipt is untouched and marked superseded in `results/README.md`.

**Files changed:**
- `scripts/build_jev_eval_cases.py` — `find_unanswerable` (named checks), `UnanswerableCasesError`, `excluded_exception_ids` (validated, stale-id check), the `key_line` var, `_unknown_window`/`_normalise_unknown`, `BuiltCases`, the refusal path in `main`.
- `workflow/jev_eval.py` — `Attempt.proof_present`, `EvalSummary.evidence_retained`/`evidence_total`, `_evidence_retention`, `_proof_present`, the summary line.
- `tests/scripts/test_build_jev_eval_cases.py`, `tests/workflow/test_jev_eval.py` — AC-named guard, exception, duplicate, proof, unknown-uniqueness/spread and retention tests.
- `test-data/jev-eval/cases.generated.yaml` — regenerated (`make jev-eval-cases`).
- `results/README.md` — the 3.2 receipt marked superseded; `test-data/jev-eval/README.md`, `docs/DEVELOPER.md` — the guard, the retention count, the unknown-spread rule. `docs/USER-GUIDE.md` — no change (maintainer tooling).

**Review findings breakdown:** 40 findings — 0 high, 3 medium, 27 low, 10 false, 0 maybe-false. 30 patch rows applied (the two medium groups: revert the unintended `package.json`/`package-lock.json` unpin, and make `_unknown_window` refuse instead of emitting a duplicate/short window; plus the exceptions-file validation, the empty-proof guard and exact duplicate signature, the single exceptions read reported on the refusal path, the tests moved onto the public surface, the open/closed checks and the doc wording). 10 rejected with recorded refutations in the Review Triage Log; nothing deferred.

**Follow-up review recommendation:** true — two `medium` entries were patched. Named unverified risk: the generator's new refusal path and the reverted toolchain are proven by unit tests and `make check`, but the *next* eval run (story 3.12) is the first end-to-end exercise of the guarded generator (and of the retention line) against real promptfoo output.

**Verification performed:** `make check` PASS — bootstrap; layer contract PASS; 8 schemas + state diagram byte-identical; ruff check+format clean; mypy --strict clean (57 source files); pylint duplicate-code 10.00/10; 798 passed, 66 deselected; coverage 95.00% ≥ 85%. Focused: `pytest tests/scripts/test_build_jev_eval_cases.py tests/workflow/test_jev_eval.py` → 59 passed. `make jev-eval-cases` then `--check` → byte-identical. No model calls; the 3.2 receipt files are byte-unchanged. I/O matrix audit: all 7 rows covered by passing AC-named tests.

**Residual risks:** the retention denominator is the run's labelled cases (exceptions would shrink it; the spec records the reading); the unknown window's cause-freeness is the distiller's marker definition (a marker-free warning line can land in a window, guarded by the no-cause test); `key_line` in the case vars is recorded in the promptfoo output but is public in the committed manifest and never sent to the model.
