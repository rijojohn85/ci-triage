-- Story 2.6 / AD-15: pr_feedback — post-terminal human feedback on an
-- opened PR, held in its own table so free text can never reach `history`
-- and poison agent evidence (AC3, RT-04). Forward-only, applied once by
-- workflow/migrate.py (AD-25).

CREATE TABLE pr_feedback (
    feedback_id   uuid PRIMARY KEY,
    run_id        uuid NOT NULL REFERENCES triage_run (run_id),
    repo_id       bigint NOT NULL,
    pr_number     integer NOT NULL,
    feedback_text text NOT NULL,
    author_login  text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- Every pr_feedback read/write is repo-scoped (AD-15).
CREATE INDEX ix_pr_feedback_repo_run ON pr_feedback (repo_id, run_id);
