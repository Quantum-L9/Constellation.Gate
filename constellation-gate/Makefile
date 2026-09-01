PYTHON ?= python
PIP ?= pip
PYTEST ?= pytest

.PHONY: install install-dev lint typecheck test test-unit test-integration pr pr-check clean

install:
	$(PIP) install -e .

install-dev:
	$(PIP) install -e ".[dev]"

# Mirrors the CI job exactly. `ruff check` alone lets a format-only failure
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

# Local validation gate. This target runs checks only -- it does not push,
# tag, or open a pull request. Publication remains a deliberate, separate act.
pr: lint typecheck test
	@echo "pr: validation gate passed (lint + typecheck + test)"

# Alias so either spelling reaches the same gate.
pr-check: pr

clean:
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .mypy_cache .ruff_cache dist build *.egg-info
