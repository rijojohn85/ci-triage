---
title: Stage 4 rubric map: Blameless CI triage (A2A)
source: .memlog.md (brainstorm 2026-09-25). `Lnn` means memlog line nn.
scope: v1 certification slice only (L83, L131)
---

# Stage 4 rubric map: Blameless CI triage (A2A)

Tagline (L61): "Blameless CI triage: who, why, how sure, and a fix, with receipts."
Architecture (L124): hub-and-spoke orchestrator (an A2A server with an explicit state machine) calls the A2A agents. Postgres holds the queue, history and audit. One cluster serves many repos.
v1 is done when (L92): all 5 scenarios pass end to end (5/5), and red-team findings are documented. Zero findings is not required.

**Scenarios** (L93)
- **S1:** code bug under concurrent pushes, with 2 suspect commits. Ends in a fix PR to the author.
- **S2:** flaky test. Ends in a deflake PR plus quarantine.
- **S3:** infra OOM. No PR. Ends in an infra report to on-call.
- **S4:** external API failure. Ends in a mock/contract-test PR.
- **S5:** high-risk or low-confidence case. Ends in a human punch-out via A2A `INPUT_REQUIRED`.

**Success rule** (L94): a scenario succeeds when it reaches the correct terminal state. An escalation counts as success when escalation is the expected outcome.

`GAP` marks something the memlog does not decide.

---

## 1. Folder/file map

| Folder / file | Purpose | v1 components that fill it (memlog) | Proven by | Evidence artifact to produce |
|---|---|---|---|---|
| `prompts/` | AI agent prompts | Claude Analyzer: explains Jev's verdict and cites evidence (L49). Fix Proposer, Sonnet (L15, L43). Adversarial Reviewer, Opus/Sonnet, checks blast radius (L15, L43). Router/Notifier: finds the owner from CODEOWNERS+blame (L15). Deflake Advisor (L18, L29). External-dep mock proposer (L38). Haiku distill-summary (L43). | S1–S5 | One prompt file per agent. Each states its model tier and its evidence-cited output schema (L35). |
| `agents/` (extra) | A2A Agent Cards + servers | Every agent is an A2A server with an Agent Card, built on the Python A2A SDK (L44). Jev is wrapped as an A2A agent with skill `classify` (L52). Discovery works by skill **and** description (L126). Stage 1 is an exact skill-id/tag match. Stage 2 is a Jev description-routing fallback. Below threshold, discovery returns a no-route error (L129). Card URLs are allowlisted, and card text is untrusted (L130). | S1–S5 (routing). A no-route case is `GAP` (no scenario covers it). | Agent Card JSON for each agent, the registry allowlist, and a routing log showing tag matches vs description fallback |
| `workflow/` | End-to-end handoffs, branching, revision | Orchestrator state machine (L124). Pipeline order: webhook → Log Distiller (deterministic, L24) → suspect-commit narrowing (L23) → history lookup (L66) → Jev classify (L48) → Claude Analyzer (L49) → branch by class (L19, L33, L38) → Fix/Deflake/Mock proposer → Adversarial Reviewer → risk gate (L20) → draft PR + Triage Card (L98), or infra report (L101), or `INPUT_REQUIRED` (L72, L107). | Branching: S1 code, S2 flaky, S3 infra, S4 external, S5 escalate | State-machine definition, a handoff diagram, and the branch table (class → action, L63). **Revision loop: `GAP`** (see §4). |
| `guardrails/` | Schema validation, risk checks, review gates, human approval | Schema validator rejects claims without citations (L35). Tiered risk gate: diffs that disable/skip tests or touch CI config, secrets or infra manifests are BLOCKED and escalated (L20). Deflake guard: loosened assertions, added retries, bumped timeouts or skips are escalated (L37). Low-confidence branch: confidence below threshold or conflicting signals trigger a punch-out (L36). Adversarial Reviewer (L15). Jev injection pre-screen on distilled logs, layer 1 only, ~69% recall (L50, SHOULD). Jev risk scorer (L51, COULD). Webhook HMAC + delivery-ID dedupe (L70, L74). Least privilege: agents hold no tokens and can only open draft PRs (L56, L71, L135). Every PR needs human approval, never auto-merge (L16). Retrieved and stored text is treated as untrusted (L31, L67). | S1, S2, S4 (gate passes, draft PR). S2 (deflake guard sees a legitimate fix). S5 (gate blocks or confidence is low). | Validator rules and unit tests, the risk-gate rule list, Reviewer verdicts per run, and the GitHub App permission manifest |
| `punch-out/` | Evidence of human escalation + a bypass scenario | Two tiers of human (L134). Tier 1: routine draft-PR approval by the dev. Tier 2: authority escalation to the team lead via `INPUT_REQUIRED` (L102). The paused task is stored in the DB and no worker holds it (L123). Approval resumes the task (L72). The evidence pack goes to the approver with no blame (L36). | S5 (escalation). S1–S4 (non-escalation path). | S5 run showing the state moving WORKING → INPUT_REQUIRED → (approve) → COMPLETED. Approver identity, the evidence pack and a timestamp. **Bypass scenario: `GAP`** (see §4). |
| `monitoring/` + `runs/` | Audit trail: per-step input/output tokens, total tokens, cost, status, outcome | Usage audited per step (L43). Postgres audit table (L124). Model tiering gives the cost story: Haiku, then Sonnet, then Opus (L43). Deterministic distiller cuts tokens (L24). Jev costs about $0.042/M input tokens (L47). | S1–S5 | One JSON/row per step with agent, model, in/out tokens, cost, status and outcome. A per-run total. **Claude pricing: `GAP`** (L109). |
| `test-data/` | Scenarios | Synthetic demo repo with seeded failures: a bug commit, a flaky test, OOM/infra, an external API, concurrent pushes (L41). JUnit XML plus logs (L42, L76). | S1–S5 | Scenario manifest: seed, expected class, expected terminal state, expected suspect SHA |
| `demo-repo/` (extra) | Target repo that raises real CI failures | Python repo (L40, L41). GitHub Actions CI. GitHub App installed with least privilege (L71). `.ci-triage.yml` (L78; the memlog does not say whether it is v1 or v2: `GAP`). 2nd language is a COULD (L131). | S1–S5 | Repo link or snapshot, the seeded commits, and the CI run IDs |
| `gateway/` (extra) | Webhook intake | GitHub App webhook (`workflow_run` completed, failure). HMAC `X-Hub-Signature-256` check. Returns 202 fast, then queues (L70). Replay dedupe by delivery ID (L74). Postgres `SKIP LOCKED` queue (L120). Local run on kind/k3d + smee/cloudflared, with a docker-compose fallback (L73). Coalescing and priority lanes are COULD (L121–122, L131). | S1–S5 (intake). Forged-webhook test in `redteam/`. | Gateway logs: accepted runs and rejected forged/replayed deliveries |
| `tests/<agent>.promptfooconfig.yaml` | Each agent evaluated on its own before wiring | promptfoo evals for every agent (L9). Pass bar is `GAP` (L95). | Per agent (not per scenario) | One promptfoo yaml + results per agent (Classifier/Jev, Analyzer, Router, Fix, Deflake, Mock, Reviewer) |
| `redteam/` (extra) | Adversarial review | promptfoo redteam: `indirect-prompt-injection` with `indirectInjectionVar`, `jailbreak`, `jailbreak-templates`, https target (L108). Targets: logs that try to flip Jev's class (L53). Poisoned history, commit messages and PR titles (L67). Rogue Agent Card claiming all skills (L130). Forged webhook (L74). Cross-repo leakage via bola/rbac (L117, SHOULD). Weekly regeneration and the OWASP LLM Top 10 table are COULD (L57–58). Found attacks are frozen into a regression suite (L57). | Mostly outside S1–S5. S5 may carry an injected log (`GAP`: not decided). | Red-team config, the findings report (pass/fail per plugin), and the regression suite |
| `evals/feedback/` (extra) | Human verdicts become new test cases | Each approve, reject or edit of a draft PR is appended as a promptfoo case (L87, L89). Tier: v1 add (L89) but SHOULD in MoSCoW (L131). | S1, S2, S4 (PR verdicts). S5 (approver verdict). | Generated test cases linked to the source PR |
| `history/` or DB schema (extra) | Structured grounding in place of RAG | SQLite/Postgres past runs: test_id, fingerprint hash, class, SHA, runner metrics (L66). MUST (L127). Fingerprint by normalized error+stack hash, exact match (L28, L66). Queries scoped by repo_id (L116). | S2 (flaky history). S3 (runner metrics). S1 (other PRs failing the same test, L26). | Schema, seed rows, and the lookup log for each run |
| `results/` | Workflow monitoring results | E2E success table, 5/5 target (L92). Calibration/reliability table: confidence vs actual correctness. MUST (L62, L128). | S1–S5 | Success table, calibration table, cost/token summary, red-team summary |
| `README.md` | Overview + decisions | JTBD and hirers (L97–105). Architecture choice A over B/C (L110–124). RAG considered and rejected, with reasons (L65, L68). Jev limits (L47, L50). Least-privilege rationale (L135). OWASP table (COULD, L58). | — | README sections that match this map |

---

## 2. Grader-criteria checklist

**1. Workflow definition**
- [ ] Orchestrator state machine is documented, with states and transitions (L124)
- [ ] Handoffs follow the pipeline order in §1 `workflow/`
- [ ] Branch table: code / flaky / infra / external / escalate each map to an action (L19, L33, L38, L63)
- [ ] A2A discovery shown working by tag and by description fallback (L126, L129)
- [ ] Revision loop defined and shown (`GAP`)

**2. Guardrails (automated checks + adversarial review)**
- [ ] Citation schema validator rejects uncited claims (L35), with a failing example
- [ ] Risk-gate rules (L20) and deflake guard (L37), each with a blocked example
- [ ] Confidence threshold → punch-out (L36). Threshold value is `GAP`.
- [ ] Adversarial Reviewer verdicts attached to every PR-producing run (L15)
- [ ] Webhook HMAC + replay rejection (L70, L74)
- [ ] promptfoo red-team report, with findings documented (L92, L108)
- [ ] Least-privilege token manifest (L71)
- [ ] Per-agent promptfoo evals pass the bar (`GAP`, L95)

**3. Human punch-out**
- [ ] S5 trace: `INPUT_REQUIRED` → approver action → resume (L72, L107)
- [ ] Evidence pack plus a named approver (team lead) (L36, L102)
- [ ] Paused task persisted, worker freed (L123)
- [ ] Every other run ends in a draft PR that waits for dev approval, with no auto-merge (L16)
- [ ] Bypass scenario (`GAP`)

**4. E2E success rate**
- [ ] S1–S5 run against the demo repo, and each run records expected vs actual terminal state (L94)
- [ ] 5/5 in `results/` (L92)
- [ ] Calibration table (L128)

**5. Audit trail**
- [ ] Per step: input/output tokens, total, cost, status, outcome (L43, L124)
- [ ] Evidence citations for each run: log line, SHA, metric (L35)
- [ ] Human decisions logged (approver, verdict, time), which also feeds `evals/feedback/` (L89)
- [ ] Claude costs computed from verified pricing (`GAP`, L109)

---

## 3. Scenario × criterion coverage

| Criterion | S1 code | S2 flaky | S3 infra | S4 external | S5 escalate | Outside scenarios |
|---|---|---|---|---|---|---|
| Workflow / branching | code → fix PR. Suspect narrowing picks from 2 suspects. | flaky → deflake PR + quarantine | infra → no PR, infra report | external → mock PR | → INPUT_REQUIRED | no-route discovery (`GAP`) |
| Guardrails | schema + gate pass. Reviewer checks blast radius. | deflake guard must allow a legitimate fix and block a masking one (`GAP`: which does S2 show?) | no PR, so no gate. Schema still applies. | gate pass (test double, not a skip) | gate blocks and/or low confidence | `redteam/`, HMAC, rogue card |
| Human punch-out | dev approves draft PR (tier 1) | dev approves (tier 1) | on-call receives report (no approval step) | dev approves (tier 1) | team lead approves (tier 2) | bypass (`GAP`) |
| E2E success | terminal = fix PR opened, correct author | terminal = deflake PR opened | terminal = report to on-call | terminal = mock PR opened | terminal = escalated | — |
| Audit trail | ✓ | ✓ | ✓ | ✓ | ✓ plus approval record | red-team run logs |
| Calibration (results/) | point | point | point | point | point with low confidence | 5 points are thin (`GAP`) |

---

## 4. Gaps / open questions

- [ ] **Per-agent promptfoo pass bar.** Use the Stage 3 quality bar, but the exact threshold is not confirmed (L95).
- [ ] **Claude pricing.** Verify via the claude-api skill at build time, not from memory (L109). The Jev price is web-reported (L47) and not verified.
- [ ] **Revision loop.** The rubric asks for "revision", but the memlog never defines a Reviewer-reject → Proposer-revise loop (max iterations, exit to punch-out). A human "edit" only feeds evals (L89).
- [ ] **Bypass scenario for `punch-out/`.** Not defined. Possible readings: a routine path that skips tier-2 escalation, or a proof that a bypass attempt is blocked. Pick one.
- [ ] **Confidence threshold value**, and how "conflicting signals" is computed (L36, L129).
- [ ] **What S5 triggers.** High-risk, low-confidence, or both, and whether it includes an injection attempt (L93).
- [ ] **S2 deflake guard behaviour.** Must a legitimate root-cause deflake pass while a retry/timeout bump escalates (L18, L37)?
- [ ] **Quarantine mechanism for S2.** A PR edit that skips a test would trip the risk gate (L20). How the two interact is undefined.
- [ ] **Calibration sample size.** 5 scenarios give 5 points. Decide whether to run repeats or variants.
- [ ] **MUST list.** L131 says "MUST + history + calibration + discovery" but never lists the base MUSTs. Confirm that everything in §1 not tagged SHOULD/COULD is MUST.
- [ ] **Priority conflicts.** The feedback loop is a "v1 add" (L89) but SHOULD (L131). The Triage Card is a "v1 serves" (L105) but SHOULD (L131). Confirm the tier for each.
- [ ] **`.ci-triage.yml` and the code dependency graph tool** (L30, L78). Not placed in MoSCoW; confirm v1 or v2.
- [ ] **Model tiering is still an idea** (L43), not a recorded decision. Confirm the final model per agent.
- [ ] **Deferred red-team targets.** Weekly red team, the OWASP table and cross-repo leakage are SHOULD/COULD. Decide which to include so `redteam/` evidence is scoped.
- [ ] **Demo repo location** (in-repo vs separate GitHub repo) and the GitHub App setup evidence are not specified.
