# User guide — Blameless CI Triage

How to install and use the tool. This file describes only what works on `main` today; each story that changes user-visible behaviour updates it in the same PR (AGENTS.md "How work is done", step 7).

**Current status:** the local service foundation works (Epic 0). Postgres starts and is migrated by a one-shot job; no product workflows yet. Sections below fill in as their stories land.

## What the tool will do

When a GitHub Actions run fails on a repository where the GitHub App is installed, the tool works out why and answers with one of:

- a **draft pull request** with a proposed fix (never merged automatically);
- an **infra report** issue for on-call, when the CI machine rather than the code broke;
- a **pause for a human**, when it is unsure or the fix is risky; a CODEOWNER then approves or rejects.

It never blames a person without evidence.

## Run it locally (story 0.3)

Requirements: Docker with the Compose plugin (`docker compose version` prints ≥ 2.27), Python ≥ 3.10 with `psycopg 3.3.6` available (`.venv` from `bash scripts/bootstrap.sh`).

1. Copy the sample env file and fill in the names it lists (only `POSTGRES_PASSWORD` is needed for the database to start):

   ```bash
   cp .env.example .env
   # edit .env — set POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB
   ```

2. Start PostgreSQL 18 and let the one-shot migration job initialise the database:

   ```bash
   docker compose --project-directory . -f deploy/compose.yaml up -d --wait
   ```

   `--wait` returns once postgres is healthy and the migrate job exited successfully (exit 0).

3. Verify:

   ```bash
   docker compose --project-directory . -f deploy/compose.yaml exec postgres \
     psql -U triage -d triage -c 'SELECT * FROM schema_migrations;'
   ```

4. Re-running migrations (after new `.sql` files land in `deploy/migrations/`):

   ```bash
   docker compose --project-directory . -f deploy/compose.yaml run --rm migrate
   ```

   Applied migrations never re-apply (idempotent); a failing migration exits non-zero and dependent services never start.

5. Tear down:

   ```bash
   docker compose --project-directory . -f deploy/compose.yaml down -v   # -v also drops the database volume
   ```

Webhook intake, agents, and triage runs are not started yet (stories 0.4+).

## Sections

| Section | Available after |
| --- | --- |
| Section | Status |
| --- | --- |
| Run it locally (Compose) | done (story 0.3) |
| Install the GitHub App on a repository | stories 0.4, 1.1 |
| Reading a draft PR or infra report | story 2.11 |
| Approving or rejecting a paused triage | Epic 5 |
| Configuration | to be decided by the stories that add settings |
