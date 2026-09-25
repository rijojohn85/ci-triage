"""Story 1.1 AC1 / story 1.3 AC2: signature verification and secret rotation.

The fakes and clock come from `tests/security/gateway_fakes.py`; no live GitHub.
"""

import json
from collections.abc import Callable

import httpx
from starlette.testclient import TestClient

from gateway.app import create_app
from gateway.settings import GatewayLimits, GatewaySettings
from gateway.signature import SIGNATURE_HEADER, verify_signature
from gateway.store import IntakeOutcome
from tests.security.gateway_fakes import (
    DELIVERY_HEADER,
    EVENT_HEADER,
    INSTALLATION_ID,
    ROTATED_WEBHOOK_SECRET,
    TEST_WEBHOOK_SECRET,
    FakeIntakeStore,
    FrozenClock,
    sign,
    workflow_run_payload,
)


class TestSignatureBeforeParse:
    def test_ac1_missing_signature_returns_401(
        self,
        post: Callable[..., httpx.Response],
        workflow_run_event: Callable[..., dict[str, object]],
        fake_store: FakeIntakeStore,
    ) -> None:
        response = post(workflow_run_event(workflow_run_id=1), signature=None)
        assert response.status_code == 401
        assert fake_store.enqueue_calls == []

    def test_ac1_bad_signature_returns_401_without_parsing_or_enqueue(
        self,
        post: Callable[..., httpx.Response],
        workflow_run_event: Callable[..., dict[str, object]],
        fake_store: FakeIntakeStore,
    ) -> None:
        response = post(workflow_run_event(workflow_run_id=2), signing_secret="the-wrong-secret")
        assert response.status_code == 401
        assert fake_store.enqueue_calls == []

    def test_ac1_bad_signature_never_parses_a_broken_body(
        self, post: Callable[..., httpx.Response], fake_store: FakeIntakeStore
    ) -> None:
        # A 401 (not a 400) over invalid JSON proves the body was never parsed.
        response = post(b"{ not json", signing_secret="the-wrong-secret")
        assert response.status_code == 401
        assert fake_store.enqueue_calls == []

    def test_ac1_valid_signature_accepted(
        self,
        post: Callable[..., httpx.Response],
        workflow_run_event: Callable[..., dict[str, object]],
        fake_store: FakeIntakeStore,
    ) -> None:
        response = post(workflow_run_event(workflow_run_id=3))
        assert response.status_code == 202
        delivery_id, identity, run_id = fake_store.enqueue_calls[0]
        assert delivery_id == "delivery-0001"
        assert identity.workflow_run_id == 3
        assert str(run_id) == response.json()["run_id"]

    def test_ac1_unknown_installation_rejected_and_no_downstream(
        self,
        post: Callable[..., httpx.Response],
        workflow_run_event: Callable[..., dict[str, object]],
        fake_store: FakeIntakeStore,
    ) -> None:
        response = post(workflow_run_event(installation_id=9999))
        assert response.status_code == 403
        assert fake_store.enqueue_calls == []
        assert fake_store.queue_depth_calls == [], "no queue check downstream"

    def test_ac1_accepts_any_configured_rotation_secret(
        self,
        webhook_secret: str,
        rotated_secret: str,
        sign_body: Callable[[bytes, str], str],
    ) -> None:
        # AD-25 rotation: a tuple of two secrets accepts either during overlap.
        body = b'{"action":"completed"}'
        secrets = (webhook_secret, rotated_secret)
        assert verify_signature(body, sign_body(body, rotated_secret), secrets)
        assert verify_signature(body, sign_body(body, webhook_secret), secrets)
        assert not verify_signature(
            body, sign_body(body, webhook_secret), (rotated_secret,)
        )

    def test_ac1_malformed_signature_headers_are_rejected(
        self, webhook_secret: str, sign_body: Callable[[bytes, str], str]
    ) -> None:
        body = b"{}"
        assert not verify_signature(body, None, (webhook_secret,))
        assert not verify_signature(body, "", (webhook_secret,))
        assert not verify_signature(body, "sha256=not-hex", (webhook_secret,))
        assert not verify_signature(body, "sha1=deadbeef", (webhook_secret,))
        assert not verify_signature(body, sign_body(body, webhook_secret), ())

    def test_ac1_run_identity_is_not_mutated_by_a_duplicate(
        self,
        post: Callable[..., httpx.Response],
        workflow_run_event: Callable[..., dict[str, object]],
        fake_store: FakeIntakeStore,
    ) -> None:
        payload = workflow_run_event(workflow_run_id=44)
        first = post(payload, delivery="d-identity-1")
        second = post(payload, delivery="d-identity-2")
        assert first.status_code == 202
        assert second.status_code == 200
        assert fake_store.run_count == 1
        assert first.json()["run_id"] == second.json()["run_id"]
        assert str(fake_store.enqueue_calls[0][2]) == first.json()["run_id"]
        assert IntakeOutcome.ENQUEUED.value == "enqueued"

    def test_ac1_signed_non_dict_body_returns_400(
        self, post: Callable[..., httpx.Response], fake_store: FakeIntakeStore
    ) -> None:
        response = post(b"[1, 2, 3]")
        assert response.status_code == 400
        assert fake_store.enqueue_calls == []

    def test_ac1_blank_event_header_is_ignored(
        self,
        post: Callable[..., httpx.Response],
        workflow_run_event: Callable[..., dict[str, object]],
        fake_store: FakeIntakeStore,
    ) -> None:
        response = post(workflow_run_event(workflow_run_id=9), event="")
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"
        assert fake_store.enqueue_calls == []


class TestRotationLifecycle:
    """Story 1.3 AC2: old-only -> overlap -> retired, through the real app.

    Each phase builds its own `create_app` with a distinct `GatewaySettings`
    secret tuple (rotation is a config change, not a code path -- AD-25).
    `signature.py` and `settings.py` are untouched; this proves the existing
    `_split_secrets` + `verify_signature` contract already carries the whole
    lifecycle.
    """

    def _app_client(
        self,
        secrets: tuple[str, ...],
        fake_store: FakeIntakeStore,
        limits: GatewayLimits,
        clock: FrozenClock,
    ) -> TestClient:
        settings = GatewaySettings(
            webhook_secrets=secrets,
            allowed_installation_ids=frozenset({INSTALLATION_ID}),
            database_url="postgresql://unused",
        )
        app = create_app(settings, fake_store, limits, clock=clock)
        return TestClient(app)

    def _post(
        self,
        client: TestClient,
        *,
        secret_used_to_sign: str | None,
        delivery: str,
        workflow_run_id: int,
    ) -> httpx.Response:
        body = json.dumps(
            workflow_run_payload(workflow_run_id=workflow_run_id)
        ).encode("utf-8")
        headers = {EVENT_HEADER: "workflow_run", DELIVERY_HEADER: delivery}
        if secret_used_to_sign is not None:
            headers[SIGNATURE_HEADER] = sign(body, secret_used_to_sign)
        return client.post("/webhook", content=body, headers=headers)

    def test_ac2_rotation_lifecycle_old_overlap_retired(
        self,
        fake_store: FakeIntakeStore,
        limits: GatewayLimits,
        clock: FrozenClock,
    ) -> None:
        old, new = TEST_WEBHOOK_SECRET, ROTATED_WEBHOOK_SECRET

        # Old-only phase: only the old secret is configured.
        with self._app_client((old,), fake_store, limits, clock) as client:
            old_ok = self._post(
                client, secret_used_to_sign=old, delivery="d-old-1", workflow_run_id=101
            )
            new_rejected = self._post(
                client, secret_used_to_sign=new, delivery="d-old-2", workflow_run_id=102
            )
        assert old_ok.status_code == 202
        assert new_rejected.status_code == 401

        # Overlap phase: both secrets are configured during rotation.
        with self._app_client((old, new), fake_store, limits, clock) as client:
            old_still_ok = self._post(
                client, secret_used_to_sign=old, delivery="d-overlap-1", workflow_run_id=103
            )
            new_also_ok = self._post(
                client, secret_used_to_sign=new, delivery="d-overlap-2", workflow_run_id=104
            )
            wrong_secret_rejected = self._post(
                client,
                secret_used_to_sign="not-a-configured-secret",
                delivery="d-overlap-3",
                workflow_run_id=105,
            )
        assert old_still_ok.status_code == 202
        assert new_also_ok.status_code == 202
        assert wrong_secret_rejected.status_code == 401

        # Retired phase: the old secret has been dropped from config.
        with self._app_client((new,), fake_store, limits, clock) as client:
            old_now_rejected = self._post(
                client, secret_used_to_sign=old, delivery="d-retired-1", workflow_run_id=106
            )
            new_still_ok = self._post(
                client, secret_used_to_sign=new, delivery="d-retired-2", workflow_run_id=107
            )
        assert old_now_rejected.status_code == 401
        assert new_still_ok.status_code == 202
