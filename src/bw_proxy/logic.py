import json
import os
from typing import Dict, Any, List, Optional, Annotated
from copy import deepcopy

from .config import MAX_BATCH_SIZE, REDACTED_POPULATED, AUDIT_MATCH_TAG, AUDIT_MISMATCH_TAG, MAX_AUDIT_SCAN_SIZE
from .subprocess_wrapper import SecureSubprocessWrapper, SecureBWError, SecureProxyError, _safe_error_message
from .models import (
    BlindItem, BlindFolder, BlindOrganization, BlindOrganizationCollection, 
    TransactionPayload, TemplateType, BatchComparePayload, TransactionStatus,
    FindDuplicatesPayload, CompareSecretRequest, FindDuplicatesBatchPayload,
    FindAllDuplicatesPayload
)
from .transaction import TransactionManager
from .logger import TransactionLogger
from .wal import WALManager
from .ui import HITLManager
from .scrubber import deep_scrub_payload
from .config import (
    CONFIG_PATH,
    DOCKER_UNLOCK_MAX_DURATION_SECONDS,
    dump_config_text,
    get_config_value,
    HITL_VALIDATION_MODE,
    set_config_value,
    write_config_text,
)
from .unlock_lease import UnlockLeaseManager, is_docker_runtime
from .vault_runtime import (
    VaultExecutionContext,
    auth_state,
    autosave_large_result,
    build_execution_context,
    ensure_fresh_sync,
    ensure_target_server,
    finalize_execution_context,
    get_command_policy,
    load_bw_status,
    relock_vault,
    requires_authenticated_vault,
    requires_fresh_sync,
    supports_unlock_lease,
    validate_authenticated_context,
)
vault_operation = requires_authenticated_vault  # Alias for tests
from .web_ui import WebEditorManager
from .wal import WAL_FILE


def _result(status: str, message: str, **extra: Any) -> Dict[str, Any]:
    payload = {"status": status, "message": message}
    payload.update(extra)
    return payload


def _success(message: str, **extra: Any) -> Dict[str, Any]:
    return _result("success", message, **extra)


def _error(message: str, **extra: Any) -> Dict[str, Any]:
    return _result("error", message, **extra)


def _aborted(message: str, **extra: Any) -> Dict[str, Any]:
    return _result("aborted", message, **extra)


def _coerce_logic_response(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
            return _success("Operation completed.", data=parsed)
        except json.JSONDecodeError:
            text = raw.strip()
            lower = text.lower()
            if lower.startswith("success"):
                return _success(text)
            if "aborted" in lower or "cancelled" in lower:
                return _aborted(text)
            if "error" in lower or "failed" in lower or "fatal" in lower:
                return _error(text)
            return _success(text)
    return _success("Operation completed.", data=raw)


def _transaction_result(raw: Any, *, operation_type: str) -> Dict[str, Any]:
    parsed = _coerce_logic_response(raw)
    message = parsed.get("message", "")
    if parsed.get("status") == "success" and "data" not in parsed and "results" not in parsed and message:
        if "\n" in message:
            lines = [line for line in message.splitlines() if line.strip()]
            parsed["message"] = lines[0]
            parsed["execution_trace"] = lines[1:]
    parsed.setdefault("operation_type", operation_type)
    return parsed


def _recovery_result(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    return _transaction_result(raw, operation_type="recovery")


def _normalize_search_term(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value[:256].strip()
    return value or None


def _matches_search(value: Optional[str], search: Optional[str]) -> bool:
    if not search:
        return True
    return search.casefold() in (value or "").casefold()


def _dedupe_by_id(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in rows:
        row_id = row.get("id")
        if row_id:
            if row_id in seen_ids:
                continue
            seen_ids.add(row_id)
        deduped.append(row)
    return deduped


def _filter_raw_items(
    rows: List[Dict[str, Any]],
    *,
    search_items: Optional[str],
    folder_id: Optional[str],
    collection_id: Optional[str],
    organization_id: Optional[str],
) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    for row in rows:
        if not _matches_search(row.get("name"), search_items):
            login_block = row.get("login") or {}
            uris = login_block.get("uris") or []
            if not any(_matches_search(uri.get("uri"), search_items) for uri in uris if isinstance(uri, dict)):
                continue
        if folder_id is not None and row.get("folderId") != folder_id:
            continue
        if organization_id is not None and row.get("organizationId") != organization_id:
            continue
        if collection_id is not None:
            collection_ids = row.get("collectionIds") or []
            if collection_id not in collection_ids:
                continue
        filtered.append(row)
    return _dedupe_by_id(filtered)


def _filter_raw_folders(rows: List[Dict[str, Any]], *, search_folders: Optional[str]) -> List[Dict[str, Any]]:
    return _dedupe_by_id([row for row in rows if _matches_search(row.get("name"), search_folders)])


def _split_active_and_trash_rows(
    active_rows: List[Dict[str, Any]],
    trash_rows: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Some Bitwarden CLI versions can surface the same entity in both active and trash list calls.
    Prefer the explicit trash result and remove duplicates from the active side.
    """
    trash_rows = _dedupe_by_id(trash_rows)
    trash_ids = {row.get("id") for row in trash_rows if row.get("id")}
    active_rows = _dedupe_by_id(
        [row for row in active_rows if not row.get("id") or row.get("id") not in trash_ids]
    )
    return active_rows, trash_rows


def _resolve_context_session(
    execution_context: Optional[VaultExecutionContext],
    *,
    password_from_review: Optional[bytearray] = None,
    sync_after_unlock: bool = False,
) -> Optional[bytearray]:
    if execution_context is None:
        return None
    if execution_context.session_key is None:
        from .vault_runtime import open_vault_session

        open_vault_session(execution_context, master_password=password_from_review)
    if sync_after_unlock and execution_context.session_key is not None:
        ensure_fresh_sync(execution_context)
    return execution_context.session_key


def _lease_status() -> dict:
    lease_status = UnlockLeaseManager.status()
    if lease_status.get("state") == "expired":
        try:
            UnlockLeaseManager.clear()
            relock_vault()
        except Exception:
            pass
    return lease_status


def _maybe_run_recovery(session_key: Optional[bytearray]) -> Optional[Dict[str, Any]]:
    if session_key is None or not WALManager.has_pending_transaction():
        return None
    recovery_msg = _recovery_result(TransactionManager.check_recovery(session_key))
    return recovery_msg if recovery_msg else None


def _login_hint() -> str:
    email = os.environ.get("BW_EMAIL") or "<email>"
    url = os.environ.get("BW_URL") or "<server-url>"
    return f"bw-proxy admin login --email {email} --url {url}"


# Backward-compatible aliases for tests and narrow internal imports that still
# target the older helper names.
_load_bw_status = load_bw_status
_auth_state = auth_state
_ensure_target_server = ensure_target_server
_validate_authenticated_context = validate_authenticated_context
_relock_vault = relock_vault


def _open_authenticated_vault(title: str) -> tuple[Optional[bytearray], Optional[bytearray]]:
    status = _load_bw_status()
    state = _auth_state(status)
    if state == "unauthenticated":
        raise SecureProxyError(
            "Bitwarden is logged out. Run "
            f"'{_login_hint()}' first, then retry the 'do' command."
        )
    _validate_authenticated_context(status)
    master_password = HITLManager.ask_master_password(title=title)
    if not master_password:
        raise SecureProxyError("Authentication cancelled. Master Password is required to unlock the authenticated vault.")
    session_key = SecureSubprocessWrapper.unlock_vault(master_password)
    return master_password, session_key

def login(email: str, url: str) -> Dict[str, Any]:
    """
    Authenticates with the Bitwarden server.
    
    Args:
        email: The account email address.
    """
    mp: Optional[bytearray] = None
    sk: Optional[bytearray] = None
    try:
        _ensure_target_server(url)
        status_before = _load_bw_status()
        state_before = _auth_state(status_before)

        if state_before in {"locked", "unlocked"}:
            _validate_authenticated_context(
                status_before,
                expected_server=url,
                expected_email=email,
            )
            if state_before == "unlocked":
                _relock_vault()
            return _success(
                "Bitwarden is already authenticated. Vault is locked and ready for future 'do' commands.",
                email=email,
                url=url,
                authenticated=True,
                auth_status="locked",
                mode="noop",
            )

        mp = HITLManager.ask_master_password(title=f"Login: {email}")
        if not mp:
            return _aborted("Password cancelled.", email=email, url=url)

        sk = SecureSubprocessWrapper.login_vault(email, mp)
        UnlockLeaseManager.clear()
        _relock_vault()
        return _success(
            "Logged in successfully. The vault is now authenticated and locked.",
            email=email,
            url=url,
            authenticated=True,
            auth_status="locked",
            mode="login",
        )
    except Exception as e:
        return _error(_safe_error_message(e), email=email, url=url)
    finally:
        if sk is not None:
            for i in range(len(sk)):
                sk[i] = 0
        if mp is not None:
            for i in range(len(mp)):
                mp[i] = 0

def get_admin_status() -> Dict[str, Any]:
    """Return local operational status for the human/operator CLI."""
    bw_status = _load_bw_status()
    configured_server = os.environ.get("BW_URL")
    configured_email = os.environ.get("BW_EMAIL")
    if not configured_server:
        try:
            configured_server = SecureSubprocessWrapper.get_server() or None
        except Exception:
            configured_server = None
    lease_status = _lease_status()
    if _auth_state(bw_status) == "unauthenticated" and lease_status.get("state") == "active":
        UnlockLeaseManager.clear()
        lease_status = {
            "state": "invalidated",
            "message": "A stale unlock lease was cleared because Bitwarden is logged out.",
        }

    pending_wal = WALManager.has_pending_transaction()

    return _success(
        "Loaded administrative status.",
        bitwarden_status=bw_status,
        configured_auth={
            "server_url": configured_server,
            "user_email": configured_email,
        },
        wal={
            "pending": pending_wal,
            "state": "pending" if pending_wal else "clean",
            "file": WAL_FILE,
            "note": (
                "A WAL artifact exists. This usually means an interrupted transaction or a stale recovery file."
                if pending_wal
                else "No pending WAL artifact."
            ),
        },
        config={
            "path": str(CONFIG_PATH),
            "max_batch_size": MAX_BATCH_SIZE,
            "validation_mode": HITL_VALIDATION_MODE,
        },
        unlock_lease=lease_status,
    )

def admin_unlock() -> Dict[str, Any]:
    """Create a Docker-only temporary unlock lease for repeated do commands."""
    if not is_docker_runtime():
        return _error("admin unlock is only supported in Docker mode.")

    status = _load_bw_status()
    state = _auth_state(status)
    if state == "unauthenticated":
        return _error(
            "Bitwarden is logged out. Run "
            f"'{_login_hint()}' first."
        )
    try:
        _validate_authenticated_context(status)
    except Exception as exc:
        return _error(_safe_error_message(exc))

    lease_status = _lease_status()
    if lease_status.get("state") == "active":
        return _success(
            "Unlock lease is already active.",
            unlock_lease=lease_status,
            mode="noop",
        )

    mp: Optional[bytearray] = None
    sk: Optional[bytearray] = None
    try:
        mp = HITLManager.ask_master_password(title="Create Docker Unlock Lease")
        if not mp:
            return _aborted("Unlock lease creation cancelled by the user.")
        sk = SecureSubprocessWrapper.unlock_vault(mp)
        lease = UnlockLeaseManager.create(
            session_key=sk,
            server_url=status.get("serverUrl") or os.environ.get("BW_URL"),
            user_email=status.get("userEmail") or os.environ.get("BW_EMAIL"),
        )
        try:
            _relock_vault()
        except Exception as exc:
            UnlockLeaseManager.clear()
            return _error(
                "Unlock lease creation failed because the vault could not be re-locked safely. "
                f"Lease discarded. {_safe_error_message(exc)}"
            )
        return _success(
            "Docker unlock lease created.",
            unlock_lease=UnlockLeaseManager.status(),
            expires_at=lease.expires_at,
            duration_seconds=DOCKER_UNLOCK_MAX_DURATION_SECONDS,
        )
    except Exception as exc:
        return _error(_safe_error_message(exc))
    finally:
        if sk is not None:
            for i in range(len(sk)):
                sk[i] = 0
        if mp is not None:
            for i in range(len(mp)):
                mp[i] = 0


def admin_lock() -> Dict[str, Any]:
    """Clear the Docker unlock lease and force the local vault back to locked state."""
    if not is_docker_runtime():
        return _error("admin lock is only supported in Docker mode.")

    lease_status = _lease_status()
    UnlockLeaseManager.clear()

    status = _load_bw_status()
    state = _auth_state(status)
    if state == "unauthenticated":
        return _success(
            "Bitwarden is already logged out. Unlock lease cleared.",
            unlock_lease={"state": "none"},
            mode="noop",
        )

    try:
        _relock_vault()
    except Exception as exc:
        return _error(
            f"Unlock lease cleared, but failed to lock the local Bitwarden vault: {_safe_error_message(exc)}"
        )
    return _success(
        "Unlock lease cleared and vault locked.",
        previous_unlock_lease=lease_status,
        unlock_lease={"state": "none"},
    )


@requires_authenticated_vault("Manual Vault Synchronization")
@supports_unlock_lease
def sync(session_key: Optional[bytearray] = None, **kwargs) -> Dict[str, Any]:
    """
    Forces a manual vault synchronization with the Bitwarden server.
    Pulls latest changes from the remote vault into the local cache.
    Note: All vault-access commands (get-vault-map, propose-vault-transaction, etc.)
    already perform an automatic sync before execution. Use this command only when
    you need an explicit manual sync without any other operation.

    Output: JSON with {"status": "success", "message": "..."}.

    Example:
      bw-proxy do sync
    """
    try:
        res = SecureSubprocessWrapper.execute(["sync"], session_key)
        return _success(res)
    except Exception as e:
        return _error(f"Sync failed: {_safe_error_message(e)}")


def logout() -> Dict[str, Any]:
    """
    Logs out from Bitwarden and clears any ephemeral session state.
    After logout, the next vault operation will require re-authentication.

    Output: JSON with {"status": "success", "message": "..."}.

    Example:
      bw-proxy admin logout
    """
    try:
        UnlockLeaseManager.clear()
        status_before = _load_bw_status()
        if status_before.get("status") == "unauthenticated":
            return _success("Already logged out.", authenticated=False, mode="noop")
        res = SecureSubprocessWrapper.logout_vault()
        status_after = _load_bw_status()
        if status_after.get("status") == "unauthenticated":
            return _success(res or "Logged out.", authenticated=False, mode="logout")
        return _success(res or "Logout command completed.", authenticated=False, mode="logout")
    except Exception as e:
        status_after = _load_bw_status()
        if status_after.get("status") == "unauthenticated":
            return _success("Already logged out.", authenticated=False, mode="noop")
        return _error(f"Logout failed: {_safe_error_message(e)}")


def get_config_param(path: str) -> Dict[str, Any]:
    try:
        value = get_config_value(path)
        return _success("Configuration value loaded.", path=path, value=value)
    except KeyError:
        return _error(f"Unknown configuration path: {path}", path=path)


def set_config_param(path: str, value: Any) -> Dict[str, Any]:
    try:
        if path == "hitl.validation_mode":
            normalized = str(value).strip().lower()
            if normalized not in {"browser", "terminal"}:
                return _error("Invalid validation mode. Expected one of: browser, terminal.", path=path)
            value = normalized
        persisted = set_config_value(path, value)
        return _success("Configuration value updated.", path=path, value=persisted)
    except Exception as exc:
        return _error(f"Failed to update configuration: {_safe_error_message(exc)}", path=path)


def edit_config_interactively() -> Dict[str, Any]:
    raw_text = dump_config_text()
    response = WebEditorManager.edit_text(
        title="BW-Proxy Config Editor",
        initial_text=raw_text,
        on_save=write_config_text,
    )
    if not response or not response.get("approved"):
        return _aborted("Configuration edit cancelled.")
    saved = response.get("data") or {}
    return _success("Configuration updated successfully.", config=saved, path=str(CONFIG_PATH))

@requires_authenticated_vault("Retrieve Vault Map")
@supports_unlock_lease
@requires_fresh_sync
@autosave_large_result
def get_vault_map(
    search_items: Optional[str] = None,
    search_folders: Optional[str] = None,
    folder_id: Optional[str] = None,
    collection_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    trash_state: str = "all",
    include_orgs: bool = True,
    session_key: Optional[bytearray] = None,
    execution_context: Optional[VaultExecutionContext] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Retrieves a comprehensive, sanitized map of the vault including Items, Folders,
    Organizations, and Collections. All secret fields (passwords, TOTP, card numbers,
    SSN, etc.) are automatically redacted — the caller never sees sensitive values.

    Output JSON structure:
      {"status": "success", "data": {
        "items": [...], "folders": [...], "trash_items": [...],
        "trash_folders": [...], "organizations": [...], "collections": [...]
      }}

    Args:
        search_items: Case-insensitive substring filter on item name or login URI.
        search_folders: Case-insensitive substring filter on folder name.
        folder_id: UUID of a specific folder. Only items in that folder are returned.
        collection_id: UUID of a specific collection. Only items in that collection are returned.
        organization_id: UUID of an organization. Filters items, collections, and orgs.
        trash_state: Controls trash visibility. Values: 'none' (active only), 'only' (trash only), 'all' (both). Default: 'all'.
        include_orgs: If true (default), include organizations and collections in the output.

    Examples:
      bw-proxy do get-vault-map
      bw-proxy do get-vault-map '{"search_items": "github"}'
      bw-proxy do get-vault-map '{"trash_state": "only"}'
      bw-proxy do get-vault-map '{"organization_id": "3b79...", "include_orgs": true}'
      bw-proxy do get-vault-map -o /tmp/vault.json
    """
    try:
        search_items = _normalize_search_term(search_items)
        search_folders = _normalize_search_term(search_folders)

        has_item_filters = any([search_items, folder_id, collection_id, organization_id])
        has_folder_filters = bool(search_folders)
        fetch_items = not has_folder_filters or has_item_filters
        fetch_folders = not has_item_filters or has_folder_filters

        items_base_args = ["list", "items"]
        if search_items:
            items_base_args.extend(["--search", search_items])
        if folder_id:
            items_base_args.extend(["--folderid", folder_id])
        if collection_id:
            items_base_args.extend(["--collectionid", collection_id])
        if organization_id:
            items_base_args.extend(["--organizationid", organization_id])

        folders_base_args = ["list", "folders"]
        if search_folders:
            folders_base_args.extend(["--search", search_folders])

        folders = []
        items = []
        trash_items = []
        trash_folders = []
        organizations = []
        collections = []
        raw_items: List[Dict[str, Any]] = []
        raw_trash_items: List[Dict[str, Any]] = []
        raw_folders: List[Dict[str, Any]] = []
        raw_trash_folders: List[Dict[str, Any]] = []

        if trash_state in ["none", "all"] and fetch_items:
            raw_items = SecureSubprocessWrapper.execute_json(items_base_args, session_key)
            raw_items = _filter_raw_items(
                raw_items,
                search_items=search_items,
                folder_id=folder_id,
                collection_id=collection_id,
                organization_id=organization_id,
            )

        if trash_state in ["none", "all"] and fetch_folders:
            raw_folders = SecureSubprocessWrapper.execute_json(folders_base_args, session_key)
            raw_folders = _filter_raw_folders(raw_folders, search_folders=search_folders)

        if trash_state in ["only", "all"] and fetch_items:
            trash_items_args = items_base_args + ["--trash"]
            raw_trash_items = SecureSubprocessWrapper.execute_json(trash_items_args, session_key)
            raw_trash_items = _filter_raw_items(
                raw_trash_items,
                search_items=search_items,
                folder_id=folder_id,
                collection_id=collection_id,
                organization_id=organization_id,
            )

        if trash_state in ["only", "all"] and fetch_folders:
            trash_folders_args = folders_base_args + ["--trash"]
            raw_trash_folders = SecureSubprocessWrapper.execute_json(trash_folders_args, session_key)
            raw_trash_folders = _filter_raw_folders(raw_trash_folders, search_folders=search_folders)

        raw_items, raw_trash_items = _split_active_and_trash_rows(raw_items, raw_trash_items)
        raw_folders, raw_trash_folders = _split_active_and_trash_rows(raw_folders, raw_trash_folders)

        items = [BlindItem(**deepcopy(i)).model_dump(exclude_unset=True) for i in raw_items]
        folders = [BlindFolder(**deepcopy(f)).model_dump(exclude_unset=True) for f in raw_folders]
        trash_items = [BlindItem(**deepcopy(i)).model_dump(exclude_unset=True) for i in raw_trash_items]
        trash_folders = [BlindFolder(**deepcopy(f)).model_dump(exclude_unset=True) for f in raw_trash_folders]

        if include_orgs:
            try:
                raw_orgs = SecureSubprocessWrapper.execute_json(["list", "organizations"], session_key)
                if organization_id:
                    raw_orgs = [o for o in raw_orgs if o.get("id") == organization_id]
                organizations = [BlindOrganization(**deepcopy(o)).model_dump(exclude_unset=True) for o in raw_orgs]

                cols_args = ["list", "collections"]
                if organization_id:
                    cols_args.extend(["--organizationid", organization_id])
                
                raw_cols = SecureSubprocessWrapper.execute_json(cols_args, session_key)
                if organization_id:
                    raw_cols = [c for c in raw_cols if c.get("organizationId") == organization_id]
                if collection_id:
                    raw_cols = [c for c in raw_cols if c.get("id") == collection_id]
                collections = [BlindOrganizationCollection(**deepcopy(c)).model_dump(exclude_unset=True) for c in raw_cols]
            except Exception:
                organizations = []
                collections = []
        
        result = {
            "status": "success",
            "message": "Vault map successfully retrieved. Sensitive fields are redacted.",
            "data": {
                "folders": folders,
                "items": items,
                "trash_items": trash_items,
                "trash_folders": trash_folders,
                "organizations": organizations,
                "collections": collections
            }
        }
        
        return result
    except SecureBWError as e:
        return _error(f"Bitwarden CLI Error: {str(e)}")
    except Exception as e:
        return _error(f"Proxy Internal Error during serialization: {_safe_error_message(e)}")

@requires_authenticated_vault("Vault Transaction Proposal", unlock_deferred=True)
@supports_unlock_lease
@requires_fresh_sync
def propose_vault_transaction(
    rationale: str, 
    operations: List[Dict[str, Any]], 
    execution_context: Optional[VaultExecutionContext] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Proposes a batch of modifications to the vault through the ACID transaction engine.
    Every transaction is Atomic (all-or-nothing) and backed by a Write-Ahead Log (WAL).
    A browser popup shows all proposed operations to the user, who must enter their
    Master Password to approve execution. Destructive actions trigger RED ALERTS.

    Args:
        rationale: Human-readable reason for the transaction (shown in the approval popup).
        operations: JSON array of operation objects. Each MUST have an "action" field.

    Valid actions and their required fields:

      ITEM ACTIONS:
        create_item     -> type (1=Login, 2=SecureNote, 3=Card, 4=Identity), name. Optional: folder_id, login, card, identity.
        rename_item     -> target_id, new_name
        move_item       -> target_id, folder_id (UUID or null for root)
        delete_item     -> target_id  [WARNING: moves to trash]
        restore_item    -> target_id  [restores from trash]
        favorite_item   -> target_id, favorite (bool)
        move_to_collection -> target_id, organization_id, collection_ids (list)
        toggle_reprompt -> target_id, reprompt (bool)
        delete_attachment -> target_id, attachment_id  [UNRECOVERABLE - must be alone in batch]

      FOLDER ACTIONS:
        create_folder   -> name
        rename_folder   -> target_id, new_name
        delete_folder   -> target_id  [HARD DELETE - must be alone in batch, no trash]

      EDIT ACTIONS:
        edit_item_login    -> target_id, optional: username, uris
        edit_item_card     -> target_id, optional: cardholderName, brand, expMonth, expYear
        edit_item_identity -> target_id, optional: title, firstName, email, phone, etc.
        upsert_custom_field -> target_id, name, value, type (0=Text, 2=Boolean)

    SECURITY: Passing secret fields (password, totp, number, code, ssn) will FAIL validation.
    BATCH LIMIT: Max 15 operations per transaction (configurable via config.yaml).

    Examples:
      bw-proxy do propose-vault-transaction '{
        "rationale": "Organize vault",
        "operations": [{"action":"create_folder","name":"Servers"}]
      }'

      bw-proxy do propose-vault-transaction /tmp/operations.json
      bw-proxy do -o /tmp/tx_result.json propose-vault-transaction /tmp/operations.json
    """
    payload = {
        "rationale": rationale,
        "operations": operations
    }
    try:
        return _transaction_result(
            TransactionManager.execute_batch(payload, execution_context=execution_context),
            operation_type="transaction",
        )
    except Exception as e:
        return _error(f"Proxy Error processing transaction: {_safe_error_message(e)}", operation_type="transaction")

def get_proxy_audit_context(limit: int = 5) -> Dict[str, Any]:
    """
    Returns the current operational status and recent transaction history of the BW-Proxy.
    Use this to check for Write-Ahead Log (WAL) orphans (crashed transactions awaiting
    auto-recovery) and to review recent transaction outcomes.

    Output JSON structure:
      {"wal_status": "CLEAN|PENDING", "max_batch_size": 15,
       "recent_transactions": [{"timestamp": ..., "transaction_id": ..., "status": ..., "rationale": ...}]}

    Args:
        limit: Number of recent transactions to include in the output (default: 5).

    Examples:
      bw-proxy do get-proxy-audit-context
      bw-proxy do get-proxy-audit-context '{"limit": 20}'
    """
    has_wal = WALManager.has_pending_transaction()
    wal_status_msg = "CLEAN (Vault is synchronized)" if not has_wal else "PENDING (A transaction crashed and is awaiting auto-recovery.)"
    recent_logs = TransactionLogger.get_recent_logs_summary(limit)
    context = _success(
        "Loaded proxy audit context.",
        wal_status=wal_status_msg,
        max_batch_size=MAX_BATCH_SIZE,
        recent_transactions=recent_logs,
    )
    return context

def inspect_transaction_log(tx_id: str = None, n: int = None) -> Dict[str, Any]:
    """
    Fetches the COMPLETE detailed JSON payload of a specific transaction log.
    Contains the full execution_trace, rollback_trace, error_message, and all
    operation details. Use this to diagnose failed or rolled-back transactions.

    Provide exactly one of tx_id or n in the RPC payload (not both).

    Args:
        tx_id: UUID of the transaction to inspect (from get-proxy-audit-context output).
        n: Index of the transaction, 1-indexed from newest (1=most recent, 2=second most recent, etc.).

    Examples:
      bw-proxy do inspect-log '{"n": 1}'
      bw-proxy do inspect-log '{"tx_id": "3171cf74-3104-4184-b1b0-cd0c69199d2f"}'
      bw-proxy do -o /tmp/tx_details.json inspect-log '{"n": 1}'
    """
    try:
        log_data = TransactionLogger.get_log_details(tx_id=tx_id, n=n)
        return _success("Loaded transaction log.", log=log_data)
    except SecureProxyError as e:
        return _error(_safe_error_message(e))
    except Exception as e:
        return _error(f"Unexpected Error reading log: {_safe_error_message(e)}")

@requires_authenticated_vault("Blind Secret Comparison Audit", unlock_deferred=True)
@supports_unlock_lease
@requires_fresh_sync
@autosave_large_result
def compare_secrets_batch(
    payload: BatchComparePayload, 
    session_key: Optional[bytearray] = None, 
    execution_context: Optional[VaultExecutionContext] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    BLIND AUDIT: Safely compares secret fields (passwords, TOTPs, notes, custom fields)
    between vault items without EVER exposing the actual values. Returns MATCH or MISMATCH
    verdicts for each comparison pair.

    Args:
        payload: JSON object with the comparison batch. Schema:
          {
            "rationale": "Why this audit is needed",
            "comparisons": [
              {
                "item_id_a": "UUID of first item",
                "field_a": "field path (e.g. login.password, notes, fields.API_KEY)",
                "item_id_b": "UUID of second item",
                "field_b": "field path"
              }
            ]
          }

    Valid field paths: login.password, login.totp, notes, card.number, card.code,
      identity.ssn, identity.passportNumber, identity.licenseNumber, login.uris,
      fields.<FIELD_NAME> (for custom fields by name).

    Output: {"status": "success", "results": [{"index": 1, "verdict": "MATCH|MISMATCH", ...}]}

    Examples:
      bw-proxy do compare-secrets-batch '{
        "rationale": "Check if GitHub and GitLab share the same password",
        "comparisons": [{
          "item_id_a": "aaa-111", "field_a": "login.password",
          "item_id_b": "bbb-222", "field_b": "login.password"
        }]
      }'

      bw-proxy do compare-secrets-batch /tmp/audit_request.json
    """
    try:
        id_to_name = {}
        active_session = session_key
        if active_session is not None:
            try:
                raw_items = SecureSubprocessWrapper.execute_json(["list", "items"], active_session)
                for item in raw_items:
                    if item.get("id") and item.get("name"):
                        id_to_name[item["id"]] = item["name"]
            except Exception:
                pass

        approval = HITLManager.authorize_comparisons(
            payload,
            id_to_name,
            needs_password=active_session is None,
        )
        if not approval.get("approved"):
            return _aborted("Audit cancelled by user.")

        active_session = _resolve_context_session(
            execution_context,
            password_from_review=approval.get("password"),
            sync_after_unlock=True,
        ) or active_session
        recovery_msg = _maybe_run_recovery(active_session)
        if recovery_msg:
            return recovery_msg

        results = []
        for i, req in enumerate(payload.comparisons, 1):
            try:
                is_match = SecureSubprocessWrapper.audit_compare_secrets(
                    req.item_id_a, req.field_a, req.custom_name_a,
                    req.item_id_b, req.field_b, req.custom_name_b,
                    active_session
                )
                verdict = AUDIT_MATCH_TAG if is_match else AUDIT_MISMATCH_TAG
                results.append({
                    "index": i,
                    "item_a": req.item_id_a,
                    "field_a": req.field_a,
                    "item_b": req.item_id_b,
                    "field_b": req.field_b,
                    "verdict": verdict
                })
            except Exception as e:
                results.append({"index": i, "error": _safe_error_message(e)})

        return _success("Blind audit completed.", results=results)
    except Exception as e:
        return _error(f"Proxy Error during audit: {_safe_error_message(e)}")

@requires_authenticated_vault("Fetch Entity Template")
@supports_unlock_lease
def fetch_template(
    template_type: str, 
    session_key: Optional[bytearray] = None, 
    execution_context: Optional[VaultExecutionContext] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Fetches the sanitized JSON schema template for a Bitwarden entity type.
    Useful for understanding the valid fields before creating or editing items.
    Secret fields are proactively redacted in the output.

    Args:
        template_type: One of: 'item', 'item.login', 'item.card', 'item.identity', 'item.secureNote', 'folder'.

    Output: {"_metadata": {...}, "template": {<redacted schema>}}

    Examples:
      bw-proxy do get-template '{"template_type": "item.login"}'
      bw-proxy do get-template '{"template_type": "folder"}'
      bw-proxy do -o /tmp/card_schema.json get-template '{"template_type": "item.card"}'
    """
    try:
        valid_type = TemplateType(template_type)
    except ValueError:
        valid_types = [e.value for e in TemplateType]
        return _error(f"Invalid template type '{template_type}'. Must be one of: {', '.join(valid_types)}")

    try:
        template_data = SecureSubprocessWrapper.execute_json(["get", "template", valid_type.value], session_key)
        safe_data = deep_scrub_payload(template_data)
        
        return _success(
            "Template loaded.",
            _metadata={
                "source": f"bw get template {valid_type.value}",
                "note": "Secret fields have been proactively redacted by BW-Proxy to maintain AI-Blindness."
            },
            template=safe_data,
        )
    except SecureBWError as e:
        return _error(f"Bitwarden CLI Error: {str(e)}")
    except Exception as e:
        return _error(f"Proxy Error: {_safe_error_message(e)}")

@requires_authenticated_vault("Duplicate Secret Scan", unlock_deferred=True)
@supports_unlock_lease
@requires_fresh_sync
@autosave_large_result
def find_item_duplicates(
    payload: FindDuplicatesPayload, 
    session_key: Optional[bytearray] = None, 
    execution_context: Optional[VaultExecutionContext] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Finds vault items that share the same secret value as a target item.
    Compares the target's secret field against all candidates of the same type.
    Useful for detecting password reuse across the vault.

    Args:
        payload: JSON object with the scan request. Schema:
          {
            "rationale": "Why this scan is needed",
            "target_id": "UUID of the item to check",
            "field": "field path to compare (e.g. login.password, notes, fields.API_KEY)",
            "candidate_field": "(optional) compare against a different field on candidates",
            "candidate_ids": ["(optional) list of specific item UUIDs to scan"],
            "scan_limit": 100  // optional, max items to scan (1-1000)
          }

    Output: {"status": "success", "duplicate_ids": ["id1", "id2"], "scan_size": N, "total_available": M}

    Examples:
      bw-proxy do find-duplicates '{
        "rationale": "Check if this password is reused",
        "target_id": "abc-123",
        "field": "login.password"
      }'

      bw-proxy do find-duplicates /tmp/dup_scan.json
    """
    try:
        id_to_name = {}
        target_item = None
        raw_items = []
        active_session = session_key
        if active_session is not None:
            try:
                raw_items = SecureSubprocessWrapper.execute_json(["list", "items"], active_session)
                target_item = SecureSubprocessWrapper.execute_json(["get", "item", payload.target_id], active_session)
                if target_item:
                    id_to_name[payload.target_id] = target_item.get("name", payload.target_id)
            except Exception:
                pass

        approval = HITLManager.authorize_duplicate_scan(
            payload,
            id_to_name,
            needs_password=active_session is None,
        )
        if not approval.get("approved"):
            return _aborted("Operation aborted by user.")

        active_session = _resolve_context_session(
            execution_context,
            password_from_review=approval.get("password"),
            sync_after_unlock=True,
        ) or active_session
        recovery_msg = _maybe_run_recovery(active_session)
        if recovery_msg:
            return recovery_msg
        if not raw_items:
            raw_items = SecureSubprocessWrapper.execute_json(["list", "items"], active_session)

        candidates = payload.candidate_ids
        total_found = 0
        if not candidates:
            if not target_item:
                 target_item = SecureSubprocessWrapper.execute_json(["get", "item", payload.target_id], active_session)
            
            target_type = target_item.get("type")
            all_potential = [i["id"] for i in raw_items if i.get("type") == target_type and i.get("id") != payload.target_id]
            total_found = len(all_potential)
            
            limit = payload.scan_limit if payload.scan_limit is not None else MAX_AUDIT_SCAN_SIZE
            candidates = all_potential[:limit]
        else:
            total_found = len(candidates)

        matches = SecureSubprocessWrapper.audit_bulk_compare(
            target_id=payload.target_id,
            field_path=payload.field,
            candidate_ids=candidates,
            session_key=active_session,
            candidate_field_path=payload.candidate_field
        )

        return _success(
            "Duplicate scan completed.",
            duplicate_ids=matches,
            scan_size=len(candidates),
            total_available=total_found,
        )

    except Exception as e:
        return _error(f"Proxy Error: {_safe_error_message(e)}")

@requires_authenticated_vault("Batch Duplicate Scan", unlock_deferred=True)
@supports_unlock_lease
@requires_fresh_sync
@autosave_large_result
def find_duplicates_batch(
    payload: FindDuplicatesBatchPayload, 
    session_key: Optional[bytearray] = None, 
    execution_context: Optional[VaultExecutionContext] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Finds duplicates for multiple target items in a single vault sweep.
    More efficient than calling find-item-duplicates repeatedly — uses one
    Master Password prompt and one sync for all targets.

    Args:
        payload: JSON object with the batch scan request. Schema:
          {
            "rationale": "Why this batch scan is needed",
            "targets": [
              {"target_id": "UUID", "field": "login.password", "candidate_field": "(optional)"},
              {"target_id": "UUID", "field": "notes"}
            ],
            "candidate_ids": ["(optional) list of item UUIDs to scan against"],
            "scan_limit": 100  // optional (1-1000)
          }

    Max 10 targets per batch.

    Output: {"status": "success", "results": {"<target_id>": ["dup1", "dup2"]}, "scan_size": N}

    Examples:
      bw-proxy do find-duplicates-batch '{
        "rationale": "Audit top 3 accounts for password reuse",
        "targets": [
          {"target_id": "aaa-111", "field": "login.password"},
          {"target_id": "bbb-222", "field": "login.password"},
          {"target_id": "ccc-333", "field": "login.password"}
        ]
      }'
    """
    try:
        id_to_name = {}
        active_session = session_key
        if active_session is not None:
            try:
                raw_items = SecureSubprocessWrapper.execute_json(["list", "items"], active_session)
                for t in payload.targets:
                    for item in raw_items:
                        if item["id"] == t.target_id:
                            id_to_name[t.target_id] = item["name"]
                            break
            except Exception:
                pass

        approval = HITLManager.authorize_duplicate_scan(
            payload,
            id_to_name,
            needs_password=active_session is None,
        )
        if not approval.get("approved"):
            return _aborted("Operation aborted by user.")

        active_session = _resolve_context_session(
            execution_context,
            password_from_review=approval.get("password"),
            sync_after_unlock=True,
        ) or active_session
        recovery_msg = _maybe_run_recovery(active_session)
        if recovery_msg:
            return recovery_msg

        candidates = payload.candidate_ids
        total_found = 0
        if not candidates:
            raw_items = SecureSubprocessWrapper.execute_json(["list", "items"], active_session)
            all_potential = [i["id"] for i in raw_items]
            total_found = len(all_potential)
            limit = payload.scan_limit if payload.scan_limit is not None else MAX_AUDIT_SCAN_SIZE
            candidates = all_potential[:limit]
        else:
            total_found = len(candidates)

        prep = []
        for t in payload.targets:
            prep.append({
                "target_id": t.target_id,
                "target_path": t.field,
                "candidate_path": t.candidate_field or t.field
            })

        results = SecureSubprocessWrapper.audit_multi_target_compare(
            prep, candidates, active_session
        )

        return _success(
            "Batch duplicate scan completed.",
            results=results,
            scan_size=len(candidates),
            total_available=total_found,
        )
    except Exception as e:
        return _error(f"Proxy Error: {_safe_error_message(e)}")

@requires_authenticated_vault("Global Collision Scan", unlock_deferred=True)
@supports_unlock_lease
@requires_fresh_sync
@autosave_large_result
def find_all_vault_duplicates(
    payload: FindAllDuplicatesPayload, 
    session_key: Optional[bytearray] = None, 
    execution_context: Optional[VaultExecutionContext] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Deep audit: scans the ENTIRE vault for ANY items sharing identical secret values.
    Detects global password reuse, duplicate notes, and identical custom field values.
    This is a computationally expensive operation — use scan_limit to control scope.

    Args:
        payload: JSON object with the global scan request. Schema:
          {
            "rationale": "Why this full vault scan is needed",
            "scan_limit": 200  // optional, max items to include (1-1000, default: 100)
          }

    Output: JSON with collision groups (items sharing the same secret value).

    Examples:
      bw-proxy do find-all-vault-duplicates '{
        "rationale": "Full vault password reuse audit",
        "scan_limit": 500
      }'

      bw-proxy do -o /tmp/collisions.json find-all-vault-duplicates /tmp/global_scan.json
    """
    try:
        active_session = session_key
        approval = HITLManager.authorize_duplicate_scan(
            payload,
            {},
            needs_password=active_session is None,
        )
        if not approval.get("approved"):
             return _aborted("Operation aborted by user.")

        active_session = _resolve_context_session(
            execution_context,
            password_from_review=approval.get("password"),
            sync_after_unlock=True,
        ) or active_session
        recovery_msg = _maybe_run_recovery(active_session)
        if recovery_msg:
            return recovery_msg

        limit = payload.scan_limit if payload.scan_limit is not None else MAX_AUDIT_SCAN_SIZE
        raw_items = SecureSubprocessWrapper.execute_json(["list", "items"], active_session)
        all_ids = [i["id"] for i in raw_items][:limit]

        special_target = [{
            "target_id": "ffffffff-ffff-ffff-ffff-ffffffffffff",
            "target_path": "notes"
        }]
        
        audit_results = SecureSubprocessWrapper.audit_multi_target_compare(
            targets=special_target,
            candidate_ids=all_ids,
            session_key=active_session
        )

        return _success("Global collision scan completed.", results=audit_results)
    except Exception as e:
        return _error(f"Proxy Error: {_safe_error_message(e)}")

@requires_authenticated_vault("Blind Secret Refactor", unlock_deferred=True)
@supports_unlock_lease
@requires_fresh_sync
def refactor_item_secrets(
    rationale: str, 
    operations: List[Dict[str, Any]], 
    execution_context: Optional[VaultExecutionContext] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    BLIND REFACTORING: Safely moves, copies, or deletes secret fields between vault items
    through the ACID transaction engine. The actual secret values are never exposed — the
    proxy handles the transfer internally.

    Args:
        rationale: Human-readable reason for the refactor (shown in approval popup).
        operations: JSON array of refactor operations. Each operation requires:
          {
            "action": "vault_refactor",  // auto-set if omitted
            "refactor_action": "move|copy|delete",
            "source_item_id": "UUID of the source item",
            "scope": "field|user|pass|totp|note",
            "key": "field name or scope key (e.g. 'API_KEY' for scope=field, 'password' for scope=pass)",
            "dest_item_id": "UUID of destination item (required for move/copy)",
            "dest_key": "(optional) destination field name, defaults to same as key"
          }

    Scope values:
      field -> custom fields (key = field name)
      user  -> login.username
      pass  -> login.password
      totp  -> login.totp
      note  -> notes

    Examples:
      bw-proxy do refactor-secrets '{
        "rationale": "Move API key from old to new item",
        "operations": [{
          "refactor_action": "move",
          "source_item_id": "aaa-111",
          "scope": "field",
          "key": "API_KEY",
          "dest_item_id": "bbb-222"
        }]
      }'

      bw-proxy do refactor-secrets '{
        "rationale": "Delete leaked TOTP",
        "operations": [{
          "refactor_action": "delete",
          "source_item_id": "ccc-333",
          "scope": "totp",
          "key": "totp"
        }]
      }'
    """
    from .models import EditAction
    for op in operations:
        if "action" not in op:
            op["action"] = EditAction.REFACTOR
            
    payload = {
        "rationale": rationale,
        "operations": operations
    }
    try:
        return _transaction_result(
            TransactionManager.execute_batch(payload, execution_context=execution_context),
            operation_type="refactor",
        )
    except Exception as e:
        return _error(f"Proxy Error processing refactor: {_safe_error_message(e)}", operation_type="refactor")
