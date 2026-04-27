# 🔐 BW-Proxy — Sovereign Bitwarden Appliance

> **Zero Trust · AI-Blind · ACID Durable**  
> A high-security proxy for Bitwarden organization vaults, designed to keep LLMs and AI agents blind to your real secrets while giving them full refactoring and auditing capabilities.

---

## 🏛️ Philosophy: The Sovereign Hub

BW-Proxy is not just a tool; it's a **Sovereign Appliance**. It creates a secure, air-gapped environment (via Docker) where your Bitwarden vault can be manipulated by AI without the AI ever seeing a plain-text password or a master key.

- **0 Trust**: Secrets never leave the proxy's memory-wiped runtime.
- **100% Control**: Every transaction requires explicit Human-In-The-Loop (HITL) approval via a premium web interface.
- **ACID Integrity**: Uses a Write-Ahead Log (WAL) to ensure your vault never ends up in a corrupted state during complex refactors.

---

## 🚀 Installation

### 1. Appliance Mode (Recommended)
Install the pre-built, security-hardened image directly from the GitHub Container Registry (GHCR).

```bash
curl -fsSL https://raw.githubusercontent.com/KpihX/bw-proxy/main/install.sh | sudo bash
```

### 2. Developer Mode (Source)
Clone the repository and build it locally using `uv`.

```bash
git clone https://github.com/KpihX/bw-proxy.git
cd bw-proxy
make docker-install
```

---

## 🛠️ Usage

Once installed, use the `bw-proxy` command anywhere.

### Administrative Control
```bash
bw-proxy admin login    # Authenticate (one-time setup)
bw-proxy admin unlock   # Create a secure session lease
bw-proxy admin status   # Check the health of the appliance
```

### Vault Operations (`do`)
The AI agent uses these tools to manage your vault blindly.
```bash
bw-proxy do get-vault-map         # Scan the vault (redacted output)
bw-proxy do find-duplicates       # Audit for secret collisions
bw-proxy do refactor-secrets      # Move secrets blindly between items
bw-proxy do propose               # Batch several operations with rationale
```

---

## 🛡️ Security Machinery

- **Docker-Only Lease**: The master password is used to generate a temporary, encrypted session key stored only within the persistent Docker volume.
- **Persistent Machine ID**: Stabilizes Bitwarden's device identity to prevent repeated "New Device" emails and decryption failures.
- **Root-Owned Proxy**: The `install.sh` script places the binary in `/usr/local/bin` (root-owned), preventing non-privileged malware from tampering with the proxy logic.
- **Memory Wiping**: All cryptographic keys are held in `bytearray` buffers and explicitly zeroed out after each use.

---

## 🏗️ Architecture

```ascii
      AI AGENT
         │
         ▼
    ┌──────────┐      HITL APPROVAL
    │ BW-PROXY │ ◄─── (Browser UI)
    └────┬─────┘
         │
         ▼ (Encrypted WAL)
    ┌──────────┐
    │  BIT-    │
    │  WARDEN  │
    └──────────┘
```

---

## ⚖️ License
Standard KπX Sovereign License. Part of the **K-Homelab** ecosystem.

Designed with ❤️ by **KAMDEM Ivann (KpihX)**.
