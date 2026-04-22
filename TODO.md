# TODO

- [x] Add a short operator runbook for the daemon lifecycle and WAL recovery flow.
- [x] Add a concise maintainer entrypoint section to the README so a new agent knows which `docs/` files to read first.
- [ ] Review whether the root `AGENT.md` should eventually be slimmed to match the newer `.agent/AGENT.md` handoff style.
- [ ] HTTP transport layer — expose bw-mcp over streamable-HTTP for homelab deployment (Traefik), following the tick-mcp/whats-mcp pattern.
- [ ] Telegram admin bridge — `/status`, `/wal`, `/recover` commands via a configured bot, same pattern as whats-mcp.
