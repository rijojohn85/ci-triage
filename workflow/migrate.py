"""Forward-only SQL migration runner (story 0.3, AD-25).

Minimal hand-rolled design, per the story constraint: plain ``.sql`` files in
``deploy/migrations/``, tracked in a single ``schema_migrations`` table, each
file applied in exactly one transaction, non-zero exit on any failure. No
Alembic/SQLAlchemy, no advisory lock, no new dependencies (psycopg is the
pinned stack driver). Later stories add tables by dropping new ``.sql`` files —
this module never changes for that.

Pure logic (read/plan/apply) is separated from process-bound concerns
(exit codes, stdout) so unit tests fake the connection via
``MigrationConnection`` and the marked integration tests use real psycopg.
"""

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Protocol

import psycopg

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MIGRATIONS_DIR = REPO_ROOT / "deploy" / "migrations"

SCHEMA_MIGRATIONS_SQL = """\
CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_id text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
)"""

# One transaction per file: file body + tracking row commit or roll back
# together (no partial state, ever).
APPLIED_ROW_SQL = "INSERT INTO schema_migrations (migration_id) VALUES (%s)"
LIST_APPLIED_SQL = "SELECT migration_id FROM schema_migrations"

EXIT_OK = 0
EXIT_CONNECTION = 1
EXIT_MIGRATION_FAILED = 2


class MigrationError(Exception):
    """A migration's SQL failed; the transaction rolled back (AC1)."""

    def __init__(self, message: str, migration_id: str) -> None:
        super().__init__(f"migration {migration_id} failed: {message}")
        self.migration_id = migration_id


class Transaction(Protocol):
    def __enter__(self) -> object: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> object: ...


class MigrationConnection(Protocol):
    """Smallest surface the runner needs (SOLID-I: per-consumer protocol)."""

    def transaction(self) -> Transaction: ...
    def execute(self, sql: str, params: tuple[object, ...] = ()) -> object: ...
    def fetch_all(
        self, sql: str, params: tuple[object, ...] = ()
    ) -> list[tuple[object, ...]]: ...


@dataclass(frozen=True)
class MigrationFile:
    id: str
    path: Path

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")


def read_migrations(directory: Path) -> list[MigrationFile]:
    """Order files lexicographically; forward-only files are zero-padded."""
    return sorted(
        (
            MigrationFile(path.stem, path)
            for path in directory.glob("*.sql")
            if path.is_file()
        ),
        key=lambda m: m.id,
    )


def pending_files(
    migrations: list[MigrationFile], applied: set[str]
) -> list[MigrationFile]:
    return [m for m in migrations if m.id not in applied]


def ensure_schema_migrations(conn: MigrationConnection) -> None:
    # Its own transaction: the tracking table exists even when a later
    # migration fails right after (no partial state, no absent tracker).
    with conn.transaction():
        conn.execute(SCHEMA_MIGRATIONS_SQL)


def _applied_ids(conn: MigrationConnection) -> set[str]:
    return {str(row[0]) for row in conn.fetch_all(LIST_APPLIED_SQL)}


def apply_pending_files(conn: MigrationConnection, directory: Path) -> int:
    """Apply every not-yet-applied file; return how many were applied."""
    ensure_schema_migrations(conn)
    todo = pending_files(read_migrations(directory), _applied_ids(conn))
    applied = 0
    for migration in todo:
        _apply_one(conn, migration)
        applied += 1
    return applied


def _apply_one(conn: MigrationConnection, migration: MigrationFile) -> None:
    # Instantiating the transaction context must happen before the possibly
    # failing execute() so the withdrawal of the whole file body is atomic.
    with conn.transaction():
        try:
            conn.execute(migration.sql)
        except MigrationError:
            raise
        except Exception as exc:
            raise MigrationError(str(exc), migration.id) from exc
        conn.execute(APPLIED_ROW_SQL, (migration.id,))


class PsycopgMigrationConnection:
    """Adapt a psycopg connection to the runner protocol (I/O edge)."""

    def __init__(self, raw: "psycopg.Connection[psycopg.rows.TupleRow]") -> None:
        self._raw = raw

    def transaction(self) -> Transaction:
        return self._raw.transaction()

    def execute(
        self, sql: str, params: tuple[object, ...] = ()
    ) -> psycopg.Cursor[psycopg.rows.TupleRow]:
        return self._raw.execute(sql, params or None)

    def fetch_all(
        self, sql: str, params: tuple[object, ...] = ()
    ) -> list[tuple[object, ...]]:
        return [tuple(row) for row in self._raw.execute(sql, params or None).fetchall()]


def build_report(conn: MigrationConnection, directory: Path) -> str:
    """Human-readable status line for --status/--dry-run (docs commands)."""
    files = read_migrations(directory)
    done = _applied_ids(conn)
    pending = pending_files(files, done)
    lines = [
        f"migrations dir: {directory}",
        f"tracked applied: {len(done)}",
        f"known files: {len(files)}",
        f"pending: {len(pending)}",
    ]
    lines.extend(f"  pending {m.id}" for m in pending)
    return "\n".join(lines)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=DEFAULT_MIGRATIONS_DIR,
        help="directory of forward-only .sql files (default: deploy/migrations)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list pending migrations and exit without applying",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Process boundary: env/exit codes live only here (AD-25 one-shot job)."""
    args = parse_args(argv)
    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        print("FAIL: DATABASE_URL is not set", file=sys.stderr)
        return EXIT_CONNECTION

    try:
        # autocommit so each conn.transaction() block below is a real,
        # independently committed BEGIN/COMMIT (psycopg 3 semantics).
        with psycopg.connect(dsn, autocommit=True) as raw:
            conn = PsycopgMigrationConnection(raw)  # pyright: ignore[reportArgumentType]
            if args.dry_run:
                pending = build_report(conn, args.migrations_dir)
                print(pending)
                return EXIT_OK
            count = apply_pending_files(conn, args.migrations_dir)
            print(f"applied {count} migration(s); tracking: schema_migrations")
            return EXIT_OK
    except psycopg.OperationalError as exc:
        print(f"FAIL: cannot connect: {exc}", file=sys.stderr)
        return EXIT_CONNECTION
    except MigrationError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return EXIT_MIGRATION_FAILED


if __name__ == "__main__":
    sys.exit(main())
