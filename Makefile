# Local quality gates — keep in sync with .github/workflows/ci.yml
# See docs/V2/BEST_PRACTICES.md §11.
.PHONY: help install lint format typecheck test test-integration cov build audit ci clean conformance

PYTHON ?= python3
PIP ?= pip
COV_FAIL_UNDER ?= 75
PYTEST_FLAGS ?= -q -m "not integration"

help:
	@echo "Targets: install lint format typecheck test conformance cov build audit ci clean"

install:
	$(PIP) install -U pip
	$(PIP) install -e ".[dev]"

lint:
	ruff check src tests
	ruff format --check src tests

format:
	ruff check --fix src tests
	ruff format src tests

typecheck:
	mypy

test:
	pytest $(PYTEST_FLAGS)

conformance:
	$(PYTHON) tests/conformance/run_suite.py

cov:
	pytest $(PYTEST_FLAGS) \
	  --cov=zeus_client \
	  --cov-report=term-missing \
	  --cov-fail-under=$(COV_FAIL_UNDER)

test-integration:
	pytest -q -m integration

build:
	rm -rf dist build
	$(PYTHON) -m build
	twine check dist/*

audit:
	pip-audit

ci: lint typecheck cov build
	@echo "ci OK"

clean:
	rm -rf dist build .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml
