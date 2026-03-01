from typing import Any, Dict, List
from .config import load_config

# Import the precise payload tag used across the system to maintain consistency
config_cache = load_config()
PAYLOAD_TAG = config_cache.get("security", {}).get("payload_tag", "[PAYLOAD]")

# These are the dictionary keys that the Bitwarden CLI, our Pydantic models,
# or our internal dictionaries use to store secrets. 
# We meticulously hunt for these keys regardless of how deeply nested they are.
_SECRET_KEYS = frozenset({
    "password", "totp", "notes", "value", "ssn", "number", "code",
    "passportNumber", "licenseNumber", "key"
})

def deep_scrub_payload(payload: Any) -> Any:
    """
    Recursively clones and scrubs a payload of any potentially sensitive data.
    If it finds a dictionary key matching one of the _SECRET_KEYS, its value 
    is replaced with PAYLOAD_TAG.
    
    This operates exclusively as a failsafe exactly before logs are written to disk.
    
    Args:
        payload: Any data structure (dict, list, string, int, etc.)
        
    Returns:
        A deep-copied, scrubbed version of the payload safe for disk logging.
    """
    if isinstance(payload, dict):
        scrubbed_dict = {}
        for k, v in payload.items():
            if k in _SECRET_KEYS:
                # If the key is sensitive, replace its value entirely
                # (unless it's already None/empty to preserve structure without leaking)
                if v:
                    scrubbed_dict[k] = PAYLOAD_TAG
                else:
                    scrubbed_dict[k] = v
            else:
                # Normal key, recurse into the value
                scrubbed_dict[k] = deep_scrub_payload(v)
        return scrubbed_dict
        
    elif isinstance(payload, list):
        return [deep_scrub_payload(item) for item in payload]
        
    elif isinstance(payload, tuple):
        return tuple(deep_scrub_payload(item) for item in payload)
        
    # Primitive types (str, int, float, bool, None)
    return payload
