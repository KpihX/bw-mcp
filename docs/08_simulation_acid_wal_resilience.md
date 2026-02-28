# Simulation 08: The "Blackout" Stress Test (ACID & WAL Resilience)

[ ⬅️ 07: Advanced Search Filtering ](07_simulation_advanced_search.md) | [ Back to README ➡️ ](../README.md)

**Context:** The AI Assistant `antigravity` is performing a massive migration: moving 20 items to a new folder and deleting 5 obsolete ones. The payload is large and complex.

## 🕒 T+0: The Request
Assistant sends a `propose_vault_transaction` with 25 operations.
- **Rationale:** "Migrating legacy project credentials to the archived folder and purging expired entries."

## 🛡️ T+2s: Virtual Vault & WAL Initialization
- **Consistency (C):** The proxy pulls templates and current item states into RAM. It simulates all 25 changes. Validation passes.
- **Durability (D):** The Proxy Generates 25 **Rollback Commands**. 
- It writes them to `logs/wal/pending_transaction.json`. **This is the point of no return for safety.**

## ⚠️ T+5s: The Incident (Power Failure / `kill -9`)
1. The human approves via Zenity and enters the Master Password.
2. The proxy begins execution:
    - `bw edit item 1` -> OK
    - `bw edit item 2` -> OK
    - ...
    - `bw delete item 21` -> OK
3. **CRASH:** At operation 22, the user's computer loses power or the process is forcefully killed.

**Vault State:** The vault is now **CORRUPTED**. 21 items are modified/moved, but 4 are untouched. The system is in an "In-Between" state.

## 🔄 T+1 hour: The Automatic Resurrection
The user restarts their machine. They ask the Assistant: "Hey, show me my vault."

1. **The Sentinelle:** Assistant calls `get_vault_map`.
2. **The Discovery:** The proxy prompts for the Master Password (Auth).
3. **The Recovery (A & D):**
    - The `check_recovery()` logic detects the orphaned `pending_transaction.json`.
    - **Isolation (I):** It freezes all new requests.
    - **Rollback:** It reads the 21 compensating actions (LIFO). 
    - It executes `bw edit` (revert) and `bw restore` for every item that was partially modified.
4. **Conclusion:** The proxy returns a message to the AI: 
   `"WARNING: A previous critical crash was detected. The proxy automatically executed a full WAL rollback to restore Vault integrity."`

## 💎 The ACID Result
- **Atomicity:** Even though the crash happened midway, the result is "Nothing was changed". No partial mess left behind.
- **Transparency:** A log `logs/transactions/tx_id_CRASH_RECOVERED_ON_BOOT.log` is created for audit.
- **Stable State:** The Bitwarden vault remains exactly as it was before the migration started.

**Outcome:** Your data survived a hardware failure thanks to the WAL Engine.
