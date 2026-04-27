import json
import os
import signal
import sys
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

import typer
from rich.console import Console

from . import logic
from .cli_support import (
    CLIGroupState,
    CommandSpec,
    GROUP_DEFAULT_FORMATS,
    InfoOutputFormat,
    OutputFormat,
    emit_result,
    register_command,
    render_group_examples,
)
from .daemon import clear_pid, is_running, read_pid, write_pid
from .logger import LOG_DIR, TransactionLogger
from .subprocess_wrapper import SecureSubprocessWrapper, _sanitize_args_for_log
from .ui import HITLManager
from .unlock_lease import UnlockLeaseManager, is_docker_runtime
from .vault_runtime import relock_vault
from .wal import WALManager


console = Console()

app = typer.Typer(
    name="bw-proxy",
    help="🔐 Sovereign Hub for Bitwarden — Zero Trust · AI-Blind · ACID",
    no_args_is_help=True,
    add_completion=False,
)
mcp_app = typer.Typer(help="MCP server lifecycle commands (stdio runtime + local PID control)")
admin_app = typer.Typer(help="Administrative utilities (status, auth, logs, WAL, config)")
do_app = typer.Typer(
    help="🔐 Sovereign vault operations. All secret fields are redacted.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

app.add_typer(mcp_app, name="mcp")
app.add_typer(admin_app, name="admin")
app.add_typer(do_app, name="do")

_do_ctx = CLIGroupState(output_format=GROUP_DEFAULT_FORMATS["do"])
_admin_ctx = CLIGroupState(output_format=GROUP_DEFAULT_FORMATS["admin"])

CONFIG_PARAM_MAP = {
    "max-batch-size": ("proxy.max_batch_size", int),
}


def _print_version(value: bool) -> None:
    if not value:
        return
    console.print(f"[bold cyan]BW-Proxy[/bold cyan] v[bold]{pkg_version('bw-proxy')}[/bold] 🔐")
    raise typer.Exit()


@app.callback()
def app_callback(
    version: Annotated[
        Optional[bool],
        typer.Option("-V", "--version", callback=_print_version, is_eager=True, help="Display the installed version and exit."),
    ] = None,
) -> None:
    pass


def _render_admin_result(data: Dict[str, Any], command_name: str) -> None:
    emit_result(
        console,
        data,
        output_file=None,
        output_format=_admin_ctx.output_format,
        command_name=command_name,
        profile="admin",
    )


def _normalize_import_operations(raw_payload: Any) -> tuple[Optional[str], List[Dict[str, Any]]]:
    if isinstance(raw_payload, dict):
        if "operations" in raw_payload:
            ops = raw_payload.get("operations")
            if not isinstance(ops, list):
                raise ValueError("'operations' must be a JSON array.")
            rationale = raw_payload.get("rationale")
            if rationale is not None and not isinstance(rationale, str):
                raise ValueError("'rationale' must be a string when provided.")
            return rationale, ops
        if "items" in raw_payload:
            items = raw_payload.get("items")
            if not isinstance(items, list):
                raise ValueError("'items' must be a JSON array.")
            ops = []
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError("Every imported item must be a JSON object.")
                op = dict(item)
                op.setdefault("action", "create_item")
                ops.append(op)
            rationale = raw_payload.get("rationale")
            if rationale is not None and not isinstance(rationale, str):
                raise ValueError("'rationale' must be a string when provided.")
            return rationale, ops
    if isinstance(raw_payload, list):
        ops = []
        for entry in raw_payload:
            if not isinstance(entry, dict):
                raise ValueError("Imported JSON arrays must contain only objects.")
            op = dict(entry)
            if "action" not in op and {"type", "name"}.issubset(op.keys()):
                op["action"] = "create_item"
            ops.append(op)
        return None, ops
    raise ValueError(
        "Import file must be either a JSON array of operations/items or an object with "
        "'operations' or 'items'."
    )


# --- MCP COMMANDS ---


@mcp_app.command("serve")
def mcp_serve() -> None:
    """Start the BW-Proxy server in stdio MCP mode (blocks until killed)."""
    from .server import main as _server_main

    write_pid(os.getpid())
    try:
        _server_main()
    finally:
        clear_pid()


@mcp_app.command("daemon")
def mcp_daemon() -> None:
    """Start a background keep-alive loop for the Docker runtime."""
    import time
    from .unlock_lease import UnlockLeaseManager

    write_pid(os.getpid())
    try:
        lease_mgr = UnlockLeaseManager()
        console.print("🚀 [Daemon] Runtime keep-alive started.")
        
        # Initial grace period to allow 'admin unlock' to be called
        grace_period_end = time.time() + 300 
        
        while True:
            lease = lease_mgr.get_lease()
            is_valid = lease and not lease_mgr.is_expired(lease)
            
            if is_valid:
                # Reset grace period if we have a valid lease
                grace_period_end = time.time() + 60
            elif time.time() > grace_period_end:
                if lease:
                    console.print("ℹ️ [Daemon] Lease expired and grace period ended. Exiting.")
                else:
                    console.print("ℹ️ [Daemon] No active lease after grace period. Exiting.")
                break
            
            time.sleep(5)
    except KeyboardInterrupt:
        console.print("ℹ️ [Daemon] Interrupted.")
    finally:
        clear_pid()
        console.print("🏁 [Daemon] Runtime keep-alive stopped.")


@mcp_app.command("status")
def mcp_status() -> None:
    """Check whether the MCP server process is currently running."""
    pid = read_pid()
    if pid is None:
        _render_admin_result({"status": "stopped", "message": "No PID file found.", "running": False}, "mcp status")
        raise typer.Exit(1)
    if is_running(pid):
        _render_admin_result({"status": "success", "message": "MCP server is running.", "running": True, "pid": pid}, "mcp status")
        return
    clear_pid()
    _render_admin_result({"status": "stale", "message": f"PID {pid} not responding. Cleared stale PID file.", "running": False, "pid": pid}, "mcp status")
    raise typer.Exit(2)


@mcp_app.command("stop")
def mcp_stop() -> None:
    """Send SIGTERM to the running server via the PID file."""
    pid = read_pid()
    if pid is None:
        _render_admin_result({"status": "success", "message": "Not running — nothing to stop.", "running": False}, "mcp stop")
        return
    if is_running(pid):
        os.kill(pid, signal.SIGTERM)
        clear_pid()
        _render_admin_result({"status": "success", "message": "Server terminated cleanly.", "running": False, "pid": pid}, "mcp stop")
        return
    clear_pid()
    _render_admin_result({"status": "success", "message": f"Stale PID {pid} detected and cleared.", "running": False, "pid": pid}, "mcp stop")


@mcp_app.command("restart")
def mcp_restart() -> None:
    """Stop the running server (MCP clients will auto-respawn it)."""
    pid = read_pid()
    if pid is None or not is_running(pid):
        if pid is not None:
            clear_pid()
        _render_admin_result({"status": "success", "message": "Not running — nothing to restart.", "running": False}, "mcp restart")
        return
    os.kill(pid, signal.SIGTERM)
    clear_pid()
    _render_admin_result(
        {
            "status": "success",
            "message": "Restart signal sent. The MCP client will auto-respawn the server on the next tool call.",
            "running": False,
            "pid": pid,
        },
        "mcp restart",
    )


# --- ADMIN COMMANDS ---


log_app = typer.Typer(help="Manage and view transaction logs")
wal_app = typer.Typer(help="Inspect and manage the Write-Ahead Log")
config_app = typer.Typer(help="View, set, or edit proxy configuration")

admin_app.add_typer(log_app, name="log")
admin_app.add_typer(wal_app, name="wal")
admin_app.add_typer(config_app, name="config")


@admin_app.callback(invoke_without_command=True)
def _admin_callback(
    ctx: typer.Context,
    output_format: Annotated[
        InfoOutputFormat,
        typer.Option("-f", "--format", help="Output format: json or table.", case_sensitive=False),
    ] = InfoOutputFormat.TABLE,
) -> None:
    _admin_ctx.output_format = OutputFormat(output_format.value)
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())


@admin_app.command("status")
def admin_status() -> None:
    """Show the overall local/operator status (auth, WAL, config, server)."""
    _render_admin_result(logic.get_admin_status(), "admin status")


@admin_app.command("login")
def admin_login(
    email: Annotated[Optional[str], typer.Option("-e", "--email", help="Bitwarden account email.")] = None,
    url: Annotated[Optional[str], typer.Option("-u", "--url", help="Bitwarden server URL.")] = None,
) -> None:
    """Authenticate with Bitwarden (defaults to BW_EMAIL/BW_URL env vars)."""
    target_email = email or os.environ.get("BW_EMAIL")
    target_url = url or os.environ.get("BW_URL")
    missing = []
    if not target_email:
        missing.append("email")
    if not target_url:
        missing.append("url")
    if missing:
        joined = ", ".join(missing)
        _render_admin_result(
            {
                "status": "error",
                "message": f"Missing required Bitwarden login parameter(s): {joined}. Provide them with --email/--url or set BW_EMAIL/BW_URL in .env.",
            },
            "admin login",
        )
        raise typer.Exit(1)
    _render_admin_result(logic.login(target_email, target_url), "admin login")


@admin_app.command("logout")
def admin_logout() -> None:
    """Logout from Bitwarden and clear ephemeral session state."""
    _render_admin_result(logic.logout(), "admin logout")


@admin_app.command("unlock")
def admin_unlock() -> None:
    """Create a temporary Docker unlock lease for repeated vault operations."""
    _render_admin_result(logic.admin_unlock(), "admin unlock")


@admin_app.command("lock")
def admin_lock() -> None:
    """Clear the Docker unlock lease and return the local vault to locked state."""
    _render_admin_result(logic.admin_lock(), "admin lock")


@log_app.command("view")
def log_view(
    l: int = typer.Option(5, "-l", "--last", help="Number of latest logs to list in a table"),
    n: int = typer.Option(None, "-n", "--number", help="The N-th most recent log to view in full JSON (1=newest)"),
) -> None:
    """View transaction logs."""
    if n is not None:
        try:
            log_data = TransactionLogger.get_log_details(n=n)
            _render_admin_result({"status": "success", "mode": "detail", "index": n, "log": log_data}, "admin log view")
            return
        except Exception as exc:
            _render_admin_result({"status": "error", "message": str(exc)}, "admin log view")
            raise typer.Exit(1)
    summaries = TransactionLogger.get_recent_logs_summary(l)
    _render_admin_result(
        {
            "status": "success",
            "mode": "summary",
            "count": len(summaries),
            "message": "No logs found." if not summaries else f"Loaded {len(summaries)} transaction summaries.",
            "transactions": summaries,
        },
        "admin log view",
    )


@log_app.command("purge")
def log_purge(keep: int = typer.Option(10, "-k", "--keep", help="Number of latest logs to keep")) -> None:
    """Delete old transaction logs."""
    if not os.path.exists(LOG_DIR):
        _render_admin_result({"status": "success", "message": "Log directory is absent; nothing to purge.", "deleted": 0, "kept": keep}, "admin log purge")
        return
    files = sorted([f for f in os.listdir(LOG_DIR) if f.endswith(".json")], reverse=True)
    if len(files) <= keep:
        _render_admin_result({"status": "success", "message": "Nothing to purge.", "deleted": 0, "kept": len(files)}, "admin log purge")
        return
    for f in files[keep:]:
        os.remove(os.path.join(LOG_DIR, f))
    _render_admin_result({"status": "success", "message": f"Purged {len(files) - keep} old log files.", "deleted": len(files) - keep, "kept": keep}, "admin log purge")


@wal_app.command("view")
def wal_view() -> None:
    """Inspect the Write-Ahead Log."""
    if WALManager.has_pending_transaction():
        mp = None
        session_key = None
        try:
            lease = UnlockLeaseManager.load(require_valid=True) if is_docker_runtime() else None
            if lease is not None:
                session_key = bytearray(lease.session_key)
            else:
                mp = HITLManager.ask_master_password("Unlock WAL for Inspection")
                if not mp:
                    _render_admin_result(
                        {"status": "aborted", "message": "WAL inspection cancelled by the user."},
                        "admin wal view",
                    )
                    raise typer.Exit(1)
                session_key = SecureSubprocessWrapper.unlock_vault(mp)

            wal_data = WALManager.read_wal(session_key)
            if not wal_data:
                _render_admin_result(
                    {
                        "status": "success",
                        "message": "WAL file exists but is empty after decryption.",
                        "wal": {"state": "empty", "exists": True, "file": logic.WAL_FILE},
                    },
                    "admin wal view",
                )
                return
            safe_wal = {
                "status": "success",
                "message": "Pending WAL decrypted successfully.",
                "wal": {
                    "state": "pending",
                    "exists": True,
                    "file": logic.WAL_FILE,
                    "transaction_id": wal_data.get("transaction_id"),
                    "rollback_command_count": len(wal_data.get("rollback_commands", [])),
                    "rollback_commands": [{"cmd": _sanitize_args_for_log(entry.get("cmd", []))} for entry in wal_data.get("rollback_commands", [])],
                },
            }
            _render_admin_result(safe_wal, "admin wal view")
            return
        except Exception:
            _render_admin_result(
                {
                    "status": "error",
                    "message": "WAL file exists but could not be decrypted with the provided Master Password. This can mean a wrong password, a stale WAL from an older session, or a corrupted file.",
                    "wal": {"state": "undecryptable", "exists": True, "file": logic.WAL_FILE},
                },
                "admin wal view",
            )
            raise typer.Exit(1)
        finally:
            if lease is None and session_key is not None:
                try:
                    relock_vault()
                except Exception:
                    pass
            if session_key is not None:
                for i in range(len(session_key)):
                    session_key[i] = 0
            if mp is not None:
                for i in range(len(mp)):
                    mp[i] = 0
    _render_admin_result(
        {
            "status": "success",
            "message": "WAL is clean.",
            "wal": {"state": "clean", "exists": False, "file": logic.WAL_FILE},
        },
        "admin wal view",
    )


@config_app.command("get")
def config_get(
    max_batch_size: Annotated[bool, typer.Option("-m", "--max-batch-size", help="Read proxy.max_batch_size.")] = False,
    validation_mode: Annotated[bool, typer.Option("-v", "--validation-mode", help="Read hitl.validation_mode.")] = False,
) -> None:
    """Read one configuration parameter."""
    selected = [
        path for path, enabled in [
            ("proxy.max_batch_size", max_batch_size),
            ("hitl.validation_mode", validation_mode),
        ] if enabled
    ]
    if len(selected) != 1:
        _render_admin_result({"status": "error", "message": "Select exactly one configuration parameter to read."}, "admin config get")
        raise typer.Exit(1)
    _render_admin_result(logic.get_config_param(selected[0]), "admin config get")


@config_app.command("set")
def config_set(
    max_batch_size: Annotated[Optional[int], typer.Option("-m", "--max-batch-size", help="Set proxy.max_batch_size.")] = None,
    validation_mode: Annotated[Optional[str], typer.Option("-v", "--validation-mode", help="Set hitl.validation_mode to browser or terminal.")] = None,
) -> None:
    """Write one configuration parameter."""
    updates = [
        (path, value) for path, value in [
            ("proxy.max_batch_size", max_batch_size),
            ("hitl.validation_mode", validation_mode),
        ] if value is not None
    ]
    if len(updates) != 1:
        _render_admin_result({"status": "error", "message": "Provide exactly one configuration parameter to update."}, "admin config set")
        raise typer.Exit(1)
    path, value = updates[0]
    _render_admin_result(logic.set_config_param(path, value), "admin config set")


@config_app.command("edit")
def config_edit() -> None:
    """Open the full config in a browser-based editor, validate, then apply."""
    _render_admin_result(logic.edit_config_interactively(), "admin config edit")


# --- DO SUBCOMMANDS ---


@do_app.callback(invoke_without_command=True)
def _do_callback(
    ctx: typer.Context,
    output_file: Annotated[
        Optional[Path],
        typer.Option("-o", "--output-file", help="Write the command output to a file instead of stdout."),
    ] = None,
    output_format: Annotated[
        OutputFormat,
        typer.Option("-f", "--format", help="Output format: json, pretty, or table.", case_sensitive=False),
    ] = GROUP_DEFAULT_FORMATS["do"],
    show_examples: Annotated[
        bool,
        typer.Option("-e", "--examples", help="Show usage examples for all vault operations and exit."),
    ] = False,
):
    if show_examples:
        render_group_examples(console, "do", title="[bold green]BW-Proxy Vault Operation Examples[/bold green]")
        raise typer.Exit()
    _do_ctx.output_file = output_file
    _do_ctx.output_format = output_format
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())


def _get_output_file() -> Optional[Path]:
    return _do_ctx.output_file


def _get_output_format() -> OutputFormat:
    return _do_ctx.output_format


@do_app.command("import-json")
def do_import_json(
    import_file: Annotated[
        Optional[Path],
        typer.Argument(exists=True, file_okay=True, dir_okay=False, readable=True, help="JSON file with operations or item payloads."),
    ] = None,
    rationale: Annotated[Optional[str], typer.Option("-r", "--rationale", help="Fallback rationale if the JSON file doesn't include one.")] = None,
):
    """Import a JSON file through the standard ACID transaction engine."""
    if not import_file:
        console.print("[red]Error: import_file is required.[/red]")
        raise typer.Exit(1)
    try:
        raw_payload = json.loads(import_file.read_text(encoding="utf-8"))
        payload_rationale, ops = _normalize_import_operations(raw_payload)
        final_rationale = payload_rationale or rationale
        if not final_rationale:
            console.print("[red]Error: A rationale is required either in the JSON file or via --rationale.[/red]")
            raise typer.Exit(1)
        res = logic.propose_vault_transaction(final_rationale, ops)
        emit_result(console, res, output_file=_do_ctx.output_file, output_format=_do_ctx.output_format, command_name="do import-json")
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


from .cli_bridge import register_all as _register_logic_commands
from .cli_bridge import render_full_help as _render_full_help

_register_logic_commands(do_app, emit_result, _get_output_file, _get_output_format)


@do_app.command("help", hidden=True)
def do_help_cmd():
    """Comprehensive reference for ALL vault operations (description + Args + Output)."""
    _render_full_help()


@do_app.command("examples", hidden=True)
def do_examples_cmd():
    """Usage examples for all vault operations."""
    render_group_examples(console, "do", title="[bold green]BW-Proxy Vault Operation Examples[/bold green]")


def _register_manual_commands() -> None:
    register_command(CommandSpec(group="mcp", name="serve", summary="Start the BW-Proxy server in stdio MCP mode (blocks until killed).", body="Starts the local stdio MCP runtime and writes a PID file for lifecycle control.", examples=["bw-proxy mcp serve"], supports_output_file=False))
    register_command(CommandSpec(group="mcp", name="daemon", summary="Start a background keep-alive loop for the Docker runtime.", body="Maintains a stable machine identity for the Bitwarden CLI across ephemeral invocations. Exits when the vault lease expires.", examples=["bw-proxy mcp daemon"], supports_output_file=False))
    register_command(CommandSpec(group="mcp", name="status", summary="Check whether the MCP server process is currently running.", body="Reads the PID file and reports whether the local MCP process is alive, stale, or absent.", examples=["bw-proxy mcp status"], supports_output_file=False))
    register_command(CommandSpec(group="mcp", name="stop", summary="Send SIGTERM to the running server via the PID file.", body="Gracefully terminates the local MCP process when a live PID is registered.", examples=["bw-proxy mcp stop"], supports_output_file=False))
    register_command(CommandSpec(group="mcp", name="restart", summary="Stop the running server (MCP clients will auto-respawn it).", body="Stops the local MCP process so the MCP host can respawn a fresh runtime on the next tool call.", examples=["bw-proxy mcp restart"], supports_output_file=False))

    register_command(CommandSpec(group="admin", name="status", summary="Show the overall local/operator status (auth, WAL, config, server).", body="Aggregates Bitwarden CLI status, WAL state, server URL, environment hints, and key local configuration into one operator-facing status page.", examples=["bw-proxy admin status"], supports_output_file=False))
    register_command(CommandSpec(group="admin", name="login", summary="Authenticate with Bitwarden (defaults to BW_EMAIL/BW_URL env vars).", body="Authenticates the local Bitwarden CLI against the configured server using an operator-provided master password.", examples=["bw-proxy admin login --email user@example.com --url https://vault.example.com", "bw-proxy admin login -e user@example.com -u https://vault.example.com"], supports_output_file=False))
    register_command(CommandSpec(group="admin", name="logout", summary="Logout from Bitwarden and clear ephemeral session state.", body="Clears local ephemeral session state and logs out from the Bitwarden CLI.", examples=["bw-proxy admin logout"], supports_output_file=False))
    register_command(CommandSpec(group="admin", name="unlock", summary="Create a temporary Docker unlock lease for repeated do commands.", body="Unlocks the authenticated vault once, caches an encrypted short-lived session lease in Docker data, then re-locks the local Bitwarden CLI state.", examples=["bw-proxy admin unlock"], supports_output_file=False))
    register_command(CommandSpec(group="admin", name="lock", summary="Clear the Docker unlock lease and return the local vault to locked state.", body="Deletes any cached Docker unlock lease and forces the local Bitwarden CLI back to the locked resting state.", examples=["bw-proxy admin lock"], supports_output_file=False))
    register_command(CommandSpec(group="admin", name="log view", summary="View transaction logs.", body="Shows recent transaction summaries or one detailed transaction log payload.", examples=["bw-proxy admin log view", "bw-proxy admin log view --last 10", "bw-proxy admin log view --n 1"], supports_output_file=False))
    register_command(CommandSpec(group="admin", name="log purge", summary="Delete old transaction logs.", body="Removes old log files while keeping the newest N records on disk.", examples=["bw-proxy admin log purge --keep 10"], supports_output_file=False))
    register_command(CommandSpec(group="admin", name="wal view", summary="Inspect the Write-Ahead Log.", body="Decrypts and displays the scrubbed pending WAL payload when recovery data exists.", examples=["bw-proxy admin wal view"], supports_output_file=False))
    register_command(CommandSpec(group="admin", name="config get", summary="Read one configuration parameter.", body="Reads one supported configuration parameter from config.yaml.", examples=["bw-proxy admin config get -m", "bw-proxy admin config get -v"], supports_output_file=False))
    register_command(CommandSpec(group="admin", name="config set", summary="Write one configuration parameter.", body="Updates one supported configuration parameter in config.yaml.", examples=["bw-proxy admin config set -m 25", "bw-proxy admin config set -v terminal"], supports_output_file=False))
    register_command(CommandSpec(group="admin", name="config edit", summary="Edit the full config in a browser and apply only after validation.", body="Opens a browser-based YAML editor for the full config, validates the edited content, then writes the real config.yaml only after approval.", examples=["bw-proxy admin config edit"], supports_output_file=False))

    register_command(CommandSpec(group="do", name="import-json", summary="Import a JSON file through the standard ACID transaction engine.", body="Converts file-backed operation payloads or item arrays into the normal transaction engine flow.", examples=["bw-proxy do import-json /tmp/items.json --rationale 'Bulk import'", "bw-proxy do import-json /tmp/ops.json -f pretty -o /tmp/result.txt"]))


_register_manual_commands()


def main() -> None:
    if len(sys.argv) == 1:
        sys.argv.extend(["mcp", "serve"])
    app(prog_name="bw-proxy")


if __name__ == "__main__":
    main()
