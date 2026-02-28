import pytest
import json
from unittest.mock import patch, MagicMock

# Important: We patch the decorators from fastmcp out so we can test the raw function
# The function is decorated, so we need to access its __wrapped__ attribute or test the module logic
import bw_blind_proxy.server as server

@patch('bw_blind_proxy.server.HITLManager.ask_master_password')
@patch('bw_blind_proxy.server.SecureSubprocessWrapper.unlock_vault')
@patch('bw_blind_proxy.server.SecureSubprocessWrapper.execute_json')
def test_get_vault_map_search_parameter(mock_exec_json, mock_unlock, mock_ask):
    """Ensure search argument maps to --search for both items and folders."""
    mock_ask.return_value = "pw"
    mock_unlock.return_value = "session"
    mock_exec_json.return_value = []
    
    # Run the original unwrapped function manually to avoid FastMCP context issues
    # With fastmcp.tool(), the tool logic is callable directly in Python
    server.get_vault_map(search="Lokad")
    
    # Verify the execute_json calls
    calls = mock_exec_json.call_args_list
    assert len(calls) == 6 # Active Items, Active Folders, Trash Items, Trash Folders, Organizations, Collections
    
    # Check Active Items call
    assert calls[0][0][0] == ["list", "items", "--search", "Lokad"]
    
    # Check Active Folders call
    assert calls[1][0][0] == ["list", "folders", "--search", "Lokad"]

@patch('bw_blind_proxy.server.HITLManager.ask_master_password')
@patch('bw_blind_proxy.server.SecureSubprocessWrapper.unlock_vault')
@patch('bw_blind_proxy.server.SecureSubprocessWrapper.execute_json')
def test_get_vault_map_trash_only(mock_exec_json, mock_unlock, mock_ask):
    """Ensure trash_only skips fetching active items to speed up the proxy."""
    mock_ask.return_value = "pw"
    mock_unlock.return_value = "session"
    mock_exec_json.return_value = []
    
    server.get_vault_map(trash_only=True)
    
    calls = mock_exec_json.call_args_list
    # With trash_only=True and include_orgs=True, we expect 4 calls: 
    # Trash Items, Trash Folders, Organizations, Collections
    assert len(calls) == 4
    
    assert calls[0][0][0] == ["list", "items", "--trash"]
    assert calls[1][0][0] == ["list", "folders", "--trash"]
    assert calls[2][0][0] == ["list", "organizations"]
    assert calls[3][0][0] == ["list", "org-collections"]

@patch('bw_blind_proxy.server.HITLManager.ask_master_password')
@patch('bw_blind_proxy.server.SecureSubprocessWrapper.unlock_vault')
@patch('bw_blind_proxy.server.SecureSubprocessWrapper.execute_json')
def test_get_vault_map_folder_id(mock_exec_json, mock_unlock, mock_ask):
    """Ensure folder_id is added to the args array."""
    mock_ask.return_value = "pw"
    mock_unlock.return_value = "session"
    mock_exec_json.return_value = []
    
    server.get_vault_map(folder_id="my-folder")
    
    calls = mock_exec_json.call_args_list
    # Active Items should have the flag
    assert calls[0][0][0] == ["list", "items", "--folderid", "my-folder"]
    # Active Folders should NOT have the flag (bw list folders doesn't take folderid)
    assert calls[1][0][0] == ["list", "folders"]
