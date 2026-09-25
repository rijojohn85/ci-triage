---
title: 'Story 0.1 — Reproduce the rubric layout and pinned toolchain'
type: 'feature'
created: '2026-09-25'
status: 'done' # PR #1 merged to main
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '297788786093eece7a94100426d0bc7e53bb24bc'
context:
  - _bmad-output/implementation-artifacts/epic-0-context.md
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The repo is an empty scaffold; builders and graders have no shared bootstrap, no required directory layout, and no verified pinned toolchain, so component work cannot start reproducibly.

**Approach:** Creating the spine's Structural Seed directory layout (placeholder dirs with README/.gitkeep pointing to the story that fills them), a documented bootstrap that installs and validates the spine-pinned toolchain with loud mismatch reporting, a README recording setup/commands/layout/entrypoints, and `.env.example` + `.gitignore` so secrets stay out of the repo.

</frozen-after-approval>

## Boundaries & Constraints

**Always:**
- Pinned stack (spine wins; if a pin cannot install, REPORT the concrete mismatch — never substitute): Python ≥ 3.10, a2a-sdk[http-server] 1.1.5, typesafe-sdk 0.7.1, anthropic 1.8.0, pydantic 2.13.5, psycopg 3.3.6, PostgreSQL 18 (`postgres:18` image), promptfoo 0.123.1 (npm), smee-client 5.0.0 (npm); Claude model IDs only `claude-haiku-4-5-20251001` (Analyzer) and `claude-sonnet-5` (Proposer/Reviewer).
- Layout: `prompts/`, `workflow/`, `guardrails/`, `agents/`, `gateway/`, `contracts/`, `punch-out/`, `monitoring/`, `runs/`, `results/`, `test-data/`, `tests/security/`, `deploy/` plus root eval entrypoints `jev.test.yaml`, `analyzer.test.yaml`, `proposer.test.yaml`, `reviewer.test.yaml`, `promptfooconfig.redteam.yaml`, `README.md` — per spine Structural Seed.
- Layer contract (AC2): `contracts/` imports nothing from the app layers; `guardrails/` depends only on `contracts`; agent code has no GitHub/Postgres clients; model IDs and per-skill `step_timeout` live in runtime YAML, never code; secrets via environment variables only.
- `.env` git-ignored; only `.env.example` with variable names (no values) committed.

**Never:**
- No gateway logic, no agents, no workflow engine, no Pydantic contract models (Story 0.2's), no compose services, no schemas (Story 0.3+ work).
- No secrets or values committed; no other model IDs in config; no silent version substitution.

## Tasks & Acceptance

**Execution:**
- [x] `sprint-status.yaml` -- track story `0-1-*` backlog → in-progress -- binding tracking requirement
- [x] `.gitignore` -- ignore `.env`, `.venv`, `__pycache__`, `node_modules/`, local exports -- AC2/AC5 secrets rule
- [x] Directory tree -- create all 13 spine directories; empty ones get README.md naming the owning story (agents/jev…, guardrails/schemas/…, deploy/migrations/, etc.) -- AC1 layout
- [x] `pyproject.toml` + lockfile -- package `triage` (src-less: packages contracts/guardrails/etc. own code later; this story ships bootstrap deps only) with exact pins -- AC1
- [x] `package.json` -- promptfoo `0.123.1`, smee-client `5.0.0` devDependencies; npm lock via package-lock.json -- AC1 npm promptfoo pin
- [x] `config/runtime.yaml` -- model IDs + per-skill `step_timeout` placeholders referencing the four agents (values pinned; loaded later stories) -- AC2 "runtime YAML owns model IDs"
- [x] `.env.example` -- names only: GITHUB_APP_PRIVATE_KEY, GITHUB_WEBHOOK_SECRET, GITHUB_APP_ID, GITHUB_APP_INSTALLATION_ID, ANTHROPIC_API_KEY, TYPESAFE_API_KEY, DATABASE_URL, TRIAGE_ENV -- AC2/secrets
- [x] `scripts/bootstrap.sh` -- create venv, `pip install -e .` (exact pins resolve from lockfile), `npm ci`, verify each pinned version via importlib/npm ls, print one `versions:` block; on unavailable pin: print concrete mismatch (expected vs available), exit non-zero, never install a substitute -- AC1, AC3
- [x] `scripts/check_layer_contract.py` -- AST/dep scan: contract modules must not import workflow/agents/gateway; guardrails must not import anything but contracts (+stdlib); agents/* must import no GitHub API client or psycopg/sqlalchemy; grep runtime YAML for forbidden model IDs outside the Sonnet/Haiku pair -- AC2
- [x] `README.md` -- purpose, bootstrap commands, layout map with root eval entrypoint locations, pinned-version record output path, remediation duty for missing pins as explicit unresolved build prerequisite -- AC1 entrypoints documented, AC3
- [x] Bootstrap run + version record from clean checkout; paste real output into README "Pinned toolchain versions (recorded)" and story record -- AC1 evidence

**Acceptance Criteria** (from epics.md Story 0.1, verbatim):

**AC1** Given a clean checkout, When the documented bootstrap runs, Then the spine-pinned Python-compatible toolchain and npm promptfoo are installed and version output is recorded, And prompts/, workflow/, guardrails/, agents/, gateway/, contracts/, punch-out/, monitoring/, runs/, results/, test-data/, tests/security/ and deploy/ exist with root eval entrypoint locations documented.

**AC2** Given the layer contract, When imports and dependency configuration are checked, Then contracts has no application-layer dependency and guardrails depends only on contracts, And agent code has no GitHub/Postgres clients; runtime YAML owns model IDs and per-skill step_timeout; secrets use environment variables.

**AC3** Given an unavailable pinned dependency, When bootstrap validates the environment, Then it reports the concrete mismatch without silently replacing the binding stack, And README setup records remediation as an explicit unresolved build prerequisite.

## Implementation Notes

- Pin verification sources (2026-09-25): PyPI (a2a-sdk 1.1.5 page: Python ≥3.10, `http-server` extra exists, no postgresql extra deployed) / telemetry via npm registry (promptfoo 0.123.1, smee-client 5.0.0 real). Actual install of all Python pins ran clean on Python 3.14.2 (/tmp/opencode/stage4-venv). postgres:18 manifest OK.
- Version output recorded: run `scripts/bootstrap.sh --print-versions`; captured into README "Pinned toolchain versions (recorded 2026-09-25)".

## Verification

**Commands:**
- `bash scripts/bootstrap.sh` -- expected: pip + npm install exact pins, zero drift, exits 0
- `python scripts/check_layer_contract.py` -- expected: PASS lines for contracts/guardrails/agents/secrets-YAML
- `bash scripts/bootstrap.sh --print-versions` -- expected: prints pinned versions block matching spine Stack table
- `git status` -- expected: `.env` ignored; no secrets tracked

## Review Triage Log

| # | Finding | Verdict | Evidence |
|---|---|---|---|
| 1 | verification-gap: `check_runtime_yaml` counts `step_timeout` but never enforces it (probe: gutted runtime.yaml still PASS) | high (pre-verified) | Layer checker's own AC2 claim unverified; probed with fixture, exit 0 on missing timeouts |
| 2 | verification-gap + blind-hunter: `check_guardrails` blocks only known APP_LAYERS, not "contracts+stdlib only" (`import requests` passes) | high (pre-verified) | Positive allowlist absent; probed with guardrails/evil.py, PASS printed |
| 3 | blind-hunter + edge: no Python >=3.10 floor check; pip/npm failures abort with raw traceback before PIN MISMATCH report (AC3) | medium | bootstrap.sh has no preflight; set -e dies before mismatch protocol on missing npm or unresolvable pin |
| 4 | verification-gap: `verify_npm` trusts `npm ls` which reports locked id, not installed artifact (probe: tampered node_modules package.json still "verified") | medium | Probed in /tmp project; verify against node_modules/*/package.json instead |
| 5 | `print_versions` python line uses outer `$PY`, not venv interpreter | medium | Reports wrong interpreter if venv built from other python |
| 6 | README claims `--print-versions` "print the block only" but it runs full bootstrap first | low | Flag checked after all installs; wording + minor flow |
| 7 | `check_agents` raw-text `github` scan false-positives on comments/URLs | medium | Word regex over comments; should AST-check imports instead |
| 8 | `.gitignore`: `.env.local` variants and future `runs/<id>/`, `results/<id>/` artifacts trackable | medium | AD-16 leak-prevention surface; trivial pattern fix |
| 9 | MODEL_ID_RE lowercase-only; uppercase model ID variant escapes scan | medium | AC2 model allowlist check bypassable with case variation |
| 10 | node/npm versions absent from versions block; README recorded block can silently go stale | low | print node/npm alongside py pins |
| 11 | Transitive deps unlocked (no Python constraints file) though spec says "lockfile" | medium | Commit pip freeze as constraints.lock, install with `-c` |
| 12 | `check_layer_contract.py`: `module_of()` dead code; missing layer dirs yield vacuous PASS; dead `punch-out` in APP_LAYERS | low | Dead helper; dir-existence check one line each |
| 13 | `.env.example` lacks per-var owner-scope comments (AD-16 placement contract invisible) | low | Comments only |
| 14 | runtime.yaml: no note on temperature removed in anthropic 1.x / Jev key scoping | low | Comments only |
| 15 | sprint-status.yaml `last_updated` got narrative stuffed into timestamp field | low | Restore timestamp format |
| 16 | README Secrets section duplicates .env.example var list (drift risk) | low | Replace list with pointer |
| 17 | promptfoo stubs need ANTHROPIC_API_KEY to even attempt eval | low | Add one note line to stubs |
| 18 | Concurrent bootstrap race | low (rejected) | Everyday use; fix adds lockfile complexity |
| 19 | f-string secret-assign regex gap | low (rejected) | Exotic path; basic scan sufficient this story |
| 20 | Node engine note placed under "prerequisites" header | false | Header explicitly says "not pin mismatches" — self-consistent |
| 21 | redteam stub `targets:` vs `provider:` inconsistency | low (rejected) | Both accepted promptfoo keys; unifying risks wrong key; cosmetic |
| 22 | Spec "lockfile" wording for Python side | — (rejected) | Fix would edit spec; action taken via finding 11 patch |
| 23 | README layout table omits _bmad-output etc. | low (rejected) | Process docs, not build layout |
