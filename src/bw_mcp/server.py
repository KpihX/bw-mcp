import json

from mcp.server.fastmcp import FastMCP
from typing import Dict, Any, List, Optional

from .config import load_config, MAX_BATCH_SIZE, REDACTED_POPULATED
from .subprocess_wrapper import SecureSubprocessWrapper, SecureBWError, SecureProxyError, _safe_error_message
from .models import BlindItem, BlindFolder, BlindOrganization, BlindOrganizationCollection, TransactionPayload
from .transaction import TransactionManager
from .logger import TransactionLogger
from .wal import WALManager
from .ui import HITLManager

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
    try:
        master_password = HITLManager.ask_master_password(title="Proxy Request: Read Vault Map")
        session_key = SecureSubprocessWrapper.unlock_vault(master_password)
        
        recovery_msg = TransactionManager.check_recovery(master_password, session_key)
        if recovery_msg:
            return recovery_msg
            
    except Exception as e:
        return f"Access Denied or Recovery Failed: {_safe_error_message(e)}"
        
    try:
        items_base_args = ["list", "items"]
        if search_items: items_base_args.extend(["--search", search_items])
        if folder_id: items_base_args.extend(["--folderid", folder_id])
        if collection_id: items_base_args.extend(["--collectionid", collection_id])
        if organization_id: items_base_args.extend(["--organizationid", organization_id])
        
        folders_base_args = ["list", "folders"]
        if search_folders: folders_base_args.extend(["--search", search_folders])
        
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
        import json
        return json.dumps(result, indent=2)
        
    except SecureBWError as e:
        return f"Bitwarden CLI Error: {str(e)}"
    except Exception as e:
        return f"Proxy Internal Error during serialization: {_safe_error_message(e)}"
    finally:
        # Clean session key and master password from memory securely
        if 'session_key' in locals():
            for i in range(len(session_key)):
                session_key[i] = 0
            del session_key
        if 'master_password' in locals():
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

def main():
    """Entry point for the script."""
    mcp.run()

if __name__ == "__main__":
    main()
