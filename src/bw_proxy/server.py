import json
from mcp.server.fastmcp import FastMCP
from typing import Dict, Any, List, Optional, Annotated

from .config import load_config, MAX_BATCH_SIZE, REDACTED_POPULATED
from .models import (
    BatchComparePayload, FindDuplicatesPayload, FindDuplicatesBatchPayload,
    FindAllDuplicatesPayload, TemplateType
)
from . import logic

# Load configuration (cached automatically)
config = load_config()
SERVER_NAME = config.get("proxy", {}).get("name", "BW-Proxy")

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
    return logic.get_vault_map(
        search_items, search_folders, folder_id, collection_id, 
        organization_id, trash_state, include_orgs
    )

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
          16. "vault_refactor" -> Requires: refactor_action ("move", "copy", "delete"), source_item_id, scope ("field", "user", "pass", "totp", "note"), key. Optional: dest_item_id, dest_key.
          
          Note: YOU CANNOT PASS SENSITIVE FIELDS ('password', 'totp', 'number', 'code', 'ssn', 'value' of hidden fields). ATTEMPTING TO DO SO WILL FAIL VALIDATION.
          
    This tool DOES NOT execute immediately. It shows a popup to the user detailing
    the operations. The user must explicitly type their Master Password to approve 
    and execute the batch transaction. Destructive actions trigger RED ALERTS.
    """
    return logic.propose_vault_transaction(rationale, operations)

@mcp.tool()
def get_proxy_audit_context(limit: int = 5) -> str:
    """
    Returns the current operational status of the BW-Proxy.
    Use this to check for 'Write-Ahead Log' (WAL) orphans and recent log history.
    """
    return logic.get_proxy_audit_context(limit)

@mcp.tool()
def inspect_transaction_log(tx_id: str = None, n: int = None) -> str:
    """
    Fetches the COMPLETE detailed JSON payload of a specific transaction log.
    If a transaction failed or rolled back, use this to read the `execution_trace`,
    `rollback_trace`, and `error_message` to understand what went wrong.
    """
    return logic.inspect_transaction_log(tx_id, n)

@mcp.tool()
def compare_secrets_batch(payload: BatchComparePayload) -> str:
    """
    BLIND AUDIT PRIMITIVE: Safely compares secret fields (passwords, TOTPs, URIs, notes)
    between two vault items without EVER exposing the text to you (the LLM).
    Returns highly structured JSON with matching statuses.
    """
    return logic.compare_secrets_batch(payload)

@mcp.tool()
def find_item_duplicates(payload: Annotated[FindDuplicatesPayload, "The duplication scan request."]) -> str:
    """
    Finds items sharing the same secret value as a target item.
    Supports dynamic field pathing (e.g. login.password, notes, fields.API_KEY).
    Self-bypass enabled for scan_limit.
    """
    return logic.find_item_duplicates(payload)

@mcp.tool()
def find_duplicates_batch(payload: FindDuplicatesBatchPayload) -> str:
    """
    Finds duplicates for multiple targets in a single sweep.
    Best for cleaning up the vault without multiple master password prompts.
    """
    return logic.find_duplicates_batch(payload)

@mcp.tool()
def get_template(template_type: TemplateType) -> str:
    """
    Retrieves the pure JSON schema template for a Bitwarden entity type.
    Crucial for autonomous agents needing to understand valid fields before creating/editing items.
    """
    return logic.fetch_template(template_type.value)

@mcp.resource("bw://templates/{template_type}")
def template_resource(template_type: str) -> str:
    """Read a Bitwarden entity template schema (e.g. bw://templates/item.login)"""
    return logic.fetch_template(template_type)

@mcp.tool()
def find_all_vault_duplicates(payload: Annotated[FindAllDuplicatesPayload, "The total vault collision scan request."]) -> str:
    """
    Scans the entire vault for ANY items sharing secret values (passwords, notes, identical custom fields).
    This is a deep audit tool for identifying overall secret reuse patterns.
    """
    return logic.find_all_vault_duplicates(payload)

@mcp.tool()
def refactor_item_secrets(rationale: str, operations: List[Dict[str, Any]]) -> str:
    """
    BLIND REFACTORING: Move, Copy, or Delete secret fields between items securely.
    """
    return logic.refactor_item_secrets(rationale, operations)

def main():
    """Entry point for the script."""
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
