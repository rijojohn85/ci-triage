- source_spec: `_bmad-output/implementation-artifacts/spec-2-2-compute-immutable-jev-confidence-and-cited-caps.md`
  summary: Map an SDK Choice/probability label outside the 5 classes to a typed non-retryable AD-22 agent error at the Jev agent edge.
  evidence: `JevChoice.from_sdk` raises a bare ValueError for e.g. "timeout"; loud but untyped. Belongs to the E3 Jev agent that calls the SDK.
