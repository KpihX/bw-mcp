import pytest
from bw_blind_proxy.models import BlindItem, BlindLogin, BlindFolder

def test_blind_login_redacts_password():
    """Ensure that password and totp are ALWAYS redacted and excluded from serialization."""
    raw_login = {
        "username": "admin",
        "password": "super_secret_password_123",
        "totp": "JBSWY3DPEHPK3PXP",
        "uris": [{"match": None, "uri": "https://example.com"}]
    }
    
    login = BlindLogin(**raw_login)
    
    # Check programmatic access is redacted default
    assert login.password == "[REDACTED_BY_PROXY]"
    assert login.totp == "[REDACTED_BY_PROXY]"
    
    # Check actual dictionary dump excludes them by default 
    # (Because Field(exclude=True) drops them from model_dump)
    dumped = login.model_dump(exclude_unset=True)
    assert "password" not in dumped
    assert "totp" not in dumped
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
    
    # Notes are excluded from dump by Field(exclude=True)
    assert "notes" not in dumped
    # Unknown fields must NOT be in the dump
    assert "this_is_a_new_bw_field_with_secrets" not in dumped
    
    # Core fields are kept
    assert dumped["id"] == "1234-5678"
    assert dumped["name"] == "My Bank"
    # Login is nested and sanitized
    assert "password" not in dumped.get("login", {})

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
