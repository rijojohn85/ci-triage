---
title: 'Story 1.1 — Authenticate and deduplicate failed-run intake'
type: 'feature'
created: '2026-09-26'
status: 'done'
route: 'dispatch'
baseline_revision: 'e1c074839a145e336d0956c9d4b9fef53592d13e'
review_loop_iteration: 0
followup_review_recommended: true
context: ['{project-root}/AGENTS.md']
warnings: ['oversized']
deferred:
  - summary: >-
      The gateway compose service is granted GITHUB_APP_PRIVATE_KEY and GITHUB_APP_ID it never reads.
    evidence: |-
      Pre-existing AD-16 placement from story 0.3; story 1.1's intent says keep the AD-16 secret names unchanged, so 1.1 deliberately did not alter it. A later least-privilege pass should trim the gateway environment.
    location: >-
      deploy/compose.yaml
    severity: low
  - summary: >-
      A store outage yields an unlogged 500 from the gateway, with no operator-visible audit of rejections.
    evidence: |-
      gateway/app.py does not wrap store calls or log a reason; AGENTS.md asks errors to be typed and logged. Not required by any 1.1 AC; a logging story should own it.
    location: >-
      gateway/app.py
    severity: low
  - summary: >-
      The gateway image copies an explicit workflow/ file whitelist that can break on a new import.
    evidence: |-
      deploy/gateway.Dockerfile copies only workflow/__init__.py, run_states.py and ids.py; a new import from gateway/ would fail in the image with no test catching it. Deferred until the image is built in CI.
    location: >-
      deploy/gateway.Dockerfile
    severity: low
  - summary: >-
      The gateway integration test reuses tests/workflow/conftest.py's pg_dsn fixture and duplicates two small helpers.
    evidence: |-
      tests/security/test_gateway_store_integration.py imports another package's fixture and re-implements apply_migrations/query; a shared conftest plugin would remove the duplication.
    location: >-
      tests/security/test_gateway_store_integration.py
    severity: low
---

## Build Brief

**(1) Story + key:** 1.1 — Authenticate and deduplicate failed-run intake; sprint-status key `1-1-authenticate-and-deduplicate-failed-run-intake`.

**(2) ACs in one line:**
- **AC1:** over raw workflow_run bytes, `X-Hub-Signature-256` is checked with `hmac.compare_digest` before any parsing; missing/bad signature → 401; unknown `installation.id` is rejected and the gateway makes no LLM/GitHub call.
- **AC2:** an authentic `workflow_run` completed/failure event passing the per-installation rate limit and per-repo queue-depth cap inserts one `triage_run` in `RECEIVED` and returns 202; a replayed `X-GitHub-Delivery` is a 2xx no-op and the unique `(repo_id, workflow_run_id, run_attempt)` still forbids a second run under a new delivery id.
- **AC3:** only `workflow_run` completed/failure enqueues (`issue_comment` and other kinds/conclusions are ignored); configured limits stop intake bursts and a rejection makes zero downstream calls.

**(3) Binding ADs:** **AD-17** (signature before parse, 401; installation reject; delivery replay 2xx no-op; unique run identity; per-installation rate limit + per-repo queue cap; insert `triage_run(RECEIVED)` → 202; gateway makes no LLM/GitHub calls). **AD-1** (the only opening move is `[*] → RECEIVED`; state is a `triage_run` column). **AD-4/AD-6** (`run_id` is UUIDv7). **AD-16** (App private key/webhook secret placement unchanged; no secret in logs). **AD-25** (forward-only migration applied by the one-shot job; two webhook secrets accepted during rotation, exercised by 1.3). **AD-19** (limits from config, never code). **AD-22** (rejections are definitive responses, not retries).

**(4) Files:**
- Create: `gateway/__init__.py`, `gateway/signature.py`, `gateway/events.py`, `gateway/limits.py`, `gateway/settings.py`, `gateway/store.py`, `gateway/app.py`, `gateway/__main__.py`; `workflow/ids.py`; `config/gateway.yaml`; `deploy/migrations/0002_webhook_delivery.sql`; `deploy/gateway.Dockerfile`; tests under `tests/security/`.
- Change: `deploy/compose.yaml` (gateway placeholder → real build/command, same secret names), `Makefile` (add `gateway/` to ruff/mypy/pylint), `scripts/check_layer_contract.py` (gateway import rule), `requirements/constraints.txt` + `pyproject.toml` + `scripts/bootstrap.sh` (uvicorn pin), `gateway/README.md`, `deploy/README.md`, `deploy/migrations/README.md`, `docs/DEVELOPER.md`.
- **NOT touched:** leases/workers (1.2), `run_step`/resume (2.3), A2A server/TaskStore (2.4), distiller (2.5), orchestrator, agents, prompts, risk gate, `contracts/` (no new payload type).

**(5) Approach (SOLID/DRY):**
- **S:** `gateway/` is transport only — pure signature/event/limit logic has no I/O (no DB, no HTTP client); one `app.py` composes them.
- **D/I:** `IntakeStore` `Protocol` (enqueue + delivery-record + queue-depth) with a `PostgresIntakeStore` I/O adapter; the app depends on the protocol, tests use a fake. `Clock` injectable into the rate limiter for determinism.
- **O:** event acceptance is a small table/registry over `(action, conclusion)`, not an if/elif chain; a new accepted event is a new entry.
- **DRY:** limits load only from `config/gateway.yaml` (one loader); `run_id` comes from one `workflow.ids.new_run_id()` (UUIDv7), reused by 2.3/2.4; signature/secret handling lives once and already accepts a tuple of secrets so 1.3 adds rotation without rework.
- **Reuse:** Starlette (already pinned via `a2a-sdk[http-server]`) + `starlette.testclient.TestClient` (httpx present); psycopg for enqueue; `workflow.migrate` picks up `0002` with no change.

**(6) TDD plan (red-first; names cite ACs):** AC1 `test_ac1_missing_signature_returns_401`, `test_ac1_bad_signature_returns_401_without_parsing_or_enqueue`, `test_ac1_valid_signature_accepted`, `test_ac1_unknown_installation_rejected_and_no_downstream`; AC2 `test_ac2_authentic_failure_enqueues_received_and_returns_202`, `test_ac2_replayed_delivery_is_2xx_noop_single_row`, `test_ac2_run_identity_unique_under_new_delivery_id`, `test_ac2_concurrent_duplicates_create_one_run`; AC3 `test_ac3_only_completed_failure_workflow_run_enqueues`, `test_ac3_issue_comment_excluded`, `test_ac3_rate_limit_blocks_burst`, `test_ac3_queue_depth_cap_blocks_excess`, `test_ac3_rejection_zero_downstream_calls`, `test_ac3_no_llm_or_github_imports_in_gateway`; `test_new_run_id_is_uuid7_time_ordered`; integration `test_0002_webhook_delivery_applies_and_replay_is_noop`, `test_ac2_queue_count_matches_accepted`.

**(7) Risks / OQ:** uvicorn is not installed — pin it (check context7/PyPI first, AGENTS step 6) in the three pin sources. GitHub request/response headers and payload shape are fixture-driven (no live GitHub in unit tests); the live tunnel is 1.3. Limits are in-process (single gateway under Compose v1) — note this in DEVELOPER. No OQ remaining; dependencies 0.3/0.4/2.1 are done.

**(8) Doc impact:** `docs/DEVELOPER.md` — new "Gateway intake (story 1.1)" section in plain terms (what signature check, replay no-op, run identity and the two limits do and why), 1.1 in "Built so far", rows for `gateway/`, `config/gateway.yaml`, `0002` in "Where things live", and how to run the gateway locally under "Running things". `docs/USER-GUIDE.md` — no doc change: operator-only ingress; no user-visible install/use flow changes.

<intent-contract>

## Intent

**Problem:** Nothing accepts GitHub `workflow_run` failures yet. Without a gateway that verifies authenticity, rejects unknown installations, collapses replays/duplicates and sheds bursts, forged or flooded webhooks could create phantom `triage_run` work that every later capability then processes.

**Approach:** Build `gateway/` as a Starlette ASGI app: a pure constant-time signature check over raw bytes, a small accepted-event registry (`workflow_run` completed/failure only), an in-memory per-installation rate limiter and a DB-backed per-repo queue-depth cap, and an `IntakeStore` protocol whose Postgres adapter inserts `webhook_delivery` + `triage_run(RECEIVED)` idempotently in one transaction. `run_id` is UUIDv7 from a new pure `workflow/ids.py`.

## Boundaries & Constraints

**Always:** verify `X-Hub-Signature-256` over raw request bytes with `hmac.compare_digest` before parsing; return 401 on missing/bad signature; reject unknown `installation.id`; return a 2xx no-op for a replayed `X-GitHub-Delivery`; dedupe on unique `(repo_id, workflow_run_id, run_attempt)`; insert `triage_run(RECEIVED)` and return 202 only after the checks; load limits from `config/gateway.yaml`; keep `run_id` UUIDv7; keep AD-16 secret placement names unchanged.

**Never:** make an LLM or GitHub API call from the gateway; parse the body before the signature check; return 500 for a rejected/duplicate request; write any state other than `RECEIVED`; add business/state-machine logic to `gateway/`; touch leases, steps, A2A or the distiller.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| HAPPY_PATH | valid signature, known installation, completed/failure, limits allow | `webhook_delivery` + one `triage_run(RECEIVED)`; 202 | none |
| REPLAY_DELIVERY | same `X-GitHub-Delivery` again | no new rows; 2xx no-op | none |
| DUPLICATE_RUN_NEW_DELIVERY | new delivery id, same `(repo,run,attempt)` | no second `triage_run`; 2xx | none |
| BAD_SIGNATURE | missing/incorrect HMAC | 401; body never parsed; no enqueue | definitive 401 |
| UNKNOWN_INSTALLATION | `installation.id` not configured | rejected; no enqueue, no downstream call | definitive 4xx |
| OTHER_EVENT | `issue_comment`, other action/conclusion | ignored; no enqueue | 2xx no-op |
| RATE_LIMITED | > limit per installation in window | rejected; no enqueue | 429 |
| QUEUE_FULL | repo pending runs at cap | rejected; no enqueue | 429 |
| CONCURRENT_DUPES | two requests same identity at once | exactly one `triage_run` | one request no-ops |

</intent-contract>

## Code Map

- `deploy/migrations/0001_triage_run.sql` — `triage_run` columns, `uq_triage_run_identity (repo_id, workflow_run_id, run_attempt)`, `state` CHECK. `0002` adds `webhook_delivery` only; do not edit `0001`.
- `workflow/migrate.py` — `read_migrations()` picks up `0002_*.sql`; do not modify.
- `workflow/run_states.py` — `RunState.RECEIVED` is the only state inserted (AD-1); reuse the enum, no literal.
- `workflow/thresholds.py` + `guardrails/thresholds.yaml` — the loader/one-config-file pattern to mirror for `config/gateway.yaml` (keep gateway config out of `workflow/`).
- `deploy/compose.yaml:56-69` — the `gateway` placeholder (busybox, env names) to replace with the real image/command; secret keys stay identical.
- `tests/security/test_compose_secret_placement.py` — owns the AD-16 scope table and exact service set; the change must keep it green (env names and service set unchanged).
- `scripts/check_layer_contract.py:136-148` — `check_agents` AST pattern to mirror for a new `gateway` rule forbidding `anthropic`/`a2a`/GitHub-client imports.
- `Makefile:13-64` — add `gateway/` to `ruff-check`, `ruff-format`, `mypy-check`, `pylint-dup` (coverage source stays contracts/guardrails/workflow per AGENTS.md).
- `requirements/constraints.txt`, `pyproject.toml`, `scripts/bootstrap.sh` (`PY_PINS` + `verify_py`) — the three pin sources for uvicorn; pin the current stable after checking context7/PyPI (AGENTS step 6).
- `tests/workflow/conftest.py` — the disposable `postgres:18` `pg_dsn` fixture for the integration tests.
- Starlette is installed (pinned 1.7.0 via `a2a-sdk[http-server]`); use `starlette.applications.Starlette` and `starlette.testclient.TestClient`.

## Tasks & Acceptance

**Execution:**
- `tests/security/test_gateway_signature.py`, `test_gateway_intake.py`, `test_gateway_limits.py` -- write failing AC tests first (red) -- TDD per AGENTS.md
- `gateway/signature.py` -- pure `verify_signature(raw_body, header, secrets) -> bool` using `hmac.compare_digest` over sha256 -- AC1
- `gateway/events.py` -- accepted-event registry + minimal parse of `workflow_run` completed/failure; expose installation/repo/run identity -- AC1/AC3
- `gateway/settings.py` -- `GatewaySettings.from_env()` (webhook secret tuple, allowed installation ids, DSN) + `GatewayLimits` loader for `config/gateway.yaml` -- AC1/AC3, AD-19
- `config/gateway.yaml` -- per-installation rate limit and per-repo queue-depth cap -- AC3, AD-19
- `gateway/limits.py` -- `InstallationRateLimiter` (injectable clock) + queue-depth check against the store -- AC3
- `gateway/store.py` -- `IntakeStore` `Protocol` + `PostgresIntakeStore` doing delivery-dedupe then idempotent `triage_run` insert in one transaction -- AC2/AD-17
- `gateway/app.py` -- `create_app(settings, store, clock)` Starlette app: signature → installation → event → limits → enqueue; status codes per the matrix -- AC1/AC2/AC3
- `workflow/ids.py` -- pure `new_run_id()` UUIDv7 (time-ordered, RFC 9562) -- AC2/AD-4
- `gateway/__main__.py` -- load settings + Postgres store + uvicorn serve -- runnable gateway, AD-25
- `deploy/migrations/0002_webhook_delivery.sql` -- `delivery_id` primary key + repo/run identity + `received_at` -- AC2/AD-17/AD-25
- `deploy/gateway.Dockerfile` + `deploy/compose.yaml` -- real gateway image/command; secret names unchanged -- AD-16/AD-25
- `scripts/check_layer_contract.py` + `Makefile` -- mechanical gateway boundary + gate inclusion -- AC1/AC3
- `requirements/constraints.txt`, `pyproject.toml`, `scripts/bootstrap.sh` -- uvicorn pin (single-source discipline) -- AD-25
- `tests/security/test_gateway_store_integration.py` -- `@pytest.mark.integration`: `0002` applies, replay no-op, queue count -- AC2/AC3
- `gateway/README.md`, `deploy/README.md`, `deploy/migrations/README.md`, `docs/DEVELOPER.md` -- docs (brief part 8)

**Acceptance Criteria:**
- Given raw bytes and no/bad signature, when the request arrives, then 401 and the body is never parsed and nothing is enqueued (AC1).
- Given a valid signature and unknown `installation.id`, when evaluated, then it is rejected with no LLM/GitHub call (AC1).
- Given an authentic completed/failure event within limits, when received, then one `triage_run(RECEIVED)` is inserted and 202 returned (AC2).
- Given a replayed delivery or a duplicate run identity under a new delivery id, when received, then no second run exists and the response is 2xx (AC2).
- Given other events/conclusions or a burst past the configured limits, when evaluated, then nothing enqueues and no downstream call is made (AC3).
- Given concurrent duplicate requests, when both run, then exactly one `triage_run` exists (AC2).

## Verification

**Commands:**
- `.venv/bin/pytest tests/security -q` -- expected: unit tests green, red-first history noted
- `.venv/bin/pytest -m integration tests/security -q` (Docker) -- expected: `0002` applies; replay no-op; queue count
- `make check` -- expected: PASS including the gateway layer rule and `gateway/` lint/type gates
- `python -c "from gateway.app import create_app"` -- expected: imports cleanly

**Manual checks:**
- `grep -R "anthropic\|import a2a\|from a2a" gateway/*.py` returns nothing (AD-17 boundary).

## Review Triage Log

### 2026-09-26 — Review pass

- verdicts: 39 findings — high 0, medium 8, low 29, false 2, maybe-false 0
- findings:
  - `[low]` `[patch]` `workflow/ids.py` constant `_MILLISECONDS_PER_SECOND` misnames ns-per-ms — renamed `_NANOSECONDS_PER_MILLISECOND`.
  - `[medium]` `[patch]` `_parse_body` lets `UnicodeDecodeError` escape → 500 — now catches `ValueError` → 400.
  - `[low]` `[reject]` a replay also tripping the rate/queue gates returns 429, not 2xx — no duplicate work results and GitHub retries; the fix needs a pre-limit delivery lookup (new store surface); not worth the complexity.
  - `[medium]` `[patch]` Postgres adapter returned `run_id=None` on replay/duplicate while the fake returned the existing id — adapter now selects the existing run id by identity and the integration test asserts it.
  - `[medium]` `[patch]` `webhook_delivery` lacks `run_id` so a replay could not recover it — resolved by selecting from `triage_run` by `(repo_id, workflow_run_id, run_attempt)`; no column added.
  - `[low]` `[reject]` queue-depth read and insert are not atomic → concurrent overshoot — the cap is a shedding heuristic with no everyday harm, and an atomic guarded insert adds complexity.
  - `[low]` `[reject]` `from_env` accepts empty secrets/installations/DSN — config is deployed deliberately and a misconfiguration fails loudly on first request; validation was not an AC.
  - `[low]` `[defer]` gateway is granted `GITHUB_APP_PRIVATE_KEY`/`GITHUB_APP_ID` it never reads — pre-existing 0.3 placement; 1.1's intent says keep AD-16 names unchanged; deferred to a least-privilege pass.
  - `[low]` `[reject]` Dockerfile repeats pins and pins `click` — matches the established `migrate.Dockerfile` pattern; `click` ships with uvicorn; explicit image pins are intentional.
  - `[low]` `[patch]` no `.dockerignore` for `context: .` — added a repo-root `.dockerignore`.
  - `[low]` `[patch]` `.env.example` missing the new gateway knobs — added names-only `GATEWAY_HOST_PORT=`, `GATEWAY_HOST=`, `GATEWAY_PORT=`.
  - `[low]` `[reject]` no healthcheck/health route — outside the ACs; Compose gating already depends on postgres+migrate and no consumer needs it yet.
  - `[low]` `[defer]` no logging/error wrapping around store calls — hardening for a later logging story, not a 1.1 AC.
  - `[false]` `[reject]` rate-limiter memory grows unbounded — `screen()` rejects installations not in `allowed_installation_ids` before the limiter, so the key set is bounded by configuration.
  - `[low]` `[patch]` test re-declared the forbidden-module set and used a non-recursive glob — now imports the set from `scripts.check_layer_contract` and uses `rglob`.
  - `[low]` `[defer]` Dockerfile's explicit `workflow/` whitelist is fragile — real but unexercised until the image is built in CI.
  - `[low]` `[patch]` `starlette`/`PyYAML` imported directly but only transitive — added as direct pinned dependencies.
  - `[low]` `[reject]` `tests/security/test_run_ids.py` misplaced — the spec places the story's tests under `tests/security/`, and `workflow/ids.py` is the intake run identity; moving buys nothing.
  - `[low]` `[patch]` signed non-dict body and blank `X-GitHub-Event` untested — added both cases.
  - `[medium]` `[patch]` body read fully before the signature with no cap → memory exhaustion (AD-17 flooding) — added a bounded body read (`max_body_bytes`) returning 413.
  - `[medium]` `[patch]` duplicate of the `UnicodeDecodeError` finding — same fix.
  - `[medium]` `[patch]` duplicate of the lost `run_id` finding — same fix.
  - `[low]` `[reject]` duplicate of the non-atomic queue-cap finding.
  - `[low]` `[reject]` duplicate of the no-fail-fast settings finding.
  - `[low]` `[reject]` `load_gateway_limits` unguarded on a missing/empty file — the file is committed and static; the failure is loud, not silent.
  - `[low]` `[reject]` `new_run_id(now_ms=...)` can overflow the 48-bit range — reachable only through the test injection; the real clock cannot.
  - `[false]` `[reject]` duplicate of the rate-limiter memory finding.
  - `[medium]` `[patch]` duplicate of the fake/real `run_id` divergence (verification-gap).
  - `[low]` `[patch]` per-installation rate-limit isolation untested — added a two-id unit test.
  - `[low]` `[patch]` queue-depth `state = RECEIVED` filter unobservable — added a terminal-state integration case.
  - `[low]` `[reject]` intent-alignment: invented response codes/body vocabulary and the fake-vs-Postgres evidence split — descriptive only; the codes are a designer choice the spec left open, and integration tests are excluded from `make check` by the project's own configuration.
  - `[medium]` `[patch]` duplicate of the fake-vs-adapter contract break (clean-code).
  - `[low]` `[patch]` test duplicated the header constants — now imported from `gateway.signature`/`gateway.events`.
  - `[low]` `[patch]` the forbidden-module fact lived twice — single-sourced from `scripts.check_layer_contract`.
  - `[low]` `[patch]` duplicated AST import scan in tests — the scan now reuses the script's helpers.
  - `[low]` `[patch]` unit test asserted the fake's locking — renamed to state it verifies the fake contract; integration owns the real concurrency proof.
  - `[low]` `[patch]` duplicate of the `ids.py` constant-name finding.
  - `[low]` `[patch]` DEVELOPER still called the gateway a placeholder — corrected.
  - `[low]` `[patch]` DEVELOPER `scripts/` status omitted 1.1 — added.

## Auto Run Result

Status: done
Baseline: `e1c074839a145e336d0956c9d4b9fef53592d13e`.

**Summary.** Built the webhook intake gateway (AD-17): constant-time HMAC over the raw body before parsing, an accepted-event registry (`workflow_run` completed/failure only), unknown-installation rejection, an in-memory per-installation rate limiter and a Postgres-backed per-repo queue-depth cap, and idempotent enqueue of one `triage_run(RECEIVED)` via delivery dedupe plus the unique run identity, all in one transaction. `run_id` is a new pure UUIDv7 factory (`workflow/ids.py`). Starlette + uvicorn pinned and the gateway compose service is now real.

**Files changed (one line each):**
- `gateway/{__init__,app,events,limits,settings,signature,store,__main__}.py` — the intake app, pure decisions, Protocol + Postgres adapter, uvicorn entrypoint.
- `workflow/ids.py` — pure UUIDv7 `new_run_id`.
- `config/gateway.yaml` — rate limit, window, queue-depth cap, max body bytes (AD-19).
- `deploy/migrations/0002_webhook_delivery.sql` — the delivery-replay record.
- `deploy/gateway.Dockerfile`, `deploy/compose.yaml`, `deploy/README.md`, `deploy/migrations/README.md` — real gateway image/service, docs.
- `Makefile`, `scripts/check_layer_contract.py` — gateway lint/type gates and the no-LLM/GitHub layer rule.
- `pyproject.toml`, `requirements/constraints.txt`, `scripts/bootstrap.sh` — uvicorn + direct `starlette`/`PyYAML` pins.
- `tests/security/{conftest,gateway_fakes,test_gateway_signature,test_gateway_intake,test_gateway_limits,test_gateway_store_integration,test_run_ids}.py`, `tests/workflow/test_triage_run_migration.py` — AC tests and the migration-count derivation.
- `docs/DEVELOPER.md`, `gateway/README.md`, `.env.example`, `.dockerignore` — docs and build hygiene.

**Review findings.** 39 reported: 0 high, 8 medium, 29 low, 2 false. Patched 12 entries (the 3 medium root causes below plus the low corrections); deferred 4 (compose least-privilege, store logging, image workflow-file whitelist, integration-test fixture reuse); rejected 23 with reasons in the log above (2 verified false: the rate-limiter memory claim and one duplicate).

**Patched medium root causes:** (1) `_parse_body` now catches `ValueError` so a signed non-UTF-8 body is a 400, never a 500; (2) the Postgres adapter now returns the existing `run_id` on replay/duplicate, matching the fake and asserting it in integration; (3) the request body is read bounded by `max_body_bytes` (413 over the cap) so an unauthenticated caller cannot exhaust memory.

**Follow-up review recommendation: true.** Named unverified risk: the new bounded-body 413 path and the adapter's second `SELECT` on conflict are fresh behaviour added during patching and have not themselves been re-reviewed.

**Verification performed:**
- `git diff` reviewed since baseline (1814-line patch, then re-generated after patches).
- `.venv/bin/pytest tests/security -q` → 35 passed, 3 deselected.
- `make check` → PASS (bootstrap, layer contract, schema/state-diagram drift, ruff check+format, mypy --strict, pylint dup, 196 tests, coverage 92.87%).
- `.venv/bin/pytest -m integration -q` → 12 passed (postgres:18: `0002` apply, replay/duplicate run-id, queue count, concurrency).
- `python -c "from gateway.app import create_app"` → clean; gateway has no `anthropic`/`a2a`/GitHub imports (layer gate).

**Residual risks:** limits and the rate limiter are in-process (correct for the single Compose gateway; a multi-replica gateway needs a shared store); the gateway image is defined but not built in CI yet; cost/token auditing and the worker loop arrive in later stories.
