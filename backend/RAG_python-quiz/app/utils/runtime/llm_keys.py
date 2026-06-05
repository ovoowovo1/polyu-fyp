from __future__ import annotations

from typing import List, Optional


def split_api_keys(raw_value: str) -> List[str]:
    return [key.strip() for key in (raw_value or "").split(",") if key.strip()]


def first_csv_key(raw_value: str) -> str:
    keys = split_api_keys(raw_value)
    return keys[0] if keys else ""


def get_llm_runtime_keys(settings) -> List[str]:
    if settings.llm_api_key.strip():
        return [settings.llm_api_key.strip()]
    return split_api_keys(settings.llm_api_keys)


def first_configured_llm_key(settings) -> str:
    if settings.llm_api_key.strip():
        return settings.llm_api_key.strip()
    return first_csv_key(settings.llm_api_keys)


def ensure_llm_init(keys: List[str], index: int, settings) -> tuple[List[str], int]:
    if keys:
        return keys, index
    return get_llm_runtime_keys(settings), 0


def current_llm_api_key(keys: List[str], index: int) -> Optional[str]:
    if not keys or index >= len(keys):
        return None
    return keys[index]
