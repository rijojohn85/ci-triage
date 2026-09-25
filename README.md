# Blameless CI Triage — Certification Slice

Spoke-based multi-agent system that triages CI failures and produces blameless, human-gated fixes. This repo is Story 0.1 of Epic 0: the reproducible rubric layout and pinned toolchain foundation. Full planning docs: `_bmad-output/planning-artifacts/` (architecture spine, epics.md).

## Quickstart (bootstrap)

```bash
bash scripts/bootstrap.sh              # create .venv, install pinned Python deps, npm-install pinned tools, verify pins
python3 scripts/check_layer_contract.py  # enforce the layer contract (contracts/guardrails/agents/secrets/YAML)
bash scripts/bootstrap.sh --print-versions  # after bootstrap: validate + print the pinned versions block without re-installing (installs only if the env does not yet exist)
```

Python: `>= 3.10` (uses `PYTHON=...` override, default `python3`). npm ≥ 10, node ≥ 22 expected (see engine notes below).

## Pinned toolchain versions (recorded)

Real output of `bash scripts/bootstrap.sh --print-versions`, recorded 2026-09-25 on this checkout:

```
versions:
  python: 3.14.2
  node: v22.20.0
  npm: 10.9.3
  a2a-sdk: 1.1.5
  typesafe-sdk: 0.7.1
  anthropic: 1.8.0
  pydantic: 2.13.5
  psycopg: 3.3.6
  promptfoo (npm): 0.123.1
  smee-client (npm): 5.0.0
  postgresql: postgres:18 image (pinned; used from Story 0.3 compose, not installed here)
```

## Unresolved build prerequisites

Remediation notes for any pin that cannot be installed at bootstrap time. Known environment notes (not pin mismatches):

- `promptfoo@0.123.1` declares `engines.node >= 22.22.0`; local node is 22.20.0 → npm prints an `EBADENGINE` warning but installs the pinned version. If node ≥ 22.22 becomes a hard prerequisite, upgrade node (remediation: install newer node, re-run bootstrap).
- `postgres:18` Docker image pin is used from Story 0.3 (compose); nothing to install in this story.
- `requirements/constraints.txt` is a frozen `pip freeze` of the installed .venv (used via `pip install -e . -c requirements/constraints.txt` to pin transitive deps). When the file is absent, bootstrap regenerates it from a fresh install; refresh is automated, not a manual step.

If a bootstrap run reports `PIN MISMATCH: ...`, do not substitute versions; fix the environment or record the blocking mismatch here.

## Layout

| Path | Purpose |
| --- | --- |
| `prompts/` | agent prompts (`analyzer.md`, `proposer.md`, `reviewer.md`, `jev-classes.yaml`) |
| `workflow/` | orchestration state machine, registry, A2A client/server, TaskStore adapter, step runners |
| `guardrails/` | validator, citation_check, risk_gate, thresholds.yaml; `guardrails/schemas/` holds generated JSON Schemas |
| `agents/` | spoke agents: `agents/jev/`, `agents/analyzer/`, `agents/proposer/`, `agents/reviewer/` — no GitHub/Postgres clients |
| `contracts/` | Pydantic v2 payload models (single source; Story 0.2) |
| `gateway/` | GitHub webhook gateway (Epic 1) |
| `punch-out/` | breakpoint/halting-session handling |
| `monitoring/` | dashboards/alerts |
| `runs/`, `results/` | per-run working dirs and final artifacts (never contain secrets) |
| `test-data/` | demo-repo setup docs, fixtures (Story 0.4) |
| `tests/security/` | security test suites |
| `deploy/` | compose.yaml, `k8s/`, `registry.<env>.yaml`, `migrations/` (Story 0.3+) |
| `scripts/` | `bootstrap.sh`, `check_layer_contract.py` |
| `config/` | `runtime.yaml` — model IDs + per-skill `step_timeout` (owned by YAML, never code) |

## Root eval entrypoints

promptfoo eval configs live at repo root: `jev.test.yaml`, `analyzer.test.yaml`, `proposer.test.yaml`, `reviewer.test.yaml`, `promptfooconfig.redteam.yaml`. Each points at a file under `prompts/`. They are documented placeholders at this story; eval content is delivered by later stories.

## Secrets

Secrets are read from environment variables only. `.env` (and any `.env.*` variant) is git-ignored; only `.env.example` is committed — variable names and their owning components are documented there (per AD-16 key-placement scopes). Do not paste real values into `.env.example`, prompts, code, `runs/`, or `results/`.

## Architecture spine

Directory layout, layer contract, and pinned stack reflect the spine Structural Seed in `_bmad-output/planning-artifacts/` (architecture spine + `epics.md`). The layer contract enforced by `scripts/check_layer_contract.py`:

- `contracts/` imports nothing from the app layers.
- `guardrails/` depends only on `contracts/` (+stdlib).
- `agents/` have no GitHub API or Postgres clients (model API + contracts only).
- Model IDs and per-skill `step_timeout` live in `config/runtime.yaml`, never code.
- Secrets via environment variables only.
