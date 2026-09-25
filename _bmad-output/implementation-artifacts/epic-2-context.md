# Epic 2 Context: Turn failures into durable, evidence-backed triage

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Build the orchestrator workflow that turns a failed CI run into a durable, evidence-backed triage outcome. Every state move, step output, retry, approval, and GitHub side effect is persisted and inspectable, so an interrupted run resumes without duplicate work or double LLM spend, and operators can trust state, effects, and attempt accounting. This epic delivers the core capability: explicit state machine, capped Jev confidence, deterministic evidence, shared step execution with bounded retries, evaluated specialist integration with human pauses, adversarial review + deterministic risk gating, idempotent publication, and live recovery proof.

## Stories

- Story 2.1: Enforce the explicit state transition invariants
- Story 2.2: Compute immutable Jev confidence and cited caps
- Story 2.3: Persist completed steps atomically and resume
- Story 2.4: Serve a read-only A2A task projection
- Story 2.5: Distill CI logs deterministically
- Story 2.6: Maintain structured tenant-scoped history
- Story 2.7: Build and persist the deterministic evidence pack
- Story 2.8: Shared step runner: validation retry + transient retry
- Story 2.9: Integrate evaluated classification and analysis with pauses
- Story 2.10: Integrate proposal review, revisions and risk gating
- Story 2.11: Deliver idempotent drafts, quarantine metadata and reports
- Story 2.12: Prove live-pipeline recovery and retry accounting

## Requirements & Constraints

- Only declared state transitions may execute; an undeclared move raises, and the state diagram is generated from the single transition table, not maintained separately. Escalations pause at a waiting state carrying one of: low_confidence, unknown_class, no_route, validation_failed, review_rejected, gate_blocked, plus an optional proposal reference.
- One effective confidence number drives routing and gating: the immutable Jev classification confidence capped downward by cited caps; nothing may raise it. A human class override changes neither confidence field — it skips only the low-confidence/unknown-class checks for the rest of the run. Final cutoffs are an open question (OQ-2): tests use explicit fixture thresholds, never accepted calibration.
- A completed step's output and its state change commit atomically in one lease-guarded transaction; a reclaimed run re-enters its current state and never re-executes a completed step; stale-owner results are discarded.
- The A2A task view is a read-only projection of authoritative run state — task identity equals the run ID; there is no independent task-state writer. Paused runs expose a blame-free evidence pack without scheduling a worker; no author attribution appears while paused or reporting.
- CI logs are distilled deterministically before any model sees them: keep error blocks and stack traces, drop narrative, strip ANSI/control characters, number lines, bound size by config. Distilled output is the only log form ever exposed to request builders.
- History is structured-only (no free text), fingerprinted from normalized test identity and stack frames, tenant-scoped on every query, written once per terminal run by the orchestrator only; seed data enters via import and human PR feedback goes to separate storage.
- The evidence pack is built deterministically: numbered distilled log, last-green baseline (same workflow/branch, else default-branch head), full SHAs of the commit range, deterministically ranked candidate suspects (file-intersection only), history rows, and runner metrics. Analyzer may pick suspects only from this set; every citation must resolve against it.
- Two separate retry budgets in one shared step runner: validation failures get one feedback-fed retry then escalate as validation_failed (never emit an uncited verdict); transient failures (network, 429, 5xx, timeout, retryable agent errors) get at most three backoff attempts then the run fails terminally with history written once. Every attempt is its own audited step with usage (NULL counters stay NULL, never 0).
- Adversarial review precedes any PR: only the Proposer authors diffs; revisions are bounded at two rounds before escalating as review_rejected; dangerous objections escalate straight to a deterministic risk gate that blocks test-skipping/timeout/loosening/workflow-file diffs and that LLM output cannot override.
- All GitHub effects are idempotent (keyed by run + step, check-before-create, resume-safe), draft-only, never merging, with least-privilege tokens held only by the orchestrator. Blame-free runs (paused, reporting, or below cutoff) carry no author attribution; reviewer requests are deterministic.
- Recovery must be proven end-to-end: crashes before/after commit or external-write acknowledgment produce no duplicate effects; a re-driven workflow attempt enters as a new run through normal intake with no manual re-insert, and the old run stays failed with history written once.

## Technical Decisions

- Hand-rolled explicit state machine in `workflow/`: one transition table is the source of truth, no workflow engine, workers claim runs via short-transaction lease (`SELECT … FOR UPDATE SKIP LOCKED`), leases renew during long steps and are re-checked at commit (fencing discards stale results).
- Run state lives only in the `triage_run` table; the A2A task view is a one-way read-only TaskStore adapter over `triage_run`/`run_step` (task_id = run_id = UUIDv7 = spoke contextId); the SDK's database task store is not deployed.
- Spokes are stateless: blocking, non-streaming JSON-RPC `send_message` bounded by per-skill step_timeout from config; the result persists as `run_step` before the next call; agents hold no GitHub tokens and no DB access; repo context travels in the request.
- All inter-agent payloads are Pydantic v2 models in `contracts/`; JSON schemas are generated into `guardrails/` and CI-fail on drift. Verdicts always carry class, both confidence fields, caps, suspects, citations, risk_tier, terminal_state, nullable diff and quarantine. All SHAs are full 40-char.
- Citations are a closed set (log_line, commit, metric, history_row, jev_signal), each validated against the evidence actually served this run; unresolvable or missing citations are schema failures. Suspect blame requires commit + log_line citations.
- One copy of each prompt in `prompts/`; all cutoffs, thresholds, and distiller bounds live only in `guardrails/thresholds.yaml`; model IDs and timeouts come from config, never code; do not rely on temperature.
- Untrusted data (distilled logs, commit messages, titles, history rows, card text) is passed in delimited data sections, never concatenated into instructions.
- Quarantine is recommendation metadata (test id, reason, citations) applied as a label + PR-body list, never written into a diff; a flaky diff must be a root-cause change that passes the risk gate.
- Workflow-file diffs never reach the write path: the gate blocks them and an approval routes to reporting (diff delivered for human application); a push GitHub still rejects for missing workflows permission is a non-retryable error → failed.
- Audit and cost are computed by the orchestrator: every LLM/Jev call (routing included) recorded as a `run_step` with split token counters, priced from a versioned price file, unpriced models flagged with NULL cost.
- Errors split retryable vs non-retryable; spoke errors return A2A failed with a typed agent error `{code, message, retryable}`. Forward-only SQL migrations; structured JSON logs carrying run_id/task_id/step; secrets only in the gateway/orchestrator (GitHub) and the agents that need them.

## Cross-Story Dependencies

- Foundation: 2.1 needs epic 0 groundwork (0.2, 0.3). 2.2 and 2.5 need 0.2; 2.3 needs 1.2; 2.7 needs 0.4.
- Core chain: 2.1 → 2.2/2.3 → 2.4, 2.5 → 2.6 → 2.7.
- 2.8 (shared step runner) depends on 2.3, 2.6 and on fixture contracts from epics 4 and 6 (4.1, 6.1, 6.2); specialist calls in 2.8 are fixtures only.
- 2.9 integrates the real agents and depends on evaluated agents from epic 3 (3.2, 3.4, 3.6, 3.8, 3.9), evidence/risk work from epics 4 (4.1, 4.3), and 6.1/6.2.
- 2.10 needs 2.9 plus 3.6/3.8 and 4.2. 2.11 needs 2.10 plus 4.3. 2.12 needs 2.11 plus 3.10.
- Open question OQ-1 gates 2.9: no agent connects to the workflow without its independent evaluation receipt; never claim a pass without the user-supplied bar.
