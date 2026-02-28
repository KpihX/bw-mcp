import pytest
import json
from unittest.mock import patch, MagicMock
from bw_blind_proxy.transaction import TransactionManager
from bw_blind_proxy.models import TransactionPayload
from bw_blind_proxy.subprocess_wrapper import SecureBWError

# Sample payload mimicking what the LLM generates
TEST_PAYLOAD = {
    "rationale": "Test coverage",
    "operations": [
        {"action": "rename_item", "target_id": "1", "new_name": "New"},
        {"action": "create_folder", "name": "Folder 1"},
        {"action": "delete_folder", "target_id": "99"},
        {"action": "delete_item", "target_id": "1"},
        {"action": "edit_item_card", "target_id": "1", "expYear": "2030"},
        {"action": "upsert_custom_field", "target_id": "1", "name": "Key", "value": "Val", "type": 0},
        {"action": "restore_item", "target_id": "1"},
        {"action": "toggle_reprompt", "target_id": "1", "reprompt": True}
    ]
}

@patch('bw_blind_proxy.transaction.HITLManager.review_transaction')
@patch('bw_blind_proxy.transaction.HITLManager.ask_master_password')
@patch('bw_blind_proxy.transaction.SecureSubprocessWrapper.unlock_vault')
@patch('bw_blind_proxy.transaction.SecureSubprocessWrapper.execute')
@patch('bw_blind_proxy.transaction.SecureSubprocessWrapper.execute_json')
def test_full_transaction_batch_execution(mock_exec_json, mock_exec, mock_unlock, mock_ask_pw, mock_review):
    """Mocks all HITL and Subprocess dependencies to rigorously test the Transaction routing engine."""
    
    # Setup mocks
    mock_review.return_value = True
    mock_ask_pw.return_value = "fake_master_password"
    mock_unlock.return_value = "fake_session_key_12345"
    
    # Mock the JSON returns for get operations (Item Get, Folder Template, Item Get)
    mock_exec_json.side_effect = [
        {"name": "OldName"}, # For rename_item
        {"name": "TemplateFolder"}, # For create_folder
        {"name": "CardItem", "card": {"brand": "visa"}}, # For edit_item_card
        {"name": "FieldItem", "fields": []}, # For upsert custom field
        {"name": "RepromptItem", "reprompt": 0}, # For toggle_reprompt
    ]

    # Run the big batch
    result = TransactionManager.execute_batch(TEST_PAYLOAD)
    
    # Assertions
    assert "Transaction completed successfully" in result
    assert mock_review.call_count == 1
    assert mock_ask_pw.call_count == 1
    assert mock_unlock.call_count == 1
    
    # 8 operations total means execute was called 8 times (either direct or post-edit)
    assert mock_exec.call_count == 8

@patch('bw_blind_proxy.transaction.HITLManager.review_transaction')
def test_transaction_aborted_by_user(mock_review):
    """Test what happens when a user clicks 'No' or closes the Zenity popup."""
    mock_review.return_value = False
    result = TransactionManager.execute_batch(TEST_PAYLOAD)
    assert result == "Transaction aborted by the user."

@patch('bw_blind_proxy.transaction.HITLManager.review_transaction')
@patch('bw_blind_proxy.transaction.HITLManager.ask_master_password')
@patch('bw_blind_proxy.transaction.SecureSubprocessWrapper.unlock_vault')
def test_transaction_unlock_failure(mock_unlock, mock_ask, mock_review):
    """Test what happens when the user types the wrong master password."""
    mock_review.return_value = True
    mock_ask.return_value = "wrong_password"
    mock_unlock.side_effect = SecureBWError("Invalid Master Password")
    
    result = TransactionManager.execute_batch(TEST_PAYLOAD)
    assert "Transaction failed during unlock: Invalid Master Password" in result

def test_invalid_payload_rejected():
    """Ensure invalid dictionaries are caught before doing anything."""
    invalid_raw = {"rationale": "bad", "operations": [{"action": "fake"}]}
    result = TransactionManager.execute_batch(invalid_raw)
    assert "Error: Invalid transaction payload" in result

@patch('bw_blind_proxy.transaction.HITLManager.review_transaction')
@patch('bw_blind_proxy.transaction.HITLManager.ask_master_password')
@patch('bw_blind_proxy.transaction.SecureSubprocessWrapper.unlock_vault')
@patch('bw_blind_proxy.transaction.SecureSubprocessWrapper.execute')
@patch('bw_blind_proxy.transaction.SecureSubprocessWrapper.execute_json')
def test_transaction_rollback_lifo(mock_exec_json, mock_exec, mock_unlock, mock_ask, mock_review):
    """Test that a mid-flight failure triggers compensating actions in reverse (LIFO) order."""
    mock_review.return_value = True
    mock_ask.return_value = "pw"
    mock_unlock.return_value = "session"
    
    payload = {
        "rationale": "Rollback test",
        "operations": [
            {"action": "rename_item", "target_id": "item1", "new_name": "Renamed"},
            {"action": "create_folder", "name": "F1"},
            {"action": "delete_folder", "target_id": "fail_folder"}
        ]
    }
    
    mock_exec_json.side_effect = [
        {"id": "item1", "name": "Original"}, # For rename (safe_edit_item calls get item)
        {"id": "f_tpl"},                     # For create folder (get template)
    ]
    
    def fake_execute(args, sk):
        if args[0] == "delete" and args[1] == "folder" and args[2] == "fail_folder":
            raise SecureBWError("Simulated failure")
        if args[0] == "create" and args[1] == "folder":
            return '{"id": "new_folder_uuid"}'
        return ""
        
    mock_exec.side_effect = fake_execute
    
    result = TransactionManager.execute_batch(payload)
    
    assert "CRITICAL: Transaction failed" in result
    assert "A full rollback was successfully performed" in result
    assert "Simulated failure" in result
    
    calls = [call[0][0] for call in mock_exec.call_args_list]
    assert len(calls) == 5
    
    # Forward execution
    assert calls[0][0] == "edit" and calls[0][2] == "item1"
    assert calls[1][0] == "create" and calls[1][1] == "folder"
    assert calls[2] == ["delete", "folder", "fail_folder"] # Fails here
    
    # LIFO Rollback Execution
    # Rollback #2 (Undo create folder)
    assert calls[3] == ["delete", "folder", "new_folder_uuid"]
    
    # Rollback #1 (Undo rename)
    assert calls[4] == ["edit", "item", "item1", '{"id": "item1", "name": "Original"}']
