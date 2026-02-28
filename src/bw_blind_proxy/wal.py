import json
import os
import time
from typing import List, Dict, Any

from .config import STATE_DIR

# Determine and export paths
WAL_DIR = os.path.join(STATE_DIR, "wal")
WAL_FILE = os.path.join(WAL_DIR, "pending_transaction.json")

class WALManager:
    """
    Manages the Write-Ahead Log (WAL) to guarantee atomic execution of batch transactions.
    Rollback functions are serialized to disk BEFORE execution.
    If the process dies during execution, the proxy can read the WAL on next boot
    and execute the compensating commands to restore the vault.
    """
    
    @staticmethod
    def _ensure_dir():
        if not os.path.exists(STATE_DIR):
            os.makedirs(STATE_DIR, exist_ok=True)
        if not os.path.exists(WAL_DIR):
            os.makedirs(WAL_DIR, exist_ok=True)
            
    @staticmethod
    def write_wal(transaction_id: str, rollback_commands: List[Dict[str, Any]]):
        """
        Writes the transaction intent and its compensating actions to disk.
        """
        WALManager._ensure_dir()
        data = {
            "transaction_id": transaction_id,
            "timestamp": time.time(),
            "rollback_commands": rollback_commands # LIFO order should be maintained during execution
        }
        with open(WAL_FILE, 'w') as f:
            json.dump(data, f, indent=2)
            
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
        
    @staticmethod
    def read_wal() -> Dict[str, Any]:
        """
        Reads the pending WAL data.
        """
        if not os.path.exists(WAL_FILE):
            return {}
        with open(WAL_FILE, 'r') as f:
            return json.load(f)
