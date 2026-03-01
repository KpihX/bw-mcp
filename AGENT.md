# 🤖 Project Agent Mandate: BW-MCP

## 🎯 Project Vision
**BW-MCP** is a sovereign Model Context Protocol (MCP) server designed to act as a security-hardened intermediary between Large Language Models (LLMs) and the Bitwarden CLI (`bw`). 

- **AI-Blind Management:** Metadata is visible, secrets are redacted.
- **Deep Illustration & Transparency:** "Illustration" is the core mandate. Every architectural layer and data structure must be visualized (ASCII art, schemas) and documented with concrete examples. NO abstraction without illustration.

## 🛠️ Engineering Standards
- **Language:** Technical content, code, comments, and documentation must be in **ENGLISH ONLY**.
- **Stack:** Python 3.12+, `uv` for dependency management, `mcp` Python SDK.
- **Architecture:** Modular and decoupled. The MCP server must be usable by any agent (Claude Code, Gemini CLI, Cursor, etc.). Built mathematically on 16 `StrEnum` Actions for 100% API coverage with Pydantic polymorphism.
- **Security First:** 
    - No caching of `BW_SESSION` keys in logs or persistent storage.
    - Mandatory sanitization of all output from the `bw` CLI.
    - Explicit human validation (via system notifications or CLI prompts) for write/update operations.
- **Distribution:** Primary distribution via PyPI (`uv tool install bw-mcp`).

## ⚙️ Operational Rules
- **No Bypassing:** Agents must never attempt to call `bw` directly using `run_shell_command`. All Bitwarden interactions must go through the tools defined in this MCP server.
- **Exhaustive Documentation:** Every tool must have a clear description, parameter schema, and explained security implications.
- **Full Verbose Validation:** Any validation scripts must follow the "Full Verbose" mandate defined in the global `GEMINI.md`.

## ⏱️ Post-Action Mandates (The Zero-Trust Update Cycle)
Whenever modifying the codebase (adding an Action, changing a schema, changing tool parameters), you **MUST** execute this checklist before declaring the task complete:
1. **Tests:** Update `tests/` and ensure `uv run pytest -v` runs flawlessly.
2. **Models:** Ensure `models.py` has `extra="forbid"` on any write payload and update the global Enum action counts.
3. **README:** Update the "Exhaustive API Coverage" section with the new action(s) and architecture diagram if needed.
4. **Docs:** Update or create the relevant simulation in `docs/` (ex: 01, 04, 06) with ASCII diagrams showing the exact data flow.
5. **AGENT.md:** Update the tracked feature parity/action count.

## 🧠 Knowledge Retention
The agent must proactively update the `README.md` and this `AGENT.md` as the project evolves. Current status: 
- **16 `StrEnum` Actions** deployed for 100% API coverage.
  - *(Was 17: `restore_folder` removed — Bitwarden folders have no trash; CLI command does not exist)*
- **ACID Transaction Engine** (Virtual Vault → Disk WAL → Execution) active.
- **Auditing CLI** active (`bw-proxy logs` & `bw-proxy purge`).
- **Internalized Configuration** active (`config.yaml` & `config.py`).
- **Configurable Batch Size Cap** active (`MAX_BATCH_SIZE` from config, enforced at Pydantic level in `models.py`, injected dynamically into tool docstring in `server.py`).
- **Shared Rollback Engine** active (`_perform_rollback(tx_id, stack, session_key)` in `transaction.py`): single source of truth for LIFO rollback, consumed by both `execute_batch` (on operation failure) and `check_recovery` (on boot, if WAL found).
- **Idempotent Rollback** active (`pop_rollback_command(tx_id)` in `wal.py`): after every successful rollback command, the command is popped from the WAL JSON file on disk, ensuring that a crash-during-rollback will NOT cause double-application of already-executed compensating commands on the next boot.
- **Non-Destructive `check_recovery`** active: if `_perform_rollback` fails during recovery, the WAL is intentionally NOT cleared. The LLM receives a structured diagnostic message so it can retry (transient network error) or escalate to the user (permanent error like "Item not found").
- **AI Introspection Tools** active: The LLM has native access to `get_proxy_audit_context` (for checking WAL orphans and recent log counts) and `inspect_transaction_log` (for deep-diving into individual JSON traces of rolled-back operations).

---

## 🤝 Integration for Fellow Agents
If you are a newly spawned agent tasked with extending or debugging this server:

1. **Self-Introspection:** Immediately call `get_proxy_audit_context`. This will tell you the current server limits (batch sizes, redaction tags) and the health of the vault transaction state.
2. **Architecture Brief:** This is a **3-Phase Commit** system.
    - **Phase 1 (Validation):** Input is mapped through Pydantic Enums in `models.py`.
    - **Phase 2 (Durability):** Rollback commands are snapshotted, encrypted with **Fernet**, and pushed to `~/.bw_mcp/wal/`.
    - **Phase 3 (Execution):** Safe surgical edits are pushed via the Bitwarden CLI using `bytearray` memory-wiping containers.
3. **Key Files for Deep-Dive:**
    - [README.md](README.md): The structural map and feature overview.
    - [MEMORY.md](MEMORY.md): **READ THIS FIRST.** It contains the "Why" behind every complex security decision (Bytecode vs Strings, ACID logic, Bitwarden quirks).
    - [CHANGELOG.md](CHANGELOG.md): The historical evolution from v1.0.0 (Foundation) to v1.2.0 (Ironclad Hardening).
    - `src/bw_mcp/models.py`: The single source of truth for the 16 actions.
    - `src/bw_mcp/transaction.py`: The heart of the ACID engine.
