"""Story 1.3 AC1 tests: `build_receipt` is secret-free (unit), plus the live
end-to-end smoke path (integration only — needs Compose + smee + demo repo).

The unit tests load the module the same way test_verify_demo_repo.py does,
so `make check` never imports a script package (scripts/ has no __init__).
"""

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "smoke_signed_tunnel.py"

_spec = importlib.util.spec_from_file_location("smoke_signed_tunnel", SCRIPT)
assert _spec is not None and _spec.loader is not None
smoke = importlib.util.module_from_spec(_spec)
sys.modules["smoke_signed_tunnel"] = smoke
_spec.loader.exec_module(smoke)

# A realistic-looking secret value the receipt must never contain, whatever
# path produced it (AD-16). Not a real credential.
FAKE_SECRET = "ghs_S3cr3tWebhookValueThatMustNeverAppearInAnyReceipt"


# ---------------------------------------------------------------------------
# AC1: build_receipt is pure and secret-free
# ---------------------------------------------------------------------------


def test_ac1_build_receipt_contains_status_and_run_reference() -> None:
    receipt = smoke.build_receipt(
        status="PASS", run_id="0199abc-run", delivery_id="d-1"
    )
    assert receipt["status"] == "PASS"
    assert receipt["run_id"] == "0199abc-run"
    assert receipt["delivery_id"] == "d-1"


def test_ac1_build_receipt_never_contains_a_secret_substring() -> None:
    receipt = smoke.build_receipt(
        status="PASS", run_id="0199abc-run", delivery_id="d-1"
    )
    serialized = " ".join(receipt.values())
    assert FAKE_SECRET not in serialized


def test_ac1_build_receipt_signature_has_no_secret_parameter() -> None:
    # A structural guarantee (not just an assertion on one call): the
    # function's parameters are status/run_id/delivery_id only, so no
    # caller can pass a secret in even by mistake.
    import inspect

    params = list(inspect.signature(smoke.build_receipt).parameters)
    assert params == ["status", "run_id", "delivery_id"]


def test_ac1_read_env_file_parses_key_value_lines(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\nDATABASE_URL=postgresql://u:p@localhost/db\n\nWORKER_ID=w1\n",
        encoding="utf-8",
    )
    values = smoke.read_env_file(env_file)
    assert values == {
        "DATABASE_URL": "postgresql://u:p@localhost/db",
        "WORKER_ID": "w1",
    }


def test_ac1_read_env_file_missing_file_returns_empty() -> None:
    assert smoke.read_env_file(Path("/nonexistent/.env")) == {}


def test_ac1_database_url_missing_raises_smoke_error() -> None:
    with pytest.raises(smoke.SmokeError):
        smoke.database_url({})


def test_ac1_database_url_returns_configured_value() -> None:
    assert smoke.database_url({"DATABASE_URL": "postgresql://x"}) == "postgresql://x"


def test_ac1_poll_for_single_delivery_raises_on_more_than_one_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCursor:
        def execute(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        def fetchall(self) -> list[tuple[str, str]]:
            return [("d-1", "r-1"), ("d-2", "r-2")]

        def __enter__(self) -> "FakeCursor":
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    class FakeConn:
        def cursor(self) -> FakeCursor:
            return FakeCursor()

        def __enter__(self) -> "FakeConn":
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr(smoke.psycopg, "connect", lambda *_a, **_k: FakeConn())
    with pytest.raises(smoke.SmokeError, match="exactly one"):
        smoke.poll_for_single_delivery(
            "postgresql://unused", 1, datetime.now(timezone.utc), timeout_seconds=1
        )


def test_ac1_poll_for_single_delivery_times_out_when_nothing_arrives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCursor:
        def execute(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        def fetchall(self) -> list[tuple[str, str]]:
            return []

        def __enter__(self) -> "FakeCursor":
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    class FakeConn:
        def cursor(self) -> FakeCursor:
            return FakeCursor()

        def __enter__(self) -> "FakeConn":
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr(smoke.psycopg, "connect", lambda *_a, **_k: FakeConn())
    with pytest.raises(smoke.SmokeError, match="timed out"):
        smoke.poll_for_single_delivery(
            "postgresql://unused", 1, datetime.now(timezone.utc), timeout_seconds=0
        )


def test_ac1_write_receipt_writes_json_with_no_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(smoke, "RECEIPT_DIR", tmp_path / "smoke")
    receipt = smoke.build_receipt(status="PASS", run_id="r-1", delivery_id="d-1")
    path = smoke.write_receipt(receipt)
    content = path.read_text(encoding="utf-8")
    assert FAKE_SECRET not in content
    assert '"status": "PASS"' in content


# ---------------------------------------------------------------------------
# AC1: gh() / trigger_failing_run() (unit — real precedent in
# tests/scripts/test_verify_demo_repo.py::test_ac4_cli_exits_nonzero_on_mismatch)
# ---------------------------------------------------------------------------


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_ac1_trigger_failing_run_builds_expected_gh_argv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_run(argv: list[str], **kwargs: Any) -> _FakeCompletedProcess:
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return _FakeCompletedProcess(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(smoke.subprocess, "run", fake_run)
    smoke.trigger_failing_run("my-org", "my-repo", "ci.yml", "scratch-branch")
    assert captured["argv"] == [
        "gh",
        "workflow",
        "run",
        "ci.yml",
        "--repo",
        "my-org/my-repo",
        "--ref",
        "scratch-branch",
    ]
    assert captured["kwargs"]["timeout"] == smoke.GH_TIMEOUT_SECONDS


def test_ac1_gh_raises_smoke_error_with_stderr_detail_on_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*_args: Any, **_kwargs: Any) -> _FakeCompletedProcess:
        return _FakeCompletedProcess(
            returncode=1, stdout="", stderr="some context\nHTTP 404: Not Found"
        )

    monkeypatch.setattr(smoke.subprocess, "run", fake_run)
    with pytest.raises(smoke.SmokeError, match="HTTP 404: Not Found"):
        smoke.gh("workflow", "run", "ci.yml")


def test_ac1_gh_raises_smoke_error_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: Any, **kwargs: Any) -> _FakeCompletedProcess:
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout", 0))

    monkeypatch.setattr(smoke.subprocess, "run", fake_run)
    with pytest.raises(smoke.SmokeError, match="timed out"):
        smoke.gh("workflow", "run", "ci.yml")


# ---------------------------------------------------------------------------
# AC1: main()'s except SmokeError branch writes a secret-free FAIL receipt
# ---------------------------------------------------------------------------


def test_ac1_main_writes_fail_receipt_with_empty_refs_and_no_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(smoke, "RECEIPT_DIR", tmp_path / "smoke")
    env_file = tmp_path / ".env"
    env_file.write_text(f"DATABASE_URL={FAKE_SECRET}\n", encoding="utf-8")
    monkeypatch.setattr(smoke, "ENV_PATH", env_file)

    def fake_trigger(*_args: Any, **_kwargs: Any) -> None:
        raise smoke.SmokeError("gh workflow run failed: boom")

    monkeypatch.setattr(smoke, "trigger_failing_run", fake_trigger)

    exit_code = smoke.main(
        ["--org", "o", "--repo", "r", "--repo-id", "1", "--timeout-seconds", "1"]
    )
    assert exit_code == 1

    receipts = list((tmp_path / "smoke").glob("receipt-*.json"))
    assert len(receipts) == 1
    content = receipts[0].read_text(encoding="utf-8")
    receipt = json.loads(content)
    assert receipt["status"].startswith("FAIL:")
    assert receipt["run_id"] == ""
    assert receipt["delivery_id"] == ""
    assert FAKE_SECRET not in content


# ---------------------------------------------------------------------------
# AC1: live end-to-end smoke run (integration only)
# ---------------------------------------------------------------------------

DEMO_ORG = "rijojohn85-dev"
DEMO_REPO = "triage-demo-py"
DEMO_REPO_ID = 1387450356


@pytest.mark.integration
def test_ac1_live_smoke_run_enqueues_exactly_one_triage_run() -> None:
    """Requires Compose + smee tunnel up and the demo repo reachable
    (`docker compose -f deploy/compose.yaml up -d --wait`, `.env` populated).
    Human-run per docs/USER-GUIDE.md; not part of `make check`.
    """
    exit_code = smoke.main(
        [
            "--org",
            DEMO_ORG,
            "--repo",
            DEMO_REPO,
            "--repo-id",
            str(DEMO_REPO_ID),
        ]
    )
    assert exit_code == 0
