---
reviews: ARCHITECTURE-SPINE.md (Blameless CI Triage, draft 2026-09-25)
lenses: [adversary, good-spine rubric walker]
reviewer: adversarial review agent
date: 2026-09-25
sources_checked:
  - ARCHITECTURE-SPINE.md
  - .memlog.md
  - brainstorm/rubric-map.md, brainstorm-intent.md, promptfooconfig.redteam.yaml
  - a2a-sdk docs (via context7, /a2aproject/a2a-python): TaskState enum, DefaultRequestHandler + TaskStore
  - GitHub App permission model (from prior knowledge; context7 not queried for GitHub)
---

# Adversarial Review: Architecture Spine, Blameless CI Triage

## Verdict

The spine is well built at the level of its paradigm. The hub-and-spoke model, the single owner of run state, blocking stateless spokes, one confidence number, one prompt copy, one thresholds file, and a deterministic gate are the right decisions, and each is written as a checkable rule. **It is not yet safe to build from.** Two teams can each follow every AD exactly and still build incompatible units in about 25 places. Four of these break a graded scenario or the E2E run outright:

1. **S2 cannot reach its expected terminal state.** A quarantine is a skip or xfail, and AD-13 blocks it.
2. **Draft PRs cannot be opened.** AD-16 grants no `contents:write`.
3. **AWAITING_APPROVAL has a single `approve` exit (to PR_OPENING).** Three of the five ways into that state have no diff to open.
4. **The SKIP LOCKED claim does not cover a long, blocking LLM call.** The spine gives no lease model.

The state machine also has no DISTILLING-adjacent state for **suspect narrowing, history lookup, or evidence-pack assembly**, so no one owns `suspects`. The operational envelope is almost entirely missing: no migrations, backups, secret rotation, token expiry handling, or per-environment registry.

Severity scale: **Critical** means a graded scenario, E2E run, or security property fails. **High** means two units are near-certain to build incompatible code. **Medium** means divergence is likely and costly to fix later. **Low** covers clarity and hygiene.

---

## Lens 1: Adversary. Compliant but incompatible pairs

Each entry lists the two units, the divergence (both sides obey every AD), and a proposed one-line AD rule.

### A. State machine and transitions

**A1. [Critical] S2 flaky quarantine vs the risk gate** (Proposer vs `risk_gate`)
Rubric S2 expects a "deflake PR + quarantine" ending in a draft PR. Every quarantine mechanism (pytest `skip`/`xfail`, a marker, a quarantine list the test runner reads) "skips/disables/xfails a test", so AD-13 returns `blocked` and the run lands in AWAITING_APPROVAL. The Proposer team puts the quarantine in the diff and the gate team blocks it, so S2 fails 5/5. The rubric-map already flags this (§4, "Quarantine mechanism for S2"); the spine does not resolve it.
> **New AD rule:** "Quarantine is never part of `proposed_diff`. It is a recommendation field (`quarantine: {test_id, reason, citation}`) rendered in the PR body and recorded in `history`. `proposed_diff` for class `flaky` must be a root-cause change that passes the gate. A test-disabling quarantine goes only through AWAITING_APPROVAL."

**A2. [Critical] `approve` from an escalation with no diff** (`workflow/` transition author vs `punch-out/` CLI)
AWAITING_APPROVAL is entered from CLASSIFYING (low confidence, unknown, or no-route), ANALYZING (validation failed twice), REVIEWING (rejected after 2 rounds), and GATING (blocked). Only the last two carry a diff, but the only `approve` edge goes to PR_OPENING. One developer opens an empty PR or crashes into FAILED. Another adds an unlisted edge to REPORTING, which AD-1 says must raise. S5 does not say which trigger it uses (rubric-map §4 "What S5 triggers" is still open).
> **Tightened AD-1/AD-14:** "AWAITING_APPROVAL stores `escalation_reason ∈ {low_confidence, unknown_class, no_route, validation_failed, review_rejected, gate_blocked}` and `proposal_step_id?`. `approve` → PR_OPENING only when `proposal_step_id` is set. Otherwise `approve` → REPORTING (evidence report). `reject` → REPORTING → REJECTED_BY_HUMAN."

**A3. [High] Which proposal the human approves** (orchestrator vs CLI)
After REVIEWING → PROPOSING loops there are up to 3 proposals. The approver may approve round N while PR_OPENING opens "latest". Nothing binds the approval to a specific diff.
> **Rule:** "`approval` row references `proposal_step_id` + `sha256(proposed_diff)`. PR_OPENING opens exactly that diff and refuses on mismatch."

**A4. [High] Schema failures in PROPOSING and REVIEWING have no edge** (AD-8 vs AD-1)
AD-8 applies to "every agent step" (second failure → AWAITING_APPROVAL), but the table has that edge only from ANALYZING. A PROPOSING developer following AD-8 raises an illegal transition. A developer following AD-1 sends the run to FAILED instead. CLASSIFYING (Jev returns malformed output) has the same problem.
> **Tightened AD-1:** "Every agent-calling state (CLASSIFYING, ANALYZING, PROPOSING, REVIEWING) has an edge → AWAITING_APPROVAL(`validation_failed`), and the diagram shows each one."

**A5. [High] FAILED and retry semantics** (worker author vs A2A client author vs spoke author)
"Any state may also move to FAILED (after retries)" conflicts with "any transition not in the table raises". The spine does not say:
- how many retries happen or with what backoff;
- whether a transport or 5xx retry uses up AD-8's single schema retry;
- whether `AgentError.retryable=false` fails the run immediately;
- whether FAILED is terminal or can be re-driven;
- whether FAILED writes a `history` row.

Two developers will build different retry budgets and different A2A-visible states.
> **New AD rule:** "Transient errors (timeout, 5xx, 429, `AgentError.retryable`) get 3 attempts with exponential backoff per step. They are logged as separate `run_step` attempts and do not count toward AD-8. Exhaustion or `retryable=false` → FAILED. FAILED is terminal: it writes a `history` row with outcome `failed`, and re-drive means a new run. The `* → FAILED` edges appear in the table."

**A6. [High] Revision rounds: off-by-one and the meaning of "accepted"** (Proposer loop vs Reviewer)
The spine does not say whether "Max 2 revision rounds" means 2 or 3 proposals. The only severity value it names is `dangerous`, so "accepted" could mean "no objections" or "no blocking objections". The round counter's location is also unspecified (a column, or a count of `run_step` rows).
> **Rule:** "`severity ∈ {info, minor, major, dangerous}`. Accepted = no `major` or `dangerous`. `revision_round` is a `triage_run` column starting at 0, incremented on REVIEWING → PROPOSING, and the transition is allowed only while `revision_round < 2` (3 proposals max)."

**A7. [Medium] The Analyzer lowers confidence below the cutoff, but ANALYZING has no low-confidence edge** (Analyzer vs `workflow/`)
AD-9 lets Claude agents lower confidence, yet the class-cutoff check exists only at CLASSIFYING. One developer re-checks after ANALYZING through an unlisted edge. Another ignores the new value, so a capped confidence still opens a PR.
> **Rule:** "The confidence cutoff is re-evaluated after every step that may lower confidence. ANALYZING, PROPOSING and REVIEWING each have an edge → AWAITING_APPROVAL(`low_confidence`)."

**A8. [Medium] Class is Jev-only, but the Analyzer may "disagree"** (Analyzer contract vs branch logic)
AD-9 fixes confidence. It does not say the Analyzer can never change `class`. Contract field `class` appears in Analyzer output (the red-team asserts `v.class`), so one developer branches on the Analyzer's class and another on Jev's.
> **Rule:** "`class` is set once, by Jev, in CLASSIFYING. Analyzer output has no `class` field; disagreement is expressed only as a confidence cap with reason `class_disagreement`."

**A9. [Medium] REJECTED_BY_HUMAN "+ evidence report" has no state or idempotency key.** It is a GitHub write (AD-3) produced outside any state, and it is re-emitted on resume.
> Covered by the A2 rule (reject → REPORTING → REJECTED_BY_HUMAN). REPORTING carries an `outcome` field.

**A10. [Medium] AWAITING_APPROVAL has no timeout.** Stale tasks pile up indefinitely, and an approval weeks later acts on an outdated HEAD.
> **Rule:** "AWAITING_APPROVAL expires after `approval_ttl` (thresholds.yaml) → REPORTING(`expired`) → DONE_REPORT. PR_OPENING re-checks that the base SHA still applies, else → AWAITING_APPROVAL(`stale_base`)."

### B. Shared data shapes

**B1. [Critical] No owner or state for suspects, history lookup, or evidence pack** (orchestrator vs Analyzer)
The rubric pipeline is distill → **suspect-commit narrowing** → **history lookup** → classify → analyze. The state machine has DISTILLING → CLASSIFYING with nothing in between. `suspects` is a contract field (AD-6), but the spine does not say who computes it: a deterministic orchestrator step (last_green..HEAD files ∩ stack-trace files) or the Analyzer LLM. If both do, two sources of blame disagree. S1 ("2 suspects") is scored on this field. No contract is named for the `EvidencePack`, and "last_green" is undefined: per branch, per workflow, or the latest successful run of the same workflow on the same branch before `head_sha`?
> **New AD rule:** "DISTILLING builds `contracts.EvidencePack {distilled_log, candidate_suspects[], history_rows[], runner_metrics{}, repo_files{}}` deterministically in `workflow/evidence/`. `last_green` = the latest `conclusion=success` run of the same workflow on the same `head_branch` before this run. The Analyzer may only rank or choose from `candidate_suspects`, and each `commit` citation must be in that list."

**B2. [High] `log_line` locator semantics** (Log Distiller vs Analyzer prompt vs `citation_check`)
The spine does not say whether line numbers refer to the raw log or the distilled log, whether they are 0- or 1-based, whether they are per job/step file, or whether the distilled text is persisted. The citation checker must reproduce exactly what the Analyzer saw.
> **Rule:** "The distilled log is persisted in `run_step` (DISTILLING output) as numbered lines `{job, step, n (1-based, distilled), raw_ref}`. A `log_line` locator = `{job, step, n}` in distilled numbering. `citation_check` resolves only against that persisted artifact."

**B3. [High] `proposed_diff` format and base** (Proposer vs `risk_gate` vs PR_OPENING)
The spine does not say whether the diff is a unified-diff string or a file-replacement map, or which base it applies to (`workflow_run.head_sha` or the current branch tip, which may have moved under concurrent pushes). Without a common format, the gate's parser, the applier, and the Proposer's output will not match.
> **Rule:** "`proposed_diff` = `{base_sha, files: [{path, op: add|modify|delete, new_content}]}`, with the unified-diff text derived by the orchestrator. The gate evaluates the structured form. PR_OPENING creates the branch from `base_sha`."

**B4. [High] Repo context for the Proposer** (orchestrator vs Proposer)
"Repo context travels in the request" (AD-5), but the spine does not say which files, how large they may be, or what happens if the Proposer needs more. One Proposer developer adds a tool-use loop to fetch files, which needs a token (breaking AD-5/AD-16) or a callback (not in the design).
> **Rule:** "The orchestrator serves `repo_files` = (stack-trace files ∪ files touched by `candidate_suspects` ∪ their test files), capped at N KB. Spokes have no tools that reach outside the request. If context is insufficient, the Proposer emits `insufficient_context`, which escalates."

**B5. [High] Red-team contract vs the spine's enums** (red-team config vs `contracts/`)
AD-6 makes red-team field names part of the contract, but the red-team config asserts `v.terminal_state === 'input_required'` (an A2A-style lowercase value, not `AWAITING_APPROVAL`), reads `json.verdict` (a wrapper not defined in the spine), and its Jev comment uses `external-dep` instead of `external`. It also depends on `TRIAGE_REDTEAM_URL`, an orchestrator test endpoint that "runs one triage task on supplied evidence, no GitHub writes". That endpoint is not in the layer table or state machine, and no one owns it.
> **Rule:** "`terminal_state` in contracts = the `triage_run.state` enum (upper snake), and red-team asserts are updated to match. The red-team target is a `dry_run=true` flag on the orchestrator A2A skill, which stops before PR_OPENING/REPORTING. The response is `{verdict: TriageVerdict}`."

**B6. [Medium] Where the confidence cap is recorded** (Analyzer vs gate vs calibration)
"May only lower (cap, with a cited reason)" does not say whether the Jev raw value is overwritten or kept alongside, or what the calibration table plots (raw or effective). The citation kinds are closed at `log_line|commit|metric|history_row`, yet an injection-screen positive or a "class disagreement" cap has no matching citation kind.
> **Rule:** "Store `confidence_jev` (immutable) and `confidence_effective = min(jev, caps…)`. `caps[] = {source, reason_code, citation?}`. Gate and branch read `confidence_effective`; calibration reports both. Add citation kind `jev_signal` for the Noul result."

**B7. [Medium] `metric` citations have no source.** S3 (OOM) depends on runner metrics, which the GitHub API does not provide. The spine does not say whether they come from the job log (the exit-137 line, which is actually a `log_line`), from an artifact the demo CI uploads, or from a sidecar.
> **Rule:** "Runner metrics = a JSON artifact (`runner-metrics.json`) uploaded by the demo-repo CI, fetched by the orchestrator in DISTILLING. `metric` locator = a JSON key in that artifact."

**B8. [Medium] Jev class descriptions have no single home.** AD-11 gives each class "a description", and AD-19 fixes one copy per prompt, but `prompts/` lists only analyzer, proposer and reviewer. `agents/jev` and `jev.test.yaml` could each embed their own copy.
> **Tighten AD-19:** "`prompts/jev-classes.yaml` holds the 5 class descriptions and the Noul instruction. The Jev agent and `jev.test.yaml` load it."

**B9. [Medium] S4 external class → which skill and which gate rule** (router vs Proposer vs gate)
Skill ids list only `propose-fix`. The spine does not say whether "mock/contract-test PR" and "deflake" are modes of that skill or separate skills. The gate has no rule for "adds a test double": replacing a live HTTP call with a mock is arguably "loosening" the test. The rubric says the gate should pass it.
> **Rule:** "`propose-fix` takes `mode ∈ {fix, deflake, mock}` derived from `class`. The gate treats additions under `tests/**/fixtures|mocks/**` and `responses`/`respx` stubs as `normal`, unless an existing assertion is removed."

**B10. [Medium] Routing: when it happens and what is routed.** No state performs routing. The spine does not say whether routing runs per step (class → skill_id) or once at startup, whether stage 2 runs on the distilled log or the step intent, or whether the orchestrator calls the Jev API directly (layer table: "Jev (routing)") or the Jev A2A agent.
> **Rule:** "A static `workflow/routes.yaml` maps each step → required skill_id (stage 1). Stage 2 (a direct Jev API call from `workflow/`) runs only when a required skill_id is missing from the registry, and is evaluated at CLASSIFYING exit."

### C. Ownership and state mutation

**C1. [Critical] Claim model: SKIP LOCKED plus a multi-minute blocking LLM call** (worker author vs worker author)
`FOR UPDATE SKIP LOCKED` holds only while the transaction is open. Worker A either keeps the transaction open across Sonnet calls (long transactions, and AD-2's "one transaction" then covers the LLM call) or commits the claim and runs the call outside it. In that second case, worker B can claim the same run and spend on the LLM twice, which AD-2 was meant to prevent.
> **New AD rule:** "The claim is a short transaction that sets `lease_owner`, `lease_until = now()+step_timeout+slack`. Workers pick `WHERE state NOT IN (terminal, AWAITING_APPROVAL) AND (lease_until IS NULL OR lease_until < now()) FOR UPDATE SKIP LOCKED`. The step-commit transaction re-checks `lease_owner` (fencing) before writing `run_step` and the state."

**C2. [High] Who executes the transition when the approval arrives** (orchestrator A2A server vs worker pool)
The punch-out message lands on the orchestrator's A2A request handler. The spine does not say whether that handler performs PR_OPENING inline or only records the approval and leaves a worker to pick it up. It also does not settle a race between two concurrent approve/reject messages.
> **Rule:** "The A2A handler only validates identity, inserts `approval`, and moves AWAITING_APPROVAL → the next state in one transaction guarded by `WHERE state='AWAITING_APPROVAL'`. The first write wins, the other gets a conflict. Workers perform all side effects."

**C3. [High] The A2A TaskStore over `triage_run`** (orchestrator A2A server vs gateway)
The gateway creates runs by SQL insert, never through A2A. a2a-sdk's `DefaultRequestHandler` resolves `task_id` through its `TaskStore` (context7). With a stock `DatabaseTaskStore`, `send_message(task_id=run_id)` gets "task not found". The obvious fix, writing tasks into the SDK store, creates the second owner that AD-4 forbids.
> **Tighten AD-4:** "The orchestrator implements a read-only `TaskStore` adapter over `triage_run`/`run_step`. The `a2a-db` tables are not deployed. `REJECTED_BY_HUMAN` projects to `COMPLETED` with `outcome=rejected` (not A2A `REJECTED`, which means the agent refused the task)."

**C4. [High] Two writers of `history`** (orchestrator vs `test-data/` seeding)
AD-15 says only the orchestrator writes `history`. S2 (flaky history) and S1 (other PRs failing the same test) need **seeded** history rows, and `test-data` drivers will insert them directly.
> **Rule:** "Seed history enters only through `workflow` CLI `history import <file>` (same code path, `source=seed`). Fingerprint = `sha256(normalized error + top-N frames)`, computed only in `workflow/evidence/`."

**C5. [Medium] History "including the human verdict" is written once at terminal state.** For DONE_PR, the human verdict (merge or close of the draft PR) arrives after the terminal state. One developer writes the history row at DONE_PR and never updates it. Another delays it, which violates "one row at terminal state".
> **Rule:** "`history` is written at terminal state. Later PR verdicts go to a separate `pr_feedback` table (gateway `pull_request.closed` → SHOULD), never updating `history`."

**C6. [Medium] Duplicate runs for the same CI failure** (gateway vs orchestrator)
Dedupe is by `X-GitHub-Delivery`. A re-run of failed jobs produces a new delivery for the same `workflow_run.id` with `run_attempt+1`. S1's "concurrent pushes" produce two failing runs, which can yield two triage runs and two fix PRs for one bug. Coalescing is deferred as COULD, but S1 depends on the behaviour.
> **Rule:** "Unique `(repo_id, workflow_run_id, run_attempt)` on `triage_run`. Two open runs with the same fingerprint on the same branch: the later one references the earlier (`superseded_by`) and ends in DONE_REPORT."

### D. Security and authority

**D1. [Critical] App scopes cannot open a draft PR** (AD-16 vs AD-3 and PR_OPENING)
Creating branch `triage/<run_id>` and committing to it (Git refs, trees and commits, or the contents API) requires **`contents:write`**, and `pull_requests:write` alone is not enough. Any approved change touching `.github/workflows/**` also requires the **`workflows`** permission. The infra report (S3) and the Triage Card need a destination the scopes allow: `issues:write` for an issue, `checks:write` for a check-run summary, or `contents:write` for a commit comment. AD-16 as written makes the PR_OPENING step fail with 403 in every run.
> **Tighten AD-16:** "Scopes add `contents:write` (used only for `refs/heads/triage/*`, enforced in code and by branch protection on default branches) and `issues:write` (infra report = issue labelled `ci-triage/infra`). Diffs touching `.github/workflows/**` are never pushed, even after approval (App lacks `workflows`), and become a report."

**D2. [Critical] CODEOWNERS read from an attacker-controlled ref**
The spine does not say which ref AD-14 reads CODEOWNERS from. If it is `head_sha`, the failing commit can add its author as owner of `*` and then approve its own blocked change.
> **Rule:** "CODEOWNERS is read from the default branch's protected tip at approval time, never from `head_sha` or the triage branch."

**D3. [High] The PR-comment `/triage` command cannot "become the same A2A message"**
AD-14 authenticates with the caller's user token. A webhook `issue_comment` carries only a login, and the gateway may call only Postgres (layer table). The Deferred list says this path enters "without new ADs", which is false: it requires a second identity model (a trusted webhook-asserted login) and a gateway → orchestrator channel.
> **Rule:** "The `/triage` comment path is marked OUT of v1 until an AD defines: gateway enqueues a `pending_command` row with the webhook-verified `sender.login` and the orchestrator applies the same CODEOWNERS check."

**D4. [Medium] Installation token lifetime vs "minted per task"**
Installation tokens expire after 1 hour. Tasks can sit in AWAITING_APPROVAL for days. A developer who caches the token per task fails in PR_OPENING after approval.
> **Rule:** "Installation tokens are minted per step, cached in memory for at most 50 minutes, and never persisted."

**D5. [Medium] Jev key in the orchestrator vs NetworkPolicy.** AD-16 limits only the *agents'* egress. The orchestrator egresses to GitHub and Jev, and the gateway needs no egress, but nothing states this.
> **Rule:** Add orchestrator (GitHub, Jev) and gateway (none) egress policies.

### E. Registry and environments

**E1. [High] Card digest vs environment-specific URLs** (registry author vs deploy author)
Agent Cards embed their own `url` / `supported_interfaces[].url`. That URL differs between compose (`http://analyzer:8000`) and k8s (`http://analyzer.triage.svc`), so the sha256 differs, and one committed allowlist `{card_url, sha256}` cannot serve both targets. The spine also does not say whether the digest is taken over raw bytes or canonical JSON.
> **Rule:** "Digest = sha256 of RFC 8785 canonical JSON with `url`/`supported_interfaces[].url` removed. `registry.<env>.yaml` per environment, same digests."

**E2. [Medium] Startup ordering.** "Cards are fetched at startup, mismatch → refuse to start" combined with compose starting services in parallel can make the orchestrator crash-loop until the agents are up. The spine does not say whether the orchestrator fails or retries.
> **Rule:** "The orchestrator retries card fetches with backoff up to 60s. Only a digest mismatch or a duplicate skill is fatal. Compose uses `depends_on: condition: service_healthy`."

---

## Lens 2: Good-spine checklist

### 2.1 Does it fix the real divergence points and miss none?

| Divergence point | Status | Notes |
| --- | --- | --- |
| Run state owner | Fixed (AD-4) | Needs the TaskStore adapter (C3) |
| Workflow shape and branching | Partly fixed (AD-1) | Missing: evidence/suspect state (B1), approve semantics (A2), per-state validation edges (A4), FAILED (A5) |
| Inter-agent payload shapes | Partly fixed (AD-6) | Key shapes unset: EvidencePack, `proposed_diff`, log_line locator, verdict wrapper (B1–B5) |
| Confidence | Fixed (AD-9) | Raw vs capped storage unset (B6) |
| Citation | Fixed (AD-7) | Locator semantics and `last_green` unset (B1, B2) |
| Concurrency and claiming | **Missed** | Lease/fencing (C1), duplicate runs (C6) |
| Retry and error | **Missed** | A5 |
| Authority and identity | Partly fixed (AD-14) | CODEOWNERS ref (D2), `/triage` identity (D3) |
| GitHub permissions | **Wrong** | D1 |
| Class-specific outputs (S2 quarantine, S4 mock, S3 report destination) | **Missed** | A1, B9, D1 |
| History writes and fingerprint | Partly fixed (AD-15) | Seeding (C4), post-terminal verdicts (C5) |
| Prompts and thresholds | Fixed (AD-19) | Jev descriptions (B8) |
| Red-team harness contract | **Missed** | B5 |

### 2.2 Is each AD rule enforceable, and does it prevent its divergence?

| AD | Enforceable? | Prevents divergence? | Gap |
| --- | --- | --- | --- |
| AD-1 | Yes (transition table raises) | Partly | Table vs diagram contradiction on FAILED. AD-8 edges missing. Diagram is not declared as generated from the table, so the two can drift. Rule: generate the mermaid from the table in CI. |
| AD-2 | Yes | No, not without a lease | C1 |
| AD-3 | Yes | Partly | Revision re-runs of PR_OPENING are fine. The report and rejection report have no step key (A9). |
| AD-4 | Yes | Only with a custom TaskStore | C3 |
| AD-5 | Yes | Partly | Tool loops in spokes are not explicitly forbidden (B4) |
| AD-6 | Yes (CI schema diff) | Partly | Red-team names diverge today (B5). Contract versioning across independently deployed agents is not addressed. Add `schema_version` to DataPart metadata and reject mismatches. |
| AD-7 | Yes | Partly | B2, B6 |
| AD-8 | Yes | No | Contradicts AD-1 (A4). Transport retries unspecified (A5). |
| AD-9 | Yes | Partly | B6, A7 |
| AD-10 | Yes | Partly | Env-specific digests (E1). When routing happens (B10). |
| AD-11 | Yes | Yes | Descriptions location (B8) |
| AD-12 | Yes | Partly | Severity enum, round counting (A6) |
| AD-13 | Partly | Partly | The detection method is unspecified (regex, AST or path globs), so "loosens assertions" is not mechanically checkable without a defined rule list. S2 and S4 conflicts (A1, B9). Rule: gate rules are an enumerated list in `guardrails/risk_rules.yaml` with a unit test per rule. |
| AD-14 | Yes | Partly | D2, D3, A2, A3, C2 |
| AD-15 | Yes | Partly | C4, C5 |
| AD-16 | Yes | **No, the scopes are wrong** | D1, D4, D5 |
| AD-17 | Yes | Partly | C6. The spine does not say where known `installation.id`s are configured (add `repos.yaml`: installation_id → repo_id). |
| AD-18 | Yes | Partly | Failed attempts and retries must also be costed (one `run_step` per attempt). Jev usage shape differs from Claude's `usage`, so define `contracts.Usage` that normalises both. |
| AD-19 | Yes | Yes | B8 |
| AD-20 | Partly | Partly | "Delimited data sections" has no fixed delimiter format, so each agent invents its own and promptfoo tests a different one. Rule: one `prompts/_untrusted.md` wrapper template. |

### 2.3 Can anything under Deferred let units diverge?

| Deferred item | Safe? | Why |
| --- | --- | --- |
| Threshold values | Safe | File and readers fixed |
| promptfoo pass bar | Safe | Model swap is config-only |
| Claude prices | Safe | Single file |
| Signed cards, OTel, DBOS | Safe | Pure additions |
| **PR-comment `/triage`** | **Unsafe** | Needs a new identity model and gateway path (D3). "No new ADs" is false. |
| Triage Card | Unsafe | Needs a comment destination and permission (D1). On a `workflow_run` for `main` there is no PR to comment on. |
| Feedback-to-promptfoo loop | Mostly safe | Touches history ownership (C5) |
| **Coalescing** | **Unsafe** | S1 concurrent pushes need at least a duplicate-run rule (C6) |
| Full column-level schema | Unsafe as worded | "The invariant fields above" are scattered and never listed. Add an explicit invariant-column list: `triage_run(run_id, repo_id, state, class, confidence_jev, confidence_effective, revision_round, escalation_reason, proposal_step_id, lease_owner, lease_until, workflow_run_id, run_attempt, head_sha, base_sha)`, `run_step(run_id, step, attempt, status, usage…)`. |

### 2.4 Is every dimension decided, deferred or open?

| Dimension | Status |
| --- | --- |
| Paradigm, layering, dependency rules | Decided |
| State machine | Decided with holes (§A) |
| Data ownership | Decided with holes (§C) |
| Contracts | Decided with holes (§B) |
| Security: authn/z, secrets placement | Decided with holes (§D) |
| Concurrency and claiming | **Absent** (C1) |
| Error handling and retries | **Absent** (A5) |
| Timeouts per spoke call and whole-run budget | **Absent.** Blocking `send_message` with no timeout hangs a worker forever. Add `step_timeout` per skill in config. |
| Rate limiting (GitHub API, Anthropic 429) | **Absent**, fold into A5 |
| Deployment targets | Decided (compose + k8s) |
| **Environments** (dev vs graded E2E vs cluster; per-env config, registry, App instance, demo repo) | **Absent.** Dev and graded E2E share compose, and the spine does not say whether they use separate GitHub Apps, webhook secrets or DBs. |
| **Infra** (k8s ingress for webhooks, TLS, resource limits, replicas, health/readiness probes) | **Absent** |
| **Operations** (runbook, re-drive of FAILED, cancelling a run, draining workers) | **Absent** |
| **Backups / restore** of Postgres (audit and history are graded evidence) | **Absent.** At minimum: `pg_dump` before each graded batch, and `runs/`/`results/` exports committed. |
| **Migrations** (tool, who runs them, ordering vs workers, forward-only) | **Absent.** Recommend a plain `migrations/NNN_*.sql` applied by a one-shot `migrate` job before workers start, forward-only. |
| **Secrets rotation** (webhook secret, App key, Claude/Jev keys) | **Absent.** Recommend the gateway accepts two webhook secrets during rotation and keys are reloaded on restart. |
| Data retention (distilled logs, raw logs, runs) | **Absent** |
| Contract/version skew across independently deployed agents | **Absent** (see AD-6 row) |
| A2A protocol binding and version (JSON-RPC vs REST vs gRPC; 1.0 vs 0.3 compat) | **Absent.** a2a-sdk 1.x serves several bindings (context7). Pin one, e.g. JSONRPC 1.0, for all cards. |
| Observability | Decided (JSON logs + audit), OTel deferred |
| Cost accounting | Decided (AD-18) |
| Testing strategy (unit, promptfoo, red-team, E2E) | Implied by layout. The red-team dry-run target is undefined (B5). |
| Scenario success definition | Decided, except S5's trigger (A2) |

### 2.5 Mermaid validity

All five diagrams should parse on current Mermaid (10.x/11.x). Specific checks:

- **Layer flowchart:** valid. It omits the gateway → orchestrator path for `/triage` and does not show whether the direct `workflow → Jev API (routing)` call goes to Jev or to the Jev agent. It is inconsistent with the layer table, which lists "Jev (routing)" as a callee of `workflow`.
- **stateDiagram-v2:** it parses (labels with `<` and `/` are accepted, and duplicate `REVIEWING --> GATING` edges with different labels are legal). **Semantic issues:** FAILED is absent, the AD-8 edges are missing, "confidence < class cutoff / unknown / no-route" puts three triggers on one edge, AWAITING_APPROVAL has a single `approve` target, and there is no expiry. `DISTILLING → CLASSIFYING` hides suspect narrowing and history lookup. Recommend generating the diagram from the transition table.
- **Structural seed flowchart:** valid. `<-->` needs Mermaid ≥ 9.3. `IR <-->|A2A approve/reject| CLI` is fine. It does not show where the Log Distiller lives in the directory layout (the layer table has no row for it), and the `REJECTED_BY_HUMAN` report path is missing.
- **erDiagram:** valid. `triage_run ||--o| approval` (at most one approval) contradicts the need to audit denied non-CODEOWNER attempts. Either add `approval_attempt` or make the relationship `||--o{`. `history` is shown as optional per run, but seeded history has no run (C4).
- **Deploy flowchart:** valid (`&` chaining and quoted subgraph titles are supported). The k8s subgraph shows only a NetworkPolicy, with no ingress, Postgres, or migrate job.

---

## Consolidated proposed AD additions (one line each)

1. **AD-21 Quarantine:** quarantine is a recommendation field, never in `proposed_diff`. Flaky diffs must be root-cause changes that pass the gate (A1).
2. **AD-1a Escalation context:** AWAITING_APPROVAL stores `escalation_reason` + `proposal_step_id?`. `approve` → PR_OPENING only with a proposal, else → REPORTING. `reject` → REPORTING → REJECTED_BY_HUMAN (A2, A9).
3. **AD-14a Approval binding:** the approval references `proposal_step_id` + diff hash. CODEOWNERS is read from the protected default-branch tip (A3, D2).
4. **AD-1b Complete edges:** every agent state has a validation-failed and a low-confidence edge to AWAITING_APPROVAL. The `* → FAILED` edges are in the table, and the diagram is generated from the table (A4, A7).
5. **AD-22 Retry/FAILED:** 3 transient attempts with backoff, separate from AD-8, each costed as its own `run_step`. FAILED is terminal, writes history, and re-drive creates a new run (A5).
6. **AD-23 Lease and fencing:** short claim transaction sets `lease_owner`/`lease_until`. The commit transaction re-checks the lease (C1).
7. **AD-24 Evidence pack:** a deterministic DISTILLING builds `EvidencePack` (distilled numbered log, `candidate_suspects`, history rows, runner metrics, repo files). `last_green` is defined. The Analyzer chooses only among candidates (B1, B2, B4, B7).
8. **AD-6a Diff shape:** `proposed_diff = {base_sha, files[{path, op, new_content}]}`. Red-team `terminal_state` uses the state enum, with a `dry_run` skill flag (B3, B5).
9. **AD-9a Confidence storage:** `confidence_jev` is immutable, `confidence_effective = min(...)` with `caps[]`, and a `jev_signal` citation kind is added (B6).
10. **AD-12a Severity:** `{info, minor, major, dangerous}`. Accepted = no major or dangerous. `revision_round < 2` (A6).
11. **AD-16a Scopes:** add `contents:write` (triage/* only) and `issues:write`. Never push `.github/workflows/**`. Installation tokens are minted per step (D1, D4).
12. **AD-4a TaskStore:** a read-only adapter over `triage_run` with no a2a-db tables. The approval handler only transitions, guarded by the current state (C2, C3).
13. **AD-15a History:** seeds go through a `history import` path. Fingerprint defined. Post-terminal PR verdicts go to `pr_feedback` (C4, C5).
14. **AD-17a Run identity:** unique `(repo_id, workflow_run_id, run_attempt)`. Same-fingerprint runs on the same branch are superseded (C6).
15. **AD-10a Registry digest:** canonical JSON with URLs excluded, and a registry file per environment (E1).
16. **AD-25 Operational envelope:** forward-only SQL migrations applied by a one-shot job before workers start; `pg_dump` before graded batches; dual webhook secrets during rotation; per-skill `step_timeout`; a pinned A2A binding (JSONRPC 1.0); an `approval_ttl` (A10, §2.4).
