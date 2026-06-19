from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_PATH = BASE_DIR / "data" / "flights.csv"
DEFAULT_MODEL_CHAIN_RAW = (
    "mistral:7b,phi4:14b,qwen2.5-coder:14b,gemma4:26b,"
    "qwen3.6:27b,qwen3.6:35b-a3b,deepseek-r1:8b"
)


class ConfigurationError(ValueError):
    """Raised when required deployment settings are missing or invalid."""


def _parse_model_chain(raw: str) -> list[str]:
    return [model.strip() for model in raw.split(",") if model.strip()]


def resolve_data_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path.resolve()


def get_config() -> dict[str, Any]:
    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    ollama_timeout = int(os.getenv("OLLAMA_TIMEOUT", "180"))
    data_path = os.getenv("DATA_PATH", str(DEFAULT_DATA_PATH))
    delay_cost_per_minute = int(os.getenv("DEFAULT_DELAY_COST_PER_MINUTE", "50"))
    cancellation_cost = int(os.getenv("DEFAULT_CANCELLATION_COST", "200"))
    default_model_chain = _parse_model_chain(
        os.getenv("DEFAULT_MODEL_CHAIN", DEFAULT_MODEL_CHAIN_RAW)
    )

    model_profiles = {
        "fast": _parse_model_chain(os.getenv("MODEL_PROFILE_FAST", "mistral:7b")),
        "balanced": default_model_chain,
        "accurate": _parse_model_chain(
            os.getenv(
                "MODEL_PROFILE_ACCURATE",
                "deepseek-r1:8b,qwen3.6:35b-a3b,qwen3.6:27b,qwen2.5-coder:14b,phi4:14b",
            )
        ),
    }
    default_model_profile = os.getenv("DEFAULT_MODEL_PROFILE", "balanced").lower().strip()
    if default_model_profile not in model_profiles:
        default_model_profile = "balanced"

    default_watchdog_sensitivity = os.getenv("DEFAULT_WATCHDOG_SENSITIVITY", "normal").lower().strip()
    if default_watchdog_sensitivity not in {"relaxed", "normal", "strict"}:
        default_watchdog_sensitivity = "normal"

    log_level = os.getenv("LOG_LEVEL", "INFO").upper().strip()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        log_level = "INFO"

    log_to_file = os.getenv("LOG_TO_FILE", "true").lower().strip() in {"1", "true", "yes", "on"}

    ui_locale = os.getenv("UI_LOCALE", "en").lower().strip()
    if not ui_locale.startswith("pt"):
        ui_locale = "en"

    return {
        "OLLAMA_HOST": ollama_host,
        "OLLAMA_TIMEOUT": ollama_timeout,
        "DATA_PATH": str(data_path),
        "DEFAULT_DELAY_COST_PER_MINUTE": delay_cost_per_minute,
        "DEFAULT_CANCELLATION_COST": cancellation_cost,
        "DEFAULT_MODEL_CHAIN": default_model_chain,
        "MODEL_PROFILES": model_profiles,
        "DEFAULT_MODEL_PROFILE": default_model_profile,
        "DEFAULT_WATCHDOG_SENSITIVITY": default_watchdog_sensitivity,
        "LOG_LEVEL": log_level,
        "LOG_TO_FILE": log_to_file,
        "UI_LOCALE": ui_locale,
    }


def validate_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = dict(config or get_config())
    errors: list[str] = []

    data_path = resolve_data_path(cfg["DATA_PATH"])
    cfg["DATA_PATH"] = str(data_path)

    if not data_path.exists():
        errors.append(f"DATA_PATH does not exist: {data_path}")
    elif not data_path.is_file():
        errors.append(f"DATA_PATH is not a file: {data_path}")

    parsed_host = urlparse(cfg["OLLAMA_HOST"])
    if parsed_host.scheme not in {"http", "https"} or not parsed_host.netloc:
        errors.append(f"OLLAMA_HOST must be a valid HTTP URL: {cfg['OLLAMA_HOST']}")

    if cfg["OLLAMA_TIMEOUT"] <= 0:
        errors.append("OLLAMA_TIMEOUT must be greater than 0")

    if cfg["DEFAULT_DELAY_COST_PER_MINUTE"] < 0:
        errors.append("DEFAULT_DELAY_COST_PER_MINUTE must be zero or positive")

    if cfg["DEFAULT_CANCELLATION_COST"] < 0:
        errors.append("DEFAULT_CANCELLATION_COST must be zero or positive")

    if not cfg["DEFAULT_MODEL_CHAIN"]:
        errors.append("DEFAULT_MODEL_CHAIN must include at least one model")

    for profile_name, chain in cfg["MODEL_PROFILES"].items():
        if not chain:
            errors.append(f"MODEL_PROFILES['{profile_name}'] must include at least one model")

    if cfg["UI_LOCALE"] not in {"en", "pt"}:
        errors.append("UI_LOCALE must be 'en' or 'pt'")

    if errors:
        raise ConfigurationError("; ".join(errors))

    return cfg