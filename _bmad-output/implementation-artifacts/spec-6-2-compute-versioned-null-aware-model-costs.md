---
title: 'Story 6.2 — Compute versioned NULL-aware model costs'
type: 'feature'
created: '2026-09-26'
status: 'done'
baseline_revision: 'eb5ef3f5ecd2fc4384f568c7f3afaa2f182a0d07'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/AGENTS.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-6-context.md'
warnings: []
deferred:
  - summary: >-
      JevRate.rate is a single scalar and cannot express per-token-type Jev
      rates when OQ-3 resolves with typed billing units; the schema evolves
      with the sourced facts in the story that closes OQ-3.
    evidence: |-
      The billing units are explicitly unresolved (OQ-3), so designing the
      per-type schema now would speculate; the corrected docs state that
      wiring a sourced Jev rate is a YAML edit plus a small code change.
    location: >-
      monitoring/pricing.py
    severity: low
---

## Build Brief

**(1) Story:** 6.2 — Compute versioned NULL-aware model costs (sprint-status key `6-2-compute-versioned-null-aware-model-costs`).

**(2) ACs in one line each:**
- AC1: one versioned price table (`monitoring/prices.yaml`) holds per-token-type/per-model rates, each with source URL and retrieved date; the five token types (input, output, cache-read, 5m-write, 1h-write) stay distinct and fixture arithmetic checks each type.
- AC2: Claude rates are sourced from official documentation at build time (source + date recorded); the Jev (system_one) rate stays NULL/flagged (OQ-3) with no historical estimate substituted; unavailable token counters and incomplete per-run totals are visibly flagged, never silently summed as complete zero-cost usage.

**(3) Binding ADs:** AD-9 (confidence untouched — costing never reads probabilities), AD-18 (cost is computed by the orchestrator from one versioned `monitoring/prices.yaml`; an unpriced model yields a NULL cost, flagged), AD-19 (rates live only in the YAML — never in code; the loader is the one reader).

**(4) Files:** create `monitoring/prices.yaml`, `monitoring/pricing.py` (loader + frozen models), `monitoring/costs.py` (pure calculator), `workflow/usage_costs.py` (audit-row reader Protocol + Postgres adapter + per-run rollup); tests under `tests/monitoring/`, `tests/workflow/`. NOT touched: `workflow/usage_audit.py` (6.1's recorder — only read through a new small Protocol), `contracts/` (reuse `ModelUsage`), `guardrails/`, `gateway/`, `config/runtime.yaml`, migrations (no schema change — costs are computed, not stored), prompts, agents.

**(5) Approach:** the price table is data with provenance: `monitoring/prices.yaml` carries a `table_version`, per-model `usd_per_mtok` maps over the five token types, and per-model `source_url` + `retrieved`; the Jev entry is explicitly `rate: null` + `flagged: true` (OQ-3). `monitoring/pricing.py` loads it once into frozen Pydantic models with sanity checks (mirrors `workflow/thresholds.py`); `monitoring/costs.py` is pure (SOLID-S): `cost_of_usage(usage, table, *, jev)` returns per-type costs where a NULL counter or an unsourced rate yields a NULL cost plus a flag — never a zero — and `summarize_costs` rolls attempts into per-run totals that turn NULL (unknown) instead of summing incomplete parts, with the reasons listed. `workflow/usage_costs.py` (SOLID-I/D) reads 6.1's audit rows through a small `UsageAuditReader` Protocol + Postgres adapter, marks `call:system_one` rows as Jev-billed (the constant lives once in `workflow/usage_audit.py`), and computes the per-run summary via the pure calculator (AD-18: the orchestrator computes).

**(6) TDD plan (red-first; names cite ACs):** `tests/monitoring/test_pricing.py::test_ac1_price_table_is_versioned_with_provenance`, `::test_ac2_claude_rates_are_sourced_with_url_and_date`, `::test_ac2_jev_rate_is_null_and_flagged`, `::test_ac2_loader_refuses_an_unsourced_claude_model`; `tests/monitoring/test_costs.py::test_ac1_each_token_type_is_priced_distinctly` (fixture arithmetic per type), `::test_ac1_cache_write_tiers_stay_distinct`, `::test_ac2_unreported_counter_yields_null_cost_not_zero`, `::test_ac2_jev_call_cost_is_null_and_flagged`, `::test_ac2_run_total_with_incomplete_parts_is_null_and_flagged`, `::test_ac2_complete_run_total_sums_cleanly`; `tests/workflow/test_usage_costs.py::test_ac2_system_one_rows_are_jev_billed`, `::test_ac2_run_rollup_flags_incomplete_usage`; integration (marked): `tests/workflow/test_usage_costs_integration.py` (reader against real Postgres over 6.1's rows).

**(7) Risks / OQ:** OQ-3 (Jev price/billing units) is unresolved by design — the table ships the Jev rate NULL/flagged and nothing may substitute an estimate; a later story replaces null with a sourced rate. Claude rates were verified against the official pricing docs at build time (https://platform.claude.com/docs/en/about-claude/pricing, retrieved 2026-09-26): Haiku 4.5 $1/$5 in/out, cache read $0.10, 5m write $1.25, 1h write $2; Sonnet 5 $2/$10, $0.20/$2.50/$4 (USD per MTok). A conflicting older rate card (2026-07-24 PDF) shows Sonnet 5 at $3/$15 — the live docs page is treated as authoritative and the discrepancy is recorded here. No OQ blocking.

**(8) Doc impact:** `docs/DEVELOPER.md` — new "Model costs (story 6.2)" subsection (price table, NULL rules, how to add a model or replace the Jev rate), story-table and where-things-live rows; `docs/USER-GUIDE.md` — no user-visible behaviour change (costing is internal accounting): "no doc change" — reason: nothing about installing, configuring or using the tool changes.

<intent-contract>

## Intent

**Problem:** 6.1 records what each model call consumed, but nothing turns those token counters into costs from auditable rates — and an unsourced price or an unreported counter would silently become a zero, hiding real spend and faking complete totals.

**Approach:** One versioned, provenance-carrying price table plus a pure NULL-aware calculator: every token type priced distinctly from `monitoring/prices.yaml`, Claude rates sourced with URL and date, the unresolved Jev rate kept NULL and flagged, and any run with unavailable counters or unsourced rates carrying a visibly incomplete total.

## Boundaries & Constraints

**Always:** rates only from `monitoring/prices.yaml` (versioned, per-type, with source URL + retrieved date); a NULL counter or unsourced rate yields a NULL cost plus a flag, never 0; per-run totals with incomplete parts are NULL and flagged, never summed as complete; the five token types stay distinct end to end; costs are computed by orchestrator-side code (monitoring stays pure; no I/O in the calculator).

**Never:** no historical or estimated price substituted for an unsourced rate; no cost columns written back to `run_step` (costs are computed, not stored — no migration); no confidence/probability reads; no changes to 6.1's recorder or schema; no new dependencies.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Full usage, sourced Claude rate | all five counters reported | five distinct costs, arithmetic per type | No error expected |
| Unreported counter | some counter NULL | that type's cost NULL + flagged, others priced | flagged, not zero |
| Jev call | `call:system_one` row | cost NULL + flagged (OQ-3), regardless of counters | flagged |
| Incomplete run total | any attempt incomplete or Jev | per-run totals NULL + flagged with reasons | flagged |
| Complete run total | every attempt complete, no Jev | per-type totals sum cleanly | No error expected |
| Unsourced Claude model | model missing from table | loader refuses at startup | typed loader error |

</intent-contract>

## Code Map

- `contracts/usage.py` -- `ModelUsage` (five nullable counters + model); the calculator's input; reuse, do not edit.
- `workflow/usage_audit.py` -- 6.1's audit vocabulary: `CALL_STEP_PREFIX`, the `call:system_one` step name convention, `ModelCallAttempt`; the reader re-uses these facts (import the Jev step-name constant here rather than duplicating the string).
- `workflow/thresholds.py` -- the loader pattern to mirror: frozen Pydantic models, sanity checks, one reader for one YAML file.
- `workflow/db.py` -- `Connection`/`open_connection` plumbing for the Postgres reader adapter.
- `tests/fixtures/` -- test thresholds pattern; price-table fixtures are inline test data (a test YAML lives in `tests/monitoring/` if the loader needs a file).
- `monitoring/README.md` -- placeholder folder README; update to point at the price table + calculator.
- `pyproject.toml` -- PyYAML already pinned; no new dependency.

## Tasks & Acceptance

**Execution:**
- `monitoring/prices.yaml` -- create the versioned table: `table_version`, per-model five-type `usd_per_mtok` + `source_url` + `retrieved` for both allowed Claude models (sourced 2026-09-26), `jev.system_one` rate NULL + flagged -- AC1/AC2.
- `monitoring/pricing.py` -- create frozen `PriceTable`/`ModelRates` models + `load_prices()` with sanity checks (version present; every non-Jev model has all five rates + provenance; Jev NULL stays flagged) -- AC1/AC2.
- `monitoring/costs.py` -- create pure `TokenCosts`, `cost_of_usage(usage, table, *, jev)`, `summarize_costs(...)` with NULL-not-zero and incomplete-total semantics -- AC1/AC2.
- `workflow/usage_costs.py` -- create `UsageAuditReader` Protocol + `PostgresUsageAuditReader` (repo-bound read of a run's audit rows) + `run_cost_summary(...)` marking `call:system_one` as Jev -- AC2.
- `tests/monitoring/test_pricing.py`, `tests/monitoring/test_costs.py`, `tests/workflow/test_usage_costs.py`, `tests/workflow/test_usage_costs_integration.py` -- new, red-first per brief (6) -- AC proof.
- `docs/DEVELOPER.md`, `monitoring/README.md` -- per brief (8); USER-GUIDE: no doc change (reason in brief).

**Acceptance Criteria:**
- Given the price table and reported token types, when costing runs, then each of the five types is priced distinctly with fixture arithmetic, from a versioned table whose rates carry source URL and retrieved date (AC1).
- Given build-time Claude pricing and the unresolved Jev price, when rates are sourced, then Claude provenance is recorded, the Jev rate stays NULL/flagged with no estimate, and unreported counters / incomplete run totals are flagged rather than summed as zero (AC2).

## Spec Change Log

## Review Triage Log

### 2026-09-26 — Review pass
- verdicts: 32 findings — high 0, medium 3, low 27, false 2, maybe-false 0
- findings:
  - `[medium]` `[patch]` the "Jev reprice is a YAML edit, no code change" claim is false: `cost_of_usage` short-circuits on `jev=True` and never reads `table.jev`, so a sourced Jev rate would load cleanly and then be silently unused (BH2, VG-other-a, IA-jev) — patched: the claim is corrected in `prices.yaml`, the `JevRate` docstring and DEVELOPER.md to "a YAML edit plus a small wiring change in `monitoring/costs.py` once the billing units are known (OQ-3)"; the spec's Design Notes sentence is superseded by this row (the living docs carry the corrected fact).
  - `[low]` `[patch]` loader hardening batch: an absent/unreadable `prices.yaml` escapes as raw `FileNotFoundError`; rates accept negative values; the `rates.retrieved is None` half of the provenance check is dead (the field is required); a priced-but-flagged Jev entry loads silently and the estimate-refusal test passes for the wrong reason (missing provenance, not the contradiction) (EC2, BH6, EC3, BH5, CC4, VG-other-c, BH4) — patched: `OSError` wrapped into `PriceTableError`, `ge=0` on all rates and `JevRate.rate`, dead check dropped, `_sanity_checks` forbids `rate` + `flagged` together, and the test fixture now carries provenance so the refusal is genuinely about the contradiction.
  - `[low]` `[patch]` `_row_to_attempt` always constructs a `ModelUsage`, so `usage=None` is unreachable from the real reader and the docstring's "None when the provider reported nothing" is false; the lost-usage distinction 6.1's contract carries is collapsed (BH10, CC5) — patched: the adapter returns `usage=None` when all five counter columns are NULL; the rollup's fallback keeps the same computed flags; tests updated to the honest contract.
  - `[low]` `[patch]` `audit_model_call` accepts an empty `model` string, which would later crash the cost reader's `ModelUsage` validation (EC4, EC5) — patched: the wrapper refuses an empty model at write time (root fix; the reader stays unchanged); test added.
  - `[low]` `[patch]` test DRY/quality batch: `TABLE` in `test_costs.py` duplicates `FIXTURE_TABLE` verbatim; `FULL_USAGE` copy-pasted across three modules; an f-string with no placeholder; `attempt_row` hardcodes the model so no unit test proves `model_unpriced` through the rollup (CC1, CC2, CC3, BH8, BH12) — patched: shared fixture imports, `FULL_USAGE` moved to `tests/fixtures/prices.py`, f-prefix dropped, `attempt_row` gains a `model` parameter plus an unpriced-model rollup test.
  - `[low]` `[patch]` `from typing import Mapping` deprecated alias (BH9) — patched: imported from `collections.abc`.
  - `[low]` `[patch]` docs: nothing states that `run_cost_summary` has no production caller yet (consumption lands with the later-epic dashboards/exports), and the loader-refusal vs compute-time-flag distinction (plus the absent startup wiring) is undocumented (BH1, BH13, BH14, EC6, IA-no-caller) — patched: DEVELOPER.md states both facts.
  - `[low]` `[defer]` `JevRate.rate` is a single scalar and cannot express per-token-type Jev rates when OQ-3 resolves with typed billing units (BH3) — deliberate: the billing units are explicitly unresolved, so designing the schema now would speculate; the schema evolves with the sourced facts in the story that closes OQ-3. Deferred, severity low.
  - `[low]` `[reject]` the shipped-table test pins exact rates and the retrieved date (BH7) — deliberate: a reprice is a real event that must update its provenance pinning test; the fixture-table insulation applies to the calculator tests, which stay YAML-independent.
  - `[low]` `[reject]` `sum()` filters `None` despite the no-reasons invariant (BH11) — defensive and harmless; replacing it with a cast/assert is churn on a proven invariant.
  - `[low]` `[reject]` `models: {}` loads cleanly (BH13) — an emptied table is loudly visible at compute time (`model_unpriced` flags on every row), never a silent zero; a "≥1 model" check adds little beyond the flags.
  - `[low]` `[reject]` `cost_of_usage` raises `KeyError` on a hand-built table with a missing rate key (EC1) — the loader is the one entrypoint (AD-19); bypassing it is a programmer error that fails loudly.
  - `[low]` `[reject]` `model IS NOT NULL` silently drops NULL-model rows (VG-other-b) — unreachable through the only writer (the recorder always writes `model`), and the empty-model patch closes the reachable gap at the source.
  - `[false]` `[reject]` process guarantees (branch lineage, make check output, AC-by-AC proof) absent from the diff (IA-process) — a diff cannot carry process proof; verified by the orchestrator outside it.
  - `[false]` `[reject]` `summarize_costs([])` complete-at-zero (IA-summarize) — "no attempts yet" means nothing was consumed; the never-silent-zero rule concerns missing facts, not an empty set, and flagging every pre-first-call run would be noise.

## Design Notes

NULL semantics, one rule everywhere: a missing fact (unreported counter, unsourced rate) propagates as NULL + flag — never 0, never dropped. A per-run total is the sum of its parts only when every part is known; otherwise the total is NULL and the reasons are listed.

```python
costs = cost_of_usage(usage, table, jev=False)
# costs.per_type["input"] == 0.0012  (1200 tokens × $1/MTok)
# costs.per_type["output"] is None if output_tokens was unreported
# costs.complete is False, costs.flags == ("output_unreported",)
```

The Jev entry is data, not code: replacing `rate: null` with a sourced rate later is a YAML edit plus a provenance entry — no code change (AD-19).

## Verification

**Commands:**
- `.venv/bin/pytest tests/monitoring tests/workflow/test_usage_costs.py -q` -- expected: all pass, AC-named tests green.
- `.venv/bin/pytest -m integration tests/workflow/test_usage_costs_integration.py -q` -- expected: passes against the real Postgres (reads 6.1 audit rows).
- `make check` -- expected: PASS (bootstrap, layer contract, schema drift, ruff, mypy --strict, pylint duplicate-code, pytest ≥85% on contracts/guardrails/workflow).

## Auto Run Result

Status: done

**Summary:** Versioned NULL-aware costing landed: `monitoring/prices.yaml` (table_version 1; both allowed Claude models with five distinct `usd_per_mtok` rates + source URL + retrieved 2026-09-26, verified against the official pricing docs at build time; `jev.system_one` rate NULL + flagged per OQ-3, no estimate); `monitoring/pricing.py` (one loader, frozen models, sanity checks — refuses unversioned/incomplete/unsourced/negative rates and a priced-but-still-flagged Jev entry, wraps file errors as `PriceTableError`); `monitoring/costs.py` (pure calculator: NULL counter / unpriced model / Jev call → NULL cost + flag, never 0; a run total is the sum of its parts only when every part is known, otherwise NULL with reasons); `workflow/usage_costs.py` (`UsageAuditReader` Protocol + repo-bound Postgres reader over 6.1's `call:` rows, `usage=None` preserved for lost usage, `call:system_one` marked Jev via 6.1's namespace constant, `run_cost_summary` composition). No cost columns, no migration; 6.1's recorder gained only an empty-model guard. The "Jev reprice is YAML-only" claim was corrected during review: wiring a sourced Jev rate is a YAML edit plus a small change in `monitoring/costs.py` once the billing units are known.

**Files changed:**
- `monitoring/prices.yaml`, `monitoring/pricing.py`, `monitoring/costs.py`, `monitoring/__init__.py` (new) — table, loader, calculator.
- `workflow/usage_costs.py` (new) — reader + rollup.
- `workflow/usage_audit.py` — empty-model refusal in the wrapper and adapter (review root-fix).
- `tests/monitoring/test_pricing.py`, `tests/monitoring/test_costs.py`, `tests/workflow/test_usage_costs.py`, `tests/workflow/test_usage_costs_integration.py`, `tests/fixtures/prices.py` (new).
- `docs/DEVELOPER.md`, `monitoring/README.md` — per brief §8. USER-GUIDE: no doc change (internal accounting; nothing about installing/using the tool changes).

**Review findings breakdown:** 32 findings — 0 high, 3 medium, 27 low, 2 false, 0 maybe-false. 7 patch entries applied (false "YAML-only" Jev claim corrected [medium]; loader hardening — OSError wrap, ge=0 rates, dead check dropped, priced+flagged Jev refused, wrong-reason test fixed; `usage=None` preserved for lost usage in the reader; empty-model refusal at the recorder; test DRY/quality batch; deprecated typing alias; docs additions for the no-caller and refusal-vs-flag facts). 1 item deferred (low: `JevRate` single-scalar schema evolves when OQ-3 resolves with typed billing units). 24 rejected with recorded refutations in the Review Triage Log.

**Follow-up review recommendation:** false — one medium patched entry (below the two-medium threshold), no high patched; the residual risk (Jev wiring shape) is recorded as a deferral.

**Verification performed:** `make check` PASS (bootstrap; layer contract PASS; 7 schemas + state diagram byte-identical; ruff check+format clean; mypy --strict clean; pylint duplicate-code 10.00/10; 464 passed, 59 integration deselected; coverage 94.36% ≥ 85%). Integration (explicitly run, real postgres:18): `pytest -m integration tests/workflow/test_usage_costs_integration.py tests/workflow/test_usage_audit_integration.py -q` → 12 passed. Focused: 47 unit tests over the touched files. I/O matrix audit: all 6 rows covered by passing AC-named tests.

**Residual risks:** OQ-3 remains open by design (Jev rate NULL/flagged; wiring shape deferred); nothing in production calls `load_prices()` or `run_cost_summary()` yet — consumption lands with the later-epic dashboards/exports (documented in DEVELOPER.md).
