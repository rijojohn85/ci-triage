---
title: 'Story 3.1 — Serve the Jev classifier and batched injection screen'
type: 'feature'
created: '2026-09-26'
status: 'done'
baseline_revision: 'd614dfc6b3b8aa5e9728cd71e741b68e31bb196b'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-3-context.md'
warnings: []
deferred:
  - summary: >-
      Eval surface mismatch: jev.test.yaml drives prompts/jev.md as a chat
      prompt asserting a flat {answer, confidence, noul} shape the production
      path never emits, and the pinned decisions model refuses the chat
      endpoint entirely (provider 400), so no promptfoo eval can run today.
    evidence: |-
      Verified: OpenRouter returns 400 "typesafe/jev-1-13 is a decisions
      model and cannot be used with the chat/completions endpoint"; the
      served contract is pinned by wire-level tests instead. Story 3.2 owns
      the real eval (OQ-1) and must solve the decisions-endpoint or
      SDK-driven eval.
    location: >-
      jev.test.yaml
    severity: low
  - summary: >-
      Untrusted-field coverage: _delimited_state sends only the distilled
      log; commits, candidate suspects, history rows and metrics are not
      sent to the classifier at all.
    evidence: |-
      The epic's own wording ("agents never see raw CI logs — only the
      distilled, numbered log") supports log-only for the classifier; the
      broader pack fields belong to the Analyzer story (3.3).
    location: >-
      agents/jev/classifier.py (_delimited_state)
    severity: low
---

## Build Brief

**(1) Story:** 3.1 — Serve the Jev classifier and batched injection screen (sprint-status key `3-1-serve-the-jev-classifier-and-batched-injection-screen`).

**(2) ACs in one line each:**
- AC1: over JSON-RPC, `classify-failure` makes exactly ONE `system_one` call that batches the five-class `Choice` and the `Noul` injection pre-screen; class descriptions and screen instructions load once from `prompts/jev-classes.yaml`; the distilled log travels as delimited untrusted data, never as instructions; model id and timeout come only from `config/runtime.yaml`.
- AC2: the stateless service's card (`/.well-known/agent-card.json`) declares `classify-failure`; the result conforms to the shared contract models and carries the provider-reported usage for orchestrator/harness accounting; `Choice.confidence` and `probabilities` stay separate values; a positive screen never blocks on its own (the cited cap is guardrails/workflow's job, 2.2); errors use `AgentError` / A2A FAILED; the agent holds no GitHub token and no DB client.
- AC3: with fixture provider responses (no real model calls), valid and error responses match the generated JSON schemas; the service is evaluated independently (promptfoo case exists) before any workflow connection.

**(3) Binding ADs:** AD-11 (one `system_one` call carries both `Choice` and `Noul`; class descriptions + Noul instruction live once in `prompts/jev-classes.yaml`; positive screen adds a cited cap, never blocks alone), AD-5 (stateless spoke, blocking non-streaming call, no GitHub token/DB access, repo context travels in the request), AD-6 (contracts are the payload single source; schemas generated + committed), AD-9 (`Choice.confidence` is the one number; probabilities audit-only; nothing raises it), AD-18 (usage reported, unreported counters NULL never 0 — the orchestrator/harness owns accounting from 6.1), AD-19 (prompts exist once; model IDs + timeouts from config YAML only), AD-20 (untrusted text in delimited data sections, never concatenated into instructions).

**(4) Files:** create `agents/jev/` (`questions.py`, `classifier.py`, `provider.py`, `runtime.py`, `card.py`, `executor.py`, `server.py`, `__init__.py`, README update); fill `prompts/jev.md` + `prompts/jev-classes.yaml`; extend `contracts/jev.py` (`JevResult{classification, usage}`) and `contracts/a2a.py` (add `JevResult` to the `DataPart` payload union); add `JevResult` to `scripts/generate_schemas.py` `ENVELOPE_MODELS` and regenerate schemas; replace the `jev.test.yaml` placeholder with real promptfoo cases; tests under `tests/agents/jev/` + `tests/contracts/`. NOT touched: `workflow/` (no connection to the orchestrator — 2.9 wires it), `guardrails/` (2.2 already owns the cap), other agents, `config/runtime.yaml` values, `promptfooconfig.redteam.yaml`, `docs/USER-GUIDE.md` (no user-visible behaviour — see part 8).

**(5) Approach:** the agent is a thin stateless A2A service (SOLID-S): `questions.py` builds the `Choice` (five class criteria) + `Noul` (injection instructions) pair by loading `prompts/jev-classes.yaml` once — the one source (AD-11/AD-19, DRY: promptfoo and the agent reference the same files, no class text in code); `classifier.py` is the pure domain step — delimited distilled log as `state`, one provider call, `SystemOneResponse` → `contracts.JevClassification` + `contracts.ModelUsage` (unreported counters NULL), SDK errors → typed `AgentError` with the retryable split (AD-22); `provider.py` holds the `JevProvider` Protocol + the `typesafe_sdk` adapter (SOLID-D — tests inject fakes; the agent never imports a concrete client outside this adapter); `runtime.py` is a minimal loader for the `jev` key of `config/runtime.yaml` (the spine's layer table forbids agents importing `workflow/`, so the one YAML fact has two small readers — workflow's full loader and this one-key loader; the values stay single-sourced); `executor.py`/`server.py` are transport only, mirroring `workflow/a2a_server.py`'s wiring with a real executor. `JevResult` joins the `DataPart` payload union so valid and error responses are generated-schema-checked (AD-6). Eval-first: the promptfoo cases in `jev.test.yaml` are written and seen failing/absent BEFORE `prompts/jev.md`/`jev-classes.yaml` are edited.

**(6) TDD plan (red-first; names cite ACs):** `tests/agents/jev/test_questions.py::test_ac1_questions_load_once_from_jev_classes_yaml` (five criteria + Noul instruction come from the yaml; no class text in code), `tests/agents/jev/test_classifier.py::test_ac1_one_call_batches_choice_and_noul` (exactly one provider call carrying both questions), `::test_ac1_untrusted_log_travels_as_state_not_instructions`, `::test_ac2_result_conforms_to_generated_schema` (JevResult through `DataPart` + committed `JevResult.json`), `::test_ac2_usage_reported_in_result` (unreported counters NULL, never 0), `::test_ac2_confidence_and_probabilities_distinct`, `::test_ac2_positive_screen_does_not_block`, `tests/agents/jev/test_errors.py::test_ac2_retryable_sdk_errors_map_to_retryable_agent_error` + `::test_ac2_definitive_sdk_errors_map_to_non_retryable_agent_error` (parametrized over the SDK error types), `tests/agents/jev/test_server.py::test_ac2_card_declares_classify_failure`, `::test_ac2_error_response_carries_agent_error`, `::test_ac3_valid_response_matches_generated_schema` (through the JSON-RPC app with a fake provider), `tests/agents/jev/test_runtime.py::test_ac1_model_and_timeout_from_runtime_yaml`, `tests/contracts/test_jev.py` — extend for `JevResult`.

**(7) Risks / OQ:** promptfoo cannot run without a provider key — the cases are still written first; the spec's Auto Run Result records `promptfoo eval not run: no provider key` if the key is absent (never a faked pass). The a2a-sdk 1.1.5 executor error surface (how FAILED + error data travel over JSON-RPC) must be checked against the installed SDK/docs (context7 first, web second; record the source) before wiring `executor.py`. The promptfoo eval exercises the prompt file as a chat prompt with `is-json` assertions — it cannot drive the SDK's `Choice`/`Noul` primitives; the structured call shape is pinned by the unit tests instead, and 3.2 owns the real eval quality bar (OQ-1). No new dependencies.

**(8) Doc impact:** `docs/DEVELOPER.md` — new "The Jev classifier agent (story 3.1)" section (what the service answers, the one-call shape, where prompts/config live, how 2.9 will call it); `agents/README.md` + `agents/jev/README.md` — one line each. `docs/USER-GUIDE.md` — **no doc change**: the agent is not connected to any user-visible flow yet (the workflow connection is story 2.9), so there is no user-facing behaviour to document.

<intent-contract>

## Intent

**Problem:** There is no Jev specialist to call: classification of a distilled failure has no typed A2A home, so the workflow would have no traceable, single-source Jev confidence and no batched injection pre-screen.

**Approach:** A stateless A2A agent service (`agents/jev/`) exposing `classify-failure`: one `system_one` call batching the five-class `Choice` and the `Noul` injection screen over the delimited distilled log, returning the shared `JevClassification` plus provider-reported usage, with typed `AgentError` failures — prompts and class descriptions single-sourced, model/timeout from config, no GitHub/DB access.

## Boundaries & Constraints

**Always:** one `system_one` call per classify request carrying BOTH questions (AD-11); class descriptions + Noul instruction loaded once from `prompts/jev-classes.yaml` (agent and eval reference the same files); the distilled log travels as untrusted `state`, never inside instructions (AD-20); model id + timeout from `config/runtime.yaml` only (AD-19); unreported usage counters are NULL, never 0 (AD-18); errors are typed `AgentError{code, message, retryable}` surfaced as A2A FAILED; valid and error payloads match the generated schemas (AD-6); `Choice.confidence` and `probabilities` remain separate values (AD-9); unit tests use Protocol fakes and fixture provider responses — no real model calls.

**Never:** no GitHub token or DB client anywhere in the agent (layer contract); no Postgres writes — the orchestrator/harness does accounting from 6.1; no blocking on a positive injection screen (the cited cap is 2.2's `ClassConfidence`, added by the workflow); no workflow/state-machine wiring (2.9); no new model ids (allowed set only: the pinned `typesafe/jev-1.13` via the existing OpenRouter config — never GLM or any other model); no schema hand-edits (regenerate only); no changes to `guardrails/`, other agents, or `config/runtime.yaml` values.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Valid classification | EvidencePack with distilled log; fixture provider response with choice+noul answers | one batched call; `JevResult{classification, usage}` matching generated schema | No error expected |
| Unreported usage | fixture response with NULL token counters | `ModelUsage` counters NULL, never 0 | No error expected |
| Positive injection screen | fixture `noul` above the screen cutoff | classification returned unchanged; agent does NOT block or cap (2.2 owns the cap) | No error expected |
| Retryable provider error | fixture `TypeSafeAPIConnectionError` / rate limit / timeout | `AgentError{retryable: true}` surfaced as A2A FAILED | Typed error, collected |
| Definitive provider error | fixture auth/bad-request/response-validation error | `AgentError{retryable: false}` surfaced as A2A FAILED | Typed error, collected |
| Unknown class label | fixture choice outside the five classes | `AgentError{retryable: false}` (contract parse refuses) | Typed error, collected |
| Malformed request | payload that is not an EvidencePack | A2A invalid-request error, no provider call | Typed error, collected |

</intent-contract>

## Code Map

- `contracts/jev.py` -- `JevChoice`/`JevInjectionScreen`/`JevClassification` + the `Sdk*Answer` structural Protocols; extend with `JevResult{classification, usage}`; the `from_sdk` converters are the response-mapping precedent.
- `contracts/usage.py` -- `ModelUsage` (NULL-when-unreported counters, AD-18); reuse for the reported usage; do not edit.
- `contracts/a2a.py` -- `DataPart` payload union; add `JevResult`.
- `contracts/errors.py` -- `AgentError{code, message, retryable}`; the error shape; reuse.
- `guardrails/schemas/JevClassification.json` + generator -- `scripts/generate_schemas.py` `ENVELOPE_MODELS` gains `JevResult`; `make schema-drift` gates regeneration.
- `workflow/a2a_server.py` -- the A2A wiring precedent (`create_jsonrpc_routes`, `DefaultRequestHandler`, `AgentCard`); mirror the transport shape with a real executor; do not edit.
- `workflow/runtime_config.py` -- the full four-agent loader; the agents layer may not import `workflow/` (spine layer table), hence `agents/jev/runtime.py` as the one-key reader of the same file; do not edit.
- `config/runtime.yaml` -- `jev: {model: typesafe/jev-1.13, step_timeout: 60}`; values pinned; never add models here.
- `prompts/jev.md`, `prompts/jev-classes.yaml` -- placeholders today; filled eval-first (jev.test.yaml cases first).
- `jev.test.yaml` -- placeholder; replaced with promptfoo cases (provider matching the pinned Jev model; `is-json` assertions).
- `typesafe_sdk` 0.7.1 (installed) -- `TypeSafeClient.system_one(state, questions, model=, timeout=)` → `SystemOneResponse{model, usage{input_tokens, output_tokens}, answers}`; `Choice`/`Noul` question types; error hierarchy in `typesafe_sdk._core.errors`.
- `tests/guardrails/test_validator.py` -- fixture-style precedent (contract-dumped payloads); `tests/workflow/test_a2a_client.py` -- transport-test precedent.
- `scripts/check_layer_contract.py` -- agents layer check (no GitHub/Postgres imports); new modules covered automatically.

## Tasks & Acceptance

**Execution:**
- `jev.test.yaml` -- replace the placeholder with promptfoo cases FIRST (labelled class fixtures + injected verdict-flip case, `is-json` assertions on class/confidence fields) -- eval-first (AGENTS.md prompts-are-code).
- `prompts/jev-classes.yaml` -- the five class descriptions + the Noul injection-screen instruction, one copy (AD-11/AD-19) -- single source for agent and eval.
- `prompts/jev.md` -- the Jev system prompt: role, untrusted-data rule (AD-20), output discipline -- loaded by the agent at runtime.
- `contracts/jev.py` + `contracts/a2a.py` -- add `JevResult{classification, usage}` and join the `DataPart` union -- AC2/AC3 payload surface.
- `scripts/generate_schemas.py` -- add `JevResult` to `ENVELOPE_MODELS`, regenerate -- AD-6.
- `agents/jev/questions.py` -- build the `Choice`+`Noul` pair from `prompts/jev-classes.yaml`, loaded once -- AC1.
- `agents/jev/classifier.py` -- pure classify step: delimited log as state, one provider call, response → `JevResult`, errors → `AgentError` -- AC1/AC2.
- `agents/jev/provider.py` -- `JevProvider` Protocol + `typesafe_sdk` adapter (model/timeout injected from runtime) -- SOLID-D seam.
- `agents/jev/runtime.py` -- minimal `jev`-key loader for `config/runtime.yaml` -- AD-19.
- `agents/jev/card.py`, `agents/jev/executor.py`, `agents/jev/server.py` -- AgentCard declaring `classify-failure`; executor (EvidencePack in → JevResult out; AgentError → A2A FAILED); JSON-RPC app -- AC2/AC3.
- `tests/agents/jev/…`, `tests/contracts/test_jev.py` -- red-first per brief (6) -- AC proof.
- `agents/README.md`, `agents/jev/README.md`, `docs/DEVELOPER.md` -- per brief (8).

**Acceptance Criteria:**
- Given a distilled EvidencePack, when `classify-failure` is called over JSON-RPC, then exactly one `system_one` call batches the five-class `Choice` and the `Noul` screen, class descriptions and screen instructions come once from `prompts/jev-classes.yaml`, the log travels as delimited untrusted state, and model/timeout come from `config/runtime.yaml` (AC1).
- Given the stateless service, when card/result/error are requested, then the card declares `classify-failure`, the result conforms to the shared models and carries reported usage, `Choice.confidence` and probabilities stay distinct, a positive screen does not block, errors are `AgentError`/A2A FAILED, and the agent holds no GitHub token or DB client (AC2).
- Given fixture calls and provider responses, when component checks run, then valid and error responses match the generated schemas and the service has an independent promptfoo eval case (AC3).

## Spec Change Log

## Review Triage Log

### 2026-09-26 — Review pass
- verdicts: 28 findings — high 0, medium 6, low 18, false 4, maybe-false 0
- findings:
  - `[medium]` `[patch]` reply data part is the bare `JevResult`/`AgentError`, not a `DataPart` envelope (inbound requires the wrapper; docs/AD-6 say every inter-agent data part is a `DataPart`) — verified in `executor.py:_finish`; fix: wrap the reply in `DataPart(task_id, context_id, payload)` and unwrap in tests.
  - `[medium]` `[patch]` untyped escapes past the AgentError boundary: `load_questions()` sits outside the try (yaml KeyError/ValueError propagate raw); `_result` catches only KeyError/ValueError/ValidationError so a malformed `usage`/`model` surface raises AttributeError/TypeError; executor catches only `ClassifyError` so any other exception leaves the task WORKING with no terminal FAILED — verified by reading the try scopes; fix: typed config/parse errors + catch-all in executor mapping to `AgentError`.
  - `[medium]` `[patch]` delimiter collision: a distilled log line containing `distilled_log>>>` closes the untrusted section early (AD-20 surface) — verified: `_delimited_state` does no collision guard; fix: reject/escape colliding lines (deterministic fail-closed).
  - `[medium]` `[patch]` `TypeSafeJevProvider` is never executed by any test or entrypoint (the one place the Protocol meets the real SDK is unverified) and rebuilds `AsyncTypeSafeClient()` per call when no client is injected — verified by repo-wide symbol search; fix: stub-client forwarding test + construct/cache the client once in `__init__`.
  - `[medium]` `[patch]` no servable entrypoint: nothing wires `TypeSafeJevProvider` + `load_jev_runtime` + `classify` into `create_app`, so the service cannot be started outside tests — verified: only composition site is the test; fix: thin `agents/jev/__main__.py`.
  - `[medium]` `[patch]` error payload never validated against the committed `AgentError.json` (AC3 says valid AND error responses match generated schema; only fields are asserted) — verified in `test_ac2_error_response_carries_agent_error`; fix: jsonschema-check the error payload in the wire test.
  - `[low]` `[patch]` `prompts/jev.md` is never loaded by the agent while spec/docs call it the agent's system prompt and the eval exercises it — fix: relabel in spec/docs/eval comments as the eval-side prompt contract (the served call's instructions are the `Choice`/`Noul` instructions from `jev-classes.yaml`); wiring chat system text into `system_one` is not supported by the pinned SDK call shape.
  - `[low]` `[patch]` log delimiters duplicated in `jev.md` and code constants (DRY) — fix: prompt references the rule without restating the literal markers.
  - `[low]` `[patch]` `lru_cache` on a `path`-parameterized function: one alternate-path call evicts the default entry, silently turning "loaded once" into "reloaded per request" — fix: module-level constant cache or drop the parameter from the cached function.
  - `[low]` `[patch]` duplicate `ClassifyStep` alias in `executor.py` and `server.py` — fix: import one from the other.
  - `[low]` `[patch]` `load_jev_runtime` indexes `raw["jev"]` directly (raw KeyError, untested path) — fix: typed config error + test.
  - `[low]` `[patch]` executor emits empty-string task/context ids when the request lacks them — fix: refuse with `InvalidParamsError` (deterministic) + test.
  - `[low]` `[patch]` `_evidence_pack` raises on the first non-EvidencePack data part instead of scanning further parts — fix: continue past non-EvidencePack data parts, refuse only when none found + test.
  - `[low]` `[patch]` "no class text in code" test checks only two-word bigrams (false positives/negatives) — fix: assert a distinctive substring per class description.
  - `[low]` `[patch]` `TypeSafeAPITimeoutError(60.0)` duplicates the runtime timeout literal — fix: use `RUNTIME.step_timeout`.
  - `[low]` `[patch]` the ~15-line `is-json` assertion block is copy-pasted across all six promptfoo cases — fix: hoist to a YAML anchor/`defaultTest` so the output contract has one source.
  - `[low]` `[patch]` `_result` types `response` as `Any`, so the `SystemOneResult` Protocol is unenforced on the consumed value — fix: annotate with the Protocol and widen the parse guard to `AttributeError`/`TypeError`.
  - `[low]` `[reject]` tests import `httpx2` (SDK-vendored httpx copy) — verified: `httpx2` is a real pinned dependency in `requirements/constraints.txt`; legitimate.
  - `[low]` `[defer]` eval surface mismatch: `jev.test.yaml` drives `jev.md` as a chat prompt asserting a flat `{answer, confidence, noul}` shape the production path never emits, and the pinned decisions model refuses the chat endpoint entirely (provider 400) — disclosed in the spec's risk section; the served contract is pinned by wire tests; story 3.2 owns the real eval (OQ-1) and must solve the decisions-endpoint/SDK-driven eval.
  - `[low]` `[defer]` untrusted-field coverage: `_delimited_state` sends only the distilled log; commits/suspects/history/metrics are not sent at all — the epic's own wording ("agents never see raw CI logs — only the distilled, numbered log") supports log-only for the classifier; broader pack fields belong to the Analyzer story.
  - `[false]` `[reject]` "not run" record absent from the spec — transient: the Auto Run Result is written at finalize (this step), and it records the honest blocker (provider refusal, stronger than "no provider key").
  - `[false]` `[reject]` cap artifact missing from `JevResult` (R3a) — the spec's intent-contract and AD-11 assign the cited cap to 2.2's `ClassConfidence`; the agent reporting the raw screen probability is the selected reading.
  - `[false]` `[reject]` a2a-sdk verification note missing from the diff — a unified diff cannot carry the verification record; the implementer's report records it (installed SDK source answered) and the Auto Run Result repeats it.
  - `[false]` `[reject]` eval-first ordering unverifiable — process proof lives outside the diff; the yaml comments and the implementer's red evidence (6 errors against the placeholder prompt) record it.

## Design Notes

The one-call shape (AD-11) — questions built once from the yaml:

```python
QUESTIONS = {  # agents/jev/questions.py, loaded once from prompts/jev-classes.yaml
    "choice": Choice(instructions=..., criteria={  # five FailureClass labels
        "code": "...", "flaky": "...", "infra": "...",
        "external": "...", "unknown": "..."}),
    "noul": Noul(instructions=...),  # the injection pre-screen instruction
}
result = provider.system_one(state=delimited_log, questions=QUESTIONS,
                             model=runtime.model, timeout=runtime.step_timeout)
```

Error split (AD-22): connection/timeout/rate-limit/5xx SDK errors → `AgentError(retryable=True)`; auth/bad-request/not-found/permission/unprocessable/response-validation → `retryable=False`. The executor turns either into an A2A error carrying the `AgentError` payload (exact SDK mechanism verified against the installed a2a-sdk 1.1.5 before wiring). The agent never caps or blocks on `noul` — `guardrails.confidence.ClassConfidence` (2.2) adds the cited cap downstream.

## Verification

**Commands:**
- `uv run pytest tests/agents tests/contracts/test_jev.py -q` -- expected: all pass, AC-named tests green.
- `uv run python scripts/check_layer_contract.py` -- expected: PASS (agents hold no GitHub/Postgres clients).
- `npx promptfoo eval -c jev.test.yaml` -- expected: runs only with a provider key; without one, record `promptfoo eval not run: no provider key` in the Auto Run Result (never a faked pass).
- `make check` -- expected: PASS (bootstrap, layer contract, schema drift, state diagram, ruff, mypy --strict, pylint duplicate-code, pytest ≥85%).

## Auto Run Result

Status: done

**Summary:** The Jev classifier agent landed as a stateless A2A service under `agents/jev/`: `classify-failure` accepts a `DataPart` wrapping an `EvidencePack`, makes exactly ONE `system_one` call batching the five-class `Choice` and the `Noul` injection screen (questions built once from `prompts/jev-classes.yaml`, the single copy), sends the distilled log as a delimited untrusted `state` (with a fail-closed delimiter-collision guard), and returns a `DataPart`-enveloped `JevResult{classification, usage}` on COMPLETED or a typed `AgentError` on FAILED (AD-22 retryable split; every failure path typed, nothing escapes). Model id and timeout come only from `config/runtime.yaml`; the agent holds no GitHub token and no DB client. New shared contract `JevResult` joined the `DataPart` union with its generated schema committed. A thin `agents/jev/__main__.py` composes the real provider + runtime + app so the service is actually servable. Eval-first: the six promptfoo cases in `jev.test.yaml` were written and seen failing BEFORE the prompts were edited.

**Files changed:**
- `agents/jev/` (new package) — `questions.py` (Choice+Noul from the one yaml, path-independent cache), `classifier.py` (pure step, typed errors, delimited state), `provider.py` (`JevProvider`/`SystemOneClient` Protocols + the one SDK adapter, client built once), `runtime.py` (jev-key loader, typed config errors), `card.py`/`executor.py`/`server.py` (card declaring `classify-failure`; executor: DataPart in/out, FAILED carries schema-validated `AgentError`), `__main__.py` (servable composition), README.
- `contracts/jev.py`, `contracts/a2a.py` — `JevResult{classification, usage}` added to the payload union.
- `guardrails/schemas/JevResult.json`, `DataPart.json` — regenerated (8 schemas byte-identical).
- `prompts/jev.md` (eval-side prompt contract, relabeled), `prompts/jev-classes.yaml` (the one class-description copy).
- `jev.test.yaml` — 6 promptfoo cases, output contract hoisted to `defaultTest`.
- `tests/agents/jev/` (new: questions/classifier/errors/provider/server/runtime/main), `tests/contracts/test_jev.py` — AC-named tests.
- `agents/README.md`, `docs/DEVELOPER.md` — per Build Brief part 8. `docs/USER-GUIDE.md`: no doc change (service not user-visible until 2.9 wires it).

**Review findings breakdown:** 28 findings — 0 high, 6 medium, 18 low, 4 false, 0 maybe-false. 16 patch groups applied (6 medium: DataPart reply envelope, typed catch-all + widened parse guard, delimiter-collision guard, adapter forwarding test + client built once, servable `__main__`, error-payload schema validation; 10 low: jev.md relabel, delimiter DRY, cache path-independence, alias dedup, typed config error, id refusal, part scanning, stronger leak check, timeout literal, eval dedup). 2 items deferred (eval surface mismatch — decisions model refuses the chat endpoint, story 3.2 owns the real eval; untrusted-field coverage — log-only is the supported classifier reading). 4 false findings rejected with refutations in the Review Triage Log.

**Follow-up review recommendation:** true — six medium entries were patched. Unverified risk: the reply-envelope and catch-all changes altered the wire contract after the review layers saw the diff (tests cover them, but no layer re-reviewed the patched shape), and the `__main__` composition has only a smoke test — a follow-up pass should check the patched executor/entrypoint against the 2.8 transport's expectations once that client exists.

**promptfoo eval:** NOT RUN — the pinned `typesafe/jev-1.13` is a decisions model; OpenRouter refuses it on the chat/completions endpoint promptfoo drives (provider 400, independent of any key). Cases exist and parse clean; story 3.2 owns the real eval (OQ-1). Never a faked pass.

**a2a-sdk error surface (recorded source):** the installed a2a-sdk 1.1.5 source under `.venv` answered (executor event protocol, terminal `TaskStatusUpdateEvent`, JSON-RPC error mapping, card routes); typesafe-sdk 0.7.1 error hierarchy read from its installed source. No context7/web needed.

**Verification performed:** `make check` PASS (bootstrap pins; layer contract PASS; 8 schemas + state diagram byte-identical; ruff check+format clean incl. agents/; mypy --strict clean incl. agents/; pylint duplicate-code 10.00/10; 606 passed, 65 integration deselected; coverage 94.48% ≥ 85%). Focused: `pytest tests/agents tests/contracts/test_jev.py -q` → 52 passed. I/O matrix audit: all 7 rows covered by passing AC-named tests. No `# noqa` exceptions introduced.

**Residual risks:** the two deferred items in frontmatter (eval surface — 3.2 must solve the decisions-endpoint eval; classifier sees only the distilled log by design). The follow-up-review risk named above. `TypeSafeJevProvider` resolves `TYPESAFE_API_KEY`/`TYPESAFE_BASE_URL` at first real call; a missing key surfaces then, not at startup.
