"""Per-installation rate limit and per-repo queue-depth cap (AD-17).

Pure and deterministic: the clock is injected, so no test sleeps. The queue
cap compares a depth the store supplies; the gateway keeps no durable
counter of its own beyond the database.
"""

from collections import deque
from collections.abc import Callable

__all__ = ["InstallationRateLimiter", "queue_depth_exceeds"]


class InstallationRateLimiter:
    """Sliding-window counter, one window per installation (AD-17)."""

    def __init__(
        self, limit: int, window_seconds: float, clock: Callable[[], float]
    ) -> None:
        self._limit = limit
        self._window_seconds = window_seconds
        self._clock = clock
        self._hits: dict[int, deque[float]] = {}

    def allow(self, installation_id: int) -> bool:
        now = self._clock()
        hits = self._hits.setdefault(installation_id, deque())
        while hits and now - hits[0] >= self._window_seconds:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        return True


def queue_depth_exceeds(depth: int, cap: int) -> bool:
    """A repo already at its pending-run cap rejects a new run (AD-17)."""
    return depth >= cap
