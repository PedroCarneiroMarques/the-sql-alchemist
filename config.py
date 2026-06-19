from __future__ import annotations

import os
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_PATH = BASE_DIR / "data" / "flights.csv"
DEFAULT_MODEL_CHAIN_RAW = (
    "mistral:7b,phi4:14b,qwen2.5-coder:14b,gemma4:26b,"
    "qwen3.6:27b,qwen3.6:35b-a3b,deepseek-r1:8b"
)


def _parse_model_chain(raw: str) -> list[str]:
    return [model.strip() for model in raw.split(",") if model.strip()]


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