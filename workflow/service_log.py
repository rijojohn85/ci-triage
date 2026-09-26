"""Structured, allowlisted JSON log lines for model-call invocations (AC3, AD-25).

Every line is one JSON object whose keys are exactly the `LOG_FIELDS`
allowlist — run_id, task_id and step are on every line. The closed-set
guarantee is typed, not conventional: `status` is a `StepStatus | None` and
`outcome` a `CallOutcome | None`, so only the closed `run_step` values can
be emitted, and the field list exists once (derived from the dataclass).

SOLID-S: this module only formats and emits; the audit wrapper decides
*when* an invocation logs.
"""

import json
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from contracts.usage import CallOutcome
from workflow.steps import StepStatus

__all__ = [
    "EVENT_MODEL_CALL",
    "LOG_FIELDS",
    "InvocationLine",
    "InvocationLogger",
    "log_invocation",
]

EVENT_MODEL_CALL = "model_call"
"""The one event name for an audited model-call invocation."""


class InvocationLogger(Protocol):
    """The one method the emitter needs (SOLID-I); `logging.Logger` fits."""

    def info(self, message: str) -> None: ...


@dataclass(frozen=True)
class InvocationLine:
    """The allowlisted fields of one invocation log line.

    `status`/`outcome` are the closed `run_step` values (or None before the
    call finishes); `LOG_FIELDS` is derived from these fields, so the
    allowlist and the line shape cannot drift apart.
    """

    event: str
    run_id: uuid.UUID
    task_id: str
    step: str
    attempt: int
    status: StepStatus | None = None
    outcome: CallOutcome | None = None


LOG_FIELDS = frozenset(InvocationLine.__dataclass_fields__)
"""The one allowlist: nothing outside these keys appears on a line."""


def log_invocation(logger: InvocationLogger, line: InvocationLine) -> None:
    """Emit one allowlisted JSON line; nothing else can be attached."""
    values: dict[str, object] = {}
    for name in InvocationLine.__dataclass_fields__:
        value: object = getattr(line, name)
        if isinstance(value, Enum):
            value = value.value
        elif isinstance(value, uuid.UUID):
            value = str(value)
        values[name] = value
    logger.info(json.dumps(values, sort_keys=True))
