# Run state diagram
<!-- Generated from the AD-1 transition table in workflow/transitions.py; do not edit by hand. -->
<!-- Regenerate: python scripts/generate_state_diagram.py; drift gate: make state-diagram-drift -->

```mermaid
stateDiagram-v2
  [*] --> RECEIVED
  RECEIVED --> DISTILLING
  RECEIVED --> FAILED
  DISTILLING --> CLASSIFYING
  DISTILLING --> FAILED
  CLASSIFYING --> ANALYZING
  CLASSIFYING --> AWAITING_APPROVAL: low confidence / unknown / no-route / validation failed
  CLASSIFYING --> FAILED
  ANALYZING --> REPORTING: class = infra
  ANALYZING --> PROPOSING: code / flaky / external
  ANALYZING --> AWAITING_APPROVAL: low confidence / validation failed
  ANALYZING --> FAILED
  PROPOSING --> REVIEWING
  PROPOSING --> AWAITING_APPROVAL: validation failed
  PROPOSING --> FAILED
  REVIEWING --> PROPOSING: major objections, round < 2
  REVIEWING --> GATING: accepted or dangerous (early escalation)
  REVIEWING --> AWAITING_APPROVAL: rejected after 2 rounds / validation failed
  REVIEWING --> FAILED
  GATING --> PR_OPENING: risk_tier = normal
  GATING --> AWAITING_APPROVAL: risk_tier = blocked
  GATING --> FAILED
  AWAITING_APPROVAL --> PR_OPENING: approve, proposal exists, no workflow file
  AWAITING_APPROVAL --> REPORTING: approve, diff touches .github/workflows/**
  AWAITING_APPROVAL --> ANALYZING: approve with class override, no proposal
  AWAITING_APPROVAL --> REPORTING: reject
  AWAITING_APPROVAL --> FAILED
  PR_OPENING --> DONE_PR
  PR_OPENING --> FAILED
  REPORTING --> DONE_REPORT
  REPORTING --> REJECTED_BY_HUMAN: after reject
  REPORTING --> FAILED
  DONE_PR --> [*]
  DONE_REPORT --> [*]
  FAILED --> [*]
  REJECTED_BY_HUMAN --> [*]
```
