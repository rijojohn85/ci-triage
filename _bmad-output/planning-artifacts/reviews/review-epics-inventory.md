# Review — epics.md requirements inventory (step-01)

- Target: `_bmad-output/planning-artifacts/epics.md` (not edited)
- Sources compared: SPEC.md, scope.md, scenarios.md, verification.md, spec .memlog.md; ARCHITECTURE-SPINE.md (FINAL); redteam-plan.md
- Date: 2026-09-25

## Verdict

**PASS with fixes.** Fidelity is clean: FR1–FR6 match CAP-1..CAP-6 verbatim, and a mechanical diff of spine lines 53–427 against epics.md lines 77–450 shows AD-1..AD-27, Consistency Conventions (all enums), Stack, Structural Seed and the tree are **byte-identical**. There is no weakening of AD-9, AD-13, AD-14, AD-16, AD-21, AD-23 or AD-27. The late resolutions are reflected correctly: S5 is high-risk/gate_blocked, OQ-6 is WON'T, demo-repo.md is included, and OQ-5 is limited to calibration. No stale "high risk or low confidence" S5 wording or open OQ-6 appears. No findings are High. The Medium findings are gaps and structural issues that could make story drafting diverge.

## 1. Fidelity

| Check | Result | Evidence |
| --- | --- | --- |
| CAP-1..CAP-6 intent/success/trace | Verbatim | epics.md:27–55 vs SPEC.md:24–52 |
| AD-1..AD-27 rules | Verbatim (diff empty) | epics.md:77–352 vs spine:53–328 |
| Enums (class, risk_tier, terminal_state, escalation_reason, citation kinds, objection severity, skill catalogue) | Verbatim | epics.md:81, 151–157, 163, 354–369 |
| Stack pins / tree | Verbatim | epics.md:371–450 |
| Spine Design Paradigm layer "May call" table | **Missing** | spine:22–49 not copied (F3) |
| Spine `## Deferred` | **Missing, no note** | spine:428–443 (F9) |
| NFR paraphrases vs AD rules | Faithful. Minor trace/wording drift in NFR1 and NFR4 | F8 |

## 2. Staleness

- S5: epics.md:506, 569, 580 all say high-risk timeout-bump / `gate_blocked`. OK.
- OQ-6: epics.md:491, 570 say WON'T v1. OK. Open list (561–565) has OQ-1..OQ-5 only. OK.
- OQ-5: scoped to calibration sample count/repeats/variants (565, 581). OK.
- Demo repo: epics.md:529 (`test-data/demo-repo.md`), 576 (E0 demo-repo setup). OK.
- Residual: epics.md:510 (verbatim from scenarios.md:15) still lists "the low-confidence escalation branch" **and** "high-risk and low-confidence branches". After the resolution, "high-risk" is S5 itself and low-confidence appears twice (F7).
- Residual: inputDocuments includes spec `.memlog.md`, whose lines 25–26 still hold the pre-resolution OQ-5/OQ-6 questions. They are superseded by memlog lines 31–33 but could be misread (F10).

## 3. Completeness

The nine NFRs are all sourced. None is invented:

| NFR | Source |
| --- | --- |
| NFR1 | SPEC:57; AD-5/11/25; OQ-4 |
| NFR2 | SPEC:58; AD-1–4, 15, 23 |
| NFR3 | SPEC:59; AD-3, 5, 14–17 |
| NFR4 | SPEC:60; AD-6–9, 20, 24, 27 |
| NFR5 | AD-1 (N workers), AD-5 step_timeout, AD-8, AD-17 limits, AD-22; scenarios:13 "without occupying a worker"; scope:26 no TTL |
| NFR6 | verification:19, 27; AD-19 |
| NFR7 | verification:29; AD-18 |
| NFR8 | scenarios:3; AD-25 |
| NFR9 | verification:39–41; redteam-plan:5 |

Checklist coverage:

| Required item | Present? | Where |
| --- | --- | --- |
| Rubric layout paths | Yes | epics.md:519–535 |
| 4 per-agent root test.yaml | Yes | 533, NFR6 |
| 3 Proposer variants | Yes | 64, 369, 468, 533 |
| NULL cost semantics | Yes | 65, 280–281, 543, 563 |
| Deterministic RT-01/03/04/05/06/07 | Yes | 553 |
| Branch tests outside 5/5 | Yes | 510, 580 |
| tests/security/ | Yes | 445, 531 |
| SPEC Non-goals list | **No**. scope copy (481) points to "Non-goals in SPEC.md", which is not in the inventory | F1 |
| SPEC Success signal / hard Stage 4 layout constraint | **Not as requirements** | F1 |
| RT-01..RT-08 catalogue (per-case target, plugins, expected safe behaviour, severity scale, findings template) | Only by reference | F4 |

## 4. Scope hygiene

- MUST/SHOULD/COULD/Deferred/WON'T are copied verbatim from scope.md (476–481), and decomposition rule 579 commits MUST only. OK.
- No answers to OQ-1..OQ-5 are invented. The 0.75/0.6 figures appear only as "placeholders" (562). OK.
- No v2 items appear in MUST. Risk: several verbatim MUST ADs name SHOULD artefacts in their Binds/Rule: AD-9 and AD-27 bind "Triage Card", and AD-17 accepts `issue_comment`. Without a note, a CAP-1 or CAP-2 story could pull these SHOULD features into MUST (F6).
- The spine's Deferred list (omitted) says "Second language: COULD". The user's latest scope overrides this (473), so omitting it is correct, but the omission is undocumented (F9).

## 5. Story-drafting divergence risks

- **Heading hierarchy (F2).** The embedded copies keep their original heading levels:
  - H2 at 354, 371, 387, 457, 475, 483, 489, 517, 539, 545, 567
  - H1 at 455, 496, 515

  As a result, "Story decomposition constraints", "UX Design Requirements" and "FR Coverage Map" (573–590) sit under `## Resolved` instead of under `## Requirements Inventory`. Step-02 and later steps insert content by section, so placement could go wrong.
- **Stage-2 description-fallback routing (F5).** CAP-3 (39) requires that "exact and Jev description-fallback routes are demonstrated" (MUST). RT-05 routing promptfoo is deferred (480, 553), and S1–S5 will likely all route by exact match. The inventory does not say which test or receipt demonstrates the fallback route, so drafters may either drop it or reopen deferred RT-05.
- **Duplication.** FR1–FR6 plus NFR1–9 plus verbatim scope/scenarios/verification repeat the same obligations (e.g. NULL cost appears in 4 places). Stories should cite one canonical line. Recommend the FR Coverage Map name the canonical source per item.

## Findings

| # | Sev | Where | Finding | Fix |
| --- | --- | --- | --- | --- |
| F1 | M | epics.md:481 (dangling ref); SPEC.md:61, 64–72 | The SPEC Non-goals list, Success signal and hard Stage 4 layout constraint are not in the inventory. The WON'T tier points at text drafters won't see. | Add a "WON'T/v2 (SPEC Non-goals)" block and the Success-signal and hard-layout bullets verbatim under Additional Requirements. |
| F2 | M | epics.md:354, 371, 387, 455–489, 496, 515–545, 567 | Embedded H1/H2 headings break the hierarchy. The decomposition constraints, UX and FR Coverage Map fall under `## Resolved`. | Demote the embedded headings to H4 or lower so everything stays under `## Requirements Inventory` / `### Additional Requirements`. |
| F3 | M | spine:22–49 (not copied) | The spine's layer "May call" table is missing: guardrails call contracts only; agents may not call GitHub or Postgres; punch-out calls the orchestrator A2A endpoint only; gateway only enqueues to Postgres. Stories need it for boundary/import tests. | Copy the Design Paradigm table and dependency diagram verbatim into Binding architecture. |
| F4 | M | epics.md:44, 547–555; redteam-plan:58–164 | The RT-01..RT-08 catalogue is only referenced. RT-02 (Jev flip, PF-test assert class==code or confidence<threshold) and RT-08 (harmful plus jailbreak) appear nowhere by name. The severity scale and findings template are not inlined. | Add an RT table (ID, target, PF plugin or pytest, expected safe behaviour, layer) plus severity/status definitions, with verification.md reconciliations noted. |
| F5 | M | epics.md:39 vs 480, 553 | MUST "Jev description-fallback route demonstrated" has no designated receipt, and RT-05 routing promptfoo is deferred. Drafters may drop the requirement or reopen RT-05. | Add a note: fallback routing is shown by a MUST branch/integration test outside 5/5 (registry fixture forcing a Stage-2 route, with run_step receipt). This is separate from deferred RT-05. |
| F6 | M | epics.md:173, 265, 347 | Verbatim MUST ADs bind SHOULD artefacts: Triage Card (AD-9, AD-27) and `issue_comment` intake (AD-17). CAP-1/CAP-2 stories could commit SHOULD work. | Add a scope note: `issue_comment` handling and Triage Card consumers belong only to the SHOULD backlog. MUST gateway accepts `workflow_run` completed/failure only. |
| F7 | L | epics.md:510 | The branch list is redundant after the S5 resolution. "High-risk" is now S5, and low-confidence is listed twice. This could produce duplicate stories. | Annotate: the high-risk gate is covered by S5 plus RT-07 per-rule pytest. The low-confidence branch is one test outside 5/5. |
| F8 | L | epics.md:59, 62 | NFR1 traces AD-19 in place of SPEC's AD-10. NFR4 says "uncertain" output, where AD-27 says "`confidence` below the class cutoff" plus AWAITING_APPROVAL/REPORTING. | Restore the SPEC:57 trace (AD-5, AD-10, AD-11, AD-25). Use AD-27's exact trigger wording in NFR4. |
| F9 | L | spine:428–443 omitted silently | The spine Deferred section is dropped without a note. Lost detail: "SHOULD items read TriageVerdict/pr_feedback and write via AD-3 keys", "signed cards/OTel/DBOS v2", "0.75/0.6 [ASSUMPTION]". Its "Second language COULD" is superseded. | Add a one-line note: Deferred is superseded by scope.md, except that SHOULD writes use AD-3 keys. Carry that line into the SHOULD backlog. |
| F10 | L | epics.md:2, 10 | `stepsCompleted: []` despite extraction being done. inputDocuments lists the spec `.memlog.md`, which still contains the pre-resolution OQ-5/OQ-6 questions (memlog:25–26). | Record step-01 in stepsCompleted on confirmation. Note that SPEC.md "Resolved" supersedes memlog:25–26. |
