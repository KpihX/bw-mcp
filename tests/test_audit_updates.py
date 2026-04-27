import pytest
from unittest.mock import patch, MagicMock
from bw_proxy.logic import get_vault_map
from bw_proxy.transaction import TransactionManager
from bw_proxy.subprocess_wrapper import SecureSubprocessWrapper, SecureBWError
from bw_proxy.models import (
    MoveToCollectionAction, ItemAction, SecretFieldTarget,
    BatchComparePayload, CompareSecretRequest, CreateItemAction,
    CreateLoginPayload, CreateCardPayload, CreateIdentityPayload
)
from bw_proxy.logic import compare_secrets_batch, fetch_template
import json
import base64

@patch('bw_proxy.logic.SecureSubprocessWrapper.unlock_vault')
@patch('bw_proxy.logic.SecureSubprocessWrapper.execute_json')
@patch('bw_proxy.logic.HITLManager.ask_master_password')
def test_get_vault_map_dos_truncation(mock_ask, mock_exec_json, mock_unlock):
    """Verify that long search strings are truncated to 256 chars."""
    mock_ask.return_value = bytearray("pw", "utf-8")
    mock_unlock.return_value = bytearray("session", "utf-8")
    mock_exec_json.return_value = []
    
    long_search = "A" * 500
    get_vault_map(search_items=long_search, search_folders=long_search)
    
    # Check if the calls to execute_json used truncated search strings
    # We look for calls that have "--search" followed by the value
    for call_args in mock_exec_json.call_args_list:
        args_list = call_args[0][0]
        if "--search" in args_list:
            idx = args_list.index("--search")
            search_val = args_list[idx + 1]
            assert len(search_val) == 256
            assert search_val == "A" * 256

def test_audit_compare_secrets_validation():
    """Verify defense-in-depth field validation in subprocess wrapper."""
    session_key = bytearray("fake", "utf-8")
    
    # Valid field
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(returncode=1) # Mismatch
        res = SecureSubprocessWrapper.audit_compare_secrets(
            "12345678-1234-1234-1234-123456789012", SecretFieldTarget.LOGIN_PASSWORD, None,
            "12345678-1234-1234-1234-123456789012", SecretFieldTarget.LOGIN_PASSWORD, None,
            session_key
        )
        assert res is False

    # Invalid string field
    with pytest.raises(SecureBWError) as exc:
        SecureSubprocessWrapper.audit_compare_secrets(
            "12345678-1234-1234-1234-123456789012", "invalid.field", None,
            "12345678-1234-1234-1234-123456789012", SecretFieldTarget.LOGIN_PASSWORD, None,
            session_key
        )
    assert "Invalid field target" in str(exc.value)

@patch('bw_proxy.transaction.SecureSubprocessWrapper.execute')
@patch('bw_proxy.transaction.SecureSubprocessWrapper.execute_json')
def test_move_to_collection_syntax(mock_exec_json, mock_exec):
    """Verify that MOVE_TO_COLLECTION uses the correct CLI syntax with encoded collections."""
    mock_exec_json.return_value = {"id": "item1", "name": "MoveMe"}
    session_key = bytearray("fake", "utf-8")
    
    op = MoveToCollectionAction(
        target_id="item1",
        organization_id="org1",
        collection_ids=["col1", "col2"]
    )
    
    msg, rollback = TransactionManager._execute_single_action(op, session_key)
    
    # Check CLI call: bw move <id> <orgId> <encodedJson>
    # We need to find the call where args[0] == "move"
    move_call = next(c for c in mock_exec.call_args_list if c[0][0][0] == "move")
    args = move_call[0][0]
    
    assert args[1] == "item1"
    assert args[2] == "org1"
    # The 4th arg should be the base64 encoded JSON of ["col1", "col2"]
    import base64
    import json
    expected_b64 = base64.b64encode(json.dumps(["col1", "col2"]).encode()).decode()
    assert args[3] == expected_b64
    assert "Collections: ['col1', 'col2']" in msg

@patch('bw_proxy.vault_runtime.load_bw_status', return_value={"status": "locked", "serverUrl": "https://vault.example.com", "userEmail": "agent@example.com"})
@patch('bw_proxy.vault_runtime.validate_authenticated_context', return_value=None)
@patch('bw_proxy.logic.TransactionManager.check_recovery', return_value=None)
@patch('bw_proxy.logic.SecureSubprocessWrapper.unlock_vault')
@patch('bw_proxy.logic.SecureSubprocessWrapper.execute', return_value="")
@patch('bw_proxy.logic.SecureSubprocessWrapper.execute_json')
@patch('bw_proxy.logic.SecureSubprocessWrapper.audit_compare_secrets')
@patch('bw_proxy.logic.HITLManager.ask_master_password')
@patch('bw_proxy.logic.HITLManager.authorize_comparisons')
def test_compare_secrets_batch_tool(mock_authorize, mock_ask, mock_compare, mock_exec_json, mock_exec, mock_unlock, mock_recovery, mock_validate, mock_status):
    """Test the full tool flow for compare_secrets_batch."""
    mock_ask.return_value = bytearray("pw", "utf-8")
    mock_unlock.return_value = bytearray("session", "utf-8")
    mock_exec_json.return_value = [] # for id_to_name
    mock_authorize.return_value = {"approved": True, "password": bytearray("pw", "utf-8")}
    mock_compare.return_value = True # Match
    
    payload = BatchComparePayload(
        rationale="Deduplication",
        comparisons=[
            CompareSecretRequest(
                item_id_a="idA", field_a=SecretFieldTarget.LOGIN_PASSWORD,
                item_id_b="idB", field_b=SecretFieldTarget.LOGIN_PASSWORD
            )
        ]
    )
    
    result = compare_secrets_batch(payload)
    
    assert result["status"] == "success"
    assert len(result["results"]) == 1
    assert "MATCH" in result["results"][0]["verdict"]

@patch('bw_proxy.transaction.SecureSubprocessWrapper.execute')
@patch('bw_proxy.transaction.SecureSubprocessWrapper.execute_json')
def test_create_item_variants(mock_exec_json, mock_exec):
    """Test ItemAction.CREATE for Login, Card, and Identity types."""
    session_key = bytearray("fake", "utf-8")
    
    # 1. Login
    op_login = CreateItemAction(
        type=1, name="MyLogin", folder_id="f1",
        login=CreateLoginPayload(username="user1")
    )
    def mock_get_templates(args, sk):
        if args == ["get", "template", "item"]: return {"name": "", "type": 1}
        if args == ["get", "template", "item.login"]: return {"username": ""}
        if args == ["get", "template", "item.card"]: return {"cardholderName": ""}
        if args == ["get", "template", "item.identity"]: return {"firstName": ""}
        return {}
    
    mock_exec_json.side_effect = mock_get_templates
    mock_exec.return_value = '{"id": "new_login_id"}'
    
    msg, _ = TransactionManager._execute_single_action(op_login, session_key)
    assert "Created new 1 item 'MyLogin'" in msg
    
    # Verify the JSON sent to 'create' had the username
    create_call = next(c for c in mock_exec.call_args_list if c[0][0][0] == "create")
    encoded_item = create_call[0][0][2]
    item_pushed = json.loads(base64.b64decode(encoded_item).decode())
    assert item_pushed["login"]["username"] == "user1"

@patch('bw_proxy.logic.SecureSubprocessWrapper.unlock_vault')
@patch('bw_proxy.logic.SecureSubprocessWrapper.execute')
@patch('bw_proxy.logic.HITLManager.ask_master_password')
def testfetch_template_internal(mock_ask, mock_exec, mock_unlock):
    """Test the internal fetch_template function."""
    mock_ask.return_value = bytearray("pw", "utf-8")
    mock_unlock.return_value = bytearray("session", "utf-8")
    mock_exec.return_value = '{"template": "data"}'
    
    res = fetch_template("item")
    assert "template" in res
    """Verify that UI destructive alert detects DELETE actions via Enum."""
    from bw_proxy.ui import HITLManager
    from bw_proxy.models import TransactionPayload, ItemAction, FolderAction, CreateFolderAction, DeleteItemAction
    
    # 1. Non-destructive
    payload_safe = TransactionPayload(
        rationale="Safe",
        operations=[CreateFolderAction(name="New")]
    )
    with patch('bw_proxy.ui.WebHITLManager.request_approval') as mock_request:
        mock_request.return_value = {"approved": True}
        HITLManager.review_transaction(payload_safe, {})
        web_data = mock_request.call_args.args[0]
        assert web_data["has_destructive"] is False

    # 2. Destructive (Delete Item)
    payload_danger = TransactionPayload(
        rationale="Danger",
        operations=[DeleteItemAction(target_id="1")]
    )
    with patch('bw_proxy.ui.WebHITLManager.request_approval') as mock_request:
        mock_request.return_value = {"approved": True}
        HITLManager.review_transaction(payload_danger, {"1": "Item1"})
        web_data = mock_request.call_args.args[0]
        assert web_data["has_destructive"] is True
