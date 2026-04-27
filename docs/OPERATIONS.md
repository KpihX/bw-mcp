# BW-MCP Operations Runbook 🛠️

This document covers the lifecycle management of the `bw-proxy mcp` runtime and the recovery flows for the Write-Ahead Log (WAL).

> Scope note:
> - **Shell mode**: `bw-proxy mcp` can run as a local stdio server with PID-based lifecycle commands.
> - **Docker mode**: the runtime is now ephemeral. The host wrapper launches a fresh container per invocation, so there is no background server to inspect, stop, or restart.

## 🔋 Server Lifecycle (Shell Mode)

The `bw-proxy mcp` command group includes a lifecycle controller to manage the local MCP process.

### Check Status
Verify if the server is running and which PID it owns.
```bash
bw-proxy mcp status
```

### Stop Server
Gracefully terminate the server. This sends a `SIGTERM` to the process.
```bash
bw-proxy mcp stop
```

### Restart Server
Forcefully restart the server (useful after updates).
```bash
bw-proxy mcp restart
```

## 🐳 Docker Runtime Model

Docker mode does **not** keep a resident MCP daemon alive.

Each invocation:
1. The host wrapper chooses a free loopback HITL port.
2. It launches `docker run --rm ... bw-proxy <args>`.
3. The container exits as soon as the command finishes.
4. Persistent state survives through the named Docker volume mounted at `/data`.

Implications:
- No `docker exec` against a shared MCP container.
- No fixed port `1138` reserved across the whole session.
- No daemon lifecycle commands in Docker mode.

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
bw-proxy admin wal view
```

---

## 📂 Troubleshooting

### Approval page does not open in Docker mode
The wrapper opens the approval URL on the host once the container prints it.
**Fix:** Verify that the host has a browser available and that loopback access to the chosen port is not blocked locally.

### "Item not found" during rollback
This happens if you modified an item via another Bitwarden client (Mobile, Web) during the short window of an MCP transaction.
**Fix:** The WAL will be preserved. Use `bw-proxy admin log view` to see the `failed_rollback` payload and manually fix the item in the Bitwarden Web Vault.
