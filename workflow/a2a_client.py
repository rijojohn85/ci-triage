"""The blocking A2A transport adapter (story 2.8, AD-4/AD-5, SOLID-S).

Thin transport only: one blocking, non-streaming JSON-RPC `SendMessage` per
call, with `contextId = run_id` on every message (AD-4) and the per-skill
`step_timeout` applied per call (AD-19). It converts what comes back into the
runner's vocabulary: a 6.1 `ModelCallResult` payload on success, or the typed
error pair (`TransientCallError` / `DefinitiveCallError`) the runner's AD-22
budget consumes — a spoke's A2A-`FAILED` task carries a typed `AgentError`
whose `retryable` flag decides the class (AD-22); a `COMPLETED` task's data
part is the reply. Every failure — including an unexpected exception — is
raised as one of the typed pair, so nothing escapes the runner's budgets
untyped (AD-22).

Caller constraints (revisited by 2.9's worker wiring): `call` is for
**synchronous callers only** — it runs the event loop with `asyncio.run`,
which raises inside a running loop — and it opens a fresh HTTP client per
call. The adapter holds no GitHub or Postgres client and no agent logic; the
runner is the only consumer (2.9 wires the real agent URLs).
"""

import asyncio
import re
import uuid

import httpx
from a2a.client.client import ClientCallContext
from a2a.client.errors import A2AClientError, A2AClientTimeoutError
from a2a.client.transports.jsonrpc import JsonRpcTransport
from a2a.types.a2a_pb2 import (
    AgentCapabilities,
    AgentCard,
    SendMessageRequest,
    SendMessageResponse,
    Task,
    TaskState,
)
from google.protobuf.json_format import MessageToDict, ParseDict

from contracts.errors import AgentError
from workflow.step_runner import DefinitiveCallError, TransientCallError
from workflow.usage_audit import ModelCallResult

__all__ = ["A2aSkillTransport"]

_HTTP_STATUS_RE = re.compile(r"HTTP Error (\d{3})")
"""a2a-sdk 1.1.5's `A2AClientError` carries no structured status, so the code
is read from its message; revisit if the SDK grows a typed HTTP error."""

_TRANSIENT_STATUSES = frozenset({408, 429, *range(500, 600)})
"""Request timeout, throttled, and every server error are transient (AD-22)."""


class A2aSkillTransport:
    """Blocking non-streaming `send_message` for one skill of one run (AC3)."""

    def __init__(
        self,
        url: str,
        run_id: uuid.UUID,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = url
        self._run_id = run_id
        self._http_transport = http_transport

    def call(
        self, request: object, *, timeout_seconds: float
    ) -> ModelCallResult[object]:
        """One blocking call; raises the runner's typed error pair on failure.

        Synchronous callers only (a fresh event loop per call, a fresh HTTP
        client per call); 2.9's worker wiring revisits both.
        """
        try:
            return asyncio.run(self._call_async(request, timeout_seconds))
        except (TransientCallError, DefinitiveCallError):
            raise
        except Exception as error:
            # AD-22: nothing escapes the runner's budgets untyped — an
            # unexpected failure is treated as transient (the budget bounds
            # it, then the run fails terminally).
            raise TransientCallError(
                f"unexpected transport failure: {error}"
            ) from error

    async def _call_async(
        self, request: object, timeout_seconds: float
    ) -> ModelCallResult[object]:
        async with httpx.AsyncClient(transport=self._http_transport) as client:
            rpc = JsonRpcTransport(client, _agent_card(), self._url)
            try:
                response = await rpc.send_message(
                    self._build_request(request),
                    context=ClientCallContext(timeout=timeout_seconds),
                )
            except A2AClientTimeoutError as error:
                raise TransientCallError(f"step_timeout: {error}") from error
            except A2AClientError as error:
                raise _classify_http_error(error) from error
        # TODO(2.9): read the usage agents report (3.2/3.4 reply shape) — AD-18.
        return ModelCallResult(value=_reply(response), usage=None)

    def _build_request(self, request: object) -> SendMessageRequest:
        message: dict[str, object] = {
            "messageId": uuid.uuid4().hex,
            "contextId": str(self._run_id),
            "parts": [{"data": request}],
        }
        return ParseDict({"message": message}, SendMessageRequest())


def _agent_card() -> AgentCard:
    """The minimal client-side card: non-streaming (AD-5)."""
    return AgentCard(
        name="triage-spoke",
        version="0.1.0",
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
    )


def _classify_http_error(error: A2AClientError) -> Exception:
    """Map the SDK's translated HTTP errors onto the typed pair (AD-22).

    408 (request timeout), 429 and any 5xx are transient; everything else is
    definitive. The status is read from the SDK's message because 1.1.5's
    error type carries no structured code.
    """
    message = str(error)
    status = _HTTP_STATUS_RE.search(message)
    if status is not None and int(status.group(1)) in _TRANSIENT_STATUSES:
        return TransientCallError(message)
    if "Network communication error" in message:
        return TransientCallError(message)
    return DefinitiveCallError(message)


def _reply(response: SendMessageResponse) -> object:
    """Extract the reply payload, or raise the typed pair on a failed task."""
    if response.HasField("task"):
        return _task_reply(response)
    return _message_reply(response)


def _task_reply(response: SendMessageResponse) -> object:
    status = response.task.status
    if status.state == TaskState.TASK_STATE_COMPLETED:
        return _completed_task_reply(response.task)
    if status.state == TaskState.TASK_STATE_FAILED:
        error = AgentError.model_validate(_data_part(status.message))
        if error.retryable:
            raise TransientCallError(f"{error.code}: {error.message}")
        raise DefinitiveCallError(f"{error.code}: {error.message}")
    raise DefinitiveCallError(f"unexpected task state {TaskState.Name(status.state)}")


def _completed_task_reply(task: Task) -> object:
    """A completed task's reply: its status message, else its artifacts."""
    if task.status.HasField("message"):
        return _data_part(task.status.message)
    for artifact in task.artifacts:
        for part in artifact.parts:
            if part.WhichOneof("content") == "data":
                return dict(MessageToDict(part.data))
    raise DefinitiveCallError("the completed task carries no data part")


def _message_reply(response: SendMessageResponse) -> object:
    if not response.HasField("message"):
        raise DefinitiveCallError("the reply carries neither a message nor a task")
    return _data_part(response.message)


def _data_part(message: object) -> dict[str, object]:
    """The first data part of an A2A message, as a plain JSON object."""
    for part in message.parts:  # type: ignore[attr-defined]
        if part.WhichOneof("content") == "data":
            return dict(MessageToDict(part.data))
    raise DefinitiveCallError("the message carries no data part")
