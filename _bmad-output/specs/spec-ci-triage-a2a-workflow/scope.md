# Scope and precedence

## Binding source interpretation

The latest user scope and final spine supersede brainstorm proposals, earlier memlog entries, rubric gaps and descriptive renderings. AD IDs are adopted unchanged. The architecture memlog confirms final decisions; no architecture choice is reopened here.

| Historical wording | Binding interpretation |
| --- | --- |
| contents:read; token per task | AD-16 contents:write restricted to triage/*, plus issues:write and org members:read; installation token per step; no workflows permission |
| external-dep; classify skill | AD-6/AD-11 class external; AD-10 catalogue classify-failure, analyze-failure, propose-fix, review-fix, test-only triage-dry-run |
| no-route error | AD-10 AWAITING_APPROVAL(no_route) |
| Jev probability as confidence | AD-9 immutable Choice.confidence, cited downward caps; probabilities audit-only; AD-10 routing confidence is a separate routing result |
| SQLite; free-text history | AD-15 structured-only Postgres history, orchestrator sole writer; pr_feedback separate |
| Opus; AI distiller/router; separate deflake/mock agents | Haiku Analyzer, Sonnet Proposer/Reviewer; deterministic distiller and owner notification; four agents, three Proposer variants |
| Jev pre-screen SHOULD | AD-11 batched Choice + Noul is binding; positive screen adds a cited cap and never independently blocks |
| quarantine modifies tests | AD-21 label and PR-body list, never proposed_diff |
| all outcomes produce PRs | S3 report only; uncertain/blocked runs pause; rejected approval reports; workflow-file changes become reports under AD-16 |
| unknown revision/bypass/deployment | AD-12 two revisions; AD-14 refused approval attempts audited; AD-25 Compose + smee for graded E2E, same images on plain k8s |
| second language COULD | Latest user instruction excludes multi-language from this slice |

## Priority catalogue

- **MUST vs SHOULD inside MUST ADs:** AD-9, AD-17 and AD-27 mention SHOULD features. In the MUST slice the gateway accepts only `workflow_run` completed/failure; `issue_comment` intake (the `/triage` command) and the Triage Card belong to the SHOULD backlog, and when built they write via AD-3 idempotency keys.

- **MUST:** CAP-1–CAP-6, all applicable AD rules, structured history, skill and description discovery, classification plus injection pre-screen, calibration, four per-agent evals, real GitHub scenarios, rubric evidence, tenant isolation and deterministic security tests.
- **SHOULD:** Triage Card (one PR comment: where/file:line/SHA, why/citations, confidence, fix link; clear non-suspects only with supporting evidence and obey AD-27); human approve/reject/edit feedback converted to promptfoo cases from pr_feedback, linked to source PR; /triage comment command via the same authenticated/authorized approval path; generated cross-repo leakage red-team probes (RT-04). Mandatory isolation tests remain required.
- **COULD:** weekly attack regeneration schedule, published OWASP coverage table, coalescing/fan-out, priority lanes, Jev diff risk scorer. Superseding stale runs/coalescing require a new architecture decision before implementation; they do not alter AD-1–AD-27 here.
- **Deferred:** RT-05 promptfoo routing endpoint with candidate_cards; pinned-registry pytest coverage is required now. Full column-level schema is owned by implementation, subject to spine invariants. No approval TTL in v1.
- **WON’T/v2:** the Non-goals in SPEC.md; broader multi-repo rollout beyond the tenant-safe architecture is not a certification deliverable.

## Planning handoff

Use CAP-1–CAP-6 as six candidate epic boundaries: ingress/queue; orchestration/evidence/state; agents/registry; guardrails/red team; punch-out; E2E/monitoring/results. Preserve CAP and AD references on stories. Shared contracts and state invariants constrain all slices; order dependent stories accordingly.

Next workflow: bmad-create-epics-and-stories → bmad-sprint-planning readiness gate → bmad-build. This spec does not create stories.yaml or silently choose story checkpoints.

## Historical ideas still uncommitted

OQ-5 retains the unresolved calibration population. The S5 fixture (high-risk, gate_blocked) and OQ-6 (per-repo `.ci-triage.yml` and dependency graph: WON’T in v1) are resolved in SPEC.md. External-dependency analysis can use recorded HTTP/status evidence; infra reports include runner metrics, retry guidance and prevention suggestions without inventing measurements. Cross-PR history and runner evidence remain structured, repo-scoped inputs rather than vector retrieval.
