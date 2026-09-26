"""Story 2.7 real Postgres collection/persistence boundary checks."""

import uuid

import psycopg
import pytest

from tests.workflow.test_evidence_collection import Reader, REQUEST, Tokens
from tests.workflow.test_step_integration import lease_run, migrated, query
from workflow.evidence_collection import CollectionRequest, EvidenceCollector
from workflow.history import ImportRecord
from workflow.history_store import PostgresHistoryStore
from workflow.leases import LeaseLost
from workflow.run_states import RunState
from workflow.step_store import PostgresStepRecorder
from workflow.steps import StepTaskMismatchError
from workflow.thresholds import load_thresholds

pytestmark = pytest.mark.integration


def collection(pg_dsn: str) -> tuple[EvidenceCollector, CollectionRequest]:
    migrated(pg_dsn)
    run_id = uuid.uuid4()
    with psycopg.connect(pg_dsn) as conn:
        conn.execute("INSERT INTO triage_run (run_id, repo_id, workflow_run_id, run_attempt, state) VALUES (%s, 1, 20, 2, %s)", (run_id, RunState.DISTILLING.value))
    claim = lease_run(pg_dsn, run_id)
    history = PostgresHistoryStore(pg_dsn)
    history.import_seed([ImportRecord(1, REQUEST.test_id, REQUEST.error_type, REQUEST.top_stack_frames, RunState.DONE_REPORT)])
    request = CollectionRequest(REQUEST.identity, claim, REQUEST.test_id, REQUEST.error_type, REQUEST.top_stack_frames)
    collector = EvidenceCollector(Reader(), Tokens(), history, PostgresStepRecorder(pg_dsn), load_thresholds().distiller)
    return collector, request


def test_ac1_real_collection_pack_and_state_committed_together(pg_dsn: str) -> None:
    collector, request = collection(pg_dsn)
    pack = collector.collect_and_persist(request)
    assert len(pack.history_rows) == 1
    rows = query(pg_dsn, "SELECT output FROM run_step WHERE run_id = %s AND repo_id = %s", (request.claim.run_id, 1))
    assert rows == [(pack.model_dump(mode="json"),)]
    assert query(pg_dsn, "SELECT state FROM triage_run WHERE run_id = %s", (request.claim.run_id,)) == [("CLASSIFYING",)]


def test_ac1_real_collection_fault_rolls_back_pack_and_state(pg_dsn: str) -> None:
    collector, request = collection(pg_dsn)
    with psycopg.connect(pg_dsn) as conn:
        conn.execute("CREATE FUNCTION evidence_fail_state() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'fault'; END; $$ LANGUAGE plpgsql")
        conn.execute("CREATE TRIGGER evidence_fail_state BEFORE UPDATE OF state ON triage_run FOR EACH ROW EXECUTE FUNCTION evidence_fail_state()")
    with pytest.raises(psycopg.Error):
        collector.collect_and_persist(request)
    assert query(pg_dsn, "SELECT output FROM run_step WHERE run_id = %s", (request.claim.run_id,)) == []
    assert query(pg_dsn, "SELECT state FROM triage_run WHERE run_id = %s", (request.claim.run_id,)) == [("DISTILLING",)]


def test_ac3_real_collection_stale_owner_persists_nothing(pg_dsn: str) -> None:
    collector, request = collection(pg_dsn)
    lease_run(pg_dsn, request.claim.run_id, "new-owner")
    with pytest.raises(LeaseLost):
        collector.collect_and_persist(request)
    assert query(pg_dsn, "SELECT output FROM run_step WHERE run_id = %s", (request.claim.run_id,)) == []


def test_ac3_real_collection_unrelated_task_writes_nothing(pg_dsn: str) -> None:
    collector, request = collection(pg_dsn)
    with psycopg.connect(pg_dsn) as conn:
        conn.execute("UPDATE triage_run SET workflow_run_id = 99 WHERE run_id = %s", (request.claim.run_id,))
    with pytest.raises(StepTaskMismatchError):
        collector.collect_and_persist(request)
    assert query(pg_dsn, "SELECT output FROM run_step WHERE run_id = %s", (request.claim.run_id,)) == []
    assert query(pg_dsn, "SELECT state FROM triage_run WHERE run_id = %s", (request.claim.run_id,)) == [("DISTILLING",)]


def test_ac1_ac3_real_github_read_uses_configured_failed_attempt() -> None:
    import json
    import os
    from urllib.error import HTTPError
    from urllib.parse import urlsplit
    from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

    from gateway.events import RunIdentity
    from workflow.github_evidence import GitHubEvidenceReader, GitHubResponse

    names = ("TRIAGE_EVIDENCE_INSTALLATION_ID", "TRIAGE_EVIDENCE_REPO_ID", "TRIAGE_EVIDENCE_WORKFLOW_RUN_ID", "TRIAGE_EVIDENCE_RUN_ATTEMPT", "TRIAGE_EVIDENCE_INSTALLATION_TOKEN")
    if not all(os.environ.get(name) for name in names):
        pytest.skip("live GitHub evidence configuration unavailable; set TRIAGE_EVIDENCE_* identity and installation token")

    class NoTokenRedirect(HTTPRedirectHandler):
        def redirect_request(self, req: Request, fp: object, code: int, msg: str, headers: object, newurl: str) -> None:
            return None

    class LiveRequests:
        def get(self, path: str, token: str) -> GitHubResponse:
            request = Request("https://api.github.com" + path, headers={"Accept": "application/vnd.github+json", "Authorization": "Bearer " + token})
            try:
                with build_opener(NoTokenRedirect()).open(request, timeout=30) as response:
                    content = response.read().decode("utf-8")
                    has_next = 'rel="next"' in response.headers.get("Link", "")
            except HTTPError as exc:
                if exc.code != 302 or not path.endswith("/logs"):
                    raise
                location = exc.headers["Location"]
                if urlsplit(location).scheme != "https":
                    raise AssertionError("GitHub log redirect is not HTTPS") from exc
                # AD-16: the signed download receives no authorization header.
                with urlopen(location, timeout=30) as response:
                    return GitHubResponse(text=response.read().decode("utf-8"))
            body = json.loads(content)
            assert isinstance(body, dict)
            return GitHubResponse(body, has_next=has_next)

    identity = RunIdentity(*(int(os.environ[name]) for name in names[:4]))
    evidence = GitHubEvidenceReader(LiveRequests()).collect(identity, os.environ[names[4]])
    assert evidence.failed.repo_id == identity.repo_id
    assert evidence.failed.run_id == identity.workflow_run_id
    assert len(evidence.failed.head_sha) == 40
    assert len(evidence.last_green) == 40
