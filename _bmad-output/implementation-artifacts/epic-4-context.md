# Epic 4 Context: Contain unsafe actions and demonstrate adversarial defences

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Prove that untrusted input cannot fabricate a valid triage outcome and that unsafe proposed changes are contained before anything reaches GitHub. This epic hardens the pipeline with deterministic validation and a risk gate, verifies real least-privilege permissions against the prepared demo environment, and then demonstrates the defences work by running an actual red-team suite (promptfoo) against the real pipeline and freezing the findings as durable regression tests. It is the delivery vehicle for the approved E4 outcome (FR4 / CAP-4).

## Stories

- Story 4.1: Validate schemas, served citations and attribution
- Story 4.2: Block every deterministic risk rule
- Story 4.3: Assert real least privilege and data boundaries
- Story 4.4: Expose a production-disabled real-pipeline dry-run
- Story 4.5: Wire adopted red-team fixtures and verify configuration
- Story 4.6: Execute red-team coverage and freeze findings

## Requirements & Constraints

- Agent outputs must pass strict schema and citation validation before being trusted. Citation kinds are a closed set (log line, commit, metric, history row, Jev signal) and each must resolve against the evidence actually served to that run: log line numbers must exist in the numbered distilled log, commits must fall within `last_green..HEAD`, history rows must be among the rows served, metrics among collected keys, Jev signals among this run's answers. Missing or unresolvable citations are structured validator errors, never silently accepted.
- Suspects (blame candidates) require both a commit citation and at least one log-line citation. Confidence caps must carry cited reasons and may only lower confidence, never raise it. Foreign-repo evidence, short production SHAs and probabilities posing as confidence are rejected.
- Output destined for human review, reporting, or any run whose confidence is below the class cutoff must contain no author attribution (blame-free output). This story owns the cutoff-attribution assertion that an earlier epic referenced.
- The risk gate is deterministic and pure: proposed diffs that skip/disable/xfail tests, add retries, increase timeouts, loosen assertions, or touch workflow files, secrets or infra manifests are blocked, as are dangerous Reviewer objections. Model output cannot override the gate. Safe diffs yield normal; ungated state stays not_gated. Quarantine is metadata only and never appears inside a diff.
- Permission and isolation claims must be evidenced against the real configured GitHub demo environment, not just manifests: actual App permissions, default-branch ruleset requiring human review with the App not a bypass actor, and a synthetic probe proving GitHub itself rejects unauthorized workflow-file writes (receipt stored, probe off the protected branch, no merge attempted, no tokens/keys in stored evidence).
- A test-only dry-run skill exercises the real pipeline through the gating stage with no GitHub writes, returns the real verdict with the terminal-state projection, and is disabled and unusable in production config. It accepts only known fixture repo IDs and supplied evidence; short SHA prefixes expand only at this boundary.
- Red-team coverage must actually execute: the adopted attack configuration must validate against the installed promptfoo version, frozen attack cases (verdict flip, poisoned notes, cross-repo leakage, bug-hiding diffs, log injection, jailbreak) must produce real results with full schema assertions, and findings must be recorded with severity, status, mitigations and denominators. Successful attacks get frozen verbatim as regressions that run on agent-code PRs; mitigated findings require a regression reference. No unexecuted coverage may be claimed and zero findings is not demanded.

## Technical Decisions

- Guardrails are pure and deterministic: they import only `contracts/` plus pinned pure libraries (pydantic, jsonschema) and perform no I/O. They return structured errors/decisions to the shared step runner; the workflow layer owns all state transitions (e.g. the actual pause on validation failure or gate block). Validators and the risk gate never call GitHub or Postgres.
- Contracts are Pydantic v2 models; JSON schemas are generated into `guardrails/schemas/` and committed. `TriageVerdict` always carries class, confidence, confidence_jev, caps, suspects, citations, risk_tier, terminal_state, proposed_diff, quarantine. All SHAs are full 40-char except at the dry-run boundary.
- Validation failure policy: one retry with validator errors fed back, then pause for human review with reason `validation_failed`. These retries are separate from transient-error retries.
- Risk gate blocking pauses the run for human approval with reason `gate_blocked`; only a normal risk tier proceeds to opening a draft PR.
- The dry-run skill is a test-only entry in the skill catalogue, runs the real state machine up to and including gating, treats supplied commit messages and history context as the served evidence for citation resolution, and rejects unknown repo IDs.
- Red-team targets go through the dry-run entrypoint (never the production path); the attack config lives at the repo root with generated schemas and may be split into multiple configs/invocations if the installed promptfoo version requires it. Generated plugin coverage is optional; some targets (candidate cards) are explicitly deferred.
- Findings are exported to `results/redteam/findings.md` and report exports; severity definitions match the red-team inventory and counts include denominators (attack success per case, layer catch rates).

## Cross-Story Dependencies

- 4.1 and 4.2 depend on earlier epics' contracts and validators (story 0.2) and on the analyzer/proposer outputs and projection fixtures from Epic 2 (2.2, 2.4, 2.7).
- 4.3 depends on the demo environment prepared in Epic 0 (0.4) plus Epic 2's gateway, history and isolation work (1.1, 2.5, 2.6, 2.7); it requires real configured GitHub demo access — local mocks alone cannot satisfy the real-permission checks.
- 4.4 depends on the full pipeline (2.12) and routing/registry (3.10) plus the punch-out projection (5.4); 4.5 depends on 4.4; 4.6 depends on 4.5 and 5.4.
- Story 4.1 owns the confidence-cutoff attribution assertion referenced by story 2.4; its validators serve the shared step runner rather than duplicating workflow logic.
