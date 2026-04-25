import pytest
from bw_proxy.scrubber import deep_scrub_payload, PAYLOAD_TAG

def test_scrubber_primitive_passthrough():
    assert deep_scrub_payload(None) is None
    assert deep_scrub_payload(123) == 123
    assert deep_scrub_payload("hello") == "hello"
    assert deep_scrub_payload(True) is True

def test_scrubber_flat_dict():
    raw = {
        "action": "create_item",
        "name": "My Safe Name",
        "password": "super-secret-password",
        "not_a_secret": "value is fine"
    }
    scrubbed = deep_scrub_payload(raw)
    
    assert scrubbed["action"] == "create_item"
    assert scrubbed["name"] == "My Safe Name"
    assert scrubbed["not_a_secret"] == "value is fine"
    assert scrubbed["password"] == PAYLOAD_TAG

def test_scrubber_nested_dict():
    raw = {
        "action": "edit",
        "login": {
            "username": "kpihx",
            "password": "nested-password-1",
            "totp": "123456"
        },
        "fields": [
            {"name": "SafeField", "value": "secret-value"},
            {"name": "AnotherField", "value": None}
        ]
    }
    
    scrubbed = deep_scrub_payload(raw)
    
    assert scrubbed["login"]["username"] == "kpihx"
    assert scrubbed["login"]["password"] == PAYLOAD_TAG
    assert scrubbed["login"]["totp"] == PAYLOAD_TAG
    
    assert scrubbed["fields"][0]["name"] == "SafeField"
    assert scrubbed["fields"][0]["value"] == PAYLOAD_TAG
    
    # Empty values should be preserved to maintain structure without leaking
    assert scrubbed["fields"][1]["value"] is None

def test_scrubber_complex_lists_and_tuples():
    raw = {
        "items": [
            {"name": "A", "notes": "Secret snippet A"},
            {"name": "B", "notes": "Secret snippet B"}
        ],
        "tuple_data": ({"ssn": "123-456-7890"}, {"number": "4111-2222-3333-4444"})
    }
    
    scrubbed = deep_scrub_payload(raw)
    
    assert scrubbed["items"][0]["notes"] == PAYLOAD_TAG
    assert scrubbed["items"][1]["notes"] == PAYLOAD_TAG
    
    assert isinstance(scrubbed["tuple_data"], tuple)
    assert scrubbed["tuple_data"][0]["ssn"] == PAYLOAD_TAG
    assert scrubbed["tuple_data"][1]["number"] == PAYLOAD_TAG
