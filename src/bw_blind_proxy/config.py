import os
import yaml
from pathlib import Path
from functools import lru_cache

CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"

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

# -----------------
# GLOBAL TYPED CONSTANTS
# -----------------
_config_cache = load_config()

# Redaction tags to prevent hardcoding Pydantic schemas
REDACTED_POPULATED = _config_cache.get("redaction", {}).get("populated_tag", "[REDACTED_BY_PROXY_POPULATED]")
REDACTED_EMPTY = _config_cache.get("redaction", {}).get("empty_tag", "[REDACTED_BY_PROXY_EMPTY]")

# Final path resolution for logging and WAL
default_state_dir = "~/.bw_blind_proxy"
proxy_config = _config_cache.get("proxy", {})
STATE_DIR = os.path.expanduser(proxy_config.get("state_directory", default_state_dir))

# Maximum operations per batch — configurable to minimize the race-condition window
MAX_BATCH_SIZE: int = proxy_config.get("max_batch_size", 10)
