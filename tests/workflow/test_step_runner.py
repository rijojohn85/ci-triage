"""Story 2.8 unit tests — the shared step runner (AC1, AC2, AC3).

Every edge is a Protocol fake (AGENTS.md TDD): transport, step recorder,
attempt recorder, history store and audit store are fakes, so the budgets,
attempt accounting and pause/commit/fail paths are proven with no I/O. The
real Postgres path is the marked integration test
(`tests/workflow/test_step_runner_integration.py`).
"""

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import psycopg
import pytest

from contracts.enums import EscalationReason
from contracts.usage import CallOutcome, ModelUsage
from guardrails.citation_check import ValidationIssue
from workflow.history import HistoryEntry, TerminalWrite
from workflow.leases import Claim, LeaseLost
from workflow.run_states import RunState
from workflow.step_runner import (
    DefinitiveCallError,
    FailedAttempt,
    PostgresAttemptRecorder,
    StepCommitted,
    StepContext,
    StepFailed,
    StepPaused,
    StepRunnerConfig,
    StepTransport,
    TransientCallError,
    classification_validator,
    run_step,
)
from workflow.steps import DuplicateStepError, StepCommit, StepRecord, StepStatus
from workflow.usage_audit import ModelCallAttempt, ModelCallResult

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
CREATED_AT = datetime(2026, 9, 26, 12, 0, 1, tzinfo=timezone.utc)
RUN_ID = uuid.UUID("018f6a2c-0000-7000-8000-000000000001")
REPO_ID = 7
MODEL = "claude-haiku-4-5-20251001"
SKILL = "classify"
REQUEST = {"skill": SKILL, "input": {"log": [1, 2, 3]}}
VALID_PAYLOAD = {"choice": {"answer": "code"}, "injection_screen": {"noul": 0.1}}
ISSUE = ValidationIssue(code="schema", message="bad shape", location="choice")


def config(
    step_timeout_seconds: float = 60.0,
    max_attempts: int = 3,
    backoff_base_seconds: float = 2.0,
    backoff_factor: float = 2.0,
) -> StepRunnerConfig:
    return StepRunnerConfig(
        model=MODEL,
        step_timeout_seconds=step_timeout_seconds,
        max_attempts=max_attempts,
        backoff_base_seconds=backoff_base_seconds,
        backoff_factor=backoff_factor,
    )


def terminal() -> TerminalWrite:
    return TerminalWrite(
        run_id=RUN_ID,
        repo_id=REPO_ID,
        test_id="tests/test_x.py",
        error_type="AssertionError",
        top_stack_frames=("app.py:10",),
        to_state=RunState.FAILED,
    )


def context(to_state: RunState = RunState.ANALYZING) -> StepContext:
    return StepContext(
        claim=Claim(RUN_ID, "owner-a", NOW + timedelta(seconds=300)),
        repo_id=REPO_ID,
        request=REQUEST,
        to_state=to_state,
        terminal=terminal(),
    )


def issue_list(payload: object) -> Sequence[ValidationIssue]:
    """The validator stand-in: only `VALID_PAYLOAD` is acceptable."""
    return () if payload == VALID_PAYLOAD else (ISSUE,)


class FakeTransport:
    """Scripted per-call outcomes: a payload, or an exception to raise."""

    def __init__(self, *outcomes: object) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[object, float]] = []
        self.usage: ModelUsage | None = None

    def call(self, request: object, *, timeout_seconds: float) -> object:
        self.calls.append((request, timeout_seconds))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return ModelCallResult(value=outcome, usage=self.usage)


class FakeRecorder:
    """The `StepRecorder` fake: records commits, can model a stale owner."""

    def __init__(self, owner_ok: bool = True) -> None:
        self.commits: list[StepCommit] = []
        self._owner_ok = owner_ok

    def record(self, claim: Claim, repo_id: int, commit: StepCommit) -> StepRecord:
        if not self._owner_ok:
            raise LeaseLost(claim.run_id, claim.owner)
        self.commits.append(commit)
        return StepRecord(
            step_id=uuid.uuid4(),
            run_id=claim.run_id,
            repo_id=repo_id,
            step=commit.step,
            attempt=commit.attempt,
            status=commit.status,
            output=commit.output,
            created_at=CREATED_AT,
        )

    def resume(self, run_id: uuid.UUID, repo_id: int) -> None:
        raise NotImplementedError


class FakeAttempts:
    """The `AttemptRecorder` fake: records rows; scripts the re-entrancy read."""

    def __init__(self, last: tuple[int, int] = (0, 0)) -> None:
        self.rows: list[FailedAttempt] = []
        self._last = last
        self.reads: list[tuple[uuid.UUID, int, str]] = []

    def record(self, attempt: FailedAttempt) -> None:
        self.rows.append(attempt)

    def last_attempts(
        self, run_id: uuid.UUID, repo_id: int, step: str
    ) -> tuple[int, int]:
        self.reads.append((run_id, repo_id, step))
        return self._last


class FakeHistory:
    """The `HistoryStore` fake: records terminal writes."""

    def __init__(self) -> None:
        self.writes: list[TerminalWrite] = []

    def write_terminal(self, write: TerminalWrite) -> HistoryEntry:
        self.writes.append(write)
        return HistoryEntry(
            row_id=uuid.uuid4(),
            run_id=write.run_id,
            repo_id=write.repo_id,
            test_id=write.test_id,
            error_type=write.error_type,
            top_stack_frames=write.top_stack_frames,
            fingerprint="fingerprint",
            terminal_state=write.to_state,
            human_verdict=None,
            created_at=CREATED_AT,
        )

    def import_seed(self, records: object) -> list[uuid.UUID]:
        raise NotImplementedError

    def lookup(
        self, repo_id: int, fingerprint: str, limit: int
    ) -> list[HistoryEntry]:
        raise NotImplementedError


class FakeAudit:
    """The `UsageAuditStore` fake: records 6.1 attempt rows."""

    def __init__(self) -> None:
        self.attempts: list[ModelCallAttempt] = []

    def record_attempt(self, attempt: ModelCallAttempt) -> None:
        self.attempts.append(attempt)


def run(
    transport: FakeTransport,
    *,
    validate: object = issue_list,
    recorder: FakeRecorder | None = None,
    attempts: FakeAttempts | None = None,
    history: FakeHistory | None = None,
    audit: FakeAudit | None = None,
    sleeps: list[float] | None = None,
    cfg: StepRunnerConfig | None = None,
    ctx: StepContext | None = None,
) -> object:
    """One `run_step` call with fakes everywhere; returns the typed outcome."""
    return run_step(
        ctx or context(),
        SKILL,
        transport,  # type: ignore[arg-type]
        validate,  # type: ignore[arg-type]
        recorder or FakeRecorder(),  # type: ignore[arg-type]
        attempts or FakeAttempts(),  # type: ignore[arg-type]
        history or FakeHistory(),  # type: ignore[arg-type]
        audit or FakeAudit(),  # type: ignore[arg-type]
        (sleeps if sleeps is not None else []).append,
        cfg or config(),
    )


def transient(message: str = "connection reset") -> TransientCallError:
    return TransientCallError(message)


def definitive(message: str = "bad request") -> DefinitiveCallError:
    return DefinitiveCallError(message)


# --- AC1: one validation retry with errors fed back, then a pause


def test_ac1_first_invalid_output_retries_with_errors_fed_back() -> None:
    transport = FakeTransport({"bad": 1}, VALID_PAYLOAD)
    sleeps: list[float] = []

    outcome = run(transport, sleeps=sleeps)

    assert isinstance(outcome, StepCommitted)
    assert len(transport.calls) == 2
    first_request, _ = transport.calls[0]
    assert first_request == REQUEST, "the first attempt carries the plain request"
    second_request, _ = transport.calls[1]
    assert second_request == {
        "request": REQUEST,
        "validation_issues": [ISSUE.model_dump()],
    }, "the retry feeds the structured validator errors back"
    assert sleeps == [], "a validation retry is not a transient backoff (AD-8)"


def test_ac1_second_invalid_output_pauses_validation_failed() -> None:
    transport = FakeTransport({"bad": 1}, {"bad": 2})
    recorder = FakeRecorder()

    outcome = run(transport, recorder=recorder)

    assert isinstance(outcome, StepPaused)
    assert outcome.reason is EscalationReason.VALIDATION_FAILED
    (commit,) = recorder.commits
    assert commit.step == SKILL
    assert commit.attempt == 2
    assert commit.status is StepStatus.FAILED
    assert commit.to_state is RunState.AWAITING_APPROVAL
    assert commit.guards.escalation_reason is EscalationReason.VALIDATION_FAILED
    assert commit.output == {"validation_issues": [ISSUE.model_dump()]}


def test_ac1_each_attempt_is_its_own_run_step() -> None:
    transport = FakeTransport({"bad": 1}, VALID_PAYLOAD)
    attempts = FakeAttempts()
    recorder = FakeRecorder()

    run(transport, recorder=recorder, attempts=attempts)

    (row,) = attempts.rows
    assert (row.step, row.attempt) == (SKILL, 1)
    assert row.output == {"validation_issues": [ISSUE.model_dump()]}
    (commit,) = recorder.commits
    assert (commit.step, commit.attempt, commit.status) == (
        SKILL,
        2,
        StepStatus.COMPLETED,
    )


def test_ac1_invalid_output_is_never_committed() -> None:
    transport = FakeTransport({"bad": 1}, {"bad": 2})
    recorder = FakeRecorder()

    run(transport, recorder=recorder)

    assert recorder.commits, "the pause commit is the only state move"
    for commit in recorder.commits:
        assert commit.status is not StepStatus.COMPLETED
        assert commit.output != {"bad": 1}, "no uncited/invalid verdict is committed"


# --- AC2: the transient budget (≤3 attempts with backoff), then FAILED


def test_ac2_transient_errors_retry_up_to_three_attempts_with_backoff() -> None:
    transport = FakeTransport(transient(), transient(), VALID_PAYLOAD)
    sleeps: list[float] = []

    outcome = run(transport, sleeps=sleeps)

    assert isinstance(outcome, StepCommitted)
    assert len(transport.calls) == 3
    assert sleeps == [2.0, 4.0], "config-driven exponential backoff between attempts"


def test_ac2_exhausted_transient_budget_fails_and_writes_history_once() -> None:
    transport = FakeTransport(transient(), transient(), transient())
    recorder = FakeRecorder()
    attempts = FakeAttempts()
    history = FakeHistory()

    outcome = run(transport, recorder=recorder, attempts=attempts, history=history)

    assert isinstance(outcome, StepFailed)
    (commit,) = recorder.commits
    assert (commit.attempt, commit.status, commit.to_state) == (
        3,
        StepStatus.FAILED,
        RunState.FAILED,
    )
    assert [row.attempt for row in attempts.rows] == [1, 2]
    assert len(history.writes) == 1, "terminal history is written exactly once"
    assert history.writes[0].to_state is RunState.FAILED


def test_ac2_non_retryable_error_fails_without_retry() -> None:
    transport = FakeTransport(definitive())
    recorder = FakeRecorder()
    history = FakeHistory()
    sleeps: list[float] = []

    outcome = run(transport, recorder=recorder, history=history, sleeps=sleeps)

    assert isinstance(outcome, StepFailed)
    assert len(transport.calls) == 1, "a definitive error is never retried (AD-22)"
    assert sleeps == []
    (commit,) = recorder.commits
    assert (commit.attempt, commit.status, commit.to_state) == (
        1,
        StepStatus.FAILED,
        RunState.FAILED,
    )
    assert len(history.writes) == 1


def test_ac2_fixtures_assert_attempt_counts_status_and_null_usage() -> None:
    transport = FakeTransport(transient(), VALID_PAYLOAD)
    transport.usage = ModelUsage(model=MODEL, input_tokens=5)
    attempts = FakeAttempts()
    audit = FakeAudit()

    run(transport, attempts=attempts, audit=audit)

    failed, completed = audit.attempts
    assert [row.attempt for row in audit.attempts] == [1, 2]
    assert failed.status is StepStatus.FAILED
    assert failed.usage is None, "unreported counters stay NULL, never 0 (AD-18)"
    assert completed.status is StepStatus.COMPLETED
    assert completed.usage is not None
    assert completed.usage.input_tokens == 5
    assert completed.usage.output_tokens is None, "NULL counters included"
    assert [row.attempt for row in attempts.rows] == [1]


def test_ac2_validation_and_transient_budgets_are_independent() -> None:
    # A transient failure consumes AD-22; an invalid output consumes AD-8 —
    # one attempt consumes at most one budget unit (spec Design Notes).
    transport = FakeTransport(transient(), {"bad": 1}, VALID_PAYLOAD)

    outcome = run(transport)

    assert isinstance(outcome, StepCommitted)
    assert len(transport.calls) == 3

    exhausted = FakeTransport({"bad": 1}, transient(), transient(), transient())
    recorder = FakeRecorder()
    outcome = run(exhausted, recorder=recorder)

    assert isinstance(outcome, StepFailed)
    assert len(exhausted.calls) == 4, "the invalid output did not consume AD-22"
    (commit,) = recorder.commits
    assert commit.attempt == 4


# --- AC3: lease-guarded atomic commit, auditing, per-skill timeout


def test_ac3_validated_output_and_state_commit_atomically() -> None:
    transport = FakeTransport(VALID_PAYLOAD)
    recorder = FakeRecorder()

    outcome = run(transport, recorder=recorder)

    assert isinstance(outcome, StepCommitted)
    assert len(recorder.commits) == 1, "one guarded commit: output + state move"
    commit = recorder.commits[0]
    assert commit.output == VALID_PAYLOAD
    assert commit.to_state is RunState.ANALYZING
    assert commit.status is StepStatus.COMPLETED
    assert commit.attempt == 1


def test_ac3_stale_owner_result_cannot_commit() -> None:
    transport = FakeTransport(VALID_PAYLOAD)
    recorder = FakeRecorder(owner_ok=False)
    audit = FakeAudit()

    with pytest.raises(LeaseLost):
        run(transport, recorder=recorder, audit=audit)

    assert recorder.commits == [], "the fenced commit wrote nothing"
    assert len(audit.attempts) == 1, "the attempted call was still audited (AD-18)"


def test_ac3_every_attempted_call_is_audited() -> None:
    transport = FakeTransport(transient(), transient(), VALID_PAYLOAD)
    audit = FakeAudit()

    run(transport, audit=audit)

    assert [row.step for row in audit.attempts] == ["call:classify"] * 3
    assert [row.attempt for row in audit.attempts] == [1, 2, 3]
    assert [row.status for row in audit.attempts] == [
        StepStatus.FAILED,
        StepStatus.FAILED,
        StepStatus.COMPLETED,
    ]
    assert all(row.outcome is CallOutcome.ERROR for row in audit.attempts[:2])
    assert audit.attempts[2].outcome is CallOutcome.VERDICT


def test_ac3_timeout_comes_from_per_skill_config() -> None:
    transport = FakeTransport(VALID_PAYLOAD)

    run(transport, cfg=config(step_timeout_seconds=60.0))

    assert all(timeout == 60.0 for _request, timeout in transport.calls)


# --- AC2/AD-2: attempt numbering continues from existing rows (re-entrancy)


def test_ac2_attempt_numbering_continues_from_leftover_rows() -> None:
    # A reclaimed worker re-runs a step whose earlier owner left a failed
    # attempt row and a fenced `call:` audit row: numbering continues at
    # last+1 per namespace, so the identity never collides (AD-2).
    transport = FakeTransport(VALID_PAYLOAD)
    attempts = FakeAttempts(last=(1, 3))
    recorder = FakeRecorder()
    audit = FakeAudit()

    outcome = run(transport, recorder=recorder, attempts=attempts, audit=audit)

    assert isinstance(outcome, StepCommitted)
    (commit,) = recorder.commits
    assert commit.attempt == 2, "the step's own rows continue at last+1"
    assert audit.attempts[0].attempt == 4, "the `call:` rows continue at last+1"
    assert attempts.rows == [], "a valid first try records no failed-attempt row"
    assert attempts.reads == [(RUN_ID, REPO_ID, SKILL)], "one re-entrancy read"


def test_ac2_blank_skill_is_refused_at_entry() -> None:
    with pytest.raises(ValueError):
        run_step(
            context(),
            "   ",
            FakeTransport(VALID_PAYLOAD),  # type: ignore[arg-type]
            issue_list,  # type: ignore[arg-type]
            FakeRecorder(),  # type: ignore[arg-type]
            FakeAttempts(),  # type: ignore[arg-type]
            FakeHistory(),  # type: ignore[arg-type]
            FakeAudit(),  # type: ignore[arg-type]
            lambda _seconds: None,
            config(),
        )


# --- AC1: the real guardrails validator drives the runner end to end


def test_ac1_real_classification_validator_commits_a_valid_payload() -> None:
    payload = {
        "choice": {
            "answer": "code",
            "confidence": 0.9,
            "probabilities": {"code": 0.9},
        },
        "injection_screen": {"noul": 0.1},
    }
    transport = FakeTransport(payload)
    recorder = FakeRecorder()

    outcome = run(transport, validate=classification_validator(), recorder=recorder)

    assert isinstance(outcome, StepCommitted)
    assert recorder.commits[0].output == payload


def test_ac1_real_classification_validator_feeds_issues_back() -> None:
    transport = FakeTransport({"bad": 1}, {"bad": 2})

    outcome = run(transport, validate=classification_validator())

    assert isinstance(outcome, StepPaused), (
        "the real validator's issues consume the AD-8 budget, then pause"
    )


# --- AC2: the config guards refuse an unusable StepRunnerConfig


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model", "   "),
        ("step_timeout_seconds", 0.0),
        ("max_attempts", 0),
        ("backoff_base_seconds", 0.0),
        ("backoff_factor", 0.5),
    ],
)
def test_ac2_unusable_config_field_is_refused(field: str, value: float) -> None:
    kwargs: dict[str, object] = {
        "model": MODEL,
        "step_timeout_seconds": 60.0,
        "max_attempts": 3,
        "backoff_base_seconds": 2.0,
        "backoff_factor": 2.0,
    }
    kwargs[field] = value

    with pytest.raises(ValueError):
        StepRunnerConfig(**kwargs)  # type: ignore[arg-type]


# --- the PostgresAttemptRecorder adapter, driven through a fake connection


class RecorderCursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def fetchone(self) -> tuple[object, ...] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self._rows)


class RecorderConnection:
    """Records SQL and bound params; scripts per-execute results or an error."""

    def __init__(
        self,
        *results: list[tuple[object, ...]],
        error: BaseException | None = None,
    ) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self._results = list(results)
        self._error = error

    def __enter__(self) -> "RecorderConnection":
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> RecorderCursor:
        self.calls.append((sql, params))
        if self._error is not None:
            raise self._error
        return RecorderCursor(self._results.pop(0) if self._results else [])


def recorder_against(connection: RecorderConnection) -> PostgresAttemptRecorder:
    return PostgresAttemptRecorder(
        "postgresql://unused", connect=lambda _dsn: connection
    )


def failed_row() -> FailedAttempt:
    return FailedAttempt(
        run_id=RUN_ID,
        repo_id=REPO_ID,
        step=SKILL,
        attempt=1,
        output={"error": "boom"},
    )


def test_ac2_adapter_inserts_the_failed_attempt_row() -> None:
    connection = RecorderConnection()
    recorder = recorder_against(connection)

    recorder.record(failed_row())

    sql, params = connection.calls[0]
    assert "INSERT INTO run_step" in sql
    assert params[1:6] == (RUN_ID, REPO_ID, SKILL, 1, "failed")
    assert params[6] == '{"error": "boom"}'


def test_ac2_adapter_reads_last_attempts_for_both_namespaces() -> None:
    connection = RecorderConnection(
        [("call:classify", 3), ("classify", 1)],  # one query, both namespaces
    )
    recorder = recorder_against(connection)

    last = recorder.last_attempts(RUN_ID, REPO_ID, SKILL)

    assert last == (1, 3)
    sql, params = connection.calls[0]
    assert "MAX(attempt)" in sql and "GROUP BY step" in sql
    assert params[0] == RUN_ID and params[1] == REPO_ID
    assert sorted(params[2]) == ["call:classify", "classify"]


def test_ac2_adapter_reads_zero_when_no_rows_exist() -> None:
    recorder = recorder_against(RecorderConnection())

    assert recorder.last_attempts(RUN_ID, REPO_ID, SKILL) == (0, 0)


def test_ac2_adapter_translates_only_the_identity_constraint() -> None:
    duplicate = recorder_against(
        RecorderConnection(error=IdentityViolation("uq_run_step_identity"))
    )
    with pytest.raises(DuplicateStepError) as exc:
        duplicate.record(failed_row())
    assert (exc.value.step, exc.value.attempt) == (SKILL, 1)

    other = recorder_against(
        RecorderConnection(error=IdentityViolation("uq_history_run_id"))
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        # a foreign constraint is never masked as a duplicate attempt
        other.record(failed_row())


def test_ac2_adapter_surfaces_unrelated_errors_unchanged() -> None:
    boom = RuntimeError("connection refused")
    recorder = recorder_against(RecorderConnection(error=boom))

    with pytest.raises(RuntimeError) as exc:
        recorder.record(failed_row())

    assert exc.value is boom


class IdentityViolation(psycopg.errors.UniqueViolation):
    """A UniqueViolation whose `diag` names a chosen constraint."""

    def __init__(self, constraint_name: str) -> None:
        super().__init__(f'duplicate key ... "{constraint_name}"')
        self._constraint_name = constraint_name

    @property
    def diag(self) -> object:  # type: ignore[override]
        return SimpleNamespace(constraint_name=self._constraint_name)
