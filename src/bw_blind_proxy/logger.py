import json
import os
import datetime
from typing import List, Dict, Any
from .models import TransactionPayload, TransactionStatus
from .config import STATE_DIR
from .scrubber import deep_scrub_payload

LOG_DIR = os.path.join(STATE_DIR, "logs")

class TransactionLogger:
    """
    Manages immutable, human-readable logging of all transactions applied to the Vault.
    Strictly sanitizes all payloads to prevent any secret from spilling to the disk.
    """
    
    @staticmethod
    def _ensure_dir():
        if not os.path.exists(STATE_DIR):
            os.makedirs(STATE_DIR, exist_ok=True)
        if not os.path.exists(LOG_DIR):
            os.makedirs(LOG_DIR, exist_ok=True)
            
    @staticmethod
    def log_transaction(
        transaction_id: str,
        payload: TransactionPayload,
        status: TransactionStatus,
        error_message: str = None,
        executed_ops: List[str] = None,
        failed_op: Dict[str, Any] = None,
        executed_rolled_back_cmds: List[str] = None,
        failed_rollback_cmd: str = None  # Only ONE cmd can fail in a sequential LIFO pass
    ) -> str:
        """
        Writes a detailed execution report to a local flat file.
        Format: YYYY-MM-DD_HH-MM-SS_<status>.log
        """
        TransactionLogger._ensure_dir()
        
        now = datetime.datetime.now()
        timestamp_str = now.strftime("%Y-%m-%d_%H-%M-%S")
        status_safe = status.replace(" ", "_").lower()
        
        import json
        
        filename = f"{timestamp_str}_{transaction_id}_{status_safe}.json"
        filepath = os.path.join(LOG_DIR, filename)
        
        # Build structured JSON dict
        log_data = {
            "transaction_id": transaction_id,
            "timestamp": now.isoformat(),
            "status": status,
            "rationale": payload.rationale,
            "error_message": error_message,
            "operations_requested": deep_scrub_payload(payload.model_dump().get("operations", [])),
            "execution_trace": [msg.lstrip('-> ').strip() for msg in (executed_ops or [])],
            "failed_execution": deep_scrub_payload(failed_op),
            "rollback_trace": executed_rolled_back_cmds or [],
            "failed_rollback": failed_rollback_cmd
        }
        
        # Safely remove None values to keep logs minimal
        log_data = {k: v for k, v in log_data.items() if v is not None}
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, indent=2)
            
        return filepath

    @staticmethod
    def get_recent_logs_summary(n: int) -> List[Dict[str, str]]:
        """
        Returns a high-level summary of the last `n` transactions.
        Used by the CLI table and the AI `get_proxy_audit_context` tool.
        """
        if not os.path.exists(LOG_DIR):
            return []
            
        files = [f for f in os.listdir(LOG_DIR) if f.endswith(".json")]
        if not files:
            return []
            
        files.sort(reverse=True) # Newest first
        
        summaries = []
        for filename in files[:n]:
            try:
                with open(os.path.join(LOG_DIR, filename), 'r') as f:
                    data = json.load(f)
                    
                summaries.append({
                    "timestamp": data.get("timestamp", ""),
                    "transaction_id": data.get("transaction_id", ""),
                    "status": data.get("status", ""),
                    "rationale": data.get("rationale", "")
                })
            except Exception:
                continue # Skip broken logs gracefully
                
        return summaries

    @staticmethod
    def get_log_details(tx_id: str = None, n: int = None) -> Dict[str, Any]:
        """
        Fetches the complete JSON payload of a specific transaction log.
        Matches by exact or prefix `tx_id`, OR by recency index `n` (1 = newest).
        If both are None, returns the absolute newest log.
        """
        if not os.path.exists(LOG_DIR):
            raise ValueError("No logs directory found.")
            
        all_files = [f for f in os.listdir(LOG_DIR) if f.endswith(".json")]
        if not all_files:
            raise ValueError("No transaction logs exist yet.")
            
        all_files.sort(reverse=True)
        
        target_file = None
        if n is not None:
            if n < 1 or n > len(all_files):
                raise ValueError(f"Invalid index '{n}'. Only {len(all_files)} logs available.")
            target_file = all_files[n - 1]
        elif tx_id is not None:
            matches = [f for f in all_files if tx_id in f]
            if not matches:
                raise ValueError(f"No log found matching Transaction ID: {tx_id}")
            if len(matches) > 1:
                raise ValueError(f"Multiple logs match '{tx_id}'. Please provide a more specific prefix.")
            target_file = matches[0]
        else:
            target_file = all_files[0]
            
        filepath = os.path.join(LOG_DIR, target_file)
        with open(filepath, 'r') as f:
            return json.load(f)

