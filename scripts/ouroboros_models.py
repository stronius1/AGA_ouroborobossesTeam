"""Allowlisted OpenRouter models for the isolated AGA Ouroboros profile."""

from __future__ import annotations

import os
from typing import Final


MODEL_ENV: Final = "AGA_OUROBOROS_MODEL_ID"
DEFAULT_MODEL_ID: Final = "deepseek/deepseek-v4-pro"
KIMI_MODEL_ID: Final = "moonshotai/kimi-k3"
DEMO_MODEL_ID: Final = DEFAULT_MODEL_ID
SUPPORTED_MODELS: Final = {
    DEFAULT_MODEL_ID: {
        "id": DEFAULT_MODEL_ID,
        "label": "DeepSeek V4 Pro",
        "description": "Основная проверенная модель для AGA tool-calling.",
    },
    KIMI_MODEL_ID: {
        "id": KIMI_MODEL_ID,
        "label": "Kimi K3",
        "description": "Альтернативная сильная agentic-модель OpenRouter.",
    },
}


def selected_model_id(environment: dict[str, str] | None = None) -> str:
    """Return one exact allowlisted route; arbitrary provider routes fail closed."""

    source = os.environ if environment is None else environment
    model_id = str(source.get(MODEL_ENV) or DEFAULT_MODEL_ID).strip()
    if model_id not in SUPPORTED_MODELS:
        raise ValueError("unsupported_ouroboros_model")
    return model_id


def public_models() -> list[dict[str, str]]:
    """Return the stable UI projection without provider credentials."""

    return [dict(item) for item in SUPPORTED_MODELS.values()]
