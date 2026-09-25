"""Deterministic, I/O-free helpers shared by the gateway intake tests.

Separate from `conftest.py` so test modules can import the concrete fake and
constants without importing the fixture plugin twice (a second import would
define a second `FakeIntakeStore` class).
"""

import hashlib
import hmac
import threading
import uuid

from gateway.events import DELIVERY_HEADER, EVENT_HEADER, RunIdentity
from gateway.signature import SIGNATURE_HEADER
from gateway.store import IntakeOutcome, IntakeResult

TEST_WEBHOOK_SECRET = "unit-test-webhook-value"
ROTATED_WEBHOOK_SECRET = "unit-test-rotated-webhook-value"
INSTALLATION_ID = 4242
REPO_ID = 99


def sign(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def workflow_run_payload(
    *,
    installation_id: int = INSTALLATION_ID,
    repo_id: int = REPO_ID,
    workflow_run_id: int = 777,
    run_attempt: int = 1,
    action: str = "completed",
    conclusion: str = "failure",
) -> dict[str, object]:
    return {
        "action": action,
        "installation": {"id": installation_id},
        "repository": {"id": repo_id},
        "workflow_run": {
            "id": workflow_run_id,
            "run_attempt": run_attempt,
            "conclusion": conclusion,
        },
    }


def issue_comment_payload(
    *, installation_id: int = INSTALLATION_ID, repo_id: int = REPO_ID
) -> dict[str, object]:
    return {
        "action": "created",
        "installation": {"id": installation_id},
        "repository": {"id": repo_id},
        "issue": {"number": 1},
    }


class FrozenClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeIntakeStore:
    """In-memory `IntakeStore` honouring the dedupe/idempotency contract.

    A lock makes the concurrent-duplicate test deterministic while keeping
    the same observable behaviour as the Postgres adapter (Liskov).
    """

    def __init__(self, depth: int = 0) -> None:
        self.depth = depth
        self.enqueue_calls: list[tuple[str, RunIdentity, uuid.UUID]] = []
        self.queue_depth_calls: list[int] = []
        self._by_delivery: dict[str, IntakeResult] = {}
        self._by_identity: dict[tuple[int, int, int], uuid.UUID] = {}
        self._lock = threading.Lock()

    @property
    def run_count(self) -> int:
        return len(self._by_identity)

    @property
    def delivery_count(self) -> int:
        return len(self._by_delivery)

    def queue_depth(self, repo_id: int) -> int:
        self.queue_depth_calls.append(repo_id)
        return self.depth

    def record_and_enqueue(
        self, delivery_id: str, identity: RunIdentity, run_id: uuid.UUID
    ) -> IntakeResult:
        with self._lock:
            self.enqueue_calls.append((delivery_id, identity, run_id))
            known = self._by_delivery.get(delivery_id)
            if known is not None:
                return IntakeResult(IntakeOutcome.DELIVERY_REPLAY, known.run_id)
            key = (identity.repo_id, identity.workflow_run_id, identity.run_attempt)
            existing = self._by_identity.get(key)
            if existing is not None:
                result = IntakeResult(IntakeOutcome.RUN_DUPLICATE, existing)
                self._by_delivery[delivery_id] = result
                return result
            self._by_identity[key] = run_id
            result = IntakeResult(IntakeOutcome.ENQUEUED, run_id)
            self._by_delivery[delivery_id] = result
            return result
