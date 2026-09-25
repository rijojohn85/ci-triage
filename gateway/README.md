gateway/ — GitHub webhook gateway (story 1.1). Transport only: it checks the
request really came from GitHub, rejects unknown installations, collapses
replays and duplicate runs, sheds bursts, and writes one `triage_run(RECEIVED)`.
It never calls an LLM or GitHub and holds no state-machine logic (AD-17).

| File | What it does |
| --- | --- |
| `signature.py` | constant-time check of `X-Hub-Signature-256` over the raw body; accepts a tuple of secrets (rotation, AD-25) |
| `events.py` | the accepted-event registry (`workflow_run` completed/failure only) and the run identity (repo / run / attempt) |
| `limits.py` | per-installation rate limiter (injected clock) and the per-repo queue-depth test |
| `settings.py` | reads secrets/DSN from env (AD-16 names) and limits from `config/gateway.yaml` (AD-19) |
| `store.py` | `IntakeStore` protocol + Postgres adapter: delivery dedupe then idempotent `triage_run` insert in one transaction |
| `app.py` | the Starlette app: signature → installation → event → limits → enqueue |
| `__main__.py` | loads env + store and serves with uvicorn |

Run locally: `python -m gateway` (needs `DATABASE_URL`,
`GITHUB_WEBHOOK_SECRET`, `GITHUB_APP_INSTALLATION_ID`). Unit tests are
`tests/security/test_gateway_signature.py`, `test_gateway_intake.py`,
`test_gateway_limits.py`; the Postgres path is `test_gateway_store_integration.py`
(marked integration, needs Docker).
