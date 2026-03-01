import pytest
import base64
from bw_mcp.models import (
    BlindItem, BlindLogin, BlindFolder, BlindOrganization,
    BlindCard, BlindField
)
from bw_mcp.config import REDACTED_POPULATED, REDACTED_EMPTY
from bw_mcp.subprocess_wrapper import _sanitize_args_for_log


# ====================================================================
# TESTS: Structural Command Redactor (_sanitize_args_for_log)
# ====================================================================

def test_redactor_keeps_safe_verb_and_object():
    """Whitelisted verbs and object types must pass through untouched."""
    result = _sanitize_args_for_log(["edit", "item"])
    assert result == "edit item"


def test_redactor_keeps_standalone_uuid():
    """A UUID in the target_id position is safe metadata and must be kept."""
    uuid = "90613f85-8604-4058-8ba2-fba512b97ef5"
    result = _sanitize_args_for_log(["get", "item", uuid])
    assert result == f"get item {uuid}"


def test_redactor_atomizes_raw_json_payload():
    """Raw JSON containing a password must become [PAYLOAD], even if it's short."""
    raw_json = '{"name": "Venice", "password": "abc"}'  # 37 chars — naive len<40 would KEEP this!
    result = _sanitize_args_for_log(["edit", "item", "uuid-1234", raw_json])
    assert "[PAYLOAD]" in result
    assert "password" not in result
    assert "abc" not in result


def test_redactor_atomizes_base64_payload():
    """A base64-encoded JSON blob (the normal edit/create payload) must be [PAYLOAD]."""
    b64 = base64.b64encode(b'{"password": "super_secret"}').decode()
    result = _sanitize_args_for_log(["create", "item", b64])
    assert "[PAYLOAD]" in result
    assert "super_secret" not in result


def test_redactor_atomizes_short_password():
    """A short password like 'abc' passed as a positional arg must not leak."""
    result = _sanitize_args_for_log(["unlock", "abc"])
    assert "[PAYLOAD]" in result
    assert "abc" not in result


def test_redactor_keeps_flag_and_uuid_value():
    """Flag --itemid followed by a UUID: both must be kept as safe metadata."""
    uuid = "be114fae-07df-41fc-9da5-1d3c7db2726c"
    result = _sanitize_args_for_log(["delete", "attachment", "--itemid", uuid])
    assert "delete" in result
    assert "--itemid" in result
    assert uuid in result


def test_redactor_atomizes_flag_with_non_uuid_value():
    """Flag --search followed by a plain string: the value is opaque → [PAYLOAD]."""
    result = _sanitize_args_for_log(["list", "items", "--search", "venice"])
    assert "--search" in result
    assert "[PAYLOAD]" in result
    assert "venice" not in result


def test_redactor_full_move_item_scenario():
    """Reproduce the exact scenario from the live leak: edit item uuid base64"""
    b64_payload = base64.b64encode(b'{"folderId": "abc", "password": "_1LqjiY27_"}').decode()
    uuid = "90613f85-8604-4058-8ba2-fba512b97ef5"
    result = _sanitize_args_for_log(["edit", "item", uuid, b64_payload])
    # Verb, object, UUID → kept
    assert "edit" in result
    assert "item" in result
    assert uuid in result
    # The secret payload → gone
    assert "[PAYLOAD]" in result
    assert "_1LqjiY27_" not in result



def test_blind_login_redacts_password():
    """Ensure that password and totp are ALWAYS redacted, but their PRESENCE is known."""
    raw_login = {
        "username": "admin",
        "password": "super_secret_password_123",
        "totp": "", # Empty TOTP
        "uris": [{"match": None, "uri": "https://example.com"}]
    }
    
    login = BlindLogin(**raw_login)
    
    # Check programmatic access returns correct populated/empty tag
    assert login.password == REDACTED_POPULATED
    assert login.totp == REDACTED_EMPTY
    
    # Check actual dictionary dump INCLUDES the REDACTED tags now.
    dumped = login.model_dump(exclude_unset=True)
    assert dumped["password"] == REDACTED_POPULATED
    assert dumped["totp"] == REDACTED_EMPTY
    assert "username" in dumped

def test_blind_item_drops_unknown_fields():
    """Ensure that any weird new Bitwarden field is silently dropped."""
    raw_item = {
        "id": "1234-5678",
        "organizationId": None,
        "folderId": "folder-1",
        "type": 1,
        "name": "My Bank",
        "notes": "Here is my secret PIN 1234",
        "favorite": True,
        "login": {
            "username": "john",
            "password": "abc"
        },
        "this_is_a_new_bw_field_with_secrets": "secret_data"
    }
    
    item = BlindItem(**raw_item)
    dumped = item.model_dump(exclude_unset=True)
    
    # Notes are now explicitly returned with their Null-Aware status
    assert dumped["notes"] == REDACTED_POPULATED
    
    # Unknown fields must NOT be in the dump
    assert "this_is_a_new_bw_field_with_secrets" not in dumped
    
    # Core fields are kept
    assert dumped["id"] == "1234-5678"
    assert dumped["name"] == "My Bank"
    # Login is nested and sanitized with populated tag
    assert dumped.get("login", {}).get("password") == REDACTED_POPULATED

def test_blind_folder():
    raw_folder = {
        "id": "abc-123",
        "name": "Work",
        "unknown_metadata": "drop_me"
    }
    
    folder = BlindFolder(**raw_folder)
    dumped = folder.model_dump()
    assert "unknown_metadata" not in dumped
    assert dumped["name"] == "Work"


# ====================================================================
# REGRESSION TESTS: Discovered during Live MCP Simulation (2026-03-01)
# ====================================================================

def test_blind_folder_nullable_id():
    """Regression: Bitwarden returns a 'No Folder' entry with id=null.
    This crashed the proxy before the fix."""
    raw_folder = {"id": None, "name": "No Folder"}
    folder = BlindFolder(**raw_folder)
    dumped = folder.model_dump()
    assert dumped["id"] is None
    assert dumped["name"] == "No Folder"


def test_blind_item_nullable_id():
    """Regression: Some items may have a null id in edge cases."""
    raw_item = {
        "id": None,
        "type": 1,
        "name": "Orphan Item",
        "login": {"username": "test", "password": "secret"},
    }
    item = BlindItem(**raw_item)
    dumped = item.model_dump(exclude_unset=True)
    assert dumped["id"] is None
    assert dumped["name"] == "Orphan Item"
    assert dumped["login"]["password"] == REDACTED_POPULATED


def test_blind_organization_nullable_id():
    """Regression: Organizations may have nullable ids."""
    raw_org = {"id": None, "name": "Personal"}
    org = BlindOrganization(**raw_org)
    dumped = org.model_dump()
    assert dumped["id"] is None
    assert dumped["name"] == "Personal"


def test_hidden_custom_field_redacted():
    """Regression: Custom fields of type 1 (Hidden) must have their value
    redacted. This is how API tokens (e.g. GitHub PAT) are stored in BW.
    Discovered live when the 'Claw GitHub Token' item was correctly masked."""
    raw_field_hidden = {"name": "token", "type": 1, "value": "ghp_SUPER_SECRET_TOKEN"}
    raw_field_text = {"name": "label", "type": 0, "value": "visible_value"}

    field_hidden = BlindField(**raw_field_hidden)
    field_text = BlindField(**raw_field_text)

    assert field_hidden.value == REDACTED_POPULATED  # Secret is masked
    assert field_text.value == "visible_value"        # Plain text is kept


def test_card_number_and_cvv_redacted():
    """Regression: Card numbers and CVV codes must always be redacted.
    Discovered live when the 'Revolut General' card was correctly masked."""
    raw_card = {
        "cardholderName": "Ivann Harold KAMDEM POUOKAM",
        "brand": "Mastercard",
        "expMonth": "4",
        "expYear": "2030",
        "number": "5412751234567890",
        "code": "123",
    }
    card = BlindCard(**raw_card)
    dumped = card.model_dump(exclude_unset=True)

    assert dumped["cardholderName"] == "Ivann Harold KAMDEM POUOKAM"  # Visible
    assert dumped["brand"] == "Mastercard"                            # Visible
    assert dumped["number"] == REDACTED_POPULATED                     # SECRET
    assert dumped["code"] == REDACTED_POPULATED                       # SECRET

