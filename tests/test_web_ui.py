from unittest.mock import patch

from bw_proxy.web_ui import (
    ThreadingHTTPServer,
    _build_subject_alt_names,
    _build_openssl_config,
    _generate_self_signed_cert,
)


def test_threading_http_server_reuses_address():
    assert ThreadingHTTPServer.allow_reuse_address is True


def test_subject_alt_names_cover_loopback_and_custom_host():
    entries = _build_subject_alt_names("vault.local")
    assert "DNS:localhost" in entries
    assert "IP:127.0.0.1" in entries
    assert "DNS:vault.local" in entries


def test_openssl_config_contains_subject_alt_name_extension():
    config = _build_openssl_config("127.0.0.1")
    assert "subjectAltName" in config
    assert "IP:127.0.0.1" in config
    assert "DNS:localhost" in config


@patch("bw_proxy.web_ui.subprocess.run")
def test_generate_self_signed_cert_returns_bundle_with_san_ready_config(mock_run):
    def fake_run(cmd, check, capture_output):
        key_path = cmd[cmd.index("-keyout") + 1]
        cert_path = cmd[cmd.index("-out") + 1]
        with open(key_path, "wb") as key_file:
            key_file.write(b"KEY")
        with open(cert_path, "wb") as cert_file:
            cert_file.write(b"CERT")
        return None

    mock_run.side_effect = fake_run

    bundle = _generate_self_signed_cert("localhost")

    assert bundle is not None
    bundle_path, cleanup_paths, temp_dir = bundle
    assert bundle_path.endswith("bundle.pem")
    assert any(path.endswith("openssl.cnf") for path in cleanup_paths)
    assert temp_dir
    with open(bundle_path, "rb") as bundle_file:
        assert bundle_file.read() == b"KEYCERT"
