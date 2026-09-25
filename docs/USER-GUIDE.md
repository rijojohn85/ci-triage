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

## Install the GitHub App on a repository (story 0.4)

Works today for the demo repository
[`rijojohn85-dev/triage-demo-py`](https://github.com/rijojohn85-dev/triage-demo-py);
edge cases beyond it land with story 1.1. Setup lives on GitHub; identifiers
below are recorded in [test-data/demo-repo.md](../test-data/demo-repo.md).

1. **Create/proxy the webhook channel**: open https://smee.io/new and copy
   the channel URL — that URL *is* the webhook URL; it is not a secret.
2. **Register the App** at https://github.com/settings/apps/new:
   - name, homepage URL of the repository, "Any account" install scope;
   - **Webhook**: Active, URL = the smee channel formed above, with a
     locally generated secret — the secret goes into `.env`
     (`GITHUB_WEBHOOK_SECRET`), never into chat or the repo;
   - **Repository permissions** exactly: Actions read-only, Checks
     read-only, Contents read *and* write, Pull requests read and write,
     Issues read and write, **Workflows: No access** (never grant it —
     AD-16). GitHub auto-adds `metadata` (and `statuses`), which are
     platform-implied, not requested;
   - **Organization permissions**: Members read-only (this is the
     permission story 1.1 uses to authorise CODEOWNER decisions);
   - **Subscribe to events**: Workflow run + Issue comment;
   - after creation, *Private keys → Generate a private key* and put the
     PEM into `.env` (`GITHUB_APP_PRIVATE_KEY`) — keep the file outside
     any repo tree.
3. **Install**: from the App's page choose *Install GitHub App* → your
   organization → **Only select repositories** → the demo repo. Record the
   installation ID shown at `https://github.com/settings/installations`.
4. Creating a repository ruleset (1 approval + code-owner review, no
   force-push/deletion, App not a bypass actor) is an admin step, currently
   done from `scripts/ruleset-seed.json`; UI-driven setup follows later.
5. The private key, webhook secret and IDs (`GITHUB_APP_ID`,
   `GITHUB_APP_INSTALLATION_ID`) live only in `.env` (names listed in
   `.env.example`); verify your install with
   `python scripts/verify_demo_repo.py`.

The locally running intake behind the tunnel is story 1.1; until then
webhook deliveries pile up in the smee channel only.

## Sections

| Section | Available after |
| --- | --- |
| Run it locally (Compose) | done (story 0.3) |
| Install the GitHub App on a repository | done (story 0.4); intake around it lands with story 1.1 |
| Reading a draft PR or infra report | story 2.11 |
| Approving or rejecting a paused triage | Epic 5 |
| Configuration | to be decided by the stories that add settings |
