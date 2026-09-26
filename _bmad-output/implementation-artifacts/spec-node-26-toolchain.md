---
title: 'Use Node 26 consistently for project tools'
type: 'chore'
created: '2026-09-27'
status: 'done'
route: 'dispatch'
baseline_commit: '8d65d7cb99b606b12ef89da541736ee69ae46af5'
review_loop_iteration: 0
context:
  - /tmp/stage4-node26/AGENTS.md
---

<frozen-after-approval reason="User approved the Node 26 migration brief with go">

## Intent

Make the complete project npm toolchain install and run consistently on Node 26. The observed failure was a Node 22 global promptfoo binary loading under Node 26; the project already pins newer, compatible direct dependencies. Establish a repeatable Node 26 installation and catch runtime mismatches before tools run.

The user approved an isolated worktree and branch from current main. This worktree is `/tmp/stage4-node26`, branch `story/node-26-toolchain`. Preserve unfinished story 3.11 changes in the original checkout.

## Boundaries & Constraints

Always retain architecture spine pins: promptfoo 0.123.1 and smee-client 5.0.0. Use Node 26.10.0 as the shared minimum and default, allow newer Node 26 patches/minors, reject other major versions with useful guidance. Keep the runtime version in `.nvmrc` and use it from bootstrap and the eval runner; package.json mirrors the supported range for npm tooling. Verify clean installation and command startup under Node 26. Preserve AD-18 accounting, AD-19 prompt/config sources, AD-26 eval behavior and all Python application behavior.

Never edit the architecture spine, original product spec, epics, prompts, classifier behavior, thresholds or Python dependency versions. No model calls, live GitHub operations, deployment, push or merge. Do not upgrade all transitive packages merely for recency. Avoid introducing Protocols or new abstractions for runtime configuration: keep runtime checking at existing tool entrypoints (single responsibility), reuse existing selection logic and read the shared version instead of duplicating constants (DRY).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected behavior | Error handling |
|---|---|---|---|
| Supported runtime | Node 26.10.0 or newer within major 26 | Bootstrap and eval accept it | Normal execution |
| Old runtime | Node 22, 24, or 26 below 26.10.0 | Bootstrap refuses before installation; eval skips unsuitable candidates | Explain required runtime and nvm use/install |
| Future major | Node 27 | Refuse as unverified runtime | Same clear guidance |
| Suitable fallback | PATH has old node, nvm has supported Node 26 | Eval chooses supported candidate and uses it for child execution | Preserve existing search precedence |
| Missing usable runtime | No candidate is suitable | Fail without making model calls | List attempted candidates and versions |

</frozen-after-approval>

## Code Map

- `package.json`, `package-lock.json`: exact direct pins exist; only npm development tools live here. promptfoo engines >=22.22.0, smee-client engines ^20.18 || >=22. npm lock contains 944 entries; optional sharp-win32-ia32 0.35.4 restricts Node to ^20.9.0 and is unsupported on Node 26 Windows 32-bit. Other declared engine ranges accept Node 26.10.0; engine acceptance alone is not runtime proof.
- `scripts/bootstrap.sh`: preflight currently only checks node/npm presence; then installs constrained Python dependencies and npm ci, verifies artifact versions. Add early runtime check and command startup checks so installed-version metadata cannot conceal native-module failures.
- `scripts/run_jev_eval.py`: existing `resolve_node` checks PATH, overrides, nvm, system candidates; currently accepts any Node >=22.22.0. `_run_promptfoo` uses project-local command and prepends selected node to PATH.
- `tests/scripts/test_run_jev_eval.py`: tests candidate precedence, fallback and clear failure, plus accounting and receipt behavior. Retain accounting tests and update runtime expectations deliberately for approved Node 26 policy; add AC-named cases for the new behavior.
- `Makefile`: make check includes bootstrap, lint, formatting, strict typing, duplicate check and coverage. No existing GitHub Actions toolchain workflow was found; do not invent CI configuration.
- `docs/DEVELOPER.md`: setup and eval runtime selection sections. `docs/USER-GUIDE.md`: local prerequisites and webhook tooling installation.

## Tasks & Acceptance

**Execution:**
- [x] `.nvmrc`, `package.json`, `package-lock.json`: record shared Node 26 default and npm engine range; retain direct pins; install with Node 26 and validate installed tools.
- [x] `tests/scripts/test_node_toolchain.py`, `tests/scripts/test_run_jev_eval.py`: write failing public-entrypoint tests for runtime acceptance, early rejection and eval fallback/error. Use temporary fake executables for bootstrap rejection without modifying real installed tools or requiring network.
- [x] `scripts/bootstrap.sh`: validate runtime before installs and verify project-local CLI startup for promptfoo and smee-client after installation, using the selected node on PATH. Avoid touching user promptfoo database in test verification; use a temporary configuration directory for smoke checks where needed.
- [x] `scripts/run_jev_eval.py`: read shared Node version, enforce supported range, preserve precedence and selected-node child PATH; retain scoring behavior.
- [x] `docs/DEVELOPER.md`, `docs/USER-GUIDE.md`: document nvm install/use, clean dependency installation after switching runtime, local command invocation, supported platform limitation, and runtime error guidance. Link spine pins instead of copying full package tables.

**Acceptance Criteria:**
- AC1: Given the locked dependency tree, when npm ci runs using Node 26.10.0, then installation succeeds and both local CLIs start, with declared nonoptional installed package engines compatible.
- AC2: Given a supported or unsuitable runtime, when bootstrap validates prerequisites, then it accepts supported Node 26 and rejects others before installing, with actionable guidance.
- AC3: Given mixed Node candidates, when the eval runner resolves a runtime, then it chooses supported Node 26 and produces a clear error if none exists, without changing eval output or model-call accounting.
- AC4: Given the migration changes, when make check runs under Node 26, then all gates pass and both guides describe the actual setup.

## Implementation Notes

The brief and scope were approved in the parent conversation; no additional scope approval is required. Document any optional installation warnings and distinguish CLI smoke verification from optional provider/backend runtime support. Clean install may require network escalation; do not bypass sandbox approval. Reuse the original checkout's Python venv if needed for initial red tests, but ensure imports and source under test belong to this worktree; final gates must operate on the worktree.

## Spec Change Log

## Review Triage Log

| Reviewer / finding | Verdict and evidence | Route |
|---|---|---|
| Edge case: prerelease version admitted | Medium: `_node_version` uses prefix matching, so real `v26.10.0-rc.1` output becomes `(26, 10, 0)` and is admitted despite bootstrap's full match and the stable engine range. | Patch: full match plus public runtime regression tests. |
| Clean code: three repeated bootstrap setups | Low: copying bootstrap and creating the same directories in three test bodies makes subsequent setup changes require coordinated edits. | Patch: one shared fixture, keeping test behaviors separate. |
| Clean code: temporary configuration and cleanup unasserted | Medium verification omission: new startup tests did not check the directory override or cleanup despite the documented saved-database isolation. Source uses the override and EXIT trap correctly; add regression protection. | Patch: assert isolation and cleanup. |
| Blind: prerelease parsing | Medium: independently confirms the same prefix-match defect. | Patch: same root cause as edge-case finding. |
| Blind: missing/malformed .nvmrc diagnostics | Low: deleting or replacing the committed numeric policy can raise an import error, including for help. This is unsupported local configuration; normal checkout includes the validated file, and making loading lazy adds guards and a new code path for an unlikely misuse. | Reject: negligible normal-use impact; proposed fix adds complexity. |
| Blind: successful npm output hidden | Low: successful install output is captured silently by pre-existing bootstrap code at baseline. Direct `npm ci`, already documented, exposes these warnings. | Defer: pre-existing output visibility limitation, not caused by this migration. |
| Blind: success and isolation startup assertions absent | Medium verification omission: fake CLI cases only covered failures and did not check configuration cleanup. | Patch: same root cause as clean-code configuration finding; add success case too. |
| Blind: consistency assertions repeat runtime policy | Low: metadata tests hardcode the same minimum twice; deriving the package range from `.nvmrc` checks the shared relationship directly. | Patch: derive range in test. |

Verification-gap reviewer found no gaps. All four review layers completed; static graph's apparent `resolve_node` coverage gap was checked against source and the passing public `resolve_node` and `main` tests (the harness uses dynamic import, which the graph does not trace).

## Verification

- New focused pytest runtime tests: demonstrate red then green per AC2/AC3.
- npm ci under Node 26 with existing lock, plus local promptfoo --version and smee --help: AC1.
- Inspect installed nonoptional engine ranges and smoke-check native components needed by default CLI startup; document optional backend limitations rather than claiming untested providers are verified.
- make check under Node 26: AC4, no prompt eval because prompts do not change.

### Implementation evidence (2026-09-27)

- AC1: `PATH=/home/rijojohn/.nvm/versions/node/v26.10.0/bin:$PATH bash scripts/bootstrap.sh` exited 0 after its clean `npm ci`, verifying both direct pins and both local CLI startups. Separate local `promptfoo --version` with a temporary `PROMPTFOO_CONFIG_DIR` printed 0.123.1; local `smee --help` exited 0. The initial sandbox install was cancelled after stalling; successful installation ran with network approval.
- AC1 runtime evidence: installed lockfile package engine inspection found 828 installed entries and zero incompatible declared Node ranges. Independent esbuild TypeScript transformation and an in-memory `@libsql/client` SELECT succeeded. This covers native components exercised by default tooling; optional providers/backends were not exercised.
- AC2/AC3 red: focused runtime suite initially had 10 failures and 15 passes. Bootstrap passed unsuitable Node versions into installation; eval chose unsuitable candidates; shared runtime declarations and actionable guidance were absent. Public bootstrap CLI failure cases were separately run against the unchanged HEAD bootstrap in temporary folders: both broken commands escaped detection, establishing the missing startup check.
- AC2/AC3 green: `.venv/bin/python -m pytest tests/scripts/test_node_toolchain.py tests/scripts/test_run_jev_eval.py -q` passed all 32 tests. Real Python validates fake Node executable versions; tests cover 26.10.0 and newer Node 26, early rejection, supported fallback, child PATH selection, clear failure before promptfoo and existing zero-call receipt/accounting behavior.
- AC4: `PATH=/home/rijojohn/.nvm/versions/node/v26.10.0/bin:$PATH make check` exited 0: bootstrap, layer contract, schema/state-diagram drift, lint, formatting, strict typing and duplication passed; 767 tests passed, 66 integration tests deselected; coverage 94.96% (required 85%). `git diff --check` passed. Both guides now describe nvm setup, clean installation, local CLIs, runtime errors and the unsupported optional Windows 32-bit image package.
- Warnings/limits: initial npm output included existing transitive deprecation warnings; promptfoo startup emitted Node's experimental DecompressInterceptor warning. Optional backend install scripts can be blocked by npm policy and require separate feature verification. No prompt eval, model calls, live GitHub operations, push or merge were performed.
- Design: runtime checks remain at the existing bootstrap/eval entrypoints (single responsibility); both read `.nvmrc` and eval retains its existing candidate order and child PATH logic (DRY). No new abstractions, Python dependency changes or application behavior changes.

### Final review verification (2026-09-27)

- Prerelease tests first failed for executable versions `26.10.0-rc.1` and `26.11.0-nightly20260927`; `_node_version` now uses full matching. Both public resolver cases pass.
- Bootstrap CLI tests now cover successful completion and both startup failures, both command invocations, a separate temporary promptfoo configuration, unchanged saved configuration contents, and cleanup on every exit. A temporary mutation removing cleanup failed all three cases before restoration.
- Repeated bootstrap setup is shared in a pytest fixture; package engines assertions derive from `.nvmrc`. The two affected test files pass all 35 tests.
- Parent verification: `PATH=/home/rijojohn/.nvm/versions/node/v26.10.0/bin:$PATH make check` exited 0 after review fixes: **770 passed, 66 integration tests deselected, 94.96% coverage**; all bootstrap, layer, schema, state diagram, lint, format, typing and duplication gates passed. An initial invocation with the shell's default Node 22 was correctly rejected before installation.
- All actionable review findings were resolved. One pre-existing successful-install warning visibility issue is recorded in `deferred-work.md`; missing/malformed committed runtime configuration handling was rejected as negligible unsupported local configuration complexity.
