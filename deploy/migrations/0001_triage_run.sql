-- Story 2.1 / AD-17: the first domain table — triage_run owns run state.
-- Forward-only, applied once by workflow/migrate.py (AD-25). No FK on
-- proposal_step_id in v1: the story owning the human-decision table binds it.

CREATE TABLE triage_run (
    run_id            uuid PRIMARY KEY,
    repo_id           bigint NOT NULL,
    workflow_run_id   bigint NOT NULL,
    run_attempt       integer NOT NULL,
    state             text NOT NULL,
    escalation_reason text,
    proposal_step_id  uuid NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),

    -- AD-17 run identity: one run per repo/workflow/attempt
    CONSTRAINT uq_triage_run_identity UNIQUE (repo_id, workflow_run_id, run_attempt),

    -- AD-1: state closed over the 14 states; AWAITING_APPROVAL carries
    -- exactly one escalation reason; no reason without its pause state.
    CONSTRAINT ck_triage_run_state CHECK (state IN ('RECEIVED', 'DISTILLING', 'CLASSIFYING', 'ANALYZING', 'PROPOSING', 'REVIEWING', 'GATING', 'AWAITING_APPROVAL', 'PR_OPENING', 'REPORTING', 'DONE_PR', 'DONE_REPORT', 'REJECTED_BY_HUMAN', 'FAILED')),
    CONSTRAINT ck_triage_run_escalation_reason CHECK (escalation_reason IS NULL OR escalation_reason IN ('low_confidence', 'unknown_class', 'no_route', 'validation_failed', 'review_rejected', 'gate_blocked')),
    CONSTRAINT ck_triage_run_escalation_iff_state CHECK ((state = 'AWAITING_APPROVAL') = (escalation_reason IS NOT NULL))
);
