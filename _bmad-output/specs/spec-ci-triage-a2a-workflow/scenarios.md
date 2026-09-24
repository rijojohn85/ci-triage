# Scenario acceptance

Run against a real synthetic Python GitHub demo repo with GitHub Actions, installed GitHub App, real webhook delivery and real draft PRs/issues. Compose is the graded runtime; seed/force flaky failures deterministically. Store scenario seed, expected class/state/suspect SHA, actual verdict, CI run ID, repository link and resulting PR/issue/task reference.

| Scenario | Required outcome | Receipt / trace |
| --- | --- | --- |
| S1: code bug, concurrent pushes, two suspects | pr_opened; correct rank-1 culprit; fix draft PR and reviewer request to that author | Candidate ranking and commit + log citations; Reviewer verdict; gate normal; AD-3, AD-7, AD-12, AD-24, AD-27 |
| S2: seeded flaky test | pr_opened; root-cause deflake passing the gate | Quarantine label and PR-body list, no skip/retry/timeout/assertion weakening in diff; AD-13, AD-21 |
| S3: infra OOM | report_sent; no PR | Blame-free issue labelled ci-triage/infra, runner metrics and retry/prevention guidance for on-call; AD-16, AD-27 |
| S4: external API failure | pr_opened; mock/contract-test draft PR | Cited external-failure evidence, Reviewer verdict and normal gate; AD-11–AD-13 |
| S5: high-risk change (seeded failure whose only obvious fix is a timeout bump) | input_required with escalation_reason gate_blocked, then approve/reject recorded | Risk-gate block receipt (AD-13 timeout rule), blame-free evidence pack, task state and authorized identity/note/time; AD-1, AD-4, AD-13, AD-14 |

S5 approval with an existing proposal binds proposal_step_id and diff sha256, then opens a draft; a diff touching .github/workflows/** instead moves to REPORTING with the approved diff for a human to apply (AD-14, AD-16). Approval without a proposal requires --class and resumes ANALYZING through the full applicable chain; the override leaves confidence unchanged, skips only the low-confidence/unknown-class cutoff checks and keeps output blame-free, so the PR requests the approving CODEOWNER (AD-9, AD-27). Rejection produces a report and REJECTED_BY_HUMAN. The run waits indefinitely without occupying a worker. INPUT_REQUIRED is the expected checkpoint, not a completed run.

Beyond the five graded scenarios, verify the low-confidence escalation branch, both approval forms and rejection, unauthenticated/non-owner/wrong-state refusals, high-risk and low-confidence branches, unknown class, no-route, invalid output twice, revision exhaustion, dangerous early escalation, crash recovery, replay/idempotency, stale-lease fencing and transient failure after three attempts. Record expected versus actual behavior; these checks do not change the five-scenario denominator.
