import os
import json
import typer
from rich.console import Console
from rich.table import Table
from rich.json import JSON

from .logger import LOG_DIR, TransactionLogger
from .wal import WALManager
from .models import TransactionStatus
from .scrubber import deep_scrub_payload

app = typer.Typer(help="BW-MCP Management & Audit CLI")
console = Console()

@app.command("logs", help="View the latest transaction logs in a beautifully formatted table.")
def view_logs(n: int = typer.Option(5, help="Number of latest logs to view")):
    summaries = TransactionLogger.get_recent_logs_summary(n)
    
    if not summaries:
        console.print("[yellow]No logs found or directory missing. No transactions have been processed yet.[/yellow]")
        return
        
    table = Table(title=f"Last {len(summaries)} Transactions (Anti-Gravity Vault Audit)", show_lines=True)
    table.add_column("Timestamp", style="cyan", no_wrap=True)
    table.add_column("Transaction ID", style="magenta")
    table.add_column("Status", style="bold")
    table.add_column("Rationale", style="white")
    
    for summary in summaries:
        tx_id = summary.get("transaction_id", "")
        ts = summary.get("timestamp", "")
        status = summary.get("status", "")
        rat_str = summary.get("rationale", "")
            
        stat_color = "green"
        if status == TransactionStatus.CRASH_RECOVERED_ON_BOOT:
            stat_color = "yellow"
        elif status in [TransactionStatus.ROLLBACK_TRIGGERED, TransactionStatus.ROLLBACK_SUCCESS, TransactionStatus.ROLLBACK_FAILED, TransactionStatus.ABORTED]:
            stat_color = "red"
            
        status_f = f"[{stat_color}]{status}[/{stat_color}]"
        
        table.add_row(ts, tx_id, status_f, rat_str)
            
    console.print(table)

@app.command("log", help="View the full details of a specific transaction log. Default: shows the most recent log.")
def view_log(
    tx_id: str = typer.Argument(None, help="The Transaction ID (or a unique prefix of it)"),
    n: int = typer.Option(None, "--last", "-n", help="Fetch the N-th most recent log (1 = newest)")
):
    try:
        log_data = TransactionLogger.get_log_details(tx_id=tx_id, n=n)
        
        # We don't have the original filename cleanly here without altering the return signature,
        # but the JSON has the transaction_id and timestamp which is what matters for display.
        target_display = tx_id if tx_id else (f"index {n}" if n else "most recent")
        console.print(f"[cyan bold]Log File Data for: {target_display}[/cyan bold]")
        console.print(JSON(json.dumps(log_data)))
        
    except ValueError as e:
        console.print(f"[red]{type(e).__name__}: {str(e)}[/red]")
    except Exception as e:
        console.print(f"[red]Error reading log: {type(e).__name__}[/red]")

@app.command("wal", help="Inspect the Write-Ahead Log for any stranded transactions.")
def view_wal():
    if WALManager.has_pending_transaction():
        # Typer prompt inherently returns an immutable string.
        # We cast immediately to a bytearray so downstream functions can wipe it.
        mp_str = typer.prompt("Enter Master Password to decrypt WAL", hide_input=True)
        master_password = bytearray(mp_str, "utf-8")
        # Overwrite the original string reference in python's namespace
        mp_str = "DEADBEEF" * 10
        del mp_str
        
        try:
            wal_data = WALManager.read_wal(master_password)
            if not wal_data:
                console.print(f"[red]Failed to read or decrypt the WAL file.[/red]")
                return
            
            console.print(f"[red bold]CRITICAL: Uncommitted transaction found in WAL![/red bold]")
            console.print(f"Transaction ID: {wal_data.get('transaction_id')}")
            console.print(f"Pending Rollback Commands stack size: {len(wal_data.get('rollback_commands', []))}")
            console.print("\n[cyan]Full WAL state (secrets scrubbed):[/cyan]")
            console.print(JSON(json.dumps(deep_scrub_payload(wal_data))))
            console.print("\nThe proxy will automatically resolve this upon the next MCP execution.")
            
        except ValueError as e:
            console.print(f"[red bold]Decryption Failed: Incorrect Master Password or corrupted WAL.[/red bold]")
        finally:
            for i in range(len(master_password)):
                master_password[i] = 0
            del master_password
    else:
        console.print("[green]WAL is clean. No stranded transactions. Vault is perfectly synced.[/green]")

@app.command("purge", help="Delete old transaction logs, keeping only the N most recent ones.")
def purge_logs(keep: int = typer.Option(10, help="Number of latest logs to keep")):
    if not os.path.exists(LOG_DIR):
        console.print("[yellow]No logs directory found. Nothing to purge.[/yellow]")
        return
        
    files = [f for f in os.listdir(LOG_DIR) if f.endswith(".json")]
    if not files:
        console.print("[yellow]No logs found. Nothing to purge.[/yellow]")
        return
        
    if len(files) <= keep:
        console.print(f"[green]Only {len(files)} logs exist, which is <= the keep limit of {keep}. No action taken.[/green]")
        return
        
    # Sort by descending order (newest first)
    files.sort(reverse=True)
    
    # Files to delete are everything after the 'keep' limit
    files_to_delete = files[keep:]
    
    deleted_count = 0
    for filename in files_to_delete:
        filepath = os.path.join(LOG_DIR, filename)
        try:
            os.remove(filepath)
            deleted_count += 1
        except Exception as e:
            console.print(f"[red]Error deleting log {filename}: {str(e)}[/red]")
            
    console.print(f"[green]Successfully purged {deleted_count} old log files. Kept the most recent {keep}.[/green]")

if __name__ == "__main__":
    app()
