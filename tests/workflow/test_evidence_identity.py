"""Story 2.7 task binding inside the existing step transaction."""

import uuid

import pytest

from tests.workflow.test_steps import FakeConnection, FakeCursor, CREATED_AT, claim_for, recorder_against
from workflow.run_states import RunState
from workflow.steps import StepCommit, StepTaskMismatchError, TaskRunIdentity


class IdentityConnection(FakeConnection):
    def __init__(self, actual: tuple[int, int, int] | None, run_id: uuid.UUID) -> None:
        super().__init__()
        self.actual = actual
        self.run_id = run_id

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> FakeCursor:
        self.calls.append((sql, params))
        if "workflow_run_id" in sql:
            return FakeCursor([] if self.actual is None else [self.actual])
        if sql.startswith("SELECT"):
            return FakeCursor([("DISTILLING",)])
        if sql.lstrip().startswith("INSERT"):
            return FakeCursor([(CREATED_AT,)])
        return FakeCursor([(self.run_id,)])


@pytest.mark.parametrize("actual", [(1, 99, 2), (1, 20, 1), (2, 20, 2)])
def test_ac3_unrelated_leased_task_refused_before_step_writes(actual: tuple[int, int, int]) -> None:
    run_id = uuid.uuid4()
    connection = IdentityConnection(actual, run_id)
    recorder, leases = recorder_against(connection)
    with pytest.raises(StepTaskMismatchError) as exc:
        recorder.record(claim_for(run_id), 1,
                        StepCommit("distill", RunState.CLASSIFYING,
                                   task_identity=TaskRunIdentity(1, 20, 2)))
    assert not exc.value.retryable
    assert len(leases.commits) == 1
    assert not any("INSERT" in sql or "UPDATE" in sql for sql, _ in connection.calls)


def test_ac1_matching_task_checked_in_same_guarded_commit() -> None:
    run_id = uuid.uuid4()
    connection = IdentityConnection((1, 20, 2), run_id)
    recorder, leases = recorder_against(connection)
    record = recorder.record(claim_for(run_id), 1,
        StepCommit("distill", RunState.CLASSIFYING, task_identity=TaskRunIdentity(1, 20, 2)))
    assert record.step == "distill"
    assert len(leases.commits) == 1
    assert connection.calls[1][1] == (run_id, 1)


def test_ac3_missing_task_identity_row_refused() -> None:
    run_id = uuid.uuid4()
    recorder, _ = recorder_against(IdentityConnection(None, run_id))
    with pytest.raises(StepTaskMismatchError):
        recorder.record(claim_for(run_id), 1,
            StepCommit("distill", RunState.CLASSIFYING, task_identity=TaskRunIdentity(1, 20, 2)))
