from __future__ import annotations

from pathlib import Path

import pytest

from config import ConfigurationError, get_config, resolve_data_path, validate_config


class TestConfigValidation:
    def test_validate_config_passes_with_defaults(self) -> None:
        cfg = validate_config()
        assert Path(cfg["DATA_PATH"]).exists()

    def test_validate_config_rejects_missing_data_file(self, tmp_path: Path, monkeypatch) -> None:
        missing = tmp_path / "missing.csv"
        monkeypatch.setenv("DATA_PATH", str(missing))
        with pytest.raises(ConfigurationError, match="does not exist"):
            validate_config(get_config())

    def test_validate_config_rejects_invalid_ollama_host(self, monkeypatch) -> None:
        monkeypatch.setenv("OLLAMA_HOST", "not-a-url")
        with pytest.raises(ConfigurationError, match="OLLAMA_HOST"):
            validate_config(get_config())

    def test_validate_config_rejects_empty_model_chain(self, monkeypatch) -> None:
        monkeypatch.setenv("DEFAULT_MODEL_CHAIN", " , ")
        with pytest.raises(ConfigurationError, match="DEFAULT_MODEL_CHAIN"):
            validate_config(get_config())

    def test_resolve_data_path_supports_relative_paths(self) -> None:
        path = resolve_data_path("data/flights.csv")
        assert path.exists()
