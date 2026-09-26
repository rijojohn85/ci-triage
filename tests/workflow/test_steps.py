"""Story 2.3 unit tests — step persistence and resume (AC1/AC2/AC3, AD-2).

The Postgres boundary is driven through two small Protocol fakes (AGENTS.md
"TDD": I/O boundaries tested against Protocol fakes in unit tests; the real
adapter runs in the marked integration tests). The lease store is faked so the
fencing decision stays in story 1.2; here we only prove that the recorder
supplies the step insert and the state move to that one guarded transaction,
and that a missing/other-tenant run is never written.

No test touches a database; `created_at` is scripted.
"""

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Final

import psycopg
import pytest

from contracts.enums import EscalationReason, FailureClass
from workflow.leases import Claim, LeaseLost
from workflow.run_states import RunState
from workflow.step_store import PostgresStepRecorder
from workflow.steps import (
    DuplicateStepError,
    ResumeView,
    StepCommit,
    StepRecord,
    StepStatus,
    StepWriteError,
)
from workflow.transitions import GuardInput, IllegalTransition

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
CREATED_AT = datetime(2026, 9, 26, 12, 0, 1, tzinfo=timezone.utc)
LEASE_SECONDS = 300
REPO_ID = 7
SECOND_ATTEMPT = 2
MIGRATION: Final[Path] = (
    Path(__file__).resolve().parents[2] / "deploy" / "migrations" / "0004_run_step.sql"
)


class FakeCursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def fetchone(self) -> tuple[object, ...] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self._rows)


class FakeConnection:
    """One scripted result list per `execute`; records SQL and bound params."""

    def __init__(self, *results: list[tuple[object, ...]]) -> None:
        self._results = list(results)
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> FakeCursor:
        self.calls.append((sql, params))
        rows = self._results.pop(0) if self._results else []
        return FakeCursor(rows)


class InsertRaisesConnection(FakeConnection):
    """Raises on the `run_step` insert, as the unique index would (AD-2)."""

    def __init__(self, error: BaseException) -> None:
        super().__init__([(RunState.RECEIVED.value,)])
        self._error = error

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> FakeCursor:
        if sql.lstrip().startswith("INSERT"):
            self.calls.append((sql, params))
            raise self._error
        return super().execute(sql, params)


class IdentityViolation(psycopg.errors.UniqueViolation):
    """A UniqueViolation whose `diag` names a chosen constraint."""

    def __init__(self, constraint_name: str) -> None:
        super().__init__(f'duplicate key ... "{constraint_name}"')
        self._constraint_name = constraint_name

    @property
    def diag(self) -> object:  # type: ignore[override]
        return SimpleNamespace(constraint_name=self._constraint_name)


class FakeLeaseStore:
    """The one `guarded_commit` call the recorder composes (AD-23).

    `owner_ok=False` models a stale owner: story 1.2's guard raises before the
    work ever runs, so the fake must never invoke it either.
    """

    def __init__(self, connection: FakeConnection, owner_ok: bool = True) -> None:
        self.connection = connection
        self.owner_ok = owner_ok
        self.commits: list[Claim] = []

    def claim_next(self, *, lease_seconds: int) -> Claim | None:
        raise NotImplementedError

    def renew(self, claim: Claim, *, lease_seconds: int) -> bool:
        raise NotImplementedError

    def guarded_commit(self, claim: Claim, work: object) -> object:
        self.commits.append(claim)
        if not self.owner_ok:
            raise LeaseLost(claim.run_id, claim.owner)
        return work(self.connection)  # type: ignore[operator]


def claim_for(run_id: uuid.UUID) -> Claim:
    return Claim(run_id, "owner-a", NOW + timedelta(seconds=LEASE_SECONDS))


def recorder_against(
    connection: FakeConnection, owner_ok: bool = True
) -> tuple[PostgresStepRecorder, FakeLeaseStore]:
    leases = FakeLeaseStore(connection, owner_ok=owner_ok)
    store = PostgresStepRecorder(
        "postgresql://unused", connect=lambda _dsn: connection, lease_store=leases
    )
    return store, leases


def params_of(call: tuple[str, tuple[object, ...]]) -> tuple[object, ...]:
    return call[1]


class TestRecord:
    def test_ac1_commit_records_step_and_advances_state(self) -> None:
        run_id = uuid.uuid4()
        connection = FakeConnection(
            [(RunState.RECEIVED.value,)],  # current state read
            [(CREATED_AT,)],  # INSERT ... RETURNING created_at
            [(run_id,)],  # UPDATE ... RETURNING run_id
        )
        store, leases = recorder_against(connection)

        record = store.record(
            claim_for(run_id),
            REPO_ID,
            StepCommit(
                step="distill",
                to_state=RunState.DISTILLING,
                attempt=SECOND_ATTEMPT,
                status=StepStatus.COMPLETED,
                output={"lines": 3},
            ),
        )

        assert isinstance(record, StepRecord)
        assert record.run_id == run_id
        assert record.repo_id == REPO_ID
        assert record.step == "distill"
        assert record.attempt == SECOND_ATTEMPT
        assert record.status is StepStatus.COMPLETED
        assert record.output == {"lines": 3}
        assert record.created_at == CREATED_AT
        assert len(leases.commits) == 1, "one lease-guarded transaction (AD-2)"

        select_sql, select_params = connection.calls[0]
        assert "SELECT state FROM triage_run" in select_sql
        assert select_params == (run_id, REPO_ID)

        insert_sql, insert_params = connection.calls[1]
        assert "INSERT INTO run_step" in insert_sql
        assert run_id in insert_params and REPO_ID in insert_params
        assert "distill" in insert_params and SECOND_ATTEMPT in insert_params
        assert "completed" in insert_params
        assert json.dumps({"lines": 3}) in insert_params

        update_sql, update_params = connection.calls[2]
        assert "UPDATE triage_run SET state" in update_sql
        assert update_params == (RunState.DISTILLING.value, None, run_id, REPO_ID)

    def test_commit_into_pause_binds_its_escalation_reason(self) -> None:
        # AD-1: AWAITING_APPROVAL must carry a reason, so the state move writes
        # it in the same UPDATE or the database CHECK rejects the row.
        run_id = uuid.uuid4()
        connection = FakeConnection(
            [(RunState.CLASSIFYING.value,)], [(CREATED_AT,)], [(run_id,)]
        )
        store, _ = recorder_against(connection)

        store.record(
            claim_for(run_id),
            REPO_ID,
            StepCommit(
                step="classify",
                to_state=RunState.AWAITING_APPROVAL,
                guards=GuardInput(escalation_reason=EscalationReason.UNKNOWN_CLASS),
            ),
        )

        _sql, update_params = connection.calls[2]
        assert update_params == (
            RunState.AWAITING_APPROVAL.value,
            EscalationReason.UNKNOWN_CLASS.value,
            run_id,
            REPO_ID,
        )

    def test_commit_out_of_pause_clears_the_escalation_reason(self) -> None:
        run_id = uuid.uuid4()
        connection = FakeConnection(
            [(RunState.AWAITING_APPROVAL.value,)], [(CREATED_AT,)], [(run_id,)]
        )
        store, _ = recorder_against(connection)

        store.record(
            claim_for(run_id),
            REPO_ID,
            StepCommit(
                step="approve",
                to_state=RunState.ANALYZING,
                guards=GuardInput(decision="approve", class_override=FailureClass.CODE),
            ),
        )

        _sql, update_params = connection.calls[2]
        assert update_params == (RunState.ANALYZING.value, None, run_id, REPO_ID)

    def test_failed_step_binds_failed_status(self) -> None:
        # AD-22: a failed attempt is its own step, recorded with status failed.
        run_id = uuid.uuid4()
        connection = FakeConnection([("RECEIVED",)], [(CREATED_AT,)], [(run_id,)])
        store, _ = recorder_against(connection)

        record = store.record(
            claim_for(run_id),
            REPO_ID,
            StepCommit(
                step="distill",
                to_state=RunState.DISTILLING,
                status=StepStatus.FAILED,
                output="boom",
            ),
        )

        _sql, insert_params = connection.calls[1]
        assert StepStatus.FAILED.value in insert_params
        assert record.status is StepStatus.FAILED

    def test_ac1_commit_binds_repo_id_on_every_query(self) -> None:
        run_id = uuid.uuid4()
        connection = FakeConnection([("RECEIVED",)], [(CREATED_AT,)], [(run_id,)])
        store, _ = recorder_against(connection)

        store.record(
            claim_for(run_id),
            REPO_ID,
            StepCommit(step="x", to_state=RunState.DISTILLING),
        )

        for _sql, params in connection.calls:
            assert REPO_ID in params, "every run/step query is repo-scoped (AD-15)"

    def test_ac1_no_lease_sql_of_its_own(self) -> None:
        # The manual check in the spec: fencing stays in story 1.2's guard.
        run_id = uuid.uuid4()
        connection = FakeConnection([("RECEIVED",)], [(CREATED_AT,)], [(run_id,)])
        store, _ = recorder_against(connection)

        store.record(
            claim_for(run_id),
            REPO_ID,
            StepCommit(step="x", to_state=RunState.DISTILLING),
        )

        for sql, _params in connection.calls:
            assert "FOR UPDATE" not in sql
            assert "SKIP LOCKED" not in sql

    def test_ac1_illegal_transition_writes_nothing(self) -> None:
        run_id = uuid.uuid4()
        connection = FakeConnection([(RunState.DONE_PR.value,)])
        store, _ = recorder_against(connection)

        with pytest.raises(IllegalTransition):
            store.record(
                claim_for(run_id),
                REPO_ID,
                StepCommit(step="distill", to_state=RunState.DISTILLING),
            )

        assert len(connection.calls) == 1, "only the state read ran; no writes"
        assert connection.calls[0][0].startswith("SELECT state FROM triage_run")

    def test_ac3_guard_reports_owner_mismatch(self) -> None:
        run_id = uuid.uuid4()
        connection = FakeConnection()
        store, leases = recorder_against(connection, owner_ok=False)

        with pytest.raises(LeaseLost):
            store.record(
                claim_for(run_id),
                REPO_ID,
                StepCommit(step="distill", to_state=RunState.DISTILLING),
            )

        assert len(leases.commits) == 1, "the guarded commit was asked to run"
        assert connection.calls == [], "stale work never runs (AD-23, AD-2)"

    def test_commit_unknown_repo_scope_is_refused_not_written(self) -> None:
        # Owner holds the lease, but repo_id does not match the run: the
        # repo-scoped state read finds nothing and no write happens (AD-15).
        run_id = uuid.uuid4()
        connection = FakeConnection([])  # SELECT state -> no row
        store, _ = recorder_against(connection)

        with pytest.raises(LeaseLost):
            store.record(
                claim_for(run_id),
                REPO_ID,
                StepCommit(step="distill", to_state=RunState.DISTILLING),
            )

        assert len(connection.calls) == 1
        assert connection.calls[0][1] == (run_id, REPO_ID)

    def test_duplicate_step_attempt_is_definitive_not_retryable(self) -> None:
        # The unique (run_id, step, attempt) index is the double-completion
        # backstop (AD-2): a duplicate is typed and never retryable (AD-22).
        # The fake names the identity constraint, as the real index would.
        run_id = uuid.uuid4()
        connection = InsertRaisesConnection(
            IdentityViolation("uq_run_step_identity")
        )
        store, _ = recorder_against(connection)

        with pytest.raises(DuplicateStepError) as excinfo:
            store.record(
                claim_for(run_id),
                REPO_ID,
                StepCommit(step="distill", to_state=RunState.DISTILLING),
            )

        assert excinfo.value.retryable is False
        assert excinfo.value.run_id == run_id
        assert "distill" in str(excinfo.value)

    def test_missing_insert_result_is_a_write_error_not_a_lost_lease(self) -> None:
        run_id = uuid.uuid4()
        connection = FakeConnection(
            [(RunState.RECEIVED.value,)],  # current state read
            [],  # INSERT returned no row
            [(run_id,)],
        )
        store, _ = recorder_against(connection)

        with pytest.raises(StepWriteError):
            store.record(
                claim_for(run_id),
                REPO_ID,
                StepCommit(step="distill", to_state=RunState.DISTILLING),
            )

    def test_missing_state_move_result_is_a_write_error(self) -> None:
        run_id = uuid.uuid4()
        connection = FakeConnection(
            [(RunState.RECEIVED.value,)],
            [(CREATED_AT,)],
            [],  # UPDATE ... RETURNING run_id returned no row
        )
        store, _ = recorder_against(connection)

        with pytest.raises(StepWriteError):
            store.record(
                claim_for(run_id),
                REPO_ID,
                StepCommit(step="distill", to_state=RunState.DISTILLING),
            )

    def test_step_write_error_is_definitive_not_retryable(self) -> None:
        assert StepWriteError(uuid.uuid4(), "distill").retryable is False  # AD-22


class TestResume:
    def test_ac2_resume_returns_current_state_and_completed_steps(self) -> None:
        run_id = uuid.uuid4()
        connection = FakeConnection([("DISTILLING",)], [("distill",), ("classify",)])
        store, _ = recorder_against(connection)

        view = store.resume(run_id, REPO_ID)

        assert view is not None
        assert view.state is RunState.DISTILLING
        assert view.completed_steps == frozenset({"distill", "classify"})
        assert view.is_completed("distill") is True
        assert view.is_completed("propose") is False
        for _sql, params in connection.calls:
            assert params[0] == run_id and params[1] == REPO_ID

    def test_ac2_resume_unknown_or_other_repo_returns_none(self) -> None:
        connection = FakeConnection([])  # no triage_run row for this repo
        store, _ = recorder_against(connection)

        assert store.resume(uuid.uuid4(), REPO_ID) is None

    def test_resume_view_is_pure_and_reports_completion(self) -> None:
        view = ResumeView(state=RunState.ANALYZING, completed_steps=frozenset({"a"}))

        assert view.is_completed("a") is True
        assert view.is_completed("b") is False


class TestStepStatus:
    def test_status_values_match_the_migration_check_constraint(self) -> None:
        # Read the real migration so enum/SQL drift actually fails here.
        sql = MIGRATION.read_text(encoding="utf-8")
        match = re.search(
            r"ck_run_step_status\s+CHECK\s*\(status IN \(([^)]*)\)\)",
            sql,
            re.IGNORECASE | re.DOTALL,
        )
        assert match is not None, "0004_run_step.sql must declare ck_run_step_status"
        listed = set(re.findall(r"'([a-z_]+)'", match.group(1)))
        assert listed == {status.value for status in StepStatus}


class TestStepCommitDefaults:
    def test_a_commit_defaults_to_one_completed_attempt_with_no_output(self) -> None:
        commit = StepCommit(step="classify", to_state=RunState.ANALYZING)

        assert commit.attempt == 1
        assert commit.status is StepStatus.COMPLETED
        assert commit.output is None
        assert commit.guards == GuardInput()
