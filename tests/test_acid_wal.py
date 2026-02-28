import os
import json
import uuid
import time
from unittest.mock import patch

from bw_blind_proxy.wal import WALManager
from bw_blind_proxy.logger import TransactionLogger, LOG_DIR
from bw_blind_proxy.models import TransactionPayload
from bw_blind_proxy.transaction import TransactionManager

def test_wal_serialization_and_recovery_flow(tmp_path):
    """Verifies that the WAL correctly writes JSON files and reads them cleanly."""
    
    # Temporarily remap WAL_FILE to pytest tmp directory for safe testing
    with patch('bw_blind_proxy.wal.WAL_FILE', str(tmp_path / "pending_transaction.json")), \
         patch('bw_blind_proxy.wal.WAL_DIR', str(tmp_path)):
         
        tx_id = "test-uuid-123"
        rollback_stack = [
            {"cmd": ["bw", "delete", "item", "new-id"]},
            {"cmd": ["bw", "restore", "folder", "old-folder"]}
        ]
        
        assert WALManager.has_pending_transaction() is False
        
        # 1. Simulate mid-flight
        WALManager.write_wal(tx_id, rollback_stack)
        
        assert WALManager.has_pending_transaction() is True
        
        # 2. Simulate crashed reboot
        data = WALManager.read_wal()
        assert data["transaction_id"] == tx_id
        assert data["rollback_commands"][0]["cmd"][1] == "delete"
        
        # 3. Test clear
        WALManager.clear_wal()
        assert WALManager.has_pending_transaction() is False

def test_logger_writes_safe_flat_files(tmp_path):
    """Verifies the logger produces immutable history without leaking Python runtime structures."""
    
    with patch('bw_blind_proxy.logger.LOG_DIR', str(tmp_path)):
        payload = TransactionPayload(
            rationale="Automated Test Logging",
            operations=[
                {"action": "create_item", "type": 1, "name": "Secret123"},
                {"action": "delete_folder", "target_id": "999"}
            ]
        )
        tx_id = str(uuid.uuid4())
        
        file_path = TransactionLogger.log_transaction(tx_id, payload, "SUCCESS", None)
        
        assert os.path.exists(file_path)
        with open(file_path, 'r') as f:
            content = f.read()
            
        assert "TRANSACTION ID:" in content
        assert "Automated Test Logging" in content
        assert "create_item" in content
        assert "New Creation" in content
        assert "delete_folder" in content
        assert "999" in content
        assert "SUCCESS" in content

@patch('bw_blind_proxy.transaction.SecureSubprocessWrapper.execute')
@patch('bw_blind_proxy.transaction.TransactionLogger.log_transaction') # prevent test from writing logs
def test_transaction_auto_recovery_execution(mock_log, mock_exec, tmp_path):
    """Tests if check_recovery actually triggers the `bw` subprocess strictly according to the WAL array."""
    
    # 1. Manually craft a trapped WAL json file
    trapped_wal = tmp_path / "pending_transaction.json"
    wal_data = {
        "transaction_id": "stranded-tx-crashes",
        "timestamp": time.time(),
        "rollback_commands": [
            {"cmd": ["bw", "edit", "item", "id-123", "{}"]},
            {"cmd": ["bw", "restore", "folder", "f-999"]}
        ]
    }
    trapped_wal.write_text(json.dumps(wal_data))
    
    # 2. Trap TransactionManager inside this fake WAL space
    with patch('bw_blind_proxy.wal.WAL_FILE', str(trapped_wal)), \
         patch('bw_blind_proxy.wal.WAL_DIR', str(tmp_path)):
         
        assert WALManager.has_pending_transaction() is True
         
        # 3. Start the proxy
        msg = TransactionManager.check_recovery("fake_session_key")
        
        # 4. Assertions
        assert msg is not None
        assert "CRITICAL" in msg or "WARNING" in msg
        assert "stranded-tx-crashes" in msg
        
        # Secure Subprocess receives commands WITHOUT the 'bw' prefix
        mock_exec.assert_any_call(["edit", "item", "id-123", "{}"], "fake_session_key")
        mock_exec.assert_any_call(["restore", "folder", "f-999"], "fake_session_key")
        assert mock_exec.call_count == 2
        
        # 5. File should be removed after recovery
        assert WALManager.has_pending_transaction() is False
        
        # 6. Logger should have recorded the crash recovery
        mock_log.assert_called_once()
        assert mock_log.call_args[0][2] == "CRASH_RECOVERED_ON_BOOT"
