"""Verdict surface (AD-6): Cap, Suspect, ProposedDiff, Quarantine, TriageVerdict.

`Sha40` lives once in citations.py (single source of the SHA fact); the AD-26
dry-run boundary relaxes it, never these production models.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator

from contracts.citations import Citation, Sha40
from contracts.enums import (
    CitationKind,
    DiffOperation,
    FailureClass,
    RiskTier,
    TerminalState,
)

__all__ = [
    "Cap",
    "DiffFile",
    "ProposedDiff",
    "Quarantine",
    "ShaPrefix",
    "Suspect",
    "TriageVerdict",
]


class Cap(BaseModel):
    """One confidence cap: a reason plus its citations; nothing may raise it (AD-9)."""

    model_config = ConfigDict(extra="forbid")

    value: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1)
    citations: list[Citation] = Field(min_length=1)


class Suspect(BaseModel):
    """Blame needs a commit citation plus a log line (AD-27) and a rank (AD-24)."""

    model_config = ConfigDict(extra="forbid")

    sha: Sha40
    author_login: str = Field(min_length=1)
    rank: PositiveInt
    citations: list[Citation] = Field(min_length=1)

    @model_validator(mode="after")
    def blame_kinds_are_present(self) -> "Suspect":
        kinds = {citation.kind for citation in self.citations}
        if CitationKind.COMMIT not in kinds or CitationKind.LOG_LINE not in kinds:
            raise ValueError(
                "citations must include at least one 'commit' and one 'log_line'"
            )
        return self


class DiffFile(BaseModel):
    """One file of the proposed diff (AD-6)."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    op: DiffOperation
    new_content: str


class ProposedDiff(BaseModel):
    """The Proposer's diff: `base_sha` and its files (AD-6)."""

    model_config = ConfigDict(extra="forbid")

    base_sha: Sha40
    files: list[DiffFile] = Field(min_length=1)


class Quarantine(BaseModel):
    """Quarantine recommendation stays out of `proposed_diff` (AD-21)."""

    model_config = ConfigDict(extra="forbid")

    test_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    citations: list[Citation]


class TriageVerdict(BaseModel):
    """The one verdict every consumer reads (AD-6, AD-9).

    The payload spelling is `class`; `populate_by_name` + `serialize_by_alias`
    keep the dump → revalidate round trip byte-faithful.
    """

    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, serialize_by_alias=True
    )

    class_: FailureClass = Field(alias="class")
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_jev: float = Field(ge=0.0, le=1.0)
    caps: list[Cap]
    suspects: list[Suspect]
    citations: list[Citation]
    risk_tier: RiskTier
    terminal_state: TerminalState | None = None
    proposed_diff: ProposedDiff | None = None
    quarantine: Quarantine | None = None


ShaPrefix = Annotated[str, Field(pattern=r"^[0-9a-f]{7,40}$")]
"""AD-26 dry-run boundary type: a unique `last_green..HEAD` prefix (never prod)."""
