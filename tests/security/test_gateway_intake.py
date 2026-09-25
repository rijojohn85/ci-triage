"""Story 1.1 AC2: enqueue once, collapse replays and duplicates (AD-17)."""

import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import httpx

from gateway.events import RunIdentity
from gateway.store import IntakeOutcome
from tests.security.gateway_fakes import (
    INSTALLATION_ID,
    REPO_ID,
    FakeIntakeStore,
)


class TestAuthenticIntake:
    def test_ac2_authentic_failure_enqueues_received_and_returns_202(
        self,
        post: Callable[..., httpx.Response],
        workflow_run_event: Callable[..., dict[str, object]],
        fake_store: FakeIntakeStore,
    ) -> None:
        response = post(workflow_run_event(workflow_run_id=500))
        assert response.status_code == 202
        assert response.json()["status"] == "accepted"
        delivery_id, identity, run_id = fake_store.enqueue_calls[0]
        assert delivery_id == "delivery-0001"
        assert identity == RunIdentity(INSTALLATION_ID, REPO_ID, 500, 1)
        assert str(run_id) == response.json()["run_id"]
        assert fake_store.run_count == 1

    def test_ac2_replayed_delivery_is_2xx_noop_single_row(
        self,
        post: Callable[..., httpx.Response],
        workflow_run_event: Callable[..., dict[str, object]],
        fake_store: FakeIntakeStore,
    ) -> None:
        payload = workflow_run_event(workflow_run_id=501)
        first = post(payload, delivery="d-replay")
        second = post(payload, delivery="d-replay")
        assert first.status_code == 202
        assert second.status_code == 200
        assert second.json()["status"] == "delivery_replay"
        assert fake_store.run_count == 1
        assert fake_store.delivery_count == 1

    def test_ac2_run_identity_unique_under_new_delivery_id(
        self,
        post: Callable[..., httpx.Response],
        workflow_run_event: Callable[..., dict[str, object]],
        fake_store: FakeIntakeStore,
    ) -> None:
        payload = workflow_run_event(
            workflow_run_id=502, run_attempt=2, conclusion="failure"
        )
        first = post(payload, delivery="d-first")
        second = post(payload, delivery="d-second")
        assert first.status_code == 202
        assert second.status_code == 200
        assert second.json()["status"] == "run_duplicate"
        assert fake_store.run_count == 1

    def test_fake_store_contract_collapses_concurrent_duplicates(
        self, fake_store: FakeIntakeStore
    ) -> None:
        """Verify the fake honours the store contract: the real concurrency
        proof is the integration test against Postgres."""
        identity = RunIdentity(INSTALLATION_ID, REPO_ID, 503, 1)

        def submit(index: int) -> IntakeOutcome:
            return fake_store.record_and_enqueue(
                f"concurrent-{index}", identity, uuid.uuid4()
            ).outcome

        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(submit, range(8)))

        assert fake_store.run_count == 1
        assert outcomes.count(IntakeOutcome.ENQUEUED) == 1
        assert all(
            outcome in (IntakeOutcome.ENQUEUED, IntakeOutcome.RUN_DUPLICATE)
            for outcome in outcomes
        )
