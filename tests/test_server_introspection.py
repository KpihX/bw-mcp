import json
from bw_proxy.server import mcp
from bw_proxy.logic import get_proxy_audit_context, inspect_transaction_log
from bw_proxy.config import MAX_BATCH_SIZE, REDACTED_POPULATED

def test_mcp_meta_prompt_instructions():
    # Verify that the core security rules are presence in the server instructions
    instructions = mcp.instructions
    assert "Zero Trust" in instructions
    assert str(MAX_BATCH_SIZE) in instructions
    assert REDACTED_POPULATED in instructions
    assert "ACID ENGINE" in instructions

def test_get_proxy_audit_context():
    res = get_proxy_audit_context(limit=2)
    assert isinstance(res, str)
    data = json.loads(res)
    assert "wal_status" in data
    assert data["max_batch_size"] == MAX_BATCH_SIZE
    assert isinstance(data["recent_transactions"], list)

def test_inspect_transaction_log():
    # Since the logs directory state is volatile during tests, 
    # inspect_transaction_log handles errors gracefully by returning a string starting with "Error"
    # Or if logs exist, it returns a valid JSON string.
    res = inspect_transaction_log()
    assert isinstance(res, str)
    
    if res.startswith("Error"):
        assert "Error: No transaction logs exist yet." in res or "Error: No logs directory found." in res
    else:
        data = json.loads(res)
        assert isinstance(data, dict)
