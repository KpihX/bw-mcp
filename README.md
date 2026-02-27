# BW-Blind-Proxy 🔐🤖
**Sovereign & Ultra-Secure Model Context Protocol for Bitwarden**

**BW-Blind-Proxy** is a specialized, exhaustive MCP server designed to act as an "Air-Gapped" intermediary between Large Language Models (LLMs) and your Bitwarden vault. 

It strongly enforces the **"AI-Blind Management"** philosophy: it empowers external AI agents (like Claude Code, Cursor, or Gemini) to completely reorganize, restructure, and maintain your password vault with 100% flexibility, *without ever exposing a single sensitive secret to the LLM*.

---

## 🛡️ Core Security Principles

1. **AI-Blind Read Operations:** The AI can only read structural metadata (names, folders, usernames, non-hidden custom fields). Passwords, TOTP seeds, Credit Card CVVs, and Identity SSNs are aggressively redacted *before* reaching the LLM layer via Pydantic model validation.
2. **Strict Polymorphic Pydantic Schemas:** The AI CANNOT execute blind commands on your PC. It can only propose explicit modifications via 15 strictly typed `Enum` actions. Attempts by an AI to inject a `password` into an update payload are systematically rejected.
3. **Human-In-The-Loop (HITL) Consent:** Every write transaction requires explicit, native GUI confirmation (via Zenity) and prompts for your Master Password.
4. **Anti-Phishing Memory Wiping:** The ephemeral `BW_SESSION` key and your Master Password are fundamentally obliterated from Python memory (`bytearray` scrubbing) immediately after transaction completion to defend against memory dumping.
5. **Red Alerts on Destructive Actions:** Deletions trigger visually distinct, red-colored warnings to guarantee humans do not unknowingly approve massive AI deletions.

---

## 🏗️ Exhaustive API Coverage (15 Actions)

The proxy translates the Bitwarden CLI into 15 robust, completely secure internal Enums managed by `TransactionManager`. 

### Item Operations
* `rename_item`: Safe renaming.
* `move_item`: Reparenting items inside folders.
* `delete_item`: Triggers Red Alert. Removes item to Trash.
* `restore_item`: Recovers an item from the Trash.
* `favorite_item`: Toggles the star status.
* `toggle_reprompt`: Enables/Disables Master Password Reprompt for specific items.
* `move_to_collection`: Enterprise Organization sharing.
* `delete_attachment`: Forcefully removes file attachments.

### Folder Operations
* `create_folder`, `rename_folder`, `delete_folder`

### Granular Editing (PII Protected)
* `edit_item_login`: Safely updates Username & URIs (Rejects password/TOTP edits).
* `edit_item_card`: Safely updates Expiration Dates & Brand (Rejects Credit Card Number & CVV edits).
* `edit_item_identity`: Safely updates Address & Contact Info (Rejects SSN, Passport, and License edits).
* `upsert_custom_field`: Safely adds/updates Text and Boolean fields (Rejects editing 'Hidden' or 'Linked' field types).

---

## 🚀 Installation & Usage

### Requirements
- Python `>= 3.12`
- `uv` package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- `bw` (Bitwarden CLI) installed and logged in.
- `zenity` installed on Linux (`sudo apt install zenity`) for the GUI prompts.

### Build and Install Globally
Provide the tool to your system via `uv`:
```bash
uv tool install . --force
```

### Adding to an MCP Client
Add the following to your Claude/Cursor configurations, or your `gemini-cli` config:
```json
{
  "mcpServers": {
    "bw-blind-proxy": {
      "command": "bw-blind-proxy",
      "args": []
    }
  }
}
```

---

## 📖 Deep Dives & Simulations
The project includes exhaustive transparency documentation detailing *exactly* how the proxy behaves in extreme scenarios. Please review these artifacts:
* `docs/bitwarden_architecture.md`: Explains the granular anatomy of the Bitwarden schemas and the reverse-engineering used for the Proxy's defense model.
* `docs/simulation_exhaustive.md`: The base AI negotiation cycle.
* `docs/simulation_organization.md`: Complex orchestration and batching.
* `docs/simulation_destruction.md`: How the Red Alert systems protect against malicious AI deletions.
* `docs/simulation_advanced_types.md`: How Pydantic obliterates AI attempts to modify PII and Custom Hidden Fields.
