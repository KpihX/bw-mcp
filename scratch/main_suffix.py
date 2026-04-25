# --- DO COMMANDS (Action Mode) ---

@do_app.command("login")
def do_login(email: str = typer.Argument(..., help="Bitwarden Account Email")):
    """Authenticate with Bitwarden."""
    res = logic.login(email)
    safe_json_print(res)

@do_app.command("logout")
def do_logout():
    """Logout from Bitwarden."""
    res = logic.logout()
    safe_json_print(res)

@do_app.command("get-vault-map")
def do_get_vault_map(
    search_items: Optional[str] = None,
    search_folders: Optional[str] = None,
    folder_id: Optional[str] = None,
    collection_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    trash_state: str = "all",
    include_orgs: bool = True
):
    """Retrieve the vault map (sanitized)."""
    res = logic.get_vault_map(search_items, search_folders, folder_id, collection_id, organization_id, trash_state, include_orgs)
    safe_json_print(res)

@do_app.command("propose-transaction")
def do_propose_transaction(
    rationale: str,
    operations_json: str = typer.Argument(..., help="JSON array of operations")
):
    """Execute a batch transaction via JSON input."""
    try:
        ops = json.loads(operations_json)
        res = logic.propose_vault_transaction(rationale, ops)
        safe_json_print(res)
    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")

@do_app.command("audit-context")
def do_audit_context(limit: int = 5):
    """Status context for BW-Proxy."""
    safe_json_print(logic.get_proxy_audit_context(limit))

@do_app.command("inspect-log")
def do_inspect_log(tx_id: Optional[str] = None, n: Optional[int] = None):
    """View detailed transaction audit log (tx_id or count n)."""
    safe_json_print(logic.inspect_transaction_log(tx_id, n))

@do_app.command("search-items")
def do_search_items(query: str, skip_trash: bool = True):
    """Search for items in the vault."""
    safe_json_print(logic.search_items(query, skip_trash))

@do_app.command("get-item")
def do_get_item(item_id: str):
    """Get full details of a specific item (redacted)."""
    safe_json_print(logic.get_item_details(item_id))

@do_app.command("get-template")
def do_get_template(template_type: str):
    """Fetch a Bitwarden JSON template (cleaned)."""
    safe_json_print(logic.get_bitwarden_template(template_type))

@do_app.command("compare-secrets")
def do_compare_secrets(payload_json: str = typer.Argument(..., help="JSON for BatchComparePayload")):
    """Audit secrets against expected values."""
    try:
        payload = json.loads(payload_json)
        safe_json_print(logic.compare_secrets_batch(payload))
    except Exception as e:
        console.print(f"[red]Error parsing payload: {str(e)}[/red]")

@do_app.command("find-duplicates")
def do_find_duplicates(item_id: str, field_path: str = "login.password"):
    """Search for duplicates of a secret across the vault."""
    safe_json_print(logic.find_item_duplicates(item_id, field_path))

@do_app.command("vault-audit")
def do_vault_audit(field_path: str = "login.password"):
    """Scan the entire vault for secret collisions."""
    safe_json_print(logic.find_all_vault_duplicates(field_path))

@do_app.command("refactor")
def do_refactor(
    rationale: str,
    operations_json: str = typer.Argument(..., help="JSON array of refactor operations")
):
    """Execute blind refactor via JSON input."""
    try:
        ops = json.loads(operations_json)
        res = logic.refactor_item_secrets(rationale, ops)
        safe_json_print(res)
    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")

def main() -> None:
    app()

if __name__ == "__main__":
    main()
