# Engineering Standards — Blameless CI Triage

Binding for every `bmad-build` story. The architecture spine (AD-n) wins on any conflict.
Pragmatic, not dogmatic: a principle that adds an abstraction nobody needs yet is a violation, not compliance.

## SOLID (applied to this codebase)

- **S — Single responsibility.** One module = one reason to change. Transport (A2A server/client, gateway HTTP), domain logic (state machine, risk gate, citation checker, distiller) and persistence (Postgres repos) live apart. Domain code never builds SQL or HTTP requests.
- **O — Open/closed.** Extend by adding, not editing: new failure class, risk rule, proposer variant or agent skill = new entry in a table/registry, not a new `if/elif` branch in existing code. The AD-1 transition table is the model.
- **L — Liskov.** Every agent client, repository and GitHub adapter behind a `Protocol` must be swappable by its test fake without the caller changing. Fakes honour the same contract (same exceptions, same idempotency).
- **I — Interface segregation.** Small `Protocol`s per consumer (`RunLeaseStore`, `StepRecorder`, `CheckRunWriter`), not one god-repository or god-client.
- **D — Dependency inversion.** Domain depends on `contracts/` types and `Protocol`s; concrete Postgres/GitHub/Anthropic/Jev clients are injected at the composition root (entrypoint). Agents hold no GitHub or Postgres client (AD layer contract).

## DRY

- One source of truth per fact: prompts load from `prompts/` (same files promptfoo tests), model IDs and timeouts from runtime YAML, JSON schemas generated from `contracts/` Pydantic models — never hand-copied.
- Rule of three: duplicate once if the two uses may diverge; extract on the third. Don't merge code that is only *coincidentally* alike (e.g. two risk rules with similar regexes but different owners).
- Shared step behaviour (validation retry, transient retry, audit recording) exists once — the shared step runner (story 2.8) — never re-implemented per agent.

## Clean code

- Names say intent in domain words from the spine (`triage_run`, `confidence_jev`, `run_step`, `class_override`). No `data`, `info`, `manager`, `util` modules.
- Functions do one thing; guard clauses over nesting; max cyclomatic complexity 10, max 5 parameters (use a dataclass/Pydantic model beyond that).
- No magic values: thresholds from `guardrails/thresholds.yaml`, states from the state enum.
- Types everywhere; `mypy --strict` clean. No `Any` in `contracts/` or `guardrails/`.
- Errors: typed exceptions split into retryable vs non-retryable (AD-22); never swallow — log with `run_id` and re-raise or transition to `FAILED`.
- Comments explain *why* (cite the AD), never *what*. No commented-out code, no TODO without an OQ-n or story id.
- Pure functions for decisions (risk gate, citation check, confidence min, state transitions) so they test without I/O.

## Harness (mechanical enforcement — story 0.1 installs it)

| Check | Tool | Gate |
| --- | --- | --- |
| Lint + style + complexity | `ruff check` (E,F,W,I,B,UP,SIM,N,C90,PL,ARG,RUF,ERA; mccabe max 10; max-args 5) + `ruff format --check` | 0 findings |
| Types | `mypy --strict` | 0 errors |
| Layer contract (SOLID-D / AD layers) | `import-linter` contracts: `contracts` imports no app package; `guardrails` imports only `contracts`; `agents` import no GitHub/Postgres client libs | all kept |
| Duplication (DRY) | `pylint --disable=all --enable=duplicate-code` (min-similarity-lines 8) | 0 findings |
| Tests + coverage | `pytest --cov` on `contracts`, `guardrails`, `workflow` | fail-under 85% |
| One command | `make check` (or `uv run task check`) runs all of the above; `pre-commit` runs the fast subset | green before a story is `done` |

Exceptions need an inline `# noqa: <code> — <reason / AD-n>` and are listed in the story's report.
