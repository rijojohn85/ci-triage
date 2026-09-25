# Epic 1 Context: Accept failed CI runs once and retain them safely

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Accept authentic failed CI runs exactly once and hold them safely for bounded concurrent processing. A signed `workflow_run` completed/failure webhook is verified before parsing, checked against installation and delivery/run identity, and inserted as a `RECEIVED` `triage_run` with a 202 acknowledgement; replay, forged, unknown-installation and flooding traffic never creates duplicate or phantom work. Orchestrator workers then claim runs through renewable, fenced leases so a stale owner cannot commit results after another worker takes over, and the graded runtime proves real signed tunnel delivery plus overlapping webhook-secret rotation. This is CAP-1 / FR1: the queue and worker-ownership foundation every later capability builds on.

## Stories

- Story 1.1: Authenticate and deduplicate failed-run intake
- Story 1.2: Claim, renew and fence worker leases
- Story 1.3: Verify signed tunnel delivery and secret rotation

## Requirements & Constraints

- Ingress accepts only `workflow_run` completed/failure in MUST scope; `issue_comment` (`/triage` command) is excluded (SHOULD backlog). The gateway makes no LLM or GitHub calls and holds no GitHub/Postgres clients beyond enqueue (AD-16, AD-17).
- Signature is verified over raw bytes with `hmac.compare_digest` **before** parsing; missing or bad signature returns 401. Unknown `installation.id` is rejected. A replayed `X-GitHub-Delivery` returns a 2xx no-op. The true dedupe key is unique `(repo_id, workflow_run_id, run_attempt)` — a new delivery ID must not create a second run (AD-17).
- A per-installation rate limit and a per-repo queue-depth cap prevent intake bursts from enqueueing excess jobs. Accepted requests insert `triage_run(RECEIVED)` and return 202 (AD-17).
- Worker concurrency is bounded (N workers = cap). Human waits must never hold a worker; lease claiming and renewal must not hold a database lock across the multi-minute external call (AD-1, AD-23).
- Lease claim is a short transaction on rows with no lease or an expired `lease_until`; long steps renew; the step-commit transaction re-checks `lease_owner` and discards the result on mismatch (AD-23).
- Postgres is authoritative for run state, the durable queue and audit; step output and state transition commit atomically and completed steps are never re-executed on reclaim (AD-2).
- Webhook secrets rotate with two secrets both accepted during the overlap window; after retirement the old secret fails and the new one continues; invalid signatures still fail (AD-25).
- Graded runtime uses Compose with the smee.io tunnel against the synthetic demo repo only; the same images run on plain k8s (AD-25). Structured JSON logs carry `run_id`/`task_id`/`step` and never contain secrets or raw logs (AD-16, AD-25).

## Technical Decisions

- **Run state owner:** `triage_run` is the sole owner of run state; `run_id` = UUIDv7 (AD-1, AD-4). Initial legal move is `[*] -> RECEIVED`; all moves live in one transition table in `workflow/` and any undeclared transition raises (AD-1).
- **Ingress boundary (`gateway/`):** may call Postgres for enqueue only. All four ingress protections — signature, installation, replay, run identity — plus load limits are gateway responsibilities (AD-17).
- **Lease fields:** `triage_run` carries `lease_owner` and `lease_until`; claim uses `SELECT … FOR UPDATE SKIP LOCKED` on unleased/expired rows and commits before any external call (AD-23).
- **Idempotent/atomic persistence:** a step's `run_step` row and the state transition commit in one lease-guarded transaction (AD-2). Dissolution/decisions for later states are out of scope here.
- **Operational envelope:** forward-only SQL migrations applied by a one-shot job before workers start; `pg_dump` before graded batches; `.env` under Compose and `Secret` objects on k8s; a signature check through the smee tunnel is the smoke test (AD-25).
- **Least privilege / secrets:** App private key only in gateway and orchestrator; installation tokens minted per step by the orchestrator; secrets never appear in runs, logs or prompts (AD-16).
- **Config:** env vars for secrets; YAML for thresholds, prices, registry, model IDs and timeouts — never hardcoded (AD-19, Consistency Conventions).
- **Pinned stack:** Python ≥ 3.10, a2a-sdk 1.1.5, typesafe-sdk 0.7.1, anthropic 1.8.0, pydantic 2.13.5, psycopg 3.3.6, PostgreSQL 18 (`postgres:18`), promptfoo 0.123.1, smee-client 5.0.0.
- **Consistency conventions:** times are UTC ISO-8601 in JSON and `timestamptz` in Postgres; errors return `contracts.AgentError {code, message, retryable}`.

## Cross-Story Dependencies

- 1.1 depends on 0.3 (Compose/migrations foundation), 0.4 (installed App + protected demo repo) and 2.1 (enforced state transition invariants). 1.2 depends on 1.1 and 2.1. 1.3 depends on 0.4 and 1.1.
- Epic-level: E1 requires E0 contracts/storage/runtime, and E2's state invariants must land before state-mutating worker integration. E2's durable execution in turn depends on the lease mechanism built here (AD-1, AD-2, AD-23). E4 owns the consolidated adversarial/security coverage; the deterministic gateway and lease tests in this epic remain required.
- Story 0.4 is externally dependent (repo/App administration and authenticated access). If unavailable, report setup blocked — real tunnel and permission receipts cannot come from placeholders.
