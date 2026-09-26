monitoring/ — run telemetry computed from the audit. Story 6.2 fills this
folder with the versioned price table (`prices.yaml`), its one loader
(`pricing.py`) and the pure NULL-aware cost calculator (`costs.py`; AD-18,
AD-19). The orchestrator-side reader that rolls story 6.1's audit rows
into per-run costs lives in `workflow/usage_costs.py`; see
[docs/DEVELOPER.md](../docs/DEVELOPER.md), "Model costs (story 6.2)".
Dashboards and alerts remain later-epic work (see epics.md).
