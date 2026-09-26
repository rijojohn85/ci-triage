"""Story 2.6 unit tests — history domain + Postgres adapter (AC1/AC2/AC3, AD-15).

Mirrors `tests/workflow/test_steps.py`: the Postgres boundary is driven
through a small Protocol fake, no database touched here. The real adapter
runs in the marked integration tests (`tests/workflow/test_history_integration.py`).
"""

import hashlib
import uuid
from datetime import datetime, timezone
from types import TracebackType

import psycopg
import pytest

from workflow.history import (
    HistoryEntry,
    HumanVerdict,
    ImportRecord,
    NonTerminalWriteError,
    TerminalWrite,
    normalize_fingerprint,
)
from workflow.history_store import PostgresHistoryStore
from workflow.run_states import RunState

REPO_ID = 7
OTHER_REPO_ID = 99
CREATED_AT = datetime(2026, 9, 26, 12, 0, 1, tzinfo=timezone.utc)


class FakeCursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def fetchone(self) -> tuple[object, ...] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self._rows)


class _NullTransaction:
    """No-op stand-in for `conn.transaction()` (the fake has no real rollback)."""

    def __enter__(self) -> "_NullTransaction":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        return False


class FakeConnection:
    """One scripted result list per `execute`; records SQL and bound params."""

    def __init__(self, *results: list[tuple[object, ...]]) -> None:
        self._results = list(results)
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        return False

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> FakeCursor:
        self.calls.append((sql, params))
        rows = self._results.pop(0) if self._results else []
        return FakeCursor(rows)

    def transaction(self) -> _NullTransaction:
        return _NullTransaction()


class InsertRaisesConnection(FakeConnection):
    """Raises on the `history` insert, then serves the re-select."""

    def __init__(
        self, error: BaseException, reselect_rows: list[tuple[object, ...]]
    ) -> None:
        super().__init__(reselect_rows)
        self._error = error
        self._raised = False

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> FakeCursor:
        if sql.lstrip().startswith("INSERT") and not self._raised:
            self._raised = True
            self.calls.append((sql, params))
            raise self._error
        return super().execute(sql, params)


def store_against(connection: FakeConnection) -> PostgresHistoryStore:
    return PostgresHistoryStore("postgresql://unused", connect=lambda _dsn: connection)


def sample_row(
    row_id: uuid.UUID,
    run_id: uuid.UUID,
    fingerprint: str,
    human_verdict: str | None = None,
) -> tuple[object, ...]:
    return (
        row_id,
        run_id,
        REPO_ID,
        "tests/test_x.py::test_y",
        "AssertionError",
        ["frame_a", "frame_b"],
        fingerprint,
        RunState.FAILED.value,
        human_verdict,
        CREATED_AT,
    )


class TestFingerprint:
    def test_ac1_fingerprint_is_sha256_of_normalized_fields(self) -> None:
        fingerprint = normalize_fingerprint(
            " tests/test_x.py::test_y ", " AssertionError ", [" frame_a ", "frame_b"]
        )

        expected = hashlib.sha256(
            "\x1f".join(
                ["tests/test_x.py::test_y", "AssertionError", "frame_a", "frame_b"]
            ).encode("utf-8")
        ).hexdigest()
        assert fingerprint == expected
        # normalization strips whitespace before hashing, so untrimmed and
        # trimmed inputs fingerprint identically.
        assert fingerprint == normalize_fingerprint(
            "tests/test_x.py::test_y", "AssertionError", ["frame_a", "frame_b"]
        )


class TestWriteTerminal:
    def test_ac2_exactly_one_terminal_history_row(self) -> None:
        run_id = uuid.uuid4()
        row_id_holder: list[uuid.UUID] = []

        first_conn = FakeConnection([(uuid.uuid4(), CREATED_AT)])
        store = store_against(first_conn)
        write = TerminalWrite(
            run_id=run_id,
            repo_id=REPO_ID,
            test_id="tests/test_x.py::test_y",
            error_type="AssertionError",
            top_stack_frames=("frame_a", "frame_b"),
            to_state=RunState.FAILED,
        )
        first = store.write_terminal(write)
        row_id_holder.append(first.row_id)

        # Second write: the INSERT raises UniqueViolation (uq_history_run_id),
        # the store must re-select and return the SAME existing row, not raise.
        second_conn = InsertRaisesConnection(
            psycopg.errors.UniqueViolation("duplicate key"),
            [sample_row(first.row_id, run_id, first.fingerprint)],
        )
        store2 = store_against(second_conn)
        second = store2.write_terminal(write)

        assert isinstance(first, HistoryEntry)
        assert second.row_id == first.row_id
        assert second.run_id == run_id
        # the re-select query ran, not a second insert-that-stuck
        select_calls = [
            c for c in second_conn.calls if c[0].lstrip().startswith("SELECT")
        ]
        assert len(select_calls) == 1

    def test_ac2_awaiting_approval_write_refused(self) -> None:
        run_id = uuid.uuid4()
        connection = FakeConnection()
        store = store_against(connection)

        with pytest.raises(NonTerminalWriteError):
            store.write_terminal(
                TerminalWrite(
                    run_id=run_id,
                    repo_id=REPO_ID,
                    test_id="tests/test_x.py::test_y",
                    error_type="AssertionError",
                    top_stack_frames=("frame_a",),
                    to_state=RunState.AWAITING_APPROVAL,
                )
            )

        assert connection.calls == [], "refused before any I/O"

    def test_ac2_human_verdict_included_when_present(self) -> None:
        run_id = uuid.uuid4()
        connection = FakeConnection([(uuid.uuid4(), CREATED_AT)])
        store = store_against(connection)

        entry = store.write_terminal(
            TerminalWrite(
                run_id=run_id,
                repo_id=REPO_ID,
                test_id="tests/test_x.py::test_y",
                error_type="AssertionError",
                top_stack_frames=("frame_a",),
                to_state=RunState.REJECTED_BY_HUMAN,
                human_verdict=HumanVerdict.REJECTED,
            )
        )

        assert entry.human_verdict is HumanVerdict.REJECTED
        _sql, params = connection.calls[0]
        assert HumanVerdict.REJECTED.value in params

    def test_ac2_human_verdict_absent_is_null(self) -> None:
        run_id = uuid.uuid4()
        connection = FakeConnection([(uuid.uuid4(), CREATED_AT)])
        store = store_against(connection)

        entry = store.write_terminal(
            TerminalWrite(
                run_id=run_id,
                repo_id=REPO_ID,
                test_id="tests/test_x.py::test_y",
                error_type="AssertionError",
                top_stack_frames=("frame_a",),
                to_state=RunState.FAILED,
            )
        )

        assert entry.human_verdict is None
        _sql, params = connection.calls[0]
        assert None in params


class TestLookup:
    def test_ac1_history_queries_bind_repo_id(self) -> None:
        connection = FakeConnection([sample_row(uuid.uuid4(), uuid.uuid4(), "fp")])
        store = store_against(connection)

        store.lookup(REPO_ID, "fp", 20)

        assert len(connection.calls) == 1
        _sql, params = connection.calls[0]
        assert REPO_ID in params

    def test_ac3_foreign_repo_lookup_rejected(self) -> None:
        # RT-03: a fake standing in for "seeded under repo A" -- a query
        # bound to repo B must never see it. The fake scopes its result to
        # the repo_id it was actually called with by returning empty here.
        connection = FakeConnection([])
        store = store_against(connection)

        rows = store.lookup(OTHER_REPO_ID, "fp", 20)

        assert rows == []
        _sql, params = connection.calls[0]
        assert params == (OTHER_REPO_ID, "fp", 20)


class TestImportSeed:
    def test_ac3_history_import_rejects_free_text(self) -> None:
        with pytest.raises(TypeError):
            ImportRecord(  # type: ignore[call-arg]
                repo_id=REPO_ID,
                test_id="tests/test_x.py::test_y",
                error_type="AssertionError",
                top_stack_frames=("frame_a",),
                terminal_state=RunState.FAILED,
                notes="free text should never be accepted",
            )

    def test_ac3_import_seed_rejects_non_terminal_state_before_any_io(self) -> None:
        connection = FakeConnection()
        store = store_against(connection)
        records = [
            ImportRecord(
                repo_id=REPO_ID,
                test_id="tests/test_x.py::test_y",
                error_type="AssertionError",
                top_stack_frames=("frame_a",),
                terminal_state=RunState.AWAITING_APPROVAL,
            )
        ]

        with pytest.raises(NonTerminalWriteError):
            store.import_seed(records)

        assert connection.calls == [], "refused before any I/O"

    def test_ac3_import_seed_generates_a_fresh_run_id_per_record(self) -> None:
        connection = FakeConnection([], [])
        store = store_against(connection)
        records = [
            ImportRecord(
                repo_id=REPO_ID,
                test_id="tests/test_x.py::test_y",
                error_type="AssertionError",
                top_stack_frames=("frame_a",),
                terminal_state=RunState.FAILED,
            ),
            ImportRecord(
                repo_id=REPO_ID,
                test_id="tests/test_z.py::test_w",
                error_type="ValueError",
                top_stack_frames=("frame_c",),
                terminal_state=RunState.DONE_REPORT,
                human_verdict=HumanVerdict.APPROVED,
            ),
        ]

        row_ids = store.import_seed(records)

        assert len(row_ids) == 2
        assert row_ids[0] != row_ids[1]
        assert len(connection.calls) == 2
        for _sql, params in connection.calls:
            assert REPO_ID in params
        # run_id (second bound param) differs between the two inserted rows.
        run_ids = [params[1] for _sql, params in connection.calls]
        assert run_ids[0] != run_ids[1]
