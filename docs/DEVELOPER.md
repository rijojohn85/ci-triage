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

## Where things live

| Path | Status | Contents |
| --- | --- | --- |
| `contracts/` | built (0.2) | Pydantic v2 models for every inter-agent payload; see [contracts/README.md](../contracts/README.md) |
| `guardrails/schemas/` | built (0.2) | JSON Schemas generated from `contracts/`; never edit by hand |
| `scripts/` | built (0.1, 0.2) | `bootstrap.sh`, `check_layer_contract.py`, `generate_schemas.py` |
| `tests/contracts/` | built (0.2) | contract tests, named after the ACs they prove |
| `config/runtime.yaml` | placeholder | model IDs and per-skill `step_timeout` (AD-19) |
| `deploy/` | placeholder | Compose, k8s manifests, migrations (0.3+) |
| `gateway/`, `workflow/`, `agents/`, `guardrails/` (code), `punch-out/`, `monitoring/` | placeholder | filled by Epics 1–6; each folder's README says what belongs there |
| `prompts/`, `*.test.yaml` | placeholder | agent prompts and their promptfoo evals (Epic 3) |

Layer rules (enforced by `scripts/check_layer_contract.py`): `contracts/` imports only stdlib and pydantic; `guardrails/` imports only `contracts/`; agents hold no GitHub or Postgres clients; model IDs and timeouts live in YAML; secrets come from environment variables.

## Running things

```bash
bash scripts/bootstrap.sh          # create .venv, install pinned Python and npm tools, verify pins
make check                         # every quality gate; must be green before a story is done
python scripts/generate_schemas.py # regenerate guardrails/schemas/ after changing a contract
```

`make check` runs: bootstrap check, layer contract, schema drift, ruff (check + format), `mypy --strict`, pylint duplicate-code, `pytest --cov` (≥ 85% on `contracts`, `guardrails`, `workflow`). Individual targets are listed in the [Makefile](../Makefile).

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
