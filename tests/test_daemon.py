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


def test_cli_version():
    """bw-proxy version exits 0 and prints the version string."""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "BW-Proxy" in result.output


def test_cli_status_stopped():
    """bw-proxy status exits 1 when no PID file exists."""
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 1
    assert "Stopped" in result.output


def test_cli_status_running():
    """bw-proxy status exits 0 when the PID file contains a live PID."""
    write_pid(os.getpid())
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "Running" in result.output
    clear_pid()


def test_cli_status_stale_pid():
    """bw-proxy status detects and clears a stale PID (process dead)."""
    write_pid(999_999_999)  # certainly dead
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 2
    assert "Dead" in result.output
    assert read_pid() is None  # stale file cleared


def test_cli_stop_not_running():
    """bw-proxy stop is a no-op when there is no PID file."""
    result = runner.invoke(app, ["stop"])
    assert result.exit_code == 0
    assert "nothing to stop" in result.output


def test_cli_stop_running():
    """bw-proxy stop sends SIGTERM to the running PID."""
    write_pid(os.getpid())
    with patch("os.kill") as mock_kill:
        result = runner.invoke(app, ["stop"])
    assert result.exit_code == 0
    mock_kill.assert_any_call(os.getpid(), signal.SIGTERM)
    assert read_pid() is None  # PID file cleared


def test_cli_restart_not_running():
    """bw-proxy restart is a no-op when there is no PID file."""
    result = runner.invoke(app, ["restart"])
    assert result.exit_code == 0
    assert "nothing to restart" in result.output


def test_cli_restart_running():
    """bw-proxy restart sends SIGTERM and clears the PID file."""
    write_pid(os.getpid())
    with patch("os.kill") as mock_kill:
        result = runner.invoke(app, ["restart"])
    assert result.exit_code == 0
    mock_kill.assert_any_call(os.getpid(), signal.SIGTERM)
    assert read_pid() is None  # PID file cleared after restart
    assert "Restart signal sent" in result.output
