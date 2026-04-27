# ── Config ──────────────────────────────────────────────────────────────────
PKG_NAME := bw-proxy
PKG_DIR  := src/bw_proxy

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
VERSION := $(shell grep -m 1 version pyproject.toml | tr -s ' ' | tr -d '"' | tr -d "'" | cut -d' ' -f3)

help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | \
	sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

release: ## Create and push a new git tag based on pyproject.toml version
	@echo "🚀 Releasing version v$(VERSION)..."
	@git tag -a v$(VERSION) -m "Release v$(VERSION)"
	@git push origin master
	@git push origin v$(VERSION)
	@echo "✅ Tag v$(VERSION) pushed. GitHub Action will now build the GHCR image."

# ── Dev ──────────────────────────────────────────────────────────────────────

link:  ## Install package in editable mode (user)
	@$(UV) tool install --editable . --force

unlink:  ## Uninstall tool
	@$(UV) tool uninstall $(PKG_NAME)

test: ## Run the full pytest suite
	@$(PYTEST) -q

test-cli: ## Run CLI-focused pytest coverage only
	@$(PYTEST) -q tests/test_cli_audit.py tests/test_daemon.py tests/test_docker_shim.py tests/test_logic.py

test-core: ## Run the non-benchmark pytest suite
	@$(PYTEST) -q tests

bench-cli: ## Run the ad hoc CLI performance benchmark
	@$(PYTHON) scripts/perf_audit.py

check:  ## py_compile + pytest + CLI audit
	@python3 -m py_compile $$(find src tests -name '*.py' 2>/dev/null)
	@$(MAKE) test

clean-scratch: ## Remove transient scratch artifacts that should never be committed
	@find scratch -maxdepth 1 \( -name 'live_*' -o -name 'test_type.py' \) -delete
	@find scratch -type d -name '__pycache__' -prune -exec rm -rf {} +

# ── Docker ───────────────────────────────────────────────────────────────────

docker-build: ## Build the BW-Proxy Docker image (No-Cache)
	@docker build --no-cache -t $(DOCKER_IMAGE) .

docker-volume: ## Ensure the persistent Docker data volume exists
	@docker volume create $(DOCKER_VOLUME) > /dev/null

docker-config: ## Sync non-secret Docker runtime config to ~/.bw/proxy/docker.env
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

docker-link: ## Create an agnostic host-side wrapper (symlink) to execute commands in the container
	@mkdir -p $(REAL_HOME)/.local/bin
	@chmod +x scripts/bw_proxy_shim.py
	@ln -sf $(CURDIR)/scripts/bw_proxy_shim.py $(REAL_HOME)/.local/bin/$(PKG_NAME)
	@echo "✅ Agnostic host-to-Docker wrapper (symlink) installed in $(REAL_HOME)/.local/bin/$(PKG_NAME)"

docker-install: docker-build docker-volume docker-config docker-link ## Full Docker installation for the ephemeral runtime

docker-uninstall: ## Remove Docker image and wrapper, keep persistent data
	@echo "🗑️ Removing BW-Proxy Docker artifacts..."
	@rm -f $(REAL_HOME)/.local/bin/$(PKG_NAME)
	@docker rmi $(DOCKER_IMAGE) 2>/dev/null || true
	@echo "✅ Docker uninstall complete (image and wrapper removed, data preserved)."

docker-purge: docker-uninstall ## Destructive: remove Docker volume and host config
	@echo "🔥 Purging Docker volume and config..."
	@docker volume rm $(DOCKER_VOLUME) 2>/dev/null || true
	@rm -rf $(REAL_HOME)/.bw/proxy
	@echo "✅ Docker volume and host config (~/.bw/proxy) removed."


# ── Prod (Sovereign Root) ────────────────────────────────────────────────────

install-hardened: ## Immutable system install (Root-owned code in /opt/bw-proxy)
	@mkdir -p $(REAL_HOME)/.bw/proxy/logs $(REAL_HOME)/.bw/proxy/wal
	@chmod 700 $(REAL_HOME)/.bw $(REAL_HOME)/.bw/proxy
	@echo "🛡️ Installing $(PKG_NAME) to /opt/$(PKG_NAME)..."
	@UV_TOOL_DIR=/opt UV_TOOL_BIN_DIR=$(REAL_HOME)/.local/bin $(UV) tool install . --force
	@chown -R root:root /opt/$(PKG_NAME)
	@echo "✅ Code installed in /opt/$(PKG_NAME)"
	@$(MAKE) apparmor-apply
	@echo "✅ Binary linked in $(REAL_HOME)/.local/bin/$(PKG_NAME)"
	@chown -R $(REAL_USER):$(REAL_USER) $(REAL_HOME)/.bw
	@chown -h $(REAL_USER):$(REAL_USER) $(REAL_HOME)/.local/bin/$(PKG_NAME) || true
	@echo "🛡️ AppArmor profile active and enforced."

hardened-uninstall: ## Remove hardened system install
	@echo "🗑️ Removing $(PKG_NAME) system install..."
	@UV_TOOL_DIR=/opt UV_TOOL_BIN_DIR=$(REAL_HOME)/.local/bin $(UV) tool uninstall $(PKG_NAME) || true
	@rm -rf /opt/$(PKG_NAME)
	@if [ -f $(APPARMOR_TARGET) ]; then \
		apparmor_parser -R $(APPARMOR_TARGET) && rm -f $(APPARMOR_TARGET); \
		echo "✅ AppArmor profile removed."; \
	fi
	@rm -rf $(REAL_HOME)/.bw/proxy
	@echo "✅ System install and data removed."

apparmor-apply: ## Internal: Generate and load AppArmor profile
	@echo "🛡️ Applying AppArmor profile..."
	@printf "abi <abi/3.0>,\n\
include <tunables/global>\n\n\
profile bw-proxy /opt/bw-proxy/bin/bw-proxy {\n\
  include <abstractions/base>\n\
  include <abstractions/python>\n\n\
  network inet stream,\n\
  /opt/bw-proxy/** mr,\n\
  $(REAL_HOME)/.bw/proxy/** rw,\n\
  $(REAL_HOME)/.bw/proxy/logs/* wk,\n\
  $(REAL_HOME)/.bw/proxy/wal/* wk,\n\
  owner $(REAL_HOME)/.config/bw/sessions/*.json r,\n\
  /usr/bin/bw ix,\n\
}\n" | tee $(APPARMOR_TARGET) > /dev/null
	@apparmor_parser -r $(APPARMOR_TARGET)

audit: ## Audit installation security (ownership, permissions, AppArmor)
	@echo "🔍 Auditing Sovereign Installation for $(PKG_NAME)..."
	@if [ "$$(stat -c '%%U:%%G' /opt/$(PKG_NAME))" != "root:root" ]; then \
		echo "❌ ERR: /opt/$(PKG_NAME) must be root:root"; exit 1; \
	fi
	@echo "✅ /opt/$(PKG_NAME) ownership is root:root"
	@if [ "$$(stat -c '%%U:%%G' $(REAL_HOME)/.local/bin/$(PKG_NAME))" != "$(REAL_USER):$(REAL_USER)" ]; then \
		echo "❌ ERR: Binary must be $(REAL_USER):$(REAL_USER)"; exit 1; \
	fi
	@echo "✅ Binary ownership is $(REAL_USER):$(REAL_USER)"
	@if [ "$$(stat -c '%%a' $(REAL_HOME)/.bw/proxy)" != "700" ]; then \
		echo "❌ ERR: $(REAL_HOME)/.bw/proxy must be 700"; exit 1; \
	fi
	@echo "✅ Data directory $(REAL_HOME)/.bw/proxy is 700"
	@if ! aa-status | grep -q "^   bw-proxy$$"; then \
		echo "❌ ERR: AppArmor profile 'bw-proxy' not found in aa-status"; exit 1; \
	fi
	@echo "✅ AppArmor profile is loaded and enforced."
	@echo "🏆 AUDIT PASSED"

# ── Package ───────────────────────────────────────────────────────────────────

build:  ## Build package with uv
	@rm -rf dist && uv build

publish: build  ## Publish to PyPI (requires UV_PUBLISH_TOKEN via bw-env)
	@$(ZSH_LOGIN) 'if ! env | grep -q "^UV_PUBLISH_TOKEN="; then \
		echo "UV_PUBLISH_TOKEN missing — run bw-env first"; exit 1; fi; \
		uv publish --check-url https://pypi.org/simple'

release: check build publish push  ## Full release: check → build → publish → push

# ── Git ───────────────────────────────────────────────────────────────────────

push:  ## Push current branch to all remotes (github + gitlab)
	@branch="$$(git branch --show-current)"; \
	for remote in $$(git remote); do \
		echo "==> pushing $$branch to $$remote"; \
		git push "$$remote" "$$branch"; \
	done

push-tags:  ## Push all tags to all remotes
	@for remote in $$(git remote); do git push "$$remote" --tags; done

git-status:  ## git status --short
	@git status --short

git-log:  ## Last 10 commits oneline
	@git log --oneline -10
