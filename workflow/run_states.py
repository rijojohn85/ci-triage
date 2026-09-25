"""Run-state enum: the 14 AD-1 orchestrator states, owned by `triage_run.state`.

Orchestrator-internal per the story: `contracts/` holds inter-agent payload
types (AD-6), and a state the agents never transmit does not belong there.
The enum values it shares with agents (`TerminalState`, `EscalationReason`,
`FailureClass`, `RiskTier`) come from `contracts.enums` — reused, never
redefined.
"""

from enum import Enum

__all__ = ["RUN_STATES", "TERMINAL_RUN_STATES", "RunState"]


class RunState(str, Enum):
    """`triage_run.state` values, the exact AD-1 set."""

    RECEIVED = "RECEIVED"
    DISTILLING = "DISTILLING"
    CLASSIFYING = "CLASSIFYING"
    ANALYZING = "ANALYZING"
    PROPOSING = "PROPOSING"
    REVIEWING = "REVIEWING"
    GATING = "GATING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    PR_OPENING = "PR_OPENING"
    REPORTING = "REPORTING"
    DONE_PR = "DONE_PR"
    DONE_REPORT = "DONE_REPORT"
    REJECTED_BY_HUMAN = "REJECTED_BY_HUMAN"
    FAILED = "FAILED"


RUN_STATES = tuple(RunState)  # 14 AD-1 states, in spine order

# Terminal set in AD-1 order: the three outcome states plus FAILED (AD-22).
TERMINAL_RUN_STATES = frozenset(
    (
        RunState.DONE_PR,
        RunState.DONE_REPORT,
        RunState.REJECTED_BY_HUMAN,
        RunState.FAILED,
    )
)
