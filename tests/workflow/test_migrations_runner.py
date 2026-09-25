"""Story 0.3 AC1 tests: forward-only migration runner (deterministic parts).

Tested through `workflow.migrate`'s public functions with a fake connection
honoring the runner's connection Protocol. Real-Postgres behavior (fresh
apply, idempotent re-run, rollback after a bad statement, no extra domain
tables) is covered by the marked integration tests in
tests/workflow/test_migrations_integration.py — make check stays fast
without Docker (user constraint on story 0.3).
"""

from pathlib import Path

import pytest

from workflow.migrate import MigrationError, MigrationFile, read_migrations


class FakeTransaction:
    """Count only; psycopg's transaction() rolls back when the body raises."""

    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    def __enter__(self) -> FakeTransaction:
        self._conn.transactions_started += 1
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc_type is None:
            self._conn.transactions_committed += 1


class FakeConnection:
    """MigrationConnection-shaped fake: capture SQL, optionally fail one id."""

    def __init__(self, applied: set[str] | None = None, raise_on: str = "") -> None:
        self.statements: list[tuple[str, tuple[object, ...]]] = []
        self.rows: list[tuple[object, ...]] = [(mid,) for mid in sorted(applied or ())]
        self.transactions_started = 0
        self.transactions_committed = 0
        self._raise_on = raise_on

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        if params and params == (self._raise_on,):
            raise MigrationError("simulated failure", migration_id=self._raise_on)
        self.statements.append((sql, params))

    def fetch_all(self, sql: str, params: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
        return list(self.rows)

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)


def applied_ids(conn: FakeConnection) -> list[str]:
    return [
        str(params[0])
        for sql, params in conn.statements
        if "INSERT INTO schema_migrations" in sql
    ]


def write_migrations(tmp_path: Path, files: dict[str, str]) -> Path:
    directory = tmp_path / "migrations"
    directory.mkdir()
    for name, sql in files.items():
        (directory / name).write_text(sql, encoding="utf-8")
    return directory


class TestFileNameOrder:
    def test_ac1_applies_pending_in_filename_order_exactly_once(
        self, tmp_path: Path
    ) -> None:
        directory = write_migrations(
            tmp_path,
            {"0002_second.sql": "CREATE TABLE second(id int);",
             "0001_first.sql": "CREATE TABLE first(id int);"},
        )
        conn = FakeConnection()
        migrate_apply(conn, directory)
        order = [
            sql for sql, _ in conn.statements if "CREATE TABLE" in sql
            and "schema_migrations" not in sql
        ]
        assert order == ["CREATE TABLE first(id int);", "CREATE TABLE second(id int);"]

    def test_ac1_re_run_applies_nothing(self, tmp_path: Path) -> None:
        directory = write_migrations(
            tmp_path, {"0001_a.sql": "SELECT 1;", "0002_b.sql": "SELECT 2;"}
        )
        conn = FakeConnection(applied={"0001_a", "0002_b"})
        assert migrate_apply(conn, directory) == 0
        assert applied_ids(conn) == []

    def test_partially_applied_re_run_applies_only_new(self, tmp_path: Path) -> None:
        directory = write_migrations(
            tmp_path, {"0001_a.sql": "SELECT 1;", "0002_b.sql": "SELECT 2;"}
        )
        conn = FakeConnection(applied={"0001_a"})
        assert migrate_apply(conn, directory) == 1
        assert applied_ids(conn) == ["0002_b"]


def migrate_apply(conn: FakeConnection, directory: Path) -> int:
    """Import late so collection RED-fails on missing module for all tests."""
    from workflow.migrate import apply_pending_files

    return apply_pending_files(conn, directory)


class TestFailureSemantics:
    def test_ac1_failed_migration_raises_and_marks_nothing(
        self, tmp_path: Path
    ) -> None:
        directory = write_migrations(
            tmp_path,
            {"0001_ok.sql": "SELECT 1;", "0002_broken.sql": "CREATE BAD;"},
        )
        conn = FakeConnection(raise_on="0002_broken")
        with pytest.raises(MigrationError):
            migrate_apply(conn, directory)
        assert applied_ids(conn) == ["0001_ok"]
        # committed transactions: tracker bootstrap + 0001_ok only
        assert conn.transactions_committed == 2

    def test_ac1_error_names_the_migration_file(self, tmp_path: Path) -> None:
        directory = write_migrations(tmp_path, {"0002_broken.sql": "CREATE BAD;"})
        conn = FakeConnection(raise_on="0002_broken")
        with pytest.raises(MigrationError, match="0002_broken") as excinfo:
            migrate_apply(conn, directory)
        assert "0002_broken" in str(excinfo.value)


class TestTrackingBootstrap:
    def test_ac1_bootstrap_sql_is_idempotent_create_table_if_not_exists(
        self,
    ) -> None:
        from workflow.migrate import SCHEMA_MIGRATIONS_SQL, ensure_schema_migrations

        assert SCHEMA_MIGRATIONS_SQL.startswith(
            "CREATE TABLE IF NOT EXISTS schema_migrations"
        )
        conn = FakeConnection()
        ensure_schema_migrations(conn)
        assert conn.statements == [(SCHEMA_MIGRATIONS_SQL, ())]

    def test_ac1_empty_migrations_dir_applies_zero(self, tmp_path: Path) -> None:
        directory = tmp_path / "migrations"
        directory.mkdir()
        conn = FakeConnection()
        assert migrate_apply(conn, directory) == 0
        assert applied_ids(conn) == []

    def test_read_migrations_skips_non_sql_and_sorts(self, tmp_path: Path) -> None:
        directory = write_migrations(
            tmp_path, {"0001_a.sql": "SELECT 1;", "README.md": "not sql"}
        )
        files = read_migrations(directory)
        assert [m.id for m in files] == ["0001_a"]
        assert all(isinstance(m, MigrationFile) for m in files)


class TestPlan:
    def test_ac1_dry_run_returns_pending_without_side_effects(
        self, tmp_path: Path
    ) -> None:
        from workflow.migrate import pending_files

        directory = write_migrations(
            tmp_path, {"0001_a.sql": "SELECT 1;", "0002_b.sql": "SELECT 2;"}
        )
        plan = pending_files(read_migrations(directory), applied={"0001_a"})
        assert [m.id for m in plan] == ["0002_b"]
