# 💡 BW-MCP: Ideas for Future Evolution

This document tracks architectural enhancements, protocol-specific optimizations, and new features to further strengthen the sovereign bridge between LLMs and Bitwarden.

## 🛠️ MCP Protocol Extensions
- [ ] **Unified Administrative & Maintenance Layer**: Consolidate management and maintenance tasks directly into native MCP constructs (Tools, Resources, Prompts) for full remote operability.
    *   **Admin Tools**: `purge_logs(keep_n)`, `clear_wal()`, `update_config(key, value)`.
    *   **Dynamic Resources**: `bw://status` (health, limits), `bw://audit/recent` (execution traces).
    *   **Standard Prompts**: `/wal-clean` (guided recovery), `/hygiene` (system maintenance).

- [ ] **Blind Secret Comparator**: Allow the LLM to compare secret fields between two vault items without ever exposing their values.
    *   **Mechanism**: A `compare_secret_fields(item_id_a, field_a, item_id_b, field_b)` tool fetches both secret values internally (server-side, via `bw get item`), computes a comparison (equality or hash-based), wipes both values from memory (`bytearray` zeroing), and returns only a boolean result (`true` / `false`) to the agent.
    *   **Use Cases**: Detect duplicate passwords across accounts, verify that two identity items share the same SSN (data quality audit), confirm a migrated item has the same credential as its source without revealing it.
    *   **Security Guarantee**: The secret values never leave the proxy process — the LLM receives only `"MATCH"` or `"MISMATCH"`, making this a Zero-Trust-compliant audit primitive.
