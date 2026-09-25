"""Shared fixtures for the gateway intake tests (story 1.1).

Everything here is deterministic and I/O-free: the app receives a Protocol
fake store and an injected clock, so signature, event, identity and limit
decisions are asserted as pure behaviour. The real Postgres adapter is
exercised only by `test_gateway_store_integration.py` (marked integration).

Helpers and the fake live in `gateway_fakes.py` so test modules can import
them directly without importing this plugin twice.
"""

import json
from collections.abc import Callable, Iterator

import httpx
import pytest
from starlette.testclient import TestClient

from gateway.app import create_app
from gateway.settings import GatewayLimits, GatewaySettings

from tests.security.gateway_fakes import (
    DELIVERY_HEADER,
    EVENT_HEADER,
    INSTALLATION_ID,
    ROTATED_WEBHOOK_SECRET,
    SIGNATURE_HEADER,
    TEST_WEBHOOK_SECRET,
    FakeIntakeStore,
    FrozenClock,
    issue_comment_payload,
    sign,
    workflow_run_payload,
)


@pytest.fixture()
def clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture()
def fake_store() -> FakeIntakeStore:
    return FakeIntakeStore()


@pytest.fixture()
def settings() -> GatewaySettings:
    return GatewaySettings(
        webhook_secrets=(TEST_WEBHOOK_SECRET,),
        allowed_installation_ids=frozenset({INSTALLATION_ID}),
        database_url="postgresql://unused",
    )


@pytest.fixture()
def limits() -> GatewayLimits:
    return GatewayLimits(
        rate_limit_per_installation=5,
        rate_limit_window_seconds=60,
        max_queue_depth_per_repo=3,
        max_body_bytes=4096,
    )


@pytest.fixture()
def client(
    settings: GatewaySettings,
    fake_store: FakeIntakeStore,
    limits: GatewayLimits,
    clock: FrozenClock,
) -> Iterator[TestClient]:
    app = create_app(settings, fake_store, limits, clock=clock)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def post(client: TestClient) -> Callable[..., httpx.Response]:
    def _post(
        payload: object,
        *,
        signing_secret: str = TEST_WEBHOOK_SECRET,
        event: str = "workflow_run",
        delivery: str = "delivery-0001",
        signature: str | None = "auto",
    ) -> httpx.Response:
        body = (
            payload
            if isinstance(payload, bytes)
            else json.dumps(payload).encode("utf-8")
        )
        headers = {EVENT_HEADER: event, DELIVERY_HEADER: delivery}
        if signature == "auto":
            headers[SIGNATURE_HEADER] = sign(body, signing_secret)
        elif signature is not None:
            headers[SIGNATURE_HEADER] = signature
        return client.post("/webhook", content=body, headers=headers)

    return _post


@pytest.fixture()
def workflow_run_event() -> Callable[..., dict[str, object]]:
    return workflow_run_payload


@pytest.fixture()
def issue_comment_event() -> Callable[..., dict[str, object]]:
    return issue_comment_payload


@pytest.fixture()
def webhook_secret() -> str:
    return TEST_WEBHOOK_SECRET


@pytest.fixture()
def rotated_secret() -> str:
    return ROTATED_WEBHOOK_SECRET


@pytest.fixture()
def sign_body() -> Callable[[bytes, str], str]:
    return sign
