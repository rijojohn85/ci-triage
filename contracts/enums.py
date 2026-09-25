"""Spine enums: the exact domain value sets (AD-1, AD-4, AD-6).

One source per fact: every inter-agent payload reuses these members; nothing
else defines a class/severity/op list. `(str, Enum)` keeps the a2a-sdk
Python >= 3.10 floor (StrEnum is 3.11+).
"""

from enum import Enum
from typing import TypeVar

E = TypeVar("E", bound=Enum)

__all__ = [
    "CITATION_KINDS",
    "DIFF_OPERATIONS",
    "ESCALATION_REASONS",
    "FAILURE_CLASSES",
    "OBJECTION_SEVERITIES",
    "RISK_TIERS",
    "TERMINAL_STATES",
    "CitationKind",
    "DiffOperation",
    "EscalationReason",
    "FailureClass",
    "ObjectionSeverity",
    "RiskTier",
    "TerminalState",
    "validate_enum_value",
]


class FailureClass(str, Enum):
    """Failure class enum `code | flaky | infra | external | unknown` (AD-11)."""

    CODE = "code"
    FLAKY = "flaky"
    INFRA = "infra"
    EXTERNAL = "external"
    UNKNOWN = "unknown"


class RiskTier(str, Enum):
    """Risk gate outcome `normal | blocked | not_gated` (AD-6, AD-13)."""

    NORMAL = "normal"
    BLOCKED = "blocked"
    NOT_GATED = "not_gated"


class TerminalState(str, Enum):
    """Terminal `triage_run` outcome, per the AD-4 projection table."""

    PR_OPENED = "pr_opened"
    REPORT_SENT = "report_sent"
    INPUT_REQUIRED = "input_required"
    REJECTED_BY_HUMAN = "rejected_by_human"
    FAILED = "failed"


class CitationKind(str, Enum):
    """Closed citation kinds, each with a locator (AD-7)."""

    LOG_LINE = "log_line"
    COMMIT = "commit"
    METRIC = "metric"
    HISTORY_ROW = "history_row"
    JEV_SIGNAL = "jev_signal"


class ObjectionSeverity(str, Enum):
    """Reviewer objection severity `info | minor | major | dangerous` (AD-12)."""

    INFO = "info"
    MINOR = "minor"
    MAJOR = "major"
    DANGEROUS = "dangerous"


class DiffOperation(str, Enum):
    """Proposed-diff file operation `add | modify | delete` (AD-6)."""

    ADD = "add"
    MODIFY = "modify"
    DELETE = "delete"


class EscalationReason(str, Enum):
    """`AWAITING_APPROVAL` escalation reasons, the exact AD-1 set."""

    LOW_CONFIDENCE = "low_confidence"
    UNKNOWN_CLASS = "unknown_class"
    NO_ROUTE = "no_route"
    VALIDATION_FAILED = "validation_failed"
    REVIEW_REJECTED = "review_rejected"
    GATE_BLOCKED = "gate_blocked"


FAILURE_CLASSES = tuple(member.value for member in FailureClass)
RISK_TIERS = tuple(member.value for member in RiskTier)
TERMINAL_STATES = tuple(member.value for member in TerminalState)
CITATION_KINDS = tuple(member.value for member in CitationKind)
OBJECTION_SEVERITIES = tuple(member.value for member in ObjectionSeverity)
DIFF_OPERATIONS = tuple(member.value for member in DiffOperation)
ESCALATION_REASONS = tuple(member.value for member in EscalationReason)


def validate_enum_value(enum_type: type[E], raw: str) -> E:
    """Convert `raw` to the matching enum member, listing the values on failure.

    Used where payload text is validated outside a model field, so the AD-8
    retry can feed the allowed values back to the agent.
    """
    allowed = tuple(member.value for member in enum_type)
    if raw not in allowed:
        raise ValueError(
            f"invalid {enum_type.__name__} value {raw!r}; allowed: {', '.join(allowed)}"
        )
    return enum_type(raw)
