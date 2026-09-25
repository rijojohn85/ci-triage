---
title: 'Publish shared payload contracts and generated schemas (Story 0.2)'
type: 'feature'
created: '2026-09-25'
status: 'ready-for-dev'
route: 'dispatch'
review_loop_iteration: 0
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
- [ ] `tests/contracts/test_enums.py` + `test_citations.py` -- RED first: failure-class, risk-tier, terminal-state, citation-kind, severity and diff-op membership/invalid-rejection tests naming AC1/AC2 (e.g. `test_ac2_citation_kind_is_closed`) -- TDD discipline, tests before models.
- [ ] `contracts/` modules -- GREEN: enums, discriminated Citation union, Cap/Suspect/ProposedDiff/Quarantine/TriageVerdict, EvidencePack, AgentError, approval payload, escalation, A2A DataPart envelope -- the models the tests ask for.
- [ ] `tests/contracts/test_verdict.py`, `test_evidence.py`, `test_error_and_approval.py` -- RED→GREEN for AC1 nullable rules, AC3 AgentError/escalation/class_override, run_id/task_id/contextId convention fields, short-SHA rejection -- behaviors at the package's public boundary.
- [ ] `scripts/check_layer_contract.py` -- allow pydantic + self-import for contracts/guardrails -- 0.1 wording conflicts with AD-6; report in story notes.
- [ ] `scripts/generate_schemas.py` + committed schemas + `make schema-drift` in `check` -- AC3 drift gate, `Makefile` -- CI-equivalent enforcement without a CI runner yet (no .github/ by 0.1).
- [ ] `make check` full pass, coverage ≥85% on contracts -- end-of-story proof in evidence table.

**Acceptance Criteria:**
- Given the spine contract definitions (AD-6), when a representative TriageVerdict payload validates, then every named field with spine nullability exists and `class`/`risk_tier`/`terminal_state` accept exactly the spine value sets (AC1).
- Given invalid enum values or malformed structures in agent and approval payloads, when validated, then `ValidationError` names the field and closes: citations five kinds, severities four, diff ops three, SHAs full 40-char in production models (AC2).
- Given EvidencePack, AgentError and A2A DataPart contracts, when schemas regenerate, then committed `guardrails/schemas/` output is byte-identical and any drift fails the check; escalation six values and approval `class_override` are present in contracts (AC3).

## Implementation Notes

- Confirmed constraint turns: story 0.1's checker says "contracts imports nothing but stdlib"; spine AD-6 mandates pydantic. Spine wins; amendment is deliberate and recorded here.
- Terminal state null-while-running: `terminal_state: TerminalState | None = None` where presence of any of the terminal values maps AD-1/AD-4 table `COMPLETED|FAILED` outcomes.

## Spec Change Log

(empty)

## Review Triage Log

(empty)

## Verification

**Commands:**
- `make check` -- expected: all gates green, exit 0, including new schema-drift target.
- `.venv/bin/pytest tests/contracts -q` -- expected: all named AC tests pass.
