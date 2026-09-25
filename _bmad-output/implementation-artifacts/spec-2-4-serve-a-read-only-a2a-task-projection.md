---
title: 'Story 2.4 — Serve a read-only A2A task projection'
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

**(1) Story + key:** 2.4 — Serve a read-only A2A task projection; sprint-status key `2-4-serve-a-read-only-a2a-task-projection`.

**(2) ACs in one line:**
- **AC1:** with stored run/step fixtures, A2A `get_task` reads through the TaskStore adapter; `task_id` equals the run_id UUIDv7 and status/artifacts derive from `triage_run`/`run_step`; there is no independent task-state writer and no `DatabaseTaskStore` deployment.
- **AC2:** an `AWAITING_APPROVAL` run fetched as a task returns `INPUT_REQUIRED` with a blame-free evidence-pack artifact without scheduling a worker; the same task identity persists; unknown tasks and cross-repo reads expose nothing.
- **AC3:** every AD-4 state fixture renders `status` and `terminal_state` exactly as 2.1's mapping says, and no author attribution appears for `AWAITING_APPROVAL` or `REPORTING`.

**(3) Binding ADs:** **AD-4** (task state is a one-way projection of `triage_run.state`; read-only TaskStore adapter; `task_id` = `run_id`; no `DatabaseTaskStore`/a2a-db). **AD-1** (the projection consumes `RunState`, never writes it). **AD-5/AD-6** (A2A over the JSON-RPC binding; artifacts carry `contracts` payloads). **AD-15** (every read is bound to `repo_id`; cross-repo reads expose nothing). **AD-27** (blame-free: no author attribution in `AWAITING_APPROVAL`/`REPORTING`; the below-cutoff case is 4.1 AC3).

**(4) Files:**
- Create: `workflow/task_store.py` (`TaskReader` protocol, `ReadOnlyTaskStore`, `build_task`); `workflow/a2a_server.py` (Starlette app + `RefusingExecutor` + JSON-RPC `get_task`/`list_tasks` route via the SDK); `tests/workflow/test_task_store.py`; `tests/workflow/test_task_server.py`.
- Change: `workflow/README.md`, `docs/DEVELOPER.md`; `tests/security/test_compose_secret_placement.py` only if a no-`DatabaseTaskStore` assertion needs extending (keep the existing a2a-db checks).
- **NOT touched:** `triage_run`/`run_step` writes (2.3), lease/claim (1.2), `workflow/projection.py`'s mapping table (2.1 — reuse `project()`), `workflow/attribution.py` (2.2 — reuse), the evidence-pack builder (2.7 owns producing it; this story only serves what a stored fixture step holds), history (2.6), risk gate, gateway, agents, prompts, `contracts/` (reuse `EvidencePack`; no new payload).

**(5) Approach (SOLID/DRY):**
- **S:** `task_store.py` is one-way read + pure projection; `a2a_server.py` is transport wiring only; neither writes state.
- **D/I:** `ReadOnlyTaskStore` implements the SDK `TaskStore` ABC over a small `TaskReader` protocol; unit tests fake the reader, an ASGI test drives the real store.
- **O:** every `RunState` maps through 2.1's `project()` and `workflow.run_states.TERMINAL_RUN_STATES`; no state list is re-declared here.
- **L/DRY:** writes are refused (`save`/`delete` raise `ReadOnlyTaskStoreError`) so no second task-state owner can exist; the task builder is one function used by `get` and `list`.
- **Reuse:** `DefaultRequestHandler` with a `RefusingExecutor` answers only `get_task`/`list_tasks`; wire it with the SDK's `create_jsonrpc_routes`.

**(6) TDD plan (red-first; names cite ACs):** AC1 `test_ac1_task_id_equals_run_id_uuid7`, `test_ac1_status_and_artifacts_come_from_run_and_steps`, `test_ac1_save_and_delete_are_refused`, `test_ac1_no_database_task_store_deployed`; AC2 `test_ac2_awaiting_approval_is_input_required_with_blame_free_evidence_artifact`, `test_ac2_get_task_writes_nothing_and_schedules_nothing`, `test_ac2_unknown_task_returns_none`, `test_ac2_cross_repo_read_returns_none`, `test_ac2_task_identity_stable_across_calls`; AC3 `test_ac3_all_ad4_state_fixtures_project_status_and_terminal_state`, `test_ac3_no_author_attribution_for_awaiting_approval_or_reporting`; server `test_get_task_over_jsonrpc_returns_projected_task` (httpx ASGI transport).

**(7) Risks / OQ:** assumes 2.1 (`project`), 2.2 (`attribution_allowed`), 2.3 (`run_step` + `RunStepReader`) have landed. The real evidence pack is produced by 2.7; this story serves a fixture step output shaped as `contracts.evidence.EvidencePack`. Repo scope is the adapter's configured `repo_id` (single-tenant demo deployment); authenticated multi-tenant resolution is 5.1 — noted in DEVELOPER. The orchestrator's compose service still points at the 1.2 image; wiring the serving image is later (2.8/2.12) — this story proves the app in-process over ASGI. No OQ remaining.

**(8) Doc impact:** `docs/DEVELOPER.md` — new "The A2A task view (story 2.4)" section in plain words (the task is a read-only mirror of the run; why the SDK's own database store is not deployed; why a paused run shows a blame-free evidence pack), 2.4 in "Built so far", rows for `workflow/task_store.py`/`a2a_server.py`, and the extend note (a new artifact is a new step output; never a new writer). `docs/USER-GUIDE.md` — no doc change: the CLI/user surface arrives with punch-out stories.

<intent-contract>

## Intent

**Problem:** The run's authoritative state lives in `triage_run`/`run_step`, but there is no A2A task a client can fetch, and deploying the SDK's `DatabaseTaskStore` would create a second, diverging task-state owner. A paused run also needs to expose evidence without starting work or blaming an author.

**Approach:** Build a read-only `TaskStore` adapter that projects a stored run plus its steps into the A2A protobuf `Task` (task id = run id, status via 2.1's `project()`, terminal state in metadata, artifacts from step outputs, author stripped when 2.2's attribution predicate says blame-free). Serve `get_task`/`list_tasks` by wiring the SDK's `DefaultRequestHandler` (with a refusing executor and the read-only store) into `create_jsonrpc_routes`.

## Boundaries & Constraints

**Always:** derive task identity from `run_id`; derive state/terminal state from 2.1's mapping; derive artifacts from stored `run_step` rows; bind every read to `repo_id`; refuse `save`/`delete`; serve only `get_task`/`list_tasks` (other A2A methods refuse); strip author attribution where `attribution_allowed` is false.

**Never:** write `triage_run`/`run_step` from this path; deploy `DatabaseTaskStore`/a2a-db; re-list AD-1 states; build or mutate the evidence pack; schedule a worker from `get_task`; expose another repo's run; add an auth/decision handler (5.1/5.4).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| GET_WORKING | stored run in a mid state | `Task` with mapped `TASK_STATE_WORKING`, matching artifacts | none |
| GET_PAUSED | `AWAITING_APPROVAL` + evidence step | `TASK_STATE_INPUT_REQUIRED`, `terminal_state=input_required`, blame-free artifact | none |
| GET_TERMINAL | `DONE_PR`/`DONE_REPORT`/`REJECTED_BY_HUMAN`/`FAILED` | mapped completed/failed + terminal_state | none |
| GET_UNKNOWN | run id not stored | `None` | not found |
| GET_CROSS_REPO | run exists under another `repo_id` | `None` | nothing exposed |
| SAVE_CALLED | any `Task` | refused | `ReadOnlyTaskStoreError` |
| DELETE_CALLED | any id | refused | `ReadOnlyTaskStoreError` |

</intent-contract>

## Code Map

- `workflow/projection.py:46` — `project(state) -> (TaskStateName, TerminalState | None)`; reuse for status + terminal_state. Do not edit.
- `workflow/attribution.py:16` — `attribution_allowed(state, confidence, cutoffs)`; state-based False for `AWAITING_APPROVAL`/`REPORTING`. Reuse; for this story's fixtures pass the fixture confidence.
- `workflow/run_states.py` — `RunState`, `TERMINAL_RUN_STATES`; reuse.
- `workflow/steps.py` + `deploy/migrations/0004_run_step.sql` (2.3) — the `run_step` read shape this story serves; add a `TaskReader` protocol over it, do not modify 2.3's writer.
- `contracts/evidence.py` — `EvidencePack`, reused as the paused artifact payload. Do not edit.
- `contracts/a2a.py` — `DataPart` identity convention (`task_id == context_id == run_id`).
- a2a-sdk 1.1.5 (installed): `a2a.server.tasks.task_store.TaskStore` is an async ABC (`save`/`get`/`list`/`delete`); `Task` is protobuf `a2a.types.a2a_pb2.Task{id, context_id, status{state,message,timestamp}, artifacts, history, metadata}`; `TaskState` values include SUBMITTED=1, WORKING=2, COMPLETED=3, FAILED=4, INPUT_REQUIRED=6; `DefaultRequestHandler.on_get_task` calls `task_store.get`; `a2a.server.routes.jsonrpc_routes.create_jsonrpc_routes(request_handler, rpc_url)` builds the Starlette route; `a2a.server.request_handlers.DefaultRequestHandler(agent_executor, task_store, agent_card, ...)`.
- Installed SDK anchors: `.venv/lib/python3.14/site-packages/a2a/server/...` (read the installed source; context7 may lag 1.1.5).

## Tasks & Acceptance

**Execution:**
- `tests/workflow/test_task_store.py`, `tests/workflow/test_task_server.py` -- write failing AC tests first (red) -- TDD per AGENTS.md
- `workflow/task_store.py` -- `TaskReader` protocol (`get_run(repo_id, run_id)`, `list_steps(repo_id, run_id)`, `list_runs(repo_id)`), `build_task(run, steps, ...)`, `ReadOnlyTaskStore` (async `get`/`list` project; `save`/`delete` raise `ReadOnlyTaskStoreError`) -- AC1/AC2/AC3
- `workflow/a2a_server.py` -- `RefusingExecutor`, `create_app(reader, repo_id)` wiring `DefaultRequestHandler` + `create_jsonrpc_routes` into a Starlette app -- AC1/AC2
- `tests/workflow/test_task_server.py` -- `get_task` over the ASGI app with httpx; assertions on id/status/artifacts and read-only refusals -- AC1/AC2
- `tests/security/test_compose_secret_placement.py` -- keep/extend the no-`DatabaseTaskStore`/a2a-db assertion -- AC1
- `workflow/README.md`, `docs/DEVELOPER.md` -- docs (brief part 8)

**Acceptance Criteria:**
- Given a stored run and steps, when a task is fetched, then `id == run_id` (UUIDv7) and status/artifacts match `triage_run`/`run_step` (AC1).
- Given the adapter, when `save`/`delete` is called, then it is refused and no second writer exists (AC1).
- Given an `AWAITING_APPROVAL` run with an evidence step, when fetched, then `INPUT_REQUIRED` with a blame-free evidence artifact and no worker scheduled (AC2).
- Given an unknown id or another repo's run, when fetched, then `None` is returned (AC2).
- Given every AD-4 state fixture, when rendered, then status and `terminal_state` match 2.1's mapping and paused/reporting carry no author (AC3).

## Verification

**Commands:**
- `.venv/bin/pytest tests/workflow/test_task_store.py tests/workflow/test_task_server.py -q` -- expected: unit/ASGI tests green, red-first history noted
- `make check` -- expected: PASS
- `.venv/bin/python -c "from workflow.a2a_server import create_app"` -- expected: imports cleanly

**Manual checks:**
- Confirm no `DatabaseTaskStore` reference in `workflow/` or `deploy/` (AD-4).
- Confirm `get_task` performs no INSERT/UPDATE (grep `workflow/task_store.py` for write verbs).

## Auto Run Result

Status: ready-for-dev
Blocking condition: none
Planned: 2026-09-26. Halted after planning. Reused cached `epic-2-context.md` (valid); continuity context from done specs 2.1 and 2.2. No production code written. Assumes 2.1 (`project`), 2.2 (`attribution_allowed`) and 2.3 (`run_step` reader) have landed. Evidence pack is a fixture here; 2.7 produces it.
