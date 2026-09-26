---
title: 'Story 2.8 — Shared step runner: AD-8 validation retry + AD-22 transient retry'
type: 'feature'
created: '2026-09-26'
status: 'done'
baseline_revision: '91c5778a1c8ee23744b15698905b6dee0b184e4e'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
warnings: []
deferred:
  - summary: >-
      The A2A client hard-codes `usage=None`, so every agent call's token
      counters are NULL and every run cost is flagged incomplete until 2.9
      reads the usage agents report into `ModelCallResult.usage`.
    evidence: |-
      workflow/a2a_client.py returns ModelCallResult(value=..., usage=None);
      no contract yet carries usage in an agent reply (epics: 3.2/3.4 agents
      "return usage for central accounting", AD-18). Added by the 2.7-2.8
      post-build review (2026-09-26); owner 2.9 wiring.
  - summary: >-
      The FAILED commit and the terminal history write are two separate
      writes; a crash between them leaves a FAILED run with no history row
      and nothing retries it. Detection/recovery belongs to story 2.12.
    evidence: |-
      _fail commits FAILED via the step recorder, then calls write_terminal
      on a separate store/connection; write_terminal is idempotent per run,
      so a later re-drive can complete the write, but nothing detects the
      gap today.
    location: >-
      workflow/step_runner.py
    severity: medium
  - summary: >-
      The validation-retry feedback envelope ({"request": ...,
      "validation_issues": [...]}) is an ad-hoc dict, not a contracts model
      with a generated schema; pin it as a contract when 2.9's real agents
      must consume it.
    evidence: |-
      AD-6 wants inter-agent payloads as contracts models; no consumer exists
      yet, so the shape stays a documented dict until 2.9 wires agents.
    location: >-
      workflow/step_runner.py
    severity: low
  - summary: >-
      A2aSkillTransport uses asyncio.run per call with a fresh HTTP client:
      sync callers only, no connection reuse; restructure for the worker
      loop when 2.9 wires real agents.
    evidence: |-
      asyncio.run raises inside a running event loop; the sync-only
      requirement is documented in the docstring and DEVELOPER.md.
    location: >-
      workflow/a2a_client.py
    severity: low
---

## Build Brief

**(1) Story:** 2.8 — Shared step runner: AD-8 validation retry + AD-22 transient retry (sprint-status key `2-8-shared-step-runner-ad-8-validation-retry-ad-22-transient-ret`).

**(2) ACs in one line each:**
- AC1: for schema/citation-invalid fixture output on CLASSIFYING/ANALYZING/PROPOSING/REVIEWING, the runner feeds validator errors back once; a second invalid output pauses AWAITING_APPROVAL(validation_failed); each attempt is its own `run_step`; no uncited verdict is ever committed.
- AC2: for network/429/5xx/timeout/retryable-AgentError fixtures, at most three attempts with backoff, each its own `run_step`, then FAILED writes terminal history once; AD-8 and AD-22 budgets stay separate; non-retryable errors fail without retry; fixtures assert exact attempt counts, statuses and available usage (NULL counters included).
- AC3: under a lease, the runner calls the agent with blocking non-streaming JSON-RPC `send_message` carrying contextId = run_id and the per-skill `step_timeout`, validates, and commits output + state atomically under the existing lease guard; a stale owner cannot commit; every attempted call reaches 6.1's central audit; fixture tests need no live services.

**(3) Binding ADs:** AD-1 (transitions only via 2.1's table; the pause carries `validation_failed`), AD-2 (one row per attempt; `(run_id, step, attempt)` identity), AD-4/AD-5 (A2A JSON-RPC surface; the runner is a client, the read-only server untouched), AD-6 (payloads are contracts models; schemas generated), AD-7 (citations validated before acceptance — 4.1's validator), AD-8 (one validation retry with errors fed back; second failure → `AWAITING_APPROVAL(validation_failed)`; never emit an uncited verdict), AD-15 (every read/write binds repo_id), AD-18 (every attempted call audited via 6.1's wrapper), AD-19 (model IDs and `step_timeout` from `config/runtime.yaml`; retry timings from config, never code), AD-22 (transient ≤3 attempts with backoff, each a recorded `run_step`, then terminal FAILED writes history once; non-retryable fails without retry), AD-23 (commit under the lease guard; stale owner discards).

**(4) Files:** create `workflow/step_runner.py` (the runner), `workflow/a2a_client.py` (blocking JSON-RPC transport adapter), `workflow/runtime_config.py` (model IDs + per-skill `step_timeout` loader); extend `config/orchestrator.yaml` + `workflow/orchestrator_config.py` with the transient-retry budget (max attempts 3, backoff base); extend `guardrails/validator.py` with `validate_classification` (schema + parse only); tests under `tests/workflow/`, `tests/guardrails/`. NOT touched: `workflow/step_store.py`/`lease_store.py` (reused as-is), `workflow/transitions.py`, `workflow/history*.py` (write_terminal reused), 6.1/6.2 modules (reused), `contracts/`, `guardrails/schemas/` (no contract change → no regeneration), prompts, agents, `workflow/a2a_server.py`.

**(5) Approach:** one runner, injected edges (SOLID-D): `run_step(context, skill, transport, validate, recorder, attempts, history, audit, sleep, timeouts)` — per attempt it wraps the transport call in 6.1's `audit_model_call` (AD-18), classifies the failure through a typed error pair (`TransientCallError` vs definitive), applies the two independent budgets (AD-8: 1 validation retry with the structured issues fed back; AD-22: ≤3 transient attempts with config-driven backoff via an injectable sleeper), records every failed attempt through a small insert-only `AttemptRecorder` Protocol + Postgres adapter (a failed attempt is a `run_step` row with no state move — the 6.1 insert-only pattern, without the `call:` namespace restriction), and commits the validated output + state move atomically through 2.3's lease-guarded `PostgresStepRecorder` (stale owner → the guard refuses; the runner surfaces the fencing). Exhausted transient budget → `FAILED` + one idempotent `write_terminal` (2.6). Validators are per-step callables returning 4.1's `ValidationIssue`s: verdict steps reuse `validate_verdict`; CLASSIFYING gets the new schema+parse `validate_classification`. The A2A adapter is thin transport (SOLID-S): blocking non-streaming `send_message`, contextId = run_id, timeout from `runtime.yaml`.

**(6) TDD plan (red-first; names cite ACs):** `tests/workflow/test_step_runner.py::test_ac1_first_invalid_output_retries_with_errors_fed_back`, `::test_ac1_second_invalid_output_pauses_validation_failed`, `::test_ac1_each_attempt_is_its_own_run_step`, `::test_ac1_invalid_output_is_never_committed`, `::test_ac2_transient_errors_retry_up_to_three_attempts_with_backoff`, `::test_ac2_exhausted_transient_budget_fails_and_writes_history_once`, `::test_ac2_non_retryable_error_fails_without_retry`, `::test_ac2_fixtures_assert_attempt_counts_status_and_null_usage`, `::test_ac2_validation_and_transient_budgets_are_independent`, `::test_ac3_validated_output_and_state_commit_atomically`, `::test_ac3_stale_owner_result_cannot_commit`, `::test_ac3_every_attempted_call_is_audited`, `::test_ac3_timeout_comes_from_per_skill_config`; `tests/guardrails/test_validator.py::test_ac1_classification_schema_failure_is_structured`; `tests/workflow/test_a2a_client.py::test_ac3_send_message_carries_context_id_run_id` (in-process fixture app, no live services); `tests/workflow/test_runtime_config.py` (per-skill timeouts, AD-19); integration (marked): `tests/workflow/test_step_runner_integration.py` (real Postgres: attempt rows, pause with escalation_reason, FAILED + history once, fencing).

**(7) Risks / OQ:** provider/A2A responses are explicit fixtures (per the story); real specialist integration is 2.9 — the runner's transport Protocol is the seam. The insert-only attempt recorder deliberately mirrors 6.1's pattern without the `call:` restriction — a second insert-only adapter; acceptable now (rule of three not yet met), noted for the review. `TerminalWrite` needs test_id/error_type/frames — supplied by the caller per run (fixtures here; real extraction lands with 2.9/2.12). Backoff values are config placeholders (not calibrated — mirrors OQ-2 marking). No OQ blocking.

**(8) Doc impact:** `docs/DEVELOPER.md` — new "The shared step runner (story 2.8)" subsection (budgets, attempt accounting, seams 2.9 wires), story-table and where-things-live rows, config/orchestrator.yaml mention; `docs/USER-GUIDE.md` — no user-visible behaviour change (no agents connected yet; nothing observable changes): "no doc change" — reason: the runner is internal orchestration with no live callers.

<intent-contract>

## Intent

**Problem:** Steps have no shared execution policy: validation failures and transient errors would be handled ad hoc (or not at all) when live agents connect, losing attempt accounting, pause receipts and history writes.

**Approach:** One shared step runner that every agent step goes through: it calls the agent over blocking JSON-RPC (contextId = run_id, per-skill timeout), audits every attempted call, applies the two independent retry budgets (one validation retry with errors fed back; ≤3 transient attempts with backoff), records every attempt as its own run_step, commits validated output + state atomically under the lease guard, pauses on a second validation failure, and writes terminal history once on FAILED.

## Boundaries & Constraints

**Always:** every attempt (valid, invalid, transient-failed) is its own `run_step` row; validator errors feed back at most once, then `AWAITING_APPROVAL(validation_failed)`; transient retries ≤3 with backoff, then `FAILED` + history written once; non-retryable errors fail without retry; invalid output is never committed as a step result; commit only through the lease guard; contextId = run_id on every call; model IDs/timeouts/retry timings from config.

**Never:** no live agent integration (2.9); no changes to the transition table, lease guard or history semantics; no new contract models or schema regeneration; no `call:`-namespace changes to 6.1's audit; no uncited verdict emitted; no promptfoo changes (no prompts exist).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Valid output first try | fixture payload passes validation | one attempt row (completed) + state commit | No error expected |
| Invalid then valid | attempt 1 invalid, attempt 2 valid | 2 rows; attempt 2's call carries the fed-back errors | recorded, not raised |
| Invalid twice | both attempts invalid | 2 rows, then AWAITING_APPROVAL(validation_failed) | pause, not failure |
| Transient ×3 | network/429/5xx/timeout each attempt | 3 failed rows, then FAILED + history once | terminal |
| Transient then valid | attempt 1 transient, attempt 2 valid | 2 rows, commit on attempt 2 | recorded |
| Non-retryable | definitive AgentError | 1 failed row, FAILED + history, no retry | terminal |
| Stale owner | lease changed mid-call | result discarded, no commit | surfaced, not swallowed |

</intent-contract>

## Code Map

- `workflow/steps.py` -- `StepCommit` (step/to_state/attempt/status/output/guards), `StepRecorder` Protocol, `StepStatus`; the runner's commit vocabulary.
- `workflow/step_store.py:55` -- `PostgresStepRecorder.record(claim, repo_id, commit)`: the lease-guarded insert + state move (2.3); reused, not edited.
- `workflow/lease_store.py` -- `RunLeaseStore.guarded_commit`; the stale-owner refusal lives here (AD-23) — reuse.
- `workflow/transitions.py:185-224` -- `validation_escalation` guard: `AWAITING_APPROVAL` + `EscalationReason.VALIDATION_FAILED` is a legal pause from the working states; reuse via `GuardInput(escalation_reason=...)`.
- `guardrails/validator.py` -- `validate_verdict(payload, served, *, blame_free)` + `ValidationIssue` (4.1); reused for verdict steps; gains `validate_classification`.
- `guardrails/schemas/JevClassification.json` -- committed schema; the CLASSIFYING validation surface (same two-layer pattern as the verdict).
- `workflow/usage_audit.py` -- `audit_model_call`, `UsageAuditStore`, `ModelCallError` (6.1); every attempted call is wrapped; the empty-model guard already refuses blank models.
- `workflow/history_store.py:87` -- `write_terminal(TerminalWrite)` idempotent per run (2.6); the FAILED path calls it once.
- `workflow/orchestrator_config.py` + `config/orchestrator.yaml` -- the loader to extend with the transient-retry budget (AD-19).
- `config/runtime.yaml` -- per-skill `step_timeout` (60/120/180/180) + model IDs; `workflow/runtime_config.py` is its one loader.
- `workflow/db.py` -- `Connection`/`open_connection` for the new adapters.
- `tests/workflow/conftest.py` -- `pg_dsn` fixture for marked integration tests.

## Tasks & Acceptance

**Execution:**
- `workflow/step_runner.py` -- create the runner: typed `TransientCallError`/`DefinitiveCallError`, `AttemptRecorder` Protocol + `PostgresAttemptRecorder` (insert-only failed-attempt rows), budget logic, pause/commit/fail paths -- AC1/AC2/AC3.
- `workflow/a2a_client.py` -- create the blocking non-streaming JSON-RPC transport adapter (contextId = run_id, per-skill timeout) behind the runner's transport Protocol -- AC3.
- `workflow/runtime_config.py` -- create the one `config/runtime.yaml` loader (model IDs + per-skill `step_timeout`) -- AC3/AD-19.
- `config/orchestrator.yaml` + `workflow/orchestrator_config.py` -- add the transient-retry budget (max_attempts: 3, backoff base seconds) -- AC2/AD-19.
- `guardrails/validator.py` -- add `validate_classification` (committed schema + `contracts.JevClassification` parse, same issue shape) -- AC1.
- `tests/...` -- new, red-first per brief (6) -- AC proof.
- `docs/DEVELOPER.md` -- per brief (8); USER-GUIDE: no doc change (reason in brief).

**Acceptance Criteria:**
- Given invalid fixture output on any of the four steps, when the runner validates, then errors feed back once and a second invalid output pauses with `validation_failed`, each attempt its own row, no uncited verdict committed (AC1).
- Given transient/non-retryable fixtures, when the runner handles failure, then ≤3 backoff attempts each recorded, then FAILED + history once, budgets independent, exact counts asserted (AC2).
- Given a leased run and A2A fixtures, when the runner calls and commits, then contextId = run_id, per-skill timeout, atomic lease-guarded commit, stale-owner refusal, and central auditing of every attempted call (AC3).

## Spec Change Log

## Review Triage Log

### 2026-09-26 — Review pass
- verdicts: 39 findings — high 0, medium 5, low 27, false 7, maybe-false 0
- findings:
  - `[medium]` `[patch]` the runner is not re-entrant against its own leftover rows: it always starts at attempt 1, so a reclaimed worker re-running a step whose earlier owner left failed-attempt or fenced audit rows collides on `uq_run_step_identity` and crashes uncaught — every subsequent claim repeats the collision (VG2) — patched: the runner continues attempt numbering (reads the last attempt for both the step and `call:` namespaces and starts at last+1); unit + integration tests prove the re-run after residue.
  - `[medium]` `[patch]` the validator seam is unwired to the real validators: `validate` expects `Sequence[ValidationIssue]` but `validate_verdict`/`validate_classification` return wrapper objects, and no adapter exists — AC1 is proven only with the fake (BH2) — patched: thin per-step validator adapters extract `.issues`, and a runner test drives the real `validate_classification` end to end.
  - `[medium]` `[patch]` transport error classification is fragile: substring/regex matching of SDK error text, a closed status set missing 408/501/other 5xx, and unknown exceptions escaping untyped past the runner's budgets (BH4, EC1, EC2, EC9, CC6) — patched: structured status classification where the SDK exposes it (regex fallback), 408 + any 5xx transient, and a catch-all mapping unexpected transport exceptions to `TransientCallError`; tests added.
  - `[medium]` `[patch]` `_task_reply` refuses every non-FAILED task state, so a legitimate `TASK_STATE_COMPLETED` reply would terminally fail the run (BH5, EC3) — patched: a completed task's data part is extracted (status message, else artifacts); other unexpected states are refused with the state named; tests added.
  - `[medium]` `[defer]` the FAILED commit and the terminal history write are two separate writes: a crash between them leaves a FAILED run with no history row and nothing retries it (BH9, EC5) — the window is tiny and `write_terminal` is idempotent per run; detection/recovery belongs to the live-pipeline recovery story (2.12). Deferred, severity medium.
  - `[low]` `[patch]` DRY: the identity-constraint name and the UniqueViolation→`DuplicateStepError` translation now exist in three adapters — the rule of three is met (BH7, CC1, CC2, CC3, CC7) — patched: one `duplicate_step_error(exc, …)` helper + constant in `workflow/steps.py`, all three adapters call it; the broad `except Exception` + `getattr` chain becomes a specific `UniqueViolation` catch.
  - `[low]` `[patch]` `_BACKOFF_FACTOR = 2` is a retry-timing literal in code against AD-19 (BH6, EC10) — patched: `backoff_factor` joins `RetryBudget` in `config/orchestrator.yaml`.
  - `[low]` `[patch]` validation/cleanup batch: a blank `skill` reaches `audit_model_call` mid-loop and raises with the attempt unrecorded; the dead `retryable` class attributes on the typed errors; `for_skill` rebuilds its mapping dict per call; the unused `owner_ok` parameter on the test `context()` helper (EC7, BH8, BH14b, BH13) — patched: skill validated at the runner entry alongside the config guards, dead attribute removed, mapping lifted to a module constant, dead test parameter removed.
  - `[low]` `[patch]` test-gap batch: `PostgresAttemptRecorder`'s SQL and duplicate mapping are exercised only by opted-in integration tests; `StepRunnerConfig`'s four guard branches are untested; the timeout test races a real socket server inside the unit suite (VG1, CC4, CC5, BH12, BH15, VG3) — patched: unit tests drive the recorder through the injectable `connect` fake (duplicate → `DuplicateStepError`, other errors surface), a parametrized config-guard test, and the timeout test now stubs the SDK transport and asserts the timeout value reaches `ClientCallContext` (the real-socket proof moves to the marked integration suite).
  - `[low]` `[patch]` docs: `A2aSkillTransport.call` uses `asyncio.run` (sync callers only; a running event loop would raise) and the per-call client construction — undocumented (BH3, EC8) — patched: docstring + DEVELOPER.md state the sync-caller requirement and that 2.9's worker wiring revisits it.
  - `[low]` `[defer]` the validation-retry feedback envelope (`{"request": …, "validation_issues": […]}`) is an ad-hoc dict, not a contracts model with a generated schema (BH10) — pinning it as a contract matters when 2.9's real agents must consume it; doing it now adds a contract + schema regen for a shape no consumer exists to validate. Deferred, severity low.
  - `[medium]` `[defer]` (post-build review, 2026-09-26) the A2A client hard-codes `usage=None`: agent token usage is never read, so every agent call audits NULL counters and every run cost is incomplete; no reply contract carries usage yet (owned by 3.2/3.4) — 2.9 must read it into `ModelCallResult.usage` (AD-18). Deferred, severity medium.
  - `[low]` `[defer]` per-call `asyncio.run` + fresh HTTP client loses connection reuse and forbids async callers (BH3) — the sync-only requirement is now documented; restructuring the transport for the worker loop belongs to 2.9's wiring. Deferred, severity low.
  - `[low]` `[reject]` `run_step`'s 10-parameter signature + `noqa: PLR0913, PLR0917` (BH14a) — the inline exception with a cited reason is AGENTS.md's sanctioned mechanism, the spec's Design Notes fix the shape, and the private `_Edges` bag keeps every helper ≤ 5 params; reshaping now would churn the spec'd seam for no behavioural gain.
  - `[low]` `[reject]` multiple data parts in a reply: first part returned silently (EC4) — the contracted reply shape is one data part; a multi-part reply is outside the contract the fixtures and 2.9 will pin.
  - `[low]` `[reject]` a validator crash escapes the runner untyped, stranding the run in a working state (EC6) — a validator bug is not an expected path; wrapping it as a terminal FAILED would mask the bug; surfacing it loudly is AD-22-correct.
  - `[false]` `[reject]` `config/runtime.yaml` "never created in this diff" (BH1) — the file pre-exists with exactly the asserted shape (model IDs + four `step_timeout`s); the diff only flips its DEVELOPER.md status from placeholder to built.
  - `[false]` `[reject]` `AuditIdentity(task_id=str(run_id))` conflates ids (BH11) — the spine's consistency convention defines `run_id` = A2A `task_id` = spoke `contextId`; the fixture's `"task-1"` is a fake artifact, not the convention.
  - `[false]` `[reject]` process guarantees (branch lineage, make check output, TDD ordering, batch report) absent from the diff (IA-process, IA-fakes) — a diff cannot carry process proof; the fake/fixture surface is the spec-conceded seam (real agents are 2.9).
  - `[false]` `[reject]` `types-protobuf` added without being in the brief's file list (IA-deps) — a mypy-stub pin in the dev-constraints, disclosed here and in the story report; no runtime dependency.
  - `[false]` `[reject]` no sprint-status update in the diff (IA-status) — the HALT protocol owns that sync after finalize.

## Design Notes

Budgets are counters, not loops-within-loops: one attempt consumes at most one budget unit (a transient failure consumes AD-22; an invalid output consumes AD-8). Attempt numbers increment across both budgets on the same step, so the `run_step` rows tell the whole story in order.

```python
outcome = run_step(
    context, skill="classify",
    transport=..., validate=validate_classification,
    recorder=postgres_steps, attempts=postgres_attempts,
    history=history_store, audit=audit_store,
    sleep=test_sleep, config=loaded_config,
)
```

The runner returns a typed outcome (`committed` | `paused(validation_failed)` | `failed`) — it never raises past its boundary for expected paths; fencing and store errors surface (AD-22: never swallowed).

## Verification

**Commands:**
- `.venv/bin/pytest tests/workflow/test_step_runner.py tests/workflow/test_a2a_client.py tests/workflow/test_runtime_config.py tests/guardrails/test_validator.py -q` -- expected: all pass, AC-named tests green.
- `.venv/bin/pytest -m integration tests/workflow/test_step_runner_integration.py -q` -- expected: passes against the real Postgres.
- `make check` -- expected: PASS (bootstrap, layer contract, schema drift, ruff, mypy --strict, pylint duplicate-code, pytest ≥85% on contracts/guardrails/workflow).

## Auto Run Result

Status: done

**Summary:** The shared step runner landed: `workflow/step_runner.py` — `run_step` applies the two independent budgets (AD-8: one validation retry with the structured `ValidationIssue`s fed back into the next request; a second invalid output pauses `AWAITING_APPROVAL(validation_failed)` through 2.1's guard; AD-22: ≤3 transient attempts with config-driven exponential backoff, then FAILED + one idempotent terminal history write; definitive errors fail without retry), records every failed attempt as its own insert-only `run_step` row, commits the validated output + state move atomically through 2.3's lease guard (stale owner refused), wraps every attempted call in 6.1's audit, and continues attempt numbering across worker reclaims (both namespaces). `workflow/a2a_client.py` — blocking non-streaming JSON-RPC `SendMessage` with contextId = run_id, per-skill timeout, hardened error classification (408/429/any-5xx transient, catch-all → transient, completed-task replies extracted, `AgentError.retryable` honoured). `workflow/runtime_config.py` — the one `config/runtime.yaml` loader; `config/orchestrator.yaml` gained the retry budget (max_attempts/backoff/backoff_factor). `guardrails/validator.py` gained `validate_classification` (schema + parse). Thin adapters wire the real validators into the runner's seam. No live agents — the transport Protocol is the seam 2.9 connects.

**Files changed:**
- `workflow/step_runner.py` (new) — runner, budgets, attempt continuation, `AttemptRecorder`/`PostgresAttemptRecorder`, typed outcomes.
- `workflow/a2a_client.py` (new) — the blocking A2A transport adapter.
- `workflow/runtime_config.py` (new); `config/orchestrator.yaml` + `workflow/orchestrator_config.py` — retry budget; `config/runtime.yaml` pre-existed and is now documented as built.
- `guardrails/validator.py` — `validate_classification` + `ClassificationResult`.
- `workflow/steps.py`, `workflow/step_store.py`, `workflow/usage_audit.py` — shared `duplicate_step_error` helper (DRY, rule of three met).
- `requirements/dev-constraints.txt` — pinned `types-protobuf` (mypy stubs only).
- Tests: `tests/workflow/test_step_runner.py`, `test_a2a_client.py`, `test_runtime_config.py`, `test_step_runner_integration.py` (new); `test_orchestrator_config.py`, `test_steps.py`, `test_usage_audit.py`, `test_step_integration.py`, `tests/guardrails/test_validator.py` (extended).
- `docs/DEVELOPER.md` — "The shared step runner (story 2.8)" section + rows. USER-GUIDE: no doc change (internal orchestration, no live callers — reason per brief §8).

**Review findings breakdown:** 39 findings — 0 high, 5 medium, 27 low, 7 false, 0 maybe-false. 9 patch entries applied (attempt-number continuation across reclaims [medium]; real-validator seam adapters [medium]; transport classification hardening [medium]; completed-task reply handling [medium]; shared duplicate-translation helper; backoff factor from config; validation/cleanup batch; test-gap batch incl. recorder unit tests and de-flaked timeout test; docs for the sync-only transport and the FAILED/history window). 3 items deferred (medium: FAILED-commit/history-write two-write window → 2.12; low: feedback envelope as a contracts model → 2.9; low: per-call asyncio.run/client → 2.9 wiring). 7 rejected with recorded refutations in the Review Triage Log.

**Follow-up review recommendation:** true — four medium entries were patched; the named unverified risk: the reclaim/re-run attempt-continuation path and the hardened transport classification are proven against fakes/fixture apps and real Postgres, but not against real a2a-sdk agent behaviour — 2.9's first live wiring should re-exercise both seams.

**Verification performed:** `make check` PASS (bootstrap; layer contract PASS; 7 schemas + state diagram byte-identical; ruff check+format clean; mypy --strict clean over 55 source files; pylint duplicate-code 10.00/10; 521 passed, 64 integration deselected; coverage 94.30% ≥ 85%). Integration (explicitly run, real postgres:18): `pytest -m integration tests/workflow/test_step_runner_integration.py -q` → 5 passed. Focused: 122 unit tests over the touched files. I/O matrix audit: all 7 rows covered by passing AC-named tests.

**Residual risks:** the three deferred items above; the `noqa: PLR0913, PLR0917` on `run_step`'s 10-parameter signature (the spec's Design Notes fix the shape; listed per AGENTS.md); adapter HTTP-error classification falls back to SDK message text (no structured status in a2a-sdk 1.1.5 — documented); backoff values are uncalibrated placeholders (OQ-2); `TerminalWrite` identity is caller-supplied until 2.9/2.12.
