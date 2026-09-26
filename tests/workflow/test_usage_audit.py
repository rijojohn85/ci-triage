"""Story 6.1 unit tests — the central model-call audit recorder (AC1/AC2/AC3).

The Postgres boundary is driven through a `UsageAuditStore` Protocol fake,
no database touched here (mirrors `tests/workflow/test_history.py`). The
real adapter runs in the marked integration tests
(`tests/workflow/test_usage_audit_integration.py`).
"""

import json
import logging
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace, TracebackType

import psycopg
import pytest

from contracts.usage import CallOutcome, ModelUsage
from workflow.service_log import LOG_FIELDS
from workflow.steps import DuplicateStepError, StepStatus
from workflow.usage_audit import (
    AuditIdentity,
    ModelCallAttempt,
    ModelCallError,
    ModelCallResult,
    PostgresUsageAuditStore,
    audit_model_call,
)

MODEL = "claude-haiku-4-5-20251001"
RUN_ID = uuid.UUID("018f6a2c-0000-7000-8000-000000000001")
REPO_ID = 7
REPO_ROOT = Path(__file__).resolve().parents[2]

FULL_USAGE = ModelUsage(
    model=MODEL,
    input_tokens=1200,
    output_tokens=340,
    cache_read_input_tokens=512,
    cache_creation_input_tokens_5m=64,
    cache_creation_input_tokens_1h=128,
)

IDENTITY = AuditIdentity(run_id=RUN_ID, repo_id=REPO_ID, task_id=str(RUN_ID))


class FakeUsageAuditStore:
    """Protocol fake: records attempt rows, optionally raises (the AD-2 backstop)."""

    def __init__(self, error: Exception | None = None) -> None:
        self.attempts: list[ModelCallAttempt] = []
        self._error = error

    def record_attempt(self, attempt: ModelCallAttempt) -> None:
        if self._error is not None:
            raise self._error
        self.attempts.append(attempt)


def wrapper(
    store: FakeUsageAuditStore,
    step_name: str = "call:system_one",
    attempt: int = 1,
) -> Callable[[Callable[[], ModelCallResult[str]]], str]:
    return audit_model_call(
        store, IDENTITY, step_name=step_name, attempt=attempt, model=MODEL
    )


def test_ac1_usage_fixtures_become_audit_rows_with_all_counters() -> None:
    store = FakeUsageAuditStore()

    value = wrapper(store)(lambda: ModelCallResult(value="payload", usage=FULL_USAGE))

    assert value == "payload"
    (row,) = store.attempts
    assert row.status is StepStatus.COMPLETED
    assert row.outcome is CallOutcome.VERDICT
    assert row.model == MODEL
    assert row.usage == FULL_USAGE
    assert row.step == "call:system_one"
    assert row.attempt == 1
    assert row.run_id == RUN_ID
    assert row.repo_id == REPO_ID


def test_ac1_unreported_counters_are_null_not_zero() -> None:
    store = FakeUsageAuditStore()
    partial = ModelUsage(model=MODEL, input_tokens=10)

    wrapper(store)(lambda: ModelCallResult(value="payload", usage=partial))

    (row,) = store.attempts
    usage = row.usage
    assert usage is not None
    assert usage.input_tokens == 10
    assert usage.output_tokens is None
    assert usage.cache_read_input_tokens is None
    assert usage.cache_creation_input_tokens_5m is None
    assert usage.cache_creation_input_tokens_1h is None
    assert 0 not in (
        usage.output_tokens,
        usage.cache_read_input_tokens,
        usage.cache_creation_input_tokens_5m,
        usage.cache_creation_input_tokens_1h,
    )


def test_ac2_each_invocation_gets_its_own_identifiable_attempt() -> None:
    store = FakeUsageAuditStore()

    for attempt in (1, 2, 3):
        wrapper(store, attempt=attempt)(
            lambda: ModelCallResult(value="payload", usage=FULL_USAGE)
        )

    assert [row.attempt for row in store.attempts] == [1, 2, 3]
    assert {row.step for row in store.attempts} == {"call:system_one"}
    assert all(row.run_id == RUN_ID for row in store.attempts)

    # The `(run_id, step, attempt)` identity is the duplicate backstop (AD-2):
    # a store that refuses a repeated attempt raises out of the wrapper.
    duplicate_store = FakeUsageAuditStore(
        error=DuplicateStepError(RUN_ID, "call:system_one", 1)
    )
    with pytest.raises(DuplicateStepError):
        wrapper(duplicate_store)(lambda: ModelCallResult(value="payload"))


def test_ac2_usage_returned_on_error_is_persisted() -> None:
    store = FakeUsageAuditStore()

    def failed_with_usage() -> ModelCallResult[str]:
        raise ModelCallError("provider returned usage, then failed", usage=FULL_USAGE)

    with pytest.raises(ModelCallError):
        wrapper(store)(failed_with_usage)

    (row,) = store.attempts
    assert row.status is StepStatus.FAILED
    assert row.usage == FULL_USAGE, "usage returned by the failed call is kept"
    assert row.outcome is CallOutcome.ERROR


def test_ac2_timeout_failure_keeps_the_closed_outcome() -> None:
    store = FakeUsageAuditStore()

    def timed_out() -> ModelCallResult[str]:
        raise ModelCallError("step_timeout", usage=None, outcome=CallOutcome.TIMEOUT)

    with pytest.raises(ModelCallError):
        wrapper(store)(timed_out)

    (row,) = store.attempts
    assert row.status is StepStatus.FAILED
    assert row.outcome is CallOutcome.TIMEOUT
    assert row.usage is None


def test_ac2_failed_call_cannot_claim_the_verdict_outcome() -> None:
    with pytest.raises(ValueError):
        ModelCallError("failed", outcome=CallOutcome.VERDICT)


def test_ac2_completed_result_cannot_carry_a_failure_outcome() -> None:
    store = FakeUsageAuditStore()

    with pytest.raises(ValueError):
        wrapper(store)(
            lambda: ModelCallResult(
                value="payload", usage=FULL_USAGE, outcome=CallOutcome.TIMEOUT
            )
        )

    # AD-22: the call really ran (and may have spent tokens), so the refused
    # result is still recorded — as a failed attempt, never as completed.
    [row] = store.attempts
    assert row.status is StepStatus.FAILED
    assert row.outcome is CallOutcome.ERROR
    assert row.usage == FULL_USAGE


def test_ac2_failed_call_without_usage_has_null_counters() -> None:
    store = FakeUsageAuditStore()

    def boom() -> ModelCallResult[str]:
        raise RuntimeError("connection reset")

    with pytest.raises(RuntimeError):
        wrapper(store)(boom)

    (row,) = store.attempts
    assert row.status is StepStatus.FAILED
    assert row.usage is None, "nothing fabricated: counters stay NULL, never 0"
    assert row.outcome is CallOutcome.ERROR


def test_ac2_crash_leaves_no_row_and_no_fabricated_usage() -> None:
    store = FakeUsageAuditStore()

    def crash() -> ModelCallResult[str]:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        wrapper(store)(crash)

    assert store.attempts == [], "a crash records nothing, fabricates nothing"


def test_ac2_attempted_and_completed_steps_are_distinguishable() -> None:
    store = FakeUsageAuditStore()

    def boom() -> ModelCallResult[str]:
        raise RuntimeError("first try failed")

    with pytest.raises(RuntimeError):
        wrapper(store, attempt=1)(boom)
    wrapper(store, attempt=2)(lambda: ModelCallResult(value="payload"))

    first, second = store.attempts
    assert (first.step, first.attempt, first.status) == (
        "call:system_one",
        1,
        StepStatus.FAILED,
    )
    assert (second.step, second.attempt, second.status) == (
        "call:system_one",
        2,
        StepStatus.COMPLETED,
    )


def test_ac2_step_names_outside_call_namespace_are_refused() -> None:
    # `call:` keeps attempt rows out of a step's own completion-row namespace
    # under the `(run_id, step, attempt)` identity (AD-2); a bare prefix has
    # no skill suffix and is refused too.
    store = FakeUsageAuditStore()

    with pytest.raises(ValueError):
        audit_model_call(store, IDENTITY, step_name="classify", attempt=1, model=MODEL)
    with pytest.raises(ValueError):
        audit_model_call(store, IDENTITY, step_name="call:", attempt=1, model=MODEL)

    assert store.attempts == []


def test_ac2_wrapper_refuses_non_positive_attempt() -> None:
    store = FakeUsageAuditStore()

    with pytest.raises(ValueError):
        audit_model_call(
            store, IDENTITY, step_name="call:system_one", attempt=0, model=MODEL
        )

    assert store.attempts == []


def test_ac2_wrapper_refuses_an_empty_model() -> None:
    # An empty model id would crash the cost reader's ModelUsage validation
    # later (story 6.2): refused at the wrapper, same style as the step name.
    store = FakeUsageAuditStore()

    with pytest.raises(ValueError):
        audit_model_call(
            store, IDENTITY, step_name="call:system_one", attempt=1, model="   "
        )

    assert store.attempts == []


def test_ac3_every_log_line_carries_run_id_task_id_step(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = FakeUsageAuditStore()
    failing_store = FakeUsageAuditStore()

    with caplog.at_level(logging.INFO, logger="workflow.usage_audit"):
        wrapper(store)(lambda: ModelCallResult(value="payload", usage=FULL_USAGE))

        def boom() -> ModelCallResult[str]:
            raise RuntimeError("failed call")

        with pytest.raises(RuntimeError):
            wrapper(failing_store)(boom)

    lines = [json.loads(record.message) for record in caplog.records]
    assert len(lines) == 2, "one structured line per recorded invocation"
    for line in lines:
        assert set(line) == set(LOG_FIELDS)
        assert line["run_id"] == str(RUN_ID)
        assert line["task_id"] == str(RUN_ID)
        assert line["step"] == "call:system_one"


def test_ac3_no_tokens_secrets_or_raw_logs_in_log_lines(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = FakeUsageAuditStore()
    raw_response = "RAW MODEL OUTPUT citing secret sk-ant-api99-tokensecret"

    with caplog.at_level(logging.INFO, logger="workflow.usage_audit"):
        wrapper(store)(lambda: ModelCallResult(value=raw_response, usage=FULL_USAGE))

    (line,) = [json.loads(record.message) for record in caplog.records]
    flattened = json.dumps(line)
    for forbidden in (
        raw_response,
        "RAW MODEL OUTPUT",
        "sk-ant-api99",
        "1200",
        "340",
        "512",
        "input_tokens",
        "usage",
        MODEL,
    ):
        assert forbidden not in flattened, forbidden


def test_ac3_outcome_check_matches_the_python_enum() -> None:
    """The SQL CHECK and `CallOutcome` are one closed set (AD-18, no drift)."""
    sql = (REPO_ROOT / "deploy" / "migrations" / "0007_run_step_audit.sql").read_text(
        encoding="utf-8"
    )

    match = re.search(r"CHECK \(outcome IN \(([^)]+)\)\)", sql)
    assert match is not None, "the outcome CHECK is missing from migration 0007"
    sql_values = tuple(value.strip().strip("'") for value in match.group(1).split(","))

    assert sql_values == tuple(member.value for member in CallOutcome)


class FakeCursor:
    def fetchone(self) -> tuple[object, ...] | None:
        return None

    def fetchall(self) -> list[tuple[object, ...]]:
        return []


class _NullTransaction:
    """No-op stand-in for `conn.transaction()` (the fake has no real rollback)."""

    def __enter__(self) -> "_NullTransaction":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        return False


class FakeConnection:
    """Records SQL and bound params; optionally raises on execute."""

    def __init__(self, error: BaseException | None = None) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self._error = error

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        return False

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> FakeCursor:
        self.calls.append((sql, params))
        if self._error is not None:
            raise self._error
        return FakeCursor()

    def transaction(self) -> _NullTransaction:
        return _NullTransaction()


class IdentityViolation(psycopg.errors.UniqueViolation):
    """A UniqueViolation whose `diag` names a chosen constraint."""

    def __init__(self, constraint_name: str) -> None:
        super().__init__(f'duplicate key ... "{constraint_name}"')
        self._constraint_name = constraint_name

    @property
    def diag(self) -> object:  # type: ignore[override]
        return SimpleNamespace(constraint_name=self._constraint_name)


def attempt_row(usage: ModelUsage | None) -> ModelCallAttempt:
    return ModelCallAttempt(
        run_id=RUN_ID,
        repo_id=REPO_ID,
        step="call:system_one",
        attempt=1,
        model=MODEL,
        status=StepStatus.COMPLETED,
        outcome=CallOutcome.VERDICT,
        usage=usage,
    )


def store_against(connection: FakeConnection) -> PostgresUsageAuditStore:
    return PostgresUsageAuditStore(
        "postgresql://unused", connect=lambda _dsn: connection
    )


def test_ac1_adapter_inserts_the_attempt_row_with_all_counters() -> None:
    connection = FakeConnection()
    store = store_against(connection)

    store.record_attempt(attempt_row(FULL_USAGE))

    sql, params = connection.calls[0]
    assert "INSERT INTO run_step" in sql
    assert "NULL" in sql, "output stays NULL: no raw text in the audit row"
    assert params[1:3] == (RUN_ID, REPO_ID)
    assert params[3:6] == ("call:system_one", 1, "completed")
    assert params[6] == MODEL
    assert params[7:12] == (1200, 340, 512, 64, 128)
    assert params[12] == "verdict"


def test_ac1_adapter_inserts_null_counters_when_usage_is_absent() -> None:
    connection = FakeConnection()
    store = store_against(connection)

    store.record_attempt(attempt_row(None))

    _, params = connection.calls[0]
    assert params[7:12] == (None, None, None, None, None), (
        "unreported counters are NULL, never 0 (AD-18)"
    )


def test_ac2_adapter_enforces_the_call_namespace() -> None:
    # A direct `record_attempt` cannot bypass the `call:` guard (AD-2).
    connection = FakeConnection()
    store = store_against(connection)
    row = attempt_row(FULL_USAGE)

    with pytest.raises(ValueError):
        store.record_attempt(
            ModelCallAttempt(
                run_id=row.run_id,
                repo_id=row.repo_id,
                step="classify",
                attempt=row.attempt,
                model=row.model,
                status=row.status,
                outcome=row.outcome,
                usage=row.usage,
            )
        )

    assert connection.calls == [], "nothing is inserted for a misnamed attempt"


def test_ac2_adapter_translates_only_the_identity_constraint() -> None:
    duplicate = store_against(
        FakeConnection(error=IdentityViolation("uq_run_step_identity"))
    )
    with pytest.raises(DuplicateStepError) as exc:
        duplicate.record_attempt(attempt_row(FULL_USAGE))
    assert (exc.value.step, exc.value.attempt) == ("call:system_one", 1)

    other = store_against(FakeConnection(error=IdentityViolation("uq_history_run_id")))
    with pytest.raises(psycopg.errors.UniqueViolation):
        # a foreign constraint is never masked as a duplicate attempt
        other.record_attempt(attempt_row(FULL_USAGE))
