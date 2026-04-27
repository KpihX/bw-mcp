import importlib
from pathlib import Path

import bw_proxy.config as config_module


def test_config_path_can_target_mutable_runtime_file(monkeypatch, tmp_path):
    runtime_config = tmp_path / "runtime" / "config.yaml"
    monkeypatch.setenv("BW_PROXY_CONFIG_PATH", str(runtime_config))
    config = importlib.reload(config_module)
    try:
        assert config.CONFIG_PATH == runtime_config
        # Missing runtime file should still expose the bundled default text.
        assert "proxy:" in config.dump_config_text()

        saved = config.write_config_text("proxy:\n  max_batch_size: 23\n")

        assert saved["proxy"]["max_batch_size"] == 23
        assert runtime_config.exists()
        assert config.get_config_value("proxy.max_batch_size") == 23
    finally:
        monkeypatch.delenv("BW_PROXY_CONFIG_PATH", raising=False)
        importlib.reload(config_module)
