---
title: 'Story 2.3 — Persist completed steps atomically and resume'
type: 'feature'
created: '2026-09-26'
status: 'ready-for-dev'
route: 'dispatch'
review_loop_iteration: 0
followup_review_recommended: false
context: ['{project-root}/AGENTS.md']
warnings: ['oversized']
deferred: []
---

## Build Brief

**(1) Story + key:** 2.3 — Persist completed steps atomically and resume; sprint-status key `2-3-persist-completed-steps-atomically-and-resume`.

**(2) ACs in one line:**
- **AC1:** a leased run's completed step writes its `run_step` output and the `triage_run.state` change atomically in one lease-guarded transaction; fault injection between the two writes leaves neither a partial completion nor an advanced state.
- **AC2:** after a crash-and-reclaim, the worker re-enters the current state and does not execute a completed step again; the `run_step` migration adds only the fields needed now and every run query binds `repo_id`.
- **AC3:** a stale owner's guarded step-commit is rejected so neither output nor state persists, and the discarded result never appears as an accepted `run_step`.

**(3) Binding ADs:** **AD-2** (step row + state transition commit in one transaction; reclaimed run re-enters its current state; completed steps never re-executed). **AD-23** (the transaction re-checks `lease_owner` under `FOR UPDATE`; mismatch discards). **AD-1** (state moves only through the one transition table; reuse `RunState`). **AD-4** (`run_step` hangs off `run_id`; `run_id` is UUIDv7). **AD-15** (tenant scope: every `run_step` query binds `repo_id`; no cross-repo rows). **AD-25** (forward-only migration applied by the one-shot job). **AD-22** (a lost lease is definitive; a failed attempt is its own step, not a silent skip). **AD-18** (model/token/cost columns are *not* added here — 6.1/6.2 own them).

**(4) Files:**
- Create: `workflow/steps.py` (`StepStatus`, `StepRecord`, `StepRecorder` protocol, `ResumeView`, `PostgresStepRecorder`); `deploy/migrations/0004_run_step.sql`; `tests/workflow/test_steps.py`; integration tests `tests/workflow/test_step_integration.py`.
- Change: `workflow/README.md`, `deploy/migrations/README.md` (0004 note), `docs/DEVELOPER.md`; `tests/security/test_compose_secret_placement.py` (allowlist the new `run_step` table and the `0004` reference to `triage_run`).
- **NOT touched:** 1.2's `workflow/leases.py`, `RunLeaseStore`, `config/orchestrator.yaml` (reuse `guarded_commit`; do not re-implement fencing); 2.1's `workflow/transitions.py`/`run_states.py` (reuse `transition()`; do not edit); 2.4 projection, 2.5 distiller, 2.6 history, 2.7 evidence pack, 2.8 step runner/retries, monitoring/cost, gateway intake, agents, prompts, `contracts/` (no new payload type).

**(5) Approach (SOLID/DRY):**
- **S:** `workflow/steps.py` is step persistence + resume-read only; no retry loop, no audit pricing, no HTTP.
- **I:** one small `StepRecorder` protocol for its consumer; the `run_step` SQL adapter is the only I/O; unit tests use a fake recorder.
- **D:** `PostgresStepRecorder` composes 1.2's `RunLeaseStore.guarded_commit` — the lease re-check and transaction boundary stay in one place, and 2.3 supplies the work (insert step + advance state). No second fencing implementation.
- **Reuse:** current/next state validated by 2.1's `transition(current, next, guards)` inside the guarded transaction; `RunState` reused, never re-listed.
- **DRY:** completed-step lookup is one query (`status = completed`, repo-scoped) feeding both resume and the "don't re-execute" rule; the unique `(run_id, step, attempt)` identity is the DB-level backstop.

**(6) TDD plan (red-first; names cite ACs):** AC1 `test_ac1_commit_records_step_and_advances_state`, `test_ac1_fault_between_step_write_and_state_write_rolls_back_both` (integration), `test_ac1_illegal_transition_writes_nothing`; AC2 `test_ac2_resume_skips_completed_step` (integration), `test_ac2_queries_are_repo_scoped` (integration), `test_ac2_migration_adds_only_needed_fields` (integration: exact column set, no model/token/cost columns); AC3 `test_ac3_stale_owner_commit_discarded` (integration), `test_ac3_discarded_result_absent_from_run_step_and_completed`, `test_ac3_guard_reports_owner_mismatch` (fake); migration `test_0004_migration_applies_and_unique_identity_blocks_duplicate_step` (integration).

**(7) Risks / OQ:** assumes story 1.1 (`0002`), 1.2 (`0003` + `RunLeaseStore.guarded_commit` + `config/orchestrator.yaml`) and 2.1 (`transition`) have landed; this story ships `0004`. Integration tests need Docker. The fault-injection proof runs at the `guarded_commit` primitive (two DB writes with the second forced to fail) so no test hook enters production code. "Only needed fields" is deliberate: cost/token columns wait for 6.1/6.2, evidence-pack fields for 2.7. No OQ remaining.

**(8) Doc impact:** `docs/DEVELOPER.md` — new "Steps and resume (story 2.3)" section in plain words (what a `run_step` is, why its write and the state change must be one transaction, how a reclaimed run skips finished steps and why a stale owner's result is thrown away), 2.3 in "Built so far", rows for `workflow/steps.py` and `0004` in "Where things live", and the extend note (a new persisted field is a forward migration; resume reads completed steps, never a step list). `docs/USER-GUIDE.md` — no doc change: internal durability, no user-visible flow.

<intent-contract>

## Intent

**Problem:** State can move and steps can run, but nothing persists a step's output together with the state change. A crash after a step would either lose the output or re-run it on resume, causing duplicate LLM spend and inconsistent state; a stale owner could still write after losing its lease.

**Approach:** Add a minimal `run_step` table (migration `0004`) and `workflow/steps.py`: a repo-scoped `StepRecorder` that, inside 1.2's lease-guarded transaction, validates the move with 2.1's `transition()`, inserts the step row and updates `triage_run.state` together; a `resume()` view returning the current state plus completed step names so a reclaiming worker skips finished work. A stale owner's guarded commit writes nothing.

## Boundaries & Constraints

**Always:** do the step insert and the state update in the same lease-guarded transaction; re-check `lease_owner` before either write; validate the move with `transition()` (never a raw state assignment); bind `repo_id` on every `run_step` query; expose completed steps so a reclaimed run skips them; add only the fields this story needs; keep the migration forward-only.

**Never:** re-implement lease/fencing logic from 1.2; hold a lock across a model call; add model/token/cost or evidence-pack columns (6.1/6.2/2.7); write history (2.6); add a retry loop (2.8); re-execute a completed step; let a non-owner commit.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| COMMIT_OK | owner holds lease; legal move; step output | step row + state update commit together | none |
| COMMIT_STALE | `lease_owner` no longer matches | nothing written; `False`/`LeaseLost` | definitive, no retry |
| COMMIT_ILLEGAL | move absent from the transition table | nothing written | `IllegalTransition` (non-retryable) |
| FAULT_BETWEEN_WRITES | step write succeeds, state write fails | both rolled back | transaction rollback |
| RESUME_AFTER_CRASH | committed step, run reclaimed | current state + completed steps; step not re-run | none |
| RESUME_DUPLICATE_STEP | commit a completed `(run_id, step, attempt)` again | unique identity rejects it | DB constraint |
| CROSS_TENANT_READ | query with a different `repo_id` | no rows | none |
| DUPLICATE_ATTEMPT | same `(run_id, step, attempt)` | unique constraint rejects | DB constraint |

</intent-contract>

## Code Map

- `workflow/leases.py` (1.2) — reuse `RunLeaseStore`/`guarded_commit`, `LeaseLost`; do not edit or duplicate its fencing.
- `workflow/transitions.py:402` — `transition(from_state, to_state, guards)` for the move; `GuardInput` for guard data. Do not edit.
- `workflow/run_states.py` — `RunState` and `TERMINAL_RUN_STATES`; reuse.
- `deploy/migrations/0001_triage_run.sql` — `triage_run.run_id` is the FK target; `0004` adds `run_step` only. Do not edit.
- `deploy/migrations/0002_webhook_delivery.sql` / `0003_triage_run_lease.sql` — planned by 1.1/1.2; `0004` orders after them.
- `tests/security/test_compose_secret_placement.py:131-153` — `test_ac3_no_speculative_domain_tables_triage_run_allowlisted`; it forbids `run_step` in any migration and allows only listed files to name `triage_run`. Story 1.2 adds `0003` to the `triage_run` allowlist; this story adds `run_step` to the allowed table names and `0004_run_step.sql` to the `triage_run` allowlist (its FK names it).
- `tests/workflow/conftest.py` — `pg_dsn` disposable `postgres:18`; reuse for integration tests.
- `tests/workflow/test_triage_run_migration.py` — the `PsycopgMigrationConnection` apply/CHECK pattern to mirror.

## Tasks & Acceptance

**Execution:**
- `tests/workflow/test_steps.py`, `tests/workflow/test_step_integration.py` -- write failing AC tests first (red) -- TDD per AGENTS.md
- `deploy/migrations/0004_run_step.sql` -- `run_step` with `step_id`, `run_id` FK, `repo_id`, `step`, `attempt`, `status`, `output`, `created_at`; unique `(run_id, step, attempt)`; repo/run index -- AC1/AC2/AD-15/AD-25
- `workflow/steps.py` -- `StepStatus`, `StepRecord`, `ResumeView`, `StepRecorder` protocol, `PostgresStepRecorder` composing `guarded_commit` + `transition()` -- AC1/AC2/AC3
- `tests/security/test_compose_secret_placement.py` -- allowlist `run_step` and `0004` in the schema guard -- AC2
- `tests/workflow/test_step_integration.py` -- atomic commit, fault injection, resume skip, stale-owner discard, cross-tenant read -- AC1/AC2/AC3
- `workflow/README.md`, `deploy/migrations/README.md`, `docs/DEVELOPER.md` -- docs (brief part 8)

**Acceptance Criteria:**
- Given a leased run and a legal step, when it commits, then the `run_step` row and the state change are both present (AC1).
- Given a fault after the step write and before the state write, when the transaction fails, then neither the step row nor the state change exists (AC1).
- Given a committed step, when the run is reclaimed, then the current state and completed steps are returned and the step is not re-executed (AC2).
- Given any `run_step` read, when another `repo_id` is used, then no rows are returned (AC2).
- Given a stale owner, when it attempts its guarded commit, then no step row and no state change persist (AC3).

## Verification

**Commands:**
- `.venv/bin/pytest tests/workflow/test_steps.py -q` -- expected: unit tests green, red-first history noted
- `.venv/bin/pytest -m integration tests/workflow/test_step_integration.py -q` (Docker) -- expected: atomicity/fencing/resume green on `postgres:18`
- `make check` -- expected: PASS
- `psql ... -c "\d run_step"` (via `docker compose ... exec postgres`) -- expected: no model/token/cost columns

**Manual checks:**
- Confirm `workflow/steps.py` contains no `SKIP LOCKED`/`FOR UPDATE` lease SQL of its own (it must go through 1.2's guard).

## Auto Run Result

Status: ready-for-dev
Blocking condition: none
Planned: 2026-09-26. Halted after planning. Reused cached `epic-2-context.md` (valid); continuity context from done specs 2.1 and 2.2. No production code written. Assumes 1.1 (`0002`), 1.2 (`0003` + `RunLeaseStore.guarded_commit`) and 2.1 (`transition()`) have landed; this story ships `0004`.
