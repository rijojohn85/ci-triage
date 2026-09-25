-- Story 2.3 / AD-2: one row per finished step, written in the same
-- lease-guarded transaction as the `triage_run.state` move (AD-23). Forward-only,
-- applied once by workflow/migrate.py (AD-25).
--
-- Only the fields resume needs now: identity, tenant scope, the step name and
-- attempt, its status, its output and when it was written. Model/token/cost
-- columns arrive with stories 6.1/6.2 (AD-18); evidence-pack fields with 2.7.
-- The unique `(run_id, step, attempt)` identity is the database-level backstop
-- against a duplicate completion.

CREATE TABLE run_step (
    step_id    uuid PRIMARY KEY,
    run_id     uuid NOT NULL REFERENCES triage_run (run_id),
    repo_id    bigint NOT NULL,
    step       text NOT NULL,
    attempt    integer NOT NULL,
    status     text NOT NULL,
    output     jsonb NULL,
    created_at timestamptz NOT NULL DEFAULT now(),

    -- AD-2: one (run, step, attempt) may complete at most once.
    CONSTRAINT uq_run_step_identity UNIQUE (run_id, step, attempt),
    CONSTRAINT ck_run_step_attempt_positive CHECK (attempt >= 1),
    CONSTRAINT ck_run_step_status CHECK (status IN ('completed', 'failed'))
);

-- Resume reads the current state and the completed steps of one run in one
-- repo; this index serves that repo-scoped lookup (AD-2, AD-15).
CREATE INDEX ix_run_step_run_repo ON run_step (run_id, repo_id);
