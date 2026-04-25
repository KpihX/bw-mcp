"""
daemon.py — PID File Manager for BW-MCP server lifecycle control.

Provides the primitives to write, read, clear, and check the PID of the
running bw-proxy server process. The PID file is stored in the configured
state directory (~/.bw/proxy/bw-proxy.pid by default).

This mirrors the daemon management pattern used by nginx, redis, etc.
"""
import os
import signal
from pathlib import Path


def _pid_file_path() -> Path:
    """Resolve the PID file path from the proxy configuration."""
    from .config import STATE_DIR
    state_dir = Path(STATE_DIR)
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "bw-proxy.pid"


def write_pid(pid: int) -> None:
    """Write the current process PID to the PID file."""
    _pid_file_path().write_text(str(pid))


def read_pid() -> int | None:
    """Read the PID from the PID file. Returns None if file doesn't exist or is invalid."""
    p = _pid_file_path()
    if not p.exists():
        return None
    try:
        return int(p.read_text().strip())
    except (ValueError, OSError):
        return None


def clear_pid() -> None:
    """Remove the PID file (called on clean shutdown or stale detection)."""
    p = _pid_file_path()
    try:
        p.unlink(missing_ok=True)
    except OSError:
        pass


def is_running(pid: int) -> bool:
    """
    Check if a process with the given PID is alive.

    Uses POSIX signal 0 — no signal is sent, but the OS checks if the process
    exists and we have permission to signal it.
      - ProcessLookupError (errno ESRCH) → process is dead.
      - PermissionError (errno EPERM)   → process exists but belongs to root (treat as alive).
    """
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists even if we can't signal it directly
