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
.PHONY: gates lint type test reach trace ancestry dashes build lock tables reports \
	reports-clean clean help

help:
	@echo "targets: gates lint type test reach trace ancestry dashes build lock"
	@echo "         tables reports reports-clean clean"

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
	$(PY) scripts/check_traceability.py --resolve

ancestry:
	$(PY) scripts/check_prediction_ancestry.py

dashes:
	$(PY) scripts/check_dashes.py

# The order here is the order of the CI job table in spec section 16.
gates: lint dashes type test reach trace ancestry
	@echo "all gates passed"

build:
	$(PY) -m build

# Regenerating the lock file is a deliberate commit with a CHANGELOG note, never
# a side effect of another target (spec section 18).
lock:
	$(PIP_COMPILE) --strip-extras --extra dev --extra llm \
		--output-file requirements.lock pyproject.toml

# Every table and every figure in the reports is generated from a committed
# result file. A hand typed table is a law 3 violation regardless of how good it
# looks, so generation is a prerequisite of the build rather than a step
# somebody remembers.
tables:
	$(PY) scripts/make_report_tables.py
	$(PY) scripts/make_report_figures.py

# The report engine resolved at P0 is latexmk over the TeX Live installation
# already present on the build machine (ADR 0001).
#
# `-auxdir=build` puts every intermediate file in each report's own build
# directory, which .gitignore ignores, and leaves the compiled PDF beside its
# source, which is committed. Spec section 17.2 names the main report's
# deliverable path as report/build/main.pdf and section 17.3 names the debug
# report's as report_debug/debug_report.pdf, which are two different
# conventions; the .gitignore committed at P0 ignores build/ directories, so
# the two deliverables sit at symmetric paths beside their sources rather than
# one of them living inside an ignored directory behind a negation rule.
#
# report_for_me/ is built when it is present and is never committed, per the
# author's standing instruction. Its absence is not an error.
REPORTS := report/main.tex report_debug/debug_report.tex report_for_me/report_for_me.tex

# Rebuilding a report produces the same bytes, and the mechanism deliberately
# lives in the sources rather than here.
#
# pdftex stamps a creation timestamp and a random trailer id into every PDF, and
# matplotlib's PDF backend stamps a creation date. Either would make a
# regenerated artefact differ from the committed one on every run, so
# `make reports-clean reports` would always leave a dirty tree and nobody could
# tell a rebuild of unchanged sources from one that actually changed something.
#
# Both are suppressed at the point of writing rather than by exporting a build
# epoch here: report/preamble.tex sets the pdftex primitives that omit the
# timestamps and fix the trailer id, and scripts/make_report_figures.py passes
# metadata that omits the creation date. That is stronger than an environment
# variable, because it also holds when somebody runs latexmk or the figure
# script by hand instead of going through this file.

reports: tables
	@for source in $(REPORTS); do \
		if [ -f "$$source" ]; then \
			echo "reports: building $$source"; \
			latexmk -pdf -auxdir=build -interaction=nonstopmode -halt-on-error \
				-cd "$$source" || exit 1; \
		else \
			echo "reports: $$source is not present, skipping"; \
		fi; \
	done
	@echo "reports: all present reports built"

clean:
	rm -rf build dist .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

# Everything `make reports` produces, so that `make reports-clean reports`
# demonstrates a build from nothing. The compiled PDFs go too: a target that
# left them in place could not tell a successful rebuild from a stale artefact.
reports-clean:
	rm -rf report/build report_debug/build report_for_me/build
	rm -rf report/tables report/figures
	rm -f report/main.pdf report_debug/debug_report.pdf report_for_me/report_for_me.pdf
