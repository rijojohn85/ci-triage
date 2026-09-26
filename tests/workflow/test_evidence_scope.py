"""Public collection scope, import and complete pagination regressions."""

import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.workflow.test_github_evidence import HEAD, IDENTITY, REPO, SHA, Requests
from tests.workflow.test_evidence_collection import Tokens, History, Recorder, REQUEST
from workflow.evidence_collection import EvidenceCollector
from workflow.github_evidence import GitHubEvidenceReader, GitHubResponse, EvidenceReadError
from workflow.thresholds import load_thresholds

ROOT = "/repos/org/repo"
TREE = "e" * 40
SECOND = "c" * 40
TEST = "tests/test_imports.py"
SOURCE = b"import pkg.one\nfrom pkg.two import value\nfrom .local import tool\nfrom pkg import three\n"
IMPORTS = ["pkg/one.py", "pkg/two.py", "tests/local.py", "pkg/three.py"]


class ScopedRequests(Requests):
    def __init__(
        self, log_path: str = TEST, source: bytes = SOURCE,
        changed_files: tuple[str, ...] = tuple(IMPORTS),
    ) -> None:
        super().__init__()
        self.log_path = log_path
        self.source = source
        self.changed_files = changed_files
        self.blob = hashlib.sha1(
            b"blob " + str(len(source)).encode() + b"\0" + source
        ).hexdigest()

    def get(self, path: str, token: str) -> GitHubResponse:
        if "/git/trees/" in path:
            self.calls.append(path)
            return GitHubResponse({"sha": TREE, "url": f"https://api.github.com{ROOT}/git/trees/{TREE}", "truncated": False,
                "tree": [{"path": name, "type": "blob", "sha": self.blob} for name in [TEST, *self.changed_files]]})
        if "/contents/" in path:
            self.calls.append(path)
            assert path == f"{ROOT}/contents/{TEST}?ref={HEAD}"
            return GitHubResponse({"path": TEST, "sha": self.blob, "type": "file", "encoding": "base64",
                "url": f"https://api.github.com{path}", "html_url": f"https://github.com/org/repo/blob/{HEAD}/{TEST}",
                "git_url": f"https://api.github.com{ROOT}/git/blobs/{self.blob}", "content": base64.b64encode(self.source).decode()})
        if path.endswith("/jobs/5/logs"):
            return GitHubResponse(text=f'ERROR failure\n  File "{self.log_path}", line 1')
        response = super().get(path, token)
        if "/compare/" in path:
            response.body.update({"url": f"https://api.github.com{ROOT}/compare/{SHA}...{HEAD}",
                "base_commit": {"sha": SHA, "url": f"https://api.github.com{ROOT}/commits/{SHA}"}})
        if "/commits/" in path:
            response.body["commit"]["tree"] = {"sha": TREE, "url": f"https://api.github.com{ROOT}/git/trees/{TREE}"}
            response.body["files"] = [{"filename": name} for name in self.changed_files]
        if "/attempts/2/jobs" in path:
            response.body["jobs"][0]["run_attempt"] = 2
        return response


def collector(requests: Requests) -> tuple[EvidenceCollector, Recorder]:
    recorder = Recorder()
    return EvidenceCollector(GitHubEvidenceReader(requests), Tokens(), History(), recorder, load_thresholds().distiller), recorder


@pytest.mark.parametrize(
    ("source", "changed_file"),
    [
        (b"import pkg.one\n", "pkg/one.py"),
        (b"from pkg.two import value\n", "pkg/two.py"),
        (b"from .local import tool\n", "tests/local.py"),
        (b"from pkg import three\n", "pkg/three.py"),
    ],
)
@pytest.mark.parametrize("path", [TEST, f"/home/runner/work/repo/repo/{TEST}", f"/runner/_work/repo/repo/{TEST}", f"D:\\a\\repo\\repo\\{TEST.replace('/', chr(92))}"])
def test_ac2_public_collection_resolves_normal_from_relative_imports_and_checkout_paths(
    path: str, source: bytes, changed_file: str,
) -> None:
    requests = ScopedRequests(path, source, (changed_file,))
    instance, _ = collector(requests)
    pack = instance.collect_and_persist(REQUEST)
    assert [(candidate.sha, candidate.changed_files) for candidate in pack.candidate_suspects] == [(HEAD, [changed_file])]
    assert f"{ROOT}/git/trees/{TREE}?recursive=1" in requests.calls
    assert f"{ROOT}/contents/{TEST}?ref={HEAD}" in requests.calls


@pytest.mark.parametrize("path", ["tests/../../foreign/test_a.py", "/home/runner/work/repo/repo/tests/../test_a.py"])
def test_ac3_traversal_path_refused_before_contents_read(path: str) -> None:
    requests = ScopedRequests(path)
    instance, recorder = collector(requests)
    with pytest.raises(EvidenceReadError, match="path"):
        instance.collect_and_persist(REQUEST)
    assert recorder.commits == []
    assert not any("/contents/" in call for call in requests.calls)


@pytest.mark.parametrize("fault", ["compare_url", "compare_base", "tree_url", "tree_revision", "content_url", "content_revision", "content_path", "content_blob", "job_attempt"])
def test_ac3_foreign_or_stale_response_refused_without_persistence(fault: str) -> None:
    class WrongScope(ScopedRequests):
        def get(self, path: str, token: str) -> GitHubResponse:
            response = super().get(path, token)
            if fault == "compare_url" and "/compare/" in path:
                response.body["url"] = "https://api.github.com/repos/other/repo/compare/" + SHA + "..." + HEAD
            if fault == "compare_base" and "/compare/" in path:
                response.body["base_commit"]["sha"] = SECOND
            if fault == "tree_url" and "/git/trees/" in path:
                response.body["url"] = "https://api.github.com/repos/other/repo/git/trees/" + TREE
            if fault == "tree_revision" and "/git/trees/" in path:
                response.body["sha"] = SECOND
            if fault == "content_url" and "/contents/" in path:
                response.body["url"] = "https://api.github.com/repos/other/repo/contents/" + TEST + "?ref=" + HEAD
            if fault == "content_revision" and "/contents/" in path:
                response.body["html_url"] = f"https://github.com/org/repo/blob/{SECOND}/{TEST}"
            if fault == "content_path" and "/contents/" in path:
                response.body["path"] = "tests/other.py"
            if fault == "content_blob" and "/contents/" in path:
                response.body["content"] = base64.b64encode(b"import foreign\n").decode()
            if fault == "job_attempt" and "/attempts/2/jobs" in path:
                response.body["jobs"][0]["run_attempt"] = 1
            return response

    instance, recorder = collector(WrongScope())
    with pytest.raises(EvidenceReadError):
        instance.collect_and_persist(REQUEST)
    assert recorder.commits == []


def test_ac1_ac2_public_collection_keeps_valid_later_run_commit_file_and_job_pages() -> None:
    class Pages(ScopedRequests):
        def get(self, path: str, token: str) -> GitHubResponse:
            if path.endswith("/jobs/6/logs"):
                return GitHubResponse(text="ERROR second job")
            query = parse_qs(urlsplit(path).query)
            page = int(query.get("page", ["1"])[0])
            if f"/commits/{SECOND}" in path:
                response = super().get(path.replace(SECOND, HEAD), token)
                response.body["sha"] = SECOND
                response.body["url"] = f"https://api.github.com{ROOT}/commits/{SECOND}"
            else:
                response = super().get(path, token)
            if "/actions/runs?" in path:
                if page == 1:
                    response.body["workflow_runs"][0].update({"head_sha": SECOND, "id": 9})
                return GitHubResponse(response.body, has_next=page == 1)
            if "/compare/" in path:
                response.body.update({"commits": [{"sha": SECOND if page == 1 else HEAD}], "total_commits": 2})
                return GitHubResponse(response.body, has_next=page == 1)
            if "/commits/" in path and "page" in query:
                response.body["files"] = [{"filename": "README.md" if page == 1 else "pkg/one.py"}]
                return GitHubResponse(response.body, has_next=page == 1)
            if "/attempts/2/jobs" in path:
                response.body["jobs"][0].update({"id": 5 if page == 1 else 6, "url": f"https://api.github.com{ROOT}/actions/jobs/{5 if page == 1 else 6}"})
                return GitHubResponse(response.body, has_next=page == 1)
            if path.endswith("/jobs/6/logs"):
                return GitHubResponse(text="ERROR second job")
            return response

    instance, _ = collector(Pages())
    pack = instance.collect_and_persist(REQUEST)
    assert pack.last_green == SHA
    assert [commit.sha for commit in pack.commits] == [SECOND, HEAD]
    assert [candidate.sha for candidate in pack.candidate_suspects] == [HEAD, SECOND]
    assert all(candidate.changed_files == ["README.md", "pkg/one.py"] for candidate in pack.candidate_suspects)
    assert set(pack.metrics) == {"job_5_duration_seconds", "job_6_duration_seconds"}
    assert any(line.text == "ERROR second job" for line in pack.distilled_log)
