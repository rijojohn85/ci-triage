"""Closed citation union (AD-6, AD-7): one model per kind, discriminated on `kind`."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from contracts.enums import CitationKind

__all__ = [
    "Citation",
    "CommitCitation",
    "HistoryRowCitation",
    "JevSignalCitation",
    "LogLineCitation",
    "MetricCitation",
    "Sha40",
    "create_citation",
]


class _CitationBase(BaseModel):
    """Trace markers go inline where an envelope embeds a citation."""

    model_config = ConfigDict(extra="forbid")


class LogLineCitation(_CitationBase):
    """`log_line` locator: a line number in the numbered distilled log (AD-7)."""

    kind: Literal[CitationKind.LOG_LINE] = CitationKind.LOG_LINE
    log_line: int = Field(ge=1)


Sha40 = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
"""Full 40-char hex SHA for production payloads (AD-6); AD-26 dry-run relaxes it."""


class CommitCitation(_CitationBase):
    """`commit` locator: a full `Sha40` SHA within `last_green..HEAD` (AD-7)."""

    kind: Literal[CitationKind.COMMIT] = CitationKind.COMMIT
    sha: Sha40


class MetricCitation(_CitationBase):
    """`metric` locator: a key of the collected runner metrics (AD-7)."""

    kind: Literal[CitationKind.METRIC] = CitationKind.METRIC
    metric_key: str = Field(min_length=1)


class HistoryRowCitation(_CitationBase):
    """`history_row` locator: a `row_id` served in the evidence pack (AD-7, AD-15)."""

    kind: Literal[CitationKind.HISTORY_ROW] = CitationKind.HISTORY_ROW
    row_id: str = Field(min_length=1)


class JevSignalCitation(_CitationBase):
    """`jev_signal` locator: the answer key of this run's Jev call (AD-7, AD-11)."""

    kind: Literal[CitationKind.JEV_SIGNAL] = CitationKind.JEV_SIGNAL
    answer: str = Field(min_length=1)


Citation = Annotated[
    LogLineCitation
    | CommitCitation
    | MetricCitation
    | HistoryRowCitation
    | JevSignalCitation,
    Field(discriminator="kind"),
]

_CITATION_ADAPTER: TypeAdapter[Citation] = TypeAdapter(Citation)


def create_citation(payload: dict[str, object]) -> Citation:
    """Validate one raw citation payload into the discriminated union (AD-7)."""
    return _CITATION_ADAPTER.validate_python(payload)
