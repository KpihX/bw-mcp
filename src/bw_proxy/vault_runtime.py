import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union

from .config import HITL_VALIDATION_MODE
from .subprocess_wrapper import SecureBWError, SecureProxyError, SecureSubprocessWrapper, _safe_error_message
from .ui import HITLManager
from .unlock_lease import UnlockLeaseManager, is_docker_runtime


@dataclass
class VaultExecutionContext:
    title: str
    raw_status: Dict[str, Any]
    auth_state: str
    session_key: Optional[bytearray] = None
    master_password: Optional[bytearray] = None
    auth_source: str = "none"
    should_relock: bool = False
    unlock_deferred: bool = False
    sync_completed: bool = False
    used_unlock_lease: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


def _merge_policy(func: Callable[..., Any], **updates: Any) -> Callable[..., Any]:
    policy = dict(getattr(func, "__bw_policy__", {}))
    policy.update(updates)
    setattr(func, "__bw_policy__", policy)
    return func


def get_command_policy(func: Callable[..., Any]) -> Dict[str, Any]:
    return dict(getattr(func, "__bw_policy__", {}))


def autosave_large_result(func: Callable[..., Any]) -> Callable[..., Any]:
    return _merge_policy(func, autosave_large_result=True)


def requires_fresh_sync(func: Callable[..., Any]) -> Callable[..., Any]:
    return _merge_policy(func, needs_sync=True)


def supports_unlock_lease(func: Callable[..., Any]) -> Callable[..., Any]:
    return _merge_policy(func, supports_unlock_lease=True)


def _autosave_result(command_name: str, result: Any) -> Optional[str]:
    """Saves the result to /tmp/bw_proxy/ for auditing and recovery."""
    try:
        import tempfile
        
        # We only save successful dictionary results (vault maps, duplicate scans)
        if not isinstance(result, dict) or result.get("status") != "success":
            return None
            
        timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        safe_name = command_name.replace(" ", "-").lower()
        save_dir = Path(tempfile.gettempdir()) / "bw_proxy"
        save_dir.mkdir(parents=True, exist_ok=True)
        
        save_path = save_dir / f"{timestamp}_{safe_name}.json"
        save_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return str(save_path)
    except Exception as e:
        # Silently fail on autosave; it's a best-effort convenience
        sys.stderr.write(f"\n[AUTOSAVE ERROR] {str(e)}\n")
        return None


def _configured_server_url() -> Optional[str]:
    configured = os.environ.get("BW_URL")
    if configured:
        return configured
    try:
        current = SecureSubprocessWrapper.get_server().strip()
    except Exception:
        return None
    return current or None


def _configured_email() -> Optional[str]:
    return os.environ.get("BW_EMAIL") or None


def _same_server(left: Optional[str], right: Optional[str]) -> bool:
    if not left or not right:
        return True
    return left.rstrip("/") == right.rstrip("/")


def _login_command_hint() -> str:
    email = _configured_email() or "<email>"
    server = _configured_server_url() or "<server-url>"
    return f"bw-proxy admin login --email {email} --url {server}"


def load_bw_status() -> Dict[str, Any]:
    try:
        raw_status = SecureSubprocessWrapper.execute_raw(["status"])
        parsed = json.loads(raw_status) if raw_status else {}
        if isinstance(parsed, dict):
            return parsed
        return {"status": "unknown", "raw": raw_status}
    except Exception as exc:
        return {"status": "unknown", "error": _safe_error_message(exc)}


def auth_state(status: Optional[Dict[str, Any]]) -> str:
    raw = (status or {}).get("status")
    if isinstance(raw, str):
        return raw.strip().lower()
    return "unknown"


def validate_authenticated_context(
    status: Dict[str, Any],
    *,
    expected_server: Optional[str] = None,
    expected_email: Optional[str] = None,
) -> None:
    if expected_server is None:
        expected_server = _configured_server_url()
    if expected_email is None:
        expected_email = _configured_email()
    active_server = status.get("serverUrl")
    active_email = status.get("userEmail")
    if expected_server and active_server and not _same_server(active_server, expected_server):
        raise SecureProxyError(
            "Bitwarden is authenticated against a different server. "
            f"Expected {expected_server}, got {active_server}. Run '{_login_command_hint()}' after 'bw-proxy admin logout'."
        )
    if expected_email and active_email and active_email != expected_email:
        raise SecureProxyError(
            "Bitwarden is authenticated with a different account. "
            f"Expected {expected_email}, got {active_email}. Run '{_login_command_hint()}' after 'bw-proxy admin logout'."
        )


def relock_vault() -> None:
    try:
        SecureSubprocessWrapper.lock_vault()
    except SecureBWError:
        status = load_bw_status()
        if auth_state(status) != "locked":
            raise


def _wipe_bytearray(value: Optional[bytearray]) -> None:
    if value is None:
        return
    for i in range(len(value)):
        value[i] = 0


def wipe_execution_context(context: VaultExecutionContext) -> None:
    _wipe_bytearray(context.master_password)
    _wipe_bytearray(context.session_key)
    context.master_password = None
    context.session_key = None


def ensure_target_server(target_url: Optional[str] = None) -> None:
    target_url = target_url or os.environ.get("BW_URL")
    if not target_url:
        return
    try:
        current_url = SecureSubprocessWrapper.get_server()
        if target_url.rstrip("/") not in current_url:
            SecureSubprocessWrapper.set_server(target_url)
    except Exception:
        SecureSubprocessWrapper.set_server(target_url)


def build_execution_context(title: str, *, unlock_deferred: bool = False, supports_cached_unlock: bool = True) -> VaultExecutionContext:
    status = load_bw_status()
    state = auth_state(status)
    if state == "unknown":
        raise SecureProxyError("Unable to determine Bitwarden authentication status. Check 'bw status' and try again.")
    if state == "unauthenticated":
        raise SecureProxyError(
            "Bitwarden is logged out. Run "
            f"'{_login_command_hint()}' first, then retry the 'do' command."
        )

    validate_authenticated_context(status)

    context = VaultExecutionContext(
        title=title,
        raw_status=status,
        auth_state=state,
        unlock_deferred=unlock_deferred,
    )

    if supports_cached_unlock and is_docker_runtime():
        lease = UnlockLeaseManager.load(require_valid=True)
        if lease is not None:
            validate_authenticated_context(
                {
                    "serverUrl": lease.server_url,
                    "userEmail": lease.user_email,
                }
            )
            context.session_key = bytearray(lease.session_key)
            context.auth_source = "unlock_lease"
            context.used_unlock_lease = True
            context.metadata["lease_expires_at"] = lease.expires_at
            return context

    if unlock_deferred:
        return context

    open_vault_session(context)
    return context


def open_vault_session(context: VaultExecutionContext, *, title: Optional[str] = None, master_password: Optional[bytearray] = None) -> VaultExecutionContext:
    if context.session_key is not None:
        return context
    if master_password is None:
        if sys.stderr.isatty():
            print("\n🔐 [BW-Proxy] Starting authentication preflight...", file=sys.stderr, flush=True)
            print("🔐 [BW-Proxy] Awaiting master password approval...", file=sys.stderr, flush=True)
        master_password = HITLManager.ask_master_password(title=title or context.title)
    if not master_password:
        raise SecureProxyError("Authentication cancelled. Master Password is required to unlock the authenticated vault.")
    context.master_password = bytearray(master_password)
    context.session_key = SecureSubprocessWrapper.unlock_vault(context.master_password)
    context.auth_source = "interactive_unlock"
    context.should_relock = True
    return context


def ensure_fresh_sync(context: VaultExecutionContext) -> VaultExecutionContext:
    if context.sync_completed:
        return context
    if context.session_key is None:
        raise SecureProxyError("Cannot synchronize before the vault session is open.")
    SecureSubprocessWrapper.execute(["sync"], context.session_key)
    context.sync_completed = True
    return context


def finalize_execution_context(context: VaultExecutionContext) -> Optional[str]:
    relock_error: Optional[str] = None
    try:
        if context.should_relock and not context.used_unlock_lease:
            relock_vault()
    except Exception as exc:
        relock_error = _safe_error_message(exc)
    finally:
        wipe_execution_context(context)
    return relock_error


def requires_authenticated_vault(title: str, *, unlock_deferred: bool = False) -> Callable[[Callable[..., Any]], Callable[..., Dict[str, Any]]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Dict[str, Any]]:
        policy = get_command_policy(func)

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            context: Optional[VaultExecutionContext] = None
            operation_error: Optional[Exception] = None
            result: Any = None
            try:
                context = build_execution_context(
                    title,
                    unlock_deferred=unlock_deferred,
                    supports_cached_unlock=policy.get("supports_unlock_lease", True),
                )
                if policy.get("needs_sync") and not context.unlock_deferred:
                    ensure_fresh_sync(context)
                result = func(
                    *args,
                    session_key=context.session_key,
                    master_password=context.master_password,
                    execution_context=context,
                    **kwargs,
                )
            except Exception as exc:
                operation_error = exc

            relock_error = finalize_execution_context(context) if context is not None else None

            if operation_error is not None:
                message = _safe_error_message(operation_error)
                if relock_error:
                    message = f"{message} Also failed to re-lock the vault: {relock_error}"
                return {"status": "error", "message": message}

            if relock_error:
                return {
                    "status": "error",
                    "message": f"Operation completed but the vault could not be re-locked: {relock_error}",
                    "operation_result": result,
                }

            # Handle Autosave Policy
            if policy.get("autosave_large_result"):
                save_path = _autosave_result(title, result)
                if save_path and isinstance(result, dict) and result.get("status") == "success":
                    result["message"] = f"{result.get('message', '')}\nAlso saved to {save_path}"

            if isinstance(result, dict):
                return result
            return {"status": "success", "data": result}

        _merge_policy(
            wrapper,
            needs_vault=True,
            unlock_deferred=unlock_deferred,
            supports_unlock_lease=policy.get("supports_unlock_lease", True),
        )
        return wrapper

    return decorator
