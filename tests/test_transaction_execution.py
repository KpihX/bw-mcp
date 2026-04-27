import pytest
import json
from unittest.mock import patch, MagicMock
from bw_proxy.transaction import TransactionManager
from bw_proxy.models import TransactionPayload
from bw_proxy.subprocess_wrapper import SecureBWError

# Sample payload mimicking what the LLM generates
# NOTE: delete_folder is excluded here because it must always be standalone (size 1).
TEST_PAYLOAD = {
    "rationale": "Test coverage",
    "operations": [
        {"action": "rename_item", "target_id": "1", "new_name": "New"},
        {"action": "create_folder", "name": "Folder 1"},
        {"action": "delete_item", "target_id": "1"},
        {"action": "edit_item_card", "target_id": "1", "expYear": "2030"},
        {"action": "upsert_custom_field", "target_id": "1", "name": "Key", "value": "Val", "type": 0},
        {"action": "restore_item", "target_id": "1"},
        {"action": "toggle_reprompt", "target_id": "1", "reprompt": True}
    ]
}

@patch('bw_proxy.transaction.WALManager.has_pending_transaction', return_value=False)
@patch('bw_proxy.transaction.HITLManager.authorize_transaction')
@patch('bw_proxy.transaction.SecureSubprocessWrapper.unlock_vault')
@patch('bw_proxy.transaction.SecureSubprocessWrapper.execute')
@patch('bw_proxy.transaction.SecureSubprocessWrapper.execute_json')
def test_full_transaction_batch_execution(mock_exec_json, mock_exec, mock_unlock, mock_auth, mock_wal):
    """Mocks all HITL and Subprocess dependencies to rigorously test the Transaction routing engine."""
    
    # Setup mocks
    mock_auth.return_value = {"approved": True, "password": bytearray("fake_master_password", "utf-8")}
    mock_unlock.return_value = bytearray("fake_session_key_12345", "utf-8")
    
    # Define a smart mock function to handle both UI name resolution and execution phases
    def mock_get_json_behavior(args, session_key):
        if args[:2] == ["get", "item"]:
            if args[2] == "1": return {"id": "1", "name": "TargetItem", "card": {"brand": "visa"}, "fields": [], "reprompt": 0}
        elif args[:2] == ["get", "folder"]:
            if args[2] == "99": return {"id": "99", "name": "TargetFolder"}
        elif args[:2] == ["get", "template"]:
            if args[2] == "folder": return {"name": "TemplateFolder"}
        
        # Fallback for unexpected calls
        return {"id": args[-1], "name": f"Mock_{args[-1]}"}

    mock_exec_json.side_effect = mock_get_json_behavior

    # Run the big batch
    result = TransactionManager.execute_batch(TEST_PAYLOAD)
    
    # Assertions
    assert "Transaction completed successfully" in result
    assert mock_auth.call_count == 1
    
    # 1 explicit preflight sync + 7 operations
    assert mock_exec.call_count == 8

@patch('bw_proxy.transaction.WALManager.has_pending_transaction', return_value=False)
@patch('bw_proxy.transaction.HITLManager.authorize_transaction')
@patch('bw_proxy.transaction.SecureSubprocessWrapper.unlock_vault')
@patch('bw_proxy.transaction.SecureSubprocessWrapper.execute_json')
def test_transaction_aborted_by_user(mock_exec_json, mock_unlock, mock_auth, mock_wal):
    """Test what happens when a user clicks 'No' or closes the Zenity popup."""
    mock_auth.return_value = {"approved": False}
    mock_unlock.return_value = bytearray("session", "utf-8")
    mock_exec_json.return_value = {"name": "ResolvedName"}
    
    result = TransactionManager.execute_batch(TEST_PAYLOAD)
    assert result == "Transaction aborted by the user."

@patch('bw_proxy.transaction.WALManager.has_pending_transaction', return_value=False)
@patch('bw_proxy.transaction.HITLManager.authorize_transaction')
@patch('bw_proxy.transaction.SecureSubprocessWrapper.unlock_vault')
def test_transaction_unlock_failure(mock_unlock, mock_auth, mock_wal):
    """Test what happens when the user types the wrong master password."""
    mock_auth.return_value = {"approved": True, "password": bytearray("wrong_password", "utf-8")}
    mock_unlock.side_effect = SecureBWError("Invalid Master Password")
    
    result = TransactionManager.execute_batch(TEST_PAYLOAD)
    assert "Transaction failed during unlock: Invalid Master Password" in result

def test_invalid_payload_rejected():
    """Ensure invalid dictionaries are caught before doing anything."""
    invalid_raw = {"rationale": "bad", "operations": [{"action": "fake"}]}
    result = TransactionManager.execute_batch(invalid_raw)
    assert "Error: Invalid transaction payload" in result

@patch('bw_proxy.transaction.WALManager.has_pending_transaction', return_value=False)
@patch('bw_proxy.transaction.HITLManager.authorize_transaction')
@patch('bw_proxy.transaction.SecureSubprocessWrapper.unlock_vault')
@patch('bw_proxy.transaction.SecureSubprocessWrapper.execute')
@patch('bw_proxy.transaction.SecureSubprocessWrapper.execute_json')
def test_transaction_rollback_lifo(mock_exec_json, mock_exec, mock_unlock, mock_auth, mock_wal):
    """Test that a mid-flight failure triggers compensating actions in reverse (LIFO) order."""
    mock_auth.return_value = {"approved": True, "password": bytearray("pw", "utf-8")}
    mock_unlock.return_value = bytearray("session", "utf-8")
    
    payload = {
        "rationale": "Rollback test",
        "operations": [
            {"action": "rename_item", "target_id": "item1", "new_name": "Renamed"},
            {"action": "create_folder", "name": "F1"},
            {"action": "delete_item", "target_id": "item_fail"}
        ]
    }
    
    def fake_execute_json(args, session_key):
        if args[:2] == ["get", "item"]: 
            uid = args[2]
            return {"id": uid, "name": f"Item_{uid}", "card": {"brand": "visa"}, "fields": [], "reprompt": 0}
        if args[:2] == ["get", "folder"]: return {"id": "f1", "name": "F1"}
        if args[:2] == ["get", "template"]: return {"id": "f_tpl"}
        raise SecureBWError(f"Not found: {args}")
        
    mock_exec_json.side_effect = fake_execute_json
    
    def fake_execute(args, sk):
        if args[0] == "delete" and args[1] == "item" and args[2] == "item_fail":
            raise SecureBWError("Simulated failure")
        if args[0] == "create" and args[1] == "folder":
            return '{"id": "new_folder_uuid"}'
        return ""
        
    mock_exec.side_effect = fake_execute
    
    result = TransactionManager.execute_batch(payload)
    
    assert "CRITICAL: Transaction failed" in result
    assert "A full rollback was successfully performed" in result
    
    calls = [call[0][0] for call in mock_exec.call_args_list]
    assert len(calls) == 6
    
    # Preflight sync + forward execution
    assert calls[0] == ["sync"]
    assert calls[1][0] == "edit" and calls[1][2] == "item1"
    assert calls[2][0] == "create" and calls[2][1] == "folder"
    assert calls[3] == ["delete", "item", "item_fail"]  # Fails here
    
    # LIFO Rollback Execution
    # Rollback #2 (Undo create folder)
    assert calls[4] == ["delete", "folder", "new_folder_uuid"]

    # Rollback #1 (Undo rename item1) — bw edit with original JSON base64-encoded
    import base64
    expected_data = {"id": "item1", "name": "Item_item1", "card": {"brand": "visa"}, "fields": [], "reprompt": 0}
    expected_b64 = base64.b64encode(json.dumps(expected_data).encode()).decode()
    assert calls[5] == ["edit", "item", "item1", expected_b64]


@patch('bw_proxy.transaction.TransactionLogger.log_transaction')
@patch('bw_proxy.transaction.WALManager.has_pending_transaction', return_value=False)
@patch('bw_proxy.transaction.HITLManager.authorize_transaction')
@patch('bw_proxy.transaction.SecureSubprocessWrapper.unlock_vault')
@patch('bw_proxy.transaction.SecureSubprocessWrapper.execute')
@patch('bw_proxy.transaction.SecureSubprocessWrapper.execute_json')
def test_transaction_reports_fatal_when_rollback_itself_fails(
    mock_exec_json,
    mock_exec,
    mock_unlock,
    mock_auth,
    mock_wal,
    mock_log,
):
    """A rollback failure must surface as a fatal inconsistent-state error."""
    mock_auth.return_value = {"approved": True, "password": bytearray("pw", "utf-8")}
    mock_unlock.return_value = bytearray("session", "utf-8")

    payload = {
        "rationale": "Fatal rollback test",
        "operations": [
            {"action": "rename_item", "target_id": "item1", "new_name": "Renamed"},
            {"action": "delete_item", "target_id": "item_fail"},
        ]
    }

    def fake_execute_json(args, session_key):
        if args[:2] == ["get", "item"]:
            uid = args[2]
            return {"id": uid, "name": f"Item_{uid}", "fields": [], "reprompt": 0}
        raise SecureBWError(f"Unexpected get call: {args}")

    mock_exec_json.side_effect = fake_execute_json

    edit_item1_calls = {"count": 0}

    def fake_execute(args, sk):
        if args[:3] == ["delete", "item", "item_fail"]:
            raise SecureBWError("forward failure")
        if args[:3] == ["edit", "item", "item1"]:
            edit_item1_calls["count"] += 1
            if edit_item1_calls["count"] > 1:
                raise SecureBWError("rollback failure")
        return ""

    mock_exec.side_effect = fake_execute

    result = TransactionManager.execute_batch(payload)

    assert "FATAL ERROR" in result
    assert "rollback mechanism also failed" in result
    assert mock_log.call_args.kwargs["status"] == "ROLLBACK_FAILED"

