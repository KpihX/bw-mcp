import pytest
import json
from unittest.mock import patch, MagicMock

# Important: We patch the decorators from fastmcp out so we can test the raw function
# The function is decorated, so we need to access its __wrapped__ attribute or test the module logic
import bw_proxy.server as server

@patch('bw_proxy.vault_runtime.load_bw_status', return_value={"status": "locked", "serverUrl": "https://vault.example.com", "userEmail": "agent@example.com"})
@patch('bw_proxy.vault_runtime.validate_authenticated_context', return_value=None)
@patch('bw_proxy.logic.HITLManager.ask_master_password')
@patch('bw_proxy.logic.SecureSubprocessWrapper.unlock_vault')
@patch('bw_proxy.logic.SecureSubprocessWrapper.execute', return_value="")
@patch('bw_proxy.logic.SecureSubprocessWrapper.execute_json')
@patch('bw_proxy.logic.TransactionManager.check_recovery', return_value=None)
def test_get_vault_map_split_search(mock_recovery, mock_exec_json, mock_exec, mock_unlock, mock_ask, mock_validate, mock_status):
    """Ensure search_items and search_folders route correctly to their respective base args."""
    mock_ask.return_value = bytearray("pw", "utf-8")
    mock_unlock.return_value = bytearray("session", "utf-8")
    mock_exec_json.return_value = []
    
    server.get_vault_map(search_items="Lokad", search_folders="Dev")
    
    calls = mock_exec_json.call_args_list
    # New order: Orgs, Colls, Active Items, Active Folders, Trash Items, Trash Folders
    assert len(calls) == 6 

    assert calls[0][0][0] == ["list", "organizations"]
    assert calls[1][0][0] == ["list", "collections"]
    assert calls[2][0][0] == ["list", "items", "--search", "Lokad"]
    assert calls[3][0][0] == ["list", "folders", "--search", "Dev"]

@patch('bw_proxy.vault_runtime.load_bw_status', return_value={"status": "locked", "serverUrl": "https://vault.example.com", "userEmail": "agent@example.com"})
@patch('bw_proxy.vault_runtime.validate_authenticated_context', return_value=None)
@patch('bw_proxy.logic.HITLManager.ask_master_password')
@patch('bw_proxy.logic.SecureSubprocessWrapper.unlock_vault')
@patch('bw_proxy.logic.SecureSubprocessWrapper.execute', return_value="")
@patch('bw_proxy.logic.SecureSubprocessWrapper.execute_json')
@patch('bw_proxy.logic.TransactionManager.check_recovery', return_value=None)
def test_get_vault_map_trash_state_none(mock_recovery, mock_exec_json, mock_exec, mock_unlock, mock_ask, mock_validate, mock_status):
    """Ensure trash_state='none' skips fetching the trash."""
    mock_ask.return_value = bytearray("pw", "utf-8")
    mock_unlock.return_value = bytearray("session", "utf-8")
    mock_exec_json.return_value = []
    
    server.get_vault_map(trash_state="none")
    
    calls = mock_exec_json.call_args_list
    # Orgs, Colls, Active Items, Active Folders
    assert len(calls) == 4
    
    assert calls[0][0][0] == ["list", "organizations"]
    assert calls[1][0][0] == ["list", "collections"]
    assert calls[2][0][0] == ["list", "items"]
    assert calls[3][0][0] == ["list", "folders"]
    
@patch('bw_proxy.vault_runtime.load_bw_status', return_value={"status": "locked", "serverUrl": "https://vault.example.com", "userEmail": "agent@example.com"})
@patch('bw_proxy.vault_runtime.validate_authenticated_context', return_value=None)
@patch('bw_proxy.logic.HITLManager.ask_master_password')
@patch('bw_proxy.logic.SecureSubprocessWrapper.unlock_vault')
@patch('bw_proxy.logic.SecureSubprocessWrapper.execute', return_value="")
@patch('bw_proxy.logic.SecureSubprocessWrapper.execute_json')
@patch('bw_proxy.logic.TransactionManager.check_recovery', return_value=None)
def test_get_vault_map_trash_state_only(mock_recovery, mock_exec_json, mock_exec, mock_unlock, mock_ask, mock_validate, mock_status):
    """Ensure trash_state='only' skips fetching active items to speed up the proxy."""
    mock_ask.return_value = bytearray("pw", "utf-8")
    mock_unlock.return_value = bytearray("session", "utf-8")
    mock_exec_json.return_value = []
    
    server.get_vault_map(trash_state="only")
    
    calls = mock_exec_json.call_args_list
    # Orgs, Colls, Trash Items, Trash Folders
    assert len(calls) == 4
    
    assert calls[0][0][0] == ["list", "organizations"]
    assert calls[1][0][0] == ["list", "collections"]
    assert calls[2][0][0] == ["list", "items", "--trash"]
    assert calls[3][0][0] == ["list", "folders", "--trash"]

@patch('bw_proxy.vault_runtime.load_bw_status', return_value={"status": "locked", "serverUrl": "https://vault.example.com", "userEmail": "agent@example.com"})
@patch('bw_proxy.vault_runtime.validate_authenticated_context', return_value=None)
@patch('bw_proxy.logic.HITLManager.ask_master_password')
@patch('bw_proxy.logic.SecureSubprocessWrapper.unlock_vault')
@patch('bw_proxy.logic.SecureSubprocessWrapper.execute', return_value="")
@patch('bw_proxy.logic.SecureSubprocessWrapper.execute_json')
@patch('bw_proxy.logic.TransactionManager.check_recovery', return_value=None)
def test_get_vault_map_folder_id(mock_recovery, mock_exec_json, mock_exec, mock_unlock, mock_ask, mock_validate, mock_status):
    """Ensure folder_id is added to the args array."""
    mock_ask.return_value = bytearray("pw", "utf-8")
    mock_unlock.return_value = bytearray("session", "utf-8")
    mock_exec_json.return_value = []
    
    server.get_vault_map(folder_id="my-folder")
    
    calls = mock_exec_json.call_args_list
    assert calls[0][0][0] == ["list", "organizations"]
    assert calls[1][0][0] == ["list", "collections"]
    assert calls[2][0][0] == ["list", "items", "--folderid", "my-folder"]


@patch('bw_proxy.vault_runtime.load_bw_status', return_value={"status": "locked", "serverUrl": "https://vault.example.com", "userEmail": "agent@example.com"})
@patch('bw_proxy.vault_runtime.validate_authenticated_context', return_value=None)
@patch('bw_proxy.logic.HITLManager.ask_master_password')
@patch('bw_proxy.logic.SecureSubprocessWrapper.unlock_vault')
@patch('bw_proxy.logic.SecureSubprocessWrapper.execute', return_value="")
@patch('bw_proxy.logic.SecureSubprocessWrapper.execute_json')
@patch('bw_proxy.logic.TransactionManager.check_recovery', return_value=None)
def test_get_vault_map_folder_only_search_skips_item_queries_and_dedupes_trash(mock_recovery, mock_exec_json, mock_exec, mock_unlock, mock_ask, mock_validate, mock_status):
    """Folder-only searches should not fetch every item, and trash duplicates must not leak into active folders."""
    mock_ask.return_value = bytearray("pw", "utf-8")
    mock_unlock.return_value = bytearray("session", "utf-8")
    duplicated_folder = {"id": "folder-1", "name": "Finance"}
    mock_exec_json.side_effect = [
        [],                           # orgs
        [],                           # collections
        [duplicated_folder],          # active folders
        [duplicated_folder],          # trash folders
    ]

    result = server.get_vault_map(search_folders="fin")

    assert mock_exec_json.call_count == 4
    assert mock_exec_json.call_args_list[0][0][0] == ["list", "organizations"]
    assert mock_exec_json.call_args_list[1][0][0] == ["list", "collections"]
    assert mock_exec_json.call_args_list[2][0][0] == ["list", "folders", "--search", "fin"]
    assert mock_exec_json.call_args_list[3][0][0] == ["list", "folders", "--search", "fin", "--trash"]
