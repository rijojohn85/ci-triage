"""The gateway ASGI app: signature → installation → event → limits → enqueue.

Composition only (SOLID-S/D): pure decisions live in `signature`, `events`
and `limits`; persistence is behind the `IntakeStore` Protocol. The gateway
makes no LLM or GitHub call (AD-17).
"""

import json
import time
from collections.abc import Callable, Mapping

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from gateway.events import (
    DELIVERY_HEADER,
    EVENT_HEADER,
    installation_id,
    is_accepted_event,
    parse_run_identity,
)
from gateway.limits import InstallationRateLimiter, queue_depth_exceeds
from gateway.settings import GatewayLimits, GatewaySettings
from gateway.signature import SIGNATURE_HEADER, verify_signature
from gateway.store import IntakeOutcome, IntakeStore
from workflow.ids import new_run_id

__all__ = ["create_app"]

WEBHOOK_PATH = "/webhook"

_STATUS_SIGNATURE = 401
_STATUS_BAD_REQUEST = 400
_STATUS_UNKNOWN_INSTALLATION = 403
_STATUS_TOO_LARGE = 413
_STATUS_RATE_LIMITED = 429
_STATUS_ACCEPTED = 202
_STATUS_NOOP = 200


class GatewayIntake:
    """One webhook request, stage by stage (AD-17)."""

    def __init__(
        self,
        settings: GatewaySettings,
        store: IntakeStore,
        limits: GatewayLimits,
        clock: Callable[[], float] | None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._limits = limits
        self._rate_limiter = InstallationRateLimiter(
            limits.rate_limit_per_installation,
            float(limits.rate_limit_window_seconds),
            time.monotonic if clock is None else clock,
        )

    def screen(
        self, request: Request, payload: Mapping[str, object]
    ) -> Response | None:
        """Installation, event and load checks; None means "enqueue it"."""
        installation = installation_id(payload)
        if (
            installation is None
            or installation not in self._settings.allowed_installation_ids
        ):
            return _status("unknown_installation", _STATUS_UNKNOWN_INSTALLATION)
        if not is_accepted_event(request.headers.get(EVENT_HEADER, ""), payload):
            return _status("ignored", _STATUS_NOOP)
        identity = parse_run_identity(payload)
        if identity is None:
            return _status("invalid_payload", _STATUS_BAD_REQUEST)
        if not self._rate_limiter.allow(installation):
            return _status("rate_limited", _STATUS_RATE_LIMITED)
        depth = self._store.queue_depth(identity.repo_id)
        if queue_depth_exceeds(depth, self._limits.max_queue_depth_per_repo):
            return _status("queue_full", _STATUS_RATE_LIMITED)
        return None

    def enqueue(self, request: Request, payload: Mapping[str, object]) -> Response:
        identity = parse_run_identity(payload)
        delivery_id = request.headers.get(DELIVERY_HEADER, "")
        if identity is None or not delivery_id:
            return _status("invalid_payload", _STATUS_BAD_REQUEST)
        run_id = new_run_id()
        result = self._store.record_and_enqueue(delivery_id, identity, run_id)
        if result.outcome is IntakeOutcome.ENQUEUED:
            return JSONResponse(
                {"status": "accepted", "run_id": str(run_id)},
                status_code=_STATUS_ACCEPTED,
            )
        existing = None if result.run_id is None else str(result.run_id)
        return JSONResponse(
            {"status": result.outcome.value, "run_id": existing},
            status_code=_STATUS_NOOP,
        )

    async def handle(self, request: Request) -> Response:
        raw_body = await _read_bounded(request, self._limits.max_body_bytes)
        if raw_body is None:
            # AD-17 flooding: never buffer an unbounded body. The cap is
            # checked before the signature because verifying needs the body.
            return _status("payload_too_large", _STATUS_TOO_LARGE)
        if not verify_signature(
            raw_body,
            request.headers.get(SIGNATURE_HEADER),
            self._settings.webhook_secrets,
        ):
            return _status("invalid_signature", _STATUS_SIGNATURE)
        payload = _parse_body(raw_body)
        if payload is None:
            return _status("invalid_payload", _STATUS_BAD_REQUEST)
        rejection = self.screen(request, payload)
        if rejection is not None:
            return rejection
        return self.enqueue(request, payload)


def create_app(
    settings: GatewaySettings,
    store: IntakeStore,
    limits: GatewayLimits,
    clock: Callable[[], float] | None = None,
) -> Starlette:
    intake = GatewayIntake(settings, store, limits, clock)
    return Starlette(routes=[Route(WEBHOOK_PATH, intake.handle, methods=["POST"])])


def _parse_body(raw_body: bytes) -> dict[str, object] | None:
    try:
        payload = json.loads(raw_body)
    except ValueError:  # JSONDecodeError and non-UTF-8 UnicodeDecodeError
        return None
    return payload if isinstance(payload, dict) else None


async def _read_bounded(request: Request, cap: int) -> bytes | None:
    """Stream the body up to `cap` bytes; None once the cap is exceeded."""
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > cap:
            return None
    return bytes(body)


def _status(status: str, status_code: int) -> JSONResponse:
    return JSONResponse({"status": status}, status_code=status_code)
