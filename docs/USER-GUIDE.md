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

   The failure classifier (Jev) is reached through [OpenRouter](https://openrouter.ai/settings/keys).
   Put your OpenRouter API key in `TYPESAFE_API_KEY` and set
   `TYPESAFE_BASE_URL=https://openrouter.ai/api` (no trailing path). Compose fills in that address
   by itself; scripts and evals you run outside Compose need it in `.env`.

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

## Rotating the webhook secret (story 1.3)

The gateway accepts a comma-separated list of secrets in
`GITHUB_WEBHOOK_SECRET` (see `.env.example`), so a rotation never needs a
code change or downtime — only a config edit and a restart, in three steps:

1. **Add the new secret alongside the old one.** Generate a new random
   secret value, then set `GITHUB_WEBHOOK_SECRET=<old-value>,<new-value>` in
   `.env` (old first, new second — order does not matter to the gateway, but
   keeping it consistent avoids confusion later). Restart the gateway:
   `docker compose -f deploy/compose.yaml up -d --wait gateway`. Both
   secrets are now accepted — this is the *overlap* phase.
2. **Point GitHub at the new secret and verify overlap.** In the App's
   settings (https://github.com/settings/apps), update the webhook secret
   to the new value and save. Trigger a test delivery (GitHub's *Redeliver*
   button on a recent delivery, or a fresh CI failure) and confirm the
   gateway answers `202`/`200`, not `401`. Deliveries signed with either the
   old or the new secret succeed during this window.
3. **Retire the old secret.** Once you have confirmed new deliveries are
   arriving signed with the new secret, remove the old value from `.env` so
   it holds only `GITHUB_WEBHOOK_SECRET=<new-value>`, then restart the
   gateway again. From this point a delivery signed with the old secret is
   rejected with `401`.

No admin endpoint exists for this and none is planned — rotation is always
a `.env` edit plus a restart (AD-25).

## When a run is shown without names (story 4.1)

The read-only task view (the A2A endpoint that shows a run's saved artifacts)
never shows who wrote a suspect commit while the tool is not sure enough:
everything it serves is **blame-free** — no `author_login` anywhere — when the
run is waiting for a human, when it is writing its report, when its confidence
sits below the tool's own "how sure is sure enough" line, or when that
confidence cannot be read at all. The evidence itself (commit ids, messages,
log lines) is untouched; only the person's name is held back. Once a run is
sure enough and not in a human-facing state, the author names on the served
commits are shown again, because blame then has cited evidence behind it.

## Sections

| Section | Available after |
| --- | --- |
| Run it locally (Compose) | done (story 0.3) |
| Install the GitHub App on a repository | done (story 0.4); intake around it lands with story 1.1 |
| Rotating the webhook secret | done (story 1.3) |
| When a run is shown without names | done (story 4.1) |
| Reading a draft PR or infra report | story 2.11 |
| Approving or rejecting a paused triage | Epic 5 |
| Configuration | to be decided by the stories that add settings |

## Reading the evidence pack (story 2.7)

An evidence pack contains the numbered error lines, the baseline commit,
all actual commits between that baseline and the failed run's fixed head,
ranked candidate commits, matching structured history and measured job
running times. The baseline is the latest earlier success of the same
workflow on the same branch; if none exists, it uses the default branch.
Only commits that changed a stack-frame file or a directly imported test
module become candidates. Runner checkout paths are matched to repository
files before looking for imports. A candidate is a lead to investigate, not a
verdict. An empty comparison has no commits or candidates.

The pack is saved with the run's completed `distill` step and appears in the
existing read-only task artifacts. Use line numbers, full commit SHAs,
history row IDs and metric names to locate the supporting facts. Raw setup
logs and installation tokens are kept out of the pack. Text inside the pack
is evidence to inspect, including any hostile instructions in commit
messages; it must never be treated as instructions to follow.

Collection is currently a Python entrypoint for the orchestrator:
`EvidenceCollector.collect_and_persist(CollectionRequest(...))`. It needs the
accepted task identity, a current worker claim and configured read/token/
history/step services; the [developer guide](DEVELOPER.md#deterministic-evidence-collection-story-27)
explains the wiring and test commands. The worker must already be in
`DISTILLING`; successful saving moves it to `CLASSIFYING`. Saving also checks
that the leased database run is the same repository, workflow run and attempt
as the collected evidence; a mismatch saves nothing. There is no new
CLI command or automatic agent analysis yet, and the Compose orchestrator
remains a placeholder.
