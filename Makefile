# ── Config ──────────────────────────────────────────────────────────────────
PKG_NAME := bw-mcp
PKG_DIR  := src/bw_mcp

# 🛠️ Robust path discovery (detecting real user home even under sudo/sui)
REAL_USER := $(if $(SUDO_USER),$(SUDO_USER),$(USER))
REAL_HOME := $(shell getent passwd $(REAL_USER) | cut -d: -f6)
ZSH_LOGIN := zsh -l -c
UV        := $(shell command -v uv 2>/dev/null || ls $(REAL_HOME)/.local/bin/uv 2>/dev/null || echo uv)
APPARMOR_TARGET := /etc/apparmor.d/opt.bw-mcp.bin.bw-mcp

help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

# ── Dev ──────────────────────────────────────────────────────────────────────

link:  ## Install package in editable mode (user)
	@$(UV) tool install --editable .

unlink:  ## Uninstall tool
	@$(UV) tool uninstall $(PKG_NAME)

test:  ## Run pytest
	@uv run python3 -m pytest -q

check:  ## py_compile + pytest
	@python3 -m py_compile $$(find src tests -name '*.py' 2>/dev/null)
	@uv run python3 -m pytest -q

# ── Prod (Sovereign Root) ────────────────────────────────────────────────────

APPARMOR_TARGET := /etc/apparmor.d/opt.bw-mcp.bin.bw-mcp

install: ## Immutable system install (Root-owned code in /opt/$(PKG_NAME), User binary in ~/.local/bin)
	@mkdir -p $(REAL_HOME)/.bw/mcp/logs $(REAL_HOME)/.bw/mcp/wal
	@chmod 700 $(REAL_HOME)/.bw $(REAL_HOME)/.bw/mcp
	@echo "🛡️ Installing $(PKG_NAME) to /opt/$(PKG_NAME)..."
	@UV_TOOL_DIR=/opt UV_TOOL_BIN_DIR=$(REAL_HOME)/.local/bin $(UV) tool install . --force
	@chown -R root:root /opt/$(PKG_NAME)
	@echo "✅ Code installed in /opt/$(PKG_NAME)"
	@$(MAKE) apparmor-apply
	@echo "✅ Binary linked in $(REAL_HOME)/.local/bin/$(PKG_NAME)"
	@# Fix ownership for user-specific resources created by root
	@chown -R $(REAL_USER):$(REAL_USER) $(REAL_HOME)/.bw
	@chown -h $(REAL_USER):$(REAL_USER) $(REAL_HOME)/.local/bin/$(PKG_NAME) $(REAL_HOME)/.local/bin/bw-admin || true
	@echo "🛡️ AppArmor profile active and enforced."

uninstall: ## Remove system install
	@echo "🗑️ Removing $(PKG_NAME) system install..."
	@UV_TOOL_DIR=/opt UV_TOOL_BIN_DIR=$(REAL_HOME)/.local/bin $(UV) tool uninstall $(PKG_NAME) || true
	@rm -rf /opt/$(PKG_NAME)
	@if [ -f $(APPARMOR_TARGET) ]; then \
		apparmor_parser -R $(APPARMOR_TARGET) && rm -f $(APPARMOR_TARGET); \
		echo "✅ AppArmor profile removed."; \
	fi
	@rm -rf $(REAL_HOME)/.bw/mcp
	@echo "✅ System install and data removed."

apparmor-apply: ## Internal: Generate and load AppArmor profile
	@echo "🛡️ Applying AppArmor profile..."
	@printf "abi <abi/3.0>,\n\
include <tunables/global>\n\n\
profile bw-mcp /opt/bw-mcp/bin/bw-mcp {\n\
  include <abstractions/base>\n\
  include <abstractions/python>\n\n\
  /opt/bw-mcp/** mr,\n\
  $(REAL_HOME)/.bw/mcp/** rw,\n\
  $(REAL_HOME)/.bw/mcp/logs/* wk,\n\
  $(REAL_HOME)/.bw/mcp/wal/* wk,\n\
  owner $(REAL_HOME)/.config/bw/sessions/*.json r,\n\
  /usr/bin/bw ix,\n\
  /usr/bin/zenity ix,\n\
}\n" | tee $(APPARMOR_TARGET) > /dev/null
	@apparmor_parser -r $(APPARMOR_TARGET)

audit: ## Audit installation security (ownership, permissions, AppArmor)
	@echo "🔍 Auditing Sovereign Installation for $(PKG_NAME)..."
	@# 1. Code ownership
	@if [ "$$(stat -c '%U:%G' /opt/$(PKG_NAME))" != "root:root" ]; then \
		echo "❌ ERR: /opt/$(PKG_NAME) must be root:root"; exit 1; \
	fi
	@echo "✅ /opt/$(PKG_NAME) ownership is root:root"
	@# 2. Binary ownership
	@if [ "$$(stat -c '%U:%G' $(REAL_HOME)/.local/bin/$(PKG_NAME))" != "$(REAL_USER):$(REAL_USER)" ]; then \
		echo "❌ ERR: Binary must be $(REAL_USER):$(REAL_USER)"; exit 1; \
	fi
	@echo "✅ Binary ownership is $(REAL_USER):$(REAL_USER)"
	@# 3. Data directory permissions
	@if [ "$$(stat -c '%a' $(REAL_HOME)/.bw/mcp)" != "700" ]; then \
		echo "❌ ERR: $(REAL_HOME)/.bw/mcp must be 700"; exit 1; \
	fi
	@echo "✅ Data directory $(REAL_HOME)/.bw/mcp is 700"
	@# 4. AppArmor status
	@if ! aa-status | grep -q "^   bw-mcp$$"; then \
		echo "❌ ERR: AppArmor profile 'bw-mcp' not found in aa-status"; exit 1; \
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

status:  ## git status --short
	@git status --short

log:  ## Last 10 commits oneline
	@git log --oneline -10
