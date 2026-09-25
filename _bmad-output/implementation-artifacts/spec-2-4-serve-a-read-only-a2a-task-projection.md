---
title: 'Story 2.4 — Serve a read-only A2A task projection'
type: 'feature'
created: '2026-09-26'
status: 'done'
route: 'dispatch'
baseline_revision: 'f206729ae4cff07b3b9cb9d7f9a3116961e3937d'
review_loop_iteration: 0
followup_review_recommended: false
context: ['{project-root}/AGENTS.md']
warnings: ['oversized']
deferred:
  - summary: >-
      The A2A server has no concrete Postgres TaskReader, so the served endpoint is proven only with fixture readers; its list path must be batch-shaped to avoid a query per run.
    evidence: |-
      The AC is fixture-driven ("stored run and step fixtures"), so 2.4 ships the TaskReader protocol plus a fake; the orchestrator entrypoint (a later story) must supply a real reader bound to triage_run/run_step before the endpoint serves real runs. `ReadOnlyTaskStore.list` reads every run for the repo and then calls `list_steps` once per run, so the concrete reader must add a batch `list_steps_for_runs(repo_id, run_ids)` method (or equivalent) rather than reusing the per-run call.
    location: >-
      workflow/a2a_server.py
    severity: medium (unverified)
  - summary: >-
      Every completed step output is published as an artifact without a payload allowlist, so interim data (suspects, proposed diff, objections) is served.
    evidence: |-
      build_task maps every completed run_step output to an artifact and strips only author attribution. Contract-shape validation and an exposure allowlist belong to the later coverage/security stories (4.1/4.3).
    location: >-
      workflow/task_store.py
    severity: low
  - summary: >-
      The read-only A2A endpoint has no authentication; its only scoping is the single repo_id bound at build time.
    evidence: |-
      AD-14 requires the orchestrator's own auth middleware to validate the caller's GitHub user token and reject unauthenticated calls before any check. 2.4 serves `get_task`/`list_tasks` with no auth and a build-time repo scope, so it must not be exposed beyond the single demo deployment until the AD-14 auth middleware lands (punch-out story).
    location: >-
      workflow/a2a_server.py
    severity: medium (unverified)
  - summary: >-
      The below-cutoff arm of AD-27 blame-free output is not enforced on the A2A endpoint until story 4.1.
    evidence: |-
      2.4 cannot read a run's stored confidence, so `_SERVING_CONFIDENCE` forces a confidence that is never below the cutoff; a finished low-confidence run would still show author attribution. Story 4.1 AC3 owns the confidence-below-cutoff arm and must supply the run's real confidence to `build_task`. Pinned by tests/workflow/test_task_server.py::test_ac3_below_cutoff_blame_free_arm_is_a_tracked_placeholder_until_4_1.
    location: >-
      workflow/a2a_server.py
    severity: medium (unverified)
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

## Review Triage Log

### 2026-09-26 — Review pass

- verdicts: 25 findings — high 0, medium 1, low 24, false 0, maybe-false 0
- findings:
  - `[low]` `[reject]` the agent card is built but no `/.well-known/agent-card.json` route is mounted — agent discovery/registry is story 3.9's; 2.4 serves `get_task`/`list_tasks`.
  - `[low]` `[patch]` the served path injects a fixed serving confidence, so the below-cutoff blame arm cannot trigger and the docs overclaimed it — docs reworded; the run's confidence is not persisted yet and 4.1 adds it to the reader.
  - `[low]` `[reject]` `list` ignores request filters/pagination — pagination is not in the ACs and the demo is single-tenant with a small run set; a later refinement.
  - `[low]` `[reject]` `list` does one `list_steps` per run and builds artifacts before the handler trims them — a performance refinement, no correctness harm at this scale.
  - `[low]` `[reject]` the sync `TaskReader` called from async store methods could block the loop — there is no concrete reader yet; the reader story owns the I/O strategy (async adapter or thread offload).
  - `[low]` `[reject]` AD-4's `outcome=rejected_by_human` is not written as metadata — `terminal_state` already carries the outcome; the parenthetical is descriptive.
  - `[low]` `[defer]` every completed step output is published without a payload allowlist, so interim data is served — a security/validation concern for the later coverage stories (4.1/4.3).
  - `[low]` `[patch]` `GET_TERMINAL`/`FAILED` and failed-step artifact exclusion were untested — added a failed-step artifact test.
  - `[low]` `[patch]` the compose no-`DatabaseTaskStore` check was duplicated into the task-store test — removed; the security suite owns it.
  - `[low]` `[patch]` the new test files carried ruff findings the gate never sees (`tests/` is not linted) — made both files ruff-clean.
  - `[low]` `[patch]` the unknown-task wire test only asserted `"error" in body` — now asserts the JSON-RPC code and HTTP status.
  - `[low]` `[patch]` write refusal was never exercised over the served app — added a wire test posting `CancelTask` and asserting refusal.
  - `[low]` `[reject]` `_as_run_id` accepts any UUID version, not just v7 — the client may send any id; a non-run id simply finds nothing.
  - `[low]` `[reject]` `TaskStatus(timestamp=...)` assumes a timezone-aware value — `triage_run.updated_at` is `timestamptz`, so it is always aware.
  - `[low]` `[reject]` duplicate of the `list` request-filter finding.
  - `[low]` `[reject]` duplicate of the `list` pagination finding.
  - `[low]` `[patch]` a JSON list/tuple step output was rendered as text `repr` — now treated as data artifacts.
  - `[low]` `[patch]` failed-step exclusion in the artifact filter was unverified (verification-gap) — added the test.
  - `[low]` `[patch]` duplicate of the confidence-arm and test-ruff findings (verification-gap).
  - `[low]` `[reject]` intent-alignment: the guarantees are proven mostly at the `build_task` surface over a fake reader, not the wire — the AC is explicitly fixture-driven; the concrete Postgres reader is a later integration.
  - `[low]` `[patch]` `"author_login"` was a local literal duplicating a contract field name, so a rename would silently stop the blame strip — the key now lives once in `contracts.evidence`.
  - `[low]` `[reject]` `task_store.py` builds protobuf `Task`/`Artifact` while calling itself pure — a protobuf read-model build is a pure transformation; the SDK `TaskStore` ABC is necessarily SDK-aware.
  - `[low]` `[patch]` duplicate of the confidence-arm docs finding.
  - `[low]` `[patch]` `create_app`'s `confidence`/`cutoffs` keyword parameters had no caller — removed.
  - `[medium]` `[defer]` the A2A server has no concrete Postgres `TaskReader`, so the served endpoint is proven only with fixture readers — the AC is fixture-driven, but the orchestrator entrypoint (a later story) must supply one before the endpoint serves real runs.

### 2026-09-26 — Second review pass (post-finalization fixes)

- `[medium]` `[defer]` the A2A endpoint has no authentication (AD-14); recorded with its AD-14 owner in the deferral list, and the reader deferral now names the batch shape `list_steps_for_runs` the concrete Postgres reader must use to avoid a query per run.
- `[medium]` `[defer]` the below-cutoff AD-27 blame-free arm is not enforced until story 4.1 (the serving confidence cannot be read yet); recorded as a deferral, marked with a `TODO(story 4.1)` in `workflow/a2a_server.py`, and pinned by `test_ac3_below_cutoff_blame_free_arm_is_a_tracked_placeholder_until_4_1` so the gap is loud and any wiring change is deliberate.

## Auto Run Result

Status: done
Baseline: `f206729ae4cff07b3b9cb9d7f9a3116961e3937d`.

**Summary.** Built the read-only A2A task view (AD-4): `workflow/task_store.py` projects a stored run and its steps onto a protobuf A2A `Task` (`task_id`/`context_id` = `run_id`, status/terminal-state via 2.1's `project()`, artifacts from completed `run_step` outputs, author stripped when 2.2's `attribution_allowed` is false), with `save`/`delete` refused so no second task-state owner exists. `workflow/a2a_server.py` wires the read-only store plus a `RefusingExecutor` into the SDK's `DefaultRequestHandler` and serves `get_task`/`list_tasks` over the JSON-RPC binding. No `DatabaseTaskStore`/a2a-db is used.

**Files changed (one line each):**
- `workflow/task_store.py` — the read-only projection: `RunRecord`, `TaskReader`, `build_task`, `ReadOnlyTaskStore`.
- `workflow/a2a_server.py` — transport wiring: `RefusingExecutor`, `create_app`, JSON-RPC routes.
- `contracts/evidence.py` — the one `AUTHOR_ATTRIBUTION_FIELD` constant.
- `tests/workflow/{test_task_store,test_task_server}.py` — AC and ASGI tests.
- `workflow/README.md`, `docs/DEVELOPER.md` — docs.

**Review findings.** 25 reported: 0 high, 1 medium, 24 low. Patched 12 entries (failed-step artifact coverage, wire write-refusal, list-output data artifacts, the contract-sourced author key, unused `create_app` params, the duplicated compose check, a sharper not-found assertion, test lint, and the confidence-arm docs); deferred 2 (payload allowlist for 4.1/4.3; the concrete Postgres reader); rejected 11 with reasons above.

**Patched root causes:** failed-step artifact exclusion, the served write-refusal path, JSON list outputs rendered as text, the author-key literal, dead `create_app` parameters, a duplicated schema assertion, a weak not-found test, and new-test lint — none changed the projection's behaviour for the frozen ACs.

**Follow-up review recommendation: false.** All patches were low severity and no high or two-or-more-medium entries were patched, so the work has converged.

**Verification performed:**
- `git diff` reviewed since baseline, then re-generated after patches.
- `make check` → PASS (256 tests, coverage 94.83%).
- `.venv/bin/pytest -m integration -q` → 31 passed.
- Manual: no `INSERT`/`UPDATE`/`DELETE` or run/step writes in the new modules; no `DatabaseTaskStore` in `workflow/`.

**Residual risks:** the endpoint is proven with fixture readers (a concrete Postgres `TaskReader` is owed by the orchestrator entrypoint); the run's confidence is not persisted, so only the state arm of the blame rule is live (4.1); interim step payloads are served without an allowlist (4.1/4.3).

## Spec Change Log

<!-- none: no bad_spec loopback on this story -->
