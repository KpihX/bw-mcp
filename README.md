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
      |                                     | -- 2. Zenity UI Prompt       | |
      |                                     | <- User enters Master Pw --  | |
      |                                     |                                |
      |                                     | -- 3. bw unlock -----------> |
      |                                     | <- Vault JSON (Uncensored) - |
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
      |                                     | -- 6. Zenity UI POPUP        | | [ See: docs/05_simulation_destructive_firewall.md ]
      |                                     | <- User clicks 'Approve' --- | |
      |                                     |                                |
      |                                     | -- 7. bw edit item --------> | [ See: docs/02_simulation_vault_organization.md ]
      |                                     | <- Vault Updated ----------- |
      |                                     |                                |
      | <- 8. Success Message ------------- |   (Memory Wipe to 0x00)        | [ See: docs/01_simulation_core_protocol.md ]
      |                                     |                                |
```

### The 4 Pillars of Defense

1. **AI-Blind Read Operations:** The AI reads structural metadata. `password`, `totp`, `notes` (Secure Notes), `number` (CC), `code` (CVV), `ssn` (Identity), `passportNumber`, and "Hidden" Custom Fields are instantly overwritten by Pydantic before the LLM sees the JSON.
   - If the original field is filled, the AI sees `"[REDACTED_BY_PROXY_POPULATED]"`.
   - If the field is blank or missing, the AI sees `"[REDACTED_BY_PROXY_EMPTY]"`.
   - **Deep Dive:** Read **[03_simulation_pii_redaction.md](docs/03_simulation_pii_redaction.md)** for more.
2. **Strict Polymorphic Pydantic Schemas:** The AI **CANNOT** execute wild bash commands. It can only propose from a hardcoded list of 15 `Enum` atomic actions. If a rogue AI tries to slip `"password": "hacked"` into a `RenameItem` payload, Pydantic's `extra="forbid"` rule immediately detonates the payload and aborts the transaction.
3. **Hardware-Level Memory Wiping:** The `BW_SESSION` key and your Master Password are fundamentally obliterated from Python memory immediately after usage. Instead of relying on Python's Garbage Collector (which leaves strings floating in RAM for hackers to dump), the proxy converts keys to raw `bytearray` matrices and systematically overwrites them with zeroes (`0x00`).
   - **Deep Dive:** Read **[01_simulation_core_protocol.md](docs/01_simulation_core_protocol.md)**.
4. **Red Alerts on Destructive Actions:** Modifying an item logs a blue UI prompt. Deleting an item/folder triggers a native Red Warning Zenity Box to guarantee a human doesn't sleepwalk into approving an AI's destructive hallucination.
   - **Deep Dive:** Read **[05_simulation_destructive_firewall.md](docs/05_simulation_destructive_firewall.md)**.

---

## 🛠️ Exhaustive API Coverage (15 Enum Actions)

The proxy maps Bitwarden's complex CLI into 15 robust, completely secure internal Enums.

### Item Organization (`ItemAction`)
1. **`rename_item`**: Safely alters the name of a secret.
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

### Granular PII Editing (`EditAction`)
To edit an item, the Python Subprocess grabs the full hidden JSON locally, surgicaly injects the AI's safe modification, and pushes it back up.
12. **`edit_item_login`**: Safely updates `Username` & `URIs`. (Strictly rejects attempts to edit `password` or `totp`).
13. **`edit_item_card`**: Safely updates Expiration Dates, Name, & Brand. (Strictly rejects Credit Card Number & CVV edits).
14. **`edit_item_identity`**: Safely updates Standard Address & Contact Info. (Strictly rejects SSN, Passport, and License edits).
15. **`upsert_custom_field`**: Adds/updates unstructured metadata. (Strictly limited to `Type 0: Text` and `Type 2: Boolean`. The AI is blocked from reading or altering `Type 1: Hidden` or `Type 3: Linked` secrets).

---

## 🏗️ Project Adjustment (The Final API Coverage)
To make **BW-Blind-Proxy** exhaustively complete, we implemented these historical adjustments:

1. **Schema Refactoring (`models.py`)**:
   - Created `BlindCard` (redacts number, code).
   - Created `BlindIdentity` (redacts ssn, passport, license).
   - Created `BlindField` (redacts `value` if target is hidden/linked).
   - Updated `BlindItem` to include `card`, `identity`, `secureNote` and `fields`.

2. **Transaction Refactoring (`models.py` & `transaction.py`)**:
   - Added action `toggle_favorite` (target_id, boolean).
   - Added action `edit_item_card` (allows changing expiry date, name).
   - Added action `edit_item_identity` (allows changing address/email).
   - Added action `upsert_custom_field` (allows adding/modifying Text/Boolean fields safely without erasing existing hidden fields). 

3. **Phase 4 "The Extreme Edge" (FULLY IMPLEMENTED)**:
   - Added `ItemAction.RESTORE` (Trash recovery).
   - Added `ItemAction.DELETE_ATTACHMENT` (Attachment purging).
   - Added `ItemAction.MOVE_TO_COLLECTION` (Enterprise sharing).
   - Added `ItemAction.TOGGLE_REPROMPT` (Master Password reprompt flag).

This design guarantees that *every single non-sensitive lever* in Bitwarden is directly, explicitly, and securely accessible by the LLM via Pydantic Enums, while not a single cryptographic or PII secret can ever leak.

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

---
**Maintained with 100% transparency. Your secrets remain yours.**
