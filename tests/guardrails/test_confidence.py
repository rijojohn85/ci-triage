"""Story 2.2 tests for `guardrails/confidence.py` (AD-9, AD-11, AD-14): the one
min rule (AC1), the injection screen and the separate routing type (AC2),
and the classification-branch cut-off table (AC3).

Cut-offs come from `tests/fixtures/thresholds.test.yaml`, never the real file.
"""

import pytest
from pydantic import ValidationError

from contracts.citations import JevSignalCitation
from contracts.enums import CitationKind, EscalationReason, FailureClass
from contracts.jev import JevChoice, JevInjectionScreen
from contracts.verdict import Cap
from guardrails.confidence import (
    ClassConfidence,
    RouteConfidence,
    apply_injection_screen,
    below_class_cutoff,
    class_escalation,
)
from tests.fixtures.thresholds import FIXTURE_CUTOFFS

CUTOFFS = FIXTURE_CUTOFFS


def jev_choice(answer: FailureClass, confidence: float) -> JevChoice:
    return JevChoice(
        answer=answer, confidence=confidence, probabilities={answer: confidence}
    )


def class_confidence(
    confidence: float, answer: FailureClass = FailureClass.CODE
) -> ClassConfidence:
    return ClassConfidence.from_jev(jev_choice(answer, confidence))


def make_cap(value: float) -> Cap:
    return Cap(
        value=value, reason="test cap", citations=[JevSignalCitation(answer="noul")]
    )


# --- AC1: one min rule, frozen Jev number, cited caps, audit-only probabilities


def test_ac1_no_caps_confidence_is_jev() -> None:
    assert class_confidence(0.9).confidence == 0.9


def test_ac1_cap_above_jev_does_not_raise_confidence() -> None:
    assert class_confidence(0.6).with_cap(make_cap(0.8)).confidence == 0.6


def test_ac1_several_caps_take_the_lowest() -> None:
    capped = class_confidence(0.9).with_cap(make_cap(0.7)).with_cap(make_cap(0.5))
    assert capped.confidence == 0.5


def test_ac1_adding_a_cap_never_raises_confidence() -> None:
    before = class_confidence(0.4).with_cap(make_cap(0.3))
    for value in (0.0, 0.2, 0.3, 0.5, 1.0):
        assert before.with_cap(make_cap(value)).confidence <= before.confidence


def test_ac1_uncited_cap_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Cap(value=0.5, reason="x", citations=[])


def test_ac1_confidence_cannot_be_set() -> None:
    confidence = class_confidence(0.9)
    with pytest.raises(ValidationError):
        confidence.confidence = 0.1  # type: ignore[misc]
    with pytest.raises(ValidationError):
        ClassConfidence(  # type: ignore[call-arg]
            failure_class=FailureClass.CODE, confidence_jev=0.9, confidence=1.0
        )


def test_ac1_confidence_jev_is_frozen() -> None:
    confidence = class_confidence(0.9)
    with pytest.raises(ValidationError):
        confidence.confidence_jev = 0.1  # type: ignore[misc]


def test_ac1_varied_probabilities_give_an_identical_class_confidence() -> None:
    varied = JevChoice(
        answer=FailureClass.CODE,
        confidence=0.9,
        probabilities={
            FailureClass.CODE: 0.4,
            FailureClass.FLAKY: 0.3,
            FailureClass.INFRA: 0.3,
        },
    )
    assert ClassConfidence.from_jev(varied) == class_confidence(0.9)


# --- AC2: injection screen adds one cited cap, never escalates by itself


def test_ac2_noul_positive_adds_exactly_one_jev_signal_cap() -> None:
    before = class_confidence(0.9)
    screened = apply_injection_screen(
        before, JevInjectionScreen(noul=CUTOFFS.injection_screen_cutoff), CUTOFFS
    )
    assert len(screened.caps) == 1
    assert screened.caps[0].value == CUTOFFS.injection_screen_cap
    assert [c.kind for c in screened.caps[0].citations] == [CitationKind.JEV_SIGNAL]
    assert screened.confidence <= before.confidence
    assert screened.confidence_jev == before.confidence_jev


def test_ac2_noul_negative_adds_no_cap() -> None:
    before = class_confidence(0.9)
    below_screen_cutoff = CUTOFFS.injection_screen_cutoff - 0.01
    screened = apply_injection_screen(
        before, JevInjectionScreen(noul=below_screen_cutoff), CUTOFFS
    )
    assert screened == before


def test_ac2_positive_screen_alone_does_not_escalate() -> None:
    # The screen only lowers the number. With a cap that stays at or above
    # the class cut-off, nothing escalates: the screen has no reason of its own.
    mild_cap = CUTOFFS.model_copy(update={"injection_screen_cap": 0.8})
    screened = apply_injection_screen(
        class_confidence(0.9), JevInjectionScreen(noul=1.0), mild_cap
    )
    assert isinstance(screened, ClassConfidence)
    assert class_escalation(screened, mild_cap) is None


def test_ac2_routing_confidence_is_refused_by_the_class_check() -> None:
    with pytest.raises(TypeError):
        below_class_cutoff(RouteConfidence(confidence=0.9), CUTOFFS)  # type: ignore[arg-type]


def test_ac2_routing_confidence_is_refused_by_class_escalation() -> None:
    route_confidence = RouteConfidence(confidence=0.9)
    with pytest.raises(TypeError):
        class_escalation(route_confidence, CUTOFFS)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        class_escalation(  # type: ignore[arg-type]
            route_confidence, CUTOFFS, class_override=FailureClass.CODE
        )


def test_ac2_positive_screen_with_fixture_values_escalates_only_via_low_confidence() -> (
    None
):
    # With the real fixture cutoffs, a positive screen's cap (0.5) sits below
    # the class cut-off (0.75): the branch escalates through the ordinary
    # low-confidence check, never through a screen-specific reason (there is
    # no such reason — the screen only ever adds a cap).
    screened = apply_injection_screen(
        class_confidence(0.9),
        JevInjectionScreen(noul=CUTOFFS.injection_screen_cutoff),
        CUTOFFS,
    )
    assert class_escalation(screened, CUTOFFS) is EscalationReason.LOW_CONFIDENCE


# --- AC3: classification-branch table over fixture thresholds

BRANCH_TABLE = [
    # (id, class, jev, override, expected escalation, expected below cut-off)
    ("above", FailureClass.CODE, 0.9, None, None, False),
    ("at", FailureClass.CODE, CUTOFFS.class_cutoff, None, None, False),
    ("below", FailureClass.CODE, 0.5, None, EscalationReason.LOW_CONFIDENCE, True),
    ("unknown", FailureClass.UNKNOWN, 0.9, None, EscalationReason.UNKNOWN_CLASS, False),
    (
        "unknown+below",
        FailureClass.UNKNOWN,
        0.5,
        None,
        EscalationReason.UNKNOWN_CLASS,
        True,
    ),
    ("below+override", FailureClass.CODE, 0.5, FailureClass.FLAKY, None, True),
    ("unknown+override", FailureClass.UNKNOWN, 0.9, FailureClass.CODE, None, False),
]


@pytest.mark.parametrize(
    ("answer", "jev", "override", "reason", "below"),
    [row[1:] for row in BRANCH_TABLE],
    ids=[row[0] for row in BRANCH_TABLE],
)
def test_ac3_classification_branch_table(
    answer: FailureClass,
    jev: float,
    override: FailureClass | None,
    reason: EscalationReason | None,
    below: bool,
) -> None:
    confidence = class_confidence(jev, answer)
    assert class_escalation(confidence, CUTOFFS, class_override=override) is reason
    assert below_class_cutoff(confidence, CUTOFFS) is below


def test_ac3_capped_confidence_below_class_cutoff_escalates_low_confidence() -> None:
    # jev alone is at/above the cut-off; a cap pulls the effective number
    # under it, and the escalation follows the effective number, not jev.
    capped = class_confidence(CUTOFFS.class_cutoff).with_cap(
        make_cap(CUTOFFS.class_cutoff - 0.05)
    )
    assert below_class_cutoff(capped, CUTOFFS) is True
    assert class_escalation(capped, CUTOFFS) is EscalationReason.LOW_CONFIDENCE


def test_ac3_override_changes_neither_confidence_value() -> None:
    confidence = class_confidence(0.5).with_cap(make_cap(0.4))
    before = (confidence.confidence_jev, confidence.confidence)
    class_escalation(confidence, CUTOFFS, class_override=FailureClass.FLAKY)
    assert (confidence.confidence_jev, confidence.confidence) == before
