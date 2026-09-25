"""Evidence pack served to agents (AD-24): numbered log, commits, history, metrics."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PositiveInt

from contracts.citations import Sha40

__all__ = [
    "AUTHOR_ATTRIBUTION_FIELD",
    "CandidateSuspect",
    "CommitRecord",
    "DistilledLogLine",
    "EvidencePack",
    "HistoryRow",
]

MetricValue = Annotated[float, Field(allow_inf_nan=False)]
"""Runner metric value; NaN/Inf would break JSON dumping downstream."""

AUTHOR_ATTRIBUTION_FIELD = "author_login"
"""The one field naming a commit's author; AD-27 blame-free output drops it."""


class DistilledLogLine(BaseModel):
    """One numbered line of the distilled log (AD-20, AD-24)."""

    model_config = ConfigDict(extra="forbid")

    line_number: PositiveInt
    text: str


class CommitRecord(BaseModel):
    """A full-SHA commit of the `last_green..HEAD` range (AD-24)."""

    model_config = ConfigDict(extra="forbid")

    sha: Sha40
    message: str = Field(min_length=1)
    author_login: str = Field(min_length=1)


class CandidateSuspect(BaseModel):
    """A deterministically ranked candidate; the Analyzer picks from these (AD-24)."""

    model_config = ConfigDict(extra="forbid")

    sha: Sha40
    rank: PositiveInt
    changed_files: list[str]


class HistoryRow(BaseModel):
    """Structured-only history row, cited by `row_id` (AD-15)."""

    model_config = ConfigDict(extra="forbid")

    row_id: str = Field(min_length=1)
    fingerprint: str = Field(min_length=1)
    test_id: str = Field(min_length=1)
    error_type: str = Field(min_length=1)


class EvidencePack(BaseModel):
    """The deterministic single evidence source for every agent of the run (AD-24)."""

    model_config = ConfigDict(extra="forbid")

    repo_id: str = Field(min_length=1)
    last_green: Sha40
    distilled_log: list[DistilledLogLine] = Field(min_length=1)
    commits: list[CommitRecord] = Field(min_length=1)
    candidate_suspects: list[CandidateSuspect]
    history_rows: list[HistoryRow]
    metrics: dict[str, MetricValue]
