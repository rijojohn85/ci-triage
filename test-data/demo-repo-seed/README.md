# CI Triage demo repository (story 0.4 seed)

Synthetic baseline repository for the blameless CI triage tool. Source of
truth for this content lives in the CI triage repo under
`test-data/demo-repo-seed/`; this folder is pushed to the demo repo
verbatim (see "Recreate from scratch" in `test-data/demo-repo.md`).

- `CODEOWNERS` carries the applicable fallback `*` rule (the AD-14
  authority, read from the protected default-branch tip).
- `.github/workflows/ci.yml` runs the tests on push and pull_request; the
  green baseline commit is tagged `baseline-v1`.
- Scenario drivers (stories 6.6-6.8) break this baseline on purpose and
  never extend the workflow (AD-13/AD-16 blocked path).
