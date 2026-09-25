"""Attribution predicate (AD-27 blame-free rule): whether the rank-1
suspect's author may be notified for this run.

Lives in `workflow/`, not `contracts/` or `guardrails/`, because it needs
`RunState`, which agents never see (AD-1 states are orchestrator-internal).
"""

from guardrails.confidence import ClassConfidence, ConfidenceCutoffs, below_class_cutoff
from workflow.run_states import RunState

__all__ = ["attribution_allowed"]

_NO_ATTRIBUTION_STATES = frozenset((RunState.AWAITING_APPROVAL, RunState.REPORTING))


def attribution_allowed(
    state: RunState,
    confidence: ClassConfidence,
    cutoffs: ConfidenceCutoffs,
) -> bool:
    """False in `AWAITING_APPROVAL`/`REPORTING`, or below the class cutoff.

    A human class override (AD-14) changes neither `confidence_jev` nor
    `confidence` (AD-9), so a below-cutoff run stays blame-free whether or
    not it was overridden (AD-27).
    """
    if state in _NO_ATTRIBUTION_STATES:
        return False
    return not below_class_cutoff(confidence, cutoffs)
