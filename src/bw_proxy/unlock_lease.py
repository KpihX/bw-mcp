import base64
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from .config import DOCKER_UNLOCK_MAX_DURATION_SECONDS, STATE_DIR


UNLOCK_DIR = Path(STATE_DIR) / "unlock"
UNLOCK_LEASE_FILE = UNLOCK_DIR / "session_lease.json"
UNLOCK_KEY_FILE = UNLOCK_DIR / "lease.key"


@dataclass
class UnlockLease:
    session_key: bytearray
    expires_at: int
    server_url: str
    user_email: str


def is_docker_runtime() -> bool:
    return os.environ.get("BW_PROXY_DATA") == "/data" and os.environ.get("BITWARDENCLI_APPDATA_DIR") == "/data/bw-cli"


def _ensure_unlock_dir() -> None:
    UNLOCK_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(UNLOCK_DIR, 0o700)


def _load_or_create_key() -> bytes:
    _ensure_unlock_dir()
    if UNLOCK_KEY_FILE.exists():
        return UNLOCK_KEY_FILE.read_bytes()
    key = Fernet.generate_key()
    UNLOCK_KEY_FILE.write_bytes(key)
    os.chmod(UNLOCK_KEY_FILE, 0o600)
    return key


def _fernet() -> Fernet:
    return Fernet(_load_or_create_key())


def _now() -> int:
    return int(time.time())


class UnlockLeaseManager:
    @staticmethod
    def create(session_key: bytearray, *, server_url: str, user_email: str, duration_seconds: int = DOCKER_UNLOCK_MAX_DURATION_SECONDS) -> UnlockLease:
        _ensure_unlock_dir()
        expires_at = _now() + max(1, int(duration_seconds))
        payload = {
            "expires_at": expires_at,
            "server_url": server_url,
            "user_email": user_email,
            "session_key": base64.b64encode(bytes(session_key)).decode("ascii"),
        }
        ciphertext = _fernet().encrypt(json.dumps(payload).encode("utf-8"))
        UNLOCK_LEASE_FILE.write_bytes(ciphertext)
        os.chmod(UNLOCK_LEASE_FILE, 0o600)
        return UnlockLease(
            session_key=bytearray(session_key),
            expires_at=expires_at,
            server_url=server_url,
            user_email=user_email,
        )

    @staticmethod
    def clear() -> None:
        if UNLOCK_LEASE_FILE.exists():
            UNLOCK_LEASE_FILE.unlink()

    @staticmethod
    def status() -> dict:
        if not is_docker_runtime():
            return {"state": "unsupported", "docker_only": True}
        if not UNLOCK_LEASE_FILE.exists():
            return {"state": "absent", "docker_only": True}
        try:
            lease = UnlockLeaseManager.load(require_valid=False)
        except Exception:
            return {"state": "corrupt", "docker_only": True}
        if lease is None:
            return {"state": "absent", "docker_only": True}
        state = "active" if lease.expires_at > _now() else "expired"
        return {
            "state": state,
            "docker_only": True,
            "expires_at": lease.expires_at,
            "server_url": lease.server_url,
            "user_email": lease.user_email,
        }

    @staticmethod
    def load(*, require_valid: bool = True) -> Optional[UnlockLease]:
        if not UNLOCK_LEASE_FILE.exists():
            return None
        try:
            plaintext = _fernet().decrypt(UNLOCK_LEASE_FILE.read_bytes())
            payload = json.loads(plaintext)
            lease = UnlockLease(
                session_key=bytearray(base64.b64decode(payload["session_key"])),
                expires_at=int(payload["expires_at"]),
                server_url=str(payload["server_url"]),
                user_email=str(payload["user_email"]),
            )
        except (InvalidToken, ValueError, KeyError, json.JSONDecodeError, TypeError):
            if require_valid:
                UnlockLeaseManager.clear()
            return None

        if require_valid and lease.expires_at <= _now():
            UnlockLeaseManager.clear()
        return lease

    @staticmethod
    def get_lease() -> Optional[UnlockLease]:
        """Convenience method for background daemon."""
        return UnlockLeaseManager.load(require_valid=False)

    @staticmethod
    def is_expired(lease: UnlockLease) -> bool:
        """Check if a loaded lease is expired."""
        return lease.expires_at <= _now()
