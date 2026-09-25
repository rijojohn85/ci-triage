"""The explicit AD-1 transition table: one declarative row per legal move.

Design (SOLID-O): a new edge is a new row + guard — never an if/elif chain
over states. `FAILED` edges are *derived* from the terminal set, not
hand-listed (AD-22). Guards are pure predicates over one frozen
`GuardInput` model; they only consume values the caller computed (AD-9:
confidence is story 2.2's business — the guard sees only
`confidence_below_cutoff`). No SQL, no HTTP (SOLID-S).

Thresholds come from `guardrails/thresholds.yaml` (AD-19): a caller loads
them once and passes `max_revision_rounds` in the `GuardInput`; nothing in
this module carries a threshold literal.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from contracts.enums import EscalationReason, FailureClass, RiskTier
from workflow.run_states import TERMINAL_RUN_STATES, RunState
from workflow.thresholds import load_thresholds

__all__ = [
    "GUARDS",
    "TRANSITIONS",
    "GuardInput",
    "IllegalTransition",
    "guard_fields",
    "legal_transitions",
    "transition",
    "transitions_from",
]


class GuardInput(BaseModel):
    """Frozen guard data for one attempted move (SOLID-I: one model, ≤ intent).

    Every field defaults to "unsaid"; guards reject a move whose data is
    missing (AC3) instead of guessing.
    """

    model_config = ConfigDict(frozen=True)

    confidence_below_cutoff: bool = False
    failure_class: FailureClass | None = None
    risk_tier: RiskTier | None = None
    revision_round: int = 0
    max_revision_rounds: int = 0  # loaded from guardrails/thresholds.yaml (AD-19)
    escalation_reason: EscalationReason | None = None
    decision: Literal["approve", "reject"] | None = None
    class_override: FailureClass | None = None
    touches_workflow_files: bool = False
    has_proposal: bool = False
    rejected_before_report: bool = False


class IllegalTransition(  # noqa: N818 — spine AD-1/AD-22 name the domain error
    Exception
):
    """A move outside the table, or a declared row whose guard refused.

    Non-retryable by construction (AD-22): the lifecycle, not a transient
    fault, is wrong. Names `from_state`, `to_state` and the refused guard(s).
    """

    retryable: bool = False

    def __init__(
        self,
        from_state: RunState,
        to_state: RunState,
        guard_name: str | None,
        refused_guards: tuple[str, ...] = (),
    ) -> None:
        self.from_state = from_state
        self.to_state = to_state
        self.guard_name = guard_name
        self.refused_guards = refused_guards or ((guard_name,) if guard_name else ())
        if guard_name:
            if len(self.refused_guards) == 1:
                detail = f"declared but guard {guard_name!r} refused"
            else:
                detail = (
                    "declared but guards "
                    f"{', '.join(repr(name) for name in self.refused_guards)}"
                    " refused"
                )
        else:
            detail = "not declared in the transition table"
        super().__init__(
            f"illegal transition {from_state.name} -> {to_state.name}: {detail}"
        )


Guard = Callable[[GuardInput], bool]


def _always(_: GuardInput) -> bool:
    return True


def _escalation_allowed(reasons: tuple[EscalationReason, ...]) -> Guard:
    """A pause guard: the reason must be one of the row's, and a
    `low_confidence` claim may only stand when the confidence really is
    below the cutoff (AD-9: guards only *consume* the boolean)."""

    def check(guard: GuardInput) -> bool:
        if guard.escalation_reason not in reasons:
            return False
        return (
            guard.confidence_below_cutoff
            if guard.escalation_reason is EscalationReason.LOW_CONFIDENCE
            else True
        )

    return check


def _class_is_infra(guard: GuardInput) -> bool:
    return guard.failure_class is FailureClass.INFRA


def _class_is_proposable(guard: GuardInput) -> bool:
    return guard.failure_class in (
        FailureClass.CODE,
        FailureClass.FLAKY,
        FailureClass.EXTERNAL,
    )


def _revision_round_below_max(guard: GuardInput) -> bool:
    return guard.revision_round < guard.max_revision_rounds


def _gate_allows_pr(guard: GuardInput) -> bool:
    return guard.risk_tier is RiskTier.NORMAL


def _gate_blocks(guard: GuardInput) -> bool:
    # AD-1: beat a blocked change into `AWAITING_APPROVAL(gate_blocked)`
    # — a blocked tier alone does not carry the AD-1 reason.
    return (
        guard.risk_tier is RiskTier.BLOCKED
        and guard.escalation_reason is EscalationReason.GATE_BLOCKED
    )


def _approve_of_workflow_diff(guard: GuardInput) -> bool:
    return guard.decision == "approve" and guard.touches_workflow_files


def _reject_by_human(guard: GuardInput) -> bool:
    return guard.decision == "reject"


def _approve_non_workflow_with_proposal(guard: GuardInput) -> bool:
    return (
        guard.decision == "approve"
        and guard.has_proposal
        and not guard.touches_workflow_files
    )


def _approve_override_no_proposal(guard: GuardInput) -> bool:
    return (
        guard.decision == "approve"
        and guard.class_override is not None
        and not guard.has_proposal
    )


def _report_records_rejection(guard: GuardInput) -> bool:
    return guard.rejected_before_report


GUARDS: dict[str, Guard] = {
    "always": _always,
    "classification_escalation": _escalation_allowed(
        (
            EscalationReason.LOW_CONFIDENCE,
            EscalationReason.UNKNOWN_CLASS,
            EscalationReason.NO_ROUTE,
            EscalationReason.VALIDATION_FAILED,
        )
    ),
    "analysis_escalation": _escalation_allowed(
        (EscalationReason.LOW_CONFIDENCE, EscalationReason.VALIDATION_FAILED)
    ),
    "validation_escalation": _escalation_allowed((EscalationReason.VALIDATION_FAILED,)),
    "review_escalation": _escalation_allowed(
        (EscalationReason.REVIEW_REJECTED, EscalationReason.VALIDATION_FAILED)
    ),
    "class_is_infra": _class_is_infra,
    "class_is_proposable": _class_is_proposable,
    "revision_round_below_max": _revision_round_below_max,
    "gate_allows_pr": _gate_allows_pr,
    "gate_blocks": _gate_blocks,
    "approve_of_workflow_diff": _approve_of_workflow_diff,
    "reject_by_human": _reject_by_human,
    "approve_non_workflow_with_proposal": _approve_non_workflow_with_proposal,
    "approve_override_no_proposal": _approve_override_no_proposal,
    "report_records_rejection": _report_records_rejection,
}


# Sample field values that satisfy each guard — the table's own documentation
# of its branch data, and the fixture source for AC1/AC3 tests. Threshold
# numbers come from guardrails/thresholds.yaml (AD-19), never a literal here.
_MAX_ROUNDS = load_thresholds().review_max_rounds

GUARD_FIELDS: dict[str, dict[str, object]] = {
    "always": {},
    "classification_escalation": {
        "escalation_reason": EscalationReason.LOW_CONFIDENCE.value,
        "confidence_below_cutoff": True,
    },
    "analysis_escalation": {
        "escalation_reason": EscalationReason.LOW_CONFIDENCE.value,
        "confidence_below_cutoff": True,
    },
    "validation_escalation": {
        "escalation_reason": EscalationReason.VALIDATION_FAILED.value
    },
    "review_escalation": {"escalation_reason": EscalationReason.REVIEW_REJECTED.value},
    "class_is_infra": {"failure_class": FailureClass.INFRA.value},
    "class_is_proposable": {"failure_class": FailureClass.CODE.value},
    "revision_round_below_max": {
        "revision_round": 0,
        "max_revision_rounds": _MAX_ROUNDS,
    },
    "gate_allows_pr": {"risk_tier": RiskTier.NORMAL.value},
    "gate_blocks": {
        "risk_tier": RiskTier.BLOCKED.value,
        "escalation_reason": EscalationReason.GATE_BLOCKED.value,
    },
    "approve_of_workflow_diff": {"decision": "approve", "touches_workflow_files": True},
    "reject_by_human": {"decision": "reject"},
    "approve_non_workflow_with_proposal": {"decision": "approve", "has_proposal": True},
    "approve_override_no_proposal": {
        "decision": "approve",
        "class_override": FailureClass.CODE.value,
    },
    "report_records_rejection": {"rejected_before_report": True},
}


@dataclass(frozen=True)
class Transition:
    from_state: RunState
    to_state: RunState
    guard_name: str
    label: str = ""

    @property
    def guard(self) -> Guard:
        return GUARDS[self.guard_name]


# The AD-1 edge set: state-to-state rows in spine order, labels verbatim.
_DECLARED: tuple[Transition, ...] = (
    Transition(RunState.RECEIVED, RunState.DISTILLING, "always"),
    Transition(RunState.DISTILLING, RunState.CLASSIFYING, "always"),
    Transition(RunState.CLASSIFYING, RunState.ANALYZING, "always"),
    Transition(
        RunState.CLASSIFYING,
        RunState.AWAITING_APPROVAL,
        "classification_escalation",
        "low confidence / unknown / no-route / validation failed",
    ),
    Transition(
        RunState.ANALYZING, RunState.REPORTING, "class_is_infra", "class = infra"
    ),
    Transition(
        RunState.ANALYZING,
        RunState.PROPOSING,
        "class_is_proposable",
        "code / flaky / external",
    ),
    Transition(
        RunState.ANALYZING,
        RunState.AWAITING_APPROVAL,
        "analysis_escalation",
        "low confidence / validation failed",
    ),
    Transition(RunState.PROPOSING, RunState.REVIEWING, "always"),
    Transition(
        RunState.PROPOSING,
        RunState.AWAITING_APPROVAL,
        "validation_escalation",
        "validation failed",
    ),
    Transition(
        RunState.REVIEWING,
        RunState.PROPOSING,
        "revision_round_below_max",
        "major objections, round < 2",
    ),
    Transition(
        RunState.REVIEWING,
        RunState.GATING,
        "always",
        "accepted or dangerous (early escalation)",
    ),
    Transition(
        RunState.REVIEWING,
        RunState.AWAITING_APPROVAL,
        "review_escalation",
        "rejected after 2 rounds / validation failed",
    ),
    Transition(
        RunState.GATING, RunState.PR_OPENING, "gate_allows_pr", "risk_tier = normal"
    ),
    Transition(
        RunState.GATING,
        RunState.AWAITING_APPROVAL,
        "gate_blocks",
        "risk_tier = blocked",
    ),
    Transition(
        RunState.AWAITING_APPROVAL,
        RunState.PR_OPENING,
        "approve_non_workflow_with_proposal",
        "approve, proposal exists, no workflow file",
    ),
    Transition(
        RunState.AWAITING_APPROVAL,
        RunState.REPORTING,
        "approve_of_workflow_diff",
        "approve, diff touches .github/workflows/**",
    ),
    Transition(
        RunState.AWAITING_APPROVAL,
        RunState.ANALYZING,
        "approve_override_no_proposal",
        "approve with class override, no proposal",
    ),
    Transition(
        RunState.AWAITING_APPROVAL, RunState.REPORTING, "reject_by_human", "reject"
    ),
    Transition(RunState.PR_OPENING, RunState.DONE_PR, "always"),
    Transition(RunState.REPORTING, RunState.DONE_REPORT, "always"),
    Transition(
        RunState.REPORTING,
        RunState.REJECTED_BY_HUMAN,
        "report_records_rejection",
        "after reject",
    ),
)


def _failed_edges() -> tuple[Transition, ...]:
    # Derived from the terminal set, not hand-listed 11 times (AD-22).
    return tuple(
        Transition(state, RunState.FAILED, "always")
        for state in _table_order()
        if state not in TERMINAL_RUN_STATES
    )


def _table_order() -> tuple[RunState, ...]:
    """Source states in declaration order: diagram rows read in spine order."""
    order: list[RunState] = []
    for row in _DECLARED:
        if row.from_state not in order:
            order.append(row.from_state)
    return tuple(order)


def _build_table() -> None:
    grouped: dict[RunState, list[Transition]] = {}
    for row in (*_DECLARED, *_failed_edges()):
        grouped.setdefault(row.from_state, []).append(row)
    for from_state, rows in grouped.items():
        _BY_FROM[from_state] = tuple(rows)


_BY_FROM: dict[RunState, tuple[Transition, ...]] = {}
_build_table()


TRANSITIONS: tuple[Transition, ...] = tuple(
    row for rows in _BY_FROM.values() for row in rows
)


def transitions_from(from_state: RunState) -> tuple[Transition, ...]:
    """Rows declared from one state (table order + derived FAILED last)."""
    return _BY_FROM.get(from_state, ())


def declared_edges() -> set[tuple[RunState, RunState]]:
    """The spine's declared state-to-state edge set (derived FAILED excluded)."""
    return {(row.from_state, row.to_state) for row in _DECLARED}


def legal_transitions(from_state: RunState) -> tuple[RunState, ...]:
    return tuple(dict.fromkeys(row.to_state for row in transitions_from(from_state)))


def transition(
    from_state: RunState, to_state: RunState, guards: GuardInput
) -> Transition:
    """Move `from_state -> to_state` iff a declared row's guard accepts.

    Returns the winning row; raises `IllegalTransition` (non-retryable,
    AD-22) naming both states and — for a declared-but-refused move — every
    candidate guard that refused.
    """
    candidates = [
        row for row in transitions_from(from_state) if row.to_state == to_state
    ]
    if not candidates:
        raise IllegalTransition(from_state, to_state, None)
    for row in candidates:
        if row.guard(guards):
            return row
    refusals = tuple(dict.fromkeys(row.guard_name for row in candidates))
    raise IllegalTransition(from_state, to_state, refusals[0], refusals)


def guard_fields(guard_name: str) -> dict[str, object]:
    """One source of sample data per guard (tests + introspection; AC1/AC3)."""
    return GUARD_FIELDS[guard_name]
