# 🛡️ Appliance Hardening & Security Machinery

The **BW-Proxy** is designed as a sovereign security appliance. This document details the architectural layers that protect your secrets.

---

## 1. The Multi-Layer Defense

```ascii
      HUMAN OPERATOR (Sovereign)
           │
           ▼
    ┌───────────────────────┐
    │  HOST OS (Ubuntu)     │ ◄── Root-owned shim
    └──────────┬────────────┘
               │
               ▼ (Ephemeral Docker)
    ┌───────────────────────┐
    │  BW-PROXY CONTAINER   │ ◄── Read-only code
    └──────────┬────────────┘
               │
               ▼ (Encrypted WAL)
    ┌───────────────────────┐
    │  BITWARDEN VAULT      │
    └───────────────────────┘
```

### Layer 1: Root-Owned Shim
By installing the `bw-proxy` binary in `/usr/local/bin` via `sudo`, we ensure that non-privileged malware running as your user cannot modify the proxy's logic. Even if your user account is compromised, the "Gatekeeper" remains intact.

### Layer 2: Ephemeral Docker Runtime
Each command runs in a fresh, isolated container.
- **No Persistence**: Any changes to the container's root filesystem are wiped on exit.
- **Network Isolation**: The proxy only talks to `localhost` (for HITL) and the Bitwarden API.

---

## 2. The Unlock Lease Machinery

To avoid typing your Master Password for every command, we use an **Encrypted Lease**.

1.  **Unlock**: You provide the Master Password once.
2.  **Session Generation**: The Bitwarden CLI generates a `session_key`.
3.  **Encryption**: The proxy generates a one-time `lease.key` (Fernet) and encrypts the `session_key` into `session_lease.json`.
4.  **Storage**: Both files are stored in a root-protected Docker volume (`chmod 0700`).

**Security Guarantee:** The `session_key` is never stored in plaintext on disk. It is wrapped in AES-128-CBC and protected by OS-level permissions.

---

## 3. ACID Integrity (WAL)

Every mutation (Edit, Move, Create) follows a **3-Phase Commit**:

1.  **Preparation**: The AI proposes a batch of actions.
2.  **Simulation**: The proxy simulates the changes in RAM. If a Pydantic validation fails, the process stops *before* touching the vault.
3.  **The WAL (Write-Ahead Log)**: The actions are encrypted and written to `STATE_DIR/wal/`.
4.  **Commit**: The Bitwarden CLI executes the actions.
5.  **Recovery**: If the proxy crashes mid-commit, it detects the WAL on the next start and performs a **LIFO Rollback** to restore the vault's consistency.

---

## 4. Human-In-The-Loop (HITL)

No action is performed without your explicit approval.

- **Glassmorphism UI**: A premium web interface opens automatically on your host browser.
- **Rationale Disclosure**: The AI must provide a "Why" for every action, which you review alongside the technical diff.
- **Destructive Alerts**: Operations like `DELETE` or `MOVE` trigger high-visibility warnings.

---

## 5. Metadata Redaction

AI Agents are "Blind" by design.
- **Populated**: `[REDACTED_BY_PROXY_POPULATED]` means a value exists but is hidden.
- **Empty**: `[REDACTED_BY_PROXY_EMPTY]` means no value is set.
- **Audit**: The AI can compare two redacted values (Match/Mismatch) via a secure internal subprocess without ever seeing the raw data.
