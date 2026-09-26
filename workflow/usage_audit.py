"""The central model-call audit recorder (story 6.1, AD-18, AD-2, AD-23).

Every LLM/Jev invocation — routing, spoke calls, validation retries,
transient retries — becomes one attempt-level `run_step` row: model, token
counters (NULL when the provider did not report them), status and outcome.
The wrapper records the attempt on success AND on failure; a crash before
recording leaves no row, which IS the explicit incompleteness — nothing is
fabricated (AD-18, AD-22).

SOLID-S: this module owns the audit vocabulary; the SQL lives in
`PostgresUsageAuditStore`. The audit insert is deliberately NOT a
lease-guarded state move (AD-23 guards state moves, not bookkeeping): it
never touches `triage_run.state` and never reuses `step_store.py`'s
guarded-commit path. Attempt rows use the `call:` step-name namespace so
they can never collide with a step's own completion row under the
`(run_id, step, attempt)` identity — the duplicate backstop is the
database's unique index (AD-2).

Consumers (2.8's step runner, the eval harness, the A2A client) compose
`audit_model_call`; no agent ever touches the database (AD-5, AD-18).
"""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

import psycopg

from contracts.usage import CallOutcome, ModelUsage
from workflow.db import Connection, open_connection
from workflow.service_log import EVENT_MODEL_CALL, InvocationLine, log_invocation
from workflow.steps import StepStatus, duplicate_step_error

__all__ = [
    "AuditIdentity",
    "ModelCallAttempt",
    "ModelCallError",
    "ModelCallResult",
    "PostgresUsageAuditStore",
    "UsageAuditStore",
    "audit_model_call",
]

_LOG = logging.getLogger(__name__)

CALL_STEP_PREFIX = "call:"
"""Attempt rows live in this step-name namespace, never beside a step's own
completion row (AD-2)."""

_INSERT_ATTEMPT_SQL = """
INSERT INTO run_step (
    step_id, run_id, repo_id, step, attempt, status, output,
    model, input_tokens, output_tokens, cache_read_input_tokens,
    cache_creation_input_tokens_5m, cache_creation_input_tokens_1h, outcome
)
VALUES (%s, %s, %s, %s, %s, %s, NULL, %s, %s, %s, %s, %s, %s, %s)
"""
# `output` is always NULL: no raw log text, prompts or responses in the audit
# row (AD-18). The unique `(run_id, step, attempt)` index is the duplicate
# backstop (AD-2); the insert never moves `triage_run.state` (AD-23).

T = TypeVar("T")


class UsageAuditStore(Protocol):
    """The persistence surface the audit wrapper consumes (SOLID-I)."""

    def record_attempt(self, attempt: "ModelCallAttempt") -> None: ...


@dataclass(frozen=True)
class AuditIdentity:
    """Who made the call: the run, its tenant scope and the A2A task id.

    `task_id` is the log-line identity (AC3); the row itself binds
    `run_id` + `repo_id` (AD-15).
    """

    run_id: uuid.UUID
    repo_id: int
    task_id: str


@dataclass(frozen=True)
class ModelCallAttempt:
    """One attempt-level audit row (AD-2, AD-18): the audit vocabulary.

    `status` uses the existing `run_step` CHECK values (`completed`/`failed`)
    — no new status value, so no migration CHECK change. `usage` is None
    when the provider reported nothing; its unreported counters stay NULL.
    """

    run_id: uuid.UUID
    repo_id: int
    step: str
    attempt: int
    model: str
    status: StepStatus
    outcome: CallOutcome
    usage: ModelUsage | None = None


class ModelCallError(Exception):
    """A model call failed after the provider may have returned usage.

    The caller raises it (chaining the provider error, AD-22) so the audit
    wrapper can persist the returned usage on the failed attempt row.
    `outcome` stays inside the closed `CallOutcome` set — a timeout failure
    is `TIMEOUT`, never free text, and never `VERDICT` (a failed call is
    not a verdict; AD-18).
    """

    def __init__(
        self,
        message: str,
        *,
        usage: ModelUsage | None = None,
        outcome: CallOutcome = CallOutcome.ERROR,
    ) -> None:
        if outcome is CallOutcome.VERDICT:
            raise ValueError("a failed call cannot carry the VERDICT outcome")
        super().__init__(message)
        self.usage = usage
        self.outcome = outcome


@dataclass(frozen=True)
class ModelCallResult(Generic[T]):
    """What a wrapped call hands back: its value plus the provider usage.

    `outcome` must be `VERDICT` (the model produced its answer — the
    wrapper refuses anything else); a failure is signalled by raising
    `ModelCallError`, never by a sentinel.
    """

    value: T
    usage: ModelUsage | None = None
    outcome: CallOutcome = CallOutcome.VERDICT


@dataclass(frozen=True)
class _CallContext:
    """The fixed identity of one audited call site (keeps helpers ≤ 5 args)."""

    identity: AuditIdentity
    step_name: str
    attempt: int
    model: str


def _validate_step_name(step: str) -> None:
    """The `call:<skill>` namespace with a non-empty suffix (AD-2)."""
    if not step.startswith(CALL_STEP_PREFIX) or step == CALL_STEP_PREFIX:
        raise ValueError(
            f"audit step name {step!r} must use the {CALL_STEP_PREFIX!r} "
            "namespace with a non-empty skill suffix (AD-2)"
        )


def _validate_model(model: str) -> None:
    """A non-empty model id: the cost reader's `ModelUsage` requires one."""
    if not model.strip():
        raise ValueError("audit model must be a non-empty model id (AD-18)")


def audit_model_call(
    store: UsageAuditStore,
    identity: AuditIdentity,
    *,
    step_name: str,
    attempt: int,
    model: str,
) -> Callable[[Callable[[], "ModelCallResult[T]"]], T]:
    """Record one model-call attempt around the wrapped call (SOLID-O).

    The wrapped callable returns a `ModelCallResult` (value + usage) or
    raises — `ModelCallError` when the provider returned usage despite the
    failure. Usage returned on a failed call is persisted; a crash (any
    non-`Exception` escape, or a dead process) records nothing, so lost
    usage stays explicitly incomplete (AD-18).
    """
    _validate_step_name(step_name)
    _validate_model(model)
    if attempt < 1:
        raise ValueError(f"attempt must be >= 1, got {attempt}")
    context = _CallContext(
        identity=identity, step_name=step_name, attempt=attempt, model=model
    )

    def run(call: Callable[[], "ModelCallResult[T]"]) -> T:
        try:
            result = call()
        except ModelCallError as exc:
            _record(store, context, StepStatus.FAILED, exc.outcome, exc.usage)
            raise
        except Exception:
            # AD-22: a failed attempt is a recorded step, never a silent
            # skip. `BaseException` (a crash) is deliberately not recorded.
            _record(store, context, StepStatus.FAILED, CallOutcome.ERROR, None)
            raise
        if result.outcome is not CallOutcome.VERDICT:
            raise ValueError(
                f"a completed attempt cannot carry outcome {result.outcome.value!r}"
            )
        _record(store, context, StepStatus.COMPLETED, result.outcome, result.usage)
        return result.value

    return run


def _record(
    store: UsageAuditStore,
    context: _CallContext,
    status: StepStatus,
    outcome: CallOutcome,
    usage: ModelUsage | None,
) -> None:
    """Persist the attempt row (AD-18), then log the invocation (AC3).

    The row goes first: a duplicate refusal or a crash between the two must
    never leave a log line claiming a recorded invocation with no row.
    """
    identity = context.identity
    store.record_attempt(
        ModelCallAttempt(
            run_id=identity.run_id,
            repo_id=identity.repo_id,
            step=context.step_name,
            attempt=context.attempt,
            model=context.model,
            status=status,
            outcome=outcome,
            usage=usage,
        )
    )
    log_invocation(
        _LOG,
        InvocationLine(
            event=EVENT_MODEL_CALL,
            run_id=identity.run_id,
            task_id=identity.task_id,
            step=context.step_name,
            attempt=context.attempt,
            status=status,
            outcome=outcome,
        ),
    )


def _counter_columns(
    usage: ModelUsage | None,
) -> tuple[int | None, int | None, int | None, int | None, int | None]:
    """The five token counters, NULL where the provider did not report."""
    if usage is None:
        return (None, None, None, None, None)
    return (
        usage.input_tokens,
        usage.output_tokens,
        usage.cache_read_input_tokens,
        usage.cache_creation_input_tokens_5m,
        usage.cache_creation_input_tokens_1h,
    )


class PostgresUsageAuditStore:
    """I/O adapter: insert-only, repo-bound attempt rows (AD-15, AD-18).

    No lease, no `Claim`, no state move (AD-23): bookkeeping, not a state
    transition. `connect` is injectable so unit tests drive the SQL through
    a fake connection.
    """

    def __init__(
        self,
        dsn: str,
        connect: Callable[[str], Connection] | None = None,
    ) -> None:
        self._dsn = dsn
        self._connect: Callable[[str], Connection] = connect or open_connection

    def record_attempt(self, attempt: ModelCallAttempt) -> None:
        _validate_step_name(attempt.step)
        _validate_model(attempt.model)
        counters = _counter_columns(attempt.usage)
        with self._connect(self._dsn) as conn:
            try:
                conn.execute(
                    _INSERT_ATTEMPT_SQL,
                    (
                        uuid.uuid4(),
                        attempt.run_id,
                        attempt.repo_id,
                        attempt.step,
                        attempt.attempt,
                        attempt.status.value,
                        attempt.model,
                        *counters,
                        attempt.outcome.value,
                    ),
                )
            except psycopg.errors.UniqueViolation as exc:
                # `(run_id, step, attempt)` is unique (AD-2): a repeated
                # attempt is definitive, never transient — and only a
                # violation of THIS constraint is one (shared translation).
                raise duplicate_step_error(
                    exc, attempt.run_id, attempt.step, attempt.attempt
                ) from exc
