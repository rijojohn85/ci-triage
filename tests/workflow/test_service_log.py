"""Story 6.1 unit tests — the structured invocation-log helper (AC3, AD-25).

Every service-log line for a model-call invocation is one JSON object whose
keys are exactly the allowlisted fields; run_id, task_id and step are on
every line, status/outcome are typed to the closed `StepStatus`/`CallOutcome`
sets, and no token count, secret or raw log text can enter a line (the
helper's signature has no channel for them).
"""

import json
import uuid

from contracts.usage import CallOutcome
from workflow.service_log import (
    EVENT_MODEL_CALL,
    LOG_FIELDS,
    InvocationLine,
    log_invocation,
)
from workflow.steps import StepStatus

RUN_ID = uuid.UUID("018f6a2c-0000-7000-8000-000000000001")


class RecordingLogger:
    """Protocol fake: captures the emitted lines."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def info(self, message: str) -> None:
        self.lines.append(message)


def emitted(logger: RecordingLogger) -> list[dict[str, object]]:
    return [json.loads(line) for line in logger.lines]


def test_ac3_every_log_line_carries_run_id_task_id_step() -> None:
    logger = RecordingLogger()

    log_invocation(
        logger,
        InvocationLine(
            event=EVENT_MODEL_CALL,
            run_id=RUN_ID,
            task_id=str(RUN_ID),
            step="call:system_one",
            attempt=1,
            status=StepStatus.COMPLETED,
            outcome=CallOutcome.VERDICT,
        ),
    )

    (line,) = emitted(logger)
    assert line["event"] == EVENT_MODEL_CALL
    assert line["run_id"] == str(RUN_ID)
    assert line["task_id"] == str(RUN_ID)
    assert line["step"] == "call:system_one"


def test_ac3_line_keys_are_exactly_the_allowlist() -> None:
    logger = RecordingLogger()

    log_invocation(
        logger,
        InvocationLine(
            event=EVENT_MODEL_CALL,
            run_id=RUN_ID,
            task_id=str(RUN_ID),
            step="call:system_one",
            attempt=2,
        ),
    )

    (line,) = emitted(logger)
    assert set(line) == set(LOG_FIELDS)
    assert line["status"] is None and line["outcome"] is None


def test_ac3_optional_fields_are_the_closed_set_values() -> None:
    logger = RecordingLogger()

    log_invocation(
        logger,
        InvocationLine(
            event=EVENT_MODEL_CALL,
            run_id=RUN_ID,
            task_id=str(RUN_ID),
            step="call:system_one",
            attempt=3,
            status=StepStatus.FAILED,
            outcome=CallOutcome.TIMEOUT,
        ),
    )

    (line,) = emitted(logger)
    assert line["status"] == StepStatus.FAILED.value
    assert line["outcome"] == CallOutcome.TIMEOUT.value
    assert line["attempt"] == 3
    assert all(
        isinstance(value, (str, int)) or value is None for value in line.values()
    )
