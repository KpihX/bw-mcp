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
from .subprocess_wrapper import SecureProxyError
from .config import load_config, update_config

app = typer.Typer(help="BW-MCP Management & Audit CLI")
log_app = typer.Typer(help="Manage and view transaction logs")
wal_app = typer.Typer(help="Inspect and manage the Write-Ahead Log")

app.add_typer(log_app, name="log")
app.add_typer(wal_app, name="wal")

console = Console()

@log_app.command("view")
def log_view(
    l: int = typer.Option(None, "-l", "--last", help="Number of latest logs to list in a table"),
    n: int = typer.Option(None, "-n", "--number", help="The N-th most recent log to view in full JSON (1=newest)")
):
    """View transaction logs. Use -l to list a table of logs, or -n to view a specific log in full JSON."""
    if l is not None and n is not None:
        console.print("[red]Error: -l and -n are mutually exclusive.[/red]")
        raise typer.Exit(1)
        
    if l is None and n is None:
        l = 5 # default behavior: list 5 logs
        
    if l is not None:
        summaries = TransactionLogger.get_recent_logs_summary(l)
        
        if not summaries:
            console.print("[yellow]Notice: No logs found or directory missing. No transactions have been processed yet.[/yellow]")
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
    else:
        try:
            log_data = TransactionLogger.get_log_details(n=n)
            console.print(f"[cyan bold]Log File Data for index: {n}[/cyan bold]")
            console.print(JSON(json.dumps(log_data)))
            
        except (ValueError, SecureProxyError) as e:
            console.print(f"[red]Error: {str(e)}[/red]")
        except Exception as e:
            console.print(f"[red]Error: Unexpected Error: {type(e).__name__}[/red]")


@log_app.command("purge")
def log_purge(keep: int = typer.Option(10, "-k", "--keep", help="Number of latest logs to keep")):
    """Delete old transaction logs, keeping only the N most recent ones."""
    if not os.path.exists(LOG_DIR):
        console.print("[yellow]Notice: No logs directory found. Nothing to purge.[/yellow]")
        return
        
    files = [f for f in os.listdir(LOG_DIR) if f.endswith(".json")]
    if not files:
        console.print("[yellow]Notice: No logs found. Nothing to purge.[/yellow]")
        return
        
    if len(files) <= keep:
        console.print(f"[green]Success: Only {len(files)} logs exist, which is <= the keep limit of {keep}. No action taken.[/green]")
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
            console.print(f"[red]Error: Failed deleting log {filename}: {str(e)}[/red]")
            
    console.print(f"[green]Success: Purged {deleted_count} old log files. Kept the most recent {keep}.[/green]")


@wal_app.command("view")
def wal_view():
    """Inspect the Write-Ahead Log for any stranded transactions."""
    if WALManager.has_pending_transaction():
        mp_str = typer.prompt("Enter Master Password to decrypt WAL", hide_input=True)
        master_password = bytearray(mp_str, "utf-8")
        mp_str = "DEADBEEF" * 10
        del mp_str
        
        try:
            wal_data = WALManager.read_wal(master_password)
            if not wal_data:
                console.print(f"[red]Error: Failed to read or decrypt the WAL file.[/red]")
                return
            
            console.print(f"[red bold]Alert: Uncommitted transaction found in WAL![/red bold]")
            console.print(f"Transaction ID: {wal_data.get('transaction_id')}")
            console.print(f"Pending Rollback Commands stack size: {len(wal_data.get('rollback_commands', []))}")
            console.print("\n[cyan]Full WAL state (secrets scrubbed):[/cyan]")
            console.print(JSON(json.dumps(deep_scrub_payload(wal_data))))
            console.print("\nThe proxy will automatically resolve this upon the next MCP execution.")
            
        except ValueError as e:
            console.print(f"[red]Error: Decryption Failed. Incorrect Master Password or corrupted WAL.[/red]")
        finally:
            for i in range(len(master_password)):
                master_password[i] = 0
            del master_password
    else:
        console.print("[green]Success: WAL is clean. No stranded transactions. Vault is perfectly synced.[/green]")


@wal_app.command("delete")
def wal_delete():
    """Delete the Write-Ahead Log file permanently (requires Master Password validation)."""
    if WALManager.has_pending_transaction():
        mp_str = typer.prompt("Enter Master Password to authorize WAL deletion", hide_input=True)
        master_password = bytearray(mp_str, "utf-8")
        mp_str = "DEADBEEF" * 10
        del mp_str
        
        try:
            # We read it to validate the password
            wal_data = WALManager.read_wal(master_password)
            if not wal_data:
                console.print(f"[red]Error: Failed to decrypt the WAL file. Deletion aborted.[/red]")
                return
                
            WALManager.clear_wal()
            console.print(f"[green]Success: WAL successfully deleted. Any stranded transactions are now permanently lost.[/green]")
            
        except ValueError as e:
            console.print(f"[red]Error: Authorization Failed. Incorrect Master Password.[/red]")
        finally:
            for i in range(len(master_password)):
                master_password[i] = 0
            del master_password
    else:
        console.print("[green]Success: WAL is already clean. Nothing to delete.[/green]")

@app.command("config")
def config_cmd(
    max_batch_size: int = typer.Option(None, "-m", "--max-batch-size", help="Set the maximum number of operations allowed in a single transaction batch.")
):
    """View or update proxy configuration."""
    if max_batch_size is not None:
        if max_batch_size < 1:
            console.print("[red]Error: max-batch-size must be a positive integer (>= 1).[/red]")
            raise typer.Exit(1)
        
        update_config({"proxy": {"max_batch_size": max_batch_size}})
        console.print(f"[green]Success: Configuration updated. MAX_BATCH_SIZE is now {max_batch_size}.[/green]")
    else:
        # View mode
        conf = load_config()
        console.print("[cyan bold]Current BW-MCP Configuration:[/cyan bold]")
        # Hide internal paths for cleaner output if desired, but here we show everything
        console.print(JSON(json.dumps(conf)))

if __name__ == "__main__":
    app()
