"""Reviewer objection payload (AD-12); severity is closed (AD-6)."""

from pydantic import BaseModel, ConfigDict, Field

from contracts.citations import Citation
from contracts.enums import ObjectionSeverity

__all__ = ["Objection"]


class Objection(BaseModel):
    """One structured Reviewer objection; the Reviewer never edits the diff (AD-12)."""

    model_config = ConfigDict(extra="forbid")

    severity: ObjectionSeverity
    category: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    citation: Citation
