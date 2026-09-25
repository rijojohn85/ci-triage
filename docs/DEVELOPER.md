# Developer guide — Blameless CI Triage

How the system is built, where things live, and how to run, test and extend it. This file describes what exists on `main` today; each story updates it in the same PR (AGENTS.md "How work is done", step 7).

- Decisions and their reasons: [architecture spine](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md) (AD-1 … AD-27). This guide links ADs; it does not restate them.
- Rules for writing code here: [AGENTS.md](../AGENTS.md).
- Story plan and order: [epics.md](../_bmad-output/planning-artifacts/epics.md) ("Global build order"); status in [sprint-status.yaml](../_bmad-output/implementation-artifacts/sprint-status.yaml).

## Architecture in one page

Hub and spoke (spine "Design Paradigm", AD-4, AD-5):

- A **gateway** accepts GitHub `workflow_run` failures and queues them in Postgres.
- One **orchestrator** owns each run's state (`triage_run`) and drives an explicit state machine. It is the only component that talks to agents.
- Four stateless **agents** (A2A services) each answer one question: Jev classifies the failure, the Analyzer (Haiku) explains it with citations, the Proposer (Sonnet) writes the fix, the Reviewer (Sonnet) raises objections. Agents never call each other and hold no GitHub or Postgres access.
- **Guardrails** check every agent reply (schema and citations, AD-7, AD-8); a deterministic **risk gate** (AD-13) picks the outcome: draft PR, infra report, or a pause for a human (`INPUT_REQUIRED`, AD-14).

Every message between orchestrator and agent is an A2A message whose data part is a `contracts.a2a.DataPart` (see [Contracts](#contracts-story-02)).

## Built so far

| Story | What exists | Where |
| --- | --- | --- |
| 0.1 | Rubric folder layout, pinned toolchain bootstrap, layer-contract check, quality gates (`make check`) | `scripts/`, `Makefile`, `pyproject.toml` |
| 0.2 | Shared Pydantic payload contracts, generated JSON Schemas, schema drift gate | `contracts/`, `guardrails/schemas/`, `scripts/generate_schemas.py` |
| 0.3 | Compose foundation: postgres:18 + healthcheck, one-shot forward-only migration job (`service_completed_successfully` gating), secret placement | `deploy/`, `workflow/migrate.py`, `tests/workflow/`, `tests/security/` |
| 0.4 | Protected external demo repo: seeded Python package with green CI, AD-16 GitHub App + installation, default-branch ruleset (App not a bypass actor), read-back gate | `test-data/demo-repo-seed/`, `test-data/demo-repo.md`, `scripts/verify_demo_repo.py`, `scripts/ruleset-seed.json` |
| 2.1 | The AD-1 run-state machine: `RunState` enum, one declarative transition table, pure guards, non-retryable `IllegalTransition`, pure AD-4 projection, generated state diagram + drift gate, `0001_triage_run` migration, thresholds loader | `workflow/run_states.py`, `workflow/transitions.py`, `workflow/projection.py`, `workflow/thresholds.py`, `workflow/diagram.py`, `scripts/generate_state_diagram.py`, `workflow/STATE_DIAGRAM.md`, `guardrails/thresholds.yaml`, `deploy/migrations/0001_triage_run.sql`, `tests/workflow/` |
| 2.2 | The one confidence number (AD-9): Jev's `Choice`/`Noul` contracts, the frozen `ClassConfidence` min rule, the injection pre-screen cap, classification-branch cut-off predicates, the AD-27 blame-free attribution predicate, new cut-offs in `guardrails/thresholds.yaml` | `contracts/jev.py`, `contracts/verdict.py` (`effective_confidence`), `guardrails/confidence.py`, `workflow/attribution.py`, `workflow/thresholds.py`, `guardrails/thresholds.yaml`, `guardrails/schemas/JevClassification.json`, `tests/contracts/test_jev.py`, `tests/guardrails/`, `tests/workflow/test_attribution.py`, `tests/workflow/test_thresholds.py` |
| 1.1 | Gateway intake: the webhook signature is checked over the raw bytes before parsing, unknown installations are refused, replayed deliveries and duplicate run identities collapse to one `triage_run(RECEIVED)`, bursts are shed, and run ids are time-ordered UUIDv7 | `gateway/`, `workflow/ids.py`, `config/gateway.yaml`, `deploy/migrations/0002_webhook_delivery.sql`, `deploy/gateway.Dockerfile`, `tests/security/` |

## Where things live

| Path | Status | Contents |
| --- | --- | --- |
| `contracts/` | built (0.2) | Pydantic v2 models for every inter-agent payload; see [contracts/README.md](../contracts/README.md) |
| `guardrails/schemas/` | built (0.2) | JSON Schemas generated from `contracts/`; never edit by hand |
| `guardrails/thresholds.yaml` | built (2.1, 2.2) | the one thresholds file (AD-19): `review.max_rounds`, `workflow_path_glob`, and the `confidence` cut-offs (`class_cutoff`, `no_route_cutoff`, `injection_screen_cutoff`, `injection_screen_cap`); consumed via `workflow.thresholds.load_thresholds` |
| `guardrails/confidence.py` | built (2.2) | the AD-9 min rule as code: `ClassConfidence`, `RouteConfidence`, `apply_injection_screen`, `below_class_cutoff`, `class_escalation` |
| `deploy/compose.yaml` | built (0.3, 1.1) | postgres:18 + one-shot `migrate` job + the real gateway (story 1.1) + orchestrator/agent placeholders, with AD-16 secret placement; see [deploy/README.md](../deploy/README.md) and [Compose and migrations](#compose-and-migrations-story-03) |
| `deploy/migrations/` | built (0.3, 2.1, 1.1) | forward-only `.sql` files + naming rules; runner is `workflow/migrate.py`; `0001_triage_run.sql` owns run state, `0002_webhook_delivery.sql` records seen delivery ids for replay dedupe |
| `scripts/` | built (0.1, 0.2, 0.4, 1.1, 2.1) | `bootstrap.sh`, `check_layer_contract.py`, `generate_schemas.py`, `verify_demo_repo.py`, `generate_state_diagram.py`; `ruleset-seed.json` payload for the demo-repo ruleset |
| `tests/scripts/` | built (0.4) | unit tests of the demo-repo read-back comparison logic against recorded API fixtures; live `gh` path is `@pytest.mark.integration` |
| `test-data/` | built (0.4) | demo-repo evidence: `demo-repo-expected.json` (AD-16 set, one source for script + docs), `demo-repo.md` (live facts + scenario slots), `demo-repo-seed/` (pushed verbatim to the demo repo) |
| `tests/contracts/` | built (0.2) | contract tests, named after the ACs they prove |
| `tests/workflow/`, `tests/security/` | built (0.3, 2.1, 1.1) | migration-runner and compose secret-placement tests; state-machine, projection and diagram tests; gateway signature/intake/limits tests; `@pytest.mark.integration` ones need Docker (`pytest -m integration`) |
| `gateway/` | built (1.1) | webhook intake only — signature, accepted events, load limits, one enqueue; see [gateway/README.md](../gateway/README.md) |
| `workflow/ids.py` | built (1.1) | pure `new_run_id()`: the one UUIDv7 run identity (AD-4) |
| `config/gateway.yaml` | built (1.1) | per-installation rate limit and per-repo queue-depth cap (AD-19); consumed via `gateway.settings.load_gateway_limits` |
| `config/runtime.yaml` | placeholder | model IDs and per-skill `step_timeout` (AD-19) |
| `deploy/` | partially built (0.3, 1.1) | Compose, gateway image, k8s manifests, migrations (0.3+); k8s manifests + `registry.<env>.yaml` still placeholders |
| `workflow/` (rest), `agents/`, `guardrails/` (validator, citation_check, risk_gate), `punch-out/`, `monitoring/` | placeholder | filled by Epics 2–6; each folder's README says what belongs there |
| `prompts/`, `*.test.yaml` | placeholder | agent prompts and their promptfoo evals (Epic 3) |

Layer rules (enforced by `scripts/check_layer_contract.py`): `contracts/` imports only stdlib and pydantic; `guardrails/` imports only `contracts/`; agents hold no GitHub or Postgres clients; model IDs and timeouts live in YAML; secrets come from environment variables.

## Running things

```bash
bash scripts/bootstrap.sh          # create .venv, install pinned Python and npm tools, verify pins
make check                         # every quality gate; must be green before a story is done
python scripts/generate_schemas.py # regenerate guardrails/schemas/ after changing a contract
python scripts/generate_state_diagram.py # regenerate workflow/STATE_DIAGRAM.md after a table change
python -m gateway                  # run the intake gateway against a migrated database (POST /webhook on :8080)
```

`make check` runs: bootstrap check, layer contract, schema drift, **state-diagram drift**, ruff (check + format), `mypy --strict`, pylint duplicate-code, `pytest --cov` (≥ 85% on `contracts`, `guardrails`, `workflow`). Integration tests that need Docker are marked `@pytest.mark.integration` and excluded from `make check` by default — run them with `make test-integration` (or `.venv/bin/pytest -m integration`). Individual targets are listed in the [Makefile](../Makefile).

## Demo repository (story 0.4)

The real synthetic demo repo is
[`rijojohn85-dev/triage-demo-py`](https://github.com/rijojohn85-dev/triage-demo-py)
(org-owned so AD-16's org `members:read` permission is meaningful). Its
facts — repository/App/installation IDs, ruleset, CODEOWNERS, baseline
tag, S1–S5 scenario slots — are recorded in
[test-data/demo-repo.md](../test-data/demo-repo.md); the seed material that
recreates it lives in [test-data/demo-repo-seed/](../test-data/demo-repo-seed/).

- **Expected permissions** have one source: [test-data/demo-repo-expected.json](../test-data/demo-repo-expected.json). `scripts/verify_demo_repo.py` (AC4) reads it and diffs the live `gh api` responses; [AD-16](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md) is cited, not restated.
- **Ruleset** is a repository ruleset (not legacy branch protection) built from `scripts/ruleset-seed.json`: 1 approval + code-owner review, force-push/deletion blocked, `bypass_actors: []` so the App can never bypass.
- **Not GitHub-enforced:** writes being restricted to `refs/heads/triage/*` + draft PRs is enforced in code by the E4 GitHub adapter (AD-3, AD-16); the ruleset covers the default branch only.
- **Tests**: `tests/scripts/test_verify_demo_repo.py` unit-tests the comparison logic against recorded fixtures; the live `gh` path is `@pytest.mark.integration` (`python scripts/verify_demo_repo.py --org … --repo …` runs it ad hoc).

Run the read-back:

```bash
.venv/bin/python scripts/verify_demo_repo.py \
  --org rijojohn85-dev --repo triage-demo-py \
  --app-id 5073639 --installation-id 164804973 --ruleset-id 23997553
```

## Compose and migrations (story 0.3)

The local runtime is `deploy/compose.yaml` (run from the repo root):

```bash
docker compose --project-directory . -f deploy/compose.yaml up -d --wait     # postgres + migration job (+ placeholders)
docker compose --project-directory . -f deploy/compose.yaml run --rm migrate # re-apply pending migrations
docker compose --project-directory . -f deploy/compose.yaml down -v          # stop and drop data
```

- **Postgres 18** with a `pg_isready` healthcheck; data in the named `pgdata` volume (postgres:18 keeps its data at `/var/lib/postgresql`; see the image notes).
- **Migrations** are forward-only `.sql` files in `deploy/migrations/`, applied in filename order by `workflow/migrate.py` ([AD-25](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md)). No Alembic/SQLAlchemy, no advisory lock, no new dependencies. Each file commits atomically together with its `schema_migrations` row; a failing file rolls back completely, exits non-zero, and the `service_completed_successfully` dependency keeps all workers from starting on a broken schema. Re-running applies nothing new (idempotent).
- **Secrets** come from `.env` (names in `.env.example`); [deploy/README.md](../deploy/README.md) links the scope rules. The placement contract is tested (AD-16): key scoping gateway/orchestrator, Claude agents-, Jev/orchestrator-only.
- **Worker services:** the gateway is real since story 1.1 (`deploy/gateway.Dockerfile`, `python -m gateway`); the orchestrator and agents are still busybox placeholders. The AD-16 env names are in place and the migration gating is live.
- **Connection strings:** the migrate job builds its DSN from `POSTGRES_*` names inside the compose network; host-side tools use `DATABASE_URL` from `.env`.

## Gateway intake (story 1.1)

When CI fails, GitHub sends the gateway a `workflow_run` webhook. The gateway's
only job is to prove the message is real, collapse repetition, shed floods,
and hand on exactly one piece of work (AD-17).

**The signature comes first.** GitHub signs the exact bytes it sent using a
shared secret. The gateway recomputes that signature over the raw body and
compares it in constant time. If it is missing or wrong there is no parse and
the answer is `401`, so a forged message can never become work. The check
takes a *tuple* of secrets, so webhook-secret rotation (AD-25) works with no
change here — `GITHUB_WEBHOOK_SECRET` may hold two comma-separated secrets and
either is accepted during the overlap.

**Only one event matters.** A message enqueues only when the event is
`workflow_run`, its action is `completed` and its conclusion is `failure`.
Everything else — including `issue_comment` (the `/triage` command, out of
scope for now) — is acknowledged and ignored. A signed message from an
installation id we do not know is refused with no downstream call.

**Then the limits.** A per-installation rate limit (messages per time window)
and a per-repo cap on how many runs may already be waiting stop a burst from
becoming work. Both numbers live only in `config/gateway.yaml` (AD-19), never
in code.

**Then one insert.** A message that passes everything is written as a single
`triage_run` in `RECEIVED` and answered `202`. Repetition collapses two ways:
a replayed `X-GitHub-Delivery` is a `2xx` no-op (seen ids are kept in
`webhook_delivery`), and a new delivery id that still names the same
`(repo, workflow_run, run_attempt)` creates no second run — the unique
constraint does that. Delivery record and run row commit in one transaction,
so a crash leaves neither half behind. The run id is a UUIDv7
(`workflow/ids.py`): a millisecond timestamp first, so ids sort by time and
keep the database index tidy.

**What it deliberately is not:** no state-machine logic, and no LLM or GitHub
call — enqueueing `RECEIVED` is the only write (AD-1, AD-17). The layer check
fails the build if `gateway/` ever imports an LLM or GitHub client. The limits
are in-process, which is correct for the one gateway under Compose v1 (AD-25);
a future multi-replica gateway would move them to a shared store.

**To extend it:** a new accepted event is one new entry in the registry in
`gateway/events.py`, not a new branch; a new limit is a new field in
`config/gateway.yaml` plus `GatewayLimits`. The run identity is generated by
one factory (`workflow/ids.py::new_run_id`) that later stories reuse.

## Contracts (story 0.2)

One model family per module in `contracts/`: `enums`, `citations`, `verdict`, `evidence`, `objections`, `errors`, `approval`, `a2a`. All models forbid unknown fields.

| Model | Filled in by | Purpose |
| --- | --- | --- |
| `EvidencePack` | orchestrator (no AI) | the facts for a run: numbered distilled log, commits since last green, candidate suspects, history rows, metrics (AD-24) |
| `Citation` (5 kinds) | agents | proof pointing into the evidence pack: `log_line`, `commit`, `metric`, `history_row`, `jev_signal` (AD-7) |
| `Cap` | agents | lowers confidence with a cited reason; confidence = `min(confidence_jev, caps…)` (AD-9) |
| `Suspect` | Analyzer | a ranked commit with citations (AD-27) |
| `Objection` | Reviewer | severity `info`/`minor`/`major`/`dangerous` + claim + citation (AD-12) |
| `AgentError` | any agent | `code`, `message`, `retryable` (AD-22) |
| `TriageVerdict` | orchestrator | the assembled result of a run (AD-6) |
| `DataPart` | both sides | envelope in every A2A data part: `task_id` = `context_id` = `run_id` (AD-4) |

**Adding or changing a contract:** write the failing test in `tests/contracts/` first, change the model, run `python scripts/generate_schemas.py`, commit the regenerated schema with the model. `make check` fails if the two drift apart.

## The state machine (story 2.1)

The orchestrator runs every triage as a life of exactly one record, `triage_run`, whose `state` column says where the run is. The whole story in plain words:

- **There are 14 states** and they are written down once, in `workflow/run_states.py` (`RunState`, [AD-1](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md)). A run is received from the webhook, distills the log, classifies the failure, analyzes it, then either **opens a draft PR** (code fix accepted), **reports** it (infra problem, or a human should apply the change), **pauses for a person** (`AWAITING_APPROVAL`), or **fails**.
- **Every move must be in one table.** `workflow/transitions.py` holds a single list of rows — one row per legal move, saying *from which state, to which state, and under what condition*. If code asks for a move that has no row, or the row's condition is not met, `transition()` raises `IllegalTransition`, which is deliberately non-retryable (an invented move is a bug, not a hiccup, AD-22). Nothing else in the codebase is allowed to decide these moves.
- **Conditions are pure guards** over one frozen `GuardInput` (SOLID-I: one small data bag, no god parameters): the failure class, the risk tier, the review round, the human's approve/reject decision, and a booleans-only `confidence_below_cutoff` (AD-9: the state machine never *computes* confidence — story 2.2 does). Guard thresholds come from `guardrails/thresholds.yaml` (AD-19), never from literals in code.
- **Pauses carry a reason.** `AWAITING_APPROVAL` always has an `escalation_reason` from `contracts.enums.EscalationReason` — and the database enforces it: a run in `AWAITING_APPROVAL` without a reason is rejected by `deploy/migrations/0001_triage_run.sql` CHECK constraints, and vice versa.
- **Failure is always an exit.** Any non-terminal state can go to `FAILED`; those edges are derived from the terminal set in code, not listed by hand (AD-22). Terminal states (`DONE_PR`, `DONE_REPORT`, `REJECTED_BY_HUMAN`, `FAILED`) have no moves out.
- **The diagram is the table's shadow.** `workflow/STATE_DIAGRAM.md` is generated from the table by `scripts/generate_state_diagram.py`, and `make state-diagram-drift` fails if anyone edits either out of sync. A test also parses the spine's AD-1 mermaid block and proves the table's edge set equals it.

**Extending the state machine:** add a state (a new `RunState` member) or an edge = add a row in `workflow/transitions.py` (plus a guard predicate when the edge is conditional), name the guard's sample fields in `GUARD_FIELDS`, write the failing tests first (`tests/workflow/test_transitions.py`, names cite the AC), re-run `python scripts/generate_state_diagram.py`, and commit the regenerated `STATE_DIAGRAM.md` in the same PR ([AD-1](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md), [AD-4](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md)). If the spine's AD-1 diagram disagrees with your row, stop — the spine wins ([AGENTS.md "Sources of truth"](../AGENTS.md)).

**Projection (AD-4):** `workflow/projection.py::project()` is a pure mapping-table from `RunState` to the pair (A2A `TaskState` member name, contract `TerminalState | None`) — `RECEIVED → SUBMITTED`, active states → `WORKING`, `AWAITING_APPROVAL → INPUT_REQUIRED`/`input_required`, the terminal states → `COMPLETED`/`FAILED` with their contract terminal state. a2a-sdk 1.1.5's `TaskState` is a protobuf wrapper, so the projection returns the member *name*; the A2A server story (2.4) converts to the integer at the transport edge.

## Confidence: one trusted number (story 2.2)

**What it is for.** When a CI run fails, a fast checker called Jev guesses what kind of failure it is (code, flaky, infra, external or unknown) and says how sure it is, from 0 to 1. Many parts of the system later ask "how sure are we?". They must all get the same answer, so there is exactly one trusted number. Rules: [AD-9](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md), [AD-11](../_bmad-output/planning-artifacts/architecture/architecture-stage4-2026-09-25/ARCHITECTURE-SPINE.md).

**How the number is made.**

- Jev's own score is kept exactly as it arrived and can never be changed (`contracts/jev.py`, `JevChoice`). Jev also sends how likely each other failure type was. We keep that for the record only; nothing ever makes a decision with it.
- Anything that has a reason to trust Jev less can add a **cap**: a lower limit, plus a pointer to the evidence behind it. A cap with no evidence is refused.
- The trusted number is simply **the smallest** of Jev's score and all the caps. It is worked out every time you read it, so nobody can type it in, and adding a cap can only pull it down, never up. This rule is written once, in `contracts/verdict.py` (`effective_confidence`). The final verdict checks itself against the same rule and is refused if its number doesn't match.
- The code for all of this is in `guardrails/confidence.py` (`ClassConfidence`).

**Where caps come from today.** Jev also checks whether the log looks like someone is trying to trick the AI. It answers with a number from 0 to 1. At or above the "trick check" line, we add one cap that points back to that check (`apply_injection_screen`). That is all it does: it never stops a run by itself. If the lower number then falls under the line, the normal "too unsure" check pauses the run, the same as for any other low score.

**The yes/no questions.**

- *Too unsure?* The trusted number is under the failure-type line. Exactly on the line counts as sure enough (`below_class_cutoff`).
- *Pause the run?* Yes if the type is `unknown` or the number is too low (`class_escalation`). If a person has already picked the failure type by hand (a "class override"), these two checks are skipped for the rest of the run. Both numbers stay the same.
- *May we name a person as the likely cause?* No while the run waits for a human, no while it is writing its report, and no while the number is too low. That includes after a hand-picked type, because the number is still low (`workflow/attribution.py`).
- The score used later for picking which helper agent to call is a **different kind of number** (`RouteConfidence`). The checks above refuse it, so the two can't be mixed up.

**Where the lines live.** All lines are in `guardrails/thresholds.yaml` under `confidence:`. Today they are guesses, each marked `ASSUMPTION — OQ-2, not calibrated`. `workflow/thresholds.py` reads that file once. The confidence tests read their own copy, `tests/fixtures/thresholds.test.yaml`, so changing the real numbers never breaks them; one test checks the two files still list the same keys, so the copy can't quietly drift out of shape.

**To add a new reason to trust Jev less:** build a `Cap` with its evidence and add it with `ClassConfidence.with_cap(...)`. Never add a new score field, and never write your own "smallest of" code. **To add a new line:** add it to `guardrails/thresholds.yaml` and to `ConfidenceCutoffs`, never as a number in code.
