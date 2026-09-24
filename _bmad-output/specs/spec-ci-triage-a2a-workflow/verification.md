# Verification and rubric evidence

## Required layout and receipts

| Path | Required content / trace |
| --- | --- |
| prompts/ | Single runtime/eval copies of analyzer.md, proposer.md, reviewer.md, jev-classes.yaml; model tier and typed output contract; AD-11, AD-19 |
| workflow/ | Explicit transition table, generated state diagram, class/action branch table, A2A handoffs, registry, read-only TaskStore adapter, evidence pack, history lookup traces; AD-1–AD-5, AD-10, AD-15, AD-24 |
| guardrails/ | Generated committed schemas with drift check, validator, citation checker, risk rules, thresholds.yaml; invalid-citation and blocked-diff evidence; AD-6–AD-9, AD-13, AD-19, AD-20 |
| agents/, contracts/, gateway/ | Four A2A services/cards, shared Pydantic models, authenticated intake; AD-5, AD-6, AD-10, AD-17 |
| punch-out/ | CLI, evidence pack, approval/resume/reject receipts and refused-bypass audit; AD-14 |
| monitoring/ | Versioned prices.yaml with source URLs/dates and per-token-type rates; exporters; AD-18 |
| runs/ | Exported per-step model, usage, cost, status, outcome, citations and human decisions; per-run totals; AD-18 |
| results/ | 5/5 expected/actual E2E table, per-agent eval reports, calibration table, cost/token summary, redteam/findings.md and report exports |
| demo-repo (external) | The real synthetic GitHub demo repo is a separate repository. Its URL, the GitHub App installation, the seeded commit SHAs per scenario, CI run IDs and a tagged snapshot are recorded in `test-data/demo-repo.md`; the seed commits themselves live under `test-data/` so the repo can be recreated |
| test-data/ | S1–S5 drivers, labelled distilled logs, history seed, synthetic repo seeds/CI run IDs; AD-24–AD-26 |
| tests/security/ | Deterministic gateway, registry, distiller, tenant/history and risk-gate tests; approval bypass tests |
| deploy/ | Compose, plain k8s, per-env digest registry, forward-only migrations, secret placement and NetworkPolicy; GitHub permission/ruleset evidence; AD-16, AD-25 |
| Root *.test.yaml | jev.test.yaml, analyzer.test.yaml, proposer.test.yaml, reviewer.test.yaml; evaluate each agent before integration; all three Proposer variants covered |
| Root promptfooconfig.redteam.yaml | Implement and validate the adopted seed configuration described below |
| README.md | Purpose/users, workflow diagram and branches, rubric map, setup/demo/evaluation instructions, architecture A rationale, no-RAG rationale, model/Jev limitations, least privilege and links to evidence |

Diagrams stay in companions: the adopted spine contains the structural/state diagrams and references its existing [workflow-diagram.svg](../../planning-artifacts/architecture/architecture-stage4-2026-09-25/workflow-diagram.svg). The README draft was read for source coverage; its prose is not a separate binding contract.

## Quality and audit

Use shared generated schemas in promptfoo assertions. Jev classification eval uses labelled distilled logs; calibration compares effective AD-9 confidence with correctness, retains the original Jev result/caps for traceability, and identifies sample counts and the unresolved population choice (OQ-5). Do not describe five E2E points alone as validated calibration. Analyzer may switch from Haiku to Sonnet via config if it fails the supplied bar.

Record every model call, including Jev routing and every retry. Preserve input/output/cache-read and 5m/1h cache-write usage separately; unavailable counters and unsourced prices are NULL, never zero. Compute costs centrally and flag incomplete totals. runs/ and results/ metrics are database exports, not hand-authored numbers; red-team findings prose records observations. Verify Claude prices from official sources at build and retain retrieval dates; Jev pricing remains OQ-3.

## Red-team contract

The adopted redteam-plan.md preserves the RT-01–RT-08 catalogue, attack examples, defence layers, severity rules, findings template and regression-freeze requirements. Apply scope.md priorities and the final spine when older language in that plan differs (Postgres only, per-step token, classify-failure skill, structured history, canonical citations and registry catalogue/digest checks). A historical “>N skills” heuristic has no settled N and does not replace AD-10. Historical recall/price estimates are not acceptance thresholds.

The companion plan’s seed [promptfooconfig.redteam.yaml](../../brainstorming/brainstorm-ci-triage-a2a-workflow-2026-09-25/promptfooconfig.redteam.yaml) is implementation input, not a verified runnable deliverable. Preserve its attack fixtures and safe-behavior intent while wiring generated schemas and the real AD-26 test-only triage-dry-run boundary. It runs through GATING without GitHub writes, rejects repo IDs outside the fixture map, treats supplied evidence as served evidence, permits unique short SHA expansion only at that boundary, and is disabled in production.

Before the first run, resolve the seed’s TODOs: multiple target input maps, repeated plugins with distinct injection variables, whether handwritten tests require separate promptfoo eval invocation, and the deferred candidate_cards target. These are implementation verification tasks, not new architecture decisions. Regenerate attacks for executed red-team batches and freeze successful attacks as regression cases; weekly scheduling is COULD. Jev verdict-flip coverage must reach the Jev classifier, with a separate target/config if needed.

CAP-3 stage-2 discovery proof (MUST, separate from the deferred RT-05 promptfoo routing target): an integration test outside the 5/5 denominator forces a task with no exact skill/tag match so Jev description routing selects an allowlisted skill, and a second case falls below the no-route cutoff and pauses at `AWAITING_APPROVAL(no_route)`.

Required deterministic coverage includes RT-01 distillation, RT-03 structured history/import restrictions, RT-04 tenant isolation, RT-05 allowlist/digest/catalogue/duplicate skills, RT-06 signature/replay/installation/rate limits, and RT-07 every risk rule. Generated RT-04 probes remain SHOULD and RT-05 routing promptfoo remains deferred; document skipped coverage explicitly.

Findings capture probe, expected/observed outcome, run/model version, layers bypassed/catching layer, severity/status, mitigation and regression reference before mitigated status. Include severity/status counts, per-case attack success and per-layer catch rates with denominators. Zero findings is not required. OWASP publication is COULD and requires checking official item names before publication; do not turn source coverage claims into claims of completed tests.
