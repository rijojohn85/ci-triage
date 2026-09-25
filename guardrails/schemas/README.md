guardrails/schemas/ — generated JSON Schemas from contracts/ (story 0.2). One file per public envelope model: `TriageVerdict`, `EvidencePack`, `ApprovalPayload`, `Escalation`, `AgentError`, `DataPart` (nested shapes ride along via `$defs`).

Regenerate: `scripts/generate_schemas.py` rewrites committed files; `--check` (wired as `make schema-drift`) fails the gate on byte drift. Refresh loop: check (fails) → generate (writes) → check (zero diff).

Do not hand-edit these files — edit `contracts/` and regenerate.
