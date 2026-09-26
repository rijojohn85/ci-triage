---
title: 'Maintain structured tenant-scoped history'
type: 'feature'
created: '2026-09-26'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
context: ['{project-root}/AGENTS.md']
baseline_commit: 'eb32191bbdf973553e18de62cf85f66de36a7d78'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Story 2.6. The orchestrator has no durable, tenant-scoped record of past triage outcomes (AD-15) — evidence packs (2.7) will need it, but today history can only be invented ad hoc, ungoverned by tenant scope or structure, risking cross-repo leakage or free-text poisoning of agent evidence.

**Approach:** Add a `history` table holding only enumerated/structured fields (never free text), fingerprinted by sha256 of normalized `test_id + error_type + top_stack_frames`, written exactly once per terminal run by a single orchestrator-only `HistoryStore`. Add a separate `pr_feedback` table for post-terminal human PR feedback so it can never leak into history. Seed rows enter only via a `history import` script. Every query binds `repo_id`.

## Boundaries & Constraints

**Always:** every `history`/`pr_feedback` read and write binds `repo_id` (AD-15); `history` has no free-text column — only enumerated/structured fields; `write_terminal` accepts only `RunState` values in `TERMINAL_RUN_STATES`; a duplicate `write_terminal` for the same `run_id` is a no-op that returns the existing row (idempotent, AD-2 spirit); `human_verdict` is nullable and included only when the caller supplies it; fingerprint normalization is a pure function with no I/O.

**Never:** do not wire `HistoryStore` into `workflow/step_store.py`, the orchestrator's finalize path, or any agent-facing contract — story 2.8 (shared step runner) owns that call site and depends on 2.6 being merged first; do not give agents a history writer; do not let `pr_feedback` content reach the `history` table through any code path; do not add a lease/`Claim` requirement to the history write — terminal runs are already unclaimable (`CLAIMABLE_RUN_STATES` excludes `TERMINAL_RUN_STATES`), so idempotency comes from a DB unique constraint, not lease fencing.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Terminal write, first time | `run_id` new, state=FAILED | one `history` row inserted, `row_id` returned | N/A |
| Terminal write, duplicate | same `run_id` written twice | second call returns the same existing row, no second insert | UniqueViolation caught internally, not raised |
| Non-terminal write attempt | state=AWAITING_APPROVAL | write refused, no row inserted | raises `NonTerminalWriteError` before any I/O |
| Human verdict present | state=REJECTED_BY_HUMAN, verdict=REJECTED | row's `human_verdict` = `rejected` | N/A |
| Human verdict absent | state=FAILED, verdict=None | row's `human_verdict` is NULL | N/A |
| Foreign-repo lookup (RT-03) | lookup with `repo_id` B for a row seeded under `repo_id` A | empty result, never the other tenant's row | no exception — an empty, correctly-scoped result |
| Seed import with free-text field | import record includes an unenumerated key (e.g. `notes`) | rejected before any row is written | raises `TypeError` (unexpected field) surfaced as a non-zero CLI exit |
| PR feedback write (RT-04) | free-text `feedback_text` for a terminal run | row written to `pr_feedback` only | `history` table never touched by this path |

</frozen-after-approval>

## Code Map

- `workflow/run_states.py` -- `RunState`, `TERMINAL_RUN_STATES` — the exact state guard for AC2; reuse, don't redefine.
- `workflow/steps.py` / `workflow/step_store.py` -- the domain/adapter split and Protocol-typed, injectable-`connect` pattern to mirror exactly for `history.py`/`history_store.py`. `step_store.py`'s `DuplicateStepError` catch on `psycopg.errors.UniqueViolation` is the idempotency pattern to reuse (no lease needed here — see Boundaries).
- `workflow/ids.py` -- `new_run_id()` (UUIDv7). Reuse for `history.row_id` generation (DRY — no second UUID scheme).
- `contracts/evidence.py` -- `HistoryRow` (agent-facing: `row_id`, `fingerprint`, `test_id`, `error_type`). This is the *existing*, already-correct shape agents see in the evidence pack (2.7 wires it in) — do not change it, and do not add the new full DB-row type here: it is never transmitted to an agent, so AD-6 does not bind it. The new internal type lives in `workflow/history.py`.
- `contracts/citations.py` -- `HistoryRowCitation` already cites by `row_id` only; no change needed.
- `deploy/migrations/0001_triage_run.sql`, `0004_run_step.sql` -- migration style to match: comment banner naming story/AD, `CREATE TABLE`, named `CONSTRAINT ck_*`/`uq_*`, one repo-scoped index.
- `deploy/migrations/` -- next files are `0005_history.sql`, `0006_pr_feedback.sql` (0001-0004 exist; confirmed via grep that neither table exists yet).
- `workflow/migrate.py` -- unchanged; picks up new files automatically (no edit needed).
- `tests/workflow/test_steps.py` -- the unit-test pattern to mirror: `FakeConnection`/`FakeCursor` Protocol fakes, no real DB, domain + adapter tested together in one file.
- `tests/workflow/test_step_integration.py`, `tests/workflow/test_triage_run_migration.py` -- the `pytest.mark.integration` + `pg_dsn` fixture pattern (`tests/workflow/conftest.py`) to mirror for the real-Postgres AC/RT tests.
- `scripts/migrate.py`-adjacent scripts (`scripts/verify_demo_repo.py`, `scripts/smoke_signed_tunnel.py`) -- argparse + injectable-dependency CLI pattern to mirror for `scripts/history_import.py`.

## Tasks & Acceptance

**Execution:**
- [x] `workflow/history.py` -- pure domain: `normalize_fingerprint(test_id, error_type, top_stack_frames) -> str` (sha256 hex of `\x1f`-joined stripped fields, no I/O), `HumanVerdict` enum (`APPROVED`/`REJECTED`), `HistoryEntry` frozen dataclass, `ImportRecord` frozen dataclass (enumerated fields only — an unexpected keyword raises `TypeError`), `NonTerminalWriteError` -- the AC1 fingerprint rule and the AC2 terminal-state guard, decoupled from SQL.
- [x] `workflow/history_store.py` -- `HistoryStore` Protocol + `PostgresHistoryStore`: `write_terminal(...)` (raises `NonTerminalWriteError` if `to_state not in TERMINAL_RUN_STATES`; catches `UniqueViolation` on `run_id` and re-selects the existing row), `import_seed(records)` (generates a fresh `run_id` per seed row via `workflow.ids.new_run_id()`, returns `row_id`s), `lookup(repo_id, fingerprint)` -- every SQL statement binds `repo_id` -- AC1, AC2, AC3/RT-03.
- [x] `deploy/migrations/0005_history.sql` -- `history` table: `row_id uuid PRIMARY KEY, run_id uuid NOT NULL, repo_id bigint NOT NULL, test_id text NOT NULL, error_type text NOT NULL, top_stack_frames text[] NOT NULL, fingerprint text NOT NULL, terminal_state text NOT NULL, human_verdict text NULL, created_at timestamptz NOT NULL DEFAULT now()`, `CONSTRAINT uq_history_run_id UNIQUE (run_id)`, `CHECK` on `terminal_state` (the 4 `TERMINAL_RUN_STATES` values) and `human_verdict` (`approved`/`rejected`/NULL), repo-scoped index `(repo_id, fingerprint)` -- AC1, AC2.
- [x] `deploy/migrations/0006_pr_feedback.sql` -- `pr_feedback` table: `feedback_id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES triage_run (run_id), repo_id bigint NOT NULL, pr_number integer NOT NULL, feedback_text text NOT NULL, author_login text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()`, repo-scoped index -- AC3.
- [x] `workflow/pr_feedback.py` + `workflow/pr_feedback_store.py` -- tiny domain/adapter pair mirroring `history.py`/`history_store.py`: `PRFeedbackEntry`, `PostgresPRFeedbackStore.write(...)` and `.list_for_run(repo_id, run_id)`, both `repo_id`-bound -- AC3/RT-04.
- [x] `scripts/history_import.py` -- argparse CLI: reads a JSON array of import records from a file or stdin, builds `ImportRecord` per row (rejecting unknown keys), calls `HistoryStore.import_seed`, prints the returned `row_id`s -- AC1, AC3.
- [x] `tests/workflow/test_history.py` -- unit tests (Protocol fakes, no DB): `test_ac1_fingerprint_is_sha256_of_normalized_fields`, `test_ac1_history_queries_bind_repo_id`, `test_ac2_exactly_one_terminal_history_row`, `test_ac2_awaiting_approval_write_refused`, `test_ac2_human_verdict_included_when_present`, `test_ac3_history_import_rejects_free_text`, `test_ac3_foreign_repo_lookup_rejected` (RT-03).
- [x] `tests/workflow/test_history_integration.py` (`pytest.mark.integration`) -- real Postgres: `test_ac1_migration_history_has_no_free_text_column`, `test_ac2_duplicate_finalize_writes_one_row`, `test_ac2_awaiting_approval_writes_no_history_row`, `test_ac3_rt03_foreign_repo_lookup_returns_nothing`, `test_ac3_rt04_pr_feedback_never_becomes_history`.
- [x] `tests/scripts/test_history_import.py` -- CLI unit test: rejects a record with an extra free-text key, prints `row_id`s for a valid batch.
- [x] `docs/DEVELOPER.md` -- add a short "History & PR feedback" subsection: what `history`/`pr_feedback` store, that only the orchestrator writes `history`, and where seed import lives.

**Acceptance Criteria:** (verbatim from epics.md story 2.6 — binding)
- AC1: Given normalized test_id, error_type and top stack frames, when history lookup/import executes, then fingerprint is their normalized sha256 and every query binds task repo_id, and history migration accepts only enumerated/structured fields, rejects free-text notes and returns citeable row_id values.
- AC2: Given terminal state fixtures including FAILED and REJECTED_BY_HUMAN, when the orchestrator finalizes them twice, then exactly one history row per terminal run is written with the human verdict where present, and AWAITING_APPROVAL writes no terminal history; agents have no database writer.
- AC3: Given seed or post-terminal feedback, when it is stored, then seed history enters only through history import; human PR feedback goes to separate pr_feedback storage, and RT-03/RT-04 tests reject foreign-repo lookups/model repo overrides and prove feedback cannot become free-text history.

## Implementation Notes

<!-- Agent-owned. Append-only during implementation. -->

- `write_terminal` takes one `TerminalWrite` frozen dataclass instead of six
  positional/keyword parameters — `ruff`'s `PLR0913`/`PLR0917` (max 5 args,
  AGENTS.md clean code) flagged the original six-parameter signature; a small
  model was the AGENTS.md-prescribed fix, matching `StepCommit`'s pattern in
  `workflow/steps.py`.
- `_open_connection` in both `history_store.py` and `pr_feedback_store.py`
  uses `psycopg.connect(dsn, autocommit=True)`, not a transaction block: the
  `write_terminal` retry path needs to run a SELECT immediately after a
  caught `UniqueViolation` on the same connection, which would otherwise be
  left in an aborted-transaction state. Each statement here is already
  atomic on its own, so autocommit does not weaken AC2 (the unique
  constraint is still the sole source of idempotency).
- `tests/security/test_compose_secret_placement.py::TestNoSpeculativeSchema`
  (story 0.3's anti-speculation gate) explicitly forbade a `history` table by
  name; updated to allowlist `history`/`pr_feedback` for story 2.6 the same
  way it already allowlists `triage_run`/`run_step` for 2.1/2.3, and to keep
  forbidding genuinely speculative tables (`approval`, `a2a_db`,
  `DatabaseTaskStore`).
- Per the spec's Boundaries & Constraints, `HistoryStore`/`PostgresHistoryStore`
  is not wired into `workflow/step_store.py`, any finalize path, or any
  agent-facing contract — that call site is explicitly story 2.8's, which
  depends on 2.6 being merged first.
- `docs/USER-GUIDE.md` was not changed: this story adds no user-visible
  behaviour (no new run outcome, no new operator-facing flow) — `history`
  and `pr_feedback` are internal orchestrator persistence not yet wired into
  any run path.

## Spec Change Log

## Review Triage Log

Review pass 1 (blind-hunter, edge-case-hunter, verification-gap, clean-code). All four layers ran; no reviewer instruction was unavailable.

- **`import_seed` accepts a non-terminal `terminal_state` with no guard** (verification-gap, edge-case-hunter) — `medium`. Verified: `workflow/history_store.py::import_seed` never checks `record.terminal_state in TERMINAL_RUN_STATES` (unlike `write_terminal`, `history_store.py:122-125`); `scripts/history_import.py::build_records` accepts any valid `RunState`, not just a terminal one, and passes it straight through. Reachable both via the CLI and via any direct caller of `import_seed`; today only caught late by the DB `ck_history_terminal_state` CHECK, which surfaces as an unhandled crash, not a clean rejection. → **patch**.
- **`import_seed` writes rows one-at-a-time with no transaction; a mid-batch failure leaves a partial import committed** (blind-hunter, edge-case-hunter) — `medium`. Verified: `history_store.py::import_seed` loops calling `conn.execute(_INSERT_SQL, ...)` per record on an autocommit connection with no `conn.transaction()` wrapper and no rollback. → **patch**.
- **`scripts/history_import.py` doesn't catch `OSError` from a missing/unreadable `--file`** (edge-case-hunter) — `medium`. Verified: `read_rows` calls `source.read_text(...)` directly; `main()`'s except tuple is `(json.JSONDecodeError, HistoryImportError, TypeError)` only. A mistyped path crashes with a raw traceback instead of the script's `FAIL:`/exit-code contract. → **patch**.
- **`build_records` doesn't validate `top_stack_frames` is a list before `tuple(...)`** (edge-case-hunter) — `medium`. Verified: `tuple(fields["top_stack_frames"])` on a string silently splits it into single characters (e.g. `"abc"` → `("a","b","c")`), corrupting the fingerprint input with no error raised. → **patch**.
- **`store.import_seed(records)` in `scripts/history_import.py::main` is not wrapped in try/except** (blind-hunter, verification-gap "Other findings") — `medium`. Verified: line 106 sits outside both try/except blocks in `main()`; a DB error propagates as an unhandled traceback instead of `FAIL:`/non-zero exit. → **patch**.
- **`write_terminal`'s duplicate-write re-select can raise a mislabeled "vanished" `RuntimeError` when the second call's `repo_id` differs from the first's** (edge-case-hunter) — `medium`. Verified: `uq_history_run_id` is unique on `run_id` alone, but the post-`UniqueViolation` re-select filters `WHERE run_id = %s AND repo_id = %s` with the *new* call's `repo_id`; a repo_id mismatch across two calls for the same `run_id` makes that filtered SELECT return nothing, hitting the `# pragma: no cover - defensive, DB guarantees a row` branch — which is reachable, not purely defensive. → **patch**.
- **Terminal-state values are duplicated in `workflow/run_states.py::TERMINAL_RUN_STATES` and the literal `deploy/migrations/0005_history.sql` CHECK, with no parity test** (blind-hunter, verification-gap "Other findings") — `medium`. Verified: no test compares the two lists, unlike `tests/workflow/test_triage_run_migration.py`'s existing parity test for `triage_run`'s state CHECK — an established repo convention this story didn't follow. → **patch** (add the missing parity test, same pattern).
- **`pr_feedback` has no RT-03-equivalent tenant-isolation test** (blind-hunter) — `medium`. Verified: `history` gets `test_ac3_rt03_foreign_repo_lookup_rejected`/`_returns_nothing`; `pr_feedback_store.py`'s docstring claims the same AD-15 repo-scoping guarantee but no test exercises `list_for_run` across two repos. → **patch** (add the missing test).
- **`PRFeedbackConnection`/`PRFeedbackCursor`/`_open_connection` duplicate `HistoryConnection`/`HistoryCursor`/`_open_connection` almost verbatim** (blind-hunter, clean-code) — `medium`. Verified byte-for-byte identical shapes; this is the third near-identical occurrence of this Protocol pattern in `workflow/` (after `StepConnection` in `step_store.py`), which is exactly AGENTS.md's DRY "rule of three: extract on the third." → **patch** (extract one shared `Connection`/`Cursor` Protocol + `_open_connection` helper; keep `HistoryStore`/`PRFeedbackStore` domain Protocols separate).
- **Bare `RuntimeError` instead of a typed, `retryable`-carrying exception on two defensive branches** (clean-code) — `low`. Verified: `history_store.py:169` and `pr_feedback_store.py:105` both raise plain `RuntimeError`, unlike every other typed exception in `workflow/` (AD-22 convention). Fix is a direct swap, not a new abstraction. → **patch**.
- **`PRFeedbackStore` Protocol has exactly one implementation and no test fake exercising it** (clean-code) — `low`. Verified: `grep` shows it used only in its own definition and `__all__`; unlike `HistoryStore` (faked in `tests/scripts/test_history_import.py`, consumed as `Callable[[], HistoryStore]`), nothing swaps a fake in for it. AGENTS.md: "no abstraction with one implementation unless a test fake needs it." Fix is a direct deletion. → **patch**.
- **Two tests don't follow the `test_ac<N>_*` naming convention** (blind-hunter, clean-code) — `low`. Verified: `test_human_verdict_absent_is_null` and `test_import_seed_generates_a_fresh_run_id_per_record` in `test_history.py`, and `test_0005_0006_migrations_apply_and_pr_feedback_fk_enforced` in `test_history_integration.py`, don't cite an AC, unlike every sibling test in the same files. Fix is a direct rename. → **patch**.
- **`build_records` silently coerces an empty-string `human_verdict` to `None`** (edge-case-hunter) — `low`. Verified: `HumanVerdict(verdict) if verdict else None` uses a truthiness check, so `""` (present but falsy) is swallowed instead of rejected; a garbage non-empty string still raises correctly. Fix is a one-line `is not None` swap. → **patch**.
- **`write_terminal`'s duplicate path doesn't compare the new payload against the existing row before returning it** (blind-hunter, edge-case-hunter) — `low`. Real: a second call with different `test_id`/`error_type`/`human_verdict` for the same `run_id` silently returns the stale first row with no signal. Not required by AC2 (which only asks for exactly-one-row idempotency, not payload-equality checking), no live caller exists yet in this story (2.8 wires the real finalize call), and the fix needs new comparison/mismatch-handling logic, not a direct correction. → **reject** (low + fix is more than trivial).
- **No content-level validation stops a long/narrative string inside `test_id`, `error_type`, or a `top_stack_frames` element** (blind-hunter) — `low`. Real in principle, but AD-15's "structured-only, no free text" requirement is about column shape (no notes/comment column), which the schema satisfies; the spec's Design Notes scoped "structured" to the column definitions, not per-value content policing. Fix would require inventing new, currently-undefined validation rules — more than a trivial correction, and not needed in everyday use (these fields are populated by internal callers, not raw user input). → **reject** (low + fix is more than trivial).
- **`new_run_id()` is reused to mint `history.row_id`, and its name ("run" id) no longer matches the call site** (blind-hunter, clean-code) — cosmetic. Verified, but this is the exact reuse the spec's Design Notes explicitly call out and justify (DRY, same UUIDv7 scheme). `new_run_id` is also used elsewhere in `workflow/` (e.g. `step_store.py`), so a rename has a wider blast radius than this story's scope. → **reject** (cosmetic; re-litigates an already-approved spec decision).
- **`sprint-status.yaml` still shows `in-progress`, not `in-review`** (blind-hunter) — checked: this is the correct, expected state at this exact point in the workflow (status advances after review triage, not before). → **false**.

## Design Notes

- **Why no lease/`Claim` on the write:** `CLAIMABLE_RUN_STATES` (workflow/leases.py) already excludes `TERMINAL_RUN_STATES`, so by the time a run is terminal no worker can hold or contest its lease. The `step_store.py` guarded-transaction pattern exists to keep a step write and a state *move* atomic under contention; a terminal history write has no competing writer to guard against, so the DB unique constraint on `run_id` alone gives AC2's idempotency without inventing new dedupe logic or requiring a `Claim`.
- **Why seed rows synthesize their own `run_id`:** seed/backfilled history has no real `triage_run` behind it. Rather than making `history.run_id` nullable (special-casing every query) or forcing the importer to fabricate an ID, `import_seed` calls `workflow.ids.new_run_id()` once per record — same UUIDv7 scheme already used for real runs, so the column stays `NOT NULL` and uniform for both writers.
- **Why `top_stack_frames` is `text[]`, not jsonb/free text:** AD-15 requires "structured-only, enumerated fields." An ordered array of short frame strings is structured (each element is a citable location string, not narrative); this is the "top stack frames (or their normalized form)" the story asks for, consistent with 2.5's distiller keeping only stack traces, never narrative.

## Verification

**Commands:**
- `.venv/bin/pytest tests/workflow/test_history.py tests/scripts/test_history_import.py -q` -- expected: all AC1/AC2/AC3 unit tests pass.
- `.venv/bin/pytest -m integration tests/workflow/test_history_integration.py -q` -- expected: all RT-03/RT-04 + migration integration tests pass (needs Docker).
- `make check` -- expected: green, including ≥85% coverage on `contracts/`, `guardrails/`, `workflow/`.
