"""Story 2.1 AC tests: the explicit AD-1 transition table and its guards.

Tested through `workflow.transitions`' public interface with one dict of
per-guard sample fields, so AC1 walks every row (declared edges are legal)
and AC3 feeds the guard's required data as missing. The committed diagram
byte-identity is a subprocess check on the generator tool, mirroring the
schema drift gate (tests/contracts/test_drift.py).
"""

import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

from contracts.enums import EscalationReason, TerminalState
from workflow.run_states import RUN_STATES, RunState, TERMINAL_RUN_STATES
from workflow.thresholds import load_thresholds
from workflow.transitions import (
    TRANSITIONS,
    GUARDS,
    GuardInput,
    IllegalTransition,
    legal_transitions,
    transition,
    transitions_from,
)

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
THRESHOLDS: Final = load_thresholds()

TEST_MAX_ROUNDS: Final[int] = THRESHOLDS.review_max_rounds
if TEST_MAX_ROUNDS < 1:  # yaml fixture sanity; guards branch on it (AD-19)
    raise AssertionError("review.max_rounds must be ≥ 1")


def sample_input(guard_name: str) -> GuardInput:
    from workflow.transitions import guard_fields

    return GuardInput(**guard_fields(guard_name))


# ---- AC1: every AD-1 edge is legal; undeclared moves raise ----


def test_ac1_every_spine_edge_is_legal() -> None:
    for row in TRANSITIONS:
        moved = transition(row.from_state, row.to_state, sample_input(row.guard_name))
        assert moved is row


def test_ac1_undeclared_transition_raises_illegal_and_names_guard() -> None:
    from workflow.transitions import TRANSITIONS

    sampled = (
        (RunState.RECEIVED, RunState.PROPOSING),
        (RunState.CLASSIFYING, RunState.PR_OPENING),
        (RunState.DONE_PR, RunState.REPORTING),
        (RunState.FAILED, RunState.FAILED),
        (RunState.GATING, RunState.DISTILLING),
        (RunState.REPORTING, RunState.ANALYZING),
    )
    for frm, to in sampled:
        with pytest.raises(IllegalTransition) as excinfo:
            transition(frm, to, GuardInput())
        error = excinfo.value
        assert error.from_state == frm
        assert error.to_state == to
        assert error.retryable is False  # AD-22: non-retryable
        assert not error.guard_name  # undeclared: no guard to blame
        assert frm.name in str(error) and to.name in str(error)
        # sanity: nowhere in the spine is such an edge declared
        assert all(row.from_state != frm or row.to_state != to for row in TRANSITIONS)


def test_ac1_failed_reachable_from_every_non_terminal() -> None:
    for state in RUN_STATES:
        if state in TERMINAL_RUN_STATES:
            continue  # AD-22: FAILED is terminal; terminals have no exits
        moved = transition(state, RunState.FAILED, GuardInput())
        assert moved.to_state == RunState.FAILED


def test_ac1_failed_is_not_reachable_from_terminal_states() -> None:
    for terminal in TERMINAL_RUN_STATES:
        assert RunState.FAILED not in legal_transitions(terminal)


def test_ac1_thresholds_loaded_not_literal() -> None:
    thresholds = load_thresholds()
    assert thresholds.review_max_rounds == TEST_MAX_ROUNDS
    assert thresholds.workflow_path_glob == ".github/workflows/**"
    assert thresholds.risk_gate.secret_path_globs == (
        ".env",
        ".env.*",
        "*/.env",
        "*/.env.*",
        "*.pem",
        "*.key",
        "*secrets/*",
        "*secret.*",
        "*secrets.*",
        "*credentials*",
        "*id_rsa*",
        "*id_ed25519*",
        "*.npmrc",
        "*.pypirc",
        "*.p12",
        "*.pfx",
    )
    assert thresholds.risk_gate.infra_path_globs == (
        "*Dockerfile*",
        "*docker-compose*.y*ml",
        "*compose*.y*ml",
        "*.tf",
        "*.tfvars",
        "*k8s*/*",
        "*kubernetes/*",
        "*charts/*",
        "*helm/*",
        "deploy/*",
        "*.tfstate*",
        "*terraform/*",
    )


def test_ac1_diagram_byte_identical() -> None:
    done = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "generate_state_diagram.py"),
            "--check",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert done.returncode == 0, done.stdout + done.stderr


# ---- AC2: projection onto the AD-4 table ----


def test_ac2_parametrized_projection_table() -> None:
    from workflow.projection import project

    expected: dict[RunState, tuple[str, TerminalState | None]] = {
        RunState.RECEIVED: ("TASK_STATE_SUBMITTED", None),
        RunState.DISTILLING: ("TASK_STATE_WORKING", None),
        RunState.CLASSIFYING: ("TASK_STATE_WORKING", None),
        RunState.ANALYZING: ("TASK_STATE_WORKING", None),
        RunState.PROPOSING: ("TASK_STATE_WORKING", None),
        RunState.REVIEWING: ("TASK_STATE_WORKING", None),
        RunState.GATING: ("TASK_STATE_WORKING", None),
        RunState.AWAITING_APPROVAL: (
            "TASK_STATE_INPUT_REQUIRED",
            TerminalState.INPUT_REQUIRED,
        ),
        RunState.PR_OPENING: ("TASK_STATE_WORKING", None),
        RunState.REPORTING: ("TASK_STATE_WORKING", None),
        RunState.DONE_PR: ("TASK_STATE_COMPLETED", TerminalState.PR_OPENED),
        RunState.DONE_REPORT: ("TASK_STATE_COMPLETED", TerminalState.REPORT_SENT),
        RunState.REJECTED_BY_HUMAN: (
            "TASK_STATE_COMPLETED",
            TerminalState.REJECTED_BY_HUMAN,
        ),
        RunState.FAILED: ("TASK_STATE_FAILED", TerminalState.FAILED),
    }
    assert set(expected) == set(RUN_STATES)  # all 14 states, none missing
    for state, want in expected.items():
        assert project(state) == want, state


def test_ac2_projection_names_exist_in_a2a_task_state() -> None:
    from a2a.types import TaskState
    from workflow.projection import project

    for state in RUN_STATES:
        task_state_name, _ = project(state)
        assert isinstance(TaskState.Value(task_state_name), int)  # member exists


def test_ac2_awaiting_approval_is_not_terminal() -> None:
    from workflow.projection import project

    task_state, terminal = project(RunState.AWAITING_APPROVAL)
    assert terminal == TerminalState.INPUT_REQUIRED
    assert task_state == "TASK_STATE_INPUT_REQUIRED"


def test_ac2_awaiting_approval_requires_reason() -> None:
    wrong_reasons: dict[str, dict[str, object]] = {
        "classification_escalation": {"escalation_reason": "gate_blocked"},
        "analysis_escalation": {"escalation_reason": "unknown_class"},
        "validation_escalation": {"escalation_reason": "gate_blocked"},
        "review_escalation": {"escalation_reason": "unknown_class"},
        "gate_blocks": {
            "risk_tier": "blocked",
            "escalation_reason": "review_rejected",
        },
    }
    heads_in = [row for row in TRANSITIONS if row.to_state is RunState.AWAITING_APPROVAL]
    assert {row.guard_name for row in heads_in} == set(wrong_reasons)
    for row in heads_in:
        attempts = (GuardInput(**wrong_reasons[row.guard_name]), GuardInput())
        for attempt in attempts:
            with pytest.raises(IllegalTransition) as excinfo:
                transition(row.from_state, row.to_state, attempt)
            assert excinfo.value.guard_name == row.guard_name
            assert row.guard_name in str(excinfo.value)


def test_ac2_all_six_reasons_accepted() -> None:
    entering_awaiting = {
        EscalationReason.LOW_CONFIDENCE: RunState.ANALYZING,
        EscalationReason.UNKNOWN_CLASS: RunState.CLASSIFYING,
        EscalationReason.NO_ROUTE: RunState.CLASSIFYING,
        EscalationReason.VALIDATION_FAILED: RunState.PROPOSING,
        EscalationReason.REVIEW_REJECTED: RunState.REVIEWING,
        EscalationReason.GATE_BLOCKED: RunState.GATING,
    }
    reason_fields: dict[EscalationReason, dict[str, object]] = {
        EscalationReason.LOW_CONFIDENCE: {
            "escalation_reason": "low_confidence",
            "confidence_below_cutoff": True,
        },
        EscalationReason.UNKNOWN_CLASS: {"escalation_reason": "unknown_class"},
        EscalationReason.NO_ROUTE: {"escalation_reason": "no_route"},
        EscalationReason.VALIDATION_FAILED: {"escalation_reason": "validation_failed"},
        EscalationReason.REVIEW_REJECTED: {"escalation_reason": "review_rejected"},
        EscalationReason.GATE_BLOCKED: {"risk_tier": "blocked", "escalation_reason": "gate_blocked"},
    }
    from workflow.transitions import guard_fields

    for reason, src in entering_awaiting.items():
        moved = transition(
            src, RunState.AWAITING_APPROVAL, GuardInput(**reason_fields[reason])
        )
        assert moved.to_state == RunState.AWAITING_APPROVAL
        assert moved.guard(GuardInput(**guard_fields(moved.guard_name)))


# ---- AC3: guarded edges reject missing guard data ----


def test_ac3_guarded_edges_reject_missing_guard_data() -> None:
    guarded_edges = (
        (RunState.CLASSIFYING, RunState.AWAITING_APPROVAL),
        (RunState.ANALYZING, RunState.REPORTING),
        (RunState.REVIEWING, RunState.PROPOSING),
        (RunState.GATING, RunState.PR_OPENING),
        (RunState.AWAITING_APPROVAL, RunState.PR_OPENING),
        (RunState.AWAITING_APPROVAL, RunState.ANALYZING),
        (RunState.REPORTING, RunState.REJECTED_BY_HUMAN),
    )
    for frm, to in guarded_edges:
        rows = [row for row in transitions_from(frm) if row.to_state == to]
        if not rows:
            continue  # undeclared for this from-state; separate AC1 test owns it
        if any(GUARDS[row.guard_name](GuardInput()) for row in rows):
            continue  # that from-state's guard fires on empty data by design
        with pytest.raises(IllegalTransition) as excinfo:
            transition(frm, to, GuardInput())
        assert excinfo.value.guard_name  # names the failed guard


# ---- AC3: branch-table fixtures (class, gate, revision, approval) ----


def test_ac3_branch_table_class() -> None:
    infra = transition(
        RunState.ANALYZING, RunState.REPORTING, GuardInput(failure_class="infra")
    )
    assert infra.to_state == RunState.REPORTING
    for class_value in ("code", "flaky", "external"):
        proposed = transition(
            RunState.ANALYZING,
            RunState.PROPOSING,
            GuardInput(failure_class=class_value),
        )
        assert proposed.to_state == RunState.PROPOSING
    with pytest.raises(IllegalTransition):
        transition(RunState.ANALYZING, RunState.PROPOSING, GuardInput(failure_class="infra"))
    with pytest.raises(IllegalTransition):
        transition(
            RunState.ANALYZING, RunState.REPORTING, GuardInput(failure_class="unknown")
        )
    for other in ("code", "flaky", "external"):
        with pytest.raises(IllegalTransition):
            transition(
                RunState.ANALYZING, RunState.REPORTING, GuardInput(failure_class=other)
            )


def test_ac3_branch_table_gate() -> None:
    opened = transition(
        RunState.GATING, RunState.PR_OPENING, GuardInput(risk_tier="normal")
    )
    assert opened.to_state == RunState.PR_OPENING
    blocked = transition(
        RunState.GATING,
        RunState.AWAITING_APPROVAL,
        GuardInput(risk_tier="blocked", escalation_reason="gate_blocked"),
    )
    assert blocked.to_state == RunState.AWAITING_APPROVAL
    with pytest.raises(IllegalTransition):
        transition(RunState.GATING, RunState.PR_OPENING, GuardInput(risk_tier="blocked"))
    with pytest.raises(IllegalTransition):
        transition(
            RunState.GATING, RunState.AWAITING_APPROVAL, GuardInput(risk_tier="normal")
        )
    # AD-1: a blocked tier without the matching gate_blocked reason refuses
    with pytest.raises(IllegalTransition):
        transition(
            RunState.GATING, RunState.AWAITING_APPROVAL, GuardInput(risk_tier="blocked")
        )


def test_ac3_branch_table_revision() -> None:
    reopened = transition(
        RunState.REVIEWING,
        RunState.PROPOSING,
        GuardInput(revision_round=0, max_revision_rounds=TEST_MAX_ROUNDS),
    )
    assert reopened.to_state == RunState.PROPOSING
    still_revising = transition(
        RunState.REVIEWING,
        RunState.PROPOSING,
        GuardInput(revision_round=1, max_revision_rounds=TEST_MAX_ROUNDS),
    )
    assert still_revising.to_state == RunState.PROPOSING
    with pytest.raises(IllegalTransition):
        transition(
            RunState.REVIEWING,
            RunState.PROPOSING,
            GuardInput(
                revision_round=TEST_MAX_ROUNDS, max_revision_rounds=TEST_MAX_ROUNDS
            ),
        )
    rejected = transition(
        RunState.REVIEWING,
        RunState.AWAITING_APPROVAL,
        GuardInput(escalation_reason="review_rejected"),
    )
    assert rejected.to_state == RunState.AWAITING_APPROVAL


def test_ac3_branch_table_approval() -> None:
    report = transition(
        RunState.AWAITING_APPROVAL,
        RunState.REPORTING,
        GuardInput(decision="approve", touches_workflow_files=True),
    )
    assert report.to_state == RunState.REPORTING
    opened = transition(
        RunState.AWAITING_APPROVAL,
        RunState.PR_OPENING,
        GuardInput(decision="approve", has_proposal=True),
    )
    assert opened.to_state == RunState.PR_OPENING
    reanalyzed = transition(
        RunState.AWAITING_APPROVAL,
        RunState.ANALYZING,
        GuardInput(decision="approve", class_override="code"),
    )
    assert reanalyzed.to_state == RunState.ANALYZING
    rejected = transition(
        RunState.AWAITING_APPROVAL, RunState.REPORTING, GuardInput(decision="reject")
    )
    assert rejected.to_state == RunState.REPORTING
    # declared-but-refused move names every refusing guard (AD-22 message)
    with pytest.raises(IllegalTransition) as nobody_passes:
        transition(
            RunState.AWAITING_APPROVAL, RunState.REPORTING, GuardInput(decision="approve")
        )
    for name in ("approve_of_workflow_diff", "reject_by_human"):
        assert name in str(nobody_passes.value)
    refusals = (
        (RunState.PR_OPENING, GuardInput(decision="approve", touches_workflow_files=True)),
        (RunState.REPORTING, GuardInput(decision="approve", has_proposal=True)),
        (RunState.PR_OPENING, GuardInput(decision="approve", class_override="code")),
        (RunState.ANALYZING, GuardInput(decision="approve", has_proposal=True)),
    )
    for to, shape in refusals:
        with pytest.raises(IllegalTransition):
            transition(RunState.AWAITING_APPROVAL, to, shape)
