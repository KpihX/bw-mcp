import json
from typing import Dict, Any, List, Optional, Annotated

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
from .session import SessionManager
from .scrubber import deep_scrub_payload
from .config import STATE_DIR
import os

def _get_credentials(title: str) -> tuple[Optional[bytearray], Optional[bytearray]]:
    """
    Returns a fresh (master_password, session_key) pair for one operation.
    No session key is loaded from disk or accepted from the parent environment.
    """
    # 1. ENSURE SERVER URL IS CORRECT
    target_url = os.environ.get("BW_URL")
    if target_url:
        try:
            current_url = SecureSubprocessWrapper.get_server()
            # Basic normalization for comparison
            if target_url.rstrip("/") not in current_url:
                SecureSubprocessWrapper.set_server(target_url)
        except Exception:
            # If get_server fails (empty config), just set it
            SecureSubprocessWrapper.set_server(target_url)
    else:
        # If no session and no URL, we might need to ask for URL if it's the first time
        try:
            if not SecureSubprocessWrapper.get_server():
                url = HITLManager.ask_input("Bitwarden Server URL", "Initial Setup: URL", password=False)
                if url:
                    SecureSubprocessWrapper.set_server(url)
                    os.environ["BW_URL"] = url
        except Exception:
             pass

    # 2. DISCOVERY / LOGIN FLOW
    email = os.environ.get("BW_EMAIL")
    
    if not email:
        email = HITLManager.ask_input("Bitwarden Email", "Authentication Required", password=False)
        if email: os.environ["BW_EMAIL"] = email
    
    master_password = HITLManager.ask_master_password(title=title)
        
    if not email or not master_password:
        raise SecureProxyError("Authentication cancelled or missing required info (Email/Password).")
        
    try:
        # Try login
        session_key = SecureSubprocessWrapper.login_vault(email, master_password)
        return master_password, session_key
    except Exception as e:
        # If login fails because we are already logged in but locked, try unlock
        try:
            session_key = SecureSubprocessWrapper.unlock_vault(master_password)
            return master_password, session_key
        except Exception:
            raise SecureBWError(f"Authentication Failed: {str(e)}")

def _wipe_credentials(mp: Optional[bytearray], sk: Optional[bytearray]):
    """Memory-safe wiping of sensitive bytearrays."""
    if sk is not None:
        for i in range(len(sk)): sk[i] = 0
    if mp is not None:
        for i in range(len(mp)): mp[i] = 0

def login(email: str) -> str:
    """Manual login entrypoint."""
    try:
        mp = HITLManager.ask_master_password(title=f"Login: {email}")
        if mp:
            sk = SecureSubprocessWrapper.login_vault(email, mp)
            _wipe_credentials(mp, sk)
            return "SUCCESS: Logged in. Session key was not persisted; future operations will request the Master Password again."
        return "Error: Password cancelled."
    except Exception as e:
        return _safe_error_message(e)

def setup_automated() -> str:
    """
    Step-by-step automated setup and authentication.
    Follows: URL -> EMAIL -> PASSWORD -> LOGIN/UNLOCK.
    The resulting session key is validated, wiped, and never persisted.
    """
    try:
        # 1. URL Discovery
        url = os.environ.get("BW_URL")
        if not url:
            try:
                # Only ask if not already set or purposefully changing
                if not SecureSubprocessWrapper.get_server():
                    url = HITLManager.ask_input("Bitwarden Server URL", "Setup: 1/3 Server URL", password=False)
            except Exception:
                url = HITLManager.ask_input("Bitwarden Server URL", "Setup: 1/3 Server URL", password=False)
            
            if url: os.environ["BW_URL"] = url
        
        if url:
            try:
                current = SecureSubprocessWrapper.get_server()
                if url.rstrip("/") not in current:
                    SecureSubprocessWrapper.set_server(url)
            except SecureBWError as e:
                # If we get "Logout required", it means a session is active.
                # We can't change the server now, but we can proceed if the session works.
                if "Logout required" in str(e):
                    pass 
                else:
                    raise e
            except Exception:
                # Fallback to attempt set if get failed
                SecureSubprocessWrapper.set_server(url)
            # Verify it worked
            actual = SecureSubprocessWrapper.get_server()
            # Loose match to handle https:// vs vault.
            if url.split("//")[-1].rstrip("/") not in actual:
                return f"Error: Failed to set server to {url}. Current: {actual}."

        # 2. Email Discovery
        email = os.environ.get("BW_EMAIL")
        if not email:
            email = HITLManager.ask_input("Bitwarden Account Email", "Setup: 2/3 Account Email", password=False)
            if email: os.environ["BW_EMAIL"] = email
        
        if not email:
            return "Error: Email is required for setup."

        # 3. Password / Login Discovery
        mp = HITLManager.ask_master_password(title="Setup: 3/3 Master Password")
        
        if not mp:
            return "Error: Master Password is required for setup."

        # 4. Auth Execution
        try:
            # Try login first
            sk = SecureSubprocessWrapper.login_vault(email, mp)
            # NEVER save_session(sk)
            _wipe_credentials(mp, sk)
            return json.dumps({
                "status": "success", 
                "message": f"Setup complete. Logged in as {email}."
            })
        except Exception:
            # Maybe already logged in? Try unlock
            try:
                sk = SecureSubprocessWrapper.unlock_vault(mp)
                # NEVER save_session(sk)
                _wipe_credentials(mp, sk)
                return json.dumps({
                    "status": "success",
                    "message": f"Setup complete. Vault unlocked for {email}."
                })
            except Exception as e:
                 _wipe_credentials(mp, None)
                 return f"Error during setup authentication: {str(e)}"

    except Exception as e:
        return _safe_error_message(e)

def logout() -> str:
    """
    Logout and clear session.
    """
    try:
        # CLEAR PERSISTENCE
        SessionManager.clear_session()
        
        res = SecureSubprocessWrapper.logout_vault()
        return json.dumps({"status": "success", "message": res}, indent=2)
    except Exception as e:
        return f"Logout Failed: {_safe_error_message(e)}"

def get_vault_map(
    search_items: Optional[str] = None,
    search_folders: Optional[str] = None,
    folder_id: Optional[str] = None,
    collection_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    trash_state: str = "all",
    include_orgs: bool = True
) -> str:
    """
    Retrieves the vault (Items and Folders) in a strictly sanitized format.
    """
    master_password = None
    session_key = None
    try:
        try:
            master_password, session_key = _get_credentials("Proxy Request: Read Vault Map")
            
            if master_password:
                recovery_msg = TransactionManager.check_recovery(master_password, session_key)
                if recovery_msg:
                    return recovery_msg
                
        except Exception as e:
            return f"Access Denied or Recovery Failed: {_safe_error_message(e)}"
            
        items_base_args = ["list", "items"]
        if search_items: 
            search_items = search_items[:256]
            items_base_args.extend(["--search", search_items])
        if folder_id: items_base_args.extend(["--folderid", folder_id])
        if collection_id: items_base_args.extend(["--collectionid", collection_id])
        if organization_id: items_base_args.extend(["--organizationid", organization_id])
        
        folders_base_args = ["list", "folders"]
        if search_folders:
            search_folders = search_folders[:256]
            folders_base_args.extend(["--search", search_folders])
        
        folders = []
        items = []
        trash_items = []
        trash_folders = []
        organizations = []
        collections = []

        if trash_state in ["none", "all"]:
            raw_items = SecureSubprocessWrapper.execute_json(items_base_args, session_key)
            items = [BlindItem(**i).model_dump(exclude_unset=True) for i in raw_items]
            
            raw_folders = SecureSubprocessWrapper.execute_json(folders_base_args, session_key)
            folders = [BlindFolder(**f).model_dump(exclude_unset=True) for f in raw_folders]
            
        if trash_state in ["only", "all"]:
            trash_items_args = items_base_args + ["--trash"]
            raw_trash_items = SecureSubprocessWrapper.execute_json(trash_items_args, session_key)
            trash_items = [BlindItem(**i).model_dump(exclude_unset=True) for i in raw_trash_items]
            
            trash_folders_args = folders_base_args + ["--trash"]
            raw_trash_folders = SecureSubprocessWrapper.execute_json(trash_folders_args, session_key)
            trash_folders = [BlindFolder(**f).model_dump(exclude_unset=True) for f in raw_trash_folders]
        
        if include_orgs:
            try:
                raw_orgs = SecureSubprocessWrapper.execute_json(["list", "organizations"], session_key)
                organizations = [BlindOrganization(**o).model_dump(exclude_unset=True) for o in raw_orgs]
                
                raw_cols = SecureSubprocessWrapper.execute_json(["list", "org-collections"], session_key)
                collections = [BlindOrganizationCollection(**c).model_dump(exclude_unset=True) for c in raw_cols]
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
        
        return json.dumps(result, indent=2)
        
    except SecureBWError as e:
        return f"Bitwarden CLI Error: {str(e)}"
    except Exception as e:
        return f"Proxy Internal Error during serialization: {_safe_error_message(e)}"
    finally:
        if session_key is not None:
            for i in range(len(session_key)): session_key[i] = 0
            del session_key
        if master_password is not None:
            for i in range(len(master_password)): master_password[i] = 0
            del master_password

def propose_vault_transaction(rationale: str, operations: List[Dict[str, Any]]) -> str:
    """
    Propose a batch of modifications to the vault.
    """
    payload = {
        "rationale": rationale,
        "operations": operations
    }
    try:
        return TransactionManager.execute_batch(payload)
    except Exception as e:
        return f"Proxy Error processing transaction: {_safe_error_message(e)}"

def get_proxy_audit_context(limit: int = 5) -> str:
    """
    Returns the current operational status of the BW-Proxy.
    """
    has_wal = WALManager.has_pending_transaction()
    wal_status_msg = "CLEAN (Vault is synchronized)" if not has_wal else "PENDING (A transaction crashed and is awaiting auto-recovery.)"
    
    recent_logs = TransactionLogger.get_recent_logs_summary(limit)
    
    context = {
        "wal_status": wal_status_msg,
        "max_batch_size": MAX_BATCH_SIZE,
        "recent_transactions": recent_logs
    }
    
    return json.dumps(context, indent=2)

def inspect_transaction_log(tx_id: str = None, n: int = None) -> str:
    """
    Fetches the COMPLETE detailed JSON payload of a specific transaction log.
    """
    try:
        log_data = TransactionLogger.get_log_details(tx_id=tx_id, n=n)
        return json.dumps(log_data, indent=2)
    except SecureProxyError as e:
        return f"Error: {_safe_error_message(e)}"
    except Exception as e:
        return f"Unexpected Error reading log: {_safe_error_message(e)}"

def compare_secrets_batch(payload: BatchComparePayload) -> str:
    """
    BLIND AUDIT PRIMITIVE: Safely compares secret fields.
    """
    master_password = None
    session_key = None
    try:
        master_password, session_key = _get_credentials("Unlock Vault for Secret Audit")
        
        recovery_msg = TransactionManager.check_recovery(master_password, session_key)
        if recovery_msg:
            return recovery_msg

        id_to_name = {}
        try:
            raw_items = SecureSubprocessWrapper.execute_json(["list", "items"], session_key)
            for item in raw_items:
                if item.get("id") and item.get("name"):
                    id_to_name[item["id"]] = item["name"]
        except Exception:
            pass
            
        if not HITLManager.review_comparisons(payload, id_to_name):
            return json.dumps({"status": "ABORTED", "message": "Audit cancelled by user."})
        
        results = []
        for i, req in enumerate(payload.comparisons, 1):
            try:
                is_match = SecureSubprocessWrapper.audit_compare_secrets(
                    req.item_id_a, req.field_a, req.custom_name_a,
                    req.item_id_b, req.field_b, req.custom_name_b,
                    session_key
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

        return json.dumps({"status": "success", "results": results}, indent=2)

    except Exception as e:
        return f"Proxy Error during audit: {_safe_error_message(e)}"
    finally:
        _wipe_credentials(master_password, session_key)

def fetch_template(template_type: str) -> str:
    """
    Fetches the JSON schema for a specific Bitwarden template type.
    """
    try:
        valid_type = TemplateType(template_type)
    except ValueError:
        valid_types = [e.value for e in TemplateType]
        return f"Error: Invalid template type '{template_type}'. Must be one of: {', '.join(valid_types)}"

    master_password = None
    session_key = None
    try:
        master_password, session_key = _get_credentials(f"Unlock Vault for {valid_type.value} schema")
        
        recovery_msg = TransactionManager.check_recovery(master_password, session_key)
        if recovery_msg:
            return recovery_msg

        template_data = SecureSubprocessWrapper.execute_json(["get", "template", valid_type.value], session_key)
        safe_data = deep_scrub_payload(template_data)
        
        return json.dumps({
            "_metadata": {
                "source": f"bw get template {valid_type.value}",
                "note": "Secret fields have been proactively redacted by BW-Proxy to maintain AI-Blindness."
            },
            "template": safe_data
        }, indent=2)
    except SecureBWError as e:
        return f"Bitwarden CLI Error: {str(e)}"
    except Exception as e:
        return f"Proxy Error: {_safe_error_message(e)}"
    finally:
        _wipe_credentials(master_password, session_key)

def find_item_duplicates(payload: Annotated[FindDuplicatesPayload, "The duplication scan request."]) -> str:
    """
    Finds items sharing the same secret value as a target item.
    """
    master_password = None
    session_key = None
    try:
        master_password, session_key = _get_credentials("Unlock Vault for Duplicate Scan")

        recovery_msg = TransactionManager.check_recovery(master_password, session_key)
        if recovery_msg:
            return recovery_msg

        id_to_name = {}
        target_item = None
        raw_items = []
        try:
            raw_items = SecureSubprocessWrapper.execute_json(["list", "items"], session_key)
            target_item = SecureSubprocessWrapper.execute_json(["get", "item", payload.target_id], session_key)
            if target_item:
                id_to_name[payload.target_id] = target_item.get("name", payload.target_id)
        except Exception:
            pass

        if not HITLManager.review_duplicate_scan(payload, id_to_name):
            return json.dumps({"status": "error", "message": "Operation aborted by user."})

        candidates = payload.candidate_ids
        total_found = 0
        if not candidates:
            if not target_item:
                 target_item = SecureSubprocessWrapper.execute_json(["get", "item", payload.target_id], session_key)
            
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
            session_key=session_key,
            candidate_field_path=payload.candidate_field
        )

        return json.dumps({
            "status": "success",
            "duplicate_ids": matches,
            "scan_size": len(candidates),
            "total_available": total_found
        }, indent=2)

    except Exception as e:
        return json.dumps({"status": "error", "message": f"Proxy Error: {_safe_error_message(e)}"})
    finally:
        _wipe_credentials(master_password, session_key)

def find_duplicates_batch(payload: FindDuplicatesBatchPayload) -> str:
    """
    Finds duplicates for multiple targets in a single sweep.
    """
    master_password = None
    session_key = None
    try:
        master_password, session_key = _get_credentials("Unlock Vault for Duplicate Batch Audit")

        recovery_msg = TransactionManager.check_recovery(master_password, session_key)
        if recovery_msg:
            return recovery_msg

        id_to_name = {}
        try:
            raw_items = SecureSubprocessWrapper.execute_json(["list", "items"], session_key)
            for t in payload.targets:
                for item in raw_items:
                    if item["id"] == t.target_id:
                        id_to_name[t.target_id] = item["name"]
                        break
        except Exception:
            pass

        if not HITLManager.review_duplicate_scan(payload, id_to_name):
            return "Operation aborted by user."

        candidates = payload.candidate_ids
        total_found = 0
        if not candidates:
            raw_items = SecureSubprocessWrapper.execute_json(["list", "items"], session_key)
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
            prep, candidates, session_key
        )

        return json.dumps({
            "status": "success",
            "results": results,
            "scan_size": len(candidates),
            "total_available": total_found
        }, indent=2)

    except Exception as e:
        return f"Proxy Error: {_safe_error_message(e)}"
    finally:
        _wipe_credentials(master_password, session_key)

def find_all_vault_duplicates(payload: Annotated[FindAllDuplicatesPayload, "The total vault collision scan request."]) -> str:
    """
    Scans the entire vault for ANY items sharing secret values.
    """
    master_password = None
    session_key = None
    try:
        master_password, session_key = _get_credentials("Unlock Vault for Global Collision Scan")

        recovery_msg = TransactionManager.check_recovery(master_password, session_key)
        if recovery_msg:
            return recovery_msg

        limit = payload.scan_limit if payload.scan_limit is not None else MAX_AUDIT_SCAN_SIZE
        raw_items = SecureSubprocessWrapper.execute_json(["list", "items"], session_key)
        all_ids = [i["id"] for i in raw_items][:limit]

        if not HITLManager.review_duplicate_scan(payload, {}):
             return json.dumps({"status": "error", "message": "Operation aborted by user."})

        special_target = [{
            "target_id": "ffffffff-ffff-ffff-ffff-ffffffffffff",
            "target_path": "notes"
        }]
        
        audit_results = SecureSubprocessWrapper.audit_multi_target_compare(
            targets=special_target,
            candidate_ids=all_ids,
            session_key=session_key
        )

        return json.dumps(audit_results, indent=2)

    except Exception as e:
        return json.dumps({"status": "error", "message": f"Proxy Error: {_safe_error_message(e)}"})
    finally:
        _wipe_credentials(master_password, session_key)

def refactor_item_secrets(rationale: str, operations: List[Dict[str, Any]]) -> str:
    """
    BLIND REFACTORING: Move, Copy, or Delete secret fields between items securely.
    """
    # Ensure all operations have the correct 'action' for Pydantic discriminator
    from .models import EditAction
    for op in operations:
        if "action" not in op:
            op["action"] = EditAction.REFACTOR
            
    payload = {
        "rationale": rationale,
        "operations": operations
    }
    try:
        return TransactionManager.execute_batch(payload)
    except Exception as e:
        return f"Proxy Error processing refactor: {_safe_error_message(e)}"
