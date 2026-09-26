"""The shared step runner (story 2.8, AD-8 + AD-22): one execution policy.

Every agent step goes through `run_step`: it calls the agent over blocking
non-streaming A2A `send_message` (contextId = run_id, per-skill timeout from
`config/runtime.yaml`, AD-19), wraps every attempted call in 6.1's
`audit_model_call` (AD-18), applies the two independent retry budgets, and
commits the validated output + state move atomically through 2.3's
lease-guarded `StepRecorder` (AD-23).

The two budgets are counters, not loops-within-loops (spec Design Notes):

- **AD-8 (validation):** an invalid output consumes one unit; the structured
  `ValidationIssue`s are fed back into the next request. A second invalid
  output pauses `AWAITING_APPROVAL(validation_failed)` — never an uncited
  verdict committed.
- **AD-22 (transient):** a transient failure (network, 429, 5xx, timeout,
  retryable `AgentError`) consumes one unit; at most `max_attempts` transient
  attempts with config-driven backoff, then the run fails terminally and
  `write_terminal` writes history once. A definitive error fails without
  retry.

Attempt numbers increment across both budgets, so the `run_step` rows tell
the whole story in order — and they *continue* from whatever rows already
exist for this run (a reclaimed worker re-running a step whose earlier owner
left failed-attempt or `call:` audit rows starts at last+1 per namespace, so
the `(run_id, step, attempt)` identity never collides, AD-2). A failed
attempt that does not move state is an insert-only row through
`AttemptRecorder` (the 6.1 pattern, without the `call:` namespace
restriction); the terminal attempt's row is the commit row itself. The runner
returns a typed outcome and never raises past its boundary for expected
paths; fencing (`LeaseLost`) and store errors surface (AD-22: never
swallowed).

Known window (recovery in story 2.12): the terminal FAILED commit and the
`write_terminal` history write are two separate writes — a crash between
them leaves the run FAILED with history not yet written; `write_terminal` is
idempotent per run, so the recovery pass completes it without a duplicate.
"""

import json
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

import psycopg

from contracts.enums import EscalationReason
from guardrails.citation_check import ServedEvidence, ValidationIssue
from guardrails.validator import validate_classification, validate_verdict
from workflow.db import Connection, open_connection
from workflow.history import HistoryEntry, TerminalWrite
from workflow.history_store import HistoryStore
from workflow.leases import Claim
from workflow.run_states import RunState
from workflow.steps import (
    StepCommit,
    StepRecord,
    StepRecorder,
    StepStatus,
    duplicate_step_error,
)
from workflow.transitions import GuardInput
from workflow.usage_audit import (
    AuditIdentity,
    ModelCallResult,
    UsageAuditStore,
    audit_model_call,
)

__all__ = [
    "AttemptRecorder",
    "DefinitiveCallError",
    "FailedAttempt",
    "PostgresAttemptRecorder",
    "StepCommitted",
    "StepContext",
    "StepFailed",
    "StepOutcome",
    "StepPaused",
    "StepRunnerConfig",
    "StepTransport",
    "TransientCallError",
    "classification_validator",
    "run_step",
    "verdict_validator",
]

_INSERT_FAILED_ATTEMPT_SQL = """
INSERT INTO run_step (step_id, run_id, repo_id, step, attempt, status, output)
VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
"""

_LAST_ATTEMPTS_SQL = """
SELECT step, MAX(attempt) FROM run_step
WHERE run_id = %s AND repo_id = %s AND step = ANY(%s)
GROUP BY step
"""


class TransientCallError(Exception):
    """A retryable transport failure (AD-22): network, 429, 5xx, timeout."""


class DefinitiveCallError(Exception):
    """A non-retryable transport failure (AD-22): fail without retry."""


class StepTransport(Protocol):
    """The blocking transport seam 2.9 wires to the real agents (SOLID-I)."""

    def call(
        self, request: object, *, timeout_seconds: float
    ) -> ModelCallResult[object]: ...


@dataclass(frozen=True)
class FailedAttempt:
    """One failed attempt that moves no state: an insert-only `run_step` row."""

    run_id: uuid.UUID
    repo_id: int
    step: str
    attempt: int
    output: object


class AttemptRecorder(Protocol):
    """The insert-only surface for failed attempts (SOLID-I, AD-22).

    `last_attempts` is the re-entrancy read: the highest attempt number
    already recorded for the step's own rows and for its `call:` audit rows,
    so a reclaimed worker continues the numbering instead of colliding on
    the `(run_id, step, attempt)` identity (AD-2).
    """

    def record(self, attempt: FailedAttempt) -> None: ...

    def last_attempts(
        self, run_id: uuid.UUID, repo_id: int, step: str
    ) -> tuple[int, int]: ...


class PostgresAttemptRecorder:
    """I/O adapter: insert-only failed-attempt rows (AD-2, AD-22, AD-15).

    Deliberately mirrors 6.1's `PostgresUsageAuditStore` pattern without the
    `call:` namespace restriction: a failed attempt is a `run_step` row with
    no state move and no lease (AD-23 guards state moves, not bookkeeping).
    """

    def __init__(
        self,
        dsn: str,
        connect: Callable[[str], Connection] | None = None,
    ) -> None:
        self._dsn = dsn
        self._connect: Callable[[str], Connection] = connect or open_connection

    def record(self, attempt: FailedAttempt) -> None:
        with self._connect(self._dsn) as conn:
            try:
                conn.execute(
                    _INSERT_FAILED_ATTEMPT_SQL,
                    (
                        uuid.uuid4(),
                        attempt.run_id,
                        attempt.repo_id,
                        attempt.step,
                        attempt.attempt,
                        StepStatus.FAILED.value,
                        _as_json(attempt.output),
                    ),
                )
            except psycopg.errors.UniqueViolation as exc:
                # `(run_id, step, attempt)` is unique (AD-2): a repeated
                # attempt is definitive, never transient — and only a
                # violation of THIS constraint is one (shared translation).
                raise duplicate_step_error(
                    exc, attempt.run_id, attempt.step, attempt.attempt
                ) from exc

    def last_attempts(
        self, run_id: uuid.UUID, repo_id: int, step: str
    ) -> tuple[int, int]:
        """The highest existing attempt per namespace, 0 when none (AD-2)."""
        with self._connect(self._dsn) as conn:
            rows = conn.execute(
                _LAST_ATTEMPTS_SQL,
                (run_id, repo_id, [step, f"call:{step}"]),
            ).fetchall()
        last = {str(row[0]): cast(int, row[1]) for row in rows}
        return (last.get(step, 0), last.get(f"call:{step}", 0))


def _as_json(output: object) -> str | None:
    return None if output is None else json.dumps(output)


def classification_validator() -> Callable[[object], Sequence[ValidationIssue]]:
    """The CLASSIFYING seam: the real guardrails validator, unwrapped (AC1).

    `run_step` consumes plain issue sequences; this thin adapter calls 2.8's
    `validate_classification` (schema + parse only) and returns its issues.
    """

    def validate(payload: object) -> Sequence[ValidationIssue]:
        return validate_classification(payload).issues

    return validate


def verdict_validator(
    served: ServedEvidence, *, blame_free: bool
) -> Callable[[object], Sequence[ValidationIssue]]:
    """The verdict-step seam: 4.1's `validate_verdict`, unwrapped (AD-7).

    `served` is the evidence this run actually served and `blame_free` the
    caller's AD-27 decision; the adapter returns only the issues, which is
    the shape the runner's AD-8 budget consumes.
    """

    def validate(payload: object) -> Sequence[ValidationIssue]:
        return validate_verdict(payload, served, blame_free=blame_free).issues

    return validate


@dataclass(frozen=True)
class StepRunnerConfig:
    """One step's execution settings, all from config (AD-19).

    `model` and `step_timeout_seconds` come from `config/runtime.yaml` via
    `workflow.runtime_config`; `max_attempts`, `backoff_base_seconds` and
    `backoff_factor` come from `config/orchestrator.yaml` via
    `workflow.orchestrator_config`.
    """

    model: str
    step_timeout_seconds: float
    max_attempts: int
    backoff_base_seconds: float
    backoff_factor: float

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("model must be a non-empty model id (AD-18)")
        if self.step_timeout_seconds <= 0:
            raise ValueError("step_timeout_seconds must be positive")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1 (AD-22)")
        if self.backoff_base_seconds <= 0:
            raise ValueError("backoff_base_seconds must be positive")
        if self.backoff_factor < 1:
            raise ValueError("backoff_factor must be at least 1 (AD-19)")


@dataclass(frozen=True)
class StepContext:
    """Everything one `run_step` call needs about the run (≤ 5 params rule).

    `to_state` is the success target the caller chose for this step (the
    runner never re-implements the transition table — the recorder validates
    the move through 2.1's guard). `terminal` supplies the `TerminalWrite`
    identity (test_id/error_type/frames) for the FAILED history write.
    """

    claim: Claim
    repo_id: int
    request: object
    to_state: RunState
    terminal: TerminalWrite


@dataclass(frozen=True)
class StepCommitted:
    """The validated output and its state move committed (AC3)."""

    record: StepRecord
    output: object


@dataclass(frozen=True)
class StepPaused:
    """A second invalid output paused the run (AC1, AD-8)."""

    record: StepRecord
    reason: EscalationReason


@dataclass(frozen=True)
class StepFailed:
    """The budget was exhausted (or a definitive error): terminal (AC2)."""

    record: StepRecord
    history: HistoryEntry


StepOutcome = StepCommitted | StepPaused | StepFailed


@dataclass(frozen=True)
class _Edges:
    """The injected edges of one `run_step` call (private plumbing bag).

    Keeps every helper at ≤ 5 parameters (AGENTS.md clean code) while the
    public `run_step` signature stays the one the spec's Design Notes show.
    """

    skill: str
    recorder: StepRecorder
    attempts: AttemptRecorder
    history: HistoryStore
    audit: UsageAuditStore
    sleep: Callable[[float], None]
    config: StepRunnerConfig


def run_step(  # noqa: PLR0913, PLR0917 — the spec's Design Notes fix this shape
    context: StepContext,
    skill: str,
    transport: StepTransport,
    validate: Callable[[object], Sequence[ValidationIssue]],
    recorder: StepRecorder,
    attempts: AttemptRecorder,
    history: HistoryStore,
    audit: UsageAuditStore,
    sleep: Callable[[float], None],
    config: StepRunnerConfig,
) -> StepOutcome:
    """Run one agent step under the two independent retry budgets (2.8)."""
    if not skill.strip():
        raise ValueError("skill must be a non-empty step name (AD-2)")
    edges = _Edges(
        skill=skill,
        recorder=recorder,
        attempts=attempts,
        history=history,
        audit=audit,
        sleep=sleep,
        config=config,
    )
    # AD-2 re-entrancy: continue each namespace's numbering from whatever
    # rows already exist (a reclaimed worker never collides on the identity).
    attempt, call_attempt = attempts.last_attempts(
        context.claim.run_id, context.repo_id, skill
    )
    transient_failures = 0
    validation_retries = 0
    issues: tuple[ValidationIssue, ...] = ()
    while True:
        attempt += 1
        call_attempt += 1
        try:
            payload = _call_agent(
                context,
                transport,
                edges,
                call_attempt=call_attempt,
                issues=issues,
            )
        except TransientCallError as error:
            transient_failures += 1
            if transient_failures >= config.max_attempts:
                return _fail(context, edges, attempt=attempt, message=str(error))
            _record_failed(
                edges.attempts, context, skill, attempt, {"error": str(error)}
            )
            sleep(
                config.backoff_base_seconds
                * config.backoff_factor ** (transient_failures - 1)
            )
            continue
        except DefinitiveCallError as error:
            return _fail(context, edges, attempt=attempt, message=str(error))
        issues = tuple(validate(payload))
        if not issues:
            return _commit(context, edges, payload, attempt)
        if validation_retries < 1:
            # AD-8: one validation retry; the structured issues are fed back.
            validation_retries += 1
            _record_failed(
                edges.attempts, context, skill, attempt, _issues_output(issues)
            )
            continue
        return _pause(context, edges, attempt, issues)


def _call_agent(
    context: StepContext,
    transport: StepTransport,
    edges: _Edges,
    *,
    call_attempt: int,
    issues: tuple[ValidationIssue, ...],
) -> object:
    """One audited, timeout-bounded transport call (AD-18, AC3).

    `call_attempt` is the audit namespace's own count, continued from
    whatever `call:` rows already exist, so a row left behind by a fenced
    owner never collides with this worker's rows (AD-2).
    """
    identity = AuditIdentity(
        run_id=context.claim.run_id,
        repo_id=context.repo_id,
        task_id=str(context.claim.run_id),
    )
    wrapped = audit_model_call(
        edges.audit,
        identity,
        step_name=f"call:{edges.skill}",
        attempt=call_attempt,
        model=edges.config.model,
    )
    # 6.1's wrapper unwraps the ModelCallResult and returns the payload.
    return wrapped(
        lambda: transport.call(
            _with_feedback(context.request, issues),
            timeout_seconds=edges.config.step_timeout_seconds,
        )
    )


def _with_feedback(request: object, issues: tuple[ValidationIssue, ...]) -> object:
    """The retry request carries the structured validator errors (AD-8)."""
    if not issues:
        return request
    return {"request": request, "validation_issues": _issue_dicts(issues)}


def _issue_dicts(issues: Sequence[ValidationIssue]) -> list[dict[str, str]]:
    return [issue.model_dump() for issue in issues]


def _issues_output(
    issues: Sequence[ValidationIssue],
) -> dict[str, list[dict[str, str]]]:
    return {"validation_issues": _issue_dicts(issues)}


def _record_failed(
    attempts: AttemptRecorder,
    context: StepContext,
    skill: str,
    attempt: int,
    output: object,
) -> None:
    """An attempt that moves no state is still its own `run_step` row (AD-22)."""
    attempts.record(
        FailedAttempt(
            run_id=context.claim.run_id,
            repo_id=context.repo_id,
            step=skill,
            attempt=attempt,
            output=output,
        )
    )


def _commit(
    context: StepContext,
    edges: _Edges,
    payload: object,
    attempt: int,
) -> StepCommitted:
    """Validated output + state move in one lease-guarded commit (AD-2, AD-23)."""
    record = edges.recorder.record(
        context.claim,
        context.repo_id,
        StepCommit(
            step=edges.skill,
            to_state=context.to_state,
            attempt=attempt,
            status=StepStatus.COMPLETED,
            output=payload,
        ),
    )
    return StepCommitted(record=record, output=payload)


def _pause(
    context: StepContext,
    edges: _Edges,
    attempt: int,
    issues: tuple[ValidationIssue, ...],
) -> StepPaused:
    """Second invalid output → `AWAITING_APPROVAL(validation_failed)` (AD-8)."""
    record = edges.recorder.record(
        context.claim,
        context.repo_id,
        StepCommit(
            step=edges.skill,
            to_state=RunState.AWAITING_APPROVAL,
            attempt=attempt,
            status=StepStatus.FAILED,
            output=_issues_output(issues),
            guards=GuardInput(escalation_reason=EscalationReason.VALIDATION_FAILED),
        ),
    )
    return StepPaused(record=record, reason=EscalationReason.VALIDATION_FAILED)


def _fail(
    context: StepContext,
    edges: _Edges,
    *,
    attempt: int,
    message: str,
) -> StepFailed:
    """Terminal failure: one commit row + state move, then history once (AD-22)."""
    record = edges.recorder.record(
        context.claim,
        context.repo_id,
        StepCommit(
            step=edges.skill,
            to_state=RunState.FAILED,
            attempt=attempt,
            status=StepStatus.FAILED,
            output={"error": message},
        ),
    )
    entry = edges.history.write_terminal(context.terminal)
    return StepFailed(record=record, history=entry)
