#!/bin/bash
set -e

# --- Configuration ---
APP_NAME="bw-proxy"
BIN_DEST="/usr/local/bin/$APP_NAME"
CONFIG_DIR="/etc/$APP_NAME"
VOLUME_NAME="bw_mcp_bw-data"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${RED}🗑️  Purging BW-Proxy Sovereign Appliance...${NC}"

# Check for root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Error: Please run as root (sudo).${NC}"
  exit 1
fi

# 1. Remove Binary
if [ -f "$BIN_DEST" ]; then
  echo -e "${BLUE}Removing binary from $BIN_DEST...${NC}"
  rm -f "$BIN_DEST"
fi

# 2. Remove Config
if [ -d "$CONFIG_DIR" ]; then
  echo -e "${BLUE}Removing configuration directory $CONFIG_DIR...${NC}"
  rm -rf "$CONFIG_DIR"
fi

# 3. Handle Docker Data
echo -en "${RED}Do you want to PERMANENTLY delete the vault data (Docker Volume: $VOLUME_NAME)? [y/N]: ${NC}"
read -r response
if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
  echo -e "${RED}🔥 Deleting Docker volume $VOLUME_NAME...${NC}"
  docker volume rm "$VOLUME_NAME" || true
else
  echo -e "${GREEN}✅ Data volume preserved.${NC}"
fi

# 4. Clean up Home traces (optional but clean)
# Note: Since the appliance is system-wide, we check for ~/.bw/proxy too
# but we don't force delete it unless asked.

echo -e "${GREEN}✅ BW-Proxy Appliance has been cleanly removed from the system.${NC}"
