---
title: 'Start Compose and forward-only migrations (Story 0.3)'
type: 'feature'
created: '2026-09-25'
status: 'draft'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: 'fc702b6b4e543ba632b7d1ea63bc891a841ea2cb'
context: ['{project-root}/AGENTS.md', '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Story 0.1/0.2 gave the repo a layout, quality gates and shared contracts, but no local runtime: no Postgres, no migrations, no Compose file for the gateway/orchestrator/agent services to attach to later (AD-25 runtime; epics.md 0.3).

**Approach:** Compose the local service foundation exactly as the epics define it: postgres:18 with a healthcheck, a one-shot `migrate` service that applies forward-only SQL from `deploy/migrations/` via a minimal hand-rolled runner, and worker provenance (`gateway`, `orchestrator`) declared as `depends_on: migrate: {condition: service_completed_successfully}` so startup waits and a failed migration blocks them. Secret placement (AD-16) is proven by a test that parses `deploy/compose.yaml`: App private key gateway+orchestrator only, Claude key the 3 Claude agents only, Jev key Jev+orchestrator only. `.env` stays git-ignored; `.env.example` keeps names only. No domain tables and no `a2a-db`/DatabaseTaskStore schema (AD-4) — those come with their consuming stories.

**Docs sources (AGENTS.md step 5):** Compose `depends_on` conditions `service_healthy` and `service_completed_successfully` — Context7 `/docker/compose` (compose source `startService`/`waitDependency`, `checkDependencyCompleted`) plus the E2E fixture `compose-depends-on.yaml`; postgres:18 image env vars (`POSTGRES_PASSWORD` required, `POSTGRES_USER`/`POSTGRES_DB` optional, `PGDATA` changed in 18 to `/var/lib/postgresql/18/docker`, volume `/var/lib/postgresql`) — Context7 `/websites/hub_docker_postgres` + Docker Hub page; psycopg 3.3.6 transaction blocks and multi-statement execution — Context7 `/psycopg/psycopg`.

</frozen-after-approval>

## Open Questions

(none — the runner constraint was pre-decided by the human: minimal hand-rolled runner, plain `.sql`, `schema_migrations`, one transaction per file, non-zero exit on failure, no Alembic/SQLAlchemy, no advisory lock, no new deps. Challenge called for in the brief: none raised — the ACs need nothing more: tracking table + transactionality + non-zero exit covers AC1; worker gating is Compose's `service_completed_successfully`, not runner code.)

## Code Map

Investigated state (verify against source when touching behavior):

- `deploy/migrations/README.md` — stub ("populated by Story 0.3"); `deploy/README.md` — stub ("Story 0.3+ fills"); both replaced this story.
- `deploy/compose.yaml` — does not exist yet; `deploy/k8s/` empty (k8s is a later, separate runtime story; no k8s work here).
- `.gitignore` already ignores `.env` / `.env.*` / `!.env.example`; `.env.example` already correct for AD-16 scopes (GITHUB_APP_PRIVATE_KEY, GITHUB_WEBHOOK_SECRET, GITHUB_APP_ID/INSTALLATION_ID, ANTHROPIC_API_KEY, TYPESAFE_API_KEY, DATABASE_URL, TRIAGE_ENV) — no change needed, verify only.
- `Makefile` — `check` = bootstrap-check, layer-contract, schema-drift, ruff (check+format), mypy --strict, pylint duplicate-code, pytest --cov (source `contracts`, `guardrails`, `workflow`, fail_under 85). New tests must fit these gates: migration/compose tests live in `tests/` (not covered by the 85% source filter — fine), ruff/mypy run on `scripts/ contracts/ guardrails/ workflow/` only, so the runner location must be chosen with that in mind (see Approach bullets).
- `pyproject.toml` — pytest `pythonpath=["."]`; no `markers` declared yet (add `integration` marker + `addopts = -m "not integration"` careful default; provide `make test-integration` escape hatch); `psycopg==3.3.6` already a dependency.
- `scripts/check_layer_contract.py` — app layers are `workflow, agents, gateway, guardrails, monitoring, punch_out, results, runs, test_data`; scans Python under those dirs for forbidden `psycopg` imports (agents must not import it). A migration runner must therefore NOT live in app-layer dirs named above; `deploy/` is not scanned (layer contract unaffected either way).
- `tests/contracts/test_drift.py` — pattern for a static-file-parsing gate (reads files, compares content) — reuse its shape for the compose-parse test.
- Story 0.2 spec implementation notes: pytest 9 needs explicit `pythonpath`; addopts defaults matter — do not break the `make check` fast path.
- Sprint-status: `0-2-publish-shared-payload-contracts-and-generated-schemas: review` → set `done` before branching (housekeeping step).
- Dirty tree: `opencode.jsonc` carries an unrelated one-line local edit (`$schema` key) — leave uncommitted, untouched by this story.

## Tasks & Acceptance

**Execution:**
- [ ] Housekeeping (step 0): mark 0.2 done in sprint-status.yaml, commit on main as `chore: mark 0.2 done`, push; create `story/0-3-start-compose-and-forward-only-migrations` branch.
- [ ] `tests/workflow/test_migrations_runner.py` — RED first: apply-exactly-once in filename order (AC1), re-run applies nothing and exits 0 (AC1), failing SQL rolls back completely and exits non-zero with no recorded row (AC1), `schema_migrations` bootstrap is `CREATE TABLE IF NOT EXISTS` inside the runner (AC1).
- [ ] `workflow/migrate.py` — GREEN vs red tests; runner lives in `workflow/` (ruff/mypy gates already cover it) with the DB connection behind a small Protocol (L/D of SOLID); fake connection for unit tests, psycopg for integration.
- [ ] `tests/security/test_compose_secret_placement.py` — RED→GREEN (AC2): parse `deploy/compose.yaml` with PyYAML; assert the three scoped keys appear only on their owning services and nowhere else; assert no literal secret values and no a2a-db/DatabaseTaskStore service or schema; assert worker services depend on `migrate` with `service_completed_successfully` (AC1) and postgres has a healthcheck the migrate job waits on.
- [ ] `deploy/compose.yaml` — GREEN of the parse test: postgres:18 + healthcheck (`pg_isready`), `migrate` one-shot service (psycopg runner via the tracked-down `service_completed_successfully` semantics), placeholder `gateway`/`orchestrator`/agent services (sleep or echo stubs) with only their own secret names in `environment`.
- [ ] `deploy/migrations/0001_reproduce_rubric_baseline.sql` + later stories add forward-only files; `deploy/migrations/README.md` naming rule (zero-padded prefix), no domain tables note.
- [ ] `deploy/migrate.py` interface: `--dsn` or `DATABASE_URL` env; `--dry-run` lists pending migrations, applies nothing; `--status` lists applied vs pending. Non-zero exit on any failure. (These flags are the documented commands for AC3.)
- [ ] `pyproject.toml`: register `markers = ["integration: needs Docker/Postgres"]`; default-suite speed decision — keep make-check fast per user constraint.
- [ ] Integration test `tests/workflow/test_migrations_integration.py` (`@pytest.mark.integration`): real behavior against postgres:18 in Docker — fresh apply, idempotent re-run, rollback on bad SQL, and "only schema_migrations exists" (AC3 no-domain-tables proof). Skipped unless `-m integration`.
- [ ] Human smoke test of `docker compose up` (I run it, report output): AC1 end-to-end, workers held back on migration failure; re-run idempotent.
- [ ] Docs: `docs/DEVELOPER.md` — "Compose and migrations" section + 0.3 row in "Built so far"; `docs/USER-GUIDE.md` — "Run it locally" filled (setup, up, down, what to expect); `deploy/README.md` + `deploy/migrations/README.md` updated; note in `tests/README.md` on running integration tests.
- [ ] `make check` green; AC-by-AC evidence table in the story report.

**Acceptance Criteria:**
- AC1 — Compose (docker compose up from empty environment): postgres:18 starts, migration job initializes schema_migrations and applies all files, workers start only after the job exits 0 (`service_completed_successfully`); re-running the job applies nothing (idempotent); a deliberately failing migration keeps workers from starting and exits non-zero. Unit-proven (runner logic, exit codes, rollback) + compose-parse tests + one marked integration test + a human-run compose smoke test with output reported.
- AC2 — Compose configuration inspected: App private key only gateway/orchestrator; Claude key only jev/analyzer/proposer/reviewer; Jev key only jev/orchestrator; `.env` not committed (gitignore check), `.env.example` names only; no a2a-db/DatabaseTaskStore schema. Proven by the compose-parse tests (security/).
- AC3 — documented setup/teardown/migration commands run reproducibly: the words in docs match what was actually run in the smoke test; a fresh database after migrations contains only `schema_migrations` and no speculative domain tables (triage_run, run_step, history, approval) — those come with consuming stories.


## Implementation Notes

- Runner lives at `workflow/migrate.py` on purpose: ruff/mypy already scan `workflow/`, so it gets the full quality-gate treatment without touching gate wiring; `deploy/` stays YAML+SQL only. The layer contract does not scan `deploy/` and the runner is not imported by agents — no exceptions needed. Documented in DEVELOPER.md.
- Transaction-per-file = one `conn.transaction()` block wrapping the file body + the `schema_migrations` insert, per psycopg 3 transaction docs (Context7 source above). File body executed via a single `cur.execute(sql)` — psycopg 3 sends multi-statement strings as one simple query; a mid-file statement failure aborts the transaction, nothing partial survives (rollback guarantees zero partial state).
- No advisory lock (pre-decided); the one-shot job is the only writer of `schema_migrations`, gated before workers start. If a second concurrent runner ever shows up, that is a new story with a new AD — noted, not built.
- Compose depends_on evidence: `service_completed_successfully` is a valid `depends_on` condition (Context7 /docker/compose source + fixtures); `service_healthy` under `depends_on` needs the `healthcheck` on postgres (pg_isready, standard pattern). Compose v2.27.1+ supports both (candidate version observed on this host's apt; host currently lacks the compose plugin — install step documented in USER-GUIDE/DEVELOPER).
- `postgres:18` flipped PGDATA to `/var/lib/postgresql/18/docker` with the volume at `/var/lib/postgresql` (Docker Hub note) — mounting `pgdata:/var/lib/postgresql` per the 18 image note; no local-path bind mounts.
- Placeholder worker services (`gateway`, `orchestrator`, `jev`, `analyzer`, `proposer`, `reviewer`) use `image: ...` off-the-shelf busybox/sleep stubs with correct env names — real images come with their stories (0.3 is only the foundation the epics demand).
- Secret placement is enforced by env-file names, not `secrets:` top-level mounts — env-var names in the right services are exactly what the AC inspects; Docker Compose long-form `secrets` blocks add k8s-adjacent complexity this story deliberately avoids (AD-25 says .env is the Compose secret source).
- Negative test that the repo never regresses: `.gitignore` already covers `.env`; the test suite reads `.gitignore` and asserts `.env` present — cheap guard tripwire if someone edits it later.
- mypy --strict on `workflow/migrate.py`: parameterless runner with `Database` Protocol dependency for unit fakes (L for Liskov) — unit tests use a fake connection object honoring the Protocol; the integration test uses real psycopg.
- `database` Protocol in `workflow/migrations_db.py` (I: interface segregation — one Protocol per consumer:RunLeaseStore-style small protocols elsewhere in the repo do the same), imported by `migrate.py` only.

## Spec Change Log

(empty)

## Review Triage Log

(empty)

## Verification

**Commands:**
- `make check` — expected: green, unaffected gates plus new tests, exit 0.
- `.venv/bin/pytest tests/workflow -q` — expected: AC tests green fast (no Docker).
- `.venv/bin/pytest tests/security -q` — expected: compose secret placement green, no Docker.
- `docker compose -f deploy/compose.yaml up -d --wait` — expected: healthy postgres, migration job exits 0, workers stay up; documented in DEVELOPER "Compose and migrations".
- `docker compose -f deploy/compose.yaml down` and re-`up` — migration job re-applies nothing (idempotent).
- `.venv/bin/pytest -m integration` with Docker running — full local proof not in the default make-check path.
