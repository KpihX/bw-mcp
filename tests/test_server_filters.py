import pytest
import json
from unittest.mock import patch, MagicMock

# Important: We patch the decorators from fastmcp out so we can test the raw function
# The function is decorated, so we need to access its __wrapped__ attribute or test the module logic
import bw_blind_proxy.server as server

@patch('bw_blind_proxy.server.HITLManager.ask_master_password')
@patch('bw_blind_proxy.server.SecureSubprocessWrapper.unlock_vault')
@patch('bw_blind_proxy.server.SecureSubprocessWrapper.execute_json')
def test_get_vault_map_split_search(mock_exec_json, mock_unlock, mock_ask):
    """Ensure search_items and search_folders route correctly to their respective base args."""
    mock_ask.return_value = bytearray("pw", "utf-8")
    mock_unlock.return_value = bytearray("session", "utf-8")
    mock_exec_json.return_value = []
    
    server.get_vault_map(search_items="Lokad", search_folders="Dev")
    
    calls = mock_exec_json.call_args_list
    assert len(calls) == 6 # Active Items, Active Folders, Trash Items, Trash Folders, Organizations, Collections
    
    # Check Active Items call
    assert calls[0][0][0] == ["list", "items", "--search", "Lokad"]
    
    # Check Active Folders call
    assert calls[1][0][0] == ["list", "folders", "--search", "Dev"]

@patch('bw_blind_proxy.server.HITLManager.ask_master_password')
@patch('bw_blind_proxy.server.SecureSubprocessWrapper.unlock_vault')
@patch('bw_blind_proxy.server.SecureSubprocessWrapper.execute_json')
def test_get_vault_map_trash_state_none(mock_exec_json, mock_unlock, mock_ask):
    """Ensure trash_state='none' skips fetching the trash."""
    mock_ask.return_value = bytearray("pw", "utf-8")
    mock_unlock.return_value = bytearray("session", "utf-8")
    mock_exec_json.return_value = []
    
    server.get_vault_map(trash_state="none")
    
    calls = mock_exec_json.call_args_list
    # Active Items, Active Folders, Organizations, Collections
    assert len(calls) == 4
    
    assert calls[0][0][0] == ["list", "items"]
    assert calls[1][0][0] == ["list", "folders"]
    assert calls[2][0][0] == ["list", "organizations"]
    
@patch('bw_blind_proxy.server.HITLManager.ask_master_password')
@patch('bw_blind_proxy.server.SecureSubprocessWrapper.unlock_vault')
@patch('bw_blind_proxy.server.SecureSubprocessWrapper.execute_json')
def test_get_vault_map_trash_state_only(mock_exec_json, mock_unlock, mock_ask):
    """Ensure trash_state='only' skips fetching active items to speed up the proxy."""
    mock_ask.return_value = bytearray("pw", "utf-8")
    mock_unlock.return_value = bytearray("session", "utf-8")
    mock_exec_json.return_value = []
    
    server.get_vault_map(trash_state="only")
    
    calls = mock_exec_json.call_args_list
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
    mock_ask.return_value = bytearray("pw", "utf-8")
    mock_unlock.return_value = bytearray("session", "utf-8")
    mock_exec_json.return_value = []
    
    server.get_vault_map(folder_id="my-folder")
    
    calls = mock_exec_json.call_args_list
    # Active Items should have the flag
    assert calls[0][0][0] == ["list", "items", "--folderid", "my-folder"]
    # Active Folders should NOT have the flag (bw list folders doesn't take folderid)
    assert calls[1][0][0] == ["list", "folders"]
