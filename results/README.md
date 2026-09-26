results/ — final verdicts/artifacts per run.

- `jev-eval/<YYYY-MM-DD>-<model-id>/` — the story 3.2 Jev classification eval
  receipts (committed evidence, un-ignored in `.gitignore`). The date is the
  local system date; the model id's `/` becomes `-`. One directory per run:
  - `summary.md` — the human-readable receipt: verdict, run provenance (model
    id + provider-reported model, `prompts/jev-classes.yaml` sha256, git commit,
    date, repeats), case counts per kind/class/repo, the per-class accuracy and
    confusion matrix, the trick-case table, the OQ-1 bars with each value,
    confident-wrong attempts with their caps, repeat inconsistencies and the
    required caveats.
  - `summary.json` — the same, machine-readable (every attempt, both confidence
    numbers, the caps, token totals and the bar outcomes).
  - `promptfoo-output.json` — the complete promptfoo report for the run.

  Produced by `make eval-jev` (`scripts/run_jev_eval.py`); see
  [docs/DEVELOPER.md](../docs/DEVELOPER.md) "The Jev eval (story 3.2)".

Other run artifacts are written at runtime by later stories and stay ignored
(only READMEs and the Jev eval receipts are committed).
