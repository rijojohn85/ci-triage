---
title: 'Publish shared payload contracts and generated schemas (Story 0.2)'
type: 'feature'
created: '2026-09-25'
status: 'done' # review passed locally; human review pending on PR
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '98030e12273afcd22620282aa8f3c34291591c8f'
context: ['{project-root}/AGENTS.md', '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Epic 0's layout has no shared typed payload package, so the future agents, workflow and guardrails would each invent their own shapes and drift apart (AD-6's prevented failure).

**Approach:** Build the `contracts/` Pydantic v2 package with the exact spine enums and shapes (AD-1, AD-4, AD-6, AD-7, AD-9, AD-12, AD-14, AD-24, AD-26, AD-27), generate JSON Schemas into `guardrails/schemas/` with a committed-output drift gate, and hand-write tests that validate representative payloads against the spine definitions.

## Boundaries & Constraints

**Always:**
- Field names and enum values are the spine's domain words, verbatim: failure class `code|flaky|infra|external|unknown`; risk_tier `normal|blocked|not_gated`; terminal_state null while running, else `pr_opened|report_sent|input_required|rejected_by_human|failed`; citation kinds `log_line|commit|metric|history_row|jev_signal`; objection severity `info|minor|major|dangerous`; diff ops `add|modify|delete`; escalation_reason exactly `low_confidence|unknown_class|no_route|validation_failed|review_rejected|gate_blocked`.
- Cap shape (decided by human 2026-09-25): `Cap {value: float in [0,1], reason: str, citations: [Citation]}` — AD-9 cited reason is required per cap.
- Production models accept full 40-char hex SHAs only; a separate AD-26 dry-run boundary type accepts a unique ≥7-char prefix; agent-facing `AgentError` is `{code, message, retryable}`; `class_override` appears on the approval payload.
- `contracts/` stays dependency-light: stdlib + pydantic only. The layer-contract script is amended to admit pydantic + intra-package imports for `contracts/`/`guardrails/` (AD-6 wins over the 0.1 stdlib-only wording).
- Every AC maps to at least one named test with the AC number in its name; `make check` stays the single gate, extended with a schema-drift target that regenerates and diffs.

**Never:**
- No `workflow/` state machine, risk gate, citation checker or distiller; no persistence (`run_step`, `triage_run`); no A2A server/client transport; no agents; no promptfoo changes; no edits to epics, spec, spine.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Verdict happy path | Representative TriageVerdict payload with all spine fields, terminal_state null, proposed_diff and quarantine null | Validates; all AD-6 fields present | N/A |
| Bad enum | class "async", severity "critical", op "rename", citation kind "guess" | ValidationError on each | Message names the field and allowed values |
| Short SHA in production | TriageVerdict suspect sha "abc1234" | ValidationError | Short prefix only accepted by the AD-26 dry-run type |
| Schema drift | Regenerated schema differs from guardrails/schemas/ | Drift check fails non-zero | After rerun of generator, zero diff |

</frozen-after-approval>

## Open Questions

(none — all resolved)

## Code Map

- `contracts/README.md` -- description-only today; replaced per-module README kept asis where true.
- `contracts/` (new) -- one model family per module: `enums.py`, `citations.py`, `verdict.py`, `evidence.py`, `errors.py`, `approval.py`, `a2a.py`; zero app-layer imports (AST-checked).
- `guardrails/schemas/` (new files) -- committed JSON Schemas, one per public envelope model.
- `scripts/generate_schemas.py` (new) -- deterministic generator: `Model.model_json_schema(mode='validation')` per model, sorted-key stable dump; run manually + by check.
- `scripts/check_layer_contract.py` -- amend allowlists: `contracts/` may import stdlib+pydantic+self; `guardrails/` + self; asserts/behavior unchanged otherwise. Do NOT reformat beyond ruff clean.
- `Makefile`, `pyproject.toml` -- add `make schema-drift` target and wire into `check`.
- `tests/contracts/` (new) -- pytest suites per AC; no I/O.
- `guardrails/schemas/README.md`, `contracts/README.md`, `guardrails/README.md` -- keep, extend only where stale.

## Tasks & Acceptance

**Execution:**
- [x] `tests/contracts/test_enums.py` + `test_citations.py` -- RED first: failure-class, risk-tier, terminal-state, citation-kind, severity and diff-op membership/invalid-rejection tests naming AC1/AC2 (e.g. `test_ac2_citation_kind_is_closed`) -- TDD discipline, tests before models.
- [x] `contracts/` modules -- GREEN: enums, discriminated Citation union, Cap/Suspect/ProposedDiff/Quarantine/TriageVerdict, EvidencePack, AgentError, approval payload, escalation, A2A DataPart envelope -- the models the tests ask for.
- [x] `tests/contracts/test_verdict.py`, `test_evidence.py`, `test_error_and_approval.py` -- RED→GREEN for AC1 nullable rules, AC3 AgentError/escalation/class_override, run_id/task_id/contextId convention fields, short-SHA rejection -- behaviors at the package's public boundary.
- [x] `scripts/check_layer_contract.py` -- allow pydantic + self-import for contracts/guardrails -- 0.1 wording conflicts with AD-6; report in story notes.
- [x] `scripts/generate_schemas.py` + committed schemas + `make schema-drift` in `check` -- AC3 drift gate, `Makefile` -- CI-equivalent enforcement without a CI runner yet (no .github/ by 0.1).
- [x] `make check` full pass, coverage ≥85% on contracts -- end-of-story proof in evidence table.

**Acceptance Criteria:**
- Given the spine contract definitions (AD-6), when a representative TriageVerdict payload validates, then every named field with spine nullability exists and `class`/`risk_tier`/`terminal_state` accept exactly the spine value sets (AC1).
- Given invalid enum values or malformed structures in agent and approval payloads, when validated, then `ValidationError` names the field and closes: citations five kinds, severities four, diff ops three, SHAs full 40-char in production models (AC2).
- Given EvidencePack, AgentError and A2A DataPart contracts, when schemas regenerate, then committed `guardrails/schemas/` output is byte-identical and any drift fails the check; escalation six values and approval `class_override` are present in contracts (AC3).

## Implementation Notes

- Confirmed constraint turns: story 0.1's checker says "contracts imports nothing but stdlib"; spine AD-6 mandates pydantic. Spine wins; amendment is deliberate and recorded here.
- Terminal state null-while-running: `terminal_state: TerminalState | None = None` where presence of any of the terminal values maps AD-1/AD-4 table `COMPLETED|FAILED` outcomes.
- Implemented by subagent; main verified against the diff. `pytest --cov` needed `pythonpath=["."]` in pyproject (pytest 9 dropped implicit repo-root sys.path).
- Added `contracts/objections.py` post-verification gap fix: AD-6/AD-12 reviewer objection `{severity, category, claim, citation}`; severity enum existed but the shape did not. TDD red→green: `tests/contracts/test_objections.py` (ModuleNotFoundError → 2 passed). Not an envelope schema by design (nested in the future reviewer payload).
- `$defs`-embedded nested models: Cap, Suspect, DiffFile, Citation kinds, Objection, CommitRecord, CandidateSuspect, DistilledLogLine, HistoryRow, Escalation; envelope files only for the six public payloads.
- Layer checker allowlists: `contracts/` stdlib+pydantic+self; `guardrails/` contracts+pydantic+self (+stdlib); asserted by `test_ac3_layer_contract_admits_pydantic_and_self_import`.
- `UUID7` used in `a2a.py` for the AD-4 convention; pydantic parses RFC 9562 without the 3.14-only `uuid7` constructor, keeping the >=3.10 floor honest.

## Spec Change Log

(empty)

## Review Triage Log

(empty)

<!-- Pass 1 (4 layers, 2026-09-25). Verdicts verified against code. -->
<!-- Groups (root cause → route): -->
<!-- G1 DataPart task_id/run_id/contextId equality unenforced (blind+edge+clean) — verified: no validator, no mismatch test |
     medium | patch -->
<!-- G2 Cap.citations=[] accepted though AD-9 needs cited reason; Suspect.citations=[] accepted though AD-27 needs commit+log_line;
     test_ac2_cap_reason_requires_one_cited_citation asserts empty reason instead | medium | patch -->
<!-- G3 ApprovalPayload.decision str-pattern accepts "approve\n" (re $ before newline) | low | patch (Literal) -->
<!-- G4 validate_enum_value: docstring/return mismatch; _VALUE_SETS name-dict duplicates enum values, empty set for unknown enums |
     medium | patch -->
<!-- G5 SHA handled 3 ways (_SHA40_PATTERN, inline CommitCitation pattern, Sha40); FULL_SHA literal ×3 test files | medium | patch -->
<!-- G6 DataPart payload union lacks discriminator | low (disjoint extra=forbid shapes; smart-union unambiguous today) | reject (discriminator = new public field) -->
<!-- G7 Objection orphaned from envelopes | false — deliberate, recorded in spec Implementation Notes; reviewer envelope owned by later story -->
<!-- G8 drift gate blind to stale/renamed-model schema files | medium | patch -->
<!-- G9 layer checker: only happy path tested (no negative test); relative imports mishandled (from .enums = false positive; level≥2 admitted); |
     check_contracts/check_guardrails byte-duplicate loops | medium | patch -->
<!-- G10 Makefile schema-drift target wiring untested | low | patch (make -n test) -->
<!-- G11 uuid.uuid7() in tests breaks 3.10 floor | medium | patch (fixed v7 literals) -->
<!-- G12 mypy find stderr noise on missing dirs | low | patch -->
<!-- G13 contracts README omits objections.py; __init__ comment states wrong reason | low | patch -->
<!-- G14 TriageVerdict alias round-trip: dump emits class_, revalidate fails | medium | patch (populate_by_name + serialize_by_alias) |
<!-- G15 duplicate escalation-set test in test_drift | low | patch (fold, keep enums-test as source) -->
<!-- G16 ShaPrefix unused in prod payloads | false — deliberate AD-26 boundary type for later dry-run story; tested -->
<!-- G17 DataPart closure untested (top-level extra, unknown variant) | low | patch (tests only) -->
<!-- G18 evidence table | false — post-review artifact, step-05 -->
<!-- G19 CommitRecord.author_login allows "" | low | patch -->
<!-- G20 EvidencePack.metrics allow NaN/Inf → invalid JSON | low | patch (allow_inf_nan=False) -->
<!-- G21 DiffFile delete-with-content | low — Proposer output shape-level; contradicting-op guard is validator/2.x domain | reject |
<!-- G22 citation-locator-vs-pack cross-checks (log_line>len, metric keys…) | false — AD-7 resolution is orchestrator/citation_check duty; contracts hold shapes |
<!-- G23 brittle PASS-substring assertion on checker stdout | low | patch (exit code only) |
<!-- G24 checker PASS wording test pollution / generate_schemas regenerate() returns discarded dict | low | patch |
<!-- G25 test_drift portability: .venv/bin/python hardcoded, cwd-relative paths, dead ignore_patterns | medium | patch |

## Verification

**Commands:**
- `make check` -- expected: all gates green, exit 0, including new schema-drift target.
- `.venv/bin/pytest tests/contracts -q` -- expected: all named AC tests pass.
