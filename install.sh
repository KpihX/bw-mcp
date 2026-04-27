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

echo -e "${BLUE}🛡️  BW-Proxy Sovereign Appliance Installer${NC}"

# Check for root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Error: Please run as root (sudo).${NC}"
  exit 1
fi

# 1. Pull Image
echo -e "${BLUE}📦 Pulling latest appliance image from GHCR...${NC}"
docker pull "$IMAGE_NAME" || echo -e "${RED}Warning: Could not pull image. Ensure it exists or you have internet access.${NC}"

# 2. Create Volume
echo -e "${BLUE}💾 Ensuring persistent data volume exists...${NC}"
docker volume create "$VOLUME_NAME" > /dev/null

# 3. Create Config Directory
echo -e "${BLUE}⚙️  Creating system configuration directory at $CONFIG_DIR...${NC}"
mkdir -p "$CONFIG_DIR"
chmod 755 "$CONFIG_DIR"

# 4. Create Shim Binary (The Sovereign Sword)
echo -e "${BLUE}🚀 Installing hardened command-line wrapper to $BIN_DEST...${NC}"
cat <<'EOF' > "$BIN_DEST"
#!/usr/bin/env python3
import os
import re
import sys
import socket
import shutil
import subprocess
import webbrowser

# --- Appliance Constants ---
IMAGE = "ghcr.io/kpihx/bw-proxy:latest"
VOLUME = "bw_mcp_bw-data"
DATA_DIR = "/data"
WORKSPACE_DIR = "/workspace"
URL_PATTERN = re.compile(r"(https?://[^\s]+token=[a-f0-9-]+)")

def _pick_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

def _open_browser(url):
    url = url.replace("0.0.0.0", "127.0.0.1")
    try:
        webbrowser.open(url)
    except:
        pass

def main():
    args = sys.argv[1:] or ["mcp", "serve"]
    port = _pick_port()
    
    # Generate stable runtime name
    import hashlib
    cwd_hash = hashlib.sha256(os.getcwd().encode()).hexdigest()[:8]
    runtime_name = f"bw-proxy-runtime-{os.getuid()}-{cwd_hash}"

    # Build Docker Command
    cmd = [
        "docker", "run", "--rm", "-i", "--init",
        "--name", f"{runtime_name}-oneshot",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "-v", f"{VOLUME}:{DATA_DIR}",
        "-v", f"{os.getcwd()}:{WORKSPACE_DIR}",
        "-v", "/tmp:/tmp",
        "-w", WORKSPACE_DIR,
        "-p", f"127.0.0.1:{port}:{port}",
        "-e", f"HITL_PORT={port}",
        "-e", "HITL_HOST=0.0.0.0",
        "-e", "BW_PROXY_DATA=/data",
        "-e", "BITWARDENCLI_APPDATA_DIR=/data/bw-cli",
        "-e", "HOME=/data",
        IMAGE
    ]
    cmd.extend(args)

    # Execute and Intercept URLs for HITL
    process = subprocess.Popen(
        cmd,
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
            
            match = URL_PATTERN.search(line)
            if match:
                url = match.group(1)
                sys.stderr.write(f"\r\n🚀 [Appliance] Opening HITL Approval: {url}\r\n")
                _open_browser(url)
            
            sys.stdout.write(line)
            sys.stdout.flush()
    except KeyboardInterrupt:
        process.terminate()
        sys.exit(130)

    sys.exit(process.wait())

if __name__ == "__main__":
    main()
EOF

chmod 755 "$BIN_DEST"

echo -e "${GREEN}✅ BW-Proxy Appliance v3.6.1 installed successfully!${NC}"
echo -e "Usage: ${BLUE}bw-proxy admin status${NC}"
