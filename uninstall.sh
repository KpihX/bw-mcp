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

echo -e "${RED}🗑️  Uninstalling BW-Proxy Sovereign Appliance...${NC}"

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

# 2. Ask to remove Data
echo -en "${RED}Do you want to PERMANENTLY remove the persistent data volume ($VOLUME_NAME)? [y/N]: ${NC}"
read -r response
if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
  echo -e "${RED}Removing Docker volume $VOLUME_NAME...${NC}"
  docker volume rm "$VOLUME_NAME" || true
  echo -e "${RED}Removing config directory $CONFIG_DIR...${NC}"
  rm -rf "$CONFIG_DIR"
else
  echo -e "${GREEN}Data preserved in Docker volume $VOLUME_NAME.${NC}"
fi

echo -e "${GREEN}✅ BW-Proxy uninstalled.${NC}"
