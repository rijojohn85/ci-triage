-- Story 6.1 / AD-18: every model call is auditable on its `run_step` row.
-- Forward-only, applied once by workflow/migrate.py (AD-25). Adds ONLY the
-- audit fields this story needs: the model, its token counters (all NULLable —
-- NULL means "provider did not report", never 0) and the closed outcome set.
-- No cost columns: 6.2 owns costing. Attempt rows keep the existing
-- `status` CHECK (completed/failed) and the `(run_id, step, attempt)` unique
-- identity (AD-2); they are bookkeeping only and never move the run's
-- state (AD-23).

ALTER TABLE run_step
    ADD COLUMN model                          text NULL,
    ADD COLUMN input_tokens                   integer NULL,
    ADD COLUMN output_tokens                  integer NULL,
    ADD COLUMN cache_read_input_tokens        integer NULL,
    ADD COLUMN cache_creation_input_tokens_5m integer NULL,
    ADD COLUMN cache_creation_input_tokens_1h integer NULL,
    ADD COLUMN outcome                        text NULL,

    -- AD-18: the outcome is a closed enum, never free text.
    ADD CONSTRAINT ck_run_step_outcome
        CHECK (outcome IN ('verdict', 'error', 'timeout'));
