# CHANGELOG: The Sovereign Journey of BW-MCP 🛡️

All notable changes to this project, from its inception to the current secure state.

## [v2.4.0] - 2026-04-24: Sovereign SSL & Two-Step HITL
### 🔒 Security
- **Local HTTPS Support**: HITL server now uses ephemeral self-signed SSL certificates (OpenSSL) to protect local loopback traffic and Master Password transmission.
- **Two-Step Approval Flow**: Introduced a "Lock Screen" in the Web UI. Transaction details are now strictly hidden until the Master Password is provided, preventing accidental exposure of proposed actions.
- **Enforced Authentication**: Password-first flow is now mandatory for all vault reviews and duplicate scans.
- **100% Agnostic Host Link**: Replaced Linux-oriented Bash shims with a Python-based intelligent switcher. The `bw-proxy` binary now works cross-platform (Windows/Mac/Linux) by detecting a local `.docker_mode` marker.

## [v2.3.0] - 2026-04-24: Agnostic Web Approval UI & Sovereign Browser HITL
### 🆕 Features
- **Total Agnostic UI (Browser HITL)**: Unified all user interactions (Vault Unlock, Transactions, Audit Comparisons, Duplicate Scans, Auth) into a lightweight browser-based interface.
- **Agnostic Architecture**: Zenity dependency completely removed. Works on Linux, Mac, Windows, and Headless (via SSH forwarding).
- **Micro-Server HITL Architecture**: `bw-proxy` embeds a lightweight, temporary `HTTPServer` on `localhost:1138` with glassmorphism design and strict security tokens.
- **Premium Design System**: The new UI features a modern, high-wow design with glassmorphism, Inter typography, and clear visual hierarchy for rationales and destructive warnings.
- **Secure Link with Token**: Approvals are protected by unique, one-time UUID tokens displayed in the terminal.
- **Auto-Open Integration**: Support for `webbrowser.open()` to automatically trigger approval tabs in the user's default browser.

### 🛡️ Security
- **Strict RAM-Only Enforcement**: Reinforced zero-persistence of secrets. The Browser HITL captures the Master Password as a `bytearray` and immediately wipes it from RAM once the transaction is authorized.
- **AppArmor Networking**: Updated the sovereign AppArmor profile to allow `network inet stream` specifically for the local HITL server.
- **Docker Port Exposure**: Updated `docker-compose.yml` to expose port `1138` by default for the Agnostic UI.

## [v2.2.2] - 2026-04-24: BW-Proxy Distribution & RAM-Only Hardening
### 🛡️ Security
- **RAM-Only Authentication Contract**: Removed parent-environment `BW_PASSWORD` / `BW_SESSION` consumption from application auth flows. BW-Proxy now prompts for the Master Password for each operation, creates a fresh session, and wipes it after use.
- **Docker Secret Hygiene**: Removed secret passthrough from Docker Compose and the host wrapper. `.env` is now limited to non-secret configuration such as server URL, account email, UID, and GID.
- **Verified Bitwarden CLI Supply Chain**: Docker builds now download a pinned Bitwarden CLI release and verify SHA-256 for amd64/arm64 before installing it.
- **Non-Root Container Runtime**: The runtime image now runs as an unprivileged user and keeps `/data` owner-only.

### 🧰 Distribution
- **Classic Install Split**: `make install` is now the natural user-space CLI install. The previous root-owned `/opt` flow is explicit as `make install-hardened`.
- **Docker Modes Split**: Docker is headless by default for cross-platform portability. Linux/X11 GUI approval is isolated in `docker-compose.gui.yml` and `make docker-up-gui`.
- **Current Naming Alignment**: Runtime configuration now uses `BW-Proxy` and `~/.bw/proxy` for current state. Historical changelog entries remain unchanged.

## [v2.2.1] - 2026-04-24: Real-time Hardening & Item Creation Fix
### 🛠️ Fixed
- **Automated Setup Resilience**: Hardened `admin setup` to ignore "Logout required" errors during server configuration if already set, allowing smooth progression to session validation.
- **Transaction Schema Alignment**: Resolved a Pydantic `ValidationError` by adding the missing `notes` field to the `CreateItemAction` model.
- **CLI Schema Compliance**: Fixed a critical `TypeError: Cannot read properties of null (reading 'type')` crash in Bitwarden CLI v2024 by ensuring nested objects (`login`, `secureNote`, `card`, `identity`) are properly initialized from templates during item creation.
- **Enhanced Debug Visibility**: Modified the subprocess execution engine to capture and report CLI `stderr` outputs in proxy exceptions, enabling rapid real-time troubleshooting.

## [v2.2.0] - 2026-04-23: Automated Discovery & Setup
### 🆕 Features
- **Automated Authentication Setup (`bw-proxy admin setup`)**: Introduced a guided, sequential discovery flow for Bitwarden authentication (URL -> Email -> Password).
- **Environment Ingestion**: Support for `BW_URL`, `BW_EMAIL`, and `BW_PASSWORD` in the `.env` file for zero-touch configuration in containerized environments.
- **TUI & GUI Parity**: Robust fallback mechanism for interactive prompts: automatically uses Zenity popups if `DISPLAY` is available, falling back to secure TTY input (`getpass`/`typer.prompt`) otherwise.
- **Secure Persistence**: Setup persists the encrypted session internally; the `session_key` is NEVER exposed in the console output or logs.
- **Silent Session Validation**: Proactively checks for existing valid sessions before triggering the discovery prompts.

## [v2.1.0] - 2026-04-23: Sovereign Appliance Hardening


### 🆕 Features
- **Blind Refactoring Tool (`refactor_item_secrets`)**: Introduced a breakthrough tool for secure `MOVE`, `COPY`, and `DELETE` of secrets between vault items.
- **AI-Blind Secret Migration**: Allows the AI to reorganize secret fields (passwords, TOTPs, custom fields) by key/name without ever seeing the values.
- **Deep Object Manipulation**: Support for refactoring Login credentials (username/password), Secure Notes, and arbitrary Custom Fields.

### 🔒 Security & ACID Compliance
- **Transactional Refactoring**: Integrated the refactor engine into the ACID transaction manager. Every move/copy is logged in the Write-Ahead Log (WAL) and supports full LIFO rollback.
- **HITL Transparency**: Updated the Zenity UI with distinct icons (🚚, 📋, 💥) and human-readable resolution of source/destination items.
- **Destructive Warning System**: Automatic "RED ALERT" triggers on the item source for `MOVE` and `DELETE` operations.

### 🧪 Test Coverage
- **Refactoring Test Suite**: Added `tests/test_refactor.py` covering item-to-item migration and multi-operation batches.

## [v1.9.2] - 2026-04-23: Sovereign Hardening — Root-Owned Immutability

### 🛡️ Security & Installation
- **Sovereign Install Workflow**: Transitioned to a root-owned `/opt/bw-proxy` installation pattern with user-specific data directories (`~/.bw/mcp`) and binaries (`~/.local/bin`).
- **Dynamic User Discovery**: Implemented `REAL_USER` and `REAL_HOME` logic in `Makefile` using `getent` and `SUDO_USER` to ensure correct path resolution when installed via `sui/sudo`.
- **AppArmor Enforcement**: Automated the generation and loading of a restrictive AppArmor profile (`/etc/apparmor.d/opt.bw-proxy.bin.bw-proxy`) allowing access only to specific data and system resources.
- **Unified Audit Target**: Added `make audit` for automated verification of installation ownerships, permissions, and security posture.

### 📖 Documentation & CLI Synchronization
- **Binary Renaming**: Finalized the transition of the administration CLI from `bw-proxy` to `bw-proxy` to avoid naming collisions and improve clarity.
- **Documentation Parity**: Updated `README.md`, `AUDIT.md`, and all simulation guides (`docs/05_*`, `docs/08_*`, etc.) to use the current `bw-proxy` and `bw-proxy` command structures.
- **Subcommand Calibration**: Standardized `bw-proxy log view` and `bw-proxy wal view` references across the entire doc suite.
- **Template Synchronization**: Updated `k-final` security templates (`Makefile.security.uv/bun`) to align with the new standard.

### 🔧 Housekeeping
- **Makefile Path Robustness**: Hardened `UV` path discovery and fixed `make check` execution logic (`uv run python -m pytest`).
- **Data Dir Management**: Improved uninstallation logic to cleanly remove AppArmor profiles and user-specific data directories.

## [v1.9.0] - 2026-04-23: Blind Audit 2.0 — Total Vault Collision Scan

### 🆕 Features
- **Total Vault Audit**: Introduced `find_all_vault_duplicates` for deep vault-wide collision detection across all secret fields (passwords, notes, custom fields).
- **Unified Password-First Flow**: Standardized vault unlocking across all audit tools to ensure a fresh, secure session before high-privilege scans.
- **Proactive Recovery**: Integrated `check_recovery` (WAL integrity check) into audit entrypoints to prevent scans on potentially inconsistent vault states.

### 🔒 Security
- **Blind Compare Logic**: Enhanced the embedded Python audit script with a "Total Scan" mode that fetches items and builds collision maps without any secret data touching the main process or logs.
- **Subprocess Hardening**: Fixed a critical indentation/syntax issue in the `subprocess_wrapper` script involving triple-quote nesting.

### 🎨 UI & UX
- **Global Scan View**: Updated `HITLManager` to clearly explain "Total Vault Collision" modes in Zenity popups, distinguishing them from targeted item scans.

### 🧪 Test Coverage
- **Full Suite Validation**: Maintained 84/84 tests green, verifying that unified audit logic doesn't break established single-item duplicate patterns.

## [v1.8.6] - 2026-04-22: Audit Engine Unification & Standardized Casing

### 🆕 Features
- **Unified Audit Engine**: Consolidated `find_item_duplicates` and `find_duplicates_batch` logic into a single high-performance path in `server.py`.
- **Enhanced Subprocess Layer**: Hardened `SecureSubprocessWrapper` with native support for `candidate_field_path`, allowing efficient cross-field secret comparisons in a single `bw` invocation.
- **REST-Style Casing Standard**: Standardized all tool response JSON objects to use lowercase `"status": "success"` for consistent machine parsing across all action surfaces.

### 🐛 Bug Fixes
- **Import Integrity**: Fixed a missing `field_validator` import in `models.py` that caused test collection failures.
- **Test Alignment**: Updated all 84 tests to match the new casing and payload naming conventions (`duplicate_ids`, `scan_size`, `total_available`).

### 🔧 Housekeeping
- **Dry/Redundancy Cleanup**: Removed 150+ lines of duplicate logic and redundant internal helper functions in `server.py`.
- **Refactoring Verification**: Successfully validated against a full 84/84 test suite passing in 3.63s.

## [v1.8.0] - 2026-04-22: Blind Duplicate Scanner — AI-Blind Audit v2.0

### 🆕 Features
- **Blind Duplicate Scanner**: Introduced `find_item_duplicates` tool. Allows the AI to scan the entire vault (or a candidate list) for items sharing the same secret as a target item. Performed in a single, high-speed ephemeral subprocess.
- **Dynamic Field Pathing**: Refactored the audit engine to support arbitrary dot-path resolution (e.g., `login.uris`, `notes`) and dynamic custom field resolution (e.g., `fields.MISTRAL_API_KEY`) without rigid enumeration.
- **Configurable Scan Limits**: Increased default duplicate scan limit to 100 via `config.yaml`. The `find_item_duplicates` tool now accepts an optional `scan_limit` parameter, allowing the AI to explicitly bypass the default constraints when handling large vaults.
- **Cross-Namespace Audit**: The audit engine now supports comparing secrets across different namespaces (e.g., matching a `Secure Note` content against a `Login` custom field).
- **Deep JSON Metadata Audit**: Support for comparing complex objects like `login.uris` using deep equality checks in the blind subprocess.

### 🔒 Security
- **Namespace Centralization**: Moved `ALLOWED_NAMESPACES` to `models.py` as a single source of truth for the entire proxy validation layer.
- **Namespace Whitelisting**: Implemented a defense-in-depth namespace whitelist (`login`, `card`, `identity`, `fields`, `notes`, `secureNote`) to prevent arbitrary property access in the vault JSON.
- **Bulk Audit Approval**: Added specialized HITL dialog for bulk scans, ensuring the human operator knows exactly which target and field are being used as a search key.

### 🎨 UI & UX
- **Informative Zenity Audits**: Comparison and Scan dialogues now display item **Names** instead of raw UUIDs (using an ephemeral name map) to provide better context to the human operator. 
- **Rich Formatting**: Added bold styling and color hints in Zenity to emphasize target items and field paths.

### 🧪 Test Coverage
- **New Test Suite**: Added `tests/test_audit_v2.py` specifically for dynamic pathing and bulk duplicate scans.

## [v1.7.2] - 2026-04-22: Documentation & Maintainer Experience

### 📖 Documentation
- **Maintainer Entrypoint**: Added a clear high-level map to the `README.md` to help new agents and developers navigate the core engine (ACID/WAL), the data layer (Redaction), and the server interface.
- **Operations Runbook**: Created `docs/OPERATIONS.md` covering the daemon lifecycle controller (`bw-proxy status/stop/restart`) and the WAL crash recovery flow.
- **Veracity Audit**: Performed a full documentation audit against the live Python source and 81/81 test suite to ensure all architectural claims remain strictly accurate.

### 🔧 Housekeeping
- **Makefile Hardening**: Updated the `test` target to use `uv run python -m pytest -q` for better cross-environment compatibility and script resolution.
- **TODO Cleanup**: Finalized and retired the "documentation enhancement" and "operator runbook" roadmap items.

## [v1.7.1] - 2026-03-22: WAL Security Hardening & Robustness Fixes

### 🔒 Security
- **WAL Log Sanitization**: `inspect_transaction_log` now uses `_sanitize_args_for_log` instead of `deep_scrub_payload` for rollback command arrays. `deep_scrub_payload` only redacts dict keys and cannot decode base64-encoded item JSON (which may contain passwords); `_sanitize_args_for_log` whitelists only known-safe BW CLI tokens and replaces everything else with `[PAYLOAD]`.

### 🐛 Bug Fixes
- **Specific Exception Handling**: Replaced broad `except Exception` with `except (json.JSONDecodeError, AttributeError)` in `transaction.py` rollback flow for cleaner error surface.
- **Path Fix in CHANGELOG**: Corrected PID file path reference (`~/.bw_proxy/` → `~/.bw/mcp/`).

### 🔧 Housekeeping
- Import cleanup across `config.py`, `daemon.py`, `logger.py`.
- `uv.lock` dependency refresh.
- Doc fixes in `README.md` and `docs/`.

## [v1.7.0] - 2026-03-02: Security Hardening & Robustness Audit

### 🔒 Security
- **DoS Prevention (Search Truncation)**: Implemented strict 256-character truncation for all search strings (`search_items`, `search_folders`) in `get_vault_map`. Prevents Memory/CPU exhaustion from malicious LLM-generated payloads.
- **Defense-in-Depth Audit Validation**: `audit_compare_secrets` now performs a secondary, internal validation of `SecretFieldTarget` before subprocess dispatch, ensuring malformed or smuggled field paths cannot be compared.
- **Enum-based Destructive Logic**: Refactored the UI (`ui.py`) to use `ItemAction` and `FolderAction` enums instead of hardcoded strings to determine "Danger" alerts, making the prompt logic robust to future action refactorings.
- **CLI Memory Cleaning**: Hardened the cleanup of `master_password` and `session_key` references in `cli.py` and `server.py` using `if 'var' in locals()` checks in `finally` blocks to prevent rare ReferenceErrors during cleanup.

### 🐛 Bug Fixes
- **`MoveToCollection` Syntax Fix**: Corrected the `bw move` command implementation. It now properly supports organization binding and multiple collection IDs via JSON-encoded payload, aligned with Bitwarden CLI v2024+.
- **Rollback NameError Patch**: Fixed a scoping bug in `transaction.py` where a local `import base64` inside a closure caused a `NameError` during LIFO rollback execution. Externalized all imports to the module level.
- **Import Hygiene**: Removed redundant `import json` calls across `server.py`, `logger.py`, and `transaction.py`.

### 🧪 Test Coverage
- **New Audit Test Suite**: Added `tests/test_audit_updates.py` covering DoS protection, `MoveToCollection` syntax, and polymorphic `ItemAction.CREATE` variants (Login, Card, Identity).
- **Coverage Bump**: Global test coverage increased to **69%**, with core logic reaching **75%+**.

## [v1.6.1] - 2026-03-02: Critical Security Patch (Secret Context Scrubbing)

### 🔒 Security
- **Patched Early-Exit Secret Leak**: Fixed a catastrophic memory leak in `execute_batch` and `get_vault_map` where an early exception (e.g., incorrect Master Password, or Zenity abort) would bypass the `finally` block preventing the memory-scrubbing loop (`for i in range(len(session_key)): session_key[i] = 0`). The entire logic was refactored into a unified master `try...finally` block.

## [v1.6.0] - 2026-03-02: Blind Secret Comparator (AI-Blind Audit Primitive)

### 🆕 Features
- **`compare_secrets_batch` Tool**: New MCP tool allowing the LLM to compare secret fields (passwords, TOTPs, SSNs, card numbers, custom hidden fields) between vault items without EVER seeing the values. Returns only `MATCH` / `MISMATCH`.
- **`SecretFieldTarget` StrEnum**: Strict Pydantic-enforced whitelist of auditable secret paths (`login.password`, `login.totp`, `card.number`, `card.code`, `identity.ssn`, `identity.passportNumber`, `identity.licenseNumber`, `fields.VALUE`).
- **`BatchComparePayload` Model**: Typed batch payload supporting up to `MAX_BATCH_SIZE` comparisons per call, with Pydantic validators.
- **`review_comparisons` UI**: New Zenity dialog for human-in-the-loop approval of audit requests, with full item name + UUID resolution.
- **Isolated Subprocess Execution**: Secret comparison runs in an ephemeral child Python process — secrets never enter the proxy's RAM.

### 🔒 Security Audit Fixes
- **`import sys` missing**: Fixed crash in `subprocess_wrapper.py` where `sys.executable` was used without importing `sys`.
- **Double Master Password popup**: `compare_secrets_batch` was calling `get_vault_map()` internally, triggering two Zenity password prompts. Refactored to a single unlock flow.
- **`_parse_id_map` non-existent**: Replaced phantom method call with inline vault parsing.
- **`log_operation` non-existent**: Replaced with proper `log_transaction` call using synthetic `TransactionPayload`.
- **UUID Validation**: Added `_UUID_RE` validation on `item_id_a` and `item_id_b` before subprocess dispatch to prevent malformed inputs from reaching `bw` CLI.
- **UUID disambiguation in UI**: `resolve()` now always shows `'Name' (uuid)` to prevent confusion with duplicate item names.
- **Config-driven audit tags**: `MATCH` / `MISMATCH` verdicts loaded from `config.yaml → audit.match_tag / audit.mismatch_tag`.

## [v1.5.1] - 2026-03-02: UI Transparency Hotfix (Zero-Trust Audit)

### 🔒 Security / UI
- **Patched URI Blindspot**: Removed the "pretty URI" formatter in `ui.py` that was silently stripping match strategy from Bitwarden URIs (e.g., `match=5 → Regex`). Zenity now displays the full raw list payload (`str(v)`) with zero reformatting.
- **Config-driven Redaction Check**: Replaced hardcoded `"[REDACTED"` substring check with a strict equality check against `REDACTED_POPULATED` and `REDACTED_EMPTY` from `config.py`. Single Source of Truth restored.
- **100% Transparent `_format_operation`**: Every field the LLM sends — URIs with match strategies, identity fields, card expiry, custom field values — is now shown verbatim to the human operator in Zenity before approval.

## [v1.5.0] - 2026-03-02: Native Schema Templates (Resources & Tools)

### 🧠 AI Contextualization
- **Pydantic Driven Templates**: Introduced `TemplateType` (StrEnum) in `models.py` to firmly structure the Bitwarden template types exposed to the LLM context.
- **`get_bitwarden_template` Tool**: Added a native MCP tool for the AI to securely fetch JSON schemas of Bitwarden entities (login, card, identity, etc.), automatically scrubbed of sensitive fields by the proxy.
- **Dynamic Resources**: Exposed `bw://templates/{template_type}` as MCP resources for host applications, allowing human operators to inject clean Bitwarden schemas directly into the prompt without a tool execution round-trip.

## [v1.4.3] - 2026-03-02: Structured CLI Configuration & Versioning

### ⚙️ Proxy Control
- **Refactored Config CLI**: Split `bw-proxy config` into explicit `get` and `update` subcommands for a more standard CLI experience.
- **Config Get**: Added `bw-proxy config get` to view the full YAML-derived JSON, or `bw-proxy config get -m` to strictly fetch the current batch limit.
- **Config Update**: Added `bw-proxy config update -m <N>` to programmatically tune the proxy.
- **Native Versioning**: Added `--version` flag to the `bw-proxy` CLI to match the behavior of `bw-proxy version`.

## [v1.4.2] - 2026-03-02: CLI Configuration Management

### ⚙️ Proxy Control
- **Dynamic Configuration**: Introduced `bw-proxy config` command to view and programmatically update the proxy's `config.yaml` from the CLI.
- **Batch Size adjustment**: Added `-m / --max-batch-size` option to allow users to tune the ACID engine's risk window without manual YAML editing. Includes integer validation (>= 1).
- **Atomic Config Write**: Implemented `update_config` with clean disk-load and `load_config.cache_clear()` to prevent race conditions during configuration updates.

## [v1.4.0] - 2026-03-02: Zero-Trust Auto-Sync Architecture

### 🔄 Silent Synchronization
- **Architectural Shift**: Removed the `sync_vault` MCP tool. Instead, the proxy now enforces a strict `bw sync` operation securely under-the-hood within `SecureSubprocessWrapper.unlock_vault()` immediately after decrypting the session key.
- **Guarantee**: Every `get_vault_map` and every transaction execution is now categorically guaranteed to query the latest server truth, eliminating races with external vault edits entirely and removing cognitive load from the LLM.

## [v1.3.2] - 2026-03-01: Entity Validation & Pydantic StrEnum Fixes

### 🛡️ Security & Type Hardening
- **Active Type-Checking**: Fixed a critical validation bypass where Pydantic's underlying `str` casting of `StrEnum` models circumvented our `type(op.action)` checks. The proxy now strictly intercepts AI hallucinations (e.g., trying to `move_item` on a Folder UUID) *before* the Zenity UI appears and *before* the WAL is written.
- **Clean LLM Bounce-back**: By securely wrapping the intercepted payload errors in `SecureBWError` (with `_safe_error_message`), the agent now receives a direct, scrubbed rationale explaining its structural mistake, allowing auto-correction without disk mutation or human UI spam.
- **New Test Coverage**: Expanded `test_transactions.py` with mock-based validation assertions to prevent similar architectural illusions in future updates.

## [v1.3.1] - 2026-03-01: The Daemon Evolution & Batch Upgrade

### ⚙️ Daemon Lifecycle Control
- **Typer CLI Overhaul**: Refactored the core `bw-proxy` entry point (`__init__.py` -> `main.py`) from a bare `main()` into a fully-fledged Typer CLI with systemd-like daemon controls.
- **PID File Management**: Created `daemon.py` to manage a stateful `~/.bw/mcp/bw-proxy.pid` tracking the live FastMCP stdio process.
- **Lifecycle Commands**: Introduced new subcommands for manual or automated control without breaking the core MCP protocol:
  - `bw-proxy serve` (Default backward-compatible entrypoint for Gemini/Claude/Cursor)
  - `bw-proxy status` (Check PID heartbeat)
  - `bw-proxy stop` (Send SIGTERM)
  - `bw-proxy restart` (Cleanly kill the stale process so the MCP client auto-respawns the new binary)
- **Extensive Daemon Tests**: Implemented comprehensive unit tests (`test_daemon.py`) verifying state-checking and SIGTERM mocking.

### 📈 Scale & Tooling Improvements
- **Auditing CLI Re-Architecture**: Restructured the audit commands (`bw-proxy`) from flat commands (`logs`, `log`, `wal`, `purge`) into Typer command groups:
  - `bw-proxy log view -l/--list <n>` (replaces `logs`) or `-n/--number <i>` (replaces `log`)
  - `bw-proxy log purge -k/--keep <n>` (replaces `purge`)
  - `bw-proxy wal view` (replaces `wal`)
  - `bw-proxy wal delete` (New destructive operation requiring Master Password)
- **Increased Batch Capacity**: Raised `max_batch_size` default limit in `config.yaml` from 10 to 25 operations to support heavier automated vault organization scripts without fragmentation.

## [v1.2.3] - 2026-03-01: UI Security & Pango Immunity

### 🔒 UI Hardening
- **Pango Markup Escaping**: Implemented systematic XML/HTML escaping for all strings displayed in Zenity popups. This prevents UI crashes or blank dialogs when vault items or rationales contain special characters like `&`, `<`, or `>`.
- **Bulletproof HITL**: Added unit tests specifically for character escaping in the UI layer.

## [v1.2.2] - 2026-03-01: CLI Polish & UI Aliases

### 🔧 CLI Improvements
- **Aliased Purge**: Added `-k` and `--keep` aliases for the `purge` command for faster log management.
- **Robust Error Catching**: Refined the CLI entry point to catch `ValueError` and `SecureProxyError` explicitly, preventing raw stack traces from reaching the user while maintaining diagnostic clarity.
- **Version Bump**: Synced project version to 1.2.1.

## [v1.2.0] - 2026-03-01: The Ironclad Hardening

### 🔒 Security & Cryptography
- **Encrypted WAL**: Transitioned from plaintext `.json` to encrypted `.wal` format using **Fernet (AES-128-CBC + HMAC)**.
- **Key Derivation**: Implemented **PBKDF2-HMAC-SHA256** with 480,000 iterations and 16-byte cryptographic salts for WAL security.
- **Memory Safety**: Extreme migration from `str` to `bytearray` for all sensitive credentials (Master Password, Session Key).
- **Proactive Memory Wiping**: Implemented native in-place byte-overwriting (`key[i]=0`) in `finally` blocks to defeat memory forensics.
- **Global Scrubber**: Developed `scrubber.py` with `deep_scrub_payload` to recursively purge secrets from all log files and terminal outputs.
- **Error Sanitization**: Introduced `_safe_error_message` to block LLM-based side-channel attacks via Pydantic `ValidationError` strings.

### 🏗️ Architectural Refactor
- **Isolated Destructive Actions**: Enforced a "Standalone Batch" rule for `delete_attachment` and `delete_folder` to handle Bitwarden's hard-delete nature.
- **Folder Action Correction**: Removed `restore_folder` (invalid CLI command) and finalized folder management logic.
- **Full Security Audit**: Created `AUDIT.md` documenting the 6 layers of defense-in-depth.

## [v1.1.0] - 2026-02-28: ACID Resilience & Durability

### ✨ Features
- **ACID Transaction Engine**: Implementation of the 3-phase commit engine (Virtual Vault RAM Simulation → Encrypted WAL → LIFO Rollback).
- **Idempotent Rollback**: Redesigned the WAL to consume commands incrementally, preventing double-application during recovery crashes.
- **AI Introspection Tools**: Added `get_capabilities_overview`, `get_proxy_audit_context`, and `inspect_transaction_log` for LLM self-awareness.
- **Advanced Search**: Decoupled search API with tri-state trash support and organization/collection filtering.

### 📊 Documentation & Transparency
- **Illustration-First Mandate**: Full conversion of all documentation to rich ASCII art schemas for absolute terminal compatibility.
- **Simulation Series**: Created a 01-08 walkthrough series detailing every core mechanism from protocol to WAL resilience.

## [v1.0.0] - 2026-02-28: Total-Blind Foundation

### 🧱 Core Infrastructure
- **MCP Server Architecture**: Initial deployment using `FastMCP`.
- **Blind Schemas**: Pydantic models defining the "Total Blind" philosophy (secrets are redacted before reaching the LLM).
- **Null-Aware Redaction**: Introduced `[REDACTED_BY_PROXY_POPULATED]` and `[REDACTED_BY_PROXY_EMPTY]` to give metadata context without exposure.
- **100% API Coverage**: Initial mapping of 17 StrEnum actions (later refined to 16).
- **Zenity HITL**: Integration of native Linux popups for secure Master Password capture and destruction approval.

---
*Created with the philosophy of Zero Trust, Total Transparency, and Total Blind.*
