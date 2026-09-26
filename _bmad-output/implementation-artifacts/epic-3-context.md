# Epic 3 Context: Discover and evaluate trustworthy specialist agents

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Build the four A2A specialist agents (Jev classifier, Analyzer, Proposer, Reviewer) as stateless services, plus the discovery and routing layer that connects them to the orchestrator. Each agent is served first, then independently evaluated with promptfoo before anything is wired into the live workflow, so classification quality, evidence grounding, proposal safety and adversarial review are all proven in isolation. Discovery is locked to a digest-pinned allowlist of Agent Cards with two-stage routing (exact skill match, then Jev description selection), and a below-cutoff route pauses the run for a human instead of sending evidence to an unapproved agent. The first real Jev eval (3.2) failed badly, and most of that failure was in the pipeline feeding Jev, not in Jev, so the epic now also hardens that eval: it guards the exam against cases whose evidence never reached Jev, aligns Jev's class definitions with the human labelling convention, and gives Jev structured flake history in the same call. This epic delivers the agent half of the specialist-discovery capability; orchestrator-side integration and guardrail enforcement live in other epics.

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
- Story 3.11: Guard the Jev eval against unanswerable cases
- Story 3.12: Teach Jev the CI-platform failure convention
- Story 3.13: Give Jev structured flake evidence

## Requirements & Constraints

- Every agent is a stateless A2A service: blocking, non-streaming `send_message` over JSON-RPC; no GitHub token, no database access, no meaningful task state. Repo context travels in the request.
- Each agent exposes an Agent Card at `/.well-known/agent-card.json` declaring exactly one catalogue skill; results conform to shared contract models, errors use `AgentError`/A2A `FAILED`, and reported token usage is returned for central accounting.
- No agent may be connected to the workflow before its promptfoo evaluation receipt exists. A numeric pass claim requires the user-supplied pass bar (OQ-1, now supplied); absent it, status is recorded as measured/pending, never "passed". Five E2E examples alone are not calibration.
- Agents never see raw CI logs — only the distilled, numbered log inside the deterministic evidence pack. Untrusted content (logs, commit messages, history rows, Agent Card descriptions) is passed in delimited data sections, never concatenated into instructions.
- Every claim an agent makes must carry a citation resolvable against the evidence served that run; unresolvable or missing citations are schema failures. Suspect blame requires a commit citation plus a log-line citation.
- Confidence has one immutable source (the Jev classification answer); agent-added caps may only lower it, never raise it, and routing confidence is recorded separately from classification confidence.
- Model IDs, timeouts and all cutoffs come from config/thresholds files, never code; prompts exist in exactly one copy shared by the service and its eval suite. Do not rely on `temperature`.
- The Proposer is the sole author of any diff; the Reviewer returns only structured objections and never edits or authors a diff. Quarantine recommendations stay out of the diff. Deflake proposals must be root-cause changes — skips, retries, timeout increases and assertion loosening must remain detectable as unsafe.
- Positive injection-screen results add a cited confidence cap; they never block a run on their own.
- The Jev eval must be unable to score on evidence that never reached Jev: case generation fails (naming each case) when a labelled case's proof line does not survive distillation or when two differently-labelled cases distil to identical input, and no two `unknown` cases may share normalised content. Every receipt records an evidence-retention count (proof-reached cases / all labelled cases), and no label, case or bar is changed to improve a score.
- Jev's class definitions must state the human convention that failures of the CI platform itself (action downloads, artifacts, cache, the provider's API) are `infra`, while third parties the build depends on are `external`. This is an eval-first change: the red eval precedes the prompt edit.
- Flake evidence must never leak the answer: only runs created before the failing run are used, it is structured-only (no free text), repo-scoped, collected by the orchestrator via the GitHub App, and Jev still holds no token.

## Technical Decisions

- **Jev call shape (AD-11, amended 2026-09-27):** one `system_one` call carries both the five-class `Choice` (`code | flaky | infra | external | unknown`) and the `Noul` injection pre-screen. The call may now also carry the evidence pack's structured flake evidence in its own delimited section alongside the distilled log. Class descriptions and the screen instruction live once in `prompts/jev-classes.yaml`.
- **Flake evidence:** the evidence pack gains structured, repo-scoped flake evidence — prior `history` rows for the failing fingerprint with `terminal_state`/`human_verdict`, and the failing job's recent same-branch outcomes (runs, failures, failures whose rerun on the same tested commit passed) over a config-defined window. Window size lives in `guardrails/thresholds.yaml`; the orchestrator collects it (GitHub App), Jev only reads it.
- **Distiller (AD-20, clarified 2026-09-27):** error-marker matching runs against the line with its CI-runner timestamp prefix removed, and the emitted line drops that prefix. Stack coverage spans common stacks (Go, TAP/Node, Rust, Dart/Flutter, npm, apt, Playwright, Elixir/Mix, Ruby, PHP, Java/Gradle), each as one open/closed registry entry, all linear-time.
- **Contracts:** all inter-agent payloads are Pydantic v2 models in `contracts/`; JSON Schema is generated into `guardrails/schemas/` and committed — CI fails if regeneration differs. `HistoryRow` gains structured `terminal_state`/`human_verdict`; `EvidencePack` gains a structured job-outcome summary. All SHAs are full 40-character.
- **Discovery:** a committed per-environment allowlist of `{card_url, sha256}` pins each card (digest over canonical JSON, URL fields excluded). Cards are fetched at startup and refused on digest mismatch, unknown skill ids, or duplicate skill ids. Stage 1 routing is exact skill id/tag match; stage 2 is a Jev `Choice` over allowlisted skill descriptions only. Below the no-route cutoff the run pauses with escalation reason `no_route`.
- **Skill catalogue (closed):** `classify-failure`, `analyze-failure`, `propose-fix`, `review-fix`, plus `triage-dry-run` (test only, disabled in prod). No arbitrary skill-count thresholds or extra routing endpoints.
- **Proposer:** one prompt (`prompts/proposer.md`), three distinguishable variants (fix, root-cause deflake, mock/contract), each producing a structured proposed diff with base SHA and add/modify/delete file ops; quarantine metadata (test ID, reason, citations) is a separate field.
- **Reviewer:** distinct adversarial prompt; objections carry severity (`info | minor | major | dangerous`), category, claim and citation. `dangerous` escalates early to the risk gate; `major` drives at most two revision rounds.
- **Analyzer:** selects suspects only from the candidate suspects in the served evidence pack, ranked with commit and log-line citations; runs on Haiku with a config-only fallback to Sonnet if the eval bar fails. Verify the Haiku model's build-time availability/lifecycle and record the source and date.
- **Eval receipts:** Jev eval results are saved under `results/jev-eval/` with model/version, sample counts, per-class expected/actual, the verdict against the unchanged bar, and a before/after table against the prior receipt; the OQ-1 bar lives in `guardrails/thresholds.yaml`. The 3.2 receipt is kept unchanged as the historical baseline.
- **Routing receipts:** route choice, card/skill identity, routing confidence and usage are recorded as step rows; the classification confidence field is never overwritten by routing.

## Cross-Story Dependencies

- Within the epic, service stories precede their eval stories: 3.1 → 3.2 → (3.11 → 3.12 → 3.13) → 3.3 → 3.4 → 3.5 → 3.6 → 3.7 → 3.8. Routing (3.9) requires all four agent evals; the routing integration proof (3.10) requires 3.9 and the shared step runner (2.8). 3.11 needs 3.2 plus the real-log distiller hardening (2.13); 3.12 needs 3.11; 3.13 needs 3.12 plus the structured history and evidence-pack stories (2.6, 2.7).
- Build order note: 2.13, 3.11, 3.12 and 3.13 run immediately after 3.2 (before 3.3), so 3.3 onward is now built after the Jev eval is trustworthy.
- Cross-epic: agents depend on the shared payload contracts and generated schemas (Epic 0), on the immutable Jev confidence computation, the deterministic evidence pack, structured history and the shared step runner (Epic 2), on schema/citation validation and the deterministic risk gate (Epic 4), and on the central usage/cost recording (Epic 6) for the accounting their evals must demonstrate.
- Open questions carried by this epic: OQ-1 is supplied (2026-09-27) and gates pass declarations; the final no-route cutoff stays unresolved until calibration, so routing tests use explicit test cutoffs for deterministic branch assertions; OQ-5 (calibration population, small flaky sample) stays open; OQ-3 (Jev price) and OQ-4 (build-time Haiku availability) remain open.
