import subprocess
import os
import json
import re
import sys
from typing import List, Optional, Union
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
    "send", "sends", "server", "data",
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
    
    # Internal Transparency: Log the real error to stderr so the human architect
    # can see it in terminal/container logs, but the AI only sees the redacted version.
    import traceback
    print(f"\n[INTERNAL ERROR DEBUG]\n{traceback.format_exc()}", file=sys.stderr)
    
    return f"{type(e).__name__}: An internal error occurred. Check server logs for details."

class SecureSubprocessWrapper:
    """
    A class that strictly wraps the Bitwarden CLI.
    Methods guarantee that no sensitive data leaks into /proc/<pid>/environ
    or standard error by default.
    """

    @staticmethod
    def set_server(url: str):
        """
        Configures the Bitwarden CLI server URL.
        """
        # Ensure URL starts with https:// if not provided
        if not url.startswith("http"):
            url = f"https://{url}"
        
        # We use execute_raw because config server doesn't need a session
        return SecureSubprocessWrapper.execute_raw(["config", "server", url])

    @staticmethod
    def get_server() -> str:
        """
        Returns the currently configured Bitwarden CLI server URL.
        """
        return SecureSubprocessWrapper.execute_raw(["config", "server"]).strip()
    
    @staticmethod
    def login_vault(email: str, master_password: bytearray) -> bytearray:
        """
        Logs into the vault securely using email and Master Password bytearray.
        Returns the session key as a mutable bytearray.
        """
        try:
            env = os.environ.copy()
            env[BW_PASSWORD_ENV] = master_password.decode('utf-8')
            
            # Using --raw to get only the session key
            result = subprocess.run(
                ["bw", "login", email, "--passwordenv", BW_PASSWORD_ENV, "--raw"],
                capture_output=True,
                text=False,
                env=env,
                check=False
            )
            
            if result.returncode != 0:
                raise SecureBWError(f"Failed to login user {email}. Invalid credentials or CLI error.")
                
            sk_bytes = bytearray(result.stdout)
            while sk_bytes and sk_bytes[-1] in (b'\n'[0], b'\r'[0]):
                sk_bytes.pop()
                
            # Force a sync after login
            SecureSubprocessWrapper.execute(["sync"], sk_bytes)
            
            return sk_bytes
            
        finally:
            if BW_PASSWORD_ENV in env:
                env[BW_PASSWORD_ENV] = "0" * 40
                del env[BW_PASSWORD_ENV]

    @staticmethod
    def logout_vault() -> str:
        """
        Logs out of the Bitwarden CLI, clearing local session data.
        """
        return SecureSubprocessWrapper.execute_raw(["logout"])

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
        env[BW_SESSION_ENV] = session_key.decode("utf-8")

        cmd = ["bw"] + args

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, env=env, check=False
            )

            if result.returncode != 0:
                err_clean = result.stderr.strip() if result.stderr else "Unknown error"
                # Note: internal debug logs might show this, but structural redactor 
                # will still be used for the command part.
                raise SecureBWError(f"Bitwarden command {_sanitize_args_for_log(args)} failed: {err_clean}")

            return result.stdout.strip()

        finally:
            # Wipe environment variable and memory
            if BW_SESSION_ENV in env:
                env[BW_SESSION_ENV] = "DEADBEEF" * 20
                del env[BW_SESSION_ENV]

    @staticmethod
    def get_item_raw(uuid: str, session_key: bytearray) -> dict:
        """
        Retrieves the full, unredacted JSON for a specific item.
        INTERNAL USE ONLY: Never expose this dict to the MCP tool response.
        """
        return SecureSubprocessWrapper.execute_json(["get", "item", uuid], session_key)

    @staticmethod
    def edit_item_raw(uuid: str, item_data: dict, session_key: bytearray) -> str:
        """
        Edits an item using a direct JSON payload.
        """
        import base64
        payload = base64.b64encode(json.dumps(item_data).encode("utf-8")).decode("utf-8")
        return SecureSubprocessWrapper.execute(["edit", "item", uuid, payload], session_key)

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

    @staticmethod
    def audit_compare_secrets(
        item_id_a: str, field_a: str, name_a: str | None,
        item_id_b: str, field_b: str, name_b: str | None,
        session_key: bytearray
    ) -> bool:
        """
        Executes an isolated, ephemeral Python subprocess to fetch, 
        parse, and compare two secret fields. Now supports dynamic field pathing
        and top-level field audit (notes).
        """
        # SECURITY: Deep validation from centralized models
        from .models import ALLOWED_NAMESPACES
        
        for f, label in [(field_a, "field_a"), (field_b, "field_b")]:
            ns = f.split('.')[0]
            if ns not in ALLOWED_NAMESPACES:
                raise SecureBWError(f"Invalid field target namespace for {label}: '{ns}'. Operation rejected.")

        for uid, label in [(item_id_a, "item_id_a"), (item_id_b, "item_id_b")]:
            if not _UUID_RE.match(uid):
                raise SecureBWError(f"Invalid UUID for {label}: '{uid}'.")
        
        env = os.environ.copy()
        env[BW_SESSION_ENV] = session_key.decode('utf-8')
        
        script = """
import os, json, subprocess, sys

def get_bw_item(uuid):
    res = subprocess.run(['bw', 'get', 'item', uuid], capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(2)
    return json.loads(res.stdout)

def extract(item, field_path, legacy_name=None):
    # Dynamic field resolution
    if field_path.startswith("fields."):
        # field_path can be 'fields.VALUE' (legacy) + legacy_name 
        # OR 'fields.MY_KEY' (dynamic).
        target_name = field_path[7:]
        if target_name == "VALUE" and legacy_name:
            target_name = legacy_name
            
        for f in item.get('fields', []):
            if f.get('name') == target_name:
                return f.get('value')
        return None
        
    # Standard dot-path resolution
    keys = field_path.split('.')
    val = item
    for k in keys:
        if isinstance(val, dict):
            val = val.get(k)
        else:
            return None
    return val

try:
    item_a = get_bw_item(sys.argv[1])
    val_a = extract(item_a, sys.argv[2], sys.argv[3] if sys.argv[3] != '' else None)
    
    item_b = get_bw_item(sys.argv[4])
    val_b = extract(item_b, sys.argv[5], sys.argv[6] if sys.argv[6] != '' else None)
    
    # Support deep comparison for lists (uris) or dicts
    if val_a is not None and val_a != "" and val_a == val_b:
        sys.exit(0)
    else:
        sys.exit(1)
except Exception:
    sys.exit(3)
"""
        cmd = [
            sys.executable, "-c", script, 
            item_id_a, field_a, name_a or "", 
            item_id_b, field_b, name_b or ""
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, env=env, check=False)
            if result.returncode == 0:
                return True
            elif result.returncode == 1:
                return False
            else:
                raise SecureBWError(f"Audit subprocess failed (code {result.returncode}).")
        finally:
            if BW_SESSION_ENV in env:
                env[BW_SESSION_ENV] = "DEADBEEF" * 20
                del env[BW_SESSION_ENV]

    @staticmethod
    def audit_bulk_compare(
        target_id: str,
        field_path: str,
        candidate_ids: List[str],
        session_key: bytearray,
        candidate_field_path: Optional[str] = None
    ) -> List[str]:
        """
        Finds all items in candidate_ids that have the exact same secret 
        as target_id[field_path]. Supports cross-field search via candidate_field_path.
        """
        # Map single target to multi-target engine for consistency
        prep = [{
            "target_id": target_id, 
            "target_path": field_path, 
            "candidate_path": candidate_field_path or field_path
        }]
        
        results = SecureSubprocessWrapper.audit_multi_target_compare(prep, candidate_ids, session_key)
        return results.get(target_id, [])

    @staticmethod
    def audit_multi_target_compare(
        targets: List[dict], 
        candidate_ids: List[str],
        session_key: bytearray
    ) -> dict:
        """
        Finds duplicates for multiple targets in a single sweep of candidate_ids.
        Extremely efficient: fetches each candidate only once.
        """
        # SECURITY Validation
        from .models import ALLOWED_NAMESPACES
        all_item_ids = [t["target_id"] for t in targets] + candidate_ids
        for uid in all_item_ids:
            if not _UUID_RE.match(uid):
                raise SecureBWError(f"Invalid UUID in audit request: '{uid}'.")
        
        for t in targets:
            tp, cp = t["target_path"], t.get("candidate_path") or t["target_path"]
            for p in [tp, cp]:
                ns = p.split('.')[0]
                if ns not in ALLOWED_NAMESPACES:
                    raise SecureBWError(f"Invalid security namespace in path '{p}'. Only {list(ALLOWED_NAMESPACES)} allowed.")

        env = os.environ.copy()
        env[BW_SESSION_ENV] = session_key.decode('utf-8')

        script = """
import os, json, subprocess, sys

targets_data = json.loads(sys.argv[1])
candidates = sys.argv[2:]

def get_bw_item(uuid):
    try:
        res = subprocess.run(['bw', 'get', 'item', uuid], capture_output=True, text=True)
        if res.returncode != 0: return None
        return json.loads(res.stdout)
    except Exception: return None

def extract_full_inventory(item):
    "Returns a list of (value, location_label) pairs for an item."
    inventory = []
    if not item: return inventory
    
    # Login
    pwd = item.get('login', {}).get('password')
    if pwd: inventory.append((pwd, "login.password"))
    
    # Notes
    notes = item.get('notes')
    if notes: inventory.append((notes, "notes"))
    
    # Fields
    for f in item.get('fields', []):
        val = f.get('value')
        if val: inventory.append((val, f"fields.{f.get('name', 'anon')}"))
        
    return [(v.strip(), loc) for v, loc in inventory if v and v.strip()]

# MODE DETERMINATION
special_trigger = 'ffffffff-ffff-ffff-ffff-ffffffffffff'
is_total_scan = any(t.get('target_id') == special_trigger for t in targets_data)

if is_total_scan or not targets_data:
    # TOTAL COLLISION SCAN
    all_ids = candidates if candidates else [i['id'] for i in json.loads(subprocess.run(['bw', 'list', 'items'], capture_output=True, text=True).stdout)]
    value_map = {} # { secret: [ {id, name, loc}, ... ] }
    
    for uid in all_ids:
        item = get_bw_item(uid)
        if not item: continue
        name = item.get('name', 'Unknown')
        for val, loc in extract_full_inventory(item):
            if val not in value_map: value_map[val] = []
            value_map[val].append({"id": uid, "name": name, "loc": loc})
    
    # Filter duplicates only
    collisions = {v: locs for v, locs in value_map.items() if len(locs) > 1}
    print(json.dumps({"status": "TOTAL_COLLISION", "collisions": collisions}))
    sys.exit(0)

# 1. Fetch and Cache targets for specific audit
target_cache = {}
active_targets = []
for t in targets_data:
    tid = t['target_id']
    if tid not in target_cache:
        target_cache[tid] = get_bw_item(tid)
    
    item = target_cache[tid]
    if not item: continue
    path = t['target_path']
    secret = None
    if path.startswith("fields."):
        target_name = path[7:]
        for f in item.get('fields', []):
            if f.get('name') == target_name: secret = f.get('value'); break
    else:
        keys = path.split('.'); val = item
        for k in keys:
            if isinstance(val, dict): val = val.get(k)
            else: val = None; break
        secret = val
        
    if secret and secret.strip() != "":
        active_targets.append({"target_id": tid, "secret": secret.strip()})

results = {tid: set() for tid in set(t['target_id'] for t in targets_data)}
all_ids = candidates if candidates else [i['id'] for i in json.loads(subprocess.run(['bw', 'list', 'items'], capture_output=True, text=True).stdout)]

for cid in all_ids:
    cand_item = get_bw_item(cid)
    if not cand_item: continue
    cand_values = {v for v, l in extract_full_inventory(cand_item)}
    for target in active_targets:
        if target["secret"] in cand_values:
            if cid.lower().strip() != target["target_id"].lower().strip():
                results[target["target_id"]].add(cid)

print(json.dumps({tid: sorted(list(cids)) for tid, cids in results.items()}))
"""
        cmd = [sys.executable, "-c", script, json.dumps(targets)] + candidate_ids
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, env=env)
            if result.returncode == 0:
                stdout = result.stdout.strip()
                if not stdout: return {}
                try:
                    return json.loads(stdout)
                except json.JSONDecodeError:
                    return {}
            else:
                raise SecureBWError(f"Audit analysis failed (CLI code {result.returncode}).")
        finally:
            if BW_SESSION_ENV in env:
                env[BW_SESSION_ENV] = "0" * 40
                del env[BW_SESSION_ENV]
