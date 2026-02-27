import pytest
from pydantic import ValidationError
from bw_blind_proxy.models import TransactionPayload, BlindItem, ItemAction, FolderAction

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
    """Ensure Phase 4 Extreme Edge Actions (Restore, Reprompt, Attachments) parse correctly."""
    raw = {
        "rationale": "Deep organizational operations",
        "operations": [
            {"action": "restore_item", "target_id": "test-id"},
            {"action": "toggle_reprompt", "target_id": "test-id", "reprompt": True},
            {"action": "delete_attachment", "target_id": "test-id", "attachment_id": "attach-99"},
            {"action": "move_to_collection", "target_id": "test-id", "organization_id": "org-55"}
        ]
    }
    payload = TransactionPayload(**raw)
    assert len(payload.operations) == 4
    assert payload.operations[0].action == ItemAction.RESTORE
    assert payload.operations[1].reprompt is True
    assert payload.operations[2].attachment_id == "attach-99"
    assert payload.operations[3].organization_id == "org-55"

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
    assert item.identity.ssn == "[REDACTED_BY_PROXY]"
    assert item.identity.passportNumber == "[REDACTED_BY_PROXY]"

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
    assert item.fields[1].value == "[REDACTED_BY_PROXY]"
