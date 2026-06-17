# Open Omniscience — developer convenience targets.
# Single source of truth is pyproject.toml; this just wraps common commands.
.DEFAULT_GOAL := help
PY ?= python

.PHONY: help install install-dev test lint format typecheck migrate seed run check clean dist release-dryrun

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

install: ## Install the app + analysis extra
	$(PY) -m pip install -e ".[analysis]"

install-dev: ## Install with analysis + dev tooling
	$(PY) -m pip install -e ".[analysis,dev]"

test: ## Run the test suite
	$(PY) -m pytest -q

lint: ## Lint with ruff
	ruff check src/ tests/

format: ## Auto-format with ruff
	ruff format src/ tests/
	ruff check --fix src/ tests/

typecheck: ## Type-check with mypy
	mypy src/

migrate: ## Apply database migrations
	alembic upgrade head

seed: ## Seed the curated source catalog
	$(PY) scripts/seed_sources.py

run: ## Run the app on 127.0.0.1:8000 (loopback only)
	open-omniscience

check: lint test ## Lint + test (what CI runs)

dist: ## Build the sdist + wheel into dist/
	$(PY) -m build --outdir dist

release-dryrun: dist ## Build artifacts + SHA256SUMS locally (what the release tag does, minus publish)
	cd dist && sha256sum *.whl *.tar.gz > SHA256SUMS && cat SHA256SUMS
	@echo "Artifacts + SHA256SUMS in dist/. The release workflow (.github/workflows/release.yml) does this on a 'v*' tag and publishes a GitHub Release with the checksums in the notes."

clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .ruff_cache build dist *.egg-info
	find . -type d -name __pycache__ -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null || true
