import os
import typer
from rich.console import Console
from rich.table import Table

from .logger import LOG_DIR
from .wal import WALManager
from .models import TransactionStatus

app = typer.Typer(help="BW-Blind-Proxy Management & Audit CLI")
console = Console()

@app.command("logs", help="View the latest transaction logs in a beautifully formatted table.")
def view_logs(n: int = typer.Option(5, help="Number of latest logs to view")):
    if not os.path.exists(LOG_DIR):
        console.print("[yellow]No logs directory found. No transactions have been processed yet.[/yellow]")
        return
        
    files = [f for f in os.listdir(LOG_DIR) if f.endswith(".log")]
    if not files:
        console.print("[yellow]No logs found.[/yellow]")
        return
        
    # Sort by descending order (newest first)
    files.sort(reverse=True)
    
    table = Table(title=f"Last {n} Transactions (Anti-Gravity Vault Audit)", show_lines=True)
    table.add_column("Timestamp", style="cyan", no_wrap=True)
    table.add_column("Transaction ID", style="magenta")
    table.add_column("Status", style="bold")
    table.add_column("Rationale", style="white")
    
    count = 0
    for filename in files:
        if count >= n:
            break
            
        filepath = os.path.join(LOG_DIR, filename)
        try:
            with open(filepath, 'r') as f:
                lines = f.readlines()
                
            tx_id = ""
            ts = ""
            status = ""
            rationale = []
            
            parsing_rationale = False
            for line in lines:
                line = line.strip()
                if line.startswith("TRANSACTION ID:"):
                    tx_id = line.split(":", 1)[1].strip()
                elif line.startswith("TIMESTAMP:"):
                    ts = line.split(":", 1)[1].strip()
                elif line.startswith("STATUS:"):
                    status = line.split(":", 1)[1].strip()
                elif line.startswith("RATIONALE:"):
                    parsing_rationale = True
                    continue
                elif line.startswith("OPERATIONS REQUESTED:"):
                    parsing_rationale = False
                    
                if parsing_rationale and not line.startswith("-") and line:
                    rationale.append(line)
                    
            rat_str = " ".join(rationale).strip()
            if len(rat_str) > 75:
                rat_str = rat_str[:72] + "..."
                
            stat_color = "green"
            if status == TransactionStatus.CRASH_RECOVERED_ON_BOOT:
                stat_color = "yellow"
            elif status in [TransactionStatus.ROLLBACK_TRIGGERED, TransactionStatus.ROLLBACK_SUCCESS, TransactionStatus.ROLLBACK_FAILED, TransactionStatus.ABORTED]:
                stat_color = "red"
                
            status_f = f"[{stat_color}]{status}[/{stat_color}]"
            
            table.add_row(ts, tx_id, status_f, rat_str)
            count += 1
        except Exception as e:
            console.print(f"[red]Error reading log {filename}: {str(e)}[/red]")
            
    console.print(table)

@app.command("wal", help="Inspect the Write-Ahead Log for any stranded transactions.")
def view_wal():
    if WALManager.has_pending_transaction():
        data = WALManager.read_wal()
        console.print(f"[red bold]CRITICAL: Uncommitted transaction found in WAL![/red bold]")
        console.print(f"Transaction ID: {data.get('transaction_id')}")
        console.print(f"Pending Rollback Commands stack size: {len(data.get('rollback_commands', []))}")
        console.print("\nThe proxy will automatically resolve this upon the next MCP execution.")
    else:
        console.print("[green]WAL is clean. No stranded transactions. Vault is perfectly synced.[/green]")

@app.command("purge", help="Delete old transaction logs, keeping only the N most recent ones.")
def purge_logs(keep: int = typer.Option(10, help="Number of latest logs to keep")):
    if not os.path.exists(LOG_DIR):
        console.print("[yellow]No logs directory found. Nothing to purge.[/yellow]")
        return
        
    files = [f for f in os.listdir(LOG_DIR) if f.endswith(".log")]
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
