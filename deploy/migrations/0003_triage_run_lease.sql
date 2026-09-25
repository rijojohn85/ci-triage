-- Story 1.2 / AD-23: worker lease + fencing columns on triage_run.
-- Forward-only, applied once by workflow/migrate.py (AD-25). A claim selects
-- rows with no lease or an expired one using FOR UPDATE SKIP LOCKED in a
-- short transaction; a step-commit re-checks lease_owner and discards on
-- mismatch. Leased rows stay in their current state (AD-1): this migration
-- adds no new state and the claim never writes `state`.

ALTER TABLE triage_run
    ADD COLUMN lease_owner text NULL,
    ADD COLUMN lease_until timestamptz NULL;

-- The claim filters on lease availability; index it so a busy queue keeps a
-- cheap "is this row unleased/expired" probe (AD-23).
CREATE INDEX ix_triage_run_lease_until ON triage_run (lease_until);
