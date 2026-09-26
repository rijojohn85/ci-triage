"""Citation resolution against the evidence served this run (AD-7, AD-24).

Pure domain code (stdlib + pydantic + `contracts` only, layer contract): each
closed citation kind resolves against the `ServedEvidence` — the `EvidencePack`
the orchestrator served this run plus this run's one Jev call. An unresolvable
citation becomes a structured `ValidationIssue`, collected — never raised —
because AD-8's retry/pause policy belongs to the shared step runner (2.8).
"""

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from contracts.citations import (
    Citation,
    CommitCitation,
    HistoryRowCitation,
    JevSignalCitation,
    LogLineCitation,
    MetricCitation,
)
from contracts.evidence import EvidencePack
from contracts.jev import JevClassification

__all__ = [
    "JEV_SIGNAL_ANSWERS",
    "ServedEvidence",
    "ValidationIssue",
    "check_citations",
]


class ValidationIssue(BaseModel):
    """One structured validator finding (AD-8): `code` + `message` + `location`.

    The one issue shape for both validation layers (story 4.1): the JSON
    schema layer, the pydantic parse layer and the semantic checks all emit
    it; `guardrails.validator` re-exports it as its public surface.
    """

    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    location: str


class ServedEvidence(BaseModel):
    """The evidence one run served: the pack plus that run's Jev call (AD-24).

    Every citation must resolve against exactly this — never against evidence
    from another run or repository (AD-7, AD-20).
    """

    model_config = ConfigDict(frozen=True)

    pack: EvidencePack
    jev: JevClassification


JEV_SIGNAL_ANSWERS = frozenset({"choice", "noul"})
"""The two answers of the one `system_one` Jev call (AD-7, AD-11); the
injection screen's own cap cites `noul`, so it always resolves."""

CITATION_UNRESOLVABLE = "citation_unresolvable"
"""Issue code: a citation whose locator is absent from the served pack."""


def check_citations(
    citations: Sequence[Citation],
    served: ServedEvidence,
    location: str,
) -> list[ValidationIssue]:
    """Resolve every citation against `served`; one issue per failure.

    `location` is the issue-location base (e.g. `suspects[0].citations`);
    per-citation issues append `[i]`.
    """
    return [
        ValidationIssue(
            code=CITATION_UNRESOLVABLE,
            message=_unresolvable_message(citation),
            location=f"{location}[{index}]",
        )
        for index, citation in enumerate(citations)
        if not _resolves(citation, served)
    ]


def _resolves(citation: Citation, served: ServedEvidence) -> bool:
    """The closed per-kind resolution table (AD-7); extend by adding a case."""
    pack = served.pack
    match citation:
        case LogLineCitation():
            return citation.log_line in {
                line.line_number for line in pack.distilled_log
            }
        case CommitCitation():
            return citation.sha in {record.sha for record in pack.commits}
        case MetricCitation():
            return citation.metric_key in pack.metrics
        case HistoryRowCitation():
            return citation.row_id in {row.row_id for row in pack.history_rows}
        case JevSignalCitation():
            return citation.answer in JEV_SIGNAL_ANSWERS
        case _:
            # An unknown kind is an unresolvable citation, never a raise:
            # the validator collects issues, it does not throw (AD-8).
            return False


def _unresolvable_message(citation: Citation) -> str:
    """One human-readable reason per kind; the kind word stays in the message."""
    match citation:
        case LogLineCitation():
            return f"log_line {citation.log_line} is not in the served distilled log"
        case CommitCitation():
            return "commit citation sha is not in last_green..HEAD of the served pack"
        case MetricCitation():
            return f"metric key '{citation.metric_key}' was not collected this run"
        case HistoryRowCitation():
            return f"history_row id '{citation.row_id}' was not served this run"
        case JevSignalCitation():
            return (
                f"jev_signal answer '{citation.answer}' is not an answer of "
                "this run's Jev call"
            )
        case _:
            return f"unknown citation kind: {type(citation).__name__}"
