import json
import re
import tempfile
from datetime import datetime
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from rich.console import Console
from rich.json import JSON
from rich.panel import Panel
from rich.table import Table


class OutputFormat(StrEnum):
    JSON = "json"
    PRETTY = "pretty"
    TABLE = "table"


class InfoOutputFormat(StrEnum):
    JSON = "json"
    TABLE = "table"


GROUP_DEFAULT_FORMATS: Dict[str, OutputFormat] = {
    "do": OutputFormat.JSON,
    "admin": OutputFormat.TABLE,
    "mcp": OutputFormat.PRETTY,
}


@dataclass
class CLIGroupState:
    output_file: Optional[Path] = None
    output_format: OutputFormat = OutputFormat.JSON


@dataclass
class CommandSpec:
    group: str
    name: str
    summary: str
    body: str = ""
    examples: list[str] = field(default_factory=list)
    schema: Optional[Dict[str, Any]] = None
    kind: str = "manual"
    supports_output_file: bool = True
    needs_vault: bool = False
    needs_sync: bool = False
    autosave_large_result: bool = False
    supports_unlock_lease: bool = False


_REGISTRY: Dict[str, Dict[str, CommandSpec]] = {}


def register_command(spec: CommandSpec) -> None:
    _REGISTRY.setdefault(spec.group, {})[spec.name] = spec


def iter_group_commands(group: str) -> Iterable[CommandSpec]:
    registry = _REGISTRY.get(group, {})
    return (registry[name] for name in sorted(registry))


def get_command(group: str, name: str) -> Optional[CommandSpec]:
    registry = _REGISTRY.get(group, {})
    if name in registry:
        return registry[name]
    alt_name = name.replace("_", "-")
    return registry.get(alt_name)


def render_group_examples(console: Console, group: str, *, title: str) -> None:
    console.print(Panel(title, border_style="green"))
    for spec in iter_group_commands(group):
        if not spec.examples:
            continue
        console.print(
            Panel(
                "\n".join(spec.examples),
                title=f"[bold]{group} {spec.name}[/bold]",
                border_style="dim",
            )
        )
        console.print()


def render_command_examples(console: Console, group: str, command_name: str) -> None:
    spec = get_command(group, command_name)
    if not spec:
        console.print(f"[red]Error: Command '{command_name}' not found in group '{group}'.[/red]")
        return
    if not spec.examples:
        console.print(f"[yellow]No examples found for '{group} {spec.name}'.[/yellow]")
        return
    console.print(
        Panel(
            "\n".join(spec.examples),
            title=f"[bold]Examples: {group} {spec.name}[/bold]",
            border_style="green",
        )
    )


def render_group_reference(console: Console, group: str, *, title: str, subtitle: str) -> None:
    console.print()
    console.print(Panel(title, subtitle=subtitle, border_style="bright_blue"))
    console.print()
    for spec in iter_group_commands(group):
        body = spec.body.strip() or spec.summary
        console.print(
            Panel(
                body,
                title=f"[bold bright_cyan]{group} {spec.name}[/bold bright_cyan]",
                border_style="cyan",
                padding=(0, 1),
            )
        )
        if spec.schema is not None:
            console.print("  [bold yellow]JSON SCHEMA[/bold yellow]")
            console.print(Panel(JSON(json.dumps(spec.schema, indent=2)), border_style="dim yellow", padding=(0, 1)))
        if spec.examples:
            console.print("  [bold green]EXAMPLES[/bold green]")
            console.print(Panel("\n".join(spec.examples), border_style="dim green", padding=(0, 1)))
        console.print()


def _infer_status(message: str) -> Optional[str]:
    lower = message.strip().lower()
    if lower.startswith("success"):
        return "success"
    if "abort" in lower:
        return "aborted"
    if "error" in lower or "failed" in lower:
        return "error"
    return None


def coerce_output_data(raw_data: Any) -> Any:
    if isinstance(raw_data, (dict, list)):
        return raw_data
    if raw_data is None:
        return {"status": "success", "message": ""}
    if not isinstance(raw_data, str):
        return {"status": "success", "data": raw_data}
    try:
        return json.loads(raw_data)
    except json.JSONDecodeError:
        payload: Dict[str, Any] = {"message": raw_data}
        status = _infer_status(raw_data)
        if status:
            payload["status"] = status
        return payload


def _flatten_rows(data: Any, prefix: str = "") -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(_flatten_rows(value, path))
        return rows
    if isinstance(data, list):
        if not data:
            rows.append((prefix or "value", "[]"))
            return rows
        for idx, value in enumerate(data):
            path = f"{prefix}[{idx}]" if prefix else f"[{idx}]"
            if isinstance(value, (dict, list)):
                rows.append((path, json.dumps(value, ensure_ascii=False)))
            else:
                rows.append((path, str(value)))
        return rows
    rows.append((prefix or "value", str(data)))
    return rows


def _render_json_text(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def _normalize_admin_payload(data: Any, command_name: Optional[str]) -> Any:
    payload = coerce_output_data(data)
    if not isinstance(payload, dict):
        return payload

    if command_name == "admin status":
        bitwarden_status = payload.get("bitwarden_status") or {}
        configured_auth = payload.get("configured_auth") or {}
        config = payload.get("config") or {}
        wal = payload.get("wal") or {}
        unlock_lease = payload.get("unlock_lease") or {}
        daemon = payload.get("daemon") or {}

        server_url = (
            bitwarden_status.get("serverUrl")
            or configured_auth.get("server_url")
            or payload.get("server_url")
            or None
        )
        user_email = bitwarden_status.get("userEmail") or configured_auth.get("user_email") or None
        
        raw_auth_status = bitwarden_status.get("status")
        lease_state = unlock_lease.get("state")
        effective_auth_status = raw_auth_status
        if raw_auth_status == "locked" and lease_state == "active":
            effective_auth_status = "unlocked (lease)"

        auth = {
            "status": effective_auth_status,
            "cli_status": raw_auth_status if effective_auth_status != raw_auth_status else None,
            "server_url": server_url,
            "user_email": user_email,
            "user_id": bitwarden_status.get("userId"),
            "last_sync": bitwarden_status.get("lastSync"),
        }
        wal_state = wal.get("state") or ("pending" if wal.get("pending") else "clean")
        normalized = {
            "status": payload.get("status"),
            "message": payload.get("message"),
            "auth": {k: v for k, v in auth.items() if v is not None},
            "daemon": {k: v for k, v in daemon.items() if v is not None and v != "unsupported"},
            "wal": {
                "state": wal_state,
                "file": wal.get("file"),
                "note": wal.get("note"),
            },
            "config": {
                "max_batch_size": config.get("max_batch_size"),
                "path": config.get("path"),
                "validation_mode": config.get("validation_mode"),
            },
        }
        if unlock_lease:
            normalized["unlock_lease"] = {k: v for k, v in unlock_lease.items() if v is not None}
        return normalized

    if command_name == "admin wal view":
        wal = payload.get("wal")
        if wal:
            normalized = {
                "status": payload.get("status"),
                "message": payload.get("message"),
                "wal": wal,
            }
            return normalized

    return payload


def _render_pretty_text(data: Any, *, command_name: Optional[str]) -> str:
    console = Console(width=120)
    title = command_name or "BW-Proxy Result"
    with console.capture() as capture:
        if isinstance(data, dict):
            status = data.get("status")
            message = data.get("message")
            header_lines = []
            if status is not None:
                header_lines.append(f"Status   : {status}")
            if command_name:
                header_lines.append(f"Command  : {command_name}")
            if message:
                header_lines.append(f"Message  : {message}")
            if header_lines:
                console.print(Panel("\n".join(header_lines), title=title, border_style="cyan"))
            else:
                console.print(Panel(title, border_style="cyan"))

            scalar_rows = {k: v for k, v in data.items() if not isinstance(v, (dict, list)) and k not in {"status", "message"}}
            nested_rows = {k: v for k, v in data.items() if isinstance(v, (dict, list))}
            if scalar_rows:
                table = Table(title="Summary")
                table.add_column("Field", style="cyan")
                table.add_column("Value", style="white")
                for key, value in scalar_rows.items():
                    table.add_row(str(key), str(value))
                console.print(table)
            for key, value in nested_rows.items():
                console.print(f"[bold yellow]{key}[/bold yellow]")
                console.print(Panel(JSON(json.dumps(value, indent=2, ensure_ascii=False)), border_style="dim yellow"))
        else:
            console.print(Panel(JSON(json.dumps(data, indent=2, ensure_ascii=False)), title=title, border_style="cyan"))
    return capture.get()


def _render_table_text(data: Any, *, command_name: Optional[str]) -> str:
    console = Console(width=140)
    with console.capture() as capture:
        table = Table(title=command_name or "BW-Proxy Result")
        table.add_column("Field", style="cyan")
        table.add_column("Value", style="white", overflow="fold")
        for field_name, value in _flatten_rows(data):
            table.add_row(field_name, value)
        console.print(table)
    return capture.get()


def format_output(
    data: Any,
    output_format: OutputFormat,
    *,
    command_name: Optional[str] = None,
    profile: Optional[str] = None,
) -> str:
    coerced = _normalize_admin_payload(data, command_name) if profile == "admin" else coerce_output_data(data)
    if output_format == OutputFormat.JSON:
        return _render_json_text(coerced)
    if output_format == OutputFormat.TABLE:
        return _render_table_text(coerced, command_name=command_name)
    return _render_pretty_text(coerced, command_name=command_name)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower())
    slug = slug.strip("._-")
    return slug or "result"


def _infer_extension(output_format: OutputFormat) -> str:
    return ".json" if output_format == OutputFormat.JSON else ".txt"


def build_temp_output_path(command_name: str, context_label: Optional[str], output_format: OutputFormat) -> Path:
    base_dir = Path(tempfile.gettempdir()) / "bw_proxy"
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    parts = [timestamp, _slugify(command_name)]
    if context_label:
        parts.append(_slugify(context_label))
    return base_dir / f"{'_'.join(parts)}{_infer_extension(output_format)}"


def write_output_file(text: str, output_file: Optional[Path], console: Console) -> bool:
    if output_file is None:
        return False
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(text, encoding="utf-8")
    console.print(f"[green]Saved output to {output_file}[/green]")
    return True


def emit_result(
    console: Console,
    data: Any,
    *,
    output_file: Optional[Path],
    output_format: OutputFormat,
    command_name: Optional[str] = None,
    autosave_label: Optional[str] = None,
    autosave: bool = False,
    profile: Optional[str] = None,
) -> None:
    rendered = format_output(data, output_format, command_name=command_name, profile=profile)
    if write_output_file(rendered, output_file, console):
        return
    print(rendered, end="" if rendered.endswith("\n") else "\n")
    coerced = _normalize_admin_payload(data, command_name) if profile == "admin" else coerce_output_data(data)
    if autosave and command_name and not (isinstance(coerced, dict) and coerced.get("status") == "error"):
        temp_output_path = build_temp_output_path(command_name, autosave_label, output_format)
        temp_output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_output_path.write_text(rendered, encoding="utf-8")
        console.print(f"[dim]Also saved to {temp_output_path}[/dim]")
