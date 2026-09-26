results/ — final verdicts/artifacts per run.

- `jev-eval/<YYYY-MM-DD>-<model-id>[-<label>]/` — the story 3.2 Jev
  classification eval receipts (committed evidence, un-ignored in `.gitignore`).
  The date is the local system date; the model id's `/` becomes `-`; the
  optional `--label` suffix (story 3.12) names a run (e.g. `-before`/`-after`)
  so an eval-first pair never overwrites the 3.2 receipt or each other. One
  directory per run:
  - `summary.md` — the human-readable receipt: verdict, run provenance (model
    id + provider-reported model, `prompts/jev-classes.yaml` sha256, git commit,
    date, repeats), case counts per kind/class/repo, the per-class accuracy and
    confusion matrix, the trick-case table, the OQ-1 bars with each value,
    confident-wrong attempts with their caps, repeat inconsistencies and the
    required caveats.
  - `summary.json` — the same, machine-readable (every attempt, both confidence
    numbers, the caps, token totals and the bar outcomes).
  - `promptfoo-output.json` — the complete promptfoo report for the run.
  - `comparison.md` — the before/after table, written only when `--compare`
    names one or more baseline receipt directories (story 3.12): one column per
    receipt (baselines in the order given, then this run) and one row per
    headline metric (verdict, overall and per-class accuracy, confident-wrong,
    trick pass rate, evidence retention).

  Produced by `make eval-jev` (`scripts/run_jev_eval.py`); `EVAL_ARGS` forwards
  `--label`/`--compare` so a labelled run stays `make eval-jev`. See
  [docs/DEVELOPER.md](../docs/DEVELOPER.md) "The Jev eval (story 3.2)".

  **Superseded.** `jev-eval/2026-09-27-typesafe-jev-1.13/` is the story 3.2
  baseline. It is kept unchanged as historical evidence, but it was produced
  before story 3.11 guarded the case generator — it carries no
  evidence-retention count and its `unknown` cases shared a runner-provisioner
  block — so it is superseded by the story 3.12 eval-first pair:
  `jev-eval/2026-09-27-typesafe-jev-1.13-before/` (run A, the unchanged prompt,
  the red eval) and `jev-eval/2026-09-27-typesafe-jev-1.13-after/` (run B, the
  CI-platform convention in `prompts/jev-classes.yaml`; **current**), whose
  `comparison.md` carries the 3.2 → A → B table. The 3.2 receipt is named as
  the baseline in that table.

Other run artifacts are written at runtime by later stories and stay ignored
(only READMEs and the Jev eval receipts are committed).
