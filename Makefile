# uv owns the environment; no manual venv activation.

.DEFAULT_GOAL := help
.PHONY: help dep test lint fix check clean

help: ## List these targets
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk -F':.*?## ' '{printf "  \033[36m%-8s\033[0m %s\n", $$1, $$2}'

dep: ## Sync the project venv from uv.lock (dev group included)
	uv sync --group dev

test: ## Run the test suite
	uv run pytest -q

lint: ## Lint
	uv run ruff check .

fix: ## Apply ruff's safe autofixes
	uv run ruff check --fix .

check: lint test ## Lint + test — the bar before hand-off

clean: ## Remove caches and build junk (keeps .venv)
	find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache dist build *.egg-info
