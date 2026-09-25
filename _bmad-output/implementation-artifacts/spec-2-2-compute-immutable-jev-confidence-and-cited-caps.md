---
title: 'Story 2.2 — Compute immutable Jev confidence and cited caps'
type: 'feature'
created: '2026-09-25'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: d090b60ada830a9a3ba530a0fbf06c19be2868c4
context: ['{project-root}/AGENTS.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Nothing yet turns one Jev answer into the single trusted "how sure" number (AD-9). 2.1's guards consume `confidence_below_cutoff` but nothing produces it; caps, the Noul injection screen, the class override and the blame-free rule have no code.

**Approach:** Pure, deterministic domain logic plus config readers. A Jev-result contract; a frozen `ClassConfidence` value object (`confidence` = min over `confidence_jev` and cap values, computed, never set); a Noul-screen step that can only add a `jev_signal`-cited cap; a separate `RouteConfidence` type; pure predicates (below cutoff, class escalation with override, attribution allowed); new cut-offs in `guardrails/thresholds.yaml` read by the one loader.

### Decisions (human, 2026-09-25)

- **A:** sprint-status "2.1 done" committed on `main` (d090b60a) before branching.
- **B:** `TriageVerdict` gets a `model_validator`: `confidence == min(confidence_jev, *cap.value)`. The min rule has one home (`contracts.verdict.effective_confidence`), reused by `ClassConfidence`. The 0.2 sample in `tests/contracts/test_verdict.py` is inconsistent with AD-9 (0.8 vs min 0.85) and its bounds test sets `confidence` alone; both get fixed deliberately and are reported.
- **C:** `ReviewThresholds` → `Thresholds`; keeps flat `review_max_rounds` and `workflow_path_glob` (2.1 tests untouched) and gains `confidence: ConfidenceCutoffs`. One file, one loader.
- **D:** Noul is a probability (SDK 0.7.1 `NoulAnswer.noul: float`), so the injection screen has two settings: `cutoff` (positive when `noul >= cutoff`) and `cap` value. Placeholders: class 0.75, no-route 0.6, screen cutoff 0.5, screen cap 0.5; each commented `ASSUMPTION — OQ-2, not calibrated`.
- Developer docs are written in very simple words, no jargon.
- **Review #5 (human, 2026-09-25):** keep `injection_screen_cap: 0.5` below `class_cutoff`, so a positive injection screen always sends the run to a human via the ordinary `low_confidence` check (the screen still has no escalation reason of its own). Placeholder until OQ-2 calibration.

## Boundaries & Constraints

**Always:** `confidence_jev` frozen once built; `confidence` is computed, with no setter or constructor argument; caps only lower or keep it; decision functions never receive `probabilities`; cut-offs only from thresholds YAML; tests read `tests/fixtures/thresholds.test.yaml`, never the real file; "below" means `confidence < cutoff` (at the cut-off is not below).

**Never:** Jev/Anthropic calls; the Jev agent; DB columns; routing/registry (AD-10); edits to 2.1's transition table, guards or tests; `guardrails/` importing anything beyond `contracts` + pydantic + stdlib.

## I/O & Edge-Case Matrix

| Scenario | Input | Expected |
|---|---|---|
| No caps | jev 0.9 | confidence 0.9 |
| Cap above jev | jev 0.6, cap 0.8 | 0.6 |
| Several caps | jev 0.9, caps 0.7, 0.5 | 0.5 |
| Uncited cap | `Cap(citations=[])` | `ValidationError` |
| Set confidence / change jev | assignment | error (frozen / no setter) |
| Noul positive | noul ≥ screen cutoff | +1 cap citing `jev_signal`, value = screen cap; no escalation |
| Noul negative | noul < cutoff | unchanged, no cap |
| At class cutoff | conf == cutoff | not below |
| Unknown class | class `unknown` | `unknown_class` (unless overridden) |
| Override set | any class/conf | no class escalation; both confidence values unchanged |
| Attribution | `AWAITING_APPROVAL` / `REPORTING` / below cutoff (override or not) | false |
| Wrong type | `RouteConfidence` into `below_class_cutoff` | `TypeError`; mypy error |

</frozen-after-approval>

## Code Map

- `contracts/verdict.py` -- `Cap` (already requires ≥1 citation, reuse); `TriageVerdict` gets the validator; add `effective_confidence(confidence_jev, caps)`.
- `contracts/citations.py:59` -- `JevSignalCitation(answer=...)`, reuse for the screen cap.
- `contracts/enums.py` -- `FailureClass`, `EscalationReason` reused.
- `workflow/thresholds.py` -- one loader; `transitions.py:211` reads `.review_max_rounds` (keep the name).
- `workflow/run_states.py` -- `RunState` (attribution needs it, so attribution lives in `workflow/`).
- `workflow/transitions.py:37` -- `GuardInput.confidence_below_cutoff` is the consumer; not edited.
- `scripts/generate_schemas.py:31` -- add `JevClassification` to `ENVELOPE_MODELS`.
- SDK 0.7.1 (checked in the installed source; context7 had only DeepWiki summaries): `ChoiceAnswer{type,choice:str,confidence:float,probabilities:dict[str,float]}`, `NoulAnswer{type,noul:float}`, frozen pydantic.

## Tasks & Acceptance

**Execution (TDD: each test first, red for the right reason):**
- [x] `contracts/jev.py` -- `JevChoice{answer: FailureClass, confidence, probabilities: dict[FailureClass,float]}`, `JevInjectionScreen{noul}`, `JevClassification{choice, injection_screen}`; frozen, extra forbid.
- [x] `contracts/verdict.py` -- `effective_confidence` + `TriageVerdict` min validator.
- [x] `guardrails/confidence.py` -- `ConfidenceCutoffs`, `ClassConfidence` (`from_jev`, `with_cap`, computed `confidence`), `RouteConfidence`, `apply_injection_screen`, `below_class_cutoff`, `class_escalation`.
- [x] `workflow/attribution.py` -- `attribution_allowed(state, confidence, cutoffs)`.
- [x] `workflow/thresholds.py` + `guardrails/thresholds.yaml` -- rename, confidence section.
- [x] `scripts/generate_schemas.py`, `guardrails/schemas/JevClassification.json` -- regen.
- [x] Tests: `tests/contracts/test_jev.py` (SDK answers convert cleanly), `tests/contracts/test_verdict.py` (validator + fixture fix), `tests/guardrails/test_confidence.py`, `tests/workflow/test_attribution.py`, `tests/fixtures/thresholds.test.yaml`.
- [x] `docs/DEVELOPER.md`, `guardrails/README.md` -- simple-words docs.

**Acceptance Criteria:** see the matrix; plus all 2.1 tests pass unchanged, and a varied `probabilities` map gives an identical `ClassConfidence`.

## Implementation Notes

## Spec Change Log

## Review Triage Log

| # | Finding (source) | Verdict | Evidence | Route |
|---|---|---|---|---|
| 1 | `Cap` mutable → confidence can rise (blind, edge) | high | `Cap` has no `frozen`; edge hunter ran `cc.caps[0].value=1.0` → 0.5→0.9 | patch |
| 2 | `TriageVerdict` mutable → validator bypass (edge) | medium | no `frozen`/`validate_assignment`; `caps.clear()` after validation passes | patch |
| 3 | `probabilities` unbounded (blind, edge) | low | `dict[FailureClass, float]`, no bounds; 5.0 accepted | patch |
| 4 | `probabilities` dict mutable in place (blind, edge) | low | true, but audit-only, no decision reads it (AD-9); immutable-mapping fix adds complexity | rejected (low) |
| 5 | Positive screen always escalates with shipped 0.5 cap < 0.75 cutoff (blind) | resolved | Human chose option 1 (keep 0.5). AD-11 "never blocks on its own" read as: no screen-specific reason; lowered number then hits the ordinary cut-off. Placeholder values (OQ-2) decide the effect | human question |
| 6 | `attribution_allowed` deny-list fails open for other states (blind, edge) | false | AD-27 names exactly AWAITING_APPROVAL, REPORTING, below-cutoff; pre-classification states have no `ClassConfidence` to pass; spec matrix matches | rejected |
| 7 | UNKNOWN class above cutoff allows attribution (edge) | false | unknown class escalates to AWAITING_APPROVAL(unknown_class) → blame-free by state | rejected |
| 8 | Override to UNKNOWN skips unknown-class check (edge) | low | AD-14 `--class` is a human choice; guarding adds a branch; unlikely | rejected (low) |
| 9 | `class_escalation(RouteConfidence)` → AttributeError, silent with override (blind, edge) | low | verified by edge hunter | patch |
| 10 | `from_sdk` unknown label → bare ValueError (blind, edge) | low | loud failure is correct here; typed AD-22 error belongs at the Jev agent edge (E3) | defer |
| 11 | `load_thresholds` copies fields by hand; DEVELOPER.md "add a line" wrong (blind, clean-code, edge) | medium | `workflow/thresholds.py` builds `ConfidenceCutoffs(...)` field by field; misspelled key ignored | patch |
| 12 | `no_route_cutoff` / `RouteConfidence` unused (blind, clean-code) | false | explicitly requested by the human (brief §3, §4) | rejected |
| 13 | Tests hard-code fixture numbers 0.75 / 0.49 (blind, clean-code) | low | trivial derive-from-CUTOFFS fix | patch |
| 14 | No test where caps pull confidence below cutoff (verification-gap) | medium | pre-verified: swapping to `confidence_jev` passes all tests | patch |
| 15 | No `unknown`+below row; check order unpinned (verification-gap) | low | pre-verified | patch |
| 16 | 2.1 tests read real thresholds; doc overclaims; fixture not key-synced (blind, verification-gap) | low | `test_transitions.py:31`; doc line in DEVELOPER.md | patch (doc + key-sync test; 2.1 untouched) |
| 17 | Duplicate injection caps on repeat call (blind, edge) | low | confidence unchanged; one-call-per-run is AD-11; guard adds branch | rejected (low) |
| 18 | Exact float equality in verdict validator (blind) | false | `min` returns one input unchanged; JSON float round trip is exact | rejected |
| 19 | Import order I001 in test_verdict (blind, clean-code) | low | ruff I001 confirmed | patch |
| 20 | USER-GUIDE no-change reason missing (blind) | false | recorded in story report, per AGENTS.md step 8 | rejected |
| 21 | No drift test for JevClassification.json (blind) | false | drift gate covers every `ENVELOPE_MODELS` entry and orphans | rejected |
| 22 | Comments cite non-existent "AGENTS.md Boundaries & Constraints" (clean-code) | low | grep confirms two sites | patch |

## Verification

**Commands:**
- `make check` -- expected: green (layer contract, schema drift, ruff, mypy --strict, pylint dup, pytest ≥85%).
