# 🧠 Project Memory: BW-Blind-Proxy

**Project:** BW-Blind-Proxy v1.2.0
**Status:** Production-Ready. 58/58 tests pass. Full security audit complete.
**Duration:** ~24h of intensive pair-programming (2026-02-28 to 2026-03-01).
**Stack:** Python 3.12+ · `mcp` SDK · Pydantic v2 · Fernet/PBKDF2 · Typer/Rich · Zenity

---

## 1. 🎯 The Problem That Started Everything

### Why does this project exist?
AI agents (Claude Code, Gemini CLI, Cursor…) are powerful but **inherently untrustworthy with secrets**. The moment you let an LLM call `bw get item <id>`, it sees your plaintext password, your TOTP seed, your credit card number. Even if the LLM doesn't *intend* to leak them, those secrets become part of the context window, get sent to remote APIs, and may appear in logs, error messages, or cached embeddings.

### The fundamental question:
> **"Can we give an AI full organizational control over a Bitwarden vault WITHOUT it ever seeing a single secret?"**

The answer is **yes**, but it requires a radical architectural decision: the AI operates on *metadata shadows* of your vault, never on the real data. This is the **"Total Blind"** philosophy.

---

## 2. 🔑 Bitwarden CLI: What We Learned the Hard Way

### 2.1. The Data Model Is NOT a Filesystem
**The trap:** We initially treated folders like filesystem directories. If you delete a folder, you'd expect its contents to go with it. **Wrong.**

**Reality:** Bitwarden folders are lightweight labels, not containers. When you delete a folder:
- The folder itself is **hard-deleted** (no trash for folders).
- Items inside **lose their `folderId`** (set to `null`) — they become "un-foldered".
- Items are NOT deleted, NOT moved to trash. They just silently orphan.

**Why this matters for rollback:** We initially implemented `restore_folder` as a rollback for `delete_folder`. This command **does not exist** in the Bitwarden CLI (`bw restore` only accepts `item` as an object type). We discovered this empirically. The correct approach was to **isolate `delete_folder` as a standalone batch** (like `delete_attachment`), making rollback conceptually unnecessary.

### 2.2. The Trash Model Is Asymmetric
| Object     |      Soft-Delete (Trash)      |                       Hard-Delete                       |         Restore          |
| :--------- | :---------------------------: | :-----------------------------------------------------: | :----------------------: |
| Item       | `bw delete item <id>` → Trash |            `bw delete item <id> --permanent`            | `bw restore item <id>` ✅ |
| Folder     |             ❌ N/A             |          `bw delete folder <id>` (always hard)          |     ❌ Does not exist     |
| Attachment |             ❌ N/A             | `bw delete attachment <id> --itemid <id>` (always hard) |     ❌ Does not exist     |

**Lesson:** Never assume symmetrical behavior across object types. Always `bw <command> --help` first.

### 2.3. The `bw edit` Command Is Total-State Replacement
`bw edit item <id> <base64_json>` does **not** merge fields. It **replaces the entire item** with whatever JSON you provide. This is both dangerous and powerful:
- **Dangerous:** If you forget a field, it disappears from the item.
- **Powerful:** It means rollback = "push the original JSON back", which is conceptually perfect.

**Our approach:** Before every edit, we `bw get item <id>` to snapshot the full state, apply our surgical modification in RAM, push the modified state, and store the original state in the WAL for rollback. This is a **read-modify-write** pattern, similar to database row-level locking.

### 2.4. The `bw move` Command Transfers Ownership
`bw move <id> <organizationId>` is an **ownership transfer**, not a copy. Once moved to an Enterprise Organization, moving the item *back* to the personal vault depends on Enterprise Policies. If "Block moving out of organization" is enabled, the rollback `bw edit` will be rejected by the server. This is an accepted edge case — we catch the exception gracefully, surface the error, and the WAL is preserved for manual intervention.

### 2.5. The `bw create` Command Requires Base64
All `bw create` and `bw edit` commands expect base64-encoded JSON, not raw JSON. The workflow is:
```
Python dict → json.dumps() → .encode() → base64.b64encode() → .decode() → pass to CLI
```
This is non-obvious and underdocumented. We encapsulate it in our `transaction.py` so the AI never has to deal with encoding.

---

## 3. 🛡️ Security Principles: The Six Layers of Defense-in-Depth

### 3.1. Layer 1 — Pydantic Read Firewall (The Blindfold)
**Problem:** The AI needs to know *what's in the vault* (names, types, folders) without seeing *the actual secrets* (passwords, TOTP, SSN).

**Solution:** Every raw Bitwarden item passes through a Pydantic model (`BlindItem`, `BlindLogin`, `BlindCard`, `BlindIdentity`) that:
1. Replaces populated secret fields with `[REDACTED_BY_PROXY_POPULATED]`.
2. Replaces empty secret fields with `[REDACTED_BY_PROXY_EMPTY]`.
3. Drops unexpected fields via `model_config = ConfigDict(extra="ignore")`.

**Why distinct tags?** An AI that knows "the password field is empty" can proactively offer to help set one. An AI that only sees a generic `[REDACTED]` cannot distinguish between "no password set" and "password exists but hidden" — losing useful organizational context.

### 3.2. Layer 2 — Pydantic Write Firewall (The Bouncer)
**Problem:** The AI could craft a malicious payload like `{"action": "create_item", "password": "backdoor123"}` to inject secrets.

**Solution:** Every write action model uses `model_config = ConfigDict(extra="forbid")`. Pydantic will throw a `ValidationError` if the AI includes ANY field not explicitly declared in the schema. Since `password`, `totp`, `ssn`, `number`, `code` are never declared in write schemas, they are mathematically impossible to inject.

**Subtlety for Custom Fields:** `UpsertCustomFieldAction.type` is `Literal[0, 2]` — only Text (0) and Boolean (2) are allowed. Hidden (1) and Linked (3) are forbidden, preventing the AI from burying secrets in custom fields.

### 3.3. Layer 3 — Human-in-the-Loop (The Gatekeeper)
**Problem:** Even with firewalls, the AI could request legitimate-but-unwanted bulk deletions.

**Solution:** Every write transaction triggers a Zenity popup requiring the human to:
1. **Review** the operation list (with 💥 RED ALERT icons for destructive ops).
2. **Type their Master Password** to unlock the vault.

The AI is TCP-frozen during this entire process — it receives nothing until the human approves.

### 3.4. Layer 4 — Memory Lifecycle (The Assassin)
**Problem:** Python `str` is immutable. Every `.strip()`, f-string, or dict assignment creates a *new copy* of the secret. Old copies linger in the heap until the Garbage Collector runs. During that window (seconds to minutes), `cat /proc/<pid>/mem` can extract the plaintext.

**Solution:** We use `bytearray` for all sensitive data:
```python
# BAD: str is immutable — copies forever
password = subprocess.stdout.decode()  # str copy #1
env["BW_PW"] = password                # str copy #2
# Both linger in memory until GC

# GOOD: bytearray is mutable — we control the lifecycle
password = bytearray(subprocess.stdout)  # mutable buffer
# ... use it ...
for i in range(len(password)):
    password[i] = 0  # physical overwrite in-place
del password
```

**The `os.environ` Problem:** Python forces `str` for env dict values. We mitigate this with:
```python
os.environ["BW_SESSION"] = session_key.decode()
# ... subprocess runs ...
os.environ["BW_SESSION"] = "DEADBEEF"  # overwrite the str ref
del os.environ["BW_SESSION"]
```
This is best-effort (the original `str` may still be on the heap until GC), but combined with ephemeral session lifetimes (~ms), the exposure window is negligible.

### 3.5. Layer 5 — Error Sanitization (The Muzzle)
**Problem:** When Pydantic catches a malformed payload, `str(e)` includes the **rejected value** in the error message:
```
ValidationError: 1 error for CreateItemAction
  password: Extra inputs are not permitted [input_value='stolen_secret_123']
```
If this string reaches the LLM, it has successfully extracted a secret via a side-channel attack.

**Solution:** `_safe_error_message(e)` in `subprocess_wrapper.py`:
- If `e` is a `SecureBWError` (pre-sanitized by us), pass it through.
- For EVERYTHING else (including `ValidationError`, `KeyError`, `json.JSONDecodeError`), return only `"TypeName: An internal error occurred. Check server logs for details."` — zero information leakage.

### 3.6. Layer 6 — Disk I/O Scrubbing (The Cleaner)
**Problem:** Logs and the WAL are written to disk. If the filesystem is compromised, an attacker could read secrets from:
1. Audit log JSON files (rollback commands contain original item states).
2. The WAL file (contains the exact commands to roll back, including full item JSON).
3. CLI terminal output (the human runs `bw-proxy wal` to inspect stranded transactions).

**Solution:** Three sub-layers:
- **6a. `deep_scrub_payload`**: Recursively walks any data structure and replaces values of sensitive keys (`password`, `totp`, `notes`, `ssn`, `number`, `code`, `passportNumber`, `licenseNumber`, `key`, `value`) with `[PAYLOAD]`.
- **6b. `_sanitize_args_for_log`**: Whitelist-based redaction for CLI args. Only known verbs (`bw`, `get`, `edit`, `delete`), known object types (`item`, `folder`), UUIDs, and known flags pass through. Everything else (base64 blobs, JSON payloads) is replaced with `[PAYLOAD]`.
- **6c. Encrypted WAL**: The WAL itself is AES-encrypted using Fernet with a key derived from the Master Password via PBKDF2 (480k iterations + 16-byte random salt per write). Even if the `.wal` file is stolen, it's cryptographically useless without the Master Password.

---

## 4. ⚙️ ACID Transaction Engine: Making a Non-Transactional CLI Transactional

### 4.1. The Problem
Bitwarden's CLI has no concept of transactions. Each `bw edit`, `bw delete`, `bw create` is an independent HTTP call to the Bitwarden server. If you execute 5 operations and the 3rd fails, the first 2 are already committed — your vault is in an inconsistent state.

### 4.2. Our Solution: The 3-Phase Commit
```
Phase 1: VALIDATION (RAM)
   → Pydantic validates the entire batch.
   → The proxy calculates the inverse (rollback) of each operation.

Phase 2: WAL WRITE (Disk)
   → The rollback commands are encrypted and written to disk.
   → This guarantees durability: even if the process is killed, recovery is possible.

Phase 3: EXECUTION (Network)
   → Operations execute one-by-one against the Bitwarden CLI.
   → If any operation fails, the rollback engine plays all previous inverses in LIFO order.
   → On success, the WAL is cleared.
```

### 4.3. The Idempotent Rollback Insight
**The bug we caught:** If the process crashes *during rollback* (e.g., after rolling back op #3 but before rolling back op #2), the WAL still contains all 3 rollback commands. On recovery, op #3 would be rolled back *again*, potentially causing a double-delete or double-restore.

**The fix:** `pop_rollback_command(tx_id)` — after each successful rollback command, that specific command is immediately removed from the WAL file on disk. If the process crashes mid-rollback, only the remaining un-executed commands survive for the next recovery attempt. This makes rollback **idempotent** — safe to retry any number of times.

### 4.4. The Isolation Rule for Unrecoverable Actions
Some operations have **no inverse**:
- `delete_attachment` — files are physically purged from Bitwarden's storage.
- `delete_folder` — folders are hard-deleted (no trash). Items lose their `folderId`.

If these were bundled in a batch where a later operation fails, we'd need to roll them back — but we can't. The solution is **architectural**: Pydantic's `isolate_disruptive_actions` validator rejects any batch containing these actions alongside other operations. They must always be alone, making rollback a non-issue (either the single op succeeds or it fails, with nothing else to undo).

---

## 5. 📂 Project Structure & Navigation

```
bw-blind-proxy/
├── src/bw_blind_proxy/
│   ├── __init__.py          # FastMCP server bootstrap
│   ├── server.py            # 5 MCP tools (get_vault_map, sync_vault, propose_vault_transaction,
│   │                        #   get_capabilities_overview, get_proxy_audit_context, inspect_transaction_log)
│   ├── models.py            # 16 StrEnum actions + Blind* read models + write schemas
│   ├── transaction.py       # ACID engine: execute_batch, _execute_single_action, _perform_rollback
│   ├── subprocess_wrapper.py # Secure bw CLI wrapper with bytearray lifecycle
│   ├── ui.py                # Zenity HITL popups (review_transaction, ask_master_password)
│   ├── wal.py               # Encrypted WAL (Fernet + PBKDF2) with idempotent pop
│   ├── logger.py            # Scrubbed JSON transaction logs
│   ├── scrubber.py          # deep_scrub_payload (recursive secret removal)
│   ├── cli.py               # Typer CLI (logs, log, wal, purge)
│   ├── config.py            # Internalized config loader
│   └── config.yaml          # All tunable parameters (salt_length, iterations, batch_size…)
├── tests/                   # 58 tests covering all layers
├── docs/                    # 01-08 simulation series + AUDIT.md + LIMITATIONS.md
├── CHANGELOG.md             # Full project evolution history
├── AGENT.md                 # Agent mandate (GEMINI.md equivalent)
└── MEMORY.md                # This file
```

---

## 6. 📋 Key Design Decisions (For Future Reference)

| Decision                                                 | Why                                                                                                                 | Alternative Considered                                                                                                                  |
| :------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------ | :-------------------------------------------------------------------------------------------------------------------------------------- |
| `bytearray` over `str` for secrets                       | Mutable = wipe-in-place. `str` is immutable = GC-dependent lifetime = memory forensics risk.                        | `ctypes` direct memory access — too fragile, non-portable.                                                                              |
| Fernet over raw AES                                      | Fernet bundles AES-128-CBC + HMAC-SHA256 + timestamp. One call, zero mistakes.                                      | `cryptography.hazmat` AES-GCM — more performant but error-prone (nonce management, no built-in MAC).                                    |
| PBKDF2 (480k iterations) over Argon2                     | Pure Python, no system dependency (`libargon2`). 480k iterations gives ~15,000 years brute-force on RTX 4090.       | Argon2id — memory-hard, better against ASICs, but requires external C library.                                                          |
| Pydantic `extra="forbid"` over manual validation         | Declarative, exhaustive, testable. One line protects against all unknown field injection forever.                   | Manual `if "password" in payload: reject()` — fragile, easy to forget a field.                                                          |
| Standalone batch for `delete_folder`/`delete_attachment` | Eliminates the need for impossible rollback logic.                                                                  | Pre-deletion snapshots + folder recreation — too complex, race-condition-prone, and still imperfect (new folder gets a different UUID). |
| JSON structured logs over flat text                      | Machine-parseable, enable the AI introspection tools (`inspect_transaction_log`), and support `deep_scrub_payload`. | Human-only text logs — cannot be safely scrubbed or programmatically consumed.                                                          |

---

## 7. 🏗️ The 16 StrEnum Actions (API Surface)

### Item Actions (9)
1. `create_item` — Shell creation (no secrets).
2. `rename_item` — Name change via read-modify-write.
3. `move_item` — Reparent to folder via `folderId` edit.
4. `favorite_item` — Toggle star via boolean edit.
5. `delete_item` — Soft-delete to Trash. Rollback = `bw restore item`.
6. `restore_item` — Pull from Trash. Rollback = `bw delete item`.
7. `toggle_reprompt` — Master Password re-prompt flag via JSON edit.
8. `move_to_collection` — Transfer to Enterprise Org. Rollback = restore original JSON *(edge case: may fail if Enterprise Policy forbids)*.
9. `delete_attachment` — **ISOLATED.** Hard-delete. No rollback possible.

### Folder Actions (3)
10. `create_folder` — Template + base64 create. Rollback = `bw delete folder`.
11. `rename_folder` — Read-modify-write on folder JSON. Rollback = restore original name.
12. `delete_folder` — **ISOLATED.** Hard-delete. No trash. Items lose `folderId`.

### Edit Actions (4)
13. `edit_item_login` — Username + URIs only. Password/TOTP forbidden.
14. `edit_item_card` — CardholderName, Brand, ExpMonth, ExpYear. Number/Code forbidden.
15. `edit_item_identity` — Name, Address, Phone, Email. SSN/Passport/License forbidden.
16. `upsert_custom_field` — Text (0) + Boolean (2) only. Hidden (1) / Linked (3) forbidden.

---

## 8. 🤝 Handoff Notes for Future Agents

- **Do NOT modify `models.py` without updating tests.** The entire security sandbox relies on `extra="forbid"` and the `BlindItem` redaction loops. Breaking either silently opens a data exfiltration vector.
- **The `deep_scrub_payload` key set** in `scrubber.py` must be expanded if Bitwarden adds new secret fields. Always check against the latest Bitwarden API schema.
- **Bitwarden `Send` objects** were deliberately excluded. They are ephemeral text shares, not vault organizational data. Add as a separate module if requested.
- **Test command:** `uv run pytest -v` (58 tests expected to pass as of v1.2.0).
- **The WAL encryption uses the Master Password as the key source.** If the user changes their Master Password between a WAL write and a recovery attempt, the WAL becomes unreadable. This is an accepted trade-off.

---

## 9. 📝 Pending Actions / Reminders

- **[ARTICLE REMINDER]**: Write a conceptual article (Medium / LinkedIn / blog) detailing the "Zero Trust for Agentic AI" philosophy behind this project. Key topics: Blindness by Design, ACID over non-transactional CLI, `bytearray` memory lifecycle, defense-in-depth layers.
- **[DEPLOYMENT]**: Push to all Git remotes after final commit.
- **[MCP REGISTRATION]**: Register the server with target AI agents (Claude Code, Gemini CLI, Cursor) via their respective MCP config files.
