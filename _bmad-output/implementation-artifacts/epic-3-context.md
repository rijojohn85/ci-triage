# Epic 3 Context: Discover and evaluate trustworthy specialist agents

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Build the four A2A specialist agents (Jev classifier, Analyzer, Proposer, Reviewer) as stateless services, plus the discovery and routing layer that connects them to the orchestrator. Each agent is served first, then independently evaluated with promptfoo before anything is wired into the live workflow, so classification quality, evidence grounding, proposal safety and adversarial review are all proven in isolation. Discovery is locked to a digest-pinned allowlist of Agent Cards with two-stage routing (exact skill match, then Jev description selection), and a below-cutoff route pauses the run for a human instead of sending evidence to an unapproved agent. This epic delivers the agent half of the specialist-discovery capability; the orchestrator-side workflow integration and guardrail enforcement live in other epics.

## Stories

- Story 3.1: Serve the Jev classifier and batched injection screen
- Story 3.2: Evaluate Jev classification before connection
- Story 3.3: Serve the evidence-grounded Analyzer
- Story 3.4: Evaluate Analyzer evidence and attribution
- Story 3.5: Serve the sole-author fix, deflake and mock Proposer
- Story 3.6: Evaluate all three Proposer variants
- Story 3.7: Serve an objections-only adversarial Reviewer
- Story 3.8: Evaluate Reviewer objections before connection
- Story 3.9: Pin agent discovery and implement two-stage routing
- Story 3.10: Prove description selection and no-route pause

## Requirements & Constraints

- Every agent is a stateless A2A service: blocking, non-streaming `send_message` over JSON-RPC; no GitHub token, no database access, no meaningful task state. Repo context travels in the request.
- Each agent exposes an Agent Card at `/.well-known/agent-card.json` declaring exactly one catalogue skill; results conform to shared contract models, errors use `AgentError`/A2A `FAILED`, and reported token usage is returned for central accounting.
- No agent may be connected to the workflow before its promptfoo evaluation receipt exists. A numeric pass claim requires the user-supplied pass bar; without it, status is recorded as measured/pending, never "passed". Five E2E examples alone are not calibration.
- Agents never see raw CI logs — only the distilled, numbered log inside the deterministic evidence pack. Untrusted content (logs, commit messages, history rows, Agent Card descriptions) is passed in delimited data sections, never concatenated into instructions.
- Every claim an agent makes must carry a citation resolvable against the evidence served that run; unresolvable or missing citations are schema failures. Suspect blame requires a commit citation plus a log-line citation.
- Confidence has one immutable source (the Jev classification answer); agent-added caps may only lower it, never raise it, and routing confidence is recorded separately from classification confidence.
- Model IDs, timeouts and all cutoffs come from config/thresholds files, never code; prompts exist in exactly one copy shared by the service and its eval suite. Do not rely on `temperature`.
- The Proposer is the sole author of any diff; the Reviewer returns only structured objections and never edits or authors a diff. Quarantine recommendations stay out of the diff. Deflake proposals must be root-cause changes — skips, retries, timeout increases and assertion loosening must remain detectable as unsafe.
- Positive injection-screen results add a cited confidence cap; they never block a run on their own.

## Technical Decisions

- **Jev call shape:** one `system_one` call on the distilled log carries both the five-class `Choice` (`code | flaky | infra | external | unknown`) and the `Noul` injection pre-screen. Class descriptions and the screen instruction live once in `prompts/jev-classes.yaml`.
- **Contracts:** all inter-agent payloads are Pydantic v2 models in `contracts/`; JSON Schema is generated into `guardrails/schemas/` and committed — CI fails if regeneration differs. All SHAs are full 40-character.
- **Discovery:** a committed per-environment allowlist of `{card_url, sha256}` pins each card (digest over canonical JSON, URL fields excluded). Cards are fetched at startup and refused on digest mismatch, unknown skill ids, or duplicate skill ids. Stage 1 routing is exact skill id/tag match; stage 2 is a Jev `Choice` over allowlisted skill descriptions only. Below the no-route cutoff the run pauses with escalation reason `no_route`.
- **Skill catalogue (closed):** `classify-failure`, `analyze-failure`, `propose-fix`, `review-fix`, plus `triage-dry-run` (test only, disabled in prod). No arbitrary skill-count thresholds or extra routing endpoints.
- **Proposer:** one prompt (`prompts/proposer.md`), three distinguishable variants (fix, root-cause deflake, mock/contract), each producing a structured proposed diff with base SHA and add/modify/delete file ops; quarantine metadata (test ID, reason, citations) is a separate field.
- **Reviewer:** distinct adversarial prompt; objections carry severity (`info | minor | major | dangerous`), category, claim and citation. `dangerous` escalates early to the risk gate; `major` drives at most two revision rounds.
- **Analyzer:** selects suspects only from the candidate suspects in the served evidence pack, ranked with commit and log-line citations; runs on Haiku with a config-only fallback to Sonnet if the eval bar fails.
- **Models:** Analyzer Haiku; Proposer and Reviewer Sonnet — pinned IDs from config. Verify the Haiku model's build-time availability/lifecycle and record the source and date; do not assume prior retirement claims.
- **Routing receipts:** route choice, card/skill identity, routing confidence and usage are recorded as step rows; the classification confidence field is never overwritten by routing.

## Cross-Story Dependencies

- Within the epic, service stories precede their eval stories in a chain: 3.1 → 3.2 → 3.3 → 3.4 → 3.5 → 3.6 → 3.7 → 3.8. Routing (3.9) requires all four agent evals to be done; the routing integration proof (3.10) requires 3.9 and the shared step runner.
- Cross-epic: agents depend on the shared payload contracts and generated schemas (Epic 0), on the immutable Jev confidence computation, the deterministic evidence pack and the shared step runner (Epic 2), on schema/citation validation and the deterministic risk gate (Epic 4), and on the central usage/cost recording (Epic 6) for the accounting their evals must demonstrate.
- Open questions carried by this epic: the per-agent pass bar must be supplied by the user before any "passed" status; the final no-route cutoff stays unresolved until calibration, so routing tests use explicit test cutoffs for deterministic branch assertions.
