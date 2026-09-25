"""Smoke test: a real signed `workflow_run` delivery reaches the gateway and
enqueues exactly once (story 1.3, AC1; AD-17, AD-25).

Split into a pure `build_receipt()` (unit-tested, secret-free by
construction — it never receives a secret value, so it can never write one)
and an I/O `main()` (integration-only, needs Compose + smee + the demo repo
running). `main()` reads `DATABASE_URL` from `.env` itself; a secret is never
passed as a CLI arg and never printed (AD-16).

Usage (Compose up, smee tunnel forwarding, `.env` populated):
    python scripts/smoke_signed_tunnel.py \
        --org rijojohn85-dev --repo triage-demo-py --repo-id 1387450356 \
        [--workflow ci.yml] [--ref main] [--timeout-seconds 180]

Steps: trigger a failing run in the demo repo via `gh workflow run` (the
human's own gh auth, no App key), poll Postgres for exactly one
`webhook_delivery` row (joined to its `triage_run`) received since the
script started, and write a receipt under `deploy/smoke/` holding status
and run reference only.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
RECEIPT_DIR = ROOT / "deploy" / "smoke"
DEFAULT_ORG = "rijojohn85-dev"
DEFAULT_REPO = "triage-demo-py"
DEFAULT_WORKFLOW = "ci.yml"
DEFAULT_REF = "main"
DEFAULT_TIMEOUT_SECONDS = 180
POLL_INTERVAL_SECONDS = 3
CLOCK_SKEW_MARGIN_SECONDS = 5


class SmokeError(Exception):
    """The smoke run failed: trigger, poll timeout, or more than one match."""


# ---------------------------------------------------------------------------
# Pure (unit-tested): never sees a secret, so the receipt can never leak one
# ---------------------------------------------------------------------------


def build_receipt(status: str, run_id: str, delivery_id: str) -> dict[str, str]:
    """A secret-free record of one smoke run: status + run reference only."""
    return {
        "status": status,
        "run_id": run_id,
        "delivery_id": delivery_id,
    }


# ---------------------------------------------------------------------------
# I/O: .env, gh, Postgres (live path is @pytest.mark.integration only)
# ---------------------------------------------------------------------------


def read_env_file(path: Path = ENV_PATH) -> dict[str, str]:
    """Parse `.env` as simple KEY=VALUE lines; values never leave this dict
    except into the one connection string `main()` uses (never printed)."""
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def database_url(env: dict[str, str]) -> str:
    value = env.get("DATABASE_URL", "")
    if not value:
        raise SmokeError("DATABASE_URL missing from .env")
    return value


GH_TIMEOUT_SECONDS = 30


def gh(*args: str) -> str:
    """Run a `gh` subcommand; raise with gh's own error, never a secret."""
    try:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=GH_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise SmokeError(
            f"gh {' '.join(args)} timed out after {GH_TIMEOUT_SECONDS}s"
        ) from exc
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()[-1] if result.stderr else "?"
        raise SmokeError(f"gh {' '.join(args)} failed: {detail}")
    return result.stdout


def trigger_failing_run(org: str, repo: str, workflow: str, ref: str) -> None:
    """Dispatch `workflow` on `ref`; the demo repo seed's `ci.yml` on the
    scenario branches is expected to end `completed`/`failure` (AD-25:
    smee + synthetic repo only — never a real user-facing repo)."""
    gh("workflow", "run", workflow, "--repo", f"{org}/{repo}", "--ref", ref)


@dataclass(frozen=True)
class DeliveryMatch:
    delivery_id: str
    run_id: str


_POLL_SQL = """
SELECT wd.delivery_id, tr.run_id::text
FROM webhook_delivery wd
JOIN triage_run tr
  ON tr.repo_id = wd.repo_id
 AND tr.workflow_run_id = wd.workflow_run_id
 AND tr.run_attempt = wd.run_attempt
WHERE wd.repo_id = %s AND wd.received_at > %s
ORDER BY wd.received_at DESC
"""


def poll_for_single_delivery(
    dsn: str, repo_id: int, since: datetime, timeout_seconds: int
) -> DeliveryMatch:
    """Poll until exactly one delivery lands after `since`; raise on
    timeout or on more than one match (AC1: exactly one enqueued)."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with psycopg.connect(dsn) as conn, conn.cursor() as cursor:
            cursor.execute(_POLL_SQL, (repo_id, since))
            rows = cursor.fetchall()
        if len(rows) == 1:
            delivery_id, run_id = rows[0]
            return DeliveryMatch(delivery_id=str(delivery_id), run_id=str(run_id))
        if len(rows) > 1:
            raise SmokeError(f"expected exactly one delivery, found {len(rows)}")
        time.sleep(POLL_INTERVAL_SECONDS)
    raise SmokeError("timed out waiting for a triage_run to be enqueued")


def write_receipt(receipt: dict[str, str]) -> Path:
    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    path = RECEIPT_DIR / f"receipt-{time.time_ns()}.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", default=DEFAULT_ORG)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument(
        "--repo-id",
        type=int,
        required=True,
        help="numeric GitHub repo id (see test-data/demo-repo.md)",
    )
    parser.add_argument("--workflow", default=DEFAULT_WORKFLOW)
    parser.add_argument(
        "--ref",
        default=DEFAULT_REF,
        help=(
            "branch/ref to dispatch on; must already be arranged to end in "
            "failure (the gateway only enqueues on conclusion=failure) — "
            "the default 'main' is today's green baseline and will time out"
        ),
    )
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    env = read_env_file()
    try:
        dsn = database_url(env)
        started_at = datetime.now(timezone.utc) - timedelta(
            seconds=CLOCK_SKEW_MARGIN_SECONDS
        )
        trigger_failing_run(args.org, args.repo, args.workflow, args.ref)
        match = poll_for_single_delivery(
            dsn, args.repo_id, started_at, args.timeout_seconds
        )
    except SmokeError as exc:
        receipt = build_receipt(status=f"FAIL: {exc}", run_id="", delivery_id="")
        path = write_receipt(receipt)
        print(f"SMOKE FAIL: {exc} (receipt: {path})")
        return 1
    except (psycopg.Error, OSError) as exc:
        # Never interpolate the raw exception text: psycopg errors commonly
        # echo the DSN (including the password from .env) and OSError may
        # wrap subprocess/filesystem detail — only the exception's type name
        # is safe to surface (AD-16: secrets never printed).
        receipt = build_receipt(
            status=f"FAIL: {type(exc).__name__}", run_id="", delivery_id=""
        )
        path = write_receipt(receipt)
        print(f"SMOKE FAIL: {type(exc).__name__} (receipt: {path})")
        return 1
    receipt = build_receipt(
        status="PASS", run_id=match.run_id, delivery_id=match.delivery_id
    )
    path = write_receipt(receipt)
    print(
        f"SMOKE PASS: run {match.run_id} delivery {match.delivery_id} (receipt: {path})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
