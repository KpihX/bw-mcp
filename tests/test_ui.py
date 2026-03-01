import pytest
from bw_blind_proxy.ui import HITLManager
from bw_blind_proxy.models import (
    TransactionPayload, 
    RenameItemAction, 
    RestoreItemAction,
    UpsertCustomFieldAction,
    DeleteFolderAction,
    EditItemLoginAction
)

def test_ui_format_operations():
    """Verify that every polymorphic action renders beautifully without crashing."""
    op_rename = RenameItemAction(target_id="1", new_name="A")
    op_restore = RestoreItemAction(target_id="2")
    op_field = UpsertCustomFieldAction(target_id="3", name="API Key", value="sk_123", type=0)
    op_del = DeleteFolderAction(target_id="4")
    op_login = EditItemLoginAction(target_id="5", username="user@foo.com")
    
    id_map = {"1": "Item A", "4": "Bad Folder"}
    
    assert "✏️ RENAME ITEM 'Item A' -> 'A'" in HITLManager._format_operation(op_rename, id_map)
    assert "♻️ RESTORE ITEM (2) -> From Trash" in HITLManager._format_operation(op_restore, id_map)
    assert "🏷️ UPSERT FIELD (3) -> [Text] 'API Key' = 'sk_123'" in HITLManager._format_operation(op_field, id_map)
    assert "💥 DELETE FOLDER 'Bad Folder'" in HITLManager._format_operation(op_del, id_map)
    assert "🔧 EDIT LOGIN (5) -> Username='user@foo.com'" in HITLManager._format_operation(op_login, id_map)

from unittest.mock import patch, MagicMock

def test_ui_contains_destructive_alert():
    """Ensure the RED ALERT logic triggers properly on delete actions."""
    # delete_folder must be standalone — use a single-op batch
    payload = TransactionPayload(
        rationale="Deleting a folder",
        operations=[DeleteFolderAction(target_id="2")]
    )
    
    with patch('bw_blind_proxy.ui.subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        
        HITLManager.review_transaction(payload)
        
        # Verify it passed the warning dialog
        call_args = mock_run.call_args[0][0]
        assert "zenity" in call_args
        assert "--question" in call_args
        assert "--icon-name=dialog-warning" in call_args
        assert any("DESTRUCTIVE OPERATIONS DETECTED" in arg for arg in call_args)

def test_ui_no_destructive_alert():
    """Ensure safe operations only trigger a standard question."""
    payload = TransactionPayload(
        rationale="Safe renames",
        operations=[RenameItemAction(target_id="1", new_name="Safe")]
    )
    
    with patch('bw_blind_proxy.ui.subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        
        HITLManager.review_transaction(payload)
        
        call_args = mock_run.call_args[0][0]
        assert "zenity" in call_args
        assert "--question" in call_args
        assert "--icon-name=dialog-warning" not in call_args
