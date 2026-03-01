import pytest
from pydantic import ValidationError
from bw_blind_proxy.models import TransactionPayload, BlindItem, ItemAction, FolderAction
from bw_blind_proxy.config import REDACTED_POPULATED, REDACTED_EMPTY

def test_valid_polymorphic_payload():
    """Ensure standard operations parse perfectly using strings matching Enum values."""
    raw = {
        "rationale": "Just renaming and moving",
        "operations": [
            {"action": "rename_item", "target_id": "123", "new_name": "NewName"},
            {"action": "move_item", "target_id": "123", "folder_id": "999"},
            {"action": "favorite_item", "target_id": "123", "favorite": True}
        ]
    }
    payload = TransactionPayload(**raw)
    assert len(payload.operations) == 3
    # Pydantic successfully parses "rename_item" string to ItemAction.RENAME StrEnum internally,
    # or keeps the string depending on StrEnum behavior, but we use equality natively.
    assert payload.operations[0].action == ItemAction.RENAME
    assert payload.operations[2].action == ItemAction.FAVORITE

def test_extreme_edge_actions():
    """Ensure Phase 4 Extreme Edge Actions (Restore, Reprompt) parse correctly."""
    raw = {
        "rationale": "Deep organizational operations",
        "operations": [
            {"action": "restore_item", "target_id": "test-id"},
            {"action": "toggle_reprompt", "target_id": "test-id", "reprompt": True},
            {"action": "move_to_collection", "target_id": "test-id", "organization_id": "org-55"},
        ]
    }
    payload = TransactionPayload(**raw)
    assert len(payload.operations) == 3
    assert payload.operations[0].action == ItemAction.RESTORE
    assert payload.operations[1].reprompt is True
    assert payload.operations[2].organization_id == "org-55"


def test_delete_folder_must_be_standalone():
    """Ensure that delete_folder is always rejected when bundled with other actions."""
    raw_invalid = {
        "rationale": "Trying to rename + delete folder in one shot",
        "operations": [
            {"action": "rename_item", "target_id": "item-id", "new_name": "Renamed"},
            {"action": "delete_folder", "target_id": "folder-id"}
        ]
    }
    with pytest.raises(Exception) as exc_info:
        TransactionPayload(**raw_invalid)
    assert "delete_folder" in str(exc_info.value).lower() or "disruptive" in str(exc_info.value).lower()


def test_delete_folder_standalone_is_valid():
    """Ensure that delete_folder is accepted when alone in the batch."""
    raw = {
        "rationale": "Cleaning up an empty folder.",
        "operations": [
            {"action": "delete_folder", "target_id": "folder-id"}
        ]
    }
    payload = TransactionPayload(**raw)
    assert len(payload.operations) == 1
    assert payload.operations[0].action == FolderAction.DELETE

def test_delete_attachment_must_be_standalone():
    """Ensure that the proxy fiercely rejects grouping delete_attachment with other actions."""
    raw_invalid = {
        "rationale": "I am trying to rename and then delete an attachment",
        "operations": [
            {"action": "rename_item", "target_id": "test-id", "new_name": "My Cleaned Item"},
            {"action": "delete_attachment", "target_id": "test-id", "attachment_id": "attach-99"}
        ]
    }
    
    with pytest.raises(ValidationError) as exc_info:
        TransactionPayload(**raw_invalid)
        
    assert "UNRECOVERABLE" in str(exc_info.value)

def test_delete_attachment_standalone_success():
    """Ensure that executing delete_attachment strictly alone passes validation."""
    raw_valid = {
        "rationale": "Deleting old tax returns",
        "operations": [
            {"action": "delete_attachment", "target_id": "test-id", "attachment_id": "attach-99"}
        ]
    }
    
    payload = TransactionPayload(**raw_valid)
    assert len(payload.operations) == 1
    assert payload.operations[0].action == ItemAction.DELETE_ATTACHMENT
    assert payload.operations[0].attachment_id == "attach-99"

def test_create_item_forbids_secrets():
    """Ensure that creating a shell item explicitly rejects password or other secrets."""
    raw = {
        "rationale": "Creating a login but trying to inject a password",
        "operations": [
            {
                "action": "create_item",
                "type": 1,
                "name": "My New Login",
                "login": {
                    "username": "foo",
                    "password": "I_AM_A_ROUGE_AI"
                }
            }
        ]
    }
    
    with pytest.raises(ValidationError) as exc:
        TransactionPayload(**raw)
    assert "Extra inputs are not permitted" in str(exc.value)

def test_create_item_valid_shell():
    """Ensure valid shell creation bypasses validation."""
    raw = {
        "rationale": "Safe empty shell",
        "operations": [
            {
                "action": "create_item",
                "type": 1,
                "name": "Safe Login",
                "login": {
                    "username": "safe_user"
                }
            }
        ]
    }
    payload = TransactionPayload(**raw)
    assert payload.operations[0].action == ItemAction.CREATE
    assert payload.operations[0].login.username == "safe_user"

def test_edit_login_forbids_password():
    """Ensure that editing a login explicitly rejects password updates."""
    raw = {
        "rationale": "Evil AI",
        "operations": [
            {
                "action": "edit_item_login",
                "target_id": "123",
                "username": "hacker",
                "password": "I_CHANGED_YOUR_PASSWORD"
            }
        ]
    }
    
    with pytest.raises(ValidationError) as exc:
        TransactionPayload(**raw)
    assert "Extra inputs are not permitted" in str(exc.value)

def test_edit_card_forbids_cvv():
    """Ensure that editing a card explicitly rejects CVV/Number updates."""
    raw = {
        "rationale": "Changing expiry",
        "operations": [
            {
                "action": "edit_item_card",
                "target_id": "123",
                "expYear": "2030",
                "code": "111" # Malicious CVV edit
            }
        ]
    }
    
    with pytest.raises(ValidationError) as exc:
        TransactionPayload(**raw)
    assert "Extra inputs are not permitted" in str(exc.value)

def test_upsert_custom_field_forbids_hidden_types():
    """Ensure that the AI cannot create a Hidden (type 1) or Linked (type 3) field."""
    raw = {
        "rationale": "Burying a secret password in a custom field",
        "operations": [
            {
                "action": "upsert_custom_field",
                "target_id": "123",
                "name": "SecretKey",
                "value": "supersecret",
                "type": 1 # Forbiden! Only 0 (text) and 2 (boolean) allowed.
            }
        ]
    }
    
    with pytest.raises(ValidationError) as exc:
        TransactionPayload(**raw)
    assert "Input should be 0 or 2" in str(exc.value)

def test_sanitization_identity_ssn():
    """Ensure BlindIdentity redacts SSN but keeps public fields."""
    raw_item = {
        "id": "abc",
        "type": 4, # Identity
        "name": "My Identity",
        "identity": {
            "firstName": "Ivann",
            "ssn": "123-456-789",
            "passportNumber": "FR-999"
        }
    }
    item = BlindItem(**raw_item)
    assert item.identity.firstName == "Ivann"
    assert item.identity.ssn == REDACTED_POPULATED
    assert item.identity.passportNumber == REDACTED_POPULATED

def test_sanitization_custom_fields():
    """Ensure BlindField protects hidden values."""
    raw_item = {
        "id": "abc",
        "type": 1,
        "name": "Login",
        "fields": [
            {"name": "Public Text", "value": "Visible", "type": 0},
            {"name": "Hidden API Key", "value": "sk_live_12345", "type": 1}
        ]
    }
    item = BlindItem(**raw_item)
    assert item.fields[0].value == "Visible"
    assert item.fields[1].value == REDACTED_POPULATED


def test_batch_too_large_rejected():
    """Ensure that a batch exceeding MAX_BATCH_SIZE is rejected with a clear error."""
    from bw_blind_proxy.config import MAX_BATCH_SIZE
    # Build a batch of MAX_BATCH_SIZE + 1 operations (all simple renames)
    operations = [
        {"action": "rename_item", "target_id": f"id-{i}", "new_name": f"Item {i}"}
        for i in range(MAX_BATCH_SIZE + 1)
    ]
    raw = {
        "rationale": "Trying to rename too many items at once",
        "operations": operations
    }
    with pytest.raises(ValidationError) as exc_info:
        TransactionPayload(**raw)
    assert "BATCH TOO LARGE" in str(exc_info.value)


def test_batch_at_limit_ok():
    """Ensure that a batch exactly at MAX_BATCH_SIZE passes validation."""
    from bw_blind_proxy.config import MAX_BATCH_SIZE
    # Build a batch of exactly MAX_BATCH_SIZE operations
    operations = [
        {"action": "rename_item", "target_id": f"id-{i}", "new_name": f"Item {i}"}
        for i in range(MAX_BATCH_SIZE)
    ]
    raw = {
        "rationale": "Renaming exactly the max number of items",
        "operations": operations
    }
    # Should not raise — exactly at the boundary is allowed
    payload = TransactionPayload(**raw)
    assert len(payload.operations) == MAX_BATCH_SIZE

