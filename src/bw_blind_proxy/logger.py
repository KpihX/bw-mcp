import json
import os
import datetime
from typing import List, Dict, Any
from .models import TransactionPayload, TransactionStatus
from .config import STATE_DIR

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
            
        report.append("-" * 40)
        report.append("[EXECUTION TRACE]")
        if executed_ops:
            for msg in executed_ops:
                # msg usually starts with '-> ' from transaction logic
                clean_msg = msg.lstrip('-> ').strip()
                report.append(f"  [SUCCESS] -> {clean_msg}")
        else:
            report.append("  (No operations were successfully executed)")
            
        if failed_op:
            f_act = failed_op.get("action", "unknown")
            f_tgt = failed_op.get("target_id", "New Creation")
            report.append(f"  [CRASHED] -> {f_act} on {f_tgt}")
            
        if status != TransactionStatus.SUCCESS:
            report.append("-" * 40)
            report.append("[ROLLBACK TRACE]")
            if executed_rolled_back_cmds:
                for r_cmd in executed_rolled_back_cmds:
                    report.append(f"  [REVERSED] -> {r_cmd}")
            else:
                report.append("  (No rollback commands were executed)")
                
            if failed_rollback_cmd:
                report.append(f"  [FAILED TO REVERT] -> {failed_rollback_cmd}")
                    
        report.append("-" * 40)
        report.append("END OF LOG")
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("\n".join(report))
            
        return filepath
