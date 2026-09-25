"""A2A DataPart envelope: the data the orchestrator and spokes exchange (AD-4, AD-5)."""

from pydantic import UUID7, BaseModel, ConfigDict, model_validator

from contracts.approval import ApprovalPayload, Escalation
from contracts.errors import AgentError
from contracts.evidence import EvidencePack
from contracts.verdict import TriageVerdict

__all__ = ["DataPart"]


class DataPart(BaseModel):
    """Envelope for typed contract payloads over A2A `send_message`.

    Convention: `task_id` = `run_id` = A2A `contextId` (UUIDv7); the read-only
    TaskStore adapter projects `triage_run` state onto this identity (AD-4).
    """

    model_config = ConfigDict(extra="forbid")

    task_id: UUID7
    context_id: UUID7
    payload: TriageVerdict | EvidencePack | AgentError | ApprovalPayload | Escalation

    @model_validator(mode="after")
    def convention_ids_match(self) -> "DataPart":
        if self.task_id != self.context_id:
            raise ValueError("task_id and context_id must both be the run_id (AD-4)")
        return self
