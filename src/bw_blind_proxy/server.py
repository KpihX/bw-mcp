from mcp.server.fastmcp import FastMCP
from typing import Dict, Any, List, Optional

from .config import load_config
from .subprocess_wrapper import SecureSubprocessWrapper, SecureBWError
from .models import BlindItem, BlindFolder, BlindOrganization, BlindOrganizationCollection, TransactionPayload
from .transaction import TransactionManager
from .ui import HITLManager

# Load configuration (cached automatically)
config = load_config()
SERVER_NAME = config.get("proxy", {}).get("name", "BW-Blind-Proxy")

# Initialize Server
mcp = FastMCP(SERVER_NAME)

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
        
        recovery_msg = TransactionManager.check_recovery(session_key)
        if recovery_msg:
            return recovery_msg
            
    except Exception as e:
        return f"Access Denied or Recovery Failed: {str(e)}"
        
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
            raw_orgs = SecureSubprocessWrapper.execute_json(["list", "organizations"], session_key)
            organizations = [BlindOrganization(**o).model_dump(exclude_unset=True) for o in raw_orgs]
            
            raw_cols = SecureSubprocessWrapper.execute_json(["list", "org-collections"], session_key)
            collections = [BlindOrganizationCollection(**c).model_dump(exclude_unset=True) for c in raw_cols]
        
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
        return f"Proxy Internal Error during serialization: {str(e)}"
    finally:
        # Clean session key from memory
        sk_bytes = bytearray(session_key, 'utf-8')
        for i in range(len(sk_bytes)):
            sk_bytes[i] = 0
        del sk_bytes
        del session_key

@mcp.tool()
def propose_vault_transaction(rationale: str, operations: List[Dict[str, Any]]) -> str:
    """
    Propose a batch of modifications to the vault. Very strict schemas apply.
    
    [🛡️ ACID & WAL RESILIENCE]
    The transaction runs locally in RAM via a "Virtual Vault Mode". 
    If validation passes, a Write-Ahead Log is created. 
    Only then is the 'bw' CLI executed. If the proxy process is killed mid-flight, 
    the system auto-recovers natively (LIFO rollback) on the next operation!
    
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
          9. "create_folder" -> Requires: name (str)
          10. "rename_folder" -> Requires: target_id (str), new_name (str)
          11. "delete_folder" -> Requires: target_id (str). WARNING: Destructive.
          12. "restore_folder" -> Requires: target_id (str). Restores from trash.
          
          [EDIT ACTIONS]
          13. "edit_item_login" -> Requires: target_id, and optional 'username' or 'uris'. 
          14. "edit_item_card" -> Requires: target_id, and optional 'cardholderName', 'brand', 'expMonth', 'expYear'. 
          15. "edit_item_identity" -> Requires: target_id, and optional 'title', 'firstName', 'email', 'phone', etc.
          16. "upsert_custom_field" -> Requires: target_id (str), name (str), value (str), type (int: 0 for Text, 2 for Boolean).
          
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
        return f"Proxy Error processing transaction: {str(e)}"

def main():
    """Entry point for the script."""
    mcp.run()

if __name__ == "__main__":
    main()
