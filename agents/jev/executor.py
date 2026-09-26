"""Transport only (SOLID-S): EvidencePack in → JevResult out; AgentError → FAILED.

The executor scans the request's data parts for a `DataPart` wrapping an
`EvidencePack` and refuses anything else (a JSON-RPC invalid-request error,
no provider call), runs the injected classify step, and answers with one
terminal `TaskStatusUpdateEvent` whose status message carries the reply —
a `DataPart` envelope wrapping `JevResult` on COMPLETED or the typed
`AgentError` on FAILED (AD-6, AD-22). Every failure is typed: a catch-all
maps unexpected step failures through the AD-22 split, so the task never
stays WORKING. It holds no GitHub token and no DB client (layer contract).
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types.a2a_pb2 import (
    Message,
    Task,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from a2a.utils.errors import InvalidParamsError, UnsupportedOperationError
from google.protobuf.json_format import MessageToDict, ParseDict
from pydantic import UUID7, TypeAdapter, ValidationError

from agents.jev.classifier import ClassifyError, agent_error
from contracts.a2a import DataPart
from contracts.errors import AgentError
from contracts.evidence import EvidencePack
from contracts.jev import JevResult

__all__ = ["ClassifyStep", "JevExecutor"]

ClassifyStep = Callable[[EvidencePack], Awaitable[JevResult]]
"""The bound classify step; the executor is transport only (SOLID-D)."""

_UUID7: Any = TypeAdapter(UUID7)
"""The run-id convention root: contextId must be a UUIDv7 (AD-4)."""


def _evidence_pack(context: RequestContext, run_id: UUID) -> EvidencePack:
    """The first data part that wraps an EvidencePack; refused otherwise.

    Parts that do not carry a valid `DataPart` envelope are skipped, not
    fatal — the pack may arrive in a later part of the same message. The
    envelope's `context_id` must equal the request's contextId (the run id,
    AD-4): an envelope/run mismatch is refused before any provider call.
    """
    message = context.message
    if message is None:
        raise InvalidParamsError(message="the request carries no message")
    saw_data_part = False
    for part in message.parts:
        if part.WhichOneof("content") != "data":
            continue
        saw_data_part = True
        try:
            data_part = DataPart.model_validate(MessageToDict(part.data))
        except ValidationError:
            continue
        if isinstance(data_part.payload, EvidencePack):
            if data_part.context_id != run_id:
                raise InvalidParamsError(
                    message=(
                        "the DataPart envelope's context_id does not match "
                        "the request contextId (AD-4)"
                    )
                )
            return data_part.payload
    if not saw_data_part:
        raise InvalidParamsError(message="the message carries no data part")
    raise InvalidParamsError(
        message="classify-failure expects a DataPart wrapping an EvidencePack"
    )


def _request_ids(context: RequestContext) -> tuple[str, UUID]:
    """The A2A ids: both required, and contextId must be the UUIDv7 run id."""
    task_id = context.task_id or ""
    context_id = context.context_id or ""
    if not task_id or not context_id:
        raise InvalidParamsError(message="the request carries no task/context id")
    try:
        _UUID7.validate_python(context_id)
    except ValidationError as error:
        raise InvalidParamsError(
            message="contextId is not a UUIDv7 run id (AD-4)"
        ) from error
    return task_id, UUID(context_id)


class JevExecutor(AgentExecutor):
    """One blocking, non-streaming classify per `message/send` (AD-5)."""

    def __init__(self, classify: ClassifyStep) -> None:
        self._classify = classify

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id, run_id = _request_ids(context)
        pack = _evidence_pack(context, run_id)
        await event_queue.enqueue_event(
            Task(
                id=task_id,
                context_id=str(run_id),
                status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
            )
        )
        try:
            result = await self._classify(pack)
        except ClassifyError as error:
            payload: JevResult | AgentError = error.error
            state = TaskState.TASK_STATE_FAILED
        except Exception as error:
            payload, state = agent_error(error), TaskState.TASK_STATE_FAILED
        else:
            payload, state = result, TaskState.TASK_STATE_COMPLETED
        await self._finish(task_id, run_id, event_queue, state, payload)

    async def cancel(self, _context: RequestContext, _event_queue: EventQueue) -> None:
        raise UnsupportedOperationError(
            message="classify-failure is a blocking non-streaming call (AD-5)"
        )

    async def _finish(
        self,
        task_id: str,
        run_id: UUID,
        event_queue: EventQueue,
        state: TaskState,
        payload: JevResult | AgentError,
    ) -> None:
        """One terminal event whose status message carries the reply envelope.

        The reply data part is a `DataPart` envelope, like every inter-agent
        data part (AD-6); its ids are the run id (task_id = context_id, AD-4).
        """
        envelope = DataPart(task_id=run_id, context_id=run_id, payload=payload)
        message = ParseDict(
            {
                "messageId": uuid.uuid4().hex,
                "taskId": task_id,
                "contextId": str(run_id),
                "role": "ROLE_AGENT",
                "parts": [{"data": envelope.model_dump(mode="json")}],
            },
            Message(),
        )
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=str(run_id),
                status=TaskStatus(state=state, message=message),
            )
        )
