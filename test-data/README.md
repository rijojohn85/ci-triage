test-data/ — demo-repo setup docs, fixtures.

- `demo-repo-expected.json` — single source of truth for the App permission
  set expected by AD-16; read by `scripts/verify_demo_repo.py` and cited by
  docs (DRY).
- `demo-repo.md` — the recorded facts of the live demo repository
  (story 0.4): URL, App/installation IDs, ruleset, baseline tag, scenario
  slots S1–S5 (PENDING until filled by real runs), recreate-from-scratch.
- `demo-repo-seed/` — the seed content pushed verbatim to the demo repo
  (package, tests, `.github/workflows/ci.yml`, CODEOWNERS).
