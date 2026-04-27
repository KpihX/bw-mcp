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

# ============================================================================
# MCP TOOL REGISTRATION
# All docstrings are read from logic.py (single source of truth).
# server.py is a THIN DELEGATION LAYER — no duplicated documentation.
# ============================================================================

@mcp.tool()
def get_vault_map(
    search_items: Optional[str] = None,
    search_folders: Optional[str] = None,
    folder_id: Optional[str] = None,
    collection_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    trash_state: str = "all",
    include_orgs: bool = True
) -> Dict[str, Any]:
    return logic.get_vault_map(
        search_items, search_folders, folder_id, collection_id, 
        organization_id, trash_state, include_orgs
    )

# Delegate docstring from logic.py
get_vault_map.__doc__ = logic.get_vault_map.__doc__

@mcp.tool()
def propose_vault_transaction(rationale: str, operations: List[Dict[str, Any]]) -> Dict[str, Any]:
    return logic.propose_vault_transaction(rationale, operations)

propose_vault_transaction.__doc__ = logic.propose_vault_transaction.__doc__

@mcp.tool()
def get_proxy_audit_context(limit: int = 5) -> Dict[str, Any]:
    return logic.get_proxy_audit_context(limit)

get_proxy_audit_context.__doc__ = logic.get_proxy_audit_context.__doc__

@mcp.tool()
def inspect_transaction_log(tx_id: str = None, n: int = None) -> Dict[str, Any]:
    return logic.inspect_transaction_log(tx_id, n)

inspect_transaction_log.__doc__ = logic.inspect_transaction_log.__doc__

@mcp.tool()
def compare_secrets_batch(payload: BatchComparePayload) -> Dict[str, Any]:
    return logic.compare_secrets_batch(payload)

compare_secrets_batch.__doc__ = logic.compare_secrets_batch.__doc__

@mcp.tool()
def find_item_duplicates(payload: Annotated[FindDuplicatesPayload, "The duplication scan request."]) -> Dict[str, Any]:
    return logic.find_item_duplicates(payload)

find_item_duplicates.__doc__ = logic.find_item_duplicates.__doc__

@mcp.tool()
def find_duplicates_batch(payload: FindDuplicatesBatchPayload) -> Dict[str, Any]:
    return logic.find_duplicates_batch(payload)

find_duplicates_batch.__doc__ = logic.find_duplicates_batch.__doc__

@mcp.tool()
def get_template(template_type: TemplateType) -> Dict[str, Any]:
    return logic.fetch_template(template_type.value)

get_template.__doc__ = logic.fetch_template.__doc__

@mcp.resource("bw://templates/{template_type}")
def template_resource(template_type: str) -> Dict[str, Any]:
    """Read a Bitwarden entity template schema (e.g. bw://templates/item.login)"""
    return logic.fetch_template(template_type)

@mcp.tool()
def find_all_vault_duplicates(payload: Annotated[FindAllDuplicatesPayload, "The total vault collision scan request."]) -> Dict[str, Any]:
    return logic.find_all_vault_duplicates(payload)

find_all_vault_duplicates.__doc__ = logic.find_all_vault_duplicates.__doc__

@mcp.tool()
def refactor_item_secrets(rationale: str, operations: List[Dict[str, Any]]) -> Dict[str, Any]:
    return logic.refactor_item_secrets(rationale, operations)

refactor_item_secrets.__doc__ = logic.refactor_item_secrets.__doc__

def main():
    """Entry point for the script."""
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
