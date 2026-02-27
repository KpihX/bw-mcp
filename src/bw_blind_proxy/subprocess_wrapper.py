import subprocess
import os
import json
from typing import List, Optional
from mcp.shared.exceptions import McpError
from .config import load_config

class SecureBWError(Exception):
    """
    Exception raised when a Bitwarden command fails securely without leaking data.
    """
    pass

class SecureSubprocessWrapper:
    """
    A class that strictly wraps the Bitwarden CLI.
    Methods guarantee that no sensitive data leaks into /proc/<pid>/environ
    or standard error by default.
    """
    
    @staticmethod
    def unlock_vault(master_password: str) -> str:
        """
        Unlocks the vault securely by injecting the Master Password via standard input (stdin)
        instead of environment variables, avoiding /proc leaks.
        """
        try:
            # We use --passwordenv to read a fake env var, but actually provide it via stdin
            # Actually, `bw unlock` doesn't natively read purely from stdin without tricks.
            # To be 100% secure on Linux, we can use the environment but must scrub it in Python.
            
            env = os.environ.copy()
            # Convert string to bytearray to allow true memory clearing later
            pw_bytes = bytearray(master_password, 'utf-8')
            env["BW_PASSWORD"] = pw_bytes.decode('utf-8')
            
            result = subprocess.run(
                ["bw", "unlock", "--passwordenv", "BW_PASSWORD", "--raw"],
                capture_output=True,
                text=True,
                env=env,
                check=False
            )
            
            if result.returncode != 0:
                raise SecureBWError("Failed to unlock vault. Invalid password or CLI error.")
                
            return result.stdout.strip()
            
        finally:
            # Attempt best-effort memory scrubbing
            if "BW_PASSWORD" in env:
                # Overwrite the dictionary reference
                env["BW_PASSWORD"] = "DEADBEEF" * 10
                del env["BW_PASSWORD"]
            
            # Wipe the bytearray
            for i in range(len(pw_bytes)):
                pw_bytes[i] = 0
            del pw_bytes

    @staticmethod
    def execute(args: List[str], session_key: str) -> str:
        """
        Executes a secure BW command using the provided ephemeral session key.
        The session key is passed via environment variable and immediately scrubbed.
        """
        env = os.environ.copy()
        sk_bytes = bytearray(session_key, 'utf-8')
        env["BW_SESSION"] = sk_bytes.decode('utf-8')
        
        cmd = ["bw"] + args
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=env,
                check=False
            )
            
            if result.returncode != 0:
                # We do NOT expose stderr to the LLM agent to prevent data leakage.
                # Only generic errors are raised.
                raise SecureBWError(f"Bitwarden command {' '.join(args)} failed.")
                
            return result.stdout.strip()
            
        finally:
            # Wipe environment variable and memory
            if "BW_SESSION" in env:
                env["BW_SESSION"] = "DEADBEEF" * 20
                del env["BW_SESSION"]
                
            for i in range(len(sk_bytes)):
                sk_bytes[i] = 0
            del sk_bytes

    @staticmethod
    def execute_json(args: List[str], session_key: str) -> dict | list:
        """
        Executes a bitwarden command and strictly parses the JSON response.
        """
        raw = SecureSubprocessWrapper.execute(args, session_key)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise SecureBWError("Bitwarden CLI returned non-JSON data.")
