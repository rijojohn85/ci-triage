deploy/ — local runtime foundation (story 0.3+; epics 0.3).

| Path | Contents |
| --- | --- |
| `compose.yaml` | postgres:18 + one-shot migrate job + the real gateway (story 1.1) + agent/orchestrator placeholders with AD-16 secret placement |
| `migrate.Dockerfile` | image for the one-shot migration job: pinned `psycopg[binary]==3.3.6` + `workflow.migrate` runner |
| `gateway.Dockerfile` | gateway intake image (story 1.1, AD-17): pinned starlette/uvicorn/psycopg + `gateway` app |
| `migrations/` | forward-only `.sql` files, applied in filename order (see `migrations/README.md`) |
| `k8s/` | cluster manifests — later story, same images (AD-25) |
| `smoke/` | gitignored receipts from `scripts/smoke_signed_tunnel.py` (story 1.3) — never contains secrets |

Run from the repo root:

- start: `docker compose --project-directory . -f deploy/compose.yaml up -d --wait`
- apply migrations again after adding files: `docker compose --project-directory . -f deploy/compose.yaml run --rm migrate`
- stop and drop data: `docker compose --project-directory . -f deploy/compose.yaml down -v`

The gateway listens on `127.0.0.1:${GATEWAY_HOST_PORT:-8080}` and exposes
`POST /webhook`. Secrets come from `.env` (names documented in `.env.example`);
compose holds interpolations only. Scope per AD-16 is enforced by
`tests/security/test_compose_secret_placement.py`.
