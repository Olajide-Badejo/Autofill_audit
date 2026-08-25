# The commands of spec section 3.2, identical for CI and for a human.
#
# Every target runs through $(PY), which defaults to the project venv created at
# P0. Activate the venv and run `make gates`, or override the interpreter:
#
#     make gates                                   uses ~/.venvs/autofill-audit
#     make gates PY=python                         uses whatever is on PATH (CI does this)
#     make gates VENV=/some/other/venv             uses another venv
#
# `make gates` runs the six checks in the order CI runs them, so a red gate here
# is the same red gate there.

VENV ?= $(HOME)/.venvs/autofill-audit
PY ?= $(VENV)/bin/python
PIP_COMPILE ?= $(PY) -m piptools compile

.DEFAULT_GOAL := gates
.PHONY: gates lint type test reach trace dashes build lock reports clean help

help:
	@echo "targets: gates lint type test reach trace dashes build lock reports clean"

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

type:
	$(PY) -m mypy --strict src/

test:
	$(PY) -m pytest -q --cov=src/autofill_audit --cov-report=term-missing --cov-fail-under=90

reach:
	$(PY) scripts/check_reachability.py

trace:
	$(PY) scripts/check_traceability.py

dashes:
	$(PY) scripts/check_dashes.py

# The order here is the order of the CI job table in spec section 16.
gates: lint dashes type test reach trace
	@echo "all gates passed"

build:
	$(PY) -m build

# Regenerating the lock file is a deliberate commit with a CHANGELOG note, never
# a side effect of another target (spec section 18).
lock:
	$(PIP_COMPILE) --strip-extras --extra dev --extra llm \
		--output-file requirements.lock pyproject.toml

# The report engine resolved at P0 is latexmk over the TeX Live installation
# already present on the build machine (ADR 0001). Report sources are authored
# at P7; until then this target has nothing to build and says so.
reports:
	@for dir in report report_debug report_for_me; do \
		if [ -d "$$dir" ]; then \
			latexmk -pdf -interaction=nonstopmode -halt-on-error -cd "$$dir"/*.tex; \
		else \
			echo "reports: $$dir not authored yet (phase P7)"; \
		fi; \
	done

clean:
	rm -rf build dist .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
