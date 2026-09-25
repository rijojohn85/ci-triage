- source_spec: `_bmad-output/implementation-artifacts/spec-2-2-compute-immutable-jev-confidence-and-cited-caps.md`
  summary: Map an SDK Choice/probability label outside the 5 classes to a typed non-retryable AD-22 agent error at the Jev agent edge.
  evidence: `JevChoice.from_sdk` raises a bare ValueError for e.g. "timeout"; loud but untyped. Belongs to the E3 Jev agent that calls the SDK.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-verify-signed-tunnel-delivery-and-secret-rotation.md`
  summary: `scripts/smoke_signed_tunnel.py`'s "exactly one delivery" poll matches only on `repo_id` + `received_at > since`, so unrelated webhook traffic to the demo repo inside the poll window (a manual Redeliver, a stray retrigger, an overlapping smoke run) is indistinguishable from the triggered delivery.
  evidence: `_POLL_SQL` has no filter on the specific `workflow_run_id` the script itself triggered via `gh workflow run`. A correct fix means resolving that run id (e.g. via `gh run list`) and filtering by it — real but non-trivial; the demo repo is a private single-purpose synthetic repo (AD-25) with no other expected traffic, so the practical likelihood today is low.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-3-verify-signed-tunnel-delivery-and-secret-rotation.md`
  summary: `scripts/smoke_signed_tunnel.py`'s `_POLL_SQL` query text is never executed by any test that runs under `make check` — both poll unit tests stub `psycopg.connect` with a fake cursor whose `execute()` discards the SQL text entirely.
  evidence: Filed by the review's verification-gap layer. Only `@pytest.mark.integration::test_ac1_live_smoke_run_enqueues_exactly_one_triage_run` runs the real query, and `pyproject.toml`'s `addopts = "-m 'not integration'"` excludes it from `make check`, so a schema-drift or join typo in the query would ship green. The repo already accepts this same tradeoff for other Postgres-touching code (e.g. `tests/security/test_gateway_store_integration.py`); closing it needs a schema-aware fixture beyond this story's scope.
