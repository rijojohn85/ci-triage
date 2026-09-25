"""AC1/AC2: spine enums are exact and closed (AD-1, AD-4, AD-6)."""

import pydantic
import pytest
from pydantic import ValidationError

from contracts.enums import (
    DIFF_OPERATIONS,
    ESCALATION_REASONS,
    FAILURE_CLASSES,
    OBJECTION_SEVERITIES,
    RISK_TIERS,
    TERMINAL_STATES,
    DiffOperation,
    EscalationReason,
    FailureClass,
    ObjectionSeverity,
    RiskTier,
    TerminalState,
    validate_enum_value,
)


def test_ac1_failure_class_is_exactly_the_spine_set() -> None:
    assert FAILURE_CLASSES == ("code", "flaky", "infra", "external", "unknown")
    assert [member.value for member in FailureClass] == list(FAILURE_CLASSES)


def test_ac1_risk_tier_is_exactly_the_spine_set() -> None:
    assert RISK_TIERS == ("normal", "blocked", "not_gated")
    assert [member.value for member in RiskTier] == list(RISK_TIERS)


def test_ac1_terminal_state_is_exactly_the_spine_set() -> None:
    assert TERMINAL_STATES == (
        "pr_opened",
        "report_sent",
        "input_required",
        "rejected_by_human",
        "failed",
    )
    assert [member.value for member in TerminalState] == list(TERMINAL_STATES)


def test_ac2_objection_severity_is_exactly_the_spine_set() -> None:
    assert OBJECTION_SEVERITIES == ("info", "minor", "major", "dangerous")
    assert [member.value for member in ObjectionSeverity] == list(OBJECTION_SEVERITIES)


def test_ac2_diff_operations_are_exactly_the_spine_set() -> None:
    assert DIFF_OPERATIONS == ("add", "modify", "delete")
    assert [member.value for member in DiffOperation] == list(DIFF_OPERATIONS)


def test_ac1_escalation_reason_is_exactly_the_ad1_set() -> None:
    assert ESCALATION_REASONS == (
        "low_confidence",
        "unknown_class",
        "no_route",
        "validation_failed",
        "review_rejected",
        "gate_blocked",
    )
    assert [member.value for member in EscalationReason] == list(ESCALATION_REASONS)


@pytest.mark.parametrize(
    ("enum_type", "member", "good", "bad"),
    [
        (FailureClass, "class", "infra", "async"),
        (RiskTier, "risk_tier", "blocked", "hotfix"),
        (TerminalState, "terminal_state", "pr_opened", "done"),
        (ObjectionSeverity, "severity", "major", "critical"),
        (DiffOperation, "op", "modify", "rename"),
        (EscalationReason, "escalation_reason", "no_route", "manual"),
    ],
)
def test_ac2_enum_rejects_non_spine_value_and_names_field_and_values(
    enum_type: type, member: str, good: str, bad: str
) -> None:
    payload_model = pydantic.create_model("Payload", **{member: (enum_type, ...)})
    payload_model.model_validate({member: good})
    with pytest.raises(ValidationError) as exc:
        payload_model.model_validate({member: bad})
    message = str(exc.value)
    assert member in message
    assert good in message


def test_ac2_validate_enum_value_returns_member_and_lists_values_on_error() -> None:
    assert validate_enum_value(FailureClass, "code") is FailureClass.CODE
    with pytest.raises(ValueError, match="async"):
        validate_enum_value(FailureClass, "async")
