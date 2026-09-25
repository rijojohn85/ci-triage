"""Shared pytest fixtures for the workflow tests (Docker postgres for the
marked integration tests; story 0.3's disposable-container pattern)."""

import secrets
import subprocess
import time
from collections.abc import Iterator

import psycopg
import pytest


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
