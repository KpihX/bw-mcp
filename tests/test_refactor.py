import pytest
import base64
import json
from unittest.mock import patch, MagicMock
from bw_mcp.transaction import TransactionManager
from bw_mcp.models import EditAction, RefactorAction, RefactorScope

def test_refactor_move_field():
    # Setup mock items
    source_item = {
        "id": "source-123",
        "name": "Source Item",
        "fields": [
            {"name": "API_KEY", "value": "secret-value-123", "type": 0}
        ]
    }
    dest_item = {
        "id": "dest-456",
        "name": "Dest Item",
        "fields": []
    }
    
    mock_op = MagicMock()
    mock_op.action = EditAction.REFACTOR
    mock_op.refactor_action = RefactorAction.MOVE
    mock_op.source_item_id = "source-123"
    mock_op.dest_item_id = "dest-456"
    mock_op.scope = RefactorScope.FIELD
    mock_op.key = "API_KEY"
    mock_op.dest_key = "NEW_API_KEY"
    
    session_key = bytearray(b"dummy-session")
    
    with patch("bw_mcp.transaction.SecureSubprocessWrapper.get_item_raw") as mock_get, \
         patch("bw_mcp.transaction.SecureSubprocessWrapper.execute") as mock_exec:
        
        # Side effect for get_item_raw
        mock_get.side_effect = [source_item, dest_item]
        
        msg, rollback = TransactionManager._execute_refactor_action(mock_op, session_key)
        
        assert "Refactored (move)" in msg
        assert len(rollback) == 2 # Source edit and Dest edit
        
        # Verify source was modified (API_KEY removed)
        assert len(source_item["fields"]) == 0
        
        # Verify dest was modified (NEW_API_KEY added)
        assert len(dest_item["fields"]) == 1
        assert dest_item["fields"][0]["name"] == "NEW_API_KEY"
        assert dest_item["fields"][0]["value"] == "secret-value-123"

def test_refactor_copy_login_user():
    source_item = {
        "id": "source-123",
        "login": {"username": "kpihx"}
    }
    dest_item = {
        "id": "dest-456",
        "login": {}
    }
    
    mock_op = MagicMock()
    mock_op.action = EditAction.REFACTOR
    mock_op.refactor_action = RefactorAction.COPY
    mock_op.source_item_id = "source-123"
    mock_op.dest_item_id = "dest-456"
    mock_op.scope = RefactorScope.LOGIN_USER
    mock_op.key = "user"
    mock_op.dest_key = None
    
    session_key = bytearray(b"dummy-session")
    
    with patch("bw_mcp.transaction.SecureSubprocessWrapper.get_item_raw") as mock_get, \
         patch("bw_mcp.transaction.SecureSubprocessWrapper.execute") as mock_exec:
        
        mock_get.side_effect = [source_item, dest_item]
        
        msg, rollback = TransactionManager._execute_refactor_action(mock_op, session_key)
        
        assert source_item["login"]["username"] == "kpihx" # Copy keeps it
        assert dest_item["login"]["username"] == "kpihx"

def test_refactor_delete_note():
    source_item = {
        "id": "source-123",
        "notes": "super secret note"
    }
    
    # Use a dummy object with attributes since we use op.action, etc.
    class DummyOp:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
    
    mock_op = DummyOp(
        action=EditAction.REFACTOR,
        refactor_action=RefactorAction.DELETE,
        source_item_id="source-123",
        dest_item_id=None,
        scope=RefactorScope.NOTE,
        key="note",
        dest_key=None
    )
    
    session_key = bytearray(b"dummy-session")
    
    with patch("bw_mcp.transaction.SecureSubprocessWrapper.get_item_raw") as mock_get, \
         patch("bw_mcp.transaction.SecureSubprocessWrapper.execute") as mock_exec:
        
        mock_get.return_value = source_item
        
        msg, rollback = TransactionManager._execute_refactor_action(mock_op, session_key)
        
        assert source_item["notes"] is None
        assert len(rollback) == 1
