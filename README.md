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

### 1. `get_vault_map()`
**Description:** Fetches the structural map of the Bitwarden vault, filtering out all secrets securely via Pydantic before transmission.
*   **Input (AI provides):** None (No arguments required).
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

### 2. `propose_vault_transaction(payload)`
**Description:** Accepts a batch of actions from the AI, strictly validates the schemas using `extra="forbid"`, displays a Human-in-The-Loop UI for approval, and securely edits the Bitwarden CLI.
*   **Input (AI provides):** A JSON string matching the `TransactionPayload` schema (A rationale and a list of operations).

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

## 🛠️ Exhaustive API Coverage (17 Enum Actions)

The proxy maps Bitwarden's complex CLI into 17 robust, completely secure internal Enums.

### Item Organization (`ItemAction`)
1. **`create_item`**: Spawns an empty shell (Login, Note, Card, Identity) locally. Strictly blocks LLM from creating secrets safely.
2. **`rename_item`**: Safely alters the name of a secret.
2. **`move_item`**: Reparents an item inside a specific Folder UUID.
3. **`favorite_item`**: Toggles the star/favorite status.
4. **`delete_item`**: [🚨 RED ALERT] Removes item to the Trash.
5. **`restore_item`**: [Phase 4 Edge] Recovers an item from the Trash.
6. **`toggle_reprompt`**: [Phase 4 Edge] Enables/Disables Master Password Reprompt requirement for specific high-value items.
7. **`move_to_collection`**: [Phase 4 Edge] Enterprise Organization sharing mapping.
8. **`delete_attachment`**: [Phase 4 Edge] Forcefully removes physical file attachments.

### Folder Operations (`FolderAction`)
9. **`create_folder`**: Instantiates a new logical grouping.
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
To truly trust a sovereign proxy, you must understand how it behaves in extreme edge cases. Read these explicit simulations in the `docs/` folder:

* `docs/bitwarden_architecture.md`: Explains the granular anatomy of the Bitwarden schemas and the reverse-engineering used for the Proxy's defense model.
* `docs/01_simulation_core_protocol.md`: The base AI negotiation cycle and memory wiping.
* `docs/02_simulation_vault_organization.md`: Complex orchestration and batching logic.
* `docs/03_simulation_pii_redaction.md`: How Pydantic obliterates AI attempts to modify PII and Custom Hidden Fields.
* `docs/04_simulation_extreme_edge.md`: *(See actual file for Phase 4 Trash/Collection/Reprompt capabilities)*.
* `docs/05_simulation_destructive_firewall.md`: How the Red Alert systems protect against malicious AI deletions.
* `docs/06_simulation_safe_creation.md`: How the AI creates safe empty shells without generating passwords.

---
**Maintained with 100% transparency. Your secrets remain yours.**
