"""Pure baseline and file-intersection evidence policy (AD-24)."""

import ast
import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

from pydantic import TypeAdapter

from contracts.citations import Sha40
from contracts.evidence import (
    CandidateSuspect,
    CommitRecord,
    DistilledLogLine,
    EvidencePack,
)


@dataclass(frozen=True)
class WorkflowRun:
    repo_id: int
    run_id: int
    workflow_id: int
    branch: str
    head_sha: str
    created_at: datetime
    conclusion: str


@dataclass(frozen=True)
class ChangedCommit:
    commit: CommitRecord
    files: tuple[str, ...]


def latest_matching_success(
    failed: WorkflowRun, runs: Sequence[WorkflowRun]
) -> WorkflowRun | None:
    """The single matching-success policy shared by selection and lazy reads."""
    matching = [
        run
        for run in runs
        if run.repo_id == failed.repo_id
        and run.workflow_id == failed.workflow_id
        and run.branch == failed.branch
        and run.conclusion == "success"
        and (run.created_at, run.run_id) < (failed.created_at, failed.run_id)
    ]
    return max(matching, key=lambda run: (run.created_at, run.run_id), default=None)


def select_baseline(
    failed: WorkflowRun, runs: Sequence[WorkflowRun], default_head: str
) -> str:
    matching = latest_matching_success(failed, runs)
    return TypeAdapter(Sha40).validate_python(
        matching.head_sha if matching else default_head
    )


def normalize_path(path: str) -> str:
    """Normalize repository-relative paths without guessing a dependency graph."""
    return str(PurePosixPath(path.replace("\\", "/")))


def rank_candidates(
    commits: Sequence[ChangedCommit], evidence_files: Sequence[str]
) -> list[CandidateSuspect]:
    relevant = {normalize_path(path) for path in evidence_files}
    intersecting = [
        (commit, {normalize_path(path) for path in commit.files} & relevant)
        for commit in commits
    ]
    ordered = sorted(
        (item for item in intersecting if item[1]),
        key=lambda item: (-len(item[1]), item[0].commit.sha),
    )
    return [
        CandidateSuspect(
            sha=commit.commit.sha,
            rank=rank,
            changed_files=sorted({normalize_path(path) for path in commit.files}),
        )
        for rank, (commit, _) in enumerate(ordered, 1)
    ]


def assemble_pack(
    repo_id: int,
    baseline: str,
    commits: Sequence[ChangedCommit],
    log: list[DistilledLogLine],
    evidence_files: Sequence[str],
) -> EvidencePack:
    return EvidencePack(
        repo_id=str(repo_id),
        last_green=baseline,
        distilled_log=log,
        commits=[item.commit for item in commits],
        candidate_suspects=rank_candidates(commits, evidence_files),
        history_rows=[],
        metrics={},
    )


def repository_path(path: str, repo_name: str) -> str | None:
    """Resolve runner checkout paths; ignore absolute files outside the task repo."""
    normalized = path.replace("\\", "/")
    if ".." in normalized.split("/"):
        raise ValueError("traversal in evidence file path")
    absolute = normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized)
    if absolute:
        checkout = re.search(
            r"/(?:work|_work|a)/"
            + re.escape(repo_name)
            + "/"
            + re.escape(repo_name)
            + "/",
            normalized,
        )
        if checkout is None:
            return None
        normalized = normalized[checkout.end() :]
    return normalize_path(normalized)


def imported_paths(source: str, test: str, available: Collection[str]) -> set[str]:
    """Resolve direct Python imports against the immutable repository file list."""
    parsed = ast.parse(source)
    paths: set[str] = set()
    for node in ast.walk(parsed):
        for module in _import_modules(node, test):
            candidates = (
                f"{module}.py",
                f"{module}/__init__.py",
                f"src/{module}.py",
                f"src/{module}/__init__.py",
            )
            paths.update(
                candidate for candidate in candidates if candidate in available
            )
    return paths


def _import_modules(node: ast.AST, test: str) -> list[str]:
    if isinstance(node, ast.Import):
        return [name.name.replace(".", "/") for name in node.names]
    if isinstance(node, ast.ImportFrom):
        prefix = test.split("/")[: -node.level] if node.level else []
        module = "/".join([*prefix, *(node.module or "").split(".")]).strip("/")
        return [module, *(f"{module}/{name.name}" for name in node.names)]
    return []
