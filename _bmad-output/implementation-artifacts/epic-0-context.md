# Epic 0 Context: Reproduce the project and share stable contracts

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Establish the reproducible shared foundation for the Blameless CI Triage certification slice: a source-free checkout bootstraps into the spine-defined rubric layout with a pinned toolchain and recorded versions; one Pydantic contracts package becomes the typed single source for all inter-agent payloads with generated, committed JSON Schemas; a Compose-based local service foundation starts PostgreSQL 18 with forward-only SQL migrations and correctly scoped secret placement; and the external synthetic GitHub demo repo is prepared with a least-privilege GitHub App and protected default branch so later stories exercise the real certification environment rather than placeholders. Epic 0 enables independently buildable capability work for FR1–FR6 / CAP-1–CAP-6.

## Stories

- Story 0.1: Reproduce the rubric layout and pinned toolchain — bootstrap from a clean checkout installs the pinned toolchain and records versions, creates the full directory layout with documented root eval entrypoints, and validates the layer contract (contracts have no app-layer deps, guardrails depends only on contracts, agents have no GitHub/PG clients, secrets/env-only config).
- Story 0.2: Publish shared payload contracts and generated schemas — implement Pydantic v2 models (TriageVerdict, EvidencePack, AgentError, A2A DataParts) with exact spine enums/shapes, generate JSON Schema into guardrails/schemas/, commit and gate CI on schema drift.
- Story 0.3: Start Compose and forward-only migrations — docker compose starts postgres:18 plus a one-shot migration job with forward-only tracking, service startup gated on migration success, secrets restricted per placement contract, no speculative schema tables.
- Story 0.4: Prepare the protected external GitHub demo repository — install the GitHub App on the external synthetic Python repo with exact AD-16 permissions, configure ruleset/CODEOWNERS so human review is required and the App cannot bypass, and document the recreatable setup in test-data/demo-repo.md with a tagged baseline snapshot and no fabricated receipts.

## Requirements & Constraints

- Bootstrap must run against a clean checkout and record version output for the pinned stack; a missing or mismatched pinned dependency is reported as a concrete error without silently substituting the stack, and recorded in README as an unresolved build prerequisite (bound to AD-5, AD-6, AD-16, AD-19, AD-25).
- All contract enums and shapes must match the spine exactly: class `code|flaky|infra|external|unknown`, `risk_tier` `normal|blocked|not_gated`, `terminal_state` `pr_opened|report_sent|input_required|rejected_by_human|failed` (null while running), citation kinds `log_line|commit|metric|history_row|jev_signal`, objection severity `info|minor|major|dangerous`, diff ops `add|modify|delete`, `escalation_reason` six values (AD-1), `class_override` field on approvals (AD-9/AD-14), `AgentError {code, message, retryable}`.
- All production SHAs are full 40-character; unique short prefixes are accepted only at the dry-run boundary (AD-26).
- Secret placement: App private key only gateway/orchestrator; Claude key only the three Claude agents; Jev key only Jev agent/orchestrator. `.env` never committed; sample config contains no secrets; secrets never appear in runs/, logs or prompts (AD-16).
- GitHub App permissions exactly: `actions:read`, `checks:read`, `contents:write` (restricted to `refs/heads/triage/*`), `pull_requests:write` (draft only), `issues:write`, org `members:read`; never `workflows`. Protected default branch requires human review with the App not a bypass actor; CODEOWNERS includes a fallback `*` rule; App is never a merge actor.
- Migrations are forward-only SQL applied by a one-shot job before workers start; re-runs never reapply completed ones; a failed migration blocks dependent workers. No `a2a-db`/`DatabaseTaskStore` schema is deployed (AD-4, AD-25).
- Story 0.4 is externally dependent (repo/App admin access). If absent, setup is reported blocked; E4 cannot claim real permission verification from placeholders.

## Technical Decisions

- **Pinned stack (spine Stack table, verbatim):**
  - Python: ≥ 3.10 (a2a-sdk floor)
  - a2a-sdk (`http-server` extra; no `postgresql` extra): 1.1.5
  - typesafe-sdk (Jev / System One): 0.7.1
  - anthropic: 1.8.0
  - pydantic: 2.13.5
  - psycopg: 3.3.6
  - PostgreSQL: 18 (`postgres:18` image)
  - promptfoo (npm): 0.123.1
  - smee-client (npm): 5.0.0
  - Claude models: Analyzer `claude-haiku-4-5-20251001`; Proposer + Reviewer `claude-sonnet-5`
  - Runtime: Docker Compose (dev + graded E2E); plain k8s manifests (cluster) — same images
- **Rubric directory layout:** `prompts/` (analyzer.md, proposer.md, reviewer.md, jev-classes.yaml), `workflow/` (state machine, registry, A2A client/server, TaskStore adapter, evidence pack, step runners), `guardrails/` (schemas/ generated, validator, citation_check, risk_gate, thresholds.yaml), `agents/` (jev/, analyzer/, proposer/, reviewer/), `contracts/`, `gateway/`, `punch-out/`, `monitoring/`, `runs/`, `results/`, `test-data/`, `tests/` (incl. security/), `deploy/` (compose.yaml, k8s/, registry.<env>.yaml, migrations/). Root eval files: analyzer.test.yaml, proposer.test.yaml, reviewer.test.yaml, jev.test.yaml, promptfooconfig.redteam.yaml, README.md.
- **Layer contract:** `contracts/` may import nothing; `guardrails/` may import only `contracts/`; spoke agents get `contracts/`, own prompts, own model API only — no GitHub or Postgres clients (AD-5, AD-6).
- **Contracts:** Pydantic v2 models in `contracts/` are the single source; JSON Schema generated and committed into `guardrails/schemas/`; CI fails on regenerated drift (AD-6).
- **ID conventions:** `run_id` = UUIDv7 = A2A `task_id` = spoke `contextId`; UTC ISO-8601 JSON / `timestamptz` in Postgres (Consistency Conventions).
- **Config:** env vars for secrets; YAML/config for model IDs, per-skill `step_timeout`, thresholds, registry, prices — never code. Do not rely on `temperature` (removed in anthropic SDK 1.x) (AD-19).
- **Compose secrets:** restricted per-service placement (AD-16); sample config secret-free.

## Cross-Story Dependencies

- Story 0.1 is the root: no dependencies. Story 0.2 depends on 0.1 (needs installed toolchain and layout). Story 0.3 depends on 0.1 and 0.2 (contracts/migrations tooling present). Story 0.4 depends on 0.3 (Compose=localhost service foundation).
- Downstream: Epic 1 (CI run intake) builds on the gateway posture and migration/init from 0.3; E4 permission verification requires the real demo repo App from Story 0.4 — placeholders can never substitute. Every later epic consumes `contracts/` models and generated schemas from Story 0.2, and the layer contract enforced by 0.1 applies to all component stories. All model calls in later epics go through the pinned anthropic/typesafe-sdk versions installed here; promptfoo eval suites reference the pinned npm promptfoo.
- External blocking input: GitHub App/repo administration and authenticated access must exist at Story 0.4 build time, otherwise report setup blocked.
