# Local development for the software factory. `make check` is the bar before hand-off;
# `make drive` is the extra bar for install/ and cli.py changes, where a green suite has
# repeatedly not been enough. uv owns the environment — no manual venv activation.

.DEFAULT_GOAL := help
.PHONY: help dep test lint fix check drive diagram clean clean-all

help: ## List these targets
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk -F':.*?## ' '{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

dep: ## Sync the project venv from uv.lock (dev group included)
	uv sync --group dev

test: ## Run the test suite
	uv run pytest

lint: ## Lint everything, install/ and scripts/ included
	uv run ruff check .

# Deliberately no `ruff format` target: the repo isn't format-clean, so one would
# bury a small change under a dozen reformatted files. This applies lint fixes only.
fix: ## Apply ruff's safe autofixes (imports, unused, upgrades)
	uv run ruff check --fix .

check: lint test ## Lint + test — run this before handing work off

drive: ## Drive the real installer and the real CLI against throwaway repos
	python3 scripts/drive_install.py
	python3 scripts/drive_cli.py

diagram: ## Re-render docs/diagram.png from docs/diagram.md
	./scripts/render-diagram.sh

clean: ## Remove caches and build junk (keeps .venv)
	find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	find . -name '*.py[co]' -delete
	rm -rf .pytest_cache .ruff_cache dist build *.egg-info src/*.egg-info

clean-all: clean ## Also remove .venv — next `make dep` rebuilds it from uv.lock
	rm -rf .venv
