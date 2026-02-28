# 🤖 Project Agent Mandate: BW-Blind-Proxy

## 🎯 Project Vision
**BW-Blind-Proxy** is a sovereign Model Context Protocol (MCP) server designed to act as a security-hardened intermediary between Large Language Models (LLMs) and the Bitwarden CLI (`bw`). 

- **AI-Blind Management:** Metadata is visible, secrets are redacted.
- **Deep Illustration & Transparency:** "Illustration" is the core mandate. Every architectural layer and data structure must be visualized (ASCII art, schemas) and documented with concrete examples. NO abstraction without illustration.

## 🛠️ Engineering Standards
- **Language:** Technical content, code, comments, and documentation must be in **ENGLISH ONLY**.
- **Stack:** Python 3.12+, `uv` for dependency management, `mcp` Python SDK.
- **Architecture:** Modular and decoupled. The MCP server must be usable by any agent (Claude Code, Gemini CLI, Cursor, etc.). Built mathematically on 15 `StrEnum` Actions for 100% API coverage with Pydantic polymorphism.
- **Security First:** 
    - No caching of `BW_SESSION` keys in logs or persistent storage.
    - Mandatory sanitization of all output from the `bw` CLI.
    - Explicit human validation (via system notifications or CLI prompts) for write/update operations.

## ⚙️ Operational Rules
- **No Bypassing:** Agents must never attempt to call `bw` directly using `run_shell_command`. All Bitwarden interactions must go through the tools defined in this MCP server.
- **Exhaustive Documentation:** Every tool must have a clear description, parameter schema, and explained security implications.
- **Full Verbose Validation:** Any validation scripts must follow the "Full Verbose" mandate defined in the global `GEMINI.md`.

## 🧠 Knowledge Retention
The agent must proactively update the `README.md` and this `AGENT.md` as the project evolves, especially regarding tool definitions and security boundaries.
