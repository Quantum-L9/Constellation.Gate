PYTHON ?= python
PIP ?= pip
PYTEST ?= pytest

.PHONY: install install-dev lint typecheck test test-unit test-integration clean

install:
	$(PIP) install -e .

install-dev:
	$(PIP) install -e ".[dev]"

lint:
	ruff check src tests

typecheck:
	mypy src

test:
	$(PYTEST) -q

test-unit:
	$(PYTEST) -q tests/boundary tests/routing tests/orchestration tests/services tests/api tests/architecture

test-integration:
	$(PYTEST) -q tests/integration

clean:
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .mypy_cache .ruff_cache dist build *.egg-info

------------








```yaml
