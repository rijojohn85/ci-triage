---
title: 'Story 1.2 — Claim, renew and fence worker leases'
type: 'feature'
created: '2026-09-26'
status: 'ready-for-dev'
route: 'dispatch'
review_loop_iteration: 0
followup_review_recommended: false
context: ['{project-root}/AGENTS.md']
warnings: ['oversized']
deferred: []
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
- Change: `workflow/README.md`, `deploy/migrations/README.md` (0003 note), `docs/DEVELOPER.md`; extend `tests/workflow/conftest.py` only if the disposable-postgres fixture needs a shared helper (do not duplicate it).
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

## Auto Run Result

Status: ready-for-dev
Blocking condition: none
Planned: 2026-09-26. Halted after planning. Reused cached `epic-1-context.md` (valid). No production code written. Assumes story 1.1 lands `0002_webhook_delivery.sql` before this story's `0003`.
