# 🕹️ Operator Guide: Managing the Appliance

This guide covers the day-to-day management of the BW-Proxy appliance for human operators.

---

## 1. Lifecycle Management

### Checking Status
```bash
bw-proxy admin status
```
This shows your current Bitwarden server, account email, and whether the vault is locked/unlocked.

### Unlocking the Lease
```bash
bw-proxy admin unlock
```
Prompts for your Master Password and creates a **5-minute session lease** (configurable). During this window, AI agents can perform operations without interrupting you for a password.

### Relocking
```bash
bw-proxy admin lock
```
Immediately wipes the session lease and the `lease.key`. The appliance is now "Cold".

---

## 2. Configuration

The configuration lives in `/etc/bw-proxy/config.yaml` (System) or `~/.bw/proxy/docker.env` (Environment).

### Interactive Config Edit
```bash
bw-proxy admin config edit
```
This opens a secure browser-based YAML editor. It validates your syntax before saving.

---

## 3. Auditing the AI

### Transaction Logs
Every action taken by an AI agent is logged (redacted).
```bash
bw-proxy do inspect-log -n 5
```
Review the last 5 operations, including their rationales and success status.

### Duplicate Scans
The AI can help you clean your vault.
```bash
bw-proxy do find-duplicates --email ivann@...
```
This will trigger a HITL approval request on your browser. You can see which items are potential duplicates before the AI proceeds with any refactoring.

---

## 4. Troubleshooting

- **"New Device" Emails**: BW-Proxy uses a persistent machine ID. If you get repeated emails, ensure your Docker volume is not being deleted.
- **Port Contention**: If port `1138` is busy, the Shim will automatically pick a new random port for the HITL interface.
- **Recovery**: If a transaction fails, simply run `bw-proxy admin status`. It will detect the stale WAL and offer to recover.
