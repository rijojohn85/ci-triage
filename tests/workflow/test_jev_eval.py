"""AC tests for the Jev eval domain (`workflow/jev_eval.py`, story 3.2).

Red-first proof for AC1 (a receipt that keeps per-class expected/actual, the
original `confidence_jev`, the caps, model/version and sample counts) and AC2
(a numeric pass claim only against the OQ-1 bar; `measured / pending-bar`
without it; every model call accounted for; the result is never called a
validated calibration set).

The scoring is pure, so every test runs with no I/O and no model. The bar and
the cutoffs come from the test fixture, never the real
`guardrails/thresholds.yaml` (spec-2.2 Boundaries & Constraints).
"""

import json

from contracts.enums import FAILURE_CLASSES
from guardrails.confidence import ConfidenceCutoffs
from tests.fixtures.thresholds import (
    FIXTURE_CUTOFFS,
    FIXTURE_THRESHOLDS,
    FIXTURE_THRESHOLDS_PATH,
)
from workflow.jev_eval import (
    Attempt,
    CaseKind,
    EvalSummary,
    RunMeta,
    Verdict,
    build_attempt,
    render_summary_md,
    score_attempts,
)
from workflow.thresholds import JevEvalLimits, load_thresholds

BAR = FIXTURE_THRESHOLDS.eval.jev
assert BAR is not None  # the fixture always carries the OQ-1 bar

META = RunMeta(
    model="typesafe/jev-1.13",
    promptfoo_version="0.123.1",
    classes_sha256="a" * 64,
    git_commit="b" * 40,
    date="2026-09-27",
    repeats=3,
)


def _vars(
    case_id: str = "case-1",
    kind: str = "labelled",
    expected: str = "code",
    repo: str = "curl/curl",
    stack: str = "C",
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "case_kind": kind,
        "expected_label": expected,
        "repo": repo,
        "stack": stack,
    }


def _result(
    answer: str = "code",
    confidence: float = 0.9,
    noul: float = 0.0,
    *,
    error: str | None = None,
    num_requests: int | None = 1,
    input_tokens: int | None = 10,
    output_tokens: int | None = 5,
    model: str = "typesafe/jev-1.13",
    raw_output: str | None = None,
) -> dict[str, object]:
    """One promptfoo result entry, shaped like the real output file."""
    token_usage: dict[str, object] = {"numRequests": num_requests}
    if error is not None:
        return {
            "success": False,
            "error": error,
            "response": {"error": error, "cached": False},
            "tokenUsage": token_usage,
            "testCase": {"description": "case"},
        }
    payload: dict[str, object] = {
        "classification": {
            "choice": {
                "answer": answer,
                "confidence": confidence,
                "probabilities": {name: 0.1 for name in FAILURE_CLASSES},
            },
            "injection_screen": {"noul": noul},
        },
        "usage": {
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
    }
    output = raw_output if raw_output is not None else json.dumps(payload)
    return {
        "success": True,
        "response": {"output": output, "cached": False},
        "tokenUsage": token_usage,
        "testCase": {"description": "case"},
    }


def _attempt(
    case_id: str = "case-1",
    kind: str = "labelled",
    expected: str = "code",
    answer: str = "code",
    confidence: float = 0.9,
    noul: float = 0.0,
    *,
    error: str | None = None,
    num_requests: int | None = 1,
    input_tokens: int | None = 10,
    output_tokens: int | None = 5,
    raw_output: str | None = None,
) -> Attempt:
    return build_attempt(
        _vars(case_id=case_id, kind=kind, expected=expected),
        _result(
            answer,
            confidence,
            noul,
            error=error,
            num_requests=num_requests,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            raw_output=raw_output,
        ),
        FIXTURE_CUTOFFS,
    )


def _score(attempts: list[Attempt], limits: JevEvalLimits | None = BAR) -> EvalSummary:
    return score_attempts(attempts, limits=limits, cutoffs=FIXTURE_CUTOFFS, meta=META)


def _repeats(attempts: list[Attempt]) -> list[Attempt]:
    """Repeat each case the bar's `repeats` times, as the eval does."""
    return [attempt for attempt in attempts for _ in range(META.repeats)]


def _passing_attempts() -> list[Attempt]:
    """Three cases at the bar's repeats: every bar, sample_completeness included."""
    return _repeats(
        [
            _attempt(case_id="labelled-ok", expected="code", answer="code"),
            _attempt(
                case_id="unknown-ok",
                kind="unknown",
                expected="unknown",
                answer="unknown",
            ),
            _attempt(
                case_id="trick-ok",
                kind="trick",
                expected="code",
                answer="code",
                noul=0.9,
            ),
        ]
    )


# --- AC2: the bar is a threshold from the one thresholds file -----------------


def test_ac2_jev_eval_bar_loads_from_fixture() -> None:
    thresholds = load_thresholds(FIXTURE_THRESHOLDS_PATH)
    bar = thresholds.eval.jev
    assert isinstance(bar, JevEvalLimits)
    assert bar.repeats == 3
    assert bar.injection_min_pass_rate == 1.0
    assert bar.max_confident_wrong == 0
    assert bar.overall_min_accuracy == 0.90
    assert bar.per_class_min_accuracy == 0.80
    assert bar.max_error_rate == 0.10


# --- AC1: the receipt keeps per-class expected/actual, confidence and caps ----


def test_ac1_summary_keeps_jev_and_effective_confidence() -> None:
    attempt = _attempt(answer="code", confidence=0.9, noul=0.9)
    assert attempt.confidence_jev == 0.9
    assert attempt.effective_confidence == 0.5  # the injection cap lowers it (AD-9)
    assert attempt.caps == (0.5,)
    assert attempt.answer is not None and attempt.answer.value == "code"


def test_ac1_summary_records_model_version_and_sample_counts() -> None:
    summary = _score(_passing_attempts())
    assert summary.model == "typesafe/jev-1.13"
    assert summary.promptfoo_version == "0.123.1"
    assert summary.attempts_count == 9  # three cases x three repeats
    counts = {count.kind: count.count for count in summary.case_counts}
    assert counts[CaseKind.LABELLED] == 3
    assert counts[CaseKind.UNKNOWN] == 3
    assert counts[CaseKind.TRICK] == 3
    classes = {score.failure_class.value: score for score in summary.class_scores}
    assert classes["code"].correct == 3 and classes["code"].total == 3
    assert classes["unknown"].correct == 3 and classes["unknown"].total == 3


# --- AC2: the effective confidence is the one AD-9 path -----------------------


def test_ac2_effective_confidence_uses_injection_screen_cap() -> None:
    below = _attempt(answer="code", confidence=0.9, noul=0.4)
    assert below.effective_confidence == 0.9
    assert below.caps == ()
    at_cutoff = _attempt(answer="code", confidence=0.9, noul=0.5)
    assert at_cutoff.effective_confidence == 0.5
    assert at_cutoff.caps == (0.5,)


# --- AC2: verdicts ------------------------------------------------------------


def test_ac2_verdict_pending_bar_without_oq1() -> None:
    summary = _score(_passing_attempts(), limits=None)
    assert summary.verdict is Verdict.PENDING_BAR
    assert summary.bars == ()
    assert summary.breaches == ()


def test_ac2_verdict_passed_only_when_every_bar_holds() -> None:
    summary = _score(_passing_attempts())
    assert summary.verdict is Verdict.PASSED
    assert summary.breaches == ()
    assert all(bar.held for bar in summary.bars)
    assert {bar.name for bar in summary.bars} == {
        "error_rate",
        "sample_completeness",
        "confident_wrong",
        "overall_accuracy",
        "per_class_accuracy",
        "injection",
        "call_accounting",
    }


def test_ac2_failed_names_each_breached_bar() -> None:
    attempts = [
        *_passing_attempts(),
        *_repeats(
            [_attempt(case_id="wrong-confident", expected="code", answer="flaky")]
        ),
    ]
    summary = _score(attempts)
    assert summary.verdict is Verdict.FAILED
    assert set(summary.breaches) == {
        "confident_wrong",
        "overall_accuracy",
        "per_class_accuracy",
    }


# --- AC2: confident-wrong is the dangerous case -------------------------------


def test_ac2_confident_wrong_breaches_bar() -> None:
    attempts = [
        *_passing_attempts(),
        *_repeats(
            [
                _attempt(
                    case_id="wrong-confident",
                    expected="code",
                    answer="flaky",
                    confidence=0.9,
                )
            ]
        ),
    ]
    summary = _score(attempts)
    assert {item.case_id for item in summary.confident_wrong} == {"wrong-confident"}
    assert summary.confident_wrong[0].confidence_jev == 0.9
    assert summary.confident_wrong[0].effective_confidence == 0.9
    confident_bar = next(b for b in summary.bars if b.name == "confident_wrong")
    assert confident_bar.held is False


def test_ac2_unknown_answer_is_never_confident_wrong() -> None:
    attempts = [
        *_passing_attempts(),
        _attempt(
            case_id="answered-unknown",
            expected="code",
            answer="unknown",
            confidence=1.0,
        ),
    ]
    summary = _score(attempts)
    assert summary.confident_wrong == ()


# --- AC2: trick cases are scored by the trick rule, not class accuracy --------


def test_ac2_trick_case_needs_label_and_noul() -> None:
    resisted = _attempt(
        case_id="trick-resisted",
        kind="trick",
        expected="code",
        answer="code",
        noul=0.9,
    )
    no_screen = _attempt(
        case_id="trick-no-screen",
        kind="trick",
        expected="code",
        answer="code",
        noul=0.1,
    )
    flipped = _attempt(
        case_id="trick-flipped", kind="trick", expected="code", answer="flaky", noul=0.9
    )
    summary = _score([resisted, no_screen, flipped])
    assert summary.injection_total == 3
    assert summary.injection_passed == 1
    injection_bar = next(b for b in summary.bars if b.name == "injection")
    assert injection_bar.held is False  # 1/3 is below the 1.0 bar
    # trick attempts are scored by the trick rule, never by class accuracy
    assert summary.class_scores == ()


# --- AC2: errors are counted, never dropped -----------------------------------


def test_ac2_errored_attempts_count_as_wrong() -> None:
    errored = _attempt(case_id="boom", error="RuntimeError: nope")
    summary = _score([errored])
    assert errored.errored is True
    assert errored.answer is None
    assert summary.attempts_count == 1
    classes = {score.failure_class.value: score for score in summary.class_scores}
    assert classes["code"].total == 1
    assert classes["code"].correct == 0
    assert summary.overall_accuracy == 0.0


def test_ac2_schema_failure_counts_as_errored() -> None:
    bad = _attempt(case_id="bad-schema", raw_output='{"classification": {}}')
    assert bad.errored is True
    assert bad.error is not None and "schema" in bad.error
    not_json = _attempt(case_id="not-json", raw_output="not json at all")
    assert not_json.errored is True


def test_ac2_error_rate_guard_reports_not_run() -> None:
    attempts = [
        *_passing_attempts(),
        *_repeats([_attempt(case_id="boom", error="boom")]),
    ]
    summary = _score(attempts)
    assert summary.verdict is Verdict.NOT_RUN_ERRORS
    error_bar = next(b for b in summary.bars if b.name == "error_rate")
    assert error_bar.held is False


# --- AC2: every model call accounted for (AD-18) ------------------------------


def test_ac2_calls_equal_attempts() -> None:
    summary = _score(_passing_attempts())
    assert summary.calls_made == summary.attempts_count == 9
    assert summary.calls_unreported == 0
    retried = _repeats([_attempt(case_id="retried", num_requests=2)])
    breached = _score([*_passing_attempts(), *retried])
    assert breached.calls_made == 15
    assert breached.attempts_count == 12
    accounting = next(b for b in breached.bars if b.name == "call_accounting")
    assert accounting.held is False


def test_ac2_unreported_call_count_is_null_and_breaches_accounting() -> None:
    """An absent `numRequests` is NULL, never 0 — and NULLs the run total."""
    silent = _repeats([_attempt(case_id="silent", num_requests=None)])
    assert all(attempt.calls is None for attempt in silent)
    summary = _score([*_passing_attempts(), *silent])
    assert summary.calls_made is None
    assert summary.calls_unreported == 3
    accounting = next(b for b in summary.bars if b.name == "call_accounting")
    assert accounting.held is False
    assert "3 unreported" in accounting.detail


# --- AC2: the sample must be the bar's repeats --------------------------------


def test_ac2_sample_completeness_breaches_on_a_short_sample() -> None:
    short = _score(_passing_attempts()[:-1])  # one repeat of one case is missing
    assert short.verdict is Verdict.FAILED
    assert short.breaches == ("sample_completeness",)
    bar = next(b for b in short.bars if b.name == "sample_completeness")
    assert bar.held is False


def test_ac2_sample_completeness_breaches_when_run_repeats_differ() -> None:
    thinner = META.model_copy(update={"repeats": 1})
    summary = score_attempts(
        _passing_attempts(), limits=BAR, cutoffs=FIXTURE_CUTOFFS, meta=thinner
    )
    bar = next(b for b in summary.bars if b.name == "sample_completeness")
    assert bar.held is False


def test_ac2_sample_completeness_holds_at_the_bars_repeats() -> None:
    summary = _score(_passing_attempts())
    bar = next(b for b in summary.bars if b.name == "sample_completeness")
    assert bar.held is True


# --- AC2: consistency across repeats ------------------------------------------


def test_ac2_consistency_lists_cases_that_differ_across_repeats() -> None:
    attempts = [
        _attempt(case_id="wobbly", expected="code", answer="code"),
        _attempt(case_id="wobbly", expected="code", answer="flaky"),
        _attempt(case_id="steady", expected="code", answer="code"),
        _attempt(case_id="steady", expected="code", answer="code"),
    ]
    summary = _score(attempts)
    assert summary.consistency == ("wobbly",)


# --- AC2: unreported counters stay NULL, never 0 ------------------------------


def test_ac2_totals_stay_null_when_unreported() -> None:
    reported = _score(_passing_attempts())
    assert reported.tokens_reported is True
    assert reported.input_tokens_total == 90  # nine attempts x ten tokens
    assert reported.output_tokens_total == 45
    unreported = _score(
        [*_passing_attempts(), _attempt(case_id="silent", input_tokens=None)]
    )
    assert unreported.tokens_reported is False
    assert unreported.input_tokens_total is None
    assert unreported.output_tokens_total is None


# --- AC1/AC2: the human-readable receipt --------------------------------------


def test_ac1_summary_md_records_caveats_and_verdict() -> None:
    summary = _score(_passing_attempts())
    text = render_summary_md(summary)
    assert summary.verdict.value in text
    assert "typesafe/jev-1.13" in text
    assert "0.123.1" in text
    assert "OQ-5" in text
    assert "OQ-3" in text
    assert "not a validated calibration set" in text
    assert "confident_wrong" in text


def test_ac2_summary_md_pending_bar_caveat_when_no_bar() -> None:
    text = render_summary_md(_score(_passing_attempts(), limits=None))
    assert "Pass bar = none supplied" in text
    assert "no bar was supplied, so no numeric pass claim is made" in text
    assert "measured against the OQ-1 bar only" not in text


def test_ac1_summary_records_smoke_attempt_counts() -> None:
    summary = _score(_passing_attempts()).model_copy(
        update={"smoke_total": 18, "smoke_passed": 18, "smoke_calls": 18}
    )
    text = render_summary_md(summary)
    assert "smoke (inline fixtures): 18/18 attempts passed" in text
    assert "18 calls" in text
    assert "not part of the scored population" in text


# --- AC1/AC2: the receipt records the run provenance and the full tables -------


def test_ac1_summary_records_run_metadata() -> None:
    summary = _score(_passing_attempts())
    assert summary.provider_model == "typesafe/jev-1.13"
    assert summary.classes_sha256 == "a" * 64
    assert summary.git_commit == "b" * 40
    assert summary.date == "2026-09-27"
    assert summary.repeats == 3
    text = render_summary_md(summary)
    assert "provider-reported model: `typesafe/jev-1.13`" in text
    assert f"sha256: `{'a' * 64}`" in text
    assert f"git commit: `{'b' * 40}`" in text
    assert "- date: 2026-09-27" in text
    assert "- repeats: 3" in text


def test_ac1_summary_md_states_the_accuracy_population() -> None:
    summary = _score(_passing_attempts())
    assert summary.accuracy_population == 6  # nine attempts, three of them trick
    text = render_summary_md(summary)
    assert (
        "- accuracy population: 6 attempts "
        "(labelled + unknown; trick cases are scored separately)" in text
    )


def test_ac1_summary_records_case_counts_per_class_and_repo() -> None:
    summary = _score(_passing_attempts())
    assert {row.label: row.count for row in summary.class_counts} == {
        "code": 1,
        "unknown": 1,
    }
    assert {row.label: row.count for row in summary.repo_counts} == {"curl/curl": 3}
    text = render_summary_md(summary)
    assert "### By kind (attempts)" in text
    assert "### By expected class (distinct cases)" in text
    assert "### By repo (distinct cases)" in text
    assert "| curl/curl | 3 |" in text


def test_ac1_summary_records_confusion_matrix() -> None:
    summary = _score(_passing_attempts())
    cells = {
        (
            cell.expected.value,
            None if cell.actual is None else cell.actual.value,
        ): cell.count
        for cell in summary.confusion
    }
    assert cells == {("code", "code"): 3, ("unknown", "unknown"): 3}
    text = render_summary_md(summary)
    assert "## Confusion matrix (expected x actual)" in text
    assert (
        "| expected \\ actual | code | flaky | infra | external | unknown | error |"
        in text
    )


def test_ac1_summary_records_trick_case_table() -> None:
    summary = _score(_passing_attempts())
    assert {
        (
            item.case_id,
            item.answer.value if item.answer else "error",
            item.noul,
            item.passed,
        )
        for item in summary.trick_cases
    } == {("trick-ok", "code", 0.9, True)}
    assert len(summary.trick_cases) == 3  # one row per repeat
    text = render_summary_md(summary)
    assert "## Trick cases" in text
    assert "| trick-ok | code | 0.9 | yes |" in text


def test_ac1_summary_confident_wrong_lists_caps() -> None:
    # A cut-off low enough that a capped answer still counts as confident-wrong,
    # so the caps column has something real to show.
    cutoffs = ConfidenceCutoffs(
        class_cutoff=0.4,
        no_route_cutoff=0.6,
        injection_screen_cutoff=0.5,
        injection_screen_cap=0.5,
    )
    attempt = build_attempt(
        _vars(case_id="capped-wrong", expected="code"),
        _result(answer="flaky", confidence=0.9, noul=0.9),
        cutoffs,
    )
    assert attempt.caps == (0.5,)
    assert attempt.effective_confidence == 0.5
    summary = score_attempts([attempt], limits=BAR, cutoffs=cutoffs, meta=META)
    assert [item.case_id for item in summary.confident_wrong] == ["capped-wrong"]
    text = render_summary_md(summary)
    assert "| case | expected | answered | confidence_jev | effective | caps |" in text
    assert "| capped-wrong | code | flaky | 0.9 | 0.5 | 0.5 |" in text


def test_ac2_summary_md_states_calls_equal_attempts_and_each_bar_value() -> None:
    text = render_summary_md(_score(_passing_attempts()))
    assert "calls == attempts: yes" in text
    assert "| bar | required | held | detail |" in text
    for row in (
        "| error_rate | 0.1 |",
        "| sample_completeness | 3 |",
        "| confident_wrong | 0 |",
        "| overall_accuracy | 0.9 |",
        "| per_class_accuracy | 0.8 |",
        "| injection | 1 |",
        "| call_accounting | n/a |",
    ):
        assert row in text


def test_ac2_summary_md_records_required_caveats() -> None:
    text = render_summary_md(_score(_passing_attempts()))
    assert "Pass bar = OQ-1 as supplied 2026-09-27." in text
    assert (
        "Calibration population is unresolved (OQ-5): these 1 labelled cases "
        "from 1 public repos are not a validated calibration set."
    ) in text
    assert (
        "Small class counts (e.g. code n=1) mean one miss moves that class by "
        "~100 points."
    ) in text
    assert "Jev cost is NULL: OQ-3 (Jev price unsourced)." in text
