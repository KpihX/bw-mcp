import os
import json
import uuid
import time
import pytest
from unittest.mock import patch

from bw_proxy.wal import WALManager
from bw_proxy.logger import TransactionLogger, LOG_DIR
from bw_proxy.models import TransactionPayload
from bw_proxy.transaction import TransactionManager
from bw_proxy.subprocess_wrapper import _safe_error_message, SecureBWError

TEST_MASTER_PASSWORD = bytearray("fake-master-password-for-wal-tests", "utf-8")

def test_wal_encryption_roundtrip(tmp_path):
    """Verifies that the WAL correctly encrypts, writes, and decrypts data."""

    with patch('bw_proxy.wal.WAL_FILE', str(tmp_path / "pending_transaction.wal")), \
         patch('bw_proxy.wal.WAL_DIR', str(tmp_path)):

        tx_id = "test-uuid-123"
        rollback_stack = [
            {"cmd": ["bw", "delete", "item", "new-id"]},
            {"cmd": ["bw", "restore", "folder", "old-folder"]}
        ]

        assert WALManager.has_pending_transaction() is False

        # 1. Write encrypted WAL
        WALManager.write_wal(tx_id, rollback_stack, TEST_MASTER_PASSWORD)
        assert WALManager.has_pending_transaction() is True

        # 2. Read back and verify content matches
        data = WALManager.read_wal(TEST_MASTER_PASSWORD)
        assert data["transaction_id"] == tx_id
        assert data["rollback_commands"][0]["cmd"][1] == "delete"
        assert data["rollback_commands"][1]["cmd"][3] == "old-folder"

        # 3. Verify file is NOT plaintext JSON (encrypted)
        with open(str(tmp_path / "pending_transaction.wal"), "rb") as f:
            raw = f.read()
        assert b'"transaction_id"' not in raw  # Plaintext key must NOT appear

        # 4. Verify chmod 600
        file_stat = os.stat(str(tmp_path / "pending_transaction.wal"))
        assert oct(file_stat.st_mode)[-3:] == "600"

        # 5. Test clear
        WALManager.clear_wal()
        assert WALManager.has_pending_transaction() is False


def test_wal_wrong_key_fails(tmp_path):
    """Verifies that reading the WAL with a different session key returns empty dict."""

    with patch('bw_proxy.wal.WAL_FILE', str(tmp_path / "pending_transaction.wal")), \
         patch('bw_proxy.wal.WAL_DIR', str(tmp_path)):

        tx_id = "test-wrong-key"
        rollback_stack = [{"cmd": ["bw", "delete", "item", "x"]}]

        WALManager.write_wal(tx_id, rollback_stack, TEST_MASTER_PASSWORD)
        assert WALManager.has_pending_transaction() is True

        # Try reading with wrong key
        with pytest.raises(ValueError, match="Failed to decrypt or parse WAL"):
            WALManager.read_wal(bytearray("some-other-password", "utf-8"))


def test_wal_pop_roundtrip(tmp_path):
    """Verifies that pop_rollback_command correctly decrypts, pops, re-encrypts."""

    with patch('bw_proxy.wal.WAL_FILE', str(tmp_path / "pending_transaction.wal")), \
         patch('bw_proxy.wal.WAL_DIR', str(tmp_path)):

        tx_id = "test-pop"
        rollback_stack = [
            {"cmd": ["bw", "delete", "item", "a"]},
            {"cmd": ["bw", "delete", "item", "b"]},
            {"cmd": ["bw", "delete", "item", "c"]},
        ]
        WALManager.write_wal(tx_id, rollback_stack, TEST_MASTER_PASSWORD)
        assert len(WALManager.read_wal(TEST_MASTER_PASSWORD)["rollback_commands"]) == 3

        # Pop one
        WALManager.pop_rollback_command(tx_id, TEST_MASTER_PASSWORD)
        data = WALManager.read_wal(TEST_MASTER_PASSWORD)
        assert len(data["rollback_commands"]) == 2

        # Pop another
        WALManager.pop_rollback_command(tx_id, TEST_MASTER_PASSWORD)
        data = WALManager.read_wal(TEST_MASTER_PASSWORD)
        assert len(data["rollback_commands"]) == 1


def test_logger_writes_safe_flat_files(tmp_path):
    """Verifies the logger produces immutable history without leaking Python runtime structures."""

    with patch('bw_proxy.logger.LOG_DIR', str(tmp_path)):
        payload = TransactionPayload(
            rationale="Automated Test Logging",
            operations=[
                {"action": "create_item", "type": 1, "name": "Secret123"},
                {"action": "rename_folder", "target_id": "999", "new_name": "Archived"}
            ]
        )
        tx_id = str(uuid.uuid4())

        file_path = TransactionLogger.log_transaction(tx_id, payload, "SUCCESS", None)

        assert file_path.endswith(".json")
        with open(file_path, 'r') as f:
            log_data = json.load(f)

        assert log_data["transaction_id"] == tx_id
        assert log_data["rationale"] == "Automated Test Logging"
        assert log_data["status"] == "SUCCESS"

        ops = log_data["operations_requested"]
        assert len(ops) == 2
        assert ops[0]["action"] == "create_item"
        assert ops[0]["name"] == "Secret123"
        assert ops[1]["action"] == "rename_folder"
        assert ops[1]["target_id"] == "999"
        assert ops[1]["new_name"] == "Archived"


@patch('bw_proxy.transaction.SecureSubprocessWrapper.execute')
@patch('bw_proxy.transaction.TransactionLogger.log_transaction')
def test_transaction_auto_recovery_execution(mock_log, mock_exec, tmp_path):
    """Tests if check_recovery actually triggers the `bw` subprocess using encrypted WAL."""

    wal_file = str(tmp_path / "pending_transaction.wal")

    # 1. Write a legitimate encrypted WAL
    with patch('bw_proxy.wal.WAL_FILE', wal_file), \
         patch('bw_proxy.wal.WAL_DIR', str(tmp_path)):
        WALManager.write_wal("stranded-tx-crashes", [
            {"cmd": ["bw", "edit", "item", "id-123", "{}"]},
            {"cmd": ["bw", "restore", "folder", "f-999"]}
        ], TEST_MASTER_PASSWORD)

    # 2. Trap TransactionManager inside this fake WAL space
    with patch('bw_proxy.wal.WAL_FILE', wal_file), \
         patch('bw_proxy.wal.WAL_DIR', str(tmp_path)):

        assert WALManager.has_pending_transaction() is True

        # 3. Start the proxy recovery
        msg = TransactionManager.check_recovery(TEST_MASTER_PASSWORD, bytearray("fake-runtime-session", "utf-8"))

        # 4. Assertions
        assert "recovery-error" not in msg.lower()
        assert msg is not None
        assert "CRITICAL" in msg or "WARNING" in msg
        assert "stranded-tx-crashes" in msg

        # Secure Subprocess receives commands WITHOUT the 'bw' prefix
        mock_exec.assert_any_call(["edit", "item", "id-123", "{}"], bytearray("fake-runtime-session", "utf-8"))
        mock_exec.assert_any_call(["restore", "folder", "f-999"], bytearray("fake-runtime-session", "utf-8"))
        assert mock_exec.call_count == 2

        # 5. File should be removed after recovery
        assert WALManager.has_pending_transaction() is False

        # 6. Logger should have recorded the crash recovery
        mock_log.assert_called_once()
        assert mock_log.call_args.kwargs["status"] == "CRASH_RECOVERED_ON_BOOT"


def test_safe_error_message_securebwerror():
    """SecureBWError messages pass through (already sanitized)."""
    err = SecureBWError("Bitwarden command edit item [PAYLOAD] failed.")
    assert _safe_error_message(err) == "Bitwarden command edit item [PAYLOAD] failed."


def test_safe_error_message_generic_exception():
    """Generic exceptions must NOT leak their repr content."""
    err = json.JSONDecodeError("Expecting ','", '{"password": "secret"}', 15)
    msg = _safe_error_message(err)
    assert "JSONDecodeError" in msg
    assert "secret" not in msg
    assert "password" not in msg
