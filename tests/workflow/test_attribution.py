"""Story 2.2 AC3 tests for `workflow/attribution.py`: the AD-27 blame-free rule.

A human class override (AD-14) changes neither `confidence_jev` nor
`confidence` (AD-9), so `attribution_allowed` takes no override at all: a
below-cutoff run stays blame-free whether or not a human overrode the class.
"""

import pytest

from contracts.citations import JevSignalCitation
from contracts.enums import FailureClass
from contracts.jev import JevChoice
from contracts.verdict import Cap
from guardrails.confidence import ClassConfidence, class_escalation
from tests.fixtures.thresholds import FIXTURE_CUTOFFS
from workflow.attribution import attribution_allowed
from workflow.run_states import RunState

CUTOFFS = FIXTURE_CUTOFFS


def confidence(value: float) -> ClassConfidence:
    return ClassConfidence.from_jev(
        JevChoice(
            answer=FailureClass.CODE,
            confidence=value,
            probabilities={FailureClass.CODE: value},
        )
    )


def capped_confidence(jev: float, cap_value: float) -> ClassConfidence:
    return confidence(jev).with_cap(
        Cap(
            value=cap_value,
            reason="test cap",
            citations=[JevSignalCitation(answer="noul")],
        )
    )


@pytest.mark.parametrize("state", [RunState.AWAITING_APPROVAL, RunState.REPORTING])
def test_ac3_no_attribution_in_awaiting_approval_or_reporting(state: RunState) -> None:
    assert attribution_allowed(state, confidence(0.9), CUTOFFS) is False


def test_ac3_no_attribution_below_class_cutoff() -> None:
    assert attribution_allowed(RunState.ANALYZING, confidence(0.5), CUTOFFS) is False


def test_ac3_override_skips_escalation_but_attribution_stays_false() -> None:
    low = confidence(0.5)
    assert class_escalation(low, CUTOFFS, class_override=FailureClass.FLAKY) is None
    assert attribution_allowed(RunState.ANALYZING, low, CUTOFFS) is False


def test_ac3_attribution_allowed_at_or_above_class_cutoff() -> None:
    assert (
        attribution_allowed(
            RunState.ANALYZING, confidence(CUTOFFS.class_cutoff), CUTOFFS
        )
        is True
    )
    assert attribution_allowed(RunState.ANALYZING, confidence(0.9), CUTOFFS) is True


def test_ac3_capped_confidence_below_cutoff_blocks_attribution() -> None:
    capped = capped_confidence(0.9, CUTOFFS.class_cutoff - 0.1)
    assert attribution_allowed(RunState.ANALYZING, capped, CUTOFFS) is False
