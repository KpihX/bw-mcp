import json
import os
import time
import base64
from typing import List, Dict, Any, Optional

from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.fernet import Fernet, InvalidToken

from .config import STATE_DIR, WAL_SALT_LENGTH, WAL_KEY_LENGTH, WAL_PBKDF2_ITERATIONS

# Determine and export paths
WAL_DIR = os.path.join(STATE_DIR, "wal")
WAL_FILE = os.path.join(WAL_DIR, "pending_transaction.wal")  # .wal = encrypted blob


def _derive_key(master_password: bytearray, salt: bytes) -> bytes:
    """
    Derives a Fernet-compatible 32-byte key from the BW session key using PBKDF2.

    Why PBKDF2 and not raw hashing?
    - PBKDF2 is deliberately slow (480k iterations), making brute-force
      infeasible even if the encrypted WAL file is exfiltrated.
    - The salt ensures that two identical session keys produce different
      derived keys across different transactions.

    The session_key is itself a derivative of the Bitwarden master password,
    so we get layered key derivation: MasterPassword → BW_SESSION → PBKDF2 → Fernet key.
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=WAL_KEY_LENGTH,
        salt=salt,
        iterations=WAL_PBKDF2_ITERATIONS,
    )
    raw_key = kdf.derive(bytes(master_password))
    return base64.urlsafe_b64encode(raw_key)


class WALManager:
    """
    Manages the Write-Ahead Log (WAL) to guarantee atomic execution of batch transactions.

    SECURITY: The WAL is encrypted at rest using AES-128-CBC + HMAC (via Fernet),
    with a key derived from the active BW_SESSION via PBKDF2. This means:
    - A stolen WAL file is useless without the session key.
    - The file is also chmod 600 (owner-only access) as defense-in-depth.
    - On recovery, the same session_key (from vault unlock) decrypts the WAL.
    """

    @staticmethod
    def _ensure_dir():
        if not os.path.exists(STATE_DIR):
            os.makedirs(STATE_DIR, exist_ok=True)
        if not os.path.exists(WAL_DIR):
            os.makedirs(WAL_DIR, exist_ok=True)

    @staticmethod
    def write_wal(transaction_id: str, reversed_operations: List[Dict[str, Any]], master_password: bytearray) -> None:
        """
        Write the reversed list of operations (compensating actions) to the WAL.
        The WAL payload is AES-encrypted using the master password.
        """
        WALManager._ensure_dir()
        payload = {
            "transaction_id": transaction_id,
            "timestamp": time.time(),
            "rollback_commands": reversed_operations,
        }
        json_data = json.dumps(payload).encode("utf-8")

        # Generate a fresh random salt per write
        salt = os.urandom(WAL_SALT_LENGTH)
        key = _derive_key(master_password, salt)
        fernet = Fernet(key)
        ciphertext = fernet.encrypt(json_data)

        # Write salt + ciphertext
        with open(WAL_FILE, "wb") as f:
            f.write(salt)
            f.write(ciphertext)

        # Defense-in-depth: restrict to owner-only read/write
        os.chmod(WAL_FILE, 0o600)

    @staticmethod
    def read_wal(master_password: bytearray) -> Optional[Dict[str, Any]]:
        """
        Read and decrypt the current WAL.
        Returns the payload dict if successful, or None if WAL doesn't exist.
        Raises ValueError if cryptography fails (wrong password or corrupted file).
        """
        if not os.path.exists(WAL_FILE):
            return None
        try:
            with open(WAL_FILE, "rb") as f:
                salt = f.read(WAL_SALT_LENGTH)
                ciphertext = f.read()

            if len(salt) != WAL_SALT_LENGTH or not ciphertext:
                return None # Corrupted or incomplete WAL file

            key = _derive_key(master_password, salt)
            fernet = Fernet(key)
            plaintext = fernet.decrypt(ciphertext)
            return json.loads(plaintext)
        except (InvalidToken, json.JSONDecodeError, Exception) as e:
            raise ValueError(f"Failed to decrypt or parse WAL: {e}") from e

    @staticmethod
    def pop_rollback_command(transaction_id: str, master_password: bytearray) -> None:
        """
        Pops the first command from the rollback list in the WAL and saves it.
        This provides idempotency: if the proxy crashes DURING a rollback execution,
        it won't re-execute successful rollback commands on the next boot.
        """
        try:
            payload = WALManager.read_wal(master_password)
            if not payload or payload.get("transaction_id") != transaction_id:
                return
                
            commands = payload.get("rollback_commands", [])
            if not commands:
                return
                
            commands.pop(0) # Remove the most recently executed command
            payload["rollback_commands"] = commands
            WALManager.write_wal(transaction_id, commands, master_password)
        except Exception:
            # WARNING: If this fails, the WAL won't be updated after a successful
            # rollback command. On next boot, the proxy may re-execute it.
            # We intentionally do NOT log the exception content (may contain secrets).
            import sys
            print("[WAL] WARNING: Failed to pop rollback command from WAL. "
                  "Potential double-application risk on next recovery.", file=sys.stderr)

    @staticmethod
    def clear_wal():
        """
        Removes the WAL file, indicating a successfully committed transaction.
        """
        if os.path.exists(WAL_FILE):
            os.remove(WAL_FILE)

    @staticmethod
    def has_pending_transaction() -> bool:
        """
        Checks if a crashed transaction is awaiting recovery.
        """
        return os.path.exists(WAL_FILE)
