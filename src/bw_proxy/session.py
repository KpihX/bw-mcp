import os
from pathlib import Path
from typing import Optional
from .config import STATE_DIR

SESSION_FILE = Path(STATE_DIR) / "session.key"

class SessionManager:
    """
    Session persistence is DISABLED for security.
    Secrets must be handled in RAM only and wiped after use.
    """

    @staticmethod
    def save_session(session_key: bytearray):
        """No-op: Session persistence is forbidden."""
        pass

    @staticmethod
    def load_session() -> Optional[bytearray]:
        """Returns None: Session persistence is forbidden."""
        return None

    @staticmethod
    def clear_session():
        """No-op."""
        pass
