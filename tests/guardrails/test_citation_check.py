"""Story 4.1 tests for `guardrails/citation_check.py` (AC1, AD-7, AD-24).

Every citation kind must resolve against the evidence actually served this
run: the `EvidencePack` plus this run's one Jev call. Unresolvable citations
come back as structured issues — collected, never raised (AD-8).
"""

import pytest

from contracts.citations import (
    Citation,
    CommitCitation,
    HistoryRowCitation,
    JevSignalCitation,
    LogLineCitation,
    MetricCitation,
)
from contracts.enums import FailureClass
from contracts.evidence import CandidateSuspect, CommitRecord, EvidencePack
from contracts.jev import JevChoice, JevClassification, JevInjectionScreen
from guardrails.citation_check import (
    JEV_SIGNAL_ANSWERS,
    ServedEvidence,
    ValidationIssue,
    check_citations,
)
from tests.contracts.samples import FULL_SHA

OTHER_SHA = "b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f80912ab"

LOG_LINES = (1, 2, 3)
METRICS = {"test_duration_seconds": 12.5}
HISTORY_ROW_IDS = ("row-1", "row-2")


def served() -> ServedEvidence:
    return ServedEvidence(
        pack=EvidencePack(
            repo_id="org/demo-repo",
            last_green=OTHER_SHA,
            distilled_log=[
                {"line_number": number, "text": f"line {number}"}
                for number in LOG_LINES
            ],
            commits=[
                CommitRecord(sha=FULL_SHA, message="fix: retry", author_login="dev")
            ],
            candidate_suspects=[
                CandidateSuspect(sha=FULL_SHA, rank=1, changed_files=["x.py"])
            ],
            history_rows=[
                {"row_id": row_id, "fingerprint": "f", "test_id": "t", "error_type": "e"}
                for row_id in HISTORY_ROW_IDS
            ],
            metrics=METRICS,
        ),
        jev=JevClassification(
            choice=JevChoice(
                answer=FailureClass.CODE,
                confidence=0.9,
                probabilities={FailureClass.CODE: 0.9},
            ),
            injection_screen=JevInjectionScreen(noul=0.1),
        ),
    )


def good_citations() -> list[Citation]:
    """One citation of every closed kind, each resolving against `served()`."""
    return [
        LogLineCitation(log_line=LOG_LINES[0]),
        CommitCitation(sha=FULL_SHA),
        MetricCitation(metric_key=next(iter(METRICS))),
        HistoryRowCitation(row_id=HISTORY_ROW_IDS[0]),
        JevSignalCitation(answer="choice"),
        JevSignalCitation(answer="noul"),
    ]


# --- AC1: every citation kind resolves against the served evidence


def test_ac1_each_citation_kind_resolves_against_served_evidence() -> None:
    issues = check_citations(good_citations(), served(), "citations")

    assert issues == []


def test_ac1_jev_signal_answers_are_the_one_jev_calls_two_answers() -> None:
    assert JEV_SIGNAL_ANSWERS == frozenset({"choice", "noul"})


@pytest.mark.parametrize(
    ("citation", "message"),
    [
        (
            LogLineCitation(log_line=99),
            "log_line 99 is not in the served distilled log",
        ),
        (
            CommitCitation(sha=OTHER_SHA),
            "commit citation sha is not in last_green..HEAD of the served pack",
        ),
        (
            MetricCitation(metric_key="not_collected"),
            "metric key 'not_collected' was not collected this run",
        ),
        (
            HistoryRowCitation(row_id="row-999"),
            "history_row id 'row-999' was not served this run",
        ),
        (
            JevSignalCitation(answer="probabilities"),
            "jev_signal answer 'probabilities' is not an answer of this run's Jev call",
        ),
    ],
    ids=[
        "log_line",
        "commit",
        "metric",
        "history_row",
        "jev_signal",
    ],
)
def test_ac1_unresolvable_citation_returns_structured_error(
    citation: Citation,
    message: str,
) -> None:
    issues = check_citations([citation], served(), "citations")

    assert issues == [
        ValidationIssue(
            code="citation_unresolvable",
            message=message,
            location="citations[0]",
        )
    ]
