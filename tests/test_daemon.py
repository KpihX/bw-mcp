"""
Tests for daemon.py — PID file management and server lifecycle control.
"""
import os
import signal
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from bw_proxy.daemon import write_pid, read_pid, clear_pid, is_running


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_pid_dir(tmp_path):
    """Redirect all PID file operations to a temp directory during tests."""
    pid_path = tmp_path / "bw-proxy.pid"
    with patch("bw_proxy.daemon._pid_file_path", return_value=pid_path):
        yield pid_path


# ─────────────────────────────────────────────────────────────────────────────
# PID file primitives
# ─────────────────────────────────────────────────────────────────────────────

def test_write_and_read_pid():
    """write_pid stores PID; read_pid retrieves it correctly."""
    write_pid(12345)
    assert read_pid() == 12345


def test_read_pid_missing_file(isolated_pid_dir):
    """read_pid returns None when no file exists."""
    assert not isolated_pid_dir.exists()
    assert read_pid() is None


def test_read_pid_corrupt_file(isolated_pid_dir):
    """read_pid returns None on non-integer content."""
    isolated_pid_dir.write_text("NOT_AN_INT")
    assert read_pid() is None


def test_clear_pid_removes_file():
    """clear_pid deletes the PID file."""
    write_pid(99)
    clear_pid()
    assert read_pid() is None


def test_clear_pid_idempotent():
    """clear_pid does not raise when the file is already gone."""
    clear_pid()  # file doesn't exist yet
    clear_pid()  # still must not raise


# ─────────────────────────────────────────────────────────────────────────────
# is_running
# ─────────────────────────────────────────────────────────────────────────────

def test_is_running_current_process():
    """Our own PID is always alive."""
    assert is_running(os.getpid()) is True


def test_is_running_dead_process():
    """is_running returns False for a PID that certainly doesn't exist."""
    # PID 0 is reserved by the OS and will never be a user process
    # Using a very high PID that is almost certainly unused
    assert is_running(999_999_999) is False


def test_is_running_permission_error():
    """is_running returns True even on PermissionError (process exists but owned by root)."""
    with patch("os.kill", side_effect=PermissionError):
        assert is_running(1) is True


# ─────────────────────────────────────────────────────────────────────────────
# CLI subcommand integration (via Typer runner)
# ─────────────────────────────────────────────────────────────────────────────

from typer.testing import CliRunner
from bw_proxy.main import app

runner = CliRunner()


def test_cli_version_flag():
    """bw-proxy --version exits 0 and prints the version string."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "BW-Proxy" in result.output


def test_cli_short_version_flag():
    """bw-proxy -V exits 0 and prints the version string."""
    result = runner.invoke(app, ["-V"])
    assert result.exit_code == 0
    assert "BW-Proxy" in result.output


def test_cli_mcp_status_stopped():
    """bw-proxy mcp status exits 1 when no PID file exists."""
    result = runner.invoke(app, ["mcp", "status"])
    assert result.exit_code == 1
    assert "No PID file found" in result.output


def test_cli_mcp_status_running():
    """bw-proxy mcp status exits 0 when the PID file contains a live PID."""
    write_pid(os.getpid())
    result = runner.invoke(app, ["mcp", "status"])
    assert result.exit_code == 0
    assert "MCP server is running" in result.output
    clear_pid()


def test_cli_mcp_status_stale_pid():
    """bw-proxy mcp status detects and clears a stale PID (process dead)."""
    write_pid(999_999_999)  # certainly dead
    result = runner.invoke(app, ["mcp", "status"])
    assert result.exit_code == 2
    assert "Cleared stale PID file" in result.output
    assert read_pid() is None  # stale file cleared


def test_cli_mcp_stop_not_running():
    """bw-proxy mcp stop is a no-op when there is no PID file."""
    result = runner.invoke(app, ["mcp", "stop"])
    assert result.exit_code == 0
    assert "nothing to stop" in result.output


def test_cli_mcp_stop_running():
    """bw-proxy mcp stop sends SIGTERM to the running PID."""
    write_pid(os.getpid())
    with patch("os.kill") as mock_kill:
        result = runner.invoke(app, ["mcp", "stop"])
    assert result.exit_code == 0
    mock_kill.assert_any_call(os.getpid(), signal.SIGTERM)
    assert read_pid() is None  # PID file cleared


def test_cli_mcp_restart_not_running():
    """bw-proxy mcp restart is a no-op when there is no PID file."""
    result = runner.invoke(app, ["mcp", "restart"])
    assert result.exit_code == 0
    assert "nothing to restart" in result.output


def test_cli_mcp_restart_running():
    """bw-proxy mcp restart sends SIGTERM and clears the PID file."""
    write_pid(os.getpid())
    with patch("os.kill") as mock_kill:
        result = runner.invoke(app, ["mcp", "restart"])
    assert result.exit_code == 0
    mock_kill.assert_any_call(os.getpid(), signal.SIGTERM)
    assert read_pid() is None  # PID file cleared after restart
    assert "Restart signal sent" in result.output


def test_cli_admin_login_requires_email_and_url_when_env_missing(monkeypatch):
    """Admin login should fail clearly when email/url are absent from both flags and env."""
    monkeypatch.delenv("BW_EMAIL", raising=False)
    monkeypatch.delenv("BW_URL", raising=False)

    result = runner.invoke(app, ["admin", "login"])

    assert result.exit_code == 1
    assert "Missing required Bitwarden login parameter" in result.output


@patch("bw_proxy.main.logic.logout")
def test_cli_admin_logout_is_successful_when_already_logged_out(mock_logout):
    """Admin logout should be a success no-op when the vault is already unauthenticated."""
    mock_logout.return_value = {"status": "success", "message": "Already logged out.", "mode": "noop"}

    result = runner.invoke(app, ["admin", "logout"])

    assert result.exit_code == 0
    assert "Already logged out" in result.output


@patch("bw_proxy.main.logic.get_admin_status")
def test_cli_admin_status_default_table_deduplicates_env_noise(mock_get_admin_status):
    """Admin status should render one normalized table by default, not repeated env/server blocks."""
    mock_get_admin_status.return_value = {
        "status": "success",
        "message": "Loaded administrative status.",
        "bitwarden_status": {
            "serverUrl": "https://vault.example.com",
            "userEmail": "user@example.com",
            "status": "locked",
            "lastSync": "2026-04-26T12:56:14.872Z",
        },
        "wal": {"pending": True, "state": "pending", "file": "/tmp/pending_transaction.wal", "note": "artifact exists"},
        "config": {"path": "/tmp/config.yaml", "max_batch_size": 15, "validation_mode": "browser"},
        "environment": {"bw_url": "https://vault.example.com", "bw_email": "user@example.com"},
        "server_url": "https://vault.example.com",
    }

    result = runner.invoke(app, ["admin", "status"])

    assert result.exit_code == 0
    assert "auth.server_url" in result.output
    assert "environment.bw_url" not in result.output
    assert result.output.count("https://vault.example.com") == 1
    assert "config.validation_mode" in result.output


@patch("bw_proxy.main.logic.get_admin_status")
def test_cli_admin_status_supports_group_json_format(mock_get_admin_status):
    """Admin info commands should support a centralized group-level json format."""
    mock_get_admin_status.return_value = {
        "status": "success",
        "message": "Loaded administrative status.",
        "bitwarden_status": {"serverUrl": "https://vault.example.com", "status": "locked"},
        "wal": {"pending": False, "state": "clean", "file": "/tmp/pending_transaction.wal", "note": "No pending WAL artifact."},
        "config": {"path": "/tmp/config.yaml", "max_batch_size": 15, "validation_mode": "browser"},
    }

    result = runner.invoke(app, ["admin", "-f", "json", "status"])

    assert result.exit_code == 0
    assert '"auth"' in result.output
    assert '"server_url": "https://vault.example.com"' in result.output
    assert '"bitwarden_status"' not in result.output
    assert '"validation_mode": "browser"' in result.output


@patch("bw_proxy.main.WALManager.has_pending_transaction", return_value=True)
@patch("bw_proxy.main.WALManager.read_wal", side_effect=ValueError("bad token"))
@patch("bw_proxy.main.HITLManager.ask_master_password", return_value=bytearray(b"pw"))
def test_cli_admin_wal_view_explains_undecryptable_state(mock_password, mock_read_wal, mock_has_pending):
    """WAL failures should explain that the artifact may be stale or undecryptable, not just imply a failed command."""
    result = runner.invoke(app, ["admin", "wal", "view"])

    assert result.exit_code == 1
    assert "stale WAL" in result.output or "stale wal" in result.output.lower()
    assert "undecryptable" in result.output


@patch("bw_proxy.main.logic.get_vault_map")
def test_cli_do_get_vault_map_output_file(mock_get_vault_map, tmp_path):
    """`--output-file` writes the raw command result instead of printing it."""
    mock_get_vault_map.return_value = {"status": "success"}
    output_path = tmp_path / "vault_map.json"

    result = runner.invoke(app, ["do", "--output-file", str(output_path), "get-vault-map"])

    assert result.exit_code == 0
    assert output_path.read_text() == '{\n  "status": "success"\n}'
    assert "Saved output to" in result.output


@patch("bw_proxy.main.logic.get_vault_map")
@patch("bw_proxy.cli_support.tempfile.gettempdir")
def test_cli_do_get_vault_map_autosaves_when_output_file_missing(mock_gettempdir, mock_get_vault_map, tmp_path):
    """Without --output-file, results still go to stdout and into the system temp bw_proxy folder."""
    mock_get_vault_map.return_value = {"status": "success"}
    mock_gettempdir.return_value = str(tmp_path)

    result = runner.invoke(app, ["do", "get-vault-map"])

    assert result.exit_code == 0
    assert '"status": "success"' in result.output
    assert "Also saved to" in result.output
    autosaved = list((tmp_path / "bw_proxy").glob("*.json"))
    assert len(autosaved) == 1
    assert autosaved[0].read_text() == '{\n  "status": "success"\n}'


@patch("bw_proxy.main.logic.sync")
@patch("bw_proxy.cli_support.tempfile.gettempdir")
def test_cli_do_sync_does_not_autosave_when_output_file_missing(mock_gettempdir, mock_sync, tmp_path):
    """Small do command results should stay on stdout only unless explicitly exported."""
    mock_sync.return_value = {"status": "success"}
    mock_gettempdir.return_value = str(tmp_path)

    result = runner.invoke(app, ["do", "sync"])

    assert result.exit_code == 0
    assert '"status": "success"' in result.output
    assert "Also saved to" not in result.output
    assert list((tmp_path / "bw_proxy").glob("*")) == []


@patch("bw_proxy.main.logic.get_vault_map")
def test_cli_do_get_vault_map_accepts_only_rpc_payload(mock_get_vault_map):
    """Business parameters should flow through one JSON RPC payload, not ad hoc CLI flags."""
    mock_get_vault_map.return_value = {"status": "success"}

    result = runner.invoke(app, ["do", "get-vault-map", '{"folder_id":"folder-123"}'])

    assert result.exit_code == 0
    mock_get_vault_map.assert_called_once()
    assert mock_get_vault_map.call_args.kwargs == {
        "folder_id": "folder-123",
    }


@patch("bw_proxy.main.logic.inspect_transaction_log")
def test_cli_do_inspect_log_accepts_rpc_payload(mock_inspect):
    """`do inspect-log` should read business parameters only from the RPC payload."""
    mock_inspect.return_value = '{"transaction_id":"abc"}'

    result = runner.invoke(app, ["do", "inspect-log", '{"n":1}'])

    assert result.exit_code == 0
    mock_inspect.assert_called_once_with(n=1)


def test_cli_do_help_hides_business_flags_and_keeps_only_meta_flags():
    """Help output should expose only PAYLOAD plus CLI meta flags for dynamic RPC commands."""
    result = runner.invoke(app, ["do", "inspect-log", "--help"])
    assert result.exit_code == 0
    assert "--payload" in result.output
    assert "--output-file" in result.output
    assert "--examples" in result.output
    assert "--n" not in result.output
    assert "--tx-id" not in result.output


@patch("bw_proxy.main.logic.fetch_template")
def test_cli_do_get_template_accepts_rpc_payload(mock_fetch):
    """Single-parameter RPC commands must also use the JSON payload contract."""
    mock_fetch.return_value = {"status": "success", "template": "item"}

    result = runner.invoke(app, ["do", "get-template", '{"template_type":"item"}'])

    assert result.exit_code == 0
    mock_fetch.assert_called_once_with(template_type="item")


@patch("bw_proxy.main.logic.find_all_vault_duplicates")
def test_cli_do_single_payload_model_accepts_bare_rpc_object(mock_find_all):
    """Commands backed by one Pydantic payload model should accept the bare JSON object."""
    mock_find_all.return_value = {"status": "success"}

    result = runner.invoke(
        app,
        ["do", "find-all-vault-duplicates", '{"rationale":"Audit","scan_limit":5}'],
    )

    assert result.exit_code == 0
    payload = mock_find_all.call_args.kwargs["payload"]
    assert payload.rationale == "Audit"
    assert payload.scan_limit == 5


@patch("bw_proxy.main.logic.propose_vault_transaction")
def test_cli_do_import_json_accepts_items_file(mock_propose, tmp_path):
    """`do import-json` can convert plain item specs into create_item operations."""
    import_file = tmp_path / "items.json"
    import_file.write_text(
        '[{"type": 1, "name": "GitHub", "login": {"username": "kpihx"}}]',
        encoding="utf-8",
    )
    mock_propose.return_value = {"status": "success"}

    result = runner.invoke(
        app,
        ["do", "import-json", str(import_file), "--rationale", "Bulk import"],
    )

    assert result.exit_code == 0
    mock_propose.assert_called_once_with(
        "Bulk import",
        [{"action": "create_item", "type": 1, "name": "GitHub", "login": {"username": "kpihx"}}],
    )


@patch("bw_proxy.main.logic.propose_vault_transaction")
def test_cli_do_import_json_prefers_payload_rationale(mock_propose, tmp_path):
    """A rationale embedded in the JSON payload overrides the CLI fallback."""
    import_file = tmp_path / "ops.json"
    import_file.write_text(
        '{"rationale":"From file","operations":[{"action":"rename_item","target_id":"1","new_name":"A"}]}',
        encoding="utf-8",
    )
    mock_propose.return_value = {"status": "success"}

    result = runner.invoke(
        app,
        ["do", "import-json", str(import_file), "--rationale", "CLI rationale"],
    )

    assert result.exit_code == 0
    mock_propose.assert_called_once_with(
        "From file",
        [{"action": "rename_item", "target_id": "1", "new_name": "A"}],
    )
