import os
import yaml
from pathlib import Path
from functools import lru_cache

CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"

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
    if not config_path.exists():
        return {}

    with open(config_path, 'r') as f:
        try:
            config = yaml.safe_load(f)
        except yaml.YAMLError:
            return {}
            
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
    # 1. Load current raw data from disk
    if config_path.exists():
        with open(config_path, 'r') as f:
            try:
                data = yaml.safe_load(f) or {}
            except yaml.YAMLError:
                data = {}
    else:
        data = {}

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
    with open(config_path, 'w') as f:
        yaml.dump(updated_data, f, default_flow_style=False, sort_keys=False)

    # 5. VERY IMPORTANT: Clear the lru_cache so the next load_config() sees the change
    load_config.cache_clear()

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

HITL_HOST: str = os.environ.get("HITL_HOST", _hitl_config.get("host", "127.0.0.1"))
HITL_PORT = int(os.environ.get("HITL_PORT", 1138))
HITL_AUTO_OPEN = os.environ.get("HITL_AUTO_OPEN", "true").lower() == "true"
HITL_USE_HTTPS = os.environ.get("HITL_USE_HTTPS", "true").lower() == "true"
