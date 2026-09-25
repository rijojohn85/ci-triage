tests/ — test suites. Named after the ACs they prove (AGENTS.md TDD rules).

- `tests/contracts/` — story 0.2 payload contracts + schema drift gate; story 2.2 adds `test_jev.py`.
- `tests/guardrails/` — story 2.2 pure domain predicates (`guardrails/confidence.py`); no I/O.
- `tests/workflow/` — story 0.3 migration runner (unit, fast; fakes the DB connection); story 2.1 the state machine; story 2.2 thresholds + attribution.
- `tests/security/` — compose secret-placement + no-speculative-schema gates (static; no Docker).
- `tests/fixtures/` — shared test-only config, e.g. `thresholds.test.yaml` (never the real `guardrails/thresholds.yaml`).

Integration tests (need Docker / real postgres:18, story 0.3+) are excluded
from the default `pytest`/`make check` run via the `integration` marker:

    .venv/bin/pytest -m integration -q     # or: make test-integration

They boot their own disposable `postgres:18` container and clean up after
themselves.
