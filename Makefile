# ── Config ──────────────────────────────────────────────────────────────────
PKG_NAME := bw-proxy
PKG_DIR  := src/bw_proxy
VERSION  := $(shell grep -m 1 version pyproject.toml | tr -s ' ' | tr -d '"' | tr -d "'" | cut -d' ' -f3)

# 🛠️ Robust path discovery (detecting real user home even under sudo/sui)
REAL_USER := $(if $(SUDO_USER),$(SUDO_USER),$(USER))
REAL_HOME := $(shell getent passwd $(REAL_USER) | cut -d: -f6)
REAL_UID  := $(shell id -u $(REAL_USER))
REAL_GID  := $(shell id -g $(REAL_USER))
ZSH_LOGIN := zsh -l -c
UV        := $(shell command -v uv 2>/dev/null || ls $(REAL_HOME)/.local/bin/uv 2>/dev/null || echo uv)
PYTHON    := $(UV) run python
PYTEST    := $(PYTHON) -m pytest
APPARMOR_TARGET := /etc/apparmor.d/opt.bw-proxy.bin.bw-proxy
DOCKER_IMAGE := $(PKG_NAME):latest
DOCKER_VOLUME := bw_mcp_bw-data
DOCKER_ENV_PATH := $(REAL_HOME)/.bw/proxy/docker.env

.DEFAULT_GOAL := help

help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Dev & Test ──────────────────────────────────────────────────────────────

link:  ## Install package in editable mode (user)
	@$(UV) tool install --editable . --force

unlink:  ## Uninstall tool
	@$(UV) tool uninstall $(PKG_NAME)

test: ## Run the full pytest suite
	@$(PYTEST) -q

test-cli: ## Run CLI-focused pytest coverage only
	@$(PYTEST) -q tests/test_cli_audit.py tests/test_daemon.py tests/test_docker_shim.py tests/test_logic.py

test-core: ## Run the core pytest suite (no benchmark)
	@$(PYTEST) -q tests

bench-cli: ## Run the ad hoc CLI performance benchmark
	@$(PYTHON) scripts/perf_audit.py

check:  ## Standard quality check: compile + test
	@python3 -m py_compile $$(find src tests -name '*.py' 2>/dev/null)
	@$(MAKE) test

clean-scratch: ## Remove transient scratch artifacts
	@find scratch -maxdepth 1 \( -name 'live_*' -o -name 'test_type.py' \) -delete
	@find scratch -type d -name '__pycache__' -prune -exec rm -rf {} +

# ── Docker (Source Mode) ─────────────────────────────────────────────────────

docker-build: ## Build the local Docker image (No-Cache)
	@docker build --no-cache -t $(DOCKER_IMAGE) .

docker-volume: ## Ensure the persistent Docker data volume exists
	@docker volume create $(DOCKER_VOLUME) > /dev/null

docker-config: ## Sync non-secret Docker runtime config
	@mkdir -p $(REAL_HOME)/.bw/proxy
	@if [ -f .env ]; then \
		cp .env $(DOCKER_ENV_PATH); \
		echo "✅ Synced .env to $(DOCKER_ENV_PATH)"; \
	elif [ ! -f $(DOCKER_ENV_PATH) ]; then \
		cp .env.example $(DOCKER_ENV_PATH); \
		echo "✅ Seeded $(DOCKER_ENV_PATH) from .env.example"; \
	else \
		echo "✅ Keeping existing Docker env at $(DOCKER_ENV_PATH)"; \
	fi

docker-link: ## Create a host-side wrapper (symlink) to source shim
	@mkdir -p $(REAL_HOME)/.local/bin
	@chmod +x scripts/bw_proxy_shim.py
	@ln -sf $(CURDIR)/scripts/bw_proxy_shim.py $(REAL_HOME)/.local/bin/$(PKG_NAME)
	@echo "✅ Source-mode shim installed in $(REAL_HOME)/.local/bin/$(PKG_NAME)"

docker-install: docker-build docker-volume docker-config docker-link ## Full Source-to-Docker installation

docker-uninstall: ## Remove Docker artifacts, preserve data
	@echo "🗑️ Removing Docker shim and image..."
	@rm -f $(REAL_HOME)/.local/bin/$(PKG_NAME)
	@docker rmi $(DOCKER_IMAGE) 2>/dev/null || true

docker-purge: docker-uninstall ## Destructive: remove Docker volume and host config
	@echo "🔥 Purging Docker volume and config..."
	@docker volume rm $(DOCKER_VOLUME) 2>/dev/null || true
	@rm -rf $(REAL_HOME)/.bw/proxy

# ── Release & CD ──────────────────────────────────────────────────────────────

build:  ## Build package with uv
	@rm -rf dist && $(UV) build

tag: ## Create a new git tag based on pyproject.toml version
	@echo "🏷️ Tagging version v$(VERSION)..."
	@git tag -a v$(VERSION) -m "Release v$(VERSION)"

push:  ## Push current branch to ALL remotes
	@branch="$$(git branch --show-current)"; \
	for remote in $$(git remote); do \
		echo "==> Pushing $$branch to $$remote..."; \
		git push "$$remote" "$$branch"; \
	done

push-tags:  ## Push all tags to ALL remotes
	@for remote in $$(git remote); do \
		echo "==> Pushing tags to $$remote..."; \
		git push "$$remote" --tags; \
	done

release: check build tag push push-tags ## Full Release: check → build → tag → push-all

# ── Git Utils ─────────────────────────────────────────────────────────────────

git-status: ## Show git status short
	@git status --short

git-log: ## Show last 10 commits
	@git log --oneline -10
