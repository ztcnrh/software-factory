# uv owns the environment; no manual venv activation.

.DEFAULT_GOAL := help
.PHONY: help dep test lint fix check drive clean

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

# Installs into the sandbox and exercises labels/board/apply/gate against a throwaway issue.
# Needs `gh` authenticated for the sandbox repo and SANDBOX set to its checkout; never run in CI.
drive: ## Smoke the installer and the CLI against a sandbox repo (SANDBOX=<path>)
	./tests/drive.sh

clean: ## Remove caches and build junk (keeps .venv)
	find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache dist build *.egg-info
