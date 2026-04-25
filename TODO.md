# TODO: BW-Proxy

## High Priority (Infrastructure & Reliability)
- [ ] **Robust Port Management**: Fix "Address already in use" errors in `web_ui.py`. 
    - Implement a retry mechanism with backoff.
    - Optionally allow a dynamic port fallback or explicit port override.
- [ ] **Output Redirection**: Add a `--output-file` (or `-o`) argument to `bw-proxy do` commands to save results directly to a file (e.g., `vault_map.json`).
- [ ] **Session Persistence (Encrypted)**: Implement a way to store the session key encrypted on disk (RAM-only by default, but allow short-lived persistence to avoid redundant HITL).

## Technical Debt & Hardening
- [ ] **SSL/HTTPS Parity**: Restore reliable HTTPS for the HITL server with a valid-enough self-signed certificate (SAN fields).
- [ ] **Transaction Rollback Testing**: Verify that complex failures correctly trigger the 3-phase commit rollback.

## Future Features
- [ ] **Batch Import**: Support importing items from a JSON file via a transaction.
- [ ] **Sovereign Dashboard**: A more complete web interface for managing the proxy settings.
