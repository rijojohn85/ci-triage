---
id: SPEC-ci-triage-a2a-workflow
companions:
  - ../../planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md
  - ../../brainstorming/brainstorm-ci-triage-a2a-workflow-2026-09-25/redteam-plan.md
  - scope.md
  - scenarios.md
  - verification.md
sources:
  - ../../brainstorming/brainstorm-ci-triage-a2a-workflow-2026-09-25/brainstorm-intent.md
  - ../../brainstorming/brainstorm-ci-triage-a2a-workflow-2026-09-25/rubric-map.md
---

> **Canonical contract.** This SPEC and its companions define what to build, test and validate. User scope instructions take precedence; the final architecture spine’s AD-1–AD-27 govern implementation and override historical source wording. Sources are audit references, not additional requirements.

# Blameless CI Triage

## Why

Developers, infra on-call and approving team leads need to locate CI failures and act without blaming the wrong person or hiding real bugs. This Stage 4 AI certification slice demonstrates evidence-backed confidence, A2A discovery and collaboration, and human escalation through a reproducible synthetic GitHub project.

## Capabilities

- **CAP-1 — Ingress and durable queue (MUST)**
  - **intent:** Accept authentic failed CI runs once and retain them for bounded concurrent processing.
  - **success:** Signed completed/failure webhooks enqueue and return 202; bad signatures return 401, replays are 2xx no-ops, unknown installations are rejected, and lease fencing prevents stale workers from committing.
  - **trace:** AD-17, AD-23, AD-25.

- **CAP-2 — Orchestrator and evidence (MUST)**
  - **intent:** Turn each failed run into evidence-backed triage that survives interruption and reaches the appropriate class-specific outcome.
  - **success:** S1/S2/S4 produce draft PRs, S3 an infra issue, and uncertain or blocked runs pause; evidence includes ranked candidate commits, distilled logs, repo-scoped history and metrics; restart resumes completed work without repeating side effects.
  - **trace:** AD-1–AD-4, AD-9, AD-15, AD-21–AD-24, AD-27.

- **CAP-3 — A2A agents and discovery (MUST)**
  - **intent:** Discover appropriate specialists by skill and description, classify failures, explain evidence, propose fixes and challenge proposed changes.
  - **success:** Four agents expose pinned Agent Cards; exact and Jev description-fallback routes are demonstrated; no-route pauses for a human; code/flaky/external proposals carry Reviewer verdicts, with at most two revision rounds and Proposer as sole diff author.
  - **trace:** AD-5, AD-6, AD-10–AD-12, AD-19.

- **CAP-4 — Guardrails and adversarial evaluation (MUST)**
  - **intent:** Contain untrusted CI content and reject unsupported claims or unsafe changes before GitHub writes.
  - **success:** Schema/citation failures retry once then escalate; deterministic risk rules block dangerous changes; RT-01–RT-08 coverage and findings are recorded with the explicit optional/deferred boundaries in scope.md and verification.md.
  - **trace:** AD-6–AD-8, AD-10, AD-11, AD-13, AD-16, AD-20, AD-26, AD-27.

- **CAP-5 — Human punch-out (MUST)**
  - **intent:** Let an authorized human approve or reject uncertain or blocked triage using its evidence pack.
  - **success:** S5 exposes A2A INPUT_REQUIRED without holding a worker; authenticated CODEOWNER decisions are recorded on the same task, bound to the proposal and diff hash where present; approval resumes the prescribed path, rejection produces a report, and bypass attempts are refused and audited.
  - **trace:** AD-1, AD-4, AD-14, AD-16, AD-27.

- **CAP-6 — Certification evidence and monitoring (MUST)**
  - **intent:** Demonstrate reproducible triage quality, calibrated confidence and accountable model usage for the certification slice.
  - **success:** Real GitHub S1–S5 achieve 5/5 expected outcomes; all four per-agent promptfoo suites produce results against the user-supplied pass bar; calibration, red-team findings and per-step/per-run usage and cost exports are available under the rubric layout.
  - **trace:** AD-9, AD-18, AD-19, AD-25, AD-26.

## Constraints

- AD-1–AD-27 are settled and retain their IDs. The adopted spine supplies contracts, states, stack pins, security boundaries and operational rules; scope.md records precedence over historical wording.
- Use Python, TypeSafe Jev and Claude Sonnet/Haiku only; A2A provides discovery, routing and communication. Agents run as long-lived services, outside GitHub Actions. AD-5, AD-10, AD-11, AD-25.
- Postgres owns queue, history, audit and run state; repository isolation remains mandatory even though certification uses one synthetic demo repo. AD-1, AD-4, AD-15, AD-23.
- GitHub effects are draft-only, idempotent and human-reviewed; agents cannot hold GitHub tokens or access Postgres. No auto-merge or workflow-file write permission. AD-3, AD-5, AD-16.
- Effective classification confidence may only decrease from Jev Choice.confidence through cited caps; routing uses its own Choice result and route cutoff. Prompts and thresholds have single sources. AD-9–AD-11, AD-19.
- Preserve the hard Stage 4 layout: prompts/, workflow/, guardrails/, punch-out/, monitoring/, runs/, results/, test-data/, root jev.test.yaml, analyzer.test.yaml, proposer.test.yaml, reviewer.test.yaml, and README.md. verification.md maps required evidence.
- MUST is the certification baseline; SHOULD/COULD are explicitly optional in scope.md. Multi-language and other user-excluded v2 work cannot enter this slice.

## Non-goals

- Vector RAG, signed Agent Cards, OpenTelemetry, DBOS/Temporal, multi-language support, language-specialist agents, self-verifying fixes, automated bisect, cross-repo contagion, pre-merge flake forecasting, watcher/architect reports, per-repo `.ci-triage.yml` configuration, and a code dependency graph tool.
- Autonomous merges, production-repository rollout, or a claim of zero prompt-injection vulnerabilities.

## Success signal

- On a real synthetic GitHub demo repo, S1/S2/S4 reach pr_opened, S3 reaches report_sent, and S5 reaches input_required with a subsequent approve/reject recorded: 5/5 E2E. scenarios.md defines the receipts; INPUT_REQUIRED remains resumable, not a terminal database state.
- Every agent has a promptfoo result meeting the supplied Stage 3 bar; results/ contains calibration and documented red-team findings, while runs/ and results/ expose auditable per-step tokens/costs and per-run totals. Unknown usage/prices remain NULL and flagged, not fabricated zeros.

## Open Questions

- **OQ-1:** What numeric Stage 3 pass bar applies to each agent’s promptfoo suite? The user will supply it; certification quality cannot be declared passed until then.
- **OQ-2:** What calibrated class, route and injection-screen cutoffs should be used? Class 0.75 and route 0.6 are placeholders only, not accepted production thresholds.
- **OQ-3:** What authoritative Jev price and billing units apply? Until sourced, Jev cost is NULL and flagged; do not reuse the brainstorm’s price estimate.
- **OQ-4:** Is the configured Haiku model available and suitable at build time? Confirm the source claim “retirement not sooner than 2026-10-15” before build; model changes stay within Sonnet/Haiku and config.
- **OQ-5:** What labelled sample count/repeats/variants will support calibration? Not numerically fixed by the sources. (S5 fixture resolved: see scenarios.md.)

## Resolved

- **OQ-5 (S5 part), resolved 2026-09-25:** S5 is driven by a **high-risk** fixture: a seeded failure whose only obvious fix is a timeout bump, so the risk gate blocks it and the run pauses at `input_required` with `escalation_reason = gate_blocked`. The low-confidence branch remains a separate branch test outside the five-scenario denominator.
- **OQ-6, resolved 2026-09-25:** `.ci-triage.yml` and the code dependency graph are **WON’T in v1 (v2)**. CODEOWNERS, `guardrails/thresholds.yaml` and the fixed AD-13 risk paths cover v1.
