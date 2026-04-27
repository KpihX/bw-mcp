import os
import yaml
from pathlib import Path
from functools import lru_cache
from typing import Any

BUNDLED_CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"
WORKSPACE_CONFIG_PATH = Path("/workspace/src/bw_proxy/config.yaml")


def _resolve_config_path() -> Path:
    """
    Resolve the mutable config target.

    Priority:
    1. Explicit env override.
    2. Mounted workspace config in Docker dev mode.
    3. Persistent runtime config in BW_PROXY_DATA.
    4. Bundled source config as a host-mode fallback.
    """
    explicit = os.environ.get("BW_PROXY_CONFIG_PATH")
    if explicit:
        return Path(os.path.expanduser(explicit))

    if WORKSPACE_CONFIG_PATH.exists() and os.access(WORKSPACE_CONFIG_PATH, os.W_OK):
        return WORKSPACE_CONFIG_PATH

    runtime_data_dir = os.environ.get("BW_PROXY_DATA")
    if runtime_data_dir:
        return Path(os.path.expanduser(runtime_data_dir)) / "config.yaml"

    return BUNDLED_CONFIG_PATH


CONFIG_PATH = _resolve_config_path()


def _read_yaml_mapping(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            data = yaml.safe_load(f) or {}
        except yaml.YAMLError:
            return {}
    return data if isinstance(data, dict) else {}


def _load_base_config(config_path: Path) -> dict:
    path = Path(config_path)
    if path.exists():
        return _read_yaml_mapping(path)
    if path != BUNDLED_CONFIG_PATH:
        return _read_yaml_mapping(BUNDLED_CONFIG_PATH)
    return {}

def _load_dotenv():
    """
    Primitive .env loader to avoid external dependencies.
    Searches in current working directory and project root.
    """
    dotenv_paths = [Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"]
    for path in dotenv_paths:
        if path.exists() and path.is_file():
            with open(path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key and val and key not in os.environ:
                        os.environ[key] = val
            break

# Ingest environment variables from .env before constants are defined
_load_dotenv()

@lru_cache(maxsize=1)
def load_config(config_path=CONFIG_PATH, **overrides) -> dict:
    """
    Load the strict proxy configuration with overrides support.
    Cached to ensure we only hit the disk once per instance.
    """
    config = _load_base_config(Path(config_path))
            
    # Simple recursive dict update for overrides
    def deep_update(d, u):
        for k, v in u.items():
            if isinstance(v, dict):
                d[k] = deep_update(d.get(k, {}), v)
            else:
                d[k] = v
        return d
        
    if config is None:
        config = {}
        
    return deep_update(config, overrides)

def update_config(new_values: dict, config_path=CONFIG_PATH):
    """
    Updates the configuration file with new values.
    Uses a clean load (no cache) to ensure we don't overwrite concurrent manual edits
    with old cached state.
    """
    config_path = Path(config_path)
    data = _load_base_config(config_path)

    # 2. Recursive update helper
    def deep_update(d, u):
        for k, v in u.items():
            if isinstance(v, dict):
                d[k] = deep_update(d.get(k, {}), v)
            else:
                d[k] = v
        return d

    # 3. Apply updates
    updated_data = deep_update(data, new_values)

    # 4. Save back to disk
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w', encoding="utf-8") as f:
        yaml.dump(updated_data, f, default_flow_style=False, sort_keys=False)

    # 5. VERY IMPORTANT: Clear the lru_cache so the next load_config() sees the change
    load_config.cache_clear()


def write_config_text(raw_text: str, config_path=CONFIG_PATH) -> dict:
    """Validate and persist the full YAML config text."""
    config_path = Path(config_path)
    parsed = yaml.safe_load(raw_text) or {}
    if not isinstance(parsed, dict):
        raise ValueError("Configuration root must be a YAML mapping.")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(raw_text)
    load_config.cache_clear()
    return parsed


def dump_config_text(config_path=CONFIG_PATH) -> str:
    """Return the current raw config file text."""
    config_path = Path(config_path)
    if config_path.exists():
        return config_path.read_text(encoding="utf-8")
    if config_path != BUNDLED_CONFIG_PATH and BUNDLED_CONFIG_PATH.exists():
        return BUNDLED_CONFIG_PATH.read_text(encoding="utf-8")
    return ""


def get_config_value(path: str, config_path=CONFIG_PATH) -> Any:
    """Resolve a dotted config path from the current config mapping."""
    data = load_config(config_path=config_path)
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(path)
        current = current[part]
    return current


def set_config_value(path: str, value: Any, config_path=CONFIG_PATH) -> Any:
    """Set one dotted config path and persist the YAML file."""
    parts = path.split(".")
    if not parts:
        raise ValueError("Configuration path cannot be empty.")
    nested: dict[str, Any] = {}
    cursor = nested
    for part in parts[:-1]:
        next_cursor: dict[str, Any] = {}
        cursor[part] = next_cursor
        cursor = next_cursor
    cursor[parts[-1]] = value
    update_config(nested, config_path=config_path)
    return get_config_value(path, config_path=config_path)

# -----------------
# GLOBAL TYPED CONSTANTS
# -----------------
_config_cache = load_config()

# Redaction tags to prevent hardcoding Pydantic schemas
REDACTED_POPULATED = _config_cache.get("redaction", {}).get("populated_tag", "[REDACTED_BY_PROXY_POPULATED]")
REDACTED_EMPTY = _config_cache.get("redaction", {}).get("empty_tag", "[REDACTED_BY_PROXY_EMPTY]")

# Final path resolution for logging and WAL
# Priority: 1. ENV: BW_PROXY_DATA, 2. proxy.state_directory from YAML, 3. ~/.bw/proxy
default_state_dir = "~/.bw/proxy"
proxy_config = _config_cache.get("proxy", {})
env_state_dir = os.environ.get("BW_PROXY_DATA")
YAML_state_dir = proxy_config.get("state_directory")

STATE_DIR = os.path.expanduser(env_state_dir or YAML_state_dir or default_state_dir)

# Maximum operations per batch — configurable to minimize the race-condition window
MAX_BATCH_SIZE: int = proxy_config.get("max_batch_size", 10)

# -----------------
# SECURITY CONSTANTS
# -----------------
_security_config = _config_cache.get("security", {})

# Placeholder used in structured error logs to replace opaque/secret CLI args.
# Example: "bw edit item <uuid> [PAYLOAD] failed." instead of leaking base64/JSON.
PAYLOAD_TAG: str = _security_config.get("payload_tag", "[PAYLOAD]")

# Bitwarden environment variable names for credential injection into subprocesses.
# Defined here to avoid magic strings scattered across the codebase.
BW_PASSWORD_ENV: str = _security_config.get("bw_password_env", "BW_PASSWORD")
BW_SESSION_ENV: str = _security_config.get("bw_session_env", "BW_SESSION")

# -----------------
# CRYPTO CONSTANTS
# -----------------
_wal_crypto_config = _config_cache.get("wal_crypto", {})

# Cryptographic parameters for the Write-Ahead Log
WAL_SALT_LENGTH: int = _wal_crypto_config.get("salt_length", 16)
WAL_KEY_LENGTH: int = _wal_crypto_config.get("key_length", 32)
WAL_PBKDF2_ITERATIONS: int = _wal_crypto_config.get("iterations", 480_000)

# -----------------
# AUDIT CONSTANTS
# -----------------
_audit_config = _config_cache.get("audit", {})

AUDIT_MATCH_TAG: str = _audit_config.get("match_tag", "MATCH")
AUDIT_MISMATCH_TAG: str = _audit_config.get("mismatch_tag", "MISMATCH")

# Maximum candidates for an automatic blind duplicate scan
MAX_AUDIT_SCAN_SIZE: int = _audit_config.get("max_scan_size", 100)

# Hard physical ceiling for any scan to prevent memory/CLI exhaustion
MAX_AUDIT_SCAN_CEILING: int = _audit_config.get("max_scan_ceiling", 1000)

# -----------------
# HITL CONSTANTS
# -----------------
_hitl_config = _config_cache.get("hitl", {})
_docker_unlock_config = _config_cache.get("docker_unlock", {})

HITL_HOST: str = os.environ.get("HITL_HOST", _hitl_config.get("host", "127.0.0.1"))
HITL_PORT = int(os.environ.get("HITL_PORT", 1138))
HITL_AUTO_OPEN = os.environ.get("HITL_AUTO_OPEN", "true").lower() == "true"
HITL_USE_HTTPS = os.environ.get("HITL_USE_HTTPS", "true").lower() == "true"
HITL_VALIDATION_MODE: str = os.environ.get(
    "HITL_VALIDATION_MODE",
    _hitl_config.get("validation_mode", "browser"),
).lower()

DOCKER_UNLOCK_MAX_DURATION_SECONDS: int = int(_docker_unlock_config.get("max_duration_seconds", 300))
