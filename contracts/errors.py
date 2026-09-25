"""Agent-facing error shape (consistency conventions; AD-22 retryability flag)."""

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["AgentError"]


class AgentError(BaseModel):
    """Spoke errors return A2A `FAILED` carrying exactly this shape."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    retryable: bool
