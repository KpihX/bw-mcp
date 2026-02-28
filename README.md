# BW-Blind-Proxy 🔐🤖

**Sovereign, Exhaustive, & Ultra-Secure Model Context Protocol (MCP) for Bitwarden**

**BW-Blind-Proxy** is a specialized, air-gapped intermediary designed to physically isolate Large Language Models (LLMs) from your Bitwarden cryptographic secrets, while still granting them 100% organizational superpowers over your vault.

It strongly enforces the **"AI-Blind Management"** philosophy. You can ask an AI (Claude, Cursor, Gemini) to completely reorganize your vault, rename poorly formatted accounts, manage your Enterprise Collections, update credit card expiration dates, or tag hundreds of items as favorites. *The AI will do all of this flawlessly, without ever being able to read or modify your Master Password, your TOTP seeds, your Credit Card CVVs, or your Social Security Number.*

---

## 🧭 The Philosophy

> **Blind by Design · Zero Trust · Radical Transparency**

This project does not ask for your trust. It is architected so that trust becomes irrelevant.

### I. Blind by Design
The AI model is **physically incapable** of seeing your secrets. A `Pydantic` model layer (`extra="forbid"` + `force_redact()`) intercepts every byte returned by the Bitwarden CLI before the AI ever sees it. Passwords, TOTPs, CVVs, and SSNs are overwritten with sentinel tags (`[REDACTED_BY_PROXY_POPULATED]`) at the data layer — not by policy or politeness. This is the **Principle of Least Privilege** taken to its logical extreme: *you cannot leak what you cannot read.*

### II. Zero Trust
The proxy extends zero trust **to everyone**: the AI, the user, and itself. Every proposed batch of operations is:
1. **Validated by Pydantic** against strict enum schemas before touching any CLI.
2. **Reviewed by the Human** via a Zenity system popup requiring the Master Password.
3. **Traced to disk** in a Write-Ahead Log before execution, allowing crash recovery.
4. **Rolled back automatically** (LIFO) if any step fails, with a full audit trail.

There are no "admin bypass" modes, no `--force` flags, and no silent failures.

### III. Radical Transparency
We do not sell a dream. We document every architectural decision and **every limitation**. Our logs record not just what succeeded, but what failed, which rollback commands ran, and which one could not. You will always know the exact state of your vault.

**Notable honest limitations we cannot fix in code (but mitigate in design):**

| Limitation                          | Root cause                                     | Our mitigation                                                   |
| :---------------------------------- | :--------------------------------------------- | :--------------------------------------------------------------- |
| No atomic `COMMIT`                  | Bitwarden API has no transaction mode          | WAL + LIFO Rollback (Saga Pattern)                               |
| Race condition window               | External clients can modify vault during batch | Batch size cap of 10 ops (configurable)                          |
| Session timeout during long batches | `BW_SESSION` can expire server-side            | Short batches, WAL survives crash for auto-recovery on next boot |

→ **Full details:** [docs/LIMITATIONS.md](docs/LIMITATIONS.md)

### Why We Cap Batches at 10 Operations

```text
SCENARIO: You ask the AI to reorganize 15 items.

[Batch of 15 operations — WITHOUT cap]
─────────────────────────────────────────────────────
OP  1: rename "Github" → "GitHub"          ✅ done (live on server)
OP  2: move "Netflix" to folder "Media"    ✅ done (live on server)
...
OP  8: move "Bank-Crédit" to "Finance"     ✅ done (live on server)
        ~~ You open the Bitwarden iOS app ~~
        ~~ You delete "Bank-Crédit" (the old name no longer makes sense) ~~
OP  9: rename "Bank-Crédit" → "Crédit Agricole"  CRASH: "Item not found" ❌
ROLLBACK TRIGGERED → tries bw edit "Bank-Crédit"  FATAL: Item was deleted externally 💀
─────────────────────────────────────────────────────
Result: OPs 1–8 are live. OP 9 failed. Rollback failed. Vault is inconsistent.

[Batch of 10 operations — WITH cap]
─────────────────────────────────────────────────────
The race-condition window is reduced by ~33%.
The probability of an external edit coinciding shrinks proportionally.
Each batch of ≤10 ops is a smaller, safer, atomic-ish unit of work.
```

### Why `delete_attachment` Is Always Isolated

```text
SCENARIO: AI sends a batch with 2 ops — [delete_attachment, rename_item].

  OP 1: delete_attachment "contract.pdf" from Item "Job Contract"   ✅ DONE
         ⚠️ The file is now GONE. Bitwarden does NOT trash attachments.
  OP 2: rename_item "Job Contract" → "Old Job Contract"              CRASHES ❌

ROLLBACK:
  reverse OP 1 → ??? IMPOSSIBLE. The file no longer exists anywhere.

Result: The file is permanently destroyed. The item name was never updated.
        The user did not intend to delete the attachment—it was collateral damage.
─────────────────────────────────────────────────────
OUR GUARD: Pydantic rejects ANY batch containing delete_attachment alongside
           other operations. The AI is forced to send it alone — guaranteeing
           no other operation can trigger a rollback that erases irreplaceable data.
```

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

---

## 🔬 Radical Transparency: The Audit System

> *"We don't tell you the vault is safe. We show you. Every operation. Every error. Every rollback command."*

### 📄 Case 1: `SUCCESS` — All operations completed cleanly

```json
{
  "transaction_id": "d3117e3d-46a4-4835-a5f9-87ce6124e56d",
  "timestamp": "2026-02-28T14:12:03.862607",
  "status": "SUCCESS",
  "rationale": "Renaming GitHub entry and moving Netflix to the Media folder.",
  "operations_requested": [
    {"action": "rename_item", "target_id": "uuid-github-001", "new_name": "GitHub"},
    {"action": "move_item",   "target_id": "uuid-netflix-007", "folder_id": "uuid-media"}
  ],
  "execution_trace": [
    "Renamed item uuid-github-001 to 'GitHub'",
    "Moved item uuid-netflix-007 to folder 'uuid-media'"
  ]
}
```

---

### 📄 Case 2: `ROLLBACK_SUCCESS` — One operation crashed, vault fully restored

Op 3 fails (bad UUID). The proxy detects it, runs `_perform_rollback` in LIFO order, pops each command from the WAL as it succeeds, restores the vault to its pristine state.

```json
{
  "transaction_id": "b5a24dc6-b6c1-4ad4-9096-23d9100b2a9d",
  "timestamp": "2026-02-28T14:12:05.872506",
  "status": "ROLLBACK_SUCCESS",
  "error_message": "ExecutionError: bw: Item 'BAD_UUID' not found",
  "rationale": "Renaming 2 items and moving a third to a folder.",
  "operations_requested": [
    {"action": "rename_item", "target_id": "uuid-github-001", "new_name": "GitHub"},
    {"action": "rename_item", "target_id": "uuid-netflix-007", "new_name": "Netflix HD"},
    {"action": "move_item",   "target_id": "BAD_UUID", "folder_id": "uuid-media"}
  ],
  "execution_trace": [
    "Renamed item uuid-github-001 to 'GitHub'",
    "Renamed item uuid-netflix-007 to 'Netflix HD'"
  ],
  "failed_execution": {"action": "move_item", "target_id": "BAD_UUID"},
  "rollback_trace": [
    "bw edit item uuid-netflix-007 {\"name\": \"Netflix\", ...}",
    "bw edit item uuid-github-001 {\"name\": \"Github\", ...}"
  ]
}
```

**Observation:** The LIFO order is respected — Op 2 is undone before Op 1. The WAL file is consumed (`pop_rollback_command`) as each rollback runs, guaranteeing idempotency even if the proxy crashes *mid-rollback*.

---

### 📄 Case 3: `ROLLBACK_FAILED` — Execution crashed AND the rollback also crashed

The worst case. Op 1 succeeded, Op 2 crashed, AND the rollback for Op 1 also failed (e.g., item deleted externally during the window). **The WAL is intentionally NOT cleared**, so the LLM receives a rich diagnostic message and the human can intervene.

```json
{
  "transaction_id": "a9f2c1d8-0001-dead-beef-ff0000000000",
  "timestamp": "2026-02-28T14:13:00.000000",
  "status": "ROLLBACK_FAILED",
  "error_message": "ExecutionError: bw: Network error | RollbackError: bw: Session expired",
  "rationale": "Renaming GitHub and moving Netflix in the same batch.",
  "operations_requested": [
    {"action": "rename_item", "target_id": "uuid-github-001", "new_name": "GitHub"},
    {"action": "move_item",   "target_id": "uuid-netflix-007", "folder_id": "uuid-media"}
  ],
  "execution_trace": [
    "Renamed item uuid-github-001 to 'GitHub'"
  ],
  "failed_execution": {"action": "move_item", "target_id": "uuid-netflix-007"},
  "rollback_trace": [],
  "failed_rollback": "bw edit item uuid-github-001 {\"name\": \"Github\", ...}"
}
```

**Action required:** Read the `failed_rollback` field and re-run the command manually (`bw edit item <id> '<original_json>'`). The JSON gives you exactly what to type.

---

### 📄 Case 4: `CRASH_RECOVERED_ON_BOOT` — WAL orphan found and executed on startup

The proxy was killed mid-transaction (power cut, `kill -9`). On the next MCP tool call, `check_recovery()` reads the WAL file and calls `_perform_rollback` + `pop_rollback_command` per step before any new operations. Even a crash *during recovery* is safe: the WAL shrinks with every successful step.

```json
{
  "transaction_id": "e1f2a3b4-boot-wal-recovery-uuid",
  "timestamp": "2026-02-28T14:15:00.000000",
  "status": "CRASH_RECOVERED_ON_BOOT",
  "rationale": "Hard-crash detected upon startup. System auto-recovered via WAL.",
  "operations_requested": [],
  "execution_trace": [],
  "rollback_trace": [
    "bw edit item uuid-netflix-007 {\"name\": \"Netflix\", ...}",
    "bw edit item uuid-github-001 {\"name\": \"Github\", ...}"
  ]
}
```

---

### 📦 The WAL File: Your Last Line of Defense

During every transaction execution, the proxy writes a **Write-Ahead Log** to `~/.bw_blind_proxy/wal/pending_transaction.json` **before** each CLI command is executed. The file is deleted once the batch completes (success or clean rollback). If it exists when the proxy starts, it's a crash signal.

**Exact WAL file structure** (`pending_transaction.json`):

```json
{
  "transaction_id": "b5a24dc6-b6c1-4ad4-9096-23d9100b2a9d",
  "timestamp": 1740744725.872,
  "rollback_commands": [
    {
      "cmd": ["bw", "edit", "item", "uuid-netflix-007", "{\"name\": \"Netflix\", \"type\": 1, ...}"]
    },
    {
      "cmd": ["bw", "edit", "item", "uuid-github-001", "{\"name\": \"Github\", \"type\": 1, ...}"]
    }
  ]
}
```

**The invariant:**  
`rollback_commands[N]` is the compensating action for the `N`-th successful operation, stored in **append-then-reverse** order (`list.extend(reversed(cmds))`). On recovery, the list is traversed bottom-up (LIFO), and **each command is popped from the file after successful execution** to guarantee idempotency (see `pop_rollback_command`).

```text
State Machine: WAL lifecycle (v2 — Idempotent Rollback)

  [TX STARTS]
       |
       v
  write_wal(tx_id, [])              ← empty WAL always exists during a TX
       |
       v
  [OP 1 EXECUTES OK]
  write_wal(tx_id, [rb_1])         ← WAL updated after each success
       |
       v
  [OP 2 EXECUTES OK]
  write_wal(tx_id, [rb_1, rb_2])   ← rb_2 is at the end = LIFO head
       |
  ...crash? → WAL file persists on disk
       |
       v
  [ON NEXT BOOT: check_recovery()]
       |
       v
  _perform_rollback(tx_id, [rb_1, rb_2], session)   ← Shared LIFO engine
  ┌─ execute rb_2 ✅ → pop_rollback_command(tx_id) → WAL = [rb_1] (flush to disk!)
  ├─ execute rb_1 ✅ → pop_rollback_command(tx_id) → WAL = []
  │
  │   ...CRASH DURING ROLLBACK? No problem:
  │   At next boot, WAL shows only the REMAINING commands.
  │   Already-executed rollbacks are NEVER double-applied. ✅ IDEMPOTENT
  │
  └─ execute rb_X ❌ → ROLLBACK_FAILED:
       WAL is intentionally NOT cleared.            ← Diagnostic preserved for LLM
       LLM receives structured error msg.
       Human can intervene manually.
       v
  [TX FULLY RECOVERED]
  clear_wal()                                       ← WAL deleted. Clean slate.
```

**Shared Engine Architecture:**
```text
_perform_rollback(tx_id, stack, session_key)
  ↑                    ↑
  │                    │
execute_batch       check_recovery
(on op failure)     (on boot, if WAL found)
```
Both callers receive the same structured result `{success, executed, failed_cmd, error}` and make their own decision about clearing or preserving the WAL based on that result.

---

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
state_directory: "~/.bw_blind_proxy"
```

## 📂 Transparency & File Structure

The proxy maintains a centralized state directory (configurable) for auditing and recovery: `~/.bw_blind_proxy/`

```text
~/.bw_blind_proxy/
├── logs/                  # Immutable Audit Trail (Stripped of secrets) — JSON format
│   ├── 2026-02-28_10-00-01_<uuid>_success.json
│   ├── 2026-02-28_10-15-45_<uuid>_rollback_success.json
│   └── 2026-02-28_11-00-00_<uuid>_rollback_failed.json
└── wal/                   # Recovery Engine (Ephemeral — only exists during active TX)
    └── pending_transaction.json
```

### 🔍 Inside an Audit Log (`logs/*.json`)
Every log is a **structured JSON** — fully machine-parseable and secret-free:
```json
{
  "transaction_id": "c070d585-ba21-4b94-b065-4be725a0bb5b",
  "timestamp": "2026-02-28T10:00:01",
  "status": "SUCCESS",
  "rationale": "Cleaning up obsolete dev credentials as discussed.",
  "operations_requested": [
    {"action": "edit_item_login", "target_id": "550e8400-e29b-41d4-a716-446655440000"},
    {"action": "delete_item",    "target_id": "110b3bed-a3b8-4ee0-9cec-3dd950e2d118"}
  ],
  "execution_trace": [
    "Edited login details for item 550e8400-e29b-41d4-a716-446655440000",
    "Deleted item 110b3bed-a3b8-4ee0-9cec-3dd950e2d118"
  ]
}
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
# View the latest N transactions in a Rich table (default: 5)
uv run bw-proxy logs --n=5

# View the FULL JSON details of a specific transaction
# -- by transaction ID (or unique prefix):
uv run bw-proxy log e4f12a
# -- by recency index (1 = newest, 2 = second newest, etc.):
uv run bw-proxy log --last 1
# -- or just call it bare to get the most recent log:
uv run bw-proxy log

# Inspect the full Write-Ahead Log state (100% JSON transparency)
uv run bw-proxy wal

# Delete old logs, keeping only the N most recent ones to free up space
uv run bw-proxy purge --keep=10
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
