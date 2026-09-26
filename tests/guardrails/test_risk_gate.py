"""Story 4.2 tests for `guardrails/risk_gate.py` (AC1, AC2, AC3).

One registry entry per AD-13 rule, evaluated over the proposed diff, the
base content of modified files and the Reviewer's objections. Every rule
carries a positive AND a negative fixture (RT-07), plus the S5 timeout-bump
fixture. The gate is pure: no GitHub, Postgres, HTTP or model call, and no
model-asserted risk tier as input — override-impossibility is structural.
"""

import inspect

import pytest

from contracts.citations import HistoryRowCitation, JevSignalCitation, LogLineCitation
from contracts.enums import DiffOperation, FailureClass, ObjectionSeverity, RiskTier
from contracts.objections import Objection
from contracts.verdict import DiffFile, ProposedDiff, Quarantine, TriageVerdict
from guardrails.risk_gate import (
    RISK_RULES,
    GateInput,
    GateReason,
    RiskGateConfig,
    RiskRule,
    evaluate_risk,
)
from tests.contracts.samples import FULL_SHA
from tests.fixtures.thresholds import FIXTURE_THRESHOLDS_PATH
from workflow.thresholds import load_thresholds

_FIXTURES = load_thresholds(FIXTURE_THRESHOLDS_PATH)
CONFIG = RiskGateConfig(
    workflow_path_glob=_FIXTURES.workflow_path_glob,
    secret_path_globs=_FIXTURES.risk_gate.secret_path_globs,
    infra_path_globs=_FIXTURES.risk_gate.infra_path_globs,
)


def diff_of(*files: DiffFile) -> ProposedDiff:
    return ProposedDiff(base_sha=FULL_SHA, files=list(files))


def gate_input(
    diff: ProposedDiff | None,
    prior: dict[str, str] | None = None,
    objections: tuple[Objection, ...] = (),
) -> GateInput:
    return GateInput(
        diff=diff,
        config=CONFIG,
        prior_contents=prior or {},
        objections=objections,
    )


def dangerous_objection() -> Objection:
    return Objection(
        severity=ObjectionSeverity.DANGEROUS,
        category="bug_hiding",
        claim="this diff hides the failure instead of fixing it",
        citation=LogLineCitation(log_line=1),
    )


def rule_codes(reasons: tuple[GateReason, ...]) -> set[str]:
    return {reason.rule_code for reason in reasons}


# One positive and one negative fixture per registry rule (RT-07). A registry
# entry without a fixture fails the test, so a new rule cannot land unproven.
POSITIVE_FIXTURES = {
    "test_disabled": lambda: gate_input(
        diff_of(
            DiffFile(
                path="tests/test_pay.py",
                op=DiffOperation.ADD,
                new_content=(
                    "import pytest\n\n\n"
                    "@pytest.mark.skip(reason='flaky')\n"
                    "def test_pay():\n    assert True\n"
                ),
            )
        )
    ),
    "retry_added": lambda: gate_input(
        diff_of(
            DiffFile(
                path="tests/test_pay.py",
                op=DiffOperation.MODIFY,
                new_content="retries = 3\ndef test_pay():\n    assert True\n",
            )
        ),
        prior={"tests/test_pay.py": "def test_pay():\n    assert True\n"},
    ),
    "timeout_increased": lambda: gate_input(
        diff_of(
            DiffFile(
                path="tests/test_slow.py",
                op=DiffOperation.MODIFY,
                new_content="timeout = 60\ndef test_slow():\n    pass\n",
            )
        ),
        prior={"tests/test_slow.py": "timeout = 5\ndef test_slow():\n    pass\n"},
    ),
    "assertion_loosened": lambda: gate_input(
        diff_of(
            DiffFile(
                path="tests/test_calc.py",
                op=DiffOperation.MODIFY,
                new_content="assertIn(total, expected)\n",
            )
        ),
        prior={"tests/test_calc.py": "assertEqual(total, expected)\n"},
    ),
    "workflow_file_touched": lambda: gate_input(
        diff_of(
            DiffFile(
                path=".github/workflows/ci.yml",
                op=DiffOperation.ADD,
                new_content="name: ci\non: push\n",
            )
        )
    ),
    "secret_touched": lambda: gate_input(
        diff_of(DiffFile(path=".env", op=DiffOperation.ADD, new_content="VALUE=1\n"))
    ),
    "infra_manifest_touched": lambda: gate_input(
        diff_of(
            DiffFile(
                path="docker-compose.yml",
                op=DiffOperation.ADD,
                new_content="services:\n  app:\n    image: app\n",
            )
        )
    ),
    "reviewer_dangerous": lambda: gate_input(
        diff_of(
            DiffFile(
                path="src/pay.py",
                op=DiffOperation.MODIFY,
                new_content="def pay():\n    return 2\n",
            )
        ),
        prior={"src/pay.py": "def pay():\n    return 1\n"},
        objections=(dangerous_objection(),),
    ),
    "prior_content_missing": lambda: gate_input(
        diff_of(
            DiffFile(
                path="src/pay.py",
                op=DiffOperation.MODIFY,
                new_content="def pay():\n    return 2\n",
            )
        ),
    ),
}

NEGATIVE_FIXTURES = {
    "test_disabled": lambda: gate_input(
        diff_of(
            DiffFile(
                path="tests/test_pay.py",
                op=DiffOperation.ADD,
                new_content="def test_pay():\n    assert total == 10\n",
            )
        )
    ),
    "retry_added": lambda: gate_input(
        diff_of(
            DiffFile(
                path="tests/test_pay.py",
                op=DiffOperation.MODIFY,
                new_content="retries = 3\ndef test_pay():\n    assert total == 10\n",
            )
        ),
        # The retry already exists in the base content: not a new one.
        prior={"tests/test_pay.py": "retries = 3\ndef test_pay():\n    assert True\n"},
    ),
    "timeout_increased": lambda: gate_input(
        diff_of(
            DiffFile(
                path="tests/test_slow.py",
                op=DiffOperation.MODIFY,
                new_content="timeout = 5\ndef test_slow():\n    pass\n",
            )
        ),
        prior={"tests/test_slow.py": "timeout = 60\ndef test_slow():\n    pass\n"},
    ),
    "assertion_loosened": lambda: gate_input(
        diff_of(
            DiffFile(
                path="tests/test_calc.py",
                op=DiffOperation.MODIFY,
                new_content="assertEqual(total, expected)\n",
            )
        ),
        # Strengthening, not loosening: the weak form was in the base.
        prior={"tests/test_calc.py": "assertIn(total, expected)\n"},
    ),
    "workflow_file_touched": lambda: gate_input(
        diff_of(
            DiffFile(
                path="src/pay.py",
                op=DiffOperation.MODIFY,
                new_content="def pay():\n    return 2\n",
            )
        ),
        prior={"src/pay.py": "def pay():\n    return 1\n"},
    ),
    "secret_touched": lambda: gate_input(
        diff_of(
            DiffFile(
                path="src/pay.py",
                op=DiffOperation.MODIFY,
                new_content="def pay():\n    return 2\n",
            )
        ),
        prior={"src/pay.py": "def pay():\n    return 1\n"},
    ),
    "infra_manifest_touched": lambda: gate_input(
        diff_of(
            DiffFile(
                path="src/pay.py",
                op=DiffOperation.MODIFY,
                new_content="def pay():\n    return 2\n",
            )
        ),
        prior={"src/pay.py": "def pay():\n    return 1\n"},
    ),
    "reviewer_dangerous": lambda: gate_input(
        diff_of(
            DiffFile(
                path="src/pay.py",
                op=DiffOperation.MODIFY,
                new_content="def pay():\n    return 2\n",
            )
        ),
        prior={"src/pay.py": "def pay():\n    return 1\n"},
        objections=(
            Objection(
                severity=ObjectionSeverity.MAJOR,
                category="logic",
                claim="the fix may be incomplete",
                citation=LogLineCitation(log_line=1),
            ),
        ),
    ),
    "prior_content_missing": lambda: gate_input(
        diff_of(
            DiffFile(
                path="src/pay.py",
                op=DiffOperation.MODIFY,
                new_content="def pay():\n    return 2\n",
            )
        ),
        prior={"src/pay.py": "def pay():\n    return 1\n"},
    ),
}


# --- AC1: every AD-13 rule blocks its positive fixture


@pytest.mark.parametrize("rule", RISK_RULES, ids=[rule.code for rule in RISK_RULES])
def test_ac1_every_rule_blocks_its_positive_fixture(rule: RiskRule) -> None:
    build = POSITIVE_FIXTURES.get(rule.code)
    if build is None:
        pytest.fail(f"registry rule {rule.code!r} has no positive fixture")

    decision = evaluate_risk(build())

    assert decision.risk_tier is RiskTier.BLOCKED
    assert rule.code in rule_codes(decision.reasons)


# --- AC1: every rule passes its negative fixture (same surface, safe change)


@pytest.mark.parametrize("rule", RISK_RULES, ids=[rule.code for rule in RISK_RULES])
def test_ac1_every_rule_passes_its_negative_fixture(rule: RiskRule) -> None:
    build = NEGATIVE_FIXTURES.get(rule.code)
    if build is None:
        pytest.fail(f"registry rule {rule.code!r} has no negative fixture")

    decision = evaluate_risk(build())

    assert decision.risk_tier is RiskTier.NORMAL
    assert decision.reasons == ()


# --- AC1: a deleted test file is a block (the test_disabled delete arm)


@pytest.mark.parametrize("path", ["tests/test_pay.py", "tests/conftest.py"])
def test_ac1_test_file_deletion_is_blocked(path: str) -> None:
    decision = evaluate_risk(
        gate_input(
            diff_of(DiffFile(path=path, op=DiffOperation.DELETE, new_content=""))
        )
    )

    assert decision.risk_tier is RiskTier.BLOCKED
    assert rule_codes(decision.reasons) == {"test_disabled"}


# --- AC1: runtime pytest.xfail / pytest.importorskip are skips too


def test_ac1_runtime_skip_calls_are_blocked() -> None:
    decision = evaluate_risk(
        gate_input(
            diff_of(
                DiffFile(
                    path="tests/test_pay.py",
                    op=DiffOperation.ADD,
                    new_content=(
                        "pytest.importorskip('redis')\n"
                        "def test_pay():\n    assert True\n"
                    ),
                ),
                DiffFile(
                    path="tests/test_calc.py",
                    op=DiffOperation.ADD,
                    new_content="def test_calc():\n    pytest.xfail('known bug')\n",
                ),
            )
        )
    )

    assert decision.risk_tier is RiskTier.BLOCKED
    assert rule_codes(decision.reasons) == {"test_disabled"}


# --- AC1: relocating an existing skip line is still a block (difflib, not multiset)


def test_ac1_relocated_skip_line_is_still_blocked() -> None:
    prior = (
        "def test_a():\n"
        "    assert True\n"
        "\n"
        "@pytest.mark.skip(reason='flaky')\n"
        "def test_b():\n"
        "    assert True\n"
    )
    moved = (
        "@pytest.mark.skip(reason='flaky')\n"
        "def test_a():\n"
        "    assert True\n"
        "\n"
        "def test_b():\n"
        "    assert True\n"
    )

    decision = evaluate_risk(
        gate_input(
            diff_of(
                DiffFile(
                    path="tests/test_pay.py",
                    op=DiffOperation.MODIFY,
                    new_content=moved,
                )
            ),
            prior={"tests/test_pay.py": prior},
        )
    )

    assert decision.risk_tier is RiskTier.BLOCKED
    assert rule_codes(decision.reasons) == {"test_disabled"}


# --- AC1: case-variant paths cannot evade the path rules


def test_ac1_case_variant_paths_are_blocked() -> None:
    decision = evaluate_risk(
        gate_input(
            diff_of(
                DiffFile(
                    path="Secrets/token.pem", op=DiffOperation.ADD, new_content=""
                ),
                DiffFile(
                    path="deploy/DOCKERFILE", op=DiffOperation.ADD, new_content=""
                ),
            )
        )
    )

    assert decision.risk_tier is RiskTier.BLOCKED
    assert rule_codes(decision.reasons) == {
        "secret_touched",
        "infra_manifest_touched",
    }


# --- AC1: a DELETE + ADD of the same path fails closed (no comparison arm sees it)


def test_ac1_delete_add_same_path_fails_closed() -> None:
    decision = evaluate_risk(
        gate_input(
            diff_of(
                DiffFile(path="src/pay.py", op=DiffOperation.DELETE, new_content=""),
                DiffFile(
                    path="src/pay.py",
                    op=DiffOperation.ADD,
                    new_content="timeout = 60\n",
                ),
            ),
            # Even with the base content supplied, the pair evades every
            # comparison rule — so it fails closed regardless.
            prior={"src/pay.py": "timeout = 5\n"},
        )
    )

    assert decision.risk_tier is RiskTier.BLOCKED
    assert rule_codes(decision.reasons) == {"prior_content_missing"}


# --- AC1: a dangerous Reviewer objection blocks a safe diff (AD-12)


def test_ac1_dangerous_objection_blocks_safe_diff() -> None:
    decision = evaluate_risk(POSITIVE_FIXTURES["reviewer_dangerous"]())

    assert decision.risk_tier is RiskTier.BLOCKED
    assert rule_codes(decision.reasons) == {"reviewer_dangerous"}


# --- AC1: a model-asserted tier cannot override the gate


def test_ac1_model_asserted_tier_cannot_override() -> None:
    # The verdict claims `normal` over a test-skipping diff; the gate never
    # receives a tier, so the claim cannot leak in — structural, not a check.
    skipping = diff_of(
        DiffFile(
            path="tests/test_pay.py",
            op=DiffOperation.ADD,
            new_content="@pytest.mark.skip\ndef test_pay():\n    assert True\n",
        )
    )
    verdict = TriageVerdict(
        class_=FailureClass.CODE,
        confidence=0.9,
        confidence_jev=0.9,
        caps=(),
        suspects=[],
        citations=[JevSignalCitation(answer="choice")],
        risk_tier=RiskTier.NORMAL,
        proposed_diff=skipping,
    )
    assert verdict.risk_tier is RiskTier.NORMAL
    assert "risk_tier" not in inspect.signature(evaluate_risk).parameters
    assert "risk_tier" not in GateInput.model_fields

    decision = evaluate_risk(gate_input(skipping))

    assert decision.risk_tier is RiskTier.BLOCKED
    assert rule_codes(decision.reasons) == {"test_disabled"}


# --- AC1: the S5 timeout-bump fixture (the only-obvious-fix case)


def test_ac1_s5_timeout_bump_fixture_blocked() -> None:
    decision = evaluate_risk(
        gate_input(
            diff_of(
                DiffFile(
                    path="tests/test_slow.py",
                    op=DiffOperation.MODIFY,
                    new_content="def test_slow():\n    timeout = 60\n",
                )
            ),
            prior={"tests/test_slow.py": "def test_slow():\n    timeout = 5\n"},
        )
    )

    assert decision.risk_tier is RiskTier.BLOCKED
    assert rule_codes(decision.reasons) == {"timeout_increased"}


# --- AC2: a safe root-cause diff is normal


def test_ac2_safe_root_cause_diff_is_normal() -> None:
    decision = evaluate_risk(
        gate_input(
            diff_of(
                DiffFile(
                    path="tests/test_totals.py",
                    op=DiffOperation.MODIFY,
                    new_content="EXPECTED_TOTAL = 100\n",
                )
            ),
            prior={"tests/test_totals.py": "EXPECTED_TOTAL = 99\n"},
        )
    )

    assert decision.risk_tier is RiskTier.NORMAL
    assert decision.reasons == ()


# --- AC2: no diff to gate stays not_gated


def test_ac2_no_diff_is_not_gated() -> None:
    decision = evaluate_risk(gate_input(None))

    assert decision.risk_tier is RiskTier.NOT_GATED
    assert decision.reasons == ()


# --- AC2: quarantine is metadata only — never a gate input or a block reason


def test_ac2_quarantine_is_metadata_only() -> None:
    safe = diff_of(
        DiffFile(
            path="src/pay.py",
            op=DiffOperation.MODIFY,
            new_content="def pay():\n    return 2\n",
        )
    )
    verdict = TriageVerdict(
        class_=FailureClass.FLAKY,
        confidence=0.9,
        confidence_jev=0.9,
        caps=(),
        suspects=[],
        citations=[JevSignalCitation(answer="choice")],
        risk_tier=RiskTier.NORMAL,
        proposed_diff=safe,
        quarantine=Quarantine(
            test_id="tests/test_pay.py",
            reason="flaky in history",
            citations=[HistoryRowCitation(row_id="row-1")],
        ),
    )
    assert verdict.quarantine is not None
    assert "quarantine" not in GateInput.model_fields

    decision = evaluate_risk(
        gate_input(safe, prior={"src/pay.py": "def pay():\n    return 1\n"})
    )

    assert decision.risk_tier is RiskTier.NORMAL
    assert decision.reasons == ()


# --- AC2: a modified file without base content fails closed


def test_ac2_modified_file_without_prior_content_fails_closed() -> None:
    decision = evaluate_risk(POSITIVE_FIXTURES["prior_content_missing"]())

    assert decision.risk_tier is RiskTier.BLOCKED
    assert rule_codes(decision.reasons) == {"prior_content_missing"}


# --- AC3: reasons are structured evidence (rule code, message, location)


def test_ac3_reasons_are_structured_evidence() -> None:
    decision = evaluate_risk(POSITIVE_FIXTURES["workflow_file_touched"]())

    assert len(decision.reasons) == 1
    reason = decision.reasons[0]
    assert reason.rule_code == "workflow_file_touched"
    assert "ci.yml" in reason.message
    assert reason.location == ".github/workflows/ci.yml"


# --- AC3: the gate collects every hit, never stops at the first


def test_ac3_gate_collects_every_hit() -> None:
    decision = evaluate_risk(
        gate_input(
            diff_of(
                DiffFile(
                    path=".github/workflows/ci.yml",
                    op=DiffOperation.ADD,
                    new_content="- run: pytest\n",
                ),
                DiffFile(
                    path="tests/test_pay.py",
                    op=DiffOperation.ADD,
                    new_content="@pytest.mark.skip\ndef test_pay():\n    assert True\n",
                ),
            )
        )
    )

    assert decision.risk_tier is RiskTier.BLOCKED
    assert {"workflow_file_touched", "test_disabled"} <= rule_codes(decision.reasons)
