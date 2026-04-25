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
APPARMOR_TARGET := /etc/apparmor.d/opt.bw-proxy.bin.bw-proxy

help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

# ── Dev ──────────────────────────────────────────────────────────────────────

link:  ## Install package in editable mode (user)
	@$(UV) tool install --editable . --force

unlink:  ## Uninstall tool
	@$(UV) tool uninstall $(PKG_NAME)

install: link ## Classic user-space CLI install

uninstall: unlink ## Classic user-space CLI uninstall

test:  ## Run pytest
	@$(UV) run python -m pytest -q

check:  ## py_compile + pytest
	@python3 -m py_compile $$(find src tests -name '*.py' 2>/dev/null)
	@$(UV) run python -m pytest -q

# ── Docker ───────────────────────────────────────────────────────────────────

docker-build: ## Build the BW-Proxy Docker image (No-Cache)
	@docker compose build --no-cache

docker-up: ## Start the BW-Proxy container (Detached)
	@UID=$(REAL_UID) GID=$(REAL_GID) docker compose up -d

docker-link: ## Create an agnostic host-side wrapper to execute commands in the container
	@mkdir -p $(REAL_HOME)/.local/bin
	@cp scripts/bw_proxy_shim.py $(REAL_HOME)/.local/bin/$(PKG_NAME)
	@chmod +x $(REAL_HOME)/.local/bin/$(PKG_NAME)
	@echo "✅ Agnostic host-to-Docker wrapper installed in $(REAL_HOME)/.local/bin/$(PKG_NAME)"

docker-install: docker-uninstall docker-build docker-up docker-link ## Full Docker installation (clean + build + up + link)

docker-dev: docker-down docker-link ## Start in Development mode (Clean + Build + Up)
	@UID=$(REAL_UID) GID=$(REAL_GID) docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
	@echo "🛠️ BW-Proxy is running in DEV mode (Live Sync enabled)"

docker-down: ## Stop and remove the BW-Proxy container
	@UID=$(REAL_UID) GID=$(REAL_GID) docker compose down

docker-uninstall: docker-down ## Remove Docker image and wrapper, keep user data
	@echo "🗑️ Removing BW-Proxy Docker artifacts..."
	@rm -f $(REAL_HOME)/.local/bin/$(PKG_NAME)
	@docker rmi $(PKG_NAME):latest 2>/dev/null || true
	@docker rmi bw_mcp-bw-proxy:latest 2>/dev/null || true
	@echo "✅ Docker uninstall complete (image and wrapper removed)."

docker-purge: docker-uninstall ## Destructive: remove Docker volume too
	@echo "🔥 Purging Docker volume..."
	@docker volume rm bw_mcp_bw-data 2>/dev/null || true
	@echo "✅ Docker volume removed."

docker-logs: ## Follow Docker logs (interactive)
	@docker compose logs -f

docker-logs-all: ## Dump all Docker logs
	@docker compose logs

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
