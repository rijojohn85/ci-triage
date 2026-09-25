"""AC1 verdict and AC2 closure/nullability at the TriageVerdict boundary."""

import pytest
from pydantic import ValidationError

from contracts.enums import FailureClass, RiskTier, TerminalState
from contracts.objections import Objection
from contracts.verdict import Quarantine, Suspect, TriageVerdict
from tests.contracts.samples import FULL_SHA

REPRESENTATIVE_CONFIDENCE = 0.8
REPRESENTATIVE_CONFIDENCE_JEV = 0.9


def representative_verdict_payload() -> dict[str, object]:
    """AC1 happy path: terminal_state null while running; diff and quarantine null."""
    return {
        "class": "flaky",
        "confidence": REPRESENTATIVE_CONFIDENCE,
        "confidence_jev": REPRESENTATIVE_CONFIDENCE_JEV,
        "caps": [
            {
                "value": 0.85,
                "reason": "injection pre-screen flagged one answer",
                "citations": [{"kind": "jev_signal", "answer": "noul"}],
            }
        ],
        "suspects": [
            {
                "sha": FULL_SHA,
                "author_login": "someone",
                "rank": 1,
                "citations": [
                    {"kind": "commit", "sha": FULL_SHA},
                    {"kind": "log_line", "log_line": 3},
                ],
            }
        ],
        "citations": [{"kind": "log_line", "log_line": 3}],
        "risk_tier": "normal",
        "terminal_state": None,
        "proposed_diff": None,
        "quarantine": None,
    }


def test_ac1_representative_verdict_carries_every_spine_field() -> None:
    verdict = TriageVerdict.model_validate(representative_verdict_payload())
    assert verdict.class_ == FailureClass.FLAKY
    assert verdict.confidence == REPRESENTATIVE_CONFIDENCE
    assert verdict.confidence_jev == REPRESENTATIVE_CONFIDENCE_JEV
    assert len(verdict.caps) == 1
    assert verdict.suspects[0].author_login == "someone"
    assert verdict.risk_tier == RiskTier.NORMAL
    assert verdict.terminal_state is None
    assert verdict.proposed_diff is None
    assert verdict.quarantine is None


def test_ac1_verdict_round_trips_through_dump_and_revalidate() -> None:
    verdict = TriageVerdict.model_validate(representative_verdict_payload())
    reparsed = TriageVerdict.model_validate(verdict.model_dump())
    assert reparsed.class_ == FailureClass.FLAKY
    assert reparsed == verdict


def test_ac1_terminal_state_nullability_follows_ad4() -> None:
    payload = representative_verdict_payload()
    assert TriageVerdict.model_validate(payload).terminal_state is None
    payload["terminal_state"] = "report_sent"
    assert TriageVerdict.model_validate(payload).terminal_state == (
        TerminalState.REPORT_SENT
    )
    del payload["terminal_state"]
    assert TriageVerdict.model_validate(payload).terminal_state is None


def test_ac2_confidence_bounds_are_one_min() -> None:
    payload = representative_verdict_payload()
    for bad in (-0.1, 1.1):
        payload["confidence"] = bad
        with pytest.raises(ValidationError) as exc:
            TriageVerdict.model_validate(payload)
        assert "confidence" in str(exc.value)
    payload["confidence"] = 0.0
    TriageVerdict.model_validate(payload)
    payload["confidence"] = 1.0
    TriageVerdict.model_validate(payload)


def test_ac2_class_rejects_non_spine_value() -> None:
    payload = representative_verdict_payload()
    payload["class"] = "async"
    with pytest.raises(ValidationError) as exc:
        TriageVerdict.model_validate(payload)
    message = str(exc.value)
    assert "class" in message
    for allowed in ("code", "flaky", "infra", "external", "unknown"):
        assert allowed in message


def test_ac2_risk_tier_rejects_non_spine_value() -> None:
    payload = representative_verdict_payload()
    payload["risk_tier"] = "hotfix"
    with pytest.raises(ValidationError) as exc:
        TriageVerdict.model_validate(payload)
    assert "risk_tier" in str(exc.value)
    assert "normal" in str(exc.value)


def test_ac2_terminal_state_rejects_non_spine_value() -> None:
    payload = representative_verdict_payload()
    payload["terminal_state"] = "done"
    with pytest.raises(ValidationError) as exc:
        TriageVerdict.model_validate(payload)
    message = str(exc.value)
    assert "terminal_state" in message
    assert "pr_opened" in message


def test_ac2_suspect_sha_requires_full_40_char_hex() -> None:
    payload = representative_verdict_payload()
    payload["suspects"] = [
        {
            "sha": "abc1234",
            "author_login": "someone",
            "rank": 1,
            "citations": [
                {"kind": "commit", "sha": "abc1234"},
                {"kind": "log_line", "log_line": 3},
            ],
        }
    ]
    with pytest.raises(ValidationError) as exc:
        TriageVerdict.model_validate(payload)
    assert "sha" in str(exc.value)


def test_ac2_proposed_diff_ops_are_exactly_add_modify_delete() -> None:
    payload = representative_verdict_payload()
    payload["proposed_diff"] = {
        "base_sha": FULL_SHA,
        "files": [{"path": "tests/test_x.py", "op": "rename", "new_content": ""}],
    }
    with pytest.raises(ValidationError) as exc:
        TriageVerdict.model_validate(payload)
    message = str(exc.value)
    assert "op" in message
    for allowed in ("add", "modify", "delete"):
        assert allowed in message


def test_ac2_cap_value_is_bounded_unit_interval() -> None:
    payload = representative_verdict_payload()
    payload["caps"] = [{"value": 1.5, "reason": "x", "citations": []}]
    with pytest.raises(ValidationError) as exc:
        TriageVerdict.model_validate(payload)
    assert "value" in str(exc.value)


def test_ac2_cap_reason_requires_one_cited_citation() -> None:
    make_cap = {"value": 0.5, "reason": "injection pre-screen"}
    with pytest.raises(ValidationError) as exc:
        TriageVerdict.model_validate(
            {**representative_verdict_payload(), "caps": [make_cap]}
        )
    assert "Field required" in str(exc.value)
    assert "citations" in str(exc.value)
    with pytest.raises(ValidationError) as exc:
        TriageVerdict.model_validate(
            {
                **representative_verdict_payload(),
                "caps": [{**make_cap, "citations": []}],
            }
        )
    assert "citations" in str(exc.value)


def test_ac2_suspect_requires_commit_and_log_line_kinds() -> None:
    suspect = {
        "sha": FULL_SHA,
        "author_login": "someone",
        "rank": 1,
        "citations": [
            {"kind": "commit", "sha": FULL_SHA},
            {"kind": "log_line", "log_line": 3},
        ],
    }
    assert Suspect.model_validate(suspect).citations[0].kind is not None

    for citations in (
        [],
        [{"kind": "commit", "sha": FULL_SHA}],
        [{"kind": "log_line", "log_line": 3}],
        [{"kind": "metric", "metric_key": "x"}],
    ):
        bad = {**suspect, "citations": citations}
        with pytest.raises(ValidationError) as exc:
            Suspect.model_validate(bad)
        assert "citations" in str(exc.value)


def test_ac2_quarantine_never_lives_inside_the_diff() -> None:
    quarantine = Quarantine.model_validate(
        {
            "test_id": "tests/test_flaky.py::test_retry",
            "reason": "failed 3 of 5 on green trees",
            "citations": [{"kind": "history_row", "row_id": "row-9"}],
        }
    )
    assert quarantine.test_id.endswith("test_retry")


def test_ac2_reviewer_objection_carries_severity_category_claim_citation() -> None:
    objection = Objection.model_validate(
        {
            "severity": "major",
            "category": "assertions",
            "claim": "the fix loosens the failing assertion",
            "citation": {"kind": "log_line", "log_line": 7},
        }
    )
    assert objection.severity is not None
    with pytest.raises(ValidationError) as exc:
        Objection.model_validate(
            {
                "severity": "critical",
                "category": "c",
                "claim": "x",
                "citation": {"kind": "log_line", "log_line": 1},
            }
        )
    assert "severity" in str(exc.value)


def test_ac2_unknown_extra_keys_are_rejected() -> None:
    payload = representative_verdict_payload()
    payload["blame"] = "someone"
    with pytest.raises(ValidationError) as exc:
        TriageVerdict.model_validate(payload)
    assert "blame" in str(exc.value)


def test_ac2_suspect_rank_must_be_positive() -> None:
    suspect_rank_zero = {
        "rank": 0,
        "sha": FULL_SHA,
        "author_login": "x",
        "citations": [
            {"kind": "commit", "sha": FULL_SHA},
            {"kind": "log_line", "log_line": 3},
        ],
    }
    with pytest.raises(ValidationError) as exc:
        Suspect.model_validate(suspect_rank_zero)
    assert "rank" in str(exc.value)
