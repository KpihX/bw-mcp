---
name: bw-proxy
description: Bitwarden MCP proxy — organizational vault control while keeping LLMs blind to secrets.
version: 3.6.3
---

# 🛡️ BW-Proxy Skill

This skill allows AI agents to interact with the **BW-Proxy** appliance via its CLI surface. The CLI uses RPC 2.0 (JSON) and is the recommended way for both humans and AI agents to manage the vault efficiently.

## 🎯 Primary Goal
Manage Bitwarden vault items (Login, Note, Card, Identity) and perform blind audits/refactoring while remaining strictly blind to secret values.

---

## 🛠️ Operational Map

### 1. Administration (`admin`)
Use these commands to manage the appliance state and authentication.

| Command | Purpose |
| :--- | :--- |
| `bw-proxy admin login` | Initialize vault connection (URL, Email). |
| `bw-proxy admin status` | Check connection health and lock state. |
| `bw-proxy admin unlock` | Create a short-lived (5m) encrypted session lease. |
| `bw-proxy admin lock` | Immediately wipe the session lease and lock the proxy. |
| `bw-proxy admin config edit` | Open the secure browser-based YAML editor. |

### 2. Vault Operations (`do`)
These are the core tools for AI agents. Most commands support `--format json` (default for many) and `--rationale`.

#### 🔍 Discovery
- **`get-vault-map`**: Fetch the redacted structure of the vault.
  - *Usage*: `bw-proxy do get-vault-map [--folder-id ID] [--collection-id ID]`
- **`list-items`**: Fast redacted item listing.
  - *Usage*: `bw-proxy do list-items [--search STRING] [--n 50]`
- **`inspect-log`**: View previous transactions and their outcomes.
  - *Usage*: `bw-proxy do inspect-log [-n 10]`

#### 🏗️ Transactions (ACID)
- **`propose-vault-transaction`**: Simulate and log a batch of edits/creations.
  - *Usage*: `bw-proxy do propose-vault-transaction --rationale "..." --operations-json '[...]'`
- **`execute-vault-transaction`**: Commit a previously proposed transaction to the real vault.
  - *Usage*: `bw-proxy do execute-vault-transaction --tx-id ID`

#### 🧹 Audit & Refactor
- **`find-item-duplicates`**: Scan vault for items sharing the same secret as a target.
  - *Usage*: `bw-proxy do find-item-duplicates --item-id ID --field login.password`
- **`vault-refactor`**: Move or copy secrets between items (Blindly).
  - *Usage*: `bw-proxy do vault-refactor --operation MOVE --source-id ID --dest-id ID`

---

## 🚦 Interaction Rules

1.  **CLI over MCP**: Prefer using the CLI commands via `run_command` instead of MCP tools when possible. It is more token-efficient and provides explicit examples via `--help`.
2.  **Rationale is Mandatory**: Always provide a clear `--rationale` for any destructive or complex operation.
3.  **Lease Management**: If you need to perform multiple operations, proactively call `bw-proxy do admin-unlock` to avoid repeated password prompts for the user.
4.  **JSON First**: Use `--format json` (where available) to parse outputs programmatically.

---

## 📖 References
- [Installation Guide](references/install.md)
- [Official Repository](https://github.com/KpihX/bw-proxy)

## 📜 Changelog
- **v3.6.1**: Initial skill creation for the standardized appliance. [KpihX]
