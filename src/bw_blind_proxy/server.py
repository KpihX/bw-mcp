from mcp.server.fastmcp import FastMCP
from typing import Dict, Any, List

from .config import load_config
from .subprocess_wrapper import SecureSubprocessWrapper, SecureBWError
from .models import BlindItem, BlindFolder, TransactionPayload
from .transaction import TransactionManager
from .ui import HITLManager

# Load configuration (cached automatically)
config = load_config()
SERVER_NAME = config.get("proxy", {}).get("name", "BW-Blind-Proxy")

# Initialize Server
mcp = FastMCP(SERVER_NAME)

@mcp.tool()
def get_vault_map() -> str:
    """
    Retrieves the entire vault (Items and Folders) in a strictly sanitized format.
    The agent CANNOT see passwords, TOTP tokens, or secure notes.
    This action requires the Master Password once to unlock the vault temporarily.
    """
    try:
        master_password = HITLManager.ask_master_password(title="Proxy Request: Read Vault Map")
        session_key = SecureSubprocessWrapper.unlock_vault(master_password)
    except Exception as e:
        return f"Access Denied: {str(e)}"
        
    try:
        # Fetch Folders
        raw_folders = SecureSubprocessWrapper.execute_json(["list", "folders"], session_key)
        folders = [BlindFolder(**f).model_dump(exclude_unset=True) for f in raw_folders]
        
        # Fetch Items
        raw_items = SecureSubprocessWrapper.execute_json(["list", "items"], session_key)
        items = [BlindItem(**i).model_dump(exclude_unset=True) for i in raw_items]
        
        result = {
            "status": "success",
            "message": "Vault map successfully retrieved. Sensitive fields are redacted.",
            "data": {
                "folders": folders,
                "items": items
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
def propose_vault_transaction(payload: Dict[str, Any]) -> str:
    """
    Propose a batch of modifications to the vault. Very strict schemas apply.
    
    The payload must be a JSON object containing:
      - "rationale": A string explaining why these changes are being made.
      - "operations": A list of operation objects. Each object MUST have an "action" field matching ONE of:
      
          [ITEM ACTIONS]
          1. "rename_item" -> Requires: target_id (str), new_name (str)
          2. "move_item" -> Requires: target_id (str), folder_id (str or null)
          3. "delete_item" -> Requires: target_id (str). WARNING: Destructive.
          4. "restore_item" -> Requires: target_id (str). Restores from trash.
          5. "favorite_item" -> Requires: target_id (str), favorite (bool)
          6. "move_to_collection" -> Requires: target_id (str), organization_id (str).
          7. "toggle_reprompt" -> Requires: target_id (str), reprompt (bool).
          8. "delete_attachment" -> Requires: target_id (str), attachment_id (str). WARNING: Destructive.
          
          [FOLDER ACTIONS]
          9. "create_folder" -> Requires: name (str)
          10. "rename_folder" -> Requires: target_id (str), new_name (str)
          11. "delete_folder" -> Requires: target_id (str). WARNING: Destructive.
          
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
