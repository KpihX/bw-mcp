from unittest.mock import patch

from bw_proxy.models import (
    DeleteFolderAction,
    EditItemLoginAction,
    RenameItemAction,
    RestoreItemAction,
    TransactionPayload,
    UpsertCustomFieldAction,
)
from bw_proxy.ui import HITLManager


def test_ui_format_operations():
    """Every polymorphic action should render into a stable human-readable summary."""
    op_rename = RenameItemAction(target_id="1", new_name="A")
    op_restore = RestoreItemAction(target_id="2")
    op_field = UpsertCustomFieldAction(target_id="3", name="API Key", value="sk_123", type=0)
    op_del = DeleteFolderAction(target_id="4")
    op_login = EditItemLoginAction(target_id="5", username="user@foo.com")

    id_map = {"1": "Item A", "4": "Bad Folder"}

    assert "✏️ RENAME ITEM 'Item A' (1) ->" in HITLManager._format_operation(op_rename, id_map)
    assert "♻️ RESTORE ITEM (2) -> From Trash" in HITLManager._format_operation(op_restore, id_map)
    assert "🏷️ UPSERT FIELD (3) -> 'API Key' = 'sk_123'" in HITLManager._format_operation(op_field, id_map)
    assert "💥 DELETE FOLDER 'Bad Folder' (4)" in HITLManager._format_operation(op_del, id_map)
    assert "🔧 EDIT LOGIN (5) -> username='user@foo.com'" in HITLManager._format_operation(op_login, id_map)


def test_serialize_operation_details_includes_raw_json_and_resolved_ids():
    op = RenameItemAction(target_id="item-1", new_name="Renamed")

    details = HITLManager._serialize_operation_details(op, {"item-1": "Visible Name"})

    assert details["action"] == "rename_item"
    assert "Visible Name" in details["summary"]
    assert '"target_id": "item-1"' in details["raw_json"]
    assert details["resolved_refs"] == [
        {"field": "target_id", "id": "item-1", "name": "Visible Name"}
    ]


@patch("bw_proxy.ui.WebHITLManager.request_approval")
def test_review_transaction_uses_transparent_web_payload_without_second_password(mock_request):
    payload = TransactionPayload(
        rationale="Deleting a folder",
        operations=[DeleteFolderAction(target_id="folder-1")],
    )
    mock_request.return_value = {"approved": True}

    approved = HITLManager.review_transaction(payload, {"folder-1": "Bad Folder"})

    assert approved is True
    web_data = mock_request.call_args.args[0]
    assert web_data["type"] == "transaction"
    assert web_data["flow"] == "review"
    assert web_data["has_destructive"] is True
    assert "Nothing is executed while you inspect this page." in web_data["review_notice"]
    assert web_data["operations_details"][0]["resolved_refs"] == [
        {"field": "target_id", "id": "folder-1", "name": "Bad Folder"}
    ]
    assert '"target_id": "folder-1"' in web_data["operations_details"][0]["raw_json"]


@patch("bw_proxy.ui.WebHITLManager.request_approval")
def test_ask_input_returns_browser_text_value(mock_request):
    mock_request.return_value = {"approved": True, "input_text": "https://vault.example.com"}

    value = HITLManager.ask_input("Bitwarden Server URL", "Setup URL")

    assert value == "https://vault.example.com"
    web_data = mock_request.call_args.args[0]
    assert web_data["flow"] == "prompt"
    assert web_data["input_kind"] == "text"


@patch("bw_proxy.ui.WebHITLManager.request_approval")
def test_ask_master_password_uses_prompt_only_flow(mock_request):
    mock_request.return_value = {"approved": True, "password": bytearray(b"pw")}

    password = HITLManager.ask_master_password("Unlock Vault")

    assert password == bytearray(b"pw")
    web_data = mock_request.call_args.args[0]
    assert web_data["flow"] == "prompt"
    assert web_data["input_kind"] == "password"
