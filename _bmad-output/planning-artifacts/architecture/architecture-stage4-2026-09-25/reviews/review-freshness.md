# Freshness review — ARCHITECTURE-SPINE.md (Blameless CI Triage, Stage 4)

- **Date:** 2026-09-25
- **Scope:** Technology decisions in the spine that `.memlog.md` did not already verify. The spine was not edited.
- **Already verified (memlog, not re-checked):** PyPI versions (a2a-sdk 1.1.5, typesafe-sdk 0.7.1, pydantic 2.13.5, psycopg 3.3.6, anthropic 1.8.0), promptfoo npm 0.123.1, PostgreSQL 18 (endoflife.date), a2a-sdk Client surface (context7), typesafe-sdk Choice/confidence (docs.typesafe.ai).
- **Method:** context7 first (`/a2aproject/a2a`, `/a2aproject/a2a-python`, `/websites/a2a-protocol_sdk_python_api`, `/anthropics/anthropic-sdk-python`, `/github/docs`), then the web (platform.claude.com, docs.github.com, smee.io). The a2a-sdk 1.1.5 and typesafe-sdk 0.7.1 wheels from PyPI were also checked for the exact behaviour.

## Verdict

**PASS WITH FIXES.** One HIGH finding blocks the build: the GitHub App scopes cannot open the draft PRs the spine promises. Three MEDIUM findings are gaps in how A2A and the cost numbers work. Every other claim checked out.

## Findings

### F1 — HIGH — `contents:read` cannot create the branch that a draft PR needs (AD-16 contradicts AD-14 and the idempotency decision)
- **Evidence:** A GitHub App needs **Contents: write** for each of these: `POST /repos/{o}/{r}/git/refs` (create a branch), `POST .../git/blobs|trees|commits`, `PUT .../contents/{path}`, and git push over HTTPS. `POST /repos/{o}/{r}/pulls` needs **Pull requests: write**, and its `head` branch must already exist. Branch `triage/<run_id>` therefore cannot be created with `contents:read`. Also note that `PUT .../pulls/{n}/merge` needs only **Contents: write**. Once the App holds that permission it *can* merge, so "never auto-merge" can no longer rely on scopes alone.
- **Source:** context7 `/github/docs` (repos.json progAccess, the PAT permission examples, pulls.json merge) and web docs.github.com/en/rest/authentication/permissions-required-for-github-apps.
- **Fix:** Change AD-16 to `contents:write`. Add compensating controls: a repo ruleset or branch protection on the default branch that requires a human review and blocks the App from pushing or merging there, and an App push allowlist limited to `triage/*`. Never request `workflows:write`; the risk gate already blocks CI config changes, and GitHub rejects workflow-file edits without that permission, which adds a second layer of defence. Add the wider scope to the red-team plan, as the memlog already does for `members:read`.

### F2 — MEDIUM — "A2A `task_id` = `run_id`" works only if the orchestrator seeds a durable TaskStore
- **Evidence:** The A2A spec says: "Task IDs are **server-generated**… Client-provided `taskId` values for creating new tasks is **NOT** supported… Agents MUST return TaskNotFoundError if the provided taskId does not correspond to an existing task." In a2a-sdk 1.1.5, `DefaultRequestHandlerV2._setup_active_task` calls `task_store.get(task_id)` and raises `TaskNotFoundError` when the task is missing. A run starts from a webhook, not from a `SendMessage`, so no A2A task exists until the orchestrator writes one. An `InMemoryTaskStore` also loses it on restart, so `triage approve <task_id>` would fail after the orchestrator restarts. Tasks created on the spoke side get IDs that the spoke generates, so those IDs cannot equal `run_id`.
- **Confirmed OK:** Resuming an `INPUT_REQUIRED` task with `send_message` on the same `taskId` is supported: the spec (§3.4.3) says "client continues… with the same taskId and contextId". The SDK rejects messages to terminal tasks (`active_task.py`: "Task … is in terminal state"). `INPUT_REQUIRED` is an interrupted state, not a terminal one.
- **Source:** context7 `/a2aproject/a2a` (specification §3.4.2 and §3.4.3, a2a.proto TaskState) and the a2a-sdk 1.1.5 wheel source.
- **Fix:** In AD-4/Conventions, state that the orchestrator mints the A2A task with `id = run_id` when a run enters `RECEIVED`. Its TaskStore should be either (a) a custom `TaskStore` that reads the projection from `triage_run`, which fits the "one owner" rule best, or (b) `DatabaseTaskStore`. Option (b) needs the `postgresql` extra, and the Stack row lists only `http-server`. For spoke calls, carry `run_id` in `contextId` or message metadata. Do not use it as the spoke's `taskId`.

### F3 — MEDIUM — `securitySchemes` only declares auth; the SDK does not validate the bearer token
- **Evidence:** a2a-sdk 1.1.5 has `AgentCard.security_schemes` and `security_requirements`, and `SecurityScheme` includes `http_auth_security_scheme` (`scheme: "bearer"`). In v1.0 JSON this is `"securitySchemes": {"github": {"httpAuthSecurityScheme": {"scheme": "bearer"}}}` plus `"securityRequirements"`. The v0.3 field `security` was renamed. `ServerCallContext.user` is filled by `DefaultServerCallContextBuilder` from Starlette's `request.scope['user']`. Otherwise it is `UnauthenticatedUser`, and the raw headers go to `state['headers']`. The executor reads it as `RequestContext.call_context.user`. The SDK ships no middleware that verifies tokens.
- **Confirmed OK:** Well-known path `/.well-known/agent-card.json` (constant `AGENT_CARD_WELL_KNOWN_PATH`). `AgentSkill` fields `id, name, description, tags, examples, input_modes, output_modes, security_requirements`, so AD-10 routing on id, tags and description is valid.
- **Source:** context7 `/a2aproject/a2a-python` (context.py, routes/common.py, auth/user.py), `/a2aproject/a2a` (spec, agent-discovery), and the a2a-sdk 1.1.5 `a2a_pb2.pyi` and `constants.py`.
- **Fix:** Add to AD-14: the orchestrator mounts a Starlette `AuthenticationMiddleware`, or a custom `ServerCallContextBuilder`. It validates the GitHub token with `GET /user` and sets the user's login. The executor rejects `UnauthenticatedUser` before the CODEOWNERS check. Only the spokes' cards may omit auth. Make the executor's check mandatory, because the card declaration alone enforces nothing.

### F4 — MEDIUM — Cost formula must price four token buckets; verified Claude prices
- **Evidence:** In `usage`, `input_tokens` counts **only the uncached remainder**. Total prompt = `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`. Cache writes are priced by TTL: 1.25x for 5m and 2x for 1h. The split is in `usage.cache_creation.ephemeral_5m_input_tokens` and `ephemeral_1h_input_tokens`. On streaming `message_delta`, the input and cache fields are Optional and cumulative.
- **Official prices** (web: https://platform.claude.com/docs/en/about-claude/pricing, retrieved 2026-09-25), USD per million tokens:

| Model | Base input | 5m cache write | 1h cache write | Cache hit | Output | Batch in/out |
|---|---|---|---|---|---|---|
| Claude Sonnet 5 (`claude-sonnet-5`) | $2 | $2.50 | $4 | $0.20 | $10 | $1 / $5 |
| Claude Haiku 4.5 (`claude-haiku-4-5-20251001`) | $1 | $1.25 | $2 | $0.10 | $5 | $0.50 / $2.50 |

  Sonnet 5 footnote: the $2/$10 launch price "is now the standard price. The previously scheduled increase to $3/$15… on September 1, 2026 will not occur." Both models get the full 1M/200K context at standard rates (no long-context premium). `inference_geo: "us"` multiplies all rates by 1.1x on 4.6-and-later models. That covers Sonnet 5, and does **not** cover Haiku 4.5, which returns 400 if the parameter is sent.
- **Source:** web (platform.claude.com pricing) and context7 `/anthropics/anthropic-sdk-python` (Usage, CacheCreation, MessageDeltaUsage).
- **Fix:** Give `monitoring/prices.yaml` these five rates per model plus `source_url` and `retrieved`. `run_step` stores all four token counts plus the 5m/1h split. Cost = Σ(bucket × rate).

### F5 — LOW — Model IDs exist; Haiku 4.5 retirement floor is close
- **Evidence:** The Models overview lists `claude-sonnet-5` (Active, retirement not before 2027-06-30) and `claude-haiku-4-5-20251001` (Active, alias `claude-haiku-4-5`, retirement **not before 2026-10-15**, 20 days from today). There is no deprecation notice yet, and Anthropic guarantees at least 60 days' notice. Behaviour differences: Haiku 4.5 uses extended thinking (`budget_tokens`) and does not support `effort`. Sonnet 5 rejects `budget_tokens` and non-default sampling. The anthropic Python SDK 1.x has removed `temperature/top_p/top_k` (passing them raises `TypeError`).
- **Source:** web (platform.claude.com models/overview.md, model-deprecations.md).
- **Fix:** No change to the IDs. Keep model IDs in config (already decided). Don't rely on `temperature=0` for reproducibility; seeded scenarios already handle that. Check the deprecations page at build time.

### F6 — LOW — Jev usage may be null; Jev price is unverified
- **Evidence:** In typesafe-sdk 0.7.1, `Usage.input_tokens` and `Usage.output_tokens` are `int | None` ("None when the API did not report it"). The response carries `usage` and `model`. No Jev price was found or verified.
- **Source:** PyPI wheel source (`_core/response_types.py`). The Jev price is not in context7 or the memlog.
- **Fix:** Add a Jev row with a source to `prices.yaml`, or mark it `unpriced`. Store NULL, not 0, for tokens that were not reported, and flag the cost as incomplete in `results/`.

### F7 — LOW — `members:read` confirmed; PR-comment permission needs a build-time check
- **Evidence:** `GET /orgs/{org}/teams/{team_slug}/memberships/{username}` and `.../members` need **Members: read**, which confirms the spine. Reading CODEOWNERS and `codeowners/errors` needs Contents: read, which `contents:write` also covers. Comments go through the Issues comments API. The docs list Issues: write for `POST .../issues/{n}/comments`, with alternative permissions, and it was not confirmed whether `pull_requests:write` counts as one. The `issue_comment` webhook, used by the SHOULD `/triage` command, also depends on the Issues/PR permission.
- **Source:** web docs.github.com (permissions-required-for-github-apps) and context7 `/github/docs`.
- **Fix:** At App registration, test posting a PR comment with the chosen scopes. If it fails, add `issues:write` and record it in the red-team plan.

### F8 — LOW — smee.io is operational (dev only)
- **Evidence:** On 2026-09-25, `https://smee.io/` returned HTTP 200 and `/new` returned 307 to a fresh channel. `smee-client` npm is at 5.0.0. GitHub docs still recommend smee for local App development (`smee --url … --path … --port …`). GitHub requires a 2xx response within 10 seconds; AD-17's 202 meets that.
- **Source:** web (live probe, npm registry) and context7 `/github/docs` (testing-webhooks, App quickstart).
- **Fix:** No change. Add an E2E smoke step that confirms `X-Hub-Signature-256` still verifies on the body forwarded through smee (the gateway verifies over raw bytes). Note that webhook payloads pass through a third party, so use only the synthetic demo repo.

## Claims confirmed without findings
- A2A well-known card path, AgentSkill fields, `securitySchemes`/HTTP bearer support, and INPUT_REQUIRED resume on the same `taskId` (see F2 and F3).
- `ServerCallContext` exposes the caller (`user`, `state['auth']`, `state['headers']`) to the executor through `RequestContext.call_context`, provided middleware sets it (F3).
- Both model IDs are live; the usage field names are exactly `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`.
