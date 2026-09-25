"""Story 0.3 integration tests — real postgres:18 via Docker (AC1/AC3).

Needs Docker on the host; marked `integration` and excluded from `make
check` (pyproject addopts) so the default gate stays fast. Run explicitly:

    .venv/bin/pytest -m integration -q          # or: make test-integration

The session boots one disposable postgres:18 on an ephemeral host port and
removes it afterwards.
"""

import secrets
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from workflow import migrate

REPO = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.integration


def docker_run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True)


@pytest.fixture()
def pg_dsn() -> Iterator[str]:
    """A fresh postgres:18 per test: deterministic, no cross-test state."""
    try:
        docker_run("info", "--format", "{{.ServerVersion}}")
    except FileNotFoundError:
        pytest.skip("docker CLI not on PATH")
    name = f"triage-it-pg-{secrets.token_hex(4)}"
    started = docker_run(
        "run", "-d", "--name", name,
        "-e", "POSTGRES_PASSWORD=it-password",
        "-e", "POSTGRES_USER=it_user",
        "-e", "POSTGRES_DB=it_db",
        "-p", "127.0.0.1::5432",
        "postgres:18",
    )
    if started.returncode != 0:
        pytest.skip(f"could not start postgres:18 ({started.stderr.strip()})")
    try:
        yield f"postgresql://it_user:it-password@127.0.0.1:{wait_ready(name)}/it_db"
    finally:
        docker_run("rm", "-f", name)


def wait_ready(container: str) -> str:
    """Return the ephemeral published port once the final server accepts.

    The entrypoint's temporary init server also answers pg_isready before
    restarting, so readiness must be probed with a real SELECT over the
    published port, not inside the container.
    """
    port = ""
    for _ in range(120):
        time.sleep(0.5)
        if not port:
            ported = docker_run("port", container, "5432")
            if ported.returncode == 0:
                port = ported.stdout.strip().split(":")[-1]
        if not port:
            continue
        try:
            with psycopg.connect(
                f"postgresql://it_user:it-password@127.0.0.1:{port}/it_db",
                connect_timeout=2,
            ) as probe:
                probe.execute("SELECT 1")
            return port
        except psycopg.OperationalError:
            continue  # entrypoint restart between init phase and final server
    raise AssertionError(f"container {container} never became ready")


def applied_count(dsn: str, directory: Path) -> int:
    with psycopg.connect(dsn, autocommit=True) as conn:
        return migrate.apply_pending_files(
            migrate.PsycopgMigrationConnection(conn), directory
        )


def run_script(dsn: str, directory: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(REPO / ".venv" / "bin" / "python"),
            "-m", "workflow.migrate",
            "--migrations-dir", str(directory),
        ],
        capture_output=True, text=True, cwd=REPO,
        env={"DATABASE_URL": dsn, "PATH": "/usr/bin:/bin"},
    )


def public_tables(dsn: str) -> set[str]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public'"
        )
        rows = cur.fetchall()
    return {str(row[0]) for row in rows}


class TestApplyIdempotency:
    def test_ac1_fresh_db_applies_all_then_re_run_applies_nothing(
        self, pg_dsn: str, tmp_path: Path
    ) -> None:
        directory = tmp_path / "two"
        directory.mkdir()
        (directory / "0001_a.sql").write_text("CREATE TABLE first(id int);")
        (directory / "0002_b.sql").write_text("CREATE TABLE second(id int);")
        assert applied_count(pg_dsn, directory) == 2
        assert applied_count(pg_dsn, directory) == 0

    def test_ac1_empty_dir_tracks_only_schema_migrations(
        self, pg_dsn: str, tmp_path: Path
    ) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        assert applied_count(pg_dsn, empty) == 0
        tables = public_tables(pg_dsn)
        assert "schema_migrations" in tables
        for name in ("triage_run", "run_step", "history", "approval"):
            assert name not in tables  # AC3: no speculative domain tables

    def test_ac1_bad_sql_script_exits_nonzero_and_marks_nothing(
        self, pg_dsn: str, tmp_path: Path
    ) -> None:
        directory = tmp_path / "broken"
        directory.mkdir()
        (directory / "0001_broken.sql").write_text("CREATE BAD;")
        proc = run_script(pg_dsn, directory)
        assert proc.returncode == migrate.EXIT_MIGRATION_FAILED
        assert "0001_broken" in proc.stderr
        # rollback: nothing tracked, table `bad` absent (AC1 no partial state)
        assert "schema_migrations" in [
            row[0]
            for row in _query(pg_dsn, "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='public'")
        ]
        assert _query(
            pg_dsn,
            "SELECT migration_id FROM schema_migrations WHERE migration_id='0001_broken'",
        ) == []

    def test_ac1_good_script_reports_applied_and_exits_zero(
        self, pg_dsn: str, tmp_path: Path
    ) -> None:
        directory = tmp_path / "good"
        directory.mkdir()
        (directory / "0001_ok.sql").write_text("CREATE TABLE kept(id int);")
        proc = run_script(pg_dsn, directory)
        assert proc.returncode == 0
        assert "applied 1" in proc.stdout
        proc2 = run_script(pg_dsn, directory)
        assert proc2.returncode == 0
        assert "applied 0" in proc2.stdout


def _query(dsn: str, sql: str) -> list[tuple[object, ...]]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql)
        return list(cur.fetchall())
