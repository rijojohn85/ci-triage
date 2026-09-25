"""Story 1.1 AC1: verify the signature over raw bytes before parsing (AD-17).

The fakes and clock come from `tests/security/gateway_fakes.py`; no live GitHub.
"""

from collections.abc import Callable

import httpx

from gateway.signature import verify_signature
from gateway.store import IntakeOutcome
from tests.security.gateway_fakes import FakeIntakeStore


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
