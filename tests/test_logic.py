from unittest.mock import patch, MagicMock
from types import SimpleNamespace

from bw_proxy import logic


@patch("bw_proxy.logic.SecureSubprocessWrapper.set_server")
@patch("bw_proxy.logic.SecureSubprocessWrapper.get_server", return_value="https://elsewhere.example.com")
@patch("bw_proxy.logic.SecureSubprocessWrapper.lock_vault")
@patch("bw_proxy.logic.SecureSubprocessWrapper.login_vault")
@patch("bw_proxy.logic.HITLManager.ask_master_password", return_value=bytearray(b"pw"))
def test_login_aligns_server_before_login(mock_password, mock_login, mock_lock, mock_get_server, mock_set_server, monkeypatch):
    mock_login.return_value = bytearray(b"session")
    monkeypatch.setattr(logic, "_load_bw_status", lambda: {"status": "unauthenticated"})

    result = logic.login("agent@example.com", "https://vault.example.com")

    assert result["status"] == "success"
    assert result["mode"] == "login"
    assert result["auth_status"] == "locked"
    mock_set_server.assert_called_once_with("https://vault.example.com")
    mock_login.assert_called_once()
    mock_lock.assert_called_once()


@patch("bw_proxy.logic.SecureSubprocessWrapper.set_server")
@patch("bw_proxy.logic.SecureSubprocessWrapper.get_server", return_value="https://vault.example.com")
@patch("bw_proxy.logic.SecureSubprocessWrapper.lock_vault")
@patch("bw_proxy.logic.HITLManager.ask_master_password")
def test_login_noops_when_already_authenticated(mock_password, mock_lock, mock_get_server, mock_set_server, monkeypatch):
    monkeypatch.setattr(
        logic,
        "_load_bw_status",
        lambda: {
            "status": "locked",
            "serverUrl": "https://vault.example.com",
            "userEmail": "agent@example.com",
        },
    )

    result = logic.login("agent@example.com", "https://vault.example.com")

    assert result["status"] == "success"
    assert result["mode"] == "noop"
    mock_password.assert_not_called()
    mock_lock.assert_not_called()


@patch("bw_proxy.logic.HITLManager.ask_master_password", return_value=bytearray(b"pw"))
def test_open_authenticated_vault_requires_existing_login(mock_password, monkeypatch):
    monkeypatch.setenv("BW_EMAIL", "agent@example.com")
    monkeypatch.setenv("BW_URL", "https://vault.example.com")
    monkeypatch.setattr(logic, "_load_bw_status", lambda: {"status": "unauthenticated"})

    with patch("bw_proxy.logic.SecureSubprocessWrapper.unlock_vault") as mock_unlock:
        try:
            logic._open_authenticated_vault("Auth")
        except logic.SecureProxyError as exc:
            assert "admin login" in str(exc)
        else:
            raise AssertionError("Expected SecureProxyError when Bitwarden is logged out.")
    mock_unlock.assert_not_called()


@patch("bw_proxy.logic.SecureSubprocessWrapper.unlock_vault", return_value=bytearray(b"session"))
@patch("bw_proxy.logic.HITLManager.ask_master_password", return_value=bytearray(b"pw"))
def test_open_authenticated_vault_unlocks_only_authenticated_session(mock_password, mock_unlock, monkeypatch):
    monkeypatch.setenv("BW_EMAIL", "agent@example.com")
    monkeypatch.setenv("BW_URL", "https://vault.example.com")
    monkeypatch.setattr(
        logic,
        "_load_bw_status",
        lambda: {
            "status": "locked",
            "serverUrl": "https://vault.example.com",
            "userEmail": "agent@example.com",
        },
    )

    master_password, session_key = logic._open_authenticated_vault("Auth")

    assert master_password == bytearray(b"pw")
    assert session_key == bytearray(b"session")
    mock_unlock.assert_called_once_with(bytearray(b"pw"))


def test_logout_is_idempotent_when_already_unauthenticated():
    with patch("bw_proxy.logic._load_bw_status", return_value={"status": "unauthenticated"}):
        result = logic.logout()

    assert result["status"] == "success"
    assert result["mode"] == "noop"


def test_vault_operation_relocks_after_success():
    wrapped = logic.vault_operation("Auth")(lambda **kwargs: {"status": "success", "message": "ok"})

    with patch("bw_proxy.vault_runtime.build_execution_context") as mock_build, \
         patch("bw_proxy.vault_runtime.finalize_execution_context") as mock_finalize:
        
        mock_ctx = MagicMock()
        mock_ctx.session_key = bytearray(b"session")
        mock_ctx.master_password = bytearray(b"pw")
        mock_ctx.unlock_deferred = False
        mock_build.return_value = mock_ctx
        mock_finalize.return_value = None
        
        result = wrapped()
    
    assert result["status"] == "success"
    mock_finalize.assert_called_once_with(mock_ctx)


@patch("bw_proxy.logic._relock_vault")
@patch("bw_proxy.logic.UnlockLeaseManager.status", side_effect=[{"state": "none"}, {"state": "active"}])
@patch("bw_proxy.logic.UnlockLeaseManager.create", return_value=SimpleNamespace(expires_at="2026-04-27T20:00:00Z"))
@patch("bw_proxy.logic.SecureSubprocessWrapper.unlock_vault", return_value=bytearray(b"session"))
@patch("bw_proxy.logic.HITLManager.ask_master_password", return_value=bytearray(b"pw"))
@patch("bw_proxy.logic._validate_authenticated_context")
@patch("bw_proxy.logic.is_docker_runtime", return_value=True)
def test_admin_unlock_creates_docker_unlock_lease(
    mock_runtime,
    mock_validate,
    mock_password,
    mock_unlock,
    mock_create,
    mock_status,
    mock_relock,
    monkeypatch,
):
    monkeypatch.setattr(
        logic,
        "_load_bw_status",
        lambda: {
            "status": "locked",
            "serverUrl": "https://vault.example.com",
            "userEmail": "agent@example.com",
        },
    )

    result = logic.admin_unlock()

    assert result["status"] == "success"
    assert result["duration_seconds"] == 300
    mock_unlock.assert_called_once()
    mock_create.assert_called_once()
    mock_relock.assert_called_once()


@patch("bw_proxy.logic.is_docker_runtime", return_value=False)
def test_admin_lock_rejects_outside_docker(mock_runtime):
    result = logic.admin_lock()

    assert result["status"] == "error"
    assert "Docker mode" in result["message"]
