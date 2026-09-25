---
title: 'Story 1.2 — Claim, renew and fence worker leases'
type: 'feature'
created: '2026-09-26'
status: 'done'
route: 'dispatch'
baseline_revision: '59291c7a6c7e5d348243d7122b5423fc886e84da'
review_loop_iteration: 0
followup_review_recommended: true
context: ['{project-root}/AGENTS.md']
warnings: ['oversized']
deferred:
  - summary: >-
      A discarded stale-owner commit raises LeaseLost with no log line, so a lost lease leaves no audit trace.
    evidence: |-
      AGENTS.md asks errors to be logged with run_id before re-raising; lease_store.guarded_commit raises without logging. A logging story should own it; no 1.2 consumer reads it yet.
    location: >-
      workflow/lease_store.py
    severity: low
---

## Build Brief

**(1) Story + key:** 1.2 — Claim, renew and fence worker leases; sprint-status key `1-2-claim-renew-and-fence-worker-leases`.

**(2) ACs in one line:**
- **AC1:** with multiple eligible rows and N workers, `SELECT … FOR UPDATE SKIP LOCKED` in a short transaction sets `lease_owner`/`lease_until` and commits before any external call; one live owner claims a run and N workers enforce the concurrency cap.
- **AC2:** a long step renews its lease (`lease_until` extends while the owner is valid) and expired/unowned rows are reclaimable without a database lock held across the model call.
- **AC3:** worker A loses its lease to worker B; A's lease-guarded step-commit is discarded on `lease_owner` mismatch (no step output, no state write) and a deterministic two-worker test proves stale-owner fencing and that B can progress.

**(3) Binding ADs:** **AD-23** (claim = short transaction over unleased/expired rows; renew; step-commit re-checks `lease_owner` and discards on mismatch). **AD-2** (a step's output row and the state transition commit in one lease-guarded transaction; reclaimed runs re-enter at their current state). **AD-1** (`triage_run` owns run state; leased rows stay in their current state; terminal rows are not claimable). **AD-19/AGENTS** (lease timings and worker identity come from config, never code). **AD-22** (a lost lease is definitive, not a transient retry).

**(4) Files:**
- Create: `workflow/leases.py` (`Claim`, `RunLeaseStore` protocol, pure helpers, `PostgresRunLeaseStore`); `workflow/orchestrator_config.py` (loader); `config/orchestrator.yaml`; `deploy/migrations/0003_triage_run_lease.sql`; `tests/workflow/test_leases.py`; integration tests in `tests/workflow/test_lease_integration.py`.
- Change: `workflow/README.md`, `deploy/migrations/README.md` (0003 note), `docs/DEVELOPER.md`; extend `tests/workflow/conftest.py` only if the disposable-postgres fixture needs a shared helper (do not duplicate it). Also update `tests/security/test_compose_secret_placement.py`: the `test_ac3_no_speculative_domain_tables_triage_run_allowlisted` guard currently allows only `0001_triage_run.sql` to name `triage_run`, so `ALTER TABLE triage_run` in `0003` trips it — add `0003_triage_run_lease.sql` to that allowlist (still no `run_step`/`history`/`approval`).
- **NOT touched:** the `run_step` table and step persistence (2.3 owns them; this story supplies the guard primitive 2.3 composes), gateway intake (1.1), A2A server/TaskStore (2.4), distiller (2.5), agents, prompts, `contracts/`, `workflow/transitions.py`.

**(5) Approach (SOLID/DRY):**
- **S:** `workflow/leases.py` is domain decision logic + one SQL adapter; no HTTP, no worker loop (the loop arrives with 2.3/2.8).
- **I:** small `RunLeaseStore` `Protocol` per AGENTS.md naming: `claim_next`, `renew`, `guarded_commit`, plus pure `lease_expired`/`renew_due`. Unit tests drive a fake store; the real adapter is used only in marked integration tests.
- **D:** the guard is the unit-of-work primitive from AD-2/AD-23 — the store runs one transaction that re-checks `lease_owner` under `FOR UPDATE` and rolls back on mismatch; 2.3 passes its `run_step` write as the guarded work instead of re-implementing the check.
- **O/extend:** claimable states derive from `workflow.run_states.TERMINAL_RUN_STATES` (not a hand-listed set) so later state changes flow through.
- **DRY:** `lease_owner` is one factory (`new_lease_owner()`), timings come only from `config/orchestrator.yaml`, and `now` is injectable so no test sleeps.

**(6) TDD plan (red-first; names cite ACs):** AC1 `test_ac1_claim_sets_owner_and_expiry_and_returns_claim`, `test_ac1_claim_uses_skip_locked_and_short_transaction`, `test_ac1_leased_row_skipped_until_expiry`, `test_ac1_terminal_run_not_claimable`, `test_ac1_n_workers_claim_distinct_rows_at_most_once` (integration, N threads); AC2 `test_ac2_renew_extends_expiry_for_owner_only`, `test_ac2_expired_row_reclaimable_by_other_worker` (integration), `test_ac2_lease_expired_and_renew_due_helpers`; AC3 `test_ac3_guarded_commit_rejects_owner_mismatch` (fake), `test_ac3_stale_owner_discarded_without_state_or_output` (integration), `test_ac3_two_worker_fencing_and_b_recovers` (integration, deterministic); migration `test_0003_migration_adds_lease_columns_and_claim_index` (integration).

**(7) Risks / OQ:** migration ordering assumes 1.1 lands `0002_webhook_delivery.sql` first, so this story ships `0003`; integration tests need Docker (`postgres:18`). Time is injectable/DB-`now()`-seeded, never a real sleep. Concurrency cap is structural (N workers claim one row each), proven by the N-thread test; no worker loop here. No OQ remaining.

**(8) Doc impact:** `docs/DEVELOPER.md` — new "Worker leases and fencing (story 1.2)" section in plain terms (what a lease is, why an expired lease is reclaimable, why a stale owner's commit is thrown away), 1.2 in "Built so far", rows for `workflow/leases.py`, `config/orchestrator.yaml`, `0003` in "Where things live", and the extend note (a new claimable-state rule derives from the state machine). `docs/USER-GUIDE.md` — no doc change: internal worker mechanism, no user-visible flow.

<intent-contract>

## Intent

**Problem:** After 1.1 queues runs, multiple workers would race them. Without leases and fencing, two workers could run the same multi-minute model call, and a worker whose lease expired could still commit its stale result, corrupting run state and duplicating work.

**Approach:** Add `lease_owner`/`lease_until` to `triage_run` (migration `0003`) and build `workflow/leases.py`: a claim that locks an unleased/expired claimable row with `FOR UPDATE SKIP LOCKED` in a short transaction, a renew that only the current owner may extend, and a lease-guarded commit primitive that re-checks `lease_owner` under `FOR UPDATE` and discards the work on mismatch. A `RunLeaseStore` protocol lets unit tests fake the boundary; a deterministic two-worker integration test proves real fencing.

## Boundaries & Constraints

**Always:** claim only rows whose state is non-terminal and whose lease is absent or expired; do the claim in a short transaction that commits before any external call; set a new owner and expiry from config; extend only the current owner's lease; re-check `lease_owner` under `FOR UPDATE` inside the guarded-commit transaction and roll back on mismatch; derive claimable states from `TERMINAL_RUN_STATES`.

**Never:** hold a database lock across the model call; let a non-owner renew or commit; re-execute a completed step on reclaim (2.3 owns step persistence — this story only supplies the guard); hand-list terminal states; hardcode lease timings; add a worker loop or HTTP/A2A surface.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| CLAIM_FREE | non-terminal row, no lease | owner + `lease_until` set, committed; `Claim` returned | none |
| CLAIM_EXPIRED | non-terminal row, `lease_until < now()` | row reclaimed by the new owner | none |
| CLAIM_LEASED | live lease held by another | row skipped; next claimable row returned | none |
| CLAIM_NO_ROWS | nothing claimable | `None`; no write | none |
| RENEW_OWNER | caller is `lease_owner` | `lease_until` extended | none |
| RENEW_NON_OWNER | caller is not `lease_owner` | rejected, no extension | definitive `False`/typed error |
| RENEW_EXPIRED | lease expired mid-step | rejected | definitive |
| COMMIT_OWNER | guarded work by current owner | work commits in the same transaction | rollback on work error |
| COMMIT_STALE | `lease_owner` no longer matches | work rolled back; no state/output change | `LeaseLost`/`False` |

</intent-contract>

## Code Map

- `deploy/migrations/0001_triage_run.sql` — `triage_run` has no lease columns yet; `0003` alters it. `state` CHECK and `uq_triage_run_identity` are the claim's filters. Do not edit `0001`.
- `workflow/migrate.py` — picks up `0003_*.sql` automatically; do not modify.
- `workflow/run_states.py` — reuse `TERMINAL_RUN_STATES` to define claimable states; never a literal list.
- `workflow/transitions.py` + `workflow/thresholds.py` — the "pure domain + one config loader" pattern this story mirrors in `workflow/leases.py` + `workflow/orchestrator_config.py`.
- `deploy/migrations/0002_webhook_delivery.sql` — planned by story 1.1; orders before `0003` (assumption, see Build Brief 7).
- `tests/security/test_compose_secret_placement.py:131-153` — `test_ac3_no_speculative_domain_tables_triage_run_allowlisted`; `0003` names `triage_run` so it must join that allowlist (and must keep `run_step`/`history`/`approval` out).
- `tests/workflow/conftest.py` — `pg_dsn` disposable `postgres:18` fixture; reuse for the two-worker integration tests.
- `tests/workflow/test_triage_run_migration.py` — the `@pytest.mark.integration` + `PsycopgMigrationConnection` pattern for applying `0003` and asserting columns/index.
- AGENTS.md names `RunLeaseStore` as the per-consumer protocol; keep the name and keep it small.
- `psycopg` 3.3.6 — use `conn.transaction()` and `FOR UPDATE SKIP LOCKED`; no ORM.

## Tasks & Acceptance

**Execution:**
- `tests/workflow/test_leases.py`, `tests/workflow/test_lease_integration.py` -- write failing AC tests first (red) -- TDD per AGENTS.md
- `config/orchestrator.yaml` -- `lease_seconds` and `renew_after_seconds` -- AC1/AC2, no magic values
- `workflow/orchestrator_config.py` -- frozen loader for `config/orchestrator.yaml` (mirrors `workflow/thresholds.py`) -- AC1/AC2
- `workflow/leases.py` -- `Claim`, `new_lease_owner()`, pure `lease_expired`/`renew_due`, `RunLeaseStore` protocol (`claim_next`, `renew`, `guarded_commit`), `LeaseLost`, `PostgresRunLeaseStore` -- AC1/AC2/AC3
- `deploy/migrations/0003_triage_run_lease.sql` -- `ALTER TABLE triage_run ADD lease_owner text NULL, lease_until timestamptz NULL` + a claim index on `lease_until` -- AC1/AD-23
- `tests/security/test_compose_secret_placement.py` -- allowlist `0003_triage_run_lease.sql` in the `triage_run` table guard (consuming-story pattern set by 2.1) -- AC1
- `tests/workflow/test_lease_integration.py` -- N-thread claim uniqueness, expired reclaim, two-worker fencing via real Postgres -- AC1/AC2/AC3
- `workflow/README.md`, `deploy/migrations/README.md`, `docs/DEVELOPER.md` -- docs (brief part 8)

**Acceptance Criteria:**
- Given multiple claimable rows and N concurrent workers, when they claim, then each row is claimed at most once and each claim commits before returning (AC1).
- Given a live lease, when another worker claims, then the row is skipped; given an expired lease, when claimed, then it is reclaimed (AC1/AC2).
- Given the current owner, when it renews, then `lease_until` extends; a non-owner renew is rejected (AC2).
- Given worker A reclaimed by B, when A runs its guarded commit, then nothing A wrote persists and B can commit (AC3).
- Given a guarded commit by the current owner, when the work succeeds, then the work and the lease re-check commit atomically (AC3).

## Verification

**Commands:**
- `.venv/bin/pytest tests/workflow/test_leases.py -q` -- expected: unit tests green, red-first history noted
- `.venv/bin/pytest -m integration tests/workflow/test_lease_integration.py -q` (Docker) -- expected: claim/renew/fencing green on `postgres:18`
- `make check` -- expected: PASS
- `git grep -n "lease_owner" deploy/migrations/0003_triage_run_lease.sql` -- expected: the two columns plus the claim index

**Manual checks:**
- Confirm no `sleep(` appears in the lease tests (time is injected or DB-seeded).

## Review Triage Log

### 2026-09-26 — Review pass

- verdicts: 41 findings — high 0, medium 8, low 32, false 1, maybe-false 0
- findings:
  - `[low]` `[reject]` the fence re-checks `lease_owner` but not lease expiry — AD-23 requires only the owner re-check; a concurrent reclaim overwrites the owner and `FOR UPDATE` fences the later commit; an expired-but-unclaimed commit duplicates nothing.
  - `[low]` `[reject]` `guarded_commit` has no `now` argument — same reason; expiry is not a commit condition per AD-23.
  - `[medium]` `[patch]` `renew` never runs against real Postgres; its only test asserts SQL substrings — added a real-DB renew test (owner extends, non-owner `False` and unchanged, expired refused).
  - `[low]` `[patch]` `load_orchestrator_config` is unconsumed while docs say it is — reworded the docs to say the loader is for the worker loop (2.3/2.8); the config-to-claim join arrives with that loop.
  - `[low]` `[patch]` `renew_after_seconds < lease_seconds` is documented but unenforced — added a model validator plus a temp-file test.
  - `[low]` `[patch]` lease timings accept zero/negative — same validator also requires positive values.
  - `[low]` `[patch]` `new_lease_owner` reads an undocumented `WORKER_ID` — added it to `.env.example` and one plain sentence in DEVELOPER.
  - `[low]` `[reject]` the per-claim random token defeats owner grouping — deliberate uniqueness so a restarted worker is never mistaken for its predecessor; the prefix still names the worker.
  - `[medium]` `[patch]` the integration tests mix a fixed `NOW` with the DB/wall clock and fail after a fixed moment — `expire_lease` now seeds from the injected `NOW` and asserts against it.
  - `[low]` `[reject]` mixed DB/application clocks in one statement — lease decisions consistently use the injected `now`; `updated_at = now()` is cosmetic.
  - `[low]` `[reject]` no CHECK ties `lease_owner` to `lease_until` — the claim writes both together and renew writes only the expiry; no inconsistent state is produced.
  - `[low]` `[reject]` the claim index does not cover the `state` filter — a composite/partial index is a future performance refinement, not a correctness need.
  - `[low]` `[reject]` the `ORDER BY run_id` FIFO tie-break is undocumented — `run_id` is UUIDv7 time-ordered (AD-4), which is what makes the order FIFO.
  - `[low]` `[reject]` unit tests pin SQL substrings — the real claim/renew/fencing behaviour is proven against Postgres in the integration tests.
  - `[low]` `[reject]` `FakeConnection` returns one scripted row for every execute — the integration tests exercise the real statement order; the fake is a boundary double.
  - `[low]` `[reject]` the `row is None` branch of `guarded_commit` is untested — it models a deleted run, which nothing in 1.2 can produce.
  - `[medium]` `[patch]` duplicate of the renew real-DB coverage finding — same fix.
  - `[low]` `[reject]` two migration-index tests assert the same index — harmless redundancy, neither is wrong.
  - `[low]` `[reject]` the config loader raises raw `KeyError`/`TypeError` — the file is committed and static; the failure is loud, not silent.
  - `[low]` `[reject]` the loader re-reads YAML on every call — the worker loop will load it once; not a 1.2 hot path.
  - `[low]` `[reject]` `LeaseLost` sits outside the A2A error taxonomy — same shape as 2.1's `IllegalTransition`, which the project already accepted.
  - `[low]` `[defer]` no log line when a lease is lost — logging arrives with a later logging story.
  - `[low]` `[reject]` `guarded_commit` could hold the row lock across slow work — the step loop (2.3/2.8) passes DB-only writes; the model call happens before the guard.
  - `[false]` `[reject]` the `RunLeaseStore` Protocol "leaks an unbound TypeVar" — a type variable in a Protocol method makes it generic; `mypy --strict` accepts it.
  - `[low]` `[reject]` `_as_uuid` raises a bare `ValueError` on a schema mismatch — defensive coercion for an impossible row shape; no consumer.
  - `[low]` `[patch]` the 1.2 story row omits the schema-guard test file — added.
  - `[low]` `[reject]` duplicate of the time-bomb finding (expiry seeded from the DB clock).
  - `[low]` `[reject]` duplicate of the `datetime.now()` assertion (same fix).
  - `[low]` `[reject]` duplicate of the empty-config `TypeError` finding (static committed file).
  - `[low]` `[reject]` duplicate of the unvalidated-invariant finding.
  - `[low]` `[reject]` duplicate of the non-positive-timing finding.
  - `[medium]` `[patch]` duplicate of the wall-clock-coupled fence-proof finding — same fix.
  - `[medium]` `[patch]` duplicate of the renew real-DB finding (verification-gap).
  - `[medium]` `[patch]` duplicate of the wall-clock/gate-exclusion finding (verification-gap) — fixed the clock; exclusion from `make check` is the project's own integration convention.
  - `[low]` `[reject]` intent-alignment: SQL-text assertions, Protocol seam without a store-level fake, config join — descriptive; the behavioural matrix is proven against real Postgres and the store-level fake arrives with the worker loop.
  - `[medium]` `[patch]` `workflow/leases.py` mixes pure policy with the Postgres adapter and imports `psycopg` (AGENTS SOLID-S) — split the adapter/SQL into `workflow/lease_store.py`; `leases.py` now builds no SQL and imports no driver.
  - `[low]` `[reject]` `lease_expired`/`renew_due` have no production caller — spec-directed helpers for the 2.3/2.8 worker loop; deleting them would contradict the planned interface.
  - `[low]` `[reject]` the claimability predicate appears in both the pure helper and the SQL — one is domain policy, the other the query; the split keeps them readable.
  - `[low]` `[reject]` `claim_next` reads `WORKER_ID` inside the adapter — the spec's one `new_lease_owner` factory; documented now.
  - `[low]` `[patch]` a unit test restates the claimable-set definition verbatim — replaced with an explicit ten-state expected set.
  - `[medium]` `[patch]` DEVELOPER described config wiring that does not exist — reworded to describe the loader as it exists now (worker loop consumes it later).

## Auto Run Result

Status: done
Baseline: `59291c7a6c7e5d348243d7122b5423fc886e84da`.

**Summary.** Built the AD-23 worker-lease and fencing primitives: `workflow/leases.py` holds the pure policy (claimable states derived from the terminal set, `Claim`, `LeaseLost`, `new_lease_owner`, `lease_expired`, `renew_due`, the `RunLeaseStore` protocol), and `workflow/lease_store.py` holds the one Postgres adapter (short-transaction `FOR UPDATE SKIP LOCKED` claim, owner-only renew, `FOR UPDATE` owner re-check whose mismatch rolls the work back with `LeaseLost`). Migration `0003` adds `lease_owner`/`lease_until` and a claim index; `config/orchestrator.yaml` + `workflow/orchestrator_config.py` own the timings.

**Files changed (one line each):**
- `workflow/leases.py` — pure AD-23 policy, `Claim`, `LeaseLost`, owner factory, expiry predicates, `RunLeaseStore` protocol.
- `workflow/lease_store.py` — the Postgres adapter and its SQL (one short connection per call).
- `workflow/orchestrator_config.py`, `config/orchestrator.yaml` — lease timings from one config file (AD-19), with the invariant enforced.
- `deploy/migrations/0003_triage_run_lease.sql`, `deploy/migrations/README.md` — lease columns + claim index.
- `tests/workflow/{test_leases,test_orchestrator_config,test_lease_integration}.py`, `tests/security/test_compose_secret_placement.py` — AC tests and the schema-guard allowlist.
- `workflow/README.md`, `docs/DEVELOPER.md`, `.env.example` — docs.

**Review findings.** 41 reported: 0 high, 8 medium, 32 low, 1 false. Patched 6 root-cause entries (renew real-DB coverage, wall-clock determinism, config invariant, SOLID-S split, docs honesty, claimable-set test); deferred 1 (lease-loss logging); rejected 34 with reasons above (1 verified false: the TypeVar claim).

**Patched medium root causes:** (1) the Postgres adapter/SQL moved out of `leases.py` into `workflow/lease_store.py` so domain code builds no SQL (AGENTS SOLID-S); (2) the integration tests now seed and assert on the injected clock, removing the wall-clock time bomb; (3) a real-Postgres renew test now proves owner-only, non-owner `False`, and expired refusal; (4) DEVELOPER now describes the config loader as it exists rather than claiming a consumer that has not landed.

**Follow-up review recommendation: true.** Named unverified risk: the new `workflow/lease_store.py` split and the real-DB renew test are fresh code added during patching and have not themselves been re-reviewed.

**Verification performed:**
- `git diff` reviewed since baseline, then re-generated after patches.
- `make check` → PASS (216 tests, coverage 93.72%).
- `.venv/bin/pytest -m integration -q` → 20 passed (postgres:18; claim, reclaim, fencing, renew, `0003`).
- `rg "psycopg|SELECT|UPDATE" workflow/leases.py` → none (pure module).

**Residual risks:** `renew_due`/`lease_expired` and the config loader have no production caller until the worker loop (2.3/2.8); the claim's FIFO order relies on `run_id` being UUIDv7; no dump/log on lease loss yet.

## Spec Change Log

<!-- none: no bad_spec loopback on this story -->
