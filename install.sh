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
docker pull "$IMAGE_NAME"

# 2. Create Volume
echo -e "${BLUE}💾 Ensuring persistent data volume exists...${NC}"
docker volume create "$VOLUME_NAME" > /dev/null

# 3. Create Config Directory
echo -e "${BLUE}⚙️  Creating system configuration directory at $CONFIG_DIR...${NC}"
mkdir -p "$CONFIG_DIR"
chmod 755 "$CONFIG_DIR"

# 4. Create Shim Binary
echo -e "${BLUE}🚀 Installing command-line wrapper to $BIN_DEST...${NC}"
# We generate a self-contained shim that calls docker
cat <<EOF > "$BIN_DEST"
#!/usr/bin/env python3
import os
import sys
import subprocess
import socket
import shutil

# --- Appliance Constants ---
IMAGE = "$IMAGE_NAME"
VOLUME = "$VOLUME_NAME"
DATA_DIR = "/data"
WORKSPACE_DIR = "/workspace"

def _pick_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

def main():
    args = sys.argv[1:] or ["mcp", "serve"]
    port = _pick_port()
    
    # Generate stable runtime name
    try:
        import hashlib
        cwd_hash = hashlib.sha256(os.getcwd().encode()).hexdigest()[:8]
        runtime_name = f"bw-proxy-runtime-{os.getuid()}-{cwd_hash}"
    except:
        runtime_name = f"bw-proxy-runtime-{os.getuid()}"

    # Base docker run command
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
    
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        sys.exit(130)

if __name__ == "__main__":
    main()
EOF

chmod 755 "$BIN_DEST"

echo -e "${GREEN}✅ BW-Proxy Appliance installed successfully!${NC}"
echo -e "You can now run it anywhere with: ${BLUE}$APP_NAME admin status${NC}"
