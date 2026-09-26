---
title: 'Story 4.2 — Block every deterministic risk rule'
type: 'feature'
created: '2026-09-26'
status: 'done'
baseline_revision: 'b661f43a8b016b0be9e224ce626bd9de44fa6377'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-4-context.md'
warnings: []
deferred:
  - summary: >-
      Assertion-rule tripwire is narrow: outright assertion deletion and
      non-bare-token forms (assertEqual(a.b,…), assertTrue, assertRaises) are
      invisible to assertion_loosened.
    evidence: |-
      Verified by reading the pattern set: only the two transformation pairs
      (assertEqual(tok, → assertIn(tok,, assert tok == → assert tok in) on
      bare identifiers fire. Widening needs a semantic pass — a deletion rule
      floods false positives on legitimate refactors. Red-team story 4.6
      exercises the gate and can drive widening with fixtures.
    location: >-
      guardrails/risk_gate.py (_STRONG_ASSERTION/_WEAK_ASSERTION)
    severity: low
  - summary: >-
      Timeout-rule tripwire is narrow: a file-wide max comparison masks a bump
      behind a larger pre-existing timeout, and floats/units (timeout=0.5,
      timeout_ms, --timeout) match nothing.
    evidence: |-
      Verified: _check_timeout_increased compares max(new) > max(prior) per
      file; _TIMEOUT_PATTERN matches only integer timeout=/timeout(N) forms.
      Per-line pairing and unit widening are refinements for the same
      red-team-driven pass. Adding a first timeout to a file blocking is
      correct fail-closed behaviour (AD-13: the file's timeout went up).
    location: >-
      guardrails/risk_gate.py (_TIMEOUT_PATTERN, _check_timeout_increased)
    severity: low
  - summary: >-
      prior_contents has no producer in the system yet: no story-owned
      component supplies base file content, so once the gate is wired every
      MODIFY op fails closed until the wiring story supplies it.
    evidence: |-
      ProposedDiff carries only new_content; prior_contents is a caller
      input with no producer today (no production caller exists yet). The
      wiring story (workflow GATING integration) must fetch base content and
      pass it, or accept fail-closed blocking of every modification.
    location: >-
      guardrails/risk_gate.py (GateInput.prior_contents)
    severity: medium
---

## Build Brief

**(1) Story:** 4.2 — Block every deterministic risk rule (sprint-status key `4-2-block-every-deterministic-risk-rule`).

**(2) ACs in one line each:**
- AC1: every AD-13 rule — skip/disable/xfail a test, added retries, increased timeouts, loosened assertions, `.github/workflows/**`, secrets, infra manifests — yields `risk_tier = blocked` from its diff fixture; a `dangerous` Reviewer objection also blocks; model-asserted risk tiers cannot override the gate.
- AC2: a safe root-cause diff yields `normal`; no diff to gate retains `not_gated`; quarantine stays metadata only (never a gate input or a block reason); the RT-07 per-rule pytest carries a positive AND a negative fixture per rule plus the S5 timeout-bump gate fixture.
- AC3: the gate returns structured evidence/reasons (rule code, message, location) with no GitHub, Postgres, HTTP or model calls; the actual `AWAITING_APPROVAL(gate_blocked)` transition is NOT built here (workflow's business, later story).

**(3) Binding ADs:** AD-13 (the closed rule list; gate is deterministic with the last word; only `normal` proceeds), AD-6 (reuse `ProposedDiff`/`Objection`/`RiskTier` contracts as-is — no contract changes), AD-12 (a `dangerous` objection escalates to blocked), AD-19 (configurable values — the workflow-path glob and the new secret/infra path globs — live only in `guardrails/thresholds.yaml`, never in code), AD-21 (quarantine is metadata only, never in the diff, never a gate rule), layer contract (guardrails imports `contracts/` + pinned pure libs only, no I/O).

**(4) Files:** create `guardrails/risk_gate.py`; change `guardrails/thresholds.yaml` (new `risk_gate:` globs section), `workflow/thresholds.py` (load the new section), `tests/fixtures/thresholds.test.yaml` (mirror), `tests/guardrails/test_risk_gate.py` (new), `tests/workflow/test_thresholds.py` (new-keys test), `guardrails/README.md`, `docs/DEVELOPER.md`. NOT touched: `contracts/` (reuse as-is; no schema regeneration), existing guardrails modules (`validator`, `citation_check`, `attribution`, `confidence`), `workflow/transitions.py` (the `gate_allows_pr`/`gate_blocks` guards already consume `risk_tier` — no change), state machine, distiller, history, prompts, agents, `docs/USER-GUIDE.md` (no user-visible behaviour yet — see part 8).

**(5) Approach:** one pure module `guardrails/risk_gate.py` (SOLID-S). A **rule registry** (SOLID-O): each AD-13 rule is one entry — a frozen `RiskRule{code, check}` where `check(GateInput) -> tuple[GateReason, ...]` — iterated once; a new rule is a new entry, never a new `if/elif`. `GateInput` carries `diff: ProposedDiff | None`, `prior_contents: Mapping[path, base content]` (supplied by the caller so timeout/loosening comparisons stay deterministic), `objections: Sequence[Objection]`, and a frozen `RiskGateConfig{workflow_path_glob, secret_path_globs, infra_path_globs}` the caller builds from `guardrails/thresholds.yaml` via the existing `workflow.thresholds` loader (AD-19 single source; guardrails itself does no config I/O). `evaluate_risk` returns `GateDecision{risk_tier, reasons}`: no diff → `not_gated`; any reason → `blocked` with ALL reasons collected; else `normal`. The gate takes no model-asserted tier as input — override-impossibility is structural (AC1). DRY: globs come from thresholds.yaml; patterns for skip/retry/loosening are rule-definition constants living on their registry entries (they are the rule, not a tunable cutoff).

**(6) TDD plan (red-first; names cite ACs):** `tests/guardrails/test_risk_gate.py::test_ac1_every_rule_blocks_its_positive_fixture` (parametrized: one positive diff fixture per registry rule), `::test_ac1_every_rule_passes_its_negative_fixture` (parametrized negative per rule), `::test_ac1_dangerous_objection_blocks_safe_diff`, `::test_ac1_model_asserted_tier_cannot_override` (a verdict claiming `normal` over a test-skipping diff still gates `blocked`), `::test_ac1_s5_timeout_bump_fixture_blocked`, `::test_ac2_safe_root_cause_diff_is_normal`, `::test_ac2_no_diff_is_not_gated`, `::test_ac2_quarantine_is_metadata_only`, `::test_ac2_modified_file_without_prior_content_fails_closed`, `::test_ac3_reasons_are_structured_evidence`, `::test_ac3_gate_collects_every_hit`; `tests/workflow/test_thresholds.py::test_ac1_risk_gate_config_loads_from_thresholds_yaml`.

**(7) Risks / OQ:** Content rules (skip/retry/loosening) are line-pattern tripwires over added/removed lines — deliberately conservative pattern sets, documented in Design Notes; they are the deterministic backstop, not a semantic reviewer. Timeout-increase and assertion-loosening need the base content of modified files; the caller supplies `prior_contents`, and a modified file with no prior content **fails closed** (blocked, `prior_content_missing`) so gating can never be silently skipped. No OQ blocking; no new dependencies.

**(8) Doc impact:** `docs/DEVELOPER.md` — new "Risk gate (story 4.2)" subsection (what each rule watches, the registry, config source, fail-closed rule, who calls it later); `guardrails/README.md` — one line for `risk_gate.py`. `docs/USER-GUIDE.md` — **no doc change**: the gate is not wired into any user-visible flow yet (the `AWAITING_APPROVAL(gate_blocked)` pause lands with the workflow integration story), so there is no user-visible behaviour to document.

<intent-contract>

## Intent

**Problem:** Proposed changes reach GitHub unchecked: nothing deterministically stops a diff that hides a bug — skipping or xfail-ing a test, adding retries, bumping a timeout, loosening an assertion, or touching workflow files, secrets or infra manifests — so a model (or an injected instruction) could normalize a bug-hiding repair.

**Approach:** A pure, deterministic risk gate in `guardrails/`: one registry entry per AD-13 rule, evaluated over the proposed diff (plus the base content of modified files and the Reviewer's objections), returning `normal | blocked | not_gated` with structured per-rule evidence — no I/O, no model, no state transitions.

## Boundaries & Constraints

**Always:** guardrails imports `contracts/` + pinned pure libraries only — no GitHub/Postgres/HTTP/model I/O (layer contract); every configurable value (workflow glob, secret/infra path globs) comes from `guardrails/thresholds.yaml` via the caller (AD-19); states come from `contracts.enums.RiskTier` — `normal | blocked | not_gated`, no new strings; all rule hits are collected and returned as structured reasons, never raised; a modified file without base content fails closed.

**Never:** no `AWAITING_APPROVAL(gate_blocked)` transition, no state machine, no retry/pause policy here (workflow owns those); no contract or generated-schema changes; no new citation kinds; no model-asserted `risk_tier` input — the gate recomputes from the diff; quarantine is never a gate input or a rule; no if/elif chain over rules — the registry is the extension point.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| No diff to gate | `diff=None` | `not_gated`, no reasons | No error expected |
| Safe root-cause diff | modify fixing an expected value, prior content supplied | `normal`, no reasons | No error expected |
| Rule positive fixture (one per rule) | diff skipping a test / adding retry / bumping timeout / loosening assertion / touching workflows, secrets, infra | `blocked` + that rule's reason | Collected, not raised |
| Rule negative fixture (one per rule) | safe diff matching the same surface (e.g. timeout decreased, assertion strengthened) | `normal` | No error expected |
| Dangerous objection | safe diff + `Objection(severity=dangerous)` | `blocked` + reviewer reason | Collected |
| Model-asserted tier | skipping diff alongside a verdict claiming `normal` | `blocked` (claimed tier never an input) | No error expected |
| Missing prior content | modify op, no base content supplied | `blocked`, `prior_content_missing` (fail-closed) | Collected |
| Quarantine present | quarantine recommendation alongside a safe diff | no effect on the decision | No error expected |
| Multiple rule hits | diff violating two rules | `blocked` with ALL reasons | Collected |

</intent-contract>

## Code Map

- `contracts/verdict.py` -- `ProposedDiff`/`DiffFile{path, op, new_content}` (no old content — hence `prior_contents`), `Quarantine`; reuse, do not edit.
- `contracts/objections.py` -- `Objection{severity, category, claim, citation}`; `severity=dangerous` is the AD-12 block trigger; reuse.
- `contracts/enums.py` -- `RiskTier` (`normal|blocked|not_gated`), `ObjectionSeverity`, `DiffOperation`; the only state vocabulary; reuse.
- `guardrails/thresholds.yaml` -- the one thresholds file (AD-19); already carries `workflow_path_glob`; gains a `risk_gate:` section with `secret_path_globs` + `infra_path_globs`.
- `workflow/thresholds.py` -- the one loader; extend `Thresholds` with the new section; guardrails never imports this (layer contract) — the caller passes a `RiskGateConfig`.
- `tests/fixtures/thresholds.test.yaml` + `tests/fixtures/thresholds.py` -- test thresholds, mirrored with the real file; extend for the new keys.
- `workflow/transitions.py:138-145` -- `gate_allows_pr`/`gate_blocks` already consume `risk_tier`; proof the gate output plugs in later; do not edit.
- `guardrails/validator.py` -- precedent for the pure-module style (structured results, collected issues, no I/O); do not edit.
- `scripts/check_layer_contract.py` -- guardrails layer check; new module covered automatically.
- `tests/guardrails/test_validator.py` -- test style precedent (AC-named tests, contract-dumped payloads).

## Tasks & Acceptance

**Execution:**
- `guardrails/thresholds.yaml` -- add `risk_gate:` section (`secret_path_globs`, `infra_path_globs`) -- AD-19 single source for the gate's configurable values.
- `workflow/thresholds.py` -- load the new section into `Thresholds` -- the one loader stays the only reader.
- `tests/fixtures/thresholds.test.yaml` -- mirror the new keys -- tests never read the real file.
- `guardrails/risk_gate.py` -- create `RiskGateConfig`, `GateReason{rule_code, message, location}`, `GateDecision{risk_tier, reasons}`, `GateInput`, the `RiskRule` registry (test_disabled incl. test-file deletion, retry_added, timeout_increased, assertion_loosened, workflow_file_touched, secret_touched, infra_manifest_touched, reviewer_dangerous, prior_content_missing) and `evaluate_risk` -- AC1/AC2/AC3 core.
- `tests/guardrails/test_risk_gate.py` -- new, red-first per brief (6), positive+negative fixture per rule, S5 timeout-bump fixture -- AC proof.
- `tests/workflow/test_thresholds.py` -- extend for the new keys -- loader proof.
- `guardrails/README.md`, `docs/DEVELOPER.md` -- per brief (8).

**Acceptance Criteria:**
- Given a diff fixture per AD-13 rule, when `evaluate_risk` runs, then each yields `blocked` with that rule's structured reason, a `dangerous` objection blocks a safe diff, and a model-asserted tier cannot override the result (AC1).
- Given a safe root-cause diff or no diff, when the gate runs, then safe yields `normal`, no diff yields `not_gated`, quarantine has no effect, and the RT-07 per-rule pytest carries positive AND negative fixtures plus the S5 timeout-bump fixture (AC2).
- Given any gate run, when it returns, then the decision carries structured reasons (rule code, message, location) and the module makes no GitHub, Postgres, HTTP or model calls (AC3).

## Spec Change Log

## Review Triage Log

### 2026-09-26 — Review pass
- verdicts: 28 findings — high 0, medium 6, low 17, false 5, maybe-false 0
- findings:
  - `[medium]` `[patch]` nested secret files bypass `secret_touched` (`.env` globs match only root-level paths; `config/.env` matches none) — verified: `fnmatch("config/.env", ".env")` is False; fix: add `*/.env` + `*/.env.*` globs to both thresholds files.
  - `[medium]` `[patch]` DELETE+ADD of the same path bypasses the comparison rules (timeout/loosening only inspect MODIFY) — verified: an ADD needs no prior content, so a modification expressed as delete+add evades `timeout_increased`/`assertion_loosened`; fix: fail closed when one path appears both deleted and added in one diff.
  - `[medium]` `[patch]` multiset (Counter) added/removed lines are order-insensitive, so relocating an existing skip/retry line to another test evades the added-line rules — verified: `Counter(new) - Counter(prior)` is empty for a pure relocation; fix: derive added/removed lines with `difflib` so relocations surface as remove+add.
  - `[medium]` `[patch]` the real `guardrails/thresholds.yaml` `risk_gate` glob values are never asserted (tests pin only the fixture copy; the key-parity test compares key paths, not values) — verified: `test_ac1_risk_gate_config_loads_from_thresholds_yaml` loads the fixture; fix: assert the real file's glob values in the existing real-thresholds test.
  - `[medium]` `[patch]` (same root cause as the row above, edge-case layer) fixture/real YAML can drift on values while every gate test stays green — same fix.
  - `[medium]` `[patch]` (same root cause as the row above, verification-gap layer, pre-verified) a typo'd real-file glob ships unpinned and a `deploy/tls.key` diff gates `normal` — same fix.
  - `[low]` `[defer]` assertion rule is a narrow tripwire: outright assertion deletion and non-bare-token forms (`assertEqual(a.b,…)`, `assertTrue`, `assertRaises`) are invisible — verified by reading the pattern set; deliberately scoped in the spec's Design Notes; widening needs a semantic pass (false-positive flood on legitimate refactors); red-team story 4.6 exercises the gate and can drive widening with fixtures.
  - `[low]` `[defer]` (same root cause, edge-case layer) strong assertion removed with no weak assertion added yields no hit — same disposition.
  - `[low]` `[defer]` (same root cause, edge-case layer) assertion forms outside the two transformation pairs are invisible — same disposition.
  - `[low]` `[defer]` timeout rule precision: file-wide max comparison masks a bump behind a larger pre-existing timeout; floats/units (`timeout=0.5`, `timeout_ms`, `--timeout`) match nothing — verified; per-line pairing is a refinement for the same red-team-driven widening pass.
  - `[low]` `[defer]` (same root cause, blind-hunter layer) adding a first timeout to a modified file always blocks (fail-closed, correct per AD-13's letter — the file's timeout went up); the under-detection half (floats/units) is the deferred part.
  - `[low]` `[patch]` `GateInput` uses pydantic's default `extra="ignore"`, so `GateInput(risk_tier=…)` is silently dropped instead of rejected — fix: `extra="forbid"` (matches `RiskGateLimits`).
  - `[low]` `[patch]` runtime `pytest.xfail(…)` / `pytest.importorskip(…)` calls are not in the skip pattern — fix: extend `_SKIP_PATTERN` + fixture.
  - `[low]` `[patch]` case-variant paths (`Secrets/`, `DOCKERFILE`) evade case-sensitive `fnmatch` — fix: match case-insensitively in `_touched_paths`/`_is_test_path` + fixture.
  - `[low]` `[patch]` deleting `conftest.py` disables fixtures for many tests but matches no test-file glob — fix: add `conftest.py` to `_TEST_FILE_GLOBS` + fixture.
  - `[low]` `[patch]` `RiskGateConfig.secret_path_globs`/`infra_path_globs` lack `Field(min_length=1)`, so a caller-built empty config silently disables two AD-13 rules (fail-open in a fail-closed module) — fix: add the constraint (the loader's `RiskGateLimits` already has it).
  - `[low]` `[patch]` (same root cause, clean-code layer) empty-glob fail-open — same fix.
  - `[low]` `[patch]` `_TEST_FILE_GLOBS` is the only path glob not sourced from config — deliberate rule constant per the Build Brief, but undocumented — fix: one comment citing why it is a rule constant, not a tunable.
  - `[low]` `[patch]` `docs/DEVELOPER.md` says the secret globs are `.env*` but the yaml defines `.env` + `.env.*` (`.env*` would also match `.environment`) — fix: spell the two real globs in the doc.
  - `[low]` `[reject]` patterns hit comments/docstrings (a docstring mentioning `pytest.mark.skip` trips the gate) and non-Python test idioms are uncovered — the over-block half is the fail-safe direction (extra human review, never a shipped bug) and fixing it needs a Python parser in the pure module; the non-Python half is out of stack (the spine pins Python).
  - `[low]` `[reject]` a new (ADD) file introducing a large timeout is unchallenged — a new file's timeout is not an "increase" (AD-13's letter); the move-to-new-file evasion is already closed by test-file deletion blocking; blocking every new-file timeout would flood false positives.
  - `[false]` `[reject]` a `dangerous` objection with `diff=None` is silently discarded — unreachable: the Reviewer runs only on a proposal (AD-12), so objections-without-diff cannot occur in the workflow; `not_gated` for an ungated run is the defined behaviour.
  - `[false]` `[reject]` the epic-4-context rewrite silently drops requirements — the rewrite is this workflow's mandated context recompilation (the cached file was older than the planning artifacts), follows the compile-epic-context rules (scope aggressively, no story-level detail); the dropped items are story-level constraints that live in the story specs and epics.md, unchanged.
  - `[false]` `[reject]` (same root cause, intent-alignment layer) out-of-story surface — same refutation.
  - `[false]` `[reject]` the gate's tier lands on a new `GateDecision` surface instead of `TriageVerdict.risk_tier` — the intent's own guidance selects this reading ("output is structured evidence/reasons"; the transition and wiring are explicitly out of scope); AC3 names "the pure module returns its decision" as the surface.
  - `[false]` `[reject]` non-override is proven by introspection rather than an exercised override path — structural impossibility (no tier input exists) is the stronger guarantee; the test additionally shows the gate returning `blocked` for the diff a verdict claimed `normal` on.
  - `[low]` `[defer]` `prior_contents` has no producer in the system yet — true today by design (no caller exists; the wiring story owns supplying base content); recorded so the wiring story cannot forget it: without a producer, every MODIFY fails closed.

## Design Notes

Rule shapes (deterministic, no semantics guessing):

```python
RiskRule(code="test_disabled", check=_check_test_disabled)  # registry entry
# _check_test_disabled: added lines matching skip/xfail patterns
#   (pytest.mark.skip / skipif / xfail, pytest.skip(, unittest.skip)
#   OR a delete op on a test file path (test_*.py, *_test.py)
# timeout_increased: max timeout value in new content > max in prior content
# assertion_loosened: removed strong assertion + added weak assertion on the
#   same target token (assertEqual(tok, -> assertIn(tok,, assert tok == -> assert tok in)
```

Fail-closed rule: `prior_content_missing` blocks any modify op whose base content the caller did not supply — gating must never be silently skipped. The S5 fixture: a diff bumping a test's `timeout=5` to `timeout=60` must gate `blocked` (scenario S5's only-obvious-fix case). Pattern sets are intentionally narrow (documented tripwires); widening one is a registry-entry edit plus its fixtures.

## Verification

**Commands:**
- `uv run pytest tests/guardrails/test_risk_gate.py tests/workflow/test_thresholds.py -q` -- expected: all pass, AC-named tests green.
- `uv run python scripts/check_layer_contract.py` -- expected: PASS (guardrails imports contracts + pinned pure libraries only).
- `make check` -- expected: PASS (bootstrap, layer contract, schema drift, state diagram, ruff, mypy --strict, pylint duplicate-code, pytest ≥85% on contracts/guardrails/workflow).

## Auto Run Result

Status: done

**Summary:** The deterministic risk gate landed as one pure module, `guardrails/risk_gate.py`: a registry with one entry per AD-13 rule (test skipped/xfail-ed or its file deleted, retry machinery added, timeout raised, assertion loosened, workflow/secret/infra path touched, dangerous Reviewer objection, fail-closed on missing base content), evaluated over the proposed diff, the base content of modified files and the Reviewer's objections. No diff gates `not_gated`; any hit gates `blocked` with every structured reason collected; otherwise `normal`. The gate takes no model-asserted tier and no quarantine — override-impossibility and AD-21 are structural. Configurable globs live only in `guardrails/thresholds.yaml` (new `risk_gate:` section) read through the one loader; guardrails does no I/O. The `AWAITING_APPROVAL(gate_blocked)` transition and any caller wiring are deliberately not built (later story).

**Files changed:**
- `guardrails/risk_gate.py` (new) — the registry, `evaluate_risk`, structured `GateReason`/`GateDecision`; difflib-based added/removed lines; case-insensitive glob matching; fail-closed arms.
- `guardrails/thresholds.yaml` + `tests/fixtures/thresholds.test.yaml` — new `risk_gate:` secret/infra path globs (incl. nested `*/.env` forms).
- `workflow/thresholds.py` — `RiskGateLimits` loaded into `Thresholds` (the one loader stays the only reader).
- `tests/guardrails/test_risk_gate.py` (new) — 32 AC-named tests; registry-driven positive+negative fixture per rule, S5 timeout-bump fixture, relocation/delete+add/case-variant/runtime-skip fixtures.
- `tests/workflow/test_thresholds.py`, `tests/workflow/test_transitions.py` — new-keys test; real-file `risk_gate` glob values asserted.
- `tests/fixtures/thresholds.py` — `FIXTURE_THRESHOLDS` exported.
- `guardrails/README.md`, `docs/DEVELOPER.md` — risk-gate sections per Build Brief part 8. `docs/USER-GUIDE.md`: no doc change (gate not wired to any user-visible flow yet).

**Review findings breakdown:** 28 findings — 0 high, 6 medium, 17 low, 5 false, 0 maybe-false. 11 patch groups applied (4 medium: nested-secret globs, DELETE+ADD evasion, difflib relocation detection, real-file glob-value pinning; 7 low: extra=forbid, runtime skip calls, case-insensitive matching, conftest.py glob, min-length globs, rule-constant comment, doc wording). 3 items deferred (assertion-rule precision, timeout-rule precision, prior_contents producer — see frontmatter). 5 false findings rejected with refutations in the Review Triage Log; 2 low rejected with reasons.

**Follow-up review recommendation:** true — four medium entries were patched (nested-secret globs, DELETE+ADD fail-closed, difflib line derivation, real-file value pinning). Unverified risk: the difflib-based added/removed-line derivation changed the semantics every content rule sees (relocations and reformats now surface as changes), and the widened pattern/glob sets have no adversarial re-review — a follow-up pass should check the patched line-derivation and widened patterns against legitimate-diff fixtures the first pass never exercised.

**Verification performed:** `make check` PASS (bootstrap pins; layer contract PASS; 7 schemas + state diagram byte-identical; ruff check+format clean; mypy --strict clean; pylint duplicate-code 10.00/10; 559 passed, 65 integration deselected; coverage 94.47% ≥ 85%). Focused: `pytest tests/guardrails/test_risk_gate.py tests/workflow/test_thresholds.py tests/workflow/test_transitions.py -q` → 57 passed. I/O matrix audit: all 9 rows covered by passing AC-named tests. No `# noqa` exceptions introduced.

**Residual risks:** the three deferred items in frontmatter (assertion/timeout tripwire precision; `prior_contents` producer must land with the GATING wiring story or every MODIFY fails closed). The follow-up-review risk named above.
