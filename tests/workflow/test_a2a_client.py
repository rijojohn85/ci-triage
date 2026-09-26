"""Story 2.8 tests for `workflow/a2a_client.py` (AC3, AD-4/AD-5).

The transport adapter is driven against an in-process fixture app (a Starlette
app speaking the same JSON-RPC surface a2a-sdk 1.1.5 serves) — no live
services. The named AC test proves `contextId = run_id`; the classification
tests prove the typed error pair the runner's budgets consume (AD-22).
"""

import json
import uuid

import httpx
import pytest
from a2a.types.a2a_pb2 import SendMessageResponse
from google.protobuf.json_format import ParseDict
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from workflow import a2a_client as a2a_client_module
from workflow.a2a_client import A2aSkillTransport
from workflow.step_runner import DefinitiveCallError, TransientCallError

RUN_ID = uuid.UUID("018f6a2c-0000-7000-8000-000000000001")
REQUEST = {"skill": "classify", "input": {"log": [1, 2, 3]}}
REPLY = {"choice": {"answer": "code"}, "injection_screen": {"noul": 0.1}}
AGENT_ERROR = {"code": "agent_failed", "message": "boom", "retryable": False}


def rpc_app(
    result: dict[str, object] | None = None,
    *,
    status_code: int = 200,
    error: dict[str, object] | None = None,
) -> tuple[Starlette, list[dict[str, object]]]:
    """A minimal JSON-RPC app matching a2a-sdk's `SendMessage` surface."""
    bodies: list[dict[str, object]] = []

    async def endpoint(request: Request) -> JSONResponse:
        body: dict[str, object] = json.loads((await request.body()).decode("utf-8"))
        bodies.append(body)
        if status_code != 200:
            return JSONResponse({"oops": True}, status_code=status_code)
        payload = (
            {"jsonrpc": "2.0", "id": body["id"], "result": result}
            if error is None
            else {"jsonrpc": "2.0", "id": body["id"], "error": error}
        )
        return JSONResponse(payload)

    app = Starlette(routes=[Route("/", endpoint, methods=["POST"])])
    return app, bodies


def asgi(app: Starlette) -> httpx.ASGITransport:
    return httpx.ASGITransport(app=app)


def success_result() -> dict[str, object]:
    return {
        "message": {
            "messageId": "reply-1",
            "contextId": str(RUN_ID),
            "parts": [{"data": REPLY}],
        }
    }


def failed_task(retryable: bool) -> dict[str, object]:
    error = {**AGENT_ERROR, "retryable": retryable}
    return {
        "task": {
            "id": "task-1",
            "contextId": str(RUN_ID),
            "status": {
                "state": "TASK_STATE_FAILED",
                "message": {
                    "messageId": "err-1",
                    "contextId": str(RUN_ID),
                    "parts": [{"data": error}],
                },
            },
        }
    }


def transport_for(app: Starlette) -> A2aSkillTransport:
    return A2aSkillTransport(
        url="http://agent.test/", run_id=RUN_ID, http_transport=asgi(app)
    )


def test_ac3_send_message_carries_context_id_run_id() -> None:
    app, bodies = rpc_app(result=success_result())

    result = transport_for(app).call(REQUEST, timeout_seconds=60.0)

    assert result.value == REPLY
    assert result.usage is None, "A2A calls carry no provider usage yet (AD-18)"
    (body,) = bodies
    assert body["method"] == "SendMessage"
    message = body["params"]["message"]
    assert message["contextId"] == str(RUN_ID), "contextId = run_id (AD-4)"
    assert message["parts"][0]["data"] == REQUEST


def test_ac3_timeout_reaches_the_sdk_call_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """The per-skill timeout value reaches `ClientCallContext` (AD-19)."""
    recorded: list[object] = []
    reply = ParseDict(success_result(), SendMessageResponse())

    class RecordingRpcTransport:
        def __init__(
            self, client: object, agent_card: object, url: str
        ) -> None:
            pass

        async def send_message(
            self, request: object, *, context: object = None
        ) -> SendMessageResponse:
            recorded.append(context)
            return reply

    monkeypatch.setattr(a2a_client_module, "JsonRpcTransport", RecordingRpcTransport)

    transport_for(app=Starlette()).call(REQUEST, timeout_seconds=60.0)

    assert len(recorded) == 1
    assert getattr(recorded[0], "timeout") == 60.0


def test_ac3_http_5xx_is_transient() -> None:
    app, _ = rpc_app(status_code=500)

    with pytest.raises(TransientCallError):
        transport_for(app).call(REQUEST, timeout_seconds=60.0)


def test_ac3_http_429_is_transient() -> None:
    app, _ = rpc_app(status_code=429)

    with pytest.raises(TransientCallError):
        transport_for(app).call(REQUEST, timeout_seconds=60.0)


def test_ac3_failed_task_with_definitive_agent_error_is_not_retryable() -> None:
    app, _ = rpc_app(result=failed_task(retryable=False))

    with pytest.raises(DefinitiveCallError):
        transport_for(app).call(REQUEST, timeout_seconds=60.0)


def test_ac3_failed_task_with_retryable_agent_error_is_transient() -> None:
    app, _ = rpc_app(result=failed_task(retryable=True))

    with pytest.raises(TransientCallError):
        transport_for(app).call(REQUEST, timeout_seconds=60.0)


def test_ac3_reply_without_data_part_is_definitive() -> None:
    app, _ = rpc_app(
        result={"message": {"messageId": "m", "contextId": str(RUN_ID), "parts": []}}
    )

    with pytest.raises(DefinitiveCallError):
        transport_for(app).call(REQUEST, timeout_seconds=60.0)


# --- AD-22 hardening: the typed pair is total over the transport's failures


@pytest.mark.parametrize("status", [408, 429, 500, 501, 504])
def test_ac3_timeout_throttle_and_server_errors_are_transient(status: int) -> None:
    app, _ = rpc_app(status_code=status)

    with pytest.raises(TransientCallError):
        transport_for(app).call(REQUEST, timeout_seconds=60.0)


def test_ac3_unexpected_transport_failure_becomes_transient() -> None:
    """Nothing escapes the runner's budgets untyped (AD-22): an unexpected
    non-SDK exception is wrapped as a transient failure."""

    class ExplodingTransport(httpx.AsyncBaseTransport):
        def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise RuntimeError("boom")

    transport = A2aSkillTransport(
        url="http://agent.test/", run_id=RUN_ID, http_transport=ExplodingTransport()
    )

    with pytest.raises(TransientCallError) as exc:
        transport.call(REQUEST, timeout_seconds=60.0)

    assert "boom" in str(exc.value)


# --- a COMPLETED task reply is a legitimate answer, not a terminal failure


def completed_task_result() -> dict[str, object]:
    return {
        "task": {
            "id": "task-1",
            "contextId": str(RUN_ID),
            "status": {
                "state": "TASK_STATE_COMPLETED",
                "message": {
                    "messageId": "reply-1",
                    "contextId": str(RUN_ID),
                    "parts": [{"data": REPLY}],
                },
            },
        }
    }


def test_ac3_completed_task_reply_is_extracted() -> None:
    app, _ = rpc_app(result=completed_task_result())

    result = transport_for(app).call(REQUEST, timeout_seconds=60.0)

    assert result.value == REPLY


def test_ac3_unexpected_task_state_is_refused_with_its_name() -> None:
    app, _ = rpc_app(
        result={
            "task": {
                "id": "task-1",
                "contextId": str(RUN_ID),
                "status": {"state": "TASK_STATE_WORKING"},
            }
        }
    )

    with pytest.raises(DefinitiveCallError) as exc:
        transport_for(app).call(REQUEST, timeout_seconds=60.0)

    assert "TASK_STATE_WORKING" in str(exc.value)
