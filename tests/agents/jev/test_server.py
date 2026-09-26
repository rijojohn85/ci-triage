"""AC2/AC3: the Jev agent over the JSON-RPC app, with a fake provider.

The A2A app is driven in-process over an ASGI transport (httpx), the same
way the orchestrator's 2.8 client would call it: no network, no real model.
The card declares exactly the one catalogue skill; valid and error replies
match the committed generated schemas (AD-6); a malformed request is a
JSON-RPC invalid-request error with no provider call.
"""

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import httpx
import httpx2
from jsonschema import validate as schema_validate
from typesafe_sdk import TypeSafeRateLimitError

from agents import jev as jev_package
from agents.jev.classifier import classify
from agents.jev.server import create_app
from contracts.evidence import EvidencePack
from contracts.jev import JevResult
from tests.agents.jev.test_classifier import (
    POSITIVE_NOUL,
    REPORTED_INPUT_TOKENS,
    RUNTIME,
    FakeProvider,
    evidence_pack,
    fixture_response,
)
from tests.contracts.samples import RUN_ID


def _load_schema(name: str) -> Any:
    return json.loads(
        (
            Path(__file__).resolve().parents[3] / "guardrails" / "schemas" / name
        ).read_text(encoding="utf-8")
    )


SCHEMA: Any = _load_schema("JevResult.json")
AGENT_ERROR_SCHEMA: Any = _load_schema("AgentError.json")
VERSION_HEADERS = {"A2A-Version": "1.0"}
HTTP_OK = 200
INVALID_PARAMS_CODE = -32602


def app_with(provider: FakeProvider) -> Any:
    async def classify_fn(pack: EvidencePack) -> JevResult:
        return await classify(pack, provider, RUNTIME)

    return create_app(classify_fn)


async def _post(app: Any, body: dict[str, object]) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://jev.test"
    ) as client:
        return await client.post("/", json=body, headers=VERSION_HEADERS)


def post(app: Any, body: dict[str, object]) -> httpx.Response:
    return asyncio.run(_post(app, body))


def send_message(payload: object) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": uuid.uuid4().hex,
                "role": "ROLE_USER",
                "contextId": str(RUN_ID),
                "parts": [{"data": payload}],
            }
        },
    }


def data_part(payload: object) -> dict[str, object]:
    return {"task_id": str(RUN_ID), "context_id": str(RUN_ID), "payload": payload}


def reply_task(response: httpx.Response) -> dict[str, Any]:
    """The reply task of a blocking `SendMessage` result."""
    result: dict[str, Any] = response.json()["result"]
    task: dict[str, Any] = result["task"]
    return task


def reply_data(response: httpx.Response) -> dict[str, Any]:
    """The reply payload: the DataPart envelope's payload (AD-6)."""
    status: dict[str, Any] = reply_task(response)["status"]
    message: dict[str, Any] = status["message"]
    parts: list[dict[str, Any]] = message["parts"]
    envelope = next(part["data"] for part in parts if "data" in part)
    assert envelope["task_id"] == str(RUN_ID), "reply ids are the run id (AD-4)"
    assert envelope["context_id"] == str(RUN_ID)
    payload: dict[str, Any] = envelope["payload"]
    return payload


def test_ac2_card_declares_classify_failure() -> None:
    app = app_with(FakeProvider(fixture_response()))

    transport = httpx.ASGITransport(app=app)

    async def get_card() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://jev.test"
        ) as client:
            return await client.get(
                "/.well-known/agent-card.json", headers=VERSION_HEADERS
            )

    response = asyncio.run(get_card())

    assert response.status_code == HTTP_OK
    card = response.json()
    assert len(card["skills"]) == 1, "exactly the one catalogue skill"
    assert card["skills"][0]["id"] == "classify-failure"
    assert card["capabilities"].get("streaming") is False, "non-streaming (AD-5)"


def test_ac3_valid_response_matches_generated_schema() -> None:
    provider = FakeProvider(fixture_response())
    response = post(
        app_with(provider),
        send_message(data_part(evidence_pack().model_dump(mode="json"))),
    )

    result = reply_task(response)
    assert result["status"]["state"] == "TASK_STATE_COMPLETED"
    data = reply_data(response)
    schema_validate(data, SCHEMA)
    served = JevResult.model_validate(data)
    assert served.classification.choice.answer.value == "flaky"
    assert served.usage.input_tokens == REPORTED_INPUT_TOKENS
    assert len(provider.calls) == 1, "one provider call per classify request"


def test_ac2_error_response_carries_agent_error() -> None:
    provider = FakeProvider(error=TypeSafeRateLimitError(429, {}, httpx2.Headers()))
    response = post(
        app_with(provider),
        send_message(data_part(evidence_pack().model_dump(mode="json"))),
    )

    result = reply_task(response)
    assert result["status"]["state"] == "TASK_STATE_FAILED"
    error = reply_data(response)
    schema_validate(error, AGENT_ERROR_SCHEMA)
    assert error["code"] == "TypeSafeRateLimitError", (
        "the error payload matches the generated schema (AC3, AD-6)"
    )
    assert error["retryable"] is True


def test_ac2_malformed_request_is_invalid_request_without_provider_call() -> None:
    provider = FakeProvider(fixture_response())
    response = post(app_with(provider), send_message(data_part({"nope": True})))

    body = response.json()
    assert body["error"]["code"] == INVALID_PARAMS_CODE
    assert provider.calls == [], "a malformed request never reaches the provider"


def test_ac2_missing_data_part_is_invalid_request() -> None:
    provider = FakeProvider(fixture_response())
    response = post(app_with(provider), send_message("just text, no data part"))

    body = response.json()
    assert body["error"]["code"] == INVALID_PARAMS_CODE
    assert provider.calls == []


def test_ac2_positive_screen_does_not_block_over_the_wire() -> None:
    provider = FakeProvider(fixture_response(noul=0.95))
    response = post(
        app_with(provider),
        send_message(data_part(evidence_pack().model_dump(mode="json"))),
    )

    result = reply_task(response)
    assert result["status"]["state"] == "TASK_STATE_COMPLETED", (
        "a positive screen never blocks on its own (AD-11)"
    )
    served = reply_data(response)["classification"]["injection_screen"]
    assert served["noul"] == POSITIVE_NOUL


def test_ac2_agent_holds_no_github_token_or_db_client() -> None:
    """The layer contract as a test: no GitHub/Postgres clients in agents/jev."""
    for source in Path(jev_package.__path__[0]).glob("*.py"):
        code = source.read_text(encoding="utf-8")
        assert "psycopg" not in code, source.name
        assert "DATABASE_URL" not in code, source.name
        assert "GITHUB_TOKEN" not in code, source.name
        assert "github.com" not in code, source.name


# --- review hardening: typed catch-all, id refusal, later-part pack


def app_with_boom() -> Any:
    async def boom(_pack: EvidencePack) -> JevResult:
        raise RuntimeError("boom")

    return create_app(boom)


def test_ac2_unexpected_step_failure_is_a_typed_failed_task() -> None:
    """Nothing escapes untyped (AD-22): a non-ClassifyError step failure
    still ends as a FAILED task carrying an AgentError."""
    response = post(
        app_with_boom(),
        send_message(data_part(evidence_pack().model_dump(mode="json"))),
    )

    result = reply_task(response)
    assert result["status"]["state"] == "TASK_STATE_FAILED"
    error = reply_data(response)
    schema_validate(error, AGENT_ERROR_SCHEMA)
    assert error["code"] == "RuntimeError"
    assert error["retryable"] is True, "an unexpected failure is transient (AD-22)"


def test_ac2_missing_context_id_is_invalid_request() -> None:
    provider = FakeProvider(fixture_response())
    body: dict[str, object] = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": uuid.uuid4().hex,
                "role": "ROLE_USER",
                "parts": [{"data": data_part(evidence_pack().model_dump(mode="json"))}],
            }
        },
    }
    response = post(app_with(provider), body)

    body_json = response.json()
    assert body_json["error"]["code"] == INVALID_PARAMS_CODE
    assert provider.calls == [], "a request without ids never reaches the provider"


def test_ac2_pack_in_a_later_data_part_is_accepted() -> None:
    provider = FakeProvider(fixture_response())
    message = send_message(data_part(evidence_pack().model_dump(mode="json")))
    params: dict[str, Any] = message["params"]
    msg: dict[str, Any] = params["message"]
    parts: list[dict[str, Any]] = msg["parts"]
    parts.insert(0, {"data": "not the pack"})
    response = post(app_with(provider), message)

    result = reply_task(response)
    assert result["status"]["state"] == "TASK_STATE_COMPLETED", (
        "the executor scans later data parts before refusing"
    )
    assert len(provider.calls) == 1
