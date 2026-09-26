---
title: 'Story 6.1 — Collect every model call and attempt centrally'
type: 'feature'
created: '2026-09-26'
status: 'done'
baseline_revision: '642e56f88e84d37fcb9ff28205d946bc9b9678e5'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-6-context.md'
warnings: []
deferred:
  - summary: >-
      Migration 0007 and the audit INSERT's schema correctness are proven only
      by integration tests excluded from make check; the repo pattern runs
      Docker-backed integration explicitly (make test-integration).
    evidence: |-
      Unit tests drive the SQL through a fake connection that cannot validate
      column names; the real-schema proof lives in the marked integration
      file, which this run executed (8 passed) but the standard gate does not.
    location: >-
      workflow/usage_audit.py
    severity: low
---

## Build Brief

**(1) Story:** 6.1 — Collect every model call and attempt centrally (sprint-status key `6-1-collect-every-model-call-and-attempt-centrally`).

**(2) ACs in one line each:**
- AC1: the central audit recorder turns provider usage (fixtures) and standalone evaluation-harness calls into `run_step` rows carrying model, input/output tokens, cache-read tokens, distinct 5m/1h cache-creation tokens, status and outcome; unreported counters are NULL, never 0; collection lives in the orchestrator/harness — agents never touch the database.
- AC2: routing, spoke, validation-retry and transient-retry invocations each get their own identifiable attempt row; usage returned by a failed call is still persisted; usage lost to a crash stays explicitly incomplete (absent row, never a fabricated zero); fixtures distinguish attempted and completed steps.
- AC3: every structured service-log line for an invocation carries run_id, task_id and step; no tokens, secrets or raw logs appear; the migration adds only the audit fields this story needs.

**(3) Binding ADs:** AD-2 (one `run_step` row per attempt; the `(run_id, step, attempt)` identity is the duplicate backstop), AD-5 (A2A surface untouched — audit is orchestrator-side), AD-9 (Jev probabilities stay audit-only — usage rows never carry them), AD-18 (every LLM/Jev call is a `run_step`: model, token counters with 5m/1h cache-creation split, status, outcome; NULL when unreported), AD-19 (no new thresholds/config; model IDs come from runtime YAML, never code), AD-22 (a failed attempt is a recorded step, never a silent skip; transient-retry attempts are individually visible), AD-23 (audit rows never move run state and never touch the lease-guarded state move), AD-25 (forward-only migration; structured JSON logging; no secrets in logs).

**(4) Files:** create `contracts/usage.py`, `workflow/usage_audit.py`, `workflow/service_log.py`, `deploy/migrations/0007_run_step_audit.sql`; change `workflow/step_store.py` only if the audit insert can reuse its connection plumbing (expected: it cannot — audit inserts are deliberately NOT lease-guarded state moves; keep `step_store.py` untouched unless a shared private helper is genuinely the DRY move); tests under `tests/contracts/`, `tests/workflow/`. NOT touched: `workflow/steps.py` domain types (a new audit dataclass lives in `usage_audit.py`), `workflow/lease_store.py`, `guardrails/`, `gateway/`, `contracts/verdict.py` and existing enums beyond what a new outcome enum needs, prompts, agents, `monitoring/` (6.2 owns prices).

**(5) Approach:** one pure usage contract in `contracts/usage.py` (`ModelUsage`: model + six nullable token counters, frozen, extra-forbid — NULL means "provider did not report", the AD-18 rule as a type); one audit module in `workflow/usage_audit.py` (SOLID-S): a small `UsageAuditStore` Protocol (SOLID-I) with a Postgres adapter that INSERTs an attempt-level `run_step` row — audit rows use a distinct step-name namespace (`call:<skill>`), never collide with a step's own completion row, never move `triage_run.state` (AD-23), and bind `repo_id` (AD-15); plus `audit_model_call`, the shared wrapper (SOLID-O: 2.8's step runner and the eval harness compose it) that runs the wrapped call, records the attempt row with returned usage on success AND on failure, and logs the invocation through `workflow/service_log.py` — a structured-JSON logging helper whose every line carries run_id/task_id/step and whose redaction is proven by test. Migration 0007 adds only: `model`, `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens_5m`, `cache_creation_input_tokens_1h`, `outcome` (all NULLable) — no cost columns (6.2 owns costing).

**(6) TDD plan (red-first; names cite ACs):** `tests/contracts/test_usage.py::test_ac1_unreported_counters_stay_null` (+ round-trip); `tests/workflow/test_usage_audit.py::test_ac1_usage_fixtures_become_audit_rows_with_all_counters`, `::test_ac1_unreported_counters_are_null_not_zero`, `::test_ac2_each_invocation_gets_its_own_identifiable_attempt`, `::test_ac2_usage_returned_on_error_is_persisted`, `::test_ac2_crash_leaves_no_row_and_no_fabricated_usage`, `::test_ac2_attempted_and_completed_steps_are_distinguishable`, `::test_ac3_every_log_line_carries_run_id_task_id_step`, `::test_ac3_no_tokens_secrets_or_raw_logs_in_log_lines`; integration (marked): `tests/workflow/test_usage_audit_integration.py` against real Postgres (migration 0007 applies, insert + read-back). Layer contract and `make check` cover the rest.

**(7) Risks / OQ:** no agents exist yet (Epic 3), so the wrapper is proven with fake callables and usage fixtures — its consumers (2.8's step runner, the eval harness, the A2A client) wire it later; the spec pins the seam, not the callers. Attempt rows use the existing `run_step` status CHECK (`completed`/`failed`) — a crash before the insert leaves no row, which IS the explicit incompleteness (no new status value, so no migration CHECK change). Standalone harness calls pass their own identity namespace; the recorder is identity-agnostic. No OQ blocking.

**(8) Doc impact:** `docs/DEVELOPER.md` — new "Model-call audit (story 6.1)" subsection (recorder, wrapper, NULL rule, log helper, how 2.8/6.2 consume it), story-table and where-things-live rows; `docs/USER-GUIDE.md` — no user-visible behaviour change (audit is internal bookkeeping): "no doc change" — reason: nothing about installing, configuring or using the tool changes.

<intent-contract>

## Intent

**Problem:** Nothing records model/Jev invocations yet: when live integration starts, routing calls, retries and usage evidence would be lost, and token accounting could not be audited or costed.

**Approach:** A central, orchestrator-side audit recorder: every model call becomes an attempt-level `run_step` row with the model, its token counters (NULL when unreported), status and outcome — recorded through one shared wrapper that also emits structured, secret-free log lines — with a forward-only migration adding only the audit columns.

## Boundaries & Constraints

**Always:** unreported counters stored as NULL, never 0; usage returned by a failed call persisted; a crash leaves the usage explicitly absent (no row), never fabricated; every audit row binds `repo_id`; audit collection only in orchestrator/harness code (agents hold no DB client); log lines carry run_id, task_id, step and never tokens, secrets or raw logs; the migration adds only this story's audit fields; attempt rows never move `triage_run.state`.

**Never:** no agent-side DB access; no cost computation or price table (6.2); no retry/pause policy (2.8 owns it); no new step status values; no raw log text, prompts or responses in `run_step.output` or logs; no changes to the lease-guarded step-commit path.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Successful call, full usage | provider usage with all counters | row: model + all counters + completed + outcome | No error expected |
| Partial usage | provider reports some counters | unreported counters NULL, never 0 | No error expected |
| Failed call with usage | call raises, usage was returned | row: status failed + usage persisted + outcome | recorded, not raised |
| Failed call without usage | call raises, no usage | row: status failed, counters NULL | recorded, not raised |
| Crash before recording | process dies mid-call | no row; usage stays explicitly incomplete | nothing fabricated |
| Repeated invocation | same step name, another attempt | distinct row per attempt number | duplicate attempt raises (AD-2 backstop) |

</intent-contract>

## Code Map

- `deploy/migrations/0004_run_step.sql` -- current `run_step` shape (identity, status CHECK completed/failed, output jsonb); 0007 ALTERs only audit columns in.
- `workflow/migrate.py` -- forward-only runner; new migration file is picked up automatically (AD-25).
- `workflow/steps.py` -- `StepRecord`/`StepStatus` domain types; NOT extended (audit attempt shape lives in `usage_audit.py`).
- `workflow/step_store.py:55` -- `_INSERT_STEP_SQL` + `PostgresStepRecorder` (lease-guarded, state-moving); the audit insert is a separate, simpler adapter — do not route audit rows through the state-move path.
- `workflow/lease_store.py` -- `RunLeaseStore.guarded_commit`; audit rows deliberately outside it (AD-23 guards state moves, not bookkeeping).
- `contracts/evidence.py:21` -- pattern for a small frozen contracts model with a module constant (`AUTHOR_ATTRIBUTION_FIELD`); `contracts/usage.py` follows it.
- `contracts/errors.py` -- typed error shape; outcome values stay a closed enum, never free text.
- `workflow/evidence_collection.py:20` -- existing `logging.getLogger` usage; AC3's helper supersedes ad-hoc lines for invocations only — existing loggers stay.
- `tests/workflow/conftest.py` -- integration-test markers/DSN fixtures used by marked Postgres tests.
- `tests/fixtures/` -- test thresholds live here; usage fixtures are inline test data (no new fixture files needed).

## Tasks & Acceptance

**Execution:**
- `contracts/usage.py` -- create `ModelUsage` (model + six nullable counters) and the outcome enum -- AC1/AC2 data shape.
- `deploy/migrations/0007_run_step_audit.sql` -- ALTER `run_step` with the seven audit columns, all NULLable -- AC1/AC3 (only needed fields).
- `workflow/usage_audit.py` -- create `UsageAuditStore` Protocol + `PostgresUsageAuditStore` (insert-only, repo-bound, `call:` step namespace) + `audit_model_call` wrapper (records success and failure, persists returned usage, logs via the helper) -- AC1/AC2.
- `workflow/service_log.py` -- create the structured invocation-log helper (run_id/task_id/step on every line; field allowlist) -- AC3.
- `tests/contracts/test_usage.py`, `tests/workflow/test_usage_audit.py`, `tests/workflow/test_usage_audit_integration.py`, `tests/workflow/test_service_log.py` -- new, red-first per brief (6) -- AC proof.
- `docs/DEVELOPER.md` -- per brief (8); USER-GUIDE: no doc change (reason in brief).

**Acceptance Criteria:**
- Given provider usage fixtures and harness calls, when the recorder processes them, then audit rows carry model, all six counters (NULL when unreported), status and outcome (AC1).
- Given routing/spoke/validation-retry/transient-retry invocations, when the wrapper records them, then each attempt is its own row, failed calls keep returned usage, and a crash leaves usage explicitly absent (AC2).
- Given an invocation, when it logs, then every line carries run_id/task_id/step with no tokens, secrets or raw logs, and migration 0007 adds only the audit columns (AC3).

## Spec Change Log

## Review Triage Log

### 2026-09-26 — Review pass
- verdicts: 41 findings — high 0, medium 2, low 31, false 8, maybe-false 0
- findings:
  - `[medium]` `[patch]` log line emitted before the row is persisted, so a duplicate refusal or a crash between the two leaves a log claiming a recorded invocation with no row — contradicting "the missing row is the honest record" (BH1, EC5) — patched: `_record` persists first, logs only after a successful insert.
  - `[low]` `[patch]` any `UniqueViolation` is translated to `DuplicateStepError`, even one from a different constraint (BH2) — patched: the adapter checks `exc.diag.constraint_name` and only translates the `(run_id, step, attempt)` identity index, re-raising anything else.
  - `[low]` `[patch]` `attempt` is never validated (0/negative accepted until the DB CHECK) and `step_name="call:"` with an empty suffix passes; the namespace guard also lives only in the wrapper, so a direct `record_attempt` call bypasses it (BH4, EC8, EC1, EC2) — patched: `attempt >= 1` and non-empty `call:` suffix validated in `audit_model_call`, and the namespace guard moved into `PostgresUsageAuditStore.record_attempt` so the store enforces it too.
  - `[low]` `[patch]` incoherent status/outcome rows are constructible: `ModelCallError(outcome=VERDICT)` yields failed+verdict, a success result with `outcome=TIMEOUT` yields completed+timeout (BH5, EC4) — patched: `ModelCallError` rejects `VERDICT`, and the wrapper requires `VERDICT` on the success path.
  - `[low]` `[patch]` the closed outcome set lives twice (Python enum + SQL CHECK) with no sync pin (BH7) — patched: a unit test parses migration 0007 and asserts the CHECK list equals the `CallOutcome` values.
  - `[low]` `[patch]` `service_log`'s closed-set guarantee is by convention: `status`/`outcome` are plain `str`, the field list exists in three places, `event="model_call"` is a magic string, and the docs overclaim "no way to attach" raw text (BH8, EC7, CC4, CC5, CC7) — patched: fields typed `StepStatus | None` / `CallOutcome | None`, dict derived from the dataclass and `LOG_FIELDS` from its fields, an `EVENT_MODEL_CALL` constant, and doc wording softened to allowlisted keys with typed values.
  - `[low]` `[patch]` `ModelUsage.outcome` is dead weight — the adapter reads the outcome from the attempt, never from usage; two sources for one fact (VG4, CC1) — patched: field removed from `ModelUsage`, tests updated.
  - `[low]` `[patch]` test-quality batch: the full `run_step` column frozenset duplicated in two integration files; `test_0007_migration_applies_forward_only` doesn't cite an AC; `FakeConnection` lacks the `transaction()` member the injected `Connection` protocol requires; `object` typing defeats the hints (CC9, CC10, BH10b, CC8, CC2, CC3) — patched: shared `tests/workflow/column_sets.py` constant, test renamed `test_ac3_0007_migration_applies_forward_only`, `transaction` stub added, helpers typed `ModelCallAttempt`/real wrapper type.
  - `[low]` `[patch]` docs: DEVELOPER.md names `ModelCallFailed`, which does not exist (renamed `ModelCallError`); the "never confused with a step's own completion row" claim is overstated on the read side — `resume` includes `call:` rows in `completed_steps` (harmless today: consumers query exact step names) (VG3, VG2) — patched: doc corrected to `ModelCallError`, and the claim reworded to the identity-collision fact with the read-side note.
  - `[low]` `[defer]` migration 0007 and the audit INSERT's schema correctness are proven only by integration tests excluded from `make check` (VG1) — the repo's established pattern runs Docker-backed integration explicitly (`make test-integration`), which this run executed (8 passed); recorded so the story report does not claim `make check` proved the SQL. Deferred, severity low.
  - `[low]` `[reject]` a fresh DB connection per attempt row (BH3) — matches the established per-operation connection pattern of `step_store`/`lease_store`; pooling is an orchestrator-entrypoint concern (2.8/2.12), and audit rows are per-LLM-call (dominated by call latency).
  - `[low]` `[reject]` no duration/latency captured (BH6) — AD-18's field list does not include it and the spec forbids adding fields beyond this story's needs; adding a column would need a new forward-only migration and is 6.2+/S5 territory.
  - `[low]` `[reject]` `task_id` free-form `str`, empty passes (BH9) — the harness supplies it; `AuditIdentity` documents it as the log-line identity; validation would guard a caller bug with no demonstrated path.
  - `[low]` `[reject]` loose assertion in `test_ac1_extra_fields_are_forbidden` (BH10c) — cosmetic; the extra-forbid behaviour is also pinned structurally by the model config.
  - `[low]` `[reject]` the `except Exception` branch records no failure-class hint (BH10d) — adding error kinds means new enum values plus a forward-only migration; the closed three-value set is the AD-18 field list; the raised exception itself carries the detail.
  - `[low]` `[reject]` raw FK violation escapes untranslated (EC3) — a nonexistent run is a caller programming error that fails loudly; other adapters also let unexpected DB errors surface raw.
  - `[low]` `[reject]` a `record_attempt` failure inside a failure handler masks the original model-call error (EC6) — after the reorder the original stays in the exception chain (`__context__`), and the AD-2 duplicate refusal must surface.
  - `[low]` `[reject]` spec brief says "six nullable token counters", code has five + outcome (CC6) — the fix edits this build's spec; the migration (authoritative) and DEVELOPER.md already state the correct five-counter shape, and the discrepancy is recorded here.
  - `[false]` `[reject]` outcome semantics thin / success always VERDICT by convention (IA5 partial, BH5 context) — the closed set is the AD-18 field list; the coherence patch removes the constructible inconsistencies.
  - `[false]` `[reject]` "every model call" realized as a seam with zero production callers (IA1) — the spec-conceded Reading B; no agents exist until Epic 3, and the wiring obligation is recorded in the spec's risk section and DEVELOPER.md.
  - `[false]` `[reject]` failed-usage exercised via the bespoke `ModelCallError` no provider path populates yet (IA2) — the adaptation contract IS the seam deliverable; callers raise it when wiring lands.
  - `[false]` `[reject]` harness calls unexercised (IA3) — same seam reading; the recorder is identity-agnostic and proven with stand-ins.
  - `[false]` `[reject]` AD-19 model-ID config sourcing unexercised (IA4) — the model is a parameter, never hardcoded; no caller exists to source it yet.
  - `[false]` `[reject]` 2.3's guard test amended (IA5) — deliberate, commented supersession per the 6.1 spec; the exact-set assertion is stricter than before.
  - `[false]` `[reject]` process guarantees (branch lineage, make check output, AC-by-AC proof) absent from the diff (IA6) — a diff cannot carry process proof; verified by the orchestrator outside it.
  - `[false]` `[reject]` spec `status: in-progress` at snapshot (BH10a, IA5 partial) — transient; finalize sets `done`.

## Design Notes

Attempt rows use the `call:` step-name namespace so they can never collide with a step's own completion row under the `(run_id, step, attempt)` unique identity: the Jev call inside `classify` attempt 1 is `call:system_one` attempt 1. The wrapper is the audit primitive; 2.8's step runner composes it with retry policy — this story implements no retry loop.

```python
result = audit_model_call(
    store,
    identity,
    step_name="call:system_one",
    attempt=1,
    model="claude-haiku-4-5-20251001",
)(lambda: jev.system_one(...))
```

`outcome` is a closed enum (e.g. `verdict`, `error`, `timeout`) — never free text, never a raw response.

## Verification

**Commands:**
- `.venv/bin/pytest tests/contracts/test_usage.py tests/workflow/test_usage_audit.py tests/workflow/test_service_log.py -q` -- expected: all pass, AC-named tests green.
- `.venv/bin/pytest -m integration tests/workflow/test_usage_audit_integration.py -q` -- expected: passes against the real Postgres (migration 0007 applied).
- `make check` -- expected: PASS (bootstrap, layer contract, schema drift, ruff, mypy --strict, pylint duplicate-code, pytest ≥85% on contracts/guardrails/workflow).

## Auto Run Result

Status: done

**Summary:** Central model-call audit landed: `contracts/usage.py::ModelUsage` (model + five nullable token counters — NULL means "provider did not report", never 0) and the closed `CallOutcome` set; `workflow/usage_audit.py` with the `UsageAuditStore` Protocol, `PostgresUsageAuditStore` (insert-only, repo-bound, `output` always NULL, `call:` namespace enforced, only the identity constraint translated to `DuplicateStepError`), and `audit_model_call` — the one wrapper that persists the attempt row on success AND on failure (usage returned by a failed call is kept), lets a crash escape unrecorded (the missing row IS the incompleteness), persists before it logs, and refuses incoherent rows (no failed+verdict, no completed+failure-outcome, no attempt < 1, no bare `call:`); `workflow/service_log.py` emits one allowlisted JSON line per invocation (run_id/task_id/step on every line; typed closed-set values; field list derived once); migration 0007 adds only the seven NULLable audit columns + the outcome CHECK, pinned in sync with the Python enum by test. No cost columns (6.2), no retry policy (2.8), no state moves (AD-23).

**Files changed:**
- `contracts/usage.py` (new) — `ModelUsage` + `CallOutcome`.
- `workflow/usage_audit.py` (new) — recorder, adapter, wrapper, `ModelCallAttempt`/`ModelCallError`/`ModelCallResult`/`AuditIdentity`.
- `workflow/service_log.py` (new) — structured invocation-log helper.
- `deploy/migrations/0007_run_step_audit.sql` (new) — audit columns only.
- `tests/contracts/test_usage.py`, `tests/workflow/test_usage_audit.py`, `tests/workflow/test_service_log.py`, `tests/workflow/test_usage_audit_integration.py`, `tests/workflow/column_sets.py` (new); `tests/workflow/test_step_integration.py` (2.3 guard superseded deliberately, exact-set assertion stricter).
- `docs/DEVELOPER.md` — "Model-call audit (story 6.1)" section + table rows. USER-GUIDE: no doc change (internal bookkeeping; nothing about installing/using the tool changes — reason per brief §8).

**Review findings breakdown:** 41 findings — 0 high, 2 medium, 31 low, 8 false, 0 maybe-false. 9 patch entries applied (persist-before-log [medium], constraint-name-scoped duplicate translation, attempt/step-name/namespace validation, status/outcome coherence, enum↔CHECK sync pin, service_log structural typing + single field-list source, dead `ModelUsage.outcome` removed, test-quality batch incl. shared column constant, docs corrections). 1 item deferred (low: migration/INSERT schema proof lives in the explicitly-run integration tests, not `make check`). 31 rejected with recorded refutations in the Review Triage Log.

**Follow-up review recommendation:** false — one medium patched entry (below the two-medium threshold), no high patched; no unverified risk beyond the recorded deferral.

**Verification performed:** `make check` PASS (bootstrap; layer contract PASS; 7 schemas + state diagram byte-identical; ruff check+format clean; mypy --strict clean; pylint duplicate-code 10.00/10; 436 passed, 55 integration deselected; coverage 94.23% ≥ 85%). Integration (explicitly run, real postgres:18): `pytest -m integration tests/workflow/test_usage_audit_integration.py tests/workflow/test_step_integration.py -q` → 19 passed. Focused: 28 unit tests over the touched files. I/O matrix audit: all 6 rows covered by passing AC-named tests.

**Residual risks:** the wrapper has no production caller yet (no agents until Epic 3) — 2.8's step runner, the eval harness and the A2A client must wire `audit_model_call` in, and a caller whose provider error carries usage must re-raise it as `ModelCallError(usage=...)`; the migration/INSERT SQL proof lives in the explicitly-run integration suite (deferred item).
