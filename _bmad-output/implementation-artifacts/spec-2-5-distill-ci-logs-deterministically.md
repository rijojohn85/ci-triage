---
title: 'Story 2.5 — Distill CI logs deterministically'
type: 'feature'
created: '2026-09-26'
status: 'done'
route: 'dispatch'
baseline_revision: '81528a2a98dae0fff02d26d3b0db46181c1b1355'
review_loop_iteration: 0
followup_review_recommended: false
context: ['{project-root}/AGENTS.md']
warnings: ['oversized']
deferred:
  - summary: >-
      The injection defence for retained lines (marker lines, their indented continuations, the fallback line) rests on the request builder passing distilled output only as delimited untrusted data.
    evidence: |-
      The spec's AC2 assigns actual request-builder enforcement to a later integration story; the distiller drops non-evidence narrative but cannot guarantee instruction-free text without also discarding stack-trace source lines.
    location: >-
      workflow/distiller.py
    severity: medium (unverified)
---

## Build Brief

**(1) Story + key:** 2.5 — Distill CI logs deterministically; sprint-status key `2-5-distill-ci-logs-deterministically`.

**(2) ACs in one line:**
- **AC1:** given CI text and JUnit XML fixtures, the distiller keeps error blocks and stack traces, drops narrative outside them, strips ANSI/control characters, numbers the lines, and bounds the output by `max_bytes` read from `thresholds.yaml` — deterministically.
- **AC2:** injected narrative, control characters and overlong lines are filtered/truncated by contract/security fixtures with no model call; RT-01 pytest receipts identify exactly the surviving untrusted evidence; the output contract is the only log form exposed to request builders (enforcement checked by a later integration story).

**(3) Binding ADs:** **AD-20** (no LLM sees raw logs; keep error blocks and stack traces, drop narrative, strip ANSI/control characters, number lines, truncate at max bytes; untrusted data passed as data, never instructions). **AD-19** (distiller max bytes lives only in `guardrails/thresholds.yaml`, read through the one loader). **AD-24** (the numbered distilled log is the evidence-pack log; `DistilledLogLine` is its shape). **AD-7** (line numbers are the `log_line` citation anchors, so they must be stable).

**(4) Files:**
- Create: `workflow/distiller.py` (`DistilledLogLine` output via `contracts.evidence`; pure `distill(ci_log, junit_xml, limits)`); `tests/security/test_distiller.py`.
- Change: `guardrails/thresholds.yaml` + `tests/fixtures/thresholds.test.yaml` (add the `distiller.max_bytes` key); `workflow/thresholds.py` (`Thresholds` gains `distiller`); `tests/fixtures/thresholds.py` if a convenience constant helps; `docs/DEVELOPER.md`, `guardrails/README.md`.
- **NOT touched:** `contracts/evidence.py` (`DistilledLogLine` already exists; no change), the evidence-pack builder (2.7), `run_step` (2.3), A2A projection (2.4), gateway, agents, prompts, risk gate.

**(5) Approach (SOLID/DRY):**
- **S:** `workflow/distiller.py` is a pure text transform — no I/O, no model, no network, no clock; thresholds are passed in (loaded by the caller through `workflow.thresholds`).
- **O:** the error markers are one ordered registry (prefix/regex entries); a new CI error style is a new entry, not a new branch.
- **DRY:** the boundary model and its `max_bytes` live once in `workflow/thresholds.py`/`thresholds.yaml`; line numbering uses `DistilledLogLine.line_number` (contract) instead of embedding numbers in text; JUnit parsing uses stdlib `xml.etree.ElementTree`.
- **D:** the distiller returns contract types (`list[DistilledLogLine]`), so the future evidence pack (2.7) and request builders consume the same shape.

**(6) TDD plan (red-first; names cite ACs):** AC1 `test_ac1_keeps_error_block_and_stack_trace_and_drops_narrative`, `test_ac1_numbers_lines_from_one`, `test_ac1_strips_ansi_and_control_characters`, `test_ac1_junit_failures_become_evidence`, `test_ac1_output_respects_max_bytes`, `test_ac1_same_input_same_output`; AC2 `test_ac2_injected_narrative_never_survives`, `test_ac2_overlong_line_truncated_utf8_safe`, `test_ac2_junit_with_entities_is_not_expanded`, `test_ac2_no_model_or_network_imports`, `test_ac2_rt01_surviving_untrusted_evidence_is_only_error_evidence`, `test_ac2_output_is_contract_type`; thresholds `test_ac3_distiller_max_bytes_loads_from_fixture` (and the existing fixture/real key-parity test must keep passing).

**(7) Risks / OQ:** `distiller.max_bytes` gets a documented default (placeholder, like the OQ-2 cut-offs); tests exercise truncation with explicit small limits. When no error marker and no JUnit evidence is present, the distiller emits the final non-empty line as the single evidence line (deliberate fallback; `EvidencePack.distilled_log` requires ≥1 line — flagged for human review). JUnit XML is untrusted: DTD/ENTITY-bearing documents yield no JUnit evidence (never expanded). Line numbers are `log_line` citation anchors, so truncation must never renumber. No OQ remaining.

**(8) Doc impact:** `docs/DEVELOPER.md` — new "Distilling CI logs (story 2.5)" section in plain words (why models never see raw logs, what counts as evidence, how numbering and the byte bound work), 2.5 in "Built so far", rows for `workflow/distiller.py` and the `distiller` threshold in "Where things live", and the extend note (a new error style is a new marker entry; change the bound only in `thresholds.yaml`). `docs/USER-GUIDE.md` — no doc change: internal evidence handling, no user-visible flow.

<intent-contract>

## Intent

**Problem:** Raw CI logs are untrusted and huge; feeding them to a model risks prompt injection and wasted tokens, and there is no stable line numbering for `log_line` citations. A failed run's useful signal is its error blocks and stack traces, but today nothing extracts them deterministically.

**Approach:** Add a pure `workflow/distiller.py`: strip ANSI/control characters, keep only error blocks and stack traces (plus JUnit `<failure>`/`<error>` content as evidence) using an ordered marker registry, drop everything else, number the survivors via `DistilledLogLine`, and clip the numbered output to `distiller.max_bytes` from `guardrails/thresholds.yaml`. Same input always yields the same output.

## Boundaries & Constraints

**Always:** be pure and deterministic (no clock, network, model, filesystem, or dict-order dependence); strip ANSI escapes and non-printing control characters; keep error blocks/stack traces; drop narrative outside them; number kept lines from 1 via the contract field; read the byte bound from the thresholds loader; treat JUnit XML as untrusted data; return `list[DistilledLogLine]`.

**Never:** call a model or any network; pass raw log text through; let an injected instruction in narrative survive; expand XML entities/DTDs; renumber surviving lines on truncation; add a new thresholds key outside `thresholds.yaml`; edit `contracts/` or the evidence-pack builder.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| ERROR_BLOCK | narrative + Python traceback | only the traceback lines, numbered from 1 | none |
| NARRATIVE_ONLY | chatter with no marker | fallback: final non-empty line only | documented fallback |
| ANSI_CONTROLS | colour codes, `\r`, `\b`, NUL | codes/controls removed, text preserved | none |
| JUNIT_FAILURE | `<failure message=...>` + stack text | test id + stack become evidence lines | none |
| JUNIT_ENTITIES | DOCTYPE/ENTITY (billion-laughs) | no JUnit evidence; no expansion | treated as untrusted, skipped |
| OVERLONG_LINE | one line > bound | clipped at a UTF-8 boundary; number kept | deterministic clip |
| BYTE_BOUND | many evidence lines | emitted prefix within `max_bytes` | deterministic stop |
| NO_EVIDENCE | empty/whitespace log | one line (fallback) so the pack stays valid | documented fallback |

</intent-contract>

## Code Map

- `contracts/evidence.py:21` — `DistilledLogLine{line_number: PositiveInt, text: str}`; the output type. Do not edit.
- `contracts/citations.py:28` — `LogLineCitation.log_line` anchors to these numbers; stability matters.
- `workflow/thresholds.py` — `Thresholds` + one loader; add a frozen `DistillerLimits(max_bytes: PositiveInt)` and read `raw["distiller"]["max_bytes"]` (mirror the confidence section).
- `guardrails/thresholds.yaml` — add `distiller: {max_bytes: <n>}` (AD-19); keep the adaptive "placeholder" comment style used for the cut-offs.
- `tests/fixtures/thresholds.test.yaml` + `tests/fixtures/thresholds.py` — fixture copy and constants; `tests/workflow/test_thresholds.py` enforces key parity between fixture and real file.
- `tests/security/` — where the spec's verification table places deterministic distiller tests.
- stdlib only: `re`, `xml.etree.ElementTree` (no new dependency).

## Tasks & Acceptance

**Execution:**
- `tests/security/test_distiller.py` -- write failing AC tests first (red) -- TDD per AGENTS.md
- `workflow/thresholds.py`, `guardrails/thresholds.yaml`, `tests/fixtures/thresholds.test.yaml` -- the `distiller.max_bytes` key + frozen loader field -- AC1/AD-19
- `workflow/distiller.py` -- `distill(ci_log, junit_xml, limits) -> list[DistilledLogLine]`; `_strip_controls`, `ERROR_MARKERS` registry, `_junit_evidence`, `_clip_to_bytes` -- AC1/AC2
- `tests/security/test_distiller.py` -- fixtures for ANSI, traceback, narrative injection, JUnit, overlong line, byte bound, entities -- AC1/AC2
- `docs/DEVELOPER.md`, `guardrails/README.md` -- docs (brief part 8)

**Acceptance Criteria:**
- Given a log with narrative and a traceback, when distilled, then only the traceback lines remain, numbered from 1 (AC1).
- Given ANSI/control characters, when distilled, then they are gone and the surviving text is unchanged otherwise (AC1).
- Given JUnit XML failures, when distilled, then test id and stack text appear as numbered evidence (AC1).
- Given many evidence lines and a `max_bytes` limit, when distilled, then the emitted numbered output is within the bound and identical across runs (AC1).
- Given narrative carrying an injected instruction, when distilled, then it does not appear in the output (AC2).

## Verification

**Commands:**
- `.venv/bin/pytest tests/security/test_distiller.py -q` -- expected: green, red-first history noted
- `.venv/bin/pytest tests/workflow/test_thresholds.py -q` -- expected: fixture/real key parity still green
- `make check` -- expected: PASS

**Manual checks:**
- Confirm `workflow/distiller.py` imports no `anthropic`, `httpx`, `requests`, or `a2a` (pure transform).

## Review Triage Log

### 2026-09-26 — Review pass

- verdicts: 30 findings — high 0, medium 0, low 30, false 0, maybe-false 0
- findings:
  - `[low]` `[reject]` an instruction-like line indented directly under a kept marker survives as a continuation — the continuation is what keeps stack-trace source lines; AD-20's injection defence is that all retained lines are untrusted data, delimited downstream (the spec defers that enforcement). Pinned by a new test.
  - `[low]` `[reject]` the approved narrative-only fallback can echo a final instruction — the human explicitly approved the final non-empty line as the exit signal; it is untrusted data like every retained line. Pinned by a new test.
  - `[low]` `[patch]` JUnit evidence skipped control-stripping — every JUnit line now passes through `_strip_controls`.
  - `[low]` `[reject]` the DTD/ENTITY guard is case-sensitive — XML markup declarations are uppercase, so a lowercase form is invalid XML and `ElementTree` rejects it; nothing expands.
  - `[low]` `[reject]` `max_bytes` has no upper bound — the bound is a configured placeholder; a too-large value is an operator choice, not a code defect.
  - `[low]` `[reject]` no line-count bound — the byte bound caps total evidence; serialization framing is metadata and 2.7 owns the rendered shape.
  - `[low]` `[reject]` clipping stops after the first truncated line — the clip consumes the remaining budget, so later lines would not fit anyway.
  - `[low]` `[reject]` the ordered marker registry is used with `any()` — order is irrelevant to membership; the registry is the open/closed extension point.
  - `[low]` `[reject]` framing bytes are not counted toward `max_bytes` — the bound is defined on evidence text and documented; the pack's rendered size is 2.7's concern.
  - `[low]` `[reject]` a DTD-bearing or malformed JUnit document yields no JUnit evidence silently — that is the documented AD-20 untrusted-input behaviour; the CI text still yields evidence.
  - `[low]` `[reject]` making `distiller` required on `Thresholds` hard-breaks a config without the key — both in-repo files carry it and the key-parity test enforces it; one repo, one committed file.
  - `[low]` `[patch]` the 2.5 story row omitted the changed test files — added.
  - `[low]` `[reject]` test placement (tests/security vs tests/workflow) — the spec's verification table places the deterministic distiller tests under `tests/security/`; the loader test belongs with the other threshold tests.
  - `[low]` `[patch]` no test asserted contiguous numbering across combined CI + JUnit evidence — added.
  - `[low]` `[reject]` `test_ac1_same_input_same_output` is a weak determinism check — the function is pure with no module state; the test plus the purity scan is proportionate.
  - `[low]` `[reject]` the forbidden-import list is hand-written — a structural purity check complements the behavioural tests.
  - `[low]` `[reject]` the thresholds placeholder comment omits an OQ id — the bound is a placeholder like the OQ-2 cut-offs; it is not a labelled calibration open question.
  - `[low]` `[reject]` `_junit_header` ignores the `type` attribute and a message may contain newlines — the test id and message are the evidence; the type is optional detail.
  - `[low]` `[patch]` duplicate of the JUnit control-stripping finding — same fix.
  - `[low]` `[reject]` duplicate of the indented-continuation injection finding.
  - `[low]` `[reject]` a literal `<!DOCTYPE` inside JUnit CDATA skips the whole report — a conservative, documented skip of untrusted XML; CDATA in a failure body is not the expected shape.
  - `[low]` `[patch]` C1 controls (U+0080–U+009F) survived — the control class now removes them.
  - `[low]` `[patch]` namespaced JUnit tags yielded no evidence — JUnit matching now uses local tag names.
  - `[low]` `[reject]` duplicate of the fallback injection finding.
  - `[low]` `[patch]` the JUnit `<error>` branch was untested (verification-gap) — added a test.
  - `[low]` `[patch]` the narrative-only fallback was untested (verification-gap) — added a test.
  - `[low]` `[patch]` indented-continuation survival was unpinned (verification-gap) — added a test pinning the retained untrusted-evidence behaviour.
  - `[low]` `[reject]` intent-alignment: the intent's broader semantic expectations ("error blocks", "instructions never survive", "bound from the loader") sit wider than the internal-regex surface the tests pin — the approved readings (marker filter, distilled-index numbering, text-byte bound) are what the spec's matrix and the human's fallback decision settled.
  - `[low]` `[patch]` duplicate of the fallback untested finding (clean-code).
  - `[low]` `[reject]` duplicate of the fallback injection finding; the doc was softened to say retained lines are untrusted data.
  - `[low]` `[patch]` duplicate of the JUnit `<error>` untested finding (clean-code).

## Auto Run Result

Status: done
Baseline: `81528a2a98dae0fff02d26d3b0db46181c1b1355`.

**Summary.** Built the deterministic AD-20 distiller: `workflow/distiller.py` strips ANSI/control characters, keeps only error-marker lines, their indented continuations and JUnit `<failure>`/`<error>` content, numbers the survivors via `contracts.evidence.DistilledLogLine`, and clips the kept evidence text to `distiller.max_bytes` read through the one thresholds loader. It is pure — no model, network, filesystem or clock — so the same input always yields the same output and the `log_line` anchors stay stable. DTD/entity-bearing JUnit is skipped whole, and an empty/narrative-only log falls back to one line as the approved design.

**Files changed (one line each):**
- `workflow/distiller.py` — the pure distiller (`ERROR_MARKERS`, control stripping, JUnit evidence, UTF-8 clip).
- `workflow/thresholds.py`, `guardrails/thresholds.yaml`, `tests/fixtures/thresholds.test.yaml`, `tests/fixtures/thresholds.py` — the `distiller.max_bytes` bound and its loader.
- `tests/security/test_distiller.py`, `tests/workflow/test_thresholds.py` — AC tests.
- `docs/DEVELOPER.md`, `guardrails/README.md` — docs.

**Review findings.** 30 reported: 0 high, 0 medium, 30 low. Patched 11 entries (JUnit control-stripping, C1 controls, namespaced JUnit tags, the approved fallback/continuation/`<error>`/numbering tests, and the docs); deferred 1 (downstream request-builder enforcement of untrusted delimited data, which the spec's AC2 assigns to a later integration story); rejected 18 with reasons above.

**Patched root causes:** JUnit evidence now goes through the same control strip as CI text; C1 controls are removed; JUnit tags match by local name; and the previously unpinned behaviours (JUnit `<error>`, the approved narrative fallback, indented continuations, contiguous numbering) are covered by tests and described honestly in the docs.

**Follow-up review recommendation: false.** No high and no two-or-more-medium entries were patched, so the work has converged.

**Verification performed:**
- `git diff` reviewed since baseline, then re-generated after patches.
- `make check` → PASS (276 tests, coverage 94.91%, distiller 95%).
- `.venv/bin/pytest -m integration -q` → 31 passed (unchanged; this story is pure logic).
- Manual: `workflow/distiller.py` imports no model/network/clock module.

**Residual risks:** the byte bound counts evidence text, not serialized framing (2.7 owns the rendered shape); retained lines (markers, continuations, the fallback) are untrusted data whose injection defence is the request builder marking them delimited/untrusted (a later integration story); the distiller retains no original log positions, by design (AD-7 numbers the distilled log).

## Spec Change Log

<!-- none: no bad_spec loopback on this story -->
