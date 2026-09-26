"""Read-only GitHub evidence adapter; authority comes from task identity (AD-15).

The request boundary owns HTTP, timeouts and redirects. It must never attach
an installation token to a redirect outside api.github.com (AD-16).
"""

import base64
import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, cast
from urllib.parse import quote, urlencode

from pydantic import TypeAdapter

from contracts.citations import Sha40
from contracts.evidence import CommitRecord
from gateway.events import RunIdentity
from workflow.evidence import (
    ChangedCommit,
    WorkflowRun,
    imported_paths,
    latest_matching_success,
    repository_path,
    select_baseline,
)

_PAGE_SIZE = 100
_SHA = TypeAdapter(Sha40)
_FRAME_PATH = re.compile(r'File "([^"\n]+)", line \d+|(?:^|\s)([\w./-]+\.py):\d+')
_TEST_PATH = re.compile(r"(?:^|\s)([\w./-]+\.py)::")


class EvidenceReadError(Exception):
    """Definitive malformed or foreign evidence refusal (AD-22)."""

    retryable = False


@dataclass(frozen=True)
class GitHubResponse:
    body: dict[str, object] = field(default_factory=dict)
    text: str = ""
    has_next: bool = False


class GitHubRequests(Protocol):
    def get(self, path: str, token: str) -> GitHubResponse: ...


@dataclass(frozen=True)
class CollectedEvidence:
    failed: WorkflowRun
    last_green: str
    commits: tuple[ChangedCommit, ...]
    raw_log: str = field(repr=False)
    evidence_files: tuple[str, ...]
    metrics: dict[str, float]


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise EvidenceReadError("expected GitHub object")
    return cast(Mapping[str, object], value)


def _items(body: Mapping[str, object], key: str) -> list[Mapping[str, object]]:
    value = body.get(key)
    if not isinstance(value, list):
        raise EvidenceReadError(f"missing GitHub list {key}")
    return [_mapping(item) for item in value]


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvidenceReadError("invalid GitHub identifier")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise EvidenceReadError("missing GitHub text")
    return value


def _sha(value: object) -> str:
    try:
        return _SHA.validate_python(value)
    except ValueError as exc:
        raise EvidenceReadError("invalid full GitHub SHA") from exc


def _date(value: object) -> datetime:
    try:
        result = datetime.fromisoformat(_text(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceReadError("invalid GitHub timestamp") from exc
    if result.tzinfo is None:
        raise EvidenceReadError("GitHub timestamp lacks timezone")
    return result


def _run(body: Mapping[str, object], repo_id: int) -> WorkflowRun:
    if _integer(_mapping(body.get("repository")).get("id")) != repo_id:
        raise EvidenceReadError("workflow run belongs to another repository")
    return WorkflowRun(
        repo_id,
        _integer(body.get("id")),
        _integer(body.get("workflow_id")),
        _text(body.get("head_branch")),
        _sha(body.get("head_sha")),
        _date(body.get("created_at")),
        _text(body.get("conclusion")),
    )


def _paths(log: str, repo_name: str) -> tuple[str, ...]:
    frames = [match.group(1) or match.group(2) for match in _FRAME_PATH.finditer(log)]
    try:
        resolved = {
            repository_path(path, repo_name)
            for path in frames + _TEST_PATH.findall(log)
        }
    except ValueError as exc:
        raise EvidenceReadError("invalid evidence path") from exc
    return tuple(sorted(path for path in resolved if path is not None))


class GitHubEvidenceReader:
    """Collect one failed attempt with a caller-owned, per-step token."""

    def __init__(self, requests: GitHubRequests) -> None:
        self._requests = requests

    def _pages(self, path: str, token: str, key: str) -> list[Mapping[str, object]]:
        items: list[Mapping[str, object]] = []
        page = 1
        total: int | None = None
        while True:
            separator = "&" if "?" in path else "?"
            response = self._requests.get(
                f"{path}{separator}per_page={_PAGE_SIZE}&page={page}", token
            )
            if (
                key == "files"
                and response.body.get("url") != f"https://api.github.com{path}"
            ):
                raise EvidenceReadError("commit page repository scope mismatch")
            if key == "commits":
                _validate_comparison(response.body, path)
                total = _integer(response.body.get("total_commits"))
            items.extend(_items(response.body, key))
            if not response.has_next:
                if total is not None and total != len(items):
                    raise EvidenceReadError("incomplete comparison range")
                return items
            page += 1

    def collect(self, identity: RunIdentity, token: str) -> CollectedEvidence:
        repository = self._requests.get(f"/repositories/{identity.repo_id}", token).body
        if _integer(repository.get("id")) != identity.repo_id:
            raise EvidenceReadError("task repository scope mismatch")
        name = _text(repository.get("full_name"))
        if re.fullmatch(r"[\w.-]+/[\w.-]+", name) is None:
            raise EvidenceReadError("invalid repository name")
        root = f"/repos/{name}"
        path = (
            f"{root}/actions/runs/{identity.workflow_run_id}"
            f"/attempts/{identity.run_attempt}"
        )
        body = self._requests.get(path, token).body
        failed = _run(body, identity.repo_id)
        if (
            failed.run_id != identity.workflow_run_id
            or _integer(body.get("run_attempt")) != identity.run_attempt
        ):
            raise EvidenceReadError("task run or attempt mismatch")
        if failed.conclusion != "failure":
            raise EvidenceReadError("task is not a failed workflow run")
        query = urlencode({"status": "success", "branch": failed.branch})
        runs = self._pages(
            f"{root}/actions/runs?{query}",
            token,
            "workflow_runs",
        )
        successes = [_run(run, identity.repo_id) for run in runs]
        matching = latest_matching_success(failed, successes)
        default_branch = quote(_text(repository.get("default_branch")), safe="")
        default_head = (
            failed.head_sha
            if matching
            else _sha(
                self._requests.get(
                    f"{root}/commits/{default_branch}",
                    token,
                ).body.get("sha")
            )
        )
        baseline = select_baseline(failed, successes, default_head)
        commits = self._commits(root, baseline, failed.head_sha, token)
        raw_log, metrics = self._logs(path, root, token)
        paths = _paths(raw_log, name.split("/", 1)[1])
        evidence_files = self._imports(root, failed.head_sha, paths, token)
        return CollectedEvidence(
            failed, baseline, tuple(commits), raw_log, evidence_files, metrics
        )

    def _commits(
        self, root: str, baseline: str, head: str, token: str
    ) -> list[ChangedCommit]:
        if baseline == head:
            return []
        comparison = self._pages(
            f"{root}/compare/{baseline}...{head}", token, "commits"
        )
        shas = [_sha(item.get("sha")) for item in comparison]
        if shas and shas[-1] != head:
            raise EvidenceReadError("comparison head revision mismatch")
        if len(set(shas)) != len(shas):
            raise EvidenceReadError("duplicate comparison commit")
        return [self._commit(root, sha, token) for sha in shas]

    def _commit(self, root: str, sha: str, token: str) -> ChangedCommit:
        path = f"{root}/commits/{sha}"
        body = self._requests.get(path, token).body
        if (
            _sha(body.get("sha")) != sha
            or body.get("url") != f"https://api.github.com{path}"
        ):
            raise EvidenceReadError("commit repository or SHA mismatch")
        files = self._pages(path, token, "files")
        author = body.get("author")
        commit = _mapping(body.get("commit"))
        login = (
            _mapping(author).get("login")
            if author is not None
            else _mapping(commit.get("author")).get("name")
        )
        record = CommitRecord(
            sha=sha, message=_text(commit.get("message")), author_login=_text(login)
        )
        return ChangedCommit(
            record, tuple(_text(item.get("filename")) for item in files)
        )

    def _logs(
        self, attempt_path: str, root: str, token: str
    ) -> tuple[str, dict[str, float]]:
        jobs = self._pages(f"{attempt_path}/jobs", token, "jobs")
        logs: list[str] = []
        metrics: dict[str, float] = {}
        for job in sorted(jobs, key=lambda job: _integer(job.get("id"))):
            job_id = _integer(job.get("id"))
            expected_run = int(attempt_path.split("/runs/", 1)[1].split("/", 1)[0])
            if (
                _integer(job.get("run_id")) != expected_run
                or _integer(job.get("run_attempt"))
                != int(attempt_path.rsplit("/", 1)[1])
                or job.get("url")
                != f"https://api.github.com{root}/actions/jobs/{job_id}"
            ):
                raise EvidenceReadError("job task repository or run mismatch")
            logs.append(
                self._requests.get(f"{root}/actions/jobs/{job_id}/logs", token).text
            )
            if (
                job.get("started_at") is not None
                and job.get("completed_at") is not None
            ):
                duration = (
                    _date(job["completed_at"]) - _date(job["started_at"])
                ).total_seconds()
                if duration < 0:
                    raise EvidenceReadError("negative job duration")
                metrics[f"job_{job_id}_duration_seconds"] = duration
        return "\n".join(logs), metrics

    def _imports(
        self, root: str, head: str, paths: tuple[str, ...], token: str
    ) -> tuple[str, ...]:
        tests = [
            path
            for path in paths
            if path.endswith(".py")
            and (
                path.startswith("tests/") or path.rsplit("/", 1)[-1].startswith("test_")
            )
        ]
        if not tests:
            return paths
        available = self._tree_files(root, head, token)
        imports: set[str] = set(paths)
        for test in tests:
            if test not in available:
                continue
            source = self._source(root, head, test, available[test], token)
            try:
                imports.update(imported_paths(source, test, available))
            except SyntaxError as exc:
                raise EvidenceReadError("invalid test source") from exc
        return tuple(sorted(imports))

    def _tree_files(self, root: str, head: str, token: str) -> dict[str, str]:
        commit_path = f"{root}/commits/{head}"
        commit = self._requests.get(commit_path, token).body
        if (
            _sha(commit.get("sha")) != head
            or commit.get("url") != f"https://api.github.com{commit_path}"
        ):
            raise EvidenceReadError("head commit revision or repository mismatch")
        pointer = _mapping(_mapping(commit.get("commit")).get("tree"))
        tree_sha = _sha(pointer.get("sha"))
        tree_path = f"{root}/git/trees/{tree_sha}"
        if pointer.get("url") != f"https://api.github.com{tree_path}":
            raise EvidenceReadError("commit tree repository mismatch")
        tree = self._requests.get(f"{tree_path}?recursive=1", token).body
        if (
            _sha(tree.get("sha")) != tree_sha
            or tree.get("url") != f"https://api.github.com{tree_path}"
        ):
            raise EvidenceReadError("tree revision or repository mismatch")
        if tree.get("truncated") is not False:
            raise EvidenceReadError("incomplete repository file tree")
        return {
            _text(item.get("path")): _sha(item.get("sha"))
            for item in _items(tree, "tree")
            if item.get("type") == "blob"
        }

    def _source(self, root: str, head: str, test: str, blob: str, token: str) -> str:
        encoded = quote(test, safe="/")
        path = f"{root}/contents/{encoded}?ref={head}"
        body = self._requests.get(path, token).body
        expected_html = (
            f"https://github.com/{root.removeprefix('/repos/')}/blob/{head}/{encoded}"
        )
        if (
            body.get("url") != f"https://api.github.com{path}"
            or body.get("html_url") != expected_html
            or body.get("path") != test
            or _sha(body.get("sha")) != blob
            or body.get("git_url") != f"https://api.github.com{root}/git/blobs/{blob}"
        ):
            raise EvidenceReadError("content repository, path or revision mismatch")
        if body.get("encoding") != "base64" or body.get("type") != "file":
            raise EvidenceReadError("invalid content encoding or type")
        try:
            content = base64.b64decode(
                "".join(_text(body.get("content")).split()), validate=True
            )
            actual_blob = hashlib.sha1(
                b"blob " + str(len(content)).encode() + b"\0" + content
            ).hexdigest()
            if actual_blob != blob:
                raise EvidenceReadError("content blob revision mismatch")
            return content.decode("utf-8")
        except (ValueError, UnicodeError) as exc:
            raise EvidenceReadError("invalid test source") from exc


def _validate_comparison(body: Mapping[str, object], path: str) -> None:
    root, revision = path.split("/compare/", 1)
    baseline, _head = revision.split("...", 1)
    base = _mapping(body.get("base_commit"))
    if (
        body.get("url") != f"https://api.github.com{path}"
        or _sha(base.get("sha")) != baseline
        or base.get("url") != f"https://api.github.com{root}/commits/{baseline}"
    ):
        raise EvidenceReadError("comparison endpoints or repository mismatch")
