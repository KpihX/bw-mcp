import importlib.util
import threading
from pathlib import Path
from unittest.mock import MagicMock


_SHIM_PATH = Path(__file__).resolve().parents[1] / "scripts" / "bw_proxy_shim.py"
_SPEC = importlib.util.spec_from_file_location("bw_proxy_shim", _SHIM_PATH)
bw_proxy_shim = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(bw_proxy_shim)


def test_default_args_falls_back_to_serve(monkeypatch):
    monkeypatch.setattr(bw_proxy_shim.sys, "argv", ["bw-proxy"])
    assert bw_proxy_shim._default_args() == ["mcp", "serve"]


def test_build_docker_command_uses_ephemeral_runtime(monkeypatch):
    monkeypatch.setattr(bw_proxy_shim.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(bw_proxy_shim.sys.stdout, "isatty", lambda: False)
    monkeypatch.setattr(bw_proxy_shim, "_docker_user_args", lambda: ["--user", "1000:1000"])
    monkeypatch.setenv("BW_URL", "https://vault.example.com")
    monkeypatch.setenv("BW_EMAIL", "agent@example.com")
    monkeypatch.setenv("HITL_USE_HTTPS", "true")

    cmd = bw_proxy_shim.build_docker_command(["mcp", "serve"], 43123)

    assert cmd[:5] == ["docker", "run", "--rm", "--init", "-i"]
    assert "--user" in cmd
    assert "1000:1000" in cmd
    assert f"{bw_proxy_shim.DEFAULT_VOLUME}:{bw_proxy_shim.DEFAULT_DATA_DIR}" in cmd
    assert "127.0.0.1:43123:43123" in cmd
    assert "HITL_HOST=0.0.0.0" in cmd
    assert "HITL_PORT=43123" in cmd
    assert "HITL_AUTO_OPEN=false" in cmd
    assert "BW_URL=https://vault.example.com" in cmd
    assert "BW_EMAIL=agent@example.com" in cmd
    assert cmd[-3:] == [bw_proxy_shim.DEFAULT_IMAGE, "mcp", "serve"]


def test_rewrite_approval_url_maps_container_host_to_loopback():
    assert (
        bw_proxy_shim._rewrite_approval_url("https://0.0.0.0:43123/?token=abc")
        == "https://127.0.0.1:43123/?token=abc"
    )


def test_emit_unsupported_mcp_message_returns_failure(capsys):
    rc = bw_proxy_shim._emit_unsupported_mcp_message("status")
    captured = capsys.readouterr()
    assert rc == 1
    assert "not available in Docker mode" in captured.out
    assert "bw-proxy mcp status" in captured.out


class _FakeStdout:
    def __init__(self, lines):
        self._lines = iter(lines)

    def readline(self):
        return next(self._lines, "")


def test_run_command_opens_browser_once_and_rewrites_url(monkeypatch):
    opened = []

    def fake_popen(cmd, **kwargs):
        process = MagicMock()
        process.stdout = _FakeStdout([
            "booting\n",
            "URL      : https://0.0.0.0:43123/?token=abc\n",
            "done\n",
        ])
        process.wait.return_value = 0
        process.returncode = 0
        return process

    monkeypatch.setattr(bw_proxy_shim, "_pick_host_port", lambda: 43123)
    monkeypatch.setattr(bw_proxy_shim, "build_docker_command", lambda args, port: ["docker", str(port)] + args)
    monkeypatch.setattr(bw_proxy_shim.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(bw_proxy_shim.webbrowser, "open", lambda url: opened.append(url))

    rc = bw_proxy_shim.run_command(["mcp", "serve"])

    assert rc == 0
    assert opened == ["https://127.0.0.1:43123/?token=abc"]


def test_run_command_reopens_browser_when_token_changes_on_same_port(monkeypatch):
    opened = []

    def fake_popen(cmd, **kwargs):
        process = MagicMock()
        process.stdout = _FakeStdout([
            "URL      : https://0.0.0.0:43123/?token=11111111-1111-4111-8111-111111111111\n",
            "still waiting\n",
            "URL      : https://0.0.0.0:43123/?token=22222222-2222-4222-8222-222222222222\n",
            "done\n",
        ])
        process.wait.return_value = 0
        process.returncode = 0
        return process

    monkeypatch.setattr(bw_proxy_shim, "_pick_host_port", lambda: 43123)
    monkeypatch.setattr(bw_proxy_shim, "build_docker_command", lambda args, port: ["docker", str(port)] + args)
    monkeypatch.setattr(bw_proxy_shim.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(bw_proxy_shim.webbrowser, "open", lambda url: opened.append(url))

    rc = bw_proxy_shim.run_command(["mcp", "serve"])

    assert rc == 0
    assert opened == [
        "https://127.0.0.1:43123/?token=11111111-1111-4111-8111-111111111111",
        "https://127.0.0.1:43123/?token=22222222-2222-4222-8222-222222222222",
    ]


def test_parallel_invocations_use_distinct_ports_and_no_duplicate_browser_opens(monkeypatch):
    assigned_ports = [43123, 43124]
    opened = []
    lock = threading.Lock()

    def fake_pick_host_port():
        with lock:
            return assigned_ports.pop(0)

    def fake_popen(cmd, **kwargs):
        port = int(cmd[1])
        process = MagicMock()
        process.stdout = _FakeStdout([
            f"URL      : https://0.0.0.0:{port}/?token={port}\n",
            "",
        ])
        process.wait.return_value = 0
        process.returncode = 0
        return process

    monkeypatch.setattr(bw_proxy_shim, "_pick_host_port", fake_pick_host_port)
    monkeypatch.setattr(bw_proxy_shim, "build_docker_command", lambda args, port: ["docker", str(port)] + args)
    monkeypatch.setattr(bw_proxy_shim.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(bw_proxy_shim.webbrowser, "open", lambda url: opened.append(url))

    results = []

    def run_once():
        results.append(bw_proxy_shim.run_command(["mcp", "serve"]))

    threads = [threading.Thread(target=run_once) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results == [0, 0]
    assert sorted(opened) == [
        "https://127.0.0.1:43123/?token=43123",
        "https://127.0.0.1:43124/?token=43124",
    ]
