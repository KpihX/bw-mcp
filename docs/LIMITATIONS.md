# ⚠️ BW-MCP — Known Limitations & Mitigation Guide

> *"We do not ask you to trust us. We ask you to read this."*  
> — The BW-MCP Project

This document presents the architectural limitations that **cannot be solved in code alone**. For each limitation, we provide the exact failure scenario, the underlying root cause, and actionable mitigation advice.

The other limitations of our system (batch size, unrecoverable attachments) **are enforced and documented directly in the code**. Those are not listed here because we fix what we can fix. This document is reserved for limits imposed by **external, immutable constraints** (Bitwarden's API design).

---

## 1. The Non-Atomic Bitwarden API (ACID Incompleteness)

### Root Cause
SQL Databases (PostgreSQL, MySQL, SQLite) offer transactional atomicity. The entire sequence of `INSERT`, `UPDATE`, `DELETE` runs in an invisible "staging area". Only a final `COMMIT` makes it permanent. If anything fails, `ROLLBACK` is a no-op (nothing ever touched the real disk).

Bitwarden has **no equivalent**. Every `bw edit`, `bw create`, `bw delete` is an **immediate, irreversible HTTP request** to the Bitwarden server. There is no "staging mode".

```text
| SQL (Ideal World)                   | Bitwarden API (Reality)   |
| ----------------------------------- | ------------------------- |
| BEGIN;                              |
| UPDATE vault SET ...;               | bw edit item ... → LIVE ✅ |
| UPDATE vault SET ...;               | bw edit item ... → LIVE ✅ |
| UPDATE vault SET ...;               | bw edit item ... → LIVE ✅ |
| -- error! --                        | -- error! --              |
| ROLLBACK; ← no-op, safe             | Rollback must RE-EXECUTE  |
| compensating bw commands ← can fail |
```

### Why This Matters
BW-MCP compensates with a **WAL + LIFO Rollback** engine (Saga Pattern). This is industry-grade resilience engineering, but it is fundamentally a manual undo mechanism. If a compensating command (`bw edit Item X {original_json}`) itself fails, the vault is left in an inconsistent state.

This can only happen in combination with a concurrent external event (see Section 2 below).

### Mitigation
- **Use short batches.** The proxy enforces a maximum of `MAX_BATCH_SIZE` operations (default: 25) per transaction call. The fewer operations, the shorter the execution window.
- **Monitor your logs.** Every transaction produces a `.json` file in `~/.bw_mcp/logs/` with its `STATUS`. An unexpected `ROLLBACK_FAILED` status is the signal to inspect your vault.
- **After a `FATAL` error:** Consult the `.log` file for the exact `[FAILED TO REVERT]` command and execute it manually (`bw edit item <id> '<json>'`).

---

## 2. Write Exclusivity (The Race Condition Window)

### Root Cause
Bitwarden is a **multi-client synchronization system** by design. Your vault is synced in real-time across your phone, browser extension, and desktop app. This is its greatest strength as a password manager — and our greatest vulnerability as a proxy.

A **Race Condition** occurs when two concurrent actors (the proxy + an external client) modify the same vault item, leading to conflicts.

### Illustrated Scenario: The Deadly Race

```text
| Timeline (ms)                     | BW-MCP                               | Your Mobile App       |
| --------------------------------- | ------------------------------------ | --------------------- |
| 0ms                               | TX starts (3 ops):                   |
| 1ms                               | [OP 1] rename "Github" → "GitHub"    | ← executes OK ✅       |
| WAL records rollback cmd          |
| 2ms                               |                                      | You manually DELETE   |
|                                   | the "GitHub" item (typo)             |
| 3ms                               | [OP 2] move "Netflix" to folder...   | ← CRASHES (network) ❌ |
| 4ms                               | ROLLBACK TRIGGERED                   |
| 5ms                               | Try: bw edit item [github-uuid]...   |
| ← "Not found" (item was deleted!) | FATAL ERROR 💀                        |
| --------------                    | ------------------------------------ | -------------------   |
Result: "Netflix" was NOT moved. "GitHub" was deleted externally.
         The vault is in a state that neither party intended.
```

### Mitigation
1. **Treat MCP transactions like database migrations**: During an active session, consider your vault temporarily "exclusive write locked" from a policy standpoint. Avoid touching the vault from another client.
2. **Use small, focused batches.** The exposure window is directly proportional to the number of operations. Fewer operations equal less time and less risk.
3. **Prefer atomic, single-item operations for frequently-edited items.** Items you edit often (e.g., work credentials rotated by scripts) should be moved individually.
4. **Sync before and after.** Running `bw sync` before a large transaction ensures the proxy starts with the most current vault state.

---

## 3. Session Timeout During Long Transactions

### Root Cause
Bitwarden CLI sessions (`BW_SESSION`) can become invalid during a long-running transaction due to:
- Session timeout on the server side.
- A network interruption invalidating the session token.
- A system-level event (VPN reconnect, network interface change).

### Illustrated Scenario
```text
[OP 1] Rename "Server" → "Mainframe" ✅
[OP 2] Move 8 items to a new folder... (takes ~2 seconds)
       └── Mid-loop: VPN reconnects, session token invalidated
[OP 7] bw edit item ... → "Not logged in." ❌
ROLLBACK TRIGGERED
bw edit item [previous-uuid] ... → "Not logged in." ❌
FATAL ERROR: Both execution and rollback sessions are dead.
```

### Mitigation
1. **Keep batches small and fast.** Smaller batches complete in milliseconds, whereas very large batches create a multi-second window where a session can expire.
2. **Avoid long transactions on unstable networks (mobile hotspot, public Wi-Fi).** The proxy relies on the session remaining valid for the full duration of the batch.
3. **The WAL is your idempotent safety net.** After a session timeout crash, the encrypted WAL is preserved at `~/.bw_mcp/wal/pending_transaction.wal`. On the next tool call, `check_recovery()` re-prompts for the Master Password, decrypts the WAL via PBKDF2/Fernet, and re-attempts the rollback using your fresh session.

   **Crucially:** If the system also crashes *while rolling back* (e.g., two back-to-back Ctrl+C), the WAL is not corrupted. After each successful rollback command, `pop_rollback_command()` removes it from the WAL file on disk. The next recovery attempt picks up **exactly where it left off** — no command is ever applied twice.

   ```text
   ROLLBACK INTERRUPTED mid-way (Ctrl+C after 2/4 commands):

   WAL before rollback:  [rb_4, rb_3, rb_2, rb_1]  (LIFO order)
   rb_4 executed ✅  → pop → WAL: [rb_3, rb_2, rb_1]
   rb_3 executed ✅  → pop → WAL: [rb_2, rb_1]
   ⚡ CRASH

   WAL on next boot:     [rb_2, rb_1]
   rb_2 executed ✅  → pop → WAL: [rb_1]
   rb_1 executed ✅  → pop → WAL: [] → clear_wal() → done.
   ```
