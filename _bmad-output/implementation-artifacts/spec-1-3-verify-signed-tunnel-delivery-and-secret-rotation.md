---
title: 'Verify signed tunnel delivery and secret rotation'
type: 'feature'
created: '2026-09-26'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '6c2ba22e0037957274d730ebaef166e755266634'
context: ['{project-root}/AGENTS.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Story 1.1 proved rotation and signature checks as pure/unit behaviour, but nothing yet proves the whole rotation lifecycle end to end, or that a real signed delivery through the smee tunnel actually reaches the gateway and enqueues exactly once (AD-17, AD-25).

**Approach:** Add one unit test that drives the full rotation lifecycle (old-only → overlap → retired) through the public gateway app with fakes, and one repeatable smoke script that triggers a real signed `workflow_run` failure from the demo repo through Compose + smee, confirms a single enqueued `triage_run` with its delivery ID recorded, and writes a secret-free receipt. Document the rotation procedure.

## Boundaries & Constraints

**Always:** Secrets never appear in the receipt or any committed file (AD-16). Rotation is exercised purely through `GatewaySettings.webhook_secrets` tuples — no change to `signature.py`'s already-rotation-safe contract. The smoke script reads `.env` values itself; no secret is ever passed as a CLI arg or printed. "Retire" is a config change (drop the old secret from `GITHUB_WEBHOOK_SECRET`) plus a gateway restart — no code path exists for it.

**Never:** Do not add an admin/API endpoint for rotation. Do not touch `gateway/signature.py` or `gateway/settings.py` (already correct per 1.1). Do not make the smoke script part of `make check`'s default unit run — its live half is `@pytest.mark.integration` only.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Old-only phase | app configured with `(old,)` | old signature → 202; new signature → 401 | N/A |
| Overlap phase | app configured with `(old, new)` | both signatures → 202; wrong secret → 401 | N/A |
| Retired phase | app configured with `(new,)` | old signature → 401; new signature → 202 | N/A |
| Smoke receipt write | run status + run reference | receipt file written | test asserts no secret substring present |

</frozen-after-approval>

## Code Map

- `tests/security/test_gateway_signature.py` -- add `TestRotationLifecycle.test_ac2_rotation_lifecycle_old_overlap_retired`; build 3 `create_app` instances directly (own `GatewaySettings`) instead of the shared `client`/`settings` fixtures, since the secret tuple must vary per phase. Reuse `fake_store`, `limits`, `clock` fixtures and `sign`/`workflow_run_payload` from `gateway_fakes.py`.
- `gateway/app.py`, `gateway/settings.py`, `gateway/signature.py`, `gateway/store.py` -- read-only reference; rotation already works via `_split_secrets` + `verify_signature`'s secret tuple. No changes.
- `scripts/verify_demo_repo.py` -- pattern to follow for a new one-shot script: stdlib argparse, `gh api` via subprocess for GitHub-side actions, no App key.
- `test-data/demo-repo.md` -- demo repo facts: smee channel `https://smee.io/R53e2D7yfSg3sBV` (non-secret), repo `rijojohn85-dev/triage-demo-py`, workflow `ci.yml`.
- `.env.example` -- `DATABASE_URL`, `GITHUB_WEBHOOK_SECRET` names already present; no new var needed.
- **New:** `scripts/smoke_signed_tunnel.py` -- triggers a real failing run in the demo repo (`gh workflow run` / re-run with a failing ref, or re-run an existing failing run), polls Postgres (`webhook_delivery`, `triage_run`) via `DATABASE_URL` for exactly one matching row, and writes the receipt. Split into a pure `build_receipt(status, run_id, delivery_id) -> dict` (unit-testable, asserted secret-free) and an I/O `main()` (integration-only).
- **New:** `deploy/smoke/` -- gitignored receipt output dir with a committed `README.md`, mirroring the `runs/`/`results/` convention (AD-18 reserves `runs/`/`results/` for DB-table exports only, so the receipt — a script artifact, not a DB export — gets its own dir under `deploy/`, which AD-25 already binds).
- **New:** `tests/scripts/test_smoke_signed_tunnel.py` -- unit tests `build_receipt` (no secret substrings, correct fields) and, `@pytest.mark.integration`, the live end-to-end path.
- `docs/USER-GUIDE.md` -- add a "Rotating the webhook secret" procedure after the App-install section.
- `docs/DEVELOPER.md` -- new "Signed tunnel smoke test (story 1.3)" section noting script + receipt location.
- `.gitignore` -- add `deploy/smoke/*` / `!deploy/smoke/README.md`.

## Tasks & Acceptance

**Execution:**
- [x] `tests/security/test_gateway_signature.py` -- write failing `test_ac2_rotation_lifecycle_old_overlap_retired` first (red), then confirm it passes unmodified against existing `signature.py`/`settings.py` (green) -- proves AC2 with no production code change
- [x] `scripts/smoke_signed_tunnel.py` -- add `build_receipt()` pure function + `main()` CLI (compose-up assumed already running per USER-GUIDE step)
- [x] `deploy/smoke/README.md` -- document the dir's purpose (mirrors `runs/README.md` wording)
- [x] `.gitignore` -- ignore `deploy/smoke/*` except its README
- [x] `tests/scripts/test_smoke_signed_tunnel.py` -- red-green for `build_receipt` secret-free assertion; `@pytest.mark.integration` test for the full smoke run
- [x] `docs/USER-GUIDE.md` -- rotation procedure (add secret to `.env`, restart, verify overlap, remove old secret, restart)
- [x] `docs/DEVELOPER.md` -- smoke script/receipt location note

**Acceptance Criteria:**
- Given Compose + smee tunnel running and a real signed `workflow_run` failure delivered from the demo repo, when the smoke script runs, then exactly one `triage_run` is enqueued with its `X-GitHub-Delivery` ID recorded in `webhook_delivery`, and the written receipt contains status + run reference with no secret value (AC1)
- Given the rotation lifecycle test, when secrets move old-only → overlap → retired, then old and new are both accepted only during overlap, an invalid signature always gets 401, and after retirement only the new secret is accepted (AC2)

## Implementation Notes

## Spec Change Log

## Review Triage Log

- **`main()` narrow exception handling leaks secrets on crash** — `scripts/smoke_signed_tunnel.py:169-180`. Verdict: `high`. Evidence: `except SmokeError` is the only handler; `psycopg.connect(dsn)` (line 131, called from `poll_for_single_delivery`) can raise `psycopg.OperationalError`, whose message commonly echoes the DSN including the password from `.env`, and `gh()`'s `subprocess.run` has no guard for `gh` missing from `PATH` (`FileNotFoundError`) — both propagate uncaught, crashing with a raw traceback and no receipt written, contradicting the module's own AD-16 claim ("never printed"). Route: `patch`.
- **`gh()` has no subprocess timeout** — `scripts/smoke_signed_tunnel.py:90-96`. Verdict: `medium`. Evidence: `subprocess.run` passes no `timeout=`; a stalled `gh` (auth prompt, network stall) blocks the script indefinitely — `--timeout-seconds` only bounds the DB poll loop. Route: `patch`.
- **`write_receipt` filename collision at 1s resolution** — `scripts/smoke_signed_tunnel.py:143-147`. Verdict: `low` (kept: fix is trivial, not rejected). Evidence: `receipt-{int(time.time())}.json` — two runs within the same second overwrite each other's receipt; no test exercises repeated calls. Route: `patch`.
- **Poll `since` uses host clock vs. DB server clock** — `scripts/smoke_signed_tunnel.py:124-140,171`. Verdict: `medium`. Evidence: `started_at = datetime.now(timezone.utc)` is captured on the script's host before `trigger_failing_run`; `wd.received_at > %s` compares against Postgres's own clock. Clock skew between hosts can exclude the very delivery being waited for, producing a false timeout on a correct run — exactly the false-negative a repeatable smoke check must avoid. Route: `patch`.
- **Poll match not scoped to the triggered run** — `scripts/smoke_signed_tunnel.py:112-140`. Verdict: `medium`. Evidence: `_POLL_SQL` filters only on `repo_id` + `received_at > since`; any other webhook traffic to the same demo repo inside the poll window (a manual GitHub Redeliver, a stray retrigger, an overlapping smoke run) is indistinguishable from the triggered delivery, so the "exactly one" check can false-match or false-raise on unrelated traffic. Real gap, but the demo repo is a private single-purpose synthetic repo (AD-25) with no other expected traffic in normal use, so likelihood is low and a correct fix (resolving the actual triggered `workflow_run_id` via `gh run list` and filtering by it) is materially more than the smallest change. Route: `defer`.
- **Docs imply the default command works against a green baseline** — `docs/DEVELOPER.md:148-151` (example command `--ref main`). Verdict: `medium`. Evidence: `test-data/demo-repo.md` records the baseline as the `last_green` anchor and scenario branches S1–S5 as `PENDING`; `ci.yml` runs only on push/PR to `main`. Following the documented example verbatim today dispatches a run that succeeds, so `poll_for_single_delivery` always times out — a developer sees "SMOKE FAIL: timed out" with no indication it's an environmental gap, not a regression. Route: `patch` (doc caveat + `--ref`/`--workflow` help text, not a design change).
- **No unit test for `gh()`/`trigger_failing_run()`, or for `main()`'s failure branch** — `tests/scripts/test_smoke_signed_tunnel.py`. Verdict: `medium`. Evidence: both functions are exercised only by the `@pytest.mark.integration` test, excluded from `make check`; the sibling script `scripts/verify_demo_repo.py` has repo precedent for mocking `subprocess.run` (`tests/scripts/test_verify_demo_repo.py`) that this story didn't follow. The exact code path most responsible for keeping a failure message secret-free (`main()`'s `except SmokeError` branch) is also untested outside the live path. Route: `patch`.
- **`_POLL_SQL`'s query text never runs under `make check`** — `scripts/smoke_signed_tunnel.py:112-121`, filed by the verification-gap layer (pre-verified per its evidence rules). Verdict: `medium` (gap real, disposition filed by the reviewing layer). Evidence: both mocked poll tests stub `psycopg.connect` with a `FakeCursor.execute` that discards its SQL argument entirely, so a schema-drift or join typo would ship green; only the integration-marked test runs the real query, and `addopts = "-m 'not integration'"` excludes it from `make check`. Route: `defer` (repo already accepts this tradeoff for other Postgres-touching code, e.g. `test_gateway_store_integration.py`; closing it needs a schema-aware fixture beyond this story's scope).
- **Receipt shape differs between PASS/FAIL (no schema field)** — `scripts/smoke_signed_tunnel.py:176-180`. Verdict: `low`, rejected. Evidence: `run_id`/`delivery_id` are `""` on failure with no distinguishing field, but the free-text `status` string already carries the specific reason ("FAIL: timed out...", "FAIL: expected exactly one..."); unlikely to be met in everyday (single-run, human-read) use, and a proper fix (schema/version field) is more than a direct correction. Rejected per the low-finding rule.
- **Demo-repo facts duplicated across 3+ literals** — `scripts/smoke_signed_tunnel.py:37-39`, `tests/scripts/test_smoke_signed_tunnel.py:171-173`, `docs/DEVELOPER.md:150`. Verdict: `low`, rejected. Evidence: org/repo/repo-id/workflow are independent literals instead of loading from `test-data/demo-repo.md`/a JSON companion as `verify_demo_repo.py` does for its *expected* values; developer-only, no functional risk since these are default/example values (not verification-critical), and the fix (CLI redesign or new JSON companion) is more than trivial for the benefit. Rejected per the low-finding rule.

## Verification

**Commands:**
- `.venv/bin/pytest tests/security/test_gateway_signature.py -k rotation_lifecycle -v` -- expected: AC2 test passes
- `.venv/bin/pytest tests/scripts/test_smoke_signed_tunnel.py -v -m "not integration"` -- expected: `build_receipt` unit tests pass, no live calls
- `.venv/bin/pytest tests/scripts/test_smoke_signed_tunnel.py -v -m integration` -- expected: live smoke run passes against a running Compose + smee tunnel + demo repo (human-run, needs `.env` populated and `docker compose ... up -d --wait`)
- `make check` -- expected: green (AGENTS.md quality gates)
