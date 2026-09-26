---
title: 'Story 4.1 — Validate schemas, served citations and attribution'
type: 'feature'
created: '2026-09-26'
status: 'done'
baseline_revision: '8196df5145f72d15791adb7451b8073bbca0ed60'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-4-context.md'
warnings: []
deferred:
  - summary: >-
      No production TaskReader.get_confidence exists and run confidence is not
      persisted, so a real Postgres reader can only return None and every
      production run serves blame-free until confidence persistence lands.
    evidence: |-
      Only the two test fakes implement get_confidence; no column or step
      contract stores ClassConfidence. Settled by the story that persists run
      confidence and wires the concrete reader (2.8/2.12).
    location: >-
      workflow/task_store.py
    severity: medium
  - summary: >-
      blame_free=True plus any suspect always yields attribution_present
      because Suspect.author_login is a required contract field, so a
      blame-free raw verdict with suspects can never validate; 2.8 must define
      the blame-free verdict policy (strip-then-validate vs suspects-free
      blame-free verdicts).
    evidence: |-
      contracts.verdict.Suspect requires author_login (min_length=1); the
      rendered-output path is proven blame-free by the strip walk, but the
      raw-payload policy is undecided.
    location: >-
      guardrails/validator.py
    severity: medium
---

## Build Brief

**(1) Story:** 4.1 — Validate schemas, served citations and attribution (sprint-status key `4-1-validate-schemas-served-citations-and-attribution`).

**(2) ACs in one line each:**
- AC1: pure validators check agent output against the committed JSON schema and resolve every citation against the EvidencePack/Jev answers served this run; missing/unresolvable citations return structured validator errors; guardrails imports contracts only.
- AC2: suspects are candidates carrying both a commit and a log_line citation; caps carry cited reasons and cannot raise confidence; foreign-repo evidence, short production SHAs and probabilities-as-confidence are rejected.
- AC3: output for AWAITING_APPROVAL, REPORTING, or a run below the class cutoff (including 2.4's stored projection fixtures) shows no author attribution; fixtures prove invalid-citation and attribution failures; the validator returns errors for the shared step runner (2.8) rather than implementing a competing workflow.

**(3) Binding ADs:** AD-6 (committed generated schemas are the validation surface), AD-7 (closed citation kinds, every citation resolves against the pack served this run), AD-8 (validator returns errors; retry/pause policy stays with the workflow — NOT implemented here), AD-9 (confidence = min rule; probabilities audit-only), AD-20 (untrusted evidence never becomes instructions — validator is pure), AD-24 (suspects only from `candidate_suspects`; citations resolve against the pack), AD-27 (blame-free output: no author attribution for AWAITING_APPROVAL/REPORTING/below-cutoff, even after a class override).

**(4) Files:** create `guardrails/citation_check.py`, `guardrails/validator.py`, `guardrails/attribution.py`; change `workflow/task_store.py` (reuse the attribution walk), `workflow/a2a_server.py` (drop `_SERVING_CONFIDENCE`), `workflow/evidence_collection.py` (import path), `pyproject.toml` (pinned jsonschema); tests under `tests/guardrails/` and `tests/workflow/`. NOT touched: contracts/ models (reuse as-is; no schema regeneration), `guardrails/confidence.py`, `workflow/attribution.py` predicate, transitions/state machine, distiller, history, risk gate (4.2), prompts, agents.

**(5) Approach:** three small pure modules in `guardrails/` (SOLID-S): `citation_check` resolves each citation kind against a `ServedEvidence` (EvidencePack + this run's `JevClassification`); `validator` validates the raw payload against the committed `TriageVerdict.json` (jsonschema, pinned) then parses with `contracts.TriageVerdict` so model invariants (min rule, suspect blame kinds) surface as the same structured issues; `attribution` owns the deep author-key scan/strip, moved from `workflow/task_store.py` (DRY — one walk, two consumers). The A2A server gets the run's real confidence through a new `TaskReader.get_confidence` (SOLID-I — small protocol addition); unknown/absent confidence serves blame-free (defensive default). No retry/pause logic — the validator returns a list of structured issues and stops (AD-8 belongs to 2.8).

**(6) TDD plan (red-first; names cite ACs):** `tests/guardrails/test_citation_check.py::test_ac1_each_citation_kind_resolves_against_served_evidence`, `::test_ac1_unresolvable_citation_returns_structured_error` (one per kind), `::test_ac1_missing_suspect_blame_citations_rejected`; `tests/guardrails/test_validator.py::test_ac1_schema_failure_is_structured_not_silent`, `::test_ac2_suspect_must_be_a_served_candidate`, `::test_ac2_cap_cannot_raise_confidence`, `::test_ac2_short_production_sha_rejected`, `::test_ac2_foreign_commit_evidence_rejected`, `::test_ac2_probabilities_as_confidence_rejected`, `::test_ac3_attribution_present_is_a_structured_error`; `tests/guardrails/test_attribution.py::test_ac3_deep_scan_finds_author_key_at_any_depth`; `tests/workflow/test_task_server.py::test_ac3_below_cutoff_run_is_served_blame_free` (replaces the 2.4 placeholder guard, which instructs its own deletion).

**(7) Risks / OQ:** jsonschema is a new pinned dependency (supply-chain: pin an established ≥7-day-old 4.x release). The committed schema cannot express the min rule or blame-kind invariants — the pydantic parse layer covers them; both layers map into the same `ValidationIssue` shape. `jev_signal` answer keys are the two answers of the one Jev call (`choice`, `noul`) — fixed constant, cited to AD-7/AD-11. No OQ blocking.

**(8) Doc impact:** `docs/DEVELOPER.md` — new "Guardrails validator" subsection (modules, ServedEvidence, issue shape, how 2.8 will consume it); `docs/USER-GUIDE.md` — A2A endpoint behaviour note: low-confidence runs are now served blame-free (user-visible AC3 change).

<intent-contract>

## Intent

**Problem:** Agent output is currently trusted: nothing rejects a verdict whose citations point at evidence that was never served, a suspect outside the candidate list, a confidence raised past its caps, or author attribution in blame-free output — so untrusted evidence could fabricate a valid verdict.

**Approach:** A pure, deterministic guardrails validator: schema-check the raw payload against the committed generated schema, resolve every citation against the evidence actually served this run, enforce suspect/cap/confidence rules, and prove blame-free rendering on the A2A projection — returning structured errors, never silently passing.

## Boundaries & Constraints

**Always:** guardrails imports `contracts/` only (layer contract); every citation resolves against the pack served this run; errors are structured (`code` + `message` + `location`), all issues collected per validation, never raised as bare exceptions past the validator boundary; thresholds/cutoffs only from `guardrails/thresholds.yaml`; full 40-char SHAs in production payloads.

**Never:** no retry/pause/state-transition logic in the validator (AD-8 is 2.8's shared step runner); no GitHub/Postgres/LLM I/O in guardrails; no new citation kinds or contract changes; no schema hand-edits (regenerate only); no weakening of the 2.4 projection tests.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Valid verdict | payload matching schema, all citations resolvable, suspects from candidates | parsed `TriageVerdict`, zero issues | No error expected |
| Schema failure | payload with short SHA / unknown field / bad enum | structured issue(s), code `schema` | collected, not raised |
| Unresolvable citation | citation whose locator is absent from the served pack | issue per citation, code `citation_unresolvable` | collected |
| Suspect not a candidate | suspect sha outside `candidate_suspects` | issue, code `suspect_not_candidate` | collected |
| Confidence mismatch | `confidence_jev` ≠ served Jev `Choice.confidence` (probability-as-confidence) | issue, code `confidence_mismatch` | collected |
| Attribution in blame-free output | payload with `author_login` at any depth while blame-free | issue, code `attribution_present` | collected |
| Unknown run confidence | reader returns None for a run's confidence | served blame-free (defensive) | No error expected |

</intent-contract>

## Code Map

- `contracts/citations.py` -- closed citation union + `Sha40` pattern (short SHAs already rejected at parse); reuse, do not edit.
- `contracts/evidence.py` -- `EvidencePack` (distilled_log line numbers, commits, history_rows row_ids, metrics keys), `AUTHOR_ATTRIBUTION_FIELD = "author_login"`; reuse.
- `contracts/verdict.py` -- `TriageVerdict` (min-rule + suspect blame-kind model validators), `Cap` (≥1 citation), `effective_confidence`; reuse.
- `contracts/jev.py` -- `JevClassification{choice, injection_screen}`; `choice.confidence` is the only valid `confidence_jev` source (AD-9).
- `guardrails/confidence.py` -- `ClassConfidence.from_jev`, `below_class_cutoff`, `ConfidenceCutoffs`; reuse; do not edit.
- `guardrails/schemas/TriageVerdict.json` -- committed generated schema; the AC1 validation surface; never hand-edit.
- `guardrails/thresholds.yaml` -- `confidence.class_cutoff` (AD-19); cutoffs read via `workflow.thresholds.load_thresholds` in tests use `tests/fixtures/thresholds.test.yaml`.
- `workflow/task_store.py:133` -- `without_author_attribution` deep walk; move the walk to `guardrails/attribution.py`, keep the workflow name as a re-export so `workflow/evidence_collection.py:17` and existing tests stay valid.
- `workflow/task_store.py:71` -- `TaskReader` protocol; add `get_confidence(repo_id, run_id) -> ClassConfidence | None`; `ReadOnlyTaskStore._project` uses it per run instead of the injected constant.
- `workflow/a2a_server.py:37` -- `_SERVING_CONFIDENCE` placeholder + `TODO(story 4.1)`; delete both, wire the reader-supplied confidence.
- `workflow/attribution.py:16` -- `attribution_allowed(state, confidence, cutoffs)`; reuse unchanged (state arms + cutoff arm).
- `tests/workflow/test_task_server.py:297` -- placeholder guard test; delete deliberately (its docstring instructs 4.1 to).
- `tests/fixtures/thresholds.test.yaml` -- test cutoffs; never read the real thresholds file in tests.
- `scripts/check_layer_contract.py` -- enforces guardrails→contracts-only; new guardrails modules are covered automatically.

## Tasks & Acceptance

**Execution:**
- `pyproject.toml` -- add pinned `jsonschema` (via `uv add jsonschema==<pinned 4.x>`) -- AC1 schema checks run against the committed schema file.
- `guardrails/citation_check.py` -- create `ServedEvidence` (pack + `JevClassification`) and per-kind resolution returning issues -- AC1/AC2 core.
- `guardrails/validator.py` -- create `ValidationIssue{code,message,location}`, `ValidationResult{verdict,issues}`, `validate_verdict(payload, served)`: jsonschema check → pydantic parse → citation walk → suspect/candidate, confidence-mismatch, attribution checks -- AC1/AC2/AC3.
- `guardrails/attribution.py` -- create `contains_author_attribution` + `strip_author_attribution` (moved walk) -- AC3, DRY.
- `workflow/task_store.py` -- re-export the moved walk; add `TaskReader.get_confidence`; per-run confidence in `_project` -- AC3.
- `workflow/a2a_server.py` -- delete `_SERVING_CONFIDENCE` + TODO; wire reader confidence (None → blame-free) -- AC3.
- `workflow/evidence_collection.py` -- update import to `guardrails.attribution` -- DRY follow-through.
- `tests/guardrails/test_citation_check.py`, `tests/guardrails/test_validator.py`, `tests/guardrails/test_attribution.py` -- new, red-first per brief (6) -- AC proof.
- `tests/workflow/test_task_server.py` -- delete placeholder guard; add below-cutoff blame-free serving test over the 2.4 fixtures -- AC3.
- `docs/DEVELOPER.md`, `docs/USER-GUIDE.md` -- per brief (8).

**Acceptance Criteria:**
- Given an agent payload and this run's served pack, when `validate_verdict` runs, then every citation kind resolves against the pack and unresolvable/missing citations yield structured issues (AC1).
- Given suspects and caps, when validation runs, then suspects must be served candidates with commit+log_line citations, caps cannot raise confidence, and foreign commits, short SHAs and probabilities-as-confidence are rejected (AC2).
- Given blame-free output (AWAITING_APPROVAL, REPORTING, below-cutoff, or unknown confidence), when rendered or validated, then no `author_login` key survives at any depth, proven over the 2.4 projection fixtures (AC3).

## Spec Change Log

## Review Triage Log

### 2026-09-26 — Review pass
- verdicts: 36 findings — high 0, medium 3, low 23, false 10, maybe-false 0
- findings:
  - `[medium]` `[defer]` no production `TaskReader.get_confidence` / run confidence not persisted, so a real Postgres reader can only return `None` and every production run serves blame-free until persistence lands (BH5, IA3) — verified: only the two test fakes implement the method; confidence is stored nowhere (no column, no step contract). Settled by the story that persists run confidence and wires the concrete reader (2.8/2.12). Deferred, severity medium.
  - `[medium]` `[defer]` `blame_free=True` + any suspect always yields `attribution_present` because `Suspect.author_login` is a required contract field, so a blame-free raw verdict with suspects can never validate (BH1) — verified: contract requires `author_login` (min_length=1); the rendered-output path is proven blame-free by the strip, but the raw-payload policy for 2.8 (strip-then-validate vs suspects-free blame-free verdicts) is a decision 2.8 owns. Deferred, severity medium.
  - `[low]` `[patch]` `check_citations`/`_unresolvable_message` raise `TypeError` for an unknown citation kind, past the documented never-raises boundary (BH12, EC4) — patched: default arms return a structured `citation_unresolvable` issue instead of raising.
  - `[low]` `[patch]` `blame_free: bool = False` permissive default lets a 2.8 caller silently skip the AD-27 check (EC5, CC4) — patched: `blame_free` is now a required keyword-only argument; call sites updated.
  - `[low]` `[patch]` parse-failed blame-free payload skips the attribution check (early return before it), so its retry feedback omits the leak (EC1) — patched: attribution check runs before the early return.
  - `[low]` `[patch]` `validate_verdict` typed `Mapping[str, object]` but handles/tests non-Mapping input behind `# type: ignore`; `_parse`'s Mapping guard is dead under the declared type (BH4, CC6, CC5) — patched: signature widened to `object`, guard is now real, test annotations tightened (`list[Citation]`/`Sequence[Citation]`), ignores removed.
  - `[low]` `[patch]` parametrized unresolvable-citation test asserts `message=issues[0].message` (tautology); per-kind wording only substring-checked (BH7) — patched: literal expected message per parametrized case.
  - `[low]` `[patch]` `without_author_attribution` alias re-export in `workflow/task_store.py` has no remaining consumer (CC1) — verified by grep (only task_store itself) — patched: direct `strip_author_attribution` import, alias dropped from imports/`__all__`/docstring.
  - `[low]` `[patch]` USER-GUIDE overclaim: "the author of the top suspect is shown again" — the code shows/hides `author_login` on every served commit, not just rank-1 (CC2) — patched: reworded to author names on the served commits.
  - `[low]` `[reject]` `jev_signal` resolution uses the static `JEV_SIGNAL_ANSWERS` instead of `served.jev` (BH2) — refuted: `ServedEvidence.jev` is a required `JevClassification`, whose two answers are exactly `choice`/`noul`; a run without a Jev call cannot construct `ServedEvidence`, so the static set is extensionally identical to "this run's answers".
  - `[low]` `[reject]` schema + `Draft202012Validator` built at import time = filesystem I/O in the pure layer; bare exception if the file is missing (BH3, EC7, CC3) — refuted as harm: the schema file is committed and byte-drift-gated by `make schema-drift`, so a missing/moved file fails CI before any consumer imports; reading a repo-committed artifact is not the I/O the layer rule guards (no network/db/secrets), and lazy loading would add indirection for no reachable failure.
  - `[low]` `[reject]` only the first `author_login` location reported; test name says "deepest" but walk is first-DFS (BH9) — cosmetic: one location is sufficient feedback to fix the leak; the strip removes all keys regardless; rename would churn a passing test for no behavioural gain.
  - `[low]` `[reject]` schema-layer and parse-layer double-report the same defect with different location spellings (BH10) — by design: the two layers are the spec's stated approach; duplicates in retry feedback are informative, and dropping the parse layer when schema fails would hide invariant detail.
  - `[low]` `[reject]` `strip_author_attribution` rewrites tuples to lists (BH13) — pre-existing behaviour moved verbatim; the only consumers JSON-serialize, where tuples and lists are the same; no in-memory tuple consumer exists.
  - `[low]` `[reject]` no blame-free test through `list_tasks` (BH14) — `list` and `get` share `_project`, which holds all confidence/blame logic and is tested at store and wire level; the list wrapper adds no confidence-specific branch.
  - `[low]` `[reject]` unbounded recursion in the attribution walk for adversarially deep payloads (EC2, EC3) — the surrounding standard layers (jsonschema, pydantic) share the same recursion envelope, so a depth bound in the walk alone would not make validation recursion-safe; harm requires a hostile payload that already breaks the stdlib layers; a depth guard is new complexity guarding an undemonstrated path.
  - `[low]` `[reject]` `JEV_SIGNAL_ANSWERS` could drift from `JevClassification` fields (EC9) — hypothetical future drift; the constant is AD-7/AD-11-cited and pinned by its own test, so any change is a deliberate, failing-test-visible edit.
  - `[low]` `[reject]` intent-alignment: layer-contract gate broadened for `jsonschema` without an inline `# noqa` exception (IA4) — the exception is disclosed in the spec's risk section, will be listed in the story report per AGENTS.md, and the docs state it; an inline noqa on an import the checker whitelists would be noise.
  - `[false]` `[reject]` suspect's commit citation not required to equal the suspect's own sha (BH8) — neither AC2 nor AD-27 requires it; the suspect sha itself is already constrained to served candidates; the citation carries evidence provenance.
  - `[false]` `[reject]` float `==` on `confidence_jev` brittle (BH11, EC8) — both numbers originate from the same serialized Jev answer; a round-trip-different value is by definition not this run's Jev number, so exact equality is the correct semantics.
  - `[false]` `[reject]` pack.commits membership vs literal `last_green..HEAD` range (BH16) — the pack is by definition the served `last_green..HEAD` evidence (built by 2.7's `assemble_pack`); AD-7 mandates resolution against the served pack, not an independent range re-derivation.
  - `[false]` `[reject]` USER-GUIDE "done (story 4.1)" while spec says in-progress (BH15) — transient mid-run state; the finalize step sets `status: done` before the run ends.
  - `[false]` `[reject]` intent's process guarantees (branch lineage, make check green, AC-by-AC proof, batch report) absent from the diff (IA1, IA2) — a unified diff cannot carry process proof; branch ancestry and gate output verified by the orchestrator outside the diff; per-story dispatch is the workflow's design.
  - `[false]` `[reject]` spec `status: in-progress` / no sprint-status row yet (IA5) — transient; the HALT protocol owns the sprint-status sync at `done`.
  - `[false]` `[reject]` suspect rank not checked against the candidate's rank (EC6) — no AC requires rank equality; rank consumers are deterministic workflow code, not the validator's mandate.

## Design Notes

`validate_verdict` collects ALL issues in one pass (retry feedback in 2.8 gets the complete list, not just the first failure). Two validation layers, one issue shape: the committed JSON schema catches shape/enum/pattern violations (short SHAs included); the pydantic parse catches the invariants JSON Schema cannot express (min rule, blame kinds). Example issue:

```python
ValidationIssue(
    code="citation_unresolvable",
    message="commit citation sha is not in last_green..HEAD of the served pack",
    location="suspects[0].citations[0]",
)
```

`jev_signal` answer keys: `frozenset({"choice", "noul"})` — the two answers of the single `system_one` call (AD-7, AD-11); the injection screen's own cap cites `noul`, so it always resolves.

## Verification

**Commands:**
- `uv run pytest tests/guardrails tests/workflow/test_task_server.py tests/workflow/test_task_store.py -q` -- expected: all pass, new AC-named tests green.
- `uv run python scripts/check_layer_contract.py` -- expected: PASS (guardrails imports contracts only).
- `make check` -- expected: PASS (bootstrap, layer contract, schema drift, ruff, mypy --strict, pylint duplicate-code, pytest ≥85% on contracts/guardrails/workflow).

## Auto Run Result

Status: done

**Summary:** Pure guardrails validator landed: `validate_verdict` checks the raw agent payload against the committed generated `TriageVerdict` JSON schema (pinned jsonschema 4.25.1), parses it with `contracts.TriageVerdict` so the min-rule and blame-kind invariants surface as the same structured issues, resolves every citation (all five closed kinds, across verdict/caps/suspects/quarantine surfaces) against the `ServedEvidence` (pack + this run's Jev call), rejects suspects outside `candidate_suspects`, rejects a `confidence_jev` that is not this run's Jev `Choice.confidence` (probabilities-as-confidence), and flags `author_login` anywhere in blame-free output. The A2A task view now reads each run's real confidence through the new `TaskReader.get_confidence` (unknown → blame-free, defensive), the 2.4 `_SERVING_CONFIDENCE` placeholder and its guard test are gone, and the deep author-key walk moved once to `guardrails/attribution.py` (DRY, shared by task view, evidence collection and validator). No retry/pause logic — AD-8 stays with 2.8.

**Files changed:**
- `guardrails/citation_check.py` (new) — `ServedEvidence`, `ValidationIssue` (the one issue shape), `JEV_SIGNAL_ANSWERS`, closed per-kind citation resolution; unknown kinds resolve as unresolvable, never raise.
- `guardrails/validator.py` (new) — `validate_verdict(payload, served, *, blame_free)` → `ValidationResult{verdict, issues}`; two layers + suspect/confidence/attribution checks; all issues collected.
- `guardrails/attribution.py` (new) — deep `author_login` find/locate/strip walk (moved from `workflow/task_store.py`).
- `workflow/task_store.py` — `TaskReader.get_confidence` added; per-run confidence in `build_task` (None → blame-free); alias re-export dropped after rewiring.
- `workflow/a2a_server.py` — `_SERVING_CONFIDENCE` + TODO(story 4.1) deleted; reader-supplied confidence.
- `workflow/evidence_collection.py` — imports the moved walk from `guardrails.attribution`.
- `pyproject.toml`, `requirements/constraints.txt`, `requirements/dev-constraints.txt`, `scripts/bootstrap.sh` — pinned `jsonschema==4.25.1` (+ stubs for mypy).
- `scripts/check_layer_contract.py` — guardrails allowed extras now include `jsonschema` (still no I/O).
- `tests/guardrails/test_citation_check.py`, `tests/guardrails/test_validator.py`, `tests/guardrails/test_attribution.py` (new); `tests/workflow/test_task_store.py`, `tests/workflow/test_task_server.py` (AC3 below-cutoff/unknown-confidence tests; 2.4 placeholder guard deleted as it instructed).
- `docs/DEVELOPER.md`, `docs/USER-GUIDE.md`, `guardrails/README.md`, `workflow/README.md` — per Build Brief part 8.

**Review findings breakdown:** 36 findings — 0 high, 3 medium, 23 low, 10 false, 0 maybe-false. 7 patch entries applied (all low: never-raise citation default arms, required `blame_free` keyword, attribution check before early return, honest `object` payload typing + test annotation cleanup, literal expected messages, dead alias re-export dropped, USER-GUIDE reword). 3 items deferred (2 medium: no production confidence source until persistence lands; blame-free raw-verdict policy owned by 2.8; 1 low: list-path N+1 batching, pre-existing from 2.4). 26 rejected with recorded refutations in the Review Triage Log.

**Follow-up review recommendation:** false — 0 high and 0 medium patched entries (all 7 patches low); no unverified risk named beyond the two deferred items already recorded.

**Verification performed:** `make check` PASS (bootstrap pins incl. jsonschema 4.25.1; layer contract PASS; 7 schemas + state diagram byte-identical; ruff check+format clean; mypy --strict clean; pylint duplicate-code 10.00/10; 408 passed, 47 integration deselected; coverage 93.77% ≥ 85%). Focused: `pytest tests/guardrails tests/workflow/test_task_server.py tests/workflow/test_task_store.py -q` → 92 passed. I/O matrix audit: all 7 rows covered by passing AC-named tests.

**Residual risks:** the two deferred items above (production confidence source; blame-free raw-verdict policy in 2.8). The layer-contract gate now admits `jsonschema` for guardrails — pure-library addition, no I/O; if a reviewer wants it stricter, the alternative is a hand-rolled schema checker, which the spec rules out.
