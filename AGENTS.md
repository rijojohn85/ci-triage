# AGENTS.md — Blameless CI Triage

Instructions for any coding agent (Claude Code, Codex, Cursor, Copilot, Gemini CLI, OpenCode, …) and for humans.
Tool-specific files (`CLAUDE.md`, BMad overrides in `_bmad/custom/`) only point here — this file is the single source.

## Sources of truth (read-only for builders)

- Architecture spine: `_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md` — AD-1…AD-27 are hard constraints; pinned versions win over what you remember.
- Spec: `_bmad-output/specs/spec-ci-triage-a2a-workflow/`
- Stories: `_bmad-output/planning-artifacts/epics.md` (execution order = its "Global build order"); status: `_bmad-output/implementation-artifacts/sprint-status.yaml`.
- Never edit the spine, spec or epics while building. If a story conflicts with them, stop and report.

On any conflict: spine AD > this file > everything else.

## How work is done

1. **Brief before code.** Before changing anything, state what will be built: story + ACs, binding ADs, files to create/change and what is deliberately not touched, approach (naming the SOLID/DRY decisions), tests per AC, risks/open questions. Wait for the human's go.
2. **TDD** (below) for every behaviour change.
3. **Quality gates** (below) green before a story is called done. Report AC by AC with the command that proved it.
4. One branch per story (`story/<sprint-status key>`), off an up-to-date `main`; merged only after human review.
5. Library/API usage: check current docs (context7 first, web second) and say which source answered.
6. Models: Claude Sonnet / Haiku and TypeSafe Jev only. No secrets in the repo; `.env.example` holds names only.

## TDD

- **Red → green → refactor.** Write the test for the next slice of an AC first, run it, and see it fail for the right reason before writing production code. Then the minimum code to pass. Then refactor with tests green.
- Every AC maps to at least one named test; the test name cites it (`test_ac2_guardrails_imports_only_contracts`).
- Test behaviour through public interfaces, not private helpers. Deterministic parts (state machine, risk gate, citation checker, distiller, confidence `min`) are pure functions with fast unit tests and no I/O.
- I/O boundaries (Postgres, GitHub, A2A peers, Anthropic, Jev) are tested against `Protocol` fakes in unit tests and against the real thing in marked integration tests (`@pytest.mark.integration`).
- **Prompts are code too — eval-first.** Before creating or changing a prompt in `prompts/`, add or change the promptfoo case in the agent's `*.test.yaml` that captures the intended behaviour, see it fail (or be absent), then edit the prompt.
- Bug fix = a failing test that reproduces the bug first.
- Never weaken, skip or delete a test to get green; if a test is wrong, say so and fix it deliberately.

## SOLID (applied here)

- **S — Single responsibility.** One module, one reason to change. Transport (A2A server/client, gateway HTTP), domain logic (state machine, risk gate, citation checker, distiller) and persistence (Postgres repos) live apart. Domain code never builds SQL or HTTP requests.
- **O — Open/closed.** Extend by adding: a new failure class, risk rule, proposer variant or agent skill is a new table/registry entry, not a new `if/elif` branch. The AD-1 transition table is the model.
- **L — Liskov.** Every agent client, repository and GitHub adapter behind a `Protocol` is swappable by its test fake without the caller changing; fakes honour the same contract (exceptions, idempotency).
- **I — Interface segregation.** Small `Protocol`s per consumer (`RunLeaseStore`, `StepRecorder`, `CheckRunWriter`), not one god-repository or god-client.
- **D — Dependency inversion.** Domain depends on `contracts/` types and `Protocol`s; concrete Postgres/GitHub/Anthropic/Jev clients are injected at the entrypoint. Agents hold no GitHub or Postgres client.

## DRY

- One source per fact: prompts load from `prompts/` (the same files promptfoo tests); model IDs and timeouts from runtime YAML; JSON schemas generated from `contracts/` Pydantic models; thresholds from `guardrails/thresholds.yaml`.
- Rule of three: tolerate one duplicate when the two uses may diverge; extract on the third. Don't merge code that is only coincidentally alike.
- Shared step behaviour (validation retry, transient retry, audit recording) lives once, in the shared step runner (story 2.8).

## Clean code

- Names use the spine's domain words (`triage_run`, `confidence_jev`, `run_step`, `class_override`). No `utils`, `helpers`, `manager`, `data` modules.
- Functions do one thing; guard clauses over nesting; cyclomatic complexity ≤ 10; ≤ 5 parameters (use a model/dataclass beyond that).
- No magic values: thresholds from config, states from the state enum.
- Full type hints; no `Any` in `contracts/` or `guardrails/`.
- Errors are typed and split retryable vs non-retryable (AD-22); never swallowed — log with `run_id`, then re-raise or transition to `FAILED`.
- Comments explain *why* (cite the AD), not *what*. No commented-out code; no TODO without an OQ-n or story id.
- Don't over-engineer: no abstraction with one implementation unless a test fake needs it.

## Quality gates

Mechanical checks that enforce the rules above. Status: the layer-contract check and bootstrap exist (story 0.1); the rest are being added in the 0.1 follow-up — until `make check` exists, run what is present and say what is missing.

| Check | Tool | Gate |
| --- | --- | --- |
| Bootstrap / pinned toolchain | `scripts/bootstrap.sh` | exits 0 |
| Layer contract (SOLID-D) | `scripts/check_layer_contract.py` | passes |
| Lint, style, complexity | `ruff check` (E,F,W,I,B,UP,SIM,N,C90,PL,ARG,RUF,ERA; mccabe 10; max-args 5) + `ruff format --check` | 0 findings |
| Types | `mypy --strict` | 0 errors |
| Duplication (DRY) | `pylint --disable=all --enable=duplicate-code` (min-similarity-lines 8) | 0 findings |
| Tests + coverage (TDD) | `pytest --cov` on `contracts`, `guardrails`, `workflow` | ≥ 85% |
| Agent evals | `npx promptfoo eval -c <agent>.test.yaml` for any agent whose prompt changed | pass bar (OQ-1) |
| All of the above | `make check` | green before done |

Exceptions need an inline `# noqa: <code> — <reason / AD-n>` and are listed in the story report.
