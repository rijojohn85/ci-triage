"""Story 1.1 AC3: accept only the signed failure event, shed bursts (AD-17)."""

from collections.abc import Callable
from pathlib import Path

import httpx

from gateway.limits import InstallationRateLimiter
from gateway.settings import GatewayLimits
from scripts.check_layer_contract import (
    FORBIDDEN_GATEWAY_MODULES,
    imports_of,
    project_top_of,
)
from tests.security.gateway_fakes import FakeIntakeStore, FrozenClock


class TestEventAcceptance:
    def test_ac3_only_completed_failure_workflow_run_enqueues(
        self,
        post: Callable[..., httpx.Response],
        workflow_run_event: Callable[..., dict[str, object]],
        fake_store: FakeIntakeStore,
    ) -> None:
        success = post(workflow_run_event(workflow_run_id=1, conclusion="success"))
        requested = post(workflow_run_event(workflow_run_id=2, action="requested"))
        assert success.status_code == 200
        assert requested.status_code == 200
        assert fake_store.enqueue_calls == []

    def test_ac3_issue_comment_excluded(
        self,
        post: Callable[..., httpx.Response],
        issue_comment_event: Callable[..., dict[str, object]],
        fake_store: FakeIntakeStore,
    ) -> None:
        response = post(issue_comment_event(), event="issue_comment")
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"
        assert fake_store.enqueue_calls == []


class TestLoadLimits:
    def test_ac3_rate_limit_blocks_burst(
        self,
        post: Callable[..., httpx.Response],
        workflow_run_event: Callable[..., dict[str, object]],
        fake_store: FakeIntakeStore,
        clock: FrozenClock,
        limits: GatewayLimits,
    ) -> None:
        allowed = limits.rate_limit_per_installation
        codes = [
            post(workflow_run_event(workflow_run_id=100 + index), delivery=f"burst-{index}")
            .status_code
            for index in range(allowed + 1)
        ]
        assert codes[:allowed] == [202] * allowed
        assert codes[allowed] == 429
        assert len(fake_store.enqueue_calls) == allowed
        clock.advance(limits.rate_limit_window_seconds + 1)
        refreshed = post(workflow_run_event(workflow_run_id=999), delivery="after-window")
        assert refreshed.status_code == 202

    def test_ac3_rate_limit_is_per_installation(self) -> None:
        limiter = InstallationRateLimiter(
            limit=1, window_seconds=60, clock=lambda: 0.0
        )
        assert limiter.allow(1) is True
        assert limiter.allow(2) is True, "a second installation has its own window"
        assert limiter.allow(1) is False, "the first installation is now over its limit"

    def test_ac3_queue_depth_cap_blocks_excess(
        self,
        post: Callable[..., httpx.Response],
        workflow_run_event: Callable[..., dict[str, object]],
        fake_store: FakeIntakeStore,
        limits: GatewayLimits,
    ) -> None:
        fake_store.depth = limits.max_queue_depth_per_repo - 1
        within = post(workflow_run_event(workflow_run_id=200), delivery="depth-ok")
        assert within.status_code == 202
        fake_store.depth = limits.max_queue_depth_per_repo
        full = post(workflow_run_event(workflow_run_id=201), delivery="depth-full")
        assert full.status_code == 429
        assert full.json()["status"] == "queue_full"

    def test_ac3_rejection_zero_downstream_calls(
        self,
        post: Callable[..., httpx.Response],
        workflow_run_event: Callable[..., dict[str, object]],
        issue_comment_event: Callable[..., dict[str, object]],
        fake_store: FakeIntakeStore,
        limits: GatewayLimits,
    ) -> None:
        assert post(workflow_run_event(workflow_run_id=1), signing_secret="wrong").status_code == 401
        assert (
            post(workflow_run_event(workflow_run_id=2, installation_id=9999)).status_code
            == 403
        )
        assert post(issue_comment_event(), event="issue_comment").status_code == 200
        fake_store.depth = limits.max_queue_depth_per_repo
        assert post(workflow_run_event(workflow_run_id=3)).status_code == 429
        assert fake_store.enqueue_calls == []


class TestGatewayBoundary:
    def test_ac3_no_llm_or_github_imports_in_gateway(self) -> None:
        gateway_dir = Path(__file__).resolve().parents[2] / "gateway"
        offenders = [
            f"{path.name}: {module}"
            for path in sorted(gateway_dir.rglob("*.py"))
            for module in imports_of(path)
            if project_top_of(module).lower() in FORBIDDEN_GATEWAY_MODULES
        ]
        assert offenders == []


class TestBodyCap:
    def test_ac3_oversized_body_returns_413_without_enqueue(
        self,
        post: Callable[..., httpx.Response],
        fake_store: FakeIntakeStore,
        limits: GatewayLimits,
    ) -> None:
        oversized = b"x" * (limits.max_body_bytes + 1)
        response = post(oversized)
        assert response.status_code == 413
        assert response.json()["status"] == "payload_too_large"
        assert fake_store.enqueue_calls == []
