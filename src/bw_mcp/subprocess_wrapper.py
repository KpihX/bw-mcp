import subprocess
import os
import json
import re
from typing import List, Optional
from mcp.shared.exceptions import McpError
from .config import load_config, PAYLOAD_TAG, BW_PASSWORD_ENV, BW_SESSION_ENV

# ─── Structural Command Redactor ────────────────────────────────────────────
# Bitwarden CLI commands follow a strict grammar:
#   bw <VERB> <OBJECT> [<ID>] [<PAYLOAD>] [--FLAGS...]
#
# We know exactly which tokens are "metadata" (safe to log) and which are
# "payloads" (opaque blobs that may contain secrets in any encoding).
#
# Strategy: WHITELIST known-safe tokens. Everything else is [PAYLOAD].
# This is robust against: raw JSON, base64 JSON, short passwords, future
# Bitwarden CLI format changes, and all unknown edge cases.

_BW_SAFE_VERBS = frozenset({
    "list", "get", "create", "edit", "delete", "restore",
    "move", "share", "sync", "lock", "unlock", "login",
    "logout", "status", "config", "generate", "encode",
})

_BW_SAFE_OBJECTS = frozenset({
    "item", "items", "folder", "folders", "org-collection",
    "org-collections", "collection", "collections", "organization",
    "organizations", "attachment", "template", "item-collections",
    "item.login", "item.card", "item.identity", "item.securenote",
    "send", "sends",
})

_BW_SAFE_FLAGS = frozenset({
    "--raw", "--pretty", "--nointeraction", "--quiet",
    "--passwordenv", "--session", "--permanent", "--itemid",
    "--organizationid", "--folderid", "--collectionid", "--search",
    "--url", "--trash", "--file",
})

# UUID v4 pattern: xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx
_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)

# Flag-value pairs like --itemid <value> — the value itself is a UUID, keep it.
_FLAG_VALUE_RE = re.compile(r'^--[a-zA-Z\-]+$')


def _sanitize_args_for_log(args: List[str]) -> str:
    """
    Reconstruct a command string safe for error logs/LLM messages.

    Keeps only whitelisted verbs, object types, UUIDs, and CLI flags.
    Everything else (JSON, base64, passwords, keys) becomes [PAYLOAD].

    Example:
      ["edit", "item", "uuid-123", "eyJwYXNz..."]
      → "edit item uuid-123 [PAYLOAD]"
    """
    safe_tokens: List[str] = []
    prev_was_flag = False

    for arg in args:
        if arg in _BW_SAFE_VERBS:
            safe_tokens.append(arg)
            prev_was_flag = False
        elif arg in _BW_SAFE_OBJECTS:
            safe_tokens.append(arg)
            prev_was_flag = False
        elif arg in _BW_SAFE_FLAGS:
            safe_tokens.append(arg)
            prev_was_flag = True  # Next token is the flag's value
        elif prev_was_flag:
            # This is the value of a --flag argument.
            # If it's a UUID, it's safe metadata. Otherwise redact.
            if _UUID_RE.match(arg):
                safe_tokens.append(arg)
            else:
                safe_tokens.append(PAYLOAD_TAG)
            prev_was_flag = False
        elif _UUID_RE.match(arg):
            # Standalone UUID = item/folder ID, safe metadata.
            safe_tokens.append(arg)
            prev_was_flag = False
        else:
            # Unknown token → could be JSON, base64, secret, anything.
            safe_tokens.append(PAYLOAD_TAG)
            prev_was_flag = False

    return " ".join(safe_tokens)

class SecureBWError(Exception):
    """
    Exception raised when a Bitwarden command fails securely without leaking data.
    """
    pass

class SecureProxyError(Exception):
    """
    Exception raised for known, safe proxy-level errors (e.g. log not found, 
    batch too large) that are safe to expose to the LLM.
    """
    pass


def _safe_error_message(e: Exception) -> str:
    """
    Return an error string safe for LLM consumption and disk logs.

    - SecureBWError/SecureProxyError: already sanitized or known safe → pass through.
    - Any other exception (JSONDecodeError, ValidationError, etc.): Python's repr
      often includes the raw data that caused the error, which may contain secrets.
      We return only the exception type name with a generic message.
    """
    if isinstance(e, (SecureBWError, SecureProxyError)):
        return str(e)
    return f"{type(e).__name__}: An internal error occurred. Check server logs for details."

class SecureSubprocessWrapper:
    """
    A class that strictly wraps the Bitwarden CLI.
    Methods guarantee that no sensitive data leaks into /proc/<pid>/environ
    or standard error by default.
    """
    
    @staticmethod
    def unlock_vault(master_password: bytearray) -> bytearray:
        """
        Unlocks the vault securely using the Master Password bytearray.
        Returns the session key as a mutable bytearray to allow manual memory wiping by the caller.
        """
        try:
            env = os.environ.copy()
            # Decode only for the microsecond it is injected into the OS env dictionary
            # There's no escaping a python string here without an external C-extension,
            # but we limit its lifetime strictly to this subprocess call.
            env[BW_PASSWORD_ENV] = master_password.decode('utf-8')
            
            # Use text=False to capture stdout as raw bytes, preventing python from caching it
            result = subprocess.run(
                ["bw", "unlock", "--passwordenv", BW_PASSWORD_ENV, "--raw"],
                capture_output=True,
                text=False,
                env=env,
                check=False
            )
            
            if result.returncode != 0:
                raise SecureBWError("Failed to unlock vault. Invalid password or CLI error.")
                
            sk_bytes = bytearray(result.stdout)
            while sk_bytes and sk_bytes[-1] in (b'\n'[0], b'\r'[0]):
                sk_bytes.pop()
                
            # AUTO-SYNC: Immediately force a sync to ensure absolute data consistency
            # before rendering the map or starting a transaction execution.
            SecureSubprocessWrapper.execute(["sync"], sk_bytes)
            
            return sk_bytes
            
        finally:
            # Attempt best-effort memory scrubbing of the environment dictionary
            if BW_PASSWORD_ENV in env:
                env[BW_PASSWORD_ENV] = "DEADBEEF" * 10
                del env[BW_PASSWORD_ENV]

    @staticmethod
    def execute(args: List[str], session_key: bytearray) -> str:
        """
        Executes a secure BW command using the provided ephemeral session key bytearray.
        The session key is passed via environment variable and immediately scrubbed.
        """
        env = os.environ.copy()
        env[BW_SESSION_ENV] = session_key.decode('utf-8')
        
        cmd = ["bw"] + args
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=env,
                check=False
            )
            
            if result.returncode != 0:
                # We do NOT expose stderr to the LLM agent to prevent data leakage.
                # Use structural redaction: only whitelisted tokens survive.
                raise SecureBWError(f"Bitwarden command {_sanitize_args_for_log(args)} failed.")
                
            return result.stdout.strip()
            
        finally:
            # Wipe environment variable and memory
            if BW_SESSION_ENV in env:
                env[BW_SESSION_ENV] = "DEADBEEF" * 20
                del env[BW_SESSION_ENV]

    @staticmethod
    def execute_json(args: List[str], session_key: bytearray) -> dict | list:
        """
        Executes a bitwarden command and strictly parses the JSON response.
        """
        raw = SecureSubprocessWrapper.execute(args, session_key)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise SecureBWError("Bitwarden CLI returned non-JSON data.")

    @staticmethod
    def execute_raw(args: List[str]) -> str:
        """
        Executes a raw Bitwarden command that does NOT require a session key (e.g. sync, config).
        """
        cmd = ["bw"] + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode != 0:
                raise SecureBWError(f"Bitwarden command {_sanitize_args_for_log(args)} failed.")
            return result.stdout.strip()
        except Exception as e:
            raise SecureBWError(f"Subprocess error: {str(e)}")
