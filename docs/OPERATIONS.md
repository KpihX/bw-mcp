# BW-MCP Operations Runbook 🛠️

This document covers the lifecycle management of the `bw-mcp` server and the recovery flows for the Write-Ahead Log (WAL).

## 🔋 Server Lifecycle

The `bw-mcp` package includes a lifecycle controller to manage the background process.

### Check Status
Verify if the server is running and which PID it owns.
```bash
bw-mcp status
```

### Stop Server
Gracefully terminate the server. This sends a `SIGTERM` to the process.
```bash
bw-mcp stop
```

### Restart Server
Forcefully restart the server (useful after updates).
```bash
bw-mcp restart
```

---

## 🔐 WAL Recovery Flow

The Write-Ahead Log (WAL) ensures your vault remains consistent even if a transaction is interrupted.

### Symptom: `PENDING` WAL
If `get_proxy_audit_context()` returns `wal_status: "PENDING"`, it means a transaction crashed mid-flight.

### Automatic Recovery
Simply performing ANY read or write operation (e.g., `get_vault_map`) will trigger the recovery logic.
1. The proxy detects the `.wal` file.
2. A Zenity popup asks for your Master Password.
3. The proxy decrypts the WAL and rolls back the interrupted transaction.
4. The `.wal` file is deleted upon success.

### Manual Inspection
If automatic recovery fails or you want to see what's inside the WAL:
```bash
# View the scrubbed content of the WAL
uv run bw-proxy wal view

# Force delete the WAL (WARNING: Vault might remain in inconsistent state)
uv run bw-proxy wal delete
```

---

## 📂 Troubleshooting

### Zenity Popup doesn't appear
If you are running in a headless environment (SSH without X-forwarding), Zenity will fail.
**Fix:** Ensure your `DISPLAY` variable is set or use a machine with a desktop environment.

### "Item not found" during rollback
This happens if you modified an item via another Bitwarden client (Mobile, Web) during the short window of an MCP transaction.
**Fix:** The WAL will be preserved. Use `bw-proxy log view` to see the `failed_rollback` payload and manually fix the item in the Bitwarden Web Vault.
