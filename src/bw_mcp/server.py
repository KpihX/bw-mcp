import json

from mcp.server.fastmcp import FastMCP
from typing import Dict, Any, List, Optional, Annotated

from .config import load_config, MAX_BATCH_SIZE, REDACTED_POPULATED, AUDIT_MATCH_TAG, AUDIT_MISMATCH_TAG, MAX_AUDIT_SCAN_SIZE
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

# Load configuration (cached automatically)
config = load_config()
SERVER_NAME = config.get("proxy", {}).get("name", "BW-MCP")

# Initialize Server with a system meta-prompt for immediate context & zero-latency alignment
mcp = FastMCP(
    SERVER_NAME,
    instructions=f"""
You are a Bitwarden Agent operating through a SECURE BLIND PROXY (Zero Trust). 
**CRITICAL OPERATIONAL RULES:**
1. AI-BLIND: Secrets are REDACTED as '{REDACTED_POPULATED}'. Do NOT attempt to read or modify them.
2. BATCH LIMIT: Strictly limited to {MAX_BATCH_SIZE} operations per transaction to minimize race conditions.
3. ACID ENGINE: Every transaction is Atomic (All-or-Nothing) and backed by a Write-Ahead Log (WAL).
4. HUMAN-IN-THE-LOOP: provide a clear 'rationale' for every proposal to convince the human to approve.
5. SELF-AUDIT: If a transaction crashes, use 'get_proxy_audit_context' and 'inspect_transaction_log' to diagnose and propose manual recovery steps.
6. AUTO-SYNC: The proxy automatically and securely forces a 'bw sync' before ANY transaction or vault map retrieval to guarantee 100% data integrity. You never need to call sync yourself.
"""
)

@mcp.tool()
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
    Supports advanced filtering (search_items, search_folders, folder_id, collection_id, organization_id) 
    and a tri-state filter for the trash (trash_state="none", "only", or "all").
    The agent CANNOT see passwords, TOTP tokens, or secure notes.
    This action requires the Master Password once to unlock the vault temporarily.
    """
    master_password = None
    session_key = None
    try:
        try:
            master_password = HITLManager.ask_master_password(title="Proxy Request: Read Vault Map")
            session_key = SecureSubprocessWrapper.unlock_vault(master_password)
            
            recovery_msg = TransactionManager.check_recovery(master_password, session_key)
            if recovery_msg:
                return recovery_msg
                
        except Exception as e:
            return f"Access Denied or Recovery Failed: {_safe_error_message(e)}"
            
        items_base_args = ["list", "items"]
        if search_items: 
            # DoS Prevention: Limit search string length
            search_items = search_items[:256]
            items_base_args.extend(["--search", search_items])
        if folder_id: items_base_args.extend(["--folderid", folder_id])
        if collection_id: items_base_args.extend(["--collectionid", collection_id])
        if organization_id: items_base_args.extend(["--organizationid", organization_id])
        
        folders_base_args = ["list", "folders"]
        if search_folders:
            # DoS Prevention: Limit search string length
            search_folders = search_folders[:256]
            folders_base_args.extend(["--search", search_folders])
        
        folders = []
        items = []
        trash_items = []
        trash_folders = []
        organizations = []
        collections = []

        if trash_state in ["none", "all"]:
            # Fetch Active (Not deleted)
            raw_items = SecureSubprocessWrapper.execute_json(items_base_args, session_key)
            items = [BlindItem(**i).model_dump(exclude_unset=True) for i in raw_items]
            
            raw_folders = SecureSubprocessWrapper.execute_json(folders_base_args, session_key)
            folders = [BlindFolder(**f).model_dump(exclude_unset=True) for f in raw_folders]
            
        if trash_state in ["only", "all"]:
            # Fetch Deleted (Trash) using the same filters
            trash_items_args = items_base_args + ["--trash"]
            raw_trash_items = SecureSubprocessWrapper.execute_json(trash_items_args, session_key)
            trash_items = [BlindItem(**i).model_dump(exclude_unset=True) for i in raw_trash_items]
            
            trash_folders_args = folders_base_args + ["--trash"]
            raw_trash_folders = SecureSubprocessWrapper.execute_json(trash_folders_args, session_key)
            trash_folders = [BlindFolder(**f).model_dump(exclude_unset=True) for f in raw_trash_folders]
        
        if include_orgs:
            try:
                # Organizations can fail if user doesn't belong to any or if CLI returns error
                raw_orgs = SecureSubprocessWrapper.execute_json(["list", "organizations"], session_key)
                organizations = [BlindOrganization(**o).model_dump(exclude_unset=True) for o in raw_orgs]
                
                raw_cols = SecureSubprocessWrapper.execute_json(["list", "org-collections"], session_key)
                collections = [BlindOrganizationCollection(**c).model_dump(exclude_unset=True) for c in raw_cols]
            except Exception:
                # Silently ignore org failures to allow personal vault access
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
        
        # For simplicity in MCP text context
        return json.dumps(result, indent=2)
        
    except SecureBWError as e:
        return f"Bitwarden CLI Error: {str(e)}"
    except Exception as e:
        return f"Proxy Internal Error during serialization: {_safe_error_message(e)}"
    finally:
        # Clean session key and master password from memory securely
        if session_key is not None:
            for i in range(len(session_key)):
                session_key[i] = 0
            del session_key
        if master_password is not None:
            for i in range(len(master_password)):
                master_password[i] = 0
            del master_password

@mcp.tool()
def propose_vault_transaction(rationale: str, operations: List[Dict[str, Any]]) -> str:
    """
    Propose a batch of modifications to the vault. Very strict schemas apply.
    
    [🛡️ ACID & WAL RESILIENCE]
    The transaction runs locally in RAM via a "Virtual Vault Mode". 
    If validation passes, a Write-Ahead Log is created. 
    Only then is the 'bw' CLI executed. If the proxy process is killed mid-flight, 
    the system auto-recovers natively (LIFO rollback) on the next operation!
    
    [🔢 BATCH LIMITS]
    Strictly follow the batch size limits defined in your system instructions. 
    Reason: Every operation in a batch extends the time window during which an external Bitwarden client
    (mobile app, web vault) could modify the same items. The longer the window, the higher the probability
    that a rollback command will fail with 'Item not found', leaving the vault in an inconsistent state.
    If you need more operations, split them into sequential calls to this tool.
    
    The payload must be a JSON object containing:
      - "rationale": A string explaining why these changes are being made.
      - "operations": A list of operation objects. Each object MUST have an "action" field matching ONE of:
      
          [ITEM ACTIONS]
          1. "create_item" -> Requires: type (1-4), name. Optional: folder_id, organization_id, login, card, identity. SECRETS FORBIDDEN.
          2. "rename_item" -> Requires: target_id (str), new_name (str)
          3. "move_item" -> Requires: target_id (str), folder_id (str or null)
          4. "delete_item" -> Requires: target_id (str). WARNING: Destructive.
          5. "restore_item" -> Requires: target_id (str). Restores from trash.
          6. "favorite_item" -> Requires: target_id (str), favorite (bool)
          7. "move_to_collection" -> Requires: target_id (str), organization_id (str).
          8. "toggle_reprompt" -> Requires: target_id (str), reprompt (bool).
          9. "delete_attachment" -> Requires: target_id (str), attachment_id (str). 
             WARNING: Destructive & UNRECOVERABLE. MUST be the ONLY operation in the batch.
          
          [FOLDER ACTIONS]
          Note: Bitwarden folders are flat. They act like mutually exclusive tags (an item can only be in one folder). You CANNOT place a folder inside another folder. Therefore, folders cannot be "moved" or "restored" from trash, only created, renamed, or deleted.
          9.  "create_folder" -> Requires: name (str)
          10. "rename_folder" -> Requires: target_id (str), new_name (str)
          11. "delete_folder" -> Requires: target_id (str).
              WARNING: DISRUPTIVE & MUST be the ONLY operation in a batch of size 1.
              Bitwarden folders have NO trash. Deleting a folder is a hard delete.
              All items inside will lose their folder reference (become un-foldered).
              This action CANNOT be bundled with any other operation.
          
          [EDIT ACTIONS]
          12. "edit_item_login" -> Requires: target_id, and optional 'username' or 'uris'. 
          13. "edit_item_card" -> Requires: target_id, and optional 'cardholderName', 'brand', 'expMonth', 'expYear'. 
          14. "edit_item_identity" -> Requires: target_id, and optional 'title', 'firstName', 'email', 'phone', etc.
          15. "upsert_custom_field" -> Requires: target_id (str), name (str), value (str), type (int: 0 for Text, 2 for Boolean).
          
          Note: YOU CANNOT PASS SENSITIVE FIELDS ('password', 'totp', 'number', 'code', 'ssn', 'value' of hidden fields). ATTEMPTING TO DO SO WILL FAIL VALIDATION.
          
    This tool DOES NOT execute immediately. It shows a popup to the user detailing
    the operations. The user must explicitly type their Master Password to approve 
    and execute the batch transaction. Destructive actions trigger RED ALERTS.
    """
    payload = {
        "rationale": rationale,
        "operations": operations
    }
    try:
        # Pass the raw dictionary to the Transaction Manager
        return TransactionManager.execute_batch(payload)
    except Exception as e:
        return f"Proxy Error processing transaction: {_safe_error_message(e)}"

@mcp.tool()
def get_proxy_audit_context(limit: int = 5) -> str:
    """
    Returns the current operational status of the BW-MCP.
    Use this to check for 'Write-Ahead Log' (WAL) orphans and recent log history.
    
    Call this tool if you encounter a transaction failure or if you 
    need to synchronize your internal state with the system's audit trail.
    """
    
    has_wal = WALManager.has_pending_transaction()
    wal_status_msg = "CLEAN (Vault is synchronized)" if not has_wal else "PENDING (A transaction crashed and is awaiting auto-recovery. Do NOT send new operations yet.)"
    
    recent_logs = TransactionLogger.get_recent_logs_summary(limit)
    
    context = {
        "wal_status": wal_status_msg,
        "max_batch_size": MAX_BATCH_SIZE,
        "recent_transactions": recent_logs
    }
    
    return json.dumps(context, indent=2)

@mcp.tool()
def inspect_transaction_log(tx_id: str = None, n: int = None) -> str:
    """
    Fetches the COMPLETE detailed JSON payload of a specific transaction log.
    If a transaction failed or rolled back, use this to read the `execution_trace`,
    `rollback_trace`, and `error_message` to understand what went wrong.
    
    Args:
        tx_id: The UUID mapping to the transaction (matches by exact string or prefix).
        n: The index of the log to fetch (1 = the absolute most recent log, 2 = the second most recent, etc.).
        
    If BOTH arguments are empty, it defaults to returning the most recent log (n=1).
    """
    
    try:
        log_data = TransactionLogger.get_log_details(tx_id=tx_id, n=n)
        return json.dumps(log_data, indent=2)
    except SecureProxyError as e:
        return f"Error: {_safe_error_message(e)}"
    except Exception as e:
        return f"Unexpected Error reading log: {_safe_error_message(e)}"

@mcp.tool()
def compare_secrets_batch(payload: BatchComparePayload) -> str:
    """
    BLIND AUDIT PRIMITIVE: Safely compares secret fields (passwords, TOTPs, URIs, notes)
    between two vault items without EVER exposing the text to you (the LLM).
    Useful for deduplication audits or confirming successful migrations.
    Returns highly structured JSON with matching statuses.
    """
    master_password = None
    session_key = None
    try:
        # 1. Unlock sequence (Password-First)
        master_password = HITLManager.ask_master_password(title="Unlock Vault for Secret Audit")
        session_key = SecureSubprocessWrapper.unlock_vault(master_password)
        
        # 2. Safety recovery check
        recovery_msg = TransactionManager.check_recovery(master_password, session_key)
        if recovery_msg:
            return recovery_msg

        # 3. Resolve Names for HITL review
        id_to_name = {}
        try:
            raw_items = SecureSubprocessWrapper.execute_json(["list", "items"], session_key)
            for item in raw_items:
                if item.get("id") and item.get("name"):
                    id_to_name[item["id"]] = item["name"]
        except Exception:
            pass
            
        # 4. HITL Review
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
        if session_key is not None:
            for i in range(len(session_key)): session_key[i] = 0
            del session_key
        if master_password is not None:
            for i in range(len(master_password)):
                master_password[i] = 0
            del master_password


def _fetch_template(template_type: str) -> str:
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
        # 1. Unlock sequence (Password-First)
        master_password = HITLManager.ask_master_password(title=f"Unlock Vault for {valid_type.value} schema")
        session_key = SecureSubprocessWrapper.unlock_vault(master_password)
        
        # 2. Safety recovery check
        recovery_msg = TransactionManager.check_recovery(master_password, session_key)
        if recovery_msg:
            return recovery_msg

        template_data = SecureSubprocessWrapper.execute_json(["get", "template", valid_type.value], session_key)
        safe_data = deep_scrub_payload(template_data)
        
        return json.dumps({
            "_metadata": {
                "source": f"bw get template {valid_type.value}",
                "note": "Secret fields have been proactively redacted by BW-MCP to maintain AI-Blindness. Empty fields remain empty."
            },
            "template": safe_data
        }, indent=2)
    except SecureBWError as e:
        return f"Bitwarden CLI Error: {str(e)}"
    except Exception as e:
        return f"Proxy Error: {_safe_error_message(e)}"
    finally:
        if session_key is not None:
            for i in range(len(session_key)): session_key[i] = 0
            del session_key
        if master_password is not None:
            for i in range(len(master_password)):
                master_password[i] = 0
            del master_password

@mcp.tool()
def find_item_duplicates(payload: Annotated[FindDuplicatesPayload, "The duplication scan request."]) -> str:
    """
    Finds items sharing the same secret value as a target item.
    Supports dynamic field pathing (e.g. login.password, notes, fields.API_KEY).
    Self-bypass enabled for scan_limit.
    """
    master_password = None
    session_key = None
    try:
        # 1. Unlock sequence (Password-First)
        master_password = HITLManager.ask_master_password(title="Unlock Vault for Duplicate Scan")
        session_key = SecureSubprocessWrapper.unlock_vault(master_password)

        # 2. Safety recovery check
        recovery_msg = TransactionManager.check_recovery(master_password, session_key)
        if recovery_msg:
            return recovery_msg

        # 3. Resolve target name for HITL review
        id_to_name = {}
        target_item = None
        raw_items = []
        try:
            # 💡 Execution Order: Fetch items list THEN specific item for name resolution
            raw_items = SecureSubprocessWrapper.execute_json(["list", "items"], session_key)
            target_item = SecureSubprocessWrapper.execute_json(["get", "item", payload.target_id], session_key)
            if target_item:
                id_to_name[payload.target_id] = target_item.get("name", payload.target_id)
        except Exception:
            pass

        # 4. Human-in-the-loop review
        if not HITLManager.review_duplicate_scan(payload, id_to_name):
            return json.dumps({"status": "error", "message": "Operation aborted by user."})

        # 5. Candidate Discovery
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

        # 6. Blind Execution
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
        if session_key is not None:
            for i in range(len(session_key)): session_key[i] = 0
            del session_key
        if master_password is not None:
            for i in range(len(master_password)):
                master_password[i] = 0
            del master_password

@mcp.tool()
def find_duplicates_batch(payload: FindDuplicatesBatchPayload) -> str:
    """
    Finds duplicates for multiple targets in a single sweep.
    Best for cleaning up the vault without multiple master password prompts.
    """
    master_password = None
    session_key = None
    try:
        # 1. Unlock sequence (Password-First)
        master_password = HITLManager.ask_master_password(title="Unlock Vault for Duplicate Batch Audit")
        session_key = SecureSubprocessWrapper.unlock_vault(master_password)

        # 2. Safety recovery check
        recovery_msg = TransactionManager.check_recovery(master_password, session_key)
        if recovery_msg:
            return recovery_msg

        # 3. Resolve names for HITL review
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

        # 4. Review Request
        if not HITLManager.review_duplicate_scan(payload, id_to_name):
            return "Operation aborted by user."

        # 5. Candidate Discovery
        candidates = payload.candidate_ids
        total_found = 0
        if not candidates:
            # We fetch once for the whole batch
            raw_items = SecureSubprocessWrapper.execute_json(["list", "items"], session_key)
            all_potential = [i["id"] for i in raw_items]
            total_found = len(all_potential)
            limit = payload.scan_limit if payload.scan_limit is not None else MAX_AUDIT_SCAN_SIZE
            candidates = all_potential[:limit]
        else:
            total_found = len(candidates)

        # 6. Preparation for multi-target scan
        prep = []
        for t in payload.targets:
            prep.append({
                "target_id": t.target_id,
                "target_path": t.field,
                "candidate_path": t.candidate_field or t.field
            })

        # 7. Execute Multi-Audit
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
        if session_key is not None:
            for i in range(len(session_key)): session_key[i] = 0
            del session_key
        if master_password is not None:
            for i in range(len(master_password)):
                master_password[i] = 0
            del master_password

@mcp.tool()
def get_template(template_type: TemplateType) -> str:
    """
    Retrieves the pure JSON schema template for a Bitwarden entity type.
    Crucial for autonomous agents needing to understand valid fields before creating/editing items.
    """
    return _fetch_template(template_type.value)

@mcp.resource("bw://templates/{template_type}")
def template_resource(template_type: str) -> str:
    """Read a Bitwarden entity template schema (e.g. bw://templates/item.login)"""
    return _fetch_template(template_type)

@mcp.tool()
def find_all_vault_duplicates(payload: Annotated[FindAllDuplicatesPayload, "The total vault collision scan request."]) -> str:
    """
    Scans the entire vault for ANY items sharing secret values (passwords, notes, identical custom fields).
    This is a deep audit tool for identifying overall secret reuse patterns.
    """
    master_password = None
    session_key = None
    try:
        # 1. Unlock sequence (Password-First)
        master_password = HITLManager.ask_master_password(title="Unlock Vault for Global Collision Scan")
        session_key = SecureSubprocessWrapper.unlock_vault(master_password)

        # 2. Safety recovery check
        recovery_msg = TransactionManager.check_recovery(master_password, session_key)
        if recovery_msg:
            return recovery_msg

        # 3. Target discovery (all items)
        limit = payload.scan_limit if payload.scan_limit is not None else MAX_AUDIT_SCAN_SIZE
        raw_items = SecureSubprocessWrapper.execute_json(["list", "items"], session_key)
        all_ids = [i["id"] for i in raw_items][:limit]

        # 4. Human-in-the-loop review
        if not HITLManager.review_duplicate_scan(payload, {}):
             return json.dumps({"status": "error", "message": "Operation aborted by user."})

        # 5. Blind Execution (Special Trigger)
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
        if session_key is not None:
            for i in range(len(session_key)): session_key[i] = 0
            del session_key
        if master_password is not None:
            for i in range(len(master_password)):
                master_password[i] = 0
            del master_password

def main():
    """Entry point for the script."""
    mcp.run()

if __name__ == "__main__":
    main()
