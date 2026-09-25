"""Punch-out payloads (AD-14): escalation to the human and the human's approval."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from contracts.enums import EscalationReason, FailureClass

__all__ = ["ApprovalPayload", "Escalation"]


class Escalation(BaseModel):
    """`AWAITING_APPROVAL` message to the human (AD-1, AD-14)."""

    model_config = ConfigDict(extra="forbid")

    reason: EscalationReason
    proposal_step_id: str | None = None


class ApprovalPayload(BaseModel):
    """The human's `triage approve|reject` decision, one A2A message (AD-14).

    Effect contract of `class_override`: replaces only the low-confidence and
    unknown-class cutoff checks; `confidence` itself stays min(...) (AD-9).
    """

    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    note: str = Field(min_length=1)
    class_override: FailureClass | None = None
