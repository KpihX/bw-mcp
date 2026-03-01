"""
BW-MCP — Sovereign MCP Server for Bitwarden.

CLI subcommands (daemon-style, like nginx):
  bw-mcp serve    → Start the MCP server in stdio mode (default when no arg)
  bw-mcp stop     → Send SIGTERM to the running server via PID file
  bw-mcp restart  → Stop old process (MCP client auto-respawns on next call)
  bw-mcp status   → Check if the server is running
  bw-mcp version  → Display version and exit
"""
import os
import signal

import typer
from importlib.metadata import version as pkg_version
from rich.console import Console

from .daemon import write_pid, read_pid, clear_pid, is_running

console = Console()

app = typer.Typer(
    name="bw-mcp",
    help="🔐 Sovereign MCP Server for Bitwarden — Zero Trust · AI-Blind · ACID",
    no_args_is_help=False,
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    """Default: run 'serve' if no subcommand is given (backward compatibility)."""
    if ctx.invoked_subcommand is None:
        _serve()


@app.command("serve")
def _serve() -> None:
    """Start the BW-MCP server in stdio MCP mode (blocks until killed)."""
    from .server import main as _server_main  # lazy import — keeps startup fast
    write_pid(os.getpid())
    try:
        _server_main()
    finally:
        clear_pid()


@app.command("version")
def _version() -> None:
    """Display the installed version and exit."""
    v = pkg_version("bw-mcp")
    console.print(f"[bold cyan]BW-MCP[/bold cyan] v[bold]{v}[/bold] 🔐")


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
    """
    Stop the running server.

    The MCP client (Gemini / Claude / Cursor) will automatically respawn
    a fresh process on the next tool call, loading the latest installed binary.

    Workflow after 'uv tool install --force':
      bw-mcp restart
      → [trigger any tool call in your MCP client]
      → fresh bw-mcp process spawned ✅
    """
    pid = read_pid()
    if pid is None or not is_running(pid):
        if pid is not None:
            clear_pid()
        console.print("[yellow]Not running — nothing to restart.[/yellow]")
        return
    os.kill(pid, signal.SIGTERM)
    clear_pid()
    console.print(
        f"[bold cyan]🔄 Restart signal sent[/bold cyan] — "
        f"PID [bold]{pid}[/bold] stopped.\n"
        "[dim]Your MCP client will auto-respawn the server on the next tool call.[/dim]"
    )


def main() -> None:
    """Entrypoint called by pyproject.toml [project.scripts]."""
    app()


__all__ = ["main", "app"]
