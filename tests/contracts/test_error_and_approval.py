"""AC3: AgentError, escalation set, approval override and A2A DataPart conventions."""

import pytest
from pydantic import ValidationError

from contracts.a2a import DataPart
from contracts.approval import ApprovalPayload, Escalation
from contracts.enums import EscalationReason, FailureClass
from contracts.errors import AgentError
from tests.contracts.samples import RUN_ID


def test_ac3_agent_error_is_code_message_retryable() -> None:
    error = AgentError.model_validate(
        {"code": "model_timeout", "message": "Claude call timed out", "retryable": True}
    )
    assert (error.code, error.message, error.retryable) == (
        "model_timeout",
        "Claude call timed out",
        True,
    )


def test_ac3_agent_error_shape_is_closed() -> None:
    with pytest.raises(ValidationError) as exc:
        AgentError.model_validate({"code": "x", "message": "y"})
    assert "retryable" in str(exc.value)


@pytest.mark.parametrize("reason", list(EscalationReason))
def test_ac3_escalation_accepts_all_six_ad1_reasons(reason: EscalationReason) -> None:
    escalation = Escalation.model_validate(
        {"reason": reason.value, "proposal_step_id": None}
    )
    assert escalation.reason == reason


def test_ac3_escalation_carries_optional_proposal_step_id() -> None:
    escalation = Escalation.model_validate(
        {"reason": "gate_blocked", "proposal_step_id": "step-42"}
    )
    assert escalation.proposal_step_id == "step-42"
    assert Escalation.model_validate({"reason": "no_route"}).proposal_step_id is None


def test_ac3_approval_payload_carries_class_override() -> None:
    approval = ApprovalPayload.model_validate(
        {
            "decision": "approve",
            "class_override": "flaky",
            "note": "flaky on green trees",
        }
    )
    assert approval.class_override == FailureClass.FLAKY
    assert approval.note.startswith("flaky")


def test_ac3_approval_class_override_is_optional() -> None:
    approval = ApprovalPayload.model_validate(
        {"decision": "reject", "class_override": None, "note": "touches workflows"}
    )
    assert approval.class_override is None


def test_ac3_approval_class_override_rejects_unknown_class() -> None:
    with pytest.raises(ValidationError) as exc:
        ApprovalPayload.model_validate(
            {"decision": "approve", "class_override": "hotfix", "note": "n"}
        )
    message = str(exc.value)
    assert "class_override" in message
    assert "code" in message


def test_ac3_approval_decision_rejects_padded_or_unknown_text() -> None:
    for bad in ("approve\n", " APPROVE", "reject ", "allow"):
        with pytest.raises(ValidationError) as exc:
            ApprovalPayload.model_validate(
                {"decision": bad, "class_override": None, "note": "n"}
            )
        assert "decision" in str(exc.value)


def agent_error_payload() -> dict[str, object]:
    return {"code": "timeout", "message": "x", "retryable": True}


def test_ac3_datapart_convention_task_and_context_id() -> None:
    payload = {
        "task_id": str(RUN_ID),
        "context_id": str(RUN_ID),
        "payload": agent_error_payload(),
    }
    part = DataPart.model_validate(payload)
    assert part.task_id == RUN_ID
    assert part.context_id == RUN_ID
    assert isinstance(part.payload, AgentError)


def test_ac3_datapart_rejects_non_uuid_convention_fields() -> None:
    payload = {
        "task_id": "run-1",
        "context_id": "run-1",
        "payload": agent_error_payload(),
    }
    with pytest.raises(ValidationError) as exc:
        DataPart.model_validate(payload)
    assert "task_id" in str(exc.value)


def test_ac3_datapart_rejects_mismatched_convention_fields() -> None:
    payload = {
        "task_id": str(RUN_ID),
        "context_id": "018f22e2-79b0-7cc3-98c4-dc0c0c07398f",
        "payload": agent_error_payload(),
    }
    with pytest.raises(ValidationError) as exc:
        DataPart.model_validate(payload)
    assert "task_id" in str(exc.value)


def test_ac3_datapart_rejects_unknown_top_level_key() -> None:
    payload = {
        "task_id": str(RUN_ID),
        "context_id": str(RUN_ID),
        "payload": agent_error_payload(),
        "trace": "extra",
    }
    with pytest.raises(ValidationError) as exc:
        DataPart.model_validate(payload)
    assert "trace" in str(exc.value)


def test_ac3_datapart_rejects_unknown_payload_variant() -> None:
    payload = {
        "task_id": str(RUN_ID),
        "context_id": str(RUN_ID),
        "payload": {"verdict": "gibberish", "blame": "someone"},
    }
    with pytest.raises(ValidationError) as exc:
        DataPart.model_validate(payload)
    assert "payload" in str(exc.value)
