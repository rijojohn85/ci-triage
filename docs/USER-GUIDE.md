# User guide — Blameless CI Triage

How to install and use the tool. This file describes only what works on `main` today; each story that changes user-visible behaviour updates it in the same PR (AGENTS.md "How work is done", step 7).

**Current status:** nothing is usable yet. The project is building its foundation (Epic 0). Sections below fill in as their stories land.

## What the tool will do

When a GitHub Actions run fails on a repository where the GitHub App is installed, the tool works out why and answers with one of:

- a **draft pull request** with a proposed fix (never merged automatically);
- an **infra report** issue for on-call, when the CI machine rather than the code broke;
- a **pause for a human**, when it is unsure or the fix is risky; a CODEOWNER then approves or rejects.

It never blames a person without evidence.

## Sections

| Section | Available after |
| --- | --- |
| Run it locally (Compose) | story 0.3 |
| Install the GitHub App on a repository | stories 0.4, 1.1 |
| Reading a draft PR or infra report | story 2.11 |
| Approving or rejecting a paused triage | Epic 5 |
| Configuration | to be decided by the stories that add settings |
