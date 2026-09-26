# Jev eval data — labelled real CI failures (story 3.2)

This folder holds real, failed GitHub Actions job logs from public repositories,
each labelled with one of the four Jev classes and **proof** for that label.
It is the calibration data for the story 3.2 Jev classification eval
(`jev.test.yaml`); nothing here is synthetic and no model was used to label it.

| file | what it is |
| --- | --- |
| `manifest.yaml` | one entry per case: repo, class, evidence, run/job ids, the exact log line that proves the label |
| `logs/<id>.log` | the raw log of the one failing job (ANSI codes stripped, secrets scrubbed; last 1 MB kept when the original was larger) |

## Labelling rules (short form)

Rules are checked in this order and the **first** one that applies wins:
`external` → `infra` → `flaky` → `code`. If two classes fit, or none can be
proved, the run is skipped.

- **`external`** — the failing line is a request to a third-party host that
  failed (HTTP 429/5xx, DNS failure, TLS/connection timeout to a registry or
  package index, Docker Hub rate limit, remote test server). The host is named
  in `key_line`. `evidence_kind: third_party_request_failed`.
- **`infra`** — the log shows a runner/environment failure that is not the
  product: the runner never started the job (action download info unresolved),
  tool setup crashed, the artifact service rejected an upload, a service
  container never initialized, or the checkout's TLS trust store was missing.
  `evidence_kind: runner_or_setup_failure`.
- **`flaky`** — the same job failed on attempt 1 and passed on attempt 2 of the
  **same run** (same commit, no new commit), and the failing line is inside the
  project's own tests/build. `evidence_kind: rerun_passed_same_sha`.
- **`code`** — either a later commit on the same PR/branch changed source or
  test files and the same job then passed (`fixed_by_commit`), or a
  lint/typecheck/compile job failed on lines that PR changed
  (`failure_in_pr_diff`).

`unknown` is deliberately not collected here; it is built separately.

### GitHub-hosted services: how the boundary was drawn

For a project whose CI runs on GitHub Actions, GitHub's own platform services
are treated as **infra** when the *runner/setup* fails without naming a
third-party dependency (e.g. "Failed to resolve action download info",
artifact service 403), and as **external** when the failing line is a named-host
request that failed (e.g. `codeload.github.com` returning 429, `EAI_AGAIN` for
`api.github.com`, a 503 from `github.com` during checkout). Product
dependencies (Docker Hub, apt indexes, npm/pypi/hex/crates/maven) are always
`external`. The `key_line` in each entry shows exactly which line was used.

## Counts (class × repo)

| repo | code | flaky | infra | external | total |
| --- | --- | --- | --- | --- | --- |
| apache/kafka | 2 | 0 | 1 | 0 | 3 |
| curl/curl | 0 | 0 | 1 | 1 | 2 |
| elixir-lang/elixir | 1 | 0 | 0 | 1 | 2 |
| fission/fission | 2 | 3 | 2 | 0 | 7 |
| flutter/flutter | 2 | 0 | 0 | 0 | 2 |
| home-assistant/core | 2 | 0 | 2 | 0 | 4 |
| laravel/framework | 0 | 0 | 2 | 3 | 5 |
| microsoft/playwright | 2 | 0 | 0 | 0 | 2 |
| nodejs/node | 1 | 2 | 0 | 2 | 5 |
| rails/rails | 1 | 0 | 3 | 3 | 7 |
| tokio-rs/tokio | 2 | 1 | 0 | 2 | 5 |
| **total** | **15** | **6** | **11** | **12** | **44** |

Balance rules from the task: every class uses at least 5 repos and no repo
gives more than 3 cases to one class — held for `code`, `infra`, `external`.
`flaky` could not be built from 5 repos (see below). Every source repo appears
at least twice.

Case mix by evidence kind:

- `code` — 13 × `failure_in_pr_diff`, 2 × `fixed_by_commit`
- `flaky` — 6 × `rerun_passed_same_sha`
- `infra` — 11 × `runner_or_setup_failure`
- `external` — 12 × `third_party_request_failed`

Runs in the dataset were created between 2026-06-30 and 2026-09-26.

## Skipped / could not prove

Roughly 7,400 failed-job records from about 4,000 recent failed runs across the
11 source repos were scanned (200–300 failed runs per repo, plus ~1,100 job
logs read in full). What was skipped, and why:

- **`flaky` shortfall (6 instead of 12, from 3 repos instead of 5).** GitHub
  only keeps the previous attempt's job records for some repositories. For
  apache/kafka, elixir-lang/elixir, microsoft/playwright, home-assistant/core
  and rails/rails, `…/runs/{id}/attempts/1/jobs` returns an empty list or 404
  for every rerun checked, so the required proof (job failed on attempt 1,
  passed on attempt 2, same commit) cannot be produced from those repos. For
  those repos most attempt-2 successes are also `action_required` approval
  reruns that never ran any job, which are not flakes. Only fission, nodejs and
  tokio retained the needed attempt-1 records in the window.
- **Hangs and timeouts** — `The action has timed out`, `has exceeded the
  maximum execution time` (e.g. curl "linux-mingw" and "CM openssl torture"
  jobs): a hang in the product and a slow runner look the same, so these were
  not labelled.
- **Bare exit codes** — jobs whose only error line is
  `##[error]Process completed with exit code N` with nothing explaining it
  (e.g. fission benchmark, elixir "Upload release").
- **Missing images / 404s** — `manifest unknown` for a container tag (many
  rails devcontainer runs, `ghcr.io/rails/devcontainer/images/ruby:*`): a
  missing image is config, not a registry outage.
- **Cancelled / concurrency-cancelled runs** — `The operation was canceled.`,
  run conclusion `cancelled`, and jobs that only failed because a job they
  depend on failed (e.g. the flutter "Mac_arm64_verify_binaries" guard, kafka
  "CI checks completed").
- **Ambiguous causes** — a kernel OOPS inside tokio's io_uring test VM (infra
  or flake?), MariaDB runs whose container log shows a healthcheck credential
  error (config or environment?), and the fission kind-cluster run where the
  kind binary failed its checksum before any test ran (external download or
  runner setup?).
- **Unavailable logs** — expired/removed logs (e.g. tokio FreeBSD jobs return
  `BlobNotFound`) were dropped, as were runs whose logs were empty.
- **microsoft/playwright** needed the `fixed_by_commit` route (its PR runs are
  test jobs, not lint jobs, and its reruns keep no attempt-1 records); two such
  cases are included.

## Provenance and scrubbing

- Every case comes from a public repository; `run_url` / `evidence_url` in
  `manifest.yaml` link back to the source run, PR or commit.
- Logs were scrubbed before committing: e-mail addresses → `<email>`, token-like
  strings (`ghp_`/`ghs_`/`gho_`/`sk-`/`AKIA`/JWT/`Bearer …`) → `<redacted>`,
  ANSI escape codes stripped. GitHub's own masking (`***`) is left as-is.
  40-character hex commit SHAs are kept: they are public identifiers, and
  removing them would break the quoted evidence lines.
- Five logs were larger than 1 MB and are kept as their last 1 MB
  (`truncated: true` in the manifest).
- `key_line` in every manifest entry is a verbatim substring of its log file.

Labels are proof-based; human spot-check pending.
