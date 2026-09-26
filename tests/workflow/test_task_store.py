"""Story 2.4 unit tests — the read-only A2A task projection (AC1/AC2/AC3, AD-4).

The `TaskReader` boundary is a small Protocol (AGENTS.md "TDD": I/O against a
fake in unit tests). Every test proves one thing: the task id is the run id,
state and artifacts are read from `triage_run`/`run_step`, the store refuses
writes, a paused run is `INPUT_REQUIRED` with a blame-free evidence artifact,
unknown and other-repo ids expose nothing, and every AD-4 state renders 2.1's
mapping. No test touches a database or a model.
"""

import asyncio
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from a2a.server.context import ServerCallContext
from a2a.types.a2a_pb2 import ListTasksRequest, Task, TaskState
from google.protobuf.json_format import MessageToDict

from contracts.enums import FailureClass
from contracts.jev import JevChoice
from guardrails.confidence import ClassConfidence
from tests.contracts.samples import FULL_SHA, RUN_ID
from tests.fixtures.thresholds import FIXTURE_CUTOFFS
from workflow.projection import project
from workflow.run_states import RunState
from workflow.steps import StepRecord, StepStatus
from workflow.task_store import (
    ReadOnlyTaskStore,
    ReadOnlyTaskStoreError,
    RunRecord,
    TaskReader,
    build_task,
)

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
REPO_ID = 7
OTHER_REPO_ID = 8
UUID_VERSION_7 = 7


def full_confidence() -> ClassConfidence:
    """A confidence at the top of the range, so only the state rule can bite."""
    return ClassConfidence.from_jev(
        JevChoice(
            answer=FailureClass.CODE,
            confidence=1.0,
            probabilities={FailureClass.CODE: 1.0},
        )
    )


def low_confidence() -> ClassConfidence:
    return ClassConfidence.from_jev(
        JevChoice(
            answer=FailureClass.CODE,
            confidence=0.1,
            probabilities={FailureClass.CODE: 0.1},
        )
    )


def run(
    state: RunState,
    *,
    run_id: uuid.UUID = RUN_ID,
    repo_id: int = REPO_ID,
) -> RunRecord:
    return RunRecord(run_id=run_id, repo_id=repo_id, state=state, updated_at=NOW)


def step(
    name: str,
    output: object,
    *,
    run_id: uuid.UUID = RUN_ID,
    repo_id: int = REPO_ID,
    status: StepStatus = StepStatus.COMPLETED,
) -> StepRecord:
    return StepRecord(
        step_id=uuid.uuid4(),
        run_id=run_id,
        repo_id=repo_id,
        step=name,
        attempt=1,
        status=status,
        output=output,
        created_at=NOW,
    )


def evidence_output() -> dict[str, object]:
    """A stored evidence-pack-shaped step output, author attribution included."""
    return {
        "repo_id": "org/demo-repo",
        "last_green": FULL_SHA,
        "distilled_log": [{"line_number": 1, "text": "FAILED tests/test_x.py"}],
        "commits": [
            {
                "sha": FULL_SHA,
                "message": "fix: retry socket",
                "author_login": "someone",
            }
        ],
        "candidate_suspects": [
            {"sha": FULL_SHA, "rank": 1, "changed_files": ["tests/test_x.py"]}
        ],
        "history_rows": [],
        "metrics": {"load_duration_seconds": 12.5},
    }


def part_payload(task: Task, artifact_index: int = 0) -> Any:
    return MessageToDict(task.artifacts[artifact_index].parts[0].data)


class FakeReader:
    """A repo-scoped `TaskReader`; records every read it is asked for."""

    def __init__(
        self,
        runs: Sequence[RunRecord] = (),
        steps: Sequence[StepRecord] = (),
        *,
        confidence: ClassConfidence | None = full_confidence(),
    ) -> None:
        self._runs = list(runs)
        self._steps = list(steps)
        # Default is the top-of-range number the 2.4 tests injected; an
        # explicit None means "confidence unknown" and serves blame-free.
        self._confidence = confidence
        self.calls: list[tuple[str, int, uuid.UUID | None]] = []

    def get_run(self, repo_id: int, run_id: uuid.UUID) -> RunRecord | None:
        self.calls.append(("get_run", repo_id, run_id))
        return next(
            (
                record
                for record in self._runs
                if record.repo_id == repo_id and record.run_id == run_id
            ),
            None,
        )

    def list_steps(self, repo_id: int, run_id: uuid.UUID) -> list[StepRecord]:
        self.calls.append(("list_steps", repo_id, run_id))
        return [
            record
            for record in self._steps
            if record.repo_id == repo_id and record.run_id == run_id
        ]

    def list_runs(self, repo_id: int) -> list[RunRecord]:
        self.calls.append(("list_runs", repo_id, None))
        return [record for record in self._runs if record.repo_id == repo_id]

    def get_confidence(
        self, repo_id: int, run_id: uuid.UUID
    ) -> ClassConfidence | None:
        self.calls.append(("get_confidence", repo_id, run_id))
        return self._confidence


def store_for(reader: TaskReader) -> ReadOnlyTaskStore:
    return ReadOnlyTaskStore(reader, REPO_ID, cutoffs=FIXTURE_CUTOFFS)


class TestAc1TaskIdentityAndContent:
    def test_ac1_task_id_equals_run_id_uuid7(self) -> None:
        task = build_task(
            run(RunState.DISTILLING),
            (),
            confidence=full_confidence(),
            cutoffs=FIXTURE_CUTOFFS,
        )

        assert task.id == str(RUN_ID)
        assert task.context_id == str(RUN_ID)
        assert uuid.UUID(task.id).version == UUID_VERSION_7

    def test_ac1_status_and_artifacts_come_from_run_and_steps(self) -> None:
        steps = [step("distill", {"lines": 3}), step("classify", {"class": "code"})]

        task = build_task(
            run(RunState.DISTILLING),
            steps,
            confidence=full_confidence(),
            cutoffs=FIXTURE_CUTOFFS,
        )

        assert task.status.state == TaskState.TASK_STATE_WORKING
        assert task.status.timestamp.ToDatetime().replace(tzinfo=timezone.utc) == NOW
        assert [artifact.name for artifact in task.artifacts] == ["distill", "classify"]
        assert [artifact.artifact_id for artifact in task.artifacts] == [
            str(record.step_id) for record in steps
        ]
        assert part_payload(task, 0) == {"lines": 3}
        assert part_payload(task, 1) == {"class": "code"}
        assert task.metadata["terminal_state"] is None

    def test_ac1_completed_step_without_output_makes_no_artifact(self) -> None:
        steps = [step("distill", {"lines": 3}), step("empty", None)]

        task = build_task(
            run(RunState.DISTILLING),
            steps,
            confidence=full_confidence(),
            cutoffs=FIXTURE_CUTOFFS,
        )

        assert [artifact.name for artifact in task.artifacts] == ["distill"]

    def test_ac1_failed_step_makes_no_artifact(self) -> None:
        task = build_task(
            run(RunState.DISTILLING),
            [step("boom", {"error": "kaboom"}, status=StepStatus.FAILED)],
            confidence=full_confidence(),
            cutoffs=FIXTURE_CUTOFFS,
        )

        assert task.artifacts == []

    def test_ac1_completed_empty_dict_output_still_becomes_an_artifact(self) -> None:
        task = build_task(
            run(RunState.DISTILLING),
            [step("empty", {})],
            confidence=full_confidence(),
            cutoffs=FIXTURE_CUTOFFS,
        )

        assert [artifact.name for artifact in task.artifacts] == ["empty"]
        assert part_payload(task) == {}

    def test_ac1_sequence_output_becomes_a_data_artifact(self) -> None:
        citations = [{"kind": "commit", "sha": FULL_SHA}]

        task = build_task(
            run(RunState.DISTILLING),
            [step("citations", citations)],
            confidence=full_confidence(),
            cutoffs=FIXTURE_CUTOFFS,
        )

        assert part_payload(task) == citations

    def test_ac1_non_mapping_step_output_becomes_a_text_artifact(self) -> None:
        task = build_task(
            run(RunState.DISTILLING),
            [step("note", "plain text")],
            confidence=full_confidence(),
            cutoffs=FIXTURE_CUTOFFS,
        )

        assert task.artifacts[0].parts[0].text == "plain text"

    def test_ac1_save_and_delete_are_refused(self) -> None:
        reader = FakeReader([run(RunState.DISTILLING)])
        store = store_for(reader)
        context = ServerCallContext()
        task = build_task(
            run(RunState.DISTILLING),
            (),
            confidence=full_confidence(),
            cutoffs=FIXTURE_CUTOFFS,
        )

        with pytest.raises(ReadOnlyTaskStoreError):
            asyncio.run(store.save(task, context))
        with pytest.raises(ReadOnlyTaskStoreError):
            asyncio.run(store.delete(str(RUN_ID), context))

        assert reader.calls == [], "a refused write never reaches the reader (AD-4)"

    def test_ac1_read_only_error_is_not_retryable(self) -> None:
        assert ReadOnlyTaskStoreError.retryable is False

    def test_ac1_no_database_task_store_deployed(self) -> None:
        # The Compose/migration schema side of AD-4 lives in
        # tests/security/test_compose_secret_placement.py; here we prove the
        # serving code itself never wires the SDK's database task store.
        repo = Path(__file__).resolve().parents[2]
        offenders = [
            str(path.relative_to(repo))
            for path in (repo / "workflow").rglob("*.py")
            if "DatabaseTaskStore" in path.read_text(encoding="utf-8")
        ]

        assert offenders == [], (
            "AD-4: the SDK database task store is never referenced in workflow/"
        )


class TestAc2PauseUnknownAndIdentity:
    def test_ac2_awaiting_approval_is_input_required_with_blame_free_evidence_artifact(
        self,
    ) -> None:
        evidence = step("evidence", evidence_output())

        task = build_task(
            run(RunState.AWAITING_APPROVAL),
            [evidence],
            confidence=full_confidence(),
            cutoffs=FIXTURE_CUTOFFS,
        )

        assert task.status.state == TaskState.TASK_STATE_INPUT_REQUIRED
        assert task.metadata["terminal_state"] == "input_required"
        payload = part_payload(task)
        assert payload["commits"] == [
            {"sha": FULL_SHA, "message": "fix: retry socket"}
        ]
        assert payload["distilled_log"] == [
            {"line_number": 1, "text": "FAILED tests/test_x.py"}
        ]

    def test_ac2_unknown_task_returns_none(self) -> None:
        store = store_for(FakeReader())
        context = ServerCallContext()

        assert asyncio.run(store.get(str(RUN_ID), context)) is None
        assert asyncio.run(store.get("not-a-uuid", context)) is None

    def test_ac2_cross_repo_read_returns_none(self) -> None:
        other = run(RunState.DISTILLING, repo_id=OTHER_REPO_ID)
        reader = FakeReader([other])
        store = store_for(reader)

        assert asyncio.run(store.get(str(RUN_ID), ServerCallContext())) is None
        assert reader.calls == [("get_run", REPO_ID, RUN_ID)], (
            "the read is bound to the adapter's repo_id (AD-15)"
        )

    def test_ac2_task_identity_stable_across_calls(self) -> None:
        reader = FakeReader([run(RunState.AWAITING_APPROVAL)], [])
        store = store_for(reader)

        first = asyncio.run(store.get(str(RUN_ID), ServerCallContext()))
        second = asyncio.run(store.get(str(RUN_ID), ServerCallContext()))

        assert first is not None and second is not None
        assert first.id == second.id == str(RUN_ID)


class TestAc3ProjectionAndBlameFree:
    def test_ac3_all_ad4_state_fixtures_project_status_and_terminal_state(self) -> None:
        for state in RunState:
            task = build_task(
                run(state),
                (),
                confidence=full_confidence(),
                cutoffs=FIXTURE_CUTOFFS,
            )
            expected_name, terminal = project(state)

            assert task.status.state == int(TaskState.Value(expected_name)), state
            assert task.metadata["terminal_state"] == (
                terminal.value if terminal else None
            ), state

    @pytest.mark.parametrize(
        "state", [RunState.AWAITING_APPROVAL, RunState.REPORTING]
    )
    def test_ac3_no_author_attribution_for_awaiting_approval_or_reporting(
        self, state: RunState
    ) -> None:
        evidence = step("evidence", evidence_output())

        task = build_task(
            run(state),
            [evidence],
            confidence=full_confidence(),
            cutoffs=FIXTURE_CUTOFFS,
        )

        commits = part_payload(task)["commits"]
        assert all("author_login" not in commit for commit in commits)
        assert commits[0]["sha"] == FULL_SHA, "the evidence itself is intact"

    def test_ac3_author_attribution_preserved_when_not_blame_free(self) -> None:
        evidence = step("evidence", evidence_output())

        task = build_task(
            run(RunState.ANALYZING),
            [evidence],
            confidence=full_confidence(),
            cutoffs=FIXTURE_CUTOFFS,
        )

        assert part_payload(task)["commits"][0]["author_login"] == "someone"

    def test_ac3_below_cutoff_confidence_is_blame_free(self) -> None:
        # 4.1 AC3 owns the cutoff assertion; 2.4 reuses the shared predicate
        # rather than re-listing the rule, so the render already strips.
        evidence = step("evidence", evidence_output())

        task = build_task(
            run(RunState.ANALYZING),
            [evidence],
            confidence=low_confidence(),
            cutoffs=FIXTURE_CUTOFFS,
        )

        commits = part_payload(task)["commits"]
        assert all("author_login" not in commit for commit in commits)

    def test_ac3_store_serves_the_readers_confidence_per_run(self) -> None:
        # Story 4.1 wiring: the below-cutoff arm through the store — the
        # reader's low confidence makes an ANALYZING run blame-free.
        reader = FakeReader(
            [run(RunState.ANALYZING)],
            [step("evidence", evidence_output())],
            confidence=low_confidence(),
        )
        store = store_for(reader)

        task = asyncio.run(store.get(str(RUN_ID), ServerCallContext()))

        assert task is not None
        commits = part_payload(task)["commits"]
        assert all("author_login" not in commit for commit in commits)
        assert ("get_confidence", REPO_ID, RUN_ID) in reader.calls

    def test_ac3_unknown_confidence_is_served_blame_free(self) -> None:
        # A confidence the reader cannot supply is served blame-free: the
        # defensive default never leaks a name on missing data (AD-27).
        reader = FakeReader(
            [run(RunState.ANALYZING)],
            [step("evidence", evidence_output())],
            confidence=None,
        )
        store = store_for(reader)

        task = asyncio.run(store.get(str(RUN_ID), ServerCallContext()))

        assert task is not None
        commits = part_payload(task)["commits"]
        assert all("author_login" not in commit for commit in commits)


class TestList:
    def test_list_projects_every_run_in_the_repo(self) -> None:
        second_run_id = uuid.uuid4()
        reader = FakeReader(
            [
                run(RunState.DISTILLING),
                run(RunState.DONE_PR, run_id=second_run_id),
                run(RunState.FAILED, run_id=uuid.uuid4(), repo_id=OTHER_REPO_ID),
            ]
        )
        store = store_for(reader)

        page = asyncio.run(store.list(ListTasksRequest(), ServerCallContext()))

        assert {task.id for task in page.tasks} == {str(RUN_ID), str(second_run_id)}
