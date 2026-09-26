"""AC: `contracts/jev.py` converts typesafe_sdk 0.7.1 answers cleanly
(AD-9, AD-11); `JevChoice.confidence` is frozen once built (AD-9)."""

import pytest
from pydantic import ValidationError
from typesafe_sdk import ChoiceAnswer, NoulAnswer

from contracts.a2a import DataPart
from contracts.enums import FailureClass
from contracts.jev import JevChoice, JevClassification, JevInjectionScreen, JevResult
from contracts.usage import ModelUsage
from tests.contracts.samples import RUN_ID

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


# --- Story 3.1 AC2/AC3: the served result carries the classification plus the
# provider-reported usage, and joins the A2A DataPart payload union (AD-6,
# AD-18). `Choice.confidence` and `probabilities` stay separate values (AD-9).


def classification() -> JevClassification:
    return JevClassification(
        choice=JevChoice.from_sdk(sdk_choice_answer()),
        injection_screen=JevInjectionScreen.from_sdk(NoulAnswer(noul=0.1)),
    )


def test_ac2_jev_result_carries_classification_and_usage() -> None:
    usage = ModelUsage(model="typesafe/jev-1.13", input_tokens=120, output_tokens=8)
    result = JevResult(classification=classification(), usage=usage)

    dumped = result.model_dump(mode="json")
    assert dumped["classification"]["choice"]["answer"] == "flaky"
    assert dumped["classification"]["choice"]["confidence"] == 0.9
    assert dumped["classification"]["injection_screen"]["noul"] == 0.1
    assert dumped["usage"] == {
        "model": "typesafe/jev-1.13",
        "input_tokens": 120,
        "output_tokens": 8,
        "cache_read_input_tokens": None,
        "cache_creation_input_tokens_5m": None,
        "cache_creation_input_tokens_1h": None,
    }
    assert JevResult.model_validate(dumped) == result


def test_ac2_unreported_usage_counters_stay_null_never_zero() -> None:
    usage = ModelUsage(model="typesafe/jev-1.13")
    result = JevResult(classification=classification(), usage=usage)

    assert result.usage.input_tokens is None
    assert result.usage.output_tokens is None
    assert result.usage.model_dump(mode="json")["input_tokens"] is None, (
        "an unreported counter is NULL, never 0 (AD-18)"
    )


def test_ac2_confidence_and_probabilities_stay_distinct_values() -> None:
    choice = JevChoice.from_sdk(sdk_choice_answer())

    assert choice.confidence == 0.9
    assert choice.probabilities[FailureClass.FLAKY] == 0.9
    assert choice.probabilities[FailureClass.CODE] == 0.05, (
        "probabilities are the per-class audit view, not the confidence (AD-9)"
    )


def test_ac2_jev_result_joins_the_datapart_payload_union() -> None:
    part = DataPart(
        task_id=RUN_ID,
        context_id=RUN_ID,
        payload=JevResult(
            classification=classification(),
            usage=ModelUsage(model="typesafe/jev-1.13"),
        ),
    )

    assert isinstance(part.payload, JevResult)


def test_ac2_jev_result_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        JevResult.model_validate(
            {
                "classification": classification().model_dump(mode="json"),
                "usage": ModelUsage(model="typesafe/jev-1.13").model_dump(mode="json"),
                "extra": "nope",
            }
        )
