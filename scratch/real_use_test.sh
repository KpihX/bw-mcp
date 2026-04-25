#!/bin/bash
set -e

echo "🚀 Starting BW-Proxy Real Use Verification Loop..."

# 1. Admin Setup (Discovery/Auth)
echo "--- [1] Admin Setup ---"
RESULT=$(bw-proxy admin setup)
echo "$RESULT" | jq .
if echo "$RESULT" | grep -q "session_key"; then
    echo "❌ ERROR: session_key exposed in setup output!"
    exit 1
fi
echo "✅ Admin setup output is secure."

# 2. Daemon Status
echo "--- [2] Status Check ---"
bw-proxy status || echo "⚠️ Daemon might be stopped (normal if not serve-mode yet)"

# 3. Admin Tools
echo "--- [3] Admin Logs ---"
bw-proxy admin log view -l 5

echo "--- [4] Admin WAL ---"
bw-proxy admin wal view

echo "--- [5] Admin Config ---"
bw-proxy admin config get

# 4. Do App (Action Surface)
echo "--- [6] Get Vault Map (Simulation) ---"
# Note: Real DO commands might require interactive HITL. 
# We'll try a search to see if session is correctly used.
bw-proxy do search_items --query "test" || echo "⚠️ Search failed (might be interactive or empty)"

echo "--- [7] Version ---"
bw-proxy --version

echo "🏆 Basic suite finished."
