"""Story 1.1 unit tests: UUIDv7 run identity (AC2 / AD-4).

`run_id` is the one identifier later stories reuse (2.3/2.4). It must be a
time-ordered UUIDv7 (RFC 9562) so Postgres index locality holds, generated
by one pure factory.
"""

import uuid

from workflow.ids import new_run_id


class TestNewRunId:
    def test_new_run_id_is_uuid7_time_ordered(self) -> None:
        earlier = new_run_id(now_ms=1_700_000_000_000)
        later = new_run_id(now_ms=1_700_000_000_001)

        assert earlier.version == 7, "run_id must be UUIDv7 (AD-4)"
        assert later.version == 7
        assert earlier.variant == uuid.RFC_4122
        assert earlier < later, "the 48-bit timestamp prefix must order ids"

    def test_new_run_id_prefix_is_the_millisecond_timestamp(self) -> None:
        now_ms = 1_700_000_000_123
        run_id = new_run_id(now_ms=now_ms)
        assert run_id.bytes[0:6] == now_ms.to_bytes(6, "big")

    def test_new_run_id_is_unique_per_call(self) -> None:
        assert new_run_id() != new_run_id()
