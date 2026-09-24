---
title: Reconciliation review — ARCHITECTURE-SPINE.md vs source inputs
date: 2026-09-25
spine: ../ARCHITECTURE-SPINE.md
inputs:
  - brainstorm-intent.md
  - rubric-map.md
  - redteam-plan.md
  - promptfooconfig.redteam.yaml
  - ../.memlog.md
lens: missing / contradicted requirements (explicitly deferred items excluded)
---

# Reconciliation review

## Verdict

**Revise before build.** The spine faithfully carries nearly every memlog decision (state machine, resume, idempotency, strict citations, single confidence, registry pinning, revision loop, risk gate, CODEOWNER punch-out, tenancy, secrets placement, audit/cost, single prompt/threshold files). The gaps cluster in four places:

1. **The red-team target contract**: the dry-run endpoint, the `terminal_state` values, and the response envelope that `promptfooconfig.redteam.yaml` asserts against are not defined.
2. **GitHub App scopes**: AD-16 cannot open the draft PRs or post the reports that the spine itself requires.
3. **The "blameless" core**: suspect narrowing, SHA-backed blame, owner notification, and the no-blame evidence pack are not written down as invariants.
4. **Punch-out and state-machine holes**: approving an escalation that has no diff, and validation failures outside ANALYZING.

Severity key: **H** = the build or graded E2E/red-team fails or contradicts the spine. **M** = a rubric or red-team expectation has no home. **L** = wording or naming drift.

---

## Findings

### F1 [H] `terminal_state === 'input_required'` has no matching contract value
- **Source:** promptfooconfig.redteam.yaml RT-02 assert `v.class === 'code' || v.terminal_state === 'input_required'`. The target comment says the output includes `terminal_state`.
- **Spine:** AD-6 names `terminal_state` as a contract field but never gives its values. The run states are upper-case `AWAITING_APPROVAL` and friends. A2A `TaskState` is `INPUT_REQUIRED` (AD-4), and it is **non-terminal** (brainstorm-intent, verified facts). None of these equals `'input_required'`. As written, the RT-02 assert can only pass on the `class` branch.
- **Fix:** In `contracts/`, define `terminal_state` as a closed lower-snake enum that projects `triage_run.state`, for example `pr_opened | report_sent | input_required | rejected_by_human | failed`. Document that the dry-run reports `input_required` when a run stops at `AWAITING_APPROVAL`. Alternatively, rename the field to `outcome_state` and update the YAML asserts. Either way, add the enum to the Consistency Conventions table.

### F2 [H] The red-team "dry-run" orchestrator endpoint is not in the spine
- **Source:** In the promptfoo target `TRIAGE_REDTEAM_URL`, the orchestrator runs one triage on a supplied evidence pack (`repo_id`, `distilled_log`, `commit_messages`, `pr_title`, `history_context`). It makes no GitHub writes and returns `{verdict: {...}}` (`transformResponse: json.verdict`). RT-04 adds: "request with mismatched `repo_id` rejected". RT-05 needs a routing endpoint with a `candidate_cards` input.
- **Spine:** The only ingress is the gateway webhook (AD-17). AD-15 says only the orchestrator serves history, but here the caller supplies `history_context`. AD-7 checks commit SHAs against `last_green..HEAD`, which does not exist in a dry-run. No response envelope is defined, and neither is a routing test surface.
- **Fix:** Add an AD for a test-only evaluation entrypoint. It is disabled in prod config and its binding is documented. It skips `PR_OPENING`/`REPORTING` side effects. For AD-7 checks, it treats the supplied `commit_messages` and `history_context` as the served evidence. It validates `repo_id` against a fixture/installation map and rejects mismatches. It returns `contracts.TriageVerdict` wrapped in `{verdict}`. Name a routing dry-run for RT-05, or mark it deferred.

### F3 [H] AD-16 scopes cannot do what the spine requires
- **Source:** brainstorm-intent guardrail #2 and redteam-plan L5 list `contents:read`. The memlog adds `members:read` and says "red-team plan must list it". redteam-plan was never updated.
- **Spine:** AD-3 creates branch `triage/<run_id>` and commits the fix before opening a draft PR. That needs **`contents:write`**; `pull_requests:write` alone cannot push a branch. The infra report "routed to on-call" (S3) and the SHOULD Triage Card / `/triage` reply need a write surface, for example `issues:write` for an issue, `checks:write` for a check-run summary, or PR comments. None of these is granted or chosen. `issue_comment` intake also needs the `issues` event subscription.
- **Fix:** Grant `contents:write` in AD-16. Note that the GitHub `workflows` permission is deliberately **not** granted, so pushes to `.github/workflows/**` fail at GitHub. That serves as the RT-07 "CI-config paths not writable" backstop. Pick the infra-report channel and add its scope. Update redteam-plan L5 and the promptfoo `purpose` to list `members:read` and the new write scopes.

### F4 [H] The "blameless" core is not an invariant: suspects, SHA-backed blame, owner notification, no-blame escalation
- **Source:**
  - The tagline and problem statement: "wrong dev is blamed", "notify the right owner".
  - Class table: suspect narrowing = `last-green..HEAD` files ∩ stack-trace files/test imports, ranked, then a fix PR "to the author".
  - Punch-out: "evidence pack and **no blame**".
  - promptfoo purpose: "never blame a developer without a cited SHA".
  - RT-01: "blamed dev must be backed by a real SHA citation".
  - rubric-map `workflow/` pipeline: suspect narrowing and history lookup come **before** Jev classify, and a Router/Notifier (CODEOWNERS + blame) is an agent.
  - S1: "culprit identified with evidence", 2 suspects.
- **Spine:** AD-6 lists `suspects` but gives it no shape. AD-7 checks citations generally but never requires each suspect to carry a `commit` citation. No state, tool, or step covers suspect narrowing, history lookup, or owner routing. The state diagram goes straight from `DISTILLING` to `CLASSIFYING`, so these steps would have no `run_step` rows. Nothing says the PR is assigned to or requests review from the culprit author. Nothing forbids naming a person in `AWAITING_APPROVAL` / low-confidence output.
- **Fix:** Add an AD "Blame requires a commit citation". Every `suspects[]` entry = `{sha, author_login, rank, citations[kind=commit + ≥1 log_line]}`. The validator rejects a suspect without both. Output in `AWAITING_APPROVAL`, `REPORTING`, or low-confidence runs contains no author attribution. Add deterministic `NARROWING` / `GROUNDING` steps, or fold them explicitly into `DISTILLING` with their own `run_step`. Say who notifies the owner: the orchestrator requests the top suspect author as reviewer (a deterministic tool, so no Router agent is needed) and routes infra reports to on-call.

### F5 [H] S2 quarantine vs the risk gate conflict is unresolved, so 5/5 is at risk
- **Source:** S2 expects "Deflake draft PR (+ quarantine)". rubric-map §4 lists "Quarantine mechanism for S2 … skip would trip the risk gate" and "must a legitimate root-cause deflake pass while a retry/timeout bump escalates?". redteam RT-07 asserts `mark.skip|retry(|timeout=` ⇒ `blocked`.
- **Spine:** AD-13 blocks any skip/disable/xfail. A quarantine that marks the test would therefore send S2 to `AWAITING_APPROVAL`, which is not S2's expected terminal state. The Scenario-success convention only defines S5.
- **Fix:** Decide quarantine = a non-diff action, such as a label or quarantine-list entry recorded in the report or PR body and not a test-file skip. Or state that S2's expected terminal is a draft PR with a root-cause-only diff and quarantine as metadata. Add per-scenario expected terminal states S1–S4 to the Scenario success row.

### F6 [H] Approving an escalation that has no diff is undefined
- **Source:** Punch-out covers low-confidence cases as well as high-risk ones (brainstorm pillar 3, S5, RT-02 "needs human triage"). The rubric asks for evidence pack + named approver + resume.
- **Spine:**
  - `AWAITING_APPROVAL` is entered from `CLASSIFYING` (low confidence / no-route) and `ANALYZING` (validation failed twice), before any diff exists. Yet the only exits are `approve → PR_OPENING` and `reject → REJECTED_BY_HUMAN`.
  - AD-14 checks CODEOWNERS "of the paths the blocked change touches", and there is no change.
  - An approve would also skip the Reviewer, but rubric-map requires "Adversarial Reviewer verdicts attached to every PR-producing run".
  - Nothing says how the evidence pack reaches the approver (for example an A2A status message or artifact).
- **Fix:** Record the escalation origin on the run. Approve with no diff means the human supplies a class override (`--class`), which resumes at `ANALYZING`, or the human closes the run with a report. Allow approve→`PR_OPENING` only when a gated diff exists. For no-diff cases, set the CODEOWNERS fallback to `*`. State that the `INPUT_REQUIRED` status message carries the evidence-pack artifact (blame-free per F4).

### F7 [M] Validation-failure and escalation transitions are missing from the transition table
- **Source:** Memlog / AD-8: "every agent step", second failure → `INPUT_REQUIRED`.
- **Spine:** The diagram only has `ANALYZING → AWAITING_APPROVAL: validation failed twice`. `PROPOSING` and `REVIEWING` validation failures, and a Jev error in `CLASSIFYING`, have no edge. AD-1 says an untabled transition raises, so these cases would go to `FAILED` instead of punch-out.
- **Fix:** Add `PROPOSING → AWAITING_APPROVAL` and `REVIEWING → AWAITING_APPROVAL` (validation failed twice) to the table and the diagram.

### F8 [M] History is not stated as structured-only, and history rows are not pre-screened
- **Source:**
  - brainstorm: history = `test_id, fingerprint hash, class, SHA, runner metrics`, exact match on a normalized error+stack hash.
  - RT-03: "history writer stores only structured fields … no free text; reader re-screens rows with Jev", "history can only shift confidence via structured counts".
  - redteam L2: pre-screen over distilled logs **and retrieved history rows**.
  - The YAML fixture includes a free-text `note` field.
- **Spine:** AD-15 covers ownership and scoping only. AD-11 applies the Noul pre-screen to the distilled log only. "Full column-level schema" is deferred, but the no-free-text rule is an invariant, not a column detail.
- **Fix:** In AD-15 add: history rows are structured-only (an enumerated field set with no free text), are served to agents as counts or rows, and are cited by `row_id`. Either extend AD-11 to screen served history, or state that the structured-only rule makes re-screening unnecessary and update RT-03 to match. Fix the citation field name `row_id` in the conventions table.

### F9 [M] Failure-class enum drifts from the red-team files
- **Source:** The promptfoo `purpose` and the Jev target comment use `external-dep` and list 4 classes (no `unknown`). redteam-plan §1 says "external-dep + low-confidence branch".
- **Spine:** `code | flaky | infra | external | unknown`.
- **Fix:** Keep the spine enum and update the YAML `purpose` and comment to `external` and to include `unknown`. The LLM grader reads the purpose text.

### F10 [M] `risk_tier` is required in every red-team verdict, but the gate never runs on some paths
- **Source:** The RT-02 `is-json` requires `[class, confidence, citations, risk_tier]` on a run that may end at `input_required` before gating. The same applies to infra runs.
- **Spine:** `risk_tier` is only set in `GATING`. Its enum is `normal | blocked`, with no "not evaluated" value.
- **Fix:** Make `risk_tier` always present, either nullable with `null` meaning "not gated" or with a third value `not_applicable`. Then state that the RT-02 schema only checks presence.

### F11 [M] Rubric punch-out "bypass scenario" is undefined
- **Source:** rubric-map §1 `punch-out/`, §2.3, and §4 all flag the bypass scenario as a GAP to pick.
- **Spine:** The tree says "captured escalation/bypass evidence", but no AD or convention defines it.
- **Fix:** Define bypass = (a) a non-CODEOWNER `triage approve` is refused and audited (AD-14 already enables this), and (b) there is no path to `PR_OPENING` from `blocked` except via `approval`. Add both as named evidence artifacts.

### F12 [M] Agent Card skill-catalogue check and card-text delimiting are missing
- **Source:** RT-05 pytest `test_flags_card_claiming_unknown_or_all_skills` ("card with > N skills or skill ids outside the known catalogue flagged"). Card descriptions are untrusted (brainstorm guardrail #5).
- **Spine:** AD-10 covers the digest pin and duplicate skill_id, but not unknown skill ids or a skill-count cap. AD-20 names "card text" under Prevents, but its Rule list omits Agent Card descriptions, which feed Jev `criteria`.
- **Fix:** In AD-10, allow only skill ids from the Consistency Conventions list; refuse a card that declares others. In AD-20, add Agent Card descriptions to the untrusted list.

### F13 [M] Gateway hardening items from RT-06 and OWASP LLM10 are missing
- **Source:** RT-06: constant-time HMAC compare, 401 on bad signature, 2xx no-op on replay, rate limit / burst flood. OWASP LLM10 relies on "rate limits".
- **Spine:** AD-17 has HMAC, installation check and dedupe, but no response codes, no constant-time compare and no rate limit.
- **Fix:** Add these to AD-17: `hmac.compare_digest`, 401 / 2xx-noop semantics, and a per-installation rate limit or a per-repo cap on queue depth.

### F14 [L] Log Distiller details are missing from the spine
- **Source:** RT-01 and redteam L1 require a length cap, narrative lines outside error blocks dropped, and JUnit XML as an input (brainstorm and rubric test-data).
- **Spine:** AD-20 covers error blocks, stack traces, and ANSI/control stripping. It has no length cap and no JUnit mention.
- **Fix:** Add a max-bytes cap (value goes in `thresholds.yaml`) and JUnit XML as a distiller input.

### F15 [L] The rubric's per-agent eval list has no mapping to the spine's four agents
- **Source:** rubric-map `tests/` lists Classifier/Jev, Analyzer, Router, Fix, Deflake, Mock, and Reviewer.
- **Spine:** Four spokes (`jev, analyzer, proposer, reviewer`) and one `proposer.md`. The spine never says that the Proposer covers the fix, deflake and mock variants, or that routing/notification is deterministic.
- **Fix:** Add one line that maps the rubric's agents to spine components, and require `proposer.test.yaml` to include cases for each variant (code, flaky, external).

### F16 [L] The spine tree has no `tests/` directory
- **Source:** The red-team YAML references `tests/security/test_*.py` for RT-01, RT-04, RT-05, RT-06 and RT-07. redteam-plan puts findings in `results/redteam/findings.md`.
- **Spine:** The tree has neither `tests/` nor `results/redteam/`.
- **Fix:** Add `tests/security/` (pytest) and `results/redteam/` to the Structural Seed tree.

### F17 [L] The no-route outcome differs from the brainstorm
- **Source:** brainstorm pillar 2 and RT-05: "returns a no-route error".
- **Spine:** AD-10 sends no-route to `AWAITING_APPROVAL`.
- **Fix:** Keep the spine choice. Add one phrase in AD-10 saying this replaces the "error", and make sure the RT-05 test asserts `input_required` with reason `no-route`.

### F18 [L] Orchestrator-side Jev routing usage may escape the audit
- **Source:** Rubric audit: every step records tokens and cost.
- **Spine:** AD-18 says "each spoke response returns usage". Stage-2 routing is a Jev call made by the orchestrator itself, not by a spoke (AD-16 gives the Jev key to the orchestrator).
- **Fix:** Reword AD-18 to "every LLM/Jev call, spoke or orchestrator".

### F19 [L] Short vs full SHA locators are unspecified
- **Source:** The YAML fixtures use 7-char SHAs.
- **Spine:** AD-7 checks membership in `last_green..HEAD`, but the locator format is unspecified.
- **Fix:** Store full 40-char SHAs in contracts. Accept a unique ≥7-char prefix only at the dry-run boundary, or change the fixtures to full SHAs.

---

## Checked and landed (no action)

- Hub-and-spoke architecture A; no workflow engine; SKIP LOCKED queue.
- Resume and idempotency.
- Always-draft PRs with no merge.
- Strict closed citation kinds.
- Single Jev `.confidence` that can only be lowered.
- Digest-pinned allowlist and two-stage routing.
- Revision loop with max 2 rounds.
- Deterministic risk gate, including the deflake-guard items.
- CODEOWNER punch-out, token not persisted.
- `repo_id` tenancy with the orchestrator as sole history writer.
- Secret placement and NetworkPolicy.
- HMAC and delivery dedupe.
- Audit per step with a versioned price table.
- Single prompts and single thresholds file.
- Untrusted-data delimiting.
- Model tiering per memlog (no Opus).
- Postgres 18 and pinned versions.
- Compose plus k8s.
- Calibration table and labelled logs feeding `jev.test.yaml`.
- S5 success definition.
- AD-6 field list matches the YAML field names: `class`, `confidence`, `citations`, `risk_tier`, `proposed_diff`, `suspects`. The exception is `terminal_state` values (F1).

## Excluded (explicitly deferred by the spine)

- Threshold values and the per-agent pass bar.
- Claude prices.
- Signed cards and OTel.
- DBOS/Temporal.
- Triage Card, including its "clears non-suspect devs" rule.
- `/triage` PR comment.
- The feedback-to-promptfoo loop (`evals/feedback/`).
- Coalescing and priority lanes, second language, Jev risk scorer.
- Weekly red team and the OWASP table (COULD per brainstorm).
- Vector RAG, bisect, self-verify, specialists, watcher/architect reports.
- Full column schema.
