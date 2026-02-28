import json
import os
import datetime
from typing import List, Dict, Any
from .models import TransactionPayload
from .config import STATE_DIR

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
        status: str,
        error_message: str = None
    ) -> str:
        """
        Writes a detailed execution report to a local flat file.
        Format: YYYY-MM-DD_HH-MM-SS_<status>.log
        """
        TransactionLogger._ensure_dir()
        
        now = datetime.datetime.now()
        timestamp_str = now.strftime("%Y-%m-%d_%H-%M-%S")
        status_safe = status.replace(" ", "_").lower()
        
        filename = f"{timestamp_str}_{transaction_id}_{status_safe}.log"
        filepath = os.path.join(LOG_DIR, filename)
        
        # Serialize payload cleanly
        # Because we strictly use Pydantic, the payload NEVER contains passwords by default
        # But we dump it to have a perfect track of what the AI requested.
        payload_dump = payload.model_dump()
        
        report = []
        report.append(f"TRANSACTION ID: {transaction_id}")
        report.append(f"TIMESTAMP:      {now.isoformat()}")
        report.append(f"STATUS:         {status}")
        if error_message:
            report.append(f"ERROR:          {error_message}")
        report.append("-" * 40)
        report.append(f"RATIONALE:")
        report.append(f"  {payload.rationale}")
        report.append("-" * 40)
        report.append("OPERATIONS REQUESTED:")
        
        for idx, op in enumerate(payload_dump.get("operations", [])):
            op_action = op.get("action", "unknown")
            op_target = op.get("target_id", "New Creation")
            report.append(f"  [{idx+1}] Action: {op_action} | Target: {op_target}")
            # Do not log the entire payload of identities or cards to avoid meta-leakage, 
            # though they are technically non-secrets, just keeping logs tight.
            
        report.append("-" * 40)
        report.append("END OF LOG")
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("\n".join(report))
            
        return filepath
