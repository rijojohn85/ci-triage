# Epic 6 Context: Demonstrate reproducible outcomes and accountable model usage

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

This epic produces the certification evidence for the whole system: prove that triage quality is reproducible and that model usage is accountable. It instruments every model/Jev call with auditable usage and centrally computed costs, calibrates the confidence cutoffs against labelled data, records per-agent eval pass decisions against a human-supplied bar, verifies the deployment runs identically under Compose and k8s, then seeds and drives the five real-GitHub scenarios (S1–S5) through one graded batch and exports a single results index a grader can trust. The 5/5 expected-versus-actual claim may only be made from real receipts, never from fixtures or invented numbers.

## Stories

- Story 6.1: Collect every model call and attempt centrally
- Story 6.2: Compute versioned NULL-aware model costs
- Story 6.3: Calibrate confidence and central thresholds on labelled data
- Story 6.4: Record the supplied per-agent quality pass decision
- Story 6.5: Verify graded operations and same-image cluster manifests
- Story 6.6: Seed and drive the code and flaky GitHub scenarios
- Story 6.7: Seed and drive infra and external GitHub scenarios
- Story 6.8: Drive S5 high-risk timeout-bump and live human decision
- Story 6.9: Execute the final five-scenario certification batch
- Story 6.10: Export the results index and reproducible README

## Requirements & Constraints

**Usage audit (6.1).** Every LLM and Jev invocation — routing, spoke calls, validation retries, transient retries — is recorded as its own identifiable attempt with model, input/output tokens, cache-read tokens, and 5m/1h cache-write tokens kept distinct, plus status and outcome. Usage returned by a failed call is still persisted. Counters a provider doesn't report are stored as NULL, never 0; usage lost to a crash stays explicitly incomplete. Audit collection lives in the orchestrator/eval harness — agents never touch the database. Log lines carry run_id, task_id and step; no tokens, secrets or raw logs.

**Costing (6.2).** Costs are computed centrally from one versioned price table (per-token-type, per-model rates, each with source URL and retrieval date). Claude prices must be verified from official sources at build time. Jev pricing is unresolved and stays NULL/flagged — no historical estimate may be substituted. Runs with unavailable counters or unsourced rates carry visibly incomplete totals, never silently summed zeros.

**Calibration (6.3).** Final cutoffs must come from labelled-data evidence beyond the five demo scenarios; class confidence and routing confidence are calibrated separately. The single thresholds file is the only home for final values and documents their provenance. Human decisions on the calibration population and cutoffs must be captured explicitly — never invented.

**Per-agent quality pass (6.4).** All four agent suites (Jev classification, Analyzer, all three Proposer variants, Reviewer) are compared against the user-supplied pass bar, with links to complete eval reports. Evaluated prompt files must be the same files the runtime loads. A missing bar keeps certification pending; the Analyzer may switch Haiku→Sonnet via config with a same-suite rerun.

**Operations (6.5).** Compose (the graded E2E runtime) and plain k8s manifests must reference the same images and per-environment digest-pinned registries; forward-only migrations complete before workers start. NetworkPolicy must deny agent egress except to the model APIs, and only the orchestrator/tool layer may reach GitHub — denial must be proven with real traffic, not asserted from manifests. A graded batch requires a passing preflight: pg_dump taken first, plus a signed-tunnel smoke and service health checks.

**Scenario drivers (6.6–6.8).** S1–S5 run against the real synthetic GitHub demo repo with real CI and webhook delivery. Expected and actual outcomes are recorded as distinct values; a failure is reported, never papered over by rewriting expectations. Drivers must be able to recreate the fixtures. S5 requires a live authorized CODEOWNER approve/reject through the CLI on the same task — a synthetic decision does not count.

**The 5/5 claim (6.9).** Exactly five graded scenario rows; success requires every scenario criterion to pass (including S1's correct rank-1 suspect and S2's metadata-only quarantine). Branch, security and resilience receipts stay outside the denominator. Missing or failed receipts yield an honest incomplete/failed result.

**Exports (6.10).** `runs/` and `results/` are database exports, never hand-authored numbers. The results index must link every branch receipt, security/resilience test, eval report, calibration table and red-team finding to a real file, and the README must let a grader rerun everything. No unsourced pricing, model-lifecycle or pass claims may be added.

## Technical Decisions

- **Audit shape:** usage is recorded as `run_step` rows (one per attempt); costs come from a versioned `monitoring/prices.yaml`; exports are derived from these tables. Failed attempts and retries are costed individually.
- **Confidence model:** `confidence_jev` is immutable once written; the effective `confidence` is the minimum of it and any cited caps. Calibration reports both values. A human class override changes neither number — it only bypasses the low-confidence/unknown-class cutoff checks for that run.
- **Single sources:** all cutoffs live only in `guardrails/thresholds.yaml`; prompts exist once in `prompts/` and are the same files promptfoo evaluates; model IDs and timeouts come from config, never code.
- **Operational envelope:** same images across Compose and k8s; forward-only SQL migrations via a one-shot job before workers; pg_dump before each graded batch; dual webhook secrets during rotation; structured JSON logging; smoke test through the smee tunnel.
- **Blame-free output:** reports and paused-run output (S3 infra issue, S5 evidence pack) carry no author attribution; S3's report is an issue labelled `ci-triage/infra` with runner metrics, no PR.
- **Quarantine (S2):** is a PR label plus a quarantine list in the PR body — never written into the diff, which must be a root-cause deflake passing the risk gate.
- **S5 gate:** the risk gate deterministically blocks a timeout-bump diff; the run pauses with `gate_blocked` and INPUT_REQUIRED remains a resumable checkpoint, not a terminal state.
- **Idempotency:** every GitHub write is keyed `run_id + step` on branch `triage/<run_id>`; PRs are always draft.
- **Dry-run boundary:** the test-only dry-run skill is the only place a unique ≥7-char SHA prefix may be accepted; it is disabled in production config.
- **Receipts:** `test-data/demo-repo.md` records seed commits, full SHAs, CI run IDs, a tagged snapshot and resulting PR/issue/task references per scenario.

## UX & Interaction Patterns

No new UX is built in this epic. S5 reuses the punch-out CLI approval flow from Epic 5 (approve/reject on the same task, decision recorded with identity, note and time). The grader-facing "interface" is the results index and README: one place that distinguishes scenario success, branch coverage, eval quality and known limitations, with rerun instructions.

## Cross-Story Dependencies

**Within the epic (strict chain):** 6.2 needs 6.1's audit rows; 6.3 needs 6.2's costing plus the Jev/Analyzer eval and live-pipeline stories; 6.4 needs 6.3; 6.5 needs 6.2; scenario drivers build on each other (6.6 → 6.7 → 6.8) and on 6.5; the final batch 6.9 needs 6.4–6.8; the exports 6.10 need 6.9.

**From other epics:** 6.1 needs the atomic step persistence story (2.3); 6.5 needs lease/fencing (1.2), live-pipeline recovery (2.12) and least-privilege assertions (4.3); 6.6 needs the demo repo prepared in 0.4; 6.7/6.8 need the punch-out stories (5.4); 6.9 needs red-team execution (4.6).

**External gates:** the per-agent pass bar (OQ-1) and calibration population/cutoff decisions (OQ-2/OQ-5) block 6.4/6.3 acceptance; Jev pricing (OQ-3) may remain explicitly unpriced; the Analyzer model must be re-verified against the permitted Sonnet/Haiku set (OQ-4) if it changes. Story 6.5 needs a supported cluster/network-policy environment for traffic receipts (Compose stays the graded runtime). Story 6.8 needs a live authorized CODEOWNER; missing participation leaves it incomplete.

**Build-order note:** 6.1 and 6.2 execute early (phase 2 of the global build order) so no live call can escape auditing; 6.3–6.10 run in the final phase.
