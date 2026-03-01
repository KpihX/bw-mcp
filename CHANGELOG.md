# CHANGELOG: The Sovereign Journey of BW-MCP 🛡️

All notable changes to this project, from its inception to the current secure state.

## [v1.3.0] - 2026-03-01: The Daemon Evolution & Batch Upgrade
### ⚙️ Daemon Lifecycle Control
- **Typer CLI Overhaul**: Refactored the core `bw-mcp` entry point (`__init__.py` -> `main.py`) from a bare `main()` into a fully-fledged Typer CLI with systemd-like daemon controls.
- **PID File Management**: Created `daemon.py` to manage a stateful `~/.bw_mcp/bw-mcp.pid` tracking the live FastMCP stdio process.
- **Lifecycle Commands**: Introduced new subcommands for manual or automated control without breaking the core MCP protocol:
  - `bw-mcp serve` (Default backward-compatible entrypoint for Gemini/Claude/Cursor)
  - `bw-mcp status` (Check PID heartbeat)
  - `bw-mcp stop` (Send SIGTERM)
  - `bw-mcp restart` (Cleanly kill the stale process so the MCP client auto-respawns the new binary)
- **Extensive Daemon Tests**: Implemented comprehensive unit tests (`test_daemon.py`) verifying state-checking and SIGTERM mocking.

### 📈 Scale Improvements
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
