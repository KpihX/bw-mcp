"""
RPC 2.0 CLI Bridge — Sovereign RPC mapping from logic.py to Typer.

ARCHITECTURE:
  - Command mapping: 1 Function = 1 Subcommand.
  - Parameter mapping: All business parameters via a SINGLE positional JSON payload.
  - Global Help: 'do --help' displays FULL multiline JSON schemas with TYPES for ALL functions.
  - Local Help: Every command has a -e/--examples flag for instant usage guidance.
  - Regression Protection: Schemas and types are introspected directly from source logic.
"""

import inspect
import json
import sys
import select
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Dict, Optional, Annotated, get_type_hints, List, Union

import typer
from rich.console import Console
from rich.panel import Panel
from rich.json import JSON

from . import logic
from .cli_support import CommandSpec, register_command, render_group_examples, render_group_reference

console = Console()

# Internal parameters never exposed to CLI
_INTERNAL_PARAMS = frozenset({"kwargs", "session_key", "master_password", "execution_context"})
_EXPLICIT_COMMANDS = frozenset({"login", "logout", "vault_operation", "get_admin_status", "get_config_param", "set_config_param", "edit_config_interactively"})

# Map logic function names to user-friendly CLI command names
_CMD_MAPPING = {
    "fetch_template": "get-template",
    "inspect_transaction_log": "inspect-log",
    "find_item_duplicates": "find-duplicates",
    "find_all_vault_duplicates": "find-all-vault-duplicates",
    "refactor_item_secrets": "refactor-secrets",
}

# Command registry for cross-referencing and testing
_COMMAND_REGISTRY: Dict[str, Dict[str, Any]] = {}


def _stdin_has_data() -> bool:
    """
    Detect whether stdin actually has readable payload data available.

    In Docker shim mode we keep stdin open with `docker run -i`, but many commands
    do not provide any payload through stdin. Simply checking `isatty()` is not
    enough because container stdin is often a pipe, which would otherwise make the
    CLI block forever on `read()`.
    """
    if sys.stdin.isatty():
        return False
    try:
        readable, _, _ = select.select([sys.stdin], [], [], 0.0)
        return bool(readable)
    except Exception:
        return False


def _get_type_name(typ: Any) -> str:
    """Extract a human-readable name from a type annotation."""
    if typ is inspect.Parameter.empty or typ is Any:
        return "Any"
    if typ is type(None):
        return "None"
    
    s = str(typ)
    s = s.replace("typing.", "")
    s = s.replace("bw_proxy.models.", "")
    s = s.replace("bw_proxy.", "")
    s = s.replace("<class '", "").replace("'>", "")
    s = s.replace("NoneType", "None")
    
    if "Union[" in s and "None" in s:
        import re
        match = re.search(r"Union\[([^,]+),\s*None\]", s)
        if match:
            s = f"Optional[{match.group(1)}]"
        else:
            s = s.replace("Union", "Optional")
    
    return s.strip()


def _extract_model_schema(typ: Any) -> Optional[Dict[str, str]]:
    """Return a field/type map for Pydantic models used as a single RPC payload."""
    model_fields = getattr(typ, "model_fields", None)
    if not isinstance(model_fields, dict):
        return None
    schema: Dict[str, str] = {}
    for field_name, field_info in model_fields.items():
        schema[field_name] = _get_type_name(getattr(field_info, "annotation", Any))
    return schema


def _parse_docstring(docstring: Optional[str]) -> Dict[str, str]:
    """Split docstring into summary, body, and examples, excluding Args blocks from help."""
    if not docstring:
        return {"summary": "", "body": "", "examples": ""}

    lines = docstring.splitlines()
    body_lines: list[str] = []
    examples_lines: list[str] = []
    section = "body"
    for line in lines:
        stripped = line.strip().lower()
        if stripped.startswith(("examples:", "example:", "cli usage")):
            section = "examples"
        elif stripped.startswith(("args:", "arguments:", "parameters:")):
            section = "args"
            continue
        elif stripped and not line.startswith((" ", "\t")) and line.rstrip().endswith(":"):
            # Treat later top-level labeled blocks (e.g. Output:) as body content again.
            section = "body"

        if section == "body":
            body_lines.append(line)
        elif section == "examples":
            examples_lines.append(line)

    summary_lines = []
    for line in body_lines:
        if not line.strip() and summary_lines: break
        if line.strip(): summary_lines.append(line)

    summary = "\n".join(summary_lines).strip()
    body = "\n".join(body_lines).strip()
    if body.startswith(summary):
        body = body[len(summary):].lstrip()
    examples = "\n".join(examples_lines).strip()

    return {"summary": summary, "body": body, "examples": examples}


def _unique_flags(*flag_groups: list[str]) -> list[str]:
    """Preserve CLI flag order while removing duplicates."""
    ordered: list[str] = []
    seen: set[str] = set()
    for group in flag_groups:
        for flag in group:
            if flag in seen:
                continue
            seen.add(flag)
            ordered.append(flag)
    return ordered


def _build_rpc_wrapper(func_name: str, func_obj: Any, emit_result_fn: Any, get_output_file_fn: Any, get_output_format_fn: Any):
    """
    Build a Typer command wrapper with a DYNAMIC SIGNATURE using exec().
    This ensures Typer/Click correctly introspects all parameters.
    """
    docstring = inspect.getdoc(func_obj) or ""
    parsed = _parse_docstring(docstring)
    hints = get_type_hints(func_obj)
    sig = inspect.signature(func_obj)
    policy = getattr(func_obj, "__bw_policy__", {})
    
    schema = {}
    expected_params = []
    
    # 1. Build the function signature string
    sig_parts = []
    
    # First: The positional payload argument (Annotated style: default value goes after =)
    sig_parts.append('payload_arg: Annotated[Optional[str], typer.Argument(metavar="[PAYLOAD]", help="JSON payload or path to JSON file.")] = None')
    
    required_params = []
    payload_model_param: Optional[str] = None

    # Second: derive schema/requirements from business parameters
    for name, param in sig.parameters.items():
        if name in _INTERNAL_PARAMS: continue
        expected_params.append(name)
        typ = hints.get(name, param.annotation)
        type_name = _get_type_name(typ)
        if name == "payload":
            model_schema = _extract_model_schema(typ)
            if model_schema is not None:
                schema = model_schema
                payload_model_param = name
            else:
                schema[name] = type_name
        else:
            schema[name] = type_name
        if param.default is inspect.Parameter.empty:
            required_params.append(name)

    # Third: Global/meta options
    sig_parts.append('_cli_payload: Annotated[Optional[str], typer.Option("-p", "--payload", help="JSON payload or path.")] = None')
    sig_parts.append('_cli_output_file: Annotated[Optional[Path], typer.Option("-o", "--output-file", help="Write output to a file.")] = None')
    sig_parts.append('_cli_show_examples: Annotated[bool, typer.Option("-e", "--examples", help="Show usage examples and exit.")] = False')

    # 2. Build the function body
    func_def = f"def {func_name}({', '.join(sig_parts)}):\n"
    func_def += "    params = {}\n"
    func_def += "    if _cli_show_examples:\n"
    func_def += "        render_command_examples(func_name)\n"
    func_def += "        raise typer.Exit()\n"
    
    func_def += "    final_payload = _cli_payload or payload_arg\n"
    func_def += "    if not final_payload and stdin_has_data():\n"
    func_def += "        try: final_payload = sys.stdin.read().strip()\n"
    func_def += "        except Exception: final_payload = None\n"
    
    func_def += "    if final_payload:\n"
    func_def += "        p = Path(final_payload)\n"
    func_def += "        if p.exists() and p.is_file(): text = p.read_text(encoding='utf-8')\n"
    func_def += "        else: text = final_payload\n"
    func_def += "        try: params = json.loads(text)\n"
    func_def += "        except JSONDecodeError as exc:\n"
    func_def += "            console.print(f'[red]Error: Invalid JSON payload.[/red]\\n{exc}')\n"
    func_def += "            raise typer.Exit(1)\n"
    func_def += "    if params is None:\n"
    func_def += "        params = {}\n"
    func_def += "    if params and not isinstance(params, dict):\n"
    func_def += "        console.print(Panel('[bold red]RPC payload must be a JSON object keyed by parameter name.[/bold red]', border_style='red'))\n"
    func_def += "        raise typer.Exit(1)\n"
    func_def += "    if payload_model_param and isinstance(params, dict):\n"
    func_def += "        if payload_model_param not in params or len(params) != 1:\n"
    func_def += "            params = {payload_model_param: params}\n"
    func_def += "    unknown_params = sorted(set(params) - set(expected_params))\n"
    func_def += "    if unknown_params:\n"
    func_def += "        joined = ', '.join(unknown_params)\n"
    func_def += "        console.print(Panel(f'[bold red]Unknown RPC parameter(s):[/bold red] {joined}', border_style='red'))\n"
    func_def += "        raise typer.Exit(1)\n"
    func_def += "    missing_params = [p for p in required_params if p not in params]\n"
    func_def += "    if missing_params:\n"
    func_def += "        joined = ', '.join(missing_params)\n"
    func_def += "        console.print(Panel(f'[bold red]Missing required RPC parameter(s):[/bold red] {joined}', border_style='red'))\n"
    func_def += "        raise typer.Exit(1)\n"

    func_def += "    # Pydantic V2 Validation Layer\n"
    func_def += "    from pydantic import TypeAdapter, ValidationError\n"
    func_def += "    validated_params = {}\n"
    func_def += "    for p_name, p_val in params.items():\n"
    func_def += "        if p_name not in expected_params: continue\n"
    func_def += "        try:\n"
    func_def += "            hint = hints.get(p_name)\n"
    func_def += "            if hint:\n"
    func_def += "                validated_params[p_name] = TypeAdapter(hint).validate_python(p_val)\n"
    func_def += "            else: validated_params[p_name] = p_val\n"
    func_def += "        except ValidationError as e:\n"
    func_def += "            console.print(Panel(f'[bold red]Validation Error for parameter \"{p_name}\":[/bold red]\\n{e}', border_style='red'))\n"
    func_def += "            raise typer.Exit(1)\n"
    func_def += "        except Exception as e:\n"
    func_def += "            validated_params[p_name] = p_val\n"
    
    func_def += "    final_output_file = _cli_output_file or get_output_file_fn()\n"
    func_def += "    final_output_format = get_output_format_fn()\n"
    func_def += "    try:\n"
    func_def += "        # Use getattr(logic, ...) to support mocking in tests\n"
    func_def += "        target_func = getattr(logic, func_name)\n"
    func_def += "        result = target_func(**validated_params)\n"
    func_def += "        emit_result_fn(console, result, output_file=final_output_file, output_format=final_output_format, command_name=f'do {reg_key}', autosave=command_policy.get('autosave_large_result', False))\n"
    func_def += "    except Exception as exc:\n"
    func_def += "        console.print(f'[red]Execution Error: {exc}[/red]')\n"
    func_def += "        raise typer.Exit(1)\n"

    # 3. Exec and catch the function
    namespace = {
        'typer': typer,
        'Optional': Optional,
        'Annotated': Annotated,
        'List': List,
        'Dict': Dict,
        'Union': Union,
        'Any': Any,
        'Path': Path,
        'sys': sys,
        'stdin_has_data': _stdin_has_data,
        'json': json,
        'JSONDecodeError': JSONDecodeError,
        'console': console,
        'Panel': Panel,
        'render_command_examples': render_command_examples,
        'func_name': func_name,
        'func_obj': func_obj,
        'emit_result_fn': emit_result_fn,
        'get_output_file_fn': get_output_file_fn,
        'get_output_format_fn': get_output_format_fn,
        'expected_params': expected_params,
        'required_params': required_params,
        'payload_model_param': payload_model_param,
        'logic': logic,
        # Pydantic V2: resolved hints injected so TypeAdapter can work inside exec()
        'hints': hints,
        'reg_key': _CMD_MAPPING.get(func_name, func_name.replace("_", "-")),
        'command_policy': policy,
    }
    
    # Try to import bw_proxy itself and models
    try:
        import bw_proxy
        namespace['bw_proxy'] = bw_proxy
    except ImportError:
        pass

    try:
        from . import models
        namespace['models'] = models
        namespace.update({name: getattr(models, name) for name in dir(models) if not name.startswith("_")})
    except ImportError:
        pass

    try:
        exec(func_def, namespace)
        _rpc_executor = namespace[func_name]
    except Exception as e:
        console.print(f"[dim yellow]Bridge Generation Warning for {func_name}: {e}. Retrying with loose types...[/dim yellow]")
        # Second attempt: replace complex types with 'Any'
        loose_sig_parts = []
        for p in sig_parts:
            if ":" in p and "Annotated" in p:
                # Keep the name and assignment but simplify the type to Any
                name_part = p.split(":")[0]
                default_part = p.split("=")[-1]
                loose_sig_parts.append(f"{name_part}: Any = {default_part}")
            else:
                loose_sig_parts.append(p)
        
        loose_func_def = f"def {func_name}({', '.join(loose_sig_parts)}):\n"
        # Rebuild the same body but with loose signature
        body_lines = func_def.splitlines()[1:]
        loose_func_def += "\n".join(body_lines)
        
        try:
            exec(loose_func_def, namespace)
            _rpc_executor = namespace[func_name]
        except Exception as e2:
            console.print(f"[red]CRITICAL: Bridge Generation Failed for {func_name}: {e2}[/red]")
            console.print(f"[dim]Def: {func_def}[/dim]")
            def _rpc_executor(**kwargs): pass

    # Build compact schema string for --help text (escaped for Rich markup)
    schema_json_str = json.dumps(schema, indent=2)
    schema_escaped = schema_json_str.replace("[", r"\[")

    # Help text (used by Typer's --help; must be a plain string)
    help_text = f"{parsed['summary']}\n\n"
    help_text += "RPC 2.0 JSON SCHEMA:\n"
    help_text += f"{schema_escaped}\n\n"
    if parsed["body"]:
        help_text += f"{parsed['body']}\n\n"
    if parsed["examples"]:
        help_text += f"{parsed['examples']}"

    # Store raw schema string for colorized rendering in `do help`
    _rpc_executor.__doc__ = help_text
    _rpc_executor._schema_json = schema_json_str  # type: ignore[attr-defined]
    return _rpc_executor


def render_full_help() -> None:
    """Detailed reference for ALL do commands — manual and dynamic."""
    render_group_reference(
        console,
        "do",
        title="[bold cyan]BW-Proxy Sovereign RPC 2.0 — Complete Reference[/bold cyan]",
        subtitle="[dim]bw-proxy do help[/dim]",
    )


def render_all_examples() -> None:
    """Usage examples for ALL commands."""
    render_group_examples(console, "do", title="[bold green]BW-Proxy Sovereign RPC 2.0 — Usage Examples[/bold green]")


def render_command_examples(command_name: str) -> None:
    """Show examples for a specific command."""
    from .cli_support import render_command_examples as _render_examples
    _render_examples(console, "do", command_name)


def register_all(do_app: typer.Typer, emit_result_fn: Any, get_output_file_fn: Any, get_output_format_fn: Any):
    """Dynamic registration of logic.py functions as RPC commands."""
    for name, obj in inspect.getmembers(logic, inspect.isfunction):
        if name.startswith("_") or name in _EXPLICIT_COMMANDS: continue
        if getattr(obj, "__module__", "") != logic.__name__: continue

        # Use mapping if available, otherwise default to slugified function name
        cmd_name = _CMD_MAPPING.get(name, name.replace("_", "-"))
        parsed = _parse_docstring(inspect.getdoc(obj))
        
        # Build the wrapper (now with dynamic signature)
        wrapper = _build_rpc_wrapper(name, obj, emit_result_fn, get_output_file_fn, get_output_format_fn)
        
        # Re-derive schema for short_help
        hints = get_type_hints(obj)
        sig = inspect.signature(obj)
        schema = {}
        for p_name, param in sig.parameters.items():
            if p_name in _INTERNAL_PARAMS: continue
            typ = hints.get(p_name, param.annotation)
            if p_name == "payload":
                model_schema = _extract_model_schema(typ)
                if model_schema is not None:
                    schema = model_schema
                    continue
            schema[p_name] = _get_type_name(typ)
        
        rich_schema_str = json.dumps(schema, indent=2).replace("[", r"\[")
        short_help = f"{parsed['summary']}\nSCHEMA: {rich_schema_str}"
        
        do_app.command(name=cmd_name, help=wrapper.__doc__, short_help=short_help)(wrapper)

        _COMMAND_REGISTRY[cmd_name] = {
            "parsed_doc": parsed,
            "schema": schema,
            "policy": getattr(obj, "__bw_policy__", {}),
        }
        policy = getattr(obj, "__bw_policy__", {})
        register_command(
            CommandSpec(
                group="do",
                name=cmd_name,
                summary=parsed["summary"],
                body=parsed["body"],
                examples=parsed["examples"].splitlines() if parsed["examples"] else [],
                schema=schema,
                kind="dynamic",
                needs_vault=policy.get("needs_vault", False),
                needs_sync=policy.get("needs_sync", False),
                autosave_large_result=policy.get("autosave_large_result", False),
                supports_unlock_lease=policy.get("supports_unlock_lease", False),
            )
        )
