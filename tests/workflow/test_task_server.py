"""Story 2.4 server tests — the JSON-RPC `get_task`/`list_tasks` route (AC1/AC2).

The A2A app is driven in-process over an ASGI transport (httpx), the same way
a client would call it: no network, no worker. The tests prove the route
returns the read-through projection, an unknown id is a JSON-RPC not-found
error, `list_tasks` is repo-scoped, and a read never schedules any executor
work (AD-4). The 1.0 protocol header is required by a2a-sdk 1.1.5's version
guard.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest
from a2a.server.agent_execution import RequestContext
from a2a.server.context import ServerCallContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.types.a2a_pb2 import AgentCard, GetTaskRequest
from a2a.utils.errors import UnsupportedOperationError
from starlette.applications import Starlette

from contracts.enums import FailureClass
from contracts.jev import JevChoice
from guardrails.confidence import ClassConfidence
from tests.contracts.samples import FULL_SHA, RUN_ID
from tests.fixtures.thresholds import FIXTURE_CUTOFFS
from workflow import a2a_server
from workflow.a2a_server import RefusingExecutor, create_app
from workflow.run_states import RunState
from workflow.steps import StepRecord, StepStatus
from workflow.task_store import ReadOnlyTaskStore, RunRecord

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
REPO_ID = 7
VERSION_HEADERS = {"A2A-Version": "1.0"}
HTTP_OK = 200
NOT_FOUND_CODE = -32001
UNSUPPORTED_OPERATION_CODE = -32004


def full_confidence() -> ClassConfidence:
    return ClassConfidence.from_jev(
        JevChoice(
            answer=FailureClass.CODE,
            confidence=1.0,
            probabilities={FailureClass.CODE: 1.0},
        )
    )


class RecordingReader:
    """A minimal repo-scoped reader that records every call."""

    def __init__(self, runs: list[RunRecord], steps: list[StepRecord]) -> None:
        self._runs = runs
        self._steps = steps
        self.calls: list[str] = []

    def get_run(self, repo_id: int, run_id: uuid.UUID) -> RunRecord | None:
        self.calls.append("get_run")
        return next(
            (
                record
                for record in self._runs
                if record.repo_id == repo_id and record.run_id == run_id
            ),
            None,
        )

    def list_steps(self, repo_id: int, run_id: uuid.UUID) -> list[StepRecord]:
        self.calls.append("list_steps")
        return [
            record
            for record in self._steps
            if record.repo_id == repo_id and record.run_id == run_id
        ]

    def list_runs(self, repo_id: int) -> list[RunRecord]:
        self.calls.append("list_runs")
        return [record for record in self._runs if record.repo_id == repo_id]


class RecordingExecutor(RefusingExecutor):
    """A refusing executor that also counts any attempt to run work."""

    def __init__(self) -> None:
        self.executions = 0

    async def execute(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        self.executions += 1
        await super().execute(context, event_queue)


def evidence_step() -> StepRecord:
    return StepRecord(
        step_id=uuid.uuid4(),
        run_id=RUN_ID,
        repo_id=REPO_ID,
        step="evidence",
        attempt=1,
        status=StepStatus.COMPLETED,
        output={
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
            "candidate_suspects": [],
            "history_rows": [],
            "metrics": {},
        },
        created_at=NOW,
    )


def awaiting_run() -> RunRecord:
    return RunRecord(
        run_id=RUN_ID,
        repo_id=REPO_ID,
        state=RunState.AWAITING_APPROVAL,
        updated_at=NOW,
    )


def handler_with(
    reader: RecordingReader, executor: RecordingExecutor
) -> DefaultRequestHandler:
    store = ReadOnlyTaskStore(
        reader,
        REPO_ID,
        confidence=full_confidence(),
        cutoffs=FIXTURE_CUTOFFS,
    )
    return DefaultRequestHandler(
        agent_executor=executor,
        task_store=store,
        agent_card=AgentCard(name="triage-orchestrator", version="0.1.0"),
    )


def app_with(reader: RecordingReader, executor: RecordingExecutor) -> Starlette:
    return Starlette(
        routes=create_jsonrpc_routes(handler_with(reader, executor), "/")
    )


async def post(app: Any, body: dict[str, object]) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://triage.test"
    ) as client:
        return await client.post("/", json=body, headers=VERSION_HEADERS)


def test_get_task_over_jsonrpc_returns_projected_task() -> None:
    reader = RecordingReader([awaiting_run()], [evidence_step()])
    app = create_app(reader, REPO_ID)

    response = asyncio.run(
        post(
            app,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "GetTask",
                "params": {"id": str(RUN_ID)},
            },
        )
    )

    assert response.status_code == HTTP_OK
    result = response.json()["result"]
    assert result["id"] == str(RUN_ID)
    assert result["contextId"] == str(RUN_ID)
    assert result["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
    assert result["metadata"]["terminal_state"] == "input_required"
    assert result["artifacts"][0]["name"] == "evidence"
    commits = result["artifacts"][0]["parts"][0]["data"]["commits"]
    assert all("author_login" not in commit for commit in commits), (
        "a paused task is blame-free (AD-27)"
    )


def test_get_task_unknown_over_jsonrpc_is_not_found() -> None:
    app = create_app(RecordingReader([], []), REPO_ID)

    response = asyncio.run(
        post(
            app,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "GetTask",
                "params": {"id": str(uuid.uuid4())},
            },
        )
    )

    body = response.json()
    assert response.status_code == HTTP_OK
    assert body["error"]["code"] == NOT_FOUND_CODE
    assert body["error"]["message"] == "Task not found"
    assert "result" not in body


def test_list_tasks_over_jsonrpc_returns_only_the_repo_runs() -> None:
    missing_run = RUN_ID
    other_run = uuid.uuid4()
    reader = RecordingReader(
        [
            RunRecord(
                run_id=missing_run,
                repo_id=REPO_ID,
                state=RunState.DONE_PR,
                updated_at=NOW,
            ),
            RunRecord(
                run_id=other_run,
                repo_id=99,
                state=RunState.DONE_PR,
                updated_at=NOW,
            ),
        ],
        [],
    )
    app = create_app(reader, REPO_ID)

    response = asyncio.run(
        post(app, {"jsonrpc": "2.0", "id": 3, "method": "ListTasks", "params": {}})
    )

    result = response.json()["result"]
    assert [task["id"] for task in result["tasks"]] == [str(missing_run)]


def test_ac2_get_task_writes_nothing_and_schedules_nothing() -> None:
    reader = RecordingReader([awaiting_run()], [evidence_step()])
    executor = RecordingExecutor()
    handler = handler_with(reader, executor)

    task = asyncio.run(
        handler.on_get_task(GetTaskRequest(id=str(RUN_ID)), ServerCallContext())
    )

    assert task is not None
    assert executor.executions == 0, "a read never schedules a worker (AD-4)"
    assert set(reader.calls) <= {"get_run", "list_steps"}, (
        "the read path only reads triage_run/run_step"
    )


def test_ac2_write_methods_are_refused_over_the_wire() -> None:
    reader = RecordingReader([awaiting_run()], [evidence_step()])
    executor = RecordingExecutor()
    app = app_with(reader, executor)

    response = asyncio.run(
        post(
            app,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "CancelTask",
                "params": {"id": str(RUN_ID)},
            },
        )
    )

    body = response.json()
    assert response.status_code == HTTP_OK
    assert body["error"]["code"] == UNSUPPORTED_OPERATION_CODE
    assert "result" not in body
    assert executor.executions == 0, "a refused write never runs agent work"


def test_refusing_executor_refuses_work() -> None:
    executor = RefusingExecutor()

    with pytest.raises(UnsupportedOperationError):
        asyncio.run(executor.execute(None, None))  # type: ignore[arg-type]
    with pytest.raises(UnsupportedOperationError):
        asyncio.run(executor.cancel(None, None))  # type: ignore[arg-type]


def test_ac3_below_cutoff_blame_free_arm_is_a_tracked_placeholder_until_4_1() -> None:
    # 2.4 cannot read a run's stored confidence yet, so `create_app` serves a
    # confidence that is never below the cutoff and the below-cutoff arm of the
    # AD-27 rule is NOT enforced on this endpoint. Story 4.1 must replace
    # `_SERVING_CONFIDENCE` with the run's real confidence and delete this
    # guard. If this test fails, the serving confidence changed: close the 2.4
    # deferral and update story 4.1 with it.
    assert a2a_server._SERVING_CONFIDENCE.confidence_jev == 1.0
    assert not a2a_server._SERVING_CONFIDENCE.confidence_jev < min(
        FIXTURE_CUTOFFS.no_route_cutoff, FIXTURE_CUTOFFS.class_cutoff
    ), "the placeholder is deliberately above every cutoff"
