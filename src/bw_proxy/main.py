import os
import signal
import json
import sys
import typer
from json import JSONDecodeError
from typing import Optional, List, Dict, Any, Annotated
from importlib.metadata import version as pkg_version
from rich.console import Console
from rich.table import Table
from rich.json import JSON

from .daemon import write_pid, read_pid, clear_pid, is_running
from .logger import TransactionLogger, LOG_DIR
from .wal import WALManager
from .models import TransactionStatus, TemplateType, BatchComparePayload, FindDuplicatesPayload, FindDuplicatesBatchPayload, FindAllDuplicatesPayload
from .config import load_config, update_config
from .subprocess_wrapper import _sanitize_args_for_log, SecureProxyError
from . import logic

console = Console()

app = typer.Typer(
    name="bw-proxy",
    help="🔐 Sovereign Hub for Bitwarden — Zero Trust · AI-Blind · ACID",
    no_args_is_help=True,
    add_completion=False,
)

admin_app = typer.Typer(help="Administrative utilities (logs, WAL, config)")
do_app = typer.Typer(help="Directly execute MCP tools (Script Mode)")

app.add_typer(admin_app, name="admin")
app.add_typer(do_app, name="do")

# --- DAEMON COMMANDS ---

@app.command("serve")
def _serve() -> None:
    """Start the BW-Proxy server in stdio MCP mode (blocks until killed)."""
    from .server import main as _server_main
    write_pid(os.getpid())
    try:
        _server_main()
    finally:
        clear_pid()

@app.command("status")
def _status() -> None:
    """Check whether the MCP server process is currently running."""
    pid = read_pid()
    if pid is None:
        console.print("[yellow]⏹  Stopped[/yellow] — no PID file found.")
        raise typer.Exit(1)
    if is_running(pid):
        console.print(f"[green]✅ Running[/green] — PID [bold]{pid}[/bold]")
    else:
        console.print(f"[red]💀 Dead[/red] — PID {pid} not responding. Clearing stale PID file.")
        clear_pid()
        raise typer.Exit(2)

@app.command("stop")
def _stop() -> None:
    """Send SIGTERM to the running server via the PID file."""
    pid = read_pid()
    if pid is None:
        console.print("[yellow]Not running — nothing to stop.[/yellow]")
        return
    if is_running(pid):
        os.kill(pid, signal.SIGTERM)
        clear_pid()
        console.print(f"[green]✅ Stopped[/green] — PID [bold]{pid}[/bold] terminated.")
    else:
        console.print(f"[yellow]Stale PID {pid} detected — cleared.[/yellow]")
        clear_pid()

@app.command("restart")
def _restart() -> None:
    """Stop the running server (MCP clients will auto-respawn it)."""
    pid = read_pid()
    if pid is None or not is_running(pid):
        if pid is not None:
            clear_pid()
        console.print("[yellow]Not running — nothing to restart.[/yellow]")
        return
    os.kill(pid, signal.SIGTERM)
    clear_pid()
    console.print(
        f"[bold cyan]🔄 Restart signal sent[/bold cyan] — PID [bold]{pid}[/bold] stopped.\n"
        "[dim]Your MCP client will auto-respawn the server on the next tool call.[/dim]"
    )

@app.command("version")
def _version() -> None:
    """Display the installed version and exit."""
    v = pkg_version("bw-proxy")
    console.print(f"[bold cyan]BW-Proxy[/bold cyan] v[bold]{v}[/bold] 🔐")

# --- ADMIN COMMANDS (formerly cli.py) ---

log_app = typer.Typer(help="Manage and view transaction logs")
wal_app = typer.Typer(help="Inspect and manage the Write-Ahead Log")
config_app = typer.Typer(help="View or update proxy configuration")

admin_app.add_typer(log_app, name="log")
admin_app.add_typer(wal_app, name="wal")
admin_app.add_typer(config_app, name="config")

@admin_app.command("setup")
def admin_setup():
    """Step-by-step automated setup and authentication discovery."""
    res = logic.setup_automated()
    safe_json_print(res)

@log_app.command("view")
def log_view(
    l: int = typer.Option(5, "-l", "--last", help="Number of latest logs to list in a table"),
    n: int = typer.Option(None, "-n", "--number", help="The N-th most recent log to view in full JSON (1=newest)")
):
    """View transaction logs."""
    if n is not None:
        try:
            log_data = TransactionLogger.get_log_details(n=n)
            console.print(f"[cyan bold]Log File Data for index: {n}[/cyan bold]")
            console.print(JSON(json.dumps(log_data)))
        except Exception as e:
            console.print(f"[red]Error: {str(e)}[/red]")
    else:
        summaries = TransactionLogger.get_recent_logs_summary(l)
        if not summaries:
            console.print("[yellow]Notice: No logs found.[/yellow]")
            return
        table = Table(title=f"Last {len(summaries)} Transactions", show_lines=True)
        table.add_column("Timestamp", style="cyan")
        table.add_column("Transaction ID", style="magenta")
        table.add_column("Status", style="bold")
        table.add_column("Rationale", style="white")
        for s in summaries:
            status = s.get("status", "")
            color = "green" if "SUCCESS" in status else "yellow" if "RECOVERED" in status else "red"
            table.add_row(s.get("timestamp", ""), s.get("transaction_id", ""), f"[{color}]{status}[/{color}]", s.get("rationale", ""))
        console.print(table)

@log_app.command("purge")
def log_purge(keep: int = typer.Option(10, "-k", "--keep", help="Number of latest logs to keep")):
    """Delete old transaction logs."""
    if not os.path.exists(LOG_DIR): return
    files = sorted([f for f in os.listdir(LOG_DIR) if f.endswith(".json")], reverse=True)
    if len(files) <= keep: return
    for f in files[keep:]:
        os.remove(os.path.join(LOG_DIR, f))
    console.print(f"[green]Purged {len(files)-keep} old log files.[/green]")

@wal_app.command("view")
def wal_view():
    """Inspect the Write-Ahead Log."""
    if WALManager.has_pending_transaction():
        mp = typer.prompt("Enter Master Password to decrypt WAL", hide_input=True)
        try:
            wal_data = WALManager.read_wal(bytearray(mp, "utf-8"))
            if not wal_data: return
            console.print("[red bold]Uncommitted transaction found in WAL![/red bold]")
            safe_wal = {
                "transaction_id": wal_data.get("transaction_id"),
                "rollback_commands": [{"cmd": _sanitize_args_for_log(e.get("cmd", []))} for e in wal_data.get("rollback_commands", [])]
            }
            console.print(JSON(json.dumps(safe_wal)))
        except Exception:
            console.print("[red]Decryption Failed.[/red]")
    else:
        console.print("[green]WAL is clean.[/green]")

@config_app.command("get")
def config_get():
    """View current configuration."""
    console.print(JSON(json.dumps(load_config())))

@config_app.command("update")
def config_update(max_batch_size: int = typer.Option(None, "-m", "--max-batch-size")):
    """Update configuration."""
    if max_batch_size:
        update_config({"proxy": {"max_batch_size": max_batch_size}})
        console.print(f"[green]MAX_BATCH_SIZE updated to {max_batch_size}[/green]")

# --- HELPERS ---

def safe_json_print(data: str):
    """Attempt to print as JSON, fallback to raw text if invalid."""
    if not data:
        return
    try:
        # Check if it's valid JSON
        json.loads(data)
        console.print(JSON(data))
    except (JSONDecodeError, TypeError):
        # Not JSON, print as is
        if "Error" in data or "Denied" in data:
            console.print(f"[red]{data}[/red]")
        else:
            console.print(data)

# --- DO COMMANDS (Action Mode) ---

@do_app.command("login")
def do_login(email: Optional[str] = typer.Argument(None, help="Bitwarden Account Email")):
    """Authenticate with Bitwarden (defaults to BW_EMAIL env var)."""
    target_email = email or os.environ.get("BW_EMAIL")
    if not target_email:
        console.print("[red]Error: Email must be provided or set via BW_EMAIL env var.[/red]")
        raise typer.Exit(1)
    res = logic.login(target_email)
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

@do_app.command("get-template")
def do_get_template(type_name: str):
    """Fetch Bitwarden entity template."""
    safe_json_print(logic.fetch_template(type_name))

def main() -> None:
    if len(sys.argv) == 1:
        sys.argv.append("serve")
    app()

if __name__ == "__main__":
    main()
