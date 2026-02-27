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
