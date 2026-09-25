# Demo repository record — story 0.4 (AC3)

The real synthetic demo repository used by permission and workflow tests
(CAP-1…CAP-6). Every value below came from a command run during story 0.4;
scenario slots S1–S5 are explicit PENDING entries filled later by the
scenario drivers (stories 6.6–6.8). No fabricated receipts.

Created 2026-09-25. Binding: AD-16 (least privilege / secret placement),
AD-3 (idempotent writes), AD-17 (ingress), AD-25 (smee + synthetic repo
only), AD-14 (CODEOWNERS authority).

## Repository

| Fact | Value |
| --- | --- |
| URL | https://github.com/rijojohn85-dev/triage-demo-py |
| Full name | `rijojohn85-dev/triage-demo-py` |
| Repo ID | `1387450356` |
| Visibility | public |
| Default branch | `main` |
| Owner org | `rijojohn85-dev` (org ID `333783852`, free plan) |
| Clone URL | `git@github.com:rijojohn85-dev/triage-demo-py.git` |

## GitHub App + installation (AC1)

| Fact | Value |
| --- | --- |
| App name / slug | `ci-triage-rijojohn85-dev` |
| App ID | `5073639` (public, not a secret) |
| App owner | `rijojohn85` (personal account; installed "Any account") |
| Installation ID | `164804973` |
| Installation created | `2026-09-25T18:05:45.000+05:30` |
| Repository selection | `selected` — demo repo only |

**Read back from GitHub** (`GET /orgs/rijojohn85-dev/installations`,
app_id filtered — command in "Read-back" below). Granted permissions,
exactly the AD-16 requested set:

`actions:read, checks:read, contents:write, pull_requests:write, issues:write` (repository) + `members:read` (organization)

- **Platform-implied by GitHub, never requested:** `metadata:read`,
  `statuses:write`. Distinguished from requested permissions in every
  read-back output. `sys.argv`-style grants like `workflows` are forbidden
  by AD-16 and verified absent (`workflows` permission must never appear).
- **Subscribed events:** `issue_comment`, `workflow_run` (exact match).
- **Webhook:** proxied in dev through smee channel
  https://smee.io/R53e2D7yfSg3sBV (URL is not a secret; the webhook secret
  that protects deliveries lives only in `.env` as `GITHUB_WEBHOOK_SECRET`).

Secrets (`GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID`,
`GITHUB_APP_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET`) live only in `.env`,
never in chat/repo/logs (AD-16). Names already enumerated in
`.env.example`.

## Protection (AC2)

Ruleset created via the Rulesets REST API (NOT legacy branch protection),
ID **`23997553`**, name `protect-default-branch`:
- `enforcement: active`, targets `~DEFAULT_BRANCH`
- `pull_request` rule: `required_approving_review_count: 1`,
  `require_code_owner_review: true`, `dismiss_stale_reviews_on_push: true`,
  `require_last_push_approval: false`, all merge methods allowed
- `non_fast_forward` (force-push blocked), `deletion` (deletion blocked)
- `bypass_actors: []` — the App is never a bypass actor

CODEOWNERS at the repo root (blob sha
`c9e9d116051d0411c20ef41d3aa6fd0143d9cc0c` on `main`):

```
* @rijojohn85
```

Applicable fallback `*` rule naming the fixture owner `@rijojohn85`; the
punch-out CLI (AD-14) resolves CODEOWNERS only from the protected
default-branch tip.

**Implementation restriction (not GitHub-enforced):** triage writes are
restricted in code to `refs/heads/triage/*` and draft PRs. This is
enforced by the E4 GitHub adapter (AD-3: `run_id + step` keyed writes,
check-before-create, `triage/<run_id>` branch; AD-16: contents:write used
only for `refs/heads/triage/*`), not by GitHub itself — the ruleset only
guarantees the default branch needs human review and that the App cannot
bypass it.

## Baseline snapshot (AC3, CAP-6 anchor)

| Fact | Value |
| --- | --- |
| Baseline commit | `fe2a35d0ec762e899b3e94b0bc2b38bb3aac8277` |
| Commit message / author | `baseline: synthetic demo package with green CI seed (story 0.4)` — Rijo John, 2026-09-25T12:52:28Z |
| Annotated tag | `baseline-v1` (tag object sha `50f80598ff23713547c3356e9cf15828979b5930`) |
| CI workflow | `ci.yml` (workflow ID `366957769`), runs on push + pull_request to `main` |
| Baseline CI run | `36137502078` — success, event `push`, 12 s |
| Seed source of truth | `test-data/demo-repo-seed/` in this repo |

The baseline is the `last_green` anchor (AD-24) and the starting point the
S1–S5 drivers break on purpose.

## Scenario slots (S1–S5)

Fill these from real runs only (stories 6.6–6.8); leave PENDING otherwise.

| Slot | Scenario | Seed / head SHA | CI run ID | Output ref | Status |
| --- | --- | --- | --- | --- | --- |
| S1 | code bug, two suspects, rank-1 culprit | PENDING | PENDING | draft PR | PENDING |
| S2 | seeded flaky test, root-cause deflake | PENDING | PENDING | draft PR + quarantine label | PENDING |
| S3 | infra OOM | PENDING | PENDING | issue `ci-triage/infra` | PENDING |
| S4 | external API failure, mock/contract | PENDING | PENDING | draft PR | PENDING |
| S5 | high-risk fix (timeout bump) | PENDING | PENDING | `input_required` + approve/reject | PENDING |

## Read-back (AC4)

```bash
.venv/bin/python scripts/verify_demo_repo.py \
  --org rijojohn85-dev --repo triage-demo-py \
  --app-id 5073639 --installation-id 164804973 \
  --ruleset-id 23997553 --tag baseline-v1
# → VERIFY PASS: demo repository matches AD-16 + AC2 expectations (exit 0)
```

The script reads the expected set from the single source
`test-data/demo-repo-expected.json` and exits non-zero on any deviation.
It uses the human's own gh auth; no App key needed; no secrets printed.

## Recreate from scratch

1. Create the free org `rijojohn85-dev` → in https://github.com/organizations/new
   (if it no longer exists; record the new org ID in the table above).
2. **Create repository** `triage-demo-py`, public, empty (no README/license).
3. Push the seed verbatim from this repo (source of truth
   `test-data/demo-repo-seed/`):
   ```bash
   rm -rf /tmp/opencode/demo-push && mkdir -p /tmp/opencode/demo-push
   git init /tmp/opencode/demo-push/repo -q
   cp -a test-data/demo-repo-seed/. /tmp/opencode/demo-push/repo/
   cd /tmp/opencode/demo-push/repo
   git remote add origin git@github.com:rijojohn85-dev/triage-demo-py.git
   git add -A && git commit -m "baseline: synthetic demo package with green CI seed (story 0.4)"
   git push -u origin main
   ```
4. Wait for the `ci` workflow run to complete successfully; note its run ID
   and annotate the *same* head commit:
   ```bash
   git tag -a baseline-v1 -m "Green pre-scenario baseline; CI run <RUN_ID> green"
   git push origin baseline-v1
   ```
5. Create the ruleset via the Rulesets REST API (bypass_actors empty):
   ```bash
   gh api -X POST /repos/rijojohn85-dev/triage-demo-py/rulesets \
     --input scripts/ruleset-seed.json
   ```
   (see `scripts/ruleset-seed.json` — same payload used for ruleset 23997553).
6. Register + install the GitHub App exactly as recorded in
   `docs/USER-GUIDE.md` ("Install the GitHub App on a repository"),
   including the "Only select repositories" scope and the webhook secret
   (a *new* secret for the new install; never reuse or copy values).
7. Run the read-back from `scripts/verify_demo_repo.py`; it must end
   `VERIFY PASS` before this slot is released for S1–S5.
