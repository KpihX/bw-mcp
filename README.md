# BW-MCP 🔐🤖

**Sovereign, Exhaustive, & Ultra-Secure Model Context Protocol (MCP) for Bitwarden**

**BW-MCP** is a specialized, air-gapped intermediary designed to physically isolate Large Language Models (LLMs) from your Bitwarden cryptographic secrets, while still granting them 100% organizational superpowers over your vault.

It strongly enforces the **"AI-Blind Management"** philosophy. You can ask an AI (Claude, Cursor, Gemini) to completely reorganize your vault, rename poorly formatted accounts, manage your Enterprise Collections, update credit card expiration dates, or tag hundreds of items as favorites. *The AI will do all of this flawlessly, without ever being able to read or modify your Master Password, your TOTP seeds, your Credit Card CVVs, or your Social Security Number.*

---

## 🧭 The Philosophy

> **Zero Trust · Total Transparency · Total Blind**

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

## 🛠️ Maintainer Entrypoint

If you are an AI agent or a new developer taking over this project, here is your roadmap:

### 1. The Core Engine (ACID & WAL)
- **`src/bw_mcp/transaction.py`**: The Saga Pattern orchestrator. Manages the 3-phase commit (Simulate → Log → Execute → Rollback).
- **`src/bw_mcp/wal.py`**: The Encrypted Write-Ahead Log implementation. Handles Fernet encryption and PBKDF2 key derivation.
- **`src/bw_mcp/subprocess_wrapper.py`**: The raw interface to the `bw` CLI. Handles memory-safe password passing and RAM wiping.

### 2. The Data Layer (Sanitization)
- **`src/bw_mcp/models.py`**: Pydantic models for every Bitwarden entity. This is where `force_redact()` lives—our primary defense against PII leakage.
- **`src/bw_mcp/scrubber.py`**: Recursive payload scrubbing for logs and error messages.

### 3. The Server Interface
- **`src/bw_mcp/server.py`**: FastMCP implementation. Defines the 5 tools and the server lifecycle.
- **`src/bw_mcp/ui.py`**: Zenity-based Human-in-the-Loop dialogue system.

### 4. Quality & Testing
- **`tests/`**: 81+ tests covering transactions, redaction, and crash recovery. Always run `make test` before suggesting a commit.
- **`docs/AUDIT.md`**: Read this to understand the established security invariant before modifying the data flow.

**Notable limitations we cannot fix in code (but mitigate in design):**

| Limitation                          | Root cause                                     | Our mitigation                                                   |
| :---------------------------------- | :--------------------------------------------- | :--------------------------------------------------------------- |
| No atomic `COMMIT`                  | Bitwarden API has no transaction mode          | WAL + LIFO Rollback (Saga Pattern)                               |
| Race condition window               | External clients can modify vault during batch | Batch size cap of 25 ops (configurable)                          |
| Session timeout during long batches | `BW_SESSION` can expire server-side            | Short batches, WAL survives crash for auto-recovery on next boot |

→ **Full details:** [docs/LIMITATIONS.md](docs/LIMITATIONS.md)

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
- [CHANGELOG.md](CHANGELOG.md): The historical evolution from v1.0.0 (Foundation) to v1.9.1 (Sovereign Hardening).

### 🎥 The Zero-Trust Interactive Path
If you want to understand the codebase, read the documentation in this specific order:
1. **[Core Protocol](docs/01_simulation_core_protocol.md)**: How we unlock and wipe RAM.
2. **[Vault Organization](docs/02_simulation_vault_organization.md)**: AI Batching and Orchestration.
3. **[PII & Card Defense](docs/03_simulation_pii_redaction.md)**: Shielding your Identity and Credit Cards.
4. **[Advanced Edge Features](docs/04_simulation_extreme_edge.md)**: Trash, Collections, and Attachments.
5. **[The Destructive Firewall](docs/05_simulation_destructive_firewall.md)**: How Zenity prevents AI hallucinations from deleting your life.
6. **[Safe Creation](docs/06_simulation_safe_creation.md)**: How the AI spawns empty shell items without polluting secrets.
7. **[Advanced Search Filtering](docs/07_simulation_advanced_search.md)**: How the AI optimizes context tokens using the precise backend queries.
8. **[ACID Resilience & Encrypted WAL](docs/08_simulation_acid_wal_resilience.md)**: How the Proxy auto-recovers from an OS-level blackout using encrypted WAL (Fernet + PBKDF2).
9. **[Security Audit Report](docs/AUDIT.md)**: The full 4-pass security audit — 6 defense layers, exposure matrix, crypto review.
10. **[Known Limitations](docs/LIMITATIONS.md)**: Architectural constraints imposed by external APIs and their mitigations.

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

 [ AI Agent ]                       [ BW-MCP ]               [ Bitwarden CLI ]
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

 [ AI Agent ]                       [ BW-MCP ]               [ Bitwarden CLI ]
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
3. **Zero-Memory-Leak Password Strategy:** Your Master Password and `BW_SESSION` key are **never** stored as Python `str` objects (which are immutable and linger in RAM until the Garbage Collector reclaims them). Instead, the proxy:
   - Captures Zenity `stdout` as raw `bytes` (`text=False` in `subprocess.run`).
   - Immediately converts to a mutable `bytearray`.
   - After use, **overwrites every byte with `0x00`** via explicit loop (`for i in range(len(key)): key[i] = 0`).
   - This eliminates the main attack vector of memory dump forensics. **Deep Dive:** Read **[01_simulation_core_protocol.md](docs/01_simulation_core_protocol.md)**.
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
  "error_message": "SecureBWError: An internal error occurred. Check server logs for details.",
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
    "edit item uuid-netflix-007 [PAYLOAD]",
    "edit item uuid-github-001 [PAYLOAD]"
  ]
}
```

**Observation:** The LIFO order is respected — Op 2 is undone before Op 1. The WAL file is consumed (`pop_rollback_command`) as each rollback runs, guaranteeing idempotency even if the proxy crashes *mid-rollback*. Note that `rollback_trace` entries are **sanitized** by `_sanitize_args_for_log` — base64 payloads and raw JSON are replaced with `[PAYLOAD]` tags. The `error_message` is filtered through `_safe_error_message` to prevent exception internals from leaking to disk.

---

### 📄 Case 3: `ROLLBACK_FAILED` — Execution crashed AND the rollback also crashed

The worst case. Op 1 succeeded, Op 2 crashed, AND the rollback for Op 1 also failed (e.g., item deleted externally during the window). **The WAL is intentionally NOT cleared**, so the LLM receives a rich diagnostic message and the human can intervene.

```json
{
  "transaction_id": "a9f2c1d8-0001-dead-beef-ff0000000000",
  "timestamp": "2026-02-28T14:13:00.000000",
  "status": "ROLLBACK_FAILED",
  "error_message": "SecureBWError: An internal error occurred. Check server logs for details.",
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
  "failed_rollback": "edit item uuid-github-001 [PAYLOAD]"
}
```

**Action required:** Read the `failed_rollback` field and inspect the WAL or Bitwarden web vault to identify the original state. Note that `[PAYLOAD]` masks the base64-encoded original item JSON — the proxy never writes raw secrets to log files.

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
    "edit item uuid-netflix-007 [PAYLOAD]",
    "edit item uuid-github-001 [PAYLOAD]"
  ]
}
```

---

### 📦 The WAL File: Your Last Line of Defense

During every transaction execution, the proxy writes an **AES-encrypted Write-Ahead Log** to `~/.bw/mcp/wal/pending_transaction.wal` **before** each CLI command is executed. The file is deleted once the batch completes (success or clean rollback). If it exists when the proxy starts, it's a crash signal.

#### 🔐 WAL Encryption Architecture

The WAL file is **never** stored as plaintext on disk. It is encrypted using a layered cryptographic pipeline:

```text
                    ┌──────────────────────────────────────────────────┐
                    │           WAL CRYPTO PIPELINE                    │
                    │                                                  │
  Master Password   │   ┌───────────┐   ┌─────────┐   ┌───────────┐  │
  (bytearray) ──────┼──▶│  PBKDF2   │──▶│ 32-byte │──▶│  Fernet   │  │
                    │   │ HMAC-SHA256│   │   key   │   │ Encrypt   │  │
  os.urandom(16) ───┼──▶│ 480k iter │   └─────────┘   │ (AES-128  │  │
  (random salt)     │   └───────────┘                  │  +HMAC)   │  │
                    │                                  └─────┬─────┘  │
                    │                                        │        │
                    │   .wal file on disk = [salt‖ciphertext]│        │
                    └────────────────────────────────────────┘        │
```

**Why this stack?**

| Component     | What it is                                                                                                                  | Why we chose it                                                                                                                                                                                                           |
| :------------ | :-------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Fernet**    | A symmetric encryption scheme from the `cryptography` library implementing AES-128-CBC with HMAC-SHA256 for authentication. | Provides **authenticated encryption** out of the box — a tampered ciphertext is detected and rejected. No need to manually manage IVs or MAC tags.                                                                        |
| **PBKDF2**    | Password-Based Key Derivation Function v2 (RFC 8018). Repeatedly hashes the input with HMAC-SHA256.                         | Makes brute-force infeasible: 480,000 iterations mean that trying 1 billion passwords would take ~years on consumer hardware. Even if the `.wal` file is stolen, the key cannot be recovered without the Master Password. |
| **Salt**      | A 16-byte random value generated fresh via `os.urandom()` for **every** WAL write.                                          | Two identical Master Passwords produce different derived keys across different writes. This defeats precomputation attacks (rainbow tables) and ensures each WAL encryption is cryptographically unique.                  |
| **bytearray** | A mutable byte sequence used instead of Python's immutable `str`.                                                           | Allows **manual memory zeroing** (`key[i] = 0`) after use. Python's GC cannot guarantee when a `str` is freed, but a zeroed `bytearray` contains nothing exploitable.                                                     |

**WAL binary format on disk** (`pending_transaction.wal`):
```text
┌──────────────────┬─────────────────────────────────┐
│  Salt (16 bytes) │  Fernet Ciphertext (variable)   │
│  os.urandom(16)  │  AES-128-CBC + HMAC-SHA256      │
└──────────────────┴─────────────────────────────────┘
                   ▲
                   │ chmod 600 (owner-only read/write)
```

**Decrypted logical structure** (only visible in RAM after correct password):
```json
{
  "transaction_id": "b5a24dc6-b6c1-4ad4-9096-23d9100b2a9d",
  "timestamp": 1740744725.872,
  "rollback_commands": [
    {"cmd": ["bw", "edit", "item", "uuid-netflix-007", "<base64_encoded_original_item>"]},
    {"cmd": ["bw", "edit", "item", "uuid-github-001", "<base64_encoded_original_item>"]}
  ]
}
```

**The invariant:**  
`rollback_commands[N]` is the compensating action for the `N`-th successful operation, stored in **append-then-reverse** order (`list.extend(reversed(cmds))`). On recovery, the list is traversed bottom-up (LIFO), and **each command is popped from the file after successful execution** to guarantee idempotency (see `pop_rollback_command`).

```text
State Machine: WAL lifecycle (v3 — Encrypted + Idempotent Rollback)

  [TX STARTS]
       |
       v
  write_wal(tx_id, [], master_pw)     ← empty WAL, encrypted with fresh salt
       |
       v
  [OP 1 EXECUTES OK]
  write_wal(tx_id, [rb_1], master_pw) ← WAL re-encrypted after each success
       |
       v
  [OP 2 EXECUTES OK]
  write_wal(tx_id, [rb_1, rb_2], master_pw)
       |
  ...crash? → Encrypted .wal file persists on disk
       |
       v
  [ON NEXT BOOT: check_recovery(master_pw, session_key)]
       |
       v
  read_wal(master_pw)  ← Decrypt with PBKDF2 + Fernet
       |
       v
  _perform_rollback(tx_id, [rb_1, rb_2], master_pw, session_key)
  ┌─ execute rb_2 ✅ → pop_rollback_command(tx_id, master_pw) → re-encrypt WAL = [rb_1]
  ├─ execute rb_1 ✅ → pop_rollback_command(tx_id, master_pw) → re-encrypt WAL = []
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
  clear_wal()                                       ← Encrypted .wal deleted. Clean slate.
```

**Shared Engine Architecture:**
```text
_perform_rollback(tx_id, stack, master_password, session_key)
  ↑                    ↑
  │                    │
execute_batch       check_recovery
(on op failure)     (on boot, if WAL found)
```
Both callers receive the same structured result `{success, executed, failed_cmd, error}` and make their own decision about clearing or preserving the WAL based on that result.

---

## 🔌 MCP Tools Reference (Inputs & Outputs)

The Proxy exposes exactly **six** tools to the AI Agent. This limits the attack surface while enabling profound orchestration and self-auditing capabilities. Global context (Security, Batch Limits, ACID rules) is delivered to the AI via a **Meta-Prompt instruction** upon server initialization, ensuring zero-latency alignment.

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
*   **Auditing & CLI:** Every modification request is written to a human-readable, secret-stripped log in `logs/transactions/`. A dedicated Typer/Rich CLI (`bw-admin log view`) allows you to view the latest modifications beautifully in the terminal.
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

*   **Output (AI receives):** A success string or a sanitized error. If the AI tries to manipulate forbidden keys, Pydantic rejects the payload and `_safe_error_message` strips the field values from the error to prevent the AI from seeing what was rejected.

**Example Expected Output:**
```text
Transaction completed successfully.
- Moved item uuid-item-1 to folder uuid-folder-1
```

**Example Failure Output (If AI attempts a hack):**
```text
Error: Invalid transaction payload. ValidationError: An internal error occurred. Check server logs for details.
```
> **Why not show the full ValidationError?** Because Pydantic includes the rejected field **values** in its error message (e.g., `input_value='stolen_secret'`). The `_safe_error_message` function strips this, returning only the exception type name.

### 3. `get_proxy_audit_context(limit)`
**Description:** Allows the AI to check the operational health of the proxy.
*   **Returns:**
    *   The `MAX_BATCH_SIZE` currently configured.
    *   The **WAL Status**: whether the vault is synchronized (`CLEAN`) or if a previous transaction crashed and is awaiting recovery (`PENDING`).
    *   A summary of the last `N` transactions (timestamp, status, rationale).

### 4. `inspect_transaction_log(tx_id, n)`
**Description:** Grants the AI access to the full, unredacted JSON audit logs generated by the `TransactionLogger`. 
*   **Use Case:** If the AI receives a `ROLLBACK_FAILED` status, it can use this tool to read the `execution_trace`, the `rollback_trace`, and specifically the `failed_rollback` string, allowing it to provide the exact manual recovery command to the human user.

### 5. `refactor_item_secrets(rationale, operations)`
**Description:** Breakthrough tool for **AI-Blind secret migration** (Move, Copy, Delete).
*   **Move**: Transparently migrates a secret from source to destination and cleans up the source.
*   **Copy**: Clones a secret (e.g., password -> custom field backup) across any items.
*   **Delete**: Securely nullifies a secret field.
*   **Batching**: Can execute multiple refactor operations in a single ACID transaction, mixed with standard edits.

### 6. `get_template(template_type)`
**Description:** Safely fetches Bitwarden entity schemas.

---

## 🛠️ Architecture

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                       BW-MCP — ARCHITECTURE                                 │
└─────────────────────────────────────────────────────────────────────────────┘

  ┌──────────────────────────┐
  │  Agent Workspace         │  (Claude / Gemini / Cursor)
  │  (LLM has ZERO secrets)  │
  └────────┬─────────────────┘
           │  Tool Call (get_vault_map / propose_vault_transaction)
           ▼
  ┌──────────────────────────┐
  │  FastMCP Server          │  ← 5 tools exposed, meta-prompt aligned
  │  server.py               │
  └──────┬───────────────────┘
         │                          │ READ path
         │ WRITE path               ▼
         │                 ┌───────────────────┐
         │                 │  Pydantic Models  │  BlindItem redaction
         │                 │  models.py  🔒    │  extra="forbid" on writes
         │                 └────────┬──────────┘
         │                          │ Redacted payload → back to Agent
         ▼
  ┌──────────────────────────┐
  │  Virtual Vault &         │  Validates batch · Pre-computes rollback stack
  │  WAL Engine              │
  │  transaction.py + wal.py │
  └──────┬───────────────────┘
         │
         ▼
  ┌──────────────────────────┐
  │  Human-in-the-Loop       │  Zenity popup → Red Alert for destructive ops
  │  ui.py  ⚠️               │  Master Password captured as bytearray
  └──────┬───────────────────┘
         │  Approved + Password
         ▼
  ┌──────────────────────────┐
  │  WAL Disk (Encrypted)    │  Fernet(AES-128) + PBKDF2(480k iter) + salt
  │  ~/.bw/mcp/wal/  │  chmod 600 · idempotent pop on each step
  └──────┬───────────────────┘
         │
         ▼
  ┌──────────────────────────┐
  │  subprocess `bw` CLI     │  bytearray session key → zeroed in finally
  │  subprocess_wrapper.py   │
  └──────┬──────────┬────────┘
         │          │
    Success        Failure / Crash
         │          │
         ▼          ▼
  ┌────────────┐  ┌───────────────────────┐
  │ Clear WAL  │  │  LIFO Crash Recovery  │  Rollback applied in reverse
  │ Write Log  │  │  transaction.py       │  WAL preserved until clean
  └────────────┘  └───────────────────────┘
```

---

## 🛠️ Exhaustive API Coverage (17 Enum Actions)

The proxy maps Bitwarden's complex CLI into 17 robust, completely secure internal Enums.

### 🧠 AI Contextualization (Self-Documenting Templates)
Before proposing data mutations, the AI (or the Human) can dynamically fetch the exact, strict JSON schemas of Bitwarden entities. This system completely eliminates hallucinated fields and ensures migrations perfectly match the underlying `bw` CLI expectations.

- **`get_template(template_type)` Tool**: A native MCP tool allowing the autonomous agent to securely fetch the JSON schema of entities (e.g., `item.login`, `item.card`, `folder`).
- **`template_resource` (URI: `bw://templates/{template_type}`)**: Native MCP resources exposed natively to the host app. An operator can inject clean schemas directly without requiring an AI tool-execution round-trip (e.g., typing `@bw://templates/item.login` in Cursor).

**Illustration (Transparency & Strict Scrubbing):**
When a template is requested, the proxy forces a `bw get template ...`, intercepts the JSON, and strictly purges any keys where secrets might reside *before* returning it to the LLM. The AI only sees a perfectly safe skeleton.
```json
{
  "_metadata": {
    "source": "bw get template item.login",
    "note": "Secret fields have been proactively redacted by BW-MCP to maintain AI-Blindness. Empty fields remain empty."
  },
  "template": {
    "passwordHistory": [],
    "type": 1,
    "name": "Item name",
    "notes": "[REDACTED_BY_PROXY_EMPTY]",
    "login": {
      "username": "",
      "password": "[REDACTED_BY_PROXY_EMPTY]",
      "totp": "[REDACTED_BY_PROXY_EMPTY]",
      "uris": [
        { "match": null, "uri": "https://google.com" }
      ]
    }
  }
}
```

### Item Organization (`ItemAction`)
1.  **`create_item`**: Spawns an empty shell (Login, Note, Card, Identity) locally. Strictly blocks LLM from creating secrets safely.
2.  **`rename_item`**: Safely alters the name of a secret.
3.  **`move_item`**: Reparents an item inside a specific Folder UUID.
4.  **`favorite_item`**: Toggles the star/favorite status.
5.  **`delete_item`**: [🚨 RED ALERT] Removes item to the Trash.
6.  **`restore_item`**: [Phase 4 Edge] Recovers an item from the Trash.
7.  **`toggle_reprompt`**: [Phase 4 Edge] Enables/Disables Master Password Reprompt requirement for specific high-value items.
8.  **`move_to_collection`**: [Phase 4 Edge] Enterprise Organization sharing mapping.
9.  **`delete_attachment`**: [Phase 4 Edge - ISOLATED] Forcefully removes physical file attachments. **UNRECOVERABLE** — must be the only operation in its batch.

### Folder Operations (`FolderAction`)
10. **`create_folder`**: Instantiates a new logical grouping.
11. **`rename_folder`**: Self-explanatory.
12. **`delete_folder`**: [🚨 RED ALERT - ISOLATED] Hard-deletes a folder. **Bitwarden folders have NO trash** — this is permanent and not reversible by rollback. All items inside lose their `folderId` reference (moved to "No Folder"). **MUST be the only operation in its batch.** `restore_folder` does NOT exist in the Bitwarden CLI and has been removed.

### Granular PII Editing (`EditAction`)
To edit an item, the Python Subprocess grabs the full hidden JSON locally, surgically injects the AI's safe modification, and pushes it back up.
13. **`edit_item_login`**: Safely updates `Username` & `URIs`. (Strictly rejects attempts to edit `password` or `totp`).
14. **`edit_item_card`**: Safely updates Expiration Dates, Name, & Brand. (Strictly rejects Credit Card Number & CVV edits).
15. **`edit_item_identity`**: Safely updates Standard Address & Contact Info. (Strictly rejects SSN, Passport, and License edits).
16. **`upsert_custom_field`**: Adds/updates unstructured metadata. (Strictly limited to `Type 0: Text` and `Type 2: Boolean`. The AI is blocked from reading or altering `Type 1: Hidden` or `Type 3: Linked` secrets).
17. **`vault_refactor`**: [🆕 v2.0] Atomic Move/Copy/Delete of secret fields. Enables AI-led vault reorganization without secret exposure.

---

### 🦾 The "Extreme Edge" (Phase 4 Logic)
For organizational perfection, the Proxy handles advanced states without ever touching the secret keys:

```text
    [ TRASH ] <--- restore_item --- [ PROXY ] --- delete_attachment ---> [ FILES ]
                                       |
    [ ORG   ] <--- move_to_coll --- [ PROXY ] --- toggle_reprompt  ---> [ RE-AUTH ]
```

> **🟡 Point of Vigilance (Theoretical Edge Case): `move_to_collection`**
> Moving an item to an Enterprise Organization transfers ownership. Reverting this operation (rolling back to a personal vault) depends entirely on Enterprise Policies. If the user lacks Admin privileges and the Org enforces a "Block moving out of organization" policy, the Bitwarden server will reject the rollback command. The proxy gracefully catches this API failure, prevents crash, and alerts the user/agent that rollback permissions were denied.

**Deep Dive:** Explore how these complex subcommands are executed in **[04_simulation_extreme_edge.md](docs/04_simulation_extreme_edge.md)**.

---

## 🔒 Security Posture & ACID Compliance

The core philosophy of **BW-MCP** is **Zero-Trust for the AI, Total-Reliability for the Human**. We achieve this by treating Bitwarden modifications as database transactions.

### 📜 What is ACID?
We implement the four pillars of database reliability to protect your vault:
*   **A - Atomicity (Atomicité) :** Every batch of operations is "All-or-Nothing". If one rename fails, all preceding creates/deletes in that batch are automatically reversed.
*   **C - Consistency (Cohérence) :** Data is validated against strict Pydantic models in a **Virtual Vault** (RAM) before hitting the CLI.
*   **I - Isolation :** Each transaction is processed in its own secure session context.
*   **D - Durability (Durabilité) :** Once a transaction starts, its intent is written to **encrypted disk** (Fernet + PBKDF2). It survives process death (`kill -9`) and power outages.

### 🛡️ WAL: Write-Ahead Logging (D-Durability)
To guarantee **Durability**, we use a **WAL Engine** with **AES encryption at rest**. 
1. **The Log First:** Before `bw` executes any destructive command, the proxy derives a Fernet key from your Master Password (PBKDF2, 480k iterations) and encrypts the **Compensating Action** (Rollback) to `pending_transaction.wal`.
2. **Atomic Recovery:** Upon any tool call (like `get_vault_map`), the proxy first checks for a stranded WAL. If found, it re-prompts for the Master Password, decrypts the WAL, and forces a vault repair **before** allowing further actions.
3. **Defense-in-depth:** The `.wal` file is `chmod 600` (owner-only access). Even if an attacker can read the file, the AES ciphertext is useless without the Master Password.

### 🛡️ Error Message Sanitization
Every error message returned to the LLM passes through `_safe_error_message()`. Only `SecureBWError` messages (pre-sanitized by structural CLI token whitelisting) are passed through. All other Python exceptions (which may include secret data in their `str()` representation) are replaced with a generic `"TypeName: An internal error occurred."` message.

### 🛡️ Log Scrubbing Engine (`deep_scrub_payload`)
Before any data is written to the audit logs on disk, the `deep_scrub_payload()` function recursively walks the entire data structure and replaces the values of sensitive keys with `[PAYLOAD]` tags. The key list (`_SECRET_KEYS`) covers: `password`, `totp`, `notes`, `value`, `ssn`, `number`, `code`, `passportNumber`, `licenseNumber`, `key`.

### 🛡️ CLI Token Redaction (`_sanitize_args_for_log`)
When logging Bitwarden CLI commands (in rollback traces and error messages), a **whitelist-only** strategy is used. Only known-safe tokens (verbs like `edit`, object types like `item`, UUIDs, and CLI flags) survive. Everything else — JSON payloads, base64 blobs, passwords — is replaced with `[PAYLOAD]`.

---

## ⚙️ Configuration & Internalization

Following the developer mandate of **Independent Autonomous Packages**, the configuration is internalized within the package source.

*   **Location:** `src/bw_mcp/config.yaml`
*   **Customization:** You can modify the `state_directory`, batch size, redaction tags, and cryptographic parameters.

```yaml
# src/bw_mcp/config.yaml
proxy:
  name: "BW-MCP"
  state_directory: "~/.bw/mcp"
  max_batch_size: 25

redaction:
  populated_tag: "[REDACTED_BY_PROXY_POPULATED]"
  empty_tag: "[REDACTED_BY_PROXY_EMPTY]"

security:
  payload_tag: "[PAYLOAD]"        # Mask for opaque CLI payloads in logs/errors
  bw_password_env: "BW_PASSWORD"  # Env var name for Master Password injection
  bw_session_env: "BW_SESSION"    # Env var name for Session Key injection

wal_crypto:
  salt_length: 16       # Random salt per WAL write (bytes)
  key_length: 32         # AES key derived from PBKDF2 (bytes)
  iterations: 480000     # PBKDF2 iteration count (brute-force resistance)
```

## 📂 Transparency & File Structure

The proxy maintains a centralized state directory (configurable) for auditing and recovery: `~/.bw/mcp/`

```text
~/.bw/mcp/
├── logs/                  # Immutable Audit Trail (Scrubbed of secrets) — JSON format
│   ├── 2026-02-28_10-00-01_<uuid>_success.json
│   ├── 2026-02-28_10-15-45_<uuid>_rollback_success.json
│   └── 2026-02-28_11-00-00_<uuid>_rollback_failed.json
└── wal/                   # Recovery Engine (Ephemeral — only exists during active TX)
    └── pending_transaction.wal   ← AES-encrypted (Fernet + PBKDF2)
```

### 🔍 Inside an Audit Log (`logs/*.json`)
Every log is a **structured JSON** — fully machine-parseable and **secret-free** thanks to `deep_scrub_payload` and `_sanitize_args_for_log`:
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
> **Security note:** The `operations_requested` field is scrubbed by `deep_scrub_payload` — any `password`, `value`, `notes`, etc. are replaced with `[PAYLOAD]`. The `rollback_trace` entries use `_sanitize_args_for_log` — base64 blobs become `[PAYLOAD]`.

### 🔐 Inside a WAL Entry (`wal/pending_transaction.wal`)
This file exists **only** during an active transaction. It is **AES-encrypted at rest** — its contents are never visible as plaintext on disk.
```text
Binary format: [16-byte salt][Fernet ciphertext (AES-128-CBC + HMAC-SHA256)]
Permissions:   chmod 600 (owner-only read/write)
Decryption:    Requires the same Master Password used during the transaction.
```
To inspect a stranded WAL, use the CLI: `bw-admin wal view` (prompts for Master Password, displays scrubbed content).

---

## 🔧 Installation & Commands

Requires Python 3.12+ and `uv`.

### 🛡️ Sovereign Hardened Installation (Recommended)
This is the production standard for KpihX-compliant environments. The source code is installed into `/opt/bw-mcp` with `root:root` ownership, while data and configs are isolated in the user's home with strict permissions.

```bash
# 1. Clone the repo
git clone https://github.com/KpihX/bw-mcp.git
cd bw-mcp

# 2. Perform the sovereign install (requires sui/sudo for /opt/ and AppArmor)
sui make install

# 3. Verify the installation security
make audit
```

### 🖥️ Native Auditing CLI (`bw-admin`)

The proxy features an underlying auditor capturing every structural modification intent.

```bash
# View a table of the 5 most recent transactions
bw-admin log view -l 5

# View the FULL JSON details of the most recent transaction (index 1)
bw-admin log view -n 1

# Delete old logs, keeping only the 10 most recent ones
bw-admin log purge -k 10

# Inspect the full Write-Ahead Log state (Requires Master Password)
bw-admin wal view

# Delete the Write-Ahead Log to force-clear stranded transactions (Requires Master Password)
bw-admin wal delete

# View full configuration
bw-admin config get
```

### ⚙️ Daemon Lifecycle CLI (`bw-mcp`)

The main entrypoint acts as a lightweight daemon controller similar to `systemd` or `nginx`.
When run by an AI client without arguments, it defaults to `bw-mcp serve` (stdio mode).

```bash
# Check if the server is currently running (reads PID file)
bw-mcp status

# Stop a running server cleanly via SIGTERM
bw-mcp stop

# Restart the server (Useful after 'sui make install' to load new bytecode)
# The MCP client will automatically respawn it on the next query.
bw-mcp restart

# Print current version
bw-mcp version
```

### 🔌 Adding to an MCP Client

To integrate this sovereign proxy into your favorite AI agent, use the following configurations.

#### 1. Recommended (Global Installation)
If you installed the proxy via `uv tool install bw-mcp`, the configuration is extremely simple:

**Claude Desktop (`claude_desktop_config.json`):**
```json
{
  "mcpServers": {
    "bw-mcp": {
      "command": "bw-mcp",
      "args": []
    }
  }
}
```

**Cursor / Other IDEs:**
Register a new MCP server with:
- **Type:** `command`
- **Command:** `bw-mcp`

#### 2. Local Development (Fallthrough)
If you are running from the source code without global installation:

**Claude Desktop:**
```json
{
  "mcpServers": {
    "bw-mcp": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/bw-mcp",
        "run",
        "bw-mcp"
      ]
    }
  }
}
```

#### 3. Gemini CLI Extension Integration 🤖

If you use the `gemini-cli`, you can integrate `bw-mcp` natively to give your agent Bitwarden superpowers.

**Case A: Local Development / Cloned Repository**

1. In the root of your `bw-mcp` clone, create a `gemini-extension.json`:
```json
{
  "name": "bw-mcp",
  "version": "1.5.0",
  "description": "Sovereign IA-Blind Proxy for Bitwarden",
  "mcpServers": {
    "bw-mcp": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/bw-mcp/",
        "run",
        "bw-mcp"
      ]
    }
  },
  "contextFileName": "GEMINI.md"
}
```
> **Tip:** You can customize `GEMINI.md` in the project root to provide specific, persistent instructions to the Gemini agent regarding your vault's security policy or organization preferences.

1. Install the extension directly from the folder:
```bash
gemini extensions install .
```

**Case B: Installation via PyPI**

1. Create a dedicated directory for the extension bridge (e.g., `~/bw-gemini`).
2. Inside, create a `gemini-extension.json` pointing to your global `bw-mcp` executable:
```json
{
  "name": "bw-mcp",
  "version": "1.5.0",
  "description": "Sovereign IA-Blind Proxy for Bitwarden",
  "mcpServers": {
    "bw-mcp": {
      "command": "/path/to/your/.local/bin/bw-mcp",
      "args": []
    }
  },
  "contextFileName": "GEMINI.md"
}
```
3. (Optional) Create a `GEMINI.md` in that directory for custom instructions.
4. Install the extension using the folder path:
```bash
gemini extensions install ~/bw-gemini/
```

**Verification**

Check that the server is detected and active:
```bash
gemini extensions list
# or
gemini mcp list
```

---

## 🚨 Troubleshooting (Discovered During Live Simulation)

These issues were discovered during a real-world MCP simulation session and are now handled gracefully by the proxy.

### 1. `get_vault_map` returns almost no items after a server import

**Symptom:** You imported credentials via the Bitwarden/Vaultwarden Web UI, but the proxy only shows a handful of old items.

**Cause:** The Bitwarden CLI operates on a **local encrypted cache**. It does NOT contact the server on every `bw list` command. After a large import on the Web, the CLI's cache is stale.

**Solution:** If the CLI is out of sync, the proxy natively executes a strict `bw sync` before any transaction or read query. You do not need to do this manually anymore.

### 2. Bitwarden Mobile/Desktop shows "Sync Failed" or "An error has occurred"

**Symptom:** After a massive import, client apps (phone, desktop) fail to synchronize.

**Cause:** The local database of rich UI clients can become "confused" after a sudden, large structural change to the vault. This is a known Bitwarden behavior.

**Solution:** **Log out** of the app completely, then **log back in**. This forces the app to rebuild its local database from scratch. On mobile: `Settings > Log Out`. On Desktop: `Account > Log Out`. This does NOT delete your data; it simply rebuilds the local cache.

### 3. `list org-collections` fails (Organizations)

**Symptom:** The proxy logs `Bitwarden command list org-collections failed.`

**Cause:** If your Bitwarden account has no active Organization membership (e.g., personal/free tier), the CLI returns an error instead of an empty list. This is a Bitwarden CLI quirk.

**Solution:** The proxy now handles this **gracefully**. Organization and collection fetching is wrapped in a try-except block. If it fails, the `organizations` and `collections` fields are returned as empty arrays `[]`, and the rest of the vault data is served normally. You can also set `include_orgs=False` to skip this step entirely.

### 4. `BlindFolder` or `BlindItem` crash on `id: null`

**Symptom:** `ValidationError: Input should be a valid string [type=string_type, input_value=None]`

**Cause:** Bitwarden returns a sentinel "No Folder" entry with `"id": null`. The Pydantic models originally required `id: str`.

**Solution:** Fixed. All structural models (`BlindItem`, `BlindFolder`, `BlindOrganization`) now accept `id: Optional[str] = None`.

---

## 📖 Deep Dives & Simulations
To truly trust a sovereign proxy, you must understand how it behaves in extreme edge cases. Read these explicit simulations in the `docs/` folder:

* `docs/bitwarden_architecture.md`: Explains the granular anatomy of the Bitwarden schemas and the reverse-engineering used for the Proxy's defense model.
* `docs/01_simulation_core_protocol.md`: The base AI negotiation cycle, `bytearray` memory wiping, and `text=False` capture.
* `docs/02_simulation_vault_organization.md`: Complex orchestration and batching logic.
* `docs/03_simulation_pii_redaction.md`: How Pydantic obliterates AI attempts to modify PII and Custom Hidden Fields.
* `docs/04_simulation_extreme_edge.md`: *(See actual file for Phase 4 Trash/Collection/Reprompt capabilities)*.
* `docs/05_simulation_destructive_firewall.md`: How the Red Alert systems protect against malicious AI deletions.
* `docs/06_simulation_safe_creation.md`: How the AI creates safe empty shells without generating passwords.
* `docs/07_simulation_advanced_search.md`: Precision mapping and search queries to limit LLM context bloat.
* `docs/08_simulation_acid_wal_resilience.md`: Encrypted WAL, crash-recovery, PBKDF2/Fernet pipeline, and idempotent rollback.
* `docs/AUDIT.md`: **Full security audit report** — 6 defense layers, exposure surface matrix, `str(e)` exhaustive classification, cryptographic architecture review, brute-force resistance analysis.
* `docs/LIMITATIONS.md`: Known architectural limitations and mitigations.

---
**Maintained with 100% transparency. Your secrets remain yours.**
