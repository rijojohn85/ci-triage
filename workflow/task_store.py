"""The read-only A2A task view: a one-way projection of `triage_run`/`run_step`.

AD-4: the orchestrator's A2A task state is never stored twice. `triage_run` is
the sole owner; this module *reads* a run and its steps and projects them onto
an A2A protobuf `Task`, with `task_id` = `run_id` (UUIDv7). The SDK's own
database-backed task store is deliberately not used, so no second task-state
writer can exist (SOLID-L): `save` and `delete` are refused outright.

SOLID-S: the domain decision lives here; the SQL that feeds it lives in a
separate adapter behind the small `TaskReader` protocol (SOLID-I/D). 2.1's
`project()` owns the state/terminal-state mapping and 2.2's
`attribution_allowed()` owns the AD-27 blame-free rule — neither is re-listed
here. Artifacts are read straight from completed `run_step` outputs; this
story does not build or mutate an evidence pack (2.7 owns producing it).
The AD-27 author-key walk lives once in `guardrails.attribution` (story 4.1).
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from a2a.helpers.proto_helpers import new_data_artifact, new_text_artifact
from a2a.server.context import ServerCallContext
from a2a.server.tasks import TaskStore
from a2a.types.a2a_pb2 import (
    Artifact,
    ListTasksRequest,
    ListTasksResponse,
    Task,
    TaskStatus,
)

from guardrails.attribution import strip_author_attribution
from guardrails.confidence import ClassConfidence, ConfidenceCutoffs
from workflow.attribution import attribution_allowed
from workflow.projection import project
from workflow.run_states import RunState
from workflow.steps import StepRecord, StepStatus

__all__ = [
    "ReadOnlyTaskStore",
    "ReadOnlyTaskStoreError",
    "RunRecord",
    "TaskReader",
    "build_task",
]

# JSON data outputs (objects and arrays) go into a data artifact; anything
# else (text, numbers) is served as text.
_DATA_OUTPUT_TYPES = (Mapping, list, tuple)


@dataclass(frozen=True)
class RunRecord:
    """A stored `triage_run` read for projection (AD-1, AD-4).

    Pure read shape: the run's identity, its tenant scope, its state and when
    it last moved. The run's `confidence` is not here: the reader supplies it
    per run (`TaskReader.get_confidence`), and an unreadable confidence is
    served blame-free (AD-27 defensive default).
    """

    run_id: uuid.UUID
    repo_id: int
    state: RunState
    updated_at: datetime


class TaskReader(Protocol):
    """The read-only store access a `ReadOnlyTaskStore` needs (SOLID-I).

    Every method is bound to `repo_id`, so one repo can never read another's
    run (AD-15). There is no write method: the projection cannot persist.
    """

    def get_run(self, repo_id: int, run_id: uuid.UUID) -> RunRecord | None: ...

    def list_steps(self, repo_id: int, run_id: uuid.UUID) -> Sequence[StepRecord]: ...

    def list_runs(self, repo_id: int) -> Sequence[RunRecord]: ...

    def get_confidence(
        self, repo_id: int, run_id: uuid.UUID
    ) -> ClassConfidence | None: ...


class ReadOnlyTaskStoreError(Exception):
    """A write was attempted against the read-only task view (AD-4).

    Definitive, never retryable (AD-22): there is no task state to write —
    `triage_run` is the only owner.
    """

    retryable: bool = False


def build_task(
    run: RunRecord,
    steps: Sequence[StepRecord],
    *,
    confidence: ClassConfidence | None,
    cutoffs: ConfidenceCutoffs,
) -> Task:
    """Project one stored run and its steps into an A2A `Task` (AD-4).

    One function serves both `get` and `list` (DRY). Status and terminal state
    come from 2.1's mapping; blame is stripped using 2.2's predicate, so
    `AWAITING_APPROVAL`/`REPORTING` (and a below-cutoff run) carry no author.
    An unknown/absent confidence is served blame-free (AD-27 defensive
    default): without a number, no name is leaked.
    """
    task_state_name, terminal_state = project(run.state)
    blame_free = confidence is None or not attribution_allowed(
        run.state, confidence, cutoffs
    )
    return Task(
        id=str(run.run_id),
        context_id=str(run.run_id),
        status=TaskStatus(state=task_state_name, timestamp=run.updated_at),
        metadata={
            "terminal_state": terminal_state.value if terminal_state else None,
        },
        artifacts=[
            _artifact(record, blame_free=blame_free)
            for record in steps
            if record.status is StepStatus.COMPLETED and record.output is not None
        ],
    )


def _artifact(record: StepRecord, *, blame_free: bool) -> Artifact:
    output = strip_author_attribution(record.output) if blame_free else record.output
    artifact_id = str(record.step_id)
    if isinstance(output, _DATA_OUTPUT_TYPES):
        return new_data_artifact(record.step, output, artifact_id=artifact_id)
    return new_text_artifact(record.step, str(output), artifact_id=artifact_id)


def _as_run_id(task_id: str) -> uuid.UUID | None:
    """An A2A task id must be a run id; anything else is simply not found."""
    try:
        return uuid.UUID(task_id)
    except ValueError:
        return None


class ReadOnlyTaskStore(TaskStore):
    """The SDK `TaskStore` the orchestrator serves, backed by reads only (AD-4).

    `get` and `list` project stored runs; `save` and `delete` raise, so this
    view can never become a second task-state owner. The thresholds are
    injected (SOLID-D); each run's serving confidence comes from the reader
    (story 4.1), so a below-cutoff run is served blame-free.
    """

    def __init__(
        self,
        reader: TaskReader,
        repo_id: int,
        *,
        cutoffs: ConfidenceCutoffs,
    ) -> None:
        self._reader = reader
        self._repo_id = repo_id
        self._cutoffs = cutoffs

    async def get(self, task_id: str, _context: ServerCallContext) -> Task | None:
        run_id = _as_run_id(task_id)
        if run_id is None:
            return None
        run = self._reader.get_run(self._repo_id, run_id)
        if run is None:
            return None
        return self._project(run, self._reader.list_steps(self._repo_id, run.run_id))

    async def list(
        self, _params: ListTasksRequest, _context: ServerCallContext
    ) -> ListTasksResponse:
        tasks = [
            self._project(run, self._reader.list_steps(self._repo_id, run.run_id))
            for run in self._reader.list_runs(self._repo_id)
        ]
        return ListTasksResponse(tasks=tasks)

    async def save(self, task: Task, _context: ServerCallContext) -> None:
        raise ReadOnlyTaskStoreError(
            f"refused save for task {task.id}: the task view is read-only (AD-4)"
        )

    async def delete(self, task_id: str, _context: ServerCallContext) -> None:
        raise ReadOnlyTaskStoreError(
            f"refused delete for task {task_id}: the task view is read-only (AD-4)"
        )

    def _project(self, run: RunRecord, steps: Sequence[StepRecord]) -> Task:
        return build_task(
            run,
            steps,
            confidence=self._reader.get_confidence(self._repo_id, run.run_id),
            cutoffs=self._cutoffs,
        )
