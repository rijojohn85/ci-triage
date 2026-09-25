"""`run_id` factory: pure UUIDv7 (RFC 9562), the one run identity (AD-4).

`run_id` travels as the A2A `contextId`/`task_id` and keys `triage_run`, so it
is generated here once and reused by 2.3/2.4. UUIDv7 keeps a 48-bit
millisecond timestamp first, which gives Postgres index locality without a
separate sequence. Hand-rolled because `requires-python >= 3.10`: `uuid.uuid7`
only exists from 3.14, and the pinned floor wins.
"""

import os
import time
import uuid

__all__ = ["new_run_id"]

_VERSION_7 = 0x70
_VARIANT_RFC_4122 = 0x80
_RANDOM_BYTES = 10
_NANOSECONDS_PER_MILLISECOND = 1_000_000


def new_run_id(now_ms: int | None = None) -> uuid.UUID:
    """Return a fresh time-ordered UUIDv7; `now_ms` is injectable for tests."""
    milliseconds = (
        time.time_ns() // _NANOSECONDS_PER_MILLISECOND if now_ms is None else now_ms
    )
    raw = bytearray(os.urandom(_RANDOM_BYTES))
    raw[0] = (raw[0] & 0x0F) | _VERSION_7
    raw[2] = (raw[2] & 0x3F) | _VARIANT_RFC_4122
    return uuid.UUID(bytes=milliseconds.to_bytes(6, "big") + bytes(raw))
