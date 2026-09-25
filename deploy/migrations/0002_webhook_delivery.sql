-- Story 1.1 / AD-17: delivery-level replay dedupe for gateway intake.
-- Forward-only, applied once by workflow/migrate.py (AD-25). The run
-- identity itself is enforced by uq_triage_run_identity in 0001; this
-- table only remembers which GitHub delivery ids have been seen so a
-- replay is a 2xx no-op.

CREATE TABLE webhook_delivery (
    delivery_id       text PRIMARY KEY,
    repo_id           bigint NOT NULL,
    workflow_run_id   bigint NOT NULL,
    run_attempt       integer NOT NULL,
    received_at       timestamptz NOT NULL DEFAULT now()
);
