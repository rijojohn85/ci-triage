guardrails/ — validator, citation_check, risk_gate, thresholds.yaml. Depends only on contracts/. Schema files live in `guardrails/schemas/` (generated, committed; drift gate = `make schema-drift`). Filled by: Epic 2/3 stories (schemas shipped by story 0.2).

`confidence.py` (story 2.2) is the one confidence number as code (AD-9): it turns one Jev answer plus zero or more cited caps into a single trusted "how sure" value that only ever goes down, never up, and answers whether that number is low enough to pause a run. See [docs/DEVELOPER.md § Confidence](../docs/DEVELOPER.md#confidence-one-trusted-number-story-22) for the full picture in plain words.

`thresholds.yaml` is the one thresholds file (AD-19). Story 2.5 adds the `distiller.max_bytes` key there — the most evidence text the log distiller may keep — read through `workflow.thresholds`. See [docs/DEVELOPER.md § Distilling CI logs](../docs/DEVELOPER.md#distilling-ci-logs-story-25).
