#!/usr/bin/env python3
import os
import re
import shutil
import socket
import subprocess
import sys
import webbrowser
from pathlib import Path

DEFAULT_IMAGE = "bw-proxy:latest"
DEFAULT_VOLUME = "bw_mcp_bw-data"
DEFAULT_ENV_PATH = Path.home() / ".bw" / "proxy" / "docker.env"
DEFAULT_DATA_DIR = "/data"
DEFAULT_WORKSPACE_DIR = "/workspace"
MCP_LIFECYCLE_UNSUPPORTED = {"status", "stop", "restart"}
URL_PATTERN = re.compile(r"(https?://[^\s]+token=[a-f0-9-]+)")


def _load_env_file(path: Path) -> None:
    if not path.exists() or not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and val and key not in os.environ:
            os.environ[key] = val


def _load_runtime_env() -> None:
    _load_env_file(DEFAULT_ENV_PATH)
    _load_env_file(Path.cwd() / ".env")


def _default_args() -> list[str]:
    return sys.argv[1:] or ["mcp", "serve"]


def _is_unsupported_mcp_command(args: list[str]) -> bool:
    return len(args) >= 2 and args[0] == "mcp" and args[1] in MCP_LIFECYCLE_UNSUPPORTED


def _hash_cwd() -> str:
    import hashlib
    return hashlib.sha256(str(Path.cwd()).encode("utf-8")).hexdigest()[:8]


def _docker_user_args() -> list[str]:
    try:
        return ["--user", f"{os.getuid()}:{os.getgid()}"]
    except AttributeError:
        return []


def _pick_host_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _rewrite_approval_url(url: str) -> str:
    return url.replace("0.0.0.0", "127.0.0.1").replace("localhost", "127.0.0.1")


def _open_browser(url: str) -> bool:
    try:
        if webbrowser.open(url):
            return True
    except Exception:
        pass

    open_commands = []
    if shutil.which("xdg-open"):
        open_commands.append(["xdg-open", url])
    if shutil.which("gio"):
        open_commands.append(["gio", "open", url])
    if shutil.which("open"):
        open_commands.append(["open", url])

    for cmd in open_commands:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode == 0:
                return True
        except Exception:
            continue

    return False


def _build_env_args(port: int) -> list[str]:
    env_args = [
        "-e", f"BW_PROXY_DATA={DEFAULT_DATA_DIR}",
        "-e", f"BITWARDENCLI_APPDATA_DIR={DEFAULT_DATA_DIR}/bw-cli",
        "-e", f"HOME={DEFAULT_DATA_DIR}",
        "-e", "PYTHONUNBUFFERED=1",
        "-e", "HITL_HOST=0.0.0.0",
        "-e", f"HITL_PORT={port}",
        "-e", "HITL_AUTO_OPEN=false",
        "-e", "FORCE_COLOR=1",
        "-e", "TERM=xterm-256color",
    ]
    # Try to pass terminal width if possible
    try:
        columns, _ = shutil.get_terminal_size()
        env_args.extend(["-e", f"COLUMNS={columns}"])
    except Exception:
        pass

    for key in ("BW_URL", "BW_EMAIL", "HITL_USE_HTTPS"):
        value = os.environ.get(key)
        if value:
            env_args.extend(["-e", f"{key}={value}"])
    return env_args


def build_docker_command(args: list[str], port: int, use_tty: bool = False) -> list[str]:
    image = os.environ.get("BW_PROXY_DOCKER_IMAGE", DEFAULT_IMAGE)
    volume = os.environ.get("BW_PROXY_DOCKER_VOLUME", DEFAULT_VOLUME)
    workspace = Path.cwd()
    cmd = ["docker", "run", "--rm", "--init", "-i"]
    if use_tty and sys.stdin.isatty() and sys.stdout.isatty():
        cmd.append("-t")
    cmd.extend(_docker_user_args())
    cmd.extend(["-v", f"{volume}:{DEFAULT_DATA_DIR}"])
    cmd.extend(["-v", f"{workspace}:{DEFAULT_WORKSPACE_DIR}"])
    cmd.extend(["-v", "/tmp:/tmp"])
    cmd.extend(["-w", DEFAULT_WORKSPACE_DIR])
    cmd.extend(["-p", f"127.0.0.1:{port}:{port}"])
    cmd.extend(_build_env_args(port))
    cmd.append(image)
    cmd.extend(args)
    return cmd


def _ensure_docker_ready() -> None:
    if shutil.which("docker") is None:
        raise RuntimeError("Docker CLI not found in PATH.")
    image = os.environ.get("BW_PROXY_DOCKER_IMAGE", DEFAULT_IMAGE)
    inspect = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
        text=True,
        check=False,
    )
    if inspect.returncode != 0:
        raise RuntimeError(
            f"Docker image '{image}' is missing. Run 'make docker-install' first."
        )
    subprocess.run(
        ["docker", "volume", "create", os.environ.get("BW_PROXY_DOCKER_VOLUME", DEFAULT_VOLUME)],
        capture_output=True,
        text=True,
        check=False,
    )


def _emit_unsupported_mcp_message(command: str) -> int:
    print(
        f"❌ 'bw-proxy mcp {command}' is not available in Docker mode.\n"
        "   BW-Proxy now runs one ephemeral container per invocation.\n"
        "   Use 'bw-proxy mcp serve', 'bw-proxy do ...', or 'bw-proxy admin ...' instead."
    )
    return 1


def _get_runtime_name() -> str:
    """Generate a stable, unique name for the runtime container."""
    try:
        import hashlib
        cwd_hash = hashlib.sha256(str(Path.cwd().resolve()).encode()).hexdigest()[:8]
        return f"{DEFAULT_IMAGE.split(':')[0]}-runtime-{os.getuid()}-{cwd_hash}"
    except Exception:
        return f"{DEFAULT_IMAGE.split(':')[0]}-runtime-{os.getuid()}"


def _is_runtime_active(name: str) -> bool:
    """Check if the named runtime container is currently running."""
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", name],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def _ensure_runtime_active(name: str, port: int) -> None:
    """Start the runtime container in the background if not already active."""
    if _is_runtime_active(name):
        return

    # Remove stale container if it exists but is not running
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)

    # Prepare command to start the container in background
    # We use a dummy command (tail -f /dev/null) to keep it alive
    # or we can use 'mcp daemon' once implemented.
    cmd = ["docker", "run", "-d", "--name", name, "--init"]
    cmd.extend(_docker_user_args())
    volume = os.environ.get("BW_PROXY_DOCKER_VOLUME", DEFAULT_VOLUME)
    cmd.extend(["-v", f"{volume}:{DEFAULT_DATA_DIR}"])
    cmd.extend(["-v", f"{Path.cwd()}:{DEFAULT_WORKSPACE_DIR}"])
    cmd.extend(["-v", "/tmp:/tmp"])
    cmd.extend(["-w", DEFAULT_WORKSPACE_DIR])
    cmd.extend(["-p", f"127.0.0.1:{port}:{port}"])
    cmd.extend(_build_env_args(port))
    cmd.append(os.environ.get("BW_PROXY_DOCKER_IMAGE", DEFAULT_IMAGE))
    
    # The entrypoint will be the dummy waiter if no args provided
    # But actually, we want the proxy to run a keep-alive loop.
    cmd.extend(["mcp", "daemon"])

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to start runtime container: {result.stderr}")


def _get_runtime_name() -> str:
    return f"bw-proxy-runtime-{os.getuid()}-{_hash_cwd()}"


def run_command(args: list[str]) -> int:
    """
    Pick a port, build the Docker command, and stream output while detecting
    HITL approval URLs.
    """
    runtime_name = _get_runtime_name()

    # Special case: admin lock should stop the container
    if args[:2] == ["admin", "lock"]:
        subprocess.run(["docker", "stop", runtime_name], capture_output=True, check=False)
        print("✅ Runtime container stopped.")
        return 0

    port = _pick_host_port()
    _ensure_runtime_active(runtime_name, port)

    if _is_runtime_active(runtime_name) and args[0] != "mcp":
        # Route via existing runtime
        cmd = ["docker", "exec", "-i"]
        if sys.stdin.isatty():
            cmd.append("-t")
        cmd.extend([runtime_name, "bw-proxy"])
        cmd.extend(args)
    else:
        cmd = build_docker_command(args, port)

    if sys.stderr.isatty():
        if args[:1] == ["do"]:
            sys.stderr.write("⏳ [Host Agent] Starting BW-Proxy vault operation container. Authentication may be required.\n")
            sys.stderr.flush()
        elif args[:2] == ["admin", "login"]:
            sys.stderr.write("⏳ [Host Agent] Starting BW-Proxy authentication container.\n")
            sys.stderr.flush()

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=sys.stdin,
        text=True,
        bufsize=1,
    )

    last_approval_url = None
    assert process.stdout is not None
    try:
        while True:
            line = process.stdout.readline()
            if not line:
                break

            # Intercept HITL approval URL and open browser
            match = URL_PATTERN.search(line)
            if match:
                url = _rewrite_approval_url(match.group(1))
                if url != last_approval_url:
                    last_approval_url = url
                    sys.stdout.write(f"\r\n🚀 [Host Agent] Detected Approval URL: {url}\r\n")
                    sys.stdout.flush()
                    if not _open_browser(url):
                        sys.stdout.write("⚠️ [Host Agent] Failed to auto-open browser. Open the URL manually.\r\n")
                        sys.stdout.flush()

            # Normalise line endings for terminal compatibility
            normalised = line.rstrip("\n").rstrip("\r") + "\r\n"
            sys.stdout.write(normalised)
            sys.stdout.flush()

    except KeyboardInterrupt:
        if should_use_runtime:
            # For exec, we just interrupt the local process, container stays alive
            process.terminate()
        else:
            process.terminate()
        sys.stdout.write("\r\nInterrupted.\r\n")
        sys.stdout.flush()

    process.wait()
    return process.returncode



def main():
    try:
        _load_runtime_env()
        args = _default_args()
        if _is_unsupported_mcp_command(args):
            sys.exit(_emit_unsupported_mcp_message(args[1]))
        _ensure_docker_ready()
        sys.exit(run_command(args))
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)

if __name__ == '__main__':
    main()
