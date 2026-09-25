"""Reviewer-objection payload (AD-12, AD-6): severity is closed, claim is cited."""

import pytest
from pydantic import ValidationError

from contracts.objections import Objection


def test_ac2_objection_carries_severity_category_claim_and_citation() -> None:
    obj = Objection.model_validate(
        {
            "severity": "major",
            "category": "blame",
            "claim": "rank-1 suspect does not touch the failing test",
            "citation": {"kind": "commit", "sha": "a" * 40},
        }
    )
    assert obj.severity == "major"
    assert obj.claim == "rank-1 suspect does not touch the failing test"


def test_ac2_objection_rejects_severity_outside_spine_set() -> None:
    with pytest.raises(ValidationError, match="major"):
        Objection.model_validate(
            {
                "severity": "critical",
                "category": "blame",
                "claim": "x",
                "citation": {"kind": "commit", "sha": "a" * 40},
            }
        )
