# 🤖 Project Agent Mandate: BW-Blind-Proxy

## 🎯 Project Vision
**BW-Blind-Proxy** is a sovereign Model Context Protocol (MCP) server designed to act as a security-hardened intermediary between Large Language Models (LLMs) and the Bitwarden CLI (`bw`). 

- **AI-Blind Management:** Metadata is visible, secrets are redacted.
- **Deep Illustration & Transparency:** "Illustration" is the core mandate. Every architectural layer and data structure must be visualized (ASCII art, schemas) and documented with concrete examples. NO abstraction without illustration.

## 🛠️ Engineering Standards
- **Language:** Technical content, code, comments, and documentation must be in **ENGLISH ONLY**.
- **Stack:** Python 3.12+, `uv` for dependency management, `mcp` Python SDK.
- **Architecture:** Modular and decoupled. The MCP server must be usable by any agent (Claude Code, Gemini CLI, Cursor, etc.). Built mathematically on 17 `StrEnum` Actions for 100% API coverage with Pydantic polymorphism.
- **Security First:** 
    - No caching of `BW_SESSION` keys in logs or persistent storage.
    - Mandatory sanitization of all output from the `bw` CLI.
    - Explicit human validation (via system notifications or CLI prompts) for write/update operations.

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
- **17 `StrEnum` Actions** deployed for 100% API coverage.
- **ACID Transaction Engine** (Virtual Vault -> Disk WAL -> Execution) active.
- **Auditing CLI** active (`bw-proxy logs` & `bw-proxy purge`).
- **Internalized Configuration** active (`config.yaml` & `config.py`).
