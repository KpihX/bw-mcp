from typer.testing import CliRunner

from bw_proxy import cli_bridge
from bw_proxy.cli_support import get_command
from bw_proxy.main import app


runner = CliRunner()


def test_root_help_exposes_only_groups_and_no_version_command():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "mcp" in result.output
    assert "admin" in result.output
    assert "do" in result.output
    assert "Commands" in result.output
    assert "\n│ version " not in result.output


def test_version_flag_is_supported():
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert "BW-Proxy" in result.output


def test_short_version_flag_is_supported():
    result = runner.invoke(app, ["-V"])

    assert result.exit_code == 0
    assert "BW-Proxy" in result.output


def test_do_global_help_keeps_command_table_and_inline_schemas():
    result = runner.invoke(app, ["do", "--help"])

    assert result.exit_code == 0
    assert "COMMAND" in result.output or "Commands" in result.output
    assert "get-vault-map" in result.output
    assert "propose-vault-transaction" in result.output
    assert "SCHEMA: {" in result.output


def test_do_command_help_keeps_typed_rpc_schema_block_without_duplicate_summary():
    result = runner.invoke(app, ["do", "propose-vault-transaction", "--help"])

    assert result.exit_code == 0
    assert "RPC 2.0 JSON SCHEMA" in result.output
    assert result.output.count("Proposes a batch of modifications to the vault through the ACID transaction") == 1
    assert '"rationale": "str"' in result.output
    assert "Args:" not in result.output


def test_do_command_help_exposes_only_payload_and_meta_flags():
    result = runner.invoke(app, ["do", "get-vault-map", "--help"])

    assert result.exit_code == 0
    assert "--payload" in result.output
    assert "--output-file" in result.output
    assert "--examples" in result.output
    assert "--search-items" not in result.output
    assert "--folder-id" not in result.output
    assert "--organization-id" not in result.output


def test_do_examples_are_available_for_dynamic_commands():
    result = runner.invoke(app, ["do", "propose-vault-transaction", "-e"])

    assert result.exit_code == 0
    assert "Examples:" in result.output
    assert "operations.json" in result.output or "Organize vault" in result.output


def test_admin_help_exposes_only_group_level_format_and_no_examples_or_output_file():
    result = runner.invoke(app, ["admin", "--help"])

    assert result.exit_code == 0
    assert "--format" in result.output
    assert "-f" in result.output
    assert "--examples" not in result.output
    assert "--output-file" not in result.output


def test_admin_config_get_is_single_param_reader():
    result = runner.invoke(app, ["admin", "config", "get", "--max-batch-size"])

    assert result.exit_code == 0
    assert "proxy.max_batch_size" in result.output


def test_admin_config_get_supports_validation_mode_selector():
    result = runner.invoke(app, ["admin", "config", "get", "--help"])

    assert result.exit_code == 0
    assert "--validation-mode" in result.output
    assert "-v" in result.output


def test_admin_config_set_replaces_update_surface():
    result = runner.invoke(app, ["admin", "config", "set", "--help"])

    assert result.exit_code == 0
    assert "max-batch-size" in result.output
    assert "-m" in result.output
    assert "--validation-mode" in result.output
    assert "-v" in result.output
    assert "update" not in result.output.lower()


def test_admin_login_help_has_url_and_email_flags_only():
    result = runner.invoke(app, ["admin", "login", "--help"])

    assert result.exit_code == 0
    assert "--email" in result.output
    assert "-e" in result.output
    assert "--url" in result.output
    assert "-u" in result.output
    assert "Arguments" not in result.output


def test_stdin_has_data_uses_readiness_probe(monkeypatch):
    class FakeStdin:
        def isatty(self) -> bool:
            return False

    fake_stdin = FakeStdin()
    monkeypatch.setattr(cli_bridge.sys, "stdin", fake_stdin)
    monkeypatch.setattr(cli_bridge.select, "select", lambda read, write, err, timeout: ([fake_stdin], [], []))
    assert cli_bridge._stdin_has_data() is True

    monkeypatch.setattr(cli_bridge.select, "select", lambda read, write, err, timeout: ([], [], []))
    assert cli_bridge._stdin_has_data() is False


def test_dynamic_command_registry_exposes_sync_and_autosave_policy_flags():
    vault_map = get_command("do", "get-vault-map")
    sync = get_command("do", "sync")

    assert vault_map is not None
    assert vault_map.needs_vault is True
    assert vault_map.needs_sync is True
    assert vault_map.autosave_large_result is True
    assert vault_map.supports_unlock_lease is True

    assert sync is not None
    assert sync.needs_vault is True
    assert sync.needs_sync is False
    assert sync.autosave_large_result is False
