"""Provider usage of one model call (story 6.1, AD-18).

The AD-18 rule as a type: a token counter the provider did not report is
NULL, never 0 — a reported 0 is a real value. The per-call outcome is the
closed `CallOutcome` set here (never free text, never a raw response,
AD-18); the audit row reads it from the attempt, not from the usage.

Pure contract only: no SQL, no I/O (SOLID-S; the audit persistence lives in
`workflow/usage_audit.py`).
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["CallOutcome", "ModelUsage"]


class CallOutcome(str, Enum):
    """Closed `run_step.outcome` set for a model call (AD-18).

    `(str, Enum)` keeps the Python >= 3.10 floor (StrEnum is 3.11+).
    """

    VERDICT = "verdict"
    ERROR = "error"
    TIMEOUT = "timeout"


class ModelUsage(BaseModel):
    """What one model call consumed: the model and its token counters.

    Every counter is nullable; NULL means "provider did not report" (AD-18),
    so downstream costing (6.2) can keep incomplete totals visibly
    incomplete instead of silently summing zeros.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(min_length=1)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cache_read_input_tokens: int | None = Field(default=None, ge=0)
    cache_creation_input_tokens_5m: int | None = Field(default=None, ge=0)
    cache_creation_input_tokens_1h: int | None = Field(default=None, ge=0)
