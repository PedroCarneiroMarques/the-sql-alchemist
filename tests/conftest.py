from __future__ import annotations

import pytest

from src.core import DATA_PATH, DEFAULT_MODEL_CHAIN, ChatBI


@pytest.fixture(scope="session")
def bi() -> ChatBI:
    return ChatBI(str(DATA_PATH), DEFAULT_MODEL_CHAIN)
