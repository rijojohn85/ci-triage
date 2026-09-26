"""The one Postgres adapter for steps and resume (AD-2, AD-23).

SOLID-S: the domain words live in `workflow/steps.py`; this module builds the
SQL and owns the psycopg connection. It composes story 1.2's
`RunLeaseStore.guarded_commit` — the lease re-check and the transaction
boundary stay in one place, and 2.3 supplies only the work (insert the step,
move the state). It never re-implements fencing or takes a row lock of its own.

Every `run_step` and `triage_run` query binds `repo_id` (AD-15). The unique
`(run_id, step, attempt)` identity is the database-level backstop against a
duplicate completion (AD-2). `connect` and the lease store are injectable so
unit tests drive the SQL through a fake connection and a fake lease store.
"""

import json
import uuid
from collections.abc import Callable
from datetime import datetime
from types import TracebackType
from typing import Protocol, TypeVar, cast

import psycopg

from workflow.lease_store import PostgresRunLeaseStore
from workflow.leases import Claim, LeaseConnection, LeaseLost, RunLeaseStore
from workflow.run_states import RunState
from workflow.steps import (
    ResumeView,
    StepCommit,
    StepRecord,
    StepStatus,
    StepTaskMismatchError,
    StepWriteError,
    TaskRunIdentity,
    duplicate_step_error,
)
from workflow.transitions import transition

__all__ = ["PostgresStepRecorder"]

# The state row is already locked by `guarded_commit`'s owner re-check (AD-23),
# so the read needs no row lock of its own — fencing stays in story 1.2.
_SELECT_STATE_SQL = "SELECT state FROM triage_run WHERE run_id = %s AND repo_id = %s"

_SELECT_TASK_IDENTITY_SQL = """
SELECT repo_id, workflow_run_id, run_attempt FROM triage_run
WHERE run_id = %s AND repo_id = %s
"""

_SELECT_COMPLETED_STEPS_SQL = """
SELECT step FROM run_step
WHERE run_id = %s AND repo_id = %s AND status = %s
"""

_INSERT_STEP_SQL = """
INSERT INTO run_step (step_id, run_id, repo_id, step, attempt, status, output)
VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
RETURNING created_at
"""

# `escalation_reason` moves with `state`: the migration's CHECK requires it to
# be non-null exactly when the state is AWAITING_APPROVAL (AD-1).
_ADVANCE_STATE_SQL = """
UPDATE triage_run SET state = %s, escalation_reason = %s, updated_at = now()
WHERE run_id = %s AND repo_id = %s
RETURNING run_id
"""

T = TypeVar("T")


class StepCursor(Protocol):
    def fetchone(self) -> tuple[object, ...] | None: ...
    def fetchall(self) -> list[tuple[object, ...]]: ...


class StepConnection(Protocol):
    """Smallest connection surface the resume read needs (SOLID-I)."""

    def __enter__(self) -> "StepConnection": ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> object: ...
    def execute(self, sql: str, params: tuple[object, ...] = ()) -> StepCursor: ...


def _open_connection(dsn: str) -> StepConnection:
    return psycopg.connect(dsn)


def _as_json(output: object) -> str | None:
    return None if output is None else json.dumps(output)


def _escalation_reason(commit: StepCommit) -> str | None:
    """The reason to store with the move: present only on a pause (AD-1)."""
    if commit.to_state is not RunState.AWAITING_APPROVAL:
        return None
    reason = commit.guards.escalation_reason
    return None if reason is None else reason.value


class PostgresStepRecorder:
    """I/O adapter: the step write and the state move share one guarded commit."""

    def __init__(
        self,
        dsn: str,
        connect: Callable[[str], StepConnection] | None = None,
        lease_store: RunLeaseStore | None = None,
    ) -> None:
        self._dsn = dsn
        self._connect: Callable[[str], StepConnection] = connect or _open_connection
        self._leases: RunLeaseStore = lease_store or PostgresRunLeaseStore(dsn)

    def record(self, claim: Claim, repo_id: int, commit: StepCommit) -> StepRecord:
        # The whole body runs inside 1.2's lease-guarded transaction: the
        # owner re-check, the step insert and the state move commit or roll
        # back together (AD-2, AD-23).
        return self._leases.guarded_commit(claim, self._work(claim, repo_id, commit))

    def _work(
        self, claim: Claim, repo_id: int, commit: StepCommit
    ) -> Callable[[LeaseConnection], StepRecord]:
        def work(conn: LeaseConnection) -> StepRecord:
            current = self._current_state(conn, claim, repo_id)
            if commit.task_identity is not None:
                self._validate_task_identity(conn, claim, repo_id, commit.task_identity)
            # AD-1: the move must be a row in story 2.1's table, not a raw
            # assignment. An illegal move raises before any write.
            transition(current, commit.to_state, commit.guards)
            step_id = uuid.uuid4()
            try:
                created = conn.execute(
                    _INSERT_STEP_SQL,
                    (
                        step_id,
                        claim.run_id,
                        repo_id,
                        commit.step,
                        commit.attempt,
                        commit.status.value,
                        _as_json(commit.output),
                    ),
                ).fetchone()
            except psycopg.errors.UniqueViolation as exc:
                # `(run_id, step, attempt)` is unique (AD-2): a second
                # completion of the same attempt is definitive, not transient
                # — only a violation of THIS constraint is one (shared
                # translation).
                raise duplicate_step_error(
                    exc, claim.run_id, commit.step, commit.attempt
                ) from exc
            advanced = conn.execute(
                _ADVANCE_STATE_SQL,
                (
                    commit.to_state.value,
                    _escalation_reason(commit),
                    claim.run_id,
                    repo_id,
                ),
            ).fetchone()
            if created is None or advanced is None:
                # guarded_commit already re-checked the lease, and the run row
                # was read in this transaction, so a missing insert/update
                # result is a data-integrity fault, never a lost lease.
                raise StepWriteError(claim.run_id, commit.step)
            return StepRecord(
                step_id=step_id,
                run_id=claim.run_id,
                repo_id=repo_id,
                step=commit.step,
                attempt=commit.attempt,
                status=commit.status,
                output=commit.output,
                created_at=cast(datetime, created[0]),
            )

        return work

    def _validate_task_identity(
        self,
        conn: LeaseConnection,
        claim: Claim,
        repo_id: int,
        identity: TaskRunIdentity,
    ) -> None:
        # AD-15: the locked run must be the task whose evidence was read;
        # repository scope alone does not distinguish runs or attempts.
        row = conn.execute(
            _SELECT_TASK_IDENTITY_SQL, (claim.run_id, repo_id)
        ).fetchone()
        expected = (identity.repo_id, identity.workflow_run_id, identity.run_attempt)
        if identity.repo_id != repo_id or row != expected:
            raise StepTaskMismatchError(claim.run_id)

    def _current_state(
        self, conn: LeaseConnection, claim: Claim, repo_id: int
    ) -> RunState:
        row = conn.execute(_SELECT_STATE_SQL, (claim.run_id, repo_id)).fetchone()
        if row is None:
            # The run is not in this tenant scope; the owner may not commit
            # here (AD-15). Definitive, like a lost lease (AD-22).
            raise LeaseLost(claim.run_id, claim.owner)
        return RunState(str(row[0]))

    def resume(self, run_id: uuid.UUID, repo_id: int) -> ResumeView | None:
        with self._connect(self._dsn) as conn:
            state_row = conn.execute(_SELECT_STATE_SQL, (run_id, repo_id)).fetchone()
            if state_row is None:
                return None
            step_rows = conn.execute(
                _SELECT_COMPLETED_STEPS_SQL,
                (run_id, repo_id, StepStatus.COMPLETED.value),
            ).fetchall()
        return ResumeView(
            state=RunState(str(state_row[0])),
            completed_steps=frozenset(str(row[0]) for row in step_rows),
        )
