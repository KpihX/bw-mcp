#!/bin/bash
set -e

# --- Configuration ---
APP_NAME="bw-proxy"
IMAGE_NAME="ghcr.io/kpihx/bw-proxy:latest"
BIN_DEST="/usr/local/bin/$APP_NAME"
CONFIG_DIR="/etc/$APP_NAME"
VOLUME_NAME="bw_mcp_bw-data"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🛡️  BW-Proxy Sovereign Appliance Installer v3.6.2${NC}"

# Check for root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Error: Please run as root (sudo).${NC}"
  exit 1
fi

# 1. Pull Image (The Brain)
echo -e "${BLUE}📦 Pulling latest appliance image from GHCR...${NC}"
docker pull "$IMAGE_NAME" || { echo -e "${RED}Error: Failed to pull image. Check connection/auth.${NC}"; exit 1; }

# 2. Infrastructure (The Vault & Config)
echo -e "${BLUE}💾 Ensuring persistent data volume exists...${NC}"
docker volume create "$VOLUME_NAME" > /dev/null

echo -e "${BLUE}⚙️  Ensuring config directory at $CONFIG_DIR exists...${NC}"
mkdir -p "$CONFIG_DIR"
chmod 755 "$CONFIG_DIR"

# 3. Forging the Sword (System-wide Shim)
echo -e "${BLUE}🚀 Installing hardened system binaire to $BIN_DEST...${NC}"

# Note: We use a single-file python script to keep it zero-dependency and fast.
cat <<'EOF' > "$BIN_DEST"
#!/usr/bin/env python3
import os
import re
import sys
import socket
import subprocess
import webbrowser

# --- Appliance Constants ---
IMAGE = "ghcr.io/kpihx/bw-proxy:latest"
VOLUME = "bw_mcp_bw-data"
DATA_DIR = "/data"
WORKSPACE_DIR = "/workspace"
URL_PATTERN = re.compile(r"(https?://[^\s]+token=[a-f0-9-]+)")

def _pick_port():
    """Pick a random free port for HITL."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

def _open_browser(url):
    """Agnostic browser opener."""
    # Ensure loopback binding
    url = url.replace("0.0.0.0", "127.0.0.1")
    try:
        webbrowser.open(url)
    except:
        pass

def main():
    args = sys.argv[1:] or ["mcp", "serve"]
    port = _pick_port()
    uid = os.getuid()
    gid = os.getgid()
    
    # Execution directory for workspace mounting
    cwd = os.getcwd()
    
    # Stable container name for this workspace
    import hashlib
    cwd_hash = hashlib.sha256(cwd.encode()).hexdigest()[:8]
    runtime_name = f"bw-proxy-appliance-{uid}-{cwd_hash}"

    # --- Docker Command Assembly ---
    docker_cmd = [
        "docker", "run", "--rm", "-i", "--init",
        "--name", f"{runtime_name}-exec-{os.getpid()}",
        "--user", f"{uid}:{gid}",
        "-v", f"{VOLUME}:{DATA_DIR}",
        "-v", f"{cwd}:{WORKSPACE_DIR}",
        "-v", "/tmp:/tmp", # For temp artifacts
        "-w", WORKSPACE_DIR,
        "-p", f"127.0.0.1:{port}:{port}",
        "-e", f"HITL_PORT={port}",
        "-e", "HITL_HOST=0.0.0.0",
        "-e", "BW_PROXY_DATA=/data",
        "-e", "BITWARDENCLI_APPDATA_DIR=/data/bw-cli",
        "-e", "HOME=/data",
        IMAGE
    ]
    docker_cmd.extend(args)

    # --- Execution Loop with URL Interception ---
    # We use stderr for our messages to avoid polluting MCP stdio flux
    process = subprocess.Popen(
        docker_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=sys.stdin,
        text=True,
        bufsize=1
    )

    try:
        while True:
            line = process.stdout.readline()
            if not line: break
            
            # Intercept HITL URLs
            match = URL_PATTERN.search(line)
            if match:
                url = match.group(1)
                sys.stderr.write(f"\r\n🚀 [Appliance] Detected Approval URL: {url}\r\n")
                _open_browser(url)
            
            # Forward everything to stdout (MCP Protocol)
            sys.stdout.write(line)
            sys.stdout.flush()
    except KeyboardInterrupt:
        process.terminate()
        sys.exit(130)

    return process.wait()

if __name__ == "__main__":
    sys.exit(main())
EOF

chmod 755 "$BIN_DEST"

echo -e "${GREEN}✅ BW-Proxy Appliance v3.6.2 successfully installed in $BIN_DEST${NC}"
echo -e "Try it now: ${BLUE}bw-proxy admin status${NC}"
