"""Story 2.3 integration tests — real postgres:18 via Docker (AC1/AC2/AC3).

Proves the AD-2 atomic fact against the real database: the `run_step` insert
and the `triage_run.state` move commit together (a fault between them rolls
both back), a reclaimed run reads its current state and finished steps, every
read is repo-scoped, and a stale owner's guarded commit persists nothing.

The fault-injection test forces the second of the two writes to fail with a
real database trigger, so no test hook enters production code. Needs Docker on
the host; marked `integration` and excluded from `make check`. Run explicitly:

    .venv/bin/pytest -m integration tests/workflow/test_step_integration.py -q
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from itertools import count
from pathlib import Path
from typing import Final

import psycopg
import pytest

from contracts.enums import EscalationReason, FailureClass
from workflow import migrate
from workflow.ids import new_run_id
from workflow.lease_store import PostgresRunLeaseStore
from workflow.leases import Claim, LeaseLost
from workflow.run_states import RunState
from workflow.step_store import PostgresStepRecorder
from workflow.steps import StepCommit, StepStatus
from workflow.transitions import GuardInput

pytestmark = pytest.mark.integration

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR: Final[Path] = REPO_ROOT / "deploy" / "migrations"
LEASE_SECONDS = 300
REPO_ID = 42
OTHER_REPO_ID = 99
_WORKFLOW_RUN_IDS = count(5001)

EXPECTED_STEP_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "step_id",
        "run_id",
        "repo_id",
        "step",
        "attempt",
        "status",
        "output",
        "created_at",
    }
)


def migrated(dsn: str) -> int:
    with psycopg.connect(dsn, autocommit=True) as conn:
        return migrate.apply_pending_files(
            migrate.PsycopgMigrationConnection(conn), MIGRATIONS_DIR
        )


def insert_run(
    dsn: str,
    run_id: uuid.UUID,
    state: RunState = RunState.RECEIVED,
    repo_id: int = REPO_ID,
) -> None:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO triage_run (run_id, repo_id, workflow_run_id, "
            "run_attempt, state) VALUES (%s, %s, %s, %s, %s)",
            (run_id, repo_id, next(_WORKFLOW_RUN_IDS), 1, state.value),
        )


def query(dsn: str, sql: str, params: tuple[object, ...] = ()) -> list[tuple]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def current_state(dsn: str, run_id: uuid.UUID) -> str:
    return str(
        query(dsn, "SELECT state FROM triage_run WHERE run_id = %s", (run_id,))[0][0]
    )


def escalation_reason(dsn: str, run_id: uuid.UUID) -> str | None:
    value = query(
        dsn, "SELECT escalation_reason FROM triage_run WHERE run_id = %s", (run_id,)
    )[0][0]
    return None if value is None else str(value)


def step_rows(dsn: str, run_id: uuid.UUID) -> list[tuple]:
    return query(
        dsn,
        "SELECT step, attempt, status, output FROM run_step "
        "WHERE run_id = %s ORDER BY step",
        (run_id,),
    )


def claim_run(dsn: str, run_id: uuid.UUID) -> Claim:
    claim = PostgresRunLeaseStore(dsn).claim_next(lease_seconds=LEASE_SECONDS)
    assert claim is not None and claim.run_id == run_id
    return claim


def lease_run(dsn: str, run_id: uuid.UUID, owner: str = "approval-handler") -> Claim:
    """Lease a specific run directly.

    `claim_next` deliberately excludes a paused run (AD-1), so the approval
    path — which acts on one known run — leases it by id. This helper stands in
    for that path until the punch-out story supplies it.
    """
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE triage_run SET lease_owner = %s, "
            "lease_until = now() + interval '5 minutes' WHERE run_id = %s",
            (owner, run_id),
        )
    return Claim(run_id, owner, datetime.now(timezone.utc) + timedelta(minutes=5))


def expire_lease(dsn: str, run_id: uuid.UUID) -> None:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE triage_run SET lease_until = now() - interval '1 second' "
            "WHERE run_id = %s",
            (run_id,),
        )


def test_ac1_commit_records_step_and_advances_state(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_run(pg_dsn, run_id)
    claim = claim_run(pg_dsn, run_id)

    record = PostgresStepRecorder(pg_dsn).record(
        claim,
        REPO_ID,
        StepCommit(
            step="distill",
            to_state=RunState.DISTILLING,
            output={"distilled": True},
        ),
    )

    assert record.run_id == run_id and record.repo_id == REPO_ID
    assert current_state(pg_dsn, run_id) == RunState.DISTILLING.value
    rows = step_rows(pg_dsn, run_id)
    assert len(rows) == 1
    step, attempt, status, output = rows[0]
    assert (step, attempt, status) == ("distill", 1, StepStatus.COMPLETED.value)
    assert output == {"distilled": True}


def test_ac1_fault_between_step_write_and_state_write_rolls_back_both(
    pg_dsn: str,
) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_run(pg_dsn, run_id)
    claim = claim_run(pg_dsn, run_id)

    # Force the second write (the state UPDATE) to fail at the database, after
    # the step INSERT has already run: the whole transaction must roll back.
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        conn.execute(
            "CREATE FUNCTION it_fail_state() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'forced state write failure'; END; $$ "
            "LANGUAGE plpgsql"
        )
        conn.execute(
            "CREATE TRIGGER it_fail_state BEFORE UPDATE OF state ON triage_run "
            "FOR EACH ROW EXECUTE FUNCTION it_fail_state()"
        )

    with pytest.raises(psycopg.Error):
        PostgresStepRecorder(pg_dsn).record(
            claim,
            REPO_ID,
            StepCommit(step="distill", to_state=RunState.DISTILLING),
        )

    assert step_rows(pg_dsn, run_id) == [], "the step insert rolled back"
    assert current_state(pg_dsn, run_id) == RunState.RECEIVED.value, (
        "the state move rolled back too"
    )


def test_ac1_commit_into_pause_writes_the_escalation_reason(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_run(pg_dsn, run_id, state=RunState.CLASSIFYING)
    claim = claim_run(pg_dsn, run_id)

    PostgresStepRecorder(pg_dsn).record(
        claim,
        REPO_ID,
        StepCommit(
            step="classify",
            to_state=RunState.AWAITING_APPROVAL,
            guards=GuardInput(escalation_reason=EscalationReason.UNKNOWN_CLASS),
        ),
    )

    # The CHECK ck_triage_run_escalation_iff_state passes because the reason
    # moved with the state in the same UPDATE.
    assert current_state(pg_dsn, run_id) == RunState.AWAITING_APPROVAL.value
    assert escalation_reason(pg_dsn, run_id) == EscalationReason.UNKNOWN_CLASS.value


def test_ac1_commit_out_of_pause_clears_the_escalation_reason(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        # AD-1: a paused run is not valid without its reason, so seed both.
        cur.execute(
            "INSERT INTO triage_run (run_id, repo_id, workflow_run_id, run_attempt, "
            "state, escalation_reason) VALUES (%s, %s, %s, 1, %s, %s)",
            (
                run_id,
                REPO_ID,
                next(_WORKFLOW_RUN_IDS),
                RunState.AWAITING_APPROVAL.value,
                EscalationReason.UNKNOWN_CLASS.value,
            ),
        )
    # The approval path leases the specific paused run by id (claim_next
    # excludes paused runs, AD-1); this proves the recorder clears the reason.
    claim = lease_run(pg_dsn, run_id)

    PostgresStepRecorder(pg_dsn).record(
        claim,
        REPO_ID,
        StepCommit(
            step="approve",
            to_state=RunState.ANALYZING,
            guards=GuardInput(decision="approve", class_override=FailureClass.CODE),
        ),
    )

    assert current_state(pg_dsn, run_id) == RunState.ANALYZING.value
    assert escalation_reason(pg_dsn, run_id) is None, "leaving the pause clears it"


def test_ac2_failed_step_is_not_a_completed_step(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_run(pg_dsn, run_id)
    recorder = PostgresStepRecorder(pg_dsn)
    claim = claim_run(pg_dsn, run_id)

    recorder.record(
        claim, REPO_ID, StepCommit(step="distill", to_state=RunState.DISTILLING)
    )
    recorder.record(
        claim,
        REPO_ID,
        StepCommit(
            step="classify",
            to_state=RunState.CLASSIFYING,
            status=StepStatus.FAILED,
            output="boom",
        ),
    )

    view = recorder.resume(run_id, REPO_ID)
    assert view is not None
    assert view.completed_steps == frozenset({"distill"}), (
        "a failed attempt is recorded but is not a completion (AD-22, AD-2)"
    )
    statuses = {
        str(row[0]): str(row[1])
        for row in query(
            pg_dsn,
            "SELECT step, status FROM run_step WHERE run_id = %s ORDER BY step",
            (run_id,),
        )
    }
    assert statuses == {"distill": "completed", "classify": "failed"}


def test_ac2_resume_skips_completed_step(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_run(pg_dsn, run_id)
    recorder = PostgresStepRecorder(pg_dsn)
    first = claim_run(pg_dsn, run_id)
    recorder.record(
        first,
        REPO_ID,
        StepCommit(step="distill", to_state=RunState.DISTILLING),
    )

    # The worker crashed; its lease expires and a new owner reclaims the run.
    expire_lease(pg_dsn, run_id)
    second = claim_run(pg_dsn, run_id)
    assert second.owner != first.owner

    view = recorder.resume(run_id, REPO_ID)

    assert view is not None
    assert view.state is RunState.DISTILLING, "re-enters at its current state (AD-2)"
    assert view.is_completed("distill") is True, "completed step is not re-run"
    assert view.completed_steps == frozenset({"distill"})


def test_ac2_queries_are_repo_scoped(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_run(pg_dsn, run_id)
    claim = claim_run(pg_dsn, run_id)
    PostgresStepRecorder(pg_dsn).record(
        claim,
        REPO_ID,
        StepCommit(step="distill", to_state=RunState.DISTILLING),
    )

    recorder = PostgresStepRecorder(pg_dsn)
    assert recorder.resume(run_id, OTHER_REPO_ID) is None, "no cross-repo reads (AD-15)"
    assert recorder.resume(run_id, REPO_ID) is not None


def test_ac2_migration_adds_only_needed_fields(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0

    columns = query(
        pg_dsn,
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'run_step'",
    )
    names = {str(row[0]) for row in columns}
    assert names == EXPECTED_STEP_COLUMNS, "no model/token/cost or evidence fields"
    for forbidden in ("model", "token", "cost", "evidence", "price"):
        assert not any(forbidden in name for name in names), forbidden

    definitions = [
        str(row[0])
        for row in query(
            pg_dsn,
            "SELECT indexdef FROM pg_indexes WHERE tablename = 'run_step'",
        )
    ]
    assert any("run_id" in d and "repo_id" in d for d in definitions), (
        "the resume read is served by a repo/run index (AD-2, AD-15)"
    )


def test_ac3_stale_owner_commit_discarded(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_run(pg_dsn, run_id)
    recorder = PostgresStepRecorder(pg_dsn)
    stale = claim_run(pg_dsn, run_id)

    expire_lease(pg_dsn, run_id)
    fresh = claim_run(pg_dsn, run_id)
    assert fresh.owner != stale.owner

    with pytest.raises(LeaseLost):
        recorder.record(
            stale,
            REPO_ID,
            StepCommit(step="distill", to_state=RunState.DISTILLING),
        )

    assert step_rows(pg_dsn, run_id) == [], "no step row from the stale owner"
    assert current_state(pg_dsn, run_id) == RunState.RECEIVED.value, (
        "no state change from the stale owner"
    )


def test_ac3_discarded_result_absent_from_run_step_and_completed(
    pg_dsn: str,
) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_run(pg_dsn, run_id)
    recorder = PostgresStepRecorder(pg_dsn)
    stale = claim_run(pg_dsn, run_id)
    expire_lease(pg_dsn, run_id)
    fresh = claim_run(pg_dsn, run_id)

    with pytest.raises(LeaseLost):
        recorder.record(
            stale,
            REPO_ID,
            StepCommit(step="stale-step", to_state=RunState.DISTILLING),
        )

    # The new owner proceeds and commits its own step; the discarded result
    # never appears as an accepted step or in the resume view.
    recorder.record(
        fresh,
        REPO_ID,
        StepCommit(step="fresh-step", to_state=RunState.DISTILLING),
    )
    view = recorder.resume(run_id, REPO_ID)
    assert view is not None
    assert view.completed_steps == frozenset({"fresh-step"})
    assert "stale-step" not in [row[0] for row in step_rows(pg_dsn, run_id)]


def test_0004_migration_applies_and_unique_identity_blocks_duplicate_step(
    pg_dsn: str,
) -> None:
    expected = len(migrate.read_migrations(MIGRATIONS_DIR))
    assert migrated(pg_dsn) == expected
    assert migrated(pg_dsn) == 0, "forward-only: never rerun (AD-25)"

    run_id = new_run_id()
    insert_run(pg_dsn, run_id)
    insert_step = (
        "INSERT INTO run_step "
        "(step_id, run_id, repo_id, step, attempt, status, output) "
        "VALUES (gen_random_uuid(), %s, %s, 'distill', 1, 'completed', %s::jsonb)"
    )
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(insert_step, (run_id, REPO_ID, json.dumps({"n": 1})))
        with pytest.raises(psycopg.errors.UniqueViolation):
            # same (run_id, step, attempt) identity is the DB backstop (AD-2)
            cur.execute(insert_step, (run_id, REPO_ID, json.dumps({"n": 2})))
