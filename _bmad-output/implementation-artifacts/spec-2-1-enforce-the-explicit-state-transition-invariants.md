---
title: 'Story 2.1 — Enforce the explicit state transition invariants'
type: 'feature'
created: '2026-09-25'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: a0e00185c7dbae0d8d4b4e033d741eb29046d381
context: ['{project-root}/AGENTS.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The orchestrator's run lifecycle (AD-1) lives only in prose and a Mermaid diagram; nothing stops an illegal state move, and `triage_run` has no table to own run state. Workers (1.2), steps (2.3) and approvals (2.4) all depend on a single declarative transition table and its guard rules existing first.

**Approach:** Build the domain state machine: a `RunState` enum (14 AD-1 states) in `workflow/`, one declarative transition table whose rows are `(from, to, guard)`, pure guard predicates over a frozen guard-input model, a pure AD-4 projection to a2a-sdk `TaskState`, the first domain migration `0001_triage_run.sql`, and a generated Mermaid diagram with a drift gate that checks the table against the spine's AD-1 block. TDD throughout; no external services connected (AC3).

### Brief (CHECKPOINT 1 summary)

**(1) Story + key:** 2.1 — Enforce the explicit state transition invariants; sprint-status key `2-1-enforce-the-explicit-state-transition-invariants`.

**(2) ACs in one line:**
- **AC1:** all AD-1 edges plus `FAILED` from every non-terminal state are legal via the table; undeclared moves raise typed `IllegalTransition` (non-retryable, names from/to/failed guard, AD-22); the state diagram is generated from the table, byte-identical to a committed file; a test parses the spine's AD-1 mermaid block and asserts edge-set equality.
- **AC2:** `project(run_state)` maps all 14 states per the AD-4 table (a2a-sdk 1.1.5 protobuf `TaskState` member names verified locally: `TASK_STATE_SUBMITTED`, `TASK_STATE_WORKING`, `TASK_STATE_INPUT_REQUIRED`, `TASK_STATE_COMPLETED`, `TASK_STATE_FAILED`); parametrized projection test; `AWAITING_APPROVAL` is non-terminal in DB and requires an `EscalationReason`; each of the 6 reasons is accepted; `proposal_step_id` optional.
- **AC3:** guarded edges reject a move when required guard data is missing; branch-table fixtures cover class (infra→REPORTING), gate (normal→PR_OPENING / blocked→AWAITING_APPROVAL), revision (round<2→PROPOSING else AWAITING_APPROVAL), approval (workflow-file→REPORTING vs non-workflow with proposal→PR_OPENING; class override without proposal→ANALYZING; reject→REPORTING). Fixture inputs only.

**(3) Binding ADs and how they constrain:**
- **AD-1:** one transition table in `workflow/`; undeclared transition raises; diagram generated from the table; `AWAITING_APPROVAL` carries reason + optional `proposal_step_id`.
- **AD-4:** projection is a pure mapping to A2A `TaskState` + contract `TerminalState`; `input_required` terminal-state contract for AWAITING_APPROVAL.
- **AD-6:** reuse `contracts.enums` (`TerminalState`, `EscalationReason`, `RiskTier`, `FailureClass`); no redefinition.
- **AD-9:** guards only *consumes* a `confidence_below_cutoff` boolean; confidence computation is 2.2.
- **AD-14/AD-16:** approve + workflow file → REPORTING (never PR_OPENING); approve with class override → ANALYZING only with no proposal; reject → REPORTING (then REJECTED_BY_HUMAN only after reject).
- **AD-22:** `IllegalTransition` is non-retryable; FAILED reachable from every non-terminal state, derived from the terminal set, not hand-listed 11 times.
- **AD-17:** `triage_run` has UNIQUE `(repo_id, workflow_run_id, run_attempt)`.
- **AD-25:** migration is forward-only SQL applied by the existing one-shot runner.

**(4) Files to create/change; NOT touched:**
- Create: `workflow/run_states.py` (`RunState`), `workflow/transitions.py` (table + `transition()` + guards), `workflow/diagram.py`-backed `scripts/generate_state_diagram.py`, generated `workflow/STATE_DIAGRAM.md`, `deploy/migrations/0001_triage_run.sql`, `guardrails/thresholds.yaml` (review max rounds = 2, workflow-path glob), tests under `tests/workflow/`.
- Change: `Makefile` (add `state-diagram-drift` to `check`), `deploy/migrations/README.md` (typo "monotonic interrupt" → "integer"; update "No domain tables here" line: `triage_run` arrives with 2.1), `docs/DEVELOPER.md`.
- NOT touched: workers, leases (1.2), `run_step`/2.3, A2A server/TaskStore adapter (2.4), GitHub or LLM calls, `contracts/` except no change (reuse only).

**(5) Approach (SOLID/DRY decisions, 5 bullets):**
- **S:** domain machine (states/table/guards) in `workflow/`; pure, no SQL/HTTP.
- **O:** one declarative tuple table; new edge = new row + guard, no if/elif chain over states. `FAILED` edges derived from the terminal set.
- **D/I:** guards consume a single frozen `GuardInput` model (≤5 params, dataclass/pydantic frozen); `project()` is a mapping-table function, no a2a import beyond the enum.
- **Reuse:** `TerminalState`, `EscalationReason`, `FailureClass`, `RiskTier` from `contracts/enums`; migration runner `workflow/migrate.py` untouched.
- **RunState stays in `workflow/`** (argued): it is orchestrator-internal per the story; `contracts/` holds inter-agent payload types (AD-6), and a state the agents never transmit does not belong there. Terminal/escalation values it needs are already in contracts and reused.

**(6) TDD plan (red→green, names cite ACs):** first test per AC: `test_ac1_every_spine_edge_is_legal`, `test_ac1_undeclared_transition_raises_illegal_and_names_guard`, `test_ac1_failed_reachable_from_every_non_terminal`, `test_ac1_diagram_byte_identical`, `test_ac1_table_edges_equal_spine_mermaid_block`; `test_ac2_parametrized_projection_table`, `test_ac2_awaiting_approval_requires_reason`, `test_ac2_all_six_reasons_accepted`; `test_ac3_guarded_edges_reject_missing_guard_data`, `test_ac3_branch_table_class_gate_revision_approval`; integration `@pytest.mark.integration`: `test_0001_migration_applies_and_check_constraints_reject_bad_state_and_missing_reason`, `test_enum_check_constraint_parity` (DB CHECK value lists == Python enums).

**(7) Risks / open questions / prerequisites:** a2a-sdk 1.1.5 `TaskState` is a protobuf enum wrapper, not a python `Enum` — projection returns the wrapper's name value and the test asserts on member names. Prerequisite: 0.2/0.3 merged (done). No OQ remaining.

**(8) Doc impact:** `docs/DEVELOPER.md` — add 2.1 to "Built so far"; state machine files, `guardrails/thresholds.yaml`, diagram script into "Where things live"; new "Extending the state machine (2.1)" section (add state/edge = row+guard+test, regenerate diagram; links AD-1/AD-4). Per human approval instruction: explain the state-machine rules and routes in very simple plain terms there, not just as terse references. `docs/USER-GUIDE.md` — no doc change: no user-visible behaviour; this story is internal domain logic + migration only.

</frozen-after-approval>

## Code Map

- `contracts/enums.py` — reuse `TerminalState`, `EscalationReason`, `FailureClass`, `RiskTier`; `FAILURE_CLASSES`, `RISK_TIERS`, `ESCALATION_REASONS` tuples exist for parity checks. Do not edit.
- `contracts/approval.py` — `ApprovalPayload.decision/class_override` shapes the guard-input approval fields; reuse semantics.
- `contracts/errors.py` — error with `retryable: bool` flag; `IllegalTransition` (in `workflow/transitions.py`) follows the same shape with `retryable=False` (AD-22).
- `workflow/migrate.py` — forward-only runner; `read_migrations()` picks up `0001_*.sql` automatically. Do not modify.
- `deploy/migrations/README.md` — fix typo "monotonic increasing interrupt" → "increasing integer"; update the "No domain tables here" bullet (`triage_run` arrives with 2.1).
- `Makefile` — `check:` target chain; add `state-diagram-drift` modelled on `schema-drift`; `pytest-cov` runs `pytest --cov` over contracts/guardrails/workflow tests.
- `scripts/generate_schemas.py` — reference for the `--check` drift-gate pattern (`generate_state_diagram.py` mirrors its CLI shape).
- `a2a-sdk 1.1.5` — `TaskState` at `a2a.types` is a protobuf `EnumTypeWrapper` (values: 0=UNSPECIFIED, 1=SUBMITTED, 2=WORKING, 3=COMPLETED, 4=FAILED, 5=CANCELED, 6=INPUT_REQUIRED, 7=REJECTED, 8=AUTH_REQUIRED). Projection asserts conceptually; the A2A server story (2.4) converts to the integer.

## Tasks & Acceptance

**Execution:**
- [x] `tests/workflow/test_transitions.py` -- write failing AC tests first (red) -- TDD per AGENTS.md
- [x] `workflow/run_states.py` -- `RunState` enum, 14 AD-1 states (AC1)
- [x] `workflow/transitions.py` -- transition table, `GuardInput` frozen model, pure guards, `transition()` raising `IllegalTransition` (AC1+AC3)
- [x] `guardrails/thresholds.yaml` -- `review.max_rounds: 2`, `workflow_path_glob: .github/workflows/**`; table/guards read loader (no literals) (AC3)
- [x] `scripts/generate_state_diagram.py` + `workflow/STATE_DIAGRAM.md` -- Mermaid render from table + `make state-diagram-drift` in `Makefile` (AC1)
- [x] `tests/workflow/test_spine_contract.py` -- parse spine AD-1 mermaid block, assert edge-set equality incl. derived FAILED edges (AC1)
- [x] `workflow/projection.py` -- pure `project(run_state) -> (TaskState, TerminalState | None)` from the AD-4 mapping (AC2)
- [x] `deploy/migrations/0001_triage_run.sql` -- columns per AD-17 identity, state CHECK, escalation CHECK + iff-AWAITING_APPROVAL pair, `proposal_step_id uuid NULL` (no FK) (AC1+AC2+AD-25)
- [x] `tests/workflow/test_triage_run_migration.py` -- `@pytest.mark.integration`: apply via `PsycopgMigrationConnection`, CHECK constraints reject bad state / missing reason; enum/CHECK parity test (AC1+AC2)
- [x] `deploy/migrations/README.md` -- typo + "domain tables" line fixes
- [x] `docs/DEVELOPER.md` -- Built so far / Where things live / Extending section
- [x] `make check` full pass

**Acceptance Criteria:**
- Given the table, when a sampled undeclared move is requested, then `IllegalTransition` names from/to and failed guard (AC1).
- Given the committed `STATE_DIAGRAM.md`, when the generator re-runs, then output is byte-identical; `make check` green including the drift gate (AC1).
- Given all 14 states, when projected, then the AD-4 mapping holds; AWAITING_APPROVAL without reason is rejected (AC2).
- Given branch-table fixtures with no external services, when each guarded edge is exercised, then expected next state (AC3).

## Verification

**Commands:**
- `.venv/bin/pytest tests/workflow -q` -- expected: all unit tests green, red-first history noted
- `.venv/bin/pytest -m integration tests/workflow --ds tests/workflow/conftest.py -q` (Docker) -- expected: migration + CHECK + parity green
- `make check` -- expected: PASS including new `state-diagram-drift`
- `.venv/bin/python scripts/generate_state_diagram.py --check` -- expected: exit 0

## Spec Change Log

## Review Triage Log

## Implementation Notes

## Implementation Notes (append)

- Baseline a0e00185; TDD red-first per AC (evidence in step-03 report): AC1 spine-edge equality test initially over-counted derived FAILED edges — test corrected to compare spine block == declared edges, with separate derived-FAILED + prose assertions.
- `transition()` returns the winning `Transition` row; `guard_fields()` gives each guard a first-class sample dict (tests + introspection).
- Deliberate fix in `tests/security/test_compose_secret_placement.py`: story 0.3's "no domain tables" guard narrowed — `0001_triage_run.sql` is the only migration allowed to name `triage_run`; the other domain tables stay forbidden.
- Removed a duplicated module-load `_build_table()` call found in step-03 diff review; gates re-run green.
- `requirements/constraints.txt`: PyYAML pin + types-PyYAML added (yaml already transitively installed); `types-PyYAML` also in dev-constraints.
- a2a-sdk 1.1.5 protobuf TaskState: projection returns member names as plain strings; verified via `TaskState.Value(name)` in tests.
- `make check` PASS: bootstrap, layer contract, schema drift, state-diagram drift, ruff, ruff format, mypy --strict, pylint dup, 128 tests, cov 91.23% (≥85). Integration: `pytest -m integration tests/workflow` → 6 passed (Docker postgres:18).

## Review Triage Log

| # | Layer | Verdict | Finding + evidence |
|---|---|---|---|
| 1 | blind | medium | Missing spec-named test `test_ac2_awaiting_approval_requires_reason` — TDD plan (spec §6) names it; no state-machine-level test proves wrong/missing reason data refuses entry to AWAITING_APPROVAL. Verified: grep over tests/workflow/test_transitions.py shows no such test. → patch (also blind#2, clean-code TDD drift row). |
| 2 | verification-gap | medium | `triage_run.proposal_step_id` ships with zero DB-side evidence: no integration insert/select with or without the column. AC2 clause "proposal_step_id optional" unverified at the DB boundary for 2.3/2.4. → patch (also clean-code named-test gap). |
| 3 | blind | medium | GATING→AWAITING_APPROVAL guard (`gate_blocks`) fires on `risk_tier=blocked` alone and never requires the matching `escalation_reason` — guard passes while the DB `ck_triage_run_escalation_iff_state` rejects the eventual row; AD-1 reasons live in the domain, not only in DDL. → patch (with #1: guards on pause entries pair the cause with the reason; fixtures/tests updated). |
| 4 | blind + clean-code | low | `GUARD_FIELDS["revision_round_below_max"]` hardcodes `max_revision_rounds: 2`, duplicating thresholds.yaml and contradicting the module docstring ("no threshold literal"). → patch. |
| 5 | blind + clean-code | low | `transition()` refuses name only `candidates[0].guard_name` (e.g. a rejected reject attempt blamed on `approve_of_workflow_diff`). Cosmetically misleading; fix trivial. → patch. |
| 6 | clean-code | low | `workflow/transitions.py` (SOLID-S) mixes pure table/guards with config-file I/O (`yaml.safe_load` + THRESHOLDS_PATH). Single consumer today but risk-gate story 2.10 will read thresholds too. → patch (extract loader to `workflow/thresholds.py`; docs updated). |
| 7 | clean-code | low | conftest.py duplicates `pg_dsn`/`wait_ready`/`docker_run` from `tests/workflow/test_migrations_integration.py`; module-level fixture shadows conftest. → patch (dedupe, single conftest fixture). |
| 8 | clean-code | low | Dead/dishonest small code: unused `terminal_states()` wrapper (docstring misstates FAILED as derived), unused `projection_table` alias, `_ENTRY_STATE` magic string duplicating `RunState.RECEIVED`, inert `# pyright: ignore` in a mypy project, `AD-2` comment misciting AD-1, `f"[*]"` no-placeholder f-string, `test_ac3_no_domain_tables_in_migrations` name now misleading, `--check` drift message hardcodes the filename while `--diagram-path` exists. All direct deletions/one-line fixes. → patch (single group). |
| 9 | blind + clean-code | low | `types-PyYAML` pinned in runtime `requirements/constraints.txt` and `dev-constraints.txt`; stubs do not belong in the runtime resolver set. → patch. |
| 10 | clean-code | low | `workflow/README.md` stale: still says "Filled by: Epic 2 stories" although 2.1 delivered the state machine. → patch (one-line status + link). |
| 11 | blind | false | Error shape divergence `IllegalTransition` vs contracts `{code,message,retryable}` — no consumer until story 2.8; retryable flag present; message string suffices. Everyday harm unlikely; aligning shapes is later-story work. Rejected. |
| 12 | blind | false | `workflow_path_glob` unused here — intended: consumed by the risk-gate story (2.10); the file is the single key source being laid down for later stories. Rejected. |
| 13 | blind | false | UUIDv7 unchecked — frozen scope defines the column as plain uuid; generation strategy belongs to the story that creates runs (2.3/2.4). Rejected. |
| 14 | blind | false | `updated_at` never updated — this story's migration is intentionally minimal; writers arrive with 2.3. Rejected. |
| 15 | blind | false | Missing leased-scan index on `triage_run` — frozen scope leaves lease concerns to 1.2's own migration. Ruled excluded by intent. Rejected. |
| 16 | blind | dup | `test_ac3_guarded_edges` `continue` skips — same claim as #17, routed there. |
| 17 | clean-code | low | `test_ac3_guarded_edges_reject_missing_guard_data` silently `continue`s listed edges that pass on empty data, so the AC3 property is asserted only for a subset. Small fix: assert the hardcoded tuple equals the guarded rows derived from the table. → patch (with #1 group). |
| 18 | blind + clean-code | low | `tests/` not covered by ruff in `make check` — pre-existing 0.1 Makefile convention, all earlier test files share it; not caused by this story. → defer. |
| 19 | clean-code | false | DEVELOPER.md projection paragraph "restates AD-4 table" — restatement in plain terms is the human-approved doc instruction for this story; the paragraph exists precisely for that. Rejected. |
| 20 | blind | false | Frozen-intent numbering nit ("approvals (2.4)") — fix would edit the frozen block; rejected per triage rules. |
| 21 | blind | false | Malformed thresholds.yaml surfaces as bare KeyError — file is committed and static; loaders' failure mode is louder, not silent. Everyday risk negligible; fix adds complexity. Rejected as low. |
| 22 | blind | low | Diagram parity test asserts state-name substrings per table row — but byte-identity gate + spine edge-set test jointly cover structural drift; harm nil. Rejected (cosmetic). |
