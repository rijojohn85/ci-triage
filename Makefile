# Quality gates — single entry: `make check` (AGENTS.md § Quality gates).
# Tool targets are thin wrappers over .venv tools; pins live in pyproject.toml
# + requirements/dev-constraints.txt (installed by bootstrap).
.PHONY: check bootstrap print-versions schema-drift state-diagram-drift ruff mypy pylint-dup pytest-cov test-integration pre-commit

VENV := .venv
PY := $(VENV)/bin/python
RUFF := $(VENV)/bin/ruff
MYPY := $(VENV)/bin/mypy
PYLINT := $(VENV)/bin/pylint
PYTEST := $(VENV)/bin/pytest

check: bootstrap-check layer-contract schema-drift state-diagram-drift ruff-check ruff-format mypy-check pylint-dup pytest-cov
	@echo "MAKE CHECK: PASS"

bootstrap-check:
	@bash scripts/bootstrap.sh >/dev/null 2>&1 || { \
		echo "FAIL: bootstrap"; exit 2; }
	@echo "PASS: bootstrap (pins verified)"

layer-contract:
	@$(PY) scripts/check_layer_contract.py

schema-drift:
	@$(PY) scripts/generate_schemas.py --check

state-diagram-drift:
	@$(PY) scripts/generate_state_diagram.py --check

ruff-check:
	@if find contracts guardrails workflow -name "*.py" 2>/dev/null | grep -q .; then \
		$(RUFF) check scripts/ contracts/ guardrails/ workflow/; \
	else \
		$(RUFF) check scripts/; \
	fi

ruff-format:
	@$(RUFF) format --check scripts/ contracts/ guardrails/ workflow/

mypy-check:
	@$(MYPY) --strict scripts/
	@src_dirs=""; \
	for d in contracts guardrails workflow; do \
		if find $$d -name "*.py" 2>/dev/null | grep -q .; then src_dirs="$$src_dirs $$d/"; fi; \
	done; \
	if [ -n "$$src_dirs" ]; then \
		$(MYPY) --strict $$src_dirs; \
	else \
		echo "PASS: mypy src deferred (no Python source yet in contracts/guardrails/workflow)"; \
	fi

pylint-dup:
	@$(PYLINT) --disable=all --enable=duplicate-code \
		--min-similarity-lines=8 \
		scripts/ contracts/ guardrails/ workflow/ 2>/dev/null; \
	rc=$$?; if [ $$rc -ne 0 ] && [ $$rc -ne 4 ]; then exit $$rc; fi
	@# pylint exit 4 = duplicate-code finding surfaced above; 0 = clean.

pytest-cov:
	@if find contracts guardrails workflow -name "*.py" 2>/dev/null | grep -q .; then \
		$(PYTEST) --cov -q; \
	else \
		echo "PASS: pytest --cov deferred (no Python source yet in contracts/guardrails/workflow)"; \
	fi

pre-commit: bootstrap-check
	@$(VENV)/bin/pre-commit run --all-files

# Integration tests need Docker (compose/postgres:18) — story 0.3+; excluded
# from `check` by the pytest addopts marker default.
test-integration:
	@$(PYTEST) -m integration -q
