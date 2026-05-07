from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    import streamlit as st
except Exception:
    st = None

# Este ficheiro deve viver na raiz do projeto:
# chab_ai_engine/config.py
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DEFAULT_DATA_PATH = DATA_DIR / "flights.csv"


def _read_secret(key: str, default: Any = None) -> Any:
    if st is None:
        return default
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return default


def get_config() -> dict[str, Any]:
    ollama_host = os.getenv("OLLAMA_HOST") or _read_secret("OLLAMA_HOST", "http://localhost:11434")
    ollama_timeout = int(os.getenv("OLLAMA_TIMEOUT") or _read_secret("OLLAMA_TIMEOUT", 180))
    data_path = os.getenv("DATA_PATH") or _read_secret("DATA_PATH", str(DEFAULT_DATA_PATH))
    delay_cost_per_minute = int(
        os.getenv("DEFAULT_DELAY_COST_PER_MINUTE") or _read_secret("DEFAULT_DELAY_COST_PER_MINUTE", 50)
    )
    cancellation_cost = int(
        os.getenv("DEFAULT_CANCELLATION_COST") or _read_secret("DEFAULT_CANCELLATION_COST", 200)
    )
    default_model_chain_raw = os.getenv("DEFAULT_MODEL_CHAIN") or _read_secret(
        "DEFAULT_MODEL_CHAIN",
        "mistral:7b,phi4:14b,qwen2.5-coder:14b,gemma4:26b,qwen3.6:27b,qwen3.6:35b-a3b,deepseek-r1:8b",
    )

    if isinstance(default_model_chain_raw, str):
        default_model_chain = [m.strip() for m in default_model_chain_raw.split(",") if m.strip()]
    else:
        default_model_chain = list(default_model_chain_raw)

    return {
        "OLLAMA_HOST": ollama_host,
        "OLLAMA_TIMEOUT": ollama_timeout,
        "DATA_PATH": str(data_path),
        "DEFAULT_DELAY_COST_PER_MINUTE": delay_cost_per_minute,
        "DEFAULT_CANCELLATION_COST": cancellation_cost,
        "DEFAULT_MODEL_CHAIN": default_model_chain,
    }