# 📦 Installation Guide (Agnostic Appliance)

This guide explains how to install the **BW-Proxy** as a system-wide appliance on any Linux distribution with Docker installed.

---

## 1. Quick Install (curl | bash)

The recommended way to install the production-ready appliance is via the standalone installer. This method requires **sudo** privileges.

```bash
curl -fsSL https://raw.githubusercontent.com/KpihX/bw-proxy/main/install.sh | sudo bash
```

### What happens?
- **Docker Pull**: Downloads the latest hardened image from `ghcr.io/kpihx/bw-proxy`.
- **System Binary**: Creates a root-owned Python shim at `/usr/local/bin/bw-proxy`.
- **Persistent Storage**: Creates a Docker volume named `bw_mcp_bw-data`.
- **Global Config**: Prepares `/etc/bw-proxy/` for system-wide configuration.

---

## 2. Manual Source Install (Cloning)

If you prefer building from source or contributing:

```bash
git clone https://github.com/KpihX/bw-proxy.git
cd bw-proxy
make docker-install
```

This will build the image locally and link the source-mode shim to `~/.local/bin/bw-proxy`.

---

## 3. Post-Installation

Once installed, verify the status:

```bash
bw-proxy admin status
```

Then, initialize your vault connection:

```bash
bw-proxy admin login
```

---

## 4. Uninstallation

To completely remove the appliance and all its data:

```bash
sudo ./uninstall.sh
```
*(Or manually remove `/usr/local/bin/bw-proxy`, `/etc/bw-proxy`, and the Docker volume).*
