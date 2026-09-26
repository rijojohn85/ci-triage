---
title: 'Story 2.13 — Distil real GitHub Actions logs across stacks'
type: 'bugfix'
created: '2026-09-27'
status: 'done'
baseline_revision: 'c33d0153c5e1a647abd58086de630dc66bd1a12a'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
warnings: [oversized]
deferred:
  - summary: >-
      Regenerating `test-data/jev-eval/cases.generated.yaml` (story 2.13) makes the
      committed story 3.2 eval receipts unreproducible from the new cases.
    evidence: |-
      The receipts under `results/jev-eval/2026-09-27-typesafe-jev-1.13/` were produced
      from the pre-2.13 distilled lines; the regenerated cases carry prefix-stripped
      lines, so a re-run cannot reproduce those receipts. Story 3.11 owns the
      resolution: it keeps the 3.2 receipt unchanged as the historical baseline and
      marks it superseded in `results/README.md`.
    location: >-
      results/jev-eval/2026-09-27-typesafe-jev-1.13/
    severity: low
---

## Build Brief

**(1) Story:** 2.13 — Distil real GitHub Actions logs across stacks (sprint-status key `2-13-distil-real-github-actions-logs-across-stacks`). Fixes the verified root cause from `sprint-change-proposal-2026-09-27.md` finding 1: real GitHub Actions lines start with an ISO-8601 runner timestamp, so every `^`-anchored `ERROR_MARKERS` pattern never matches, and the markers only know Python-style errors. Measured today: the manifest `key_line` survives distillation in **15/38** labelled cases.

**(2) ACs in one line each:**
- AC1: a real line `2026-…Z <text>` is marker-matched on `<text>` and emitted as `<text>` (prefix stripped); prefix-less logs behave exactly as before (every existing 2.5 test stays green, unchanged); the strip is linear-time.
- AC2: each failure style found in the committed real logs gets exactly one new `ERROR_MARKERS` registry entry (open/closed, no `if/elif`), each pattern linear-time on adversarial input; and the real distiller over every manifest log keeps the manifest `key_line` (target 38/38), except ids in a committed, human-approved exceptions list.

**(3) Binding ADs:** AD-20 (distiller keeps error blocks/stack traces, drops narrative, strips ANSI/control **and CI-runner line prefixes (timestamps)**, numbers lines, bounds by `distiller.max_bytes`; the kept lines stay untrusted) — this is the rule the story makes true; AD-19 (the byte bound comes only from `guardrails/thresholds.yaml`; no literals); AD-24 (the numbered distilled lines are the evidence-pack log); AD-7 (line numbers are stable citation anchors — truncation never renumbers).

**(4) Files:**
- Change `workflow/distiller.py` — add the runner-prefix strip and the new registry entries.
- Change `tests/security/test_distiller.py` — add AC1/AC2 tests (existing tests untouched).
- Create `test-data/jev-eval/distiller-exceptions.yaml` — committed exceptions list (empty if the target is met), read by the acceptance test and extended by story 3.11.
- Regenerate `test-data/jev-eval/cases.generated.yaml` via `make jev-eval-cases` (the distilled output changed; the 3.2 drift gate must stay green).
- Change `docs/DEVELOPER.md` — the distiller section (brief §8).

  **NOT touched:** `scripts/build_jev_eval_cases.py` logic (only its generated output changes), `workflow/evidence_collection.py` (reuses `distill`), `guardrails/thresholds.yaml`, `contracts/`, `guardrails/schemas/`, `manifest.yaml` labels/`key_line`/`evidence`, the spine/spec/epics, and `results/jev-eval/**`.

**(5) Approach:**
- Strip the runner prefix **once**, in the cleaning step that already runs over the whole CI text, so both marker matching and emission see the stripped line (one place, DRY; SOLID-S — the distiller stays a pure text transform). Prefix regex ≈ `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z ` applied per line; linear-time. JUnit evidence has no runner prefix and is unaffected.
- Extend the **one ordered registry** `ERROR_MARKERS` with one entry per failure style present in `test-data/jev-eval/logs/` (open/closed; a new style is a new entry, never a branch). Styles verified from the real logs: Go `--- FAIL:`, Dart/Flutter `error •`, apt/dpkg `E: `, Playwright `N) [`, Elixir/Mix `** (Mix)`, `GitHub API error:`, `Cache error:`, Node test-runner `Command:`, `Could not `, `cause: `, the generic uppercase `FAILED` result line (kind download verify, cargo test), and the Rails API-doc lint line. Each is anchored or token-shaped so it stays precise; the existing per-line scan cap (`_MAX_MARKER_SCAN_CHARS`) is unchanged.
- **Acceptance test:** run the real distiller (`workflow.distiller.distill`, the real `load_thresholds().distiller`) over every manifest log and assert the manifest `key_line` with its timestamp prefix removed appears in the distilled output (substring of the joined line texts — the same metric as the 15/38 baseline). Ids in `distiller-exceptions.yaml` are excluded and reported.
- Keep every existing marker and every existing 2.5 test unchanged; the change only alters behaviour for prefix-bearing input and for the newly-registered styles.

**(6) TDD plan (red-first; names cite ACs), all in `tests/security/test_distiller.py`:**
- `test_ac1_runner_timestamp_prefix_is_stripped_from_emitted_line`
- `test_ac1_marker_matches_after_timestamp_prefix_is_stripped`
- `test_ac1_log_without_prefix_is_unchanged`
- `test_ac1_timestamp_strip_is_linear_time` (long adversarial timestamp-like line, bounded time)
- `test_ac2_<style>_failure_line_is_kept` — one test per new style, each asserting the real excerpt's failure line survives and its neighbours that are narrative do not
- `test_ac2_every_new_pattern_is_linear_time` — adversarial input per new pattern
- `test_ac2_manifest_key_lines_survive_real_distillation` — the 38/38 acceptance test
- `test_ac2_exceptions_file_shape` — ids are unique and each entry carries `reason` + `status`

**(7) Risks / OQ:** (i) a `key_line` may be human prose with no machine failure shape; `distiller-exceptions.yaml` (`id` + `reason` + `status: pending-human-approval`) is the sanctioned escape hatch — target 0 entries, and the prototype reached 38/38 without it. (ii) Marker breadth vs precision: each marker must trace to a real failure line; the scan cap and linear-time tests bound the cost. (iii) `make jev-eval-cases` rewrites the committed cases file — expected in this story. (iv) The TAP `not ok`, `npm ERR!` and Rust `error[E…]` styles named in the epic's AC are **absent from the committed logs** (verified by search), so no fixture can be cut for them and no marker is added; this is reported. No blocking OQ.

**(8) Doc impact:** `docs/DEVELOPER.md` — extend "Distilling CI logs (story 2.5)": the runner-timestamp prefix rule (AD-20 clarification), how to add a marker (one registry entry, linear-time, with a real-log fixture), and the manifest key_line acceptance test + exceptions file. `docs/USER-GUIDE.md` — **no doc change**: the distiller is internal and no user-visible behaviour changes.

<intent-contract>

## Intent

**Problem:** Real GitHub Actions log lines begin with the runner's ISO-8601 timestamp, so every `^`-anchored `ERROR_MARKERS` pattern never matches, and the marker set only knows Python-style errors. The distiller therefore drops the failing line of real logs from most stacks, and agents receive only the exit code instead of the evidence that explains the failure (manifest `key_line` survives in 15/38 labelled cases).

**Approach:** Make the distiller strip the CI-runner line prefix before marker matching and from the emitted line (AD-20), and add one `ERROR_MARKERS` registry entry per failure style found in the committed real logs (open/closed), so the failing line of every common stack survives.

## Boundaries & Constraints

**Always:** marker matching and the emitted line both ignore the runner's ISO-8601 line prefix; prefix-less logs behave exactly as before; a new style is a new registry entry, never a branch; every pattern stays linear-time on adversarial input; the byte bound comes only from `guardrails/thresholds.yaml`; the manifest `key_line` survives for every labelled case (or the case is in the committed exceptions list with a reason); line numbers stay stable.

**Never:** edit `manifest.yaml` `label`/`key_line`/`evidence`; special-case case ids in code; weaken a `key_line`; change the spine/spec/epics; add a threshold literal; touch the 3.2 receipt files; change existing markers or existing 2.5 tests.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Timestamped marker line | `2026-09-21T18:28:16.9542359Z ERROR: boom` | matched on `ERROR: boom`; emitted as `ERROR: boom` | No error expected |
| Timestamped narrative line | `2026-…Z INFO compiling` | dropped (unchanged) | No error expected |
| Prefix-less line | `ERROR: boom` | kept exactly as before | No error expected |
| New-style marker (timestamped) | `2026-…Z --- FAIL: TestX (0.02s)` | kept; prefix stripped | No error expected |
| Adversarial long line | 50k-char timestamp-like line | linear-time scan; bounded by `max_bytes` | No error expected |
| No marker, no JUnit | narrative-only log | fallback last line, prefix stripped | No error expected |
| JUnit evidence | `<failure>…</failure>` | unchanged (no runner prefix) | DTD/ENTITY still skipped |

</intent-contract>

## Code Map

- `workflow/distiller.py:36` -- `ERROR_MARKERS`, the one ordered registry; extend with new entries. `:25` `_ANSI_ESCAPE`, `:33` `_CONTROL_CHARS`, `:71` `_strip_controls` -- the cleaning step where the runner-prefix strip lands. `:68` `_MAX_MARKER_SCAN_CHARS` -- the per-line cap that keeps matching linear. `:78` `_matches_error_marker`, `:85` `_evidence_text_lines`, `:146` `_fallback_lines`, `:190` `distill` -- the paths that must see stripped lines.
- `workflow/thresholds.py` -- `DistillerLimits` + `load_thresholds()`; the real `distiller.max_bytes` (65536) the acceptance test must use. Reuse, do not edit.
- `workflow/evidence_collection.py:98` -- the other `distill` caller (2.7); no change needed.
- `tests/security/test_distiller.py` -- the 2.5 test home; add AC1/AC2 tests here, keep every existing test verbatim.
- `test-data/jev-eval/manifest.yaml` -- 38 labelled entries with `id`, `stack`, `label`, `log_file`, `key_line`; read-only source of the acceptance test.
- `test-data/jev-eval/logs/*.log` -- the committed real logs the fixtures are cut from and the acceptance test runs over.
- `test-data/jev-eval/distiller-exceptions.yaml` -- new committed exceptions list (`id`/`reason`/`status`).
- `scripts/build_jev_eval_cases.py:33,134,202` -- imports `ERROR_MARKERS`/`distill`; its output `cases.generated.yaml` changes when markers/output change (regenerate via `make jev-eval-cases`); no code change.
- `tests/scripts/test_build_jev_eval_cases.py:99` -- the unknown-case no-cause test reads `ERROR_MARKERS`; keep green.
- `Makefile:jev-eval-cases` -- `make jev-eval-cases` regenerates the committed cases file.
- `docs/DEVELOPER.md:476` -- "Distilling CI logs (story 2.5)" section to extend.

## Tasks & Acceptance

**Execution:**
- `workflow/distiller.py` -- add the runner-prefix strip in the cleaning step (one place, applied to the CI text) and one new `ERROR_MARKERS` entry per real failure style -- AC1/AC2.
- `tests/security/test_distiller.py` -- add the AC1/AC2 tests from brief §6, red-first, each fixture cut from a committed log -- AC1/AC2 proof.
- `test-data/jev-eval/distiller-exceptions.yaml` -- create the committed exceptions list (empty when the target is met) with the documented shape -- AC2.
- `test-data/jev-eval/cases.generated.yaml` -- regenerate with `make jev-eval-cases` -- keeps the 3.2 drift gate green.
- `docs/DEVELOPER.md` -- extend the distiller section per brief §8.

**Acceptance Criteria:**
- Given a real GitHub Actions line with the runner timestamp prefix, when the distiller matches markers, then it matches on the prefix-stripped text and emits the line without the prefix, and a prefix-less log behaves exactly as before (AC1).
- Given the committed real logs, when the distiller runs, then each stack's failure line is kept by one new `ERROR_MARKERS` entry (open/closed, linear-time), and the manifest `key_line` survives distillation for every labelled case except committed exceptions (target 38/38) (AC2).

## Spec Change Log

## Review Triage Log

### 2026-09-27 — Review pass
- verdicts: 34 findings — high 0, medium 1, low 25, false 8, maybe-false 0
- findings:
  - `[low]` `[patch]` `cause: ` is an unanchored substring that also matches the word `because: ` — real collision, though no committed log contains `because: ` (the 4 `cause: ` hits are uv/pip cause lines); anchor it (`^\s*cause: `) in the marker-precision batch.
  - `[low]` `[patch]` new unanchored markers sweep narrative into the distilled output — verified: `Could not ` keeps 25 `WARNING: Could not open the configuration file…` lines in fission-flaky-01 (267→292); the larger growth (flutter-code-01 225, tokio-ext-01 155) is genuine analyzer/apt error lines, and the k8s-YAML continuations are pre-existing (`\w*(Error|Exception)`); anchor the broad markers.
  - `[low]` `[patch]` the claim "A log without the prefix behaves exactly as before" is now misleading — true for the prefix strip itself, but the new markers also change prefix-less logs; qualify the DEVELOPER.md sentence.
  - `[low]` `[patch]` `test_ac2_exceptions_file_shape` hard-codes `status == "pending-human-approval"`, so an approved exception would fail it — the file is empty today; allow the documented approved state.
  - `[low]` `[patch]` the acceptance test never checks exception ids exist in the manifest — a stale id is silently ignored; assert ids ⊆ manifest ids.
  - `[low]` `[patch]` `_manifest_by_id()`/`_key_line()` re-parse the manifest per call (38×) — test hygiene; load once.
  - `[low]` `[patch]` the acceptance test strips the expected key_line with the private `distiller._RUNNER_LINE_PREFIX` — AGENTS.md requires the public interface; the manifest key_lines are already prefix-free so the self-fulfilling risk is moot, but the coupling is real; strip with an independent literal regex in the test.
  - `[low]` `[patch]` the linearity proof shares one 2 s budget across all 12 patterns — make it per-pattern (parametrized) so a single slow pattern cannot hide in the total.
  - `[false]` `[reject]` `_strip_runner_prefix` "manufactures leading whitespace" that changes continuation semantics — after the strip a line is exactly what the runner wrote; an indented line continues a kept block only when the previous line was kept, which is the documented continuation rule and identical to prefix-less behaviour.
  - `[false]` `[reject]` the timestamp regex is GitHub-UTC-only (offsets, tabs, multi-space, bare EOL) — the GitHub Actions runner always writes `Z ` + text (verified across all 38 committed logs); supporting unseen variants adds surface with no demonstrated need.
  - `[false]` `[reject]` the TAP `not ok`, `npm ERR!` and Rust `error[E…]` styles named in the epic AC are dropped with no follow-up — a search of all 38 logs finds 0 occurrences; the spec's Build Brief §7 records this, and a marker with no real fixture would be untested surface.
  - `[false]` `[reject]` per-style tests use fixture limits while the acceptance test uses the real bound — the AC requires the real bound in the acceptance test (it does); the fixture bound is the repo's unit-test convention and the slices are 3 lines.
  - `[low]` `[reject]` `_log_slice` hard-codes 1-based line ranges — latent brittleness if a committed log is ever re-truncated; the smallest fix is a helper rewrite (more than a direct correction) and the logs are immutable in-repo, so developers will not meet it in normal use.
  - `[low]` `[defer]` regenerating `cases.generated.yaml` makes the 3.2 receipts unreproducible — story 3.11 owns this: it keeps the 3.2 receipt unchanged as the historical baseline and marks it superseded in `results/README.md`; recorded in `deferred`.
  - `[low]` `[patch]` the new 2.13 row sits between the 2.5 and 2.6 rows in the DEVELOPER.md story table — move it after 2.6.
  - `[low]` `[patch]` the linearity input never drives the seconds group (`\d{2}`) — fold into the per-pattern linearity batch.
  - `[low]` `[patch]` a non-runner line whose text starts with an ISO-8601 token is truncated — intended behaviour (the prefix is runner metadata by shape); the fix is the doc qualification, not code.
  - `[false]` `[reject]` a runner timestamp not followed by exactly one space leaves a residual prefix — the runner emits exactly `Z ` (verified); no committed log has a tab or double space after the timestamp.
  - `[low]` `[patch]` `cause: ` matches `because: ` (edge-case layer) — same root cause and fix as the first row.
  - `[low]` `[patch]` unanchored markers sweep narrative (edge-case layer) — same root cause as the second row.
  - `[low]` `[patch]` a malformed exceptions file yields a confusing error — guard with a clear assertion (same batch as the exceptions-shape fix).
  - `[low]` `[patch]` the "prefix-less behaves exactly as before" claim is false (edge-case layer) — same root cause as row three.
  - `[medium]` `[patch]` `scripts/build_jev_eval_cases.py::_cause_free_lines` matches markers on the raw, still-timestamped line while the distiller's "error line" is now the prefix-stripped line — pre-verified by the verification-gap layer; the committed file is currently clean, but a future log whose early lines carry an anchored-marker failure would embed a cause line in an `unknown` case undetected. Fix: strip the prefix before `marker.search` (keep the raw line emitted) and extend the unknown-case test.
  - `[low]` `[patch]` `cause: ` matches `because: ` (verification-gap "other findings") — duplicate of the first row.
  - `[false]` `[reject]` a bare timestamp at end-of-line keeps its prefix and can surface as the fallback line — the runner never writes a bare timestamp line (verified); a line with no message is not produced.
  - `[low]` `[patch]` the broad markers keep narrative and nothing bounds narrative volume (intent-alignment) — same root cause as the marker-precision batch; the measured 2.13 delta is 25 narrative lines, the rest of the growth is genuine error lines.
  - `[low]` `[patch]` the acceptance test reaches into a private regex (intent-alignment) — duplicate of the test-seam row.
  - `[low]` `[patch]` the ReDoS coverage is one aggregate test, not per-pattern (intent-alignment) — duplicate of the linearity row.
  - `[low]` `[patch]` no statement of the 2.7 evidence-pack test check — the check was done (no test feeds a timestamped log; `make check` green with all evidence tests unchanged); recorded in the Auto Run Result.
  - `[false]` `[reject]` extras beyond the letter of the intent (spec artifact, README row, extra AC1 test) — the spec artifact is required by the workflow, the README row keeps the folder listing truthful, and the extra test strengthens coverage; none is a defect.
  - `[false]` `[reject]` 38/38 and `make check` unverifiable from the diff — the parent ran both: `make check` PASS (768 passed, coverage 94.96%) and the acceptance test passes.
  - `[low]` `[patch]` `Could not `/`cause: `/`\bFAILED\b` precision (clean-code) — duplicate of the marker-precision batch.
  - `[low]` `[patch]` `_key_line` uses a private attribute (clean-code) — duplicate of the test-seam row.
  - `[low]` `[patch]` the comment in `test_ac1_marker_matches_after_timestamp_prefix_is_stripped` names the anchored `FAILED ` marker although `\bFAILED\b` is unanchored — reword it to name the marker the test actually relies on.
- patch pass applied: all 24 `patch` rows fixed as their row describes — the three loose markers anchored (`^Could not `, `^\s*cause: `, `\bFAILED\s*$`), the "prefix-less behaves exactly as before" claim qualified, the exceptions-file test widened (approved status, ids ⊆ manifest, malformed-file guard), the test seam moved off the private regex with the manifest parsed once, the linearity proof parametrized per pattern with a seconds-group input, the comment reworded, `_cause_free_lines` matching on the prefix-stripped line, and the DEVELOPER.md 2.13 row moved after 2.6. Re-verified: `make check` PASS (780 passed, coverage 94.96%) and the 38/38 acceptance test green.

## Design Notes

The prefix is stripped in the one cleaning pass so there is a single place that decides what a "line" is: `_matches_error_marker`, `_evidence_text_lines`, `_fallback_lines` and the emitted text all read the cleaned lines. Stripping per-marker or per-emitter would duplicate the rule (DRY) and let matching and emission diverge.

```python
_RUNNER_LINE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z ")
# applied once, per line, inside the cleaning step:
cleaned = "\n".join(_RUNNER_LINE_PREFIX.sub("", line) for line in _strip_controls(ci_log).split("\n"))
```

Registry entries are anchored (`^--- FAIL: `, `^Could not `, `^\s*cause: `) or token-shaped (`error •`, `Cache error:`) so a narrative line that merely mentions a word is not swept in; the scan cap keeps even a token-shaped pattern linear on a hostile long line.

## Verification

**Commands:**
- `.venv/bin/pytest tests/security/test_distiller.py tests/scripts/test_build_jev_eval_cases.py -q` -- expected: all pass; existing 2.5 tests unchanged and green; AC-named tests green.
- `make jev-eval-cases && .venv/bin/python scripts/build_jev_eval_cases.py --check` -- expected: writes the file, then PASS (byte-identical).
- `make check` -- expected: PASS (bootstrap, layer contract, schema/state-diagram drift, ruff, mypy --strict, pylint duplicate-code, pytest ≥85%).

## Auto Run Result

Status: done

**Summary:** The distiller strips the CI-runner ISO-8601 line prefix (`2026-…Z `) once in the cleaning pass, so marker matching and the emitted line both see the line without the runner's timestamp (AD-20 clarified 2026-09-27); the strip leaves a prefix-less log unchanged. `ERROR_MARKERS` gained one entry per failure style found in the committed real logs — Go `--- FAIL:`, Dart/Flutter `error •`, apt/dpkg `E: `, Playwright `N) [`, Elixir/Mix `** (Mix)`, `GitHub API error:`, `Cache error:`, Node `Command:`, `^Could not `, `^\s*cause: `, end-anchored `FAILED`, and the Rails API-doc lint line — open/closed (no branches), each linear-time on adversarial input. A new acceptance test runs the real distiller with the real `distiller.max_bytes` over all 38 manifest logs and proves the manifest `key_line` survives: **15/38 → 38/38**, no exceptions needed (`distiller-exceptions.yaml` is empty). `scripts/build_jev_eval_cases.py` now matches markers on the prefix-stripped line when it builds `unknown` cases.

**Files changed:**
- `workflow/distiller.py` — `_RUNNER_LINE_PREFIX` + `_strip_runner_prefix` (applied once in `distill`) and 12 new anchored/token-shaped `ERROR_MARKERS` entries.
- `tests/security/test_distiller.py` — 21 pre-existing tests unchanged; +AC1 tests (prefix strip, marker-after-strip, prefix-less unchanged, linear-time, fallback) and +AC2 tests (one per real failure style, per-pattern linear-time, the 38/38 acceptance test, exceptions-file shape).
- `test-data/jev-eval/distiller-exceptions.yaml` (new) — committed exceptions list, empty.
- `test-data/jev-eval/cases.generated.yaml` — regenerated (`make jev-eval-cases`).
- `scripts/build_jev_eval_cases.py` — `_cause_free_lines` matches on the prefix-stripped line (keeps the raw line emitted).
- `tests/scripts/test_build_jev_eval_cases.py` — the unknown-case no-cause test also checks the prefix-stripped text.
- `test-data/jev-eval/README.md` — one row for the new exceptions file.
- `docs/DEVELOPER.md` — distiller section (runner-prefix rule, how to add a marker, acceptance test + exceptions file), story row, where-things-live rows. `docs/USER-GUIDE.md` — no change (internal; no user-visible behaviour).

**Review findings breakdown:** 34 findings — 0 high, 1 medium, 25 low, 8 false, 0 maybe-false. 24 patch rows applied (three loose markers anchored; the "prefix-less behaves exactly as before" claim qualified; the exceptions-file test widened; the test seam moved off the private regex; per-pattern linearity; the misleading comment reworded; the generator cause-free strip; the DEVELOPER.md row order). 1 deferred (low: the 3.2 receipts are not reproducible from the regenerated cases — story 3.11 supersedes them). 9 rejected with recorded refutations in the Review Triage Log.

**Follow-up review recommendation:** false — no `high` entry was patched and only one `medium` entry was patched, so the work converged in this pass.

**Verification performed:** `make check` PASS — bootstrap; layer contract PASS; 8 schemas + state diagram byte-identical; ruff check+format clean; mypy --strict clean (57 source files); pylint duplicate-code 10.00/10; 780 passed, 66 deselected; coverage 94.96% ≥ 85%. Focused: `pytest tests/security/test_distiller.py tests/scripts/test_build_jev_eval_cases.py` → 63 passed. `make jev-eval-cases` then `--check` → byte-identical. The 2.7 evidence-pack tests were checked and needed no change (no test feeds a timestamped log to the distiller; `tests/workflow/test_evidence_collection.py` passes unchanged). I/O matrix audit: all 7 rows covered by passing AC-named tests.

**Residual risks:** the TAP `not ok`, `npm ERR!` and Rust `error[E…]` styles named in the epic AC do not occur in any committed log, so no fixture could be cut and no marker was added (reported, not guessed); the deferred receipt-reproducibility item above; `_log_slice` in the tests uses committed line ranges (rejected as low — the logs are immutable in-repo).
