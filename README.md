# BW-Blind-Proxy 🔐🤖

**Sovereign, Exhaustive, & Ultra-Secure Model Context Protocol (MCP) for Bitwarden**

**BW-Blind-Proxy** is a specialized, air-gapped intermediary designed to physically isolate Large Language Models (LLMs) from your Bitwarden cryptographic secrets, while still granting them 100% organizational superpowers over your vault.

It strongly enforces the **"AI-Blind Management"** philosophy. You can ask an AI (Claude, Cursor, Gemini) to completely reorganize your vault, rename poorly formatted accounts, manage your Enterprise Collections, update credit card expiration dates, or tag hundreds of items as favorites. *The AI will do all of this flawlessly, without ever being able to read or modify your Master Password, your TOTP seeds, your Credit Card CVVs, or your Social Security Number.*

---

The transparency of this proxy is its greatest strength. Follow the **[Visual Simulation Path](docs/01_simulation_core_protocol.md)** to see every byte in motion.

### 🎥 The Zero-Trust Interactive Path
If you want to understand the codebase, read the documentation in this specific order:
1. **[Core Protocol](docs/01_simulation_core_protocol.md)**: How we unlock and wipe RAM.
2. **[Vault Organization](docs/02_simulation_vault_organization.md)**: AI Batching and Orchestration.
3. **[PII & Card Defense](docs/03_simulation_pii_redaction.md)**: Shielding your Identity and Credit Cards.
4. **[Advanced Edge Features](docs/04_simulation_extreme_edge.md)**: Trash, Collections, and Attachments.
5. **[The Destructive Firewall](docs/05_simulation_destructive_firewall.md)**: How Zenity prevents AI hallucinations from deleting your life.
6. **[Safe Creation](docs/06_simulation_safe_creation.md)**: How the AI spawns empty shell items without polluting secrets.
7. **[Advanced Search Filtering](docs/07_simulation_advanced_search.md)**: How the AI optimizes context tokens using the precise backend queries.
8. **[ACID Resilience & WAL](docs/08_simulation_acid_wal_resilience.md)**: How the Proxy auto-recovers from an OS-level blackout without dataloss.

```text
   [ USER PROMPT ]  : "IpihX, rename my GitHub account and move it to Dev."
          |
          v
   (01) CORE READ   : Proxy unlocks Vault in RAM (then wipes Master Password)
          |
          v
   [ CENSORY LAYER ]: Pydantic overwrites 🔐 Secrets & 🪪 PII (SSN, CVV...)
          |           --> [ See: docs/03_simulation_pii_redaction.md ]
          v
   [ THE AI BRAIN ] : Sees metadata only (IDs, Names). Proposes a Batch.
          |
          v
   (02) BATCH WRITE : Proxy checks actions against Strict Enums (Anti-Hallucination)
          |           --> [ See: docs/02_simulation_vault_organization.md ]
          v
   (05) HITL FIREWALL : ⚠️ RED ALERT Popup on your screen. You click 'Approve'.
          |           --> [ See: docs/05_simulation_destructive_firewall.md ]
          v
   [ BITWARDEN VAULT ]: Proxy executes commands safely. Final RAM Wipe.
```

### Flow Visualization: How the Proxy Works
Here is exactly how an AI interacts with your vault.

```text
================================================================================
                    PHASE 1: READING METADATA (AI-Blind)
================================================================================

 [ AI Agent ]                       [ BW-Blind-Proxy ]               [ Bitwarden CLI ]
      |                                     |                                |
      | -- 1. get_vault_map() ------------> |                                |
      |                                     | -- 2. Zenity UI Prompt ------> |
      |                                     | <- User enters Master Pw ----  |
      |                                     |                                |
      |                                     | -- 3. bw unlock ----------->   |
      |                                     | <- Vault JSON (Uncensored) -   |
      |                                     |                                |
      |   (Pydantic Validation Firewall)    |  [ See: docs/01_simulation_core_protocol.md ]
      |   * Redact 'password', 'totp' *     |  [ See: docs/03_simulation_pii_redaction.md ]
      |   * Redact 'CVV', 'SSN', etc. *     |                                |
      |                                     |                                |
      | <- 4. Sanitized Structural Map ---- |                                |
      |                                     |                                |

================================================================================
                    PHASE 2: BATCH EXECUTION (Write)
================================================================================

 [ AI Agent ]                       [ BW-Blind-Proxy ]               [ Bitwarden CLI ]
      |                                     |                                |
      | -- 5. propose_vault_transaction --> |                                |
      |                                     |   (Enum Schema Validation)     |
      |                                     |   * extra="forbid" aborts *    |
      |                                     |                                |
      |                                     | -- 6. Zenity UI POPUP          |  [ See: docs 05_simulation_destructive_firewall.md ]
      |                                     | <- User clicks 'Approve' ---   |
      |                                     |                                |
      |                                     | -- 7. bw edit item -------->   [ See: docs/02_simulation_vault_organization.md ]
      |                                     | <- Vault Updated -----------   |
      |                                     |                                |
      | <- 8. Success Message ------------- |   (Memory Wipe to 0x00)        | [ See: docs/01_simulation_core_protocol.md ]
      |                                     |                                |
```

### The 4 Pillars of Defense

1. **AI-Blind Read Operations:** The AI reads structural metadata only.
   - **Never Received:** The LLM is isolated from `revisionDate`, `creationDate`, `deletedDate`, `passwordHistory`, and `attachments` (unless explicitly requested). They are completely ignored by Pydantic and never reach the prompt.
   - **Redacted (Tags):** The LLM sees the *existence* of sensitive fields but not their value. `password`, `totp`, `notes` (Secure Notes), `number` (CC), `code` (CVV), `ssn` (Identity), `passportNumber`, and "Hidden" Custom Fields are instantly overwritten with `[REDACTED_BY_PROXY_...]`.
   - **Deep Dive:** Read **[03_simulation_pii_redaction.md](docs/03_simulation_pii_redaction.md)** for more.
2. **Strict Polymorphic Pydantic Schemas:** The AI **CANNOT** execute wild bash commands. It can only propose from a hardcoded list of 17 `Enum` atomic actions. If a rogue AI tries to slip `"password": "hacked"` into a `create_item` payload, Pydantic's `extra="forbid"` rule immediately detonates the payload and aborts the transaction.
   - **Deep Dive:** Read **[06_simulation_safe_creation.md](docs/06_simulation_safe_creation.md)**.
3. **Hardware-Level Memory Wiping:** The `BW_SESSION` key and your Master Password are fundamentally obliterated from Python memory immediately after usage. Instead of relying on Python's Garbage Collector (which leaves strings floating in RAM for hackers to dump), the proxy converts keys to raw `bytearray` matrices and systematically overwrites them with zeroes (`0x00`).
   - **Deep Dive:** Read **[01_simulation_core_protocol.md](docs/01_simulation_core_protocol.md)**.
4. **Red Alerts on Destructive Actions:** Modifying an item logs a blue UI prompt. Deleting an item/folder triggers a native Red Warning Zenity Box to guarantee a human doesn't sleepwalk into approving an AI's destructive hallucination.
   - **Deep Dive:** Read **[05_simulation_destructive_firewall.md](docs/05_simulation_destructive_firewall.md)**.

## 🔌 MCP Tools Reference (Inputs & Outputs)

The Proxy exposes exactly **two** tools to the AI Agent. This drastically limits the attack surface while enabling profound orchestration capabilities.

### 1. `get_vault_map(search_items, search_folders, folder_id, collection_id, organization_id, trash_state, include_orgs)`
**Description:** Fetches the structural map of the Bitwarden vault, filtering out all secrets securely via Pydantic before transmission. Supports native Bitwarden CLI filtering to drastically reduce the context window and speed up searches.
*   **Input (AI provides):** All arguments are optional.
    *   `search_items` (str): Search specifically in item names, metadata, or URIs.
    *   `search_folders` (str): Search specifically in folder names.
    *   `folder_id` (str): Filter items by a specific folder UUID.
    *   `collection_id` (str): Filter items by a specific collection UUID.
    *   `organization_id` (str): Filter items/collections by org UUID.
    *   `trash_state` (str, default="all"): Tri-state filter for Trash fetching:
        *   `"none"`: Fetch ONLY active vaults. (Maximizes speed and minimizes tokens).
        *   `"only"`: Fetch ONLY the trash. (Useful for finding items to restore).
        *   `"all"`: Fetch everything.
    *   `include_orgs` (bool): If false, skips fetching the Organization mappings.
*   **Output (AI receives):** A sanitized JSON containing `folders`, `items`, `trash_items`, `trash_folders`, `organizations`, and `collections`.

**Example Output (What the AI sees):**
```json
{
  "status": "success",
  "data": {
    "folders": [{"id": "uuid-folder-1", "name": "Work"}],
    "items": [
      {
        "id": "uuid-item-1",
        "name": "Lokad Intranet",
        "type": 1,
        "folderId": "uuid-folder-1",
        "login": {
            "username": "kpihx@lokad.com", 
            "password": "[REDACTED_BY_PROXY_POPULATED]",
            "totp": "[REDACTED_BY_PROXY_EMPTY]"
        }
      }
    ],
    "trash_items": [], "trash_folders": [], "organizations": [], "collections": []
  }
}
```

### 2. `propose_vault_transaction(rationale, operations)`
**Description:** Submits a batch of operations (create, edit, delete, move, etc.) for execution.
*   **Absolute Agent-Blindness:** The AI operates exclusively on sanitized payloads (Pydantic `extra="ignore"` for reads, `extra="forbid"` for writes). Passwords, TOTPs, CVVs, and secure notes are mathematically scrubbed before reaching the context window.
*   **Human-in-The-Loop Execution:** All write operations trigger a massive Zenity UI popup detailing the exact operations intent. The human must visually authorize the batch and enter the Master Password.
*   **ACID Transaction Engine:** A full 3-phase Commit engine (Virtual Vault RAM Simulation $\rightarrow$ Disk Write-Ahead Log $\rightarrow$ LIFO Rollback) guarantees mathematical consistency. The vault is never left in an uncommitted state even upon network failure or `kill -9` process interruptions.
*   **Auditing & CLI:** Every modification request is written to a human-readable, secret-stripped log in `logs/transactions/`. A dedicated Typer/Rich CLI (`bw-proxy logs`) allows you to view the latest modifications beautifully in the terminal.
*   **Input (AI provides):**
    *   `rationale` (str): A direct message to the user explaining *why* the AI wants to do this.
    *   `operations` (List[VaultTransactionAction]): An array of polymorphic action objects.
**Example Input (How the AI asks):**
```json
{
  "rationale": "I am organizing your Lokad credentials into the Work folder.",
  "operations": [
    {
      "action": "move_item",
      "target_id": "uuid-item-1",
      "folder_id": "uuid-folder-1"
    }
  ]
}
```

*   **Output (AI receives):** A success string or a fast-failing `ValidationError` string if the AI tries to manipulate forbidden keys.

**Example Expected Output:**
```text
Transaction completed successfully.
- Moved item uuid-item-1 to folder uuid-folder-1
```

**Example Failure Output (If AI attempts a hack):**
```text
ValidationError: 1 validation error for TransactionPayload... Extra inputs are not permitted (type=extra_forbidden)
```

---

## 🛠️ Architecture

```mermaid
graph TD
    A[Agent Workspace (Claude/Gemini)] -->|Tool Call| B[FastMCP Server]
    B -->|Sanitized Read| C[Pydantic Models]
    C -->|Redacted Payload| A
    B -->|Write Intention| D[Virtual Vault & WAL Engine]
    D -->|Zenity UI Prompts| E[Human Approval + Master Password]
    E -->|Write-Ahead Log Serialization| F[(Local WAL Disk)]
    F -->|Secure Execution| G[subprocess `bw` CLI]
    G -->|Success| H[Clear WAL + Write Audit Log]
    G -->|Failure/Crash| I[LIFO Crash Recovery]
```

---

## 🛠️ Exhaustive API Coverage (17 Enum Actions)

The proxy maps Bitwarden's complex CLI into 17 robust, completely secure internal Enums.

### Item Organization (`ItemAction`)
1.  **`create_item`**: Spawns an empty shell (Login, Note, Card, Identity) locally. Strictly blocks LLM from creating secrets safely.
2.  **`rename_item`**: Safely alters the name of a secret.
2.  **`move_item`**: Reparents an item inside a specific Folder UUID.
3.  **`favorite_item`**: Toggles the star/favorite status.
4.  **`delete_item`**: [🚨 RED ALERT] Removes item to the Trash.
5.  **`restore_item`**: [Phase 4 Edge] Recovers an item from the Trash.
6.  **`toggle_reprompt`**: [Phase 4 Edge] Enables/Disables Master Password Reprompt requirement for specific high-value items.
7.  **`move_to_collection`**: [Phase 4 Edge] Enterprise Organization sharing mapping.
8.  **`delete_attachment`**: [Phase 4 Edge] Forcefully removes physical file attachments.

### Folder Operations (`FolderAction`)
9.  **`create_folder`**: Instantiates a new logical grouping.
10. **`rename_folder`**: Self-explanatory.
11. **`delete_folder`**: [🚨 RED ALERT] Deletes the folder (does not delete the items inside, they go to root).
12. **`restore_folder`**: [Phase 4 Edge] Recovers a folder from the Trash.

### Granular PII Editing (`EditAction`)
To edit an item, the Python Subprocess grabs the full hidden JSON locally, surgicaly injects the AI's safe modification, and pushes it back up.
13. **`edit_item_login`**: Safely updates `Username` & `URIs`. (Strictly rejects attempts to edit `password` or `totp`).
14. **`edit_item_card`**: Safely updates Expiration Dates, Name, & Brand. (Strictly rejects Credit Card Number & CVV edits).
15. **`edit_item_identity`**: Safely updates Standard Address & Contact Info. (Strictly rejects SSN, Passport, and License edits).
16. **`upsert_custom_field`**: Adds/updates unstructured metadata. (Strictly limited to `Type 0: Text` and `Type 2: Boolean`. The AI is blocked from reading or altering `Type 1: Hidden` or `Type 3: Linked` secrets).

---

### 🦾 The "Extreme Edge" (Phase 4 Logic)
For organizational perfection, the Proxy handles advanced states without ever touching the secret keys:

```text
    [ TRASH ] <--- restore_item --- [ PROXY ] --- delete_attachment ---> [ FILES ]
                                       |
    [ ORG   ] <--- move_to_coll --- [ PROXY ] --- toggle_reprompt  ---> [ RE-AUTH ]
```
**Deep Dive:** Explore how these complex subcommands are executed in **[04_simulation_extreme_edge.md](docs/04_simulation_extreme_edge.md)**.

---

## 🔒 Security Posture & ACID Compliance

The core philosophy of **BW-Blind-Proxy** is **Zero-Trust for the AI, Total-Reliability for the Human**. We achieve this by treating Bitwarden modifications as database transactions.

### 📜 What is ACID?
We implement the four pillars of database reliability to protect your vault:
*   **A - Atomicity (Atomicité) :** Every batch of operations is "All-or-Nothing". If one rename fails, all preceding creates/deletes in that batch are automatically reversed.
*   **C - Consistency (Cohérence) :** Data is validated against strict Pydantic models in a **Virtual Vault** (RAM) before hitting the CLI.
*   **I - Isolation :** Each transaction is processed in its own secure session context.
*   **D - Durability (Durabilité) :** Once a transaction starts, its intent is written to disk. It survives process death (`kill -9`) and power outages.

### 🛡️ WAL: Write-Ahead Logging (D-Durability)
To guarantee **Durability**, we use a **WAL Engine**. 
1. **The Log First:** Before `bw` executes any destructive command, the proxy serializes the **Compensating Action** (Rollback).
2. **Atomic Recovery:** Upon any tool call (like `get_vault_map`), the proxy first checks for a stranded WAL. If found, it forces a vault repair **before** allowing further actions.

---

## ⚙️ Configuration & Internalization

Following the developer mandate of **Independent Autonomous Packages**, the configuration is internalized within the package source.

*   **Location:** `src/bw_blind_proxy/config.yaml`
*   **Customization:** You can modify the `state_directory` to point to any location.

```yaml
# src/bw_blind_proxy/config.yaml
state_directory: "~/.bw-blind-proxy"
```

## 📂 Transparency & File Structure

The proxy maintains a centralized state directory (configurable) for auditing and recovery: `~/.bw-blind-proxy/`

```text
~/.bw-blind-proxy/
├── logs/                  # Immutable Audit Trail (Stripped of secrets)
│   ├── 2026-02-28_10-00-01_txid_success.log
│   └── 2026-02-28_10-15-45_txid_rollback_triggered.log
└── wal/                   # Recovery Engine (Ephemeral)
    └── pending_transaction.json
```

### 🔍 Inside an Audit Log (`logs/*.log`)
Extremely detailed but **100% blind to secrets**.
```text
TRANSACTION ID: c070d585-ba21-4b94-b065-4be725a0bb5b
TIMESTAMP:      2026-02-28T10:00:01
STATUS:         SUCCESS
----------------------------------------
RATIONALE:
  Cleaning up obsolete dev credentials as discussed.
----------------------------------------
OPERATIONS REQUESTED:
  [1] Action: edit_item_login | Target: 550e8400-e29b-41d4-a716-446655440000
  [2] Action: delete_item | Target: 110b3bed-a3b8-4ee0-9cec-3dd950e2d118
----------------------------------------
END OF LOG
```

### 🔍 Inside a WAL Entry (`logs/wal/pending_transaction.json`)
This file exists **only** during an active transaction to protect your data.
```json
{
  "transaction_id": "tx-8892",
  "timestamp": 1740733800.0,
  "rollback_commands": [
    { "cmd": ["bw", "restore", "item", "id-item-B"] },
    { "cmd": ["bw", "edit", "item", "id-item-A", "{\"original_data\": \"...\"}"] }
  ]
}
```

---

## 🔧 Installation & Commands

Requires Python 3.12+ and `uv`.

```bash
# Clone the repository
git clone [...]
cd bw-blind-proxy

# Install project and CLI binary using uv
uv sync
```

### 🖥️ Native Auditing CLI (`bw-proxy`)

The proxy features an underlying auditor capturing every structural modification intent.

```bash
# View the latest N transactions applied on your Bitwarden vault
uv run bw-proxy logs --n=5

# Delete old logs, keeping only the N most recent ones to free up space
uv run bw-proxy purge --keep=10

# Inspect the status of the local ACID Write-Ahead Log engine
uv run bw-proxy wal
```

## 🔒 Security Posture & ACID Compliance

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
To truly trust a sovereign proxy, you must understand how it behaves in extreme edge cases. Read these explicit simulations in the `docs/` folder:

* `docs/bitwarden_architecture.md`: Explains the granular anatomy of the Bitwarden schemas and the reverse-engineering used for the Proxy's defense model.
* `docs/01_simulation_core_protocol.md`: The base AI negotiation cycle and memory wiping.
* `docs/02_simulation_vault_organization.md`: Complex orchestration and batching logic.
* `docs/03_simulation_pii_redaction.md`: How Pydantic obliterates AI attempts to modify PII and Custom Hidden Fields.
* `docs/04_simulation_extreme_edge.md`: *(See actual file for Phase 4 Trash/Collection/Reprompt capabilities)*.
* `docs/05_simulation_destructive_firewall.md`: How the Red Alert systems protect against malicious AI deletions.
* `docs/06_simulation_safe_creation.md`: How the AI creates safe empty shells without generating passwords.
* `docs/07_simulation_advanced_search.md`: Precision mapping and search queries to limit LLM context bloat.
* `docs/08_simulation_acid_wal_resilience.md`: 100% transparency on the crash-recovery and Typer Audit Logging mechanism.

---
**Maintained with 100% transparency. Your secrets remain yours.**
