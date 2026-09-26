"""Orchestrator evidence collection and fenced persistence (AD-16, AD-24)."""

import json
import logging
from dataclasses import dataclass
from typing import Protocol

from contracts.evidence import EvidencePack, HistoryRow
from gateway.events import RunIdentity
from workflow.distiller import distill
from workflow.evidence import assemble_pack
from workflow.github_evidence import CollectedEvidence, EvidenceReadError
from workflow.history import HistoryEntry, normalize_fingerprint
from workflow.leases import Claim
from workflow.run_states import RunState
from workflow.steps import StepCommit, StepRecord, TaskRunIdentity
from workflow.task_store import without_author_attribution
from workflow.thresholds import DistillerLimits

_LOG = logging.getLogger(__name__)


class InstallationTokens(Protocol):
    def mint(self, installation_id: int, repo_id: int) -> str: ...


class EvidenceReader(Protocol):
    def collect(self, identity: RunIdentity, token: str) -> CollectedEvidence: ...


class HistoryLookup(Protocol):
    def lookup(self, repo_id: int, fingerprint: str) -> list[HistoryEntry]: ...


class EvidenceRecorder(Protocol):
    def record(self, claim: Claim, repo_id: int, commit: StepCommit) -> StepRecord: ...


@dataclass(frozen=True)
class CollectionRequest:
    identity: RunIdentity
    claim: Claim
    test_id: str
    error_type: str
    top_stack_frames: tuple[str, ...]


def agent_context(pack: EvidencePack) -> str:
    """Only bounded pack data, with delimiter characters escaped (AD-20).

    Author removal uses the task artifact projection's existing policy (AD-27).
    Caller instructions must live outside this data block.
    """
    content = json.dumps(
        without_author_attribution(pack.model_dump(mode="json")), sort_keys=True
    )
    for character, escaped in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026")):
        content = content.replace(character, escaped)
    return f"<untrusted_evidence>\n{content}\n</untrusted_evidence>"


class EvidenceCollector:
    """A worker calls this during DISTILLING; agents never receive its token."""

    def __init__(
        self,
        reader: EvidenceReader,
        tokens: InstallationTokens,
        history: HistoryLookup,
        recorder: EvidenceRecorder,
        limits: DistillerLimits,
    ) -> None:
        self._reader = reader
        self._tokens = tokens
        self._history = history
        self._recorder = recorder
        self._limits = limits

    def collect_and_persist(self, request: CollectionRequest) -> EvidencePack:
        try:
            return self._collect_and_persist(request)
        except Exception:
            # AD-22: log identity, never raw evidence, token or exception text.
            _LOG.error("evidence collection failed run_id=%s", request.claim.run_id)
            raise

    def _collect_and_persist(self, request: CollectionRequest) -> EvidencePack:
        identity = request.identity
        token = self._tokens.mint(identity.installation_id, identity.repo_id)
        collected = self._reader.collect(identity, token)
        if (
            collected.failed.repo_id != identity.repo_id
            or collected.failed.run_id != identity.workflow_run_id
        ):
            raise EvidenceReadError("collected evidence task mismatch")
        log = distill(
            collected.raw_log.replace(token, "[redacted]"), None, self._limits
        )
        pack = assemble_pack(
            identity.repo_id,
            collected.last_green,
            collected.commits,
            log,
            collected.evidence_files,
        )
        pack.metrics = collected.metrics
        fingerprint = normalize_fingerprint(
            request.test_id, request.error_type, request.top_stack_frames
        )
        history = self._history.lookup(identity.repo_id, fingerprint)
        if any(
            row.repo_id != identity.repo_id or row.fingerprint != fingerprint
            for row in history
        ):
            raise EvidenceReadError("history repository or fingerprint mismatch")
        pack.history_rows = [
            HistoryRow(
                row_id=str(row.row_id),
                fingerprint=row.fingerprint,
                test_id=row.test_id,
                error_type=row.error_type,
            )
            for row in sorted(history, key=lambda row: str(row.row_id))
        ]
        # Revalidate assigned metrics: malformed boundary output cannot bypass
        # the contract's finite-number check (AD-6).
        pack = EvidencePack.model_validate(pack.model_dump(mode="json"))
        self._recorder.record(
            request.claim,
            identity.repo_id,
            StepCommit(
                step="distill",
                to_state=RunState.CLASSIFYING,
                output=pack.model_dump(mode="json"),
                task_identity=TaskRunIdentity(
                    identity.repo_id, identity.workflow_run_id, identity.run_attempt
                ),
            ),
        )
        return pack
