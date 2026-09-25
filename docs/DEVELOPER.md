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

## Where things live

| Path | Status | Contents |
| --- | --- | --- |
| `contracts/` | built (0.2) | Pydantic v2 models for every inter-agent payload; see [contracts/README.md](../contracts/README.md) |
| `guardrails/schemas/` | built (0.2) | JSON Schemas generated from `contracts/`; never edit by hand |
| `deploy/compose.yaml` | built (0.3) | postgres:18 + one-shot `migrate` job + placeholders for gateway/orchestrator/agents with AD-16 secret placement; see [deploy/README.md](../deploy/README.md) and [Compose and migrations](#compose-and-migrations-story-03) |
| `deploy/migrations/` | built (0.3) | forward-only `.sql` files + naming rules; runner is `workflow/migrate.py` |
| `scripts/` | built (0.1, 0.2, 0.4) | `bootstrap.sh`, `check_layer_contract.py`, `generate_schemas.py`, `verify_demo_repo.py`; `ruleset-seed.json` payload for the demo-repo ruleset |
| `tests/scripts/` | built (0.4) | unit tests of the demo-repo read-back comparison logic against recorded API fixtures; live `gh` path is `@pytest.mark.integration` |
| `test-data/` | built (0.4) | demo-repo evidence: `demo-repo-expected.json` (AD-16 set, one source for script + docs), `demo-repo.md` (live facts + scenario slots), `demo-repo-seed/` (pushed verbatim to the demo repo) |
| `tests/contracts/` | built (0.2) | contract tests, named after the ACs they prove |
| `tests/workflow/`, `tests/security/` | built (0.3) | migration-runner and compose secret-placement tests; `@pytest.mark.integration` ones need Docker (`pytest -m integration`) |
| `config/runtime.yaml` | placeholder | model IDs and per-skill `step_timeout` (AD-19) |
| `deploy/` | partially built (0.3) | Compose, k8s manifests, migrations (0.3+); k8s manifests + `registry.<env>.yaml` still placeholders |
| `gateway/`, `workflow/`, `agents/`, `guardrails/` (code), `punch-out/`, `monitoring/` | placeholder | filled by Epics 1–6; each folder's README says what belongs there |
| `prompts/`, `*.test.yaml` | placeholder | agent prompts and their promptfoo evals (Epic 3) |

Layer rules (enforced by `scripts/check_layer_contract.py`): `contracts/` imports only stdlib and pydantic; `guardrails/` imports only `contracts/`; agents hold no GitHub or Postgres clients; model IDs and timeouts live in YAML; secrets come from environment variables.

## Running things

```bash
bash scripts/bootstrap.sh          # create .venv, install pinned Python and npm tools, verify pins
make check                         # every quality gate; must be green before a story is done
python scripts/generate_schemas.py # regenerate guardrails/schemas/ after changing a contract
```

`make check` runs: bootstrap check, layer contract, schema drift, ruff (check + format), `mypy --strict`, pylint duplicate-code, `pytest --cov` (≥ 85% on `contracts`, `guardrails`, `workflow`). Integration tests that need Docker are marked `@pytest.mark.integration` and excluded from `make check` by default — run them with `make test-integration` (or `.venv/bin/pytest -m integration`). Individual targets are listed in the [Makefile](../Makefile).

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
- **Worker services** (gateway, orchestrator, agents) are busybox placeholders until their stories — the AD-16 env names are already in place and the migration gating is live.
- **Connection strings:** the migrate job builds its DSN from `POSTGRES_*` names inside the compose network; host-side tools use `DATABASE_URL` from `.env`.

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
