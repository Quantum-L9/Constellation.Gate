PYTHON ?= python
PIP ?= pip
PYTEST ?= pytest

.PHONY: install install-dev lint typecheck test test-unit test-integration contracts pr clean

install:
	$(PIP) install -e .

install-dev:
	$(PIP) install -e ".[dev]"

# Mirrors the CI job exactly. `ruff check` alone let a format-only failure
# reach CI, which is the class of gap a local lint target exists to prevent.
lint:
	ruff check src tests
	ruff format --check src tests

typecheck:
	mypy src

test:
	$(PYTEST) -q

test-unit:
	$(PYTEST) -q tests/boundary tests/routing tests/orchestration tests/services tests/api tests/architecture

test-integration:
	$(PYTEST) -q tests/integration

contracts:
	$(PYTHON) scripts/validate_contracts.py

# Local validation gate. This target does NOT push, publish, or open a remote
# pull request -- it is the repository's canonical pre-PR verification run.
pr: lint typecheck contracts test

clean:
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .mypy_cache .ruff_cache dist build *.egg-info
