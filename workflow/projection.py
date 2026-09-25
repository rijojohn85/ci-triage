"""The pure AD-4 projection: `triage_run.state` onto A2A `TaskState`.

Pure mapping-table function — no SDK import beyond checking that the member
names we emit really exist in a2a-sdk 1.1.5 (the tests do that). a2a-sdk's
`TaskState` is a protobuf `EnumTypeWrapper`, not a Python Enum, so we hand
back the member *name* as a plain str; the A2A server story (2.4) converts
to the integer value at the transport edge.
"""

from typing import Final

from contracts.enums import TerminalState
from workflow.run_states import RunState

__all__ = ["project", "projection_table"]

TASK_STATE_SUBMITTED: Final[str] = "TASK_STATE_SUBMITTED"
TASK_STATE_WORKING: Final[str] = "TASK_STATE_WORKING"
TASK_STATE_INPUT_REQUIRED: Final[str] = "TASK_STATE_INPUT_REQUIRED"
TASK_STATE_COMPLETED: Final[str] = "TASK_STATE_COMPLETED"
TASK_STATE_FAILED: Final[str] = "TASK_STATE_FAILED"

Projection = tuple[str, TerminalState | None]

projection_table: Final[dict[RunState, Projection]] = {
    RunState.RECEIVED: (TASK_STATE_SUBMITTED, None),
    RunState.DISTILLING: (TASK_STATE_WORKING, None),
    RunState.CLASSIFYING: (TASK_STATE_WORKING, None),
    RunState.ANALYZING: (TASK_STATE_WORKING, None),
    RunState.PROPOSING: (TASK_STATE_WORKING, None),
    RunState.REVIEWING: (TASK_STATE_WORKING, None),
    RunState.GATING: (TASK_STATE_WORKING, None),
    RunState.AWAITING_APPROVAL: (
        TASK_STATE_INPUT_REQUIRED,
        TerminalState.INPUT_REQUIRED,
    ),
    RunState.PR_OPENING: (TASK_STATE_WORKING, None),
    RunState.REPORTING: (TASK_STATE_WORKING, None),
    RunState.DONE_PR: (TASK_STATE_COMPLETED, TerminalState.PR_OPENED),
    RunState.DONE_REPORT: (TASK_STATE_COMPLETED, TerminalState.REPORT_SENT),
    RunState.REJECTED_BY_HUMAN: (TASK_STATE_COMPLETED, TerminalState.REJECTED_BY_HUMAN),
    RunState.FAILED: (TASK_STATE_FAILED, TerminalState.FAILED),
}


def project(run_state: RunState) -> Projection:
    """One-way AD-4 projection of a run state onto its A2A task state."""
    return projection_table[run_state]
