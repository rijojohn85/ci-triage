# Developer guide — Blameless CI Triage

How the system is built, where things live, and how to run, test and extend it. This file describes what exists on `main` today; each story updates it in the same PR (AGENTS.md "How work is done", step 7).

- Decisions and their reasons: [architecture spine](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md) (AD-1 … AD-27). This guide links ADs; it does not restate them.
- Rules for writing code here: [AGENTS.md](../AGENTS.md).
- Story plan and order: [epics.md](../_bmad-output/planning-artifacts/epics.md) ("Global build order"); status in [sprint-status.yaml](../_bmad-output/implementation-artifacts/sprint-status.yaml).

## Architecture in one page

Hub and spoke (spine "Design Paradigm", AD-4, AD-5):

- A **gateway** accepts GitHub `workflow_run` failures and queues them in Postgres.
- One **orchestrator** owns each run's state (`triage_run`) and drives an explicit state machine. It is the only component that talks to agents.
- Four stateless **agents** (A2A services) each answer one question: Jev classifies the failure, the Analyzer (Haiku) explains it with citations, the Proposer (Sonnet) writes the fix, the Reviewer (Sonnet) raises objections. Agents never call each other and hold no GitHub or Postgres access.
- **Guardrails** check every agent reply (schema and citations, AD-7, AD-8); a deterministic **risk gate** (AD-13) picks the outcome: draft PR, infra report, or a pause for a human (`INPUT_REQUIRED`, AD-14).

Every message between orchestrator and agent is an A2A message whose data part is a `contracts.a2a.DataPart` (see [Contracts](#contracts-story-02)).

## Built so far

| Story | What exists | Where |
| --- | --- | --- |
| 0.1 | Rubric folder layout, pinned toolchain bootstrap, layer-contract check, quality gates (`make check`) | `scripts/`, `Makefile`, `pyproject.toml` |
| 0.2 | Shared Pydantic payload contracts, generated JSON Schemas, schema drift gate | `contracts/`, `guardrails/schemas/`, `scripts/generate_schemas.py` |
| 0.3 | Compose foundation: postgres:18 + healthcheck, one-shot forward-only migration job (`service_completed_successfully` gating), secret placement | `deploy/`, `workflow/migrate.py`, `tests/workflow/`, `tests/security/` |
| 0.4 | Protected external demo repo: seeded Python package with green CI, AD-16 GitHub App + installation, default-branch ruleset (App not a bypass actor), read-back gate | `test-data/demo-repo-seed/`, `test-data/demo-repo.md`, `scripts/verify_demo_repo.py`, `scripts/ruleset-seed.json` |
| 2.1 | The AD-1 run-state machine: `RunState` enum, one declarative transition table, pure guards, non-retryable `IllegalTransition`, pure AD-4 projection, generated state diagram + drift gate, `0001_triage_run` migration, thresholds loader | `workflow/run_states.py`, `workflow/transitions.py`, `workflow/projection.py`, `workflow/thresholds.py`, `workflow/diagram.py`, `scripts/generate_state_diagram.py`, `workflow/STATE_DIAGRAM.md`, `guardrails/thresholds.yaml`, `deploy/migrations/0001_triage_run.sql`, `tests/workflow/` |
| 2.2 | The one confidence number (AD-9): Jev's `Choice`/`Noul` contracts, the frozen `ClassConfidence` min rule, the injection pre-screen cap, classification-branch cut-off predicates, the AD-27 blame-free attribution predicate, new cut-offs in `guardrails/thresholds.yaml` | `contracts/jev.py`, `contracts/verdict.py` (`effective_confidence`), `guardrails/confidence.py`, `workflow/attribution.py`, `workflow/thresholds.py`, `guardrails/thresholds.yaml`, `guardrails/schemas/JevClassification.json`, `tests/contracts/test_jev.py`, `tests/guardrails/`, `tests/workflow/test_attribution.py`, `tests/workflow/test_thresholds.py` |
| 1.1 | Gateway intake: the webhook signature is checked over the raw bytes before parsing, unknown installations are refused, replayed deliveries and duplicate run identities collapse to one `triage_run(RECEIVED)`, bursts are shed, and run ids are time-ordered UUIDv7 | `gateway/`, `workflow/ids.py`, `config/gateway.yaml`, `deploy/migrations/0002_webhook_delivery.sql`, `deploy/gateway.Dockerfile`, `tests/security/` |
| 1.2 | Worker leases and fencing: a claim takes the next unleased/expired non-terminal, non-paused run in a short `FOR UPDATE SKIP LOCKED` transaction, renew extends only the owner's live lease, and a stale owner's lease-guarded commit is discarded (`LeaseLost`); lease validity uses the database clock and lease timings come from config | `workflow/leases.py`, `workflow/lease_store.py`, `workflow/orchestrator_config.py`, `config/orchestrator.yaml`, `deploy/migrations/0003_triage_run_lease.sql`, `tests/workflow/`, `tests/security/test_compose_secret_placement.py` |
| 2.3 | Steps and resume: a finished step's row and the run's state move commit in one lease-guarded transaction, validated by the 2.1 transition table; a reclaimed run reads its current state and completed step names so it skips finished work, and a stale owner's step-commit writes nothing | `workflow/steps.py`, `workflow/step_store.py`, `deploy/migrations/0004_run_step.sql`, `tests/workflow/test_steps.py`, `tests/workflow/test_step_integration.py`, `tests/security/test_compose_secret_placement.py` |
| 2.4 | Read-only A2A task view: `get_task`/`list_tasks` project a stored run and its steps onto an A2A `Task` (task id = run id), a paused run is `INPUT_REQUIRED` with a blame-free evidence pack and no worker is started, and every write to the view is refused — so no second task-state writer exists | `workflow/task_store.py`, `workflow/a2a_server.py`, `tests/workflow/test_task_store.py`, `tests/workflow/test_task_server.py` |
| 2.5 | Deterministic CI-log distiller (AD-20): strips ANSI/control characters, keeps only error blocks, stack traces and JUnit failures, numbers the survivors, and clips them to the `distiller.max_bytes` bound — with no model, network or clock, so the same input always gives the same output | `workflow/distiller.py`, `workflow/thresholds.py`, `guardrails/thresholds.yaml`, `tests/security/test_distiller.py`, `tests/workflow/test_thresholds.py`, `tests/fixtures/thresholds.py` |
| 2.6 | Structured tenant-scoped `history` (AD-15): sha256 fingerprint of normalized test_id + error_type + top stack frames, `write_terminal` accepts only terminal `RunState`s and is idempotent per `run_id`, every read/write binds `repo_id`, seed rows enter only via `history_import`, a separate `pr_feedback` table keeps human PR text out of `history` forever | `workflow/history.py`, `workflow/history_store.py`, `workflow/pr_feedback.py`, `workflow/pr_feedback_store.py`, `deploy/migrations/0005_history.sql`, `deploy/migrations/0006_pr_feedback.sql`, `scripts/history_import.py`, `tests/workflow/test_history.py`, `tests/workflow/test_history_integration.py`, `tests/scripts/test_history_import.py` |
| 4.1 | The pure guardrails validator (AD-6/7/8/9/24/27): agent payloads are checked against the committed generated `TriageVerdict` schema, every citation resolves against the evidence served this run, suspects come only from the served candidates, `confidence_jev` must be this run's Jev number, and blame-free output carries no author key — all as collected structured issues, never raised; the A2A task view now serves each run's real confidence (unknown → blame-free) | `guardrails/validator.py`, `guardrails/citation_check.py`, `guardrails/attribution.py`, `workflow/task_store.py`, `workflow/a2a_server.py`, `workflow/evidence_collection.py`, `pyproject.toml` (pinned `jsonschema`), `tests/guardrails/`, `tests/workflow/test_task_store.py`, `tests/workflow/test_task_server.py` |
| 6.1 | Central model-call audit (AD-18): every model/Jev invocation becomes its own attempt-level `run_step` row with the model, its token counters (NULL when the provider did not report them, never 0), status and a closed outcome; usage returned by a failed call is still saved, a crash saves nothing (nothing is invented), attempt rows never move run state, and every invocation logs one structured, secret-free JSON line | `contracts/usage.py`, `workflow/usage_audit.py`, `workflow/service_log.py`, `deploy/migrations/0007_run_step_audit.sql`, `tests/contracts/test_usage.py`, `tests/workflow/test_usage_audit.py`, `tests/workflow/test_service_log.py`, `tests/workflow/test_usage_audit_integration.py`; see [Model-call audit](#model-call-audit-story-61) |
| 6.2 | Versioned NULL-aware model costs (AD-18): one provenance-carrying price table (`table_version`, per-model five-type rates each with source URL + retrieved date, the Jev rate NULL + flagged per OQ-3), a pure NULL-aware calculator (an unreported counter, an unpriced model or a Jev-billed call yields a NULL cost plus a flag, never 0; a run total with any incomplete part is NULL with the reasons listed), and the orchestrator-side reader that rolls 6.1's audit rows into per-run costs — computed, never stored | `monitoring/prices.yaml`, `monitoring/pricing.py`, `monitoring/costs.py`, `workflow/usage_costs.py`, `tests/monitoring/`, `tests/workflow/test_usage_costs.py`, `tests/workflow/test_usage_costs_integration.py`; see [Model costs](#model-costs-story-62) |
| 2.8 | The shared step runner (AD-8, AD-22): one execution policy every agent step goes through — blocking non-streaming A2A `send_message` with `contextId = run_id` and a per-skill timeout, every attempted call audited centrally, one validation retry with the structured errors fed back (a second invalid output pauses with `validation_failed`), at most three transient attempts with config-driven backoff then a terminal `FAILED` with history written once, a definitive error failing without retry, every attempt its own `run_step` row, and the validated output + state move committed atomically under the lease guard | `workflow/step_runner.py`, `workflow/a2a_client.py`, `workflow/runtime_config.py`, `workflow/orchestrator_config.py` + `config/orchestrator.yaml` (retry budget), `guardrails/validator.py` (`validate_classification`), `tests/workflow/test_step_runner.py`, `tests/workflow/test_a2a_client.py`, `tests/workflow/test_runtime_config.py`, `tests/workflow/test_step_runner_integration.py`, `tests/guardrails/test_validator.py`; see [The shared step runner](#the-shared-step-runner-story-28) |
| 4.2 | The deterministic risk gate (AD-13, AD-12, AD-21): one registry entry per rule — skip/disable/xfail a test (incl. test-file deletion), added retries, increased timeouts, loosened assertions, workflow/secret/infra paths, a `dangerous` Reviewer objection, missing base content (fail closed) — evaluated over the proposed diff, the base content of modified files and the Reviewer's objections; returns `normal | blocked | not_gated` with structured reasons, no I/O, no model, and no model-asserted tier can override it; the new path globs live in `guardrails/thresholds.yaml` | `guardrails/risk_gate.py`, `guardrails/thresholds.yaml` (`risk_gate:` globs), `workflow/thresholds.py`, `tests/guardrails/test_risk_gate.py`, `tests/workflow/test_thresholds.py`; see [The risk gate](#the-risk-gate-story-42) |
| 3.1 | The Jev classifier agent served: a stateless A2A service answering `classify-failure` over JSON-RPC — one batched model call carries the five-class `Choice` and the `Noul` injection screen over the delimited distilled log, the reply is the shared `JevResult` (classification + provider-reported usage) matching the generated schema, errors are typed `AgentError` on an A2A `FAILED` task, and the agent holds no GitHub token and no database client | `agents/jev/`, `prompts/jev-classes.yaml`, `contracts/jev.py` (`JevResult`), `contracts/a2a.py`, `guardrails/schemas/JevResult.json`, `jev.test.yaml`, `tests/agents/jev/`; see [The Jev classifier agent](#the-jev-classifier-agent-story-31) |

## Where things live

| Path | Status | Contents |
| --- | --- | --- |
| `contracts/` | built (0.2) | Pydantic v2 models for every inter-agent payload; see [contracts/README.md](../contracts/README.md) |
| `guardrails/schemas/` | built (0.2) | JSON Schemas generated from `contracts/`; never edit by hand |
| `guardrails/thresholds.yaml` | built (2.1, 2.2, 2.5, 4.2) | the one thresholds file (AD-19): `review.max_rounds`, `workflow_path_glob`, the `confidence` cut-offs (`class_cutoff`, `no_route_cutoff`, `injection_screen_cutoff`, `injection_screen_cap`), `distiller.max_bytes`, `evidence.max_history_rows` and the `risk_gate` secret/infra path globs; consumed via `workflow.thresholds.load_thresholds` |
| `guardrails/confidence.py` | built (2.2) | the AD-9 min rule as code: `ClassConfidence`, `RouteConfidence`, `apply_injection_screen`, `below_class_cutoff`, `class_escalation` |
| `guardrails/citation_check.py` | built (4.1) | citation resolution against the evidence served this run (AD-7): `ServedEvidence` (pack + the run's Jev call), the closed per-kind resolution table, `ValidationIssue` (the one issue shape) |
| `guardrails/validator.py` | built (4.1, 2.8) | the pure verdict validator (AD-6/7/8/9/27): `validate_verdict(payload, served, blame_free=…)` → `ValidationResult{verdict, issues}`; two layers (committed JSON schema + pydantic parse) plus the suspect/confidence/attribution checks; `validate_classification(payload)` (2.8, schema + parse only) is the CLASSIFYING surface; see [The guardrails validator](#the-guardrails-validator-story-41) |
| `guardrails/attribution.py` | built (4.1) | the deep `author_login` walk (AD-27), moved from `workflow/task_store.py` (DRY): `strip_author_attribution`, `contains_author_attribution`, `attribution_location` |
| `deploy/compose.yaml` | built (0.3, 1.1) | postgres:18 + one-shot `migrate` job + the real gateway (story 1.1) + orchestrator/agent placeholders, with AD-16 secret placement; see [deploy/README.md](../deploy/README.md) and [Compose and migrations](#compose-and-migrations-story-03) |
| `deploy/migrations/` | built (0.3, 2.1, 1.1, 1.2, 2.3, 2.6, 6.1) | forward-only `.sql` files + naming rules; runner is `workflow/migrate.py`; `0001_triage_run.sql` owns run state, `0002_webhook_delivery.sql` records seen delivery ids for replay dedupe, `0003_triage_run_lease.sql` adds the AD-23 lease columns + claim index, `0004_run_step.sql` adds the AD-2 step record, `0005_history.sql` adds the AD-15 structured-only history table, `0006_pr_feedback.sql` adds the separate post-terminal PR feedback table, `0007_run_step_audit.sql` adds the AD-18 model-call audit columns to `run_step` |
| `scripts/` | built (0.1, 0.2, 0.4, 1.1, 2.1, 2.6) | `bootstrap.sh`, `check_layer_contract.py`, `generate_schemas.py`, `verify_demo_repo.py`, `generate_state_diagram.py`, `history_import.py`; `ruleset-seed.json` payload for the demo-repo ruleset |
| `tests/scripts/` | built (0.4) | unit tests of the demo-repo read-back comparison logic against recorded API fixtures; live `gh` path is `@pytest.mark.integration` |
| `test-data/` | built (0.4) | demo-repo evidence: `demo-repo-expected.json` (AD-16 set, one source for script + docs), `demo-repo.md` (live facts + scenario slots), `demo-repo-seed/` (pushed verbatim to the demo repo) |
| `tests/contracts/` | built (0.2) | contract tests, named after the ACs they prove |
| `tests/workflow/`, `tests/security/` | built (0.3, 2.1, 1.1, 1.2, 2.2, 2.3, 2.4, 2.5, 2.8) | migration-runner and compose secret-placement tests; state-machine, projection and diagram tests; gateway signature/intake/limits tests; lease unit + fencing tests; step unit + atomic-commit/resume/fencing tests; A2A task-view unit + JSON-RPC ASGI tests; distiller AC tests (no I/O); step-runner, A2A-client and runtime-config tests (`@pytest.mark.integration` ones need Docker, `pytest -m integration`) |
| `gateway/` | built (1.1) | webhook intake only — signature, accepted events, load limits, one enqueue; see [gateway/README.md](../gateway/README.md) |
| `workflow/ids.py` | built (1.1) | pure `new_run_id()`: the one UUIDv7 run identity (AD-4) |
| `workflow/leases.py` | built (1.2) | the pure AD-23 policy (claimable states, expiry predicates, owner token) and the small `RunLeaseStore` / connection protocol (SOLID-I) |
| `workflow/lease_store.py` | built (1.2) | the one Postgres adapter for leases: the claim / renew / lease-guarded commit SQL lives here (SOLID-S) |
| `workflow/orchestrator_config.py` | built (1.2) | loader plus sanity checks for the one orchestrator settings file (AD-19); the worker loop that will read it arrives with stories 2.3/2.8 |
| `workflow/steps.py` | built (2.3) | the pure step domain (AD-2, no SQL): `StepStatus`, `StepRecord`, `StepCommit`, `ResumeView` and the small `StepRecorder` protocol |
| `workflow/step_store.py` | built (2.3) | the one Postgres adapter for steps: `PostgresStepRecorder` composes 1.2's lease guard, inserts the step and moves the state in that one transaction (SOLID-S) |
| `contracts/usage.py` | built (6.1) | the pure usage contract (AD-18): `ModelUsage` (model + token counters, NULL = "provider did not report", never 0) and the closed `CallOutcome` set |
| `workflow/usage_audit.py` | built (6.1) | the central model-call audit recorder: `audit_model_call` (the one wrapper around every model call), `ModelCallAttempt`/`ModelCallError`/`ModelCallResult`, the `UsageAuditStore` protocol and `PostgresUsageAuditStore` (insert-only, repo-bound, `call:` step namespace); see [Model-call audit](#model-call-audit-story-61) |
| `workflow/service_log.py` | built (6.1) | the structured invocation-log helper (AD-25): one allowlisted JSON line per invocation, run_id/task_id/step on every line, no channel for tokens, secrets or raw logs |
| `monitoring/prices.yaml` | built (6.2) | the one versioned price table (AD-18, AD-19): `table_version`, per-model five-type `usd_per_mtok` + `source_url` + `retrieved` for both allowed Claude models, and the Jev (`system_one`) rate NULL + flagged (OQ-3) |
| `monitoring/pricing.py` | built (6.2) | the table's one loader: frozen `PriceTable`/`ModelRates`/`JevRate` + `TokenType`, `load_prices()` with sanity checks (version present, all five rates + provenance per model, an unpriced Jev entry stays flagged) |
| `monitoring/costs.py` | built (6.2) | the pure NULL-aware calculator (AD-18, no I/O): `TokenCosts`, `RunCostSummary`, `cost_of_usage(usage, table, *, jev)` and `summarize_costs(...)` — a missing fact is NULL + flag, never 0 |
| `workflow/usage_costs.py` | built (6.2) | the orchestrator-side rollup: the `UsageAuditReader` protocol + `PostgresUsageAuditReader` (repo-bound read of 6.1's `call:` rows) and `run_cost_summary(...)`, which marks `call:system_one` rows Jev-billed and computes via the pure calculator |
| `workflow/task_store.py` | built (2.4, 4.1) | the read-only A2A task view: `RunRecord`, the small `TaskReader` protocol (now including `get_confidence`), `build_task` (2.1's `project` + 2.2's `attribution_allowed`; an unknown confidence is served blame-free) and `ReadOnlyTaskStore`, whose `save`/`delete` refuse (AD-4, SOLID-S/I) |
| `workflow/a2a_server.py` | built (2.4, 4.1) | the A2A transport wiring: `RefusingExecutor` plus `create_app`, which serves `get_task`/`list_tasks` through a2a-sdk 1.1.5's JSON-RPC routes (AD-4, AD-5); each run's serving confidence comes from the reader |
| `workflow/distiller.py` | built (2.5) | the pure AD-20 log distiller: `distill(ci_log, junit_xml, limits) -> list[DistilledLogLine]`, the ordered `ERROR_MARKERS` registry, ANSI/control stripping, JUnit evidence and the UTF-8-safe byte clip; no I/O, model, network or clock (SOLID-S) |
| `config/gateway.yaml` | built (1.1) | per-installation rate limit and per-repo queue-depth cap (AD-19); consumed via `gateway.settings.load_gateway_limits` |
| `config/orchestrator.yaml` | built (1.2, 2.8) | `lease_seconds` / `renew_after_seconds` plus the AD-22 transient-retry budget (`retry.max_attempts`, `retry.backoff_base_seconds`) (AD-19); `workflow.orchestrator_config.load_orchestrator_config` reads it |
| `config/runtime.yaml` | built (2.8) | per-agent model IDs and `step_timeout` (AD-19); `workflow.runtime_config.load_runtime_config` is its one loader (`for_skill` maps the runner's skill names onto the agent keys) |
| `workflow/step_runner.py` | built (2.8) | the shared step runner: `run_step(...)` with the two independent retry budgets (AD-8 validation retry + AD-22 transient ≤3 with backoff), the typed `TransientCallError`/`DefinitiveCallError` pair, `FailedAttempt` + the `AttemptRecorder` protocol and `PostgresAttemptRecorder` (insert-only failed-attempt rows), and the typed `committed`/`paused`/`failed` outcomes; see [The shared step runner](#the-shared-step-runner-story-28) |
| `workflow/a2a_client.py` | built (2.8) | the blocking non-streaming A2A transport adapter (`A2aSkillTransport`): `contextId = run_id`, per-call timeout, and the `AgentError.retryable` → typed-error classification the runner's budgets consume (AD-4, AD-5, AD-22) |
| `deploy/` | partially built (0.3, 1.1) | Compose, gateway image, k8s manifests, migrations (0.3+); k8s manifests + `registry.<env>.yaml` still placeholders |
| `guardrails/risk_gate.py` | built (4.2) | the deterministic risk gate (AD-13): `evaluate_risk(GateInput)` → `GateDecision{risk_tier, reasons}`, the `RISK_RULES` registry (one frozen `RiskRule{code, check}` per rule), `RiskGateConfig` built by the caller from `guardrails/thresholds.yaml`; no I/O, no model; see [The risk gate](#the-risk-gate-story-42) |
| `workflow/` (rest), `agents/` (analyzer, proposer, reviewer), `punch-out/` | placeholder | filled by Epics 2–6; each folder's README says what belongs there |
| `prompts/` (analyzer, proposer, reviewer), `*.test.yaml` (analyzer, proposer, reviewer) | placeholder | agent prompts and their promptfoo evals (Epic 3) |
| `agents/jev/` | built (3.1) | the Jev classifier agent (stateless A2A service): `questions.py` (the batched `Choice`+`Noul` pair, loaded once from the yaml), `classifier.py` (the pure classify step + the AD-22 error split), `provider.py` (`JevProvider` protocol + the typesafe-sdk adapter), `runtime.py` (the jev-key reader of `config/runtime.yaml`), `card.py`/`executor.py`/`server.py` (transport); see [The Jev classifier agent](#the-jev-classifier-agent-story-31) |
| `prompts/jev-classes.yaml` | built (3.1) | the single copy of the five class descriptions + the injection-screen instruction (the Jev agent has no separate `.md` prompt — spine layout) — the served call's instructions come from the yaml (AD-11, AD-19); `jev.test.yaml` holds the promptfoo cases (eval-first; the real eval bar is story 3.2, OQ-1) |

Layer rules (enforced by `scripts/check_layer_contract.py`): `contracts/` imports only stdlib and pydantic; `guardrails/` imports only `contracts/` (+ pydantic and the pinned `jsonschema` that checks payloads against the committed schemas — still no I/O, no GitHub, no Postgres); agents hold no GitHub or Postgres clients; model IDs and timeouts live in YAML; secrets come from environment variables.

## Running things

```bash
bash scripts/bootstrap.sh          # create .venv, install pinned Python and npm tools, verify pins
make check                         # every quality gate; must be green before a story is done
python scripts/generate_schemas.py # regenerate guardrails/schemas/ after changing a contract
python scripts/generate_state_diagram.py # regenerate workflow/STATE_DIAGRAM.md after a table change
python -m gateway                  # run the intake gateway against a migrated database (POST /webhook on :8080)
```

`make check` runs: bootstrap check, layer contract, schema drift, **state-diagram drift**, ruff (check + format), `mypy --strict`, pylint duplicate-code, `pytest --cov` (≥ 85% on `contracts`, `guardrails`, `workflow`). Integration tests that need Docker are marked `@pytest.mark.integration` and excluded from `make check` by default — run them with `make test-integration` (or `.venv/bin/pytest -m integration`). Individual targets are listed in the [Makefile](../Makefile).

## Demo repository (story 0.4)

The real synthetic demo repo is
[`rijojohn85-dev/triage-demo-py`](https://github.com/rijojohn85-dev/triage-demo-py)
(org-owned so AD-16's org `members:read` permission is meaningful). Its
facts — repository/App/installation IDs, ruleset, CODEOWNERS, baseline
tag, S1–S5 scenario slots — are recorded in
[test-data/demo-repo.md](../test-data/demo-repo.md); the seed material that
recreates it lives in [test-data/demo-repo-seed/](../test-data/demo-repo-seed/).

- **Expected permissions** have one source: [test-data/demo-repo-expected.json](../test-data/demo-repo-expected.json). `scripts/verify_demo_repo.py` (AC4) reads it and diffs the live `gh api` responses; [AD-16](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md) is cited, not restated.
- **Ruleset** is a repository ruleset (not legacy branch protection) built from `scripts/ruleset-seed.json`: 1 approval + code-owner review, force-push/deletion blocked, `bypass_actors: []` so the App can never bypass.
- **Not GitHub-enforced:** writes being restricted to `refs/heads/triage/*` + draft PRs is enforced in code by the E4 GitHub adapter (AD-3, AD-16); the ruleset covers the default branch only.
- **Tests**: `tests/scripts/test_verify_demo_repo.py` unit-tests the comparison logic against recorded fixtures; the live `gh` path is `@pytest.mark.integration` (`python scripts/verify_demo_repo.py --org … --repo …` runs it ad hoc).

Run the read-back:

```bash
.venv/bin/python scripts/verify_demo_repo.py \
  --org rijojohn85-dev --repo triage-demo-py \
  --app-id 5073639 --installation-id 164804973 --ruleset-id 23997553
```

## Compose and migrations (story 0.3)

The local runtime is `deploy/compose.yaml` (run from the repo root):

```bash
docker compose --project-directory . -f deploy/compose.yaml up -d --wait     # postgres + migration job (+ placeholders)
docker compose --project-directory . -f deploy/compose.yaml run --rm migrate # re-apply pending migrations
docker compose --project-directory . -f deploy/compose.yaml down -v          # stop and drop data
```

- **Postgres 18** with a `pg_isready` healthcheck; data in the named `pgdata` volume (postgres:18 keeps its data at `/var/lib/postgresql`; see the image notes).
- **Migrations** are forward-only `.sql` files in `deploy/migrations/`, applied in filename order by `workflow/migrate.py` ([AD-25](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md)). No Alembic/SQLAlchemy, no advisory lock, no new dependencies. Each file commits atomically together with its `schema_migrations` row; a failing file rolls back completely, exits non-zero, and the `service_completed_successfully` dependency keeps all workers from starting on a broken schema. Re-running applies nothing new (idempotent).
- **Secrets** come from `.env` (names in `.env.example`); [deploy/README.md](../deploy/README.md) links the scope rules. The placement contract is tested (AD-16): key scoping gateway/orchestrator, Claude agents-, Jev/orchestrator-only.
- **Jev via OpenRouter:** Jev is called with the pinned `typesafe-sdk` pointed at OpenRouter. `TYPESAFE_API_KEY` holds an OpenRouter key; `TYPESAFE_BASE_URL` (non-secret, Compose default `https://openrouter.ai/api`) sits only next to that key, on `jev` and `orchestrator`. The SDK appends `/v1/systemone`, so the call shape of [AD-11](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md) and `Choice.confidence` of AD-9 are unchanged. The model ID is `jev.model` in `config/runtime.yaml` (`typesafe/jev-1.13`). Without the base URL the SDK falls back to `api.typesafe.ai`, where the OpenRouter key fails, so `tests/security/test_compose_secret_placement.py` guards the default.
- **Worker services:** the gateway is real since story 1.1 (`deploy/gateway.Dockerfile`, `python -m gateway`); the orchestrator and agents are still busybox placeholders. The AD-16 env names are in place and the migration gating is live.
- **Connection strings:** the migrate job builds its DSN from `POSTGRES_*` names inside the compose network; host-side tools use `DATABASE_URL` from `.env`.

## Gateway intake (story 1.1)

When CI fails, GitHub sends the gateway a `workflow_run` webhook. The gateway's
only job is to prove the message is real, collapse repetition, shed floods,
and hand on exactly one piece of work (AD-17).

**The signature comes first.** GitHub signs the exact bytes it sent using a
shared secret. The gateway recomputes that signature over the raw body and
compares it in constant time. If it is missing or wrong there is no parse and
the answer is `401`, so a forged message can never become work. The check
takes a *tuple* of secrets, so webhook-secret rotation (AD-25) works with no
change here — `GITHUB_WEBHOOK_SECRET` may hold two comma-separated secrets and
either is accepted during the overlap.

**Only one event matters.** A message enqueues only when the event is
`workflow_run`, its action is `completed` and its conclusion is `failure`.
Everything else — including `issue_comment` (the `/triage` command, out of
scope for now) — is acknowledged and ignored. A signed message from an
installation id we do not know is refused with no downstream call.

**Then the limits.** A per-installation rate limit (messages per time window)
and a per-repo cap on how many runs may already be waiting stop a burst from
becoming work. Both numbers live only in `config/gateway.yaml` (AD-19), never
in code. The queue-depth cap is a *soft* cap: the depth is read, then the run
is inserted, in two statements, so two requests racing the same last slot can
push the depth over by one. That is fine for shed-load; make it exact inside
the insert transaction if it ever must be.

**The store calls run off the event loop.** Reading the queue depth and
writing the run are blocking Postgres calls, so `handle` runs them through
`run_in_threadpool`. The event loop stays free to serve other requests (and to
return a pending `429`) instead of stalling behind one query. The pure checks —
signature, installation, event, rate limit — stay on the loop, so the
in-memory rate limiter is never touched by two threads at once.

**Then one insert.** A message that passes everything is written as a single
`triage_run` in `RECEIVED` and answered `202`. Repetition collapses two ways:
a replayed `X-GitHub-Delivery` is a `2xx` no-op (seen ids are kept in
`webhook_delivery`), and a new delivery id that still names the same
`(repo, workflow_run, run_attempt)` creates no second run — the unique
constraint does that. Delivery record and run row commit in one transaction,
so a crash leaves neither half behind. The run id is a UUIDv7
(`workflow/ids.py`): a millisecond timestamp first, so ids sort by time and
keep the database index tidy.

**What it deliberately is not:** no state-machine logic, and no LLM or GitHub
call — enqueueing `RECEIVED` is the only write (AD-1, AD-17). The layer check
fails the build if `gateway/` ever imports an LLM or GitHub client. The limits
are in-process, which is correct for the one gateway under Compose v1
(AD-25): the rate limiter's counter is per process, so running N uvicorn
workers multiplies the effective limit by N. A future multi-replica gateway
must move the counters to a shared store.

**To extend it:** a new accepted event is one new entry in the registry in
`gateway/events.py`, not a new branch; a new limit is a new field in
`config/gateway.yaml` plus `GatewayLimits`. The run identity is generated by
one factory (`workflow/ids.py::new_run_id`) that later stories reuse.

## Worker leases and fencing (story 1.2)

After the gateway queues a failed run, a pool of workers picks runs up. Two
workers must never run the same long model call, and a worker that has been
replaced must not write down a result it is no longer entitled to give. A
**lease** is how the database records which worker currently owns a run. The
rules are [AD-23](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md)
and [AD-2](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md).

- **Taking a run is one quick, all-or-nothing step.** A worker asks for the
  next run that is not finished and is either unclaimed or whose lease has run
  out. A run that is waiting for a person (`AWAITING_APPROVAL`) is never
  offered: it has no worker work until a human decides (AD-1), so a pile of
  paused runs cannot starve new work by occupying every worker. In one small
  database transaction a worker takes exactly one eligible row
  (`SELECT … FOR UPDATE SKIP LOCKED`) and stamps its own owner name and an
  expiry time, then that transaction finishes *before* any slow work starts.
  Other workers skip a row that is already taken; "SKIP LOCKED" means they do
  not wait in line for it, they just move on to the next run. Because each
  worker takes one row at a time, the number of workers is the concurrency cap.
- **The expiry makes a crashed worker harmless.** A worker that dies mid-run
  cannot hand its lease back, so the lease simply runs out. After that the run
  is claimable again by any worker — nobody has to unlock anything by hand. A
  step that runs long can ask to **renew** first (push its own expiry further
  out), but only while it still owns the lease and the lease has not already
  expired.
- **A replaced worker's result is thrown away.** Before a worker writes a
  step's output and moves the run on, it checks again, inside that same
  transaction, that it still owns the lease (`FOR UPDATE`). If another worker
  has taken the run in the meantime, the whole write is rolled back and the
  worker gets a `LeaseLost` error. That error is final — not something to retry
  — because the run belongs to someone else now. This is the "fence": the old
  worker cannot overwrite the new owner's progress. The door for step output
  arrives with the step story (2.3); this story supplies the guard it composes.

**Where the numbers live.** How long a lease lasts and when to renew come only
from `config/orchestrator.yaml` (AD-19). The loader
`workflow/orchestrator_config.py` checks the two values make sense (a positive
lease, and a renew point before the lease ends); the worker loop that will
read them arrives with stories 2.3/2.8. The Postgres SQL lives on its own in
`workflow/lease_store.py`, so the policy in `workflow/leases.py` stays free of
database code. Lease validity uses the *database's* clock: the claim and the
renew anchor the new expiry to `now()` and compare against `now()`, so two
workers whose local clocks disagree can never treat a live lease as expired.
The small pure helpers (`lease_expired`, `renew_due`) still take a `now` so a
worker can decide *when* to renew from its own clock; the database always has
the final say on whether a lease is valid.

The owner name is made by one factory, `workflow/leases.py::new_lease_owner`.
It takes the worker's name from the `WORKER_ID` environment variable (name
only in `.env.example`) and adds a random suffix, so each claim is unique and
a restarted worker can never be mistaken for the one before it. `RunLeaseStore`
is the small interface the worker loop will use; the one real implementation
talks to Postgres, and the tests drive it through a fake. Because the database
owns lease validity, no test has to sleep.

**To extend it:** a new claimable-state rule is a change in the state machine —
the claimable set is worked out as *all states minus the terminal ones and the
human-wait states*, never
a hand-written list — so it flows through here with no edit. `workflow/leases.py`
and its adapter `workflow/lease_store.py` stand alone; the worker loop itself
arrives with stories 2.3/2.8.

## Signed tunnel smoke test (story 1.3)

Story 1.1 proved rotation and signature checks as pure/unit behaviour.
`tests/security/test_gateway_signature.py::TestRotationLifecycle` now also
drives the full old-only → overlap → retired lifecycle through the real app
with fakes (AC2), with no change to `signature.py` or `settings.py` — the
existing secret-tuple contract already carries the whole lifecycle. Story
1.3 adds the other half: proof that a *real* signed delivery, through the
actual smee tunnel and Compose stack, reaches the gateway and enqueues
exactly once (AC1).

`scripts/smoke_signed_tunnel.py` is the repeatable script for that. It is
split the same way every I/O script in this repo is: a pure `build_receipt()`
(unit-tested; it takes only status/run_id/delivery_id, so it structurally
cannot leak a secret) and an I/O `main()` that triggers a failing run in the
demo repo via `gh workflow run`, polls Postgres for exactly one matching
`webhook_delivery` + `triage_run` row, and writes the receipt. `main()`
reads `DATABASE_URL` from `.env` itself — never a CLI argument, never
printed (AD-16).

Run it (Compose + smee tunnel already up, `.env` populated, per the
USER-GUIDE rotation section above):

```bash
.venv/bin/python scripts/smoke_signed_tunnel.py \
  --org rijojohn85-dev --repo triage-demo-py --repo-id 1387450356
```

The default `--ref main` dispatches against today's green baseline (see
`test-data/demo-repo.md`: `last_green` with scenario branches S1–S5 still
`PENDING`). The gateway only enqueues a `triage_run` for a `workflow_run`
whose `conclusion` is `failure` (`gateway/events.py`), so a run against the
current `main` completes successfully, nothing gets enqueued, and
`poll_for_single_delivery` always times out with `SMOKE FAIL: timed out
waiting...` — that failure means the target ref is green, not that the
tunnel/gateway path is broken. Point `--ref` at a branch arranged to end in
failure (a scratch branch with a broken commit, or a populated S1–S5
scenario branch once available) to exercise the real AC1 path end to end.

Receipts land under `deploy/smoke/` (gitignored except its README — a
script artifact, not a DB-table export, so it gets its own dir rather than
reusing `runs/`/`results/`). The live path is
`tests/scripts/test_smoke_signed_tunnel.py::test_ac1_live_smoke_run_enqueues_exactly_one_triage_run`,
marked `@pytest.mark.integration` so `make check` stays offline; run it with
`.venv/bin/pytest tests/scripts/test_smoke_signed_tunnel.py -m integration`.

## Steps and resume (story 2.3)

A triage run is a series of steps: distil the log, classify the failure, analyze
it, and so on. Each step can call a slow model, so the run must survive a worker
that dies in the middle. Two things make that safe, and both are
[AD-2](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md).

- **A finished step is written down.** A `run_step` row records what the step
  was, which attempt it was, whether it finished or failed, its output, and
  which repo it belongs to. A failed attempt is its own row, never a silent
  skip (AD-22). Only the fields needed today are there: model/token/cost
  columns wait for stories 6.1/6.2 (AD-18), and evidence-pack fields for 2.7.
- **The step and the run's move are one write.** The same database transaction
  that inserts the step row also moves the run to its next state, and it does
  both only if the worker still owns the run's lease. Because the two happen
  together, a crash between them is impossible: either both are there, or
  neither is. The move must be a row in story 2.1's one transition table; an
  invented move changes nothing and raises `IllegalTransition`.

**Resuming.** When a worker dies, its lease simply runs out and another worker
claims the same run (story 1.2). Before doing any step, that worker calls
`resume(run_id, repo_id)` on the recorder. It gets back two things: the run's
**current state** and the **names of the steps already completed**. So it
re-enters the state it was in and skips anything already done, instead of
paying for the same model call twice. The database's unique key on
`(run_id, step, attempt)` is the last line of defence: even if two workers ever
tried the same step, only one row can exist.

**Throwing away a replaced worker's result.** If another worker has taken the
run by the time the old one tries to write, the write is refused and the old
worker gets `LeaseLost`; neither the step row nor the state move persists, and
the discarded result never appears as an accepted step or in a later resume.

**Where the code lives.** `workflow/steps.py` holds only the plain types
(`StepStatus`, `StepRecord`, `StepCommit`, `ResumeView`) and the small
`StepRecorder` interface a worker loop uses — it has no database code.
`workflow/step_store.py` holds the one real implementation,
`PostgresStepRecorder`, and the SQL. That implementation does no fencing of
its own — it hands the work to story 1.2's lease-guarded commit, so the lease
check and the transaction boundary exist in exactly one place. Every read and
write binds `repo_id`, so one repo can never see another's steps (AD-15). The
unit tests use the real recorder, driving it through a fake connection and a
fake lease store; the real database path is the marked integration tests.

**To extend it:** a new persisted field on a step is a new forward migration
(AD-25) plus the matching field on `StepRecord`/`StepCommit`. Resume works from
the rows that exist, never from a stored list of steps, so adding one does not
change how a run is resumed.

## History & PR feedback (story 2.6)

**What `history` stores.** A durable, tenant-scoped record of past triage
outcomes ([AD-15](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md)),
so a later run can ask "have we seen this failure before?" without ever
inventing an answer. Every row holds only enumerated/structured fields —
`test_id`, `error_type`, `top_stack_frames` (an array of short location
strings, never narrative), a sha256 `fingerprint` of those three normalized
and joined, the `terminal_state` the run ended in, and an optional
`human_verdict`. There is no free-text column, on purpose: this table feeds
agent evidence packs later (story 2.7), and free text is exactly what AD-20
keeps out of that path.

**Who writes it.** Only the orchestrator, through `HistoryStore`, and only
once a run is terminal. `write_terminal` refuses — before touching the
database — any `RunState` outside `TERMINAL_RUN_STATES`
(`workflow/run_states.py`), raising `NonTerminalWriteError`. Calling it twice
for the same `run_id` is not an error: the database's `uq_history_run_id`
unique constraint catches the second insert, and the store re-selects and
returns the same row instead of writing a duplicate — no lease is needed
here, because a terminal run can no longer be claimed
(`CLAIMABLE_RUN_STATES` in `workflow/leases.py` already excludes
`TERMINAL_RUN_STATES`). Agents never get a `HistoryStore` — there is no
agent-facing writer, only the read-only `HistoryRow` subset served in the
evidence pack (`contracts/evidence.py`).

**Every read and write binds `repo_id`.** `lookup(repo_id, fingerprint, limit)`
never returns another tenant's row, even for a fingerprint that collides
with one seeded under a different repo.

**Seed history** enters through exactly one door: `scripts/history_import.py`,
a CLI that reads a JSON array (file or stdin), builds one
`workflow.history.ImportRecord` per row and calls `HistoryStore.import_seed`.
`ImportRecord` is a frozen dataclass of enumerated fields only — a row with
an extra key (e.g. `notes`) raises `TypeError` before any row is written, so
a free-text seed can never slip in. Each seed row gets a fresh `run_id` via
`workflow.ids.new_run_id()` (the same UUIDv7 scheme real runs use), since
seed/backfilled history has no real `triage_run` behind it.

**`pr_feedback` stays separate on purpose.** Human feedback left on an
opened PR is free text by nature, so it lives in its own table
(`workflow/pr_feedback.py` / `workflow/pr_feedback_store.py`), written by a
different store with no shared code path into `history`. `feedback_text`
can never become a `history` row.

**Where the code lives.** `workflow/history.py` holds the pure domain:
`normalize_fingerprint` (sha256 of the stripped fields, joined by `\x1f`, no
I/O), `HumanVerdict`, `HistoryEntry` (the internal full-row type — distinct
from the agent-facing `contracts.evidence.HistoryRow`), `ImportRecord`,
`TerminalWrite` and `NonTerminalWriteError`. `workflow/history_store.py`
holds the one Postgres adapter, `PostgresHistoryStore`, mirroring
`workflow/step_store.py`'s injectable-`connect` pattern. Migrations:
`deploy/migrations/0005_history.sql`, `deploy/migrations/0006_pr_feedback.sql`.

## The A2A task view (story 2.4)

A client (a person's tool, or another service) asks "what is happening with
this run?" through A2A. The answer must be the same before and after a pause,
and it must never become a second place where run state is kept. That second
copy is the thing [AD-4](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md)
forbids, so this story is a **read-only mirror** of the run.

- **The task is the run, mirrored.** The task's id is the run's id (`run_id`,
  the UUIDv7 from story 1.1). Its status and its `terminal_state` come from
  story 2.1's one mapping (`workflow/projection.py::project`) — the same table
  the rest of the system trusts — and its artifacts are read straight from the
  stored `run_step` outputs (story 2.3). Nothing is computed twice and nothing
  new is stored.
- **The SDK's own database store is not deployed.** a2a-sdk ships a task store
  that keeps tasks in its own database tables. Wiring it in would create a
  second owner of run state that could drift from `triage_run`. Instead,
  `ReadOnlyTaskStore` puts a thin read-only layer over `triage_run`/`run_step`:
  `get` and `list` project through the small `TaskReader`; `save` and `delete`
  raise `ReadOnlyTaskStoreError` (not retryable, AD-22). A read can therefore
  never write anything.
- **A paused run shows the evidence, blame-free.** When a run waits for a
  human (`AWAITING_APPROVAL`), fetching it answers `INPUT_REQUIRED` and carries
  the stored evidence pack as an artifact, so the person can decide without the
  run doing any work. Because the run is paused (and again while it is
  `REPORTING`), the AD-27 rule says output must not name anyone: the author
  field is dropped from every artifact. This story serves only that state half
  of the blame rule. The other half — a run whose confidence is under the
  cut-off — needs the run's confidence, which is not stored yet, so story 4.1
  will add it to the reader. Both halves go through story 2.2's one
  `attribution_allowed`, so the rule still has a single home. A read never asks
  a worker to start.
- **Unknown and other-repo ids show nothing.** Every read is bound to the
  adapter's configured `repo_id` (AD-15); a run under another repo looks exactly
  like a run that does not exist — `None`, which the A2A layer turns into a
  not-found error. Today that repo scope is the single demo deployment; proper
  per-user identity arrives with story 5.1.

**Where the code lives.** `workflow/task_store.py` holds the read shapes and
the projection (`RunRecord`, `TaskReader`, `build_task`, `ReadOnlyTaskStore`) —
it builds no SQL, so the future Postgres reader can live in its own adapter
module. `workflow/a2a_server.py` is only transport: it wires the read-only
store and a `RefusingExecutor` (which refuses to run any agent work) into
a2a-sdk's `DefaultRequestHandler`, then exposes the JSON-RPC binding with
`create_jsonrpc_routes`. The unit tests fake the reader and drive the real
store; the server test drives the real app in-process over an ASGI transport.
`create_app` reads the confidence cut-offs from the one thresholds file
(AD-19).

**To extend it:** a new artifact is a new kind of step output — a new
`run_step` row — never a new writer or a new task-state table. A new state
flows in automatically because the status mapping is story 2.1's table, not a
list kept here. The confidence-below-cut-off half of the blame rule is not
served yet because the run's confidence is not stored; story 4.1 will add it to
the reader, and the shared `attribution_allowed` predicate is already in place
here, so the strip follows with no second copy of the rule.

## Distilling CI logs (story 2.5)

A failed CI run produces a huge wall of text that no one wrote for us. Two
things are true about it, and both are
[AD-20](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md):
a model must never be shown the raw text, and the only part worth keeping is
the error evidence. `workflow/distiller.py` turns that wall into a short,
numbered list of lines. The shape is `contracts.evidence.DistilledLogLine`
(AD-24), and the numbers are the `log_line` anchors the citation rules point
at (AD-7).

**What counts as evidence.** The distiller keeps two kinds of line:

- lines from the raw CI text that match an **error marker** — a Python
  `Traceback (most recent call last):`, a `File "…", line N` frame, an
  `ERROR:`/`FAILED`/`panic:` line, a pytest `E   …` assertion line, and so on
  — plus the indented lines that continue such a block;
- the `<failure>` and `<error>` parts of a JUnit XML report: one line naming
  the failing test, then its stack text.

Everything else — progress chatter, timings, the story before the error — is
thrown away. The JUnit lines come first in the numbered list: they are the
parsed, structured signal, so when the byte bound is reached it is the raw CI
text that is trimmed first, never the JUnit evidence. But the lines that are
kept are still untrusted. An error marker
line, a line indented under one, and the fallback line can all hold text an
attacker wrote. The request builder must pass the kept lines to a model only
as clearly separated untrusted data, never as instructions (AD-20).

**ANSI and control characters.** Terminals colour their output with escape
codes. The distiller removes those codes, and removes non-printing control
characters (`\r`, `\b`, NUL, and the rest) while leaving the text itself
alone. Tabs and newlines stay.

**Numbering and the byte bound.** Kept lines are numbered from 1 through
`DistilledLogLine.line_number`; the numbers are their citation anchors, so
once a line has a number it keeps it. The total kept text is clipped to
`distiller.max_bytes`, which lives only in
[`guardrails/thresholds.yaml`](../guardrails/thresholds.yaml) and is read
through the one loader (`workflow/thresholds.py`, AD-19). An overlong line is
cut at a full character — never in the middle of a multi-byte letter — and
once the bound is reached the later lines are dropped, so nothing is
renumbered. The byte bound counts the kept evidence text; the small number
labels are not counted. Today the bound is a marked placeholder, like the
confidence cut-offs (OQ-2).

**Two deliberate edges.** JUnit XML is untrusted: a document that declares a
DOCTYPE or an entity is skipped whole, so a "billion laughs" expansion can
never run (AD-20). And when there is no error marker and no JUnit evidence at
all, the distiller keeps the last non-empty line (or a single empty line for
an empty log), so the evidence pack always has at least one line, as its
contract requires.

**Where the code lives.** `workflow/distiller.py` is a pure text transform
(SOLID-S): it takes the text and the bound in, and returns contract types; it
has no I/O, no model, no network and no clock, so the same input always gives
the same output. The JUnit XML is read with the standard library
(`xml.etree.ElementTree`), so no new dependency is needed.
`workflow/thresholds.py` owns the bound's shape (`DistillerLimits`) and the
one loader.

**To extend it:** a new CI error style is one new entry in `ERROR_MARKERS`,
never a new branch. To change the byte bound, change it only in
`guardrails/thresholds.yaml`. The distiller builds no SQL and no HTTP, so
another consumer (the evidence-pack builder, story 2.7) can reuse the same
numbered lines without any change here.

## Contracts (story 0.2)

One model family per module in `contracts/`: `enums`, `citations`, `verdict`, `evidence`, `objections`, `errors`, `approval`, `a2a`. All models forbid unknown fields.

| Model | Filled in by | Purpose |
| --- | --- | --- |
| `EvidencePack` | orchestrator (no AI) | the facts for a run: numbered distilled log, commits since last green, candidate suspects, history rows, metrics (AD-24) |
| `Citation` (5 kinds) | agents | proof pointing into the evidence pack: `log_line`, `commit`, `metric`, `history_row`, `jev_signal` (AD-7) |
| `Cap` | agents | lowers confidence with a cited reason; confidence = `min(confidence_jev, caps…)` (AD-9) |
| `Suspect` | Analyzer | a ranked commit with citations (AD-27) |
| `Objection` | Reviewer | severity `info`/`minor`/`major`/`dangerous` + claim + citation (AD-12) |
| `AgentError` | any agent | `code`, `message`, `retryable` (AD-22) |
| `TriageVerdict` | orchestrator | the assembled result of a run (AD-6) |
| `DataPart` | both sides | envelope in every A2A data part: `task_id` = `context_id` = `run_id` (AD-4) |

**Adding or changing a contract:** write the failing test in `tests/contracts/` first, change the model, run `python scripts/generate_schemas.py`, commit the regenerated schema with the model. `make check` fails if the two drift apart.

## The state machine (story 2.1)

The orchestrator runs every triage as a life of exactly one record, `triage_run`, whose `state` column says where the run is. The whole story in plain words:

- **There are 14 states** and they are written down once, in `workflow/run_states.py` (`RunState`, [AD-1](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md)). A run is received from the webhook, distills the log, classifies the failure, analyzes it, then either **opens a draft PR** (code fix accepted), **reports** it (infra problem, or a human should apply the change), **pauses for a person** (`AWAITING_APPROVAL`), or **fails**.
- **Every move must be in one table.** `workflow/transitions.py` holds a single list of rows — one row per legal move, saying *from which state, to which state, and under what condition*. If code asks for a move that has no row, or the row's condition is not met, `transition()` raises `IllegalTransition`, which is deliberately non-retryable (an invented move is a bug, not a hiccup, AD-22). Nothing else in the codebase is allowed to decide these moves.
- **Conditions are pure guards** over one frozen `GuardInput` (SOLID-I: one small data bag, no god parameters): the failure class, the risk tier, the review round, the human's approve/reject decision, and a booleans-only `confidence_below_cutoff` (AD-9: the state machine never *computes* confidence — story 2.2 does). Guard thresholds come from `guardrails/thresholds.yaml` (AD-19), never from literals in code.
- **Pauses carry a reason.** `AWAITING_APPROVAL` always has an `escalation_reason` from `contracts.enums.EscalationReason` — and the database enforces it: a run in `AWAITING_APPROVAL` without a reason is rejected by `deploy/migrations/0001_triage_run.sql` CHECK constraints, and vice versa.
- **Failure is always an exit.** Any non-terminal state can go to `FAILED`; those edges are derived from the terminal set in code, not listed by hand (AD-22). Terminal states (`DONE_PR`, `DONE_REPORT`, `REJECTED_BY_HUMAN`, `FAILED`) have no moves out.
- **The diagram is the table's shadow.** `workflow/STATE_DIAGRAM.md` is generated from the table by `scripts/generate_state_diagram.py`, and `make state-diagram-drift` fails if anyone edits either out of sync. A test also parses the spine's AD-1 mermaid block and proves the table's edge set equals it.

**Extending the state machine:** add a state (a new `RunState` member) or an edge = add a row in `workflow/transitions.py` (plus a guard predicate when the edge is conditional), name the guard's sample fields in `GUARD_FIELDS`, write the failing tests first (`tests/workflow/test_transitions.py`, names cite the AC), re-run `python scripts/generate_state_diagram.py`, and commit the regenerated `STATE_DIAGRAM.md` in the same PR ([AD-1](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md), [AD-4](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md)). If the spine's AD-1 diagram disagrees with your row, stop — the spine wins ([AGENTS.md "Sources of truth"](../AGENTS.md)).

**Projection (AD-4):** `workflow/projection.py::project()` is a pure mapping-table from `RunState` to the pair (A2A `TaskState` member name, contract `TerminalState | None`) — `RECEIVED → SUBMITTED`, active states → `WORKING`, `AWAITING_APPROVAL → INPUT_REQUIRED`/`input_required`, the terminal states → `COMPLETED`/`FAILED` with their contract terminal state. a2a-sdk 1.1.5's `TaskState` is a protobuf wrapper, so the projection returns the member *name*; the A2A server story (2.4) converts to the integer at the transport edge.

## Confidence: one trusted number (story 2.2)

**What it is for.** When a CI run fails, a fast checker called Jev guesses what kind of failure it is (code, flaky, infra, external or unknown) and says how sure it is, from 0 to 1. Many parts of the system later ask "how sure are we?". They must all get the same answer, so there is exactly one trusted number. Rules: [AD-9](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md), [AD-11](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md).

**How the number is made.**

- Jev's own score is kept exactly as it arrived and can never be changed (`contracts/jev.py`, `JevChoice`). Jev also sends how likely each other failure type was. We keep that for the record only; nothing ever makes a decision with it.
- Anything that has a reason to trust Jev less can add a **cap**: a lower limit, plus a pointer to the evidence behind it. A cap with no evidence is refused.
- The trusted number is simply **the smallest** of Jev's score and all the caps. It is worked out every time you read it, so nobody can type it in, and adding a cap can only pull it down, never up. This rule is written once, in `contracts/verdict.py` (`effective_confidence`). The final verdict checks itself against the same rule and is refused if its number doesn't match.
- The code for all of this is in `guardrails/confidence.py` (`ClassConfidence`).

**Where caps come from today.** Jev also checks whether the log looks like someone is trying to trick the AI. It answers with a number from 0 to 1. At or above the "trick check" line, we add one cap that points back to that check (`apply_injection_screen`). That is all it does: it never stops a run by itself. If the lower number then falls under the line, the normal "too unsure" check pauses the run, the same as for any other low score.

**The yes/no questions.**

- *Too unsure?* The trusted number is under the failure-type line. Exactly on the line counts as sure enough (`below_class_cutoff`).
- *Pause the run?* Yes if the type is `unknown` or the number is too low (`class_escalation`). If a person has already picked the failure type by hand (a "class override"), these two checks are skipped for the rest of the run. Both numbers stay the same.
- *May we name a person as the likely cause?* No while the run waits for a human, no while it is writing its report, and no while the number is too low. That includes after a hand-picked type, because the number is still low (`workflow/attribution.py`).
- The score used later for picking which helper agent to call is a **different kind of number** (`RouteConfidence`). The checks above refuse it, so the two can't be mixed up.

**Where the lines live.** All lines are in `guardrails/thresholds.yaml` under `confidence:`. Today they are guesses, each marked `ASSUMPTION — OQ-2, not calibrated`. `workflow/thresholds.py` reads that file once. The confidence tests read their own copy, `tests/fixtures/thresholds.test.yaml`, so changing the real numbers never breaks them; one test checks the two files still list the same keys, so the copy can't quietly drift out of shape.

**To add a new reason to trust Jev less:** build a `Cap` with its evidence and add it with `ClassConfidence.with_cap(...)`. Never add a new score field, and never write your own "smallest of" code. **To add a new line:** add it to `guardrails/thresholds.yaml` and to `ConfidenceCutoffs`, never as a number in code.

## The guardrails validator (story 4.1)

Before anything an agent says is believed, it is checked against the facts
this run actually served. The checker is pure code — no database, no network,
no model — in three small modules under `guardrails/` (rules: AD-6, AD-7,
AD-8, AD-9, AD-24, AD-27 of the [architecture spine](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md)).

**What is checked, in plain words:**

- **The shape is right.** The raw payload must match the committed, generated
  JSON schema for a verdict (`guardrails/schemas/TriageVerdict.json` — never
  hand-edited; regenerate it from the contract). A verdict claiming a suspect
  with a shortened commit id, an unknown field, or a made-up failure class
  fails here.
- **Every proof points at evidence this run was shown.** A citation may point
  at a line of the numbered distilled log, a commit between the baseline and
  the failed head, a collected timing metric, a served history row, or one of
  the two answers of this run's Jev call. Anything else — evidence from
  another run or repository — is refused. The facts live in one bag,
  `ServedEvidence` (`guardrails/citation_check.py`): the evidence pack plus
  that run's Jev answer.
- **Blame is only allowed for served suspects.** A named suspect must be one
  of the candidate commits the pack ranked, and must carry both a commit
  citation and a log-line citation.
- **The confidence number is honest.** `confidence_jev` must be exactly this
  run's Jev score — Jev's per-class probabilities are kept for the record
  only and can never be smuggled in as the score. Caps can only pull the
  number down; a verdict whose number doesn't match the smallest-of rule is
  refused (that rule lives in the contract itself, `contracts/verdict.py`).
- **Blame-free output stays name-free.** When the caller says this output is
  blame-free (waiting for a human, writing a report, or the confidence is
  below the line), any `author_login` key anywhere inside the payload is an
  error. The deep scan/strip walk lives once in `guardrails/attribution.py`
  and is shared with the task view.

**What comes back.** `validate_verdict(payload, served, blame_free=…)` never
raises and never stops at the first problem: it returns a `ValidationResult`
with the parsed verdict (or `None`) and **every** issue found, each one a
small structured record — a short `code` (`schema`, `citation_unresolvable`,
`suspect_not_candidate`, `confidence_mismatch`, `attribution_present`), a
human-readable `message`, and a `location` saying exactly where in the
payload the problem is (e.g. `suspects[0].citations[0]`). Two checking layers
feed the same issue shape: the JSON schema layer (shape, enums, patterns) and
the contract parse layer (the rules JSON Schema cannot express, like the
smallest-of rule and the blame-citation rule).

**Who uses it.** The validator only answers questions; it runs no workflow.
Story 2.8's shared step runner will call it after each agent step and decide
what happens next (one retry with the issues fed back, then a pause) — that
policy is deliberately not here (AD-8). The read-only A2A task view now also
serves each run's real confidence, read per run through the small
`TaskReader.get_confidence` protocol method; a run whose confidence cannot be
read is served blame-free, never with names.

**To extend it:** a new citation kind is a new case in the closed resolution
table in `guardrails/citation_check.py` plus its contract model — never a new
`if` scattered elsewhere. A new check is a new pure function in
`guardrails/validator.py` returning the same issue shape. Tests live in
`tests/guardrails/` and name the AC they prove.

Run the focused checks:

```bash
.venv/bin/pytest tests/guardrails tests/workflow/test_task_store.py tests/workflow/test_task_server.py -q
.venv/bin/python scripts/check_layer_contract.py
```

## The risk gate (story 4.2)

Before a proposed fix reaches GitHub, one piece of pure code decides whether
the change looks safe or looks like it is hiding a bug. It is deterministic:
same input, same answer, every time — no model, no database, no network — in
`guardrails/risk_gate.py` (rules: AD-13, AD-12, AD-21 of the
[architecture spine](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md)).

**What it watches, in plain words.** The gate looks at the proposed diff
(what files the fix would change and their new content), the current content
of the files being changed, and any objection the Reviewer raised. Every
path is first put in one canonical form (`./a/b`, `a/../a/b` and
backslash spellings all collapse to `a/b`), so a path cannot dodge the
rules by how it is written; a path that is absolute, still climbs out of
the repo with `..`, or names no file at all is blocked outright
(`unsafe_path` — fail closed). A change is blocked when it:

- **Disables a test.** A new `pytest.mark.skip`/`skipif`/`xfail`, a
  `pytest.skip(...)`, `pytest.importorskip(...)`, a `unittest.skip` or
  `unittest.SkipTest`, `self.skipTest(...)`, the bare `mark.*` forms
  (after `from pytest import mark`), or `pytest.skip.Exception` on a line
  the diff adds — or a whole test file deleted. `skip` inside an unrelated
  name (`skip_header_rows`) never trips it.
- **Adds retries.** Retry machinery on a line the diff adds, matched
  case-insensitively: `retry`/`retries`/`reruns` (including inside
  `max_retries=…`), `.on_exception`, `@backoff.`, `flaky`, `stamina`,
  `tenacity`. A retry that already existed before the fix is not a new one.
- **Raises a timeout.** Compared per changed line, not per file: any
  added timeout value bigger than the value it replaced blocks, a brand-new
  timeout line blocks, and any timeout in a newly added file blocks — so a
  bump cannot hide beside a larger unchanged timeout. The spellings caught
  are case-insensitive and include `TIMEOUT = …`, `set_timeout(…)`,
  `timeout_seconds=`/`timeout_ms=`/`connect_timeout:`, `@pytest.mark.timeout(N)`,
  floats and digit separators (`1_000`), compared numerically. Lowering a
  timeout is fine; the bare word "timeout" without a value is not a hit.
- **Weakens an assertion.** Two ways: a strong check removed while a weak
  check on the same target was added (`assertEqual(tok, …)` →
  `assertIn(tok, …)`, `assert tok == …` → `assert tok in …`, `assertTrue(…)`,
  `assertIsNotNone(…)`, a `pytest.approx` comparison — the target may be a
  dotted or subscripted name like `resp.status` or `data["k"]`); or a test
  file whose changed lines hold net fewer assertion lines than before
  (an outright deletion); or the same target asserted against a different
  expected value (`assert f() == 1` → `assert f() == 2`,
  `assertEqual(total, 5)` → `assertEqual(total, 6)`) — rewriting the test to
  match the current output. Strengthening, pure relocations and comment-only
  edits are fine.
- **Touches protected paths.** Any file under the workflow glob
  (`.github/workflows/**`), a secret path (`.env`, `.env.*`, `*.pem`,
  `*.key`, `*secrets/*`, `*secret.*`, `*secrets.*`, `*credentials*`,
  `*id_rsa*`, `*id_ed25519*`, `*.npmrc`, `*.pypirc`, `*.p12`, `*.pfx`) or an
  infra manifest (`Dockerfile`s, compose files, Terraform files, state
  (`*.tfstate*`) and `terraform/` folders, `k8s*/`/`kubernetes/`,
  `*charts/*`, `*helm/*`, the top-level `deploy/*`). The secret and deploy
  globs are deliberately narrow so `src/secret_scanner.py` or
  `docs/deploy/guide.md` do not pause a run for nothing — the globs live only in `guardrails/thresholds.yaml`
  (AD-19), never in code.
- **Was called dangerous by the Reviewer.** One objection with severity
  `dangerous` blocks even a change that trips no other rule — and even a
  gate run with no diff at all (AD-12: "any `dangerous` objection escalates
  early to `GATING`, which blocks"; AD-13: "also `blocked` if the Reviewer
  marked the change `dangerous`").
- **Hides its starting point.** If a file is being changed but the caller
  did not supply what the file looked like before, the change is blocked
  (`prior_content_missing`) — gating must never be silently skipped. This
  is the fail-closed rule.

**Known gaps.** The content rules are deliberately conservative pattern
tripwires, not a semantic reviewer: they can over-block (a comment
mentioning `flaky` trips the retry rule — the fail-safe direction) and a
few exotic spellings may still slip past; the red-team story (4.6) owns
widening with fixtures.

**What comes back.** `evaluate_risk(GateInput)` returns a `GateDecision`:
`not_gated` when there is no diff to judge (unless a `dangerous` Reviewer
objection stands — that blocks), `blocked` with **every** reason
collected when any rule trips, `normal` otherwise. Each reason is a small
structured record — the rule's `code`, a human-readable `message` and the
`location` (the file path, or `objections[0]` for a Reviewer objection).
The gate takes no model-asserted risk tier as input: it recomputes from the
diff, so a verdict claiming `normal` cannot override it — that
override-impossibility is structural (there is no input to lie through),
not a check. Quarantine recommendations are metadata only and are never a
gate input or a block reason (AD-21).

**Who uses it.** The gate only answers questions; it runs no workflow. The
actual `AWAITING_APPROVAL(gate_blocked)` pause lands with the workflow
integration story; the transition guards
(`workflow/transitions.py:gate_allows_pr`/`gate_blocks`) already consume the
`risk_tier` the gate returns. The caller builds the `RiskGateConfig` (the
path globs) from `guardrails/thresholds.yaml` via `workflow.thresholds` —
guardrails itself does no config I/O.

**To extend it:** a new rule is one new registry entry in `RISK_RULES` (a
frozen `RiskRule{code, check}`) plus its positive and negative fixtures in
`tests/guardrails/test_risk_gate.py` — the registry-driven tests fail if a
rule lands without fixtures. Never a new `if/elif` scattered elsewhere.

Run the focused checks:

```bash
.venv/bin/pytest tests/guardrails/test_risk_gate.py tests/workflow/test_thresholds.py -q
.venv/bin/python scripts/check_layer_contract.py
```

## Deterministic evidence collection (story 2.7)

The worker can now build and save one pack of facts for a failed run. The
rules are linked in the [architecture spine](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md)
(AD-7, AD-15, AD-16, AD-20, AD-24, AD-27).

- `workflow/evidence.py` chooses the latest earlier successful run of the same
  workflow and branch, or the repository's default-branch head. It ranks only
  commits whose files overlap stack frames or direct test imports: most
  overlapping files first, then full SHA to break ties.
- `workflow/github_evidence.py::GitHubEvidenceReader` reads the task's repository
  and failed attempt, follows all pages, and compares against that attempt's
  fixed head. Past successful runs are listed for the failing workflow only
  (`/actions/workflows/{workflow_id}/runs`), so a busy branch with many
  workflows does not multiply GitHub reads. It reads each commit's files, job logs and actual job durations.
  Python test imports are resolved against files in that head's tree. Linux
  and Windows runner checkout paths are made relative to the task repository;
  traversal paths are refused. Comparison endpoints, job attempts and each
  tree/source locator are checked, and source bytes must match the expected
  Git blob. No
  dependency graph is involved. Incomplete trees or comparison ranges are
  refused. The injected request boundary returns `GitHubResponse`; `has_next`
  must reflect GitHub's next-page link. It must handle log download redirects
  without forwarding the installation token outside `api.github.com`.
- `workflow/evidence_collection.py::EvidenceCollector.collect_and_persist`
  takes a `CollectionRequest` containing the accepted `RunIdentity`, worker
  claim and failure fields for history lookup. Inject the reader, a token
  issuer, `PostgresHistoryStore`, `PostgresStepRecorder` and
  `load_thresholds().evidence` (the log byte cap plus
  `evidence.max_history_rows`). The token issuer's `mint(installation_id,
  repo_id)` is called once per collection. The collector trims and numbers
  logs, looks up matching history in that repository (only the newest
  `evidence.max_history_rows` rows, so a failure that keeps recurring cannot
  grow every agent's context without limit), and saves the pack as
  the `distill` step while moving `DISTILLING` to `CLASSIFYING` through the
  existing guarded transaction. `StepCommit.task_identity` carries the task's
  repository, workflow run and attempt; the recorder checks these against the
  leased database row inside that transaction before writing anything. Existing
  callers may omit this optional field. A mismatched task, stale claim or
  failed write returns no pack.
- `agent_context(pack)` puts the saved facts inside an escaped
  `<untrusted_evidence>` block. Instructions belong outside it. It reuses
  `guardrails/attribution.py::strip_author_attribution` (the one deep
  author-key walk, shared with the task view and the validator); the task view
  continues to apply the existing rule about when authors may be shown.

The callable collection entrypoint is available for worker wiring. There is
no new command, background worker, live token issuer or specialist-agent
connection in this story. Raw logs and tokens are neither step output nor
agent context. No GitHub writes occur. Empty comparisons produce empty commit
and candidate lists, and missing timing measurements produce no metric.

GitHub API shapes and pagination were checked against the official
[commit documentation](https://docs.github.com/en/rest/commits/commits),
[workflow-run documentation](https://docs.github.com/en/rest/actions/workflow-runs)
and [workflow-job documentation](https://docs.github.com/en/rest/actions/workflow-jobs).

Run the focused checks:

```bash
.venv/bin/pytest tests/workflow/test_evidence.py tests/workflow/test_github_evidence.py tests/workflow/test_evidence_scope.py tests/workflow/test_evidence_collection.py tests/workflow/test_evidence_identity.py tests/contracts/test_evidence.py -q
.venv/bin/pytest -m integration tests/workflow/test_evidence_integration.py -q
make check
```

The marked checks use real Postgres 18 through disposable Docker containers.
They prove the pack and state move commit together, a database fault rolls
both back, a replaced worker cannot save its pack, and evidence for a different
workflow run cannot be attached to the leased run.

The same marked test file includes a real GitHub read. To enable it, set
`TRIAGE_EVIDENCE_INSTALLATION_ID`, `TRIAGE_EVIDENCE_REPO_ID`,
`TRIAGE_EVIDENCE_WORKFLOW_RUN_ID`, `TRIAGE_EVIDENCE_RUN_ATTEMPT` and
`TRIAGE_EVIDENCE_INSTALLATION_TOKEN` in the test process environment. Use a
failed attempt with available logs and a token authorized for that repository.
Keep the token outside the repository. Without all five values, the GitHub
check explicitly skips; a skip is not a successful live read.

## The shared step runner (story 2.8)

Every agent step — classify, analyze, propose, review — now goes through one
piece of code that decides how a step is tried, retried, paused and written
down. Before this story each caller would have had to invent that policy
itself; now it is written once, in
[`workflow/step_runner.py`](../workflow/step_runner.py). The rules are linked
in the [architecture spine](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md)
(AD-1, AD-2, AD-8, AD-18, AD-19, AD-22, AD-23).

**What one step looks like.** The runner asks the agent for an answer (one
blocking call, no streaming), checks the answer against the facts of this
run, and then either accepts it and moves the run on, asks the agent again,
stops and waits for a person, or gives up and marks the run failed. Three
plain rules drive everything:

- **A wrong answer gets one second chance.** If the answer fails the checks,
  the runner sends the exact list of problems back to the agent and tries
  once more. If the second answer is also wrong, the run stops and waits for
  a human, carrying the reason `validation_failed`. A wrong answer is never
  written down as if it were a good one.
- **A hiccup gets at most three tries.** Network trouble, "too busy"
  answers, server errors and timeouts are all hiccups: the runner waits a
  little longer between each try (the wait grows each time) and gives up for
  good after three failed tries, marking the run failed and writing the
  failure into history exactly once. A *definitive* error — one the agent
  says must not be retried — gives up immediately.
- **Every try is written down.** Each attempt, good or bad, gets its own
  row, numbered in order, so the run's history shows exactly what was tried
  and what happened. The two rules above keep separate count: a wrong answer
  does not use up a hiccup try, and vice versa.

**Who records what.** Two kinds of row are written per attempt. The audit
row (`call:<skill>`, story 6.1) says which model was called and what it
cost in tokens — written for every attempted call, success or failure. The
plain row (the step's own name) records the attempt's outcome; a failed
attempt that doesn't move the run is inserted on its own
(`PostgresAttemptRecorder`), while the attempt that ends the step (accepted,
paused, or finally failed) is written in the same lease-guarded transaction
that moves the run's state — so output and state always change together, and
a worker that lost its run in the meantime writes nothing (story 1.2's
fence).

**Where the numbers live.** Which model to use and how long to wait for an
answer come from `config/runtime.yaml` (one loader,
`workflow/runtime_config.py`); how many hiccup tries are allowed and how
long the first wait is come from `config/orchestrator.yaml` under `retry:`
(loaded with everything else by `workflow/orchestrator_config.py`). Both are
placeholders today, not calibrated (OQ-2) — change the YAML, never the code.

**How the call travels.** `workflow/a2a_client.py` is the only piece that
speaks the wire: one blocking, non-streaming A2A `send_message` per try,
addressed with `contextId = run_id`, cut off at the per-skill timeout. When
an agent answers "I failed" with its typed error, the adapter turns the
error's "you may retry me" flag into the runner's hiccup/definitive
distinction. It holds no database or GitHub access. Two caller constraints
are deliberate today and revisited by story 2.9's worker wiring: `call` is
for synchronous callers only (it runs a fresh event loop per call, which
raises inside a running one), and it opens a fresh HTTP client per call.

**One known window.** When a step finally fails, the runner writes the
failed attempt row and the `FAILED` state move in one guarded transaction,
and the terminal history row in a second, separate write. A crash between
the two leaves the run failed with history not yet written; the history
write is idempotent per run, so story 2.12's recovery pass completes it
without a duplicate.

**What is deliberately not here yet.** No real agent is wired in — the
runner's transport is a small interface (the seam story 2.9 connects), and
the tests drive it with stand-ins. The caller also supplies, per run, the
identity used for the terminal history write (test id, error type, stack
frames); extracting those from real failures lands with stories 2.9/2.12.

Run the focused checks:

```bash
.venv/bin/pytest tests/workflow/test_step_runner.py tests/workflow/test_a2a_client.py tests/workflow/test_runtime_config.py tests/workflow/test_orchestrator_config.py tests/guardrails/test_validator.py -q
.venv/bin/pytest -m integration tests/workflow/test_step_runner_integration.py -q
make check
```

The marked checks use real Postgres 18 through disposable Docker containers.
They prove every attempt lands as its own row, a second wrong answer pauses
with `validation_failed`, an exhausted hiccup budget ends `FAILED` with
history written once, and a replaced worker's result is refused.

## Model-call audit (story 6.1)

Every time the system asks a model to do work — a routing call, a spoke
agent call, a retry after a validation problem, a retry after a hiccup —
one row is written that says which model was used and what it cost in
tokens. Nothing records these calls by itself yet (the agents arrive with
Epic 3); this story builds the recorder they will all share, and proves it
with stand-in calls. The rules are linked in the
[architecture spine](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md)
(AD-2, AD-5, AD-15, AD-18, AD-19, AD-22, AD-23, AD-25).

- `contracts/usage.py::ModelUsage` is the shape of what one call consumed:
  the model name plus its token counters. A counter the provider did not
  report is stored as empty (NULL), never as zero — zero would pretend the
  tokens were free. `CallOutcome` is the closed set of per-call outcomes
  (`verdict`, `error`, `timeout`); it is never free text.
- `workflow/usage_audit.py::audit_model_call` is the one wrapper every
  model call goes through. It runs the call, writes the attempt row with
  the returned usage on success **and** on failure, and emits one log line.
  If the process dies mid-call, no row is written — the missing row *is*
  the honest record that usage was lost; nothing is invented. A call that
  returns but is labelled with a failure outcome (a caller bug) is saved as
  a failed attempt — its tokens were still spent — and then refused with
  `ValueError`, so the bug is loud but the call is never lost. Agents never
  touch the database: the wrapper lives in the orchestrator/eval-harness
  layer, and the callers (story 2.8's step runner, the evaluation harness,
  the A2A client) wire it in when they exist.
- Attempt rows are stored in the existing `run_step` table, in their own
  `call:<skill>` name namespace. The `(run_id, step, attempt)` identity can
  never collide with a step's own completion row; the resume view's
  completed-step list does include `call:` rows, but consumers query exact
  step names, so no false skip is possible. They are plain bookkeeping: they
  never move the run's state and never touch the lease-guarded commit path
  (AD-23). A second row for the same call attempt is refused by the
  database's uniqueness rule (AD-2).
- `workflow/service_log.py::log_invocation` writes each invocation as one
  JSON log line. Every line carries the run id, task id and step name, and
  the line is built from a fixed field list — there is simply no way to
  attach token counts, secrets or raw model output to it.
- `deploy/migrations/0007_run_step_audit.sql` adds only the audit columns
  to `run_step` (model, the five token counters, outcome — all nullable).
  There are no cost columns: story 6.2 owns pricing and will read these
  rows to compute costs centrally.

Run the focused checks:

```bash
.venv/bin/pytest tests/contracts/test_usage.py tests/workflow/test_usage_audit.py tests/workflow/test_service_log.py -q
.venv/bin/pytest -m integration tests/workflow/test_usage_audit_integration.py -q
make check
```

The marked checks use real Postgres 18 through disposable Docker containers.
They prove migration 0007 applies and adds only the audit columns, a full
usage fixture lands as a row with every counter, unreported counters stay
NULL, a failed call keeps the usage it did return, a duplicate attempt is
refused, and an audit row never moves the run's state.

## Model costs (story 6.2)

Story 6.1 records what every model call consumed; this story turns those
token counters into money amounts — and it does so honestly: anything
unknown stays visibly unknown instead of quietly becoming a zero. The
rules are linked in the
[architecture spine](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md)
(AD-9, AD-18, AD-19).

- `monitoring/prices.yaml` is the one price table. It carries a version
  number, and every priced model lists five separate rates — regular
  input, output, cache reads, 5-minute cache writes and 1-hour cache
  writes (USD per million tokens) — plus where the rate came from
  (`source_url`) and when it was looked up (`retrieved`). The Jev
  (`system_one`) entry has no rate yet: it is explicitly empty and flagged
  (OQ-3), and nothing may stand in for it.
- `monitoring/pricing.py::load_prices` is the only code that reads the
  table. It refuses a table that is unversioned, missing a rate type, or
  missing provenance — a bad price file is a startup error, never a
  silent zero.
- `monitoring/costs.py` is the pure calculator (no I/O). `cost_of_usage`
  prices one call, each token type at its own rate; a counter the
  provider did not report, an unpriced model, or a Jev-billed call yields
  an empty cost plus a flag — never 0. `summarize_costs` rolls a run's
  calls up: the run total is the sum of its parts only when every part is
  known; otherwise every total is empty and the reasons are listed.
- `workflow/usage_costs.py` is the orchestrator-side reader: it reads
  story 6.1's attempt rows through a small protocol (`UsageAuditReader`,
  Postgres adapter included), treats `call:system_one` rows as
  Jev-billed, and produces the per-run summary. Costs are computed, never
  stored — there are no cost columns and no migration.

To add or reprice a model: edit `monitoring/prices.yaml` (bump
`table_version`, add the five rates and fresh provenance) — no code
change. To replace the Jev rate once a real price exists (OQ-3): a YAML
edit plus a small wiring change in `monitoring/costs.py`, once the
billing units are known — the calculator does not read the Jev entry yet.

Two different guards, by design: the loader refuses a model that is in
the table but unsourced at load time; a model missing from the table is
flagged `model_unpriced` when its usage is costed. Nothing in production
consumes this yet — no startup wiring calls `load_prices()`, and nothing
calls `run_cost_summary`; the dashboards and exports of later epic
stories will.

Run the focused checks:

```bash
.venv/bin/pytest tests/monitoring tests/workflow/test_usage_costs.py -q
.venv/bin/pytest -m integration tests/workflow/test_usage_costs_integration.py -q
make check
```

The marked checks use real Postgres 18 through disposable Docker
containers. They prove the reader reads 6.1's real audit rows with NULL
counters preserved, a Jev-billed or incomplete run carries a NULL, flagged
total, a complete run sums cleanly, and the read is repo-bound.

## The Jev classifier agent (story 3.1)

The Jev agent is the specialist that answers one question: *what kind of
failure is this?* It is a small, stateless web service that speaks the same
A2A protocol the orchestrator uses. It is not wired into the live workflow
yet — story 2.9 makes the first real call; story 3.2 evaluates it before
that connection is allowed.

**What it answers.** A caller sends one `classify-failure` message whose
data part is a `DataPart` wrapping an `EvidencePack` (the numbered, distilled
log plus the run's commits and history). The agent makes **exactly one**
model call (AD-11) that asks two things at once:

- which of the five failure classes (`code | flaky | infra | external |
  unknown`) the failure belongs to, and
- how likely the log is an *injection attempt* — text inside the log trying
  to give the model instructions — rather than genuine failure output.

The reply's data part is a `JevResult`: the classification (class, one
confidence number, per-class probabilities kept separately for audit only,
AD-9) plus the token usage the provider reported. A counter the provider did
not report stays empty, never zero (AD-18). A positive injection screen is
just a number in the reply — the agent never blocks or lowers anything on
its own; the confidence cap for it is added downstream by the guardrails
layer (story 2.2).

**The one untrusted-data rule (AD-20).** The distilled log travels as a
delimited data section (the call's `state`), never inside the instructions.
The delimiters carry a fresh random nonce on every call
(`<<<distilled_log:{nonce}` … `distilled_log:{nonce}>>>`), so a log line
that happens to contain delimiter-looking text can never close the section
early — injection-looking log text is just data and blocks nothing on its
own. Embedded newlines inside one log line are escaped so every numbered
line stays exactly one line.

**One retry layer (AD-18, AD-22).** The typesafe-sdk ships its own hidden
retry policy (2 retries by default). The Jev adapter disables it — the
client is built with `RetryPolicy(max_retries=0)` and every call passes the
same policy — so the workflow's step runner is the ONLY retry layer: every
attempt is recorded, and a step can never quietly multiply model calls or
outlive its lease.

**Where things live.**

- `prompts/jev-classes.yaml` — the single copy of the five class
  descriptions and the injection-screen instruction. The agent and the eval
  suite both point at this one file; no class wording is duplicated in code.
- `agents/jev/questions.py` — loads the yaml once per process and builds the
  two-part question; `classifier.py` — the pure classify step, including the
  split that decides which provider failures are worth retrying (AD-22);
  `provider.py` — the small seam (`JevProvider` protocol) with the
  typesafe-sdk adapter (public SDK types only; SDK retries off, see above),
  so tests inject fakes and no real model is ever called in unit tests;
  `runtime.py` — reads the `jev` key of `config/runtime.yaml` (model id
  `typesafe/jev-1.13`, 60s timeout, serve host/port — values live only in
  the YAML, AD-19); `card.py`/`executor.py`/`server.py` — the transport:
  the Agent Card declaring the one catalogue skill `classify-failure`, the
  executor that refuses a malformed request or a data-part envelope whose
  `context_id` does not match the request's run id (AD-4) without calling
  the provider, and the JSON-RPC app; `__main__.py` — the servable
  composition (`python -m agents.jev`), host/port from the YAML.
- `contracts/jev.py::JevResult` — the reply shape; it is part of the
  `DataPart` payload union and its JSON Schema is generated and committed
  (`guardrails/schemas/JevResult.json`), like every inter-agent payload
  (AD-6).

**Errors.** Every failure is a typed `AgentError{code, message, retryable}`
carried on an A2A `FAILED` task: connection, timeout, throttling and server
errors are retryable; authentication, bad request, not-found, permission,
validation and "the answer is not a valid Jev answer" are not. The step
runner (2.8) reads that flag to decide whether to retry.

**How 2.9 will call it.** The orchestrator's existing transport
(`workflow/a2a_client.py`) already speaks the right shape: a blocking
non-streaming `SendMessage` with `contextId = run_id` and the `DataPart`
payload; the reply task's status message carries the `JevResult` (or the
`AgentError` on `FAILED`). The agent serves its card at
`/.well-known/agent-card.json` for discovery (story 3.9).

**Run and test it** (unit tests never call a real model — the provider is a
fake):

```bash
.venv/bin/pytest tests/agents/jev tests/contracts/test_jev.py -q
.venv/bin/python scripts/check_layer_contract.py   # agents hold no GitHub/Postgres clients
make check
```

**The eval** (`jev.test.yaml`) drives the real served path: a promptfoo
Python provider (`agents/jev/eval_provider.py`) builds the `EvidencePack`
from each case's log and calls the real `classify()` with the real
`TypeSafeJevProvider` (pinned model/timeout from the YAML), asserting on the
`JevResult` JSON the service answers with. It needs `TYPESAFE_API_KEY`
(OpenRouter) in the environment — promptfoo loads `.env` itself, but must be
told which Python has the repo's dependencies:

```bash
PROMPTFOO_PYTHON=$PWD/.venv/bin/python npx promptfoo eval -c jev.test.yaml
```

**The live smoke test** makes ONE real `system_one` call and asserts a
schema-valid `JevResult` with usage; it is marked `integration` and skipped
without a key:

```bash
TYPESAFE_API_KEY=... .venv/bin/pytest -m integration tests/agents/jev/test_integration.py -q
```
