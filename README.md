# 🔐 BW-Proxy — Sovereign Bitwarden Appliance

> **Zero Trust · AI-Blind · ACID Durable**  
> The authoritative appliance for Bitwarden organization vault control. Keep AI agents and LLMs blind to your real secrets while giving them full auditing and refactoring powers.

---

## 🏛️ Project Architecture (Sovereign Tree)

```ascii
BW-PROXY PROJECT
├── 📂 src/bw_proxy/     ◄── Core Engine (ACID Transaction, WAL, Redaction)
├── 📂 scripts/          ◄── Host-side Shims (Dynamic porting, Browser HITL)
├── 📂 docs/             ◄── Deep-dive Hardening & Operator Guides
├── 📄 install.sh        ◄── System-wide Appliance Installer (Root-owned)
├── 📄 Makefile          ◄── Developer & Release Automator
└── 📄 Dockerfile        ◄── Multi-stage Hardened Runtime
```

---

## 🚀 Installation Modes

### A. Appliance Mode (Standard Pro)
Ideal for production use. Installs a root-owned binary and uses the official image.

**Via curl (Zero-Clone):**
```bash
curl -fsSL https://raw.githubusercontent.com/KpihX/bw-proxy/main/install.sh | sudo bash
```

**What it does internally:**
1.  **Image**: Pulls `ghcr.io/kpihx/bw-proxy:latest`.
2.  **Binary**: Creates `/usr/local/bin/bw-proxy` (owned by root).
3.  **Config**: Creates `/etc/bw-proxy/`.
4.  **Data**: Creates a persistent Docker volume `bw_mcp_bw-data`.

---

### B. Developer Mode (Source Clone)
Ideal for contribution or source-level auditing.

```bash
git clone https://github.com/KpihX/bw-proxy.git
cd bw-proxy
make docker-install  # Requires SUDO for builds
```

---

## ⚙️ Core Mechanisms (The Magic)

### 1. The HITL Browser Flux
When an AI agent requests a vault change, the proxy intercepts the execution:
1.  **Port Allocation**: The host shim finds a free random port.
2.  **Container Launch**: The appliance starts, mapping the internal HITL server to that port.
3.  **URL Interception**: The shim detects the Approval URL in stdout and **automatically opens your browser**.
4.  **Human Approval**: You review the rationale and the diff, then approve with your Master Password.

### 2. The 3-Phase ACID Commit (WAL)
Every mutation is transactional.
- **Simulation**: Actions are validated in RAM first.
- **WAL**: Actions are encrypted and logged to disk *before* execution.
- **Commit**: Actions are sent to the Bitwarden CLI.
- **Rollback**: If a crash occurs, the proxy performs a LIFO rollback on the next start.

### 3. Scoped Union Fetch
To handle organizational vaults without metadata loss:
- The proxy discovers all accessible **Organizations** and **Collections** first.
- It then performs scoped queries (`--organizationid`) to fetch "rich" items with full metadata.
- It merges results with the global vault list, ensuring organizational assignments are preserved.

---

## 🕹️ Interface Modes

### 1. MCP Mode (For AI Agents)
Start the stdio server for Gemini, Claude, or Cursor.
```bash
bw-proxy mcp serve
```

### 2. CLI Mode (For Humans)
Manage your appliance directly.
```bash
bw-proxy admin status   # Health check
bw-proxy admin unlock   # Create a 5-minute session lease
bw-proxy do list-items  # Quick redacted scan
```

---

## 🛠️ Maintenance & Release

- **Update**: `curl ... | sudo bash` (re-runs the installer).
- **Uninstall**: `sudo ./uninstall.sh`.
- **Release (Dev)**: `make release` (automatic tagging and GHCR propulsion).

---

## ⚖️ License
MIT License. See `LICENSE` for details.

Designed with ❤️ by **KpihX**.
