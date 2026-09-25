"""AC: `contracts/jev.py` converts typesafe_sdk 0.7.1 answers cleanly
(AD-9, AD-11); `JevChoice.confidence` is frozen once built (AD-9)."""

import pytest
from pydantic import ValidationError
from typesafe_sdk import ChoiceAnswer, NoulAnswer

from contracts.enums import FailureClass
from contracts.jev import JevChoice, JevClassification, JevInjectionScreen

PROBABILITIES = {
    "code": 0.05,
    "flaky": 0.9,
    "infra": 0.02,
    "external": 0.02,
    "unknown": 0.01,
}


def sdk_choice_answer(choice: str = "flaky", confidence: float = 0.9) -> ChoiceAnswer:
    return ChoiceAnswer(
        choice=choice, confidence=confidence, probabilities=PROBABILITIES
    )


def test_ac1_choice_answer_converts_to_frozen_jev_choice() -> None:
    jev_choice = JevChoice.from_sdk(sdk_choice_answer())
    assert jev_choice.answer is FailureClass.FLAKY
    assert jev_choice.confidence == 0.9
    assert jev_choice.probabilities[FailureClass.FLAKY] == 0.9
    assert jev_choice.probabilities[FailureClass.CODE] == 0.05


def test_ac1_jev_choice_confidence_is_frozen_once_built() -> None:
    jev_choice = JevChoice.from_sdk(sdk_choice_answer())
    with pytest.raises(ValidationError):
        jev_choice.confidence = 0.1  # type: ignore[misc]


def test_ac1_noul_answer_converts_to_injection_screen() -> None:
    screen = JevInjectionScreen.from_sdk(NoulAnswer(noul=0.62))
    assert screen.noul == 0.62


def test_ac1_probabilities_are_bounded() -> None:
    with pytest.raises(ValidationError):
        JevChoice(
            answer=FailureClass.FLAKY,
            confidence=0.9,
            probabilities={FailureClass.FLAKY: 5.0},
        )


def test_ac1_jev_classification_forbids_extra_fields() -> None:
    classification = JevClassification(
        choice=JevChoice.from_sdk(sdk_choice_answer()),
        injection_screen=JevInjectionScreen.from_sdk(NoulAnswer(noul=0.1)),
    )
    with pytest.raises(ValidationError):
        JevClassification.model_validate(
            {**classification.model_dump(mode="json"), "extra": "nope"}
        )
