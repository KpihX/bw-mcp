# Simulation 08: The "Blackout" Stress Test (ACID & WAL Resilience)

[ ⬅️ 07: Advanced Search Filtering ](07_simulation_advanced_search.md) | [ Back to README ➡️ ](../README.md)

**Context:** The AI Assistant `antigravity` is performing a batch migration: moving several items to a new folder and deleting obsolete ones — reaching the maximum operations configured in `MAX_BATCH_SIZE`.

## 🕒 T+0: The Request
Assistant sends a `propose_vault_transaction` with a full batch of operations.
- **Rationale:** `"Migrating legacy project credentials to the archived folder and purging expired entries."`

## 🛡️ T+2s: WAL Initialization
- **Consistency (C):** Pydantic validates the ops against strict Enums. `extra="forbid"` ensures no secret field was sneaked in.
- **Durability (D):** The proxy writes an empty WAL immediately: `write_wal(tx_id, [], master_password)`. The WAL is **AES-encrypted at rest** using a Fernet key derived from the Master Password via PBKDF2 (480k iterations) with a fresh 16-byte random salt.
- After each successful op, a rollback command is appended and the WAL is **re-encrypted** with a new salt: `write_wal(tx_id, [rb_1], master_password)`.
- **This is the point of no return for safety.**

## ⚠️ T+5s: The Incident (Power Failure / `kill -9`)
1. The human approves via Zenity and enters the Master Password.
2. The proxy begins execution:
    - `bw move item-1 to archived-folder` → OK, WAL = `[rb_1]`
    - `bw move item-2 to archived-folder` → OK, WAL = `[rb_1, rb_2]`
    - ...
    - `bw delete item-9` → OK, WAL = `[rb_1, ..., rb_9]`
3. **CRASH:** At the final operation, the user's computer loses power.

**Vault State:** 9 ops are live on the Bitwarden server. The WAL has 9 rollback commands.

## 🔄 T+1 hour: The Idempotent Auto-Recovery
The user restarts their machine. They ask: "Hey, show me my vault."

1. **The Sentinel:** Assistant calls `get_vault_map`.
2. **The Discovery:** `check_recovery()` detects the orphaned encrypted `pending_transaction.wal` file.
3. **The Decryption:** The proxy re-prompts for the Master Password, derives the Fernet key via PBKDF2, and decrypts the WAL to recover the 9 rollback commands.
4. **The Shared Engine:** `_perform_rollback(tx_id, [rb_1...rb_9], master_password, session_key)` is called.

```text
LIFO Rollback with Idempotent WAL Consumption:

WAL before: [rb_1, rb_2, ..., rb_9]  (rb_9 = LIFO head)

rb_9 executed ✅ → pop_rollback_command(tx_id, master_pw) → re-encrypt WAL: [rb_1, ..., rb_8]
rb_8 executed ✅ → pop_rollback_command(tx_id, master_pw) → re-encrypt WAL: [rb_1, ..., rb_7]
...
⚡ CRASH again? No problem.
At next boot, encrypted WAL only contains REMAINING commands.
Already-reversed ops are NEVER double-applied.
...
rb_1 executed ✅ → pop_rollback_command(tx_id, master_pw) → re-encrypt WAL: []
clear_wal() → encrypted .wal file deleted.
```

4. **Recovery Message to the LLM:**
`"WARNING: A previous critical crash was detected (TX: <uuid>). The proxy executed a full WAL rollback (9 command(s)) and restored vault integrity. You may now proceed safely."`

5. **The Log Created (JSON, scrubbed by `deep_scrub_payload`):**
```json
{
  "transaction_id": "the-crashed-tx-uuid",
  "status": "CRASH_RECOVERED_ON_BOOT",
  "rationale": "Hard-crash detected upon startup. System auto-recovered via WAL.",
  "operations_requested": [],
  "rollback_trace": [
    "restore item legacy-id-9",
    "restore item legacy-id-8",
    "...",
    "edit item item-1 [PAYLOAD]"
  ]
}
```

## 💭 What if Recovery Itself Fails?

If `_perform_rollback` encounters an error (e.g. `"Item not found"` because it was also deleted externally):
- The WAL is **NOT cleared**. The proxy preserves the evidence.
- The LLM receives a **structured diagnostic message**:
  ```
  CRITICAL: A previous crash (TX: <uuid>) was detected and the WAL rollback FAILED.
  Recovery Error: bw: item not found
  Successfully reversed commands: [rb_9, rb_8, ...]
  Command that failed to revert: bw edit item legacy-id-X {...}
  Diagnosis: If the error mentions 'Item not found', manual intervention is required.
  IMPORTANT: Do NOT attempt new vault operations until this is resolved.
  ```
- The LLM can distinguish: **transient error** (retry) vs **permanent error** (escalate to user).

## 💨 The Batch Cap (Why It Matters Here)

**Use short batches.** The proxy enforces a maximum of `MAX_BATCH_SIZE` operations (default: 25) per transaction call. The fewer operations, the shorter the execution window, dramatically reducing the risk window and making the WAL smaller and the rollback less complex.

## 📎 The ACID Result
- **Atomicity (A):** Despite the crash, the final state is "Nothing was changed". The saga rollback guarantees it.
- **Consistency (C):** All Pydantic validations passed before a single byte reached the network.
- **Isolation (I):** `check_recovery()` blocks all new operations until the vault is confirmed clean.
- **Durability (D):** The encrypted WAL survived the power cut. It was consumed incrementally using `pop_rollback_command` (which re-encrypts the WAL after each pop), making the recovery crash-proof itself.
- **Confidentiality:** The WAL file is AES-encrypted (Fernet + PBKDF2) and `chmod 600`. Even if exfiltrated, it's useless without the Master Password.
- **Transparency:** A `CRASH_RECOVERED_ON_BOOT` JSON log is written as forensic proof (scrubbed by `deep_scrub_payload`). Inspect with `bw-proxy log --last 1`.

**Outcome:** Your data survived a hardware failure — and would survive a sequence of hardware failures — thanks to the encrypted, idempotent WAL Engine.
