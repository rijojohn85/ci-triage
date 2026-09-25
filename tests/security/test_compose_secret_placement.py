"""Story 0.3 AC2 tests: compose secret placement + migration-free schema.

Parses deploy/compose.yaml (static, no Docker) and asserts the AD-16
secret-placement contract: each scoped key is present (by name, as an
interpolation) only on its owning services, never as a literal value. Also
asserts the AC1 Compose gating pattern (workers watch the one-shot migrate
job with service_completed_successfully) and that no speculative domain
tables or a2a-db/DatabaseTaskStore schema are deployed (AD-4 / epics AC3).
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
COMPOSE = REPO / "deploy" / "compose.yaml"
MIGRATIONS_DIR = REPO / "deploy" / "migrations"

SECRET_SCOPES: dict[str, set[str]] = {
    "GITHUB_APP_PRIVATE_KEY": {"gateway", "orchestrator"},
    "GITHUB_WEBHOOK_SECRET": {"gateway"},
    "GITHUB_APP_ID": {"gateway", "orchestrator"},
    "GITHUB_APP_INSTALLATION_ID": {"gateway", "orchestrator"},
    # AD-16 / epics 0.3 AC2: the Claude key lives only in the three Claude
    # agents (the orchestrator reaches models through them via A2A).
    "ANTHROPIC_API_KEY": {"analyzer", "proposer", "reviewer"},
    "TYPESAFE_API_KEY": {"jev", "orchestrator"},
    # Workflow persistence keeps its own DSN; spoke agents never get DB access.
    "DATABASE_URL": {"gateway", "orchestrator", "migrate"},
    "POSTGRES_PASSWORD": {"postgres"},
    "POSTGRES_USER": {"postgres"},
    "POSTGRES_DB": {"postgres"},
}

EXPECTED_SERVICES = {
    "postgres", "migrate", "gateway", "orchestrator",
    "jev", "analyzer", "proposer", "reviewer",
}

WORKER_SERVICES = ("gateway", "orchestrator")


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def services(compose: dict[str, Any]) -> dict[str, Any]:
    return compose["services"]


def env_of(service: dict[str, Any]) -> dict[str, str]:
    env = service.get("environment") or {}
    assert isinstance(env, dict), "compose must use map-form environment"
    return env


class TestSecretPlacement:
    def test_ac2_expected_service_set_is_exact(
        self, services: dict[str, Any]
    ) -> None:
        assert set(services) == EXPECTED_SERVICES, (
            "a new service must join the scope review (tests security before)"
        )

    def test_ac2_no_scoped_secret_outside_owners(
        self, services: dict[str, Any]
    ) -> None:
        for name, service in services.items():
            for key in env_of(service):
                if key in SECRET_SCOPES:
                    assert name in SECRET_SCOPES[key], (
                        f"{key} must not be on {name} (owners: {sorted(SECRET_SCOPES[key])})"
                    )

    def test_ac2_scoped_keys_map_to_their_service_names_in_compose(
        self, services: dict[str, Any]
    ) -> None:
        """The canonical three from epics 0.3 AC2, name-for-name."""
        assert "GITHUB_APP_PRIVATE_KEY" in env_of(services["gateway"])
        assert "GITHUB_APP_PRIVATE_KEY" in env_of(services["orchestrator"])
        for agent in ("analyzer", "proposer", "reviewer"):
            assert "ANTHROPIC_API_KEY" in env_of(services[agent])
        assert "ANTHROPIC_API_KEY" not in env_of(services["orchestrator"])
        assert "ANTHROPIC_API_KEY" not in env_of(services["gateway"])
        assert "TYPESAFE_API_KEY" in env_of(services["jev"])
        assert "TYPESAFE_API_KEY" in env_of(services["orchestrator"])
        assert "TYPESAFE_API_KEY" not in env_of(services["analyzer"])
        assert "DATABASE_URL" in env_of(services["migrate"])
        for agent in ("jev", "analyzer", "proposer", "reviewer"):
            assert "DATABASE_URL" not in env_of(services[agent])

    def test_ac2_no_literal_secret_values(self, services: dict[str, Any]) -> None:
        for name, service in services.items():
            for key, value in env_of(service).items():
                if key in SECRET_SCOPES:
                    assert "${" in str(value), (
                        f"{name}/{key} must interpolate from env, not set a literal"
                    )


class TestPostgresAndMigrationGating:
    def test_ac1_postgres_is_pinned_18_with_healthcheck(
        self, services: dict[str, Any]
    ) -> None:
        postgres = services["postgres"]
        assert postgres["image"].startswith("postgres:18")
        assert postgres.get("healthcheck", {}).get("test")

    def test_ac1_migrate_waits_for_healthy_postgres(
        self, services: dict[str, Any]
    ) -> None:
        depends = services["migrate"]["depends_on"]["postgres"]
        assert depends["condition"] == "service_healthy"

    def test_ac1_workers_start_only_after_migrate(
        self, services: dict[str, Any]
    ) -> None:
        for worker in WORKER_SERVICES:
            entry = services[worker]["depends_on"]["migrate"]
            assert entry["condition"] == "service_completed_successfully", (
                f"{worker} must wait for the one-shot migrate job (AC1)"
            )


class TestNoSpeculativeSchema:
    def test_ac3_no_speculative_domain_tables_triage_run_allowlisted(self) -> None:
        # Story 0.3 AC3 forbade speculative domain tables; story 2.1 legitimately
        # adds `triage_run` via 0001 — only that one file may name it. The
        # remaining domain tables still arrive with their consuming stories.
        sql_files = list(MIGRATIONS_DIR.glob("*.sql"))
        forbidden = re.compile(
            r"\b(run_step|history|approval|a2a_db|a2a_db_"
            r"|DatabaseTaskStore)\b",
            re.IGNORECASE,
        )
        offending = [
            f.name
            for f in sql_files
            if forbidden.search(f.read_text(encoding="utf-8"))
        ]
        assert offending == []
        allowed_triage_run = [
            "0001_triage_run.sql",  # story 2.1 (AD-1, AD-17)
            "0003_triage_run_lease.sql",  # story 1.2: ALTER ... lease columns (AD-23)
        ]
        declared = sorted(
            f.name
            for f in sql_files
            if re.search(r"\btriage_run\b", f.read_text(encoding="utf-8"), re.IGNORECASE)
        )
        assert declared == allowed_triage_run
        # no a2a-db/taskstore service either
        compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
        blob = str(compose)
        for name in ("a2a_db", "a2a-db", "DatabaseTaskStore"):
            assert name not in blob


class TestEnvFiles:
    def test_ac2_no_env_committed(self) -> None:
        import subprocess

        files = subprocess.run(
            ["git", "ls-files"], capture_output=True, text=True, check=True,
            cwd=REPO,
        ).stdout.splitlines()
        offenders = [
            f for f in files
            if f == ".env" or (f.startswith(".env.") and f != ".env.example")
        ]
        assert offenders == []

    def test_ac2_env_example_holds_names_only(self) -> None:
        example = (REPO / ".env.example").read_text(encoding="utf-8")
        for line in example.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            assert value.strip() == "", (
                f".env.example must carry names only; {key} has a value"
            )
        for key in SECRET_SCOPES:
            if key.startswith("POSTGRES_"):
                continue  # postgres-local names live in compose defaults
            assert re.search(rf"^{key}=", example, re.MULTILINE), key
