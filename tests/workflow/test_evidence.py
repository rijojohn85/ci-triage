"""Story 2.7 pure evidence behaviour."""

from datetime import datetime, timedelta, timezone

from contracts.evidence import CommitRecord, DistilledLogLine
from workflow.evidence import ChangedCommit, WorkflowRun, assemble_pack, rank_candidates, select_baseline

SHA = "a" * 40
HEAD = "b" * 40
NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)


def test_ac1_latest_matching_success_and_fallback() -> None:
    failed = WorkflowRun(1, 7, 9, "feature", HEAD, NOW, "failure")
    good = WorkflowRun(1, 6, 9, "feature", SHA, NOW, "success")
    other = WorkflowRun(1, 8, 10, "feature", HEAD, NOW, "success")
    assert select_baseline(failed, [other, good], HEAD) == SHA
    assert select_baseline(failed, [other], SHA) == SHA


def test_ac2_two_suspects_normalized_intersection_and_stable_order() -> None:
    commits = [
        ChangedCommit(CommitRecord(sha=HEAD, message="second", author_login="x"), ("./src/a.py",)),
        ChangedCommit(CommitRecord(sha=SHA, message="first", author_login="x"), ("tests/test_a.py", "src/a.py")),
    ]
    ranked = rank_candidates(commits, ["src/a.py", "tests/test_a.py"])
    assert [(c.sha, c.rank) for c in ranked] == [(SHA, 1), (HEAD, 2)]
    assert ranked == rank_candidates(list(reversed(commits)), ["tests/test_a.py", "src/a.py"])
    assert rank_candidates(commits, ["unrelated.py"]) == []


def test_ac1_empty_actual_range_is_valid_pack() -> None:
    pack = assemble_pack(1, SHA, [], [DistilledLogLine(line_number=1, text="ERROR")], [])
    assert pack.commits == []
    assert pack.candidate_suspects == []


def test_ac1_latest_matching_success_multiple_matches_reversal_and_ties() -> None:
    from workflow.evidence import latest_matching_success

    failed = WorkflowRun(1, 30, 9, "feature", HEAD, NOW, "failure")
    older = WorkflowRun(1, 10, 9, "feature", "c" * 40, NOW, "success")
    newest = WorkflowRun(1, 20, 9, "feature", SHA, NOW, "success")
    other_branch = WorkflowRun(1, 25, 9, "main", HEAD, NOW, "success")
    other_workflow = WorkflowRun(1, 26, 8, "feature", HEAD, NOW, "success")
    not_success = WorkflowRun(1, 27, 9, "feature", HEAD, NOW, "failure")
    future = WorkflowRun(1, 31, 9, "feature", HEAD, NOW, "success")
    runs = [older, newest, other_branch, other_workflow, not_success, future]
    assert latest_matching_success(failed, runs) == newest
    assert latest_matching_success(failed, list(reversed(runs))) == newest
    assert select_baseline(failed, runs, HEAD) == SHA
    assert latest_matching_success(failed, [not_success, other_branch]) is None


def test_ac1_latest_success_uses_date_before_run_id() -> None:
    from workflow.evidence import latest_matching_success

    failed = WorkflowRun(1, 30, 9, "feature", HEAD, NOW, "failure")
    older = WorkflowRun(
        1, 25, 9, "feature", "c" * 40, NOW - timedelta(hours=2), "success"
    )
    later = WorkflowRun(
        1, 5, 9, "feature", SHA, NOW - timedelta(hours=1), "success"
    )
    assert latest_matching_success(failed, [older, later]) == later
    assert latest_matching_success(failed, [later, older]) == later
    assert select_baseline(failed, [older, later], HEAD) == SHA
