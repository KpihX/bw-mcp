import pytest
from unittest.mock import patch, MagicMock
from bw_proxy.subprocess_wrapper import SecureSubprocessWrapper, SecureBWError
from bw_proxy.logic import find_item_duplicates, compare_secrets_batch
from bw_proxy.models import FindDuplicatesPayload, BatchComparePayload, CompareSecretRequest
import json
import base64

@patch('bw_proxy.vault_runtime.load_bw_status', return_value={"status": "locked", "serverUrl": "https://vault.example.com", "userEmail": "agent@example.com"})
@patch('bw_proxy.vault_runtime.validate_authenticated_context', return_value=None)
@patch('bw_proxy.logic.TransactionManager.check_recovery', return_value=None)
@patch('bw_proxy.logic.SecureSubprocessWrapper.unlock_vault')
@patch('bw_proxy.logic.SecureSubprocessWrapper.execute', return_value="")
@patch('bw_proxy.logic.SecureSubprocessWrapper.execute_json')
@patch('bw_proxy.logic.SecureSubprocessWrapper.audit_bulk_compare')
@patch('bw_proxy.logic.HITLManager.ask_master_password')
@patch('bw_proxy.logic.HITLManager.authorize_duplicate_scan')
def test_find_item_duplicates_tool(mock_authorize, mock_ask, mock_bulk, mock_exec_json, mock_exec, mock_unlock, mock_recovery, mock_validate, mock_status):
    """Test the find_item_duplicates tool flow."""
    mock_ask.return_value = bytearray("pw", "utf-8")
    mock_unlock.return_value = bytearray("session", "utf-8")
    
    # Mock list items to find candidates of same type
    mock_exec_json.side_effect = [
        [
            {"id": "target", "name": "Target", "type": 1},
            {"id": "cand1", "name": "Cand1", "type": 1},
            {"id": "cand2", "name": "Cand2", "type": 1},
            {"id": "other", "name": "Other", "type": 2},
        ],
        {"id": "target", "type": 1} # for get item target
    ]
    
    mock_authorize.return_value = {"approved": True, "password": bytearray("pw", "utf-8")}
    mock_bulk.return_value = ["cand1"] # Only cand1 matches
    
    payload = FindDuplicatesPayload(
        rationale="Cleanup",
        target_id="target",
        field="login.password"
    )
    
    res = find_item_duplicates(payload)
    
    assert res["status"] == "success"
    assert res["duplicate_ids"] == ["cand1"]
    assert res["scan_size"] == 2 # cand1 and cand2 are type 1

def test_audit_dynamic_field_resolution():
    """Verify that subprocess wrapper extracts dynamic fields correctly."""
    session_key = bytearray("fake", "utf-8")
    
    # Test valid dynamic field whitelist
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(returncode=0) # Match
        res = SecureSubprocessWrapper.audit_compare_secrets(
            "12345678-1234-1234-1234-123456789012", "fields.MISTRAL_API_KEY", None,
            "12345678-1234-1234-1234-123456789012", "login.password", None,
            session_key
        )
        assert res is True

    # Test invalid namespace
    with pytest.raises(SecureBWError) as exc:
        SecureSubprocessWrapper.audit_compare_secrets(
            "12345678-1234-1234-1234-123456789012", "malicious.path", None,
            "12345678-1234-1234-1234-123456789012", "login.password", None,
            session_key
        )
    assert "Invalid field target namespace" in str(exc.value)

@patch('bw_proxy.vault_runtime.load_bw_status', return_value={"status": "locked", "serverUrl": "https://vault.example.com", "userEmail": "agent@example.com"})
@patch('bw_proxy.vault_runtime.validate_authenticated_context', return_value=None)
@patch('bw_proxy.logic.TransactionManager.check_recovery', return_value=None)
@patch('bw_proxy.logic.SecureSubprocessWrapper.unlock_vault')
@patch('bw_proxy.logic.SecureSubprocessWrapper.execute', return_value="")
@patch('bw_proxy.logic.SecureSubprocessWrapper.execute_json')
@patch('bw_proxy.logic.SecureSubprocessWrapper.audit_compare_secrets')
@patch('bw_proxy.logic.HITLManager.ask_master_password')
@patch('bw_proxy.logic.HITLManager.authorize_comparisons')
def test_compare_secrets_batch_v2(mock_authorize, mock_ask, mock_compare, mock_exec_json, mock_exec, mock_unlock, mock_recovery, mock_validate, mock_status):
    """Test that batch compare now accepts dynamic strings."""
    mock_ask.return_value = bytearray("pw", "utf-8")
    mock_unlock.return_value = bytearray("session", "utf-8")
    mock_exec_json.return_value = []
    mock_authorize.return_value = {"approved": True, "password": bytearray("pw", "utf-8")}
    mock_compare.return_value = True
    
    payload = BatchComparePayload(
        rationale="Test",
        comparisons=[
            CompareSecretRequest(
                item_id_a="idA", field_a="notes",
                item_id_b="idB", field_b="fields.HIDDEN"
            )
        ]
    )
    
    res = compare_secrets_batch(payload)
    assert res["status"] == "success"
    assert res["results"][0]["field_a"] == "notes"
    assert res["results"][0]["field_b"] == "fields.HIDDEN"
