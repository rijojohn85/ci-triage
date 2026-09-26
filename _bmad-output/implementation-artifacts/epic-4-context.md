# Epic 4 Context: Contain unsafe actions and demonstrate adversarial defences

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Prove that untrusted or adversarial input cannot silently turn into an ordinary GitHub write. This epic adds the deterministic safety layer — schema/citation validation, the risk gate, least-privilege and boundary verification — plus a side-effect-free way to drive the real pipeline for testing, and then executes the adopted red-team plan against real targets, recording findings and freezing successful attacks as permanent regression tests. Reviewers must be able to inspect recorded adversarial findings; unsupported claims, injection attempts and unsafe changes must be visibly caught, not assumed caught.

## Stories

- Story 4.1: Validate schemas, served citations and attribution
- Story 4.2: Block every deterministic risk rule
- Story 4.3: Assert real least privilege and data boundaries
- Story 4.4: Expose a production-disabled real-pipeline dry-run
- Story 4.5: Wire adopted red-team fixtures and verify configuration
- Story 4.6: Execute red-team coverage and freeze findings

## Requirements & Constraints

**Validation (pure, deterministic):**
- Agent output is checked against generated, committed JSON schemas; a schema failure is a structured validator error, never a silent pass.
- Citation kinds are a closed set (`log_line`, `commit`, `metric`, `history_row`, `jev_signal`); every citation must resolve against the evidence actually served to that run this run — log line numbers in the numbered distilled log, commits within `last_green..HEAD`, history rows among served rows, metrics among collected keys, Jev signals among this run's answers. Missing or unresolvable citations fail validation.
- Suspects must carry both a `commit` and at least one `log_line` citation. Confidence caps must carry cited reasons and can only lower confidence, never raise it. Foreign-repo evidence, short production SHAs, and probabilities used as confidence are rejected.
- Output destined for a human pause, a report, or any run whose confidence is below the class cutoff must contain no author attribution (blame-free), including after a human class override.
- Validation failure policy: one retry with validator errors fed back; a second failure pauses the run (`validation_failed`). Validators return errors to the shared step runner — they must not implement a competing workflow.

**Risk gate (deterministic, last word before GitHub):**
- A diff that skips/disables/xfails a test, adds retries, increases timeouts, loosens assertions, or touches `.github/workflows/**`, secrets, or infra manifests is `blocked`; so is any change the Reviewer marked `dangerous`. Model output cannot override the gate.
- Safe root-cause diffs are `normal`; runs with nothing to gate stay `not_gated`. Quarantine is metadata only (label + PR-body entry), never inside the diff.
- The gate is a pure module: structured evidence/reasons, no GitHub or Postgres calls. The actual pause transition is owned by the integrated workflow.

**Least privilege and boundaries (real evidence, not manifests):**
- Permissions and rulesets must be verified against the actual configured GitHub demo environment: read-only on actions/checks, write limited to contents (triage branches only), draft PRs, issues, org members read — and never the `workflows` permission. The default branch must require human review with the App not a bypass actor. A manifest alone cannot make a check pass; missing/mismatched real configuration fails.
- A synthetic probe must demonstrate GitHub itself rejecting an unauthorized workflow-file write, with a stored receipt; the probe stays off the protected default branch, never merges, and tokens/keys never appear in stored evidence.
- Static checks must confirm layer dependency and secret-placement rules for implemented layers (guardrails depends only on contracts).

**Dry-run (test-only evaluation entrypoint):**
- A test skill runs the real pipeline through GATING and returns the verdict with the standard terminal-state projection, with zero GitHub writes; early pause/report outcomes preserve real branch behaviour.
- It treats supplied commit messages and history context as the served evidence, rejects unknown repo IDs, and is the only place where a unique ≥7-character SHA prefix may be expanded; ambiguous or missing prefixes fail. Free-text history notes are ignored (poisoning defence).
- In production config the skill is disabled and absent as a usable skill; a write-spy regression must prove every test path stays side-effect free.

**Red-team execution and findings:**
- The adopted seed attack configuration must be validated against the installed promptfoo version and official docs before use; multiple target input maps, repeated plugins with distinct injection variables, and handwritten tests must be explicitly resolved (split configs if needed) — nothing silently omitted.
- Required coverage: log injection, Jev verdict flip, history poisoning, bug-hiding changes, harmful/jailbreak — with actual executed results, not assumed runs. Deterministic probes supply complementary receipts. Generated RT-04 plugins are optional; the RT-05 routing target stays deferred and is not reopened. No weekly schedule or OWASP publication work.
- Findings are recorded with probe, expected vs observed outcome, run/model version, which layers bypassed/caught, severity and status, mitigation, and regression reference. Severity/status counts, per-case attack success, and layer catch rates must include denominators. Severity definitions match the red-team inventory.
- A successful attack is frozen verbatim as a regression (per-agent or red-team regression suite) that runs on agent-code PRs; a "mitigated" status requires a regression reference. Zero findings is not a pass bar, and unexecuted coverage is never claimed.

## Technical Decisions

- **Guardrails layer purity:** `guardrails/` (schemas, validator, citation check, risk gate) imports `contracts/` only — no I/O, no GitHub, no Postgres. `workflow/` owns all state transitions; guardrails produce decisions, the workflow applies them.
- **Contracts are the single source:** inter-agent payloads are Pydantic v2 models; JSON schemas are generated into `guardrails/schemas/`, committed, and CI fails on drift. `TriageVerdict` always carries class, confidence, `confidence_jev`, caps, suspects, citations, `risk_tier` (`normal | blocked | not_gated`, always present), terminal state, nullable proposed diff and quarantine.
- **SHA discipline:** full 40-character SHAs everywhere; the ≥7-character unique-prefix expansion exists only at the dry-run boundary.
- **Confidence model:** `confidence` = `min(confidence_jev, caps…)`; immutable once written; nothing raises it. Cutoffs come only from `guardrails/thresholds.yaml` (class cutoff, injection screen, etc.), never code.
- **GitHub App posture:** permissions are minimal and fixed; the `workflows` permission is never granted so GitHub itself rejects workflow-file pushes (a platform backstop behind the risk gate). Installation tokens are minted per step and held only by the orchestrator; secrets never appear in runs, logs, prompts, or stored evidence.
- **Dry-run skill:** `triage-dry-run` is in the skill catalogue as test-only, disabled by prod config, and is the red-team target — probes exercise deployed logic, not a parallel fake pipeline.
- **Red-team tooling:** promptfoo (pinned version) with a root `promptfooconfig.redteam.yaml`; findings land in `results/redteam/findings.md` plus report exports.

## Cross-Story Dependencies

- **Within the epic:** 4.5 depends on 4.4 (red-team targets need the dry-run entrypoint); 4.6 depends on 4.5 and on 5.4 (approval-bypass coverage follows the approval epic).
- **On earlier epics:** 4.1 needs the contracts package, evidence-pack and projection fixtures, and the shared step runner (0.2, 2.2, 2.4, 2.7). 4.2 needs contracts and the evidence pack (0.2, 2.2). 4.3 needs the configured GitHub demo environment from 0.4 — real receipts are mandatory; local mocked checks alone cannot satisfy the real-permission criteria — plus intake, isolation and history work (1.1, 2.5, 2.6, 2.7). 4.4 needs E2 workflow integration, independently evaluated E3 agents, and the E5 approval handler (2.12, 3.10, 5.4).
- **Epic-level boundaries:** reusable validators and the risk gate land early because E2/E3/E5 integration consumes them; gate and security controls precede any GitHub writes. Component tests stay with the owning epics (E1/E2/E3/E5) — this epic owns the consolidated adversarial coverage and closes gaps between them.
