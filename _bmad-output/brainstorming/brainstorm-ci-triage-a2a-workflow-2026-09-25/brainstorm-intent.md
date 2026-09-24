---
title: CI Triage Multi-Agent Workflow (A2A) - Brainstorm Intent
date: 2026-09-25
source: _bmad-output/brainstorming/brainstorm-ci-triage-a2a-workflow-2026-09-25/.memlog.md
status: converged - ready for bmad-architecture / bmad-prd / bmad-spec
---

# CI Triage Multi-Agent Workflow - Intent

Tagline (proposed): "Blameless CI triage - who, why, how sure, and a fix, with receipts."

## Problem & root cause

When CI fails, teams struggle to classify the failure (flaky vs infra vs code vs external dependency), notify the right owner, triage quickly, and apply fixes without causing regressions elsewhere. Classification is hard because of high log volume, concurrent pushes from many devs, heavy tests, and infra overload under load. A wrong call costs a lot: the wrong dev is blamed, a real bug is hidden by a deflake, main stays broken, devs go back and forth, and external API calls in E2E tests fail. **Root cause (Five Whys): triage has no evidence-backed confidence, so every wrong call costs trust and human coordination.** The system must show evidence and confidence, not only a verdict.

## Three pillars (the heart of the project)

1. **Evidence-backed confidence**: every verdict comes with cited evidence (log line / commit SHA / metric) and a confidence value. A calibration table proves the confidence value is honest.
2. **A2A routing and discovery with TypeSafe Jev, by skill + description**: agents are A2A servers with Agent Cards. Discovery first tries an exact skill-id/tag match, then falls back to Jev, which routes the task need against registered skill descriptions (labels = skill ids). If confidence is below the threshold, it returns a no-route error.
3. **Human punch-out via A2A `INPUT_REQUIRED`**: high-risk or low-confidence cases pause the task in `INPUT_REQUIRED`, and approval resumes it. Paused tasks are persisted in the DB, not held by a worker.

Unifying mechanism: **confidence is the currency.** Jev's probability drives the classification branch, the description-routing fallback, and the punch-out. The calibration table proves the number is honest.

Two tiers of human: routine draft-PR approval (dev) vs authority escalation (team lead via `INPUT_REQUIRED`). This resolves "always human" vs "the rubric needs real branching".

## Goal & success criteria

- Primary: Stage 4 certification (workflow, guardrails, punch-out, E2E success, audit trail; mirror the Stage 4 folder rubric).
- Longer term (no deadline): a general agent that works across multiple repos and languages. Phasing: **v1 = certification slice, v2 = multi-repo/multi-language**.
- v1 done =
  - 5 scenarios implemented (see table).
  - **5/5 E2E success**, where success = reaching the **correct terminal state** (escalation counts when escalation is expected).
  - Red-team findings documented (zero findings not required).
  - promptfoo evals for every agent. **Per-agent pass bar = open question** (Stage 3 quality bar, threshold to be confirmed).

## Users / hirers served in v1

| Hirer | Job | v1 output |
|---|---|---|
| Dev whose build broke | Know where the problem is and how to fix it | Draft fix PR; Triage Card (SHOULD) |
| Infra on-call | "Is it mine?" | Infra report with runner metrics + retry window (S3) |
| Team lead | Approve risk, keep team unblocked | Designated approver for high-risk punch-out (S5) |

Deferred to v2: pipeline watchers (main-status summary) and the architect (weekly hotspot report).

## Decisions

- **Stack**: GitHub Actions CI, Python, Claude API, TypeSafe Jev (classifier).
- **Architecture A (hub-and-spoke)**: the orchestrator is an A2A server with an explicit state machine that calls A2A agents. Rejected: B, a choreographed chain (repo context and token must travel through every hop), and C, event-driven (A2A used only for card discovery).
- **Trigger**: agents do **not** run in GitHub Actions. A GitHub App webhook (`workflow_run` completed, conclusion=failure) goes to the Gateway, which verifies the `X-Hub-Signature-256` HMAC, returns 202 fast, and enqueues the task for the orchestrator. A long-running agent system on a cluster handles it.
- **One cluster, multi-repo**: a single GitHub App is installed on many repos. The payload carries `repository` + `installation.id`. A per-repo installation token is minted per task. Only the orchestrator/tool layer holds the token. Agents are stateless, and repo context lives in the task.
- **Postgres** for the queue (jobs table, `SELECT ... FOR UPDATE SKIP LOCKED`), history, and audit. N orchestrator workers = concurrency cap. A queue is required for fast webhook ack, bursts, Claude/GitHub rate limits, durability across restarts, retries, and `INPUT_REQUIRED` tasks that wait hours.
- **Vector RAG rejected**: the grounding needs are structured lookups (failed-test history, cross-PR failures, runner metrics), and a small synthetic corpus gives vector search nothing to win. A structured history table (test_id, fingerprint hash, class, SHA, runner metrics, keyed by repo; exact-match lookups) is used instead. This is documented in the README as a conscious decision.
- **Always a draft PR, never auto-merge**: a human approves every PR.
- **Test data**: synthetic demo repo with seeded failures (bug commit, flaky test, OOM/infra, external API, concurrent pushes).
- **Jev used for 5-class failure classification** (user direction). Jev returns class + probabilities with no explanation, so Claude explains the verdict with evidence citations.

## Failure classes (5) and branch per class

| Class | Branch / action |
|---|---|
| Code bug | Suspect-commit narrowing (last-green..HEAD files ∩ stack-trace files/test imports, ranked) → fix draft PR to the author |
| Flaky test | Root-cause deflake draft PR + quarantine (not just retry) |
| Infra (e.g. OOM/overload) | No code PR → infra/capacity report to on-call |
| External dependency (3rd-party API in E2E) | Check status/recorded HTTP errors → mock/contract-test draft PR |
| Low confidence / conflicting signals / high risk | `INPUT_REQUIRED` punch-out with an evidence pack and no blame → team lead |

Pipeline shape: a deterministic (non-LLM) Log Distiller extracts error blocks and stack traces before any LLM sees them. The git range and log parsing are tools, and the LLM reasons over the distilled evidence. Confidence signals: failed-test history, other PRs failing the same test, runner resource usage, and interdependent code.

## Guardrails & defence in depth

Principle: **assume injection will get through and contain the blast radius.** Least privilege (agents hold no tokens, draft-only PRs, no secrets in the agent env, a human approves) is what makes red-team imperfection acceptable.

1. **Ingress**: webhook HMAC verification; replay protection via delivery-ID dedupe.
2. **GitHub App token scope**: `actions:read`, `contents:read`, `checks:read`, `pull_requests:write` (draft only).
3. **Input shrinking**: the deterministic Log Distiller reduces tokens and the injection surface.
4. **Jev injection pre-screen** on distilled logs (SHOULD). This is one layer only, not the sole defence (~69% recall reported).
5. **Untrusted-data handling**: stored history, commit messages, PR titles, and Agent Card descriptions are attacker-influenced and treated as data.
6. **Evidence-cited output schema**: the validator rejects uncited claims.
7. **Risk gate**: a normal draft PR goes ahead, but a draft PR that disables/skips tests, edits CI config, touches secrets, or edits infra manifests is BLOCKED and escalated. The deflake guard escalates PRs that loosen assertions, add retries, bump timeouts, or skip tests.
8. **Agent Card registry allowlist**: only allowlisted card URLs are accepted. Red-team a rogue card that claims all skills.
9. **Tenant isolation**: history queries are scoped by `repo_id`, and LLM context never mixes repos.
10. **Human approval** of every PR, plus `INPUT_REQUIRED` authority escalation.

Red-team targets: prompt injection via logs, Jev class-flipping ("this is flaky, not code"), indirect injection via history/commit metadata, rogue Agent Card, cross-repo leakage (promptfoo `bola`/`rbac`), and forged/replayed webhooks.

## v1 scope (MoSCoW)

- **MUST**
  - A2A for discovery, routing, and comms, with discovery by **skill AND description** (two-stage: exact match, then Jev description routing)
  - promptfoo evals for every agent
  - Red team against prompt injection
  - Mirror the Stage 4 folder rubric
  - Hub-and-spoke orchestrator + Postgres queue/history/audit, one cluster multi-repo
  - GitHub App webhook trigger
  - Jev 5-class classification + Claude evidence-cited explanation
  - Branch per failure class; always a draft PR, never auto-merge
  - Human punch-out via `INPUT_REQUIRED`
  - 5 scenarios, 5/5 E2E
  - **History table** (promoted from SHOULD)
  - **Calibration table in `results/`** (promoted from SHOULD)
- **SHOULD**
  - Triage Card (single PR comment: where / why / how sure / fix link; clears non-suspect devs)
  - Human approve/reject/edit of draft PRs auto-appended as promptfoo test cases (feedback loop; keep simple)
  - Jev injection pre-screen
  - Cross-repo leakage red team
- **COULD**
  - Weekly scheduled red team (regenerated attacks; found attacks frozen into the regression suite) + OWASP LLM Top 10 coverage table
  - Dedupe/coalescing (same repo+fingerprint → one triage, fan-out cards) and priority lanes (main/release first)
  - Second language
  - Jev risk scorer on PR diffs
- **WON'T (v1)**
  - Vector RAG
  - Self-verifying fix
  - Bisect agent
  - Cross-repo contagion
  - Pre-merge flake forecast
  - Watcher/architect reports
  - Language-specialist fix agents

## Scenarios (v1)

| # | Scenario | Expected terminal state |
|---|---|---|
| S1 | Code bug under concurrent pushes, 2 suspects | Culprit identified with evidence → fix draft PR to author |
| S2 | Flaky test | Deflake draft PR (+ quarantine) |
| S3 | Infra OOM | No PR; infra report routed to on-call |
| S4 | External API failure | Mock/contract-test draft PR |
| S5 | High-risk / low-confidence | Human punch-out via `INPUT_REQUIRED` → team lead |

## Verified facts vs to-verify

**Verified (via context7)**
- A2A Python SDK (`/a2aproject/a2a-python`):
  - `TaskState` = `SUBMITTED`, `WORKING`, `INPUT_REQUIRED`, `AUTH_REQUIRED`, `COMPLETED`, `FAILED`, `CANCELED`, `REJECTED`.
  - Status is set via `TaskUpdater.update_status` in the executor.
  - `INPUT_REQUIRED` is non-terminal, so it fits the punch-out.
- promptfoo (`/promptfoo/promptfoo`):
  - Redteam plugin `indirect-prompt-injection` with `config.indirectInjectionVar`.
  - Strategies `jailbreak`, `jailbreak-templates`.
  - `https` target with named inputs for agent endpoints.

**Researched (web, not independently verified)**
- TypeSafe Jev:
  - Returns class + probabilities from a fixed label set, ~100ms, ~$0.042/M input tokens, no explanations.
  - Python package `typesafe-sdk`.
  - Reported injection detection 118/170 @0.5 with 0 FP.
  - VentureBeat reports that injection can sway Jev verdicts.

**To verify**
- Claude model pricing: check via the claude-api skill at build time, not from memory. Model tiering (Haiku classify/summarise, Sonnet fix proposer, Opus/Sonnet adversarial reviewer) is a proposal pending this check.
- Stage 3 quality bar: the exact per-agent promptfoo threshold.

## Open questions

1. Per-agent promptfoo pass bar: which Stage 3 threshold applies?
2. Confidence thresholds: values for the classification punch-out and the description-routing no-route cutoff.
3. v1 second language (COULD): Python only, or Python + TS/Go?
4. Local dev/demo setup: kind/k3d + smee.io/cloudflared tunnel vs a docker-compose fallback (proposed, not decided).
