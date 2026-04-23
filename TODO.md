# TODO

- [x] Add a short operator runbook for the daemon lifecycle and WAL recovery flow.
- [x] Add a concise maintainer entrypoint section to the README so a new agent knows which `docs/` files to read first.
- [x] Implement Blind Audit 2.0: Dynamic pathing (`fields.*`, `notes`, `uris`) and cross-namespace comparison.
- [x] Implement Blind Duplicate Scanner tools (`find_item_duplicates`, `find_all_vault_duplicates`) for vault-wide maintenance.
- [x] Enhance Audit HITL UI with item names and rich Zenity formatting.
- [x] Refactor and unify Audit Engine logic in `server.py` and `subprocess_wrapper.py`.
- [x] Integrate `check_recovery` and `Password-First` logic into all audit entrypoints (v1.9.0 finalization).
- [x] Standardize Sovereign root-owned installation with AppArmor confinement and user-side data parity (v1.9.1).
- [x] Implement Blind Refactoring Tool (`refactor_item_secrets`) for secure Move/Copy/Delete of secrets (v2.0.0 prep).
