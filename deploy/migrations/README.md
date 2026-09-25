deploy/migrations/ — forward-only SQL migrations (story 0.3, AD-25).

Rules:

- One `.sql` file per schema change, named `NNNN_short_description.sql` with a
  zero-padded, monotonically increasing integer (e.g. `0001_...`). The filename
  sort defines the apply order; never rename a file that already shipped.
- Files are applied by `workflow/migrate.py` (one-shot `migrate` service in
  `deploy/compose.yaml`), each in exactly one transaction, tracked in
  `schema_migrations`. Applied files never rerun. A failing file leaves no
  partial state (transaction rolls back) and makes the compose job exit
  non-zero, so dependent workers never start on a broken schema (AC1).
- Startup (fresh DB) initialises `schema_migrations`; no other bootstrap.
- Domain tables arrive with their consuming stories: `triage_run` with story
  2.1 (`0001_triage_run.sql`, the AD-1/AD-4/AD-17 run-state owner);
  `webhook_delivery` with story 1.1 (`0002_webhook_delivery.sql`, the AD-17
  delivery-replay record) — it does not own or alter `triage_run`. Story 1.2
  alters `triage_run` (`0003_triage_run_lease.sql`) to add the AD-23 worker
  lease columns (`lease_owner`, `lease_until`) and their claim index. `run_step`,
  `history` and the punch-out table later. No `a2a-db` /
  DatabaseTaskStore schema (AD-4, story 2.4 owns its persistence).

Apply locally:

    docker compose --project-directory . -f deploy/compose.yaml up -d --wait postgres
    docker compose --project-directory . -f deploy/compose.yaml run --rm migrate
    # inspect: docker compose --project-directory . -f deploy/compose.yaml exec postgres \
    #   psql -U triage -d triage -c 'SELECT * FROM schema_migrations'
