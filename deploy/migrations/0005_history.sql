-- Story 2.6 / AD-15: history — durable, tenant-scoped, structured-only
-- record of terminal triage outcomes. Written exactly once per run by the
-- orchestrator's HistoryStore (never by an agent), fingerprinted by sha256
-- of normalized test_id + error_type + top stack frames. No free-text
-- column: only enumerated/structured fields, ever. Forward-only, applied
-- once by workflow/migrate.py (AD-25).

CREATE TABLE history (
    row_id           uuid PRIMARY KEY,
    run_id           uuid NOT NULL,
    repo_id          bigint NOT NULL,
    test_id          text NOT NULL,
    error_type       text NOT NULL,
    top_stack_frames text[] NOT NULL,
    fingerprint      text NOT NULL,
    terminal_state   text NOT NULL,
    human_verdict    text NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),

    -- AC2: at most one terminal history row per run; write_terminal treats a
    -- UniqueViolation here as a no-op and re-selects the existing row
    -- (idempotent, AD-2 spirit) instead of taking a lease.
    CONSTRAINT uq_history_run_id UNIQUE (run_id),
    -- Exactly the TERMINAL_RUN_STATES set (workflow/run_states.py).
    CONSTRAINT ck_history_terminal_state CHECK (terminal_state IN ('DONE_PR', 'DONE_REPORT', 'REJECTED_BY_HUMAN', 'FAILED')),
    CONSTRAINT ck_history_human_verdict CHECK (human_verdict IS NULL OR human_verdict IN ('approved', 'rejected'))
);

-- Fingerprint lookup is always repo-scoped (AD-15, AC1/AC3 RT-03).
CREATE INDEX ix_history_repo_fingerprint ON history (repo_id, fingerprint);
