"""Story 4.1 tests for `guardrails/validator.py` (AC1, AC2, AC3).

Two validation layers, one issue shape: the committed generated JSON schema
catches shape/enum/pattern violations; the `contracts.TriageVerdict` parse
catches the invariants JSON Schema cannot express (the min rule, suspect
blame kinds). All issues are collected — never raised — because AD-8's retry
policy belongs to the shared step runner (2.8), not here.
"""

import pytest

from contracts.citations import CommitCitation, JevSignalCitation, LogLineCitation
from contracts.enums import FailureClass, RiskTier
from contracts.verdict import Suspect, TriageVerdict
from guardrails.citation_check import ServedEvidence, ValidationIssue
from guardrails.validator import validate_verdict
from tests.contracts.samples import FULL_SHA
from tests.guardrails.test_citation_check import OTHER_SHA, served

SOMEONE = "someone"


def verdict_payload() -> dict[str, object]:
    """A fully valid verdict for `served()`, dumped through the contract."""
    verdict = TriageVerdict(
        class_=FailureClass.CODE,
        confidence=0.9,
        confidence_jev=0.9,
        caps=(),
        suspects=[
            Suspect(
                sha=FULL_SHA,
                author_login=SOMEONE,
                rank=1,
                citations=[
                    CommitCitation(sha=FULL_SHA),
                    LogLineCitation(log_line=1),
                ],
            )
        ],
        citations=[JevSignalCitation(answer="choice")],
        risk_tier=RiskTier.NORMAL,
    )
    return verdict.model_dump(mode="json")


def codes(issues: list[ValidationIssue] | tuple[ValidationIssue, ...]) -> list[str]:
    return [issue.code for issue in issues]


# --- AC1: schema failures are structured, never silent


def test_ac1_valid_verdict_parses_with_zero_issues() -> None:
    result = validate_verdict(verdict_payload(), served(), blame_free=False)

    assert result.issues == ()
    assert result.verdict is not None
    assert result.verdict.class_ is FailureClass.CODE


def test_ac1_schema_failure_is_structured_not_silent() -> None:
    payload = verdict_payload()
    payload["suspects"][0]["citations"][0]["sha"] = "abc1234"  # type: ignore[index]
    payload["unknown_field"] = "nope"

    result = validate_verdict(payload, served(), blame_free=False)

    assert result.verdict is None
    assert set(codes(result.issues)) == {"schema"}
    locations = [issue.location for issue in result.issues]
    # The parse layer spells the discriminated-union leaf with its branch tag.
    assert "suspects[0].citations[0].commit.sha" in locations
    assert "unknown_field" in locations


# --- AC1: a suspect without its blame citations is rejected (AD-27, via parse)


def test_ac1_missing_suspect_blame_citations_rejected() -> None:
    payload = verdict_payload()
    payload["suspects"][0]["citations"] = [  # type: ignore[index]
        {"kind": "metric", "metric_key": "test_duration_seconds"}
    ]

    result = validate_verdict(payload, served(), blame_free=False)

    assert result.verdict is None
    assert "commit" in result.issues[0].message
    assert "log_line" in result.issues[0].message
    assert result.issues[0].location == "suspects[0]"


# --- AC2: suspects come only from candidate_suspects


def test_ac2_suspect_must_be_a_served_candidate() -> None:
    payload = verdict_payload()
    payload["suspects"][0]["sha"] = OTHER_SHA  # type: ignore[index]

    result = validate_verdict(payload, served(), blame_free=False)

    assert codes(result.issues) == ["suspect_not_candidate"]
    assert result.issues[0].location == "suspects[0]"


# --- AC2: caps carry cited reasons and can only lower confidence


def test_ac2_cap_cannot_raise_confidence() -> None:
    payload = verdict_payload()
    payload["caps"] = [  # type: ignore[assignment]
        {
            "value": 0.8,
            "reason": "history says flaky",
            "citations": [{"kind": "history_row", "row_id": "row-1"}],
        }
    ]
    # min(0.9, 0.8) = 0.8, but the payload claims 0.9: the cap was raised past.
    payload["confidence"] = 0.9

    result = validate_verdict(payload, served(), blame_free=False)

    assert result.verdict is None
    assert "min(confidence_jev, caps" in result.issues[0].message
    # A model-validator failure sits at the payload root.
    assert result.issues[0].location == ""


# --- AC2: short production SHAs are rejected (schema pattern)


def test_ac2_short_production_sha_rejected() -> None:
    payload = verdict_payload()
    payload["suspects"][0]["sha"] = "abc1234"  # type: ignore[index]

    result = validate_verdict(payload, served(), blame_free=False)

    assert result.verdict is None
    assert set(codes(result.issues)) == {"schema"}
    assert "suspects[0].sha" in [issue.location for issue in result.issues]
    assert "40" in result.issues[0].message or "pattern" in result.issues[0].message


# --- AC2: foreign-repo evidence never becomes a citation


def test_ac2_foreign_commit_evidence_rejected() -> None:
    payload = verdict_payload()
    payload["suspects"][0]["citations"][0]["sha"] = OTHER_SHA  # type: ignore[index]

    result = validate_verdict(payload, served(), blame_free=False)

    assert codes(result.issues) == ["citation_unresolvable"]
    assert result.issues[0].location == "suspects[0].citations[0]"


# --- AC2: probabilities are audit-only, never confidence_jev (AD-9)


def test_ac2_probabilities_as_confidence_rejected() -> None:
    payload = verdict_payload()
    payload["confidence"] = 0.4  # type: ignore[index]
    payload["confidence_jev"] = 0.4  # type: ignore[index]

    result = validate_verdict(payload, served(), blame_free=False)

    assert codes(result.issues) == ["confidence_mismatch"]
    assert result.issues[0].location == "confidence_jev"


# --- AC3: author attribution in blame-free output is a structured error


def test_ac3_attribution_present_is_a_structured_error() -> None:
    result = validate_verdict(verdict_payload(), served(), blame_free=True)

    assert codes(result.issues) == ["attribution_present"]
    assert result.issues[0].location == "suspects[0].author_login"


def test_ac3_attribution_is_allowed_when_not_blame_free() -> None:
    result = validate_verdict(verdict_payload(), served(), blame_free=False)

    assert result.issues == ()


def test_ac3_attribution_is_collected_even_when_the_parse_fails() -> None:
    # The leak must reach the retry feedback even when the payload is also
    # invalid, so the attribution check runs before the parse early return.
    payload = verdict_payload()
    payload["unknown_field"] = "nope"

    result = validate_verdict(payload, served(), blame_free=True)

    assert result.verdict is None
    assert "attribution_present" in codes(result.issues)


# --- AC1: every citation surface is walked (caps, quarantine, top level)


def test_ac1_cap_and_quarantine_citations_resolve_against_the_pack() -> None:
    payload = verdict_payload()
    payload["caps"] = [  # type: ignore[assignment]
        {
            "value": 0.5,
            "reason": "injection pre-screen flagged this answer",
            "citations": [{"kind": "jev_signal", "answer": "noul"}],
        }
    ]
    payload["confidence"] = 0.5
    payload["quarantine"] = {  # type: ignore[assignment]
        "test_id": "tests/test_x.py",
        "reason": "flaky in history",
        "citations": [{"kind": "history_row", "row_id": "row-1"}],
    }

    result = validate_verdict(payload, served(), blame_free=False)

    assert result.issues == ()


def test_ac1_quarantine_citation_unresolvable_is_located() -> None:
    payload = verdict_payload()
    payload["quarantine"] = {  # type: ignore[assignment]
        "test_id": "tests/test_x.py",
        "reason": "flaky in history",
        "citations": [{"kind": "history_row", "row_id": "row-999"}],
    }

    result = validate_verdict(payload, served(), blame_free=False)

    assert codes(result.issues) == ["citation_unresolvable"]
    assert result.issues[0].location == "quarantine.citations[0]"


# --- guard: the validator never raises past its boundary


def test_ac1_garbage_payload_is_collected_not_raised() -> None:
    result = validate_verdict({"class": "nonsense"}, served(), blame_free=False)

    assert result.verdict is None
    assert len(result.issues) > 0


@pytest.mark.parametrize("payload", [None, [], "text", 7])
def test_ac1_non_object_payload_is_a_schema_issue(payload: object) -> None:
    result = validate_verdict(payload, served(), blame_free=False)

    assert result.verdict is None
    assert set(codes(result.issues)) == {"schema"}


def test_served_evidence_is_importable_from_the_validator_surface() -> None:
    # The validator module is the public surface 2.8 consumes; ServedEvidence
    # and ValidationIssue must be reachable there.
    from guardrails.validator import ServedEvidence as ServedEvidenceAlias
    from guardrails.validator import ValidationIssue as ValidationIssueAlias

    assert ServedEvidenceAlias is ServedEvidence
    assert ValidationIssueAlias is ValidationIssue
